import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router'
import { useOpenPath } from '@/routes/navigation'
import { sortThreads, ThreadList, type ThreadSort } from './ThreadList'
import { TimelineCanvas } from './TimelineCanvas'
import './threads.css'
import {
  cacheKey,
  fetchSpan,
  fitView,
  TIER_MIN_SCALE,
  tierForScale,
  visibleSpan,
  type Span,
  type Tier,
} from './timeline'
import {
  fetchTimeline,
  listThreads,
  type BandBucket,
  type ThreadsFailure,
  type ThreadSummary,
  type TimelineMeeting,
  type TimelineMoment,
  type TimelinePayload,
} from './threadsApi'
import { useTimelineView } from './useTimelineView'

/**
 * The Threads screen (story 10.6).
 *
 * It opens zoomed out — every thread a band across the corpus's time span, with
 * mention density — and one continuous zoom carries the reader down through
 * meetings to moments without changing screens. The tiers are a function of
 * `scale` alone (`timeline.ts`), each is fetched from story 10.3 at its own
 * level for the window on screen, and the outgoing tier stays drawn until the
 * incoming one has data. Nothing is drawn that a moment does not back.
 *
 * The evidence tier and inline replay are story 10.6a and are deliberately not
 * here; this screen clamps at the moments tier's floor.
 */

/** The tier currently drawn, with the data that drew it. */
interface Drawn {
  tier: Tier
  /** Fine-tier payloads stay paired with the thread that supplied them. */
  threadId: string | null
  /** The anchor the layer's `--t` values are relative to. */
  epochMs: number
  bands: Record<string, Array<BandBucket>> | null
  meetings: Array<TimelineMeeting> | null
  moments: Array<TimelineMoment> | null
}

/** Requests are debounced this long before they leave. */
const FETCH_DEBOUNCE_MS = 120

