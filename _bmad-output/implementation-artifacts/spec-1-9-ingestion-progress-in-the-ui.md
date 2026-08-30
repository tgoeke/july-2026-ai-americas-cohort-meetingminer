---
title: 'Story 1.9: Ingestion Progress in the UI'
type: 'feature'
created: '2026-08-19'
baseline_commit: '89a1a0b300838a1601414d4ea291cac08d0893d7'
baseline_revision: '89a1a0b300838a1601414d4ea291cac08d0893d7'
status: 'done'
review_loop_iteration: 1
followup_review_recommended: true
deferred:
  - summary: >-
      GET /meetings returns every job ever ingested with all eight checkpoints and has no
      pagination or limit; the SSE stream re-reads the full job x job_stage join every tick
      per open connection.
    evidence: |-
      `_MEETINGS_WITH_STAGES` and `_JOBS_WITH_STAGES` carry no WHERE, LIMIT, or OFFSET. The
      module docstring and the spec's Design Notes both cite the `job_stage.updated_at`
      trigger (migration 0002) as what makes a cheap change-detection read possible, but
      nothing selects or filters on it. Cheap at this corpus size (30 jobs); the cost grows
      with total ingests rather than with in-flight ones, and every reconnect re-fetches
      the whole list. The spec scoped this out explicitly ("cheap on a single-user machine";
      "if a future load makes polling wrong, the endpoint's internals change and its wire
      contract does not"), so it is a scale deferral rather than a defect.
    location: >-
      server/meetingminer/api/meetings.py, server/meetingminer/api/events.py
    severity: medium
  - summary: >-
      The evidence_complete viewability gate is computed server-side but enforced only by the
      UI; the meeting-detail route Epic 2 builds must enforce it server-side.
    evidence: |-
      There is no meeting-detail route to defend yet, so the gate exists solely as a
      `disabled` prop on the Open button plus an `onOpen?` handler the shell does not supply.
      The spec's Design Notes state this as the honest boundary this story can hold. Epic 2
      inherits the obligation, and nothing in the code will remind it.
    location: >-
      web/src/features/meetings/MeetingsList.tsx
    severity: medium
  - summary: >-
      make check-client only asserts the three generated client files exist; it does not diff
      the committed client against the live OpenAPI schema.
    evidence: |-
      The spec's Code Map describes `check-client` as failing the build when the committed
      client is stale, but the target is a three-file existence loop (infra/Makefile). Real
      drift had accumulated unnoticed: regenerating in this story also flipped
      `Unprocessable Content` to `Unprocessable Entity` on the pre-existing createIngest
      operation. Pre-existing condition from story 1.10, surfaced by this review.
    location: >-
      infra/Makefile
    severity: medium
  - summary: >-
      The browser cannot tell a half-open stream from a healthy idle one — there is no
      client-side heartbeat timeout.
    evidence: |-
      `useJobEvents` sets `live` on any received frame but arms no timer, so a connection
      where no bytes arrive and no error is raised leaves the header reading `live` forever
      while the list silently stops updating. The server's heartbeat exists precisely to make
      this detectable; the client does not yet act on its absence.
    location: >-
      web/src/features/meetings/useJobEvents.ts
    severity: low
  - summary: >-
      The generated TypeScript client types the SSE body as `unknown`, so the wire contract is
      re-established by hand rather than by the generator.
    evidence: |-
      `StreamJobEventsResponses` is `{ 200: unknown }` because openapi-ts does not read
      OpenAPI 3.2's `itemSchema`. The three wire names therefore exist as two independent
      sources of truth — `EVENT_STAGE`/`EVENT_DONE`/`EVENT_ERROR` in events.py and
      `WIRE_EVENT_NAMES` in useJobEvents.ts — and the hand-written `isJobEvent` guard checks
      four of the seven fields. Nothing fails if the two drift. Revisit when the generator
      supports the shape.
    location: >-
      web/src/features/meetings/useJobEvents.ts
    severity: low
  - summary: >-
      The stream's snapshot read runs on anyio's default thread limiter, shared with every
      other sync route in the api.
    evidence: |-
      Each open stream occupies a worker thread once per poll interval via
      `anyio.to_thread.run_sync`. With many concurrent tabs this competes with the sync
      `/meetings` and `/jobs/{job_id}` handlers for the same default 40-thread pool. Not
      reachable in single-user use; a dedicated CapacityLimiter is the fix if it becomes real.
    location: >-
      server/meetingminer/api/events.py
    severity: low
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
  - '{project-root}/_bmad-output/specs/spec-meetingminer/ux-spine.md'
parallel_safe_with:
  - summary: >-
      Shares no file with story 1.7 (`server/projections`, `pipeline/runner.py`) or with the
      in-flight story 1.6 remediation (`pipeline/stages/**`, `domain/drops.py`).
    detail: |-
      Story 1.6 remediation landed as 89a1a0b and this story is baselined on it. It touches
      `server/meetingminer/api/**`, `web/**`, and one shared addition to
      `server/meetingminer/domain/jobs.py` (`evidence_complete`) whose definition is pinned
      identically in the 1.7 spec. The 1.6 remediation spec explicitly excludes API/UI from its
      scope.
---

<intent-contract>

## Intent

**Problem:** Ingestion is invisible. The web app renders a `/health` panel and nothing else; the API exposes no way to list meetings and no way to watch a job advance, only a point-in-time `GET /jobs/{jobId}`. A user who submits a drop has no idea whether a ~120-minute recording is on `frames` or `align`, whether a stage failed, or when a meeting is safe to open — and "precompute before viewing" is a rule with no mechanism behind it.

**Approach:** Add a `GET /meetings` list carrying each meeting's ingestion status, and a `GET /jobs/events` SSE stream that emits the pinned `job.stage`, `job.done`, and `job.error` events by watching job rows in Postgres. Build the meetings view in the web app against the regenerated typed client: a list with live per-stage progress, a visible stage error, and meetings that stay unopenable until their evidence bundle is complete.

## Boundaries & Constraints

**Always:**
- **Pinned event names** (FR8): the SSE stream emits exactly `job.stage`, `job.done`, and `job.error`. These are the *wire* names; they are deliberately distinct from the worker's structured log-event names (`stage.started`, `stage.done`, `job.paused`, `job.failed`), which are not a wire contract and must not leak into the stream.
- **Viewability is `evidence_complete`, not `job.status = 'done'`.** No job can reach `done` until Epic 4 registers `extract`, so gating on it would leave every meeting permanently unopenable. See *Design Notes* — this predicate is a shared contract with story 1.7.
- **The API never executes pipeline stages** (AD-11). Progress is served by reading job rows; the API process starts no work and blocks on nothing.
- **AD-5 table ownership:** this story's API code reads job, job_stage, and meeting rows. It writes none of them.
- **RFC 9457 problem+json** for every error response, through the existing `problems.py` handlers.
- **camelCase at the API boundary**, snake_case inside Python — the established `alias_generator=to_camel` pattern on every response model.
- Every new route carries an explicit `operation_id`, so the generated TypeScript client keeps stable names.
- **The committed client is regenerated** (`make client`) and the regenerated files are committed, matching the story-1.10 decision that `web/src/client/` is tracked.
- The stream survives an idle connection (heartbeat) and a client reconnect, and it terminates cleanly when the watched job reaches a terminal state.
- Transcript-only meetings render as a first-class state in the list, never as an error or a degraded-looking failure.

**Ask First:**
- If serving progress requires the worker to push (LISTEN/NOTIFY or otherwise) rather than the API reading rows — that would change AD-11's "API reading job rows" and touch worker files under active 1.6 remediation.
- If the meetings list needs any field that does not already exist in Postgres.

**Never:**
- No changes under `server/meetingminer/pipeline/**`, `server/meetingminer/worker/**`, or `server/meetingminer/domain/drops.py` — all are under active story-1.6 remediation.
- No changes under `server/meetingminer/projections/**` — story 1.7 owns that module in parallel.
- No meeting *detail* view, moment view, replay, screenshot rendering, or search UI. Those are Epic 2 and Epic 3. This story ships the list and the progress it carries.
- No new dependency on a state-management or data-fetching library. React state and the generated client are sufficient at this size.
- No polling loop in the browser as the primary mechanism — the stream is the mechanism; a single fetch on mount seeds it.
- No authentication, no multi-user affordance (NFR10).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Empty corpus | no meetings | list renders an empty state naming how meetings arrive (the puller) | N/A |
| Job queued, no meeting row yet | job row exists, worker has not claimed it | row appears in the list keyed by job, status `queued`, no title yet | N/A |
| Job running | stages advancing | per-stage progress updates live from `job.stage` without a reload | N/A |
| Transcript-only drop | video stages `skipped` | skipped stages render as *skipped*, visibly distinct from *done* and from *failed*; not an error | N/A |
| Evidence complete | stages through `moments` settled | `job.done` emitted once; the meeting becomes openable | N/A |
| Job paused at `extract` | `moments` done, `extract` queued and unregistered | meeting is openable; the unbuilt stage is not shown as failure or as in-progress | N/A |
| Stage failed | `job_stage.status='failed'` with an error | `job.error` emitted; the recorded stage error is displayed against that stage | error text shown verbatim, never swallowed |
| Attempt to open an incomplete meeting | evidence not complete | the open affordance is disabled with the reason stated | no navigation occurs |
| Stream reconnect | browser drops the connection | client reconnects and re-seeds from `GET /meetings`; no duplicate or missing rows | reconnect is silent below a threshold, then surfaced |
| API unreachable | api down | a named connection error, existing rows retained rather than blanked | reconnect attempted with backoff |
| Idle stream | no job activity | heartbeat keeps the connection open; no spurious events | N/A |
| Two jobs in flight | worker advances them in sequence | both rows update independently; events carry `jobId` | N/A |
| Failed job re-queued | intake returns the same job re-queued | its stages reset visibly; no duplicate list row | N/A |

</intent-contract>

## Code Map

- `_bmad-output/planning-artifacts/epics.md:31` — **FR8** pins the three SSE event names. `:103` **UX-DR1**: progress shown, viewing exposed only after full precompute. `:413` the story's three acceptance criteria.
- `_bmad-output/specs/spec-meetingminer/ux-spine.md` — *Ingestion flow*: ingestion completes before viewing; transcript-only meetings are searchable and citable without screenshots. The list is the only view this story builds.
- `server/meetingminer/api/jobs.py` — the existing `GET /jobs/{job_id}`. `_JOB_WITH_STAGES:26` is the single-statement job+stages read (one snapshot, deliberately — the comment explains why splitting it is wrong); `_STAGE_ORDER:19` sorts stages into pipeline order; `JobStage`/`JobResponse:33-52` are the camelCase response models to mirror. **The new stream and list build on these patterns.**
- `server/meetingminer/domain/jobs.py:11` — `STAGE_NAMES` (8 stages, `extract` last and unregistered), `:26` `VIDEO_ONLY_STAGES` (what a transcript-only drop records as `skipped`). This story adds `evidence_complete` here; see *Design Notes*.
- `server/meetingminer/pipeline/runner.py:328-329` — the honest pause at an unregistered stage: the job stays `running`, the stage stays `queued`, and `run_job()` **returns**. **This is why `job.status = 'done'` is unusable as the viewability gate** and why the paused state must not render as failure.
- `server/meetingminer/pipeline/runner.py:230` `_set_stage()` and `:243` `_fail_job()` — every stage transition is a committed `UPDATE` on `job_stage`/`job`, and `updated_at` is maintained by a database trigger (migration 0002). That trigger is what makes a cheap change-detection read possible without touching the worker.
- `server/meetingminer/migrations/0001_jobs.sql:4` `job` (`status`, `source_id`, `drop_path`, `corpus`, `error`, timestamps), `:22` `job_stage` (`name`, `status`, `error`, timestamps). `0002_meetings_media_frames.sql:26` `meeting` (`job_id` UNIQUE, `source_id`, `corpus`, `started_at`, `started_at_precision`, `title`, `has_recording`). The list is a join across these three; `meeting.job_id` is UNIQUE, so it is one-to-one.
- `server/meetingminer/api/main.py:81` — `app.include_router(...)`; `:74` CORS already allows the Vite dev origins, `:44` the lifespan holds `app.state.pool`. New routers register here.
- `server/meetingminer/api/problems.py` — `Problem` / `ProblemDetails`, registered handlers. Reuse; do not invent a second error shape.
- `web/src/App.tsx` — the current `/health` panel. Its abort-and-supersede pattern (`controllerRef`, `AbortSignal.any`, the "never set state for a stale check" guard, story 1.10 finding 22) is the concurrency discipline to carry into the new views.
- `web/src/client/sdk.gen.ts:24-41` — generated `createIngest`, `getJob`, `getHealth`. Regenerating adds the new operations. `web/src/client/core/serverSentEvents.gen.ts` — **the generated client already ships SSE support**; check whether it covers this shape before hand-rolling an `EventSource`.
- `web/package.json` — React 19.2, Vite 8.2, Tailwind 4.3, Base UI + shadcn, oxlint, `client` script (`openapi-ts`). **No test runner is declared** — see the deferred-work item below.
- `web/src/components/ui/button.tsx` — the only shadcn component installed so far; add others via the shadcn CLI rather than hand-writing them.
- `infra/Makefile:119` `check-client` (fails the build when the committed client is stale), `:140` `test:`, `:308` `start-web:`, `:410` `client:`. Regenerating the client is a tracked, checked step.
- `_bmad-output/implementation-artifacts/deferred-work.md` — carries "Introduce a front-end test harness (vitest + testing-library)", deferred from story 1.10 as a scope decision. **This story adopts it** — it is the first substantial UI, and its acceptance criteria are otherwise verifiable by `tsc` alone.

## Tasks & Acceptance

**Execution:**
- `server/meetingminer/domain/jobs.py` -- add `EVIDENCE_STAGES` and the pure `evidence_complete(stage_statuses)` predicate exactly as specified in *Design Notes*. If story 1.7 has already landed it, consume it unchanged. Do not modify `STAGE_NAMES`. -- One definition of "safe to open", shared with the projection trigger, in the module that depends on nothing above it.
- `server/meetingminer/api/meetings.py` -- new `GET /meetings` (`operation_id: listMeetings`) returning one row per job: `jobId`, `meetingId` (nullable before mint), `title`, `sourceId`, `corpus`, `startedAt`, `startedAtPrecision`, `hasRecording`, `status`, `error`, `stages[]`, and a computed `viewable` boolean from `evidence_complete`. One statement, one snapshot, mirroring `_JOB_WITH_STAGES`. Newest first. -- The list the UI seeds from and re-seeds to after a reconnect; `viewable` is computed server-side so the gate is not a UI opinion.
- `server/meetingminer/api/events.py` -- new `GET /jobs/events` (`operation_id: streamJobEvents`) returning `text/event-stream`. Reads job + job_stage rows on a configurable interval, diffs against the last emitted snapshot, and emits `job.stage` on any stage transition, `job.done` once when `evidence_complete` first holds, and `job.error` on a failure — every payload carrying `jobId`. Emits a comment heartbeat when idle and closes when no job is live. -- The live half of FR8; polling Postgres inside the API keeps AD-11 intact and touches no worker file.
- `server/meetingminer/config.py` -- add the stream's poll interval and heartbeat interval to the API settings as strict fields. -- Timing that affects perceived responsiveness is configuration, matching the project's no-magic-constants discipline.
- `server/meetingminer/api/main.py` -- register the two new routers. -- Nothing else in this file changes.
- `server/tests/test_api_meetings.py`, `server/tests/test_api_events.py` -- list shape and ordering; `viewable` false while evidence is incomplete and true once `moments` settles; the transcript-only skipped-stage shape; the paused-at-`extract` case rendering as complete-and-viewable rather than failed; a failed stage surfacing its recorded error; the three event names emitted with correct payloads; heartbeat on an idle stream; clean termination. -- The viewability gate and the event-name contract are the two things a future refactor is most likely to break silently.
- `web/package.json`, `web/vitest.config.ts`, `web/src/test/setup.ts` -- add `vitest`, `@testing-library/react`, `@testing-library/jest-dom`, `jsdom`; a `test` script. -- Adopts the deferred-work harness item; without it this story's UI behavior is unverifiable.
- `make client` / `web/src/client/**` -- regenerate and commit the typed client so `listMeetings` and `streamJobEvents` are available. -- `check-client` fails the build otherwise.
- `web/src/features/meetings/MeetingsList.tsx` (+ a `StageProgress` component and a `useJobEvents` hook) -- seed from `listMeetings`, subscribe to the stream, apply events by `jobId`, render per-stage progress with `done` / `skipped` / `running` / `queued` / `failed` visually distinct, show a stage error verbatim, and disable the open affordance with a stated reason while `viewable` is false. Carry `App.tsx`'s abort-and-supersede discipline into the seed fetch. -- The three acceptance criteria of the story, in one view.
- `web/src/App.tsx` -- make the meetings list the app's main view; keep the health panel as a subordinate element rather than deleting it. -- The health check is still the fastest "is my environment up" signal during development.
- `web/src/features/meetings/*.test.tsx` -- component tests for: live stage advance, skipped stages rendered as skipped, failed stage showing its error, and the open affordance disabled until `viewable`. -- Pins the behavior the epic's acceptance criteria actually name.
- `infra/Makefile` -- run the web test suite in `test`. -- A harness that does not run in CI is not a harness.

**Acceptance Criteria:**
- Given an in-flight job, when the meetings view is open, then its stage progress advances live with no reload and no browser polling loop, driven by `job.stage` events.
- Given the SSE stream, when its events are inspected on the wire, then their names are exactly `job.stage`, `job.done`, and `job.error`, each payload carries `jobId`, and no worker log-event name appears.
- Given a transcript-only meeting, when its job runs, then `probe`, `frames`, `ocr`, `screens`, and `transcribe` render as *skipped* — visually distinct from both *done* and *failed* — and the meeting still becomes viewable.
- Given a meeting whose evidence stages are not all settled, when a user tries to open it, then it is not openable and the reason is stated.
- Given a meeting whose stages through `moments` are settled while `extract` sits queued and unregistered, when the list renders, then the meeting is openable and no stage shows as failed or perpetually running.
- Given a failed stage, when the list renders that job, then the recorded stage error is displayed verbatim against that stage.
- Given the browser drops the stream, when it reconnects, then the list re-seeds from `GET /meetings` and shows neither duplicate nor missing rows.
- Given the API is unreachable, when the view is open, then a named connection error appears and previously loaded rows are retained rather than blanked.
- Given an idle stream with no job activity, when it is held open past the heartbeat interval, then the connection stays open and no spurious event is emitted.
- Given `make test`, when it runs, then the server suite, the new web suite, the puller suite, and the web build all pass, and `check-client` confirms the committed client matches the live schema.

## Spec Change Log

- **2026-08-19 (follow-up review) — the null-rows branch of `onEvent` re-seeds instead of calling
  `onAlive`.** The two cases were conflated. `onAlive` exists for a *failed* first load on an idle
  system, where a heartbeat is the only signal that another attempt is worth making, and it is
  correctly inert while a seed is running. The event case needs the opposite behaviour: precisely
  *because* a seed is running, its snapshot predates the event, so a further read is required.

- **`GET /jobs/events` is registered before `GET /jobs/{job_id}`.** Starlette matches routes in
  registration order, so with the natural ordering `/jobs/events` was swallowed by the
  parameterized route and rejected as a malformed UUID (422). `api/main.py` now includes
  `events.router` ahead of `jobs.router`, with the reason in a comment.
- **The stream uses FastAPI's native SSE support** (`response_class=EventSourceResponse` plus
  `ServerSentEvent` items) rather than a hand-rolled `StreamingResponse`. That is what makes the
  operation describe itself as `text/event-stream` in the schema, which in turn is what makes
  `@hey-api/openapi-ts` emit `streamJobEvents` as `client.sse.get`. The generator does not read
  the OpenAPI 3.2 `itemSchema`, so the stream's payload types as `unknown` in the client and is
  narrowed to the generated `JobEvent` by a type guard in `useJobEvents.ts`.
