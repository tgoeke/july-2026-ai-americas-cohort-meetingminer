---
title: 'Story 1.3: Checkpointed Ingestion Worker (probe + frames)'
type: 'feature'
created: '2026-08-18'
status: 'done'
baseline_revision: '43e24dd5f3e841ba39d16d4f5f5c7953c4a3ac7e'
baseline_commit: 'acf5d754212aa5538b0958f603245e0145f53ba4'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
warnings: ['oversized']
deferred: []
---

<intent-contract>

## Intent

**Problem:** Jobs queue but nothing runs them — the worker idles, no Meeting row is ever minted, and no pipeline stage exists. Every downstream story (1.4 screens, 1.5 transcripts, 1.6 moments) needs a checkpointed, restartable stage runner and the first two stages to build on.

**Approach:** Give the worker a claim-and-advance loop over the eight `job_stage` checkpoints: it mints the meeting, skips the video stages for transcript-only drops, runs the implemented stages (`probe`, `frames`), and pauses at the first stage that has no implementation yet. `probe` records ffprobe media metadata; `frames` writes ffmpeg-sampled JPEGs under `MM_CONTENT_ROOT` with only relative paths in the DB.

## Boundaries & Constraints

**Always:**
- AD-11: the worker claims `queued` job rows and advances named stages, checkpointing each in Postgres. The api never executes a stage. Every stage is idempotent — a rerun deterministically overwrites *only* rows keyed to that job's meeting.
- AD-5/AD-14: the worker mints exactly one Meeting row per job (Postgres `uuidv7()`), linked by `job_id`, unique per `source_id`. Minted when the job is claimed, before stage dispatch — not inside `probe`, which is skipped for transcript-only drops.
- AD-3: media lives under `MM_CONTENT_ROOT`; the DB stores paths relative to that root only.
- AD-1: transcript-only drops (no `recording.mp4`) record `probe → frames → ocr → screens → transcribe` as `skipped` and proceed to `align`.
- AD-13: the drop directory is read-only — the worker reads `metadata.json` and the media, never writes into or deletes from the drop.
- Stages with no implementation yet (`ocr`…`extract`) are left `queued`; the worker stops advancing that job, leaves it `running`, and logs a paused event. It never marks unbuilt work `done` or `skipped`.
- Resume, not restart: stages already `done`/`skipped` are not re-executed when a job is re-claimed. Only a stage reset to `queued` (or left `running` by a crash) re-executes.
- Failure: `job_stage.status = 'failed'` + stage error, `job.status = 'failed'`, `job.error` naming the stage, `updated_at` bumped by a DB trigger. Never swallowed.
- Every worker/pipeline log line is structured JSON carrying `job_id` and `stage` (NFR17/NFR18).
- `MM_CONTENT_ROOT` is validated at worker startup (set, absolute, creatable, writable) — the deferred story-1.1 item, now that `frames` consumes it. Named fatal error, no traceback, matching the config/migration gate.
- Conventions: snake_case Python / snake_case Postgres; `domain` imports nothing above it; `pipeline` may import `domain` and `adapters`; `api` never imports `pipeline`.

**Block If:**
- The stage runner would need a second worker process or a distributed lease to be correct (AD-9 fixes exactly one worker on one Mac).
- Making `probe`/`frames` work would require modifying drop contents (AD-13).

**Never:**
- No `ocr`, `screens`, `transcribe`, `align`, `moments`, or `extract` implementations (stories 1.4–1.6, Epic 4).
- No SSE endpoint or job-progress API change (story 1.9) — `GET /jobs/{id}` keeps its current shape, so the committed TS client stays valid.
- No projections, Neo4j, or Meilisearch writes (story 1.7); no participants or transcript rows (story 1.5).
- No broker, no scheduler, no folder watcher; no new intake path.
- No adapter ports (`Ocr`/`Stt`/`Llm`) — ffmpeg/ffprobe are plain subprocess tools, not model calls.
- Never modify `pull_transcript/`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Recording drop claimed | `queued` job, drop with `recording.mp4` | meeting row minted; `probe` + `frames` `done`; `meeting_media` row; `frame` rows with relative paths; job stays `running`, `ocr` still `queued` | N/A |
| Transcript-only drop | `queued` job, drop with `transcript.txt` only | `probe frames ocr screens transcribe` all `skipped`; job stays `running` with `align` `queued` | N/A |
| Resume after pause/crash | job `running`, `probe` `done`, `frames` `queued` | claim re-runs `frames` only; `probe` not re-executed | N/A |
| Idempotent rerun | `frames` reset to `queued`, frames already on disk | frame rows and files for that meeting replaced, not duplicated; other meetings untouched | N/A |
| ffprobe fails | unreadable/corrupt `recording.mp4` | `probe` `failed` with the tool's error, job `failed`, `job.error` names the stage | named `StageError`, JSON log with `job_id`+`stage` |
| ffmpeg missing | no ffmpeg on PATH | stage fails with a named "ffmpeg not found" error | same as above |
| `MM_CONTENT_ROOT` unusable | unset, or a non-writable path | worker exits non-zero with a named startup error before claiming anything | no traceback |
| Orphaned `running` job | worker killed mid-stage, restarted | startup requeues `running` jobs to `queued`; stage checkpoints untouched, so completed stages are not redone | N/A |
| No queued jobs | empty queue | worker idles at the existing poll interval; no log spam | N/A |

