import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { Button, buttonVariants } from '@/components/ui/button'
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
  feedCorpusFromParam,
  filterEmptySentence,
  hasActiveFilters,
  momentsHeaderCount,
  type FeedFilters,
  type MomentFeedItem,
} from './feed'
import { fetchThreadOptions, THREADS_TIMEOUT_MS, type ThreadOption } from './threads'

/** The corpus tags a drop is recorded under (`docs/glossary.md`). The select
 * also carries any other tag the served items actually use, so a corpus this
 * build has not heard of is still selectable rather than invisible. */
const KNOWN_CORPORA = ['real', 'scripted'] as const

/** The three filters, read from the URL so a filtered view is a link
 * (EXPERIENCE.md · Filters row). */
function filtersFromParams(params: URLSearchParams): FeedFilters {
  return {
    corpus: feedCorpusFromParam(params.get('corpus')),
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
  | { kind: 'ready'; items: Array<MomentFeedItem>; total: number; corpusTotal: number }
  | {
      kind: 'error'
      message: string
      stale: { items: Array<MomentFeedItem>; total: number; corpusTotal: number } | null
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
  const [focusAfterAppend, setFocusAfterAppend] = useState<string | null>(null)
  const [announcement, setAnnouncement] = useState('')
  const [threadQuery, setThreadQuery] = useState('')
  const [threadCatalog, setThreadCatalog] = useState<
    | { kind: 'loading' }
    | { kind: 'ready'; options: Array<ThreadOption> }
    | { kind: 'error'; message: string }
  >({ kind: 'loading' })

  // Asynchronous ownership (EXPERIENCE.md): every read carries a generation,
  // a newer read aborts the older one, and a late response for a superseded
  // generation is discarded rather than allowed to overwrite the visible feed.
  const generation = useRef(0)
  const controller = useRef<AbortController | null>(null)
  const loadedFilterKey = useRef<string | null>(null)
  const threadController = useRef<AbortController | null>(null)

  const filterKey = JSON.stringify(filters)

  const publish = useCallback((next: FeedState) => {
    stateRef.current = next
    setState(next)
  }, [])

  const read = useCallback(
    async (
      offset: number,
      previous: Array<MomentFeedItem> | null,
      fallback: {
        items: Array<MomentFeedItem>
        total: number
        corpusTotal: number
      } | null,
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
          corpusTotal: page.corpusTotal,
        }
        if (offset === 0) loadedFilterKey.current = filterKey
        publish(next)
        if (offset > 0 && page.items.length > 0) {
          setFocusAfterAppend(page.items[0].momentId)
          const noun = page.items.length === 1 ? 'moment' : 'moments'
          setAnnouncement(`${page.items.length} more ${noun} — ${next.items.length} of ${page.total}`)
        }
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
        ? {
            items: current.items,
            total: current.total,
            corpusTotal: current.corpusTotal,
          }
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

  const readThreadCatalog = useCallback(() => {
    threadController.current?.abort()
    const own = new AbortController()
    threadController.current = own
    const timeout = AbortSignal.timeout(THREADS_TIMEOUT_MS)
    setThreadCatalog({ kind: 'loading' })
    void fetchThreadOptions(AbortSignal.any([own.signal, timeout])).then(
      (options) => setThreadCatalog({ kind: 'ready', options }),
      (error: unknown) => {
        if (own.signal.aborted && !timeout.aborted) return
        setThreadCatalog({
          kind: 'error',
          message: timeout.aborted
            ? `timed out after ${THREADS_TIMEOUT_MS}ms`
            : error instanceof Error
              ? error.message
              : String(error),
        })
      },
    )
  }, [])

  useEffect(() => {
    readThreadCatalog()
    return () => threadController.current?.abort()
  }, [readThreadCatalog])

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

  // Explicit paging must not strand a keyboard user on the button that just
  // disappeared. Once React has mounted the appended cards, put focus on the
  // first new title; the adjacent status region carries the same result to a
  // screen reader without moving visual focus for pointer users.
  useEffect(() => {
    if (focusAfterAppend === null) return
    const title = [...document.querySelectorAll<HTMLElement>('[data-moment-title-id]')].find(
      (candidate) => candidate.dataset.momentTitleId === focusAfterAppend,
    )
    title?.focus()
    setFocusAfterAppend(null)
  }, [focusAfterAppend])

  const threadOptions = useMemo(() => {
    if (threadCatalog.kind !== 'ready') return []
    const needle = threadQuery.trim().toLocaleLowerCase()
    return threadCatalog.options
      .filter((thread) => needle === '' || thread.name.toLocaleLowerCase().includes(needle))
      .map((thread): [string, string] => [thread.threadId, thread.name])
  }, [threadCatalog, threadQuery])

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
  const corpusTotal =
    state.kind === 'ready'
      ? state.corpusTotal
      : state.kind === 'error'
        ? (state.stale?.corpusTotal ?? 0)
        : 0
  const threadName =
    threadCatalog.kind === 'ready'
      ? (threadCatalog.options.find((thread) => thread.threadId === filters.thread)?.name ?? null)
      : null

  return (
    <section className="flex flex-col gap-2" data-testid="moments-feed" aria-label="Moments">
      <p className="sr-only" role="status" aria-live="polite">
        {announcement}
      </p>
      <div className="flex flex-wrap items-baseline justify-between gap-4">
        <h2 className="text-sm font-medium text-muted-foreground">
          Moments
          {items !== null && (
            <>
              {' '}
              <span
                className="font-mono tabular-nums text-foreground"
                data-testid="moments-count"
              >
                {momentsHeaderCount(total, corpusTotal, filtered)}
              </span>
            </>
          )}
        </h2>
        <div className="flex flex-wrap items-center gap-2" data-testid="moments-filters">
          <FilterSelect
            name="corpus"
            value={filters.corpus}
            options={corpusOptions.map((corpus) => [corpus, corpus])}
            onChange={(value) => setFilter('corpus', value)}
          />
          <ThreadFilter
            value={filters.thread}
            options={threadOptions}
            selectedName={threadName}
            query={threadQuery}
            onQueryChange={setThreadQuery}
            unavailable={threadCatalog.kind === 'error' ? threadCatalog.message : null}
            onRetry={readThreadCatalog}
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
        <div
          role="alert"
          className="mt-4 text-sm text-destructive"
          data-testid="moments-error"
        >
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
        </div>
      )}

      {items !== null && items.length === 0 && (
        <div className="mt-4 flex flex-col items-start gap-3" data-testid="moments-empty">
          <p className="text-sm">
            {filtered ? filterEmptySentence(filters, threadName) : EMPTY_CORPUS}
          </p>
          {filtered ? (
            <Button size="sm" variant="outline" onClick={clearFilters}>
              Clear filters
            </Button>
          ) : (
            <Link to="/add" className={buttonVariants({ size: 'sm' })}>
              Add meeting
            </Link>
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
                onClick={() =>
                  void read(items.length, items, { items, total, corpusTotal })
                }
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

function ThreadFilter({
  value,
  options,
  selectedName,
  query,
  onQueryChange,
  unavailable,
  onRetry,
  onChange,
}: {
  value: string | null
  options: Array<[string, string]>
  selectedName: string | null
  query: string
  onQueryChange: (value: string) => void
  unavailable: string | null
  onRetry: () => void
  onChange: (value: string | null) => void
}) {
  const visibleOptions: Array<[string, string]> =
    value !== null && value !== '' && !options.some(([id]) => id === value)
      ? [[value, selectedName ?? value], ...options]
      : options
  return (
    <span className="inline-flex min-h-6 items-center gap-1.5 rounded-md border px-2 py-1 text-xs" style={{ borderColor: 'var(--control-border)' }}>
      <label htmlFor="moments-thread-search" className="text-muted-foreground">
        thread
      </label>
      <input
        id="moments-thread-search"
        data-testid="filter-thread-search"
        type="search"
        value={query}
        placeholder="find"
        aria-label="Search threads"
        className="w-20 bg-transparent text-xs text-foreground outline-none"
        onChange={(event) => onQueryChange(event.target.value)}
      />
      <select
        data-testid="filter-thread"
        aria-label="Filter by thread"
        className="max-w-36 bg-transparent text-xs text-foreground outline-none"
        value={value ?? ''}
        onChange={(event) => onChange(event.target.value === '' ? null : event.target.value)}
      >
        <option value="">any</option>
        {visibleOptions.map(([id, name]) => (
          <option key={id} value={id}>{name}</option>
        ))}
      </select>
      {unavailable !== null && (
        <span
          role="alert"
          aria-label="Thread catalog unavailable"
          data-testid="thread-filter-unavailable"
          className="inline-flex items-center gap-1 text-muted-foreground"
          title={unavailable}
        >
          unavailable
          <button type="button" className="underline" onClick={onRetry}>
            <span className="sr-only">Retry thread catalog</span>
            <span aria-hidden="true">retry</span>
          </button>
        </span>
      )}
    </span>
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
  // A copied filtered URL can be opened before its matching item has appeared
  // in the current page. Native selects otherwise display that real value as
  // blank, making the active constraint both invisible and impossible to
  // clear deliberately.
  const visibleOptions: Array<[string, string]> =
    value !== null && value !== '' && !options.some(([optionValue]) => optionValue === value)
      ? [[value, value], ...options]
      : options
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
        {visibleOptions.map(([optionValue, label]) => (
          <option key={optionValue} value={optionValue}>
            {label}
          </option>
        ))}
      </select>
    </label>
  )
}
