import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useNavigate } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MomentsFeed } from './MomentsFeed'
import type { MomentFeedItem } from './feed'

function item(momentId: string, overrides: Partial<MomentFeedItem> = {}): MomentFeedItem {
  return {
    momentId,
    meetingId: `meeting-${momentId}`,
    meetingTitle: `Meeting ${momentId}`,
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
    reasons: [{ kind: 'recency', label: 'recently recorded', at: null }],
    ...overrides,
  }
}

function response(items: Array<MomentFeedItem>, total: number, offset = 0) {
  return new Response(JSON.stringify({ items, total, limit: 24, offset }), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

function RouteChange() {
  const navigate = useNavigate()
  return (
    <button type="button" onClick={() => navigate('/?kind=decision')}>
      Filter now
    </button>
  )
}

function renderFeed(withRouteChange = false) {
  return render(
    <MemoryRouter>
      {withRouteChange && <RouteChange />}
      <MomentsFeed
        onOpenMoment={() => undefined}
        onOpenMeeting={() => undefined}
        onOpenThread={() => undefined}
      />
    </MemoryRouter>,
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('review F7 — paging ownership and announcements', () => {
  it('moves focus to the first appended card and announces the new count', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const offset = Number(new URL(String(input)).searchParams.get('offset') ?? '0')
        return Promise.resolve(
          offset === 0
            ? response([item('moment-1')], 2)
            : response([item('moment-2')], 2, offset),
        )
      }),
    )
    renderFeed()

    await userEvent.click(await screen.findByTestId('moments-show-more'))

    const appendedTitle = await screen.findByTestId('moment-title-moment-2')
    await waitFor(() => expect(appendedTitle).toHaveFocus())
    expect(screen.getByRole('status')).toHaveTextContent('1 more moment — 2 of 2')
  })

  it('keeps every reason in the exact order supplied by the api', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve(
          response([
            item('moment-1', {
              threads: [{ threadId: 'thread-1', name: 'served thread', colorOrdinal: 1 }],
              reasons: [
                { kind: 'decision', label: 'decision first', ref: 'artifact-1' },
                { kind: 'risk', label: 'risk second' },
                { kind: 'thread', label: 'thread third', ref: 'thread-1' },
              ],
            }),
          ], 1),
        ),
      ),
    )
    renderFeed()

    const line = await screen.findByTestId('reason-line')
    expect([...line.children].map((node) => node.textContent)).toEqual([
      'decision first',
      'risk second',
      '#thread third',
    ])
  })

  it('discards a response superseded by a newer url filter', async () => {
    let releaseFirst!: (value: Response) => void
    const first = new Promise<Response>((resolve) => {
      releaseFirst = resolve
    })
    let calls = 0
    vi.stubGlobal(
      'fetch',
      vi.fn(() => {
        calls += 1
        return calls === 1
          ? first
          : Promise.resolve(response([item('newer', { reasons: [{ kind: 'decision', label: 'new' }] })], 1))
      }),
    )
    renderFeed(true)

    await userEvent.click(screen.getByRole('button', { name: 'Filter now' }))
    expect(await screen.findByTestId('moment-title-newer')).toBeInTheDocument()
    releaseFirst(response([item('older')], 1))

    await waitFor(() => expect(screen.queryByTestId('moment-title-older')).toBeNull())
    expect(screen.getByTestId('moment-title-newer')).toBeInTheDocument()
  })
})
