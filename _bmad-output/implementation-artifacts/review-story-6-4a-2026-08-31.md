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
