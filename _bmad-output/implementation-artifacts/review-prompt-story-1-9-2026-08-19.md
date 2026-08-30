# Reviewer handoff — Story 1.9: Ingestion Progress in the UI

You have none of the context from the run that produced this change. Everything you
need is below.

## Repo and review range

- **Repo:** `/Users/devopsterus/current/cohort/meetingminer` (git, branch `main`, pushed to
  `origin/main`)
- **Review range:** `89a1a0b300838a1601414d4ea291cac08d0893d7..HEAD`
- **Commits in range (both are story 1.9; nothing else is in this range):**
  - `848db8188a0915c10ba1f1209b792b6092661972` — feat(api,web): stream ingestion progress and list meetings (story 1.9)
  - `7f6b76be354ce4299888f880cdddd1b2a529f7fe` — docs(story-1.9): record the spec, its review triage, and the deferrals

**Read the working tree with care.** A second agent is landing **story 1.7** (evidence
projections + rebuild CLI) into this same working tree in parallel. Its work is
**uncommitted** and is *not* in your review range, but it *is* present on disk:
`server/meetingminer/projections/**`, `server/meetingminer/adapters/embed/**`,
`server/meetingminer/migrations/0007_projection_state.sql`, `server/tests/projection_seed.py`,
`server/tests/test_projections_*.py`, `server/meetingminer/pipeline/runner.py`,
`server/pyproject.toml`, `server/uv.lock`, and the story-1.7 half of
`server/tests/conftest.py`. Four files carry **both** stories' changes on disk —
`config.yaml`, `server/meetingminer/config.py`, `server/tests/test_config.py`,
`infra/Makefile` — but the commits above contain **only** story 1.9's hunks of each.
Review the diff, not the working tree, when they disagree.

## The spec

`_bmad-output/implementation-artifacts/spec-1-9-ingestion-progress-in-the-ui.md`

- **Frozen intent — do not critique, treat as given:** everything inside the
  `<intent-contract>` block (Intent, Boundaries & Constraints, I/O & Edge-Case Matrix).
- **Planner work — fair game, attack freely:** Code Map, Tasks & Acceptance, Design Notes,
  Verification, and the Review Triage Log.

## Architecture authority

`_bmad-output/planning-artifacts/epics.md` and the architecture decision records it carries.
The ones that actually govern this change:

- **AD-11** — ingest pipeline stage order, and "UI progress is served by the API reading job
  rows (SSE)". This is why the api polls and the worker was not touched at all.
- **AD-5** — table ownership. This story's api code **reads** `job`, `job_stage`, and
  `meeting`; it writes none of them.
- **AD-4** — projections are built on publish. Relevant only as the reason `extract` is out
  of the viewability predicate.
- **AD-1** — a transcript-only drop records its video stages as `skipped`. This is why
  `skipped` counts as settled.
- **AD-10** — no magic constants; tuning lives in `config.yaml`.
- **FR8** (`epics.md:31`) — pins the three SSE event names.
- **UX-DR1** (`epics.md:103`) — progress is shown; viewing is exposed only after full
  precompute.
- Story acceptance criteria: `epics.md:413`.

## Scope

**In scope — the 34 files in the range:**

- Server: `api/events.py` *(new)*, `api/meetings.py` *(new)*, `api/jobs.py`, `api/main.py`,
  `domain/jobs.py`, `config.py`, `config.yaml`
- Server tests: `tests/test_api_events.py` *(new)*, `tests/test_api_meetings.py` *(new)*,
  `tests/test_config.py`
- Web: `src/features/meetings/**` *(new)*, `src/lib/api.ts` *(new)*, `src/App.tsx`,
  `src/App.test.tsx` *(new)*, `src/test/**` *(new)*, `src/client/**` *(regenerated)*
- Web config: `package.json`, `pnpm-lock.yaml`, `vitest.config.ts` *(new)*,
  `vite.config.ts`, `tsconfig.node.json`
- Build: `infra/Makefile`
- Docs: the spec, `sprint-status.yaml`, `deferred-work.md`

**Explicitly out of scope:**

- Story 1.7's projections work (see the warning above) — do not review it, do not report
  findings against it.
