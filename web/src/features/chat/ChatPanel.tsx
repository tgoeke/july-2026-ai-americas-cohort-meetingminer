import { type FormEvent, useCallback, useEffect, useRef, useState } from 'react'
import type { CitationModel, RouteModel } from '@/client/types.gen'
import { SourceLinkAnchor } from '@/components/SourceLinkAnchor'
import { Button } from '@/components/ui/button'
// The ask box's model select (story 8.3). One element in the header row — the
// panel's anatomy is otherwise unchanged, and the popover owns its own reads,
// its own writes and its own failure states.
import { ModelSelect } from '@/features/settings/ModelSelect'
import { offsetLabel, sourceLinkOf } from '@/lib/affordance'
import { API_BASE } from '@/lib/api'
import { chatStream } from './chatStream'
import { type ChatFailure, classifyFailure, questionProblem, routeSummary } from './chat'

export interface ChatPanelProps {
  /**
   * Opening a citation's moment view is the shell's navigation to make, the
   * same optional-prop convention `CorpusSearch.onOpenMoment` uses: the
   * affordance lives here, the navigation lives in whatever mounts this.
   * Called with `momentId` alone — identically for every citation, regardless
   * of `screenshotId`/`sourceDeepLink` (`MomentView` renders the degraded
   * mode itself).
   */
  onOpenMoment?: (momentId: string) => void
  presentation?: 'standalone' | 'chrome'
  expanded?: boolean
}

/** How long a question waits for the api before it names the timeout — a
 * generous bound because synthesis is two model calls plus retrieval, not
 * one index lookup (`CorpusSearch.SEARCH_TIMEOUT_MS` is 8s for comparison). */
const CHAT_TIMEOUT_MS = 60_000

/**
 * Ask a question over the corpus, stream the cited answer, follow a citation
 * into the moment view (FR15, UX-DR10).
 *
 * One request per submitted question (Boundaries): `chatStream()` is the only
 * call this component makes, over a hand-rolled `fetch` reader rather than
 * the generated SSE client, because a `422 no-citable-answer` is the server's
 * final word on this question and must not be retried
 * (`web/src/features/chat/chatStream.ts`).
 *
 * Progressive rendering is safe by construction: story 3.3 validates the
 * whole answer before any `chat.token` event is sent, so appending each
 * token's text as it arrives can never show an uncited or later-rejected
 * fragment.
 */
