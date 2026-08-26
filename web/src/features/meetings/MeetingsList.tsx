import { useCallback, useEffect, useRef, useState } from 'react'
import { listMeetings } from '@/client/sdk.gen'
import type { JobEvent, MeetingListItem } from '@/client/types.gen'
import { Button } from '@/components/ui/button'
import { API_BASE } from '@/lib/api'
import { mediaUrl } from '@/lib/media'
import {
  applyEvent,
  blockedReason,
  corporaOf,
  countParts,
  durationLabel,
  meetingLabel,
  type MeetingSort,
  startedLabel,
  visibleRows,
} from './rows'
import { StageLegend, StageProgress } from './StageProgress'
import { useJobEvents } from './useJobEvents'

/** How long the list waits for `GET /meetings` before naming the timeout. */
export const SEED_TIMEOUT_MS = 5000

function describe(error: unknown): string {
  if (error instanceof Error) return error.message
  if (typeof error === 'string') return error
  return JSON.stringify(error)
}

export interface MeetingsListProps {
  /**
   * Opening a meeting is Epic 2's view. The gate lives here either way, so the
   * affordance is wired to a handler the shell may or may not supply yet.
   */
  onOpen?: (row: MeetingListItem) => void
}

export function MeetingsList({ onOpen }: MeetingsListProps) {
  const [rows, setRows] = useState<Array<MeetingListItem> | null>(null)
  const [seedError, setSeedError] = useState<string | null>(null)
  // Card-view state only: the canonical `rows` stay unfiltered and unsorted so
  // the SSE apply path keeps finding every job, filtered out or not.
  const [corpusFilter, setCorpusFilter] = useState<string | null>(null)
  const [sort, setSort] = useState<MeetingSort>('newest')
  // Mirrors `rows` for the event handler, which must read the current list
  // without re-subscribing the stream on every render.
  const rowsRef = useRef<Array<MeetingListItem> | null>(null)
  // Held across renders so unmount aborts an in-flight seed.
  const controllerRef = useRef<AbortController | null>(null)
  // At most one seed is ever in flight, so a stale response can never
  // overwrite a newer one (story 1.10, finding 22) — the race is closed by
  // construction rather than by an abort-and-discard guard. A request made
  // while one is running is remembered and re-run exactly once afterwards, so
  // a burst of events cannot turn into a burst of fetches.
  const seedStateRef = useRef({ inFlight: false, pending: false, unmounted: false })

  const commit = useCallback((next: Array<MeetingListItem>) => {
    rowsRef.current = next
    setRows(next)
  }, [])

  const fetchMeetings = useCallback(async () => {
    const controller = new AbortController()
    controllerRef.current = controller
    // An explicit timer rather than `AbortSignal.timeout`, for two reasons:
    // that signal cannot be cancelled, so every retry would leave a live timer
    // behind for its full duration; and a real `setTimeout` is something a
    // test can drive, which is the only way this branch is ever exercised.
    const expiry = new AbortController()
    const timer = setTimeout(() => expiry.abort(), SEED_TIMEOUT_MS)
    const signal = AbortSignal.any([controller.signal, expiry.signal])
    try {
      const { data, error } = await listMeetings({ signal })
      if (controller.signal.aborted) return
      if (error !== undefined || data === undefined) {
        throw new Error(`api returned an error response: ${JSON.stringify(error)}`)
      }
      commit(data.meetings)
      setSeedError(null)
    } catch (err) {
      // Unmounted: never set state for a read nobody is waiting on.
      if (controller.signal.aborted) return
      // Rows are deliberately left standing: stale progress beats a blank list.
      setSeedError(expiry.signal.aborted ? `timed out after ${SEED_TIMEOUT_MS}ms` : describe(err))
    } finally {
      clearTimeout(timer)
    }
  }, [commit])

  const requestSeed = useCallback(() => {
    const state = seedStateRef.current
    if (state.inFlight) {
      state.pending = true
      return
    }
    void (async () => {
      state.inFlight = true
      try {
        do {
          state.pending = false
          await fetchMeetings()
        } while (state.pending && !state.unmounted)
      } finally {
        state.inFlight = false
      }
    })()
  }, [fetchMeetings])

  /**
   * The api answered. If the list has never loaded, its seed failed while the
   * api was down and this is the moment to try again — but only when no seed
   * is already running, because that running seed *is* the retry.
   *
   * Without this the view wedges on "Loading meetings…" forever: a first seed
   * that fails leaves `rows` null, and on an idle system no event will ever
   * arrive to prompt another attempt.
   */
  const onAlive = useCallback(() => {
    if (rowsRef.current === null && !seedStateRef.current.inFlight) requestSeed()
  }, [requestSeed])

  const onEvent = useCallback(
    (event: JobEvent) => {
      const current = rowsRef.current
      if (current === null) {
        // No rows to apply to. Either the list never loaded, or — the case
        // that matters — a seed is in flight whose snapshot was read *before*
        // this event. Re-seeding covers both: `requestSeed` coalesces into the
        // running fetch and re-runs it once afterwards, so the list converges
        // on a read taken after the event reached the api. Calling `onAlive`
        // here would drop the event instead, because it declines to act while
        // a seed is in flight — and a dropped `job.done` never recovers, since
        // this branch returns before the `job.done` re-seed below.
        requestSeed()
        return
      }
      const next = applyEvent(current, event)
      if (next === null) {
        requestSeed() // a job this list has never seen
        return
      }
      commit(next)
      // A completed job has just acquired its meeting row; pick up the title.
      if (event.event === 'job.done') requestSeed()
    },
    [commit, requestSeed],
  )

  const connection = useJobEvents({ onEvent, onResync: requestSeed, onAlive })

  useEffect(() => {
    const state = seedStateRef.current
    state.unmounted = false
    requestSeed()
    return () => {
      state.unmounted = true
      controllerRef.current?.abort()
    }
  }, [requestSeed])

  const banner =
    connection.kind === 'lost'
      ? `Lost the progress stream from the api at ${API_BASE}: ${connection.message}. Retrying — the rows below may be stale.`
      : seedError !== null
        ? `Cannot reach the api at ${API_BASE}: ${seedError}. Retrying — the rows below may be stale.`
        : null

  const corpora = rows === null ? [] : corporaOf(rows)
  const shown = rows === null ? null : visibleRows(rows, corpusFilter, sort)

  return (
    <section className="flex w-full flex-col gap-4">
      <header className="flex flex-wrap items-baseline justify-between gap-4">
        <div className="flex items-baseline gap-2">
          <h2 className="text-lg font-semibold tracking-tight uppercase">Meetings</h2>
          {rows !== null && (
            <span
              data-testid="meetings-count"
              className="font-mono text-sm text-muted-foreground"
            >
              {corpusFilter === null || shown === null
                ? rows.length
                : `${shown.length} of ${rows.length}`}
            </span>
          )}
        </div>
        <span data-testid="connection-state" className="text-xs text-muted-foreground">
          {connection.kind === 'live' ? 'live' : connection.kind}
        </span>
      </header>

      {rows !== null && rows.length > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          {/* The filter renders only corpora that exist in the served rows —
              never an invented category (SPEC-ui-reimagine CAP-1). */}
          <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Filter by corpus">
            <Button
              size="sm"
              variant={corpusFilter === null ? 'secondary' : 'ghost'}
              aria-pressed={corpusFilter === null}
              data-testid="corpus-filter-all"
              onClick={() => setCorpusFilter(null)}
            >
              All
            </Button>
            {corpora.map((corpus) => (
              <Button
                key={corpus}
                size="sm"
                variant={corpusFilter === corpus ? 'secondary' : 'ghost'}
                aria-pressed={corpusFilter === corpus}
                data-testid={`corpus-filter-${corpus}`}
                onClick={() => setCorpusFilter(corpus)}
              >
                {corpus}
              </Button>
            ))}
          </div>
          <Button
            size="sm"
            variant="outline"
            data-testid="sort-toggle"
            aria-label={`Sorted ${sort} first — switch to ${sort === 'newest' ? 'oldest' : 'newest'} first`}
            onClick={() => setSort((current) => (current === 'newest' ? 'oldest' : 'newest'))}
          >
            {sort === 'newest' ? 'newest first' : 'oldest first'}
          </Button>
        </div>
      )}

      {banner !== null && (
        <p role="alert" className="rounded-md border border-destructive/40 p-3 text-sm text-destructive">
          {banner}
        </p>
      )}

      {rows === null ? (
        <p className="text-sm text-muted-foreground">Loading meetings…</p>
      ) : rows.length === 0 ? (
        <p data-testid="empty-state" className="rounded-lg border border-dashed p-6 text-sm text-muted-foreground">
          No meetings yet. One appears here when the Teams puller finalizes a source drop and
          posts it to <code>/ingests</code> — files left in the drop folder are never picked
          up on their own.
        </p>
      ) : shown !== null && shown.length === 0 ? (
        <p data-testid="filtered-empty-state" className="rounded-lg border border-dashed p-6 text-sm text-muted-foreground">
          No meetings in the “{corpusFilter}” corpus.
        </p>
      ) : (
        <ul className="flex flex-col gap-3">
          {(shown ?? []).map((row) => {
            const label = meetingLabel(row)
            const reason = row.viewable ? null : blockedReason(row)
            const meta = [startedLabel(row), durationLabel(row.durationMs), row.corpus, row.status]
              .filter((part) => part != null)
              .join(' · ')
            const counts = countParts(row)
            return (
              <li
                key={row.jobId}
                data-testid={`meeting-${row.jobId}`}
                data-viewable={row.viewable}
                className="flex gap-4 rounded-lg border p-4"
              >
                {/* Poster column. Honest absence beats decoration: a meeting
                    with no poster says why in one sentence rather than
                    rendering a decorative placeholder image. */}
                {row.posterScreenshotPath != null ? (
                  <img
                    data-testid={`poster-${row.jobId}`}
                    src={mediaUrl(row.posterScreenshotPath)}
                    alt={`${label} poster screenshot`}
                    loading="lazy"
                    className="h-20 w-32 shrink-0 rounded border object-cover"
                  />
                ) : (
                  <div
                    data-testid={`no-poster-${row.jobId}`}
                    className="flex h-20 w-32 shrink-0 items-center justify-center rounded border border-dashed p-2 text-center text-[10px] leading-tight text-muted-foreground"
                  >
                    {row.hasRecording === false
                      ? 'Transcript only — no recording, so no screens were captured.'
                      : 'No screens captured yet.'}
                  </div>
                )}

                <div className="flex min-w-0 grow flex-col gap-2">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <div className="flex min-w-0 flex-col">
                      <span className="truncate font-medium">{label}</span>
                      <span className="text-xs text-muted-foreground">{meta}</span>
                    </div>
                    {row.hasRecording === false && (
                      <span
                        data-testid={`transcript-only-${row.jobId}`}
                        className="rounded-full border border-slate-400/60 px-2 py-0.5 text-xs text-muted-foreground"
                      >
                        transcript only
                      </span>
                    )}
                  </div>

                  {counts.length > 0 && (
                    <p
                      data-testid={`counts-${row.jobId}`}
                      className="font-mono text-xs text-muted-foreground"
                    >
                      {counts.join(' · ')}
                    </p>
                  )}

                  <StageProgress stages={row.stages} />

                  {row.error !== null && row.error !== undefined && (
                    <p data-testid={`job-error-${row.jobId}`} className="text-xs text-rose-700 dark:text-rose-400">
                      <span className="font-mono">{row.error}</span>
                    </p>
                  )}

                  <div className="flex flex-wrap items-center gap-3">
                    <Button
                      size="sm"
                      disabled={!row.viewable}
                      title={reason ?? undefined}
                      // Every row would otherwise render a button named just
                      // "Open", leaving the rows indistinguishable to a screen
                      // reader and ambiguous to any by-name query.
                      aria-label={`Open ${label}`}
                      aria-describedby={reason ? `reason-${row.jobId}` : undefined}
                      onClick={() => onOpen?.(row)}
                    >
                      Open
                    </Button>
                    {reason !== null && (
                      <span id={`reason-${row.jobId}`} className="text-xs text-muted-foreground">
                        {reason}
                      </span>
                    )}
                  </div>
                </div>
              </li>
            )
          })}
        </ul>
      )}

      <StageLegend />
    </section>
  )
}
