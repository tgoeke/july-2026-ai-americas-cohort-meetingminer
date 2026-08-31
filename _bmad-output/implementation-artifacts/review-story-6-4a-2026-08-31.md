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

### F-11 — New acquisition refusals omit `rule` and `remediation`

- **Location:** `server/meetingminer/api/acquisitions.py:223-266`
- **Severity:** Medium
- **Finding:** The both-sources, neither-source, and upload-session-in-progress branches construct RFC 9457 problems without the `rule` and `remediation` extensions the frozen contract requires for every refusal.
- **Evidence:** The tests at `server/tests/test_api_uploads.py:760-809` assert only status/type for these paths and deliberately bypass the stronger `refusal()` helper. A client can render every upload parser failure uniformly but loses that contract on the most common acquisition-request mistakes and collision.
- **Suggested direction:** Give these upload acquisition paths stable rules and remediations in the upload vocabulary, preserve the existing problem types/IDs, and assert all three required fields in the HTTP tests.

### F-12 — An `exists` result falsely claims the upload session produced the old drop

- **Location:** `server/meetingminer/acquisitions.py:1098-1106`
- **Severity:** Medium
- **Finding:** The runner always writes `tool="upload-session"` to the acquisition status, including when `mint()` returned `exists` for a drop previously produced by `mint-drop` or another producer. In that case the status source disagrees with the immutable drop provenance it is meant to summarize.
- **Evidence:** `run_acquisition()` derives tool/version from `result.metadata`; the new upload runner hardcodes the tool. The story's own identity test creates a hand-minted drop first and then reaches `exists`, so production would report that hand-minted drop as upload-produced.
- **Suggested direction:** Derive status source fields from `result.metadata.provenance` for both created and existing outcomes. A newly created upload still reports `upload-session`; an existing hand mint reports `mint-drop`.

### F-13 — Final hashing and ffprobe block the API event loop

- **Location:** `server/meetingminer/uploads.py:742-769`, `server/meetingminer/uploads.py:897-955`, and `server/meetingminer/pipeline/media.py:34`
- **Severity:** High
- **Finding:** The async request handler synchronously rereads each completed file to hash it and then runs ffprobe inline. At the configured 8 GiB recording cap this blocks the API event loop for a full second disk pass; ffprobe itself permits a 600-second timeout, during which unrelated API requests cannot advance.
- **Evidence:** `_PartSink.on_part_end()` calls `sha256_and_size()` synchronously after the stream already wrote and counted the bytes, and `_finish()` calls `_assert_video_within_cap()` synchronously from `create_session()`. The hand-driven parser avoids boot-volume spooling but still monopolizes the one async loop at finalization.
- **Suggested direction:** Maintain the SHA-256 incrementally in `on_part_data` and use the existing byte counter at part end. Offload the blocking probe to a worker thread while keeping session publication awaited and failure cleanup unchanged.

### F-14 — An overlong boundary escapes the named multipart refusal path

- **Location:** `server/meetingminer/uploads.py:868-893`
- **Severity:** Medium
- **Finding:** `MultipartParser(...)` is constructed before the parser-error `try`. The installed dependency rejects a boundary longer than 256 bytes from its constructor, so client-controlled malformed input escapes as an unstructured internal error rather than `upload-malformed` with rule/detail/remediation.
- **Evidence:** Runtime inspection of `python-multipart` 0.0.32 shows the constructor raises `FormParserError` when `len(boundary) > MAX_BOUNDARY_LENGTH`. Only exceptions from stream iteration, `parser.write()`, and `finalize()` are translated today; the outer block merely cleans the directory and re-raises.
- **Suggested direction:** Put parser construction inside the same translation boundary (or validate the boundary before creating a directory) and add an HTTP regression for an overlong boundary.

### F-15 — Story backlog IDs collide with the current integration branch

- **Location:** `docs/backlog.md` (`B-53` and `B-54` added by Story 6.4a)
- **Severity:** Low
- **Finding:** `origin/main` now owns B-53 for Story 8.2a, while this branch independently added B-53 and B-54. Rebasing as required would leave duplicate identifiers and make references ambiguous.
- **Evidence:** `git show origin/main:docs/backlog.md` contains `B-53 · Let the api report the worker's loaded binding...`; the two Story 6.4a entries are `A failed upload acquisition...` and `Nothing reaps an acquisition's status file`. The owner explicitly reserved the next free IDs above B-54 for this lane.
- **Suggested direction:** Renumber only Story 6.4a's two entries to B-55 and B-56 during the rebase; do not alter another lane's identifiers.

### F-16 — The identity test cannot detect an upload-side timestamp regression

