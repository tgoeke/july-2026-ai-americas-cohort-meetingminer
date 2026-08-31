import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MomentsFeed } from './MomentsFeed'
import type { MomentFeedItem } from './feed'

/**
 * The front door, against fixtures.
 *
 * `GET /moments/feed` is story 10.4, built in parallel, so every test here
 * serves the wire shape from that story's acceptance criteria rather than
 * waiting for the endpoint — which is also what proves the client reads the
 * agreed field names and nothing else.
 */

function item(overrides: Partial<MomentFeedItem> = {}): MomentFeedItem {
  return {
    momentId: 'moment-1',
    meetingId: 'meeting-1',
    meetingTitle: 'Retrieval bake-off review',
    startedAt: '2026-08-14T12:00:00Z',
    startedAtPrecision: 'second',
    startMs: 760_000,
    endMs: 845_000,
    corpus: 'real',
    hasRecording: true,
    sourceDeepLink: null,
    screenshotId: 'screenshot-1',
    viewType: 'slide',
    preview: 'BM25 stays first-class; hybrid only on paraphrase.',
    threads: [{ threadId: 'thread-1', name: 'retrieval split', colorOrdinal: 1 }],
    reasons: [
      {
        kind: 'decision',
        label: 'decision at 12:40',
        ref: 'artifact-1',
        at: '2026-08-14T12:40:00Z',
      },
    ],
    ...overrides,
  }
}

interface Page {
  items: Array<MomentFeedItem>
  total?: number
  corpusTotal?: number
}

/** Serve the feed, one page per `offset` the component asks for. Any other
 * address reads as unreachable — nothing else on this screen fetches. */
