# Story 11-4 Remediation Verification Review

## Scope

Independent verification of the Story 11-4 remediation diff only, including mutation-first validation of every fix, footprint checks, adjacent-behavior checks, resolution-claim verification, the story-specific contract-test bypasses, and the prohibition on lint/type-driven source sweeps.

## Range

`dc1e64d..9b70dd1`

## Findings

### V1 — Shell short-circuit operators bypass both tool contracts

**Location:** `server/tests/test_lint_contract.py:209` · **Severity:** high · **Finding:** The hardened lint and typecheck assertions validate only the tokens beginning at `uv`; they do not validate the shell prefix that decides whether `uv` executes. Replacing `&&` with `||` after either successful `cd` silently disables the tool while the contract and target both exit zero. · **Evidence:** With the exact lint mutation `cd $(ROOT) || uv run --project $(ROOT)/server ruff check $(ROOT)/server`, `test_make_lint_runs_ruff_check_over_the_whole_server_tree` passed and `make lint` exited 0 after printing only that recipe. With the exact typecheck mutation `cd $(ROOT)/server || uv run --project $(ROOT)/server python -m mypy`, `test_make_typecheck_runs_mypy_bare_from_server` passed and `make typecheck` exited 0 after printing only that recipe. No ruff or mypy result was emitted in either run. · **Resolution:** Open. Add red-first mutation coverage and pin the complete command tokens, including the expected working directory and `&&`, before the exact `uv` argv.
