---
title: 'Story 2.2: Moment View'
type: 'feature'
created: '2026-08-20'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/specs/spec-meetingminer/ux-spine.md'
warnings: [oversized]
deferred:
  - summary: >-
      The committed generated client does not byte-match what `make client` produces, and
      `check-client` cannot detect generated-content drift.
    evidence: |-
      Port 8000 was serving another checkout's pre-2.2 api during both the build and the review, so
      the client was regenerated from this branch's `app.openapi()` dump with an injected
      `servers: http://localhost:8000` entry to keep `client.gen.ts` byte-identical. Side effect:
      `types.gen.ts` `ClientOptions.baseUrl` became the literal `'http://localhost:8000'` where
      `make client` (whose live /openapi.json carries no servers entry) emits the template-literal
      form — so the next honest `make client` run will revert that one line as an unexplained diff.
      Type-only, no runtime effect. The underlying tooling gap is pre-existing: `check-client`
      asserts only that the three .gen.ts files exist, never that they match the schema, so any
      semantic drift would also ship silently. Fix is a regenerate-and-diff check, or simply
      rerunning `make client` on this branch once :8000 is free and committing the result.
    location: >-
      web/src/client/types.gen.ts
    severity: low
  - summary: >-
      The abort-controller + expiry-timer + error-classification load idiom now exists in four
      copies; a shared hook is the missing extraction.
    evidence: |-
      CorpusSearch and MeetingsList already carried the pattern (story 1.10 finding 22 lineage);
      MeetingMoments and MomentView added two more verbatim copies, each with the same timeout
      sentence and expiry plumbing. Story 2.3's drill-down will need a fifth. All copies are
      individually tested (including the hang path since this review), so this is maintenance debt,
      not a defect — but a refactor of the plumbing now has four places to miss.
    location: >-
      web/src/features/moments/MeetingMoments.tsx
    severity: low
baseline_revision: 'f653a3d566899b26c1f5983e4514827924f19d19'
---

<intent-contract>

## Intent

**Problem:** Every moment is fully precomputed and searchable (stories 1.x, 3.1), but nothing can display one: there is no API read for a moment or a meeting's moments, no moment page, the meetings list's Open button does nothing, and search hits dead-end at an inline replay. CAP-4's promise — verify a claim in seconds — has no surface, and the server-side `viewable` gate deferred from story 1.9 has no route to live on.

**Approach:** Add read-only `GET /meetings/{meetingId}/moments` and `GET /moments/{momentId}` (camelCase, generated-client-served, evidence-gated), and a web moment view: still screenshot on top, covering transcript below, right rail of extracted artifacts with an explicit empty state, replay button opening the story-2.1 player at `startMs`, and degraded transcript-only mode showing the transitional source deep link instead.

## Boundaries & Constraints

**Always:**
- The API stays read-only over evidence (AD-5/AD-11): SELECTs only, sync psycopg via `app.state.pool`, plain `def` routes, raw SQL constants — the house style of `meetings.py`/`search.py`.
- Both new endpoints are server-gated on evidence completeness: an existing meeting whose evidence stages are not all `done`/`skipped` answers an RFC 9457 problem, not data. A meeting that was never ingested has no row and answers 404 — the status code is the required augmentation-versus-never-ingested distinction.
- Covering transcript = the `moment_segment` join, never a `BETWEEN start_ms AND end_ms` filter — a covered segment may legitimately end after its moment does (`pipeline/moments.py:208-215`).
- Moment ordering is `start_ms` (tiebreak `id`); no ordinal is invented — augmentation would invalidate it.
- Superseded moments (`provenance->>'superseded' = 'true'`) are excluded from the meeting's moment list but still served by `GET /moments/{id}` flagged `superseded: true` — their ids are citations and must keep resolving.
- Payload fields reuse the `SearchHit` vocabulary and types (`momentId`, `meetingId`, `startMs`, `startedAt` as `datetime`, `screenshotId`, `sourceDeepLink`, `hasRecording`) so the generated TS client keeps one spelling per column (`search.py:113-118`).
- `sourceDeepLink` is `moment.source_deep_link` verbatim: no time parameter appended, no re-derivation from `meeting.provenance` (`domain/drops.py:284-287`).
- Screenshot delivery reuses `GET /media/{path}`: the detail payload carries the stored content-root-relative `screenshot.path`; no root, no absolute path, no server-built URL leaves the server.
- Web: no player mounts for a transcript-only moment — `ReplayPlayer` has no failure surface, so the caller gates, reusing the `safeHref`/affordance decision search already litigated.
- All web UI follows house style: Tailwind-only, hand-rolled fetch with abort-race guards, `null` = never answered vs `[]` = answered-empty, `aria-live` regions, helper module + colocated vitest.

