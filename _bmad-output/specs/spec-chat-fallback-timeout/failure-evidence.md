# Failure evidence — chat fallback timeout

Observed 2026-08-21. All server lines are from `.logs/api.log` (the running
uvicorn's stdout/stderr); the api answered `GET /health` 200 throughout.

## The reported symptom

The web chat panel showed:

> Cannot reach the api at http://localhost:8000: timed out after 60000ms.

`60000ms` is unique to `web/src/features/chat/ChatPanel.tsx`
(`CHAT_TIMEOUT_MS = 60_000`); no other view uses that bound.

## Timeline of the failing turn (UTC)

| Time | Event | Detail |
|---|---|---|
| 20:33:39.977 | `llm.bound` | model `claude-sonnet-5`, fallback `ollama/qwen3:30b`, timeout 120s |
| 20:33:41.592 | `llm.fallback_engaged` | primary AuthenticationError: `API key is invalid.` (Anthropic, `https://api.anthropic.com`) |
| 20:34:00.366 | `chat.classified` | template null, reason `no-template` — classification on the fallback took ~19s |
| 20:34:01.830 | `chat.search_completed` | terms "API limits", hybrid, 30 ranked |
| 20:34:01.835 | `chat.prompt_cropped` | 28 moments, 10 cropped, 2 dropped |
| 20:35:21.976 | `chat.completed` | `elapsed_ms: 102007`, 6 citations, `streamed: true` |

The browser's 60s expiry fired at ~20:34:40, mid-synthesis. The server kept
going and completed a valid cited answer 42s after the client had already
reported the api unreachable.

## Mechanism

1. `ANTHROPIC_API_KEY` in `.env` is set but invalid — Anthropic rejects it in
   ~1.6s on every chat turn, so every turn rides the local fallback
   (`ollama/qwen3:30b`), logged only server-side (`llm.fallback_engaged`).
2. On the fallback, the two model calls total ~100s for a short question
   (classification ~19s, synthesis ~80s at 28 moments in the prompt).
3. `ChatPanel`'s 60s timer spans the entire request through `chat.done`, and by
   design the server streams **nothing** until the whole answer is validated
   (story 3.3: the stream is a replay of an already-gated answer). So a
   fallback-path turn delivers zero bytes before the client aborts.
4. The abort is classified as a transport failure and rendered with the
   "Cannot reach the api" wording — a diagnosis of an unreachable server for a
   server that was up, accepted the request, and finished it.

## Prior same-day failures, different mechanism

At 15:02Z and 15:03Z, `POST /chat` returned fast 503s: the fallback tag was
then `qwen3:32b`, which neither Ollama endpoint serves — the dead-fallback
case the `config.yaml` comment now warns about. The tag was corrected to
`qwen3:30b` on 2026-08-20; the 20:33Z turn confirms the corrected fallback
works and is merely slow.
