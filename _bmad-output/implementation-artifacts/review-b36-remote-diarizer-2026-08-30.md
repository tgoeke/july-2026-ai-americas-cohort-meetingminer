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
- **Finding:** Fixed. `_number` accepted every Python `int`/`float` without requiring finiteness or handling conversion overflow. Python's JSON decoder accepts `NaN` and `Infinity`, and an arbitrarily large JSON integer is also reachable. Those values raised raw `ValueError`/`OverflowError` during float conversion or rounding instead of the frozen contract's named `DiarizerError`. `_number` now returns `None` for non-finite or unrepresentable values so the existing malformed-turn diagnostic owns them.
- **Evidence:** Against the unfixed rebased code, direct calls through `_to_turns` produced `ValueError: cannot convert float NaN to integer`, `OverflowError: cannot convert float infinity to integer`, and `OverflowError: int too large to convert to float`. The new focused pytest selection was then observed red with 4 failures for `NaN`, positive infinity, negative infinity, and the oversized integer. After the fix, the same selection passed: 6 passed, 35 deselected. `transcribe.py:180-182` catches the resulting `DiarizerError`.
- **Suggested direction:** Make numeric coercion reject non-finite and unrepresentable values as malformed turns, add regression rows for `NaN`, infinities, and an oversized integer, and verify each raises `DiarizerError` naming the endpoint and offending turn.

### Finding 2 — truncated response bodies bypass `DiarizerError`

- **Location:** `server/meetingminer/adapters/diarize/remote_http.py:178-202`
- **Severity:** Medium
- **Finding:** Fixed. `_post` classified `HTTPError`, `URLError`, `TimeoutError`, and `OSError`, but `response.read()` could raise `http.client.IncompleteRead` (an `HTTPException`, not an `OSError`) when the peer closed before its advertised `Content-Length`. The raw exception crossed the `Diarizer` port, including while extracting an `HTTPError` body. Both paths now become an endpoint-naming `DiarizerError` and no partial payload is parsed as success.
- **Evidence:** A local server that advertised 32 response bytes, wrote the complete 12-byte `{"turns":[]}` payload, and closed caused the unfixed engine to raise raw `IncompleteRead(12 bytes read, 20 more expected)`. The new real-socket selection was observed red with 2 failures for truncated 200 and 503 bodies; after the fix it passed 3 tests, including a non-JSON 502 whose own decoded text remains in the error.
- **Suggested direction:** Convert incomplete/framing failures on both success and HTTP-error bodies into endpoint-naming `DiarizerError`s, never parse a partial payload as healthy empty turns, and add real-socket regressions for truncated 200/error bodies plus an unparseable HTTP-error body whose own text must survive.

### Finding 3 — `timeout_seconds` is an inactivity timeout, not the promised finite request budget

- **Location:** `server/meetingminer/adapters/diarize/remote_http.py:165-181,291-300`
- **Severity:** High
- **Finding:** Fixed. Passing `timeout_seconds` once to `urlopen` limited individual blocking socket operations; it did not impose a wall-clock deadline on the whole upload/response. A peer could keep the call alive indefinitely by sending each next byte before the socket timeout. The adapter now carries one monotonic deadline through streaming upload and incremental response reads, applies the remaining budget to each response read, and routes expiry through the existing named timeout error.
- **Evidence:** Against the unfixed code, a loopback server sent the 13-byte healthy empty-turns JSON one byte every 40 ms. With `timeout_seconds=0.08`, `diarize` returned success after 0.532 s—6.6 times the configured budget; the new focused test was observed red because no `DiarizerError` was raised. After the fix, the slow-drip, original idle-timeout, and both truncation cases passed together: 4 passed, 41 deselected, with the slow-drip test also requiring elapsed wall time below 0.3 s.
- **Suggested direction:** Track one monotonic deadline across upload and response consumption, bound each transport read by the remaining budget, and fail with the existing endpoint/setting diagnostic once the total request budget is exhausted. Add a slow-drip regression that is red on the unfixed implementation.

### Finding 4 — upload length is measured from a different filesystem observation than the opened stream

- **Location:** `server/meetingminer/adapters/diarize/remote_http.py:146-173`
- **Severity:** Medium
- **Finding:** Fixed. `_post` called `path.stat()` before `path.open()`. If the path was replaced or changed between those operations, `Content-Length` described the old object while the request streamed the newly opened object. The adapter now opens first and sizes the upload with `os.fstat(handle.fileno())`, so the header and streamed bytes start from the same file object.
- **Evidence:** Against the unfixed code, a deterministic stale-stat probe reported a one-byte audio size while opening a larger file. The engine declared/read 214 multipart bytes and returned healthy `()` even though the server's received body did not contain the closing boundary; the new regression was observed red with `KeyError: 'file'`. After the fix, the focused test passed and asserted both the complete audio payload and closing multipart boundary.
- **Suggested direction:** Open first and derive the advertised size from that exact descriptor (`fstat`), preserving streaming and explicit `Content-Length`; add a regression that makes path metadata stale and proves the complete multipart body still arrives.

