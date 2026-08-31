import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router'
import { Button } from '@/components/ui/button'
import { API_BASE } from '@/lib/api'
import { problemMessage } from '@/lib/problems'
import { MomentCard } from './MomentCard'
import {
  ARTIFACT_KINDS,
  EMPTY_CORPUS,
  FEED_PAGE_SIZE,
  FEED_TIMEOUT_MS,
  RANKED_BY,
  RANKING_SENTENCE,
  fetchMomentsFeed,
  filterEmptySentence,
  hasActiveFilters,
  momentsHeaderCount,
  type FeedFilters,
  type MomentFeedItem,
} from './feed'

/** The corpus tags a drop is recorded under (`docs/glossary.md`). The select
 * also carries any other tag the served items actually use, so a corpus this
 * build has not heard of is still selectable rather than invisible. */
const KNOWN_CORPORA = ['real', 'scripted'] as const

/** The three filters, read from the URL so a filtered view is a link
 * (EXPERIENCE.md · Filters row). */
function filtersFromParams(params: URLSearchParams): FeedFilters {
  return {
    corpus: params.get('corpus'),
    thread: params.get('thread'),
    kind: params.get('kind'),
    meeting: params.get('meeting'),
  }
}

export interface MomentsFeedProps {
  /** Hidden child routes keep this feed mounted; inactive feeds keep their page. */
  active?: boolean
  /** Opening a moment is the shell's navigation to make (story 2.2's rule). */
  onOpenMoment: (momentId: string) => void
  onOpenMeeting: (meetingId: string) => void
  onOpenThread: (threadId: string) => void
}

type FeedState =
  | { kind: 'loading' }
  | { kind: 'ready'; items: Array<MomentFeedItem>; total: number }
  | {
      kind: 'error'
      message: string
      stale: { items: Array<MomentFeedItem>; total: number } | null
      retry: { offset: number; previous: Array<MomentFeedItem> | null }
    }

/**
 * The front door (story 10.5, FR40, UX-DR16/17): the most pressing moments
 * first, each carrying the api's own reason for being there.
 *
 * Every card is a served row — screenshot, meeting and offset, the reason
 * line, thread chips — and each replays in place and links to its moment and
 * its meeting. Nothing on this screen is composed client-side: the ranking is
 * story 10.4's deterministic score, the reasons are its labels verbatim, and
 * the count in the header is its `total`.
 *
 * Filters are URL query params, so a narrowed feed is a link and Back
 * restores it. Paging is an explicit `Show 24 more` button rather than
 * infinite scroll (EXPERIENCE.md · Interaction Primitives).
 */
