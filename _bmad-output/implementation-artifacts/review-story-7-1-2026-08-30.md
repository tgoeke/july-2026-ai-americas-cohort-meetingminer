# Code Review — Story 7.1: Diarizer Engine Behind the Port

Date: 2026-08-30

## Scope

Review the Story 7.1 implementation against its frozen intent contract and the applicable architecture decisions. The requested implementation scope is:

- `server/meetingminer/adapters/diarize/`
- `DiarizerConfig` in `server/meetingminer/config.py`
- the `diarizer:` block in `config.yaml`
- `[project.optional-dependencies]` in `server/pyproject.toml`
- the `HF_TOKEN` line in `.env.example`
- `server/tests/test_diarize_pyannote.py`

The exclusions and pre-recorded deferred items named in the review handoff remain out of scope.

## Review Range

- Target branch: `story/7-1`
- Range reviewed: `5cdfce7..db36748`
- Review worktree branch: `story/7-1-review`

## Findings

### 1. Generated tags can leave the placeholder namespace

- **Location:** `server/meetingminer/adapters/diarize/pyannote.py:60`; `server/meetingminer/pipeline/speakers.py:58-64`
- **Severity:** Low
- **Finding:** The canonicalizer has no speaker-count bound and formats indices wider than three digits, but the never-guess matcher accepts at most three suffix characters. The 1,001st distinct surviving label therefore becomes `SPEAKER_1000`, which is not recognized as a placeholder and can enter downstream name-resolution logic as though it were a participant label. This violates the frozen invariant that no generated tag ever resolves to a participant.
- **Evidence:** `_to_turns` uses `f"SPEAKER_{len(canonical):02d}"`, whose width is a minimum rather than a maximum. `_PLACEHOLDER_LABEL` permits only `\w{1,3}` after `speaker`. A direct probe over 1,001 distinct valid turns produced `DiarizationTurn(..., speaker='SPEAKER_1000')`, and `is_placeholder_label('SPEAKER_1000')` returned `False`. The new test only checks `SPEAKER_100`, so it does not exercise the boundary.
- **Suggested direction:** Preserve the never-guess invariant for every possible output: either reject an excessive distinct-speaker count with a named `DiarizerError`, or coordinate an explicit widening of the placeholder-label contract and pin the first four-digit tag in regression coverage.
- **Resolution:** Resolved on the review branch. A regression test first failed because 1,001 distinct speakers did not raise; `_to_turns` now refuses a 1,001st distinct surviving label before emitting `SPEAKER_1000`. The focused test and the full pyannote adapter module pass (23 passed).

### 2. The build-time availability probe can approve an unusable installation

- **Location:** `server/meetingminer/adapters/diarize/__init__.py:48-57,92-98`; `server/meetingminer/adapters/diarize/pyannote.py:35-39,85-99`
- **Severity:** Medium
- **Finding:** `build_diarizer` equates `find_spec("pyannote.audio")` with an importable engine. A partial or ABI-broken installation can expose a module spec while `from pyannote.audio import Pipeline` still raises. That engine is returned successfully at the promised fail-closed boundary and fails only on its first `diarize`, after the transcribe stage has already extracted audio and completed STT. This contradicts the frozen matrix row requiring an import failure to raise the named `DiarizerError` at build time, before work.
- **Evidence:** `_pyannote_available` never imports `Pipeline`; the real import is deferred inside `_load_pipeline`. `transcribe.run` builds the diarizer at line 171, performs STT at lines 175-178, and only invokes the diarizer at line 180. The branch's `test_a_half_installed_extra_is_named_as_such_at_load_time` explicitly injects an `ImportError` and expects it from `diarize`, demonstrating the late-failure behavior rather than enforcing the build-time contract.
- **Suggested direction:** Keep model construction/download lazy, but make the build boundary validate the precise provider symbol needed at runtime and convert any import failure to the named missing/broken-extra `DiarizerError`. Add a regression case where module discovery succeeds but importing `Pipeline` fails, and assert that `build_diarizer` itself refuses the binding.

### 3. Tests do not exercise the application's real provider-factory wiring

- **Location:** `server/meetingminer/adapters/diarize/pyannote.py:35-39`; `server/tests/test_diarize_pyannote.py:93-98,198-207,234-289`
- **Severity:** Medium
- **Finding:** The only application code that connects configured values to pyannote's real API is `_load_pipeline`, but no test invokes it. Functional tests inject replacement factories; the extra-gated test merely inspects the provider method's signature. The application can therefore stop forwarding the configured token/model correctly while the entire suite stays green.
- **Evidence:** `_engine` always supplies a lambda factory, and every lazy-load/error test constructs `PyannoteDiarizer(..., pipeline_factory=...)`. `test_the_pinned_pipeline_api_accepts_token` asserts only that upstream `Pipeline.from_pretrained` declares `token`; it never calls `_load_pipeline` or observes its arguments. Mutations such as removing `token=token`, substituting a different model, or using the wrong keyword leave those tests unchanged but make the first real gated-model load fail.
- **Suggested direction:** Exercise `_load_pipeline` through a controlled fake `pyannote.audio.Pipeline` and assert the exact `from_pretrained(model, token=token)` call. Keep the test model-free; the missing check is application wiring, not network/model inference.

### 4. The shipped optional-extra installation path is not gated

