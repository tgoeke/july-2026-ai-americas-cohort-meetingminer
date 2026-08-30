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

### Finding 3 — Check glue still judges sibling probes as subject artifacts before locking

- Location: `evals/checks/test_publish_gate.py:117`
- Severity: high
- Finding: The glue's subject snapshot includes every artifact row and reads membership before `run_gate_probe` acquires the per-moment lock. A sibling probe captured as `published` can be correctly erased by its owner before these reads, causing this run to report the transient row as a published subject artifact missing from both stores.
- Evidence: `artifacts = corpus.artifacts_for(meeting_id)` at line 119 is passed unchanged into the subject membership loop at lines 177–186 and pure assembly at lines 203–206. `gate_probe.run_gate_probe`—the first code that can coordinate by moment—does not run until line 210. No F5 test sends a probe-marked row through this glue snapshot.
- Resolution: Fixed in this review. The glue regression failed with the published sibling reported absent from both stores. Probe ownership detection is now shared from `gate_probe.py`; the glue excludes marked rows only from immutable subject membership/assembly, while `run_gate_probe` still re-reads the unfiltered corpus under its moment lock. The complete glue test file passes (`6 passed`).

### Finding 4 — A post-commit connection-mode failure skips probe cleanup entirely

- Location: `evals/checks/gate_probe.py:731`
- Severity: high
- Finding: After the probe insert commits, `conn.autocommit = True` runs before the cleanup-protected `try/finally`. An exception from that driver state transition escapes `_execute_probe` with a committed probe row and no cleanup attempt or recorded cleanup verdict.
- Evidence: The known `artifact_id` is committed at lines 702–703. The autocommit assignment at line 731 is outside the `try` beginning at line 734 and the `finally` invoking `cleanup_probe` at lines 790–803. Existing interruption tests inject failures only after that protected region begins.
- Resolution: Fixed in this review. The fake-connection regression first raised out of `_execute_probe` with no result. The autocommit transition now occurs inside the interruption-catching `try/finally`; its failure is named on the returned probe and the known id is erased with a verified cleanup. The full probe file passes (`38 passed`).

### Finding 5 — Publish-gate module guidance still grants unaccepted eval overlap

- Location: `evals/checks/test_publish_gate.py:16`
- Severity: medium
- Finding: F11 restores the single-flight rule in AGENTS, dispatch, and RUNBOOK, but the store-mutating publish-gate module still says it is safe while another eval run is running. That contradicts the owner-acceptance hold and can mislead someone running or composing this check directly.
- Evidence: Lines 16–21 claim subject safety and conclude, `safe to run while another eval run or any suite is running.` The F11 docs-contract test reads only AGENTS, dispatch, and RUNBOOK, so this contradictory in-scope check documentation remains invisible.
- Resolution: Fixed in this review. The expanded F11 test first failed on the stale sentence. The publish-gate header now says the check participates in `make evals-run`'s single-flight lane pending owner live acceptance and may overlap only store-free suites; the contract test passes.
