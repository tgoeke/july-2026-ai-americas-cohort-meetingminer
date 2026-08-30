# Code re-review — Story 11-1: Seconds-Fast Default Suite

Date: 2026-08-29

## Scope

- Repository: `/Users/devopsterus/current/cohort/meetingminer`
- Review worktree: `/Users/devopsterus/current/cohort/meetingminer-wt/11-1-review`
- Branch: `story/11-1-review`
- Reviewed range: `183bdf175288d74350e7147fc7134bcce9fb126e..31ff5392dc6d28d4b9e116efc6b759d37d2b8521`
- Specification: `_bmad-output/implementation-artifacts/spec-11-1-seconds-fast-default-suite.md`
- Mode: full re-review

## Verdict

**Changes requested.** All ten original findings are verified fixed, but this re-review found three new medium-severity verification/enforcement gaps. Story 11-1 remains in progress and must not merge until they are remediated and re-reviewed.

## Findings

### 1. `test-fast` can silently lose one of its promised prerequisite suites

- **Location:** `server/tests/test_compose_contract.py:200`
- **Severity:** medium
- **Finding:** The `test-fast` contract proves only the server pytest argv. Nothing pins the target's promised `check-client`, `puller-test`, `web-test`, and `evals-test` prerequisites.
- **Evidence:** `rg -n "test-fast" server/tests` finds only `test_make_test_fast_runs_the_whole_server_fast_set`, whose assertions at lines 200–209 inspect the server command. The only prerequisite-composition test is `test_test_target_runs_the_puller_suite` in `test_makefile_procs.py:1113`, and it covers `test:`, not `test-fast:`. Deleting `web-test` (or another prerequisite) from `infra/Makefile:294` leaves every current Story 11-1 contract green while `make test-fast` stops exercising that suite.
- **Suggested direction:** Add a Make contract that derives the effective `test-fast` prerequisite/command sequence and requires `check-client`, `puller-test`, `web-test`, and `evals-test` before the whole-server fast pytest command. Confirm the regression fails when any promised prerequisite is removed.

### 2. Function-level slow marks can grow without changing the exact-set contract

- **Location:** `server/tests/test_compose_contract.py:280`
- **Severity:** medium
- **Finding:** The AST-derived exact-set guard inventories only module-level `pytestmark` assignments. The four production function-level slow marks are outside every exact inventory, so adding an arbitrary fifth `@pytest.mark.slow(reason=...)` silently removes a fast test from the default suite while all existing contracts remain green.
- **Evidence:** `_has_module_level_slow_mark` at lines 293–309 visits only top-level assignments named `pytestmark`; `test_the_module_level_slow_set_is_exactly_the_measured_twelve` at lines 311–318 compares only module stems. Production function-level marks currently exist at `test_api_events.py:434`, `test_api_events.py:455`, `test_artifact_publish.py:414`, and `test_worker_extract.py:1164`. The collection rule accepts any additional function-level mark with a non-empty reason, and the runtime budget exempts it, so neither backstop detects this shrinkage.
- **Suggested direction:** Add an exact, syntax-derived inventory of the four production function-level slow node ids (separate from pytester probe strings), compared both ways. Confirm a deliberate extra decorator makes the contract fail.

### 3. Dynamic twin-fixture requests bypass the collection invariant

- **Location:** `server/tests/fast_budget.py:88`
- **Severity:** medium
- **Finding:** The collection rule examines `item.fixturenames`, which contains the statically known fixture closure but not a fixture obtained dynamically with `request.getfixturevalue("projection_stores")` or `request.getfixturevalue("stores_up")`. An unmarked test can therefore enter the default fast set and acquire/wipe the twins despite the stated invariant that every twin-bound test is slow.
- **Evidence:** The guard at lines 86–90 intersects `_TWIN_FIXTURES` only with `item.fixturenames`; repository search currently finds no production `getfixturevalue` use, so this is a reachable future regression rather than a present misclassified node. A pytester probe whose unmarked test calls `request.getfixturevalue("projection_stores")` would pass collection under the current plugin and execute the twin fixture.
- **Suggested direction:** Enforce the same rule when either named fixture is set up dynamically (while retaining the collection-time diagnostic for static requests), and add a pytester regression that demonstrates the unfixed plugin reaches the dynamic fixture before the fix.

### Layer triage

- Active layers: blind hunter, edge-case hunter, verification-gap reviewer, acceptance auditor.
- Result: 3 patch findings, 0 decision-needed, 0 deferred, 9 normalized claims dismissed as by-design, explicitly amended/deferred, or non-actionable noise.
- Dismissed themes: the spec deliberately budgets call phase rather than fixtures or timeouts; Postgres-down skips and module-level marking are frozen choices; current reasons all contain source and measurement; `PYTEST_ADDOPTS` is an explicit operator override; the `--deselect` hint edge does not invalidate the required `-m ""` guidance; the residual 49-second fixture cost is already an owner-deferred item.

## Original findings verification

