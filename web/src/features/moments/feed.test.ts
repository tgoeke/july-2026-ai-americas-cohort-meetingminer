import { describe, expect, it } from 'vitest'
import {
  ARTIFACT_KINDS,
  FeedContractError,
  cardMetaLabel,
  filterEmptySentence,
  hasActiveFilters,
  isArtifactKind,
  isoDateOf,
  momentsHeaderCount,
  NO_FILTERS,
  offsetChipLabel,
  parseFeedResponse,
  screenshotAlt,
  screenshotUrl,
  threadChipName,
  threadPaletteOf,
  type MomentFeedItem,
} from './feed'

/** One served feed item, in story 10.4's field names. Fixtures live here
 * rather than in a shared conftest so this story's shape cannot drift into
 * another lane's tests (wave rules, 2026-08-30). */
function item(overrides: Partial<MomentFeedItem> = {}): MomentFeedItem {
  return {
    momentId: 'moment-1',
    meetingId: 'meeting-1',
    meetingTitle: 'Retrieval bake-off review',
    startedAt: '2026-08-14T12:00:00Z',
    startedAtPrecision: 'second',
    startMs: 760_000,
    endMs: 845_000,
    corpus: 'real',
    hasRecording: true,
    sourceDeepLink: null,
    screenshotId: 'screenshot-1',
    viewType: 'slide',
    preview: 'BM25 stays first-class; hybrid only on paraphrase.',
    threads: [{ threadId: 'thread-1', name: 'retrieval split', colorOrdinal: 1 }],
    reasons: [
      {
        kind: 'decision',
        label: 'decision at 12:40',
        ref: 'artifact-1',
        at: '2026-08-14T12:40:00Z',
      },
    ],
    ...overrides,
  }
}

describe('isArtifactKind', () => {
  it('accepts the seven publishable kinds and nothing else', () => {
    for (const kind of ARTIFACT_KINDS) expect(isArtifactKind(kind)).toBe(true)
    // Story 10.4 persists risk and question as ranking signals, not artifacts;
    // they must never be drawn as a kind chip.
    for (const kind of ['risk', 'question', 'due', 'recency', 'published', 'thread', 'topic']) {
      expect(isArtifactKind(kind)).toBe(false)
    }
  })
})

describe('hasActiveFilters', () => {
  it('is false only when nothing narrows the feed', () => {
    expect(hasActiveFilters(NO_FILTERS)).toBe(false)
    expect(hasActiveFilters({ ...NO_FILTERS, kind: 'decision' })).toBe(true)
    expect(hasActiveFilters({ ...NO_FILTERS, meeting: 'meeting-1' })).toBe(true)
  })
})

describe('parseFeedResponse', () => {
  it('reads the envelope and its items', () => {
    const page = parseFeedResponse({
      items: [item()],
      total: 24,
      corpusTotal: 24,
      limit: 24,
      offset: 0,
    })
    expect(page.total).toBe(24)
    expect(page.items[0].momentId).toBe('moment-1')
    expect(page.items[0].threads[0].colorOrdinal).toBe(1)
    expect(page.items[0].reasons[0].label).toBe('decision at 12:40')
  })

  it('refuses an item with no reason rather than rendering an unexplained card', () => {
    // Story 10.4 drops these before pagination. One that escapes would make
    // the header count a lie, so it is a page-level error, not a quiet card.
    expect(() => parseFeedResponse({ items: [item({ reasons: [] })], total: 1, corpusTotal: 1 })).toThrow(
      FeedContractError,
    )
    expect(() => parseFeedResponse({ items: [item({ reasons: [] })], total: 1, corpusTotal: 1 })).toThrow(
      /items\[0\]: reasons\[\] must be non-empty/,
    )
  })

  it('names the field and the item when a required value is missing', () => {
    expect(() =>
      parseFeedResponse({ items: [{ ...item(), momentId: undefined }], total: 1, corpusTotal: 1 }),
    ).toThrow(/items\[0\]: momentId/)
  })

  it('refuses a body that is not the paged envelope', () => {
    expect(() => parseFeedResponse({ moments: [] })).toThrow(/items array/)
    expect(() => parseFeedResponse(null)).toThrow(/must be an object/)
  })

  it('refuses an envelope that omits its required paging fields', () => {
    expect(() => parseFeedResponse({ items: [item()], corpusTotal: 1 })).toThrow(/total/)
  })
})

describe('momentsHeaderCount', () => {
  it('counts the corpus when nothing is filtered', () => {
    expect(momentsHeaderCount(24, 24, false)).toBe('24')
    // Paging is not filtering: 24 of 96 shown unfiltered still reads as 96.
    expect(momentsHeaderCount(24, 96, false)).toBe('96')
  })

  it('reads "6 of 24" once a filter narrows it', () => {
    expect(momentsHeaderCount(6, 24, true)).toBe('6 of 24')
    expect(momentsHeaderCount(24, 24, true)).toBe('24')
  })
})