**Block If:**
- The right rail cannot ship without an artifact schema decision that contradicts `projections/publish_gate.py`'s forward contract (states `extracted|approved|published`).
- Wiring navigation turns out to require editing files an in-flight story owns.

**Never:**
- No artifact tables, migrations, or extraction — Epic 4 owns them; the rail reads an empty collection today.
- No meeting drill-down/screenshot series page and no full router (story 2.3 owns the drill-down; a URL router is not required by any AC here).
- No writes from the API, no store clients in `api/` (`test_projections_single_writer.py` AST-walks it).
- No edits to `pipeline/`, migrations, or worker-owned tables.
- No hand-edited `web/src/client/*.gen.ts` — regeneration only.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Moments list | `GET /meetings/{id}/moments`, viewable meeting | 200: meeting header (`meetingId`, `title`, `hasRecording`, `corpus`, `startedAt(+Precision)`) + `moments[]` ordered by `start_ms, id`, superseded rows absent | No error expected |
| Moment detail | `GET /moments/{id}`, viewable recording-backed meeting | 200: moment core fields + `screenshotId`/`screenshotPath` + `segments[]` via `moment_segment` ordered by segment `ordinal` + `artifacts: []` | No error expected |
| Transcript-only detail | Moment of a meeting with `has_recording = false`, no screenshots | 200: `screenshotId`/`screenshotPath` null, `sourceDeepLink` carries the recap URL, `hasRecording: false` | No error expected |
| Unknown meeting | Unknown UUID on the list route | 404 problem | `not-found` |
| Unknown moment | Unknown UUID on the detail route | 404 problem | `not-found` |
| Not yet viewable | Meeting exists, an evidence stage not `done`/`skipped` (first ingest or augmentation in flight) | 409 problem naming that evidence is still being prepared; applies to both routes | `meeting-not-viewable` |
| Superseded moment | Detail on a `superseded` moment | 200 with `superseded: true`, `segments: []` | No error expected |
| Overhanging segment | Covering segment with `end_ms` past the moment's `end_ms` | Segment still returned in full | No error expected |
| Empty moments | Viewable meeting, zero live moments | 200 with `moments: []` | No error expected |
| Malformed id | Non-UUID path parameter | 422 problem (existing app-wide validation handler) | `invalid-request` |

</intent-contract>

## Code Map

Read on `story/2-2` at baseline `f653a3d`.

