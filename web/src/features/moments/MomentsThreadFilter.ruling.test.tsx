import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MomentsFeed } from './MomentsFeed'

const thread = (threadId: string, name: string) => ({
  threadId,
  name,
  mentionCount: 4,
  meetingCount: 2,
  firstMentionAt: '2026-08-01T12:00:00Z',
  lastMentionAt: '2026-08-31T12:00:00Z',
  colorOrdinal: 1,
})

afterEach(() => vi.unstubAllGlobals())

describe('F11 owner ruling: complete searchable thread source', () => {
  it('selects an off-page thread from GET /threads and filters by its id', async () => {
    const feedCalls: Array<URL> = []
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = new URL(String(input))
      if (url.pathname.endsWith('/threads')) {
        return Promise.resolve(new Response(JSON.stringify({
          threads: [thread('thread-page', 'Visible on page'), thread('thread-off-page', 'Launch readiness')],
        })))
      }
      feedCalls.push(url)
      return Promise.resolve(new Response(JSON.stringify({
        items: [],
        total: 0,
        unfilteredTotal: 24,
        limit: 24,
        offset: 0,
      })))
    }))

    render(
      <MemoryRouter>
        <MomentsFeed onOpenMoment={() => {}} onOpenMeeting={() => {}} onOpenThread={() => {}} />
      </MemoryRouter>,
    )

    await userEvent.type(await screen.findByTestId('filter-thread-search'), 'launch')
    await waitFor(() => expect(screen.getByTestId('filter-thread')).toHaveTextContent('Launch readiness'))
    await userEvent.selectOptions(screen.getByTestId('filter-thread'), 'thread-off-page')
    await waitFor(() => expect(feedCalls.at(-1)?.searchParams.get('thread')).toBe('thread-off-page'))
    await userEvent.clear(screen.getByTestId('filter-thread-search'))
    await userEvent.type(screen.getByTestId('filter-thread-search'), 'does not match')
    expect(screen.getByTestId('filter-thread')).toHaveDisplayValue('Launch readiness')
  })

  it('announces catalog failure, retains a deep link, and retries', async () => {
    let threadAttempt = 0
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = new URL(String(input))
      if (url.pathname.endsWith('/threads')) {
        threadAttempt += 1
        return threadAttempt === 1
          ? Promise.reject(new Error('catalog offline'))
          : Promise.resolve(new Response(JSON.stringify({
              threads: [thread('thread-deep', 'Deep-linked launch')],
            })))
      }
      return Promise.resolve(new Response(JSON.stringify({
        items: [], total: 0, unfilteredTotal: 24, limit: 24, offset: 0,
      })))
    }))

    render(
      <MemoryRouter initialEntries={['/?thread=thread-deep']}>
        <MomentsFeed onOpenMoment={() => {}} onOpenMeeting={() => {}} onOpenThread={() => {}} />
      </MemoryRouter>,
    )

    expect(await screen.findByRole('status', { name: 'Thread catalog unavailable' })).toHaveTextContent(
      'unavailable',
    )
    expect(screen.getByTestId('filter-thread')).toHaveValue('thread-deep')
    await userEvent.click(screen.getByRole('button', { name: 'Retry thread catalog' }))
    await waitFor(() => expect(screen.getByTestId('filter-thread')).toHaveDisplayValue('Deep-linked launch'))
  })
})