- Any meeting **detail** view, moment view, replay, screenshot rendering, or search UI.
  Those are Epic 2 and Epic 3. This story ships the list and the progress it carries.
- The vendored puller (`pull_transcript/`).
- The six items already recorded as deferred in the spec's frontmatter `deferred:` list and
  in `deferred-work.md`. Re-reporting them is noise.
- Authentication and any multi-user affordance (NFR10 defers them).

**No commit in the range belongs to another story.**

## Design decisions to attack

The planner is not a neutral judge of its own calls. Each of these is a choice plus the
assumption under it. Go after the assumptions.

1. **Viewability gates on `evidence_complete`, not on `job.status = 'done'`.**
   *Assumption:* the epic's "has not reached `done`" criterion means *precompute before
   viewing*, and the evidence bundle is complete at `moments`. `extract` is in `STAGE_NAMES`,
   has no registered implementation, and the runner deliberately pauses there
   (`pipeline/runner.py:328-329`), so a literal reading ships a UI that never opens anything —
   confirmed on the live database, where `extract` is `queued` on all 30 jobs and no job is
   `done`. *Attack:* is re-interpreting a stated acceptance criterion the right call, or should
   the criterion have been escalated instead? Does the predicate stay correct once Epic 4
   registers `extract`?

2. **The predicate lives in `domain/jobs.py` as a shared contract with story 1.7.**
   *Assumption:* both stories need the identical question answered, and pinning the definition
   in both specs prevents two parallel agents from diverging. *Attack:* is a shared mutable
   contract between two in-flight stories sound, or does it couple them?

3. **The gate is server-computed but UI-enforced only.**
   *Assumption:* with no meeting-detail route in existence, a disabled button plus a
   server-computed `viewable` is the honest boundary this story can hold, and Epic 2 inherits
   the server-side enforcement obligation. *Attack:* does shipping a gate nothing enforces
   create a false sense of safety? Is the deferral sufficient to make Epic 2 honor it?

4. **The api polls Postgres on an interval; the worker is untouched.**
   *Assumption:* AD-11 sanctions reading rows; a short-interval read of two small tables is
   cheap on a single-user machine; LISTEN/NOTIFY would add a publisher to `runner.py` (the file
   under concurrent story-1.6/1.7 edits) and buy latency nobody can perceive on stages that run
   for minutes. *Attack:* the module docstring cites the `job_stage.updated_at` trigger as what
   makes cheap change detection possible, but **no query filters on it** — the read is an
   unbounded full join every tick, per connection. Is the justification honest?

5. **One multiplexed stream, not one per job.** *Assumption:* browsers cap concurrent
   connections per origin, and a future detail view filters the same stream. *Attack:* the
   intent says "terminates cleanly when *the watched job* reaches a terminal state" (singular).
   The implementation closes when *every* watched job has settled, treats evidence-complete as
   settled, and **never** closes a stream that never saw a live job. The third rule is in
   neither the intent nor the spec.

6. **Wire event names are deliberately distinct from the worker's structured log-event names.**
   *Assumption:* `job.stage`/`job.done`/`job.error` are a wire contract; `stage.started`/
   `job.paused`/etc. are a logging vocabulary with different granularity and audience. *Attack:*
   the two now exist as independent hardcoded lists (`events.py` and `useJobEvents.ts`) with
   nothing connecting them, because the generated client types the SSE body as `unknown`.

7. **The heartbeat bound is pinned to FastAPI's private `_PING_INTERVAL`.**
   *Assumption:* mirroring the private constant as `FASTAPI_SSE_KEEPALIVE_SECONDS = 15.0` and
   bounding the configured heartbeat by it makes the stated invariant enforceable. *Attack:*
   this couples a validated config bound to a private framework constant that can change in a
   patch release.

8. **The front-end test harness was adopted here rather than left deferred.**
   *Assumption:* every acceptance criterion is a behavior `tsc` cannot see, so without vitest
   the story is unverifiable, and this is the first UI substantial enough to justify it.
   *Attack:* this closes a deferral story 1.10 made as an explicit scope decision.

9. **`web-test` was split into its own target running before `infra-up`.** *Assumption:* a
   store-free suite should fail in seconds. *Attack:* `make test` is now the only gate and
   there is no CI.

## History you need to tell a regression from a pre-existing condition

