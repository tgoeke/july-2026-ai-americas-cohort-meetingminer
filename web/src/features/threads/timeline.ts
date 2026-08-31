/**
 * The Threads timeline's decision core: the time→x mapping, the level-of-detail
 * thresholds with their hysteresis, zoom about a focus point, the bucket unit,
 * the fetch window, and density alpha.
 *
 * Everything here is pure. The screen's two hard promises — *smooth* and *no
 * layout jump* — are properties of these functions, not of the DOM, so they are
 * provable in a unit test: an item's x depends only on `(t, from, scale)`, and a
 * tier change never touches `from` or `scale`.
 *
 * `EXPERIENCE.md` · Semantic Zoom is the contract. `scale` is **milliseconds per
 * pixel** throughout, and `t` is always the api's canonical UTC `occurredAt` —
 * `startMs` is a replay offset and never determines cross-meeting x.
 */

/** The tiers story 10.6 draws. `evidence` is story 10.6a and is not here. */
export type Tier = 'bands' | 'meetings' | 'moments'

/** The tiers, coarsest first. */
export const TIERS: ReadonlyArray<Tier> = ['bands', 'meetings', 'moments']

/**
 * The lower bound of each tier's `scale` band, in ms/px
 * (`EXPERIENCE.md` · Semantic Zoom, the tier table).
 *
 * `bands` runs from 2 h/px upward with no ceiling; `meetings` covers
 * 4 min/px – 2 h/px; `moments` covers 2 s/px – 4 min/px. Below 2 s/px is the
 * evidence tier, which story 10.6a owns — this screen clamps there.
 */
export const TIER_MIN_SCALE: Readonly<Record<Tier, number>> = {
  bands: 7_200_000,
  meetings: 240_000,
  moments: 2_000,
}

/** The exclusive upper bound of each tier's `scale` band, in ms/px. */
export const TIER_MAX_SCALE: Readonly<Record<Tier, number>> = {
  bands: Number.POSITIVE_INFINITY,
  meetings: 7_200_000,
  moments: 240_000,
}

/**
 * How far past a tier's ceiling the scale must go before the tier is left
 * upward — the "leave back at" column, so a wheel notch that just crossed a
 * threshold does not flap back.
 */
export const HYSTERESIS = 1.25

/** Story 10.6 stops at the moments tier; 2 s/px is the evidence threshold. */
export const MIN_SCALE = TIER_MIN_SCALE.moments

/** ×1.25 per wheel notch, ×1.5 per key press (`EXPERIENCE.md` · Semantic Zoom). */
export const WHEEL_ZOOM_STEP = 1.25
export const KEY_ZOOM_STEP = 1.5

/** Zoom eases over 120 ms; a tier change cross-fades over 160 ms. */
export const ZOOM_EASE_MS = 120
export const TIER_FADE_MS = 160

/** Fixed geometry shared by measurement, axis, tracks, and pointer anchoring. */
export const TIMELINE_ROW_HEADER_PX = 150
export const TIMELINE_ROW_GAP_PX = 12
export const TIMELINE_GUTTER_PX = TIMELINE_ROW_HEADER_PX + TIMELINE_ROW_GAP_PX
export const MOMENT_CELL_WIDTH_PX = 120

/** A visible window: its left edge in epoch ms, and ms per pixel. */
export interface View {
  /** The instant at x = 0, in epoch milliseconds. */
  from: number
  /** Milliseconds per pixel. */
  scale: number
}

/** A closed time span in epoch milliseconds. */
export interface Span {
  from: number
  to: number
}

/**
 * x, in CSS pixels, of an instant in a view.
 *
 * This is the one mapping. Every tier uses it, which is why an item's x is
 * unchanged across a tier change: the tier is a function of `scale`, and `scale`
 * is an input here, not an output.
 */
export function xOf(t: number, view: View): number {
  return (t - view.from) / view.scale
}

/** The instant at a pixel offset — `xOf` inverted. */
export function timeAtX(x: number, view: View): number {
  return view.from + x * view.scale
}

/** The visible span of a view `width` pixels wide. */
export function visibleSpan(view: View, width: number): Span {
  return { from: view.from, to: view.from + width * view.scale }
}

/** Whether `a` is finer (more zoomed in) than `b`. */
export function isFiner(a: Tier, b: Tier): boolean {
  return TIERS.indexOf(a) > TIERS.indexOf(b)
}

/**
 * The tier a scale belongs to, given the tier currently drawn.
 *
 * Zooming *in* crosses a threshold as soon as the scale passes the current
 * tier's floor. Zooming *out* needs `HYSTERESIS` × the current tier's ceiling,
 * which is what stops a single wheel notch from flapping between two tiers.
 * The loop handles a jump of more than one tier (a `Fit` from the moments tier,
 * say), applying the same rule at every step.
 */
