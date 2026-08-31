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
