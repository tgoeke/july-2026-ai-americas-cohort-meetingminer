---
id: SPEC-chat-fallback-timeout
companions:
  - failure-evidence.md
sources: []
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# Chat Fallback Timeout Break-fix

Landed on `main` at `8080a1a` (2026-08-21). Re-derived 2026-08-29 to retire
premises that have since expired; the contract below is what the landed code
must keep satisfying.

## Why

A chat question in the web UI reported "Cannot reach the api at
http://localhost:8000: timed out after 60000ms" while the api was up and
completed a valid cited answer at 102s. The chain: the `ANTHROPIC_API_KEY` was
invalid — the owner had revoked it after unauthorized paid use — so every chat
turn's primary failed in ~1.6s and silently rode the local fallback
(`ollama/qwen3:30b`), whose two model calls total ~100s; the chat panel's 60s
timer spans the whole request and the server streams nothing until the full
answer is validated, so the client aborted with zero bytes received and
misreported a live server as unreachable. Log excerpts and the timeline are in
`failure-evidence.md`.

The silent fallback came from the planning spine's AD-10 default bindings,
which the owner never agreed to. Decision of record (2026-08-21): chat and
judge run `openai/gpt-5.2` with **no fallback**, applied to `config.yaml`.
The Anthropic key was restored 2026-08-29; both providers are valid and model
choice becomes a UI option under Epic 8 — that work is specced in `epics.md`,
not here.

## Capabilities

- **CAP-1** — *retired 2026-08-21.* (Was: a fallback turn completes in the UI.
  The fallback is removed by owner decision; there is no such turn.)
- **CAP-2** — *retired 2026-08-21.* (Was: fallback engagement visible.
  Superseded by CAP-4.)
- **CAP-3**
  - **intent:** A client-side timeout on a request the server accepted is
    reported as a timeout, not as an unreachable api.
  - **success:** The "Cannot reach the api" wording appears only when no
    connection was established; an expiry mid-request names the wait, not the
    transport.
- **CAP-4**
  - **intent:** A chat turn whose model call fails surfaces the failure to
    the user promptly, never a silent substitute model and never a hang to
    the client timeout.
  - **success:** With the bound provider unreachable and no fallback
    configured, the chat panel shows the server's error naming the failed
    binding within seconds; no run of the flow reproduces the "Cannot reach
    the api" report while `GET /health` answers 200.

## Constraints

- No silent model substitution anywhere on the chat path (owner direction of
  record). Degraded behavior must be visible where it happens. Epic 8's
  user-selected binding is subject to the same rule: a failing selection is a
  named error, never a substitute.
- Story 3.3 invariant holds: the whole answer is validated before any
  `chat.token` is sent. No fix may stream unvalidated tokens.
- `422 no-citable-answer` remains the server's final word — never retried
  (existing `chatStream` contract).
- The `openai/` prefix is required on the model tag: the adapter's bare-name
  routing (`_BARE_OPENAI_PREFIXES` in `adapters/llm/litellm.py`) predates
  gpt-5 and would not resolve `providers.openai` for an unprefixed tag.
- Verification of failure paths uses the free path (invalid/absent key). A
  paid model call requires a fresh explicit yes from the owner.

## Non-goals

- Changing the extraction role's bindings: its local-to-local fallback
  (`ollama/gpt-oss:120b -> ollama/qwen3:30b`) stays by owner decision
  (2026-08-21) — surfaced, accepted, no paid substitution involved.
- Making any local model faster.
- Per-role model catalogs and user selection (Epic 8).

## Success signal

With `OPENAI_API_KEY` absent or invalid, a chat question in the web UI shows
a prompt, accurate error naming the `llm.roles.chat` binding; with a valid
key, the same question returns a cited answer. Neither case can reproduce
"Cannot reach the api" while `GET /health` answers 200.

## Assumptions

- The 102s fallback measurement (one short question, 28 moments) is moot for
  chat but stands as the recorded latency of `qwen3:30b` on this path.

## Resolved

- Live paid chat turn: verified 2026-08-22 (chat provider account topped up,
  ask-the-corpus break-fix `884404f`).
- Spine AD-10 default-bindings sentence: closed by supersession 2026-08-29 —
  `docs/architecture.md` is the technical contract and carries no such
  sentence; the stale line survives only in the untracked planning spine.
- Worker restart hold: retired 2026-08-29 — the paid extraction backlog no
  longer exists (`docs/backlog.md` B-30).
- Anthropic key: restored 2026-08-29 by the owner; no rotation was ever the
  fix.
