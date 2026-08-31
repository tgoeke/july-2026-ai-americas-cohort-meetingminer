import { BEYOND_PALETTE_NOTE, paintFor, swatchStyle } from './palette'
import { ThreadCuration, type CurationAction } from './ThreadCuration'
import type { CuratedThread, ThreadSummary } from './threadsApi'

/**
 * The list column: every thread, searchable by name and sortable by activity or
 * recency, with the thread's own hue and its lap swatch.
 *
 * Colour is never the only carrier of identity — the name is always printed, in
 * the lap-1 hue, with a 12 × 12 swatch beside it that carries the lap
 * (`DESIGN.md` · Threads). Selecting a row enters that thread on the canvas.
 */

/** How the list is ordered. Both orders are stable on name. */
export type ThreadSort = 'activity' | 'recency'

export interface ThreadListProps {
  threads: Array<ThreadSummary>
  query: string
  onQueryChange: (query: string) => void
  sort: ThreadSort
  onSortChange: (sort: ThreadSort) => void
  focusedThreadId: string | null
  onFocus: (threadId: string) => void
  /**
   * Mentions inside the visible window, per thread, when the bands tier has
   * resolved. Activity means *in the window*; before there is a window's worth
   * of data the corpus-wide `mentionCount` is the honest answer, and the header
   * says which is being used.
   */
  activity: Record<string, number> | null
  /**
   * Re-read `GET /threads` after a curation landed (story 10.2a). Absent on a
   * read-only mount: without a way to refresh, the controls would leave the
   * list showing the grouping the user just corrected, which reads as the
   * correction having failed.
   */
  onCurated?: (thread: CuratedThread, action: CurationAction) => void
}

/** Search matches on the name, case-insensitively, as a substring. */
export function matchesQuery(thread: ThreadSummary, query: string): boolean {
  const needle = query.trim().toLowerCase()
  if (needle.length === 0) return true
  return thread.name.toLowerCase().includes(needle)
}

/** The list order: activity descending, or last mention descending. */
export function sortThreads(
  threads: ReadonlyArray<ThreadSummary>,
  sort: ThreadSort,
  activity: Record<string, number> | null,
): Array<ThreadSummary> {
  const weight = (thread: ThreadSummary) =>
    activity === null ? thread.mentionCount : (activity[thread.threadId] ?? 0)
  return [...threads].sort((a, b) => {
    if (sort === 'activity') {
      const delta = weight(b) - weight(a)
      if (delta !== 0) return delta
    } else {
      const delta = Date.parse(b.lastMentionAt) - Date.parse(a.lastMentionAt)
      if (delta !== 0) return delta
    }
    return a.name.localeCompare(b.name)
  })
}

export function ThreadList({
  threads,
  query,
  onQueryChange,
  sort,
  onSortChange,
  focusedThreadId,
  onFocus,
  activity,
  onCurated,
}: ThreadListProps) {
  const visible = sortThreads(threads.filter((t) => matchesQuery(t, query)), sort, activity)

  return (
    <aside aria-label="Threads" className="min-w-0 md:w-[280px] md:shrink-0 md:border-r md:pr-6">
      <div className="flex items-baseline gap-2 text-sm font-medium text-muted-foreground">
        Threads <span className="font-mono tabular-nums text-foreground">{threads.length}</span>
      </div>

      <input
        type="search"
        value={query}
        onChange={(event) => onQueryChange(event.target.value)}
        aria-label="Search threads by name"
        placeholder="Search threads by name"
        className="mt-3 h-8 w-full rounded-md border border-white/34 bg-transparent px-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
      />

      <div role="group" aria-label="Sort threads" className="mt-3 flex items-center gap-2 text-xs">
        <button
          type="button"
          aria-pressed={sort === 'activity'}
          onClick={() => onSortChange('activity')}
          className={`min-h-6 rounded-sm px-2 ${sort === 'activity' ? 'text-foreground underline' : 'text-muted-foreground'}`}
        >
          activity
        </button>
        <span aria-hidden="true" className="text-muted-foreground">
          ·
        </span>
        <button
          type="button"
          aria-pressed={sort === 'recency'}
          onClick={() => onSortChange('recency')}
          className={`min-h-6 rounded-sm px-2 ${sort === 'recency' ? 'text-foreground underline' : 'text-muted-foreground'}`}
        >
          recency
        </button>
      </div>

      {visible.length === 0 ? (
        <div className="mt-4 text-sm">
          <p>No threads match &quot;{query}&quot;.</p>
          <button
            type="button"
            onClick={() => onQueryChange('')}
            className="mt-2 min-h-6 rounded-md border border-white/34 px-2 text-xs"
          >
            Clear
          </button>
        </div>
      ) : (
        <ul className="mt-3 space-y-1">
          {visible.map((thread) => {
            const paint = paintFor(thread.colorOrdinal)
            const selected = thread.threadId === focusedThreadId
            return (
              <li key={thread.threadId} aria-current={selected ? 'true' : undefined}>
                <button
                  type="button"
                  onClick={() => onFocus(thread.threadId)}
                  className={`mm-focusable flex w-full flex-col items-start gap-0.5 rounded-md px-2 py-1.5 text-left ${selected ? 'bg-muted' : 'hover:bg-muted/60'}`}
                >
                  <span
                    className="flex items-center gap-2 text-sm font-medium"
                    style={{ color: paint.name }}
                  >
                    <span
                      aria-hidden="true"
                      data-testid={`lap-swatch-${thread.threadId}`}
                      data-lap={paint.lap}
                      className="inline-block size-3 shrink-0 rounded-[2px]"
                      style={swatchStyle(paint)}
                    />
                    {thread.name}
                  </span>
                  <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
                    {thread.mentionCount} mentions · {thread.meetingCount} meetings · last{' '}
                    {thread.lastMentionAt.slice(0, 10)}
                  </span>
                </button>
                {paint.lap === 3 ? (
                  <p className="px-2 text-[11px] text-muted-foreground">{BEYOND_PALETTE_NOTE}</p>
                ) : null}
                {onCurated !== undefined ? (
                  <ThreadCuration
                    thread={thread}
                    mergeTargets={threads.filter((t) => t.threadId !== thread.threadId)}
                    onCurated={onCurated}
                  />
                ) : null}
              </li>
            )
          })}
        </ul>
      )}
    </aside>
  )
}