export function tierForScale(scale: number, current: Tier): Tier {
  let tier = current
  // Bounded by the tier count; each pass moves one step in one direction.
  for (let step = 0; step < TIERS.length; step += 1) {
    if (scale < TIER_MIN_SCALE[tier]) {
      const finer = TIERS[TIERS.indexOf(tier) + 1]
      if (finer === undefined) return tier
      tier = finer
      continue
    }
    if (scale >= TIER_MAX_SCALE[tier] * HYSTERESIS) {
      const coarser = TIERS[TIERS.indexOf(tier) - 1]
      if (coarser === undefined) return tier
      tier = coarser
      continue
    }
    return tier
  }
  return tier
}

/**
 * Zoom by `factor` about the pixel `focusX`, so the instant under the focus
 * point keeps its screen position.
 *
 * `factor` > 1 zooms *out* (more ms per pixel). The identity that makes the
 * gesture feel anchored — and that the "no layout jump" test asserts — is
 * `xOf(timeAtX(focusX, before), after) === focusX`.
 */
export function zoomAbout(view: View, factor: number, focusX: number): View {
  const scale = clampScale(view.scale * factor)
  return { from: view.from + focusX * (view.scale - scale), scale }
}

/** Scale held inside story 10.6's range: never past the evidence threshold. */
export function clampScale(scale: number): number {
  if (!Number.isFinite(scale) || scale <= 0) return MIN_SCALE
  return Math.max(MIN_SCALE, scale)
}

/**
 * The view that fits `span` into `width` pixels.
 *
 * A zero-length span (one meeting with day precision, a thread with a single
 * mention) would divide to a zero scale, so it is widened to a minute either
 * side before the division — a fit must always produce a drawable window.
 */
export function fitView(span: Span, width: number): View {
  const usable = width > 0 ? width : 1
  let { from, to } = span
  if (!(to > from)) {
    from -= 60_000
    to += 60_000
  }
  const scale = clampScale((to - from) / usable)
  // Centred on the span's midpoint rather than anchored at its left edge. For a
  // span that fits, the two are the same number; for one so short that the
  // scale clamps at the evidence threshold, only centring puts the thing the
  // reader asked to see in the middle of the canvas instead of near its edge.
  return { from: from + (to - from) / 2 - (usable * scale) / 2, scale }
}

/**
 * Pan by a fraction of the visible window — `Shift+←` / `Shift+→` and the
 * `‹` `›` controls both move 80% of it.
 */
export function panByWindow(view: View, fraction: number, width: number): View {
  return { ...view, from: view.from + fraction * width * view.scale }
}

/** Pan by a pixel delta, for a drag or a wheel's horizontal component. */
export function panByPixels(view: View, dx: number): View {
  return { ...view, from: view.from - dx * view.scale }
}

/** The bands tier's bucket units, and their nominal width in ms. */
export const BUCKET_MS: Readonly<Record<'day' | 'week' | 'month', number>> = {
  day: 86_400_000,
  week: 604_800_000,
  month: 2_629_800_000,
}

export type BucketUnit = 'day' | 'week' | 'month'

/** The smallest bucket that is at least 8 px wide at this scale. */
export function bucketUnitFor(scale: number): BucketUnit {
  if (BUCKET_MS.day / scale >= 8) return 'day'
  if (BUCKET_MS.week / scale >= 8) return 'week'
  return 'month'
}

/** How far past each edge a tier is fetched: half the visible span. */
export const FETCH_PAD = 0.5

/**
 * The span to fetch for a view: the visible window padded 50% each side, with
 * both edges snapped to a quarter of the visible span.
 *
 * The snap is what makes the cache key stable: a one-pixel pan must not miss
 * the cache and re-ask the api for the same tier.
 */
export function fetchSpan(view: View, width: number): Span {
  const visible = visibleSpan(view, width)
  const span = visible.to - visible.from
  const pad = span * FETCH_PAD
  const step = span / 4 || 1
  return {
    from: Math.floor((visible.from - pad) / step) * step,
    to: Math.ceil((visible.to + pad) / step) * step,
  }
}

/**
 * The identity of a tier fetch: pin membership is part of it, so pinning a
 * thread re-asks even when the tier and window have not moved
 * (`EXPERIENCE.md` · Fetch discipline).
 */
export function cacheKey(
  threadIds: ReadonlyArray<string>,
  level: string,
  span: Span,
): string {
  return `${[...threadIds].sort().join('|')}::${level}::${span.from}::${span.to}`
}

