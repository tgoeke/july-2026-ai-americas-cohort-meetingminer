---
title: 'Story 2.7 remediation: Safe Parallel Test Ownership'
type: 'bugfix'
created: '2026-08-19'
status: 'done'
review_loop_iteration: 0
baseline_commit: 'dcef015b2e9d4d9d647b0d392b8fdc0457c1a0cf'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/review-story-2-7-2026-08-20.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Story 2.7 gave concurrent server suites distinct Postgres databases and serialized the shared projection stores, but its cleanup command can still delete a newly starting live suite's database. Setup failures can leak per-run databases, a stuck projection holder leaves every waiter opaque and unbounded, and the operational contract is contradictory or stale.

**Approach:** Make a PostgreSQL session advisory lock the durable ownership record for every per-run test database and require pruning to obtain that same lock before dropping. Make projection-lock waiting bounded and diagnostic, protect both mechanisms with focused regression tests, and synchronize the documentation and Story 2.7 contract with the settled AD-4-compatible design.

## Boundaries & Constraints

**Always:** Acquire a database-owner lock before creating, dropping, or migrating each `meetingminer_test*` database and retain it through teardown; a killed process must release ownership automatically. Pruning must skip an owned database even when it has no backend, but remove an unowned idle database. Postgres remains the only per-run namespace. Projection tests retain one cross-worktree temp-file lock keyed to the configured Neo4j and Meilisearch endpoints; a wait must end with a useful diagnostic rather than an unbounded hang. All test setup paths clean up after themselves. Keep the existing 88-test concurrency command valid.

**Ask First:** Halt if this work requires a Meilisearch index prefix, a per-run Neo4j database, or a broader application/rebuild locking redesign.

**Never:** Do not amend AD-4, alter production projection write behavior, weaken projection serialization, remove cleanup of abandoned databases, or introduce a general test-runner dependency solely for timeouts.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
| --- | --- | --- | --- |
| Active suite during prune | A fixture owns a created database but has not opened a target-DB backend | Prune skips it; the suite can migrate and complete | Ownership lock is released during fixture teardown or process death |
| Abandoned database | Per-run database has no backend or owner | Prune drops it | Continue scanning other candidates if one candidate cannot be dropped |
| Setup failure | Create succeeded; migration/config setup later fails | Database is removed before pytest reports the setup error | Cleanup failure is observable without masking the primary failure |
| Stuck projection holder | Another process holds the shared file lock past the configured wait | Waiting fixture fails with lock path, elapsed wait, and holder metadata | Later runs acquire normally after holder exit/release |

</frozen-after-approval>

## Code Map

- `server/tests/conftest.py` — owns `RUN_ID`, the session test database, shared test fixtures, and `_projection_store_lock`; add the common database-owner-lock helper and bounded file-lock behavior here.
- `server/tests/test_migrations.py` — owns pending and CLI per-run databases; consume the same ownership helper so their creation gaps cannot be pruned.
- `infra/Makefile` — `PRUNE_TEST_DBS` finds/drops leaked databases; require the advisory lock before each destructive action and report skips/failures accurately.
- `server/meetingminer/db.py`, `server/meetingminer/worker/main.py`, `server/meetingminer/projections/stores.py` — read-only pattern references for session-scoped Postgres advisory locks and holder diagnostics; do not change production behavior.
- `server/tests/test_parallel_store_safety.py` — new focused store-backed/process regression coverage for database ownership/pruning and file-lock exclusion/timeout.
- `AGENTS.md`, `CLAUDE.md`, `docs/agent-kickoff-prompt.md`, `infra/Makefile` help — operating instructions that must describe the settled server-suite/evals-run limits consistently.
- `_bmad-output/implementation-artifacts/deferred-work.md`, `_bmad-output/implementation-artifacts/sprint-status.yaml` — correct the stale Meilisearch-prefix contract to the lock-based AD-4-compatible design.

## Tasks & Acceptance

**Execution:**

