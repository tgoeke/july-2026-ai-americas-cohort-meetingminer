import { describe, expect, it } from 'vitest'
import { parseFeedResponse, threadPaletteOf } from './feed'

describe('review F1 — Story 10.4 colorOrdinal compatibility', () => {
  it('keeps a thread with a null ordinal and gives it no invented hue', () => {
    const page = parseFeedResponse({
      items: [
        {
          momentId: 'moment-1',
          meetingId: 'meeting-1',
          meetingTitle: 'Review',
          startedAt: '2026-08-31T12:00:00Z',
          startedAtPrecision: 'second',
          startMs: 1_000,
          endMs: 2_000,
          corpus: 'real',
          hasRecording: true,
          sourceDeepLink: null,
          screenshotId: null,
          viewType: null,
          preview: null,
          threads: [{ threadId: 'thread-1', name: 'retrieval', colorOrdinal: null }],
          reasons: [{ kind: 'thread', label: 'retrieval', ref: 'thread-1', at: null }],
        },
      ],
      total: 1,
      corpusTotal: 1,
      limit: 24,
      offset: 0,
    })

    expect(page.items[0].threads[0].colorOrdinal).toBeNull()
    expect(threadPaletteOf(page.items[0].threads[0].colorOrdinal ?? null)).toEqual({
      hue: null,
      lap: null,
      textCssVar: '--thread-beyond-band',
      swatchCssVar: '--thread-beyond-band',
    })
  })

  it('uses the lap-one hue for a lap-two name and the darker token only for its swatch', () => {
    expect(threadPaletteOf(9)).toEqual({
      hue: 1,
      lap: 2,
      textCssVar: '--thread-1-band',
      swatchCssVar: '--thread-1-band-lap2',
    })
  })
})
