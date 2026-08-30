---
title: 'Source-drop schema reloaded on change'
type: 'bugfix'
created: '2026-08-20'
status: 'done'
baseline_revision: '0513c6167df163a84917e43a05863e10c4bbc5e3'
review_loop_iteration: 1
followup_review_recommended: false
context: []
warnings: [oversized]
deferred: []
---

<intent-contract>

## Intent

**Problem:** The api reads `docs/source-drop.schema.json` once at startup (`ingests.load_drop_schema`) into a module global and nothing ever invalidates it — uvicorn `--reload` watches `.py` only. In operation (2026-08-19) this cost 28 false `422 invalid-drop` refusals against a schema file that had accepted those drops for six hours: the fault was a stale process, but it presented as bad drops. (Sprint id `2-6-source-drop-schema-reloaded-on-change`; not in `epics.md` — contract is the `deferred-work.md` entry.)

**Approach:** Keep the fail-fast startup gate, but record the loaded schema's file identity (path, `st_mtime_ns`, `st_size`) and re-stat it on each `POST /ingests`; on change, re-read and swap the validator. A reload that fails (file gone, unreadable, invalid JSON, invalid schema) fails closed as a 500 problem naming the schema file — never as `422 invalid-drop`, because the drop is not the fault. Every (re)load emits one structured stdout event naming the loaded path, `$id`, mtime, and size, so "which copy got loaded" is observable.

## Boundaries & Constraints

**Always:**
- Startup behavior stays fail-fast with a named error and no traceback (`fatal: api startup aborted: ...`, exit 1) — `test_failfast.py` must keep passing.
- The reload check is a `stat()` per ingest request, not a file read; an unchanged file must not be re-parsed.
- The 500 reload-failure problem is RFC 9457 `application/problem+json` with its own slug (`drop-schema-unreadable`), and recovery requires no restart: once the file is readable/valid again, the next request validates normally.
- The load event goes through `meetingminer.logs.log_event` (one JSON line on stdout), matching NFR17 house style.

**Block If:** The fix appears to require touching `api/main.py`'s router-registration block or changing `load_drop_schema`'s call signature in a way that forces edits to files another in-flight story owns.

**Never:**
- No change to the worker's per-call schema read in `domain/drops.py:read_drop` (already never stale) or to `mintdrop.py`.
- No filesystem watcher, thread, or background task — poll-on-request only.
- No change to the wire contract of `POST /ingests` for valid drops, and no edits to `docs/source-drop.schema.json` itself.
- Tests must never write to the repo's real `docs/source-drop.schema.json`; they install a temp copy and restore module state.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Stale-process incident replayed | Schema on disk updated (e.g. `schemaVersion` enum widened) after api start; drop valid only under the new schema | Next `POST /ingests` validates against the new schema and accepts (no restart) | No error expected |
| Schema tightened at runtime | Schema on disk updated to refuse a shape it previously accepted | Next `POST /ingests` refuses with `422 invalid-drop` citing the new schema's violation | Standard 422 problem |
| Unchanged schema | mtime_ns and size unchanged since last load | Cached validator reused; file not re-read | No error expected |
| Reload fails: invalid JSON | File changed on disk to unparseable/invalid-schema content | `500` problem, slug `drop-schema-unreadable`, detail names the path and error | Fail closed; NOT `422 invalid-drop` |
| Reload fails: file deleted | Schema file missing at request time | `500` problem, slug `drop-schema-unreadable` | Fail closed |
| Recovery after failed reload | File restored to valid content | Next request loads it and proceeds normally | No restart needed |
| Startup with unreadable schema | Boot with missing/corrupt schema | `fatal: api startup aborted: source-drop schema unreadable: <path>: ...`, exit 1 | Unchanged fail-fast |
| Every successful (re)load | Load at startup or reload at request time | One stdout JSON event `drop_schema_loaded` with `path`, `schemaId` (`$id`), `mtime` (ISO 8601 UTC), `size` | No error expected |

</intent-contract>

## Code Map

Read on `story/2-6` at baseline `444469d`.