- **`GET /meetings` returns `{ "meetings": [...] }`** rather than a bare array, so a later
  addition (paging, counts) is not a breaking response-shape change.
- **Every event payload carries `viewable`,** not only `job.done`. The gate then self-heals: a
  client that missed one event converges on the next one it sees. Payloads also repeat the wire
  name in an `event` field, because the generated client yields event *data* without the name.
- **A job seen for the first time emits one `job.stage`** naming where it currently sits.
  Without it a drop submitted while the list is open would stay invisible; the UI treats an
  event for an unknown `jobId` as its cue to re-seed from `GET /meetings`.
- **"Closes when no job is live" is qualified:** the stream ends only once every job it has
  watched has settled *and* it watched at least one. A connection that opened onto an idle
  system stays open and heartbeats instead, because closing it would put the browser into a
  reconnect loop with nothing to report.
- **`job_events_heartbeat_seconds` defaults to 10s and the loader bounds it at 15s** —
  FastAPI's own fixed SSE keepalive interval — so the configured value is the one a client
  actually sees. The bound is enforced rather than asserted by a comment.
- **The `Open` affordance takes an optional `onOpen` handler.** There is no meeting-detail
  route yet (Epic 2), so the shell wires none; the gate — disabled with the reason stated while
  `viewable` is false — is what this story ships.