1. **Verified fixed.** `uv run --project server pytest -q server/tests/test_fast_budget.py::test_the_real_session_loads_fast_budget_from_conftest -o mm_fast_test_budget_seconds=3.0` passed (1 passed in 0.03s); the real session accepted and exposed the override.
2. **Verified fixed.** `uv run --project server pytest -q server/tests/test_config.py -k __no_such__` exited 5 with 55 deselected and no hint, while `uv run --project server pytest -q server/tests/test_projections_locks.py` exited 5 with 9 deselected and exactly the `-m ""` slow-module hint.
3. **Verified fixed.** The 41-test command passed `test_make_test_runs_the_server_suite_with_the_marker_filter_cleared`; an independent `make -n -C infra test` showed the effective server argv ending in `pytest -m "" <worktree>/server/tests` with `MM_REQUIRE_TEST_STORES=1`. `make check-test-stores` also passed its real slow-module node (1 passed in 0.07s).
4. **Verified fixed.** The 41-test command passed `test_make_test_fast_runs_the_whole_server_fast_set`; independent `make -n -C infra test-fast` showed the sole server command using the exact `server/tests` root, `-q -rs`, the server project, and no command-line `-m`.
5. **Verified fixed.** The 41-test command passed `test_the_module_level_slow_set_is_exactly_the_measured_twelve`; inspection confirms it parses each `test_*.py` with `ast`, recognizes assignment/list/tuple forms, and compares the derived set for exact equality with `SLOW_MODULES`.
6. **Verified fixed.** The 41-test command exercised `abc`, `nan`, `inf`, `0`, and `-1` as usage errors naming the key/value and accepted `3.5`; the separate real-session command also accepted `3.0`.
7. **Verified fixed.** The 41-test command passed `test_a_non_strict_xfail_that_passes_over_budget_keeps_its_xpass`; the plugin exempts reports carrying `wasxfail` before applying the budget failure.
8. **Verified fixed.** The 41-test command passed both parametrizations of `test_a_slow_mark_without_a_reason_stops_collection` (`cli` and `addopts`), which require a usage error naming the offending node id.
9. **Verified fixed.** The spec's 2026-08-29 change log explicitly limits outcome equality to pre-`e5510c7` node ids, permits the named regression tests, and revision-pins totals. Collection independently reports `1382/1708 (326 deselected)` by default and `1708` with `-m ""`; no test file is deleted from `e5510c7..31ff539`, and no server test/config file changed after count-pin commit `722e521`.
10. **Verified fixed.** `infra/Makefile:94,286-292`, `AGENTS.md:158-165`, and `project-context.md:72-78` consistently state that Postgres-backed fast tests skip with reasons, twin-bound tests are deselected, and `make test` requires the twins.

## Verification log

- `uv run --project server pytest -q server/tests/test_fast_budget.py server/tests/test_compose_contract.py -m ""` — PASS: 41 passed, 1 pre-existing Starlette deprecation warning, 2.82s pytest time.
- Real-session override and hint paths — PASS with the exit codes and output recorded under original findings 1–2.
- Collection — PASS: default `1382/1708 tests collected (326 deselected)`; `-m ""` collected all 1708.
- Make dry-run argv and live `make check-test-stores` — PASS; effective commands match the contracts and the store check ran 1 test successfully.
- `time make test-fast` — PASS: puller 128, web 257, eval harness 549, server 1382 passed / 326 deselected / 1 pre-existing warning in 47.61s; target completed in 1m03.69s wall.
- `time make test` — PASS: puller 128, web 257, eval harness 549, test-store reachability 1, full server 1708 passed / 1 pre-existing warning in 537.30s, and the web production build completed; target completed in 9m17.05s wall.
- Baseline node-id comparison — PASS: parsed the preserved `e5510c7` JUnit (1683 nodes) and compared it with the branch's full `-m "" --co -q` collection (1708 nodes): 0 missing, 25 added. Because both the baseline JUnit and this review's full gate contain only passes, outcomes changed on 0 pre-existing node ids. Added nodes are 16 in `test_fast_budget.py`, 8 in `test_compose_contract.py`, and 1 from `test_extraction_core.py` on the rebased main baseline.
- Branch hygiene — PASS: `story/11-1-review` and `origin/story/11-1-review` both resolve to `31ff5392dc6d`; the review worktree is clean.
- `make check-reviews` from the main checkout — PASS: every dispatched review has a report on disk; the checker reports that 42 reports are gitignored, so commit status cannot be checked.

## Closeout

- Review result: changes requested (3 new medium patch findings).
- Story/spec status intentionally left `in-review`; sprint status intentionally left `in-progress` (`11-1-seconds-fast-default-suite: in-progress`).
- No merge performed because must-fix findings remain.
- Per the re-review handoff, no code, spec, sprint-status, or deferred-work file was edited. This report is the only changed artifact.
- The report is ignored by `.gitignore` and therefore remains uncommitted as instructed; it was not force-added.