- **Location:** `server/tests/test_api_uploads.py:934-989`
- **Severity:** Medium
- **Finding:** The hand mint runs first, so the upload runner reaches `mint()`'s `exists` short-circuit before `started_at_argument` is evaluated. The final `startedAt` assertion therefore rechecks only the hand-created drop and would stay green if the upload path passed the wrong timestamp or omitted it. Identity coverage also exercises Zoom VTT and plain TXT only, not recording-primary or Teams/pass-through construction.
- **Evidence:** `mint()` returns from `find_existing_drop()` at `server/meetingminer/mintdrop.py:707-715`; timestamp resolution occurs later at lines 717-723. Thus the test proves converted-byte identity/`exists`, but not the claimed upload-side timestamp/precision equivalence.
- **Suggested direction:** Add upload-first/direct-result construction tests over every supported primary/dialect shape, and demonstrate their sensitivity with a temporary mutation of the runner's timestamp argument before retaining only the green code.

### F-17 — The real detached upload argv and CLI dispatch are untested

- **Location:** `server/meetingminer/acquisitions.py:701-728`, `server/meetingminer/acquisitions.py:1198-1212`, and `server/tests/test_api_uploads.py:733-749`
- **Severity:** Medium
- **Finding:** Upload launch tests replace `child_command()` wholesale with `/bin/sleep`, while runner tests invoke `run_upload_acquisition()` directly. No test proves production emits `--upload-session` or that `main()` routes that flag to the upload runner.
- **Evidence:** Changing the emitted flag to `--url`, or dispatching upload mode to `run_acquisition()`, leaves the current 202 launch and direct-runner tests green.
- **Suggested direction:** Pin the exact upload child command and drive `main()` with upload arguments while stubbing only the terminal runner call.

### F-18 — A live upload request can still be swept as abandoned

- **Location:** `server/meetingminer/api/uploads.py:257-282` and `server/meetingminer/uploads.py:603-646`
- **Severity:** High
- **Finding:** The create route releases the acquisition claim lock before streaming begins, while an incomplete staging directory has no ownership marker. A concurrent `POST /uploads` can therefore sweep a request that is still receiving bytes or awaiting ffprobe once its latest file activity is older than the configured TTL.
- **Evidence:** The sweep deliberately deletes no-`session.json` directories by child-file mtime, and the current one-minute test configuration is shorter than ffprobe's permitted 600-second timeout. The existing incomplete-directory test proves such a directory is removed; it never establishes that no request owns it.
- **Suggested direction:** Give every in-flight create a process-visible ownership marker that sweep excludes, remove it on every exit, and test a sweep interleaved with a controlled live request. Do not hold the blocking filesystem claim lock across an awaited multi-gigabyte stream.

### F-19 — Failed deletion can publish terminal ownership beside a reusable session

- **Location:** `server/meetingminer/uploads.py:582-598` and `server/meetingminer/acquisitions.py:1061-1078`
- **Severity:** High
- **Finding:** `discard_session()` suppresses recursive-delete errors and returns `False`, but `_complete_upload_record()` ignores that result and writes `posted` or `failed`. A complete session can remain claimable beside a terminal record, reopening the duplicate-consumer window the ownership remediation claims to close.
- **Evidence:** Injecting an `rmtree` failure leaves `session.json` and all evidence intact; `launch_upload()` consults only live records, so it can claim the same session again after the first record becomes terminal. DELETE also translates failed removal into a misleading 404.
- **Suggested direction:** Make deletion failure a named upload-state error and never publish terminal status unless the session is absent after cleanup. Pin both terminal completion and DELETE with a failed-removal regression.

### F-20 — Upload infrastructure failures still omit RFC 9457 refusal extensions

- **Location:** `server/meetingminer/api/uploads.py:285-286`, `server/meetingminer/api/uploads.py:312-313`, `server/meetingminer/api/uploads.py:358-359`, and `server/meetingminer/api/acquisitions.py:280-281`
- **Severity:** Medium
- **Finding:** Several upload state and acquisition-start failures still construct bare Problems without `rule` and `remediation`, despite the frozen contract requiring `rule`, `detail`, and `remediation` on every refusal.
- **Evidence:** `upload-session-unreadable` already exists in the closed upload vocabulary, but the upload router bypasses the shared refusal helper. `AcquisitionStateError` similarly returns `acquisition-state-unwritable` without the two extensions.
- **Suggested direction:** Route every upload state/start failure through stable rules in the upload vocabulary and assert the full three-field shape for POST, GET, DELETE, and acquisition launch failures.

### F-21 — A duplicate YouTube launch receives upload-session remediation

- **Location:** `server/meetingminer/api/acquisitions.py:267-279`
- **Severity:** Medium
- **Finding:** The shared `AcquisitionInProgress` handler always uses the upload vocabulary's remediation, which tells the client not to delete an upload session. A YouTube acquisition has no upload session.
- **Evidence:** Both launch kinds raise the same exception class, while the handler does not inspect `record.kind`. Existing YouTube collision coverage asserts IDs and type but not the remediation text.
- **Suggested direction:** Select a kind-appropriate stable rule/remediation while preserving YouTube's pinned refusal vocabulary, and add assertions for both source kinds.

### F-22 — Existing YouTube provenance loses its tool version through the upload door