- **`server/tests/conftest.py` gained `meeting_projection` in `EVIDENCE_TABLES`.** Story 1.7's
  migration 0007 landed in the shared tree while this story was in flight and its table
  references `meeting`, which makes the isolation `TRUNCATE` fail without it. Additive only.
- **Deferred-work item closed:** "Introduce a front-end test harness (vitest + testing-library)
  and pin the App.tsx re-check abort behavior with a component test" — the harness is in, and
  `web/src/App.test.tsx` pins the abort-and-supersede guard (verified by deleting the guard and
  watching the test fail).

## Review Triage Log

### 2026-08-19 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 22: (high 2, medium 11, low 9)
- defer: 6: (high 0, medium 3, low 3)
- reject: 6: (high 0, medium 0, low 6)
- addressed_findings:
  - `[high]` `[patch]` The list wedged permanently when the first seed failed and the stream had never connected — `rows` stayed `null`, every event was dropped, and `markLive()` only re-seeds when `everConnected` was already true. Recovery path added and tested.
  - `[high]` `[patch]` `job_event_stream`'s per-tick `read_snapshot` had no error handling, so a transient database failure killed the generator after headers were sent. Transient failures are now survived and logged.
  - `[medium]` `[patch]` `diff_snapshots` never compared `snapshot.status`/`snapshot.error`, so a `queued`→`running` job move with no stage change emitted nothing.
  - `[medium]` `[patch]` The stage-less job failure path (`_fail_job` with no stage, three call sites in the runner) was uncovered on both sides, and `blockedReason` contradicted the rendered job error for that state.
  - `[medium]` `[patch]` `applyEvent` discarded a held stage error on a status-only event while falling back for `status` — the two rules are now consistent.
  - `[medium]` `[patch]` `job_events_heartbeat_seconds` was bounded at 3600 while both comments asserted it must stay under FastAPI's 15s SSE ping; the test fixture also sat exactly at that boundary.
  - `[medium]` `[patch]` The reopen-after-clean-close path had no coverage — `fakeStream.close()` was called by nothing and replacing the reopen loop with a `return` kept the suite green.
  - `[medium]` `[patch]` A clean server close left the connection header reading `live` through the reopen delay.
  - `[medium]` `[patch]` `useJobEvents` wrote `handlers.current` during render — unsafe under StrictMode and concurrent rendering.
  - `[medium]` `[patch]` The 5s seed timeout was untested; dropping `AbortSignal.any` kept the suite green.
  - `[medium]` `[patch]` The "does not navigate" test asserted a property the DOM enforces on a disabled button; button accessible names were also identical across rows.
  - `[medium]` `[patch]` `sprint-status.yaml` still recorded this story as `backlog`.
  - `[medium]` `[patch]` `web/vitest.config.ts` fell outside every tsconfig `include`, so `tsc -b` never checked it.
  - `[low]` `[patch]` `asStageStatus` relabelled an unknown status as `queued` rather than failing visibly.
  - `[low]` `[patch]` `blockedReason`'s fallback claimed ingestion had not started for a state where it had finished.
  - `[low]` `[patch]` The `GET /meetings` LEFT JOIN NULL-stage branch was never exercised.
  - `[low]` `[patch]` `@testing-library/user-event` was added and never used.
  - `[low]` `[patch]` The store-free web suite ran after `infra-up` and the full pytest run, contradicting the ordering principle stated two lines above it.
  - `[low]` `[patch]` `events.py` and `meetings.py` emitted no log lines despite the project's structured log vocabulary.
  - `[low]` `[patch]` `JobSnapshot` was declared `frozen=True` but its dicts were written after construction.
  - `[low]` `[patch]` The `__dirname` → `import.meta.dirname` change carried no rationale and raised the Node floor silently.
  - `[low]` `[patch]` `live` in `MeetingsList.test.tsx` was module-scoped and never reset, so its guard could be satisfied by the previous test's stream.

