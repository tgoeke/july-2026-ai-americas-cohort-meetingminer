import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MomentsFeed } from './MomentsFeed'

afterEach(() => vi.unstubAllGlobals())

describe('review F14 — url filter visibility', () => {
  it('keeps an active thread visible before that thread appears in served items', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve(
          new Response(JSON.stringify({ items: [], total: 0, corpusTotal: 0, limit: 24, offset: 0 }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          }),
        ),
      ),
    )
    render(
      <MemoryRouter initialEntries={['/?thread=thread-9']}>
        <MomentsFeed
          onOpenMoment={() => undefined}
          onOpenMeeting={() => undefined}
          onOpenThread={() => undefined}
        />
      </MemoryRouter>,
    )

    const select = await screen.findByTestId<HTMLSelectElement>('filter-thread')
    expect(select).toHaveValue('thread-9')
    expect(screen.getByRole('option', { name: 'thread-9' })).toBeInTheDocument()
  })
})
