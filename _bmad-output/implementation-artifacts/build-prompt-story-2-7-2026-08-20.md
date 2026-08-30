# Builder handoff — Story 2.7 review remediation

## Review record

- **Repository / branch:** `meetingminer`, `story/2-7-parallel-safe-store-backed-tests`
- **Reviewed implementation range:** `945238208e8af286b213fc126c1e35b28b9846d1..141dc3934c940e32b5df0a8b8a362a8ea73b8145`
- **Review artifact:** `_bmad-output/implementation-artifacts/review-story-2-7-2026-08-20.md`
- **Branch movement:** this artifact and handoff are review commits after the reviewed tip. Rebase remediation onto current `main` before merging.

## Outcome

Story 2.7 **does not pass review**. Fix, commit, push, and return it for re-review.

## Fix now

1. **Make pruning safe:** `infra/Makefile:350-355` can drop a suite that has created but not yet connected to its test database. The review reproduced this by dropping `meetingminer_test_12e6940ef9a4` from a live suite. Establish durable run ownership that pruning observes for the fixture lifetime; preserve cleanup of abandoned databases.
2. **Guarantee teardown after creation:** `server/tests/conftest.py:153-158` and `server/tests/test_migrations.py:258-262` create unique databases before their cleanup guard is active. Every created test database needs cleanup even when subsequent migration/config setup fails.
3. **Bound and diagnose projection-lock waits:** `server/tests/conftest.py:776-782` blocks forever. Preserve serialization but make an unattended hang bounded and diagnosable.
4. **Add discriminating regression tests:** cover distinct cross-process database ownership, projection-lock exclusion, and prune safety during a starting suite. Each new test must be demonstrated against the unfixed code first.
5. **Synchronize operating instructions:** update `infra/Makefile:106-108`, `docs/agent-kickoff-prompt.md:34-39`, and `CLAUDE.md:14-15` to say server suites can overlap, projection tests queue, and `make evals-run` remains serial.

## Contract amendment required

Amend `sprint-status.yaml:123-126` and the Story 2.7 deferred-work contract: they call for a per-run Meilisearch prefix that AD-4 forbids. The settled design is per-run Postgres names plus a shared projection lock. Do not add an index prefix without an AD-4 amendment.

## Verification

- `make infra-up`
- `server/.venv/bin/python -m pytest server/tests -q`
- Run two simultaneous pytest commands over `test_migrations.py`, `test_projections_graph.py`, `test_projections_search.py`, and `test_ingests.py`; both must exit 0.
- `make test-db-prune` only after suites finish, then confirm no `meetingminer_test%` databases remain.
- Run all new regression coverage and show that each test fails on the unfixed implementation.

## Out of scope

- No Meilisearch index prefix without an AD-4 amendment.
- No per-run Neo4j Community database design.
- No general application/rebuild locking redesign.
