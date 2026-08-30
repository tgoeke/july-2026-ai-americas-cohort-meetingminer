---
title: 'Lint and Type Tooling in the Fast Loop'
type: 'chore'
created: '2026-08-30'
status: 'ready-for-dev'
baseline_revision: '5cdfce7'
review_loop_iteration: 0
followup_review_recommended: false
context: ['{project-root}/AGENTS.md', '{project-root}/_bmad-output/implementation-artifacts/wave-2026-08-30-rules.md', '{project-root}/_bmad-output/implementation-artifacts/build-prompt-story-11-4-2026-08-30.md']
warnings: ['oversized']
deferred: []
---

<intent-contract>

## Intent

**Problem:** The fast loop has no lint or type tooling: `.gitignore` anticipates `.ruff_cache/` and `.mypy_cache/` but nothing is declared, so the errors a test never catches (unused imports, blind excepts, type mismatches in the decision cores) reach review instead (backlog B-4, epics.md Story 11.4).

**Approach:** Add pinned `ruff` and `mypy` to the server dev dependency group with a committed configuration that is green on main as it stands — a dated baseline, never a source sweep — plus `make lint` and `make typecheck` targets that join `make test-fast` as prerequisites, pinned by contract tests.

## Boundaries & Constraints

**Always:** Stay inside the build-prompt footprint table exactly: `server/pyproject.toml` (dev group additions + new `[tool.ruff]`/`[tool.ruff.lint]`/`[tool.ruff.lint.per-file-ignores]`/`[tool.mypy]` tables at EOF), `infra/Makefile` (`lint:`/`typecheck:` before `test-fast:` at main line 295; the `test-fast:` rule line gains `lint typecheck` directly after `check-client`), `server/tests/test_compose_contract.py` main lines 294–308 only, `AGENTS.md` one paragraph at the end of "Fast loop and full gate" edited LAST after `git fetch && git rebase origin/main`, NEW `server/tests/test_lint_contract.py`, and the `_bmad-output/implementation-artifacts` process files (incl. `deferred-work.md`, directed by the prompt). `server/uv.lock` is regenerated mechanically by uv when the dev group changes — a consequence, not a widening. Commit and push each coherent unit; `python3 _bmad/scripts/branch_conflicts.py --against story/11-4` must be clean (pairs involving `story/11-2-review` excepted) before the final push.

**Block If:** Green `make lint`/`make typecheck` cannot be reached without editing an existing source or test file; or `branch_conflicts.py` reports a conflict with another lane that narrowing this story's own edits cannot clear.

**Never:** Modify any existing source or test file to satisfy ruff or mypy (no fixes, no `noqa`, no `# type: ignore` additions). No `ruff format`. No edit to `[project]` in pyproject (7-1 owns an addition there), no `.PHONY`/`help`/other Makefile lines, nothing in `test_compose_contract.py` outside lines 294–308 (11-2 owns 10–100). Never `git add -A`, `make evals-run`, `make up`, or a merge to main; the story ends at `review`, not `done`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Lint green on baseline | `make lint` on this branch | exit 0, no violations | No error expected |
| Typecheck green | `make typecheck` on this branch | exit 0 over the decision-core file list | No error expected |
| Fast loop runs both | `make test-fast` | `check-client`, then `lint` and `typecheck`, then store-free suites, then the fast set | A lint/type error fails the loop before pytest |
| Contract drift | `test-fast:` rule line loses `lint` or `typecheck` | `test_compose_contract.py` / `test_lint_contract.py` fail naming both edit sites | Named assertion |

</intent-contract>

## Code Map

