# B-36 remote diarizer review — 2026-08-30

## Scope

Review and remediate the LAN diarization endpoint behind the `Diarizer` port. In scope: `server/meetingminer/adapters/diarize/remote_http.py`, `server/meetingminer/adapters/diarize/__init__.py`, `DiarizerConfig` in `server/meetingminer/config.py`, the `diarizer:` block of `config.yaml`, and `server/tests/test_diarize_remote.py`. The STT-over-HTTP half of B-36, the committed default engine choice, and the frozen intent contract are out of scope.

## Review range

Requested builder range: `a401d6c..6bdcca8` on `story/b36-remote-diarizer`.

Rebased review range: `origin/main..97754b4` on `story/b36-remote-diarizer-review` at the start of code inspection:

- `10457a6` — spec(b36): plan the remote-http diarizer engine behind the Diarizer port
- `46a5708` — feat(b36): bind the LAN diarization endpoint behind the Diarizer port
- `9c1cbaa` — docs(b36): spec to review with its change log, sprint tracking, review handoff
- `97754b4` — docs(b36): record the verified gate output and the real branch state

The report skeleton commit `74cbf2b` follows that reviewed builder range and is not implementation under review.

## Findings

### Finding 1 — non-finite and oversized timestamps escape the port error taxonomy

- **Location:** `server/meetingminer/adapters/diarize/remote_http.py:109-117,232-256`
- **Severity:** Medium
- **Finding:** Open — patch planned. `_number` accepts every Python `int`/`float` without requiring finiteness or handling conversion overflow. Python's JSON decoder accepts `NaN` and `Infinity`, and an arbitrarily large JSON integer is also reachable. Those values raise raw `ValueError`/`OverflowError` during float conversion or rounding instead of the frozen contract's named `DiarizerError`.
- **Evidence:** Against the unfixed rebased code, direct calls through `_to_turns` produced `ValueError: cannot convert float NaN to integer`, `OverflowError: cannot convert float infinity to integer`, and `OverflowError: int too large to convert to float`. `transcribe.py:180-182` catches only `DiarizerError`, so these malformed host responses bypass the adapter's promised diagnostic boundary. No test in the repository covers non-finite or oversized remote turn timestamps; the symbol/import search found remote coverage only in `server/tests/test_diarize_remote.py`.
- **Suggested direction:** Make numeric coercion reject non-finite and unrepresentable values as malformed turns, add regression rows for `NaN`, infinities, and an oversized integer, and verify each raises `DiarizerError` naming the endpoint and offending turn.

### Finding 2 — truncated response bodies bypass `DiarizerError`

- **Location:** `server/meetingminer/adapters/diarize/remote_http.py:178-202`
- **Severity:** Medium
- **Finding:** Open — patch planned. `_post` classifies `HTTPError`, `URLError`, `TimeoutError`, and `OSError`, but `response.read()` can raise `http.client.IncompleteRead` (an `HTTPException`, not an `OSError`) when the peer closes before its advertised `Content-Length`. The raw exception crosses the `Diarizer` port. The same unguarded `read()` occurs while extracting an `HTTPError` body.
- **Evidence:** A local server that advertised 32 response bytes, wrote the complete 12-byte `{"turns":[]}` payload, and closed caused the unfixed engine to raise raw `IncompleteRead(12 bytes read, 20 more expected)`. The existing timeout test delays before sending a complete body; no repository test truncates a success or error response. The suite also does not pin the required degradation of a non-JSON HTTP-error body to that body's own decoded text.
- **Suggested direction:** Convert incomplete/framing failures on both success and HTTP-error bodies into endpoint-naming `DiarizerError`s, never parse a partial payload as healthy empty turns, and add real-socket regressions for truncated 200/error bodies plus an unparseable HTTP-error body whose own text must survive.

### Finding 3 — `timeout_seconds` is an inactivity timeout, not the promised finite request budget

- **Location:** `server/meetingminer/adapters/diarize/remote_http.py:165-181,291-300`
- **Severity:** High
- **Finding:** Open — patch planned. Passing `timeout_seconds` once to `urlopen` limits individual blocking socket operations; it does not impose a wall-clock deadline on the whole upload/response. A peer can keep the call alive indefinitely by sending each next byte before the socket timeout. That contradicts the frozen requirement that the configurable finite timeout be enforced on every request and the diagnostic's claim that the call did not answer "within" the configured budget.
- **Evidence:** Against the unfixed code, a loopback server sent the 13-byte healthy empty-turns JSON one byte every 40 ms. With `timeout_seconds=0.08`, `diarize` returned success after 0.532 s—6.6 times the configured budget. The current timeout test sleeps 0.5 s before writing anything, so it verifies only an idle socket and stays green under this slow-drip mutation.
- **Suggested direction:** Track one monotonic deadline across upload and response consumption, bound each transport read by the remaining budget, and fail with the existing endpoint/setting diagnostic once the total request budget is exhausted. Add a slow-drip regression that is red on the unfixed implementation.

### Finding 4 — upload length is measured from a different filesystem observation than the opened stream

- **Location:** `server/meetingminer/adapters/diarize/remote_http.py:146-173`
- **Severity:** Medium
- **Finding:** Open — patch planned. `_post` calls `path.stat()` before `path.open()`. If the path is replaced or changes between those operations, `Content-Length` describes the old object while the request streams the newly opened object. The explicit header then becomes dishonest, defeating the reason this adapter avoids chunked transfer.
- **Evidence:** Against the unfixed code, a deterministic stale-stat probe reported a one-byte audio size while opening a larger file. The engine declared/read 214 multipart bytes and returned healthy `()` even though the server's received body did not contain the closing boundary; the current happy-path assertion checks only a stable file. Meeting audio is normally immutable by pipeline convention, which limits reachability, but the adapter itself neither takes the measurement from its open descriptor nor detects the mismatch.
- **Suggested direction:** Open first and derive the advertised size from that exact descriptor (`fstat`), preserving streaming and explicit `Content-Length`; add a regression that makes path metadata stale and proves the complete multipart body still arrives.