</intent-contract>

## Code Map

- `server/meetingminer/worker/main.py` — `main()` (`:56`) config gate → signal handlers → migration gate → `worker.startup` log (`:80`) → idle loop (`:92`). Insert content-root validation after the config gate, orphan requeue after the migration gate, and replace the idle loop body with claim-and-run. `_log()` (`:27`) moves to the shared logger; `_fatal()` (`:41`) is the named-error contract to preserve. `__main__` must keep ignoring `--mm-owner` (`:100`).
- `server/meetingminer/domain/jobs.py` — `STAGE_NAMES` (`:11`), the canonical order both api and worker use. Add the video-only stage set here (domain vocabulary, importable by both).
- `server/meetingminer/db.py` — `conninfo()` (`:45`), `create_pool()` (`:57`), `MIGRATIONS_DIR` (`:27`). Migrations are numbered `.sql` applied in filename order; next file is `0002_`.
- `server/meetingminer/migrations/0001_jobs.sql` — `job` (`:4`) and `job_stage` (`:22`) shapes, the `job_source_id_live_key` partial unique index (`:18`), and the stage-status CHECK (`:26`) that already allows `skipped`. Both tables carry `updated_at` with a DEFAULT and **no trigger** — the deferred item this story must close.
- `server/meetingminer/api/ingests.py` — `METADATA_FILENAME`/`EVIDENCE_FILENAMES` (`:75`), `_seed_stages()` (`:188`) pre-seeds all 8 stages `queued`, and `create_ingest` (`:210`) stores an absolute `drop_path` + `corpus` + `source_id` on the job. The filename constants must become one shared definition in `domain` (the api may not import `pipeline`, and the worker may not import `api`).
- `server/meetingminer/config.py` — `_StrictModel` is `extra="forbid"` (`:92`), so a new `pipeline:` block needs a model; `Secrets.mm_content_root` (`:174`) is already resolved and absolute (`:238`); `_warn_content_root()` (`:251`) is the warning this story upgrades to a worker-side fatal.
- `config.yaml` — adapter bindings (AD-10); add the `pipeline:` sampling block here, not as a code constant.
- `server/meetingminer/api/jobs.py` — read model to leave untouched (`:49`); confirms failure is already observable through `stages[]`.
- `server/tests/conftest.py` — `REPO_ROOT` (`:25`), `test_pool` (`:112`), `make_drop` (`:138`, takes a `files=` tuple), `valid_metadata()` (`:64`). Reuse all of these; add a content-root fixture and a synthetic-mp4 fixture.
- `server/tests/test_migrations.py`, `server/tests/test_failfast.py` — the subprocess fail-fast patterns to extend for the content-root gate.
- `infra/Makefile` — `check-tools` (`:89`) is where a missing ffmpeg must become a named error; `start-worker` (`:258`) greps `worker.startup` for readiness, so that event must keep its name and stay on stdout.
- `_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md` — AD-3 (`:186`), AD-5 (`:192`), AD-11 (`:216`), AD-13 (`:224`), stage list + transcript-only rule (`:135`), ERD `JOB ||--|| MEETING` (`:367`). Read-only authority; the ERD fixes names/relationships, the code owns attributes.
- `pull_transcript/` — READ-ONLY corpus; never written by this story.

## Tasks & Acceptance

