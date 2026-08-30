---
title: 'Story 1.2: Source-Drop Intake Endpoint'
type: 'feature'
created: '2026-08-18'
status: 'done'
review_loop_iteration: 0
baseline_commit: '759c0e3e44c1695c455b6e7766005cd6f2a1b3e3'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** No evidence can enter the system — there is no drop contract, no job storage, and no intake API; every pipeline story (1.3+) needs jobs to claim.

**Approach:** Pin the drop contract as `docs/source-drop.schema.json`, create the first Postgres tables (`job`, `job_stage`) via a numbered-SQL migration mechanism, and implement `POST /ingests` (validate drop at an absolute path, insert job row) plus `GET /jobs/{id}` (status + per-stage checkpoints), with all API errors as RFC 9457 `problem+json`.

## Boundaries & Constraints

**Always:**
- AD-14: `POST /ingests` takes a JSON body with an absolute drop-directory path; the API validates against the schema and inserts the job row. No Meeting row at intake — the worker mints it in story 1.3.
- Schema (AD-1): versioned, camelCase, explicit `schemaVersion` (1). `metadata.json` requires `sourceId`, `corpus` (`scripted`|`real`), `startedAt` (ISO 8601 UTC) + `startedAtPrecision` (`second`|`day`), embedded `provenance` (open object); `participants` optional. Canonical drop filenames: `metadata.json`, `recording.mp4`, `transcript.vtt`, `transcript.txt` — at least one of recording/transcript present; all other files ignored.
- Migrations: numbered `.sql` files in `server/migrations/` applied in order by a small runner recording into `schema_migrations`; `make migrate` target; api and worker fail fast at startup on pending migrations (named error, no traceback — matching the config fail-fast contract).
- IDs are UUIDv7 minted by Postgres inserts (`uuidv7()`, native in pg18).
- `sourceId` with an existing non-failed job → RFC 9457 409 conflict. A failed job is re-queued in place (same job id returned) — never a second job row per sourceId.
- Every API error body is `application/problem+json` — override FastAPI's default 404/422 handlers so nothing emits `{"detail": ...}`.
- Intake never writes into or deletes from the drop directory (AD-13).
- Conventions: snake_case Python / camelCase JSON via the existing `to_camel` alias pattern; explicit `operation_id` on every route; `api` never imports `pipeline`; DB deps: psycopg 3 (+ psycopg_pool), schema validation: `jsonschema`.

**Ask First:**
- Any new `config.yaml` key or `.env` variable (Postgres settings + password already exist in config).
- Any dependency beyond psycopg, psycopg-pool, jsonschema.
- Adding schema fields beyond the AD-1 list (e.g. `groundTruthId`).

**Never:**
- No stage execution, worker claiming, or pipeline logic (1.3); no SSE endpoint (1.9); no folder watcher; no auth; no drops-root confinement; no ORM/SQLAlchemy/alembic; never modify `pull_transcript/`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Valid transcript-only drop | dir with `transcript.txt` + valid `metadata.json` | 201, `{jobId}`; job `queued`, 8 stage rows `queued` | N/A |
| Valid recording drop | dir with `recording.mp4` (+/- transcripts) | same as above | N/A |
| Neither recording nor transcript | only `metadata.json` | 422 problem+json; no rows | named violation in `detail` |
| Invalid metadata | missing/bad `sourceId`, `corpus`, `startedAt`, `provenance` | 422 problem+json; no rows | schema violation(s) listed |
| Path missing / not a dir / relative | bad `dropPath` | 400 problem+json; no rows | names the path problem |
| Duplicate sourceId | non-failed job exists | 409 problem+json conflict | existing `jobId` in body |
| Failed-job resubmit | only job for sourceId is `failed` | 200, same `jobId`; job + stages reset to `queued` | N/A |
| Unknown files in drop | extra `.md`, `.docx`, `_source.json` | ignored; drop accepted | N/A |
| GET unknown job | random UUID | 404 problem+json | N/A |
| GET queued job | fresh job id | 200: status, sourceId, dropPath, corpus, createdAt, stages[] (name/status per stage) | N/A |

</frozen-after-approval>

## Code Map

