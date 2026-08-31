/**
 * The geometry of a semantic zoom, as pure functions (story 10.7).
 *
 * **The zoom is semantic, not magnification.** Layout is computed in world
 * coordinates — pixels per day — and every label is drawn at a constant
 * readable size, the way a map keeps its place names legible at any altitude.
 * Scaling a container with a CSS transform would do the opposite: unreadable at
 * the top of the zoom, merely bigger at the bottom, and never showing anything
 * new. Nothing in this file returns a scale factor for that reason; it returns
 * positions and sizes in real pixels.
 *
 * **What a meeting *is* changes with altitude**, over one payload already in
 * hand rather than by refetching a tier per threshold:
 *
 *   under  20 px/day   a bar — height is moment count, marked when it has screens
 *   20 to  60          the bar, with its date
 *   60 to 160          a card: title, who spoke, a strip of its screens
 *   over  160          its moments — timecode, speaker, quote, screen, clickable
 *
 * So zooming out answers "what shape did this concern have over four months"
 * and zooming in answers "what exactly was said, and what was on screen when",
 * without changing view.
 *
 * Everything here is a pure function of numbers so the rules that are wrong in
 * invisible ways — lane packing at the current altitude, zoom about the cursor —
 * are unit tests rather than things a browser has to be driven to check.
 */

/** Below this the whole corpus is a smear; there is nothing further out to see. */
export const MIN_PPD = 1.5

/**
 * A meeting is a point in time and `moments` is the deepest representation
 * there is, so past roughly 300 px/day zooming buys nothing and only makes it
 * easy to get lost between meetings.
 */
export const MAX_PPD = 300

/** Room at the left for the axis, in the same coordinates as everything else. */
export const LEFT_GUTTER_PX = 60

/** Room at the top for the month ticks. */
export const TOP_PAD_PX = 54

/** Clear air between two cards in one lane. */
export const LANE_GAP_PX = 10

export type Altitude = 0 | 1 | 2 | 3

/** What the reader is looking at, in the words the control bar prints. */
export const ALTITUDE_NAMES: Record<Altitude, string> = {
  0: 'shape',
  1: 'dates',
  2: 'meetings',
  3: 'moments',
}

/** The altitude bands, as px/day. Exported so the tests name real numbers. */
export const ALTITUDE_BREAKS = { dates: 20, meetings: 60, moments: 160 } as const

export function altitudeFor(ppd: number): Altitude {
  if (ppd < ALTITUDE_BREAKS.dates) return 0
  if (ppd < ALTITUDE_BREAKS.meetings) return 1
  if (ppd < ALTITUDE_BREAKS.moments) return 2
  return 3
}

export interface Metrics {
  /** The card's real width at this altitude — what lanes are packed against. */
  cardWidthPx: number
  /** Vertical pitch between lanes. */
  lanePitchPx: number
}

/**
 * Card footprint and vertical pitch at each altitude.
 *
 * The pitch clears the *tallest* card rather than the average. A six-moment
 * card measures around 302px — title, meta, the moment list, the open-meeting
 * button — and a 300px pitch lets it bleed one lane down, which reads as
 * sloppiness rather than as a bug.
 */
export function metricsFor(altitude: Altitude): Metrics {
  if (altitude <= 1) return { cardWidthPx: 26, lanePitchPx: 116 }
  if (altitude === 2) return { cardWidthPx: 210, lanePitchPx: 158 }
  return { cardWidthPx: 340, lanePitchPx: 344 }
}

const MS_PER_DAY = 86_400_000

/** An RFC 3339 instant as whole days from `epochMs`, or null if unparseable. */
export function dayOf(occurredAt: string, epochMs: number): number | null {
  const parsed = Date.parse(occurredAt)
  if (Number.isNaN(parsed)) return null
  return (parsed - epochMs) / MS_PER_DAY
}

/** Where a day sits on screen. The one mapping the whole view agrees on. */
export function xOf(day: number, ppd: number, panX: number): number {
  return LEFT_GUTTER_PX + day * ppd - panX
}

export function clampPpd(ppd: number): number {
  return Math.min(MAX_PPD, Math.max(MIN_PPD, ppd))
}

/**
 * The altitude at which the whole span fits, which is where the view opens:
 * the point is that you start by seeing the shape, then choose where to
 * descend.
 */
