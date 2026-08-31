import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { bandFillStyle, paintFor } from './palette'
import {
  axisTicks,
  clusterByX,
  clusterSpan,
  densityAlpha,
  isoDay,
  KEY_ZOOM_STEP,
  MOMENT_CELL_WIDTH_PX,
  offsetLabel,
  TIER_MAX_SCALE,
  TIMELINE_GUTTER_PX,
  TIMELINE_ROW_GAP_PX,
  TIMELINE_ROW_HEADER_PX,
  visibleSpan,
  WHEEL_ZOOM_STEP,
  xOf,
  HYSTERESIS,
  type Span,
  type Tier,
  type View,
} from './timeline'
import type { BandBucket, ThreadSummary, TimelineMeeting, TimelineMoment } from './threadsApi'

/**
 * The timeline canvas: a DOM grid — never a `<canvas>` — that draws the bands,
 * meetings and moments tiers over one continuous zoom.
 *
 * Two invariants shape every line here.
 *
 * *No layout jump*: an item's x is `(t − from) / scale`, computed in CSS from
 * two custom properties this component never re-renders to change
 * (`threads.css`, `useTimelineView.ts`). A tier change alters neither `from` nor
 * `scale`, so an item focused before a threshold sits at the same x after it.
 *
 * *Nothing is shown that a moment does not back*: every bucket, mark and tick
 * comes from a story 10.3 response for the window on screen. A bucket with no
 * mentions is drawn at the zero density step because its *span* is real; it is
 * never a target and never carries a label.
 */

/** One addressable cell of the grid, whatever tier drew it. */
export interface Cell {
  id: string
  rowIndex: number
  threadId: string
  /** The time span the cell occupies — what `Enter` zooms to fit. */
  span: Span
  /** The cell's accessible name; it always carries the cell's own data. */
  label: string
  kind: 'bucket' | 'meeting' | 'moment' | 'cluster'
  /**
   * What the cell counts: mentions in a bucket or a meeting, moments in a
   * cluster. A cell that stands for one moment counts one — itself.
   */
  count: number
  /** Set on a moments-tier cell that stands for exactly one moment. */
  momentId?: string
  /** Set on a cluster so its visible and accessible content names its members. */
  momentIds?: Array<string>
}

export interface TimelineCanvasProps {
  tier: Tier
  view: View
  width: number
  /** The anchor every drawn `--t` is relative to. */
  epochMs: number
  rootRef: (node: HTMLDivElement | null) => void
  threads: Array<ThreadSummary>
  focusedThreadId: string | null
  /** Bands per thread id, for the bands tier. */
  bands: Record<string, Array<BandBucket>> | null
  /** The focused thread's meetings, at the meetings and moments tiers. */
  meetings: Array<TimelineMeeting> | null
  /** The focused thread's moments, at the moments tier. */
  moments: Array<TimelineMoment> | null
  /** `true` while a tier fetch is in flight; the outgoing tier stays drawn. */
  pending: boolean
  onZoomAt: (factor: number, focusX: number) => void
  onPan: (fraction: number) => void
  onPanPixels: (dx: number) => void
  onFitTo: (span: Span) => void
  onFitAll: () => void
  onFocusThread: (threadId: string) => void
  onOpenMoment: (momentId: string) => void
}

const BAND_HEIGHT = 24
const BAND_GAP = 4
const STRIP_HEIGHT = 4

/** The custom properties an item positions itself from. */
function atStyle(t: number, epochMs: number): CSSProperties {
  return { '--t': t - epochMs } as CSSProperties
}

function spanStyle(from: number, to: number, epochMs: number): CSSProperties {
  return { '--t': from - epochMs, '--t2': to - epochMs } as CSSProperties
}

/** The grid's accessible name: the tier and the window it is showing. */
export function gridLabel(tier: Tier, view: View, width: number): string {
  const span = visibleSpan(view, width)
  return `Threads timeline — ${tier} tier, ${isoDay(span.from)} to ${isoDay(span.to)}`
}