- **Baseline is `89a1a0b`** (story 1.6 review remediation). Everything before it is
  pre-existing.
- **Two test failures are pre-existing and were reproduced identically at `89a1a0b`** in a
  separate worktree. Do **not** report them as regressions:
  - `server/tests/test_ocr_adapter.py::test_parse_tsv_without_page_dimensions_is_a_named_error`
  - `server/tests/test_worker_runner.py::test_empty_and_populated_stage_logs_carry_the_same_fields`
- **`make test` is currently red as a whole, for reasons outside this story.** Story 1.7's
  projection suites are landing in the same tree, and the parallel agent's concurrent pytest
  runs drop the shared fixed-name `meetingminer_test` database mid-run, which produces
  spurious whole-file failures and errors. Every such test passes in isolation. This is the
  already-tracked deferred item "Make DB-backed tests safe for concurrent runs".
- **One review round already ran** against this change set: 22 findings were triaged `patch`
  and fixed before the commits above, 6 were deferred, 6 rejected. The Review Triage Log in the
  spec lists all 22. The two high-severity ones were real defects: the list could wedge
  permanently on "Loading meetings…" when the first seed failed and the stream had never
  connected, and the stream's per-tick database read had no error handling. Both now have tests
  that fail when the fix is reverted. **Findings that duplicate an already-fixed item are
  noise; findings that show a fix is incomplete or wrong are exactly what is wanted.**
- The regenerated client also flipped `Unprocessable Content` → `Unprocessable Entity` on the
  pre-existing `createIngest` operation. That is drift that had been sitting uncaught because
  `make check-client` only asserts the three generated files *exist* — it does not diff them
  against the live schema. Pre-existing from story 1.10; already deferred.

## Verification baseline

These are the current results. A skip or a failure you observe that is **not** listed here is
a finding, not noise.

| Command | Current result |
|---|---|
| `cd server && uv run pytest tests/test_api_meetings.py tests/test_api_events.py tests/test_config.py -q` | **76 passed** |
| Server suite excluding story 1.7's projection tests | **579 passed, 2 failed** (both pre-existing, listed above) |
| `cd web && pnpm test` | **36 passed** (3 files) |
| `cd web && pnpm lint` | clean but for one pre-existing shadcn warning in `button.tsx` |
| `cd web && pnpm build` | tsc + vite clean |
| `make -C infra puller-test` | **72 pass, 0 fail** |
| `make client` | regenerates identically (md5-compared across two runs); no drift |
| `make test` (whole) | **red** — see the history section; not this story's failures |

Verified against the actual commit in a clean worktree: 76 server tests and 36 web tests pass
with story 1.7's files absent, so the commits stand on their own.

Live checks performed (both throwaway jobs deleted afterwards, 0 rows remaining):

- `GET /meetings` on the dev database — 30 rows, 23 viewable, camelCase, stages in pipeline
  order.
- `curl -N /jobs/events` while advancing a job — `job.stage` per transition, `job.done` exactly
  once when `moments` settled, `job.error` carrying the recorded text verbatim, `: heartbeat`
  when idle.
- A second smoke confirmed the two newly patched paths: a job-status-only transition now
  reports (it was silent before), and a stage-less job failure emits `job.error` with
  `stage: null` and the job's own error.

All 13 rows of the spec's I/O & Edge-Case Matrix map to tests that ran and passed.

## Required output

Write your findings to:

`_bmad-output/implementation-artifacts/review-story-1-9-2026-08-19.md`

Structure it as:

1. **Verdict** — one paragraph: is this change sound, and what is the single most important
   problem with it?
2. **Findings** — one section each, most severe first. For every finding give: severity
   (high/medium/low), the file and line, what is wrong, a concrete failure scenario (inputs or
   state → wrong behavior), and why it matters. Separate *defects* from *design objections*.
3. **Design decisions assessed** — walk the nine decisions above and say, for each, whether the
   assumption holds.
4. **Verification assessment** — where the tests would still pass if the code were wrong. Name
   the mutation that survives.
5. **Anything out of scope you noticed** — listed separately and clearly marked, so it can be
   deferred rather than actioned here.

**Report findings; do not apply fixes.** Do not edit any file other than the review artifact
above.