- [x] `server/tests/conftest.py` and `server/tests/test_migrations.py` -- establish and use a shared, namespaced session advisory-lock ownership helper before every per-run database lifecycle; cleanup guards start before any fallible setup.
- [x] `infra/Makefile` -- have `test-db-prune` acquire each candidate's owner lock before dropping, skip owned candidates, safely quote identifiers, and continue after an individual prune failure.
- [x] `server/tests/conftest.py` -- make projection-lock acquisition nonblocking/retried to a bounded test-configurable deadline; record holder metadata only while holding the lock and include it in timeout diagnostics.
- [x] `server/tests/test_parallel_store_safety.py` -- add discriminating process-level regression coverage for owner-lock pruning and projection lock exclusion, timeout, and release; demonstrate each test against the unfixed behavior first.
- [x] `AGENTS.md`, `CLAUDE.md`, `docs/agent-kickoff-prompt.md`, `infra/Makefile`, `deferred-work.md`, `sprint-status.yaml` -- align operational and contract wording with per-run Postgres, serialized projections, bounded waits, and serial eval runs.

**Acceptance Criteria:**

- Given a test run that owns a newly created database with no target backend, when `make test-db-prune` runs, then that database remains available and a separate abandoned per-run database is removed.
- Given migration or temporary-config setup fails after database creation, when pytest unwinds the fixture, then no corresponding per-run database remains.
- Given one process holds the projection lock past the configured deadline, when another process requests the fixture, then it fails within that bound and names the holder/path; after release, a new requester succeeds.
- Given two concurrent prescribed test processes, when they run migrations, graph, search, and ingest tests, then both exit successfully without leaked test databases.
- Given an agent follows any documented entry point, when it reads the parallel-test rule, then it receives the same AD-4-compatible operating guidance.

## Design Notes

The owner lock is acquired on a dedicated connection to the maintenance database before `CREATE DATABASE`; it is session scoped, so a killed suite releases it automatically. The pruner first obtains the same candidate-specific lock, preventing a check-to-drop race without turning a no-backend snapshot into an ownership decision. This reuses the project's established Postgres advisory-lock model rather than introducing a second filesystem registry.

The projection lock remains a filesystem lock because Neo4j and Meilisearch are shared derived stores across worktrees. Its lock file remains outside the repository; only liveness and diagnostics change.

## Verification

**Commands:**

- `make infra-up` -- expected: all three stores healthy.
- `server/.venv/bin/python -m pytest server/tests/test_parallel_store_safety.py server/tests/test_migrations.py -q` -- expected: new ownership, cleanup, and lock regressions pass.
- `server/.venv/bin/python -m pytest server/tests -q` -- expected: complete server suite passes.
- Run two concurrent pytest commands over `server/tests/test_migrations.py server/tests/test_projections_graph.py server/tests/test_projections_search.py server/tests/test_ingests.py` -- expected: both exit 0.
- `make test-db-prune` after all test processes exit, followed by a `pg_database` query for `meetingminer_test%` -- expected: zero leaked databases.

## Suggested Review Order

**Durable Postgres ownership**

- Start with the common lock identity and lifecycle helpers.
  [`conftest.py:76`](../../server/tests/conftest.py#L76)

- Confirm session fixtures acquire ownership before every fallible database setup.
  [`conftest.py:208`](../../server/tests/conftest.py#L208)

- Verify pruning obtains that same lock before destructive work.
  [`Makefile:351`](../../infra/Makefile#L351)

**Bounded shared projections**

- Validate finite timeout parsing and holder diagnostic metadata.
  [`conftest.py:831`](../../server/tests/conftest.py#L831)

- Follow the nonblocking acquisition and release path used by the fixture.
  [`conftest.py:870`](../../server/tests/conftest.py#L870)

**Regression proof and operations**

- Read the process-level tests that reproduce pruning and lock edge cases.
  [`test_parallel_store_safety.py:32`](../../server/tests/test_parallel_store_safety.py#L32)

- Confirm the documented concurrent-suite and serial-eval operating rule.
  [`AGENTS.md:75`](../../AGENTS.md#L75)

- Check the tracker records the AD-4-compatible settled design.
  [`sprint-status.yaml:123`](sprint-status.yaml#L123)
