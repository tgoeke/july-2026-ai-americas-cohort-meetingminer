import { describe, expect, it } from 'vitest'
import { EMBEDDING_BAKE_OFF, MOMENTS, RETRIEVAL_SPLIT, RETRIEVAL_SPLIT_BANDS } from './fixtures'
import { instantOf, parseThreads, parseTimeline } from './threadsApi'

describe('GET /threads', () => {
  it('reads story 10.3s field names', () => {
    const rows = parseThreads([RETRIEVAL_SPLIT])
    expect(rows[0].threadId).toBe('th-retrieval-split')
    expect(rows[0].colorOrdinal).toBe(1)
    expect(rows[0].mentionCount).toBe(47)
  })

  it('accepts the rows wrapped in an envelope as well as bare', () => {
    expect(parseThreads({ threads: [RETRIEVAL_SPLIT] })).toHaveLength(1)
  })

  it('refuses a row missing a field, naming the field and the row', () => {
    const { colorOrdinal: _dropped, ...withoutOrdinal } = RETRIEVAL_SPLIT
    expect(() => parseThreads([withoutOrdinal])).toThrow(/GET \/threads\[0\].*colorOrdinal/s)
  })

  it('refuses a body that is not a list at all', () => {
    expect(() => parseThreads({ items: 3 })).toThrow(/expected an array of threads/)
  })
})

describe('GET /threads/{id}/timeline', () => {
  it('reads bands, meetings and moments at their own levels', () => {
    const bands = parseTimeline('bands', { buckets: RETRIEVAL_SPLIT_BANDS })
    expect(bands.level).toBe('bands')
    if (bands.level === 'bands') expect(bands.buckets[0].mentionCount).toBe(4)

    const meetings = parseTimeline('meetings', { meetings: [EMBEDDING_BAKE_OFF] })
    if (meetings.level === 'meetings') {
      expect(meetings.meetings[0].title).toBe('Embedding bake-off')
      expect(meetings.meetings[0].durationMs).toBe(5_400_000)
    }

    const moments = parseTimeline('moments', { moments: MOMENTS })
    if (moments.level === 'moments') {
      expect(moments.moments).toHaveLength(MOMENTS.length)
      expect(moments.moments[0].speakers).toEqual(['Priya Natarajan'])
    }
  })

  it('treats a moment with no named speakers as no speakers, not as unknown text', () => {
    const parsed = parseTimeline('moments', { moments: [{ ...MOMENTS[0], speakers: null }] })
    if (parsed.level === 'moments') expect(parsed.moments[0].speakers).toEqual([])
  })

  it('refuses a moment without the instant it would be drawn at', () => {
    const { occurredAt: _dropped, ...withoutInstant } = MOMENTS[0]
    expect(() => parseTimeline('moments', { moments: [withoutInstant] })).toThrow(/occurredAt/)
  })

  it('refuses the evidence level by name — that tier is story 10.6a', () => {
    expect(() => parseTimeline('evidence', { items: [] })).toThrow(/story 10\.6a/)
  })
})

describe('instants', () => {
  it('reads an RFC 3339 instant and refuses anything else by value', () => {
    expect(instantOf('2026-05-13T15:00:00Z', 'x')).toBe(Date.parse('2026-05-13T15:00:00Z'))
    expect(() => instantOf('the thirteenth', 'x')).toThrow(/not an RFC 3339 instant/)
  })
})
