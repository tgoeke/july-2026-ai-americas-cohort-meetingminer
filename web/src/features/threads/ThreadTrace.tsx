/**
 * Threads is a query, not a catalogue (story 10.7, FR42/FR43, UX-DR18).
 *
 * The view **opens empty**. Story 10.6 opened onto every derived thread — 1,090
 * of them, 976 involving exactly one meeting — which is not a list of subjects
 * followed across meetings at all, and no amount of sorting made it one. What
 * replaces it is a box and a handful of subjects the corpus itself suggests.
 *
 * Naming a subject builds one left-to-right timeline of every meeting where it
 * surfaced, and clicking a meeting opens the meeting view. The thread was the
 * route; the meeting is the destination.
 *
 * **What is on screen always says how complete it is.** The api answers on one
 * of two legs — an exhaustive walk of the stored mentions, or a top-k retrieval
 * sample — and this view prints the sentence it sends, prominently, every time.
 * A sample rendered as a full history would be the same unverified-absence
 * failure as claiming no recording exists (AD-18), and this is the one view
 * whose whole claim is that it shows the corpus's true shape over time.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router'

import { useOpenPath } from '@/routes/navigation'

import './trace.css'
import TraceTimeline from './TraceTimeline'
import { paintFor, swatchStyle } from './palette'
import type { Suggestions, ThreadTrace as Trace, TraceFailure } from './traceApi'
import { fetchSuggestions, fetchTrace } from './traceApi'

export default function ThreadTrace() {
  const { threadId } = useParams<'threadId'>()
  const openPath = useOpenPath()
  const [typed, setTyped] = useState('')
  const [suggestions, setSuggestions] = useState<Suggestions | null>(null)
  const [suggestionsFailure, setSuggestionsFailure] = useState<TraceFailure | null>(null)
  const [trace, setTrace] = useState<Trace | null>(null)
  const [failure, setFailure] = useState<TraceFailure | null>(null)
  const [busy, setBusy] = useState(false)
  // Every load carries a generation; a late response may only touch visible
  // state while its generation is current, so a slow first query can never
  // overwrite the answer the reader is already reading.
  const generation = useRef(0)

  useEffect(() => {
    const controller = new AbortController()
    void fetchSuggestions(controller.signal).then(({ data, error }) => {
      if (controller.signal.aborted) return
      if (data !== undefined) setSuggestions(data)
      if (error !== undefined) setSuggestionsFailure(error)
    })
    return () => controller.abort()
  }, [])

  const load = useCallback(async (query: { q?: string; threadId?: string }) => {
    const mine = ++generation.current
    setBusy(true)
    setFailure(null)
    const { data, error } = await fetchTrace(query)
    if (mine !== generation.current) return
    setBusy(false)
    if (error !== undefined) {
      setFailure(error)
      setTrace(null)
      return
    }
    if (data === undefined) return
    setTrace(data)
    // The box must always name what is on screen. Following a related subject
    // while the input still read the old wording left the heading and the box
    // contradicting each other.
    setTyped(data.label)
  }, [])

  // A deep link to a known subject traces it; `/threads` alone stays empty.
  // React Router may reuse this component across the two sibling routes, so
  // absence is an explicit state transition rather than something mount-time
  // initialization can own. Advancing the generation also prevents a deep-link
  // response that lost the race with navigation from repainting the bare route.
  useEffect(() => {
    if (threadId !== undefined) {
      void load({ threadId })
      return
    }
    generation.current += 1
    setTyped('')
    setTrace(null)
    setFailure(null)
    setBusy(false)
  }, [threadId, load])

  const openMeeting = useCallback(
    (meetingId: string) => openPath(`/meetings/${meetingId}`),
    [openPath],
  )

  return (
    <div className="mm-trace-page">
      {/* The screen names itself. The shell places it but does not title it,
          and `shellPlacement.test.tsx` reads this heading to prove the route
          resolved here rather than to the catch-all. */}
      <h1 className="text-3xl font-semibold tracking-tight">Threads</h1>
      <form
        className="mm-trace-ask"
        onSubmit={(event) => {
          event.preventDefault()
          const phrase = typed.trim()
          if (phrase.length > 0) void load({ q: phrase })
        }}
      >
        <input
          value={typed}
          onChange={(event) => setTyped(event.target.value)}
          placeholder="Name a subject to trace across every meeting — e.g. trail closures"
          aria-label="Subject to trace"
        />
        <button type="submit" disabled={busy || typed.trim().length === 0}>
          {busy ? 'Tracing…' : 'Trace'}
        </button>
      </form>

      {trace === null && !busy && (
        <section className="mm-trace-empty">
          <h2>Trace one subject across your meetings</h2>
          <p className="mm-trace-lede">
            Name a concern and see every meeting where it came up, in the order it
            actually happened — then fly down into any of them.
          </p>

          {suggestions !== null && suggestions.subjects.length > 0 && (
            <>
              <h3>Subjects worth tracing</h3>
              <ul className="mm-trace-suggestions">
                {suggestions.subjects.map((subject) => (
                  <li key={subject.threadId}>
                    <button
                      type="button"
                      onClick={() => {
                        setTyped(subject.name)
                        void load({ threadId: subject.threadId })
                      }}
                    >
                      <span
                        className="mm-trace-swatch"
                        style={swatchStyle(paintFor(subject.colorOrdinal))}
                        aria-hidden
                      />
                      <span className="mm-trace-suggestion-name">{subject.name}</span>
                      {/* Its reach, so the choice is considered rather than a
                          button whose label is all that is known about it. */}
                      <span className="mm-trace-suggestion-reach">
                        {subject.reach.meetingCount} meetings over {subject.reach.spanDays} days
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}

          {suggestions !== null && suggestions.subjects.length === 0 && (
            <p className="mm-trace-note">
              No subject in this corpus recurs across between {suggestions.minMeetings} and{' '}
              {suggestions.maxMeetings} meetings over more than {suggestions.minSpanDays} days, so
              there is nothing to suggest. Naming a subject in the box still works.
            </p>
          )}

          {suggestionsFailure !== null && (
            <p className="mm-trace-refusal">
              Suggestions could not be loaded — {suggestionsFailure.message} Naming a subject in
              the box still works.
            </p>
          )}
        </section>
      )}

      {failure !== null && <p className="mm-trace-refusal">{failure.message}</p>}

      {trace !== null && (
        <>
          <header className="mm-trace-head">
            <h2>{trace.label}</h2>
            {/* Which of the two ways in this took, in words, always. */}
            <p className="mm-trace-completeness" data-mode={trace.mode}>
              {trace.completenessNote}
            </p>
            {trace.resolvedFrom !== null && (
              <p className="mm-trace-note">
                “{trace.resolvedFrom}” names a subject the corpus knows, so this walks every
                stored mention of it rather than the closest few passages.
              </p>
            )}
            {trace.mode === 'sample' && trace.candidates.length > 0 && (
              <div className="mm-trace-candidates">
                {/* Offered, never guessed between: "trail closures" adjoins two
                    subjects and picking one would answer a different question. */}
                <span>Did you mean one of these?</span>
                {trace.candidates.map((candidate) => (
                  <button
                    key={candidate.threadId}
                    type="button"
                    onClick={() => {
                      setTyped(candidate.name)
                      void load({ threadId: candidate.threadId })
                    }}
                  >
                    {candidate.name}
                    <span className="mm-trace-suggestion-reach">
                      {candidate.meetingCount} meetings · {candidate.spanDays}d
                    </span>
                  </button>
                ))}
              </div>
            )}
          </header>

          {trace.stops.length > 0 ? (
            <TraceTimeline trace={trace} onOpenMeeting={openMeeting} />
          ) : (
            <p className="mm-trace-note">
              Nothing in the corpus mentions this, so nothing is drawn.
            </p>
          )}

          {trace.relatedSubjects.length > 0 && (
            <footer className="mm-trace-related">
              <span>Next to this:</span>
              {trace.relatedSubjects.map((related) => (
                <button
                  key={related.threadId}
                  type="button"
                  onClick={() => {
                    setTyped(related.name)
                    void load({ threadId: related.threadId })
                  }}
                  title={`${related.sharedMoments} moments mention it alongside this`}
                >
                  {related.name}
                </button>
              ))}
            </footer>
          )}
        </>
      )}
    </div>
  )
}
