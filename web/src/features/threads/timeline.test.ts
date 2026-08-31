import { describe, expect, it } from 'vitest'
import {
  axisTicks,
  bucketUnitFor,
  cacheKey,
  clampScale,
  clusterByX,
  clusterSpan,
  densityAlpha,
  fetchSpan,
  fitView,
  HYSTERESIS,
  isoDay,
  MIN_SCALE,
  offsetLabel,
  panByPixels,
  panByWindow,
  TIER_MAX_SCALE,
  TIER_MIN_SCALE,
  tierForScale,
  timeAtX,
  visibleSpan,
  xOf,
  zoomAbout,
  type Tier,
  type View,
} from './timeline'
import { CLUSTERED_MOMENTS, MOMENTS } from './fixtures'

const WIDTH = 1000

describe('the time to x mapping', () => {
  it('places an instant at (t − from) / scale and inverts', () => {
    const view: View = { from: 1_000_000, scale: 2_000 }
    expect(xOf(1_400_000, view)).toBe(200)
    expect(timeAtX(200, view)).toBe(1_400_000)
  })

  it('is unchanged by a tier change, which is what "no layout jump" means', () => {
    // A view whose scale sits one notch either side of the bands/meetings
    // threshold: the tier differs, the mapping does not.
    const t = Date.parse('2026-05-13T15:00:00Z')
    const coarse: View = { from: Date.parse('2026-03-01T00:00:00Z'), scale: 7_300_000 }
    const fine: View = { ...coarse, scale: 7_100_000 }
    expect(tierForScale(coarse.scale, 'bands')).toBe('bands')
    expect(tierForScale(fine.scale, 'bands')).toBe('meetings')
    // The tier is a function of the scale; the mapping does not consult it.
    expect(xOf(t, coarse)).toBeCloseTo((t - coarse.from) / coarse.scale, 9)
    expect(xOf(t, fine)).toBeCloseTo((t - fine.from) / fine.scale, 9)
  })
})

describe('level-of-detail thresholds', () => {
  it('enters a finer tier the moment the scale passes the floor', () => {
    expect(tierForScale(TIER_MIN_SCALE.bands, 'bands')).toBe('bands')
    expect(tierForScale(TIER_MIN_SCALE.bands - 1, 'bands')).toBe('meetings')
    expect(tierForScale(TIER_MIN_SCALE.meetings - 1, 'meetings')).toBe('moments')
  })

  it('needs 1.25x the ceiling to leave a tier upward, so a notch cannot flap', () => {
    // 2 h/px enters meetings; 2.5 h/px is what leaves it again.
    expect(tierForScale(TIER_MAX_SCALE.meetings, 'meetings')).toBe('meetings')
    expect(tierForScale(TIER_MAX_SCALE.meetings * HYSTERESIS - 1, 'meetings')).toBe('meetings')
    expect(tierForScale(TIER_MAX_SCALE.meetings * HYSTERESIS, 'meetings')).toBe('bands')
    // 4 min/px enters moments; 5 min/px leaves it.
    expect(TIER_MAX_SCALE.moments * HYSTERESIS).toBe(300_000)
    expect(tierForScale(299_999, 'moments')).toBe('moments')
    expect(tierForScale(300_000, 'moments')).toBe('meetings')
  })

  it('crosses more than one tier in one step when a Fit demands it', () => {
    expect(tierForScale(50_000_000, 'moments')).toBe('bands')
    expect(tierForScale(3_000, 'bands')).toBe('moments')
  })

  it('stops at the moments tier — the evidence tier is story 10.6a', () => {
    expect(clampScale(500)).toBe(MIN_SCALE)
    expect(tierForScale(clampScale(500), 'moments')).toBe('moments')
    const tiers: Array<Tier> = ['bands', 'meetings', 'moments']
    for (const tier of tiers) expect(tierForScale(1, tier)).toBe('moments')
  })
})

describe('zoom about a focus point', () => {
  it('keeps the instant under the focus point at the same pixel', () => {
    const view: View = { from: Date.parse('2026-03-01T00:00:00Z'), scale: 7_300_000 }
    const focusX = 640
    const under = timeAtX(focusX, view)
    for (const factor of [1 / 1.25, 1 / 1.5, 1.25, 1.5, 1 / 4]) {
      const after = zoomAbout(view, factor, focusX)
      expect(xOf(under, after)).toBeCloseTo(focusX, 6)
    }
  })

  it('keeps the focus point fixed across a threshold crossing', () => {
    // The zoom that takes the view from the bands tier to the meetings tier
    // must not move the item the reader was looking at.
    const view: View = { from: Date.parse('2026-03-01T00:00:00Z'), scale: 7_400_000 }
    const focusX = 300
    const under = timeAtX(focusX, view)
    const after = zoomAbout(view, 1 / 1.25, focusX)
    expect(tierForScale(view.scale, 'bands')).toBe('bands')
    expect(tierForScale(after.scale, 'bands')).toBe('meetings')
    expect(xOf(under, after)).toBeCloseTo(focusX, 6)
  })

  it('never zooms past the evidence threshold', () => {
    const view: View = { from: 0, scale: 2_100 }
    expect(zoomAbout(view, 1 / 100, 500).scale).toBe(MIN_SCALE)
  })
})

