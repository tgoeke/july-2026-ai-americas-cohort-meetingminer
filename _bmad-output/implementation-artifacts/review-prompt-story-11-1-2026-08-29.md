# Code review handoff — story 11-1 "Seconds-Fast Default Suite"

Hand this file, as is, to the `bmad-code-review` agent. It has none of the build run's context; everything it needs is here.

## 1. Required output — read this before touching any code

**Report path:** `_bmad-output/implementation-artifacts/review-story-11-1-2026-08-29.md`, written under the main checkout `/Users/devopsterus/current/cohort/meetingminer` (the worktree's `_bmad-output` is a symlink to the same directory).

**Finding structure** — one block per finding, in this order:
- **Location** — `path:line` in the worktree named below
- **Severity** — high / medium / low, by consequence for a builder running the suite
- **Finding** — what is wrong or missing, one paragraph
- **Evidence** — what you ran or read that shows it (command and real output, or the lines)
- **Suggested direction** — the shape of a fix, not the fix

**Report findings; do not fix.** Do not edit any file outside the report.

**REPORT-FIRST.** Before reading any code, create the report file as a skeleton — title, scope, the review range, an empty `## Findings` section — and save it. Append each finding as you confirm it and save after every one. A crashed or closed session must lose prose, never the artifact. Six reviews in this repository were produced only as terminal text because the file requirement sat at the end of a long prompt; that is why this section is first.

**Closeout.** `make check-reviews` does not exist at this revision (no `check-reviews:` target in `infra/Makefile` at `15fdbe2` or on `main`), and `_bmad-output/` is gitignored (`.gitignore:45`), so the report cannot be committed without changing the ignore rule — do not force-add it. Before reporting completion: confirm the report exists on disk (`test -f` + `wc -c`), state its path and size, and say explicitly that it is uncommitted because the directory is ignored. A review reported in the terminal but not filed does not exist.

## 2. Repository, branch, range

- Repo: `/Users/devopsterus/current/cohort/meetingminer` (main checkout — other agents work in it; do not edit it). Review from the story worktree `/Users/devopsterus/current/cohort/meetingminer-wt/11-1` (branch `story/11-1`, checked out there), or make your own: `git -C /Users/devopsterus/current/cohort/meetingminer worktree add --detach ../meetingminer-wt/11-1-review 15fdbe2`.
- Range: `e5510c7caf385720851b199382b62aa1221f4051..15fdbe2f430e59054a4e97698cf4641a9ef5cb54` (`git diff e5510c7..15fdbe2`; 35 files, +683/−140). `origin/story/11-1` is `15fdbe2`.
- Commits, oldest first:
  - `95ff6ee` test: move REPO_ROOT out of conftest into repo_paths
  - `c5a6464` test: collapse the two make runners in test_makefile_procs into one _make
  - `f7ea25c` test: default the server suite to the fast set with a measured slow mark
  - `9731532` test: fail an unmarked test whose call phase exceeds the fast-set budget
  - `7206dd5` make: test-fast iteration target; test and check-test-stores pass -m ""
  - `1e1fb98` docs: state the fast set, the full gate, the budget, and retire B-1
  - `d36aaa6` test: two blank lines after the budget hook in conftest
  - `5e8c25a` test: fast_budget plugin with pytester coverage of the budget's three behaviours
  - `668ba1c` test: contract tests for the -m "" recipes, test-fast, and pyproject's fast set
  - `0ecef76` test: fast_budget validates once, checks slow reasons and twin fixtures, hints on by-path runs
  - `eb31e47` test: contract tests parse addopts and pin the twelve slow modules; finish the _make collapse
  - `eb8bab4` make: test-fast runs check-client first; pin the fast-set count to a commit
  - `15fdbe2` docs: own section for the fast loop and full gate; hook lives in fast_budget.py
- Every commit in the range belongs to story 11-1. `main` is three commits ahead of the base (`5af6fbd` owner runbook, `f1d3ad9`/`ab07263` story 6.7 — `config.yaml`, `server/tests/test_extraction_core.py`, `docs/owner-runbook.md`); none of those paths is in this range, and they are not under review.

## 3. The spec

`_bmad-output/implementation-artifacts/spec-11-1-seconds-fast-default-suite.md`.
- **Frozen intent** (do not critique as the builder's choice): the `<intent-contract>` block — Intent, Boundaries & Constraints, I/O & Edge-Case Matrix. It was written from the story text in `_bmad-output/planning-artifacts/epics.md` ("Story 11.1", ~line 1707), the dispatch prompt `_bmad-output/implementation-artifacts/build-prompt-story-11-1-2026-08-29.md`, and backlog B-1 as it stood at `e5510c7` (`git show e5510c7:docs/backlog.md`, lines 14–37).
- **Planner work you may attack:** Code Map, Tasks & Acceptance, Design Notes, Review Triage Log, Auto Run Result, and the frontmatter `deferred` list.

## 4. Architecture authority

`docs/architecture.md`:
- **AD-4 — Projections have exactly one writer** (line 70) and the invariant **"Single writer per store class, proven not asserted"** (line 188): the test twins exist so suites can wipe stores; nothing in this change may add a store writer or bypass the projection lock. The new collection rule keys on the fixtures that reach the twins (`projection_stores`, `stores_up`).
- **AD-9 — Infrastructure in Docker, code on the host** (line 101): the shared compose stack and the two test twins the `slow` set is bound to.
- **AD-10 — One config file drives everything** (line 109) and **"Every threshold is configuration"** (line 200): the story keeps the budget and the marker selection as configuration (`server/pyproject.toml`), not code constants — but in the test tool's config, not `config.yaml`. Decide whether that placement is consistent with the decision's intent.
- `AGENTS.md`: "What worktrees do NOT isolate: the data stores" (unchanged mechanism, per-run Postgres + cross-worktree lock) and the new "## Fast loop and full gate" section this story adds.

## 5. Scope

**In scope (the whole range):**
- `server/pyproject.toml` — `addopts = "-m 'not slow' --strict-markers"`, `slow` marker, `mm_fast_test_budget_seconds = "2.0"` with rationale.
- `server/tests/fast_budget.py` (new plugin), `server/tests/conftest.py` (`pytest_plugins = ["pytester", "fast_budget"]`, `REPO_ROOT` import), `server/tests/repo_paths.py` (new).
- `server/tests/test_fast_budget.py` (new, 6 tests), `server/tests/test_compose_contract.py` (+18 contract tests).
- Module-level `slow` marks: `test_api_chat`, `test_api_search`, `test_augmentation`, `test_failfast`, `test_makefile_procs`, `test_migrations`, `test_parallel_store_safety`, `test_projections_graph`, `test_projections_locks`, `test_projections_rebuild`, `test_projections_search`, `test_projections_traversals`. Per-test marks: `test_api_events` (2), `test_artifact_publish` (1), `test_worker_extract` (1).
- `server/tests/test_makefile_procs.py` — one `_make` runner. `server/tests/test_parallel_store_safety.py` — child pytest passes `-m ""`.
- 13 modules touched only by the `REPO_ROOT` importer rewrite.
- `infra/Makefile` — `test-fast`, `-m ""` in `test:` and `check-test-stores`, `.PHONY`, `help`.
- `AGENTS.md`, `project-context.md` ("Running and verifying"), `docs/backlog.md` (B-1 retired into "Removed from this list").

**Out of scope:** story 11.2 (per-run store isolation, containers, the lock's behaviour); `server/meetingminer/**`, `web/`, `evals/`, `tools/`, `config.yaml`, migrations; the three deferred items in the spec frontmatter (README.md make-target table and testing section; a `docs/project-record.md` entry; filing the fixture-cost residue as a backlog item) — they are outside the story's file boundary and are recorded, not forgotten; the pre-existing Starlette `httpx` deprecation warning.

## 6. Design decisions to attack

Each is the choice plus the assumption it rests on. The planner is not a neutral judge of these.

1. **The `slow` set comes from measurement, not from B-1's list.** Twelve modules + four tests, criterion "duration set by something outside the test process" (store twins, spawned process, lock, timer). Assumes the story's "identify from the measurement, not from memory" and NFR19 ("seconds") license departing from B-1's seven modules, and that `test_mint_drop` (2.8s / 68 tests, on B-1's list) belongs in the fast set.
2. **The result is ~49s of pytest, not "a few seconds".** Assumes the residue (~1,000 Postgres-backed api/worker tests at 20–50ms) is fixture cost this story may not touch under "no test changes behaviour", and that saying so is better than marking Postgres-backed modules `slow`.
3. **Budget on the call phase only.** Assumes fixture cost amortises. It did not for function-scoped `projection_stores` (per-test wipe of both twins) — closed by the collection rule rather than by budgeting setup. Attack: are there other function-scoped expensive fixtures in the fast set (`client`, `truncate_evidence`, `synthetic_recording`) that the rule does not name?
4. **The rule keys on two fixture names** (`projection_stores`, `stores_up`) via `item.fixturenames` (transitive). Assumes those are the only paths to the twins from a test. Check `_rebuild_cli_uses_test_stores`, `projection_trigger`, `fake_embedder`, and any direct `neo4j`/`meilisearch` client construction in tests.
5. **The budget also runs under `make test` (`-m ""`).** Assumes 2.0s against a 1.3s measured maximum call leaves enough headroom for the concurrent suites AGENTS.md permits; the message now says to re-run alone before marking.
6. **The hook is a local plugin module registered through `pytest_plugins` in `server/tests/conftest.py`.** Assumes every invocation shape anchors under `server/tests` or runs from `server/` (dir, file, node id, the child pytest, `testpaths`). A bare `pytest` from the repo root now errors ("non-top-level conftest"); the docs call that shape unsupported.
7. **`-m ""` is the clearing mechanism** (not an env flag). Assumes the CLI expression replaces the `addopts` one (verified on pytest 9.1.1) and that every place that runs a `slow` node id passes it: `test:`, `check-test-stores`, the child pytest in `test_parallel_store_safety`. Attack: any other pytest invocation in the repo (`evals-run` runs `pytest evals/checks` from the repo root — different rootdir, so no `addopts`; confirm).
8. **`--strict-markers` on.** Assumes the only mark names in the tree are `parametrize`, `skipif`, `real_projection`, `slow`.
9. **Store-free suites are unconditional prerequisites of `test-fast`** (`check-client puller-test web-test evals-test`). Assumes their measured 1.7s / 0.7s / 12.7s stays true.
10. **Contract tests pin text**: Makefile recipe substrings, `tomllib` values, and the twelve module names for the module-level marks. Assumes text pins are the right guard where the behaviour is not cheaply observable, and that the pinned list is a deliberate second place to edit.
11. **`pytester` is enabled globally** through `pytest_plugins`. Assumes its fixtures and options have no effect on other tests.
12. **Counts appear only where pinned to a commit** (`f7ea25c` 1,358/1,683; `eb31e47` 1,381/1,707 — also the value at `15fdbe2`); AGENTS.md and project-context.md point at `--co` instead.
13. **The `REPO_ROOT` module still relies on `sys.path` insertion.** B-1's stated mechanism is unchanged; the symbol moved out of the plugin module, which is what the AC asked for.

## 7. History you need to tell a regression from a pre-existing condition

- The budget hook first landed in `conftest.py` (`9731532`) and moved into `server/tests/fast_budget.py` (`5e8c25a`) so it could be tested through `pytester`; the review pass (`0ecef76`..`15fdbe2`) added validation, the XPASS guard, the two collection rules, the by-path hint, `--strict-markers`, the module-mark pin, the finished `_make` collapse, and the docs section.
- The whitespace regressions at two `pytestmark` insertions (`MARKER =re.compile(`) were introduced in `f7ea25c` and fixed in `0ecef76`.
- A gate run at `d36aaa6` came back `1 failed, 14 errors` — `psycopg.errors.AdminShutdown` and a Meilisearch `RemoteDisconnected` in one contiguous block — because another agent recreated the shared Docker stack mid-run (every container `Up 5 minutes`, Postgres "ready to accept connections" at 13:49:18). The re-run was clean. Not a regression.
- The "1 warning" in every run is the pre-existing `StarletteDeprecationWarning` from `fastapi/testclient.py`, present in the baseline.
- `main` advanced by three commits during the build (story 6.7 + owner runbook); no path overlap; the branch has not been rebased.

## 8. Verification baseline (a skip or failure during review is a finding, not noise)

All measured by the coordinator from the worktree root with the stores up:
- Baseline at `e5510c7`: `MM_REQUIRE_TEST_STORES=1 uv run --project server pytest server/tests --durations=0 -q` → 1,683 passed, 554s (junit kept in the build session's scratchpad; not in the repo).
- `uv run --project server pytest server/tests --co -q | tail -1` → `1381/1707 tests collected (326 deselected)`; `-m ""` → `1707 tests collected`.
- `make test-fast` → rc 0, 66s wall; server step `1381 passed, 326 deselected, 1 warning in 48.91s`; puller `# tests 128`; web `257 passed`; evals `549 passed`.
- Twins unreachable (`MM_TEST_NEO4J_URI=bolt://127.0.0.1:1 MM_TEST_MEILI_URL=http://127.0.0.1:1`, server step) → `1381 passed, 326 deselected`, 0 SKIPPED lines — the fast set needs Postgres only.
- `make test` at `15fdbe2` → rc 0, 561s wall, `1707 passed`; per-test outcomes vs the baseline: 0 changed, 0 missing, 24 added (18 `test_compose_contract`, 6 `test_fast_budget`).
- `make check-test-stores` → `1 passed`. By-path `uv run --project server pytest -q server/tests/test_projections_locks.py` → `9 deselected`, rc 5, one yellow hint line. `uv run --project server pytest -m "" server/tests/test_makefile_procs.py -q` → `46 passed`.
- Throwaway probe through the real conftest (unmarked 2.5s sleeper): FAILED naming `mm_fast_test_budget_seconds`; a failing sleeper kept its assertion; a `slow`-marked sleeper passed under `-m ""` and was deselected by default.

Harness notes for the reviewer: run pytest from the repo root or worktree root (`./config.yaml` resolves relative to the cwd); if your shell sandbox denies `.env` reads or the `uv` cache, that is the sandbox, not the repo. Server suites may run concurrently (per-run Postgres, lock-queued projection tests); do not run `make evals-run`; do not restart the Docker stack while any suite is running.
