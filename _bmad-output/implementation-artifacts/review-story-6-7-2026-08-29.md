# Code Review: Story 6.7 — Extraction Prompt Wording Generalized

## Scope

- Repository: `meetingminer`
- Review branch: `story/6-7-review`
- Source branch: `story/6-7`
- Reviewed range: `e5510c7caf385720851b199382b62aa1221f4051..d39bf0a62e782a6c3e29d3ec631ec22e2950ecec`
- Review mode: full, against `spec-6-7-extraction-prompt-wording-generalized.md`
- Review method: unchunked adversarial review using blind-hunter, edge-case-hunter, verification-gap, and acceptance-auditor layers.

## Findings

No actionable findings survived root-agent triage.

## Dismissed candidates

The four layers produced 16 raw candidate statements, normalized to 15 after
merging the duplicate case-sensitivity claim. All 15 were dismissed:

- The proposed case-insensitive `Teams` assertion would also reject the
  ordinary plural word “teams”; the capitalized bare brand word and the exact
  required generic phrase are both already pinned.
- Suggestions to replace “meeting analyst,” “meeting or recorded session,”
  “covers the whole recording,” or “with owners” contradict the frozen exact
  wording or behavior the unchanged ground rules already define.
- Missing-speaker, transcript-lineage, long-timestamp, and incomplete-recording
  concerns are pre-existing behavior outside the four-line story boundary. The
  meaningful missing-speaker issue is already recorded in the spec's deferred
  frontmatter, and `render_transcript` supplies `Unknown` when a label is absent.
- Broader semantic-vocabulary and live-model tests exceed this config-wording
  story's deterministic acceptance surface; existing composition/parser tests
  cover the unchanged runtime path.
- The claimed Python blank-line violation is factually false: the test has two
  blank lines before and after it, and `git diff --check` is clean.

## Verification

Pending.

## Verdict

Review layers and triage are clean. Final pass and merge remain contingent on
fresh verification by this review session.

## Closeout (added during the 6-1 integrate pass, 2026-08-29)

The reviewed range landed on main as `f1d3ad9`/`ab07263` (rebased copies,
byte-identical) inside the 6-1 fast-forward. The pending verification was run
on main `9826866`: `uv run --project server pytest
server/tests/test_extraction_core.py` → 105 passed. Story marked `done`.