export function fitPpd(viewportWidthPx: number, spanDays: number): number {
  return clampPpd((viewportWidthPx - 2 * LEFT_GUTTER_PX) / Math.max(1, spanDays))
}

export interface View {
  ppd: number
  panX: number
}

/**
 * Zoom about the cursor, so the thing under the pointer stays under it.
 *
 * `pointerX` is measured from the viewport's left edge. The world day beneath
 * the pointer is computed at the old altitude and pinned back to the same
 * screen position at the new one — which is the whole trick, and the reason
 * this is a function with a test rather than three lines inside an event
 * handler.
 */
export function zoomAbout(view: View, pointerX: number, factor: number): View {
  const ppd = clampPpd(view.ppd * factor)
  const worldDay = (pointerX + view.panX - LEFT_GUTTER_PX) / view.ppd
  return { ppd, panX: worldDay * ppd + LEFT_GUTTER_PX - pointerX }
}

/** Centre one day in the viewport at a named altitude. */
export function focusOn(day: number, ppd: number, viewportWidthPx: number): View {
  return { ppd, panX: day * ppd + LEFT_GUTTER_PX - viewportWidthPx / 2 }
}

/**
 * Lanes packed against each card's **actual pixel footprint at this altitude**,
 * not against the calendar date.
 *
 * This is the rule that is wrong at every zoom but one if it is computed at
 * load time. Two meetings a day apart do not overlap at 8 px/day and do overlap
 * at 210: at the coarse altitude they belong on one lane and at the deep one
 * they must not. So the packing is a function of `ppd`, and it is recomputed
 * whenever `ppd` changes.
 *
 * `days` must be ascending — the caller has already sorted the stops by time,
 * because a timeline that is not in time order is not a timeline. Returns one
 * lane index per input, positionally.
 */
export function packLanes(days: number[], ppd: number, cardWidthPx: number): number[] {
  const laneEnds: number[] = []
  return days.map((day) => {
    const x = day * ppd
    let lane = laneEnds.findIndex((end) => x >= end)
    if (lane === -1) {
      lane = laneEnds.length
      laneEnds.push(0)
    }
    laneEnds[lane] = x + cardWidthPx + LANE_GAP_PX
    return lane
  })
}

export function laneCount(lanes: number[]): number {
  return lanes.reduce((most, lane) => Math.max(most, lane + 1), 1)
}

export function canvasHeight(lanes: number, lanePitchPx: number): number {
  return TOP_PAD_PX + lanes * lanePitchPx + 24
}

const MONTHS = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
]

export interface Tick {
  day: number
  label: string
}

/**
 * Axis ticks, thinned so labels never collide at any altitude.
 *
 * The label itself never shrinks — that is the whole point of a semantic zoom —
 * so the only way to keep the axis readable as it fills up is to draw fewer of
 * them and to say more per tick as there is room for it.
 */
export function axisTicks(epochMs: number, spanDays: number, ppd: number): Tick[] {
  const step = ppd > 60 ? 7 : ppd > 14 ? 14 : 30
  const ticks: Tick[] = []
  for (let day = 0; day <= spanDays + 1; day += step) {
    const at = new Date(epochMs + day * MS_PER_DAY)
    ticks.push({
      day,
      label:
        step >= 30
          ? `${MONTHS[at.getUTCMonth()]}`
          : `${MONTHS[at.getUTCMonth()]} ${at.getUTCDate()}`,
    })
  }
  return ticks
}

/** `mm:ss` or `h:mm:ss` from a replay offset. */
export function timecode(startMs: number): string {
  const total = Math.max(0, Math.floor(startMs / 1000))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = total % 60
  const pad = (n: number) => String(n).padStart(2, '0')
  return hours > 0 ? `${hours}:${pad(minutes)}:${pad(seconds)}` : `${minutes}:${pad(seconds)}`
}

/**
 * Why a stop shows no screens, in words, and never a bare blank.
 *
 * The two absences are different claims and the difference is the whole of
 * AD-18 here. `hasRecording === false` is an *established* absence: the meeting
 * was ingested transcript-only, so no screens exist to have been captured. A
 * recorded meeting whose quoted moments carry no still is an *observed* one —
 * the capture may simply not cover these moments — and it must never be
 * reported as "no recording", which would be a claim nobody established.
 */
export function noScreenReason(hasRecording: boolean): string {
  return hasRecording
    ? 'No screen was captured at these moments.'
    : 'Transcript only — no recording, so no screens were captured.'
}