## Review verdict

**Pass after remediation.** Four findings were confirmed (1 high, 3 medium), all four were fixed red-first on `story/b36-remote-diarizer-review`, and no finding remains open. The review changed only the new adapter, its new test module, and review/tracking artifacts. It did not choose a default engine, touch B-36's STT half, contact the LAN host, merge, or commit to `main`.

## Design-decision assessment

- Keeping `remote-http` outside `ENGINES` is acceptable for this footprint. `ENGINES` is still a zero-argument class registry; `pyannote` already establishes the configured-constructor special case, while `ENGINE_CHOICES` and its test keep the diagnostic exhaustive. A factory-registry refactor would touch `noop` registration without fixing a present correctness defect.
- Independent `round(seconds * 1000)` is correct and monotone for finite inputs. Its per-boundary error is at most 0.5 ms; a finite turn with `end >= start` cannot round to `end_ms < start_ms`. Non-finite and unrepresentable inputs are now rejected by F1. Shared boundaries and collapsed turns remain pinned by tests.
- Timeline-order canonicalization matches the frozen matrix. Its difference from pyannote's host-iteration numbering is not a port defect: the emitted names remain recording-local placeholders, and no identity may be inferred from the number.
- Failing the full response on one reversed turn is the frozen fail-closed choice. Collapsed zero-millisecond turns remain silently dropped before claiming a label, matching the in-process precedent.
- The cap arithmetic is correct: exactly 1000 speakers ends at `SPEAKER_999`, which `is_placeholder_label` accepts; speaker 1001 is refused before `SPEAKER_1000` can escape the placeholder namespace.
- No build-time health probe is correct per the matrix. Syntax/config binding is resolved without contacting the operator-scheduled host; reachability is a property of the eventual call.
- HTTP error handling is status-agnostic, preserves JSON `reason` text and unparseable body text, names the endpoint, and includes the model when a valid error body supplies one. Truncated bodies now fail by name rather than becoming empty success.
- The 900-second default is supported by the recorded queueing measurements. Pydantic enforces positive finiteness, and F3 now makes the value one total monotonic request deadline rather than only a socket inactivity timeout.
- The three builder deviations are accurately recorded: `ENGINE_CHOICES`, the two `test_compose_contract.py` registries satisfied without widening the footprint, and Ruff's `.encode()` form. Editing the shared contract registry would incorrectly place this dependency-free module in the pyannote-extra lane or grow the pinned slow set for a test skipped by default.
- Repository search found only one non-loopback network path in the module: the live test guarded by `MM_DIARIZE_REMOTE_NETWORK_TEST=1`. All ordinary transport tests bind `127.0.0.1:0`; the full gate reported the live test skipped by that flag.

## Verification after remediation

- `uv run --project server pytest server/tests/test_diarize_remote.py -q` — 45 passed, 1 skipped in 1.55s.
- `uv run --project server pytest server/tests/test_diarize_pyannote.py server/tests/test_stt_adapter.py server/tests/test_config.py -q` — 180 passed, 1 skipped in 21.28s.
- `make lint` — clean. `make typecheck` — clean in 13 source files.
- Builder mutation replay — all 8 original mutations were caught: truncation instead of rounding; host-order labels; dropped reversed turn; retained collapsed turn; off-by-one speaker cap; missing `Content-Length`; unreachable-host empty fallback; swallowed host reason. The source matched the committed fix afterward (`git status --short` and scoped `git diff` empty).
- `make test-fast` — 2,007 passed, 3 skipped, 378 deselected in 67.96s; the LAN test named `MM_DIARIZE_REMOTE_NETWORK_TEST` in its skip reason.
- `make test` — exit 0: puller 128 passed; web 294 passed; evals 643 passed; diarize-extra 92 passed; server 2,385 passed, 3 skipped in 575.36s; production web build succeeded.
- `python3 _bmad/scripts/branch_conflicts.py --against story/b36-remote-diarizer` — the rebased review branch is clean against `main`; the builder branch still shows the documented shared `sprint-notes.md` seam. Review-vs-builder conflicts are expected because this branch contains the fixes.

## Residual limits

The LAN host was not contacted. The env-flagged live test remains unrun, turn quality remains unvalidated against ground truth, and no end-to-end `transcribe` run was made with `remote-http` bound because `noop` deliberately remains the committed default. Those are unchanged handoff limits, not open code-review findings.
