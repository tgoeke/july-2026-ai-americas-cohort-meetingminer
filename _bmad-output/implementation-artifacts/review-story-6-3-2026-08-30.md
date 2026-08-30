# Adversarial Review — Story 6.3

Date: 2026-08-30
Review branch: `story/6-3-review`
Source branch: `story/6-3`
Review range: `d72c658..4877cf2`

## Scope

Adversarial review of Story 6.3, Local-Files Acquisition with Transcript
Dialect Conversion, against its frozen intent contract and the architecture
authorities named in the review dispatch. The review covers only the dispatched
Story 6.3 footprint and treats the verbatim Story 6.2 override hunk as context.

## Findings

### F1 — Transcript-only identity ignores speaker attribution

- **Location:** `server/meetingminer/transcripts/dialects.py:220-225`; `server/meetingminer/mintdrop.py:652-679`
- **Severity:** high
- **Finding:** A transcript-only Zoom conversion derives `sourceId` from the generated speaker-less VTT, not from the original export or both generated artifacts. Two exports with identical timings and words but different speaker labels therefore collide. The second mint reports `exists`, and `_evidence_not_in()` cannot warn about the different `transcript.txt` because the existing drop already has that canonical filename.
- **Evidence:** A direct reproduction converted `Alice: identical words` and `Bob: identical words`. Their generated `transcript.txt` bytes and original-file digests differed, but `_digest_supplied(classify_supplied(...))[0]` produced the same `sha256:d53bde...` identity for both because `transcript.vtt` is ordered before `transcript.txt`. This is also why pinning deterministic output bytes does not protect attribution: it pins the collision-producing VTT bytes.
- **Suggested direction:** **Open — frozen-spec decision required.** Amend the identity contract so transcript-only Zoom drops use the operator's original-file digest, or a deterministic digest covering both converted transcript artifacts. Do not silently patch around the frozen statement that identity remains the converted bytes' primary digest.
- **Resolution:** **OPEN.** No code change was made because the frozen identity contract must be amended first.

### F2 — Malformed cue delimiter silently drops evidence

- **Location:** `server/meetingminer/transcripts/dialects.py:327-346`; `server/tests/test_transcript_dialects.py:431-444`
- **Severity:** high
- **Finding:** `read_zoom_cues()` only validates lines containing the exact substring `-->`. The frozen edge-case example `00:00:01 -> bad` is skipped as non-timing text; if a later valid named cue exists, conversion succeeds after discarding the malformed cue and its words.
- **Evidence:** A direct reproduction with the malformed Alice cue followed by a valid Bob cue was accepted and produced only `Bob | 00:03\nkept`. The existing malformed-timing test uses a valid `-->` delimiter with an invalid endpoint, so it never exercises the pre-validation skip.
- **Suggested direction:** Add a regression test using the frozen single-arrow example plus a later valid cue, then reject timing-like arrow lines by name and line number before any workspace output is written.
- **Resolution:** Fixed red-first in `77c805c`.

### F3 — Speaker extraction violates the first-payload-line rule

- **Location:** `server/meetingminer/transcripts/dialects.py:342-346`
- **Severity:** high
- **Finding:** The converter joins every payload line before calling `_split_speaker()`, although the frozen contract permits a speaker only on the cue's first payload line. A colon on a later line can turn preceding speech into an invented speaker label.
- **Evidence:** A cue whose payload was `Good morning` followed by `Alice: hello` minted as `Good morning Alice | 00:01\nhello`; the never-guess rule requires an unattributed turn containing all of those words.
- **Suggested direction:** Add a multiline-cue regression test, classify only the cleaned first payload line for a speaker prefix, and append later cleaned payload lines only as speech.
- **Resolution:** Fixed red-first in `895af76`.

### F4 — Reverse cue timing is silently rewritten

- **Location:** `server/meetingminer/transcripts/dialects.py:340-352`
- **Severity:** medium
- **Finding:** A cue whose end precedes its start is accepted and rewritten as a zero-duration cue through `max(end_ms, start_ms)`. This changes source evidence instead of failing closed and named.
- **Evidence:** `00:00:03.000 --> 00:00:01.000` with `Alice: hello` was accepted, rendered into the trusted text transcript at `00:03`, and emitted into the timing VTT as `00:00:03.000 --> 00:00:03.000`.
- **Suggested direction:** Add a red regression test and refuse the timing line with its source line number when `end_ms < start_ms`.
- **Resolution:** Fixed red-first in `77c805c`.

### F5 — Unattributed cues are asserted to be one speaker

- **Location:** `server/meetingminer/transcripts/dialects.py:419-430`, `:241-243`
- **Severity:** medium
- **Finding:** `zoom_turns()` maps every missing speaker to `Unknown` and then merges adjacent cues on that placeholder equality. Missing attribution is not evidence that two cues have the same speaker. The same implementation also records `Unknown` in provenance `speakerLabels`, presenting a placeholder as a discovered source label.
- **Evidence:** Two adjacent unprefixed cues after one named cue became one `Unknown` turn (`first unknown second unknown`), reduced `turnCount` from three cues to two turns, and emitted `speakerLabels: ["Alice", "Unknown"]`.
- **Suggested direction:** Merge only when the current cue carries a real speaker equal to the preceding turn's speaker. Derive `speakerLabels` from non-null cue labels so placeholders never appear as discovered labels.
- **Resolution:** Fixed red-first in `a435a82`.