- **Location:** `server/meetingminer/acquisitions.py:1190-1208`
- **Severity:** Medium
- **Finding:** Upload acquisition reads only `provenance.toolVersion`, while immutable YouTube drops store the value as `ytDlpVersion`. Rediscovering such a drop reports `tool=yt-dlp` with a null version even though the direct YouTube path reports the version.
- **Evidence:** The direct runner explicitly reads `ytDlpVersion`; the upload runner's generalized provenance branch does not. This is observable only for an `exists` result whose winning drop came from YouTube.
- **Suggested direction:** Derive the version according to the immutable provenance tool, covering both `toolVersion` and `ytDlpVersion`, and pin a pre-existing YouTube drop.

### F-23 — A terminal status-write failure strands a dead record as running

- **Location:** `server/meetingminer/acquisitions.py:1061-1078` and `server/meetingminer/acquisitions.py:1211-1217`
- **Severity:** High
- **Finding:** `_complete_upload_record()` removes the session before writing the terminal record. If that write fails, the runner's `finally` only retries deletion; the previous `running` record remains with a dead PID even when mint and intake succeeded.
- **Evidence:** `main()` catches the resulting acquisition error and exits, but there is no second durable status path after the session is already gone. The status surface therefore reports stale progress rather than terminal degradation.
- **Suggested direction:** Make terminal publication recoverable without exposing a reusable session—preserve enough state for a retry/compensating failed write—and add an injected write-failure regression that cannot leave a live-looking record.

### F-24 — Identity parity is not pinned for multi-file and non-Zoom acquisition paths

- **Location:** `server/tests/test_api_uploads.py:1338-1448`
- **Severity:** Medium
- **Finding:** Exact hand-mint/upload equality is asserted only for Zoom VTT. Plain VTT, Teams VTT, TXT, and recording assert upload-side timestamp fields without comparing the winning drop, and no runner test supplies multiple evidence files.
- **Evidence:** Hard-coding Zoom conversion for every VTT or returning only the first staged path would leave the current identity matrix green while changing source identity or silently dropping secondary evidence.
- **Suggested direction:** Compare upload and hand mint for every supported primary/dialect shape and at least one recording-plus-transcript combination, asserting `sourceId`, `startedAt`, precision, `exists`, and the complete evidence set.

### F-25 — Launch-to-child argument composition is still mocked away

- **Location:** `server/tests/test_api_uploads.py:946-1038`
- **Severity:** Medium
- **Finding:** `child_command()` and CLI dispatch are tested independently, but successful API launch replaces `child_command()` wholesale. No assertion proves `launch_upload()` supplies the claimed session id and resolved upload root to the real command builder.
- **Evidence:** Passing the acquisition id as `upload_session_id`, or the acquisition-state root as `sessions_root`, would leave both isolated tests green.
- **Suggested direction:** Exercise a real launch while replacing only `Popen`, capture its argv, and assert both ownership arguments.

### F-26 — The ownership protocol is verified only sequentially

- **Location:** `server/tests/test_api_uploads.py:1117-1164`
- **Severity:** High
- **Finding:** Launch, DELETE, sweep, and terminal cleanup rely on one lock, but tests perform every competing action only after launch completes. They cannot detect a removed or misplaced critical section.
- **Evidence:** Removing the sweep's lock leaves the current protected-session test green because its snapshot is already live; a real interleaving can take the snapshot before launch and delete after the claim.
- **Suggested direction:** Use barriers to interleave launch with DELETE/sweep and terminal cleanup with a second launch, then assert no claimed bytes disappear and no consumed session launches twice.

### F-27 — Slow-upload TTL behavior is unobserved

- **Location:** `server/tests/test_api_uploads.py:880-918`
- **Severity:** Medium
- **Finding:** No test proves TTL starts after body completion or that active child-file writes keep an incomplete staging directory alive. The existing incomplete-session test uses an empty directory and only proves eventual deletion.
- **Evidence:** Capturing `now` before streaming or reducing activity age to directory mtime would leave the suite green and can publish a nearly expired session or sweep a request still writing.
- **Suggested direction:** Drive `create_session()` with a controlled async body/clock and test an old directory containing a freshly modified in-progress file.

### F-28 — Rebase documentation still assigns this story other lanes' backlog IDs

- **Location:** `_bmad-output/implementation-artifacts/spec-6-4a-upload-sessions.md:224,297-300` and this report's F-15
- **Severity:** Low
- **Finding:** After the required rebase, the backlog correctly assigns Story 6.4a B-57/B-58, but the spec still claims B-55/B-56 and warns that B-56 remains unresolved. The report's original suggested direction is likewise stale.
- **Evidence:** Current main owns B-55/B-56 for Story 12.1; `docs/backlog.md` contains the upload entries at B-57/B-58 with no duplicate headings.
- **Suggested direction:** Update only Story 6.4a's spec/report references to B-57/B-58 and record that the integration collision is resolved.