- `server/meetingminer/api/ingests.py:86-127` — the defect. `drop_schema_path(config)` anchors to `config.config_path.parent` (finding 17 — keep). `_VALIDATOR` module global set once by `load_drop_schema(config)` (called from `main.py:68` at import); `_validator()` only errors when never loaded. All changes land here: replace the bare global with a loaded-schema record carrying path + stat signature; add the reload-or-fail-closed logic in `_validator()`.
- `server/meetingminer/api/ingests.py:256-270` — `_load_metadata` calls `_validator().iter_errors`; a `Problem` raised from `_validator()` propagates to the app-wide handler. Route decorator (`:707-730`) already declares a 500 `ProblemDetails` response — no OpenAPI change needed.
- `server/meetingminer/api/main.py:67-68` — `ingests.load_drop_schema(CONFIG)` startup gate. Signature and call stay unchanged; do not edit this file (shared-file hazard: every API story edits it).
- `server/meetingminer/api/problems.py:23-30` — slug precedent: `DROPS_ROOT_UNCONFIGURED` is a module constant only because two routers share it; this story's slug has one consumer, so an inline string in `ingests.py` matches `invalid-drop`'s precedent. `_STATUS_TITLES` already maps 500.
- `server/meetingminer/logs.py:35-42` — `log_event` (stdout) / `log_error_event` (stderr); `main.py` already passes `logs.log_event` to `build_embedder`, so importing `logs` in api modules is house style.
- `server/meetingminer/domain/drops.py:356-388` — the worker's `read_drop` re-reads the schema per call: read-only proof this defect is api-only.
- `server/tests/conftest.py:243-254` — `client` fixture imports `api.main`, so the real schema is installed at import time; tests must monkeypatch the module state and restore it.
- `server/tests/test_ingests.py` — home for the new request-level tests (sentence names, `client`/`make_drop` fixtures, Postgres per-run database — concurrency-safe per AGENTS.md).
- `server/tests/test_failfast.py:85-106` — copies the schema beside a temp config because the schema gate runs before the embedder gate; must keep passing unchanged.
- `docs/source-drop.schema.json:1-11` — `$id` is `https://meetingminer.local/schemas/source-drop/2/metadata.json`; `schemaVersion` enum `[1, 2]` — the field the incident's stale copy pinned at `[1]`, and the natural knob for the replay test.

## Tasks & Acceptance

**Execution:**
- `server/meetingminer/api/ingests.py` — replace `_VALIDATOR` with a `_LoadedSchema` record (path, `mtime_ns`, `size`, validator); factor `install_drop_schema(path)` (read → `json.loads` → `Draft202012Validator.check_schema` → construct validator → swap global → `log_event("drop_schema_loaded", ...)`) so tests can install a temp copy; `load_drop_schema(config)` wraps it with the existing fatal-exit handling (now also catching `jsonschema.SchemaError`); `_validator()` re-stats and reloads on signature change, raising `Problem(500, "drop-schema-unreadable", ...)` on any stat/read/parse/schema failure, leaving the old record in place so a fixed file recovers. Update the module docstring's stale "called once at api startup" claim. — the whole fix, in the one file that owns the cache.
- `server/tests/test_ingests.py` — add the I/O-matrix cases: incident replay (enum `[1]` refuses a v2 drop → widen file to real schema → same POST accepts), tighten-at-runtime, unchanged-file reuses the validator object, invalid-JSON and deleted-file fail closed as 500 `drop-schema-unreadable` (assert `application/problem+json` and that it is not 422), recovery without restart, and the `drop_schema_loaded` stdout event fields via `capsys`. Restore `ingests` module state with `monkeypatch.setattr`. — pins the contract at the outermost surface (`POST /ingests` + stdout).

- `server/tests/test_failfast.py` — add `test_api_exits_1_when_the_drop_schema_is_missing_at_boot` (real config.yaml copied to a docs-less tmp tree, `MM_DROPS_ROOT` set, import `api.main` → exit 1, named error, no traceback). — added during the matrix test audit: the startup-unreadable matrix row had no covering test at baseline.

