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

### Finding 2 — Initial eligibility still mistakes a live sibling probe for subject state

- Location: `evals/checks/gate_probe.py:562`
- Severity: high
- Finding: F5 adds a per-moment lock, but `run_gate_probe` rejects moments containing any `extracted` row before acquiring that lock. A sibling paused after mint on a one-moment meeting therefore makes the second run refuse immediately instead of waiting for sibling cleanup, so the claimed overlapping-run behavior remains false.
- Evidence: `eligible_moments()` includes probe-marked rows in its blocking set at lines 152–157; `run_gate_probe()` returns from the empty-eligibility branch at lines 564–593; `_moment_probe_lock` is not reached until line 621. The F5 regression `test_a_sibling_probe_waits_until_the_owner_has_cleaned` calls `_moment_probe_lock` directly and never feeds the live sibling row through `run_gate_probe`, so it does not cover this ordering.
- Resolution: Fixed in this review. A caller-level regression first failed with `entered == False`. Initial eligibility now defers probe-marked rows to the moment lock; the locked refresh either observes the live sibling's cleanup and proceeds, or names a persistent marker as stranded cleanup debt without minting over or deleting it. The full `test_gate_probe.py` file passes (`37 passed`).