- **Location:** `server/pyproject.toml:64-69`; `server/tests/test_diarize_pyannote.py:191-207`; `infra/Makefile:278-296`
- **Severity:** Medium
- **Finding:** The normal project gates run in the default extra-free environment. Their only check against the locked provider uses `pytest.importorskip`, while the real availability probe explicitly accepts either result. Consequently the story's sole real diarizer installation route can stop resolving or importing on a supported host without making `make test-fast` or `make test` fail.
- **Evidence:** `test_the_real_probe_answers_without_raising` accepts both `False` and `True`; `test_the_pinned_pipeline_api_accepts_token` skips when `pyannote.audio` is absent. The Makefile test recipes do not sync or run with `--extra diarize`. Removing `pyannote.audio` from the extra, or introducing a platform-specific lock/import incompatibility, would leave mocked engine tests green and the provider test skipped. During this review, an extra-installed environment successfully imported locked version 4.0.7 and passed all 22 new tests, which confirms the current lock rather than closing the regression gap.
- **Suggested direction:** Add a model-free packaging smoke gate in a disposable environment that syncs the committed `diarize` extra and imports `pyannote.audio`; it may be a dedicated slower/optional-dependency gate rather than part of every fast loop.

### 5. The adapter inherits enabled-by-default provider telemetry without an explicit policy

- **Location:** `server/meetingminer/adapters/diarize/pyannote.py:35-39,110-112`; `server/uv.lock:1741-1769`
- **Severity:** Low
- **Finding:** Importing and running locked pyannote 4.0.7 activates its default OpenTelemetry exporter, but the adapter neither disables it nor documents that a nominally in-process diarizer makes this external request. AD-12 permits egress, so this is not an architecture prohibition; it is an implicit operational/privacy behavior introduced by the new engine.
- **Evidence:** Direct inspection of the installed 4.0.7 wheel shows `pyannote/audio/telemetry/config.yaml` sets `metrics_enabled: true` and targets `https://otel.pyannote.ai/v1/traces`. Its pipeline hooks emit model/pipeline origin, package version, session id, audio duration, and requested speaker-count parameters on initialization/application. The story adds no `PYANNOTE_METRICS_ENABLED` handling, adapter-level telemetry choice, or operator wording.
- **Suggested direction:** Make the behavior deliberate: either disable pyannote telemetry in the adapter before model initialization, or explicitly document and test the chosen egress policy so upgrades cannot silently change it.

## Triage

All four configured adversarial layers completed: Blind Hunter, Edge Case Hunter, Verification Gap Reviewer, and Acceptance Auditor. They produced 26 raw candidates, normalized to 21 distinct claims. Five were retained and 16 were dismissed after reading the call sites and frozen contract.

| Finding | Sources | Route | Rationale |
|---|---|---|---|
| 1. Placeholder namespace overflow | Edge Case Hunter + Acceptance Auditor | Patch | The never-guess invariant is absolute and the four-digit boundary is directly reproducible. |
| 2. Discoverability is not importability | Blind Hunter + Edge Case Hunter + Acceptance Auditor | Patch | The implementation and its own test place a partial-install import failure after the required build boundary. |
| 3. Default factory wiring untested | Verification Gap Reviewer + Blind Hunter | Patch | A provider-call mutation survives every current test and breaks the first real model load. |
| 4. Optional-extra path ungated | Verification Gap Reviewer + Blind Hunter | Patch | The current 4.0.7 lock works, but no normal gate protects the installation contract from regression. |
| 5. Implicit telemetry policy | Blind Hunter | Decision needed | AD-12 permits egress, so disabling versus explicitly accepting/documenting telemetry is an owner policy choice rather than an unambiguous code patch. |

Dismissed candidates included the four items already recorded in the spec frontmatter (process-environment token threading, the extra-installed `test_stt_adapter.py` failure, stale runbook guidance, and MPS placement); they were confirmed but deliberately not re-reported. The blocked 60-minute measurement is explicitly permitted by the frozen contract while `HF_TOKEN` is absent. Other dismissed candidates were unreachable provider shapes, behavior deliberately fixed by the contract (first-surviving-appearance canonicalization and regular diarization through unchanged `speaker_at` semantics), unsupported timeout requirements, and changes outside Stories 7.2–7.4's excluded scope. The suggestion to remove `DiarizerConfig` defaults was also dismissed because the frozen Story 7.1 task explicitly requires those defaults.

## Verification

- `uv run --isolated --project server pytest server/tests/test_diarize_pyannote.py server/tests/test_stt_adapter.py -q` — 52 passed, 1 named skip in a clean extra-free environment.
- `uv run --project server pytest server/tests/test_diarize_pyannote.py -q` — 22 passed with locked `pyannote.audio` 4.0.7 installed; the provider signature check executed rather than skipping.
- The same extra-installed environment imported `pyannote.audio` 4.0.7 and showed `Pipeline.from_pretrained(..., token=...)` in its live signature.
- A real `pyannote.core.Annotation` converted successfully through `_to_turns` without loading a model.
- The combined adapter command in the extra-installed environment produced the already-recorded deferred failure in `test_stt_adapter.py` (52 passed, 1 failed); it was not re-filed as a new finding per the review handoff.
- `make check-reviews` — passed: every dispatched review has a committed report.

## Verdict

**Changes requested — Story 7.1 does not pass review as it stands.** Four patch findings remain open, including three medium-severity runtime/verification gaps, and the telemetry behavior needs an explicit owner decision. The branch must not merge until the patch findings are remediated, the telemetry choice is recorded and implemented as applicable, and the resulting tree is re-reviewed.