export function Threads() {
  const openPath = useOpenPath()
  // `/threads/:threadId` opens the screen with that thread already entered;
  // `/threads` opens on every band. Both mount this component.
  const { threadId: routeThreadId } = useParams()

  const [threads, setThreads] = useState<Array<ThreadSummary> | null>(null)
  const [listFailure, setListFailure] = useState<ThreadsFailure | null>(null)
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<ThreadSort>('activity')
  const [focusedThreadId, setFocusedThreadId] = useState<string | null>(routeThreadId ?? null)

  const [drawn, setDrawn] = useState<Drawn | null>(null)
  const [pending, setPending] = useState(false)
  const [tierFailure, setTierFailure] = useState<ThreadsFailure | null>(null)
  const [retryVersion, setRetryVersion] = useState(0)

  const corpusSpan = useMemo<Span | null>(() => corpusSpanOf(threads), [threads])

  const view = useTimelineView(
    corpusSpan === null
      ? { from: Date.now(), scale: TIER_MIN_SCALE.bands }
      : fitView(corpusSpan, 1000, TIER_MIN_SCALE.bands),
    drawn?.epochMs ?? 0,
  )

  // The tier is a pure function of the scale and the tier already drawn — the
  // second argument is what gives the thresholds their hysteresis.
  const tierRef = useRef<Tier>('bands')
  const tier = tierForScale(view.view.scale, tierRef.current)
  tierRef.current = tier

  const cacheRef = useRef(new Map<string, Drawn>())
  const generationRef = useRef(0)
  const requestedKeyRef = useRef<string | null>(null)
  const meetingsRef = useRef(new Map<string, Array<TimelineMeeting>>())

  useEffect(() => {
    setFocusedThreadId(routeThreadId ?? null)
  }, [routeThreadId])

  // --- the thread list ------------------------------------------------------

  const loadThreads = useCallback(async () => {
    setListFailure(null)
    const { data, error } = await listThreads()
    if (error !== undefined) {
      setListFailure(error)
      return
    }
    if (data !== undefined) setThreads(data)
  }, [])

  useEffect(() => {
    void loadThreads()
  }, [loadThreads])

  // The corpus span is only known once the list has landed, so the opening
  // window is fitted then — not before, and never twice.
  const fittedRef = useRef(false)
  useEffect(() => {
    if (corpusSpan === null || fittedRef.current) return
    fittedRef.current = true
    view.fitTo(corpusSpan, TIER_MIN_SCALE.bands)
  }, [corpusSpan, view])

  // --- the tier fetch -------------------------------------------------------

  const wanted = useMemo(() => {
    if (threads === null) return null
    const span = fetchSpan(view.view, view.width)
    const ids =
      tier === 'bands'
        ? threads.map((t) => t.threadId)
        : focusedThreadId === null
          ? []
          : [focusedThreadId]
    if (ids.length === 0) return null
    return { ids, span, key: cacheKey(ids, tier, span) }
  }, [threads, tier, focusedThreadId, view.view, view.width])

  useEffect(() => {
    const generation = generationRef.current + 1
    generationRef.current = generation
    if (wanted === null) {
      requestedKeyRef.current = null
      setPending(false)
      return
    }
    if (requestedKeyRef.current === wanted.key) return

    const cached = cacheRef.current.get(wanted.key)
    if (cached !== undefined) {
      requestedKeyRef.current = wanted.key
      setDrawn(cached)
      setTierFailure(null)
      setPending(false)
      return
    }

    requestedKeyRef.current = wanted.key
    setPending(true)

    const controller = new AbortController()
    const timer = setTimeout(() => {
      void (async () => {
        const level = tier
        const results = await Promise.all(
          wanted.ids.map((threadId) =>
            fetchTimeline(
              { threadId, level, from: wanted.span.from, to: wanted.span.to },
              controller.signal,
            ),
          ),
        )
        // Asynchronous ownership: a response may only touch visible state when
        // its generation is still the current one. A late success is discarded
        // exactly as a late failure is.
        if (generationRef.current !== generation || requestedKeyRef.current !== wanted.key) return
        const failed = results.find((r) => r.error !== undefined)
        if (failed?.error !== undefined) {
          setPending(false)
          setTierFailure(failed.error)
          // The outgoing tier stays drawn; the key is released so Retry — or a
          // move back into a tier that has data — asks again.
          requestedKeyRef.current = null
          return
        }
        const next = drawnFrom(level, wanted.ids, results, wanted.span, meetingsRef)
        if (next === null) {
          setPending(false)
          return
        }
        cacheRef.current.set(wanted.key, next)
        setDrawn(next)
        setTierFailure(null)
        setPending(false)
      })()
    }, FETCH_DEBOUNCE_MS)

    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [wanted, tier, retryVersion])

  // --- interaction ----------------------------------------------------------

  // A tier that refused is a wall, not a wobble: zooming further in is blocked
  // until Retry succeeds, so a finer tier is never drawn from coarser data.
  const zoomAt = useCallback(
    (factor: number, focusX: number) => {
      if (tierFailure !== null && factor < 1) return
      view.zoomAt(factor, focusX)
    },
    [tierFailure, view],
  )

  const fitTo = useCallback(
    (span: Span) => {
      if (tierFailure !== null) return
      view.fitTo(span)
    },
    [tierFailure, view],
  )

  const fitAll = useCallback(() => {
    if (corpusSpan !== null) view.fitTo(corpusSpan, TIER_MIN_SCALE.bands)
  }, [corpusSpan, view])

  const focusThread = useCallback((threadId: string) => {
    setFocusedThreadId(threadId)
  }, [])

  const openMoment = useCallback(
    (momentId: string) => {
      openPath(`/moments/${momentId}`)
    },
    [openPath],
  )

  const retry = useCallback(() => {
    setTierFailure(null)
    requestedKeyRef.current = null
    setRetryVersion((version) => version + 1)
  }, [])

  // Activity means mentions *in the visible window*, which only the bands tier
  // knows. Before it has landed the list sorts on the corpus-wide count.
  const activity = useMemo(() => {
    if (drawn?.bands == null) return null
    const window = visibleSpan(view.view, view.width)
    const out: Record<string, number> = {}
    for (const [threadId, buckets] of Object.entries(drawn.bands)) {
      out[threadId] = buckets
        .filter((b) => Date.parse(b.to) >= window.from && Date.parse(b.from) <= window.to)
        .reduce((sum, b) => sum + b.mentionCount, 0)
    }
    return out
  }, [drawn, view.view, view.width])

  const orderedThreads = useMemo(
    () => sortThreads(threads ?? [], sort, activity),
    [threads, sort, activity],
  )

  const displayedThreadId = drawn?.tier === 'bands' ? focusedThreadId : (drawn?.threadId ?? null)

  if (listFailure !== null) {
    return (
      <main className="mx-auto w-full max-w-[1600px] p-8">
        <h1 className="text-3xl font-semibold tracking-tight">Threads</h1>
        <Refusal failure={listFailure} onRetry={() => void loadThreads()} />
      </main>
    )
  }

  if (threads === null) {
    return (
      <main className="mx-auto w-full max-w-[1600px] p-8">
        <h1 className="text-3xl font-semibold tracking-tight">Threads</h1>
        <p className="mt-4 text-sm text-muted-foreground">Loading threads…</p>
      </main>
    )
  }

  if (routeThreadId !== undefined && !threads.some((t) => t.threadId === routeThreadId)) {
    return (
      <main className="mx-auto w-full max-w-[1600px] p-8">
        <h1 className="text-3xl font-semibold tracking-tight">Threads</h1>
        <p className="mt-4 text-sm text-muted-foreground">
          No thread has this id — it may have been merged away.{' '}
          <Link to="/threads" className="underline">
            All threads
          </Link>
        </p>
      </main>
    )
  }

  if (threads.length === 0) {
    return (
      <main className="mx-auto w-full max-w-[1600px] p-8">
        <h1 className="text-3xl font-semibold tracking-tight">Threads</h1>
        <p className="mt-4 text-sm text-muted-foreground">
          No threads yet. Threads appear once two meetings share a topic — extract runs topics per
          meeting (story 10.1).
        </p>
      </main>
    )
  }

  return (
    <main className="mx-auto w-full max-w-[1600px] p-8">
      <h1 className="text-3xl font-semibold tracking-tight">Threads</h1>
      <div className="mt-8 flex flex-col gap-8 md:flex-row">
        <ThreadList
          threads={orderedThreads}
          query={query}
          onQueryChange={setQuery}
          sort={sort}
          onSortChange={setSort}
          focusedThreadId={focusedThreadId}
          onFocus={focusThread}
          activity={activity}
        />
        <div className="min-w-0 flex-1">
          <TimelineCanvas
            tier={drawn?.tier ?? tier}
            view={view.view}
            width={view.width}
            epochMs={drawn?.epochMs ?? 0}
            rootRef={view.rootRef}
            threads={orderedThreads}
            focusedThreadId={displayedThreadId}
            bands={drawn?.bands ?? null}
            meetings={drawn?.meetings ?? null}
            moments={drawn?.moments ?? null}
            pending={pending}
            onZoomAt={zoomAt}
            onPan={view.pan}
            onPanPixels={view.panPixels}
            onFitTo={fitTo}
            onFitAll={fitAll}
            onFocusThread={focusThread}
            onOpenMoment={openMoment}
          />
          {tierFailure !== null ? <Refusal failure={tierFailure} onRetry={retry} /> : null}
        </div>
      </div>
    </main>
  )
}

/** The api's refusal, in the api's own words, with the one way forward. */
function Refusal({ failure, onRetry }: { failure: ThreadsFailure; onRetry: () => void }) {
  return (
    <div
      role="alert"
      className="mt-4 rounded-md border border-destructive bg-destructive/12 p-3 text-sm"
    >
      <p className="font-mono text-xs text-destructive">threads: timeline unavailable</p>
      <p className="mt-1">{failure.message}</p>
      {failure.kind === 'transport' ? (
        <p className="mt-1 text-muted-foreground">→ start the api (make api or make up)</p>
      ) : null}
      <button
        type="button"
        onClick={onRetry}
        className="mm-focusable mt-2 min-h-6 rounded-md border border-white/34 px-2 text-xs"
      >
        Retry
      </button>
    </div>
  )
}

/** The corpus's time span: first mention to last, across every thread. */
export function corpusSpanOf(threads: Array<ThreadSummary> | null): Span | null {
  if (threads === null || threads.length === 0) return null
  const firsts = threads.map((t) => Date.parse(t.firstMentionAt)).filter((t) => !Number.isNaN(t))
  const lasts = threads.map((t) => Date.parse(t.lastMentionAt)).filter((t) => !Number.isNaN(t))
  if (firsts.length === 0 || lasts.length === 0) return null
  return { from: Math.min(...firsts), to: Math.max(...lasts) }
}

/** Assemble one drawable layer from the responses that answered for it. */
function drawnFrom(
  tier: Tier,
  ids: Array<string>,
  results: Array<{ data?: TimelinePayload }>,
  span: Span,
  meetingsRef: { current: Map<string, Array<TimelineMeeting>> },
): Drawn | null {
  const epochMs = Math.floor(span.from)
  if (tier === 'bands') {
    const bands: Record<string, Array<BandBucket>> = {}
    results.forEach((result, i) => {
      const payload = result.data
      if (payload?.level === 'bands') bands[ids[i]] = payload.buckets
    })
    return { tier, threadId: null, epochMs, bands, meetings: null, moments: null }
  }
  if (tier === 'meetings') {
    const payload = results[0]?.data
    if (payload?.level !== 'meetings') return null
    const threadId = ids[0]
    if (threadId === undefined) return null
    meetingsRef.current.set(threadId, payload.meetings)
    return { tier, threadId, epochMs, bands: null, meetings: payload.meetings, moments: null }
  }
  const payload = results[0]?.data
  if (payload?.level !== 'moments') return null
  const threadId = ids[0]
  if (threadId === undefined) return null
  return {
    tier,
    threadId,
    epochMs,
    bands: null,
    // The brackets are the meetings the meetings tier already served — real
    // rows, not spans reconstructed from the moments inside them.
    meetings: meetingsRef.current.get(threadId) ?? null,
    moments: payload.moments,
  }
}
