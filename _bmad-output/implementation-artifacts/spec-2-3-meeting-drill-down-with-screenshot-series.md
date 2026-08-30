---
title: 'Story 2.3: Meeting Drill-Down with Screenshot Series'
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
      The drill-down payload is unbounded — every screenshot plus the full transcript in one
      response, with no pagination or size cap.
    evidence: |-
      A long meeting serves hundreds of screenshots and segments in a single JSON body (the real
      corpus already has 122-screenshot / 348-segment meetings). Same scale-deferral class as the
      unpaginated GET /meetings already recorded in deferred-work.md — a deliberate MVP posture,
      not a defect, but unlike that entry this one was not yet recorded anywhere.
    location: >-
      server/meetingminer/api/moments.py (getMeetingDrilldown)
    severity: low
baseline_revision: 'c61e9175f6f5d532520ecfd9c72dbd629d0614ed'
---

<intent-contract>

## Intent

**Problem:** A meeting's evidence can only be seen one moment at a time: the meeting view is a bare moments list — no screenshot series, no full transcript, no mention highlighting, no inline replay — so scanning a whole meeting's visual flow (FR17, UX-DR5, CAP-4) is impossible, and the 409 empty state cannot tell an augmenting run from a first ingest (AD-14's required distinction).

**Approach:** Add one evidence-gated read, `GET /meetings/{meetingId}/drilldown` — header with meeting-level `sourceDeepLink`, screenshot series in `ordinal` order labeled with view classification and offsets, full transcript segments each carrying their `momentId` — and rebuild the meeting view on it: series on top, transcript below with a client-side highlight box, one inline `ReplayPlayer` mount driven from any screenshot or segment, degraded transcript-only mode, and a 409 whose new `augmenting`/`jobStatus` extensions let the empty state distinguish augmentation from first ingest.

## Boundaries & Constraints

**Always:**
- API read-only over evidence (AD-5): SELECTs only, sync psycopg via `app.state.pool`, raw SQL constants, the `moments.py` house style — including the `REPEATABLE READ` header-first (404) → gate (409) → payload ordering.
- The drill-down route lives on the existing `moments.py` router — no new `include_router` line in `api/main.py` (story 2-6 owns edits near it; sprint-notes names it the chokepoint).
- Screenshot series order is `screenshot.ordinal` (UNIQUE per meeting), never a timestamp sort; view classification is the stored `screenshot.view_type` (`slide`/`ui-screen`/`participant-gallery`), with `screen.label` surfaced when set.
- Segment→moment linkage is the `moment_segment` join (a segment belongs to exactly one moment); screenshot→moment linkage is the live (non-superseded) moment with that `screenshot_id`. Superseded moments never appear in either mapping.
- Field spellings reuse the established vocabulary: `momentId`, `meetingId`, `startMs`, `endMs`, `startedAt(+Precision)`, `screenshotId`, `sourceDeepLink`, `hasRecording`, plus segment fields exactly as `MomentDetail` spells them.
- Header `sourceDeepLink` is `meeting.provenance->>'url'` verbatim (raw, nullable); the web renders it only through `affordanceOf`/`safeHref` (http/https or inert) — same rule 2.2 litigated for moment links.
- The 409 `meeting-not-viewable` problem gains only additive camelCase extensions (`augmenting: bool`, `jobStatus: str`); `meetingId` and the slug are unchanged (2.2's tests pin them).
- `augmenting` derives from one new pure predicate in `domain/jobs.py` beside `evidence_complete`: an augmentation is in flight iff some stage with status `done` follows, in `STAGE_NAMES` order, an earlier unsettled evidence stage — sound because a first ingest settles stages strictly in pipeline order while augmentation re-queues evidence stages under a settled `extract` (which both augmentation tuples deliberately exclude).
- Highlighting is client-side over segment text: a pure helper produces `{text, highlighted}` runs (the `SnippetRun` shape) rendered with the `<mark>` idiom from `CorpusSearch.tsx:300-321`; the server sends no markup (AD-15 principle).
- One inline replay at a time: a single `openReplay` key + one `ReplayPlayer` mount at the region's offset (`start_offset_ms` / `start_ms`), the `CorpusSearch.tsx:388-398` pattern; never mounted unless `hasRecording`.
- Web loaders keep the abort-controller + 8s-expiry-timer + `problems.ts` classification idiom verbatim, including hang tests and stale-response suppression.

**Block If:**
- The out-of-order-settlement predicate proves undecidable against real stage data (i.e. a first-ingest snapshot exists that it marks augmenting).
- The drill-down needs edits to files story 2-6 owns (`api/ingests.py`, `config.py`, `api/main.py`).

**Never:**
- No writes anywhere; no store clients in `api/` (AST-walk test enforces).
- No `screen.label` editing (an API-owned Epic 2 column, but curation belongs to 2.4/2.5's write surface, not this read).
- No media caching validators (`ETag`/`Last-Modified`) — story 2.1's deferred item stays deferred; this story deliberately re-declines it to keep one goal (recorded decision, not omission).
- No URL router, no `App.tsx` source changes — the highlight term is drill-down-local input state, not view state.
- No new search surface or Meilisearch involvement — mention highlighting never queries the index (it is moment-grained, not segment-grained).
- No removal of `listMeetingMoments`/`getMoment` routes or payload fields.
- No hand-edited `web/src/client/*.gen.ts`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Drill-down | `GET /meetings/{id}/drilldown`, viewable recording-backed meeting | 200: header (meeting fields + `sourceDeepLink`) + `screenshots[]` in `ordinal` order (`screenshotId`, `ordinal`, `startOffsetMs`, `endOffsetMs`, `path`, `viewType`, `screenLabel`, `classificationTags`, `momentId`) + `segments[]` in `ordinal` order (`segmentId`, `ordinal`, `startMs`, `endMs`, `speakerLabel`, `speakerResolution`, `participantId`, `text`, `momentId`) | No error expected |
| Transcript-only | Same route, `has_recording = false` | 200: `screenshots: []`, `hasRecording: false`, header `sourceDeepLink` carries the recap URL, segments fully populated | No error expected |
| Uncovered segment | Segment with no `moment_segment` row | Listed with `momentId: null` | No error expected |
| Screen-derived moment | Live moment with `screenshot_id`, zero segments | Its screenshot row carries that `momentId` | No error expected |
| Superseded moment | Moment marked superseded (links deleted, `screenshot_id` kept) | Never appears as any screenshot's or segment's `momentId` | No error expected |
| Unknown meeting | Unknown UUID | 404 problem | `not-found` |
| First ingest in flight | Meeting row exists, stages settled in-order-so-far, evidence unsettled | 409 with `augmenting: false`, `jobStatus` | `meeting-not-viewable` |
| Augmentation in flight | Evidence stage unsettled while a later stage is `done` | 409 with `augmenting: true` | `meeting-not-viewable` |
| Malformed id | Non-UUID path parameter | 422 problem, `application/problem+json` documented | `invalid-request` |
| Cross-meeting corruption | Foreign `screenshot_id`/`moment_segment` rows aimed at another meeting | No foreign path, text, or id leaks (same-meeting guards on every join) | No error expected |

</intent-contract>

## Code Map

Read on `story/2-3` at baseline `c61e917` (= origin/main 75619ae + regenerated epic-2 context).

- `server/meetingminer/domain/jobs.py:13-87` — `STAGE_NAMES` (pipeline order), `VIDEO_ONLY_STAGES`, `AUGMENTATION_STAGES:55-59` and `PARTICIPANT_AUGMENTATION_STAGES:77-79` (both deliberately exclude `extract` — the comment at :43-47 is the predicate's foundation), `EVIDENCE_STAGES:87`, `evidence_complete():106-114` (settled = done|skipped). New predicate lands here.
- `server/meetingminer/api/moments.py` — the file to extend. `_MEETING_HEADER:50-53`; `_require_viewable:269-280` (the 409 to enrich — needs job.status + stage rows via `meeting.job_id`); REPEATABLE READ as first statement at :303/:350; `_PROBLEM_RESPONSES:240-266` (reusable 404/409/422 OpenAPI block); camelCase `ConfigDict(alias_generator=to_camel, populate_by_name=True)` on every model; operation ids `listMeetingMoments`/`getMoment`. Module docstring :8-27 states gate semantics and the moment_segment-not-BETWEEN rule.
- `server/meetingminer/projections/evidence.py:254-262` — the exact screenshot-series SQL to mirror (JOIN screen, ORDER BY `ss.ordinal`); :248-253 explains the LEFT joins. `meeting_evidence_complete:150-157` is the gate predicate the api already imports. Copy SQL shape into `moments.py` (house style, `moments.py:106-108`); do not import `read_meeting`.
- `server/meetingminer/migrations/0003_screens_screenshots.sql:40-87` — `screen` (`label` nullable human column :48, `view_type` 3-value CHECK :50-51) and `screenshot` (`ordinal` UNIQUE per meeting :86, `start/end_offset_ms` :69-70, content-root-relative `path` :76-77, `view_type` :78-79); `0004_capture_retune.sql:46-47` adds `classification_tags text[]` (no CHECK). `0005:163-213` `transcript_segment` (UNIQUE (meeting_id, ordinal)); `0006:71-78` `moment_segment` (`UNIQUE(transcript_segment_id)` — segment→moment is a function).
- `server/meetingminer/pipeline/runner.py:109-149` — `mint_meeting`: meeting row exists from claim time with `provenance` = drop metadata (so first-ingest-in-flight is 409, never 404); `domain/drops.py:265-309` — `provenance.url` is raw drop metadata (unvalidated at meeting level), `stream_url` validation applies only to moment links.
- `server/meetingminer/api/meetings.py:34-91` — `viewable` computation and the only payload exposing stage rows today; `jobs.py:20-27` `stage_sort_key` (unknown names sort last).
- `server/tests/projection_seed.py:75-272` — `seed_meeting`: seeds 2 screens/screenshots, both `'ui-screen'` (literal at :152 and :162), ordinals 1-2, offsets 0-30s/30-60s; `stage_overrides` param unsettles stages; `has_recording=False` seeds no screenshots and `DEEP_LINK` on moments plus meeting `provenance={"url": DEEP_LINK}`. Needs an additive `screen_view_types` param.
- `server/tests/test_api_moments.py` — conventions to extend: field-set literals :29-45; `_supersede:53-69`; cross-meeting corruption test :141-185; REPEATABLE READ monkeypatch shape :305-385 (gate-then-commit via second connection).
- `web/src/features/moments/MeetingMoments.tsx` — the component to rebuild (today: header + failure banners + plain moments `<ul>`; loader idiom :41-88 with the explicit-expiry-timer comment at :51-52). `moments.ts:13` `MOMENT_TIMEOUT_MS = 8000`; helpers live here.
- `web/src/features/replay/ReplayPlayer.tsx:4-12` — props (`meetingId`, `startMs`, `label?`, `className?`); re-seeks on `startMs` change (don't remount per seek, `CorpusSearch.tsx:389-391`); single-`openReplay` inline mount pattern at `CorpusSearch.tsx:72,349,388-398`.
- `web/src/features/search/CorpusSearch.tsx:300-321` — the `<mark className="bg-yellow-200 dark:bg-yellow-900">` run-rendering idiom to copy (no shared helper exists yet).
- `web/src/lib/affordance.ts` (`affordanceOf`, `safeHref`, `offsetLabel`), `lib/problems.ts` (`problemType`, `problemMessage`), `lib/media.ts:31-42` `mediaUrl(path)` — first many-image consumer.
- `web/src/features/meetings/rows.ts:61-76` — `blockedReason` ordering precedent for empty-state copy.
- `web/src/App.tsx:17-23` — `AppView`/`OpenView` union (kinds `home|meeting|moment`), reused as-is; `MeetingMoments` mount :161-166. Source untouched; only `App.test.tsx:14-37` mock factory grows (same in `MomentView.test.tsx:8-21`, `MeetingMoments.test.tsx`, `CorpusSearch.test.tsx`, `MeetingsList.test.tsx` — the factory lists every SDK export by design).
- `web/src/client/sdk.gen.ts` — ten operations today; `getMeetingDrilldown` makes eleven. Regenerate via `make client` (api running); if :8000 is occupied by another checkout, dump this branch's `app.openapi()` with a `servers: http://localhost:8000` entry and run `pnpm --dir web run client -i <file>` (2.2's litigated fallback — keeps `client.gen.ts` byte-identical).
- `_bmad-output/implementation-artifacts/deferred-work.md:52-54` — the 1.9 gate obligation this story's route completes (2.2 discharged the moment routes; this is the meeting-detail half). Mark resolved.
- Story 2-6 owns `server/meetingminer/api/ingests.py`, `server/meetingminer/config.py`, `api/main.py` (its :62 call). Story 3-2 unstarted. Do not touch.

## Tasks & Acceptance

### Review Findings

- [x] [Review][Patch] Covered transcript text is not the moment affordance [web/src/features/moments/MeetingMoments.tsx:400] — completed by `spec-2-3-meeting-drill-down-review-remediation.md`; covered text is now an accessible moment button and replay remains a sibling control.
- [x] [Review][Patch] Unicode folding suppresses unrelated valid highlights [web/src/features/moments/moments.ts:119] — completed by `spec-2-3-meeting-drill-down-review-remediation.md`; folded search coordinates now map back to original text, with a prior length-changing fold regression.
- [x] [Review][Patch] One SDK mock factory is missing the regenerated operation [web/src/features/meetings/useJobEvents.test.tsx:8] — completed by `spec-2-3-meeting-drill-down-review-remediation.md`; `useJobEvents` now declares `getMeetingDrilldown`.
- [x] [Review][Patch] `classificationTags` has no non-empty fidelity test [server/tests/test_api_moments.py:564] — completed by `spec-2-3-meeting-drill-down-review-remediation.md`; the happy-path fixture asserts ordered non-empty tag fidelity.

**Execution:**

1. `server/meetingminer/domain/jobs.py` — add `augmentation_in_flight(stage_statuses: Mapping[str, str]) -> bool`: True iff some stage with status `done` follows (in `STAGE_NAMES` order) an earlier evidence stage that is not settled. Docstring must state the soundness argument (first ingest settles in order; augmentation runs under a settled `extract`) and the known blind spot (a pre-4.1 job whose `extract` never settled degrades to `augmenting: false` — the honest conservative answer).
2. `server/tests/test_domain_jobs.py` — new, store-free: predicate truth table — first-ingest snapshots (in-order, incl. transcript-only skipped prefix) false; recording-augmentation and participant-augmentation snapshots true; all-settled false; empty mapping false; unsettled-`extract` blind spot pinned false.
3. `server/meetingminer/api/moments.py` — extend `_require_viewable` to also read `job.status` + stage rows (same transaction) and raise the 409 with `augmenting` and `jobStatus` extensions. Add `GET /meetings/{meeting_id}/drilldown` (`operation_id="getMeetingDrilldown"`) per the I/O matrix: REPEATABLE READ, header (meeting fields + raw `sourceDeepLink`), screenshots (series SQL mirroring `evidence.py:254-262` + LEFT-join live moment by `screenshot_id`, same-meeting guarded), segments (LEFT join `moment_segment`→live moment, same-meeting guarded, `ordinal` order), `_PROBLEM_RESPONSES` reused.
4. `server/tests/projection_seed.py` — additive `screen_view_types: tuple[str, ...] | None = None` param zipped with `screen_identity_keys` (default keeps both `'ui-screen'`); thread through both INSERTs.
5. `server/tests/test_api_moments.py` — drill-down tests: one per I/O-matrix row, field-set literals for the three payload shapes, mixed `view_type` labels via the new seed param, `screenLabel` surfaced after an UPDATE, 409 extension pair (`stage_overrides` producing in-order vs out-of-order snapshots), cross-meeting corruption for the two new joins, REPEATABLE READ via the established monkeypatch shape, and both 2.2 routes still carrying the enriched 409 extensions.
6. `web/src/client/` — regenerate (`make client` or the pinned fallback); commit the diff.
7. `web/src/features/moments/moments.ts` — add pure helpers: `highlightRuns(text, term)` (case-insensitive, returns `{text, highlighted}[]`, whole input as one un-highlighted run for empty term) and `notViewableMessage(problem)` (augmenting → augmentation copy; `jobStatus === 'failed'` → failed copy; else preparing copy — `blockedReason` ordering precedent).
8. `web/src/features/moments/MeetingMoments.tsx` + `MeetingMoments.test.tsx` — rebuild on `getMeetingDrilldown`: keep the loader idiom, header, and failure banners; replace the moments `<ul>` with (a) screenshot series in `ordinal` order — `<img src={mediaUrl(path)}>`, `viewType` label + `screenLabel` when set + `offsetLabel(startOffsetMs)`, click opens its `momentId` when present, inline-replay affordance per item when `hasRecording`; (b) transcript section — highlight input, per-segment speaker label + `highlightRuns` rendered with the `<mark>` idiom, segment click opens its `momentId` (no affordance when null), inline-replay affordance per segment when `hasRecording`; single `openReplay` key mounting one `ReplayPlayer` at the region's offset. Degraded mode (`hasRecording: false`): no series section, no replay affordances, meeting-level `sourceDeepLink` via `affordanceOf` where the series would be. 409 empty state renders `notViewableMessage`. Tests: series order/labels, highlight, both link paths, single-mount replay switching, degraded mode, augmenting-vs-preparing copy, loader hang + stale-response suppression preserved.
9. `web/src/App.test.tsx`, `MomentView.test.tsx`, `CorpusSearch.test.tsx`, `MeetingsList.test.tsx` — add `getMeetingDrilldown` to every SDK mock factory.
10. `_bmad-output/implementation-artifacts/deferred-work.md` — mark the server-side gate item (:52-54) resolved, naming 2.2 (moment routes) and this story (meeting drill-down route).

**Acceptance Criteria:**

- Given a viewable recording-backed meeting with mixed screenshot view types, when its drill-down opens in the web app, then the series renders in timeline order, each item labeled with its classification and timestamp, and clicking a screenshot with a live moment opens that moment view.
- Given a highlight term typed in the drill-down, when the transcript renders, then every case-insensitive occurrence is wrapped in `<mark>` and clicking a covered segment opens its moment view.
- Given any screenshot or segment replay affordance, when clicked, then exactly one inline `ReplayPlayer` is mounted at that region's offset without leaving the page, and clicking another region moves the single player rather than adding one.
- Given a transcript-only meeting, when its drill-down opens, then no series and no replay affordances render, transcript highlighting and moment links work, and the meeting-level recap link is offered through the affordance helper (unsafe scheme inert).
- Given a meeting mid-augmentation versus one mid-first-ingest, when the drill-down route answers 409, then the web empty state shows augmentation copy for the former and preparing copy for the latter; a never-ingested id shows not-found copy.
- Given the regenerated client, when the server suite, `make web-test`, lint, and build run, then all pass and every SDK mock factory lists `getMeetingDrilldown`.

## Spec Change Log

## Review Triage Log

### 2026-08-20 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 15: (high 0, medium 5, low 10)
- defer: 1: (high 0, medium 0, low 1)
- reject: 12: (high 0, medium 0, low 12)
- addressed_findings:
  - `[medium]` `[patch]` The `_SCREENSHOT_SERIES` LATERAL LIMIT-1 dedup (two live moments sharing a
    still) was defended only by its SQL comment; a server test now seeds the rival moment and pins
    one series row per screenshot with the earlier moment's id winning the tie-break.
  - `[medium]` `[patch]` `notViewableMessage` showed augmentation waiting copy for a failed job;
    `jobStatus === 'failed'` now takes precedence (the `blockedReason` failure-first precedent the
    spec itself cited), with the ordering test inverted and a failed-while-augmenting case added.
  - `[medium]` `[patch]` `MomentView` discarded the enriched 409 extensions and told failed-ingest
    users the moment "appears once every stage has settled"; it now renders `notViewableMessage`,
    with the three copy tests mirrored.
  - `[medium]` `[patch]` No test observed the inline replay's seek offset — `startMs=0` would have
    passed; two `loadedmetadata`/`currentTime` tests (screenshot → 30s, segment → 40s) now pin it.
  - `[medium]` `[patch]` `highlightRuns` mis-sliced text whose case fold changes string length
    (`İ`); a length guard returns one un-highlighted run, pinned by test.
  - `[low]` `[patch]` Server test added proving the API emits `jobStatus: "failed"` on the 409.
  - `[low]` `[patch]` `augmentation_in_flight`'s missing-stage-row-is-unsettled reading pinned in
    the truth table and docstring as deliberate.
  - `[low]` `[patch]` Route docstring added; `_PROBLEM_RESPONSES` 409 description now names the
    `augmenting`/`jobStatus` extensions; the `"unknown"` fallback commented schema-unreachable.
  - `[low]` `[patch]` `DrilldownScreenshot.view_type` typed as a three-value `Literal` (ArtifactKind
    precedent); client regenerated.
  - `[low]` `[patch]` `projection_seed.py` `screen_view_types` empty-tuple trap fixed
    (`is not None`, strict zip fails loudly).
  - `[low]` `[patch]` Highlight term reset on meeting change (stale-state house rule), pinned.
  - `[low]` `[patch]` Screenshot image itself now opens its moment (AC wording); `alt` prefers
    `screenLabel`; replay toggle's visible text is a prefix of its accessible name (WCAG 2.5.3).
  - `[low]` `[patch]` `loading="lazy"` on every series image (first many-image consumer).
  - `[low]` `[patch]` Per-segment highlight runs memoized over `(data, term)`.
  - `[low]` `[patch]` The 2.2-remediation untyped-null navigation-handler regression test restored
    against the new controls.

Deferred: the unbounded drill-down payload (frontmatter `deferred`). Rejected as noise: OpenAPI-typed
problem extensions (RFC 9457 extensions are open by design, house pattern since 2.2's `meetingId`);
seed `ON CONFLICT` view_type staleness (no test reuses identity keys divergently); a
screenshots-despite-`hasRecording:false` drift guard (server cannot emit it — the 2.2 precedent);
`headerAffordance` structural-typing worry (compile-checked); speculative `cancelled`/`done`
jobStatus copy (not in the CHECK, or unreachable); topic-mention/search-term carryover (no topic
model exists; the AC's disjunction is satisfied — recorded in Design Notes); capture-side headshot
production (Epic 1 shipped capture; this story is read-only); the `moments.drilldown` log-event
namespace; an `<img onError>` fallback (no requirement, broken-image default acceptable);
`_MEETING_HEADER`/`_DRILLDOWN_HEADER` duplication (one-SQL-constant-per-read house style); the
unused `listMeetingMoments` client operation (route deliberately retained per Never).

## Design Notes

**Route on the moments router, not a new module.** The drill-down is the meeting-scoped evidence read; `moments.py` already owns `/meetings/{id}/moments` and the gate. Registering no new router leaves `api/main.py` untouched — the one file both this story and in-flight 2-6 would otherwise edit.

**`augmenting` computed server-side, keyed on stage order.** AD-14 requires the distinction be derivable from `job.status` + stage rows with no schema change. The mechanical signal is out-of-order settlement: first ingests settle stages strictly in `STAGE_NAMES` order (skips are an intake-time prefix), while both augmentation tuples re-queue evidence stages beneath a deliberately-untouched settled `extract`. One pure predicate in `domain/` keeps api and any future consumer agreeing.

**Highlight is local and client-side.** The search index is moment-grained (AD-4 fixes its shape), so segment-level mention highlighting cannot come from Meilisearch without new projection work; UX-DR3's need is "the term I care about is visible in this transcript," which a client-side run-splitter over served segment text satisfies with zero server surface. The term lives in drill-down-local state, so `App.tsx` source is untouched.

**The moments `<ul>` is replaced, not kept.** Every live moment stays reachable — transcript-derived via its segments, screen-derived via its screenshot — so 2.2's "open a moment from the meeting" behavior survives inside the richer surface; keeping the bare list beside a full transcript would render the same rows twice.

**Media caching validators re-declined.** 2.1's deferred item names this story's series as the trigger, but it is a separable `media.py` concern with its own test surface; bundling it would make this a two-goal story. Re-declined deliberately and recorded here so the deferral is a decision, not an omission.

## Verification

**Commands:**
- `cd server && .venv/bin/python -m pytest tests/test_domain_jobs.py tests/test_api_moments.py -q` — expected: green; store-backed (Postgres only), concurrent-safe since 2.7.
- `cd server && .venv/bin/python -m pytest tests/ -q` — expected: no regressions.
- `make web-test` — expected: all vitest suites pass, mock factories complete. Store-free.
- `pnpm --dir web run lint` — expected: clean bar the pre-existing `button.tsx` fast-refresh warning.
- `pnpm --dir web run build` — expected: `tsc -b` + vite clean against the regenerated client.
- `make client` (api running; else the pinned fallback) — expected: `getMeetingDrilldown` lands in `web/src/client/`; diff committed.

**Manual checks:**
- With the dev stack up, open a real ingested meeting: series renders and scrolls, a highlight term marks the transcript, clicking a segment opens its moment, an inline replay plays at the region's offset (Range → 206). Open a transcript-only meeting: no series, recap link present, highlighting and moment links intact.
- 2026-08-20 (build): performed by the implementation agent against the real corpus (branch api on
  :8013, vite on :5183; :8000 was another checkout's). Recording meeting ("vendor Contract Data
  Template Mapping Review- E&A"): 122 screenshots in ordinal order with mixed
  slide/ui-screen/participant-gallery labels, all 122 linked to live moments, 348/348 segments
  covered; highlight "contract" produced 35 `<mark>`s; exactly one `ReplayPlayer`, moving between a
  screenshot and a segment region; segment click opened its moment; recording answered 206,
  screenshot 200. Transcript-only meeting: 0 screenshots, 305 segments, recap deep link rendered,
  zero replay affordances. Unknown id → 404, malformed → 422 on the live route.

## Auto Run Result

Status: done
Blocking condition: none

**What was built.** FR17/UX-DR5's meeting drill-down — the surface the scan-then-verify flow lands
on. One new evidence-gated read, `GET /meetings/{meetingId}/drilldown` (`getMeetingDrilldown`, on
the existing moments router so `api/main.py` stayed untouched): header with meeting-level raw
`sourceDeepLink`, the screenshot series in `ordinal` order (view classification, human
`screenLabel`, offsets, live-moment linkage deduped by a LATERAL `LIMIT 1`), and the full transcript
with per-segment `momentId` via `moment_segment` — all under one REPEATABLE READ snapshot with the
404/409/422 house semantics. The 409 `meeting-not-viewable` now carries additive
`augmenting`/`jobStatus` extensions on all three gated routes, derived by a new pure
`domain/jobs.augmentation_in_flight` predicate (out-of-order stage settlement — sound because both
augmentation tuples deliberately exclude `extract`), discharging AD-14's
augmenting-vs-first-ingest empty-state distinction with no schema change. The web meeting view was
rebuilt in place on the new payload: series with inline replay affordances and clickable stills,
transcript with a local highlight box (`highlightRuns` → the `<mark>` idiom, memoized), single
`openReplay` key mounting one `ReplayPlayer` at the region's offset, degraded transcript-only mode
rendering the recap link through `affordanceOf`, and a three-way 409 empty state
(`notViewableMessage`: failed → augmenting → preparing) also adopted by `MomentView`. The 1.9
deferred server-side gate obligation is now fully discharged and marked resolved in
`deferred-work.md`.

**Files changed**

- `server/meetingminer/domain/jobs.py` — `augmentation_in_flight` predicate with the soundness
  argument and the pre-4.1 unsettled-`extract` blind spot pinned conservative.
- `server/meetingminer/api/moments.py` — the drill-down route, enriched `_require_viewable`,
  `ScreenViewType` Literal, extension-documenting 409 responses.
- `server/tests/test_domain_jobs.py` (new) — 11-case predicate truth table, store-free.
- `server/tests/test_api_moments.py` — 16 new tests (every I/O-matrix row, LATERAL dedup tie-break,
  failed `jobStatus`, mixed view types, cross-meeting containment, REPEATABLE READ).
- `server/tests/projection_seed.py` — additive `screen_view_types` param (strict zip, `is not None`).
- `web/src/client/{index,sdk.gen,types.gen}.ts` — regenerated with `getMeetingDrilldown` and the
  three-value `viewType` union (pinned fallback regeneration; :8000 held by another checkout).
- `web/src/features/moments/MeetingMoments.tsx` + tests — the drill-down view (series, highlight,
  inline replay, degraded mode, empty states), 2.2's loader idiom kept verbatim.
- `web/src/features/moments/moments.ts` + tests — `highlightRuns` (length-fold guard) and
  `notViewableMessage` (failed-first).
- `web/src/features/moments/MomentView.tsx` + tests — adopts `notViewableMessage` on its 409.
- `web/src/App.test.tsx`, `MeetingsList.test.tsx`, `CorpusSearch.test.tsx` — mock factories carry
  the eleventh operation. `App.tsx` source untouched.
- `_bmad-output/implementation-artifacts/deferred-work.md` — 1.9 gate item marked resolved.

**Review findings.** 15 patched (0 high, 5 medium, 10 low), 1 deferred (unbounded payload,
frontmatter), 12 rejected, 0 intent gaps, 0 spec defects — no re-derivation loopback.
Follow-up review recommended: **true** (score 3×5 + 1×10 = 25, threshold 5; no high).

**Verification** (every command run by the workflow owner after the review patches, not second-hand)

- `cd server && .venv/bin/python -m pytest tests/test_domain_jobs.py tests/test_api_moments.py -q`
  — 47 passed (11 domain + 36 api).
- `cd server && .venv/bin/python -m pytest tests/ -q` — 1190 passed, 0 failed, 0 skipped, 4m52s.
  Ran concurrently with another worktree's suite per AGENTS.md (per-run database); no contention.
- `make web-test` — 156 passed, 9 files.
- `pnpm --dir web run lint` — clean bar the pre-existing `button.tsx` fast-refresh warning.
- `pnpm --dir web run build` — `tsc -b` + vite build clean against the committed client.
- `make client` could not run as written (:8000 serves another checkout's api without the route);
  the client was generated from this branch's schema dump via the 2.2-pinned fallback, twice
  (route addition, then the Literal narrowing), each regen committed.
- Manual end-to-end: performed by the implementation agent during the build (dated note under
  Manual checks) — 206 replay at offset, 122-screenshot series, transcript-only degraded mode.

**Residual risks**

- The augmenting-vs-first-ingest signal is proven against snapshots built from the real
  `AUGMENTATION_STAGES` tuples, not against a live augmentation run mid-flight; the predicate's
  pre-4.1 unsettled-`extract` blind spot deliberately degrades to first-ingest copy.
- The 409 extensions are untyped in the generated client (RFC 9457 extensions are open by design);
  the contract is pinned by parallel server and web tests, not a shared type.
- The implementation agent applied migration `0009_artifacts.sql` (additive, already on main) to
  the shared dev database via `make migrate` so this branch's api could boot for the manual check.
- The web↔api seam remains pinned separately (server field-set literals, mocked-SDK component
  tests) plus the one manual pass — same posture as 2.2.
