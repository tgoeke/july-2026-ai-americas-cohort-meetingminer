# Review handoff — story 11-4 "Lint and Type Tooling in the Fast Loop"

Hand this file, as is, to the `bmad-code-review` agent. It has none of the
build run's context; everything it needs is here.

## 1. Required output — read this before touching any code

**Report path:** `_bmad-output/implementation-artifacts/review-story-11-4-2026-08-30.md`,
under the main checkout `/Users/devopsterus/current/cohort/meetingminer`.

**Finding structure** — one block per finding: **Location** (`path:line` in
the worktree named below) / **Severity** (high, medium, low — by consequence
for a builder running the loop) / **Finding** / **Evidence** (command and
real output, or the lines) / **Suggested direction**.

**Report findings; do not fix.** Do not edit any file outside the report.

**REPORT-FIRST.** Before reading any code, create the report file as a
skeleton — title, scope, the range, an empty `## Findings` section — and
save it. Append each finding as you confirm it. A crashed session must lose
prose, never the artifact.

**Closeout.** `_bmad-output/` is tracked since 2026-08-30 (owner decision):
commit and push the report like any file. Run `make check-reviews` from the
main checkout before reporting completion.

## 2. Repository, branch, range

- Repo: `/Users/devopsterus/current/cohort/meetingminer` (main checkout —
  other agents work in it; do not edit it). Review in the worktree
  `/Users/devopsterus/current/cohort/meetingminer-wt/11-4` (branch
  `story/11-4`, bootstrapped), or make your own detached one.
- Range: `origin/main..origin/story/11-4`, rebased onto main `211857c`.
  Commits, oldest first (SHAs after the 2026-08-30 rebase):
  - `7cdfad9` chore: pinned ruff+mypy dev deps with a dated committed baseline
  - `645519f` chore: make lint/typecheck join the fast loop, pinned by contract tests
  - `aeeca07` docs: file the 11.4 baseline retirement plan; spec change log
  - plus the closing docs commit (AGENTS.md paragraph, sprint files, this
    prompt) at the branch head.
- Footprint (build prompt): `server/pyproject.toml` (dev group + tool tables
  at EOF only), `infra/Makefile` (two inserted targets + the `test-fast:`
  rule line), `server/tests/test_compose_contract.py` main lines 294–308
  only, NEW `server/tests/test_lint_contract.py`, `AGENTS.md` one appended
  bullet, `server/uv.lock` (mechanical), `_bmad-output` process files.
  `git diff origin/main...origin/story/11-4 --name-only` must show nothing
  else.

## 3. The spec

`_bmad-output/implementation-artifacts/spec-11-4-lint-and-type-tooling-in-the-fast-loop.md`.
- **Frozen intent** (do not critique as the builder's choice): the
  `<intent-contract>` block. Core constraint: green `make lint` /
  `make typecheck` with NO existing source or test file modified for
  compliance — a dated baseline, never a sweep.
- **Planner work you may attack:** Code Map, Tasks & Acceptance, Design
  Notes, and the three build-time Spec Change Log entries.

## 4. Known items — verify, do not rediscover

- **UP017 seventh ignore code.** The spec named six mechanical codes; the
  committed config surfaces UP017 (30 hits) because `requires-python`
  sets ruff's target-version to py312 and the measured `--isolated` run
  never reached that rule. Check the change-log reasoning and that the
  ignore is dated and filed in `deferred-work.md`.
- **49 vs 51 remaining pairs.** The spec's 51 counted ruff's two summary
  lines as file-code pairs; the recount is 49 across 38 files. Verify the
  per-file-ignores table against
  `uv run --project server ruff check server --isolated --output-format concise`
  at ruff 0.16.5 minus the seven ignored codes (UP017 aside, which needs
  the config's target-version to fire).
- **Stale prose left deliberately** (outside the permitted footprint):
  `server/tests/test_compose_contract.py:286-293` and the `test-fast:`
  comment block in `infra/Makefile` still say "the three store-free
  suites". Filed in `deferred-work.md`; do not count as new findings.
- **`server/uv.lock` x story/7-1.** `branch_conflicts.py` reports this one
  non-excepted conflicting pair — the spec's named merge surface (both
  lanes regenerate the lock). Integration takes either side and re-runs
  `uv sync --project server`. Not a review finding.

## 5. Verification commands (all from the worktree)

- `make lint` — exit 0.
- `make typecheck` — exit 0, "no issues found in 13 source files".
- `make test-fast` — green; lint and typecheck visible after check-client,
  before pytest.
- `uv run --project server pytest server/tests/test_compose_contract.py server/tests/test_lint_contract.py -m "" -q`
- `python3 _bmad/scripts/branch_conflicts.py --against story/11-4` — clean
  except the story/11-2-review pairs (excepted) and the uv.lock pair above.
- No-sweep proof: `git diff origin/main...origin/story/11-4 --stat -- server/meetingminer server/tests ':(exclude)server/tests/test_lint_contract.py' ':(exclude)server/tests/test_compose_contract.py'`
  must be empty, and the compose-contract diff must touch only lines 294–308.

## 6. Architecture authority

`docs/architecture.md:205` — "Segmentation, classification, identity,
chunking, and highlighting are database-free, model-free" — is what maps to
the 13 `[tool.mypy] files` entries. `AGENTS.md` "Fast loop and full gate"
(as amended by this story) is the loop's contract.
