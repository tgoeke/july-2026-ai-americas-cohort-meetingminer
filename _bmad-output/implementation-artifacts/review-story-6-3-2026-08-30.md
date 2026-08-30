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

### F2 — Malformed cue delimiter silently drops evidence

- **Location:** `server/meetingminer/transcripts/dialects.py:327-346`; `server/tests/test_transcript_dialects.py:431-444`
- **Severity:** high
- **Finding:** `read_zoom_cues()` only validates lines containing the exact substring `-->`. The frozen edge-case example `00:00:01 -> bad` is skipped as non-timing text; if a later valid named cue exists, conversion succeeds after discarding the malformed cue and its words.
- **Evidence:** A direct reproduction with the malformed Alice cue followed by a valid Bob cue was accepted and produced only `Bob | 00:03\nkept`. The existing malformed-timing test uses a valid `-->` delimiter with an invalid endpoint, so it never exercises the pre-validation skip.
- **Suggested direction:** Add a regression test using the frozen single-arrow example plus a later valid cue, then reject timing-like arrow lines by name and line number before any workspace output is written.

### F3 — Speaker extraction violates the first-payload-line rule

- **Location:** `server/meetingminer/transcripts/dialects.py:342-346`
- **Severity:** high
- **Finding:** The converter joins every payload line before calling `_split_speaker()`, although the frozen contract permits a speaker only on the cue's first payload line. A colon on a later line can turn preceding speech into an invented speaker label.
- **Evidence:** A cue whose payload was `Good morning` followed by `Alice: hello` minted as `Good morning Alice | 00:01\nhello`; the never-guess rule requires an unattributed turn containing all of those words.
- **Suggested direction:** Add a multiline-cue regression test, classify only the cleaned first payload line for a speaker prefix, and append later cleaned payload lines only as speech.

## Verdict

Pending review and verification.
