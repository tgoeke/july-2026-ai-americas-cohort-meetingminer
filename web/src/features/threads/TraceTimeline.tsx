/**
 * A zoomable map of one traced subject: time on the x axis, meetings on it.
 *
 * The zoom is **semantic, not magnification**. Every position and size here is
 * a real pixel computed from `trace.ts`'s world coordinates, and every label is
 * drawn at its natural size at every altitude. There is no `transform: scale()`
 * on this subtree and there must never be one: it would be unreadable at the
 * top of the zoom, merely bigger at the bottom, and would never reveal anything
 * the reader could not already see.
 *
 * One payload serves every altitude. The whole trace arrives once and this
 * component decides what a meeting *is* as the reader descends — a bar, a dated
 * bar, a card, or its moments. Refetching a tier per threshold, which is what
 * story 10.3's level-of-detail endpoint would have this do, cannot keep what is
 * under the cursor under the cursor while the fetch is in flight.
 */

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'

import { screenshotUrl } from '@/features/moments/feed'

import { paintFor, swatchStyle } from './palette'
import type { ThreadTrace, TraceStop } from './traceApi'
import {
  ALTITUDE_NAMES,
  LEFT_GUTTER_PX,
  TOP_PAD_PX,
  altitudeFor,
  axisTicks,
  canvasHeight,
  dayOf,
  fitPpd,
  focusOn,
  laneCount,
  metricsFor,
  noScreenReason,
  packLanes,
  timecode,
  xOf,
  zoomAbout,
} from './trace'
import type { View } from './trace'

/** The altitude a click on a meeting descends to: its moments, readable. */
const DESCEND_PPD = 210

interface Placed {
  stop: TraceStop
  day: number
}

function dateLabel(occurredAt: string, precision: string): string {
  const at = new Date(occurredAt)
  if (Number.isNaN(at.getTime())) return 'undated'
  const day = at.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    timeZone: 'UTC',
  })
  // A `day`-precision meeting has no recorded time of day. Anchoring it at
  // midnight is the only placement available, and printing a clock alongside
  // it would invent one (AD-18).
  return precision === 'day' ? `${day} · date only` : day
}