- `_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md` — AD-1 (drop contract, lines 170–174), AD-14 (intake, 248–252), AD-11 (jobs, 230–234), stage list (130–137), ERD `JOB ||--o{ JOB_STAGE` (366–367), conventions (270–277). Read-only authority.
- `server/config.py` — `load_config()`, `AppConfig`; Postgres at `settings.stores.postgres` (host/port 5433/db/user, `config.yaml:45-50`) + `secrets.postgres_password`; `_StrictModel` is `extra="forbid"`.
- `server/api/main.py` — module-level `_load_or_die()` fail-fast (`:27`), camelCase `ConfigDict(alias_generator=to_camel)` pattern (`:40-48`), `operation_id` convention (`:50`). No routers/lifespan yet — this story introduces both.
- `server/worker/main.py` — `_log()` JSON logging, idle loop; add migration check at startup only.
- `server/pyproject.toml` — deps + `[tool.hatch.build.targets.wheel].only-include` (`:24-32`): new top-level modules (`db.py`, `migrations/`) must be listed there.
- `server/tests/test_failfast.py` — subprocess fail-fast pattern (`_run()` helper) to extend for pending-migration boot failure.
- `server/tests/test_health.py` — TestClient + exact-JSON + OpenAPI-shape assertion patterns.
- `infra/docker-compose.yml:8-25` — postgres `pgvector/pgvector:pg18`, host port **5433**, db/user `meetingminer`.
- `infra/Makefile` — target layout; `test` at `:53`, `client` at `:169`.
- `pull_transcript/Boomi-Techstone Daily Standup/8.5.26/_source.json` — real provenance shape to embed in test fixtures (fields vary per file: `pulledAt` vs `migratedAt`). READ-ONLY.

## Tasks & Acceptance

**Execution:**
- [x] `docs/source-drop.schema.json` — JSON Schema (2020-12) for `metadata.json` + documented canonical filenames — the contract puller JS tests will also validate against.
- [x] `server/pyproject.toml` — add `psycopg[binary]`, `psycopg-pool`, `jsonschema`; extend wheel only-include.
- [x] `server/migrations/0001_jobs.sql` — `job` (uuidv7 pk, source_id, drop_path, corpus, status, error, timestamps; partial unique index on source_id where status != 'failed') + `job_stage` (job fk, name, status, error, timestamps; unique (job_id, name)).
- [x] `server/db.py` — pool from config; migration runner (`apply_migrations`, `pending_migrations`) with `schema_migrations` table.
- [x] `server/api/problems.py` — problem+json response helper + app-wide exception handlers (404/422/500).
- [x] `server/api/ingests.py` — router: drop validation (path checks, file-presence rule, `jsonschema` against the schema file) + job insert / conflict / failed-rerun logic.
- [x] `server/api/jobs.py` — router: `GET /jobs/{id}` camelCase payload with stages.
- [x] `server/api/main.py` — lifespan (pool open/close, refuse boot on pending migrations), include routers, register problem handlers.
- [x] `server/worker/main.py` — fail fast on pending migrations at startup; loop unchanged.
- [x] `infra/Makefile` — `migrate` target; wire into `up` before host processes start.
- [x] `server/tests/` — schema fixture tests (valid/invalid metadata incl. real-shaped provenance), intake + jobs endpoint tests against a `meetingminer_test` database (created per session, migrations applied fresh; skip with named reason if Postgres on 5433 is unreachable), problem+json handler tests, pending-migration fail-fast subprocess test.

**Acceptance Criteria:**
- Given the api is running and migrations applied, when a valid drop path is POSTed to `/ingests`, then a job row exists with 8 queued stage checkpoints and the response returns its id.
- Given the epics.md Story 1.2 ACs (schema exists; invalid drop → problem+json + no row; duplicate sourceId → conflict; unknown files ignored; `GET /jobs/{id}` returns status + checkpoints; drop contents untouched), when each is exercised, then it passes as written.
- Given `make client && pnpm --dir web run build`, when run against the live api, then the TS client regenerates with the new operations and type-checks clean.
- Given a fresh database, when `make migrate` runs twice, then the second run is a no-op.

## Spec Change Log

## Design Notes

- Stage checkpoints are pre-seeded at intake: all 8 stages (`probe frames ocr screens transcribe align moments extract`) inserted as `queued`, so `GET /jobs/{id}` is meaningful before the worker exists; 1.3's worker flips them (including `skipped` for transcript-only).
- Failed-job resubmit reuses the row (reset status/error, stages back to `queued`) to honor AD-14's "rerun of its existing job"; the partial unique index enforces one live job per sourceId at the DB level.
- Problem `type` URIs: `urn:meetingminer:problem:<slug>` (e.g. `invalid-drop`, `duplicate-source`, `not-found`).

