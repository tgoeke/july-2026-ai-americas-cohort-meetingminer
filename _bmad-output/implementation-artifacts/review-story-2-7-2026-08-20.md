# Code review — Story 2.7: Parallel-Safe Store-Backed Tests

- **Range reviewed:** `945238208e8af286b213fc126c1e35b28b9846d1..141dc3934c940e32b5df0a8b8a362a8ea73b8145` on `story/2-7-parallel-safe-store-backed-tests`
- **Contract:** the Story 2.7 entry in `deferred-work.md`, the `DISPATCH RULE` in `sprint-status.yaml`, and AD-4. No frozen story spec exists.
- **Layers:** Blind Hunter, Edge Case Hunter, Verification Gap Reviewer. Acceptance Auditor skipped: no spec file.
- **Result:** **does not pass review.** The core two-process check succeeds, but the advertised pruner can delete an active suite's database; cleanup and operating-contract gaps remain.

## Findings

### 1. High — `test-db-prune` can drop a live suite's database

**Location:** `infra/Makefile:350-355`
**Caused by this change:** yes.

The candidate query decides that a database is idle from `pg_stat_activity`, then drops it separately. A run has no backend after `CREATE DATABASE` and before it opens the migration/pool connection. Pruning in that interval deletes the still-starting run's database; its next connection fails.

This was reproduced during this review: while `pytest server/tests -q` was active, `make test-db-prune` reported and dropped `meetingminer_test_12e6940ef9a4`. The target and AGENTS.md promise that pruning is safe while another suite runs. The fix must give a test run durable ownership that pruning can observe for the fixture lifetime; a no-backend snapshot is insufficient.

### 2. Medium — setup failures bypass the new per-run cleanup

**Locations:** `server/tests/conftest.py:153-158`; `server/tests/test_migrations.py:258-262`
**Caused by this change:** yes.

`test_database` creates its database and applies migrations before entering `try/finally`. A migration/assertion failure therefore leaks it. The CLI migration test creates `CLI_DATABASE` before `_write_config()` and before registering its finalizer, so a config-write/symlink failure leaks that database too. Unique names accumulate those setup leaks rather than self-overwriting. Register cleanup before fallible setup or guard the whole post-create path, with regression coverage.

### 3. Medium — a hung lock holder makes every concurrent suite hang indefinitely

**Location:** `server/tests/conftest.py:776-782`
**Caused by this change:** yes.

`flock` waits without a timeout or holder diagnostic. Process death releases it, but a live pytest process hung in a store call retains it forever and every other suite blocks silently. There is no suite-level timeout. Preserve serialization, but give unattended runs bounded, diagnosable waiting behavior or an equivalent reliable escape hatch.

### 4. Medium — the concurrency guarantee has no automated regression test

**Locations:** `server/tests/conftest.py:50-58`, `server/tests/conftest.py:756-811`, `server/tests/test_migrations.py:28-31`
**Caused by this change:** yes.

No committed test proves two interpreter processes receive distinct database names, retain them through setup/teardown, or that a second projection fixture cannot enter the wipe/schema section while the first holds the lock. Making `RUN_ID` constant or moving the lock outside the fixture would leave ordinary one-process tests green and restore the original failure. Add focused process-level regression coverage, first confirmed to fail against the unfixed implementation.

### 5. Medium — repository operating instructions still prohibit the capability this story adds

**Locations:** `infra/Makefile:106-108`; `docs/agent-kickoff-prompt.md:34-39`; `CLAUDE.md:14-15`
**Caused by this change:** yes, by omission.

These entry points still say the database is fixed/shared and only one agent may run store-backed suites. The kickoff prompt specifically governs agents that do not read AGENTS.md, so it continues to serialize the work Story 2.7 should unblock. Align all three: server suites may overlap; projection tests queue; `make evals-run` remains serial.

### 6. Medium — the live tracker requires a Meilisearch prefix that AD-4 forbids

**Location:** `_bmad-output/implementation-artifacts/sprint-status.yaml:123-126`
**Caused by this change:** pre-existing contract contradiction; the reviewed code correctly uses locking instead.

The tracker says Story 2.7 supplies per-run Meilisearch index prefixes. AD-4 fixes index names, and the implementation serializes projection tests. Amend the tracker/deferred-work contract to record the settled approach: per-run Postgres isolation plus a shared projection lock. An index-prefix alternative requires an explicit AD-4 amendment.

## Decisions examined and defensible as built

- A temp-dir lock rather than a repo lock correctly spans worktrees in the normal shared host temp realm; its endpoint tuple has the intended configured-stack granularity.
- `open(..., "w")` has a latent inode-replacement risk, but no current code deletes or recreates the lock file.
- Direct driver/client creation occurs only in the read-only availability check and `projection_stores`; the specifically named compose/config/single-writer tests are static. Current live projection tests therefore use the lock.

## Verification

- `git diff --check 9452382..HEAD` — clean.
- Two concurrent runs of `test_migrations.py`, `test_projections_graph.py`, `test_projections_search.py`, and `test_ingests.py` — **88 passed each** in 134.41 seconds; projections serialized as designed.
- No per-run databases remained after that check; `make test-db-prune` then reported `pruned 0 database(s)`.
- A full `pytest server/tests -q` review run is **not counted as passing**: the observed prune race deleted its active database, invalidating that run.
