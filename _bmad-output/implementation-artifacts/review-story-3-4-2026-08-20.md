# Review — Story 3.4 (Chat UI with Streaming & Replay Citations)

> **THIS REVIEW DID NOT SATISFY THE INDEPENDENT-REVIEW GATE. Added 2026-08-20,
> after the fact.** It was produced by a Claude subagent dispatched by the
> building session into its own worktree — the same model family as the
> builder, which is the one thing independent review exists to rule out. The
> house process is a Codex `bmad-code-review` session, which this story's own
> handoff prompt names at line 201.
>
> The findings below are real and two were applied (`f950bdc`); nothing here is
> retracted. But do not read this file as evidence that story 3-4 was
> independently reviewed. The Codex review of the landed range is filed
> separately as `review-story-3-4-<date>-codex.md`. `make check-reviews` passed
> on this file because the gate asserts a report exists, not who wrote it — see
> `deferred-work.md`.

## Scope

Independent code review of `story/3-4`, performed in a dedicated worktree
(`meetingminer-wt/3-4-review`, branch `story/3-4-review`) per
`_bmad-output/implementation-artifacts/review-prompt-story-3-4-2026-08-20.md`.

## Review range

`63d6fb1..dc08dd5` (branch `story/3-4`, rebased onto `main` at `b93285b`).

Commits in range:
- `b6825d6` — feat(3-4): add chat panel with SSE streaming and citation-to-moment wiring
- `459a709` — fix(3-4): apply 6 review findings to ChatPanel (partial-stream guard, timeout, key collision, tests)
- `95fd97a` — docs(3-4): close review with 6 patches applied, status done
- `dc08dd5` — docs(3-4): reviewer handoff prompt (this file)

In-scope files:
- `web/src/features/chat/chatStream.ts`
- `web/src/features/chat/chat.ts`
- `web/src/features/chat/ChatPanel.tsx`
- `web/src/features/chat/ChatPanel.test.tsx`
- `web/src/App.tsx` (the `ChatPanel` mount only)
- `web/src/App.test.tsx` (the one added case)

## Verification baseline