describe('fitting and panning', () => {
  it('fits a span into the canvas width', () => {
    const span = { from: 0, to: 10_000_000 }
    const view = fitView(span, WIDTH)
    expect(view.from).toBe(0)
    expect(view.scale).toBe(10_000)
    expect(visibleSpan(view, WIDTH)).toEqual(span)
  })

  it('widens a zero-length span rather than dividing to a zero scale', () => {
    const view = fitView({ from: 5_000_000, to: 5_000_000 }, WIDTH)
    expect(view.scale).toBeGreaterThan(0)
    expect(xOf(5_000_000, view)).toBeCloseTo(WIDTH / 2, 6)
  })

  it('pans by a fraction of the window and by pixels', () => {
    const view: View = { from: 0, scale: 1_000 }
    expect(panByWindow(view, 0.8, WIDTH).from).toBe(800_000)
    expect(panByPixels(view, -50).from).toBe(50_000)
  })
})

describe('the bands tier bucket', () => {
  it('picks the smallest unit that is at least 8px wide', () => {
    expect(bucketUnitFor(1_000_000)).toBe('day')
    expect(bucketUnitFor(10_800_000)).toBe('day')
    expect(bucketUnitFor(10_800_001)).toBe('week')
    expect(bucketUnitFor(75_600_000)).toBe('week')
    expect(bucketUnitFor(75_600_001)).toBe('month')
  })
})

describe('fetch discipline', () => {
  it('asks for the visible window padded half a window each side', () => {
    const view: View = { from: 0, scale: 1_000 }
    const span = fetchSpan(view, WIDTH)
    expect(span.from).toBeLessThanOrEqual(-500_000)
    expect(span.to).toBeGreaterThanOrEqual(1_500_000)
  })

  it('snaps the edges so a pan inside one snap cell still hits the cache', () => {
    const view: View = { from: 120_000, scale: 1_000 }
    expect(fetchSpan(view, WIDTH)).toEqual(fetchSpan(panByPixels(view, -1), WIDTH))
    expect(fetchSpan(view, WIDTH)).toEqual(fetchSpan(panByPixels(view, -60), WIDTH))
    // Crossing a snap boundary is a different window and does ask again — the
    // snap bounds how often that happens, it does not pretend it never does.
    expect(fetchSpan(view, WIDTH)).not.toEqual(fetchSpan(panByPixels(view, -400), WIDTH))
  })

  it('makes pin membership part of the request identity', () => {
    const span = { from: 0, to: 1 }
    expect(cacheKey(['a'], 'bands', span)).not.toBe(cacheKey(['a', 'b'], 'bands', span))
    expect(cacheKey(['b', 'a'], 'bands', span)).toBe(cacheKey(['a', 'b'], 'bands', span))
    expect(cacheKey(['a'], 'bands', span)).not.toBe(cacheKey(['a'], 'meetings', span))
  })
})

describe('mention density', () => {
  it('draws an empty bucket at the zero step so the band keeps its span', () => {
    expect(densityAlpha([0, 4, 9, 14])(0)).toBe(0.08)
  })

  it('splits the nonzero counts at their quartiles', () => {
    const alpha = densityAlpha([0, 1, 2, 3, 4, 5, 6, 7, 8])
    expect(alpha(1)).toBe(0.6)
    expect(alpha(8)).toBe(1)
    expect(alpha(3)).toBeLessThan(alpha(6))
  })

  it('gives a uniformly busy window the top step, not the lowest', () => {
    const alpha = densityAlpha([0, 5, 5, 5])
    expect(alpha(5)).toBe(1)
    expect(alpha(0)).toBe(0.08)
  })

  it('rescales as the window changes — the steps are per window, not global', () => {
    const wide = densityAlpha([1, 2, 3, 40])
    const narrow = densityAlpha([1, 2])
    expect(wide(2)).not.toBe(narrow(2))
  })
})

describe('clustering at the moments tier', () => {
  const timeOf = (m: { occurredAt: string }) => Date.parse(m.occurredAt)

  it('keeps moments apart when their hit areas do not collide', () => {
    // 2 s/px: an hour and a half of meeting is 2700px, the moments are minutes
    // apart, so every one is its own cell.
    const view: View = { from: Date.parse(MOMENTS[0].occurredAt), scale: 2_000 }
    const cells = clusterByX(MOMENTS, timeOf, view)
    expect(cells).toHaveLength(MOMENTS.length)
    expect(cells.every((c) => c.kind === 'item')).toBe(true)
  })

  it('clusters moments whose 24px hit areas would overlap, losing none', () => {
    // 4 min/px: 32 seconds apart is well under a quarter of a pixel.
    const view: View = { from: Date.parse(CLUSTERED_MOMENTS[0].occurredAt), scale: 240_000 }
    const cells = clusterByX(CLUSTERED_MOMENTS, timeOf, view)
    expect(cells).toHaveLength(1)
    expect(cells[0].kind).toBe('cluster')
    if (cells[0].kind === 'cluster') expect(cells[0].items).toHaveLength(2)
  })

  it('gives a cluster a span that Enter can zoom to fit', () => {
    const view: View = { from: Date.parse(CLUSTERED_MOMENTS[0].occurredAt), scale: 240_000 }
    const span = clusterSpan(clusterByX(CLUSTERED_MOMENTS, timeOf, view)[0])
    expect(span.to).toBeGreaterThan(span.from)
  })
})

describe('labels', () => {
  it('prints a day and a replay offset', () => {
    expect(isoDay(Date.parse('2026-05-13T15:00:00Z'))).toBe('2026-05-13')
    expect(offsetLabel(252_000)).toBe('0:04:12')
    expect(offsetLabel(3_849_000)).toBe('1:04:09')
    expect(offsetLabel(-5)).toBe('0:00:00')
  })

  it('spaces axis ticks across the visible window', () => {
    const ticks = axisTicks({ from: 0, scale: 1_000 }, WIDTH, 4)
    expect(ticks).toEqual([0, 250_000, 500_000, 750_000, 1_000_000])
  })
})
