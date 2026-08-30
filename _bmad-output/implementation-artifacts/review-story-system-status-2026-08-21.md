# Review — story/system-status — 2026-08-21

Reviewer: Claude (reviewer agent), worktree `../meetingminer-wt/system-status-review`.

## Scope

- Branch: `story/system-status`, range `2718e3e..12f7377`
  (commits `2718e3e`, `6ba7b7f`, `631055e`, `12f7377`).
- Contract: `_bmad-output/specs/spec-system-status/SPEC.md`
  + companion `_bmad-output/specs/spec-chat-fallback-timeout/SPEC.md`.
- Priority checks (per dispatch): secrets in /status payload (blocking class),
  free probes only (no paid completions, cache under concurrency), worker
  safety (observation only, DB scoping of lock query), CAP-3 copy matches
  `llm.roles.<role>` wording, disclosed boundary deviations
  (test_api_registry.py baseline append; App.test.tsx URL-aware fetch mock),
  suites run by reviewer with observed counts.
- Verification is free-path only. Worker untouched in any state.

## Priority checks — verified

- **SECRETS (blocking class): pass.** The `/status` payload is built field by
  explicit field from five pydantic models in
  `server/meetingminer/api/status.py`; no `Settings`/`Secrets` object is ever
  serialized. Key material is read only into probe request headers
  (`_probe_provider`) and never into any `detail`/`remediation` string — those
  carry env-var *names* only (`OPENAI_API_KEY` etc.), never values, lengths,
  or prefixes. The probe cache is keyed `(provider, base_url)`, not by key.
  Exception interpolations reviewed: httpx errors carry URL + transport
  message (no headers); psycopg/libpq connection errors do not echo the
  password. `test_payload_is_an_allowlist_with_no_key_material` pins this
  against known fake secrets, asserting neither the value nor its 12-char
  prefix appears, and asserts the exact field allowlist per row type.
- **FREE PROBES: pass.** The only network calls on the status path are
  provider model-list endpoints (`/v1/models`, `/models`), ollama `/api/tags`,
  a `SELECT 1`, a bolt-port TCP connect, and Meilisearch `GET /health`. No
  code path imports or invokes any completion adapter. Missing key is
  reported without probing (test-pinned). The 60s cache
  (`PROBE_TTL_SECONDS=60` > 15s poll interval) is test-pinned with a frozen
  clock: second poll inside the TTL re-probes nothing; past the TTL each
  endpoint probes exactly once more.
- **WORKER SAFETY: pass.** The status path runs three read-only SELECTs
  (`pg_locks` EXISTS, job counts, stage backlog); no
  `pg_advisory_lock`/`_unlock`, no writes, no process control. The lock query
  matches the worker's actual lock
  (`pg_try_advisory_lock(hashtext('meetingminer-worker'))`,
  `worker/main.py:52`) — recomposition and database scoping verified live
  against a scratch database: with the lock held, same-database query returns
  true, a different database returns false, and it clears on release
  (advisory locks are database-scoped, so per-run test databases cannot see a
  live worker's lock and vice versa). The stopped worker is reported as
  deliberate with the restart-is-a-spend-decision caveat, and still degrades
  `overall` (no silent green).
- **CAP-3 copy: pass.** Status rows name bindings `` `llm.roles.<role>` `` —
  the same backticked style as the chat panel's 503
  (`api/chat.py:874`: "the `llm.roles.chat` binding"). Pinned on the server
  side (`test_invalid_key_names_binding_and_remediation`) and the web side
  (`status.test.tsx` degraded-row assertions).
- **Disclosed deviation 1 — `server/tests/test_api_registry.py`:** minimal.
  Four lines: appends `"status"` to `BASELINE_ROUTER_ORDER` (default-order,
  alphabetical after `participants`; `/status` has no parameterized sibling,
  so position carries no matching hazard). No other assertion touched.
- **Disclosed deviation 2 — `web/src/App.test.tsx`:** minimal and does not
  mask chat behavior. The blanket `fetch` mock became URL-aware because the
  shell now carries a second raw-fetch reader (the status poll) and a single
  shared Response body would be consumed by whichever request lands first.
  Only `/chat` receives the stream — the chat assertions are unchanged and
  still exercised; the status poll is rejected and reads as unreachable,
  irrelevant to that citation-navigation test.
- **Registration:** `status.py` exposes a module-level `router`; the
  registry's auto-discovery picks it up (asserted by the baseline-order
  test). The web route ships as
  `web/src/features/status/StatusPage.route.tsx`, discovered by the
  `*.route.tsx` glob; the chrome indicator mounts outside the
  hidden-on-child-screens home block, so it is visible on every screen.

## Findings (non-blocking)

1. **Cold-cache concurrency issues duplicate free probes.** `_cached_probe`
   has no lock; the endpoint is sync `def`, so FastAPI runs polls
   concurrently in its threadpool, and N simultaneous polls during a
   cold/expired window each call `_probe_provider` before any of them writes
   the cache. Every such probe is a free list endpoint — no paid completion
   exists on this path — so the spend constraint holds regardless; the cache
   still bounds the steady-state rate for the single-owner UI. Cosmetic
   thundering-herd only. No change required for this story.
2. **Status surface's own unreachable copy conflates timeout/HTTP-error with
   unreachability.** `useSystemStatus` maps its 5s fetch timeout and non-2xx
   responses (`"the api answered HTTP <n>"`) into the same
   `kind: 'unreachable'`, rendered as "cannot reach the api at …". A non-2xx
   answer means the api was reached, so this mildly echoes the pattern
   companion CAP-3 fixed on the chat panel (the companion binds the chat
   path specifically and is not weakened — `d45db76`'s chat-panel wording is
   untouched). Cosmetic copy; candidate follow-up, not blocking.
3. **Unknown-but-configured provider reads `ok`.** A provider outside
   `KEY_ENV_VARS` and not `ollama`, with a configured base_url, is treated as
   keyless and `_probe_provider` returns `ok` with detail "no probe defined
   for provider …". Honest in the detail string, optimistic in the state.
   Unreachable with the committed config (anthropic/openai/ollama only).
   Not blocking.

## Suite runs (observed by reviewer, in this worktree)

- `uv run --project server pytest server/tests/test_api_status.py
  server/tests/test_api_registry.py` — **15 passed** (5 status + 10
  registry), 1 deprecation warning, 0.87s.
- `make web-test` — **13 files, 208 tests passed**, 11.3s.
- Lock-query verification script (scratch `postgres` database, free-path,
  worker untouched): acquired/seen/scoped/released as expected.
- No live provider endpoint was called by the reviewer; all provider probes
  in tests are stubbed. The worker was not started, stopped, or touched.

## Verdict

**Pass — land.** No blocking findings.

Landing: `story/system-status` rebased onto `origin/main` (2b6cdfe) clean, no
conflicts — reviewed range `2718e3e..12f7377` became `015f28a..badd275`;
`git diff 12f7377 badd275 --stat` shows only main's post-fork content
(chat-fallback-timeout + docs), so the reviewed patches are unchanged.
Suites re-run on the rebased range: server 15 passed, web 208 passed. Secrets constraint holds under
adversarial reading and test; probes are free and cached; the worker is
observed, never perturbed; CAP-1/2/3 delivered under every constraint, and
the companion contract is not weakened. Findings 1–3 are non-blocking
follow-up candidates.