Run in the review worktree (in-scope files from `dc08dd5` checked out over
this worktree's `main`-derived tree, store-free):

- `pnpm run test` — 166 passed, 10 test files, 0 failed. Matches the prompt's
  expected numbers.
- `pnpm exec tsc -b` — clean, exit 0.
- `pnpm run lint` — clean except the one pre-existing `button.tsx` fast-refresh
  warning named in the prompt as unrelated to this story. Matches.

No disagreement with the prompt's stated baseline.

## Findings

### Finding 1

- **Location** — `web/src/features/chat/ChatPanel.tsx:70` (`const timeout = AbortSignal.timeout(CHAT_TIMEOUT_MS)`)
- **Severity** — medium
- **Finding** — The 60s chat timeout uses `AbortSignal.timeout()` directly, not the explicit-timer pattern (`setTimeout` + a separate `AbortController`) that this codebase already uses in two sibling features for exactly this reason.
- **Evidence** — `web/src/features/search/CorpusSearch.tsx:82-87` and `web/src/features/moments/MomentView.tsx:62-66` both comment, near-verbatim: "An explicit timer rather than `AbortSignal.timeout`: that signal cannot be cancelled, so a superseded read would leave a live timer behind, and a real `setTimeout` is something a test can drive." `ChatPanel.tsx` does not follow that pattern, and the spec's own `## Auto Run Result / Residual risks` names the direct consequence: "`AbortSignal.timeout`'s internal timer is not reliably controllable under vitest's fake timers... this path is verified by code inspection only." The review prompt frames this as an open question ("was a controllable-timer approach... available and skipped") — it was not just available, it is the established pattern two features over in the same directory tree, used specifically to solve this exact testability problem.
- **Suggested direction** — Bring `ChatPanel.tsx`'s timeout in line with `CorpusSearch`/`MomentView`'s `setTimeout`-plus-`AbortController` pattern; this would both close the residual-risk gap and remove the one inconsistency between this story's SSE-reading code and the rest of `web/`'s request-cancellation conventions.

### Finding 2

- **Location** — `web/src/features/chat/ChatPanel.tsx:143-152` (`handleSubmit`, not gated on `busy`) and `:78-82` (state reset at the top of `ask()`)
- **Severity** — low
- **Finding** — A re-submit while a question is in flight silently discards the prior answer with no visible indication to the user that anything was abandoned.
- **Evidence** — `ask()` unconditionally calls `setAnswer('')`, `setCitations([])`, `setRoute(null)`, `setFailure(null)` at the top of every call, including a call that supersedes an in-flight one; there is no message, toast, or state distinguishing "the previous question completed" from "the previous question was interrupted by a new one." The review prompt's design decision 5 explicitly asks whether this was "fully threaded through" on the UI side. `CorpusSearch` has the same silent-supersede behavior, but that panel is live-as-you-type search where discarding a stale query is the expected UX; `ChatPanel`'s submit is a single deliberate action per question, so losing a partially-streamed answer with zero feedback is a more consequential and more surprising gap for the same pattern.
- **Suggested direction** — Not necessarily a blocking gap for this story's AC, but worth a follow-up: surface something as small as a one-line note ("previous question was interrupted") when a re-submit aborts an in-flight stream that had already started rendering an answer.

### Finding 3

- **Location** — `web/src/features/chat/chatStream.ts:79` (hand-built request body: `body: JSON.stringify({ question })`)
- **Severity** — low
- **Finding** — The outgoing `/chat` request body is not type-checked against the generated `ChatRequest`/`AskCorpusData` types, unlike the citations/route in the response, which are.
- **Evidence** — `web/src/client/types.gen.ts:1127-1128` defines `AskCorpusData = { body: ChatRequest }`, but `chatStream.ts` builds `{ question }` as a bare object literal, never importing or asserting against `ChatRequest`. `chat.ts` does import `CitationModel`/`RouteModel` from the same generated file for the response side, so the gap is narrow (request body only), matching the review prompt's own framing of design decision 7. Confirmed also: `infra/Makefile:170-173`'s `check-client` target only checks that `client.gen.ts`/`sdk.gen.ts`/`types.gen.ts` exist as files — it does not diff them against a freshly regenerated client, so nothing in CI would catch a server-side request-shape change silently drifting from this hand-built body.
- **Suggested direction** — A minimal fix (`body: JSON.stringify({ question } satisfies ChatRequest)`) would close this at near-zero cost and doesn't require reintroducing the generated SSE client. The `check-client` staleness gap is pre-existing (story 1.10) and out of this story's scope to close, but is worth flagging as a shared dependency of this finding's risk.

### Design decisions attacked, not upheld as findings

- **Decision 1** (hand-rolled `fetch` reader vs. generated SSE client): confirmed necessary, not just convenient. `web/src/client/core/serverSentEvents.gen.ts:132` unconditionally does `if (!response.ok) throw new Error(...)` before the body is ever read, regardless of `sseMaxRetryAttempts`. There is no configuration of the generated client that would have preserved the 422 `reason` extension; the hand-rolled reader was the only viable option that keeps one request per question.
- **Decision 2** (citations navigate by `momentId` alone): confirmed correct by reading `MomentView.tsx:37-94` — it independently fetches the full `MomentDetail` from `momentId` and computes its own `affordanceOf(detail)` branch (replay / deep link / inert link / no-evidence) entirely from that fetched detail, never from anything the caller passed in. Duplicating a `screenshotId`/`sourceDeepLink` branch in `ChatPanel` would be genuinely redundant, as the spec assumes.
- **Decision 4** (stream-without-`chat.done` treated as failure): traced the `doneReceived`/abort interaction through every ordering JS's single-threaded execution allows — the `controller.signal.aborted` checks (inside the loop, immediately after it exits, and in the `catch`) cover every interleaving; no race was found. The added test (`ChatPanel.test.tsx`, "surfaces a failure, not a silent partial answer...") genuinely pins the fix: it asserts `chat-answer`/`chat-citations`/`chat-route-summary` are all absent and the failure names "connection closed before the answer completed," not just a happy-path assertion. Whether discarding a mostly-complete answer outright (vs. showing it with a "connection interrupted" caveat) is the right product call is a UX judgment call the review prompt itself flags as contestable; both this reviewer and the original builder land on "discard," and the reasoning (an unfinished stream is not a validated answer) is sound given AD-15/3.3's contract. No finding filed against it.
- **Decision 6** covered by Finding 1 above.
- **Decision 7** covered by Finding 3 above.

## Overall assessment

No high-severity findings. The story's own in-repo review pass (6 patches
applied in `459a709`) closed the issues it found competently — the
partial-stream guard, the key/testid collision, and the timeout addition are
all real fixes with tests that exercise the actual failure mode, not just
happy paths. The two design decisions the review prompt most wanted a second
opinion on (decision 2's `MomentView` assumption, decision 4's
`doneReceived`/abort race) both check out on independent inspection. The
residual findings here are a testability gap the codebase had already solved
elsewhere (Finding 1), a UX nuance around silent supersede (Finding 2, low),
and a narrow type-safety gap on the hand-built request body (Finding 3, low).

