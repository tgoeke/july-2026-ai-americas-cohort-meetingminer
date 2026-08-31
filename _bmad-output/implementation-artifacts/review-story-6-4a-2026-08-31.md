# Story 6.4a Review — Upload Sessions

Date: 2026-08-31
Review branch: `story/6-4a-review`
Builder branch: `story/6-4a`
Builder head at review start: `be2c116f4452158d03850b62fee86be0aefa5a94`

## Scope

Adversarial review and red-first remediation of Story 6.4a Upload Sessions, with first priority on drop identity, staging/finalization atomicity, and bounded streaming. The frozen intent contract is review authority but is not patchable in this lane; owner decisions and frozen-spec defects remain open.

## Review range

`2d68dcc6..be2c116f4452158d03850b62fee86be0aefa5a94`

The review will also account for the required rebase onto `origin/main` before closeout.

## Findings

### F-1 — A truncated multipart body can be finalized as a complete upload

- **Location:** `server/meetingminer/uploads.py:882-904`
- **Severity:** High
- **Finding:** `create_session()` calls `MultipartParser.finalize()` and then immediately accepts `_finish()`/`write_session()`, but the installed `python-multipart` 0.0.32 implementation documents that `finalize()` does not verify the parser reached its terminal state. A connection that ends after a normal part boundary, but before the mandatory closing boundary, can therefore leave every required field/file callback complete and be recorded as a valid session rather than `upload-malformed`.
- **Evidence:** The dependency's runtime source says `MultipartParser.finalize()` is a no-op with a TODO to verify `MultipartState.END`; `create_session()` performs no state check of its own. This is exactly the socket-dies-mid-body case the hand-driven parser was meant to fail closed on. The directory remains hidden from intake, so this does not expose a partial drop, but it falsely promotes a truncated wire request into claimable session state.
- **Suggested direction:** After the stream and `finalize()`, require the parser's state to be `MultipartState.END`; otherwise raise the existing `upload-malformed` refusal so the outer failure path closes the handle and removes the session directory. Pin the behavior with a raw multipart regression whose required parts end at a non-final boundary and whose closing boundary is absent.

### F-2 — A lying `Content-Length` bypasses the only whole-request ceiling

- **Location:** `server/meetingminer/uploads.py:320-327`, `server/meetingminer/uploads.py:849-886`, and `server/meetingminer/uploads.py:663-677`
- **Severity:** High
- **Finding:** `max_body_bytes` is consulted only against the declared `Content-Length`; the actual bytes pulled from `body` are never counted, and `MultipartParser` is constructed with its infinite default `max_size`. Per-file/text caps and the installed parser's per-header limits still apply, but aggregate multipart overhead and bytes after the closing boundary are not covered by the configured whole-request ceiling. A client can declare a tiny length and stream an arbitrarily large epilogue after an otherwise valid multipart body; the parser is already in its terminal state, so the session is still created.
- **Evidence:** The stream loop passes every chunk directly to `parser.write()` without maintaining a received-byte total. Runtime inspection of `python-multipart` 0.0.32 confirms individual headers are bounded by the dependency (4,224 bytes and eight headers per part), but `MultipartParser.max_size` defaults to infinity. Thus the preflight check proves only that the client claimed a small body, not that the received body was small.
- **Suggested direction:** Count raw stream bytes before handing each chunk to the parser and raise `upload-too-large` as soon as the observed body exceeds `max_body_bytes`, without consuming another chunk. Size `max_body_bytes` for every supported evidence role plus bounded multipart overhead, and add a lying-header regression that currently succeeds despite exceeding the ceiling.

### F-3 — The declared ceiling rejects a valid three-file session