- `server/meetingminer/migrations/0006_moments.sql:11-78` — `moment` (id UUIDv7 = citation currency, `start_ms`/`end_ms`, `started_at(+_precision)`, `screenshot_id` nullable, `source_deep_link`, `segment_count`, `provenance` jsonb; **no ordinal**, deliberately) and `moment_segment` (`UNIQUE(transcript_segment_id)` — coverage is an unambiguous join). Read-only.
- `server/meetingminer/pipeline/stages/moments.py:214-232` — superseded marking: kept row, `provenance || '{"superseded": true}'`, `segment_count = 0`. The comment names Epic 2 as the reader that must not project ghosts. Read-only.
- `server/meetingminer/projections/evidence.py:149-156` — `meeting_evidence_complete(conn, meeting_id)`: the SQL-side gate predicate to reuse (store-free module; `api/` may import it). `:159-243` `read_meeting()` is the read-side precedent: moment_segment joined **through** `transcript_segment` (which carries `meeting_id`), moments `ORDER BY start_ms, id`, segments `ORDER BY ordinal`. Read-only.
- `server/meetingminer/projections/publish_gate.py:14-33` — the rail's forward contract: no artifact table yet; `ARTIFACT_STATES = ("extracted","approved","published")`; the rail is the only place unpublished artifacts will ever surface. Read-only.
- `server/meetingminer/api/meetings.py` — house style: camelCase via `ConfigDict(alias_generator=to_camel, populate_by_name=True)`, one SQL constant per read with the "one statement, one snapshot" note, positional row access, `viewable` computed at `:91`. Read-only.
- `server/meetingminer/api/search.py:79-132` — `_RESOLVE_MOMENTS` and `SearchHit`: the field vocabulary the new models must match; `:113-118` pins `startedAt` as `datetime`. Read-only.
- `server/meetingminer/api/problems.py` — `Problem(status, slug, detail, title=None, **extensions)`; declare `responses={...: {"model": ProblemDetails, "content": {"application/problem+json": {}}}}` like `jobs.py:71-73`. `_STATUS_TITLES` already maps 409 to "Conflict" at baseline (`problems.py:46`), so no `title` argument is needed.
- `server/meetingminer/api/main.py:127-139` — router registration order and its documented hazards; new router registers between `meetings` and `media`.
- `server/tests/projection_seed.py:75` — `seed_meeting(...)`: seeds job+stages (settled), meeting (`provenance={"url": DEEP_LINK}`), participants, screens+screenshots, transcript_source, 5 segments, 2 moments with links; `has_recording=False` gives the transcript-only shape (video stages `skipped`); `stage_overrides` makes a meeting non-viewable. `SeededMeeting` carries every id.
- `server/tests/test_api_meetings.py` — template: `ITEM_FIELDS` set literal asserted with `set(item) == ITEM_FIELDS`; sentence test names; `test_viewable_is_false_until_moments_settles:104` must not be contradicted.
- `server/tests/conftest.py:243-285` — `client` (TestClient, lifespan not run, truncates evidence), `test_pool`; store-free for this story's tests (Postgres only, per-`RUN_ID` database).
- `web/src/App.tsx:87-102` — flat `<main>`, no router; `App.test.tsx:16-27` mocks **every** SDK export, so regeneration surfaces here as a missing mock (same in `CorpusSearch.test.tsx:19-28`, shorter list in `MeetingsList.test.tsx:14-20`).
- `web/src/features/meetings/MeetingsList.tsx:19-25,216-228` — `onOpen?: (row) => void` already exists and is unwired; `row.meetingId` is nullable — guard. `rows.ts:113` `blockedReason` supplies the "why not yet" copy.
- `web/src/features/search/hits.ts:27-68` — `affordanceOf` (`replay | deepLink | inertLink | none`) and `safeHref` (http/https only): the degraded-mode decision to reuse, not re-derive. `CorpusSearch.tsx:363-373` shows the `ReplayPlayer` mount idiom.
- `web/src/features/replay/ReplayPlayer.tsx:4-12` — props `meetingId`, `startMs`, `label?`, `className?`; no error path — never mount it without a recording.
- `web/src/lib/media.ts:31,51` — `mediaUrl(path)` (first real consumer is this story's `<img>`) and `recordingUrl(meetingId)`.
- `web/src/lib/api.ts:10-12` — `API_BASE`; error copy names it (house convention, `hits.ts:96-114` `problemMessage`).
- `web/openapi-ts.config.ts` + `infra/Makefile:698-701` — `make client` regenerates from a **running** api (health-checked); generated client is committed and gate-checked by `check-client`.

## Tasks & Acceptance

**Execution:**

1. `server/meetingminer/api/moments.py` — new router: `GET /meetings/{meeting_id}/moments` (`operation_id="listMeetingMoments"`) and `GET /moments/{moment_id}` (`operation_id="getMoment"`). camelCase pydantic models; gate both routes via `meeting_evidence_complete`; new `Problem` slug `meeting-not-viewable` (409); list excludes superseded, detail flags it; detail reads moment+meeting join, then covering segments (`ordinal` order, fields: `startMs`, `endMs`, `speakerLabel`, `speakerResolution`, `participantId`, `text`), then `artifacts: []` typed as `MomentArtifact` (`id`, `kind` ∈ the seven rail categories, `state` ∈ publish-gate states, `title`, `body`) — rows arrive with Epic 4, fields do not change. All reads on one `pool.connection()` block, split documented like `read_meeting`.
2. `server/meetingminer/api/main.py` — register `moments.router` between `meetings` and `media`, with a comment stating why the position is safe (no literal-vs-param collision today; a future literal sibling like `/moments/recent` must precede `/moments/{id}`).
3. `server/tests/test_api_moments.py` — new, `seed_meeting`-based (Postgres only): one test per I/O-matrix row plus field-set literals for each payload shape; superseded row minted by an UPDATE mirroring `stages/moments.py:224-232`; non-viewable via `stage_overrides`.
4. `web/src/client/` — regenerate via `make client` with the api running (`make api` against the dev stack; read-only, no store contention); commit the diff.
5. `web/src/lib/affordance.ts` — move `safeHref` + the affordance union out of `features/search/hits.ts` (which re-exports or imports it); moments must not deep-import a sibling feature. Keep behavior and tests identical.
6. `web/src/features/moments/` — `MeetingMoments.tsx` (moments list for one meeting: header, per-moment rows with offset + first-line text, click-through), `MomentView.tsx` (screenshot `<img src={mediaUrl(screenshotPath)}>` on top; transcript section below with speaker labels; right rail listing the seven artifact categories with the explicit dashed-border empty state; replay button mounting `ReplayPlayer` at `startMs` only when `hasRecording`; degraded mode renders the deep link through the affordance helper), `moments.ts` (pure display/decision helpers), colocated tests for both components and the helpers. Handle 409 `meeting-not-viewable` with the "still preparing evidence" message and 404 with not-found copy.
7. `web/src/App.tsx` + `App.test.tsx` — hand-rolled view union `{kind:'home'} | {kind:'meeting', meetingId} | {kind:'moment', momentId}` with a back affordance; wire `MeetingsList onOpen` (null-guard `meetingId`); export the setter shape so 2.3/3.4 reuse it; update the exhaustive SDK mock factory.
8. `web/src/features/search/CorpusSearch.tsx` + tests — add an "Open moment" affordance per hit invoking an optional `onOpenMoment?: (momentId: string) => void` prop (the story-3.1 deferred destination); App wires it.

**Acceptance Criteria:**

- Given a viewable recording-backed seeded meeting, when its moment is opened in the web app, then the still screenshot renders on top, the covering transcript below, and the right rail shows all seven categories with the explicit empty state.
- Given that moment view, when the replay button is pressed, then `ReplayPlayer` mounts with that `meetingId` and the moment's `startMs`.
- Given a transcript-only meeting's moment, when opened, then no screenshot and no player render, and the transitional source deep link is offered exactly where replay would be (http/https only; unsafe scheme shown inert).
- Given the meetings list, when Open is clicked on a viewable row, then the meeting's moments list renders; a non-viewable row's button stays disabled with its reason.
- Given a search hit, when its "Open moment" affordance is used, then the moment view for that `momentId` renders.
- Given the regenerated client, when `make web-test` and the server suite run, then all pass and every SDK mock factory lists the two new operations.

### Review Findings

- [x] [Review][Decision] Assign the Epic 4 artifact-hydration owner — **resolved 2026-08-20: Story 4.3 owns the moment-detail artifact query and any right-rail rendering extension.** Amend Story 4.1's stale claim that 2.2 owns the read, and state this dependency in Story 4.3 before implementation. The 2.2 payload's field/state vocabulary remains the forward wire contract.
- [x] [Review][Patch] Scope moment evidence joins to the same meeting [`server/meetingminer/api/moments.py:72`] — completed by `spec-2-2-moment-view-review-remediation.md`; reader joins now suppress foreign screenshot identifiers, paths, and transcript text, with two-meeting regression coverage.
- [x] [Review][Patch] Do not render a dead moment-open button [`web/src/features/moments/MeetingMoments.tsx:157`] — completed by `spec-2-2-moment-view-review-remediation.md`; only a callable handler renders the control, including an untyped `null` regression.
- [x] [Review][Patch] Make malformed-id OpenAPI describe the RFC 9457 response [`server/meetingminer/api/moments.py:240`] — completed by `spec-2-2-moment-view-review-remediation.md`; both routes document only `application/problem+json` `ProblemDetails`, and the client was regenerated from the branch schema.
- [x] [Review][Patch] Pin the repeatable-read snapshot guarantee [`server/tests/test_api_moments.py:305`] — completed by `spec-2-2-moment-view-review-remediation.md`; deterministic second-connection tests cover both detail and list reads.
- [x] [Review][Patch] Pin stale-response suppression in both moment loaders [`web/src/features/moments/MeetingMoments.test.tsx:232`; `web/src/features/moments/MomentView.test.tsx:275`] — completed by `spec-2-2-moment-view-review-remediation.md`; late successful responses cannot replace newer route state.

## Spec Change Log

- 2026-08-20 (build): List items carry a `preview` field — the first covered
  segment's text via a LATERAL join — because the specced "offset +
  first-line text" row needs text the SearchHit vocabulary does not carry.
  Additional field only; every shared field keeps the SearchHit spelling.
- 2026-08-20 (build): `MomentArtifact.kind` pinned as wire slugs
  (`action-item`, `adr`, `decision`, `story`, `requirement`, `bug-fix`,
  `change-request`); CAP-4's verbatim category names render in the web rail
  (`ARTIFACT_CATEGORIES` in `web/src/features/moments/moments.ts`). States
  asserted equal to `publish_gate.ARTIFACT_STATES` at import and in tests.
- 2026-08-20 (build): Client regenerated from this branch's app schema
  (`app.openapi()` dumped with the `http://localhost:8000` servers entry,
  then `pnpm --dir web run client -i <file>`) rather than `make client`: port
  8000 was already serving another checkout's api, which `make client` would
  have generated the *old* schema from. Output is identical to what `make
  client` produces against this branch — `client.gen.ts` is byte-unchanged.
- 2026-08-20 (build): `problemMessage` moved to `web/src/lib/problems.ts`
  alongside the specced `lib/affordance.ts` move (with `offsetLabel`), for
  the same reason: the moment views classify RFC 9457 problems and must not
  deep-import `features/search/hits.ts`. `hits.ts` re-exports everything, so
  search's callers and tests are unchanged.

## Review Triage Log

### 2026-08-20 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 13: (high 0, medium 4, low 9)
- defer: 2: (high 0, medium 0, low 2)
- reject: 4: (high 0, medium 0, low 4)
- addressed_findings:
  - `[medium]` `[patch]` The replay mount's `startMs` wiring was unpinned — `startMs={0}` passed the
    whole suite because the test asserted only `src` and the label (which reads `detail.startMs`
    directly). `MomentView.test.tsx` now fires `loadedmetadata` and asserts `currentTime === 44`.
  - `[medium]` `[patch]` Both new loaders' 8s expiry branch had no test; deleting the
    `expiry.signal.aborted` checks stayed green. Fake-timer hang tests added per component.
  - `[medium]` `[patch]` No server test produced a live zero-coverage moment, so flipping the list's
    `LEFT JOIN LATERAL` to an inner join silently dropped rows. Test added: links deleted, row still
    listed with `preview: null`.
  - `[medium]` `[patch]` Navigating to a drill-down unmounted the home trio, destroying search state
    on Back — the verify-a-claim loop forced a re-search each round. Home is now hidden, not
    unmounted; Back-stack tests added for both entry paths (meeting-origin and search-origin).
  - `[low]` `[patch]` Gate check and data reads were separate Read Committed snapshots; both routes
    now read under one `REPEATABLE READ` transaction (the one-statement-one-snapshot invariant,
    extended).
  - `[low]` `[patch]` The module-level artifact-vocabulary `assert` vanished under `python -O`; now
    `if ... raise RuntimeError`.
  - `[low]` `[patch]` Stale content lingered on id change and beneath failures in both components;
    state is cleared at load start.
  - `[low]` `[patch]` Double-click pushed duplicate view-stack entries; identical-top pushes are
    refused, pinned by test.
  - `[low]` `[patch]` The per-hit "Open moment" button rendered enabled without a handler when
    `onOpenMoment` was absent — a dead button; it now renders only with the prop.
  - `[low]` `[patch]` Four server pinning gaps closed: `ORDER BY start_ms, id` tiebreak; the
    transcript-only *list* shape (`sourceDeepLink`, null `screenshotId`); `application/problem+json`
    on the 422; gate precedence (superseded moment on an unsettled meeting → 409).
  - `[low]` `[patch]` `meetingTitleLabel`/`momentTitleLabel` were the same function twice; collapsed.
  - `[low]` `[patch]` `preview` shipped unbounded first-segment text; capped server-side at
    `LEFT(text, 300)` with tests (detail stays uncapped).
  - `[low]` `[patch]` Code Map's "409 has no `_STATUS_TITLES` entry" note was stale (it maps
    409 → "Conflict" at baseline); corrected.