**Execution:**
- `server/meetingminer/migrations/0002_meetings_media_frames.sql` — add `meeting` (uuidv7 pk, `job_id` unique FK, `source_id` unique, corpus, `started_at` + precision, best-effort `title`, `has_recording`, `provenance` jsonb), `meeting_media` (meeting pk, duration/container/video+audio stream facts, size), `frame` (meeting FK, `offset_ms`, root-relative `path`, unique per meeting+offset); plus a `set_updated_at()` trigger function wired to `job`, `job_stage`, and the three new tables — closes the deferred `updated_at` item now that the worker mutates these rows.
- `server/meetingminer/domain/drops.py` — canonical drop filenames and a `DropContents` reader (`has_recording`, transcript paths, parsed `metadata.json`) so api and worker share one definition; `api/ingests.py` imports its filename constants from here instead of defining them.
- `server/meetingminer/domain/jobs.py` — add `VIDEO_ONLY_STAGES` (`probe frames ocr screens transcribe`) beside `STAGE_NAMES`.
- `server/meetingminer/logs.py` — one structured-JSON `log_event()` (stdout) plus a `job_id`/`stage`-bound variant, replacing the worker's private `_log`; module deliberately not named `logging`.
- `server/meetingminer/config.py` — add a `PipelineConfig` (`frames.interval_seconds`, `frames.jpeg_quality`) to `Settings`, and `require_content_root()` returning a validated, writable absolute root or raising `ConfigError`.
- `config.yaml` — add the `pipeline:` block with documented defaults (2s sampling — well under the 20–30s dwell cue, biasing toward over-capture).
- `server/meetingminer/pipeline/media.py` — `probe_media()` (ffprobe JSON) and `sample_frames()` (ffmpeg `fps` filter) as subprocess wrappers raising a named `MediaToolError` for a missing binary, non-zero exit, or unparseable output.
- `server/meetingminer/pipeline/stages/probe.py`, `.../frames.py` — the two stage implementations; `probe` upserts one `meeting_media` row, `frames` clears and rewrites only this meeting's frame rows and its own `meetings/<meeting_id>/frames/` subtree (guarded to stay inside the content root) before regenerating.
- `server/meetingminer/pipeline/stages/__init__.py` — the stage registry mapping names to implementations; unregistered names are the pause signal.
- `server/meetingminer/pipeline/runner.py` — claim a `queued` job (`FOR UPDATE SKIP LOCKED`), mint/reuse the meeting, walk `STAGE_NAMES` skipping already-`done`/`skipped` checkpoints, mark video stages `skipped` when the drop has no recording, run registered stages with per-stage checkpointing, pause at the first unregistered stage, and record failures on both the stage and job rows.
- `server/meetingminer/worker/main.py` — validate the content root at startup, requeue orphaned `running` jobs once, then poll the runner instead of idling; keep the `worker.startup` event name and the named-fatal contract.
- `infra/Makefile` — add `ffmpeg`/`ffprobe` to `check-tools` with a named error, since the worker now depends on them.
- `server/tests/` — cover every I/O matrix row: `test_drops.py` (drop vocabulary), `test_pipeline_media.py` (probe/frames against a synthetic ffmpeg-generated mp4; skip with a named reason when ffmpeg is absent), `test_worker_runner.py` (claim, mint, transcript-only skip, resume, idempotent rerun, failure recording, empty queue), `test_content_root.py` (subprocess startup gate). Extend `conftest.py` with content-root and synthetic-recording fixtures.

**Acceptance Criteria:**
- Given the epics.md Story 1.3 acceptance criteria, when each is exercised against the running worker, then it passes as written.
- Given `make up` with a recording drop POSTed to `/ingests`, when the worker claims it, then `GET /jobs/{id}` shows `probe` and `frames` `done`, frames exist under `MM_CONTENT_ROOT/meetings/<id>/frames/`, and every stored `frame.path` is relative and resolves under that root.
- Given a job whose stages are all `done`/`skipped` up to an unimplemented stage, when the worker restarts, then no completed stage re-executes and no ffmpeg process runs.
- Given `uv run --project server pytest server/tests`, when run with the compose Postgres up, then the whole suite passes with no new skips beyond the documented ffmpeg/Postgres ones.

## Spec Change Log

## Review Triage Log

### Review Findings

