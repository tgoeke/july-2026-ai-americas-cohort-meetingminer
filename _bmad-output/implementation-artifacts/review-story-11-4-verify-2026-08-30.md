# Story 11-4 Remediation Verification Review

## Scope

Independent verification of the Story 11-4 remediation diff only, including mutation-first validation of every fix, footprint checks, adjacent-behavior checks, resolution-claim verification, the story-specific contract-test bypasses, and the prohibition on lint/type-driven source sweeps.

## Range

`dc1e64d..9b70dd1`

## Findings

### V1 — Shell short-circuit operators bypass both tool contracts

**Location:** `server/tests/test_lint_contract.py:209` · **Severity:** high · **Finding:** The hardened lint and typecheck assertions validate only the tokens beginning at `uv`; they do not validate the shell controls that decide whether `uv` executes or whether its failure propagates. Replacing `&&` with `||` after either successful `cd` silently disables the tool, and Make's leading `-` recipe prefix is stripped from `make -n`, leaving failure suppression invisible to the contract. · **Evidence:** With the exact lint mutation `cd $(ROOT) || uv run --project $(ROOT)/server ruff check $(ROOT)/server`, `test_make_lint_runs_ruff_check_over_the_whole_server_tree` passed and `make lint` exited 0 after printing only that recipe. With the exact typecheck mutation `cd $(ROOT)/server || uv run --project $(ROOT)/server python -m mypy`, `test_make_typecheck_runs_mypy_bare_from_server` passed and `make typecheck` exited 0 after printing only that recipe. No ruff or mypy result was emitted in either run. With the exact raw recipe mutation `-cd $(ROOT) && uv run --project $(ROOT)/server ruff check $(ROOT)/server` and a temporary `import os` probe, the contract still passed, ruff reported `F401`, Make printed `Error 1 (ignored)`, and `make lint` exited 0. · **Resolution:** Fixed. The new `||` mutation cases failed first against the unfixed assertions (`DID NOT RAISE AssertionError`). The contracts now pin each literal Make recipe, preserving control prefixes, and the complete expanded command from `cd` through the tool argv. The restored `-cd $(ROOT) && uv run --project $(ROOT)/server ruff check $(ROOT)/server` mutation then failed at the raw-recipe assertion; all real and mutation cases pass after restoration.

### V2 — The corrected review-worktree command ignores its requested base

**Location:** `_bmad-output/implementation-artifacts/review-prompt-story-11-4-2026-08-30.md:34` · **Severity:** high · **Finding:** The remediation tells a reviewer to run `make worktree STORY=11-4-review BASE=story/11-4`, and its regression asserts that literal string, but the `worktree` target never reads `BASE`. For a missing review branch it executes `git worktree add -b story/11-4-review ... main`, so the resulting checkout omits Story 11-4. The prior report's resolution claim that this command produces a review branch “based on `story/11-4`” is therefore not honest. · **Evidence:** `make -n --no-print-directory -C infra worktree STORY=11-4-review-probe BASE=story/11-4` printed `git ... worktree add -b story/11-4-review-probe ... main`; repository search found no `BASE` reference in `infra/Makefile`. `test_review_handoff_uses_a_dedicated_review_worktree` nevertheless passed. · **Resolution:** Fixed. The strengthened regression first failed because the prompt lacked `git branch story/11-4-review story/11-4`. The handoff now creates the review branch at the story head, then runs `make worktree STORY=11-4-review` so the helper attaches the existing correctly based branch. The test pins that order, rejects unsupported `BASE=`, and the prior report's resolution now states the actual two-step behavior.

### V3 — A remediation regression widened beyond the frozen compose-test window

**Location:** `server/tests/test_compose_contract.py:319` · **Severity:** medium · **Finding:** The frozen footprint permits changes to `test_compose_contract.py` only in the original lines 294–308, but the remediation adds the standalone `test_make_test_fast_order_contract_rejects_suites_before_lint_and_typecheck` after the existing contract, outside that window. The original review's no-sweep proof excludes the entire compose file, so it did not substantiate its claim that remediation stayed within story-owned targets. · **Evidence:** `git diff dc1e64d..9b70dd1 -- server/tests/test_compose_contract.py` adds the standalone function after the original function's line-313 end; the spec and builder footprint both name original lines 294–308 as the only allowed region. The independent real mutation `test-fast: check-client puller-test web-test lint typecheck evals-test` already made the main in-window ordering contract fail. · **Resolution:** Fixed. The out-of-window duplicate regression is removed. The in-window prefix assertion remains, and the prior report now records the independent real Makefile mutation that failed against it instead of claiming a retained permanent self-test.

### V4 — The handoff test does not pin the report destination it claims to protect

**Location:** `server/tests/test_lint_contract.py:147` · **Severity:** high · **Finding:** The regression searches the whole handoff for the review-worktree path and only bans two literal phrases. The required-output block can therefore redirect the report to main using different wording while later setup text supplies every expected review-worktree string. · **Evidence:** The exact mutation replaced the report destination with `inside /Users/devopsterus/current/cohort/meetingminer` while leaving the later branch/worktree instructions unchanged. `test_review_handoff_uses_a_dedicated_review_worktree` still passed. · **Resolution:** Fixed. The regression now extracts the text between `**Report path:**` and `**Finding structure**` and requires the dedicated review-worktree path there. Reapplying the exact `inside /Users/devopsterus/current/cohort/meetingminer` mutation failed at that anchored assertion; the restored handoff passes.

## Mutation evidence

The original seven patch resolutions were tested in their recorded order. Every advertised regression failed under its corresponding broken state and passed after restoration.