Rejected as noise: an empty-string `screenshotPath` guard (the server cannot emit one); dedicated
colocated tests for the new `lib/` modules (covered via re-export and helper tests); a sideways
moment→meeting affordance (scope addition beyond the intent); spec-frontmatter cosmetics (the
`oversized` warning is a workflow flag and this log now fills the empty heading).

## Design Notes

**Gate semantics (the deferred 1.9 obligation).** Unknown id → 404 `not-found`; existing meeting with unsettled evidence → 409 `meeting-not-viewable`. That pair is the epic's required distinction between "never ingested" and "augmentation in flight" — a never-ingested meeting has no row at all. 409 (not 404) because the resource exists and the condition is transient; the problem detail says evidence is being prepared and will settle. The predicate is `projections/evidence.py:meeting_evidence_complete`, not a re-implementation, so the api and the projection trigger can never disagree.

**Superseded moments: list-hidden, detail-served.** Excluding them from the list honors the stage author's ghost warning; serving them by id honors "existing citations stay valid across augmentation" (SPEC Constraints). A flagged detail response lets a future citation renderer say "superseded" instead of breaking.

**Typed empty artifacts array.** The AC requires the rail be "functional before Epic 4 delivers extraction" and unpublished artifacts to surface here and only here. Shipping `artifacts: []` with a pinned model means Epic 4 adds rows, not a wire break. Fields chosen are the minimum forced by contract: the seven category names come from CAP-4 verbatim, states from `publish_gate.ARTIFACT_STATES`.