### F6 — Whole-second legacy stamps can erase a speaker turn's duration

- **Location:** `server/meetingminer/transcripts/dialects.py:434-449`; `server/meetingminer/pipeline/alignment.py:153-170`
- **Severity:** medium
- **Finding:** Truncating every legacy start to a whole second gives two speaker changes within one second the same start. The first turn's VTT matching window then ends at that same truncated start, before either real cue begins, so it receives no VTT end and falls back to a zero-duration boundary.
- **Evidence:** Provided starts representing cues at 1.100s and 1.900s both become 1.000s. `merge_vtt_end_timings()` returned `(None, 2200)`; `resolve_end_times()` consequently bounds the first turn at the following 1.000s start. This is a concrete downstream consequence of the frozen truncation decision.
- **Suggested direction:** **Deferred by owner ruling dated 2026-08-30.** Keep the truncation contract and converter unchanged until real Zoom exports in the new corpus show sub-second speaker changes. Preserve the reproduction in `deferred-work.md`; add only a named warning so a future occurrence becomes measurable evidence.
- **Resolution:** **DEFERRED.** The exact reproduction and revisit trigger are recorded in `deferred-work.md`. A red-first regression proved the existing fallback still stores `(1000, 1000)` then `(1000, 2200)` and now emits `stage.align.zero-duration-fallback` with the meeting, affected turn, and both colliding stamps. No converter or timing behavior changed.

### F7 — Original-file provenance can hash different bytes than were converted

- **Location:** `server/meetingminer/transcripts/dialects.py:203-216`
- **Severity:** medium
- **Finding:** The source is read once for conversion and reopened later for provenance hashing. If it changes between those reads, the trusted outputs describe the first snapshot while the only durable original-file digest describes the second.
- **Evidence:** A deterministic reproduction replaced the source after `_read_source()` returned but before `sha256_and_size()`. The output remained `Alice | 00:01\noriginal`, while provenance recorded the replacement bytes' digest rather than the converted snapshot's digest.
- **Suggested direction:** Read the source bytes once, decode and hash that same in-memory snapshot, and add a regression test that mutates the path after the snapshot while asserting provenance remains tied to the converted bytes.
- **Resolution:** Fixed red-first in `df5b7d9`.

### F8 — A missing cue separator merges two cues into fabricated speech

- **Location:** `server/meetingminer/transcripts/dialects.py:342-346`
- **Severity:** high
- **Finding:** The cue-body loop consumes until a blank line without recognizing that another timing line has started. When the separator is missing, the next cue's timing, speaker, and words become literal speech in the first cue; the second timing is lost.
- **Evidence:** Two otherwise valid cues without the intervening blank line were accepted as one Alice turn whose text was `first 00:00:03.000 --> 00:00:04.000 Bob: second`; the emitted VTT likewise contained one cue only.
- **Suggested direction:** Add a red malformed-structure test and refuse a timing line encountered inside a cue body, naming the missing separator and line number.
- **Resolution:** Fixed red-first in `77c805c`.

### F9 — Out-of-order cues enter the trusted transcript unchanged

- **Location:** `server/meetingminer/transcripts/dialects.py:325-370`
- **Severity:** medium
- **Finding:** Cue chronology is never checked. The converted text can therefore move from a later start back to an earlier start, while downstream text-turn processing assumes provided order and only the VTT side is sorted.
- **Evidence:** A 5-second Alice cue followed by a 1-second Bob cue was accepted and rendered in that source order (`Alice | 00:05`, then `Bob | 00:01`).
- **Suggested direction:** Add a red test and refuse a cue whose start precedes the previous accepted cue's start, naming both the offending line and chronology rule.
- **Resolution:** Fixed red-first in `77c805c`.

### F10 — The claimed WebVTT gate accepts malformed signatures and stamps

- **Location:** `server/meetingminer/transcripts/dialects.py:112-115`, `:317-340`
- **Severity:** low
- **Finding:** Header validation accepts any prefix beginning with `WEBVTT`, and the timing regex permits a decimal separator with no fractional digits. Files beginning `WEBVTT-NOT-A-HEADER` and cues stamped `00:00:01.` are normalized and minted despite the converter's stated strictness.
- **Evidence:** Both malformed inputs were accepted in direct reproductions and produced ordinary trusted transcript files.
- **Suggested direction:** Require the WebVTT signature token followed only by permitted header text/whitespace, and require at least one fractional digit whenever `.` or `,` is present.
- **Resolution:** Fixed red-first in `77c805c`.

### F11 — A valid no-space speaker delimiter loses attribution

