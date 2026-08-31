import { createElement } from 'react'
import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { TimelineCanvas } from './TimelineCanvas'
import { fetchTimeline, listThreads, parseThreads, parseTimeline } from './threadsApi'

const THREAD_ID = '018f8f4c-3a53-7c11-8f6c-1a2b3c4d5e6f'
const MEETING_ID = '018f8f4c-3a53-7c11-8f6c-1a2b3c4d5e70'
const MOMENT_ID = '018f8f4c-3a53-7c11-8f6c-1a2b3c4d5e71'

const envelope = {
  threadId: THREAD_ID,
  name: 'retrieval split',
  colorOrdinal: 1,
  windowFrom: '2026-05-01T00:00:00Z',
  windowTo: '2026-06-01T00:00:00Z',
  mentionCount: 4,
  meetingCount: 1,
  momentCount: 1,
}

function response(payload: unknown): Response {
  return {
    ok: true,
    status: 200,
    statusText: 'OK',
    text: async () => JSON.stringify(payload),
  } as Response
}

afterEach(() => vi.unstubAllGlobals())

describe('Story 10.3 wire contract', () => {
  it('parses the implemented bands, meetings, and moments envelopes', () => {
    const bands = parseTimeline('bands', {
      ...envelope,
      level: 'bands',
      bucketMs: 86_400_000,
      bucketCount: 1,
      bands: [
        {
          startAt: '2026-05-01T00:00:00Z',
          endAt: '2026-05-02T00:00:00Z',
          mentionCount: 4,
          meetingCount: 1,
        },
      ],
    })
    expect(bands).toMatchObject({
      level: 'bands',
      buckets: [
        { from: '2026-05-01T00:00:00Z', to: '2026-05-02T00:00:00Z', mentionCount: 4 },
      ],
    })

    const meetings = parseTimeline('meetings', {
      ...envelope,
      level: 'meetings',
      meetings: [
        {
          meetingId: MEETING_ID,
          title: null,
          corpus: 'real',
          hasRecording: false,
          occurredAt: '2026-05-13T15:00:00Z',
          lastOccurredAt: '2026-05-13T15:05:00Z',
          occurredAtPrecision: 'second',
          mentionCount: 4,
          momentCount: 1,
          topics: [],
        },
      ],
    })
    expect(meetings.level === 'meetings' && meetings.meetings[0]).toMatchObject({
      title: null,
      durationMs: 300_000,
      lastOccurredAt: '2026-05-13T15:05:00Z',
    })

    const moments = parseTimeline('moments', {
      ...envelope,
      level: 'moments',
      truncated: false,
      moments: [
        {
          momentId: MOMENT_ID,
          meetingId: MEETING_ID,
          title: 'Why BM25 wins',
          startMs: 252_000,
          occurredAt: '2026-05-13T15:04:12Z',
          occurredAtPrecision: 'second',
          speakers: ['Priya Natarajan'],
          screenshotId: null,
        },
      ],
    })
    expect(moments.level === 'moments' && moments.moments[0]).toMatchObject({
      momentId: MOMENT_ID,
      title: 'Why BM25 wins',
      speakers: ['Priya Natarajan'],
    })
  })

  it('keeps a moment whose evidence instant lies outside the mention-anchor window', () => {
    const occurredAt = '2026-06-01T00:00:01Z'
    const moments = parseTimeline('moments', {
      ...envelope,
      level: 'moments',
      truncated: false,
      moments: [
        {
          momentId: MOMENT_ID,
          meetingId: MEETING_ID,
          title: 'Evidence begins after the mention anchor',
          startMs: 2_678_401_000,
          occurredAt,
          occurredAtPrecision: 'second',
          speakers: [],
        },
      ],
    })

    expect(moments.level === 'moments' && moments.moments[0]?.occurredAt).toBe(occurredAt)
    if (moments.level !== 'moments') throw new Error('expected moments payload')
    const view = {
      from: Date.parse(envelope.windowFrom),
      scale: (Date.parse(envelope.windowTo) - Date.parse(envelope.windowFrom)) / 1000,
    }
    render(
      createElement(TimelineCanvas, {
        tier: 'moments',
        view,
        width: 1000,
        epochMs: 0,
        rootRef: () => undefined,
        threads: [
          {
            threadId: THREAD_ID,
            name: envelope.name,
            mentionCount: envelope.mentionCount,
            meetingCount: envelope.meetingCount,
            firstMentionAt: envelope.windowFrom,
            lastMentionAt: envelope.windowTo,
            colorOrdinal: envelope.colorOrdinal,
          },
        ],
        focusedThreadId: THREAD_ID,
        bands: null,
        meetings: null,
        moments: moments.moments,
        pending: false,
        onZoomAt: vi.fn(),
        onPan: vi.fn(),
        onPanPixels: vi.fn(),
        onFitTo: vi.fn(),
        onFitAll: vi.fn(),
        onFocusThread: vi.fn(),
        onOpenMoment: vi.fn(),
      }),
    )
    expect(
      screen.getByRole('gridcell', { name: /Evidence begins after the mention anchor/ }),
    ).toHaveAttribute('data-t', String(Date.parse(occurredAt)))
  })

  it('refuses truncated or malformed responses instead of half-drawing them', () => {
    expect(() =>
      parseTimeline('moments', {
        ...envelope,
        level: 'moments',
        truncated: true,
        moments: [],
      }),
    ).toThrow(/truncated/i)

    expect(() =>
      parseTimeline('moments', {
        ...envelope,
        level: 'moments',
        truncated: false,
        moments: [
          {
            momentId: MOMENT_ID,
            meetingId: MEETING_ID,
            title: 'Bad instant',
            startMs: 0,
            occurredAt: 'not-an-instant',
            occurredAtPrecision: 'second',
            speakers: [],
          },
        ],
      }),
    ).toThrow(/not an RFC 3339 instant/)

    expect(() =>
      parseTimeline('moments', {
        ...envelope,
        level: 'moments',
        truncated: false,
        moments: [
          {
            momentId: MOMENT_ID,
            meetingId: MEETING_ID,
            title: 'Bad speakers',
            startMs: 0,
            occurredAt: '2026-05-13T15:00:00Z',
            occurredAtPrecision: 'second',
            speakers: ['Priya', 4],
          },
        ],
      }),
    ).toThrow(/speakers/)
  })

  it('classifies a reachable malformed API as a problem, not a transport outage', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(response({ threads: [{ threadId: THREAD_ID }] }))))
    const result = await listThreads()
    expect(result.error).toMatchObject({ kind: 'problem' })
    expect(result.error?.message).toMatch(/GET \/threads\[0\].*name/s)
  })

  it('refuses a thread summary whose served mention extents are reversed', () => {
    expect(() =>
      parseThreads([
        {
          threadId: THREAD_ID,
          name: 'reversed extents',
          mentionCount: 2,
          meetingCount: 1,
          firstMentionAt: '2026-06-01T00:00:00Z',
          lastMentionAt: '2026-05-01T00:00:00Z',
          colorOrdinal: 1,
        },
      ]),
    ).toThrow(/GET \/threads\[0\].*lastMentionAt.*before.*firstMentionAt/s)
  })

  it('uses the live bands envelope through fetchTimeline', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve(
          response({
            ...envelope,
            level: 'bands',
            bucketMs: 86_400_000,
            bucketCount: 1,
            bands: [
              {
                startAt: '2026-05-01T00:00:00Z',
                endAt: '2026-05-02T00:00:00Z',
                mentionCount: 4,
                meetingCount: 1,
              },
            ],
          }),
        ),
      ),
    )
    const result = await fetchTimeline({
      threadId: THREAD_ID,
      level: 'bands',
      from: Date.parse('2026-05-01T00:00:00Z'),
      to: Date.parse('2026-06-01T00:00:00Z'),
    })
    expect(result.error).toBeUndefined()
    expect(result.data?.level === 'bands' && result.data.buckets).toHaveLength(1)
  })
})