- **Location:** `server/meetingminer/uploads.py:320-327`
- **Severity:** Medium
- **Finding:** `max_body_bytes` budgets one recording and only one transcript, while the accepted evidence contract permits all three roles together: `recording.mp4`, `transcript.vtt`, and `transcript.txt`. Each transcript role is independently allowed up to `max_transcript_bytes`, so a valid near-cap three-file request is refused solely from `Content-Length`.
- **Evidence:** `_PartSink` maps `.vtt` and `.txt` to distinct canonical roles and applies `max_transcript_bytes` to each; `_finish()` accepts both. The preflight formula nevertheless adds `max_transcript_bytes` once. With a recording and both transcripts near their individual caps, the declared length necessarily exceeds that formula even though no part violates its cap.
- **Suggested direction:** Budget both transcript roles plus explicit bounded multipart overhead in `max_body_bytes`, and pin the arithmetic with a regression independent of allocating multi-gigabyte fixtures.

### F-4 — Repeated metadata silently changes a write-once meeting by part order

- **Location:** `server/meetingminer/uploads.py:742-746`
- **Severity:** Medium
- **Finding:** Duplicate text fields are silently overwritten, so two `title`, `startedAt`, `corpus`, `transcriptDialect`, or `suppliedBy` parts make the last value win. That gives one wire request two meanings and lets part order decide immutable drop metadata, even though duplicate evidence roles are explicitly refused.
- **Evidence:** `on_part_end()` assigns `self.fields[self._name] = ...` without checking whether the key is already present. The parser's part-count slack and duplicate-role rule show duplicates are expected hostile/buggy input, but only file roles fail closed.
- **Suggested direction:** Add a named 400 refusal for duplicate metadata and reject the second occurrence before accepting its value. Test two conflicting titles and assert both the RFC 9457 fields and empty staging root.

### F-5 — Upload filename normalization accepts an extension `mint-drop` refuses

- **Location:** `server/meetingminer/uploads.py:786-804`
- **Severity:** Medium
- **Finding:** `_canonical_for()` applies NFKD compatibility normalization before reading the suffix, while `mintdrop.classify_supplied()` reads `Path(...).suffix.lower()` from the operator's actual filename. A filename using a compatibility character such as the fullwidth dot (`recording．mp4`) is accepted as `.mp4` by upload but refused by `mint-drop`, contradicting the claimed shared role rule.
- **Evidence:** NFKD maps U+FF0E to ASCII `.`; `Path("recording．mp4").suffix` is empty before normalization. The same named input therefore crosses the upload door but not the canonical CLI door, so parity is not by construction for every accepted filename.
- **Suggested direction:** Strip browser path components but do not compatibility-normalize before suffix classification; use exactly the same suffix expression as `mintdrop.classify_supplied()`. Add a regression for the fullwidth-dot spelling.

### F-6 — Non-RFC-3339 timestamps are accepted despite the frozen boundary

- **Location:** `server/meetingminer/uploads.py:983-1002`
- **Severity:** Medium
- **Finding:** `_started_at()` delegates syntax entirely to `mintdrop.started_at_from_argument()`, whose `datetime.fromisoformat()` accepts a broader ISO 8601 language than RFC 3339. Uploads accept space-separated timestamps, basic dates/times, ISO week dates, and offsets containing seconds even though the frozen upload contract requires RFC 3339 with an offset.
- **Evidence:** Values such as `2026-08-05 12:00:19+00:00` and `20260805T120019+0000` reach second precision and are normalized rather than refused. Existing tests cover date-only, missing-offset, and junk inputs but not the RFC grammar boundary.
- **Suggested direction:** Gate upload input with an explicit RFC 3339 pattern (`T`, extended date/time, optional fractional seconds, and `Z` or `±HH:MM`) before calling the shared mint parser. Keep the shared parser for normalization so upload/CLI identity remains identical for the accepted subset.

### F-7 — Some completed sessions are guaranteed to fail only after the 201 response

