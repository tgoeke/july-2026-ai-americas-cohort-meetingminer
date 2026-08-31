import { describe, expect, it } from 'vitest'
import { parseThreadsResponse } from './threads'

describe('F11 owner ruling: documented thread catalog', () => {
  it('reads a populated GET /threads response without deriving feed-card data', () => {
    expect(
      parseThreadsResponse({
        threads: [
          {
            threadId: 'thread-off-page',
            name: 'Off-page launch work',
            mentionCount: 9,
            meetingCount: 3,
            firstMentionAt: '2026-08-01T12:00:00Z',
            lastMentionAt: '2026-08-31T12:00:00Z',
            colorOrdinal: 2,
          },
        ],
      }),
    ).toEqual([{ threadId: 'thread-off-page', name: 'Off-page launch work' }])
  })

  it('rejects duplicate ids and reversed timestamps', () => {
    const row = {
      threadId: 'thread-1',
      name: 'Launch',
      mentionCount: 2,
      meetingCount: 1,
      firstMentionAt: '2026-08-31T12:00:00Z',
      lastMentionAt: '2026-08-01T12:00:00Z',
      colorOrdinal: 1,
    }
    expect(() => parseThreadsResponse({ threads: [row] })).toThrow('must not follow')
    expect(() => parseThreadsResponse({
      threads: [
        { ...row, firstMentionAt: '2026-08-01T12:00:00Z' },
        { ...row, firstMentionAt: '2026-08-01T12:00:00Z' },
      ],
    })).toThrow('duplicate threadId')
  })
})
