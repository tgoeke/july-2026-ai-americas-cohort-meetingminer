import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BrowserRouter, useLocation, useNavigate } from 'react-router'
import { MomentsFeed } from './MomentsFeed'

function item(momentId: string) {
  return {
    momentId,
    meetingId: `meeting-${momentId}`,
    meetingTitle: momentId,
    startedAt: '2026-08-31T12:00:00Z',
    startedAtPrecision: 'second',
    startMs: 1_000,
    endMs: 2_000,
    corpus: 'real',
    hasRecording: false,
    sourceDeepLink: null,
    screenshotId: null,
    viewType: null,
    preview: null,
    threads: [],
    reasons: [{ kind: 'recency', label: 'recent meeting', ref: null, at: null }],
  }
}

function response(items: Array<ReturnType<typeof item>>, total: number, offset = 0) {
  return new Response(JSON.stringify({ items, total, unfilteredTotal: total, limit: 24, offset }), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

function Harness() {
  const location = useLocation()
  const navigate = useNavigate()
  return (
    <>
      <button type="button" onClick={() => navigate('/moments/moment-1')}>
        Open child
      </button>
      <MomentsFeed
        active={location.pathname === '/'}
        onOpenMoment={() => undefined}
        onOpenMeeting={() => undefined}
        onOpenThread={() => undefined}
      />
    </>
  )
}

function renderFeed(path = '/') {
  window.history.replaceState(null, '', path)
  return render(
    <BrowserRouter>
      <Harness />
    </BrowserRouter>,
  )
}

beforeEach(() => {
  window.history.replaceState(null, '', '/')
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('review F4 — a mounted feed owns its visible page', () => {
  it('does not reload or lose paging when a child route hides it', async () => {
    const feedCalls: Array<URL> = []
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = new URL(String(input))
      if (url.pathname.endsWith('/threads')) {
        return Promise.resolve(new Response(JSON.stringify({ threads: [] })))
      }
      feedCalls.push(url)
      const offset = Number(url.searchParams.get('offset'))
      return Promise.resolve(offset === 0 ? response([item('one')], 2) : response([item('two')], 2, 1))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderFeed('/?corpus=real')

    await userEvent.click(await screen.findByRole('button', { name: 'Show 1 more' }))
    expect(await screen.findByTestId('moment-card-two')).toBeInTheDocument()
    expect(feedCalls).toHaveLength(2)

    await userEvent.click(screen.getByRole('button', { name: 'Open child' }))
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(feedCalls).toHaveLength(2)
    expect(screen.getByTestId('moment-card-two')).toBeInTheDocument()
  })

  it('keeps the accumulated page and retries the failed offset', async () => {
    const feedCalls: Array<URL> = []
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = new URL(String(input))
      if (url.pathname.endsWith('/threads')) {
        return Promise.resolve(new Response(JSON.stringify({ threads: [] })))
      }
      feedCalls.push(url)
      if (feedCalls.length === 1) return Promise.resolve(response([item('one')], 2))
      if (feedCalls.length === 2) return Promise.reject(new Error('second page failed'))
      return Promise.resolve(response([item('two')], 2, 1))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderFeed()

    await userEvent.click(await screen.findByRole('button', { name: 'Show 1 more' }))
    expect(await screen.findByTestId('moments-error')).toHaveTextContent('second page failed')
    expect(screen.getByTestId('moment-card-one')).toBeInTheDocument()
    expect(screen.getByTestId('moments-count')).toHaveTextContent('2')

    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByTestId('moment-card-two')).toBeInTheDocument()
    expect(feedCalls[2]?.searchParams.get('offset')).toBe('1')
  })

  it('keeps the previous cards stale when a filter refresh fails', async () => {
    const feedCalls: Array<URL> = []
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = new URL(String(input))
      if (url.pathname.endsWith('/threads')) {
        return Promise.resolve(new Response(JSON.stringify({ threads: [] })))
      }
      feedCalls.push(url)
      return feedCalls.length === 1
        ? Promise.resolve(response([item('one')], 1))
        : Promise.reject(new Error('filtered read failed'))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderFeed()
    await screen.findByTestId('moment-card-one')

    await userEvent.selectOptions(screen.getByTestId('filter-corpus'), 'scripted')
    expect(await screen.findByTestId('moments-error')).toHaveTextContent(
      'The cards below may be stale.',
    )
    expect(screen.getByTestId('moment-card-one')).toBeInTheDocument()
    await waitFor(() => expect(feedCalls).toHaveLength(2))
  })
})
