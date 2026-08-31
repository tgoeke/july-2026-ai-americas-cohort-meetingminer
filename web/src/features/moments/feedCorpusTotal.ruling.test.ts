import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchMomentsFeed, NO_FILTERS, parseFeedResponse } from './feed'

const envelope = (overrides: Record<string, unknown> = {}) => ({
  items: [],
  total: 0,
  corpusTotal: 24,
  limit: 24,
  offset: 0,
  ...overrides,
})

describe('F3 owner ruling: one-response corpus count', () => {
  it('retains the separate unfiltered corpus count', () => {
    expect(parseFeedResponse(envelope()).corpusTotal).toBe(24)
  })

  it.each([
    [{ corpusTotal: undefined }, 'corpusTotal'],
    [{ corpusTotal: -1 }, 'corpusTotal'],
    [{ corpusTotal: 1.5 }, 'corpusTotal'],
    [{ total: 25, corpusTotal: 24 }, 'total must not exceed corpusTotal'],
  ])('refuses an inconsistent envelope %o', (overrides, message) => {
    expect(() => parseFeedResponse(envelope(overrides))).toThrow(message)
  })

  it('rejects unequal totals when no item filter narrows the selected corpus', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(JSON.stringify(
      envelope({ total: 6, corpusTotal: 24 }),
    )))))
    await expect(fetchMomentsFeed(NO_FILTERS, 24, 0)).rejects.toThrow(
      'corpus-scoped feed response: total must equal corpusTotal',
    )
    await expect(fetchMomentsFeed({ ...NO_FILTERS, kind: 'decision' }, 24, 0)).resolves.toMatchObject({
      total: 6,
      corpusTotal: 24,
    })
  })

  it('rejects a response for a different requested page', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(JSON.stringify(
      envelope({ total: 12, corpusTotal: 12, limit: 12, offset: 12 }),
    )))))
    await expect(fetchMomentsFeed(NO_FILTERS, 24, 0)).rejects.toThrow(
      'feed response page does not match the request',
    )
  })
})

afterEach(() => vi.unstubAllGlobals())
