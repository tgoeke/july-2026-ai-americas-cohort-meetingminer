import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  clampScale,
  fitView,
  panByPixels,
  panByWindow,
  TIMELINE_GUTTER_PX,
  zoomAbout,
  ZOOM_EASE_MS,
  type Span,
  type View,
} from './timeline'

/**
 * The view state behind the Threads canvas, and the animation that makes it
 * feel continuous.
 *
 * Two things are kept apart on purpose:
 *
 * - the **target** view is React state. The tier, the fetch window and every
 *   `data-*` attribute read from it, so a threshold crossing takes effect the
 *   instant the gesture crosses it — no waiting for an animation to land.
 * - the **drawn** view is a pair of CSS custom properties written by a
 *   `requestAnimationFrame` loop straight onto the canvas root. It eases toward
 *   the target over 120 ms, and because the whole tier positions itself from
 *   those two numbers (`threads.css`), one write moves everything. React does
 *   not re-render while a zoom is easing, which is what keeps it smooth when a
 *   wheel is spun hard: notches accumulate into the target and the drawn view
 *   chases it.
 *
 * Under `prefers-reduced-motion: reduce` the drawn view is the target, applied
 * synchronously.
 */

/** The width used before the canvas has been measured (jsdom, first paint). */
export const FALLBACK_WIDTH = 1000

export interface TimelineViewApi {
  /** The target view — what the tier, the fetch and the tests read. */
  view: View
  /** The canvas root: carries `--mm-from` and `--mm-scale` for every track. */
  rootRef: (node: HTMLDivElement | null) => void
  /** The measured canvas width in CSS pixels. */
  width: number
  /** Zoom by `factor` (>1 zooms out) keeping `focusX` fixed on screen. */
  zoomAt: (factor: number, focusX: number) => void
  /** Zoom about the centre of the canvas. */
  zoom: (factor: number) => void
  /** Pan by a fraction of the visible window. */
  pan: (fraction: number) => void
  /** Pan by a pixel delta (a drag, or a wheel's horizontal component). */
  panPixels: (dx: number) => void
  /** Zoom and pan so `span` fills the canvas. */
  fitTo: (span: Span, minimumScale?: number) => void
}

function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches
  } catch {
    return false
  }
}

/**
 * @param initial the view to open on.
 * @param epochMs the anchor every drawn `--t` is relative to. Changing it
 *   re-writes the drawn view immediately, so the two never disagree by an
 *   epoch — an item's screen position is unchanged by a re-anchor.
 */
export function useTimelineView(initial: View, epochMs: number): TimelineViewApi {
  const [view, setView] = useState<View>(initial)
  const [width, setWidth] = useState<number>(FALLBACK_WIDTH)

  const nodeRef = useRef<HTMLDivElement | null>(null)
  const targetRef = useRef<View>(initial)
  const drawnRef = useRef<View>(initial)
  const epochRef = useRef<number>(epochMs)
  const frameRef = useRef<number | null>(null)
  const startedAtRef = useRef<number>(0)
  const fromRef = useRef<View>(initial)

  targetRef.current = view
  epochRef.current = epochMs

  const paint = useCallback((v: View) => {
    const node = nodeRef.current
    if (node === null) return
    node.style.setProperty('--mm-from', String(v.from - epochRef.current))
    node.style.setProperty('--mm-scale', String(v.scale))
  }, [])

  /** One eased step of the drawn view toward the target. */
  const tick = useCallback(
    (now: number) => {
      frameRef.current = null
      const target = targetRef.current
      const elapsed = now - startedAtRef.current
      const t = Math.min(1, elapsed / ZOOM_EASE_MS)
      // Ease-out cubic: fast off the mark, settling rather than stopping.
      const eased = 1 - (1 - t) ** 3
      const start = fromRef.current
      // `scale` is eased geometrically: a zoom reads as constant-rate only when
      // equal ratios take equal time, which is what a log-space blend gives.
      const scale = start.scale * (target.scale / start.scale) ** eased
      const next = { from: start.from + (target.from - start.from) * eased, scale }
      drawnRef.current = t >= 1 ? target : next
      paint(drawnRef.current)
      if (t < 1) frameRef.current = requestAnimationFrame(tick)
    },
    [paint],
  )

  // Start (or restart) the ease whenever the target moves. A new target during
  // an ease restarts from wherever the drawn view actually is, so a fast wheel
  // never snaps backward.
  useEffect(() => {
    if (nodeRef.current === null) return
    if (prefersReducedMotion() || typeof requestAnimationFrame !== 'function') {
      drawnRef.current = view
      paint(view)
      return
    }
    fromRef.current = drawnRef.current
    startedAtRef.current =
      typeof performance !== 'undefined' ? performance.now() : Date.now()
    if (frameRef.current !== null) cancelAnimationFrame(frameRef.current)
    frameRef.current = requestAnimationFrame(tick)
    return () => {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current)
      frameRef.current = null
    }
  }, [view, paint, tick])

  // A re-anchor is not a movement: repaint at once so the drawn view keeps the
  // same instants under the same pixels.
  useEffect(() => {
    paint(drawnRef.current)
  }, [epochMs, paint])

  const observerRef = useRef<ResizeObserver | null>(null)

  const rootRef = useCallback(
    (node: HTMLDivElement | null) => {
      // React hands the callback `null` before it hands it a new node, so the
      // previous observer is always released before another is created.
      observerRef.current?.disconnect()
      observerRef.current = null
      nodeRef.current = node
      if (node === null) return
      paint(drawnRef.current)
      const measure = () => {
        const measured = node.clientWidth - TIMELINE_GUTTER_PX
        setWidth(measured > 0 ? measured : FALLBACK_WIDTH)
      }
      measure()
      if (typeof ResizeObserver === 'function') {
        const observer = new ResizeObserver(measure)
        observer.observe(node)
        observerRef.current = observer
      }
    },
    [paint],
  )

  const zoomAt = useCallback((factor: number, focusX: number) => {
    setView((current) => zoomAbout(current, factor, focusX))
  }, [])

  const zoom = useCallback(
    (factor: number) => {
      setView((current) => zoomAbout(current, factor, width / 2))
    },
    [width],
  )

  const pan = useCallback(
    (fraction: number) => {
      setView((current) => panByWindow(current, fraction, width))
    },
    [width],
  )

  const panPixels = useCallback((dx: number) => {
    setView((current) => panByPixels(current, dx))
  }, [])

  const fitTo = useCallback(
    (span: Span, minimumScale?: number) => {
      setView(() => {
        const fitted = fitView(span, width, minimumScale)
        return { from: fitted.from, scale: clampScale(fitted.scale) }
      })
    },
    [width],
  )

  return useMemo(
    () => ({ view, rootRef, width, zoomAt, zoom, pan, panPixels, fitTo }),
    [view, rootRef, width, zoomAt, zoom, pan, panPixels, fitTo],
  )
}
