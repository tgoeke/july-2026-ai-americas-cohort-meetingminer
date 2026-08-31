import { describe, expect, it } from 'vitest'
import { parseFeedResponse } from './feed'

describe('landed moments feed denominator contract', () => {
  it('reads the exact live envelope with corpusTotal and no provisional alias', () => {
    const page = parseFeedResponse({
      items: [],
      total: 0,
      corpusTotal: 24,
      limit: 24,
      offset: 0,
    })

    expect(page.corpusTotal).toBe(24)
  })
})
