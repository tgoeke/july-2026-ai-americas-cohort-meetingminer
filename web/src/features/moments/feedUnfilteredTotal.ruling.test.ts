import { describe, expect, it } from 'vitest'
import { parseFeedResponse } from './feed'

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
})