| Fix | Exact mutation | Result against the fixed contract |
|---|---|---|
| Prior Finding 2 — baseline units | `leaving the 49 per-file entries below` plus `49 per-file baseline entries` | `test_baseline_prose_distinguishes_pairs_from_per_file_entries` failed on the pyproject assertion; restored text passed. |
| Prior Finding 3 — review worktree | `under the main checkout /Users/devopsterus/current/cohort/meetingminer` | `test_review_handoff_uses_a_dedicated_review_worktree` failed; restored destination passed. A stronger synonymous mutation later survived and became V4. |
| Prior Finding 4 — lint enforcement | `ruff check $(ROOT)/server --exit-zero` | `test_make_lint_runs_ruff_check_over_the_whole_server_tree` failed on the extra argv. |
| Prior Finding 4 — lint enforcement | `echo ruff check $(ROOT)/server` | The same contract failed because `echo` was the executed argv. |
| Prior Finding 5 — type enforcement | `echo python -m mypy` | `test_make_typecheck_runs_mypy_bare_from_server` failed because `echo` was the executed argv. |
| Prior Finding 6 — fail-fast order | `test-fast: check-client puller-test web-test lint typecheck evals-test` | The in-window compose contract failed with the reordered prefix; the restored rule passed. |
| Prior Finding 7 — measured versions | `ruff>=0.16.5,<1`, `mypy>=2.3.1,<3`, and matching ruff `required-version` | The pin contract failed on ruff. A second run with only `mypy>=2.3.1,<3` failed independently on mypy. Restored pins passed. |
| Prior Finding 8 — full baseline retirement | `per_file = lint["per-file-ignores"]` plus `assert per_file, "the per-file baseline may be retired entry-by-entry, not dropped wholesale"` | `test_ruff_baseline_contract_allows_full_per_file_retirement` failed with `KeyError`; restoration passed. A separate empty-table fixture also passed. |

Additional adversarial mutations produced and then verified the four findings above:

| Finding | Exact mutation/probe | Before patch | After patch |
|---|---|---|---|
| V1 | `cd $(ROOT) || uv run --project $(ROOT)/server ruff check $(ROOT)/server` | Contract passed; `make lint` exited 0 without ruff output. | Mutation regression fails; committed real target passes. |
| V1 | `cd $(ROOT)/server || uv run --project $(ROOT)/server python -m mypy` | Contract passed; `make typecheck` exited 0 without mypy output. | Mutation regression fails; committed real target passes. |
| V1 | `-cd $(ROOT) && uv run --project $(ROOT)/server ruff check $(ROOT)/server` with temporary `import os` | Contract passed; ruff emitted `F401`; Make printed `Error 1 (ignored)` and exited 0. | Raw-recipe assertion fails on the leading `-`; committed target passes. |
| V2 | `make worktree STORY=11-4-review-probe BASE=story/11-4` | `make -n` selected literal `main`; handoff test passed. | Handoff uses `git branch story/11-4-review story/11-4` before `make worktree STORY=11-4-review`; regression passes. |
| V3 | Standalone compose mutation test at original lines 319–339 | The remediation exceeded the frozen 294–308 window. | Duplicate removed; real reordered Makefile mutation remains caught by the in-window contract. |
| V4 | Report destination `inside /Users/devopsterus/current/cohort/meetingminer` | Handoff test passed by finding review-worktree text later in the file. | Anchored report-block assertion failed under the mutation and passed after restoration. |

## Scope and resolution audit

- The original remediation range changes six paths: three process artifacts, `server/pyproject.toml`, and the two story contract modules. It contains no `server/meetingminer` change and no unrelated test or compliance sweep.
- V3 was the sole footprint widening. The out-of-window compose self-test is removed; the current net compose change is anchored in the frozen `TEST_FAST_PREREQUISITES`/ordering-contract region.
- Prior resolution claims for Findings 3 and 6 were corrected to match the actual worktree-base behavior and retained ordering evidence.
- Review-layer triage: 4 patch findings, all fixed; 0 decision-needed; 0 deferred. Remaining suggestions were dismissed where the primary contract independently caught the mutation, current behavior was confirmed for both supported shapes, or the claim concerned archival policy outside this scoped remediation.

## Verification

- `make lint` — exit 0, `All checks passed!`.
- `make typecheck` — exit 0, `Success: no issues found in 13 source files`.
- `uv run --project server pytest server/tests/test_compose_contract.py server/tests/test_lint_contract.py -m "" -q` — `45 passed, 1 warning in 0.62s`.
- `make test-fast` — exit 0 in the foreground: lint and typecheck ran first; puller `128` passed; web `16` files / `291` tests passed; evals `549` passed; server fast set `1416 passed, 326 deselected, 1 warning in 54.72s`.
- `git diff --check dc1e64d..9b70dd1` and `git diff --check dc1e64d..HEAD` — no output.
- No-sweep proof: `git diff --name-only dc1e64d..9b70dd1 -- server/meetingminer` and the unrelated-test diff both printed nothing.
- `python3 _bmad/scripts/branch_conflicts.py --against story/11-4` — exit 1: `18 clean pair(s), 11 conflicting pair(s)`; the prior review's cross-lane process-file integration blocker remains open.
- `make check-reviews` — exit 0: `every dispatched review has a committed report`.

Verification patches were committed and pushed incrementally: V1 `dd87341`, V2 `455496e`, V3 `6a1e326`, and V4 `c43db1a`.

## Verdict

**PASS for the scoped remediation after independent follow-up patches.** Every original fix failed under its own mutation, four surviving defects were reported before repair and fixed red-first, the story contracts and complete fast loop are green, and no lint/type source sweep occurred. Story 11-4 is still **not integration-ready** because prior review Finding 1 remains open: the owner must reconcile the live cross-lane process-file conflicts during integration and rerun the conflict check. This review did not merge to `main`.
