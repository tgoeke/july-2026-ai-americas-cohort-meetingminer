import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MomentsFeed } from './MomentsFeed'

function renderFeed() {
  return render(
    <MemoryRouter>
      <MomentsFeed
        onOpenMoment={() => undefined}
        onOpenMeeting={() => undefined}
        onOpenThread={() => undefined}
      />
    </MemoryRouter>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('review F8 — honest initial, error, and empty states', () => {
  it('does not publish a false zero before ranking finishes', async () => {
    let release!: (response: Response) => void
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        if (new URL(input instanceof Request ? input.url : String(input)).pathname.endsWith('/threads')) {
          return Promise.resolve(new Response(JSON.stringify({ threads: [] })))
        }
        return new Promise<Response>((resolve) => {
          release = resolve
        })
      }),
    )
    renderFeed()

    expect(await screen.findByTestId('moments-loading')).toBeInTheDocument()
    expect(screen.queryByTestId('moments-count')).toBeNull()

    release(
      new Response(JSON.stringify({ items: [], total: 0, corpusTotal: 0, limit: 24, offset: 0 }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    expect(await screen.findByTestId('moments-empty')).toBeInTheDocument()
  })

  it('exposes the initial read failure as an alert', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) =>
        new URL(input instanceof Request ? input.url : String(input)).pathname.endsWith('/threads')
          ? Promise.resolve(new Response(JSON.stringify({ threads: [] })))
          : Promise.reject(new Error('fixture offline')),
      ),
    )
    renderFeed()

    expect(await screen.findByRole('alert')).toHaveTextContent('fixture offline')
  })

  it('preserves the api problem sentence when the generated operation is refused', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) =>
        Promise.resolve(
          new URL(input instanceof Request ? input.url : String(input)).pathname.endsWith('/threads')
            ? new Response(JSON.stringify({ threads: [] }))
            : new Response(
                JSON.stringify({ title: 'Invalid request', detail: 'corpus is unknown' }),
                {
                  status: 422,
                  headers: { 'Content-Type': 'application/problem+json' },
                },
              ),
        ),
      ),
    )
    renderFeed()

    expect(await screen.findByTestId('moments-error')).toHaveTextContent(
      'Invalid request: corpus is unknown',
    )
  })

  it('names the feed timeout instead of exposing the generated abort error', async () => {
    vi.spyOn(AbortSignal, 'timeout').mockReturnValue(AbortSignal.abort())
    vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new Error('aborted'))))
    renderFeed()

    expect(await screen.findByTestId('moments-error')).toHaveTextContent('timed out after 8000ms')
  })

  it('offers the primary Add meeting recovery when the corpus is empty', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) =>
        Promise.resolve(
          new URL(input instanceof Request ? input.url : String(input)).pathname.endsWith('/threads')
            ? new Response(JSON.stringify({ threads: [] }))
            : new Response(
                JSON.stringify({
                  items: [],
                  total: 0,
                  corpusTotal: 0,
                  limit: 24,
                  offset: 0,
                }),
                { status: 200, headers: { 'Content-Type': 'application/json' } },
              ),
        ),
      ),
    )
    renderFeed()

    expect(await screen.findByRole('link', { name: 'Add meeting' })).toHaveAttribute(
      'href',
      '/add',
    )
  })
})
