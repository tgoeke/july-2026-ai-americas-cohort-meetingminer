import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchMomentsFeed, NO_FILTERS, parseFeedResponse } from './feed'

const envelope = (overrides: Record<string, unknown> = {}) => ({
  items: [],
  total: 0,
  unfilteredTotal: 24,
  limit: 24,
  offset: 0,
  ...overrides,
})

describe('F3 owner ruling: one-response unfiltered count', () => {
  it('retains the separate unfiltered corpus count', () => {
    expect(parseFeedResponse(envelope()).unfilteredTotal).toBe(24)
  })

  it.each([
    [{ unfilteredTotal: undefined }, 'unfilteredTotal'],
    [{ unfilteredTotal: -1 }, 'unfilteredTotal'],
    [{ unfilteredTotal: 1.5 }, 'unfilteredTotal'],
    [{ total: 25, unfilteredTotal: 24 }, 'total must not exceed unfilteredTotal'],
  ])('refuses an inconsistent envelope %o', (overrides, message) => {
    expect(() => parseFeedResponse(envelope(overrides))).toThrow(message)
  })

  it('rejects unequal totals only when the request has no active filter', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(JSON.stringify(
      envelope({ total: 6, unfilteredTotal: 24 }),
    )))))
    await expect(fetchMomentsFeed(NO_FILTERS, 24, 0)).rejects.toThrow(
      'unfiltered feed response: total must equal unfilteredTotal',
    )
    await expect(fetchMomentsFeed({ ...NO_FILTERS, kind: 'decision' }, 24, 0)).resolves.toMatchObject({
      total: 6,
      unfilteredTotal: 24,
    })
  })

  it('rejects a response for a different requested page', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(JSON.stringify(
      envelope({ total: 12, unfilteredTotal: 12, limit: 12, offset: 12 }),
    )))))
    await expect(fetchMomentsFeed(NO_FILTERS, 24, 0)).rejects.toThrow(
      'feed response page does not match the request',
    )
  })
})

afterEach(() => vi.unstubAllGlobals())
