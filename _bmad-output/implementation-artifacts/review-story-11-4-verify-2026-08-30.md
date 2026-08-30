# Story 11-4 Remediation Verification Review

## Scope

Independent verification of the Story 11-4 remediation diff only, including mutation-first validation of every fix, footprint checks, adjacent-behavior checks, resolution-claim verification, the story-specific contract-test bypasses, and the prohibition on lint/type-driven source sweeps.

## Range

`dc1e64d..9b70dd1`

## Findings

### V1 — Shell short-circuit operators bypass both tool contracts

**Location:** `server/tests/test_lint_contract.py:209` · **Severity:** high · **Finding:** The hardened lint and typecheck assertions validate only the tokens beginning at `uv`; they do not validate the shell controls that decide whether `uv` executes or whether its failure propagates. Replacing `&&` with `||` after either successful `cd` silently disables the tool, and Make's leading `-` recipe prefix is stripped from `make -n`, leaving failure suppression invisible to the contract. · **Evidence:** With the exact lint mutation `cd $(ROOT) || uv run --project $(ROOT)/server ruff check $(ROOT)/server`, `test_make_lint_runs_ruff_check_over_the_whole_server_tree` passed and `make lint` exited 0 after printing only that recipe. With the exact typecheck mutation `cd $(ROOT)/server || uv run --project $(ROOT)/server python -m mypy`, `test_make_typecheck_runs_mypy_bare_from_server` passed and `make typecheck` exited 0 after printing only that recipe. No ruff or mypy result was emitted in either run. With the exact raw recipe mutation `-cd $(ROOT) && uv run --project $(ROOT)/server ruff check $(ROOT)/server` and a temporary `import os` probe, the contract still passed, ruff reported `F401`, Make printed `Error 1 (ignored)`, and `make lint` exited 0. · **Resolution:** Fixed. The new `||` mutation cases failed first against the unfixed assertions (`DID NOT RAISE AssertionError`). The contracts now pin each literal Make recipe, preserving control prefixes, and the complete expanded command from `cd` through the tool argv. The restored `-cd $(ROOT) && uv run --project $(ROOT)/server ruff check $(ROOT)/server` mutation then failed at the raw-recipe assertion; all real and mutation cases pass after restoration.
