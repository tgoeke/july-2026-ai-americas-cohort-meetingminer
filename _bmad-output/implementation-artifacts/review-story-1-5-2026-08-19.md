# Code review — Story 1.5: Transcript Verification, Alignment & Participants

Reviewed commit `85d75ec87847cc5d9f282d20c3be015da44eac46` against its parent only. The shared working tree’s Story 1.11 changes were excluded.

Review used the Story 1.5 spec, Epic 1 context, corpus facts, and four independent review layers. Items already recorded as patched or deferred in the Story 1.5 Review Triage Log were not re-reported.

## Correctness

1. **[high] Invalid STT timing is fabricated as a `0 ms` recording offset** (`server/meetingminer/adapters/stt/port.py:88-99`, used by `mlx_whisper.py:90-93` and `parakeet_mlx.py:99-100`). `to_ms()` returns `0` for a missing, nonnumeric, or non-finite provider value, and both adapters pass `0.0` when fields are absent. A malformed provider segment can therefore text-match a provided turn and become a seemingly valid verification anchor at recording start. Reject invalid timing with a named `SttError`; retain the deliberate handling for a genuinely small negative first offset only if it is distinguishable from invalid data. Add provider-payload tests proving the unfixed code would otherwise create a zero-offset segment.

2. **[medium] Impossible clock components are accepted as plausible transcript offsets** (`server/meetingminer/pipeline/transcripts.py:107-134`). `parse_timestamp("99:99")` returns 6,039,000 ms instead of raising. This violates the I/O matrix’s malformed-stamp failure rule and can create a wrong citation. Require minutes and seconds to be in `[0, 60)` (while retaining fractional seconds where supported), and test both Teams and legacy inputs.

3. **[medium] Malformed timestamp headers are silently recorded as speech** (`server/meetingminer/pipeline/transcripts.py:48, 190-203, 228-249`). The Teams matcher accepts only digit-like bracket contents; `[broken] Robin: …` is appended to the preceding turn. Likewise, a legacy-looking `Robin | broken` line becomes body text once a valid legacy header establishes the lineage. The matrix requires a named `StageError` for a malformed stamp. Detect and reject a line that structurally presents a timestamp header but cannot be parsed, with the source line named.

4. **[medium] Unattributed content before the first turn is mishandled** (`server/meetingminer/pipeline/transcripts.py:173-214, 225-263`). In Teams input, leading nonblank text is buffered and then appended to the first speaker’s segment; in legacy input, it is silently discarded unless it is the one recognized `started transcription` preamble. A title, export note, or corrupted leading turn thus becomes false attribution or evidence loss. Apart from the documented legacy preamble, fail the transcript by line rather than assigning or dropping that material.

5. **[medium] Retry cleanup leaves video-only stages marked `done` after their evidence is deleted** (`server/meetingminer/pipeline/runner.py:274-294`). When a failed recording job is retried against a now transcript-only drop, `_clear_replaced_video_evidence()` removes frames, screenshots, media, audio, and the STT lane, but existing `probe` through `transcribe` checkpoints remain settled and the loop resumes them instead of recording them as skipped. This contradicts the transcript-only stage contract and presents completed stages with no evidence. Reset every affected video-only checkpoint to `skipped` (and clear any stale error) as part of this cleanup; cover a failed-recording retry that becomes transcript-only.

6. **[low] A diarizer label with a NUL fails STT-source persistence** (`server/meetingminer/pipeline/stages/transcribe.py:94-106`). Recognized text is NUL-stripped, but `speaker_at()` is serialized directly into JSONB. A future non-noop diarizer emitting such a label fails the stage before `align` can apply its own label sanitation. Sanitize the diarizer label at this boundary and add a regression test using a fake diarizer turn.

## Design

No additional design findings after triage. Claims about direct database tampering, cross-meeting provenance foreign keys, and arbitrary participant-graph coercions were not retained: the committed worker’s writes preserve those invariants, and the proposed database constraints would conflict with the designed API-owned participant merge/delete behavior or expand the source contract without a demonstrated Story 1.5 failure.

## Tests

The existing suite does not execute invalid provider timing through either production STT adapter, malformed bracketed/legacy timestamp headers at the stage boundary, transcript preambles before the first turn, a recording-to-transcript-only retry, or a NUL-bearing diarizer label. The regression tests required by findings 1–6 should prove the failure on the unfixed implementation before asserting the fix.

## Documentation

7. **[medium] The source-drop schema documents a different participant identity rule than the implementation** (`docs/source-drop.schema.json:46-50`; `server/meetingminer/pipeline/speakers.py:137-165`). The schema says participants are deduplicated by normalized display name, while the implemented and spec-amended rule uses namespaced mail when present and normalized name as fallback. This misstates the contract for source producers and operators. Correct the description to explain that AAD object IDs are ignored and that mail is preferred when supplied, with name normalization as fallback; no schema structure change is needed.

## Resolution

All seven findings were fixed after review. The focused regression suite passed 89 tests and the full server suite completed successfully. Story 1.5 now passes this review, subject to committing and pushing the review-fix follow-up.
