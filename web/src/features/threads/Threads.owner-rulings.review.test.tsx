import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { Threads } from './Threads'
import { threadTimelinePath } from './threadTimelinePath'
import { fetchSpan, fitView, TIER_MIN_SCALE } from './timeline'

const ANCHOR = '2026-05-13T15:04:12Z'
const NEARBY_ANCHOR = '2026-05-13T15:04:13Z'
const SECOND_ANCHOR = '2026-06-17T18:30:00Z'
const OFFSET_ANCHOR = '2026-05-13T09:04:12-06:00'
const UNKNOWN_OFFSET_ANCHOR = '2026-05-13T15:04:12-00:00'
const ALPHA = {
  threadId: 'thread-alpha',
  name: 'alpha thread',
  mentionCount: 3,
  meetingCount: 1,
  firstMentionAt: '2026-05-01T00:00:00Z',
  lastMentionAt: '2026-05-03T00:00:00Z',
  colorOrdinal: 1,
}
const BETA = {
  threadId: 'thread-beta',
  name: 'beta thread',
  mentionCount: 8,
  meetingCount: 2,
  firstMentionAt: '2026-01-01T00:00:00Z',
  lastMentionAt: '2026-08-01T00:00:00Z',
  colorOrdinal: 2,
}

function response(payload: unknown): Response {
  return {
    ok: true,
    status: 200,
    statusText: 'OK',
    text: async () => JSON.stringify(payload),
  } as Response
}

function levelOf(url: string): string | null {
  return new URL(url, 'http://meetingminer.test').searchParams.get('level')
}

function Navigation() {
  const navigate = useNavigate()
  return (
    <>
      <button type="button" onClick={() => navigate(threadTimelinePath(BETA.threadId, ANCHOR))}>
        anchored beta
      </button>
      <button type="button" onClick={() => navigate(threadTimelinePath(ALPHA.threadId))}>
        bare alpha
      </button>
      <button
        type="button"
        onClick={() => navigate(threadTimelinePath(ALPHA.threadId, SECOND_ANCHOR))}
      >
        second alpha anchor
      </button>
      <button
        type="button"
        onClick={() => navigate(threadTimelinePath(ALPHA.threadId, NEARBY_ANCHOR))}
      >
        nearby alpha anchor
      </button>
      <button type="button" onClick={() => navigate(`/threads/${ALPHA.threadId}?at=last-week`)}>
        invalid alpha anchor
      </button>
    </>
  )
}

function mount(at: string, withNavigation = false) {
  return render(
    <MemoryRouter initialEntries={[at]}>
      {withNavigation ? <Navigation /> : null}
      <Routes>
        <Route path="/threads" element={<Threads />} />
        <Route path="/threads/:threadId" element={<Threads />} />
      </Routes>
    </MemoryRouter>,
  )
}

function viewOf() {
  const grid = screen.getByRole('grid')
  return {
    from: Number(grid.getAttribute('data-from')),
    scale: Number(grid.getAttribute('data-scale')),
    tier: grid.getAttribute('data-tier'),
  }
}

function timelineRequests(level: string, threadId?: string) {
  return vi
    .mocked(fetch)
    .mock.calls.map((call) => String(call[0]))
    .filter(
      (url) =>
        levelOf(url) === level &&
        (threadId === undefined || url.includes(`/threads/${threadId}/timeline?`)),
    )
}