## Verification

**Commands:**
- `uv run --project server pytest server/tests` — expected: all pass (DB tests run against compose Postgres; start it via `make infra-up` first).
- `make migrate && make migrate` — expected: exit 0 both times; second run reports nothing to apply.
- `make up`, then POST a fixture drop and GET the job — expected: 201 with `jobId`, then 200 with 8 queued stages.
- `curl -s localhost:8000/nonexistent` — expected: `application/problem+json` body, not `{"detail": ...}`.
- `make client && pnpm --dir web run build` — expected: regenerates, type-checks clean.

## Suggested Review Order

**Intake — the one door (AD-14)**

- Entry point: validate path → validate drop → conflict/re-queue/insert — the story's whole contract in one handler.
  [`ingests.py:187`](../../server/api/ingests.py#L187)

- Both UniqueViolation handlers turn lost races into 409s carrying the winner's real jobId — never a 500.
  [`ingests.py:215`](../../server/api/ingests.py#L215)

- Schema loaded once at import behind a named fatal — a missing contract file can't boot the api.
  [`ingests.py:33`](../../server/api/ingests.py#L33)

- FormatChecker makes `date-time` assertive, so impossible timestamps are rejected, not annotated.
  [`ingests.py:48`](../../server/api/ingests.py#L48)

**Drop contract (AD-1)**

- The versioned schema both api and puller tests validate against; provenance stays an open object.
  [`source-drop.schema.json:8`](../../docs/source-drop.schema.json#L8)

- `if/then` pins day-precision to T00:00:00 — contradictory precision/time pairs can't pass.
  [`source-drop.schema.json:65`](../../docs/source-drop.schema.json#L65)

**First database schema + migrations**

- `job` + `job_stage` with Postgres-minted uuidv7 and a partial unique index: one live job per sourceId.
  [`0001_jobs.sql:1`](../../server/migrations/0001_jobs.sql#L1)

- Advisory-locked, per-file-transactional runner; every failure is a named MigrationError.
  [`db.py:96`](../../server/db.py#L96)

- Boot gate shared by api and worker — pending migrations refuse startup, no silent drift.
  [`db.py:147`](../../server/db.py#L147)

- `make -j`-safe ordering: migrate waits for healthy stores via an order-only prerequisite.
  [`Makefile:64`](../../infra/Makefile#L64)

**RFC 9457 everywhere**

- One helper mints every error body; extension keys can't clobber RFC members.
  [`problems.py:66`](../../server/api/problems.py#L66)

- Handlers replace FastAPI's `{"detail": ...}` for 404/405/422/500; headers like `Allow` pass through.
  [`problems.py:127`](../../server/api/problems.py#L127)

**Process boundaries**

- Lifespan: pool open + migration gate; closes the pool before the fail-fast exit.
  [`main.py:39`](../../server/api/main.py#L39)

- Worker installs signal handlers before the DB gate, then fatals as structured JSON, never a traceback.
  [`main.py:62`](../../server/worker/main.py#L62)

- The stage list lives in `domain` — the only module both api and worker may import (api never imports pipeline).
  [`jobs.py:11`](../../server/domain/jobs.py#L11)

**Read model**

- `GET /jobs/{id}`: camelCase status + stages in canonical pipeline order.
  [`jobs.py:49`](../../server/api/jobs.py#L49)

**Peripherals**

- I/O matrix pinned end-to-end, including both race branches via a monkeypatched pre-check.
  [`test_ingests.py:1`](../../server/tests/test_ingests.py#L1)

- Schema fixtures use both real `_source.json` provenance shapes; a guard test keeps FormatChecker active.
  [`test_drop_schema.py:1`](../../server/tests/test_drop_schema.py#L1)

- Subprocess tests pin the fail-fast contract: pending migrations, unreachable DB, CLI idempotency, worker boot.
  [`test_migrations.py:1`](../../server/tests/test_migrations.py#L1)

- 500s are problem+json and don't leak exception messages.
  [`test_problems.py:1`](../../server/tests/test_problems.py#L1)