function serveFeed(pages: (offset: number) => Page) {
  const calls: Array<URL> = []
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url = new URL(input instanceof Request ? input.url : String(input))
    if (url.pathname.endsWith('/threads')) {
      return Promise.resolve(
        new Response(
          JSON.stringify({
            threads: [
              {
                threadId: 'thread-1',
                name: 'retrieval split',
                mentionCount: 3,
                meetingCount: 2,
                firstMentionAt: '2026-08-01T12:00:00Z',
                lastMentionAt: '2026-08-31T12:00:00Z',
                colorOrdinal: 1,
              },
            ],
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      )
    }
    if (!url.pathname.endsWith('/moments/feed')) {
      return Promise.reject(new Error('no api in this test'))
    }
    calls.push(url)
    const offset = Number(url.searchParams.get('offset') ?? '0')
    const page = pages(offset)
    return Promise.resolve(
      new Response(
        JSON.stringify({
          items: page.items,
          total: page.total ?? page.items.length,
          corpusTotal: page.corpusTotal ?? page.total ?? page.items.length,
          limit: Number(url.searchParams.get('limit') ?? '24'),
          offset,
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )
  })
  vi.stubGlobal('fetch', fetchMock)
  return calls
}

const noop = () => {}

function renderFeed(
  props: Partial<Parameters<typeof MomentsFeed>[0]> = {},
  initialEntry = '/',
) {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <MomentsFeed
        onOpenMoment={props.onOpenMoment ?? noop}
        onOpenMeeting={props.onOpenMeeting ?? noop}
        onOpenThread={props.onOpenThread ?? noop}
      />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.unstubAllGlobals()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('MomentsFeed', () => {
  it('says it is ranking rather than showing skeleton cards', async () => {
    let release!: () => void
    const held = new Promise<void>((resolve) => {
      release = resolve
    })
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        await held
        return new Response(JSON.stringify({ items: [], total: 0, corpusTotal: 0, limit: 24, offset: 0 }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }),
    )
    renderFeed()

    expect(await screen.findByTestId('moments-loading')).toHaveTextContent('Ranking the corpus…')
    // A skeleton is an invented card; there is not one.
    expect(screen.queryByTestId('moment-card-moment-1')).toBeNull()
    release()
    await screen.findByTestId('moments-empty')
  })

  it('renders a ranked card from served fields alone', async () => {
    serveFeed(() => ({ items: [item()], total: 24 }))
    renderFeed()

    const card = await screen.findByTestId('moment-card-moment-1')
    // Header count is the api's total, not the page length.
    expect(screen.getByTestId('moments-count')).toHaveTextContent('24')
    // Meeting, date, offsets and corpus — the served meta line.
    expect(within(card).getByText('2026-08-14 · 12:40–14:05 · real')).toBeInTheDocument()
    expect(within(card).getByTestId('moment-title-moment-1')).toHaveTextContent(
      'Retrieval bake-off review',
    )
    // The screenshot is id-addressed and carries its alt.
    const shot = within(card).getByAltText('slide at 12:40, Retrieval bake-off review')
    expect(shot).toHaveAttribute('src', 'http://localhost:8000/media/files/screenshot-1')
    // The offset chip over the frame.
    expect(within(card).getByText('slide · 12:40')).toBeInTheDocument()
    // The excerpt, quoted.
    expect(card).toHaveTextContent('BM25 stays first-class; hybrid only on paraphrase.')
  })

  it('renders the reason line in api order, labels verbatim', async () => {
    serveFeed(() => ({
      items: [
        item({
          reasons: [
            { kind: 'decision', label: 'decision at 12:40', ref: 'a1' },
            { kind: 'action-item', label: '2 action items · due 2026-09-04', ref: 'a2' },
            { kind: 'risk', label: 'risk raised at 13:02' },
            { kind: 'thread', label: 'retrieval split', ref: 'thread-1' },
          ],
        }),
      ],
    }))
    renderFeed()

    const line = await screen.findByTestId('reason-line')
    // Order is the api's order.
    expect(line.textContent).toContain('decision at 12:40')
    // The seven artifact kinds are chips, each with its glyph.
    expect(within(line).getByTestId('kind-glyph-decision')).toBeInTheDocument()
    expect(within(line).getByTestId('kind-glyph-action-item')).toBeInTheDocument()
    // `risk` is a ranking signal, never a publishable kind: plain text, no chip.
    expect(within(line).getByTestId('reason-text')).toHaveTextContent('risk raised at 13:02')
    expect(within(line).queryByTestId('reason-kind-risk')).toBeNull()
    // The thread reason resolves to the item's thread and carries its name.
    expect(within(line).getByRole('button', { name: 'thread retrieval split' })).toBeInTheDocument()
  })

  it('replays in place, one card at a time, and Esc closes it', async () => {
    serveFeed(() => ({
      items: [item(), item({ momentId: 'moment-2', meetingId: 'meeting-2' })],
    }))
    renderFeed()

    const first = await screen.findByTestId('replay-moment-1')
    expect(screen.queryByTestId('replay-player')).toBeNull()

    await userEvent.click(first)
    expect(first).toHaveAttribute('aria-expanded', 'true')
    const player = screen.getByTestId('replay-player')
    expect(player).toHaveAttribute('src', 'http://localhost:8000/media/recordings/meeting-1')
    // The player opens inside the card, not on a new screen.
    expect(screen.getByTestId('moment-card-moment-1')).toContainElement(player)

    // At most one player on the grid: opening another closes the first.
    await userEvent.click(screen.getByTestId('replay-moment-2'))
    expect(screen.getAllByTestId('replay-player')).toHaveLength(1)
    expect(first).toHaveAttribute('aria-expanded', 'false')

    await userEvent.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByTestId('replay-player')).toBeNull())
    expect(screen.getByTestId('replay-moment-2')).toHaveFocus()
  })

  it('links each card to its moment and its meeting', async () => {
    const onOpenMoment = vi.fn()
    const onOpenMeeting = vi.fn()
    serveFeed(() => ({ items: [item()] }))
    renderFeed({ onOpenMoment, onOpenMeeting })

    await userEvent.click(await screen.findByTestId('open-moment-moment-1'))
    expect(onOpenMoment).toHaveBeenCalledWith('moment-1')

    await userEvent.click(screen.getByTestId('open-meeting-moment-1'))
    expect(onOpenMeeting).toHaveBeenCalledWith('meeting-1')

    // The title is the same link as Open moment.
    await userEvent.click(screen.getByTestId('moment-title-moment-1'))
    expect(onOpenMoment).toHaveBeenCalledTimes(2)
  })

  it('offers the YouTube link beside replay, timed at the moment', async () => {
    serveFeed(() => ({
      items: [item({ sourceDeepLink: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ' })],
    }))
    renderFeed()

    const link = await screen.findByRole('link', { name: /Open on YouTube at 12:40/ })
    expect(link).toHaveAttribute('href', 'https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=760')
    // Replay stays the primary affordance.
    expect(screen.getByTestId('replay-moment-1')).toBeInTheDocument()
  })

  it('states absence rather than offering a dead button', async () => {
    serveFeed(() => ({
      items: [
        item({ hasRecording: false, sourceDeepLink: null, screenshotId: null }),
      ],
    }))
    renderFeed()

    const card = await screen.findByTestId('moment-card-moment-1')
    expect(within(card).queryByTestId('replay-moment-1')).toBeNull()
    expect(card).toHaveTextContent('Transcript only — no recording and no source link.')
    expect(card).toHaveTextContent('No screenshot — transcript-anchored moment.')
    // The moment is still reachable.
    expect(within(card).getByTestId('open-moment-moment-1')).toBeInTheDocument()
  })

  it('filters by corpus, thread and kind through the url', async () => {
    const calls = serveFeed(() => ({ items: [item()], total: 24 }))
    renderFeed()
    await screen.findByTestId('moment-card-moment-1')

    await userEvent.selectOptions(screen.getByTestId('filter-corpus'), 'scripted')
    await waitFor(() => expect(calls.at(-1)?.searchParams.get('corpus')).toBe('scripted'))

    await userEvent.selectOptions(screen.getByTestId('filter-kind'), 'decision')
    await waitFor(() => expect(calls.at(-1)?.searchParams.get('kind')).toBe('decision'))

    // The thread option comes from the complete thread catalog, not this page.
    await userEvent.selectOptions(screen.getByTestId('filter-thread'), 'thread-1')
    await waitFor(() => expect(calls.at(-1)?.searchParams.get('thread')).toBe('thread-1'))
  })

  it('filters the feed from a kind chip on a card', async () => {
    const calls = serveFeed(() => ({ items: [item()], total: 24 }))
    renderFeed()

    await userEvent.click(await screen.findByRole('button', { name: 'Filter by kind decision' }))
    await waitFor(() => expect(calls.at(-1)?.searchParams.get('kind')).toBe('decision'))
  })

  it('opens the thread a chip names', async () => {
    const onOpenThread = vi.fn()
    serveFeed(() => ({ items: [item()] }))
    renderFeed({ onOpenThread })

    await userEvent.click(await screen.findByRole('button', { name: 'thread retrieval split' }))
    expect(onOpenThread).toHaveBeenCalledWith('thread-1')
  })

  it('names the active filters when nothing matches, and clears them', async () => {
    serveFeed(() => ({ items: [], total: 0, corpusTotal: 24 }))
    renderFeed({}, '/?corpus=real&kind=decision')

    expect(await screen.findByTestId('moments-empty')).toHaveTextContent(
      'No moments match corpus real · kind decision.',
    )
    // Filtered, so the header states both numbers.
    expect(screen.getByTestId('moments-count')).toHaveTextContent('0 of 24')

    await userEvent.click(screen.getByRole('button', { name: 'Clear filters' }))
    await waitFor(() =>
      expect(screen.getByTestId('moments-empty')).toHaveTextContent(
        'No moments yet. Add a meeting — Moments fills once one is ingested.',
      ),
    )
  })

  it('pages with an explicit button, never infinite scroll', async () => {
    serveFeed((offset) =>
      offset === 0
        ? { items: [item()], total: 2 }
        : { items: [item({ momentId: 'moment-2' })], total: 2 },
    )
    renderFeed()

    const more = await screen.findByTestId('moments-show-more')
    expect(more).toHaveTextContent('Show 1 more')

    await userEvent.click(more)
    expect(await screen.findByTestId('moment-card-moment-2')).toBeInTheDocument()
    // The first page is kept, not replaced.
    expect(screen.getByTestId('moment-card-moment-1')).toBeInTheDocument()
    // Hidden once every item up to `total` is shown.
    await waitFor(() => expect(screen.queryByTestId('moments-show-more')).toBeNull())
  })

  it('names the api address when the feed cannot be reached, and retries', async () => {
    let feedAttempt = 0
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = new URL(input instanceof Request ? input.url : String(input))
      if (url.pathname.endsWith('/threads')) {
        return Promise.resolve(new Response(JSON.stringify({ threads: [] })))
      }
      feedAttempt += 1
      if (feedAttempt === 1) return Promise.reject(new Error('fetch failed'))
      return Promise.resolve(
        new Response(JSON.stringify({ items: [item()], total: 1, corpusTotal: 1, limit: 24, offset: 0 }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
    })
    vi.stubGlobal('fetch', fetchMock)
    renderFeed()

    const error = await screen.findByTestId('moments-error')
    expect(error).toHaveTextContent('Cannot reach the api at http://localhost:8000: fetch failed.')

    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByTestId('moment-card-moment-1')).toBeInTheDocument()
  })

  it('refuses a page whose item carries no reason rather than miscounting', async () => {
    serveFeed(() => ({ items: [item({ reasons: [] })], total: 1 }))
    renderFeed()

    // One page-level error, not a card rendered without the thing that
    // justifies its rank.
    expect(await screen.findByTestId('moments-error')).toHaveTextContent(
      'reasons[] must be non-empty',
    )
    expect(screen.queryByTestId('moment-card-moment-1')).toBeNull()
  })
})