- [x] [Review][Patch] A second worker can requeue and concurrently execute an active job [server/meetingminer/worker/main.py:69]
- [x] [Review][Patch] Invalid metadata after intake leaves a claimed job running instead of recording failure [server/meetingminer/pipeline/runner.py:187]
- [x] [Review][Patch] A failed frames rerun deletes durable files while retaining their database rows [server/meetingminer/pipeline/stages/frames.py:44]
- [x] [Review][Patch] The frames deletion guard permits an in-root symlink to erase another meeting's output [server/meetingminer/pipeline/stages/frames.py:35]
- [x] [Review][Patch] Retrying a failed job with a transcript-only replacement retains stale video evidence [server/meetingminer/api/ingests.py:227]
- [x] [Review][Patch] Frame offset values are output ordinals, not verified source timestamps [server/meetingminer/pipeline/media.py:176]
- [x] [Review][Patch] A valid sub-millisecond frame interval produces duplicate persisted offsets [server/meetingminer/config.py:161]
- [x] [Review][Patch] A relative MM_CONTENT_ROOT is silently accepted despite the worker's absolute-path contract [server/meetingminer/config.py:248]
- [x] [Review][Patch] Claim and meeting-minted pipeline log records omit the required stage field [server/meetingminer/pipeline/runner.py:180]
- [x] [Review][Patch] A transient database failure after claim strands work until a process restart [server/meetingminer/worker/main.py:106]

## Design Notes

- **Why the meeting is minted at claim, not in `probe`:** the story text says "the first stage mints the Meeting row", but `probe` is skipped for transcript-only drops (AC 3), which would leave those jobs meeting-less. Minting at claim — idempotently, `ON CONFLICT (job_id) DO UPDATE` — is the only reading that satisfies both criteria, and keeps the observable ("after claim, exactly one Meeting row linked to the job") intact.
- **Pause, don't fake completion.** With only two stages built, a recording job legitimately ends at `ocr`. Leaving the stage `queued` and the job `running` is the honest state; 1.4–1.6 make jobs reach `done` by registering the remaining stages. Nothing else in the codebase has to change as they land.
- **Orphan recovery instead of leases.** AD-9 pins exactly one worker on one Mac and the Makefile enforces single-instance via pidfile, so `UPDATE job SET status='queued' WHERE status='running'` once at startup is sufficient and needs no lease/heartbeat machinery. It is safe precisely because stage checkpoints are *not* reset: completed stages are skipped on the re-run, so a restart never re-runs ffmpeg over an already-sampled recording.
- **Frame offsets.** ffmpeg's `fps=1/N` filter emits at exact multiples of the interval, so `offset_ms = (index - 1) * interval_ms` is deterministic and needs no per-frame timestamp parsing. Record this assumption next to the code — story 1.4 reads these offsets for dwell detection.

```
MM_CONTENT_ROOT/
  meetings/<meeting_id>/frames/frame-000001.jpg   # DB stores "meetings/<id>/frames/frame-000001.jpg"
```

## Verification

**Commands:**
- `uv run --project server pytest server/tests` — expected: all pass (start Postgres with `make infra-up` first; ffmpeg-dependent tests skip only when ffmpeg is absent).
- `make migrate && make migrate` — expected: applies `0002_...` once; the second run reports nothing to apply.
- `make test` — expected: server suite passes and the web build succeeds unchanged (no API surface change, so the committed TS client stays valid).
- `make up`, POST a recording drop to `/ingests`, then `GET /jobs/{id}` — expected: `probe`/`frames` `done`, `ocr` `queued`; `.logs/worker.log` shows JSON lines carrying `job_id` and `stage`; the drop directory's file list, sizes, and mtimes are unchanged.
- `MM_CONTENT_ROOT=/nonexistent/nope make worker` — expected: a named startup error and exit 1, no traceback.

## Suggested Review Order

**Worker safety and recovery**

- A database-held singleton prevents an overlapping worker from reclaiming live work.
  [`main.py:34`](../../server/meetingminer/worker/main.py#L34)

- Claim-time validation and recovery keep malformed or interrupted jobs recoverable.
  [`runner.py:184`](../../server/meetingminer/pipeline/runner.py#L184)

**Frames durability and timing**

- Stage output and retain backups until the database checkpoint is durable.
  [`frames.py:49`](../../server/meetingminer/pipeline/stages/frames.py#L49)

- Persist sampled source timestamps rather than output-file ordinals.
  [`media.py:207`](../../server/meetingminer/pipeline/media.py#L207)

**Input and operational contracts**

- Reject unsafe roots and intervals before frame generation begins.
  [`config.py:157`](../../server/meetingminer/config.py#L157)

- Revalidate modified drops against the source-drop schema at claim time.
  [`drops.py:141`](../../server/meetingminer/domain/drops.py#L141)

**Regression coverage**

- Exercise persistence, worker recovery, log context, and timestamp boundary cases.
  [`test_worker_runner.py:1`](../../server/tests/test_worker_runner.py#L1)

- Pin frame-timestamp and configuration-boundary behavior.
  [`test_pipeline_media.py:1`](../../server/tests/test_pipeline_media.py#L1)
