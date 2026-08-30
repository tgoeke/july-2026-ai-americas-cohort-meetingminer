# Scoped Verification Review — Story 11-3 Remediation

## Scope

- Branch: `story/11-3-review`
- Remediation-only verification review
- Paid `make evals-run` is excluded by mandate.

## Exact Range

`5bc62ff..4e7d566`

## Findings

### Finding 1 — F12 documentation canary does not pin the governing AD-16 paragraph

- Location: `evals/tests/test_harness_boundary.py:559`
- Severity: medium
- Finding: The F12 regression checks whole-file keyword presence, so an inaccurate governing AD-16 paragraph can survive as long as the same keyword appears elsewhere in the README.
- Evidence: Mutation text: `exception for check 2.11: \`checks/gate_probe.py\` uses direct SQL to insert one` → `exception for check 2.11: \`checks/gate_probe.py\` uses SQL to insert one`. `uv run --project server pytest evals/tests/test_harness_boundary.py::test_ad16_docs_name_the_probe_exception_exactly -q` still passed (`1 passed`). The later file-map phrase `direct SQL mint` satisfied the unscoped assertion.
- Resolution: Fixed in this review. The regression now extracts the governing README and RUNBOOK exception sections before checking the required terms. It failed against the mutation above and passed after restoring `uses direct SQL`.