- `server/pyproject.toml` -- `[dependency-groups] dev` (pytest, httpx): append `ruff>=0.16.5,<0.17` and `mypy>=2.3.1,<2.4`. New tables go at EOF, after `[tool.pytest.ini_options]` (file currently ends at `mm_fast_test_budget_seconds`). Nothing in `[project]`.
- Measured baseline (2026-08-30 at 5cdfce7, ruff 0.16.5 `--isolated` ≡ discovered config since none exists): 264 violations, 202 unique file-code pairs across 110 files. Six mechanical codes carry 151 of those pairs — I001 (69 hits), UP035 (50), PLW1510 (33), SIM117 (17), RUF100 (14), UP037 (12) — and go in a dated global `ignore`, each filed in `deferred-work.md` as per-module cleanup. The remaining 51 pairs (scratchpad `ruff_baseline_pairs.txt`; regenerate with `uvx ruff check server --isolated --output-format concise`) become `[tool.ruff.lint.per-file-ignores]` entries, paths relative to `server/`. Keep ruff's default select (415 rules at 0.16.5; the `<0.17` pin is what holds the set still).
- `server/meetingminer` decision cores (architecture.md:205 "Segmentation, classification, identity, chunking, and highlighting are database-free, model-free"): `domain/` (3 files), `pipeline/{moments,screens,speakers,alignment,extraction,transcripts,outputs}.py`, `projections/{chunking,query,publish_gate}.py` — 13 files, mypy 2.3.1 green with `check_untyped_defs = true` except one `import-untyped` for `jsonschema` at `domain/drops.py:32` → module override `ignore_missing_imports` (committed ignore list; adding `types-jsonschema` would exceed the named dev-group edit). Encode the file list in `[tool.mypy] files` so the Makefile recipe stays bare.
- `infra/Makefile:295-296` -- `test-fast: check-client puller-test web-test evals-test` + one pytest recipe line. Insert `lint:` and `typecheck:` (with brief comments) immediately before; recipes `cd $(ROOT) && uv run --project $(ROOT)/server ruff check $(ROOT)/server` and `cd $(ROOT)/server && uv run --project $(ROOT)/server python -m mypy` (mypy discovers `pyproject.toml` from cwd; caches land under `server/`, both gitignored at `.gitignore:19-20` — verified, no edit).
- `server/tests/test_compose_contract.py:294` -- `TEST_FAST_PREREQUISITES` becomes `("check-client", "lint", "typecheck", "puller-test", "web-test", "evals-test")`; the ordering test (:297-313) compares `targets[1:-1]` as a set and needs only its docstring touched (line 298, in range); the recipe test (:316) ignores prerequisite recipes. The stale comment at :286-293 ("the three store-free suites") is OUTSIDE the permitted range — leave it, name it in the review prompt and deferred list.
- `server/tests/test_lint_contract.py` -- NEW: self-contained `make -n`-based assertions (no import from test_compose_contract): `lint`/`typecheck` targets exist, their recipes run `ruff check` / `mypy` under `uv run --project server`, and pyproject carries the `[tool.ruff.lint]` ignore/baseline and `[tool.mypy]` files/override tables. Fast, no stores, no `slow` mark.
- `AGENTS.md` -- "Fast loop and full gate" section ends immediately before `## Branch and merge` (currently :208). One paragraph, appended LAST after rebase onto origin/main.
- `server/uv.lock` -- tracked; `uv sync --project server` after the dep edit regenerates it. Known merge surface with story/7-1 (adds an optional-dependencies table); `branch_conflicts.py` arbitrates.

## Tasks & Acceptance

**Execution:**
- `server/pyproject.toml` -- add pinned ruff+mypy to dev group; append `[tool.ruff]`, `[tool.ruff.lint]` (dated ignore + per-file-ignores baseline), `[tool.mypy]` (files list, `check_untyped_defs`, jsonschema override) at EOF; `uv sync` -- committed config green on main, no source edits.
- `infra/Makefile` -- insert `lint:`/`typecheck:` before `test-fast:`; add `lint typecheck` after `check-client` on the rule line -- both join the loop.
- `server/tests/test_compose_contract.py` -- extend `TEST_FAST_PREREQUISITES` (+docstring line 298) -- the pinned contract follows the rule line.
- `server/tests/test_lint_contract.py` -- NEW contract test -- the targets and committed baseline cannot be silently dropped.
- `_bmad-output/implementation-artifacts/deferred-work.md` -- per-module cleanup items for the six ignored codes, baseline retirement, and per-module strictness raises -- prompt requirement.
- `git fetch && git rebase origin/main`, then `AGENTS.md` -- append the fast-loop paragraph -- ordered last by the prompt.
- `sprint-status.yaml` key `11-4-lint-and-type-tooling-in-the-fast-loop`, `sprint-notes.md` entry, `review-prompt-story-11-4-2026-08-30.md`.

**Acceptance Criteria:**
- Given this branch, when `make lint` and `make typecheck` run, then both exit 0 with committed configuration and no existing source or test file modified for compliance.
- Given `make test-fast`, when it runs, then lint and typecheck run after `check-client` and before the fast set, and the whole loop is green.
- Given a later edit dropping either target from the `test-fast:` rule line, when the server suite runs, then a contract test fails naming both edit sites.
- Given `git diff origin/main...HEAD --name-only`, when compared to the footprint table (+`server/uv.lock`), then no other path appears.

## Spec Change Log

## Review Triage Log

## Design Notes

- Default select + version pin over an explicit 415-rule list: the pin (`<0.17`) freezes the rule set as effectively as enumerating it, without a table nobody can audit. Upgrading the pin is a deliberate act that re-runs the baseline math.
- Global ignore for the six mechanical codes (151 pairs) versus per-file entries: a 110-file per-file-ignores block would drown the 51 meaningful baseline entries; the six are uniform style/mechanical debt best retired per-module (filed in deferred-work.md), and every other rule stays live in every file.
- Per-file-ignores (not `noqa`) for the 51 remaining pairs: keeps the no-sweep constraint (zero source edits) while new files get the full rule set.
- mypy scope is the architecture's decision-core definition mapped to concrete modules, `files`-encoded in config so `make typecheck` and any bare `mypy` run agree.

## Verification

**Commands:**
- `make lint` -- expected: exit 0.
- `make typecheck` -- expected: exit 0, "no issues found in 13 source files".
- `make test-fast` -- expected: green; lint+typecheck visible in the sequence.
- `uv run --project server pytest server/tests/test_compose_contract.py server/tests/test_lint_contract.py -m "" -q` -- expected: all pass.
- `python3 _bmad/scripts/branch_conflicts.py --against story/11-4` -- expected: clean against main and every story/* except story/11-2-review pairs.
