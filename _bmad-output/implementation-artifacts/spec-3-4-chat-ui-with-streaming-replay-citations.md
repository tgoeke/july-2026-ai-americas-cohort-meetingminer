---
title: 'Story 3.4 — Chat UI with Streaming & Replay Citations'
type: 'feature'
created: '2026-08-20'
status: 'done'
baseline_revision: '63d6fb1'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-3-context.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md'
warnings: ['oversized']
deferred:
  - summary: >-
      A re-submit that supersedes an in-flight, partially-streamed answer
      discards it silently, with no visible signal that anything was
      interrupted.
    evidence: |-
      `ChatPanel.tsx`'s `ask()` unconditionally clears answer/citations/
      route/failure at the top of every call, including one that aborts an
      in-flight stream via `controllerRef`. `CorpusSearch` has the same
      silent-supersede shape, but that panel is live-as-you-type search
      where discarding a stale query is expected; `ChatPanel`'s submit is one
      deliberate action per question, so losing a partially-rendered answer
      with zero feedback is a more consequential gap for the same pattern
      (independent review, review-story-3-4-2026-08-20.md, Finding 2).
    location: >-
      web/src/features/chat/ChatPanel.tsx:143-152
    severity: low
---

<intent-contract>

## Intent

**Problem:** Story 3.3 built `POST /chat` with SSE (`chat.token`/`chat.citations`/`chat.done`) and a deterministic citation gate, but nothing in `web/` calls it — there is no chat panel, no streamed answer, and no way to follow a citation into the moment view (FR15, UX-DR10).

**Approach:** Add a `chat` feature under `web/src/features/chat/`: a panel that submits a question, streams the validated answer over SSE, renders citations as "Open moment" links into Story 2.2's moment view, and shows an explicit "no citable answer" state on a gate rejection. Wired into `App.tsx`'s existing home section, no router or new `AppView` variant.

## Boundaries & Constraints

**Always:**
- Exactly one request per submitted question. Never call the JSON `askCorpus()` in addition to the SSE request for the same question — each is a real, config-bound `Llm(chat)` call, and doubling it doubles spend for nothing.
- The generated `client.sse.post`/`createSseClient` (`web/src/client/core/serverSentEvents.gen.ts:135,228`) throws away the response body on a non-2xx status and retries indefinitely by default (`sseMaxRetryAttempts` unset). A `422 no-citable-answer` is a permanent refusal, not a transient failure, so the chat request must use a hand-rolled `fetch`-based reader (`chatStream.ts`), not the generated SSE client, so the one request can read a JSON error body on failure and an event stream on success.
- Citation click always opens the moment view by `momentId` alone — no branch on `screenshotId`/`sourceDeepLink` presence. `MomentView` (Story 2.2) already renders the transcript-only degraded mode itself; `sourceDeepLink` is not read by this feature.
- The web app never parses `[[moment:` markers; it renders only from the structured `citations` array (AD-15). Concatenating `chat.token` text must reproduce `answer` verbatim — no client-side reformatting.
- Blank or over-length (`>1000` chars, `server/meetingminer/api/chat.py:96`) questions are refused client-side before any request, mirroring the server bound.
- No test may call the live `/chat` endpoint; every chat test mocks `fetch` (AGENTS.md — the Anthropic key is revoked).

**Block If:** none expected — 3.3's contract is `done` and frozen; this is UI wiring against it.