### 2026-08-19 — Follow-up review round applied

Source: `review-story-1-9-2026-08-19.md` (four independent layers over `89a1a0b..4e705e3`).
One medium defect and one low verification gap; both fixed.

- [x] **Initial seed/SSE overlap can lose a live stage transition** [`MeetingsList.tsx:110`] —
  while the first seed is in flight `rowsRef.current` is `null`, so `onEvent` called `onAlive()`,
  which deliberately declines to act while `inFlight` is true. The event was neither applied nor
  recorded as a pending re-seed, and the in-flight response then committed its older snapshot.
  Fixed by routing that branch to `requestSeed()`, which coalesces into the running fetch and
  re-runs it once afterwards. Regression: *does not lose a stage event that overtakes the first
  seed*.
- [x] **Terminal variant, not separately named by the review** — a dropped `job.done` never
  recovers, because the null branch returns before the `job.done` re-seed on the line below. The
  row keeps `viewable: false` and Open stays disabled permanently on a fully ingested meeting.
  Same one-line fix; separate regression: *does not strand a meeting unopenable when job.done
  overtakes the first seed*.
- [x] **Configured stream cadence was not asserted at the observable boundary**
  [`test_api_events.py`] — the tests patched poll and heartbeat values but asserted only that
  frames arrived inside the 20s read timeout, so fixed 1s/10s intervals stayed green. Fixed with
  three bounded-elapsed tests: a fast configured interval must arrive fast, a slow one must not
  arrive early, and the poll is timed independently of the heartbeat.