export default function TraceTimeline({
  trace,
  onOpenMeeting,
}: {
  trace: ThreadTrace
  onOpenMeeting: (meetingId: string) => void
}) {
  const viewport = useRef<HTMLDivElement | null>(null)
  const drag = useRef<{ x: number; panX: number } | null>(null)
  const [width, setWidth] = useState(1000)
  // Altitude and origin are ONE value. Held as two pieces of state they can be
  // updated from different snapshots inside one handler, and a zoom that reads
  // a stale pan is exactly the drift that stops the cursor anchoring.
  const [view, setView] = useState<View>({ ppd: 8, panX: 0 })
  const { ppd, panX } = view
  const [focused, setFocused] = useState<string | null>(null)

  const { placed, epochMs, spanDays } = useMemo(() => {
    const stamps = trace.stops
      .map((stop) => Date.parse(stop.occurredAt))
      .filter((value) => !Number.isNaN(value))
    if (stamps.length === 0) return { placed: [] as Placed[], epochMs: 0, spanDays: 1 }
    const first = Math.min(...stamps)
    const last = Math.max(...stamps)
    const rows: Placed[] = []
    for (const stop of trace.stops) {
      const day = dayOf(stop.occurredAt, first)
      if (day === null) continue
      rows.push({ stop, day })
    }
    rows.sort((a, b) => a.day - b.day)
    return {
      placed: rows,
      epochMs: first,
      spanDays: Math.max(1, (last - first) / 86_400_000),
    }
  }, [trace.stops])

  const fit = useCallback(() => {
    setView({ ppd: fitPpd(width, spanDays), panX: 0 })
    setFocused(null)
  }, [width, spanDays])

  useLayoutEffect(() => {
    const element = viewport.current
    if (element === null) return
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width))
    observer.observe(element)
    setWidth(element.clientWidth)
    return () => observer.disconnect()
  }, [])

  // Open at the altitude where the whole span is visible: the point of the view
  // is that you start by seeing the shape, then choose where to descend.
  const fitted = useRef<string | null>(null)
  useEffect(() => {
    if (fitted.current !== trace.label && width > 0) {
      fitted.current = trace.label
      fit()
    }
  }, [trace.label, width, fit])

  const zoomAt = useCallback((pointerClientX: number, factor: number) => {
    const element = viewport.current
    if (element === null) return
    const pointerX = pointerClientX - element.getBoundingClientRect().left
    setView((current) => zoomAbout(current, pointerX, factor))
  }, [])

  useEffect(() => {
    const element = viewport.current
    if (element === null) return
    const onWheel = (event: WheelEvent) => {
      if (event.deltaY === 0) return
      event.preventDefault()
      zoomAt(event.clientX, Math.exp(-event.deltaY * 0.0022))
    }
    element.addEventListener('wheel', onWheel, { passive: false })
    return () => element.removeEventListener('wheel', onWheel)
  }, [zoomAt])

  const centreX = useCallback(
    () => (viewport.current?.getBoundingClientRect().left ?? 0) + width / 2,
    [width],
  )

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (target !== null && /^(INPUT|TEXTAREA)$/.test(target.tagName)) return
      if (event.key === 'Escape') fit()
      if (event.key === '+' || event.key === '=') zoomAt(centreX(), 1.4)
      if (event.key === '-' || event.key === '_') zoomAt(centreX(), 1 / 1.4)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [fit, zoomAt, centreX])

  /** Descend onto one meeting: centre it, and go to where its moments read. */
  const descend = useCallback(
    (item: Placed) => {
      setView(focusOn(item.day, DESCEND_PPD, width))
      setFocused(item.stop.meetingId)
    },
    [width],
  )

  const altitude = altitudeFor(ppd)
  const { cardWidthPx, lanePitchPx } = metricsFor(altitude)

  // Lanes are packed against each card's ACTUAL pixel footprint at this
  // altitude. Two meetings a day apart do not overlap at 8 px/day and do
  // overlap at 210, so a lane assignment fixed at load time is wrong at every
  // zoom but one — which is why this is a `useMemo` on `ppd`, not on the data.
  const lanes = useMemo(
    () => packLanes(placed.map((item) => item.day), ppd, cardWidthPx),
    [placed, ppd, cardWidthPx],
  )
  const height = canvasHeight(laneCount(lanes), lanePitchPx)
  const ticks = useMemo(
    () => axisTicks(epochMs, spanDays, ppd),
    [epochMs, spanDays, ppd],
  )
  const busiest = Math.max(1, ...placed.map((item) => item.stop.quotedCount))
  const paint = paintFor(trace.colorOrdinal ?? 1)

  if (placed.length === 0) return null

  return (
    <section className="mm-trace" aria-label={`Timeline for ${trace.label}`}>
      <div className="mm-trace-bar">
        <span className="mm-trace-swatch" style={swatchStyle(paint)} aria-hidden />
        <strong>{trace.label}</strong>
        {trace.span !== null && (
          <span className="mm-trace-span">
            {dateLabel(trace.span.fromAt, 'second')} → {dateLabel(trace.span.toAt, 'second')} ·{' '}
            {trace.span.days} days · {trace.counts.stops} meetings
            {trace.counts.withScreen > 0 && <> · {trace.counts.withScreen} with a screen</>}
          </span>
        )}
        <span className="mm-trace-grow" />
        <span className="mm-trace-altitude" data-altitude={altitude}>
          {ALTITUDE_NAMES[altitude]}
        </span>
        <button type="button" onClick={() => zoomAt(centreX(), 1 / 1.5)} aria-label="Zoom out">
          −
        </button>
        <button type="button" onClick={() => zoomAt(centreX(), 1.5)} aria-label="Zoom in">
          +
        </button>
        <button type="button" onClick={fit}>
          fit
        </button>
      </div>

      <div
        ref={viewport}
        className="mm-trace-view"
        data-altitude={altitude}
        data-ppd={Math.round(ppd * 100) / 100}
        style={{ height }}
        onPointerDown={(event) => {
          if ((event.target as HTMLElement).closest('button') !== null) return
          drag.current = { x: event.clientX, panX }
          event.currentTarget.setPointerCapture(event.pointerId)
        }}
        onPointerMove={(event) => {
          if (drag.current === null) return
          // The origin is read from the ref, captured at pointer-down, so a
          // drag stays anchored to where it began rather than accumulating.
          const start = drag.current
          const moved = event.clientX - start.x
          setView((current) => ({ ...current, panX: start.panX - moved }))
        }}
        onPointerUp={() => {
          drag.current = null
        }}
        onPointerCancel={() => {
          drag.current = null
        }}
      >
        <div className="mm-trace-axis">
          {ticks.map((tick) => (
            <span
              key={tick.day}
              className="mm-trace-tick"
              style={{ left: xOf(tick.day, ppd, panX) }}
            >
              {tick.label}
            </span>
          ))}
        </div>

        {placed.map((item, index) => {
          const x = xOf(item.day, ppd, panX)
          // Cull what is off screen. The payload is whole; only the drawing is
          // bounded, so panning back reveals it without a fetch.
          if (x < -(cardWidthPx + 80) || x > width + cardWidthPx + 80) return null
          const stop = item.stop
          const y = TOP_PAD_PX + lanes[index] * lanePitchPx
          const hasScreens = stop.screenCount > 0
          const label = dateLabel(stop.occurredAt, stop.occurredAtPrecision)
          const title = stop.title ?? 'Untitled meeting'

          if (altitude <= 1) {
            const barHeight = 12 + (stop.quotedCount / busiest) * 62
            return (
              <button
                key={stop.meetingId}
                type="button"
                className="mm-trace-bar-item"
                data-screens={hasScreens ? 'yes' : 'no'}
                style={{ left: x, top: y + 62 - barHeight, height: barHeight }}
                title={`${label} · ${title} · ${stop.quotedCount} of ${stop.mentionCount} moments`}
                onClick={() => descend(item)}
              >
                {altitude === 1 && <span className="mm-trace-bar-date">{label}</span>}
              </button>
            )
          }

          return (
            <div
              key={stop.meetingId}
              className="mm-trace-card"
              data-focused={focused === stop.meetingId ? 'yes' : 'no'}
              data-screens={hasScreens ? 'yes' : 'no'}
              style={{ left: x, top: y, width: cardWidthPx }}
            >
              <button type="button" className="mm-trace-card-head" onClick={() => descend(item)}>
                <span className="mm-trace-card-date">{label}</span>
                <span className="mm-trace-card-title">{title}</span>
              </button>
              <p className="mm-trace-card-meta">
                {stop.quotedCount} of {stop.mentionCount} moment
                {stop.mentionCount === 1 ? '' : 's'}
                {hasScreens ? <> · {stop.screenCount} with a screen</> : null}
              </p>
              {/* Never a bare blank, and never "no recording" unless that has
                  actually been established (AD-18). */}
              {!hasScreens && (
                <p className="mm-trace-absent">{noScreenReason(stop.hasRecording)}</p>
              )}

              {altitude === 2 && hasScreens && (
                <div className="mm-trace-strip">
                  {stop.moments.slice(0, 6).map((moment) =>
                    moment.screenshotId === null ? (
                      <span key={moment.momentId} className="mm-trace-noshot" />
                    ) : (
                      <img
                        key={moment.momentId}
                        src={screenshotUrl(moment.screenshotId)}
                        alt=""
                        loading="lazy"
                      />
                    ),
                  )}
                </div>
              )}

              {altitude >= 3 && (
                <ol className="mm-trace-moments">
                  {stop.moments.map((moment) => (
                    <li key={moment.momentId}>
                      {moment.screenshotId === null ? (
                        <span className="mm-trace-noshot big" />
                      ) : (
                        <img src={screenshotUrl(moment.screenshotId)} alt="" loading="lazy" />
                      )}
                      <span className="mm-trace-moment-body">
                        <span className="mm-trace-moment-head">
                          <span className="mm-trace-tc">{timecode(moment.startMs)}</span>
                          <span className="mm-trace-speaker">
                            {moment.speakers[0] ?? 'speaker unresolved'}
                          </span>
                        </span>
                        <span className="mm-trace-quote">
                          {moment.excerpt ?? 'No transcript text is stored for this moment.'}
                        </span>
                      </span>
                    </li>
                  ))}
                </ol>
              )}

              {/* The meeting is the destination; the thread was the route. */}
              <button
                type="button"
                className="mm-trace-open"
                onClick={() => onOpenMeeting(stop.meetingId)}
              >
                Open this meeting →
              </button>
            </div>
          )
        })}
      </div>

      {/* At altitude the whole span is visible; once you descend it is not, and
          without this there is no landmark saying where you are. */}
      <div
        className="mm-trace-mini"
        onPointerDown={(event) => {
          const box = event.currentTarget.getBoundingClientRect()
          const fraction = (event.clientX - box.left) / box.width
          setView((current) => ({
            ...current,
            panX: fraction * spanDays * current.ppd + LEFT_GUTTER_PX - width / 2,
          }))
        }}
      >
        {placed.map((item) => (
          <span
            key={item.stop.meetingId}
            className="mm-trace-mini-tick"
            data-screens={item.stop.screenCount > 0 ? 'yes' : 'no'}
            style={{ left: `${(item.day / Math.max(1, spanDays)) * 100}%` }}
          />
        ))}
        <span
          className="mm-trace-mini-window"
          style={{
            left: `${Math.max(0, Math.min(100, ((panX - LEFT_GUTTER_PX) / (spanDays * ppd)) * 100))}%`,
            width: `${Math.max(1.2, Math.min(100, (width / (spanDays * ppd)) * 100))}%`,
          }}
        />
      </div>

      <p className="mm-trace-hint">
        scroll to zoom · drag to pan · click a meeting to descend · <kbd>esc</kbd> to fit
      </p>
    </section>
  )
}