export function TimelineCanvas(props: TimelineCanvasProps) {
  const {
    tier,
    view,
    width,
    epochMs,
    rootRef,
    threads,
    focusedThreadId,
    bands,
    meetings,
    moments,
    pending,
    onZoomAt,
    onPan,
    onPanPixels,
    onFitTo,
    onFitAll,
    onFocusThread,
    onOpenMoment,
  } = props

  const scrollRef = useRef<HTMLDivElement | null>(null)
  const gridRef = useRef<HTMLDivElement | null>(null)
  const dragRef = useRef<{ pointerId: number; x: number } | null>(null)
  const cellRefs = useRef(new Map<string, HTMLElement>())
  const [focusedCellId, setFocusedCellId] = useState<string | null>(null)
  const [announcement, setAnnouncement] = useState('')
  const [activeCell, setActiveCell] = useState<Cell | null>(null)
  const lastTierRef = useRef<Tier>(tier)
  const focusTimeRef = useRef<number | null>(null)
  // Whether the reader has ever put keyboard focus on a cell. Once they have,
  // a cell that stops existing — a tier change, or two moments clustering as
  // the view zooms out — must hand focus on rather than drop it to the page.
  const hadCellFocusRef = useRef(false)
  // Set while focus is being handed on after a cell stopped existing, so the
  // hand-off does not re-anchor the zoom onto the replacement cell.
  const restoringRef = useRef(false)

  const focusedThread = threads.find((t) => t.threadId === focusedThreadId) ?? null

  // Every drawn cell, as rows, in the order the arrow keys walk them.
  const rows = useMemo<Array<Array<Cell>>>(() => {
    if (tier === 'bands') return bandRows(threads, bands)
    if (tier === 'meetings') return meetingRows(focusedThread, meetings)
    return momentRows(focusedThread, moments, view)
  }, [tier, threads, bands, focusedThread, meetings, moments, view])

  const cells = useMemo(() => rows.flat(), [rows])

  const focusedCell = cells.find((c) => c.id === focusedCellId) ?? null

  // Focus is never lost to the page. On a tier change — or when the cell under
  // focus stops existing — focus moves to the cell whose span contains the
  // previous cell's instant, so the reader stays where they were looking.
  useEffect(() => {
    if (cells.length === 0) {
      setFocusedCellId(null)
      if (hadCellFocusRef.current) gridRef.current?.focus()
      return
    }
    if (focusedCellId !== null && cells.some((c) => c.id === focusedCellId)) return
    const anchor = focusTimeRef.current ?? visibleSpan(view, width).from + (width * view.scale) / 2
    const containing = cells.find((c) => c.span.from <= anchor && anchor <= c.span.to)
    const nearest =
      containing ??
      cells.reduce((best, c) =>
        Math.abs(midOf(c.span) - anchor) < Math.abs(midOf(best.span) - anchor) ? c : best,
      )
    setFocusedCellId(nearest.id)
    // The cell that had focus is gone. If the reader was on it, put them on the
    // cell that replaced it — otherwise the next arrow key goes to the page and
    // the keyboard falls out of the timeline mid-zoom.
    const active = typeof document === 'undefined' ? null : document.activeElement
    if (hadCellFocusRef.current && (active === null || active === document.body)) {
      restoringRef.current = true
      cellRefs.current.get(nearest.id)?.focus()
      restoringRef.current = false
    }
  }, [cells, focusedCellId, view, width])

  // The tier change announces itself once, politely. Continuous zoom does not.
  useEffect(() => {
    if (lastTierRef.current === tier) return
    lastTierRef.current = tier
    setAnnouncement(tierAnnouncement(tier, focusedThread, rows, cells))
  }, [tier, focusedThread, rows, cells])

  const moveFocus = useCallback(
    (cell: Cell | null) => {
      if (cell === null) return
      hadCellFocusRef.current = true
      focusTimeRef.current = midOf(cell.span)
      setFocusedCellId(cell.id)
      cellRefs.current.get(cell.id)?.focus()
    },
    [],
  )

  // The point a zoom step turns about: the instant the reader put focus on,
  // held across every step. Anchoring on the *cell* instead would drift, because
  // the cell is recomputed as the view moves — two moments cluster into one and
  // the cluster's midpoint is not where the reader was looking.
  const focusPointX = useCallback((): number => {
    const anchor = focusTimeRef.current ?? (focusedCell === null ? null : midOf(focusedCell.span))
    return anchor === null ? width / 2 : xOf(anchor, view)
  }, [focusedCell, view, width])

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      if (focusedCell === null && cells.length === 0) return
      const row = rows[focusedCell?.rowIndex ?? 0] ?? []
      const index = row.findIndex((c) => c.id === focusedCell?.id)
      switch (event.key) {
        case 'ArrowRight':
          event.preventDefault()
          if (event.shiftKey) {
            onPan(0.8)
            return
          }
          moveFocus(row[Math.min(row.length - 1, index + 1)] ?? null)
          return
        case 'ArrowLeft':
          event.preventDefault()
          if (event.shiftKey) {
            onPan(-0.8)
            return
          }
          moveFocus(row[Math.max(0, index - 1)] ?? null)
          return
        case 'ArrowDown':
        case 'ArrowUp': {
          event.preventDefault()
          const delta = event.key === 'ArrowDown' ? 1 : -1
          let targetIndex = (focusedCell?.rowIndex ?? 0) + delta
          while (targetIndex >= 0 && targetIndex < rows.length && rows[targetIndex].length === 0) {
            targetIndex += delta
          }
          const target = rows[targetIndex]
          if (target === undefined || target.length === 0) return
          const anchor = focusedCell === null ? 0 : midOf(focusedCell.span)
          moveFocus(
            target.reduce((best, c) =>
              Math.abs(midOf(c.span) - anchor) < Math.abs(midOf(best.span) - anchor) ? c : best,
            ),
          )
          return
        }
        case '+':
        case '=':
          event.preventDefault()
          onZoomAt(1 / KEY_ZOOM_STEP, focusPointX())
          return
        case '-':
        case '_':
          event.preventDefault()
          onZoomAt(KEY_ZOOM_STEP, focusPointX())
          return
        case 'Home':
          event.preventDefault()
          onFitAll()
          return
        case 'Enter':
          event.preventDefault()
          if (focusedCell !== null) {
            if (focusedCell.kind === 'bucket') onFocusThread(focusedCell.threadId)
            onFitTo(focusedCell.span)
          }
          return
        case 'Backspace': {
          event.preventDefault()
          // Out one tier: past this tier's ceiling by the hysteresis margin, so
          // the crossing sticks rather than flapping straight back.
          const ceiling = TIER_MAX_SCALE[tier]
          if (!Number.isFinite(ceiling)) return
          onZoomAt((ceiling * HYSTERESIS * 1.01) / view.scale, focusPointX())
          return
        }
        case 'o':
          if (focusedCell?.momentId !== undefined) {
            event.preventDefault()
            onOpenMoment(focusedCell.momentId)
          }
          return
        default:
      }
    },
    [
      cells.length,
      focusedCell,
      focusPointX,
      moveFocus,
      onFitAll,
      onFitTo,
      onFocusThread,
      onOpenMoment,
      onZoomAt,
      rows,
      tier,
      view.scale,
    ],
  )

  // Ctrl/⌘ + wheel and pinch zoom about the pointer; a plain wheel's horizontal
  // delta pans. The listener is attached natively so it can be non-passive and
  // stop the browser's own page zoom.
  useEffect(() => {
    const node = scrollRef.current
    if (node === null) return
    const onWheel = (event: WheelEvent) => {
      if (event.ctrlKey || event.metaKey) {
        event.preventDefault()
        const grid = gridRef.current
        if (grid === null) return
        const focusX = Math.max(
          0,
          Math.min(width, event.clientX - grid.getBoundingClientRect().left - TIMELINE_GUTTER_PX),
        )
        onZoomAt(event.deltaY > 0 ? WHEEL_ZOOM_STEP : 1 / WHEEL_ZOOM_STEP, focusX)
        return
      }
      if (Math.abs(event.deltaX) > Math.abs(event.deltaY)) {
        event.preventDefault()
        onPanPixels(-event.deltaX)
      }
    }
    node.addEventListener('wheel', onWheel, { passive: false })
    return () => node.removeEventListener('wheel', onWheel)
  }, [onPanPixels, onZoomAt, width])

  const setGridRoot = useCallback(
    (node: HTMLDivElement | null) => {
      gridRef.current = node
      rootRef(node)
    },
    [rootRef],
  )

  const registerCell = useCallback((id: string) => {
    return (node: HTMLElement | null) => {
      if (node === null) cellRefs.current.delete(id)
      else cellRefs.current.set(id, node)
    }
  }, [])

  const cellProps = (cell: Cell) => ({
    role: 'gridcell' as const,
    tabIndex: cell.id === focusedCellId ? 0 : -1,
    'aria-label': cell.label,
    'data-cell-id': cell.id,
    'data-t': String(midOf(cell.span)),
    ref: registerCell(cell.id),
    onFocus: () => {
      hadCellFocusRef.current = true
      if (!restoringRef.current) focusTimeRef.current = midOf(cell.span)
      setFocusedCellId(cell.id)
      setActiveCell(cell)
    },
    onBlur: () => setActiveCell((current) => (current?.id === cell.id ? null : current)),
    onPointerEnter: () => setActiveCell(cell),
    onPointerLeave: () => setActiveCell((current) => (current?.id === cell.id ? null : current)),
    onDoubleClick: () => onFitTo(cell.span),
    title: cell.label,
  })

  return (
    <section aria-label="Threads timeline" className="min-w-0 flex-1">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-medium text-muted-foreground">
          {tierHeading(tier, focusedThread, view, width)}
        </h2>
        <div role="group" aria-label="Timeline zoom and pan" className="flex items-center gap-1">
          <ControlButton label="Zoom out (−)" onClick={() => onZoomAt(KEY_ZOOM_STEP, width / 2)}>
            −
          </ControlButton>
          <ControlButton label="Zoom in (+)" onClick={() => onZoomAt(1 / KEY_ZOOM_STEP, width / 2)}>
            +
          </ControlButton>
          <ControlButton label="Fit (Home)" onClick={onFitAll}>
            Fit
          </ControlButton>
          <ControlButton label="Pan left (Shift+←)" onClick={() => onPan(-0.8)}>
            ‹
          </ControlButton>
          <ControlButton label="Pan right (Shift+→)" onClick={() => onPan(0.8)}>
            ›
          </ControlButton>
        </div>
      </div>

      <div
        ref={scrollRef}
        role="region"
        aria-label="Scrollable Threads timeline data"
        tabIndex={-1}
        onPointerDown={(event) => {
          if (event.button !== 0) return
          dragRef.current = { pointerId: event.pointerId, x: event.clientX }
          event.currentTarget.setPointerCapture?.(event.pointerId)
        }}
        onPointerMove={(event) => {
          const drag = dragRef.current
          if (drag === null || drag.pointerId !== event.pointerId) return
          const dx = event.clientX - drag.x
          drag.x = event.clientX
          if (dx !== 0) onPanPixels(dx)
        }}
        onPointerUp={(event) => {
          if (dragRef.current?.pointerId === event.pointerId) dragRef.current = null
        }}
        onPointerCancel={() => {
          dragRef.current = null
        }}
        className="relative overflow-x-auto rounded-md border bg-card p-4"
      >
        {pending ? <div className="mm-progress" role="presentation" /> : null}
        <div
          ref={setGridRoot}
          role="grid"
          aria-label={gridLabel(tier, view, width)}
          aria-rowcount={rows.length}
          aria-busy={pending || undefined}
          tabIndex={cells.length === 0 ? 0 : -1}
          data-tier={tier}
          data-from={String(view.from)}
          data-scale={String(view.scale)}
          data-epoch={String(epochMs)}
          onKeyDown={handleKeyDown}
          className="relative min-w-0"
        >
          <AxisRow view={view} width={width} epochMs={epochMs} />

          {activeCell !== null ? (
            <div
              aria-hidden="true"
              className="mm-at mm-cursor-line"
              style={atStyle(midOf(activeCell.span), epochMs)}
            />
          ) : null}

          <div key={tier} className="mm-layer">
            {tier === 'bands' ? (
              <BandsTier
                rows={rows}
                threads={threads}
                bands={bands}
                view={view}
                width={width}
                epochMs={epochMs}
                focusedThreadId={focusedThreadId}
                onFocusThread={onFocusThread}
                cellProps={cellProps}
                onActivate={(cell) => {
                  // Drilling a bucket enters that bucket's thread: the meetings
                  // tier draws one thread, so the gesture has to say which.
                  onFocusThread(cell.threadId)
                  onFitTo(cell.span)
                }}
              />
            ) : null}

            {tier === 'meetings' ? (
              <MeetingsTier
                rows={rows}
                threads={threads}
                focusedThread={focusedThread}
                meetings={meetings}
                epochMs={epochMs}
                cellProps={cellProps}
                onActivate={(cell) => onFitTo(cell.span)}
              />
            ) : null}

            {tier === 'moments' ? (
              <MomentsTier
                rows={rows}
                threads={threads}
                focusedThread={focusedThread}
                meetings={meetings}
                moments={moments}
                epochMs={epochMs}
                cellProps={cellProps}
                onActivate={(cell) => {
                  if (cell.momentId !== undefined) onOpenMoment(cell.momentId)
                  else onFitTo(cell.span)
                }}
              />
            ) : null}
          </div>
        </div>
      </div>

      <p aria-live="polite" className="sr-only">
        {announcement}
      </p>
    </section>
  )
}