Both fixes were mutation-checked rather than assumed. Reverting the one-line change fails both UI
regressions; hardcoding `1.0/10.0` at the stream boundary fails the heartbeat and poll cadence
tests; hardcoding `0.1/0.1` fails the slow-heartbeat test.

### 2026-08-19 — Patch round 1 applied

All 22 `patch` findings above are fixed. Three notes on how, where the fix went further than
the finding asked:

- **`AbortSignal.timeout` is gone from the meetings seed** (finding 10). It cannot be cancelled,
  so every retry left a live 5s timer behind, and no test could drive it. An explicit
  `setTimeout` + `AbortController` pair, cleared in a `finally`, is both cancellable and
  testable. `App.tsx`'s health check still uses `AbortSignal.timeout`; it is story-1.10 code
  this story only moved, and its timeout branch is out of scope here.
- **Seeds are coalesced rather than aborted-and-superseded** (finding 1). At most one request is
  in flight and at most one is queued behind it, so a stale response cannot overwrite a newer
  one by construction — the finding-22 discipline holds without an abort-and-discard guard, and
  a burst of frames cannot become a burst of fetches.
- **Every fix was mutation-checked**: the fix was reverted, the corresponding test was confirmed
  to fail, and the fix restored. That covers findings 1, 2, 3, 7, 10, 11 and 14 individually.

