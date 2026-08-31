/**
 * The semantic zoom's geometry (story 10.7).
 *
 * These are the rules that are wrong in ways nobody sees: a lane assignment
 * that was right at the altitude it was computed at, a zoom that drifts a few
 * pixels per step, a label that quietly got smaller. Each is arithmetic, so
 * each is asserted here rather than driven in a browser.
 */

import { describe, expect, it } from 'vitest'

import {
  ALTITUDE_BREAKS,
  ALTITUDE_NAMES,
  LEFT_GUTTER_PX,
  MAX_PPD,
  MIN_PPD,
  altitudeFor,
  axisTicks,
  canvasHeight,
  clampPpd,
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

const EPOCH = Date.UTC(2026, 3, 1)

describe('altitude', () => {
  it('changes what a meeting is at the four stated thresholds', () => {
    expect(altitudeFor(19.99)).toBe(0)
    expect(altitudeFor(ALTITUDE_BREAKS.dates)).toBe(1)
    expect(altitudeFor(59.99)).toBe(1)
    expect(altitudeFor(ALTITUDE_BREAKS.meetings)).toBe(2)
    expect(altitudeFor(159.99)).toBe(2)
    expect(altitudeFor(ALTITUDE_BREAKS.moments)).toBe(3)
    expect(altitudeFor(MAX_PPD)).toBe(3)
  })

  it('names each altitude for the control bar', () => {
    expect(Object.values(ALTITUDE_NAMES)).toEqual(['shape', 'dates', 'meetings', 'moments'])
  })

  it('gives a bar the same footprint whether or not it carries its date', () => {
    // Altitudes 0 and 1 draw the same object; only the label appears. If they
    // differed here, gaining a date would silently re-pack every lane.
    expect(metricsFor(0)).toEqual(metricsFor(1))
  })

  it('grows the footprint as the representation gains content, and only then', () => {
    expect(metricsFor(1).cardWidthPx).toBeLessThan(metricsFor(2).cardWidthPx)
    expect(metricsFor(2).cardWidthPx).toBeLessThan(metricsFor(3).cardWidthPx)
    expect(metricsFor(2).lanePitchPx).toBeLessThan(metricsFor(3).lanePitchPx)
  })
})

describe('lane packing', () => {
  it('packs against the pixel footprint at THIS altitude, not the date', () => {
    // The story's sharpest geometric rule. Two meetings two days apart:
    //
    //   at   8 px/day they are  16 px apart and a bar is 26 + 10 wide → two lanes
    //   at 210 px/day they are 420 px apart and a card is 340 + 10 wide → one lane
    //
    // A lane assignment fixed at load time is therefore wrong at one of these
    // two altitudes no matter which one it was computed at.
    const days = [0, 2]
    expect(packLanes(days, 8, metricsFor(0).cardWidthPx)).toEqual([0, 1])
    expect(packLanes(days, 210, metricsFor(3).cardWidthPx)).toEqual([0, 0])
  })

  it('puts well-separated meetings on one lane at every altitude', () => {
    const days = [0, 30, 60]
    expect(packLanes(days, 8, metricsFor(0).cardWidthPx)).toEqual([0, 0, 0])
    expect(packLanes(days, 210, metricsFor(3).cardWidthPx)).toEqual([0, 0, 0])
  })

  it('reuses the first lane that has cleared, rather than opening a new one', () => {
    // Three same-day meetings need three lanes; a fourth far enough along
    // belongs back on lane 0 rather than on a fourth.
    const lanes = packLanes([0, 0, 0, 10], 8, 26)
    expect(lanes).toEqual([0, 1, 2, 0])
    expect(laneCount(lanes)).toBe(3)
  })

  it('returns one lane per stop, positionally', () => {
    expect(packLanes([0, 1, 2, 3], 40, 210)).toHaveLength(4)
  })

  it('counts at least one lane even with nothing placed', () => {
    expect(laneCount([])).toBe(1)
    expect(canvasHeight(1, 116)).toBeGreaterThan(116)
  })
})

describe('zoom about the cursor', () => {
  it('keeps what is under the pointer under the pointer', () => {
    const before = { ppd: 10, panX: 100 }
    const pointerX = 250
    const worldDay = (pointerX + before.panX - LEFT_GUTTER_PX) / before.ppd

    for (const factor of [2.5, 1.4, 1 / 1.4, 0.31]) {
      const after = zoomAbout(before, pointerX, factor)
      expect(xOf(worldDay, after.ppd, after.panX)).toBeCloseTo(pointerX, 6)
    }
  })

  it('does not drift over a long run of small steps', () => {
    // A per-step rounding error is invisible for one wheel notch and obvious
    // after a scroll, which is exactly the bug this guards.
    let view = { ppd: 12, panX: 40 }
    const pointerX = 300
    const worldDay = (pointerX + view.panX - LEFT_GUTTER_PX) / view.ppd
    for (let step = 0; step < 60; step += 1) view = zoomAbout(view, pointerX, 1.02)
    expect(xOf(worldDay, view.ppd, view.panX)).toBeCloseTo(pointerX, 6)
  })

  it('never leaves the altitude band', () => {
    expect(zoomAbout({ ppd: 2, panX: 0 }, 100, 0.001).ppd).toBe(MIN_PPD)
    expect(zoomAbout({ ppd: 200, panX: 0 }, 100, 1000).ppd).toBe(MAX_PPD)
    expect(clampPpd(-5)).toBe(MIN_PPD)
  })
})

describe('fit and focus', () => {
  it('opens at the altitude where the whole span is visible', () => {
    const ppd = fitPpd(1160, 100)
    expect(ppd).toBeCloseTo(10.4, 6)
    // The last day still lands inside the viewport.
    expect(xOf(100, ppd, 0)).toBeLessThanOrEqual(1160)
  })

  it('still returns a usable altitude for a single-day span', () => {
    expect(fitPpd(1000, 0)).toBe(MAX_PPD)
    expect(fitPpd(200, 100000)).toBe(MIN_PPD)
  })

  it('centres the meeting it descends onto', () => {
    const view = focusOn(42, 210, 1000)
    expect(xOf(42, view.ppd, view.panX)).toBeCloseTo(500, 6)
  })
})

describe('the axis', () => {
  it('draws fewer ticks as the view zooms out, never smaller ones', () => {
    const far = axisTicks(EPOCH, 120, 8)
    const near = axisTicks(EPOCH, 120, 120)
    expect(near.length).toBeGreaterThan(far.length)
    // Every label is a plain string at every altitude: nothing here returns a
    // font size, because a semantic zoom never shrinks its type.
    expect(far.every((tick) => typeof tick.label === 'string')).toBe(true)
  })

  it('names the month far out and the day close in', () => {
    expect(axisTicks(EPOCH, 120, 8)[0].label).toBe('Apr')
    expect(axisTicks(EPOCH, 120, 120)[0].label).toBe('Apr 1')
  })

  it('covers the whole span', () => {
    const ticks = axisTicks(EPOCH, 90, 8)
    expect(ticks[ticks.length - 1].day).toBeGreaterThanOrEqual(90)
  })
})

describe('reading the payload', () => {
  it('places an instant as whole days from the epoch', () => {
    expect(dayOf('2026-04-11T00:00:00Z', EPOCH)).toBe(10)
  })

  it('refuses to place an instant it cannot read', () => {
    expect(dayOf('not a date', EPOCH)).toBeNull()
  })

  it('prints a replay offset as a timecode', () => {
    expect(timecode(0)).toBe('0:00')
    expect(timecode(95_000)).toBe('1:35')
    expect(timecode(3_725_000)).toBe('1:02:05')
  })
})

describe('why a stop shows no screens', () => {
  it('claims no recording only when that was established', () => {
    expect(noScreenReason(false)).toContain('Transcript only')
    expect(noScreenReason(false)).toContain('no recording')
  })

  it('never claims no recording about a meeting that has one', () => {
    // The AD-18 line: a recorded meeting whose quoted moments carry no still
    // is an observed absence, not an established one.
    const reason = noScreenReason(true)
    expect(reason).not.toContain('no recording')
    expect(reason).toContain('No screen was captured')
  })

  it('always says something, so a stop is never a bare blank', () => {
    expect(noScreenReason(true).length).toBeGreaterThan(0)
    expect(noScreenReason(false).length).toBeGreaterThan(0)
  })
})
