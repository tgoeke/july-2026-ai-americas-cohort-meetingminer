# Re-review handoff — story 11-1 "Seconds-Fast Default Suite" after remediation

Hand this file, as is, to the `bmad-code-review` agent. It has none of the build run's context; everything it needs is here. This is a **re-review**: the first review (`_bmad-output/implementation-artifacts/review-story-11-1-2026-08-29.md`) found 10 items; all 10 were remediated on the rebased branch. Verify each remediation, then review the remediation commits as new code.

## 1. Required output — read this before touching any code

**Report path:** `_bmad-output/implementation-artifacts/review-story-11-1-rereview-2026-08-29.md`, under the main checkout `/Users/devopsterus/current/cohort/meetingminer`.

**Finding structure** — one block per finding: **Location** (`path:line` in the worktree named below) / **Severity** (high, medium, low — by consequence for a builder running the suite) / **Finding** / **Evidence** (command and real output, or the lines) / **Suggested direction**. Plus one block per original finding 1–10 stating **verified fixed** or **still open**, with the command you ran.

**Report findings; do not fix.** Do not edit any file outside the report.

**REPORT-FIRST.** Before reading any code, create the report file as a skeleton — title, scope, the range, an empty `## Findings` section, the ten-item verification checklist — and save it. Append each result as you confirm it and save after every one. A crashed or closed session must lose prose, never the artifact.

**Closeout.** `make check-reviews` exists again at current `main` (`infra/Makefile` `check-reviews:` → `_bmad/scripts/check_review_reports.py`); run it from the main checkout before reporting completion. `_bmad-output/implementation-artifacts/*` is still gitignored apart from explicitly tracked files (`.gitignore`: `_bmad-output/*` with `!_bmad-output/planning-artifacts/`), so the checker degrades to presence-on-disk for this report and says so; do not force-add it. State the report's path and size, and that it is uncommitted because the directory is ignored.

## 2. Repository, branch, range

- Repo: `/Users/devopsterus/current/cohort/meetingminer` (main checkout — other agents work in it; do not edit it). Review in the worktree `/Users/devopsterus/current/cohort/meetingminer-wt/11-1-review` (branch `story/11-1-review`, bootstrapped), or make your own detached one at `31ff539`.
- Range: `183bdf175288d74350e7147fc7134bcce9fb126e..31ff5392dc6d28d4b9e116efc6b759d37d2b8521` (`git diff 183bdf1..31ff539`; base is the `main` the reviewer rebased onto). `origin/story/11-1-review` is `31ff539`.
- Commits, oldest first (the first 13 are the original story rebased; the last 4 are the remediation):
  - `97bce8d` test: move REPO_ROOT out of conftest into repo_paths
  - `8ced1f9` test: collapse the two make runners in test_makefile_procs into one _make
  - `426412d` test: default the server suite to the fast set with a measured slow mark
  - `396ec4a` test: fail an unmarked test whose call phase exceeds the fast-set budget
  - `1aaac0c` make: test-fast iteration target; test and check-test-stores pass -m ""
  - `f6fcb4d` docs: state the fast set, the full gate, the budget, and retire B-1
  - `ef00ef2` test: two blank lines after the budget hook in conftest
  - `e64855d` test: fast_budget plugin with pytester coverage of the budget's three behaviours
  - `b4bc667` test: contract tests for the -m "" recipes, test-fast, and pyproject's fast set
  - `ac6b019` test: fast_budget validates once, checks slow reasons and twin fixtures, hints on by-path runs
  - `b050d24` test: contract tests parse addopts and pin the twelve slow modules; finish the _make collapse
  - `0efe4fd` make: test-fast runs check-client first; pin the fast-set count to a commit
  - `6424523` docs: own section for the fast loop and full gate; hook lives in fast_budget.py
  - `6451453` test: budget wiring accepts overrides; hint only when the default expression emptied the run; invalid, xpass and default-path probes
  - `722e521` test: Make targets' effective pytest argv via make -n; slow set derived with ast
  - `270b0bc` make: test-fast help and comment say Postgres-only; count pinned to 722e521
  - `31ff539` docs: Postgres skips versus twin deselection in test-fast; counts re-pinned to the review branch
