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
- Range: `5cdfce7..HEAD`
- Review worktree branch: `story/7-1-review`

## Findings

### 1. Generated tags can leave the placeholder namespace

- **Location:** `server/meetingminer/adapters/diarize/pyannote.py:60`; `server/meetingminer/pipeline/speakers.py:58-64`
- **Severity:** Low
- **Finding:** The canonicalizer has no speaker-count bound and formats indices wider than three digits, but the never-guess matcher accepts at most three suffix characters. The 1,001st distinct surviving label therefore becomes `SPEAKER_1000`, which is not recognized as a placeholder and can enter downstream name-resolution logic as though it were a participant label. This violates the frozen invariant that no generated tag ever resolves to a participant.
- **Evidence:** `_to_turns` uses `f"SPEAKER_{len(canonical):02d}"`, whose width is a minimum rather than a maximum. `_PLACEHOLDER_LABEL` permits only `\w{1,3}` after `speaker`. A direct probe over 1,001 distinct valid turns produced `DiarizationTurn(..., speaker='SPEAKER_1000')`, and `is_placeholder_label('SPEAKER_1000')` returned `False`. The new test only checks `SPEAKER_100`, so it does not exercise the boundary.
- **Suggested direction:** Preserve the never-guess invariant for every possible output: either reject an excessive distinct-speaker count with a named `DiarizerError`, or coordinate an explicit widening of the placeholder-label contract and pin the first four-digit tag in regression coverage.

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
