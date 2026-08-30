---
title: 'Rebuild crash recovery: one exclusion domain for the shared stores'
type: 'bugfix'
created: '2026-08-21'
status: 'done'
review_loop_iteration: 0
baseline_commit: '9bd75eee2982dd8a63e8c02f81e6138d295c5061'
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `make rebuild` (`rebuild --all`) crashed run-ending on a Neo4j `EntityNotFound` and left the shared retrieval stores nearly empty (Meilisearch moments 2/1811, Neo4j 8 nodes) while Postgres remains intact. Root cause: the Postgres advisory lock and the test suite's cross-worktree file lock are two disjoint exclusion mechanisms over the same shared Neo4j/Meilisearch containers, so a rebuild and another worktree's projection tests (or any process on a different Postgres database) race freely — producing torn Neo4j writes and mid-run index deletion.

**Approach:** Give every store-writing path one composed exclusion domain (file lock keyed by store URLs + existing advisory lock), make one meeting's graph projection atomic, make a raw Neo4j error a per-meeting failure instead of a run abort, document rebuild's single-flight rule, then recover the corpus with a clean rebuild.

## Boundaries & Constraints

**Always:** File lock acquired before advisory lock, in every server entrypoint that writes Neo4j/Meilisearch; lock paths and timeout env (`MM_PROJECTION_LOCK_TIMEOUT_SECONDS`) stay byte-compatible with the existing conftest scheme so old and new code contend on the same files. Lock timeout/refusal raises `ProjectionLockedError` naming the holder. Postgres is source of truth — never mutated beyond `meeting_projection` rows, as today.

**Ask First:** Any change to the worker pipeline beyond lock acquisition; any Postgres schema change; wiping any volume other than `meetingminer_neo4j-data`.

