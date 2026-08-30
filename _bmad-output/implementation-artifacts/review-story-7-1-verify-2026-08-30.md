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
- **Resolution:** **RESOLVED.** Added `test_one_thousand_speakers_reaches_the_last_protected_placeholder`, which requires 1,000 turns, final tag `SPEAKER_999`, and placeholder recognition. It failed against the `999` mutation with `DiarizerError: ... more than 999 distinct speakers` and passed after restoring `1000`.

### V3. The provider-symbol validation branch is untested and accepts unusable objects

- **Location:** `server/meetingminer/adapters/diarize/__init__.py:53-54`; `server/tests/test_diarize_pyannote.py:194-214`
- **Severity:** Medium
- **Finding:** Finding 2's probe checks only that `Pipeline` is non-`None`; it does not require the `from_pretrained` callable the real factory uses. Its new regression covers an exception during module import, not a successfully imported module with an absent or unusable `Pipeline` symbol. Such an installation passes `build_diarizer` and fails only after work reaches the lazy factory.
- **Evidence:** Exact mutation `return getattr(module, "Pipeline", None) is not None` → `return True` left the discoverable-but-unimportable regression, both broken-`find_spec` cases, and the real-probe test green (`4 passed`). A module exposing `Pipeline = object()` likewise satisfies the current production predicate although `_load_pipeline` cannot call `Pipeline.from_pretrained`.
- **Resolution:** **RESOLVED.** Added `test_an_imported_provider_without_a_callable_factory_fails_at_build`; it failed on the original predicate because no `DiarizerError` was raised. `_pyannote_available` now requires callable `Pipeline.from_pretrained`; the new test and the import-exception regression pass.

### V4. Telemetry remediation reopens the late provider-import failure

- **Location:** `server/meetingminer/adapters/diarize/__init__.py:48-60`; `server/meetingminer/adapters/diarize/pyannote.py:36-42`
- **Severity:** Medium
- **Finding:** Finding 5 added `pyannote.audio.telemetry.set_telemetry_metrics` as a required runtime symbol, but Finding 2's build-time probe still validates only `pyannote.audio.Pipeline`. If the telemetry module or setter is missing/broken, `build_diarizer` returns an engine and the failure occurs on first `diarize`, after STT work, contradicting the fail-closed build boundary and the report's claim that the exact runtime provider symbol is validated.
- **Evidence:** `_pyannote_available` imports only `pyannote.audio` and checks only `Pipeline`; `_load_pipeline` later imports `set_telemetry_metrics`. The isolated packaging smoke likewise imports only `pyannote.audio`, while unit tests fabricate a valid telemetry module. A discoverable audio module with a valid `Pipeline.from_pretrained` and an importer that raises for `pyannote.audio.telemetry` therefore passes every build check on the current tree.
- **Resolution:** **RESOLVED.** Added `test_an_imported_provider_without_the_telemetry_switch_fails_at_build`; it failed on the original probe because no `DiarizerError` was raised. `_pyannote_available` now imports the telemetry module and requires callable `set_telemetry_metrics` after validating `Pipeline.from_pretrained`; all three partial-install regressions pass.

### V5. The optional-extra gate does not prove the committed lock

- **Location:** `infra/Makefile:288-289`; `_bmad-output/implementation-artifacts/review-story-7-1-2026-08-30.md:98`
- **Severity:** Medium
- **Finding:** The packaging smoke uses an isolated environment but omits `--locked`. `uv` may update `uv.lock` while preparing the command, allowing the gate to pass after repairing drift instead of rejecting an inconsistent committed pyproject/lock pair. The prior report's statement that the target installed “166 locked packages” is therefore not supported by the command it records.
- **Evidence:** Local `uv run --help` defines `--isolated` only as “Run the command in an isolated virtual environment” and separately defines `--locked` as “Assert that the `uv.lock` will remain unchanged.” The target runs `uv run --isolated --project ... --extra diarize` with no `--locked`; its contract test pins that omission exactly.
- **Resolution:** **OPEN — owner/spec decision required.** The technical repair is to add `--locked` and pin it in the gate regression, but both edits touch the already-forbidden paths in Finding V1. Apply only after the frozen footprint is amended or the gate is rehomed into an authorized path.

## Mutation Audit

The five claimed fixes were tested in remediation-commit order. Every restored fix was green; two narrower follow-up mutations exposed V2 and V3.