**Hand-rolled view state, no router.** No AC needs URLs; `CorpusSearch.tsx:31-45` records that inventing a router mid-epic collides with the story that owns paging structure. A `useState` union in `App.tsx` is the established grain, keeps `App.test.tsx` renderable without wrappers, and is the navigation primitive 2.3 and 3.4 are specced to reuse — it is deliberately exported.

**`screenshotPath` beside `screenshotId`.** The web needs a content-root-relative path for `mediaUrl()`; `SearchHit` carries only the id (its consumer never renders the image). Detail returns both: the id for citation parity, the stored `screenshot.path` verbatim for display — no root leaks, the containment guard still owns resolution at `GET /media/{path}`.

## Verification

**Commands:**
- `cd server && .venv/bin/python -m pytest tests/test_api_moments.py -q` — expected: green, one test per matrix row. Store-backed (Postgres only); safe to run concurrently since story 2.7 (AGENTS.md).
- `cd server && .venv/bin/python -m pytest tests/ -q` — expected: no regressions. Same concurrency note.
- `make web-test` — expected: all vitest suites pass, including the new moments feature and updated mock factories. Store-free.
- `pnpm --dir web run lint` — expected: clean (no `make web-lint` target exists).
- `pnpm --dir web run build` — expected: `tsc -b` clean against the regenerated committed client.
- `make client` (api running) — expected: regenerates `listMeetingMoments`/`getMoment` into `web/src/client/`; diff committed.

