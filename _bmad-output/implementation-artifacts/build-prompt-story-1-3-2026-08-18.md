# Builder handoff — Story 1.3 review fixes

Use the review artifact at `_bmad-output/implementation-artifacts/review-story-1-3-2026-08-18.md` as the source of truth. The reviewed repository was `/Users/devopsterus/current/cohort/meetingminer`, branch `main`, range `5a9da4b..6c4bd43`.

The branch has moved since review: `main` is now `acf5d75` due to the unrelated Story 1.8 kickoff-document commit. Preserve it; do not fold that change into this work. The review findings and Story 1.3 spec edits are presently uncommitted in the working tree.

**Review verdict: Story 1.3 does not pass. Fix the ten findings below now.** There are no specification defects requiring a spec amendment, and no deferred findings.

## Fix now — worker ownership, recovery, and pre-stage failures

1. `server/meetingminer/worker/main.py:69` and `server/meetingminer/pipeline/runner.py:54`: startup unconditionally requeues every `running` job. If worker A is sampling frames and a manually launched `make worker` starts worker B, B requeues and claims A's job; both mutate one meeting and its output. Enforce a database-backed single-worker ownership / recovery invariant (for example advisory lock or lease) so recovery cannot reclaim active work. Add a two-worker regression test and confirm it fails against the unfixed code.

2. `server/meetingminer/worker/main.py:106` and `server/meetingminer/pipeline/runner.py:253`: claim commits `running`, but a transient DB error is only logged and the loop continues; recovery has already run. A mid-stage connection failure leaves the job running until a manual restart. Ensure recovery happens after reconnect or the process exits in a way that guarantees startup recovery; test an injected post-claim database failure against unfixed code.

3. `server/meetingminer/pipeline/runner.py:161-187` and `server/meetingminer/domain/drops.py:149`: after intake, invalid `startedAt` or `startedAtPrecision` reaches meeting minting outside the recorded failure path. The worker logs a DB/Drop error but leaves the claimed job `running`. Revalidate complete drop metadata at claim time and record any pre-stage failure on the job (and use a clear non-stage failure convention). Add mutation-between-intake-and-claim tests confirmed red on the old code.

## Fix now — preserve evidence-store integrity

4. `server/meetingminer/pipeline/stages/frames.py:44`: a frames rerun removes the old directory before ffmpeg succeeds, while previous `frame` rows are removed only after success. Make ffmpeg fail during a rerun: old rows remain but their JPEGs are gone. Publish frames transactionally enough that after failure either the old rows/files remain consistent or both are intentionally reconciled; use a temporary output directory and safe publish if appropriate. Add a failed-rerun rows-and-files test confirmed against unfixed code.

5. `server/meetingminer/pipeline/stages/frames.py:35`: an in-root symlink from the current meeting directory to another meeting passes the containment check and `rmtree()` deletes the other meeting's `frames`. Ensure deletion is lexically scoped to the actual current meeting and refuses symlinked ancestors / uses no-follow operations. Add a regression that proves another meeting's output survives; run it against unfixed code first.

6. `server/meetingminer/api/ingests.py:227` and `server/meetingminer/pipeline/runner.py:201`: a failed job may be requeued with a transcript-only replacement drop. Existing meeting media/frame rows and JPEGs survive even though `has_recording` becomes false and video stages are skipped. Either reject an evidence-shape-changing resubmit or clean every recording-derived row/file for that meeting when effective input has no recording. Test the permitted behavior on unfixed code.

7. `server/meetingminer/config.py:161`, `server/meetingminer/pipeline/media.py:207`, and migration `0002_meetings_media_frames.sql:83`: any positive float interval is accepted, but offset values round to milliseconds and must be unique. `0.0001` produces repeated offset `0`, making the frame insert fail after output is created. Validate an interval that guarantees representable unique offsets (or change representation) before work begins, and add the boundary regression demonstrated red on old code.

## Fix now — temporal and operational contracts

8. `server/meetingminer/pipeline/media.py:176` and `:207`: persisted offsets derive from output index, not the selected source frame PTS. VFR and non-zero-start-PTS recordings can produce visual content whose timestamp differs from `0, interval, ...`, corrupting downstream temporal logic while all current fixed-rate tests pass. Persist/derive the intended source timestamps, or establish a verified output-timeline contract that satisfies downstream consumers. Cover VFR, non-zero PTS, and shorter-than-one-interval inputs; each new test must be confirmed against the unfixed code.

9. `server/meetingminer/config.py:238`: `MM_CONTENT_ROOT=media` is converted to an absolute config-relative path, so the startup absolute-path check is unreachable even though Story 1.3 requires absolute input and the fatal guidance says so. Reject raw relative values before resolution and add the real worker-startup test against unfixed code.

10. `server/meetingminer/pipeline/runner.py:180` and `server/meetingminer/logs.py:58`: `job.claimed` and `job.meeting_minted` carry `job_id` but no `stage`, contrary to the every-worker/pipeline-record contract. Bind meaningful sentinel stages such as `claim` and `meeting` and make the logging test assert every pipeline record has both required fields; verify the test fails on old code.

## Required verification

Run the Story 1.3 spec's verification commands:

- `uv run --project server pytest server/tests`
- `make migrate && make migrate`
- `make test`
- `make up`, ingest a recording drop, inspect `GET /jobs/{id}`, worker JSON logs, generated frames, and unchanged drop contents
- `MM_CONTENT_ROOT=/nonexistent/nope make worker`

Also run each new regression test introduced for the ten findings, first against the unfixed implementation to establish that it detects the specified defect. The reviewer’s two `make test` attempts stalled in `test_makefile_procs` at roughly 60%; investigate/record that only if it still occurs after rerunning in a clean test environment, and do not widen Story 1.3 solely for it.

## Ordering and dependencies

First establish database-backed worker ownership (1), then make recovery and connection-failure behavior conform to that ownership model (2). Next centralize full post-intake validation and recorded failure handling (3), because the transcript-only replacement behavior in (6) must use the same trustworthy effective-drop classification. Make frames output publication/deletion safe (4 and 5) before adding the interval boundary guard (7), because that guard's old failure mode leaves filesystem artifacts. Settle the timestamp representation and its VFR contract (8) before finalizing frames assertions. The root-input (9) and structured logging (10) fixes are independent and can land in parallel once their tests are written.

## Explicitly out of scope

Do not implement Stories 1.4–1.6 or Epic 4 stages, SSE/job-progress API work, projections, adapters, brokers/schedulers/watchers, or changes under `pull_transcript/`. Do not revisit the Story 1.2 fixes: their VTT intake and single-snapshot job-read tests passed this review.