| Fix | Exact mutation | Claiming test result while mutated | Restored result |
|---|---|---|---|
| Finding 1 — placeholder overflow | `if len(canonical) >= MAX_PLACEHOLDER_SPEAKERS:` → `if len(canonical) > MAX_PLACEHOLDER_SPEAKERS:` | Failed as required: `DID NOT RAISE DiarizerError` | Passed |
| Finding 2 — import boundary | Replaced `module = importlib.import_module("pyannote.audio")` plus the `Pipeline` predicate with `return True` | Failed as required: `DID NOT RAISE DiarizerError` | Passed |
| Finding 3 — factory wiring | `Pipeline.from_pretrained(model, token=token)` → `Pipeline.from_pretrained(model)` | Failed as required: observed `{}` instead of `{"token": "configured-token"}` | Passed |
| Finding 4 — optional-extra gate | Removed `diarize-extra-test` from the `test:` prerequisite list | Failed as required: target absent from effective `make test` steps | Passed |
| Finding 5 — telemetry disable | Removed `set_telemetry_metrics(False)` | Failed as required: event trace began with `load`, with no preceding telemetry event | Passed |
| Finding 1 follow-up — lower boundary | `MAX_PLACEHOLDER_SPEAKERS = 1000` → `MAX_PLACEHOLDER_SPEAKERS = 999` | Original overflow regression survived (`1 passed`), confirming V2. After the new boundary regression was added, the same mutation failed with `more than 999 distinct speakers` | New boundary regression passed after restoration |
| Finding 2 follow-up — exact symbol branch | `return getattr(module, "Pipeline", None) is not None` → `return True`, retaining the import call | All four relevant existing probe cases survived (`4 passed`), confirming V3 | New unusable-factory regression failed on the old predicate and passed after callable validation |

V4 used the actual unfixed cross-fix state rather than a synthetic mutation: a valid `Pipeline.from_pretrained` plus a missing telemetry module returned an engine, so the new regression failed with `DID NOT RAISE DiarizerError`; it passed after the build probe began validating `set_telemetry_metrics`.

## Scope and Resolution Honesty

- The remediation range changes eight paths. `infra/Makefile` and the pre-existing `server/tests/test_compose_contract.py` exceed the frozen footprint; V1 records the required block even though the change works.
- Findings 1–3 are behaviorally supported after V2–V4 remediation.
- Finding 4's functional claim is supported by mutation and the isolated import, but its “resolved” status is not scope-honest until V1 receives an owner ruling. Its “locked packages” evidence is also overstated because `--locked` is absent (V5).
- Finding 5 is supported both by the call-order regression and by the real locked provider probe below: telemetry is disabled before `Pipeline.from_pretrained`.

## Adversarial-Layer Triage

Blind Hunter, Edge Case Hunter, Verification Gap Reviewer, and Acceptance Auditor all completed. They produced 24 raw candidates, normalized to 12 distinct claims. Five were retained as V1–V5; seven were dismissed after call-site and scope inspection. Dismissed candidates were duplicates, unchanged pre-remediation comments/tests, behavior required by the fail-closed contract, or broader future-provider compatibility concerns outside the locked 4.0.7 remediation claim.

## Verification

- `uv run --project server pytest server/tests/test_diarize_pyannote.py -q` — `28 passed, 1 skipped` (named extra-free skip).
- `uv run --project server pytest server/tests/test_stt_adapter.py -q` — `31 passed`.
- `uv run --project server pytest server/tests/test_compose_contract.py -q` — `31 passed`.
- `make diarize-extra-test` — passed after installing 166 packages in the disposable environment. V5 remains open because this target itself omits `--locked`.
- Real-wheel telemetry proof, run with `uv run --locked --isolated --project server --extra diarize`: locked `pyannote.audio==4.0.7` reported endpoint `https://otel.pyannote.ai/v1/traces` and metrics enabled before the adapter call; with only `Pipeline.from_pretrained` mocked to prevent a model/network operation, `_load_pipeline` made the provider's own `is_metrics_enabled()` false before that call. Output: `before=true before_load=false`.
- `make test-fast` in the foreground — puller `128 passed`; web `291 passed`; evals `549 passed`; server `1430 passed, 1 skipped, 326 deselected`.
- `make evals-run` was not run.

## Verdict

**Changes requested.** V2–V4 are resolved red-first and all required suites are green. V1 and V5 remain open at Medium severity pending one owner/spec ruling: authorize the existing full-gate footprint (and then add `--locked`), or remove/rehome that gate. The branch must not merge while the frozen contract and remediation disagree.