export function MomentsFeed({
  active = true,
  onOpenMoment,
  onOpenMeeting,
  onOpenThread,
}: MomentsFeedProps) {
  const [params, setParams] = useSearchParams()
  const routeFilters = useMemo(() => filtersFromParams(params), [params])
  const activeFilters = useRef(routeFilters)
  if (active) activeFilters.current = routeFilters
  const filters = activeFilters.current
  const [state, setState] = useState<FeedState>({ kind: 'loading' })
  const stateRef = useRef<FeedState>(state)
  const [expanded, setExpanded] = useState<string | null>(null)

  // Asynchronous ownership (EXPERIENCE.md): every read carries a generation,
  // a newer read aborts the older one, and a late response for a superseded
  // generation is discarded rather than allowed to overwrite the visible feed.
  const generation = useRef(0)
  const controller = useRef<AbortController | null>(null)
  const loadedFilterKey = useRef<string | null>(null)

  const filterKey = JSON.stringify(filters)

  const publish = useCallback((next: FeedState) => {
    stateRef.current = next
    setState(next)
  }, [])

  const read = useCallback(
    async (
      offset: number,
      previous: Array<MomentFeedItem> | null,
      fallback: { items: Array<MomentFeedItem>; total: number } | null,
    ) => {
      controller.current?.abort()
      const own = new AbortController()
      controller.current = own
      const mine = (generation.current += 1)
      const timeout = AbortSignal.timeout(FEED_TIMEOUT_MS)
      const signal = AbortSignal.any([own.signal, timeout])
      if (previous === null && fallback === null) publish({ kind: 'loading' })
      try {
        const page = await fetchMomentsFeed(filters, FEED_PAGE_SIZE, offset, signal)
        if (mine !== generation.current) return
        const next: FeedState = {
          kind: 'ready',
          items: previous === null ? page.items : [...previous, ...page.items],
          total: page.total,
        }
        if (offset === 0) loadedFilterKey.current = filterKey
        publish(next)
      } catch (error) {
        if (mine !== generation.current) return
        if (own.signal.aborted && !timeout.aborted) return
        const problem = (error as { problem?: unknown })?.problem
        const named = problemMessage(problem)
        const message = timeout.aborted
          ? `timed out after ${FEED_TIMEOUT_MS}ms`
          : (named ?? (error instanceof Error ? error.message : String(error)))
        publish({ kind: 'error', message, stale: fallback, retry: { offset, previous } })
      }
    },
    [filterKey, filters, publish],
  )

  useEffect(() => {
    if (!active) return
    const current = stateRef.current
    const fallback =
      current.kind === 'ready'
        ? { items: current.items, total: current.total }
        : current.kind === 'error'
          ? current.stale
          : null
    if (loadedFilterKey.current === filterKey && fallback !== null) return
    void read(0, null, fallback)
    return () => controller.current?.abort()
    // `filterKey` rather than `filters`: the object is rebuilt on every
    // `useSearchParams` render, and re-reading the feed on an unrelated
    // re-render would restart paging under the reader.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, filterKey])

  const setFilter = useCallback(
    (name: keyof FeedFilters, value: string | null) => {
      const next = new URLSearchParams(params)
      if (value === null || value === '') next.delete(name)
      else next.set(name, value)
      setExpanded(null)
      setParams(next)
    },
    [params, setParams],
  )

  const clearFilters = useCallback(() => {
    const next = new URLSearchParams(params)
    for (const name of ['corpus', 'thread', 'kind', 'meeting']) next.delete(name)
    setParams(next)
  }, [params, setParams])

  const items =
    state.kind === 'ready'
      ? state.items
      : state.kind === 'error'
        ? (state.stale?.items ?? null)
        : null

  // Esc collapses the expanded card and returns focus to its Replay button —
  // the card is the topmost open thing on this screen.
  useEffect(() => {
    if (expanded === null) return
    const openId = expanded
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      setExpanded(null)
      const trigger = document.querySelector<HTMLElement>(`[data-testid="replay-${openId}"]`)
      trigger?.focus()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [expanded])

  // Thread options come from the threads the served items actually carry.
  // `GET /threads` (story 10.3) is the designed source and becomes the source
  // once it lands; until then the client offers only threads it has observed
  // rather than inventing a list.
  const threadOptions = useMemo(() => {
    const byId = new Map<string, string>()
    for (const item of items ?? []) {
      for (const thread of item.threads) byId.set(thread.threadId, thread.name)
    }
    return [...byId.entries()].sort((a, b) => a[1].localeCompare(b[1]))
  }, [items])

  const corpusOptions = useMemo(() => {
    const seen = new Set<string>(KNOWN_CORPORA)
    for (const item of items ?? []) if (item.corpus !== '') seen.add(item.corpus)
    return [...seen].sort()
  }, [items])

  const filtered = hasActiveFilters(filters)
  const total =
    state.kind === 'ready'
      ? state.total
      : state.kind === 'error'
        ? (state.stale?.total ?? 0)
        : 0
  const shown = items?.length ?? 0
  const threadName = threadOptions.find(([id]) => id === filters.thread)?.[1] ?? null

  return (
    <section className="flex flex-col gap-2" data-testid="moments-feed" aria-label="Moments">
      <div className="flex flex-wrap items-baseline justify-between gap-4">
        <h2 className="text-sm font-medium text-muted-foreground">
          Moments{' '}
          <span className="font-mono tabular-nums text-foreground" data-testid="moments-count">
            {momentsHeaderCount(shown, total, filtered)}
          </span>
        </h2>
        <div className="flex flex-wrap items-center gap-2" data-testid="moments-filters">
          <FilterSelect
            name="corpus"
            value={filters.corpus}
            options={corpusOptions.map((corpus) => [corpus, corpus])}
            onChange={(value) => setFilter('corpus', value)}
          />
          <FilterSelect
            name="thread"
            value={filters.thread}
            options={threadOptions}
            onChange={(value) => setFilter('thread', value)}
          />
          <FilterSelect
            name="kind"
            value={filters.kind}
            options={ARTIFACT_KINDS.map((kind) => [kind, kind])}
            onChange={(value) => setFilter('kind', value)}
          />
        </div>
      </div>
      <p className="text-xs text-muted-foreground">{RANKED_BY}</p>

      {state.kind === 'loading' && (
        <p className="mt-4 text-sm text-muted-foreground" data-testid="moments-loading">
          {RANKING_SENTENCE}
        </p>
      )}

      {state.kind === 'error' && (
        <p className="mt-4 text-sm text-destructive" data-testid="moments-error">
          Cannot reach the api at {API_BASE}: {state.message}.
          {state.stale !== null && ' The cards below may be stale.'}{' '}
          <Button
            size="sm"
            variant="outline"
            onClick={() =>
              void read(state.retry.offset, state.retry.previous, state.stale)
            }
          >
            Retry
          </Button>
        </p>
      )}

      {items !== null && items.length === 0 && (
        <div className="mt-4 flex flex-col items-start gap-3" data-testid="moments-empty">
          <p className="text-sm">
            {filtered ? filterEmptySentence(filters, threadName) : EMPTY_CORPUS}
          </p>
          {filtered && (
            <Button size="sm" variant="outline" onClick={clearFilters}>
              Clear filters
            </Button>
          )}
        </div>
      )}

      {items !== null && items.length > 0 && (
        <>
          {/* DESIGN.md · Layout & Spacing owns these numbers: three columns at
              >=1440px, two at 1280-1439, one below. Written as explicit
              min-widths rather than Tailwind's xl/2xl, whose 1280/1536
              breakpoints would give the 1280x800 recording target one
              column fewer than the design states. */}
          <div className="mt-3 grid grid-cols-1 gap-5 min-[1280px]:grid-cols-2 min-[1440px]:grid-cols-3">
            {items.map((item) => (
              <MomentCard
                key={item.momentId}
                item={item}
                expanded={expanded === item.momentId}
                onToggleReplay={() =>
                  setExpanded((open) => (open === item.momentId ? null : item.momentId))
                }
                onOpenMoment={() => onOpenMoment(item.momentId)}
                onOpenMeeting={() => onOpenMeeting(item.meetingId)}
                onSelectKind={(kind) => setFilter('kind', kind)}
                onOpenThread={onOpenThread}
              />
            ))}
          </div>
          {items.length < total && (
            <div className="mt-6 flex justify-center">
              <Button
                variant="outline"
                data-testid="moments-show-more"
                onClick={() => void read(items.length, items, { items, total })}
              >
                Show {Math.min(FEED_PAGE_SIZE, total - items.length)} more
              </Button>
            </div>
          )}
        </>
      )}
    </section>
  )
}

/** One filter: a labelled native select whose empty option is "any". Native
 * because it is keyboard- and screen-reader-correct with no work, and this
 * screen's job is the cards. */
function FilterSelect({
  name,
  value,
  options,
  onChange,
}: {
  name: string
  value: string | null
  options: Array<[string, string]>
  onChange: (value: string | null) => void
}) {
  return (
    <label
      className="inline-flex min-h-6 items-center gap-1.5 rounded-md border px-2 py-1 text-xs"
      style={{ borderColor: 'var(--control-border)' }}
    >
      <span className="text-muted-foreground">{name}</span>
      <select
        data-testid={`filter-${name}`}
        aria-label={`Filter by ${name}`}
        className="bg-transparent text-xs text-foreground outline-none"
        value={value ?? ''}
        onChange={(event) => onChange(event.target.value === '' ? null : event.target.value)}
      >
        <option value="">any</option>
        {options.map(([optionValue, label]) => (
          <option key={optionValue} value={optionValue}>
            {label}
          </option>
        ))}
      </select>
    </label>
  )
}