## Design Notes

**Viewability cannot gate on `job.status = 'done'`.** The epic's acceptance criterion says a meeting whose job "has not reached `done`" is not viewable. Taken literally today, that makes every meeting permanently unopenable: `extract` is in `STAGE_NAMES`, has no registered implementation, and the runner deliberately pauses there rather than marking unbuilt work done (`runner.py:329`). Confirmed on the real database at story 1.6 close — `extract` is `queued` on all 30 jobs and no job is `done`. A literal reading ships a UI that never opens anything, including at the demo.

The criterion's intent is *precompute before viewing*, and the evidence bundle is complete at `moments`. `extract` produces artifacts, which are Epic 4 and which project only on publish (AD-4). So viewability gates on **evidence completeness**: every stage up to and including `moments` settled (`done` or `skipped`). This is correct for both drop kinds — a transcript-only meeting's video stages are `skipped`, which is settled — and it stays correct unchanged once Epic 4 registers `extract` and jobs begin reaching `done`.

**The predicate is a shared contract with story 1.7,** which needs the identical question answered to fire its projection trigger. It lives in `domain/jobs.py`, which both the API and the worker already import and which depends on nothing above it. Whichever story lands first adds it; the second consumes it unchanged. The definition is pinned identically in both specs so two parallel agents cannot diverge:

```python
EVIDENCE_STAGES = STAGE_NAMES[: STAGE_NAMES.index("moments") + 1]

def evidence_complete(stage_statuses: Mapping[str, str]) -> bool:
    return all(stage_statuses.get(name) in {"done", "skipped"} for name in EVIDENCE_STAGES)
```

**Wire event names are not log event names.** FR8 pins `job.stage` / `job.done` / `job.error`. The worker already logs `stage.started`, `stage.done`, `stage.skipped`, `stage.resumed`, `stage.failed`, `job.paused`, `job.failed`, `job.claimed`. Those are a structured-logging vocabulary with a different granularity and a different audience; the Makefile's readiness poll greps them. Mapping them onto the wire names is this story's job, and the mapping is deliberate: many log events collapse into one `job.stage`, and `job.done` fires on evidence-completeness rather than on any single log line.

