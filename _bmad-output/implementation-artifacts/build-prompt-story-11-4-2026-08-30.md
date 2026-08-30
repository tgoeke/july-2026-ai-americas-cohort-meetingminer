# Builder handoff — Story 11.4: Lint and Type Tooling in the Fast Loop

Agent: `bmad-build-auto`. Read `wave-2026-08-30-rules.md` in this directory
first; it carries the wave-wide rules and the conflict check you must pass.

- Repository: `/Users/devopsterus/current/cohort/meetingminer`
- Worktree: `/Users/devopsterus/current/cohort/meetingminer-wt/11-4`, branch `story/11-4`
- Story: `_bmad-output/planning-artifacts/epics.md` → "Story 11.4: Lint and
  Type Tooling in the Fast Loop" (backlog B-4). One Given/When/Then clause.
- Context: `_bmad-output/implementation-artifacts/epic-11-context.md`; story
  11.1's `make test-fast` contract pinned in
  `server/tests/test_compose_contract.py` (`TEST_FAST_PREREQUISITES`, main
  line 294, and the assertion on the `test-fast:` rule line).

## Footprint — the only files and regions you may change

| Path | Allowed edit |
|---|---|
| `server/pyproject.toml` | `[dependency-groups] dev`: add `ruff` and `mypy` (pinned). NEW tables `[tool.ruff]`, `[tool.ruff.lint]` (+ `per-file-ignores`), `[tool.mypy]` appended at the END of the file. Nothing in `[project]` (7-1 adds an optional-dependencies table there). |
| `infra/Makefile` | `lint:` and `typecheck:` targets inserted immediately BEFORE the `test-fast:` rule (main line 295); the `test-fast:` rule line gains `lint typecheck` directly after `check-client`. No other Makefile line. |
| `server/tests/test_compose_contract.py` | `TEST_FAST_PREREQUISITES` and the one assertion that reads the `test-fast:` rule line (main lines 294–308). Nothing else in the file — 11-2 edits lines 10–100. |
| `AGENTS.md` | One paragraph appended at the END of "Fast loop and full gate", immediately before "## Branch and merge". **Edit it last**, after `git rebase origin/main`. |
| `server/tests/test_lint_contract.py` | NEW, optional: pins that `make lint`/`make typecheck` exist and are in the fast loop. |
| `_bmad-output/implementation-artifacts/` | Your spec, `sprint-status.yaml`, `sprint-notes.md`, `review-prompt-story-11-4-<date>.md`. |

`.gitignore` already carries `.ruff_cache/` and `.mypy_cache/` — verify, do not
edit.

## Hard constraint — no sweep

Five other branches are in flight. **Do not modify any existing source or
test file to satisfy a linter or the type checker.** Choose a `ruff` rule set
that passes on `main` as it stands, or record the exceptions as a dated
baseline in `[tool.ruff.lint.per-file-ignores]`; run `mypy` on the named
decision-core modules with a committed baseline/ignore list. Every rule you
would have liked to enable but could not goes in `deferred-work.md` as a
per-module cleanup item. `ruff format` is not part of this story.

## Verification

- `make lint`, `make typecheck`, `make test-fast` — all green on your branch
  without touching any file outside the footprint.
- `uv run --project server pytest server/tests/test_compose_contract.py -m "" -q`
- `python3 _bmad/scripts/branch_conflicts.py --against story/11-4` → clean.

## Completion

Spec `status: review`, `11-4-lint-and-type-tooling-in-the-fast-loop: review`
in `sprint-status.yaml`, review prompt written, all pushed, SHAs reported.
