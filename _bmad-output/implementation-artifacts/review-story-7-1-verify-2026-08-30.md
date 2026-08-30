# Scoped Verification Review — Story 7-1 Remediation

## Scope

- Branch: `story/7-1-review`
- Remediation range: `db36748..8f029db`
- Review boundary: remediation diff only
- Prior report: `_bmad-output/implementation-artifacts/review-story-7-1-2026-08-30.md`

## Findings

### V1. Optional-extra remediation crosses the frozen story footprint

- **Location:** `infra/Makefile:79,94,279-289`; `server/tests/test_compose_contract.py:97-118`
- **Severity:** Medium
- **Finding:** Finding 4's remediation widened into two paths the frozen Story 7.1 contract does not permit. `infra/Makefile` is explicitly forbidden, and the contract requires new tests to live only in new files; `test_compose_contract.py` is an existing file outside the build-prompt footprint. The packaging gate is useful and mutation-proven, but correctness does not make the scope expansion authorized.
- **Evidence:** Commit `0a39b59` adds `diarize-extra-test`, wires it into `make test`, and adds the contract test. The frozen spec says “Stay inside the build-prompt footprint. New tests only in new files” at line 74, says any widening beyond the recorded `server/uv.lock` exception must block at line 78, and explicitly says “No edit to ... `infra/Makefile`” at line 80. The build prompt independently lists `infra/Makefile` as “Not yours” at lines 35-38. Mutation `test: ... diarize-extra-test ...` → `test: ... evals-test infra-up ...` made `test_make_test_gates_the_optional_diarizer_extra_in_an_isolated_environment` fail; restoring it passed, confirming the edit works but remains out of scope.
- **Resolution:** **OPEN — owner/spec decision required.** Either amend the frozen footprint to authorize the full-gate and existing contract-test edits, or remove/rehome Finding 4's packaging gate. This verifier cannot honestly resolve the conflict in code without choosing between the frozen scope and the claimed regression closure.
