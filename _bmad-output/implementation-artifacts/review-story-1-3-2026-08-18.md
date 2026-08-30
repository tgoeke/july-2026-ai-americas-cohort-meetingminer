# Review — Story 1.3: Checkpointed Ingestion Worker (probe + frames)

- date: 2026-08-18
- content reviewed: `5a9da4b..6c4bd43` on `main` (Story 1.3 plus the Story 1.2 follow-up commit)
- specification: `spec-1-3-checkpointed-ingestion-worker-probe-frames.md`, frozen intent contract plus its planner-owned material
- lenses: blind hunter (12 signals), edge-case hunter (4), verification-gap (3), acceptance auditor (3)
- exclusions: `pull_transcript/`, pre-recorded deferred work, Stories 1.4–1.6 and Epic 4 functionality, and the Story 1.9 SSE surface
- verification: `make test` was started twice and collected the expected 205 tests, but both runs stalled in `test_makefile_procs` after `60%`; I terminated only those review-launched test processes. The requested migration verification was therefore not run in that combined command.

Findings confirmed by more than one independent lens are marked `(xN)`.

## Worker ownership and recovery

1. **A second worker can requeue and concurrently execute an active job (x3).** `server/meetingminer/worker/main.py:69-73` calls `requeue_orphaned_jobs()` on every process start; `server/meetingminer/pipeline/runner.py:62-66` changes *every* `running` job to `queued`, with no database-held worker ownership, lease, or heartbeat. `make worker` is a foreground command and bypasses the background `start-worker` pidfile guard. While worker A runs ffmpeg, start worker B with `make worker`: B requeues and claims A's job, and both workers can mutate its checkpoints and delete/regenerate the same frames directory. The tests only model inactive rows (`test_worker_runner.py:426-443`), so this survives `make test`. Fix: enforce a worker singleton/ownership at the database boundary (for example, a PostgreSQL advisory lock or lease) and make recovery ownership-aware; add a two-worker regression test.

2. **A transient database failure after a claim strands work until the process is restarted.** `server/meetingminer/pipeline/runner.py:253-263` intentionally re-raises a database error after `claim_job()` has committed `running`; `server/meetingminer/worker/main.py:106-116` logs that error and continues polling, but recovery runs only once before the loop. A dropped connection during a stage therefore leaves the job running forever in the still-live worker process. Fix: either exit on that class of failure so startup recovery necessarily runs, or safely rerun recovery after reconnecting; test an injected mid-job database failure.

## Drop and meeting consistency

3. **Invalid metadata after intake leaves a claimed job running instead of recording failure (x3).** `read_drop()` only checks required-field presence (`server/meetingminer/domain/drops.py:149-170`). `mint_meeting()` then parses `startedAt` and writes `startedAtPrecision` outside the stage failure handler (`server/meetingminer/pipeline/runner.py:187`). Mutate an accepted drop to `startedAt: "not-a-date"` or `startedAtPrecision: "invalid"` before claim: a `DropError`/PostgreSQL constraint error escapes, the worker logs it, and no failure is written to the job or a stage. This violates the failure-recording requirement and the prompt's mutated-between-intake-and-claim case. Fix: validate the complete accepted drop contract at claim time and route every pre-stage failure through `_fail_job`; add mutation regressions.

4. **Retrying with a transcript-only replacement retains stale video evidence.** The failed-job resubmit path replaces `drop_path`, resets stage rows, and retains the existing Meeting (`server/meetingminer/api/ingests.py:227-238`; `server/meetingminer/pipeline/runner.py:99-125`). For a job that completed probe/frames, later failed, then is resubmitted with the same source ID but no recording, the runner marks the video stages skipped (`runner.py:201-204`) but never removes `meeting_media`, `frame` rows, or their JPEGs. The Meeting says `has_recording = false` while old video evidence remains. Fix: when the effective drop has no recording, remove that meeting's recording-derived rows and output subtree, or reject an evidence-shape-changing resubmit; add the requeue regression.

## Frames integrity and temporal data

5. **A failed frames rerun deletes durable files while retaining their database rows (x2).** `server/meetingminer/pipeline/stages/frames.py:44-59` removes the existing frame directory before calling ffmpeg, but it deletes existing `frame` rows only after successful sampling (`:67-75`). Requeue a completed frames stage and make ffmpeg fail: `_fail_job()` rolls back DB work, leaving old rows committed while their files are gone. The successful-rerun test does not induce a failed rerun. Fix: sample into a temporary sibling directory and atomically publish only after a successful checkpoint, or preserve the old directory until the replacement is known good; test failure preserves a consistent rows/files pair.