/** The five density steps: zero, then the quartiles of the nonzero counts. */
export const DENSITY_ALPHA: ReadonlyArray<number> = [0.08, 0.6, 0.75, 0.88, 1]

/**
 * A count → alpha function for one window.
 *
 * Zero mentions is always 0.08, so an empty stretch of a band still reads as
 * part of the band's span. The nonzero counts across *every visible band* are
 * split at their quartiles, which is why zooming rescales the steps.
 *
 * When every nonzero count is the same number there are no quartiles to split
 * on, and dimming a uniformly busy window to the lowest step would misreport
 * it — so a single distinct value takes the top step.
 */
export function densityAlpha(counts: ReadonlyArray<number>): (count: number) => number {
  const nonzero = counts.filter((c) => c > 0).sort((a, b) => a - b)
  if (nonzero.length === 0) return (count) => (count > 0 ? 1 : DENSITY_ALPHA[0])
  const lowest = nonzero[0]
  const highest = nonzero[nonzero.length - 1]
  if (lowest === highest) return (count) => (count > 0 ? 1 : DENSITY_ALPHA[0])
  const cuts = [quantile(nonzero, 0.25), quantile(nonzero, 0.5), quantile(nonzero, 0.75)]
  return (count) => {
    if (count <= 0) return DENSITY_ALPHA[0]
    if (count <= cuts[0]) return DENSITY_ALPHA[1]
    if (count <= cuts[1]) return DENSITY_ALPHA[2]
    if (count <= cuts[2]) return DENSITY_ALPHA[3]
    return DENSITY_ALPHA[4]
  }
}

/** Linear-interpolation quantile over an ascending array. */
function quantile(sorted: ReadonlyArray<number>, p: number): number {
  const pos = (sorted.length - 1) * p
  const lower = Math.floor(pos)
  const upper = Math.ceil(pos)
  if (lower === upper) return sorted[lower]
  return sorted[lower] + (sorted[upper] - sorted[lower]) * (pos - lower)
}

/** The minimum hit area, in CSS pixels, every timeline item is given. */
export const MIN_HIT_PX = 24

/** One drawn cell at the moments tier: a moment, or moments too close to tell apart. */
export type Cluster<T> =
  | { kind: 'item'; item: T; t: number }
  | { kind: 'cluster'; items: ReadonlyArray<T>; from: number; to: number }

/**
 * Group items whose ≥ 24 px hit areas would overlap at this scale.
 *
 * Two moments 30 seconds apart are two cells at 2 s/px and one cell at
 * 4 min/px; the cluster drills on Enter rather than being dropped, so nothing a
 * moment backs disappears at any scale.
 */
export function clusterByX<T>(
  items: ReadonlyArray<T>,
  timeOf: (item: T) => number,
  view: View,
  minGapPx: number = MIN_HIT_PX,
): Array<Cluster<T>> {
  const sorted = [...items].sort((a, b) => timeOf(a) - timeOf(b))
  const out: Array<Cluster<T>> = []
  let group: Array<T> = []
  const flush = () => {
    if (group.length === 0) return
    if (group.length === 1) {
      out.push({ kind: 'item', item: group[0], t: timeOf(group[0]) })
    } else {
      out.push({
        kind: 'cluster',
        items: group,
        from: timeOf(group[0]),
        to: timeOf(group[group.length - 1]),
      })
    }
    group = []
  }
  for (const item of sorted) {
    if (group.length === 0) {
      group.push(item)
      continue
    }
    const anchor = xOf(timeOf(group[0]), view)
    if (xOf(timeOf(item), view) - anchor < minGapPx) group.push(item)
    else {
      flush()
      group.push(item)
    }
  }
  flush()
  return out
}

/** The span a cluster or item occupies, for `Enter` (zoom to fit it). */
export function clusterSpan<T>(cell: Cluster<T>): Span {
  return cell.kind === 'item' ? { from: cell.t, to: cell.t } : { from: cell.from, to: cell.to }
}

/** `2026-05-13` — the axis and every accessible name label a day this way. */
export function isoDay(t: number): string {
  return new Date(t).toISOString().slice(0, 10)
}

/** `0:04:12` — an offset inside a meeting, for a moment's anchor. */
export function offsetLabel(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = total % 60
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${hours}:${pad(minutes)}:${pad(seconds)}`
}

/** The tick marks on the axis: evenly spaced days across the visible window. */
export function axisTicks(view: View, width: number, count = 6): Array<number> {
  const { from, to } = visibleSpan(view, width)
  const step = (to - from) / Math.max(1, count)
  const ticks: Array<number> = []
  for (let i = 0; i <= count; i += 1) ticks.push(from + i * step)
  return ticks
}
