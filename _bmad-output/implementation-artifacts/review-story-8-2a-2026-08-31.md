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
