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