**Never:** No paid API calls (rebuild embeds via local Ollama only — keep it that way); no restart of the running worker; no `docker compose down -v` (takes Postgres with it); no redesign of `publish_gate.project_artifact` (latent unlocked path, no production caller — record in deferred-work, don't fix here); no Meilisearch "settle barrier" work (disproved: all tasks already awaited).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Rebuild vs test suite | Test suite holds file lock | Rebuild blocks up to timeout, then named refusal | `ProjectionLockedError` names holder file/JSON |
| Worker vs rebuild | Rebuild holds both locks | Worker projection refused by name (as today) | existing advisory refusal |
| Meeting fails in `--all` | One meeting raises `neo4j.exceptions.Neo4jError` | Recorded in `report.failures`; loop continues; exit code nonzero | per-meeting rollback, no run abort |
| Concurrent delete mid-projection | Impossible once locks compose | One tx per meeting: all-or-nothing graph write | tx rollback on error |

</frozen-after-approval>

## Code Map

- `server/meetingminer/projections/stores.py` — `projection_lock` (:414-449, advisory, try-lock + named holder), `drop_all` (:363), `ensure_search_schema` (:326, every task awaited via `await_task` :165)
- `server/meetingminer/projections/__init__.py` — four locked entrypoints: `project_meeting` :480/:498, `project_meeting_embeddings` :512/:525, `unproject_meeting` :542/:551, `rebuild` :617/:710; rebuild per-meeting `except (ProjectionError, EmbedderError, LookupError)` :774 (misses `Neo4jError` — the run-ending gap); `full_wipe` branch :735-747
- `server/meetingminer/projections/graph.py` — `project_meeting` :370-388 (auto-commit sequence, torn-write site), `_write_moments` COVERS statement :323 (crash site), `delete_meeting` :59 (batched loop — still terminates inside one tx)
- `server/tests/conftest.py` — `_projection_lock_paths` :982 (sha256 of `neo4j.uri|meilisearch.url` in tempdir), `_projection_lock_timeout_seconds` :992, `_projection_store_lock` :1027, `projection_stores` :1067 — the file-lock-only store wiper; reuse, don't duplicate
- `server/tests/test_projections_rebuild.py` :284 — `test_a_rebuild_racing_a_held_lock_is_a_named_refusal`, the test style to copy
- `infra/Makefile` — `rebuild:` :752-756; help text :119-126 (no single-flight mention); compose neo4j volumes `neo4j-data`/`neo4j-logs` (`infra/docker-compose.yml:31-41,69-73`)
- `AGENTS.md` :69-111 — shared-store section; `rebuild` never mentioned
- `_bmad-output/implementation-artifacts/deferred-work.md` — append publish_gate latent-bypass entry

## Tasks & Acceptance

**Execution:**
- [x] `server/meetingminer/projections/locks.py` (new) — extract the cross-process file lock from conftest (same path derivation, holder JSON, timeout env) as `store_file_lock(config, *, holder)` context manager raising `ProjectionLockedError` on timeout — one implementation for server and tests
- [x] `server/meetingminer/projections/__init__.py` — wrap all four store-writing entrypoints: file lock first, then `projection_lock`; add `neo4j.exceptions.Neo4jError` to rebuild's per-meeting except so a graph error is a recorded failure, not a run abort
- [x] `server/tests/conftest.py` — delegate `_projection_store_lock` to `projections.locks` (identical paths/behavior; delete the duplicated body)
- [x] `server/meetingminer/projections/graph.py` — run `project_meeting`'s delete+write sequence in one explicit transaction (`session.begin_transaction()`), keeping `_BATCH`-sized statements within it; `unproject_meeting` likewise
- [x] `server/tests/` — tests: entrypoint refused by name while file lock held; rebuild records a `Neo4jError` meeting as failure and continues; import-inspection single-writer test still passes
- [x] `AGENTS.md` + `infra/Makefile` help — state `make rebuild` is single-flight across every worktree sharing the stores
- [x] `_bmad-output/implementation-artifacts/deferred-work.md` — append `publish_gate.project_artifact` unlocked-write entry
- [x] Recovery (after fix, in order): rerun `make rebuild` once; if the same node crash reproduces → stop neo4j service only, `docker volume rm meetingminer_neo4j-data`, bring it up, `make rebuild` again; verify counts

**Acceptance Criteria:**
- Given another process holds the store file lock, when any projection entrypoint runs, then it is refused/blocked with a named `ProjectionLockedError`, never a torn write
- Given one meeting raises a raw `neo4j.exceptions.ClientError` during `rebuild --all`, when the loop reaches it, then it lands in `report.failures` and every other meeting still projects
- Given the recovery rebuild completes, when stores are inspected, then Meilisearch `moments` ≈ Postgres `moment` count (1811 ± skipped/failed named in the report), `chunks` > 0, Neo4j node count in the thousands, `artifacts` index untouched

## Spec Change Log

## Verification

**Commands:**
- `uv run --project server pytest server/tests/test_projections_rebuild.py server/tests/test_projections_graph.py server/tests/test_projections_single_writer.py` — expected: pass (queues on the shared file lock if contended)
- `make rebuild` — expected: exit 0, report names any skipped meetings; note its `migrate` dependency touches the shared dev DB
- Store counts post-rebuild via Meilisearch `/indexes/*/stats` and Neo4j `MATCH (n) RETURN count(n)` — expected: AC thresholds above

## Suggested Review Order

**One exclusion domain: the shared store file lock**

- Entry point — the extracted cross-worktree lock; same paths as conftest, so old code contends too
  [`locks.py:177`](../../server/meetingminer/projections/locks.py#L177)

- Atomic acquire-or-join under one mutex; flock released on any failure before registration
  [`locks.py:123`](../../server/meetingminer/projections/locks.py#L123)

- Release fires exactly when process-wide depth hits zero, regardless of exit order
  [`locks.py:159`](../../server/meetingminer/projections/locks.py#L159)

**Entrypoints compose both locks, file lock first**

- All four store writers: file lock gates cross-worktree, advisory lock gates same-database
  [`__init__.py:505`](../../server/meetingminer/projections/__init__.py#L505)

- Rebuild's whole run under both locks; per-meeting except now covers Neo4jError and MeilisearchError
  [`__init__.py:719`](../../server/meetingminer/projections/__init__.py#L719)

**Per-meeting graph write is all-or-nothing**

- Delete+rewrite in one explicit transaction — a torn write can no longer dangle nodes
  [`graph.py:387`](../../server/meetingminer/projections/graph.py#L387)

- Helpers retargeted from Session to Transaction; batches bound round-trips, not tx scope
  [`graph.py:61`](../../server/meetingminer/projections/graph.py#L61)

**Tests, then docs**

- Refused rebuild touched neither store nor the advisory lock — pins ordering and no-contact
  [`test_projections_locks.py:202`](../../server/tests/test_projections_locks.py#L202)

- Mid-transaction failure rolls the whole meeting back, first-time and re-projection
  [`test_projections_graph.py:428`](../../server/tests/test_projections_graph.py#L428)

- A raw Neo4j error is a recorded failure, not a run abort
  [`test_projections_rebuild.py:282`](../../server/tests/test_projections_rebuild.py#L282)

- Conftest now delegates to the shared lock; byte-compat pinned by test
  [`test_projections_locks.py:49`](../../server/tests/test_projections_locks.py#L49)

- Single-flight rule documented for every worktree
  [`AGENTS.md:93`](../../AGENTS.md#L93)