**Acceptance Criteria:**
- Given a running api (schema loaded at startup), when `docs/source-drop.schema.json` changes on disk and a drop valid only under the new content is POSTed to `/ingests`, then it is accepted without an api restart.
- Given a schema file that changed to unreadable or invalid content, when any drop is POSTed, then the response is a 500 `application/problem+json` with slug `drop-schema-unreadable` naming the schema path — never `422 invalid-drop` — and once the file is valid again the next POST succeeds with no restart.
- Given any successful schema (re)load, when it completes, then exactly one `drop_schema_loaded` JSON event on stdout carries `path`, `schemaId`, `mtime`, and `size`.
- Given an unchanged schema file, when consecutive ingests run, then the validator is not rebuilt (same object identity).
- Given a missing or corrupt schema at boot, when the api starts, then it still exits 1 with the named fatal error and no traceback.

### Review Findings

- [x] [Review][Patch] Check the schema before metadata parsing so an unloadable schema wins every ingest outcome [server/meetingminer/api/ingests.py:849] — resolved: the route now reloads/checks the schema before every drop-level operation and a malformed metadata regression test receives `500 drop-schema-unreadable`.
- [x] [Review][Patch] Convert unresolvable schema references into the named fail-closed problem [server/meetingminer/api/ingests.py:375] — resolved: `referencing.exceptions.Unresolvable` is logged and returned as the named 500 problem, with a route test.
- [x] [Review][Patch] Cover the inode branch of the reload signature [server/tests/test_ingests.py:1317] — resolved: a same-size, mtime-preserving `os.replace()` regression test proves the new schema is applied.
- [x] [Review][Patch] Verify the failed-reload operator event [server/tests/test_ingests.py:1352] — resolved: every unloadable-schema matrix case asserts one `drop_schema_load_failed` stderr event with path and error.
- [x] [Review][Patch] Exercise the startup `SchemaError` gate [server/tests/test_failfast.py:114] — resolved: valid JSON with an invalid schema is now a named exit-1/no-traceback boot case.
- [x] [Review][Patch] Pin non-object schema rejection at request time [server/tests/test_ingests.py:1338] — resolved: the fail-closed matrix includes `true`, a valid boolean JSON Schema that is not a permitted object contract.
- [x] [Review][Patch] Correct the reviewer handoff’s commit-range claim [_bmad-output/implementation-artifacts/review-prompt-story-2-6-2026-08-20.md:12] — resolved: it now names the five-commit implementation range and the separate handoff commit.

## Spec Change Log

## Review Triage Log

### 2026-08-20 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 7: (high 0, medium 4, low 3)
- defer: 0
- reject: 11: (high 0, medium 0, low 11)
- addressed_findings:
  - `[medium]` `[patch]` A boolean-JSON schema file (`true` is a valid 2020-12 schema) escaped `_SCHEMA_LOAD_ERRORS` via `schema.get("$id")` AttributeError — guarded with an isinstance check raising `SchemaError` through the named error paths.
  - `[medium]` `[patch]` A failed reload answered the client 500 but logged nothing server-side — added `log_error_event("drop_schema_load_failed", ...)` before raising.
  - `[medium]` `[patch]` `(st_mtime_ns, st_size)` misses an atomic-rename replace that preserves both (rsync -a / cp -p) — added `st_ino` to the signature and documented the remaining in-place limitation.
  - `[medium]` `[patch]` The size half of the signature was unpinned by tests (mtime-only comparison survived the suite) — added a size-only-change reload test with the original mtime restored, and made `_write_schema`'s mtime bump monotonic.
  - `[low]` `[patch]` Logged ISO mtime loses ns precision via float division — added exact integer `mtimeNs` to the `drop_schema_loaded` event.
  - `[low]` `[patch]` `assert _SCHEMA is not None` was load-bearing under `python -O` and the returned schema dict was dead plumbing — `install_drop_schema` now returns the `_LoadedSchema`; `load_drop_schema` returns `None`.
  - `[low]` `[patch]` Startup-gate test only covered a missing schema and its docstring said "unreadable" — parametrized over missing and corrupt (invalid JSON) boot scenarios.

