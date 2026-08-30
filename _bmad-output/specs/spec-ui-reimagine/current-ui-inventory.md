# Current UI Inventory

Companion to `SPEC.md`. What the web app renders today and what the server already offers that the UI ignores — surveyed 2026-08-21 against `main`. This is the gap map the reimagining closes; build against it, not from memory.

## Routes today

Router is a Vite-glob registry (`web/src/routes/registry.ts`); three child routes under the `Shell` layout in `web/src/App.tsx`.

| Path | Renders | Shows |
|---|---|---|
| `/` (layout + home, never unmounted) | `CorpusSearch`, `ChatPanel`, `MeetingsList`, Participants button, `HealthPanel` | search hits, one-shot chat answer + citations, bare meeting rows, health |
| `/meetings/:meetingId` | `MeetingMoments` via `GET /meetings/{id}/drilldown` | header, screenshot series (viewType, label, offset, inline replay), transcript segments with client-side highlight |
| `/moments/:momentId` | `MomentView` via `GET /moments/{id}` | screenshot, replay/deep-link affordance, covered segments, artifact right rail with approve-and-publish, read-only extraction prompts |
| `/participants` | `Participants` via `GET /participants` | rename, merge, duplicate-name hints |

Shell chrome is an `h1` and a back button — no nav bar, no dashboard, no 404.

## The meeting list (the "list of videos")

`web/src/features/meetings/MeetingsList.tsx`: per row — title (or `sourceId`), `startedAt · corpus · status`, transcript-only pill, `StageProgress` strip live-patched by SSE (`GET /jobs/events`), one `Open` button. The only interaction is Open. No poster image, no duration, no moment/screen/artifact/participant counts, no sorting, filtering, grouping, pagination, or per-meeting search scope.

## Server surface the UI never calls

Full operation set (client `web/src/client/sdk.gen.ts` matches `server/meetingminer/api/*.py` 1:1):

- `listMeetingMoments` (`GET /meetings/{id}/moments`) — unused; `MomentListItem` carries `segmentCount`, `preview`, `screenshotId`, `sourceDeepLink`.
- `createIngest`, `getJob` — no ingest or job-detail UI.
- `getRecording`, `getMediaFile` — reached only via `ReplayPlayer` URL building; no full-recording player.
- `askCorpus` generated op bypassed by the deliberate hand-rolled `features/chat/chatStream.ts`.

## Under-surfaced fields

- Search: `GET /search` accepts `limit`, `offset`, `meetingId`, `corpus`; `CorpusSearch.tsx` sends only `q`. `SearchHit` carries `meetingTitle`, `startedAt`, `hasRecording`, `corpus`, `score`, `screenshotId`, `sourceDeepLink`; the card shows label + offset + snippet.
- `MomentSegment.speakerResolution` and `participantId` are never rendered; Participants has no link to where a person spoke.
- `screen.label` is documented as human-edited (`server/meetingminer/api/moments.py:360`) but no endpoint or UI edits it; `viewType` is shown, never filterable.
- Artifacts (7 kinds) exist only inside one moment's right rail — no per-meeting or cross-corpus artifact roll-up, no artifact detail, `body` barely rendered.
- Graph traversals (`screen_history`, `participant_topic_moments` in `server/meetingminer/projections/traversals.py`) reach the UI only as chat's one-line route summary.

## Configuration surface

`config.yaml` (480 lines) carries the whole adapter stack: `llm.roles.{extraction,chat,judge}` (model, fallback, endpoint, context, timeouts, both extraction prompt texts), `embedder`, `stt`, `ocr`, `diarizer`, `providers`, `pipeline.{frames,screens,align,moments}` capture thresholds, `api.search`/`api.chat` query knobs, `projections` index settings, `stores` coordinates. Loaded once at process start (`server/meetingminer/config.py:924`), strict `extra="forbid"`, fail-fast; no hot reload — every edit is a restart, `projections.*` edits also need `make rebuild`. Secrets and the three roots (`MM_CONTENT_ROOT`, `MM_DROPS_ROOT`, `MM_PUBLISH_ROOT`) live in `.env` only.

API exposure today: `GET /extraction/prompts` (verbatim prompt texts, rendered read-only in `MomentView.tsx:386-405`) and `config_version` in `GET /health`. Nothing else; no mutation endpoint exists.