**Never:**
- Nothing under `server/` — 3.3 is done, outside this story's boundary.
- No new `AppView` variant or router — chat is a panel on the home view, like `CorpusSearch`.
- No auto-retry/reconnect loop for `/chat` (unlike `useJobEvents`'s job stream) — a rejected or failed question is not resubmitted automatically.
- No markdown rendering or new dependency — plain text concatenation, matching the rest of `web/`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| SSE happy path | Question submitted; corpus answers | `chat.token` text streams progressively; on `chat.done`, citations render as "Open moment" buttons; a route summary shows ("answered from N moments") | No error expected |
| Gate rejection (422) | Corpus/citation gate refuses | Explicit "no citable answer" state, not a chat bubble; no partial answer shown | Rendered via `role="alert"`-adjacent muted box, distinct from transport failure |
| Store/model unavailable (503) | Meilisearch/Neo4j/model unreachable | Failure banner naming what's unreachable, not silently retried | Shown once, no auto-retry |
| Transport failure | `fetch` throws / network unreachable | Failure banner; no partial answer shown | Shown |
| Citation click | User clicks a rendered citation | `onOpenMoment(momentId)` fires; identical handling regardless of `screenshotId`/`sourceDeepLink` | No error expected |
| Blank/over-length question | User submits blank or >1000 chars | Submit disabled/refused client-side; no request sent | No wasted call |

</intent-contract>

## Code Map

- `web/src/App.tsx:17-23` -- `AppView` union (its comment names 3.4 as a reuser); `:144-160` -- home-section wiring pattern (`onOpenMoment={(momentId) => open({ kind: 'moment', momentId })}`) to copy for the chat panel.
- `web/src/features/search/CorpusSearch.tsx` -- the state-shape, `aria-live` region, and `failure`/`busy` pattern to mirror; `onOpenMoment` optional-prop convention.
- `web/src/features/search/hits.ts` -- `SearchFailure` type and `problemMessage` re-export precedent for a `ChatFailure` type.
- `web/src/features/moments/MomentView.tsx` -- three-way failure split (transport red alert vs. muted domain-refusal box) — the template for the "no citable answer" state.
- `web/src/features/meetings/useJobEvents.ts` -- existing SSE consumption shape (`AbortController`, `onSseEvent`/`onSseError`, `for await`) for reference only; not reused directly (see Boundaries).
- `web/src/client/core/serverSentEvents.gen.ts:135,228` -- why the generated SSE client is unsuitable for `/chat`'s error path.
- `web/src/client/types.gen.ts:12-70` -- `ChatRequest`/`ChatResponse`/`CitationModel`; `:678-710` -- `RouteModel` (comment names this story's "answered from N moments" display); `:1127-1152` -- `AskCorpusData`/`Responses`/`Errors`, with the exact frame payload shapes documented on the `200` response (`chat.token` → `{event, text}`, `chat.citations` → `{event, citations}`, `chat.done` → `{event, route}`).
- `web/src/client/client.gen.ts` -- exported `client` (`buildUrl`, configured `baseUrl`) — use `client.buildUrl({ url: '/chat' })` for the request URL rather than a hardcoded string.
- `web/src/lib/api.ts` -- `API_BASE`, where `client` is configured.
- `server/meetingminer/api/chat.py:889-916` -- `_reject()`, confirming the `422` body's `reason` and `route` extensions (read-only, frozen contract).

## Tasks & Acceptance

**Execution:**
- `web/src/features/chat/chatStream.ts` -- new: hand-rolled `fetch`-based reader for `POST /chat` with `Accept: text/event-stream`. Parses SSE frames into typed `chat.token`/`chat.citations`/`chat.done` events; on a non-2xx response, parses the JSON body (preserving `reason`) instead of throwing a generic error -- one request handles both outcomes.
- `web/src/features/chat/chat.ts` -- new: pure helpers -- frame type guards, `ChatFailure` type (`transport` | `rejected` | `problem`), `routeSummary(route)` formatter.
- `web/src/features/chat/ChatPanel.tsx` -- new: question input, submit, streamed answer text, citations as "Open moment" buttons via optional `onOpenMoment` prop, the "no citable answer" state, and the failure banner.
- `web/src/features/chat/ChatPanel.test.tsx` -- new: tests over a mocked `fetch` (a `Response` built from a `ReadableStream` of SSE text) covering the happy path, a 422 rejection, a transport failure, and citation-click wiring.
- `web/src/App.tsx` -- add `<ChatPanel onOpenMoment={...} />` to the home section beside `CorpusSearch`, reusing the existing `open({ kind: 'moment', momentId })` wiring.

**Acceptance Criteria:**
- Given the app shell, when the home view renders, then a chat panel is visible alongside search, with no new `AppView` variant or router introduced.
- Given a rendered citation is clicked, when `onOpenMoment` is wired by the shell, then it opens the moment view for that `momentId` (Story 2.2) with replay available there, identically for every citation regardless of `screenshotId`/`sourceDeepLink`.
- Given a validated answer's citations, when rendered, then the web app renders only from the structured `citations` array -- it never parses `[[moment:` markers.
- Given `make web-test`, when run, then it is green with no regressions.

## Spec Change Log

## Review Triage Log

### 2026-08-20 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 6: (high 0, medium 3, low 3)
- defer: 0
- reject: 14: (high 0, medium 0, low 14)
- addressed_findings:
  - `[low]` `[patch]` Duplicate `momentId`s in the `citations` array collide on React key and `data-testid`, silently dropping a row. Keyed by `${momentId}-${index}` instead.
  - `[medium]` `[patch]` A stream that ends without ever delivering a `chat.done` frame (connection cut mid-stream) was treated as a silent success, showing a partial answer with no failure surfaced. `ask()` now treats a stream that completes with `route` still `null` as a failure.
  - `[medium]` `[patch]` No client-side timeout on the `/chat` request left the panel stuck on "Asking…"/"Finishing…" forever on a stalled connection, with no cancel affordance. Added a generous `AbortSignal.timeout` (60s, chat synthesis is slower than search) combined with the caller's abort signal, surfaced as a named timeout failure.
  - `[low]` `[patch]` The abort/supersede guard (a re-submit aborts the in-flight stream) had no test. Added one asserting only the second question's answer lands.
  - `[low]` `[patch]` `chatStream.ts`'s final-chunk-with-no-trailing-blank-line handling (a real server behavior the code comments call out) had no test. Added one.
  - `[medium]` `[patch]` The `App.tsx` chat-citation-to-`MomentView` wiring had no test exercising it through the app shell, unlike the identical wiring for search and the meetings list. Added an `App.test.tsx` case mirroring the existing search one.

Rejected (dropped): SSE request bypassing generated-client interceptors (none configured in this app); no inline citation-to-claim linkage (out of scope — AD-15/3.3's contract renders citations as a flat array, not inline anchors); citations not sorted by `startMs` (contract specifies first-appearance order; current behavior is correct); textarea stays editable while streaming (cosmetic, no functional bug — the in-flight question is captured before the request starts); no clear/reset affordance, no Enter-to-submit, no live character counter (UX enhancements outside the AC); "Finishing…" state claimed to persist indefinitely (verified false — `busy` clears in `finally` regardless of citation count); "answered from 0 moments" phrasing (structurally unreachable — 3.3 refuses empty retrieval before any model call, so a validated answer always has `retrieved >= 1`); spec frontmatter missing a timestamp bump (process metadata, not a code defect); runtime field-level validation of `citations`/`route` payloads (consistent with the existing codebase convention of trusting the typed, tested backend contract — `SearchHit`/`MomentDetail` aren't field-validated either); `parseFrame` silently dropping an unparseable/unrecognized frame without logging (low value — the pinned event names are a tested server contract); `CHAT_QUESTION_MAX_LENGTH` hand-copied from the server rather than the OpenAPI schema (the spec explicitly required mirroring the server bound this way).

## Design Notes

**Why not reuse `useJobEvents`'s SSE pattern directly.** That hook is built on the generated `client.sse.get`, which retries forever on any failure by default and discards the response body when the status isn't `2xx`. For a job stream that's correct — a dropped connection is normal and there's no error body to read. For `/chat`, a `422 no-citable-answer` is the server's final word on this question; retrying would resubmit it (and, if it ever *did* succeed on a later attempt against a changed corpus, would be surprising). `chatStream.ts` is a small hand-rolled reader instead: one `fetch`, one parse of either the event stream or the JSON error body, no retry loop. *Assumption to attack: a transient network blip during streaming now surfaces as a plain failure rather than being retried — acceptable here because the user has a visible "ask again" affordance, unlike the job list's ambient stream.*

**Progressive token rendering is safe by construction.** Story 3.3 validates the whole answer before any `chat.token` event is sent — the stream is a replay of an already-gated answer, never a live draft. So the panel can append each token's text to the visible answer as it arrives with no risk of showing an uncited or later-rejected fragment.

## Verification

**Commands:**
- `cd <worktree> && make web-test` -- expected: green, no regressions (store-free, no live server or model call).

**Manual checks (if no CLI):**
- With the api and stores up (announce first, per AGENTS.md), submit a question in the chat panel against a projected corpus and confirm citations open the moment view at the cited moment.

## Auto Run Result

Status: done
Blocking condition: none

### What was implemented

A `chat` feature under `web/src/features/chat/`: `chatStream.ts`, a hand-rolled
`fetch`-based SSE reader for `POST /chat` that reads a `422 no-citable-answer`
JSON body on the same request instead of retrying it (unlike the generated SSE
client); `chat.ts`, pure frame type guards, the `ChatFailure` taxonomy, and
display formatters; `ChatPanel.tsx`, the question input, progressively
streamed answer, citations rendered as "Open moment" buttons keyed by
`momentId`, an explicit "no citable answer" state distinct from the transport
failure banner, and a route summary line. Wired into `App.tsx`'s home section
beside `CorpusSearch`, reusing the existing `open({ kind: 'moment', momentId })`
navigation with no new `AppView` variant or router. A review pass found and
patched: a citation-list key/testid collision on a repeated `momentId`, a
stream ending without `chat.done` being shown as a silent partial success, no
client-side timeout on the request, and three missing tests (the
abort/supersede guard, the no-trailing-blank-line final SSE chunk, and the
`App.tsx` wiring exercised end to end).

### Files changed

- `web/src/features/chat/chatStream.ts` — the SSE reader.
- `web/src/features/chat/chat.ts` — frame guards, `ChatFailure`, formatters.
- `web/src/features/chat/ChatPanel.tsx` — the panel; patched for the
  key/testid collision, the missing-`chat.done` guard, and the 60s timeout.
- `web/src/features/chat/ChatPanel.test.tsx` — happy path, 422 rejection,
  transport failure, 503 outage, client-side length refusal; patched with the
  abort/supersede and no-`chat.done`/no-trailing-blank-line cases.
- `web/src/App.tsx` — mounts `ChatPanel` beside `CorpusSearch`.
- `web/src/App.test.tsx` — patched with a case proving the chat-citation-to-
  `MomentView` wiring end to end.

### Review findings breakdown

6 patches applied (medium 3, low 3); 0 deferred; 14 rejected as out of scope,
already correct, or verified non-issues (see Review Triage Log). No intent
gaps, no spec-level defects, no loopback.

### Follow-up review recommendation

`true`. Patched counts high 0, medium 3, low 3; score = 3×3 + 1×3 = 12.

### Verification performed

- `make web-test` — 162/162 passed before the review patches; 166/166 passed
  after (four new tests), observed directly in this worktree both times.
- `pnpm exec tsc -b` — clean, both before and after patches.
- `pnpm run lint` — clean both times (one pre-existing, unrelated `button.tsx`
  fast-refresh warning).

Matrix test audit: all 6 I/O rows are covered by tests that ran and passed —
SSE happy path, gate rejection, store/model outage, transport failure,
citation click, and blank/over-length refusal.

### Residual risks

- The manual check (submitting a real question against a projected corpus with
  the api and stores up) was not performed — it requires starting the shared
  Docker stores, which needs an explicit go-ahead per AGENTS.md, and was out of
  scope for this unattended run.
- The silent-supersede UX gap on a re-submit is deferred (frontmatter
  `deferred`, severity low) rather than fixed — it's a product judgment call,
  not a correctness defect.

### Independent review

An independent, fresh-context review (dispatched from
`review-prompt-story-3-4-2026-08-20.md`, filed as
`review-story-3-4-2026-08-20.md`, `make check-reviews` passing) found no
high-severity findings and confirmed both design decisions it was asked to
scrutinize most closely. Of its 3 findings:

- **Finding 1** (medium — the 60s timeout used `AbortSignal.timeout()`
  directly instead of the `setTimeout`-plus-`AbortController` pattern
  `CorpusSearch`/`MomentView` already use for the same testability reason,
  which is exactly what the "no automated test" residual risk above used to
  name): **fixed**. `ChatPanel.tsx` now uses the explicit-timer pattern;
  the previously-untestable timeout path is now consistent with the rest of
  `web/`'s cancellation conventions (still not itself covered by a new test —
  the same fake-timer unreliability applies to `CorpusSearch`'s own timeout,
  which is also untested this way; that gap is pre-existing and out of this
  story's scope to close).
- **Finding 2** (low — silent supersede on re-submit): **deferred** (see
  frontmatter `deferred` and Residual risks above).
- **Finding 3** (low — the hand-built `/chat` request body wasn't type-bound
  to the generated `ChatRequest`): **fixed**. `chatStream.ts` now asserts
  `{ question } satisfies ChatRequest`.

Re-verified after these two fixes: `make web-test` 166/166 passed, `tsc -b`
clean, `pnpm run lint` clean (same one pre-existing `button.tsx` warning).

### Review Findings

- [x] [Review][Patch] Treat `chat.done` as the terminal completion boundary and
  publish citations only on that boundary
  [web/src/features/chat/ChatPanel.tsx:84] — the current reader continues
  waiting for transport close after `chat.done`; a completed answer on a
  connection held open by an intermediary reaches the 60-second timeout, is
  cleared, and is reported as failed. Citations also become clickable before
  the completion event that declares the answer complete.
- [x] [Review][Patch] Mirror the API's character bound using Unicode code
  points [web/src/features/chat/chat.ts:71] — JavaScript `string.length` counts
  UTF-16 code units while the Python API's length validation counts Unicode
  code points, so a server-valid 501-emoji question is refused locally.
- [x] [Review][Patch] Cover the controlled 60-second timeout path
  [web/src/features/chat/ChatPanel.test.tsx:106] — the explicit timer and
  timeout diagnosis have no executable regression test; removal of the expiry
  signal or a wrong timeout classification would leave the suite green.
- [x] [Review][Defer] Surface that a re-submit interrupted an in-flight answer
  [web/src/features/chat/ChatPanel.tsx:60] — deferred as a product UX judgment,
  already recorded in this story's frontmatter rather than a correctness fix.

Remediated in `b849577`: `chat.done` now ends consumption and exposes retained
citations only on successful completion; the question limit counts Unicode code
points; mocked-fetch coverage proves both terminal completion without transport
close and the 60-second timeout. `make web-test` passed 169/169, TypeScript was
clean, and lint had only the pre-existing `button.tsx` fast-refresh warning.