export function ChatPanel({
  onOpenMoment,
  presentation = 'standalone',
  expanded = false,
}: ChatPanelProps = {}) {
  const [question, setQuestion] = useState('')
  // `null` is "no answer for the current turn yet"; `''` is "the request is
  // under way but no token has arrived" — the same null/empty split
  // `CorpusSearch` uses for `rows`, so a fresh submit renders neither a stale
  // answer nor a permanent loading state.
  const [answer, setAnswer] = useState<string | null>(null)
  const [citations, setCitations] = useState<Array<CitationModel>>([])
  const [route, setRoute] = useState<RouteModel | null>(null)
  const [failure, setFailure] = useState<ChatFailure | null>(null)
  const [busy, setBusy] = useState(false)
  // Held across renders so a re-submit aborts the in-flight stream before
  // starting another — an older answer must never overwrite a newer one
  // (story 1.10, finding 22 — the same guard `CorpusSearch` and `MomentView`
  // apply to their own requests).
  const controllerRef = useRef<AbortController | null>(null)

  const problem = questionProblem(question)

  const ask = useCallback(async (asked: string) => {
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller
    // An explicit timer rather than `AbortSignal.timeout`: that signal cannot
    // be cancelled, so a superseded or unmounted request would otherwise
    // leave a live timer running for its full duration, and a real
    // `setTimeout` is something a test can drive — the same pattern
    // `CorpusSearch.runSearch` and `MomentView` use for their own timeouts.
    // 60s, not `CorpusSearch`'s 8s: chat synthesis is two model calls plus
    // retrieval, not one index lookup.
    const expiry = new AbortController()
    const timer = setTimeout(() => expiry.abort(), CHAT_TIMEOUT_MS)
    setAnswer('')
    setCitations([])
    setRoute(null)
    setFailure(null)
    setBusy(true)
    let doneReceived = false
    let completedCitations: Array<CitationModel> | null = null
    try {
      // Inside the `try` so the `finally` owns the timer from the moment it
      // exists: `AbortSignal.any` throwing here would otherwise leak a live
      // timer that aborts a controller nothing is listening to.
      const signal = AbortSignal.any([controller.signal, expiry.signal])
      for await (const frame of chatStream(asked, { signal })) {
        if (controller.signal.aborted) return
        if (frame.event === 'chat.token') {
          setAnswer((current) => (current ?? '') + frame.text)
        } else if (frame.event === 'chat.citations') {
          // `chat.citations` precedes `chat.done` on the wire, but citations
          // become actionable only once the terminal event confirms the whole
          // answer completed. Retain them locally until then so a connection
          // cut after this frame cannot briefly expose a failed turn.
          completedCitations = frame.citations
        } else {
          setCitations(completedCitations ?? [])
          setRoute(frame.route)
          doneReceived = true
          // `chat.done` is the protocol's terminal boundary, not merely more
          // data. Waiting for transport close can turn a completed answer into
          // a timeout when an intermediary keeps the connection open.
          break
        }
      }
      // Superseded (re-submit) or unmounted while the stream was ending, with
      // no throw to catch: never set a "connection closed" failure for a
      // question nobody is waiting on any more.
      if (controller.signal.aborted) return
      if (!doneReceived) {
        // The stream closed before `chat.done` arrived — a server crash or a
        // cut connection mid-stream, not a validated answer. Showing whatever
        // tokens/citations happened to arrive as if they were the complete
        // answer would be a silent partial success; only a fully replayed
        // answer is trustworthy (Design Notes: the stream is a replay of an
        // already-gated answer, never a live draft).
        setAnswer(null)
        setCitations([])
        setRoute(null)
        // `interrupted`, not `transport`: the connection *was* established and
        // the server accepted the question — "Cannot reach the api" would
        // diagnose a live server as down (SPEC CAP-3).
        setFailure({
          kind: 'interrupted',
          message: 'the connection closed before the answer completed',
        })
      }
    } catch (err) {
      // Superseded (re-submit) or unmounted: never set state for a question
      // nobody is waiting on. An intentional abort surfaces as `AbortError`.
      if (controller.signal.aborted) return
      // No partial answer is shown on any failure: the gate validates the
      // whole answer before the first `chat.token`, so a 422 never streamed
      // one, and any other failure means the stream never finished either.
      setAnswer(null)
      setCitations([])
      setRoute(null)
      // The expiry's own abort is a `timeout`, never `transport`: the wait ran
      // out on a request the server may well have accepted and still be
      // answering — the recorded failure this distinction fixes reported a
      // live server as unreachable (SPEC CAP-3, `failure-evidence.md`). The
      // wording names the wait, not the transport.
      setFailure(
        expiry.signal.aborted
          ? {
              kind: 'timeout',
              message: `the api did not finish within ${CHAT_TIMEOUT_MS / 1000}s`,
            }
          : classifyFailure(err),
      )
    } finally {
      clearTimeout(timer)
      if (!controller.signal.aborted) setBusy(false)
    }
  }, [])

  useEffect(() => () => controllerRef.current?.abort(), [])

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    // Not gated on `busy`: a re-submit while a question is still in flight is
    // exactly the case `ask()`'s own `controllerRef.current?.abort()` exists
    // to handle — the reader should not have to wait out a slow answer to
    // fix a mistyped question, and the abort guard makes sure the older
    // stream can never overwrite the newer one (story 1.10, finding 22).
    if (problem !== null) return
    void ask(question.trim())
  }

  const showAnswer = answer !== null && answer !== ''
  const compact = presentation === 'chrome'

  return (
    <section
      className={compact ? 'relative w-full' : 'flex w-full flex-col gap-4'}
      data-testid={compact ? 'chrome-ask-surface' : undefined}
      aria-expanded={compact ? expanded : undefined}
    >
      <header className={compact ? 'sr-only' : 'flex flex-wrap items-center justify-between gap-3'}>
        <h2 className="text-lg font-semibold tracking-tight">Ask</h2>
        {!compact && <ModelSelect />}
      </header>

      <form
        onSubmit={handleSubmit}
        className={compact ? 'flex items-center gap-1.5' : 'flex flex-col gap-2'}
      >
        <label className={compact ? 'min-w-0 flex-1 text-sm' : 'flex flex-col gap-1 text-sm'}>
          <span className={compact ? 'sr-only' : 'text-muted-foreground'}>
            Ask a question about what was discussed — the answer is cited to
            the moments it came from
          </span>
          <textarea
            data-testid="chat-question-input"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="What did we decide about the purchase order?"
            rows={compact ? 1 : 2}
            aria-expanded={compact ? expanded : undefined}
            aria-controls={compact ? 'chrome-ask-results' : undefined}
            className={
              compact
                ? 'h-8 w-full resize-none rounded-md border px-2 py-1 text-sm'
                : 'rounded-md border px-3 py-2 text-sm'
            }
          />
        </label>
        {compact && <ModelSelect compact />}
        <div className={compact ? 'flex items-center' : 'flex items-center gap-3'}>
          <Button
            type="submit"
            size="sm"
            disabled={problem !== null}
            data-testid="chat-submit"
          >
            {busy ? 'Asking…' : 'Ask'}
          </Button>
          {!compact && question.trim() !== '' && problem !== null && (
            <span data-testid="chat-question-problem" className="text-xs text-destructive">
              {problem}
            </span>
          )}
        </div>
      </form>

      <div
        id={compact ? 'chrome-ask-results' : undefined}
        hidden={compact && !expanded}
        className={
          compact
            ? 'absolute top-[calc(100%+0.75rem)] right-0 z-40 flex max-h-[min(38rem,calc(100vh-5rem))] w-[min(38rem,calc(100vw-2rem))] flex-col gap-4 overflow-y-auto rounded-lg border bg-popover p-4 shadow-md'
            : 'contents'
        }
      >
        {compact && question.trim() !== '' && problem !== null && (
          <span data-testid="chat-question-problem" className="text-xs text-destructive">
            {problem}
          </span>
        )}
        {failure !== null && failure.kind !== 'rejected' && (
        <p
          role="alert"
          data-testid="chat-failure"
          className="rounded-md border border-destructive/40 p-3 text-sm text-destructive"
        >
          {/* "Cannot reach" is reserved for `transport` — a fetch that never
              connected. A timeout or a cut stream reached a live server, and
              saying otherwise sends the operator to restart an api that is up
              (SPEC CAP-3). */}
          {failure.kind === 'transport'
            ? `Cannot reach the api at ${API_BASE}: ${failure.message}.`
            : failure.kind === 'timeout'
              ? `The api at ${API_BASE} accepted the question but ${failure.message} — it may still be answering.`
              : failure.kind === 'interrupted'
                ? `The api at ${API_BASE} was answering, but ${failure.message}.`
                : `The api at ${API_BASE} could not answer that question: ${failure.message}.`}
        </p>
      )}

      {failure !== null && failure.kind === 'rejected' && (
        // Muted, not the destructive red alert above — a gate rejection is
        // the system working as designed, not a transport or store failure
        // (the same distinction `MomentView` draws between its transport
        // alert and its domain-refusal box).
        <p
          role="alert"
          data-testid="chat-rejected"
          className="rounded-md border p-3 text-sm text-muted-foreground"
        >
          No citable answer
          {failure.message ? `: ${failure.message}` : ' — nothing in the corpus supports one.'}
        </p>
      )}

        <div aria-live="polite" aria-busy={busy} className="flex flex-col gap-3">
        {showAnswer && (
          <div
            data-testid="chat-answer"
            className="whitespace-pre-wrap rounded-lg border p-4 text-sm"
          >
            {answer}
          </div>
        )}

        {citations.length > 0 && (
          <ul data-testid="chat-citations" className="flex flex-col gap-2">
            {citations.map((citation, index) => {
              // UX-DR12: a YouTube citation also links back to the video at
              // this offset. `CitationModel` carries no `hasRecording`, so
              // this is the provider check alone — another host's link has
              // no affordance on this surface, exactly as before.
              const source = sourceLinkOf(citation.sourceDeepLink, citation.startMs)
              return (
                <li
                  // `momentId` alone collides when the same moment is cited
                  // twice (two separate excerpts) — the index disambiguates
                  // both the key and the testid.
                  key={`${citation.momentId}-${index}`}
                  data-testid={`chat-citation-${citation.momentId}-${index}`}
                  className="flex items-center justify-between gap-2 rounded-md border p-2 text-sm"
                >
                  <span className="text-xs text-muted-foreground">
                    {offsetLabel(citation.startMs)}
                  </span>
                  <span className="flex flex-wrap items-center gap-2">
                    {/* Only when a shell wired the navigation: an enabled
                        button that silently does nothing is exactly the dead
                        affordance `CorpusSearch`'s own optional prop exists to
                        avoid. Opens by `momentId` alone, identically
                        regardless of `screenshotId`/`sourceDeepLink` —
                        `MomentView` renders the degraded mode itself. */}
                    {onOpenMoment !== undefined && (
                      <Button
                        size="sm"
                        variant="outline"
                        aria-label={`Open moment at ${offsetLabel(citation.startMs)}`}
                        onClick={() => onOpenMoment(citation.momentId)}
                      >
                        Open moment
                      </Button>
                    )}
                    {source?.provider === 'youtube' && (
                      <SourceLinkAnchor
                        link={source}
                        testId={`chat-citation-youtube-${citation.momentId}-${index}`}
                      />
                    )}
                  </span>
                </li>
              )
            })}
          </ul>
        )}

        {route !== null && (
          <p data-testid="chat-route-summary" className="text-xs text-muted-foreground">
            {routeSummary(route)}
          </p>
        )}

        {busy && (!showAnswer || citations.length === 0) && (
          <p data-testid="chat-busy" className="text-sm text-muted-foreground">
            {showAnswer ? 'Finishing…' : 'Asking…'}
          </p>
        )}
        </div>
      </div>
    </section>
  )
}
