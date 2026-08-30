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

### V2. The speaker-limit regression does not protect the valid upper boundary

- **Location:** `server/tests/test_diarize_pyannote.py:401-411`
- **Severity:** Low
- **Finding:** Finding 1's regression proves that 1,001 distinct speakers are rejected, but it never proves that the intended maximum of exactly 1,000 speakers succeeds and ends at `SPEAKER_999`. An off-by-one regression can therefore reject a valid placeholder tag while the claimed regression remains green.
- **Evidence:** Exact mutation `MAX_PLACEHOLDER_SPEAKERS = 1000` → `MAX_PLACEHOLDER_SPEAKERS = 999` left `test_more_than_one_thousand_speakers_fails_before_a_tag_escapes_placeholder_protection` passing (`1 passed`). The production error promises support for “at most 1000,” and `SPEAKER_999` remains inside the downstream three-character placeholder matcher.
- **Resolution:** **OPEN — remediation in progress.** Add a boundary regression that processes exactly 1,000 surviving labels and pins the final tag as `SPEAKER_999`; demonstrate it red against the `999` mutation and green after restoration.

### V3. The provider-symbol validation branch is untested and accepts unusable objects

- **Location:** `server/meetingminer/adapters/diarize/__init__.py:53-54`; `server/tests/test_diarize_pyannote.py:194-214`
- **Severity:** Medium
- **Finding:** Finding 2's probe checks only that `Pipeline` is non-`None`; it does not require the `from_pretrained` callable the real factory uses. Its new regression covers an exception during module import, not a successfully imported module with an absent or unusable `Pipeline` symbol. Such an installation passes `build_diarizer` and fails only after work reaches the lazy factory.
- **Evidence:** Exact mutation `return getattr(module, "Pipeline", None) is not None` → `return True` left the discoverable-but-unimportable regression, both broken-`find_spec` cases, and the real-probe test green (`4 passed`). A module exposing `Pipeline = object()` likewise satisfies the current production predicate although `_load_pipeline` cannot call `Pipeline.from_pretrained`.
- **Resolution:** **OPEN — remediation in progress.** Add a red-first build-boundary regression for a successfully imported provider with no usable `Pipeline.from_pretrained`, then make the probe validate that exact callable.

### V4. Telemetry remediation reopens the late provider-import failure

- **Location:** `server/meetingminer/adapters/diarize/__init__.py:48-60`; `server/meetingminer/adapters/diarize/pyannote.py:36-42`
- **Severity:** Medium
- **Finding:** Finding 5 added `pyannote.audio.telemetry.set_telemetry_metrics` as a required runtime symbol, but Finding 2's build-time probe still validates only `pyannote.audio.Pipeline`. If the telemetry module or setter is missing/broken, `build_diarizer` returns an engine and the failure occurs on first `diarize`, after STT work, contradicting the fail-closed build boundary and the report's claim that the exact runtime provider symbol is validated.
- **Evidence:** `_pyannote_available` imports only `pyannote.audio` and checks only `Pipeline`; `_load_pipeline` later imports `set_telemetry_metrics`. The isolated packaging smoke likewise imports only `pyannote.audio`, while unit tests fabricate a valid telemetry module. A discoverable audio module with a valid `Pipeline.from_pretrained` and an importer that raises for `pyannote.audio.telemetry` therefore passes every build check on the current tree.
- **Resolution:** **OPEN — remediation in progress.** Add a red-first partial-install regression and extend the build probe to validate the callable telemetry switch required to enforce the owner's disable ruling.

### V5. The optional-extra gate does not prove the committed lock

- **Location:** `infra/Makefile:288-289`; `_bmad-output/implementation-artifacts/review-story-7-1-2026-08-30.md:98`
- **Severity:** Medium
- **Finding:** The packaging smoke uses an isolated environment but omits `--locked`. `uv` may update `uv.lock` while preparing the command, allowing the gate to pass after repairing drift instead of rejecting an inconsistent committed pyproject/lock pair. The prior report's statement that the target installed “166 locked packages” is therefore not supported by the command it records.
- **Evidence:** Local `uv run --help` defines `--isolated` only as “Run the command in an isolated virtual environment” and separately defines `--locked` as “Assert that the `uv.lock` will remain unchanged.” The target runs `uv run --isolated --project ... --extra diarize` with no `--locked`; its contract test pins that omission exactly.
- **Resolution:** **OPEN — owner/spec decision required.** The technical repair is to add `--locked` and pin it in the gate regression, but both edits touch the already-forbidden paths in Finding V1. Apply only after the frozen footprint is amended or the gate is rehomed into an authorized path.