function ControlButton(props: {
  label: string
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      aria-label={props.label}
      title={props.label}
      onClick={props.onClick}
      className="mm-focusable inline-flex size-6 min-h-6 min-w-6 items-center justify-center rounded-md border border-white/34 text-xs"
    >
      {props.children}
    </button>
  )
}

function AxisRow({ view, width, epochMs }: { view: View; width: number; epochMs: number }) {
  const ticks = axisTicks(view, width)
  const span = visibleSpan(view, width)
  const withinDay = span.to - span.from < 86_400_000
  return (
    <div
      role="row"
      className="mm-track relative mb-2 h-6 border-b"
      style={{ marginLeft: TIMELINE_GUTTER_PX, width }}
    >
      {ticks.map((t) => (
        <div
          key={t}
          role="columnheader"
          className="mm-at whitespace-nowrap pl-1 font-mono text-[11px] tabular-nums text-muted-foreground"
          style={atStyle(t, epochMs)}
        >
          {withinDay ? new Date(t).toISOString().slice(11, 19) : isoDay(t)}
        </div>
      ))}
    </div>
  )
}

function BandsTier(props: {
  rows: Array<Array<Cell>>
  threads: Array<ThreadSummary>
  bands: Record<string, Array<BandBucket>> | null
  view: View
  width: number
  epochMs: number
  focusedThreadId: string | null
  onFocusThread: (threadId: string) => void
  cellProps: (cell: Cell) => Record<string, unknown>
  onActivate: (cell: Cell) => void
}) {
  const {
    rows,
    threads,
    bands,
    view,
    width,
    epochMs,
    focusedThreadId,
    onFocusThread,
    cellProps,
    onActivate,
  } = props
  const visible = visibleSpan(view, width)
  const alphaOf = useMemo(
    () =>
      densityAlpha(
        Object.values(bands ?? {}).flatMap((buckets) =>
          buckets
            .filter(
              (bucket) =>
                Date.parse(bucket.to) >= visible.from && Date.parse(bucket.from) <= visible.to,
            )
            .map((bucket) => bucket.mentionCount),
        ),
      ),
    [bands, visible.from, visible.to],
  )

  if (bands === null) {
    return <p className="py-6 text-sm text-muted-foreground">Loading bands…</p>
  }

  return (
    <div>
      {threads.map((thread, rowIndex) => {
        const paint = paintFor(thread.colorOrdinal)
        const rowCells = rows[rowIndex] ?? []
        return (
          <div
            key={thread.threadId}
            role="row"
            className="flex items-center"
            style={{ gap: TIMELINE_ROW_GAP_PX, marginBottom: BAND_GAP }}
          >
            <button
              type="button"
              role="rowheader"
              onClick={() => onFocusThread(thread.threadId)}
              className="mm-focusable shrink-0 truncate text-left text-xs font-medium"
              data-focused={thread.threadId === focusedThreadId || undefined}
              style={{
                color: paint.name,
                width: TIMELINE_ROW_HEADER_PX,
                textDecoration: thread.threadId === focusedThreadId ? 'underline' : undefined,
              }}
            >
              {thread.name}
            </button>
            <div className="mm-track relative min-w-0 flex-1" style={{ height: BAND_HEIGHT }}>
              {rowCells.map((cell) => {
                const count = cell.count
                return (
                  <div
                    key={cell.id}
                    className="mm-span"
                    style={{ ...spanStyle(cell.span.from, cell.span.to, epochMs), height: BAND_HEIGHT }}
                  >
                    <div
                      aria-hidden="true"
                      className="size-full rounded-[2px]"
                      style={bandFillStyle(paint, alphaOf(count))}
                    />
                    {count > 0 ? (
                      <button
                        type="button"
                        {...(cellProps(cell) as object)}
                        onClick={() => onActivate(cell)}
                        className="mm-hit mm-focusable rounded-[2px]"
                      />
                    ) : null}
                  </div>
                )
              })}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function MeetingsTier(props: {
  rows: Array<Array<Cell>>
  threads: Array<ThreadSummary>
  focusedThread: ThreadSummary | null
  meetings: Array<TimelineMeeting> | null
  epochMs: number
  cellProps: (cell: Cell) => Record<string, unknown>
  onActivate: (cell: Cell) => void
}) {
  const { rows, threads, focusedThread, meetings, epochMs, cellProps, onActivate } = props
  if (focusedThread === null) {
    return <p className="py-6 text-sm text-muted-foreground">Choose a thread to zoom into it.</p>
  }
  if (meetings === null) {
    return <p className="py-6 text-sm text-muted-foreground">Loading meetings…</p>
  }
  const paint = paintFor(focusedThread.colorOrdinal)
  const rowCells = rows[0] ?? []
  return (
    <div>
      <CollapsedStrips threads={threads} focusedThreadId={focusedThread.threadId} />
      <div role="row" className="flex items-center" style={{ gap: TIMELINE_ROW_GAP_PX }}>
        <span
          role="rowheader"
          className="shrink-0 truncate text-xs font-medium"
          style={{ color: paint.name, width: TIMELINE_ROW_HEADER_PX }}
        >
          {focusedThread.name}
        </span>
        <div className="mm-track relative min-w-0 flex-1" style={{ height: 40 }}>
          {rowCells.length === 0 ? (
            <p className="text-xs text-muted-foreground">No meetings in view.</p>
          ) : null}
          {rowCells.map((cell) => {
            const meeting = meetings.find((m) => m.meetingId === cell.id)
            if (meeting === undefined) return null
            return (
              <div
                key={cell.id}
                className="mm-span"
                style={{ ...spanStyle(cell.span.from, cell.span.to, epochMs), height: 40 }}
              >
                <div
                  aria-hidden="true"
                  className="size-full rounded-md"
                  style={{
                    background: `color-mix(in oklab, ${paint.band} 22%, transparent)`,
                    border: `1px solid ${paint.band}`,
                  }}
                />
                <button
                  type="button"
                  {...(cellProps(cell) as object)}
                  onClick={() => onActivate(cell)}
                  className="mm-hit mm-focusable overflow-hidden whitespace-nowrap px-2 text-left text-[11px]"
                >
                  <span className="font-medium" style={{ color: paint.name }}>
                    {meeting.title ?? isoDay(Date.parse(meeting.occurredAt))}
                  </span>
                  <span className="ml-1 font-mono tabular-nums text-muted-foreground">
                    · {meeting.mentionCount} mentions
                  </span>
                </button>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

function MomentsTier(props: {
  rows: Array<Array<Cell>>
  threads: Array<ThreadSummary>
  focusedThread: ThreadSummary | null
  meetings: Array<TimelineMeeting> | null
  moments: Array<TimelineMoment> | null
  epochMs: number
  cellProps: (cell: Cell) => Record<string, unknown>
  onActivate: (cell: Cell) => void
}) {
  const { rows, threads, focusedThread, meetings, moments, epochMs, cellProps, onActivate } = props
  if (focusedThread === null) {
    return <p className="py-6 text-sm text-muted-foreground">Choose a thread to zoom into it.</p>
  }
  if (moments === null) {
    return <p className="py-6 text-sm text-muted-foreground">Loading moments…</p>
  }
  const paint = paintFor(focusedThread.colorOrdinal)
  const rowCells = rows[0] ?? []
  const byId = new Map(moments.map((m) => [m.momentId, m]))
  return (
    <div>
      <CollapsedStrips threads={threads} focusedThreadId={focusedThread.threadId} />
      <div role="row" className="flex items-start" style={{ gap: TIMELINE_ROW_GAP_PX }}>
        <span
          role="rowheader"
          className="shrink-0 truncate text-xs font-medium"
          style={{ color: paint.name, width: TIMELINE_ROW_HEADER_PX }}
        >
          {focusedThread.name}
        </span>
        <div className="mm-track relative min-w-0 flex-1" style={{ height: 128 }}>
          {(meetings ?? []).map((meeting) => (
            <div
              key={meeting.meetingId}
              aria-hidden="true"
              className="mm-span"
              style={{
                ...spanStyle(
                  Date.parse(meeting.occurredAt),
                  meeting.lastOccurredAt === undefined
                    ? Date.parse(meeting.occurredAt) + meeting.durationMs
                    : Date.parse(meeting.lastOccurredAt),
                  epochMs,
                ),
                top: 0,
                height: 20,
                borderRadius: 6,
                background: `color-mix(in oklab, ${paint.band} 18%, transparent)`,
                border: `1px solid ${paint.band}`,
              }}
            >
              <span
                className="block truncate px-2 text-[11px] font-medium"
                style={{ color: paint.name }}
              >
                {meeting.title}
              </span>
            </div>
          ))}
          {rowCells.length === 0 ? (
            <p className="pt-6 text-xs text-muted-foreground">No moments in view.</p>
          ) : null}
          {rowCells.map((cell) => {
            const moment = cell.momentId === undefined ? null : (byId.get(cell.momentId) ?? null)
            const clusteredMoments = (cell.momentIds ?? [])
              .map((id) => byId.get(id))
              .filter((item): item is TimelineMoment => item !== undefined)
            const clusterSpeakers = Array.from(
              new Set(clusteredMoments.flatMap((item) => item.speakers)),
            )
            return (
              <div
                key={cell.id}
                className="mm-at"
                style={{ ...atStyle(midOf(cell.span), epochMs), top: 28 }}
              >
                <span
                  aria-hidden="true"
                  className="absolute left-0 top-0 block h-6 w-px -translate-x-1/2"
                  style={{ background: paint.band }}
                />
                <button
                  type="button"
                  {...(cellProps(cell) as object)}
                  onClick={() => onActivate(cell)}
                  className="mm-focusable absolute top-7 -translate-x-1/2 rounded-md px-1 py-0.5 text-center"
                  style={{ width: MOMENT_CELL_WIDTH_PX }}
                >
                  <span className="block font-mono text-[10px] tabular-nums text-muted-foreground">
                    {moment === null
                      ? `${cell.span.to > cell.span.from ? `${isoDay(cell.span.from)}` : ''}`
                      : offsetLabel(moment.startMs)}
                  </span>
                  <span className="block text-[11px] leading-tight">
                    {moment === null ? `${cell.count} moments` : moment.title}
                  </span>
                  {moment !== null || clusteredMoments.length > 0 ? (
                    <span className="block text-[10px] text-muted-foreground">
                      {moment !== null
                        ? moment.speakers.length > 0
                          ? moment.speakers.join(', ')
                          : 'speaker unknown'
                        : clusterSpeakers.length > 0
                          ? clusterSpeakers.join(', ')
                          : 'speaker unknown'}
                    </span>
                  ) : null}
                </button>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

/** The other threads at a focused tier: 4px strips, never targets. */
function CollapsedStrips({
  threads,
  focusedThreadId,
}: {
  threads: Array<ThreadSummary>
  focusedThreadId: string
}) {
  const others = threads.filter((t) => t.threadId !== focusedThreadId)
  if (others.length === 0) return null
  return (
    <div role="presentation" aria-hidden="true" className="mb-3 flex flex-col gap-0.5">
      {others.map((thread) => {
        const paint = paintFor(thread.colorOrdinal)
        return (
          <div
            key={thread.threadId}
            title={`${thread.name}, collapsed`}
            style={{ height: STRIP_HEIGHT, borderRadius: 1, opacity: 0.55, background: paint.band }}
          />
        )
      })}
    </div>
  )
}

// --- cell models ------------------------------------------------------------

function midOf(span: Span): number {
  return span.from + (span.to - span.from) / 2
}

/** One row per thread; the cell is the bucket. */
function bandRows(
  threads: Array<ThreadSummary>,
  bands: Record<string, Array<BandBucket>> | null,
): Array<Array<Cell>> {
  return threads.map((thread, rowIndex) =>
    (bands?.[thread.threadId] ?? [])
      .filter((bucket) => bucket.mentionCount > 0)
      .map((bucket) => ({
      id: `${thread.threadId}:${bucket.from}`,
      rowIndex,
      threadId: thread.threadId,
      span: { from: Date.parse(bucket.from), to: Date.parse(bucket.to) },
      label: `${thread.name}, ${bucket.from.slice(0, 10)} to ${bucket.to.slice(0, 10)}, ${bucket.mentionCount} mentions`,
      kind: 'bucket' as const,
      count: bucket.mentionCount,
      })),
  )
}

/** One row: the focused thread's meetings, drawn at their duration. */
function meetingRows(
  focusedThread: ThreadSummary | null,
  meetings: Array<TimelineMeeting> | null,
): Array<Array<Cell>> {
  if (focusedThread === null || meetings === null) return []
  return [
    [...meetings]
      .sort((a, b) => Date.parse(a.occurredAt) - Date.parse(b.occurredAt))
      .map((meeting) => {
        const from = Date.parse(meeting.occurredAt)
        return {
          id: meeting.meetingId,
          rowIndex: 0,
          threadId: focusedThread.threadId,
          span: {
            from,
            to:
              meeting.lastOccurredAt === undefined
                ? from + meeting.durationMs
                : Date.parse(meeting.lastOccurredAt),
          },
          label: `${meeting.title ?? 'Meeting'}, ${isoDay(from)}, ${meeting.mentionCount} mentions`,
          kind: 'meeting' as const,
          count: meeting.mentionCount,
        }
      }),
  ]
}

/** One row: the focused thread's moments, clustered where they would collide. */
function momentRows(
  focusedThread: ThreadSummary | null,
  moments: Array<TimelineMoment> | null,
  view: View,
): Array<Array<Cell>> {
  if (focusedThread === null || moments === null) return []
  const clustered = clusterByX(
    moments,
    (m) => Date.parse(m.occurredAt),
    view,
    MOMENT_CELL_WIDTH_PX,
  )
  return [
    clustered.map((entry) => {
      const span = clusterSpan(entry)
      if (entry.kind === 'item') {
        return {
          id: entry.item.momentId,
          rowIndex: 0,
          threadId: focusedThread.threadId,
          span,
          label: `${entry.item.title}, ${offsetLabel(entry.item.startMs)}, ${
            entry.item.speakers.length > 0 ? entry.item.speakers.join(', ') : 'speaker unknown'
          }`,
          kind: 'moment' as const,
          count: 1,
          momentId: entry.item.momentId,
        }
      }
      return {
        id: `cluster:${span.from}`,
        rowIndex: 0,
        threadId: focusedThread.threadId,
        span,
        label: `${entry.items.length} moments, ${offsetLabel(entry.items[0].startMs)} to ${offsetLabel(entry.items[entry.items.length - 1].startMs)}: ${entry.items.map((item) => item.title).join('; ')}`,
        kind: 'cluster' as const,
        count: entry.items.length,
        momentIds: entry.items.map((item) => item.momentId),
      }
    }),
  ]
}

function tierHeading(
  tier: Tier,
  focusedThread: ThreadSummary | null,
  view: View,
  width: number,
): string {
  const span = visibleSpan(view, width)
  const window = `${isoDay(span.from)} to ${isoDay(span.to)}`
  if (tier === 'bands') return `Bands tier · ${window}`
  const name = focusedThread?.name ?? 'no thread'
  return `${tier === 'meetings' ? 'Meetings' : 'Moments'} tier · ${name} · ${window}`
}

/** The one polite sentence a tier change is allowed to say. */
export function tierAnnouncement(
  tier: Tier,
  focusedThread: ThreadSummary | null,
  rows: Array<Array<Cell>>,
  cells: Array<Cell>,
): string {
  if (cells.length === 0) return 'No moments in view.'
  const name = focusedThread?.name ?? 'every thread'
  if (tier === 'bands') return `Bands tier — ${rows.length} threads across the corpus.`
  const from = Math.min(...cells.map((c) => c.span.from))
  const to = Math.max(...cells.map((c) => c.span.to))
  const noun = tier === 'meetings' ? 'meetings' : 'moments'
  return `${tier === 'meetings' ? 'Meetings' : 'Moments'} tier — ${name}, ${cells.length} ${noun} between ${isoDay(from)} and ${isoDay(to)}.`
}