## Codex independent re-review (post-landing)

**Reviewer/tool:** Codex `bmad-code-review` (this report corrects the earlier
same-model-family review provenance issue).

**Range reviewed:** `b93285b..f950bdc`; this is the complete Story 3.4 change
range, including the post-review fixes at `f950bdc`. The current integration
head was `72d49bb`, whose process-only documentation commit does not alter this
story's code.

**Layers completed:** Blind Hunter, Edge Case Hunter, Verification Gap Reviewer,
and Acceptance Auditor. No layer failed. The Acceptance Auditor found no frozen
contract or acceptance-criterion violation.

### Confirmed findings

1. **[medium][patch] `web/src/features/chat/ChatPanel.tsx:84` — `chat.done`
   does not end consumption.** The server declares a complete validated answer
   with `chat.done`, but the panel waits for the underlying response to close.
   If an intermediary holds that connection open, the 60-second timer aborts
   and clears the already-complete answer as a timeout. The same code exposes
   citations before that completion boundary. Finish the UI turn on
   `chat.done`, retaining citations for presentation at that point, and test an
   open stream that sends a complete sequence without closing.
2. **[low][patch] `web/src/features/chat/chat.ts:71` — local length validation
   counts UTF-16 code units.** Python validates character length by Unicode code
   points. A 501-emoji question is valid to the API but is locally rejected as
   more than 1000 by `String.length`. Count Unicode code points and add the
   astral-character boundary regression test.
3. **[low][patch] `web/src/features/chat/ChatPanel.test.tsx:106` — timeout
   behavior has no executable regression test.** The explicit controllable
   timer added at `ChatPanel.tsx:71-72` has no test that advances it, observes
   request abort, and asserts the named timeout with no partial answer or
   citations. Removing the expiry signal or misclassifying the abort currently
   leaves the suite green.
4. **[low][defer] `web/src/features/chat/ChatPanel.tsx:60` — silent
   supersede.** Re-submitting deliberately aborts and clears a partial answer
   without an interruption signal. This is a real UX gap, but the frozen story
   already defers it as a product choice; it is recorded in `deferred-work.md`
   rather than treated as a merge blocker.

**Dismissed after source inspection:** generic 422 classification (the current
`/chat` route has one intentional 422 refusal path and client-side bounds),
shallow runtime validation of server-owned SSE payloads, silently ignored
unknown/malformed frames, transport `event:`/payload duplication, content-type
hardening, split-CRLF parsing, and extra unmount/malformed-frame tests. These
are either pinned server-contract behavior, explicitly rejected by this
story's existing triage on the codebase's generated-contract convention, or
additional hardening with no current consumer failure.

**Review verdict:** not mergeable as-is: one medium and two low unpatched
findings remain. The existing low UX deferral is non-blocking.

### Remediation and final verdict

All three patch findings were applied in `b849577`
(`fix(3-4): complete chat turns on done`). The implementation breaks stream
consumption at `chat.done`, promotes retained citations only at that terminal
event, uses Unicode code-point counting for the mirrored question bound, and
adds mocked-fetch regression coverage for both an open transport after a
complete event sequence and the 60-second timeout.

Verification observed after remediation: `make web-test` 169/169 passed,
`pnpm exec tsc -b` clean, `pnpm run lint` clean except the known unrelated
`button.tsx` fast-refresh warning, and `make check-reviews` passed.

**Final review verdict: passes.** The silent-supersede UX item remains a
non-blocking, explicitly recorded deferral.
