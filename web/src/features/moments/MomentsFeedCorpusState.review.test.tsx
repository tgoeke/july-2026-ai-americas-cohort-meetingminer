import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MomentsFeed } from './MomentsFeed'

const item = {
  momentId: 'moment-1',
  meetingId: 'meeting-1',
  meetingTitle: 'Corpus contract review',
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
  reasons: [{ kind: 'decision', label: 'decision at 0:01', ref: null, at: null }],
}

const response = (body: unknown) => new Response(JSON.stringify(body), {
  status: 200,
  headers: { 'Content-Type': 'application/json' },
})

function renderFeed(initialEntry: string) {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <MomentsFeed
        onOpenMoment={() => undefined}
        onOpenMeeting={() => undefined}
        onOpenThread={() => undefined}
      />
    </MemoryRouter>,
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('C2/C6 corpus-scoped feed state', () => {
  it('retains a distinct corpus denominator when a filtered refresh fails', async () => {
    let feedAttempt = 0
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = new URL(input instanceof Request ? input.url : String(input))
      if (url.pathname.endsWith('/threads')) {
        return Promise.resolve(response({ threads: [] }))
      }
      feedAttempt += 1
      return feedAttempt === 1
        ? Promise.resolve(response({
            items: [item],
            total: 1,
            corpusTotal: 24,
            limit: 24,
            offset: 0,
          }))
        : Promise.reject(new Error('refresh failed'))
    }))
    renderFeed('/?kind=decision')

    expect(await screen.findByTestId('moments-count')).toHaveTextContent('1 of 24')
    await userEvent.selectOptions(screen.getByTestId('filter-corpus'), 'scripted')

    expect(await screen.findByTestId('moments-error')).toHaveTextContent('refresh failed')
    expect(screen.getByTestId('moments-count')).toHaveTextContent('1 of 24')
  })

  it('rejects an invalid URL-derived corpus before the generated request', async () => {
    const feedRequests: Array<URL> = []
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = new URL(input instanceof Request ? input.url : String(input))
      if (url.pathname.endsWith('/threads')) {
        return Promise.resolve(response({ threads: [] }))
      }
      feedRequests.push(url)
      return Promise.resolve(response({
        items: [],
        total: 0,
        corpusTotal: 0,
        limit: 24,
        offset: 0,
      }))
    }))
    renderFeed('/?corpus=unknown')

    expect(await screen.findByTestId('moments-error')).toHaveTextContent(
      'corpus must be real or scripted',
    )
    await waitFor(() => expect(feedRequests).toHaveLength(0))
  })
})