**Manual checks:**
- With the dev stack up, open a real ingested meeting from the meetings list, open a moment, press replay, and confirm the player opens at the offset; open a transcript-only meeting's moment and confirm the deep link stands in. The end-to-end seek→Range→206 loop has no automated harness (story 2.1 residual risk) — this is where it is first exercised for real.
- 2026-08-20 (build): performed via Playwright against the real corpus (branch
  api on :8010 with a scratchpad CORS shim for a vite on :5199, since :8000
  and :5173 were another checkout's). "vendor Contract Data Template Mapping
  Review- E&A": 165-moment list rendered; moment at 0:03 showed screenshot
  (200), 6-segment transcript, all seven rail categories plus the empty state;
  Replay mounted the player, recording answered **206 Partial Content**, and
  `video.currentTime` landed at 3.0s of a 3852s recording — the seek→Range→206
  loop confirmed end to end. "project- User Roles Review" (transcript-
  only): no screenshot, no replay button, no player; the SharePoint Stream
  deep link stood where replay would be. Back-stack returned moment → meeting
  list → home.

## Auto Run Result

Status: done
Blocking condition: none

**What was built.** The moment view — CAP-4's display surface. Two evidence-gated read endpoints
(`GET /meetings/{id}/moments` → `listMeetingMoments`, `GET /moments/{id}` → `getMoment`) and the web
views that consume them through the regenerated committed client: still screenshot on top, covering
transcript below, a seven-category right rail with an explicit empty state (Epic 4's forward wire
contract, `MomentArtifact`), a replay button mounting the story-2.1 player at `startMs`, and the
degraded transcript-only mode with the transitional source deep link. The story-1.9 deferred
server-side `viewable` gate now lives on both routes (404 never-ingested vs 409
`meeting-not-viewable`), and the app gained its first navigation primitive: an exported view-stack
union in `App.tsx`, wired from the meetings list's Open button and a new per-hit "Open moment"
affordance in search (the story-3.1 deferred destination).

**Files changed**

- `server/meetingminer/api/moments.py` (new) — both routes, camelCase models, the REPEATABLE READ
  single-snapshot reads, the gate, superseded semantics (list-hidden, detail-served flagged),
  `LEFT(text, 300)`-capped previews, the artifact forward contract.
- `server/meetingminer/api/main.py` — router registration between `meetings` and `media`, with the
  ordering note.
- `server/tests/test_api_moments.py` (new) — 16 tests: every I/O-matrix row, field-set literals,
  ordering tiebreak, transcript-only list shape, gate precedence, zero-coverage preview, cap.
- `web/src/client/{index,sdk.gen,types.gen}.ts` — regenerated with the two operations (see
  deferred: `types.gen.ts` baseUrl-literal drift and the regeneration workaround).
- `web/src/features/moments/{MeetingMoments,MomentView}.tsx`, `moments.ts` + 3 test files (new) —
  the list and detail views, helpers, 130-test web suite total.
- `web/src/App.tsx`, `App.test.tsx` — view-stack navigation, home kept mounted-but-hidden,
  duplicate-push guard, wired `onOpen`/`onOpenMoment`.
- `web/src/lib/affordance.ts`, `web/src/lib/problems.ts` (new), `web/src/features/search/hits.ts` —
  the degraded-mode and problem-classification helpers lifted to `lib/` with re-exports so search is
  unchanged; `CorpusSearch.tsx` gained the prop-gated "Open moment" affordance.
- `web/src/features/meetings/MeetingsList.test.tsx`, `CorpusSearch.test.tsx` — mock factories carry
  the two new SDK operations.

**Review findings.** 13 patched (0 high, 4 medium, 9 low), 2 deferred (frontmatter), 4 rejected,
0 intent gaps, 0 spec defects — no re-derivation loopback. Follow-up review recommended: **true**
(score 3×4 + 1×9 = 21, threshold 5).

**Verification** (every command run by the workflow owner after the review patches, not second-hand)

- `cd server && .venv/bin/python -m pytest tests/test_api_moments.py -q` — 16 passed.
- `cd server && .venv/bin/python -m pytest tests/ -q` — 1102 passed, 0 failed, 0 skipped, 4m55s.
  Run concurrently with other worktrees per AGENTS.md (per-run database); no contention observed.
- `make web-test` — 130 passed, 9 files.
- `pnpm --dir web run lint` — clean except the pre-existing `button.tsx` fast-refresh warning.
- `pnpm --dir web run build` — `tsc -b` + vite build clean against the committed client.
- `make client` could not run as written: :8000 serves another checkout's pre-2.2 api (verified:
  its schema has no moment paths). Client generated from this branch's schema dump instead; the
  one-line consequence is the first deferred item.
- Manual end-to-end: performed during the build via Playwright on the real corpus (see the dated
  note under Manual checks) — screenshot 200, replay 206 with `currentTime` at the offset,
  transcript-only deep link standing in.

**Residual risks**

- The rail's artifacts-exist path is exercised only web-side against hand-authored payloads; the
  server cannot emit a non-empty `artifacts` array until Epic 4's table lands. Story 4-1 is in
  flight with `0009_artifacts.sql` — its schema should be checked against `MomentArtifact`'s frozen
  wire shape (kinds/states) when it merges.
- No automated test spans the web↔api seam; the two halves are pinned separately (server payload
  field sets, mocked-SDK component tests) plus the one manual Playwright pass.
- The next honest `make client` run reverts one generated-type line (first deferred item).
