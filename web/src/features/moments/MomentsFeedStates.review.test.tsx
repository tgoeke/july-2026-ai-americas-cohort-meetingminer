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

afterEach(() => vi.unstubAllGlobals())

describe('review F8 — honest initial, error, and empty states', () => {
  it('does not publish a false zero before ranking finishes', async () => {
    let release!: (response: Response) => void
    vi.stubGlobal(
      'fetch',
      vi.fn(
        () =>
          new Promise<Response>((resolve) => {
            release = resolve
          }),
      ),
    )
    renderFeed()

    expect(await screen.findByTestId('moments-loading')).toBeInTheDocument()
    expect(screen.queryByTestId('moments-count')).toBeNull()

    release(
      new Response(JSON.stringify({ items: [], total: 0, limit: 24, offset: 0 }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    expect(await screen.findByTestId('moments-empty')).toBeInTheDocument()
  })

  it('exposes the initial read failure as an alert', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new Error('fixture offline'))))
    renderFeed()

    expect(await screen.findByRole('alert')).toHaveTextContent('fixture offline')
  })

  it('offers the primary Add meeting recovery when the corpus is empty', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve(
          new Response(JSON.stringify({ items: [], total: 0, limit: 24, offset: 0 }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          }),
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