function deferredResponse() {
  let resolve!: (value: Response) => void
  const promise = new Promise<Response>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

async function waitForTierRequest(level: string, threadId: string) {
  await waitFor(() =>
    expect(
      vi
        .mocked(fetch)
        .mock.calls.map((call) => String(call[0]))
        .some((url) => url.includes(`/threads/${threadId}/timeline?`) && levelOf(url) === level),
    ).toBe(true),
  )
}

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/threads')) return Promise.resolve(response([ALPHA, BETA]))
      if (levelOf(url) === 'bands') {
        return Promise.resolve(
          response({
            buckets: [
              {
                from: '2026-05-01T00:00:00Z',
                to: '2026-05-08T00:00:00Z',
                mentionCount: 1,
              },
            ],
          }),
        )
      }
      if (levelOf(url) === 'meetings') {
        return Promise.resolve(
          response({
            meetings: [
              {
                meetingId: 'meeting-one',
                title: 'Anchor meeting',
                occurredAt: ANCHOR,
                durationMs: 3_600_000,
                mentionCount: 1,
              },
            ],
          }),
        )
      }
      return Promise.resolve(response({ moments: [] }))
    }),
  )
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('owner rulings: optional thread moment anchor', () => {
  it('constructs a bare thread path unless a supplied RFC 3339 instant needs preserving', () => {
    expect(threadTimelinePath('thread/one')).toBe('/threads/thread%2Fone')

    const anchored = new URL(threadTimelinePath('thread/one', ANCHOR), 'http://meetingminer.test')
    expect(anchored.pathname).toBe('/threads/thread%2Fone')
    expect(anchored.searchParams.get('at')).toBe(ANCHOR)
  })

  it.each(['2026-02-30T00:00:00Z', '2026-01-01T24:00:00Z'])(
    'rejects the calendar-normalized invalid instant %s',
    (invalid) => {
      expect(() => threadTimelinePath(ALPHA.threadId, invalid)).toThrow(/RFC 3339/)
    },
  )

  it('rejects an empty thread id instead of constructing an ambiguous route', () => {
    expect(() => threadTimelinePath('', ANCHOR)).toThrow(/thread id/i)
    expect(() => threadTimelinePath('')).toThrow(/thread id/i)
  })

  it('rejects unknown-offset anchors and dot-segment thread ids in generated links', () => {
    expect(() => threadTimelinePath(ALPHA.threadId, UNKNOWN_OFFSET_ANCHOR)).toThrow(/RFC 3339/)
    expect(() => threadTimelinePath('.')).toThrow(/thread id/i)
    expect(() => threadTimelinePath('..', ANCHOR)).toThrow(/thread id/i)
  })

  it('opens an anchored link at meetings detail with the served instant centred', async () => {
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(1362)
    mount(threadTimelinePath(ALPHA.threadId, ANCHOR))

    await waitForTierRequest('meetings', ALPHA.threadId)
    const view = viewOf()
    expect(view.tier).toBe('meetings')
    // 1362px root minus the timeline's 162px row-header gutter.
    expect(view.from + view.scale * 600).toBe(Date.parse(ANCHOR))

    const expectedFetch = fetchSpan(view, 1200)
    const surviving = timelineRequests('meetings', ALPHA.threadId).at(-1)
    expect(surviving).toBeDefined()
    const query = new URL(surviving ?? '', 'http://meetingminer.test').searchParams
    expect(query.get('from')).toBe(new Date(expectedFetch.from).toISOString())
    expect(query.get('to')).toBe(new Date(expectedFetch.to).toISOString())
  })

  it('preserves a numeric-offset anchor and centres its represented instant', async () => {
    const path = threadTimelinePath(ALPHA.threadId, OFFSET_ANCHOR)
    expect(new URL(path, 'http://meetingminer.test').searchParams.get('at')).toBe(OFFSET_ANCHOR)
    mount(path)

    await waitForTierRequest('meetings', ALPHA.threadId)
    expect(viewOf().from + viewOf().scale * 500).toBe(Date.parse(OFFSET_ANCHOR))
  })

  it('opens a bare link at the bands floor fitted to that thread, not the corpus', async () => {
    mount(threadTimelinePath(ALPHA.threadId))

    await waitForTierRequest('bands', ALPHA.threadId)
    const expected = fitView(
      { from: Date.parse(ALPHA.firstMentionAt), to: Date.parse(ALPHA.lastMentionAt) },
      1000,
      TIER_MIN_SCALE.bands,
    )
    expect(viewOf()).toEqual({ ...expected, tier: 'bands' })

    const expectedFetch = fetchSpan(expected, 1000)
    const surviving = vi
      .mocked(fetch)
      .mock.calls.map((call) => String(call[0]))
      .filter((url) => levelOf(url) === 'bands')
      .at(-1)
    expect(surviving).toBeDefined()
    const query = new URL(surviving ?? '', 'http://meetingminer.test').searchParams
    expect(query.get('from')).toBe(new Date(expectedFetch.from).toISOString())
    expect(query.get('to')).toBe(new Date(expectedFetch.to).toISOString())
  })

  it('reapplies the corresponding default when the route changes without a remount', async () => {
    const user = userEvent.setup()
    mount(threadTimelinePath(ALPHA.threadId), true)
    await waitForTierRequest('bands', ALPHA.threadId)

    await user.click(screen.getByRole('button', { name: 'anchored beta' }))
    await waitForTierRequest('meetings', BETA.threadId)
    expect(viewOf().from + viewOf().scale * 500).toBe(Date.parse(ANCHOR))

    await user.click(screen.getByRole('button', { name: 'bare alpha' }))
    const expected = fitView(
      { from: Date.parse(ALPHA.firstMentionAt), to: Date.parse(ALPHA.lastMentionAt) },
      1000,
      TIER_MIN_SCALE.bands,
    )
    await waitFor(() => expect(viewOf()).toEqual({ ...expected, tier: 'bands' }))
  })

  it('recentres when only the anchor changes on the same thread route', async () => {
    const user = userEvent.setup()
    mount(threadTimelinePath(ALPHA.threadId, ANCHOR), true)
    await waitForTierRequest('meetings', ALPHA.threadId)

    await user.click(screen.getByRole('button', { name: 'second alpha anchor' }))
    await waitFor(() =>
      expect(viewOf().from + viewOf().scale * 500).toBe(Date.parse(SECOND_ANCHOR)),
    )
  })

  it('replaces an in-flight request when a same-thread anchor change snaps to the same key', async () => {
    const firstMeetings = deferredResponse()
    const meetingSignals: Array<AbortSignal | null | undefined> = []
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (url.endsWith('/threads')) return Promise.resolve(response([ALPHA, BETA]))
        if (levelOf(url) === 'meetings') {
          meetingSignals.push(init?.signal)
          if (meetingSignals.length === 1) return firstMeetings.promise
          return Promise.resolve(response({ meetings: [] }))
        }
        return Promise.resolve(response({ buckets: [] }))
      }),
    )
    const user = userEvent.setup()
    mount(threadTimelinePath(ALPHA.threadId, ANCHOR), true)
    await waitFor(() => expect(timelineRequests('meetings', ALPHA.threadId)).toHaveLength(1))

    await user.click(screen.getByRole('button', { name: 'nearby alpha anchor' }))
    await waitFor(() => expect(timelineRequests('meetings', ALPHA.threadId)).toHaveLength(2))
    expect(meetingSignals[0]?.aborted).toBe(true)
    const expected = fitView(
      { from: Date.parse(NEARBY_ANCHOR), to: Date.parse(NEARBY_ANCHOR) },
      1000,
      TIER_MIN_SCALE.meetings,
    )
    const expectedFetch = fetchSpan(expected, 1000)
    const replacement = new URL(
      timelineRequests('meetings', ALPHA.threadId).at(-1) ?? '',
      'http://meetingminer.test',
    ).searchParams
    expect(replacement.get('from')).toBe(new Date(expectedFetch.from).toISOString())
    expect(replacement.get('to')).toBe(new Date(expectedFetch.to).toISOString())
    firstMeetings.resolve(response({ meetings: [] }))
  })

  it('refits an untouched anchored default when a zero-width fallback later measures', async () => {
    let rootWidth = 162
    let resize!: ResizeObserverCallback
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockImplementation(() => rootWidth)
    vi.stubGlobal(
      'ResizeObserver',
      class {
        constructor(callback: ResizeObserverCallback) {
          resize = callback
        }
        observe() {}
        disconnect() {}
      },
    )
    mount(threadTimelinePath(ALPHA.threadId, ANCHOR))
    await waitForTierRequest('meetings', ALPHA.threadId)
    expect(viewOf().from + viewOf().scale * 500).toBe(Date.parse(ANCHOR))

    rootWidth = 1362
    act(() => resize([], {} as ResizeObserver))
    await waitFor(() => expect(viewOf().from + viewOf().scale * 600).toBe(Date.parse(ANCHOR)))
    const expectedFetch = fetchSpan(viewOf(), 1200)
    await waitFor(() => {
      const surviving = new URL(
        timelineRequests('meetings', ALPHA.threadId).at(-1) ?? '',
        'http://meetingminer.test',
      ).searchParams
      expect(surviving.get('from')).toBe(new Date(expectedFetch.from).toISOString())
      expect(surviving.get('to')).toBe(new Date(expectedFetch.to).toISOString())
    })
  })

  it('does not refit a route default after the reader pans it', async () => {
    let rootWidth = 1162
    let resize!: ResizeObserverCallback
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockImplementation(() => rootWidth)
    vi.stubGlobal(
      'ResizeObserver',
      class {
        constructor(callback: ResizeObserverCallback) {
          resize = callback
        }
        observe() {}
        disconnect() {}
      },
    )
    const user = userEvent.setup()
    mount(threadTimelinePath(ALPHA.threadId, ANCHOR))
    await waitForTierRequest('meetings', ALPHA.threadId)
    await user.click(screen.getByRole('button', { name: 'Pan right (Shift+→)' }))
    const panned = viewOf()

    rootWidth = 1362
    act(() => resize([], {} as ResizeObserver))
    await waitFor(() => expect(viewOf()).toEqual(panned))
  })

  it('refuses a malformed at value by name instead of treating it as a bare link', async () => {
    mount(`/threads/${ALPHA.threadId}?at=last-week`)
    expect(await screen.findByRole('alert')).toHaveTextContent(/invalid `at`.*RFC 3339/i)
    expect(
      vi
        .mocked(fetch)
        .mock.calls.map((call) => String(call[0]))
        .some((url) => url.includes('/timeline?')),
    ).toBe(false)
  })

  it('refuses an RFC 3339 unknown-offset anchor before route work starts', async () => {
    mount(`/threads/${ALPHA.threadId}?at=${encodeURIComponent(UNKNOWN_OFFSET_ANCHOR)}`)
    expect(await screen.findByRole('alert')).toHaveTextContent(/invalid `at`.*RFC 3339/i)
    expect(fetch).not.toHaveBeenCalled()
  })

  it.each(['%2E', '%2E%2E'])('refuses the decoded dot-segment route id %s', async (threadId) => {
    mount(`/threads/${threadId}`)
    expect(await screen.findByRole('alert')).toHaveTextContent(/invalid thread id/i)
    expect(fetch).not.toHaveBeenCalled()
  })

  it('refuses duplicate at values and never starts route work', async () => {
    mount(`/threads/${ALPHA.threadId}?at=${encodeURIComponent(ANCHOR)}&at=${encodeURIComponent(SECOND_ANCHOR)}`)
    expect(await screen.findByRole('alert')).toHaveTextContent(/`at` must appear exactly once/i)
    expect(fetch).not.toHaveBeenCalled()
  })

  it('refuses a valid at value on the thread-list route', async () => {
    mount(`/threads?at=${encodeURIComponent(ANCHOR)}`)
    expect(await screen.findByRole('alert')).toHaveTextContent(/requires `\/threads\/:threadId`/i)
    expect(fetch).not.toHaveBeenCalled()
  })

  it('shows the route refusal before an api outage and issues no request', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new Error('fetch failed'))))
    mount(`/threads/${ALPHA.threadId}?at=last-week`)

    expect(await screen.findByRole('alert')).toHaveTextContent(/invalid `at`.*RFC 3339/i)
    expect(screen.queryByText(/Cannot reach the api/)).not.toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('cancels and ignores old list work across valid-invalid-valid navigation', async () => {
    const firstList = deferredResponse()
    const listSignals: Array<AbortSignal | null | undefined> = []
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (url.endsWith('/threads')) {
          listSignals.push(init?.signal)
          if (listSignals.length === 1) return firstList.promise
          return Promise.resolve(response([ALPHA, BETA]))
        }
        return Promise.resolve(response({ meetings: [] }))
      }),
    )
    const user = userEvent.setup()
    mount(threadTimelinePath(ALPHA.threadId, ANCHOR), true)
    await waitFor(() => expect(listSignals).toHaveLength(1))

    await user.click(screen.getByRole('button', { name: 'invalid alpha anchor' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/invalid `at`/i)
    expect(listSignals[0]?.aborted).toBe(true)

    await user.click(screen.getByRole('button', { name: 'anchored beta' }))
    await waitFor(() => expect(listSignals).toHaveLength(2))
    expect(await screen.findByText(BETA.name)).toBeInTheDocument()
    await act(async () => {
      firstList.resolve(response([ALPHA]))
      await Promise.resolve()
      await Promise.resolve()
    })
    expect(screen.getByText(BETA.name)).toBeInTheDocument()
    expect(screen.queryByText(/No thread has this id/)).not.toBeInTheDocument()
  })

  it('does not request timeline data for an unknown thread route', async () => {
    mount('/threads/thread-missing')
    expect(await screen.findByText(/No thread has this id/)).toBeInTheDocument()
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 180))
    })
    expect(timelineRequests('bands')).toHaveLength(0)
    expect(timelineRequests('meetings')).toHaveLength(0)
  })

  it('clears the prior thread tier refusal before replacement route work lands', async () => {
    const betaMeetings = deferredResponse()
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (url.endsWith('/threads')) return Promise.resolve(response([ALPHA, BETA]))
        if (url.includes(`/threads/${ALPHA.threadId}/timeline?`)) {
          return Promise.resolve({
            ok: false,
            status: 503,
            statusText: 'Unavailable',
            text: async () => JSON.stringify({ detail: 'alpha tier refused' }),
          } as Response)
        }
        if (url.includes(`/threads/${BETA.threadId}/timeline?`)) return betaMeetings.promise
        return Promise.resolve(response({ buckets: [] }))
      }),
    )
    const user = userEvent.setup()
    mount(threadTimelinePath(ALPHA.threadId, ANCHOR), true)
    expect(await screen.findByRole('alert')).toHaveTextContent(/alpha tier refused/i)

    await user.click(screen.getByRole('button', { name: 'anchored beta' }))
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
    await waitFor(() => expect(timelineRequests('meetings', BETA.threadId)).toHaveLength(1))
    betaMeetings.resolve(response({ meetings: [] }))
  })

  it('remeasures before applying a valid default after the canvas was absent', async () => {
    let rootWidth = 1162
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockImplementation(() => rootWidth)
    const user = userEvent.setup()
    mount(threadTimelinePath(ALPHA.threadId, ANCHOR), true)
    await waitForTierRequest('meetings', ALPHA.threadId)
    expect(viewOf().from + viewOf().scale * 500).toBe(Date.parse(ANCHOR))

    await user.click(screen.getByRole('button', { name: 'invalid alpha anchor' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/invalid `at`/i)

    rootWidth = 1362
    await user.click(screen.getByRole('button', { name: 'second alpha anchor' }))
    await waitFor(() =>
      expect(viewOf().from + viewOf().scale * 600).toBe(Date.parse(SECOND_ANCHOR)),
    )
  })
})