- Every commit in the range belongs to story 11-1. `main` has since moved to `a22d67c` (integrate-skill restore, sprint-status sync); a trial merge conflicts on `infra/Makefile` by proximity only — both sides add to `.PHONY` and `help` (`test-fast` here, `check-reviews` on main). Not under review; the integrator resolves it by union.

## 3. The spec

`_bmad-output/implementation-artifacts/spec-11-1-seconds-fast-default-suite.md`.
- **Frozen intent** (do not critique as the builder's choice): the `<intent-contract>` block, **as amended** for the first review's findings 9 and 10 by owner decision — see `## Spec Change Log`. Outcome equality now applies to node ids that existed at `e5510c7`; the named new regression tests are allowed; totals are revision-pinned; the stores-down row is split into Postgres skips versus twin deselection.
- **Planner work you may attack:** Code Map, Tasks & Acceptance, Design Notes, both Review Triage Log entries, Auto Run Result and its remediation addendum, the frontmatter `deferred` list.

## 4. Architecture authority

`docs/architecture.md`: **AD-4 — Projections have exactly one writer** (line 70) with the invariant "Single writer per store class, proven not asserted" (line 188); **AD-9 — Infrastructure in Docker, code on the host** (line 101); **AD-10 — One config file drives everything** (line 109) with "Every threshold is configuration" (line 200) — the budget and the selection live in `server/pyproject.toml`, the test tool's config, not `config.yaml`. `AGENTS.md`: "What worktrees do NOT isolate: the data stores" and the story's own `## Fast loop and full gate`.

## 5. Scope

**In scope:** the whole range — `server/pyproject.toml`; `server/tests/fast_budget.py`, `conftest.py`, `repo_paths.py`; `test_fast_budget.py` (16 tests), `test_compose_contract.py` (+8 tests incl. the `make -n` argv and `ast` slow-set contracts); the twelve module-level `slow` marks and four per-test marks; `test_makefile_procs.py` (one `_make`); `test_parallel_store_safety.py` (child `-m ""`); 13 importer-only modules; `infra/Makefile` (`test-fast`, `-m ""` in `test`/`check-test-stores`, `.PHONY`, help); `AGENTS.md`, `project-context.md`, `docs/backlog.md`.

**Out of scope:** story 11.2; `server/meetingminer/**`, `web/`, `evals/`, `tools/`, `config.yaml`, migrations, dependencies; the three deferred owner items (README, project-record entry, filing the fixture-cost residue); the Starlette `httpx` deprecation warning; `main`'s own commits after `183bdf1`.

## 6. What to verify — the ten original findings

1. `uv run --project server pytest -q server/tests/test_fast_budget.py::test_the_real_session_loads_fast_budget_from_conftest -o mm_fast_test_budget_seconds=3.0` passes (was `assert 3.0 == 2.0`).
2. `uv run --project server pytest -q server/tests/test_config.py -k __no_such__` exits 5 with **no** hint; `uv run --project server pytest -q server/tests/test_projections_locks.py` exits 5 **with** the one-line hint. Both are pytester cases in `test_fast_budget.py`.
3. `test_compose_contract.py::test_make_test_runs_the_server_suite_with_the_marker_filter_cleared` parses `make -n -C infra test` argv: the last `-m` is `""`. Mutation: append `-m "not slow"` to the recipe → the test fails.
4. `::test_make_test_fast_runs_the_whole_server_fast_set`: project `<ROOT>/server`, exact path `<ROOT>/server/tests`, `-rs`, no `-m`. Mutation: narrow the path → fails.
5. `SLOW_MODULES` compared exactly with the `ast`-derived module-level slow set. Mutations: an extra module with a real mark → fails; a mark line inside a top-level string → fails.
6. Invalid budgets `abc`, `nan`, `inf`, `0`, `-1` → `USAGE_ERROR` naming the key and value; `3.5` accepted.
7. Over-budget non-strict xfail that passes keeps XPASS.
8. Reasonless `slow` mark under `-m "not slow"` (CLI and `addopts`) → usage error naming the node id.
9. Spec amended (Spec Change Log entry dated 2026-08-29); no test deleted to fit a count; counts pinned to `722e521` in the Makefile comment and the backlog paragraph.
10. Makefile help/comment, AGENTS.md, project-context.md state: Postgres-backed fast tests skip with reasons; twin-bound tests are `slow` and deselected from `test-fast`; `make test` requires the twins.

## 7. Design decisions to attack (new in the remediation)

1. **`make -n` as the argv oracle** for the Make contracts. Assumes a dry run prints every recipe line expanded and that joining continuation lines before `shlex.split` is enough; a recipe that builds its command in a shell variable would evade it.
2. **The "every collected item was slow" flag** decides the hint. Assumes `-k` is the only other deselection source worth excluding; `--deselect` and `-p no:...` are not considered.
3. **`ast`-derived slow set compared both ways** — a per-test `@pytest.mark.slow` is deliberately outside it (four exist). Assumes module-level marks are the canonical unit and per-test marks are covered by the collection rules and the budget.
4. **The stash-based wiring test** reads a private name (`fast_budget._BUDGET`). Assumes coupling the test to the plugin's internals is acceptable for a wiring pin.
5. **Counts pinned to `722e521`** while the final commit is `31ff539` (docs-only after the pin). Assumes a docs-only commit does not change collection.
6. Everything from the first handoff's section 6 still stands (measured `slow` set; call-phase budget; budget under the gate; `pytest_plugins` in the initial conftest; `-m ""` as the clearing mechanism; `--strict-markers`; unconditional store-free prerequisites; text-pinned contracts; `pytester` enabled globally; `REPO_ROOT` via `sys.path`).

## 8. History

- The first review rebased `story/11-1` onto `main` `183bdf1` as `story/11-1-review` (unified story diff SHA-256 unchanged, `9f0ae728…`); remediation continued there. `story/11-1` at `15fdbe2` is superseded.
- A gate run during the original build was interrupted by another agent recreating the Docker stack (`AdminShutdown` in one contiguous block) — not a regression; the re-run was clean.
- The "1 warning" in every run is the pre-existing `StarletteDeprecationWarning` from `fastapi/testclient.py`.

## 9. Verification baseline (a skip or failure during review is a finding, not noise)

Observed by the coordinator in `meetingminer-wt/11-1-review` at `31ff539`, stores up:
- `uv run --project server pytest server/tests/test_fast_budget.py server/tests/test_compose_contract.py -m "" -q` → `41 passed`.
- `--co -q` → `1382/1708 tests collected (326 deselected)`; `-m ""` → `1708 tests collected`.
- `make check-test-stores` → `1 passed`. `make test-fast` → rc 0, 65s; server step `1382 passed, 326 deselected, 1 warning in 48.85s`; puller 128, web 257, evals 549. Twins unreachable (server step) → `1382 passed, 326 deselected`, 0 SKIPPED.
- `make test` → rc 0, 549s wall, `1708 passed`; per-test outcomes vs the `e5510c7` baseline on pre-existing node ids: 0 changed, 0 missing; 25 new (16 `test_fast_budget`, 8 `test_compose_contract`, 1 `test_extraction_core` from story 6.7 on `main`).
- `uv run --project server pytest -m "" server/tests/test_makefile_procs.py -q` → `46 passed`.

Harness notes: run pytest from the worktree root with a path under `server/tests` (`./config.yaml` resolves relative to the cwd; `pytest_plugins` needs the initial conftest); a shell sandbox denying `.env` reads or the `uv` cache is the sandbox, not the repo. Server suites may run concurrently; do not run `make evals-run`; do not restart the Docker stack while any suite is running.