**The API polls Postgres; the worker is not touched.** AD-11 already says "UI progress is served by the API reading job rows (SSE)". Reading is the sanctioned mechanism, and a short-interval read of two small tables is cheap on a single-user machine. The alternative — LISTEN/NOTIFY from the worker — would add a publisher to `runner.py`, the exact file under active story-1.6 remediation, and would buy latency that nobody can perceive on a pipeline whose stages run for minutes. If a future load makes polling wrong, the endpoint's internals change and its wire contract does not.

`job_stage.updated_at` is maintained by a database trigger (migration 0002), so change detection needs no cooperation from the worker at all.

**One stream, not one per job.** `GET /jobs/events` carries every live job, each payload keyed by `jobId`. The meetings list holds one connection regardless of how many ingests are in flight, and a future meeting-detail view filters the same stream rather than opening a second. Browsers cap concurrent connections per origin; a per-job endpoint would spend that budget for nothing.

**The viewability gate is server-computed, UI-enforced — and that is the honest boundary this story can hold.** `GET /meetings` returns `viewable` so the rule has one definition, and the UI disables the open affordance. There is no meeting-detail route to defend yet; Epic 2 builds it and must enforce the same predicate server-side when it does. Say this plainly in the handoff rather than implying the gate is already enforced end-to-end.

**Adopting the front-end test harness.** `web/` has no test runner, deferred from story 1.10 as an explicit scope decision. Every acceptance criterion here is a behavior — live update, skipped-vs-failed distinction, disabled affordance — that `tsc` cannot see. Standing up vitest + testing-library is in scope for this story because without it the story cannot be verified, and it is the first UI substantial enough to justify the harness.

## Verification

**Commands:**
- `make up` -- expected: stores healthy, migrations applied, api and worker running.
- `cd server && uv run pytest tests/test_api_meetings.py tests/test_api_events.py -q` -- expected: list shape, viewability gate, and all three event names pass.
- `make client && git status --porcelain web/src/client/` -- expected: the regenerated client is committed and `check-client` is clean.
- `cd web && pnpm test` -- expected: the new component suite passes.
- `make test` -- expected: server suite, web suite, puller suite, and web build all pass.
- `curl -N http://127.0.0.1:8000/jobs/events` while a job runs -- expected: `job.stage` events stream in stage order, `job.done` fires once at `moments`, heartbeats appear when idle.
- Submit a transcript-only drop through `POST /ingests`, watch the stream -- expected: five `skipped` stages, then `job.done`.

**Manual checks (if no CLI):**
- With `make start-web`, submit a real drop and watch the list advance through the stages without reloading; kill the api mid-stream and confirm rows are retained and the reconnect message is named, then restart it and confirm recovery.
- Confirm by eye that *skipped*, *done*, *queued*, *running*, and *failed* are distinguishable without reading the labels — the transcript-only path is the common case in this corpus and must not read as damage.

## Auto Run Result

Status: done

### Implemented change

`GET /meetings` lists every job with its checkpoints and a server-computed `viewable`; `GET /jobs/events`
streams the three pinned wire names (`job.stage`, `job.done`, `job.error`) by polling job rows and diffing
snapshots, so the api starts no work and the worker is untouched (AD-11). The web app gains a meetings view
that seeds from the list, applies events by `jobId`, renders per-stage progress with `done`/`skipped`/
`running`/`queued`/`failed` visually distinct, shows stage errors verbatim, and keeps a meeting unopenable
with the reason stated until its evidence bundle is complete. Viewability gates on `evidence_complete`
(every stage through `moments` settled), not on `job.status = 'done'` — confirmed against the real database,
where `extract` is unregistered and `queued` on all 30 jobs, so gating on `done` would leave every meeting
permanently unopenable. The front-end test harness (vitest + testing-library) was adopted, closing the item
story 1.10 deferred.

### Files changed

- `server/meetingminer/domain/jobs.py` -- `EVIDENCE_STAGES` and the pure `evidence_complete()` predicate, the shared contract with story 1.7.
- `server/meetingminer/api/meetings.py` *(new)* -- `GET /meetings` (`listMeetings`), one statement, one snapshot, newest first.
- `server/meetingminer/api/events.py` *(new)* -- `GET /jobs/events` (`streamJobEvents`), the SSE stream, its snapshot diff, and its read-failure policy.
- `server/meetingminer/api/jobs.py` -- extracted `stage_sort_key()` so both endpoints order checkpoints identically.
- `server/meetingminer/api/main.py` -- registers both routers and puts the config on `app.state`; `events.router` before `jobs.router` so `/jobs/{job_id}` cannot swallow `/jobs/events`.
- `server/meetingminer/config.py`, `config.yaml` -- the `api` section: poll and heartbeat intervals as strict fields.
- `server/tests/test_api_meetings.py`, `server/tests/test_api_events.py` *(new)* -- 30 tests over the list shape, the viewability gate, and the wire contract.
- `server/tests/test_config.py` -- fixture and bounds coverage for the new `api` section.
- `web/src/features/meetings/**` *(new)* -- `MeetingsList`, `StageProgress`, `stageStyles`, the pure `rows.ts` helpers, and the `useJobEvents` hook.
- `web/src/App.tsx`, `web/src/lib/api.ts` -- the meetings list becomes the main view; the health panel stays as a subordinate element.
- `web/src/client/**` -- regenerated for `listMeetings` and `streamJobEvents`.
- `web/package.json`, `web/vitest.config.ts`, `web/tsconfig.node.json`, `web/vite.config.ts`, `web/src/test/**` -- the vitest harness.
- `web/src/App.test.tsx`, `web/src/features/meetings/*.test.tsx`, `web/src/features/meetings/useJobEvents.test.tsx` *(new)* -- 36 tests.
- `infra/Makefile` -- a `web-test` target, run before `infra-up` so a store-free suite fails in seconds.
- `_bmad-output/implementation-artifacts/deferred-work.md`, `sprint-status.yaml` -- closed the harness item, recorded this story's four deferrals, moved 1.9 to `review`.

