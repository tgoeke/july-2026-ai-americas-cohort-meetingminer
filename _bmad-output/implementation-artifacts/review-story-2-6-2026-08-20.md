# Code review — Story 2-6: Source-drop schema reloaded on change

Date: 2026-08-20

## Review target

- Repository: `/Users/devopsterus/current/cohort/meetingminer`
- Branch: `story/2-6` at `75878be8a74e68d2430e34160d8c98db6b9b7362`
- Range: `444469d7b140bbc963baed30e5b04180371e2198...75878be8a74e68d2430e34160d8c98db6b9b7362`
- Frozen contract: `_bmad-output/implementation-artifacts/spec-2-6-source-drop-schema-reloaded-on-change.md`

## Initial verdict: fail — seven fixes required before merge

### Medium

1. **An unloadable schema does not win every `POST /ingests`.**
   [`server/meetingminer/api/ingests.py:849`](../../server/meetingminer/api/ingests.py#L849) calls `_load_metadata()` before any schema check; [`_load_metadata():355-375`](../../server/meetingminer/api/ingests.py#L355) returns its own `422 invalid-drop` errors before calling `_validator()`. Consequently a deleted/corrupt schema plus malformed `metadata.json` misattributes the process fault to the drop, violating the “stat per request” and “any drop” acceptance criterion. Direct reproduction on this revision: install a temporary schema, delete it, then call `_load_metadata()` with `{ malformed`; it returns `422 invalid-drop`. Move/reuse the schema check so it occurs before metadata parsing and add the precedence regression test.

2. **An unresolvable `$ref` escapes as a generic internal error.**
   [`server/meetingminer/api/ingests.py:159`](../../server/meetingminer/api/ingests.py#L159) accepts a schema with an external `$ref` because `check_schema()` validates syntax, but [`:375`](../../server/meetingminer/api/ingests.py#L375) can raise `jsonschema.exceptions._WrappedReferencingError` while evaluating it. That exception is not in `_SCHEMA_LOAD_ERRORS`, so the client does not receive the required `drop-schema-unreadable` problem. Convert that error into the named 500 (with the error event) and cover it with a route test.

### Low

3. **The inode-based reload protection is untested.**
   [`server/tests/test_ingests.py:1317`](../../server/tests/test_ingests.py#L1317) proves only the size part of the signature. Removing `st_ino` from [`ingests.py:227`](../../server/meetingminer/api/ingests.py#L227) keeps the suite green. Test a same-size, mtime-preserving atomic replacement and assert the changed schema takes effect.

4. **The new failed-reload diagnostic event is untested.**
   [`server/tests/test_ingests.py:1352`](../../server/tests/test_ingests.py#L1352) asserts only the HTTP problem. It does not capture the `drop_schema_load_failed` stderr event emitted at [`ingests.py:237`](../../server/meetingminer/api/ingests.py#L237). Add a structured-event assertion so this observability safeguard cannot silently regress.

5. **The startup `SchemaError` path is untested.**
   [`server/tests/test_failfast.py:114`](../../server/tests/test_failfast.py#L114) has missing-file and malformed-JSON cases but no valid-JSON, invalid-schema case. Add `{"type": 42}` and retain the exit-1/named-error/no-traceback assertions.

6. **The non-object schema guard is untested.**
   [`server/tests/test_ingests.py:1338`](../../server/tests/test_ingests.py#L1338) tests an invalid object only. Add a boolean JSON schema case, such as `true`, to pin the explicit guard at [`ingests.py:152`](../../server/meetingminer/api/ingests.py#L152).

7. **The reviewer handoff names the wrong commit count.**
   [`review-prompt-story-2-6-2026-08-20.md:12`](review-prompt-story-2-6-2026-08-20.md#L12) calls `444469d..HEAD` a five-commit range, although `HEAD` includes `75878be` and the range has six commits. Correct the range or name the intended five-commit endpoint explicitly.

## Dismissed after source review

- The stat/read timing window and concurrent duplicate reload observations are deliberate, documented consequences of the contract’s stat-per-request/no-lock design; they converge on the next request and do not require a watcher or lock.
- An in-place same-size rewrite with a deliberately restored mtime and same inode is the documented stat-only residual risk. Adding ctime changes the defined signature without eliminating all platform-specific races.
- The existing validator-identity assertion meets the explicit unchanged-file acceptance criterion; a read spy would only strengthen an internal implementation test.
- Startup and request-time events share `install_drop_schema()`, so a separate startup-only event assertion would duplicate the same emission path.
- The frozen contract does not require `$id` to be mandatory, nor a permission/decoding-only test; its existing path/error coverage is adequate for this review.
- Adding inode strengthens, rather than contradicts, the contract’s mtime-and-size minimum; the spec’s review log records that choice.

## Verification performed

- `uv run --project server pytest server/tests/test_ingests.py server/tests/test_drop_schema.py -q` — **86 passed** (1 pre-existing Starlette/httpx deprecation warning).
- `uv run --project server pytest server/tests/test_failfast.py -q` — **10 passed** (1 pre-existing Starlette/httpx deprecation warning).

No production code was changed by the initial review.

## Remediation outcome

All seven review findings were applied on `story/2-6` and re-verified in this
review session. The route now checks the schema before every drop-level error,
unresolvable references fail closed with the required problem and operator
event, and the additional regression coverage exercises inode replacement,
boolean schemas, startup `SchemaError`, and the failed-reload event.

**Post-remediation verdict: pass.**

- `uv run --project server pytest server/tests/test_ingests.py server/tests/test_drop_schema.py -q` — **90 passed**.
- `uv run --project server pytest server/tests/test_failfast.py -q` — **11 passed**.