Rejected as noise or deliberate: reload lock (documented harmless race), 500 detail naming the schema path (intent-contract mandates it), redundant 422 assertion, import-time schema read in tests, OpenAPI slug enumeration (house convention: slugs are not enumerated), RecursionError/broken-stdout/accept-all-schema edge speculation, and the intent-alignment observations (test surface is house TestClient convention; `$id`+mtime satisfies the version-identity ask; the docs_root environment-dependence is a separately filed deferred item).

## Design Notes

**Reload-on-change over fail-closed-only.** `deferred-work.md` offers three tiers (log line; reload on mtime change; fail closed when file newer than load). The sprint id names the reload, and reload subsumes the log line; fail-closed remains the behavior for the case reload cannot serve (unreadable new content), because keeping a stale validator silently is exactly the failure class this story removes.

**Fail closed as 500, not 422.** The incident's expensive property was a process fault presenting as a bad drop. When the schema itself cannot be loaded, no judgment about the drop is possible, so the refusal must name the schema file and blame the server. 500 (not 503): matches the existing "config unavailable on the api process" precedent `drops-root-unconfigured`, and the route already declares 500.

**Stat-signature (`st_mtime_ns` + `st_size`), no locking.** A tuple-swap of one module global is atomic in CPython; concurrent requests may at worst rebuild the validator twice, which is harmless. If the file changes between stat and read, the next request's stat differs and converges.

## Auto Run Result

**Summary.** The api now re-stats `docs/source-drop.schema.json` on every `POST /ingests` and reinstalls the validator when the `(st_mtime_ns, st_size, st_ino)` signature changes, so a schema edit reaches a running api on the next request — no restart. A reload that fails (file gone, unreadable, invalid JSON, non-object or invalid schema) fails closed as `500 drop-schema-unreadable` naming the schema path, with a `drop_schema_load_failed` stderr event; the previous validator stays installed so a repaired file recovers with no restart. Every successful (re)load emits one `drop_schema_loaded` stdout event (`path`, `schemaId`, `mtime`, `mtimeNs`, `size`). Startup stays fail-fast (named error, exit 1), now also catching `jsonschema.SchemaError`.

**Files changed.**
- `server/meetingminer/api/ingests.py` — the reload/fail-closed mechanism replacing the once-cached `_VALIDATOR` global.
- `server/tests/test_ingests.py` — 7 request-level tests (9 items) pinning the I/O matrix at the `POST /ingests` + stdout surface.
- `server/tests/test_failfast.py` — startup schema gate parametrized over missing and corrupt boot scenarios.

**Review findings breakdown.** 4 layers (blind hunter, edge-case hunter, verification-gap, intent-alignment), 20 deduplicated findings: 0 intent_gap, 0 bad_spec, 7 patch (all applied — see Review Triage Log), 0 defer, 11 reject.

**Follow-up review recommendation: true.** Patched this pass: 0 high, 4 medium, 3 low → score 3×4 + 1×3 = 15 ≥ 5.

**Verification performed** (run by the orchestrator after patches):
- `uv run --project server pytest server/tests/test_ingests.py server/tests/test_drop_schema.py -q` → 86 passed.
- `uv run --project server pytest server/tests/test_failfast.py -q` → 10 passed.

**Residual risks.**
- An in-place same-size rewrite with a deliberately preserved mtime (same inode) is undetectable by stat alone; documented in `_validator()`'s docstring. Closing it would need content hashing per request, which trades away the stat-only hot path.
- Concurrent requests during a schema change may rebuild the validator (and emit the load event) more than once — a documented, harmless race.
- The environment-dependence of which schema copy gets resolved (`docs_root()` anchoring) is a separately filed deferred-work item and is unchanged by this story.

## Verification

**Commands:**
- `uv run --project server pytest server/tests/test_ingests.py server/tests/test_drop_schema.py -q` -- expected: all pass (store-backed; per-run database per AGENTS.md/story 2.7, safe to run concurrently)
- `uv run --project server pytest server/tests/test_failfast.py -q` -- expected: all pass (startup gates unchanged)