### Review findings breakdown

Four review layers ran in parallel against a diff isolated to this story's files. 0 intent_gap, 0 bad_spec,
**22 patches applied** (2 high, 11 medium, 9 low), **6 items deferred** (3 medium, 3 low), 6 rejected.

The two high-severity patches were real defects, not polish: the list could wedge permanently on
`Loading meetings…` when the first seed failed and the stream had never connected, and the stream's per-tick
database read had no error handling, so a transient failure killed the generator after headers were already
sent. Both now have tests that fail when the fix is reverted.

Follow-up review recommended: **true** — 2 patched findings were high severity (the rule fires on any high;
the medium/low score is 3x11 + 1x9 = 42, also over the threshold of 5).

### Verification performed

All commands below were run directly and their real results recorded.

- `make up` -- stores healthy, migrations current, api/worker/web running.
- `pytest tests/test_api_meetings.py tests/test_api_events.py tests/test_config.py -q` -- **76 passed**.
- Server suite excluding story 1.7's projection tests -- **579 passed, 2 failed**. Both failures
  (`test_ocr_adapter::test_parse_tsv_without_page_dimensions_is_a_named_error` and
  `test_worker_runner::test_empty_and_populated_stage_logs_carry_the_same_fields`) were reproduced
  identically at baseline `89a1a0b` in a separate worktree, so both are pre-existing and neither is this
  story's.
- `cd web && pnpm test` -- **36 passed** (3 files). `pnpm lint` -- clean but for one pre-existing shadcn
  warning in `button.tsx`. `pnpm build` -- tsc + vite clean.
- `make -C infra puller-test` -- **72 pass, 0 fail**.
- `make client` -- regenerates identically (md5-compared across two runs); no drift.
- Live `GET /meetings` against the dev database -- 30 rows, 23 viewable, camelCase, stages in pipeline order.
- Live SSE over a throwaway job -- `job.stage` for each of five `skipped` stages then the settled ones,
  `job.done` exactly once when `moments` settled, `job.error` carrying the recorded text verbatim, and
  `: heartbeat` on an idle stream. A second smoke confirmed the two newly patched paths: a job-status-only
  transition now reports (previously silent), and a stage-less job failure emits `job.error` with
  `stage: null` and the job's own error. Both throwaway jobs deleted; 0 rows remain.
- Matrix test audit -- all 13 I/O matrix rows map to tests that ran and passed, across the two server suites
  and the web suites.

`make test` as a whole is red, but not from this story: story 1.7's projection suites are landing in the same
working tree, and the parallel agent's concurrent pytest runs drop the shared fixed-name `meetingminer_test`
database mid-run. Every test that failed under the combined run passes in isolation, which is the existing
deferred item "Make DB-backed tests safe for concurrent runs".

### Review Findings

- [x] [Review][Patch] Heartbeat cadence is coupled to polling
  [`server/meetingminer/api/events.py:327`] — valid `heartbeat_seconds < poll_seconds` settings
  cannot produce heartbeats on the configured cadence because the loop only checks elapsed time
  after sleeping for the poll interval. Fixed and verified by the focused API event suite.
- [x] [Review][Patch] Cadence tests do not pin configured values or their independence
  [`server/tests/test_api_events.py:422`] — the new lower-only timing assertions permit altered
  cadence values, and no test observes a fast heartbeat while polling is deliberately slow. Fixed
  and verified by the focused API event suite.

### Residual risks

- The viewability gate is server-computed but **UI-enforced only**. There is no meeting-detail route to
  defend yet; Epic 2 must enforce `evidence_complete` server-side when it builds one. Deferred and recorded.
- Neither query is bounded — no pagination on the list, no `updated_at` watermark on the stream. Correct at
  30 jobs, and scoped out by the spec; deferred with evidence.
- A brief race remains between the seed fetch and the stream's baseline snapshot. Every payload carries
  `viewable`, and the client re-seeds on `job.done` and on an unknown `jobId`, so it converges.
- The stream's heartbeat bound is pinned against FastAPI's private `_PING_INTERVAL`, which can change in a
  patch release.
- `App.tsx` still uses `AbortSignal.timeout`; that is relocated story-1.10 code and its timeout branch was
  out of this story's scope.
- The api and the stores were left running from verification.
