# Story 8.2a Adversarial Review — 2026-08-31

## Scope

Adversarial review and red-first remediation of Story 8.2a, Provider Health on the Status Surface. Frozen intent-contract findings remain open for owner action; patchable implementation findings are remediated on `story/8-2a-review`.

## Review range

`9fc760fe..story/8-2a` (branch tip at review start: `53bec5b7`)

## Findings

### F1 — Failed dependency checks can serialize secret-bearing exception text

- **Location** — `server/meetingminer/api/status.py:324`
- **Severity** — high
- **Finding** — The explicit response allowlist does not make its string fields safe. Provider, Postgres, Neo4j, and Meilisearch failure branches interpolate exception text verbatim into `detail` (`status.py:324`, `:357`, `:371`, `:381`). The no-key-material test scans the whole response, including `detail`, `remediation`, attribution, and provider rows, but its exercised branches use fixed safe probe strings and a healthy real Postgres connection. It never makes an external failure return key material, so it cannot detect this leak. Its OpenAI/OpenRouter fakes also omit the current key-family markers (`sk-proj-` and `sk-or-v1-`), weakening protection against future prefix-sensitive masking.
- **Evidence** — A read-only probe with `httpx.get` patched to raise `ConnectError("sk-proj-QQZZsecretwindow123456")` returned `ProbeResult.detail == "https://api.openai.com/v1/models unreachable: sk-proj-QQZZsecretwindow123456"`. `test_no_fragment_of_any_key_serializes_in_any_branch` stubs `_probe_provider` with only `"stub ok"` and HTTP-status prose, while `_stores_up` leaves Postgres healthy. The secret-bearing failure text therefore serializes in production code while all current leak assertions stay green.
- **Suggested direction** — Treat dependency exception messages as untrusted and emit bounded, authored diagnostics that identify the endpoint and exception class without echoing arbitrary text. Extend the whole-response window assertion with realistically shaped fake keys injected through every failure-text source, including the provider probe and Postgres/store details.

### F2 — The chrome still announces system-wide health from the API-only snapshot

- **Location** — `web/src/features/status/StatusIndicator.tsx:30`
- **Severity** — high
- **Finding** — The collapsed indicator says `all systems healthy`, and the expanded healthy state says `Every dependency is healthy.` Those are precisely the system-speaking conclusions the attribution criterion forbids: `overall` includes provider and extraction-role readings taken from the API process's snapshot, while the worker may be using another snapshot. The attribution line appears only after expansion, so the persistent collapsed claim is both broader and more prominent than its later disclaimer.
- **Evidence** — `summarize()` returns the system-wide label at `StatusIndicator.tsx:30`; the expanded panel repeats the conclusion at `:73`. The server-side banned-phrase test scans neither web-authored sentence, and `status.test.tsx` currently expects `all systems healthy`, so both misleading sentences pass the full baseline. In the incident state named by the spec—stale API snapshot and restarted worker—the indicator can therefore read `all systems healthy` while the worker calls a different provider.
- **Suggested direction** — Make every healthy summary explicitly the API process's observed view, including the collapsed button, and add UI assertions that reject an unattributed whole-system healthy claim.

### F3 — The extraction disclaimer claims knowledge of the worker state it says is unobservable

- **Location** — `server/meetingminer/api/status.py:165`
- **Severity** — high
- **Finding** — The exact-pinned extraction attribution ends with `the two disagree until both are restarted`. The API has no worker binding record (the reason the story files a deferred item), so it cannot know that the two snapshots disagree; they may agree before, during, or after a config edit. The sentence passes all eight banned phrases and the exact-match test because the test pins the misleading claim itself. This is an AD-18 violation in the opposite direction: the surface now asserts a worker/API divergence it cannot observe.
- **Evidence** — Calling `_role_attribution("extraction")` printed the unconditional disagreement sentence. `EXTRACTION_SNAPSHOT_DISCLAIMER` reproduces it verbatim at `server/tests/test_api_status.py:639-645`, and `test_every_reading_is_attributed_to_the_process_that_answered` requires exact equality. The backlog item's own honest boundary says the API can only say the two *may* disagree until worker reporting exists.
- **Suggested direction** — Keep the exact-pinned disclaimer but state only the supported possibility: the snapshots may disagree after a config edit until both processes are restarted. Add a focused assertion that the API snapshot makes no claim about whether divergence currently exists.

### F4 — An unimplemented provider probe reports an endpoint as healthy without making a request

- **Location** — `server/meetingminer/api/status.py:319`
- **Severity** — high
- **Finding** — Any provider outside the hard-coded four returns `ProbeResult("ok", "no probe defined ...")`. `_key_health()` treats every provider absent from `KEY_ENV_VARS` as keyless, discards that detail, and reports `endpoint <url> answering`. Provider ids are derived from arbitrary `<provider>/...` model prefixes and `providers` is an open dictionary, so a declared provider such as `gemini` reaches this branch. Its row and every bound role can be green although no endpoint was contacted and no credential was checked.
- **Evidence** — With `httpx.get` patched to fail if called, `_probe_provider("gemini", "https://generativelanguage.googleapis.com", "unused")` returned `state="ok"` and `detail="no probe defined for provider 'gemini'"`; no request occurred. `provider_for_model()` accepts any non-empty prefix, and `ProviderEndpoint` imposes no provider-id enum. At `status.py:452-455`, that synthetic `ok` becomes `not-required`, `ok`, `endpoint ... answering`.
- **Suggested direction** — Represent `not checked` separately from `ok` and never infer keylessness merely because a provider is absent from the keyed-provider table. Either implement a proven-free list probe plus credential mapping for a provider or return a named degraded/unknown state that cannot roll the surface green.

### F5 — The deferred worker-status item now collides with `origin/main`'s B-52

- **Location** — `docs/backlog.md:781`
- **Severity** — low
- **Finding** — Story 8.2a allocated B-52 from its cut-time counter, but current `origin/main` already owns B-52 for the browser layout test harness landed by Story 10.6. Landing this branch as written would create a new duplicate after today's reconciliation. The pre-existing duplicate B-42 remains a documented historical collision and must not be renumbered in this lane.
- **Evidence** — `git show origin/main:docs/backlog.md` lists `B-52 · Give browser-only layout contracts a standing test harness`; the story branch lists `B-52 · Let the api report the worker's loaded binding...` and references it in the Story 8.2a spec and reviewer handoff. The highest id on current `origin/main` is 52.
- **Suggested direction** — Renumber only Story 8.2a's newly filed worker-binding item and its story-owned references to B-53 during the required rebase. Leave B-42 and every other lane's ids unchanged.
