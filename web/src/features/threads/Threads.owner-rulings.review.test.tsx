import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { Threads } from './Threads'
import { threadTimelinePath } from './threadTimelinePath'
import { fitView, TIER_MIN_SCALE } from './timeline'

const ANCHOR = '2026-05-13T15:04:12Z'
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

  it('opens an anchored link at meetings detail with the served instant centred', async () => {
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(1362)
    mount(threadTimelinePath(ALPHA.threadId, ANCHOR))

    await waitForTierRequest('meetings', ALPHA.threadId)
    const view = viewOf()
    expect(view.tier).toBe('meetings')
    // 1362px root minus the timeline's 162px row-header gutter.
    expect(view.from + view.scale * 600).toBe(Date.parse(ANCHOR))
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
})