- **Location:** `server/meetingminer/uploads.py:1005-1031` and `server/meetingminer/transcripts/dialects.py:262-290`
- **Severity:** Medium
- **Finding:** `_dialect()` accepts `transcriptDialect=zoom` when no VTT was uploaded, and accepts a Zoom VTT beside an uploaded TXT. The session is published as complete, but `dialects.convert_supplied()` later requires one VTT and forbids an accompanying TXT because Zoom conversion itself produces `transcript.txt`. These shapes can never mint.
- **Evidence:** `_dialect()` only requires a declaration when a VTT exists; once a non-empty known value is supplied it returns it without relating it to the staged roles. `_zoom_source()` deterministically raises for no VTT or any TXT. The request therefore answers 201 for an acquisition that can only become failed later.
- **Suggested direction:** Validate the declared dialect against the complete role set before `session.json` is published. Refuse Zoom without exactly a VTT and refuse Zoom plus TXT using the upload vocabulary, leaving the staging root empty.

### F-8 — Upload state and transcript failures fall into YouTube's `unclassified` rule

- **Location:** `server/meetingminer/acquisitions.py:377-396` and `server/meetingminer/acquisitions.py:1061-1069`
- **Severity:** Medium
- **Finding:** The upload runner catches `UploadSessionNotFound`, `UploadStateError`, and `dialects.DialectError`, then calls `refusal_for()`. That dispatcher recognizes only `UploadRefused`; every other upload-specific exception falls through `youtube.refusal_rule()` to `unclassified` with YouTube-owned remediation.
- **Evidence:** A session lost in a launch/delete/sweep race or a malformed Zoom transcript produces a failed acquisition, but its stable `rule` says only `unclassified` and tells the client to use the generic YouTube remediation. This contradicts the deliberate second closed vocabulary and AD-18's named degradation boundary.
- **Suggested direction:** Add explicit upload rules/remediations/statuses for unreadable/lost session state and transcript conversion refusal, and dispatch those exception classes before the YouTube classifier. Pin the two vocabularies as disjoint and complete.

### F-9 — Several acquisition failure paths skip the promised session cleanup

- **Location:** `server/meetingminer/acquisitions.py:778-817`, `server/meetingminer/acquisitions.py:1031-1111`, and `server/meetingminer/acquisitions.py:1182-1197`
- **Severity:** High
- **Finding:** Cleanup is only in `run_upload_acquisition()`'s `finally`, and even there `sessions` is assigned after `resolve_api_url()` and `resolve_drops_root()`. A resolution failure skips deletion; a detached child's config-load failure returns before entering the runner; and a log-open or `Popen` failure in the parent leaves the session despite writing/returning a failed acquisition.
- **Evidence:** These are ordinary host failures named by the existing refusal model, not process-kill hypotheticals. Each contradicts the frozen Always clause that a failed acquisition removes the session and can retain multi-gigabyte evidence until a later sweep.
- **Suggested direction:** Resolve/retain the sessions root before any fallible runner setup; pass the already trusted absolute sessions root to upload-mode child argv so pre-dispatch config failure can clean it; and compensate parent-side upload launch failures. Add red tests at each boundary.

### F-10 — A claimed or actively streaming session can be deleted underneath its owner

- **Location:** `server/meetingminer/acquisitions.py:821-868`, `server/meetingminer/uploads.py:555-598`, and `server/meetingminer/api/uploads.py:250-345`
- **Severity:** High
- **Finding:** The session itself has no claim visible to DELETE or the TTL sweep. `launch_upload()` reads it before taking the acquisition lock and does not re-read under that lock; DELETE never takes that lock; and the sweep knows nothing about live upload acquisitions. A later request can erase bytes after the API has returned 202. A second launch can also pre-read the session, wait for the first to become terminal, and then return another 202 for bytes being removed. For no-`session.json` directories, expiry uses directory mtime, which ordinary writes to an already-created file do not refresh; a long active stream can be swept too.
- **Evidence:** All three operations mutate/read the same session directory without one serialized ownership check. The acquisition record is the existing claim authority, but only another launch consults it. The sweep's comment says an in-flight upload must not be deleted out from under itself while its mtime rule permits exactly that once the configured TTL passes.
- **Suggested direction:** Serialize upload launch, DELETE, and sweeping against the acquisition claim lock; re-read inside the launch critical section; expose live upload-session ids so sweep skips them; refuse DELETE for a live claim; and age incomplete uploads from current file activity. Start the completed session TTL when the 201 state is published, not before a slow body is consumed.