6. **The deletion guard permits an in-root symlink to erase another meeting's frames (x2).** The guard only checks that `frames_dir.resolve()` remains under the content root (`server/meetingminer/pipeline/stages/frames.py:35-46`). If `meetings/<current-id>` points to `meetings/<other-id>`, the resolved path is still inside the root and `shutil.rmtree()` removes the other meeting's `frames` directory. This violates the requirement that a rerun overwrite only output keyed to its meeting. Fix: reject symlinked ancestors / validate the lexical `meetings/<UUID>/frames` path with no-follow operations; add a cross-meeting symlink test.

7. **Frame offsets are output ordinals, not verified source timestamps (x2).** `sample_frames()` documents that `fps=1/N` emits frames at exact multiples and `frame_offset_ms()` stores `(index - 1) * N` (`server/meetingminer/pipeline/media.py:176-180,207-212`). This is not a source PTS for VFR or timestamp-offset media: the `fps` filter selects/resamples source frames, while the JPEG ordinal has only the filter output timeline. The current tests use one fixed-rate synthetic MP4 and assert the same arithmetic as the implementation. Downstream dwell/alignment code can receive a JPEG for one moment labelled as another. Fix: capture the selected frame timestamps and persist them, or explicitly define/preserve offsets as filter output times after verifying that semantic; add VFR, non-zero-start-PTS, and shorter-than-interval coverage.

8. **A valid sub-millisecond interval produces duplicate persisted offsets.** `FramesConfig.interval_seconds` accepts every positive float (`server/meetingminer/config.py:157-163`), but `frame_offset_ms()` rounds to whole milliseconds and `frame` is unique on `(meeting_id, offset_ms)` (`server/meetingminer/migrations/0002_meetings_media_frames.sql:76-84`). With `interval_seconds: 0.0001`, multiple outputs map to offset `0`, so insert fails after JPEGs were generated. Fix: require an interval of at least one millisecond (or store sufficient timestamp precision) and test the configuration boundary.

## Contracts and observability

9. **A relative MM_CONTENT_ROOT is silently accepted despite the worker's absolute-path contract (x2).** `_load_secrets()` turns `MM_CONTENT_ROOT=media` into an absolute path beneath the config directory (`server/meetingminer/config.py:238-252`), making `require_content_root()`'s absolute check unreachable (`:302-309`). The frozen contract says the root is validated as absolute at startup, and the fatal message tells users to set an absolute path. Fix: retain the raw value or reject relative input before resolution; add a subprocess startup test for a relative setting.

10. **Claim and meeting-minted pipeline records omit the required stage field.** `run_job()` binds only `job_id` and emits `job.claimed` / `job.meeting_minted` (`server/meetingminer/pipeline/runner.py:180-192`); `BoundLogger` omits an unset `stage` (`server/meetingminer/logs.py:58-64`). The test checks `stage` solely on `stage.failed` (`server/tests/test_worker_runner.py:376-401`), so removing stage from all pre-stage records stays green. This breaks the explicit JSON logging contract. Fix: bind named non-stage contexts such as `claim` and `meeting`, and assert every emitted pipeline record carries both fields.

## Story 1.2 follow-up verification

The two Story 1.2 fixes in `a56440e` are correct and complete:

- `GET /jobs/{id}` now obtains job and stage rows with one `LEFT JOIN` statement (`server/meetingminer/api/jobs.py:25-30`), preserves jobs that have no stage rows, and sorts stages by canonical pipeline order (`:73-80`). `test_requeue_committed_mid_read_cannot_split_job_from_its_stages` invokes its concurrent requeue immediately after the endpoint's first statement; the old two-statement implementation would return the proven torn state, so the test is not vacuous.
- `test_valid_vtt_only_drop_returns_201_with_queued_job` executes the endpoint with only `transcript.vtt`, confirms the job and all seeded checkpoints, and would fail if VTT were removed from accepted evidence.

## Verdict

**Does not pass review as it stands.** Ten actionable issues remain: four high-integrity/concurrency failures and six medium contract, recovery, and verification defects. The Story 1.2 follow-up passes its secondary check.
