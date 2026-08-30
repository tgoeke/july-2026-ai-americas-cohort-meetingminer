# Review — Story 1.4: Screen Identification & Screenshots

- date: 2026-08-18
- content reviewed: `ea33274e1bc3773959c1bcdb7eaf947932ccf963..d2d56da1ec42335767290d085911b6f7237e9cdb` on `main`
- specification: `spec-1-4-screen-identification-screenshots.md`, including frozen intent contract, planner-owned material, Epic 1 context, architecture spine, and Story 1.4 acceptance criteria
- lenses: blind hunter (16 signals), edge-case hunter (2), verification-gap (1), acceptance auditor (2)
- exclusions: `pull_transcript/`; future pipeline, projection, UI, and API work; and the eight risks already recorded in the story’s `deferred` frontmatter
- verification: `git diff --check` passed. Focused regression verification passed: 6 passed (the three amended test areas, including parametrized symlink coverage). A full server-suite run collected 298 tests but remained live in Makefile process-management tests beyond a minute, so I terminated only that review-launched process; migration and web-build verification were not completed in this review session.

Findings confirmed by more than one independent lens are marked `(xN)`.

## Output consistency

1. **Empty `screens` reruns leave stale screenshot files (x3).** `server/meetingminer/pipeline/stages/screens.py:187-203` deletes this meeting’s `screenshot` rows and returns as soon as `_load_frames()` is empty. `OutputDirSwap` is constructed only at `:207`, so an earlier successful run’s `meetings/<id>/screenshots/*.jpg` remains, even though the log reports `directory=None`. This violates the I/O matrix’s requirement that a `screens` rerun replaces both the per-meeting rows and subtree, and makes the zero-output state disagree between Postgres and disk. Fix: durably publish an empty directory or safely remove the existing subtree in the empty path; add a regression that makes a previously populated meeting empty before rerunning `screens`.

## OCR adapter contract

2. **Tesseract can emit geometry outside the unit square (x3).** `server/meetingminer/adapters/ocr/tesseract.py:113-164` drops negative or zero-size words but does not bound `left + width` / `top + height` to page dimensions. It can therefore create an `OcrBlock` whose normalized width or height exceeds 1, unlike the Apple Vision adapter; `OcrBlock` promises 0–1 geometry at `server/meetingminer/adapters/ocr/port.py:34-35`. The same parser admits `NaN`/infinite numeric TSV fields and confidence values above 100, which can violate the same geometry/confidence contract. A malformed or unexpected engine result can skew view-type classification or make invalid block data durable. Fix: reject non-finite values, clamp or drop boxes outside page bounds, and constrain confidence to 0–1; add parser tests for page-overrun, non-finite, and over-range input.

## Verification coverage

3. **Intermediate symlink guards have no regression coverage.** `server/meetingminer/pipeline/outputs.py:43-49` correctly guards three components — `meetings/`, the meeting directory, and the final output subdirectory — before destructive cleanup. But `server/tests/test_output_dir_swap.py:201-209` covers only a symlink at the final component. If the loop were accidentally narrowed, a symlinked `meetings/` or meeting directory pointing at another directory *inside* `MM_CONTENT_ROOT` would pass the resolved-root containment check and cleanup could target another meeting’s evidence, while the current test remains green. Fix: parameterize the refusal test over all three components and use an in-root cross-meeting target.

## Triage notes

- Dismissed as already-owned deferred work: corpus-wide lineage scan cost, duplicated screenshot storage, OCR-engine/revision identity provenance, low-confidence OCR policy, stale downstream checkpoints after manual upstream resets, NFR2 capture-density tuning, orphan-screen lifecycle, and database-side capture-cue validation.
- Dismissed as non-actionable or unsupported by the normal writer path: direct-database cross-meeting foreign-key/path tampering, persisted frame-path traversal, and a missing simultaneous `dwell-drift` label when an immediate boundary already creates the same capture.

## Verdict

**Passes review after the agreed fixes.** The three actionable findings were implemented and each has focused regression coverage.