- **Location:** `server/meetingminer/transcripts/dialects.py:119-121`, `:385-398`
- **Severity:** medium
- **Finding:** The frozen rule defines the speaker as text before the first colon, but `_PREFIXED` requires whitespace after that colon. `Alice:hello` is therefore demoted to `Unknown`, even though no ambiguity exists about the delimiter.
- **Evidence:** A reproduction minted `Unknown | 00:01\nAlice:hello` while a later `Bob: kept` cue supplied the one recognized speaker needed to pass the file-level guard.
- **Suggested direction:** Add a red test and accept zero or more spaces after the first colon while retaining the existing conservative checks on the prefix itself.
- **Resolution:** Fixed red-first in `895af76`.

### F12 — Conversion write failures escape the named-refusal boundary

- **Location:** `server/meetingminer/transcripts/dialects.py:211-216`; `server/meetingminer/mintdrop.py:1095-1112`
- **Severity:** medium
- **Finding:** Writes of the generated transcript files and the later source hash are not wrapped as `DialectError`. A permission failure, full disk, or disappearance race can escape `main()`'s caught taxonomy as an `OSError` traceback instead of the repository's named refusal.
- **Evidence:** `_read_source()` translates read errors and `mint()` translates copy/read errors, but both `Path.write_text()` calls are direct and `main()` catches only `ConfigError`, `MintError`, and `DialectError`.
- **Suggested direction:** Add a red CLI-level write-failure test, translate conversion workspace I/O failures to `DialectError` with the affected path, and keep refusal before any drop finalization.
- **Resolution:** Fixed red-first in `df5b7d9`.

### F13 — Descending starts can reach the same silent zero-duration fallback

- **Location:** `server/meetingminer/pipeline/stages/align.py:589-605`; `server/tests/test_worker_transcripts.py`
- **Severity:** medium
- **Finding:** The first F6 warning predicate required two equal starts, but `resolve_end_times()` also returns a zero-duration fallback when the following parsed start is earlier. The named event therefore did not cover every fallback behavior its name and the owner ruling describe.
- **Evidence:** A red-first reproduction used legacy turns at 2.000s then 1.000s. The first stored boundary remained `(2000, 2000)`, but no `stage.align.zero-duration-fallback` event was emitted until the predicate accepted a following start less than or equal to the affected start.
- **Suggested direction:** Treat `following.start_ms <= segment.start_ms` as a colliding fallback for warning purposes only, retaining the two distinct stamp fields and making no timing or acceptance change.
- **Resolution:** Fixed red-first in the follow-up review patch; the exact commit is recorded at closeout.

## Triage and verification

- Triage: 1 decision-needed, 11 patch, 1 deferred, 11 dismissed as noise,
  by-design behavior, known deferred work, or out-of-scope Story 6.2 mechanics.
- Pipeline footprint: `git diff d72c658..story/6-3 --
  server/meetingminer/pipeline/` was empty.
- Story 6.2 coupling: the `f145c1e` override diff is byte-for-byte identical to
  commit `7625b79`. Merging `story/6-2-review` produced only the documented
  `normalized_extra` conflict; taking that hardened block preserved
  `transcriptDialect`, and the combined `test_transcript_dialects.py` plus
  `test_mint_drop.py` surface passed 114 tests.
- Mutation sample: deleting `verify_legacy_text(...)` was killed by
  `test_an_utterance_shaped_like_a_legacy_header_is_refused`; passing
  `args.files` instead of `conversion.supplied` was killed by
  `test_a_zoom_mint_holds_both_transcripts_and_records_the_dialect`.
- `uv run --project server pytest server/tests/test_transcript_dialects.py -q`
  — 46 passed.
- F6 warning regression: the targeted test first failed with no
  `stage.align.zero-duration-fallback` event while reproducing stored boundaries
  `(1000, 1000)` and `(1000, 2200)`, then passed after the warning-only stage
  change.
- Follow-up combined surface: `test_worker_transcripts.py` plus
  `test_transcript_dialects.py` — 78 passed after the F13 patch.
- `make test-fast` — puller 128 passed, web 291 passed, eval harness 549
  passed, server fast set 1447 passed with 326 slow tests deselected.
- `make test` — puller 128 passed, web 291 passed, eval harness 549 passed,
  server 1773 passed in 9m14s, and the production web build passed.
- `python3 _bmad/scripts/branch_conflicts.py --against story/6-3-review` —
  clean against `main`, `story/6-2`, and `story/6-3`; the documented one-block
  conflict remains against `story/6-2-review`.
- `make check-reviews` — passed; every dispatched review has a committed
  report.

## Verdict

**CHANGES REQUESTED.** Twelve patchable or owner-directed findings are fixed or
deferred with observability. The story does not pass review and must not merge
while F1 remains open: transcript-only identity can ignore corrected speaker
attribution, and resolving that requires a separate owner ruling and frozen-spec
amendment. F6 is deferred under the 2026-08-30 owner ruling and is not an open
merge decision.