describe('isoDateOf', () => {
  it('keeps the date and drops the time — no relative dates anywhere', () => {
    expect(isoDateOf('2026-08-14T12:00:00Z')).toBe('2026-08-14')
    expect(isoDateOf('2026-08-14')).toBe('2026-08-14')
    expect(isoDateOf(null)).toBeNull()
    expect(isoDateOf('not a date')).toBeNull()
  })
})

describe('cardMetaLabel', () => {
  it('reads date · span · corpus from served values', () => {
    expect(cardMetaLabel(item())).toBe('2026-08-14 · 12:40–14:05 · real')
  })

  it('shows one offset when the served end does not follow the start', () => {
    expect(cardMetaLabel(item({ endMs: 760_000 }))).toBe('2026-08-14 · 12:40 · real')
  })

  it('leaves out an empty corpus rather than inventing one', () => {
    expect(cardMetaLabel(item({ corpus: '' }))).toBe('2026-08-14 · 12:40–14:05')
  })
})

describe('offsetChipLabel', () => {
  it('names the view type and the offset', () => {
    expect(offsetChipLabel(item())).toBe('slide · 12:40')
    expect(offsetChipLabel(item({ viewType: null }))).toBe('12:40')
  })
})

describe('screenshotAlt', () => {
  it('is "<viewType> at <offset>, <meetingTitle>"', () => {
    expect(screenshotAlt(item())).toBe('slide at 12:40, Retrieval bake-off review')
  })

  it('degrades to what it knows rather than to an empty alt', () => {
    expect(screenshotAlt(item({ viewType: null, meetingTitle: null }))).toBe(
      'screenshot at 12:40',
    )
  })
})

describe('screenshotUrl', () => {
  it('is id-addressed, never a storage path (AD-17)', () => {
    expect(screenshotUrl('screenshot 1/../etc')).toBe(
      'http://localhost:8000/media/files/screenshot%201%2F..%2Fetc',
    )
  })
})

describe('filterEmptySentence', () => {
  it('names every active filter, the thread by its served name', () => {
    expect(
      filterEmptySentence(
        { corpus: 'real', thread: 'thread-1', kind: 'decision', meeting: null },
        'retrieval split',
      ),
    ).toBe('No moments match corpus real · thread #retrieval split · kind decision.')
  })

  it('falls back to the thread id when its name is not known', () => {
    expect(filterEmptySentence({ ...NO_FILTERS, thread: 'thread-9' })).toBe(
      'No moments match thread #thread-9.',
    )
  })
})

describe('threadPaletteOf', () => {
  it('maps ordinals 1–8 onto the eight hues at lap 1', () => {
    expect(threadPaletteOf(1)).toEqual({
      hue: 1,
      lap: 1,
      textCssVar: '--thread-1-band',
      swatchCssVar: '--thread-1-band',
    })
    expect(threadPaletteOf(8)).toEqual({
      hue: 8,
      lap: 1,
      textCssVar: '--thread-8-band',
      swatchCssVar: '--thread-8-band',
    })
  })

  it('maps 9–16 onto the same hues at lap 2', () => {
    expect(threadPaletteOf(9)).toEqual({
      hue: 1,
      lap: 2,
      textCssVar: '--thread-1-band',
      swatchCssVar: '--thread-1-band-lap2',
    })
    expect(threadPaletteOf(16)).toEqual({
      hue: 8,
      lap: 2,
      textCssVar: '--thread-8-band',
      swatchCssVar: '--thread-8-band-lap2',
    })
  })

  it('goes grey past the palette rather than recycling a hue', () => {
    for (const ordinal of [17, 40, 0, -1, 2.5]) {
      expect(threadPaletteOf(ordinal).textCssVar).toBe('--thread-beyond-band')
      expect(threadPaletteOf(ordinal).hue).toBeNull()
    }
  })

  it('depends only on the ordinal, never on position in a list', () => {
    // The api owns identity; the client owns only this mapping. A thread that
    // sorts differently must keep its hue.
    expect(threadPaletteOf(3)).toEqual(threadPaletteOf(3))
    expect(threadPaletteOf(3).textCssVar).not.toBe(threadPaletteOf(4).textCssVar)
  })
})

describe('threadChipName', () => {
  it('reads "thread <name>" — the # is decoration', () => {
    expect(threadChipName({ threadId: 't', name: 'retrieval split', colorOrdinal: 1 })).toBe(
      'thread retrieval split',
    )
  })
})
