import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { SearchHit, SearchResponse } from '@/client/types.gen'
import { CorpusSearch } from './CorpusSearch'
import {
  affordanceOf,
  artifactBadge,
  DEBOUNCE_MS,
  hitKey,
  hitLabel,
  offsetLabel,
  problemMessage,
  safeHref,
  SEARCH_TIMEOUT_MS,
  snippetText,
} from './hits'

const sdk = vi.hoisted(() => ({ searchCorpus: vi.fn() }))

vi.mock('@/client/sdk.gen', () => ({
  getMeetingDrilldown: vi.fn(),
  searchCorpus: sdk.searchCorpus,
  getHealth: vi.fn(),
  listMeetings: vi.fn(),
  listMeetingMoments: vi.fn(),
  getMoment: vi.fn(),
  streamJobEvents: vi.fn(),
  getJob: vi.fn(),
  createIngest: vi.fn(),
  getRecording: vi.fn(),
  getMediaFile: vi.fn(),
  listParticipants: vi.fn(),
  renameParticipant: vi.fn(),
  mergeParticipants: vi.fn(),
}))

function hit(overrides: Partial<SearchHit> = {}): SearchHit {
  return {
    momentId: 'moment-1',
    meetingId: 'meeting-1',
    meetingTitle: 'Data Hub Demo',
    startMs: 44_000,
    endMs: 46_000,
    startedAt: '2026-08-05T12:00:19Z',
    startedAtPrecision: 'second',
    screenshotId: 'screenshot-1',
    sourceDeepLink: null,
    hasRecording: true,
    corpus: 'real',
    snippet: [
      { text: 'And the ', highlighted: false },
      { text: 'purchase', highlighted: true },
      { text: ' ', highlighted: false },
      { text: 'order', highlighted: true },
      { text: ' still needs approval.', highlighted: false },
    ],
    score: 0.99,
    ...overrides,
  }
}

function response(overrides: Partial<SearchResponse> = {}): SearchResponse {
  return {
    query: 'purchase order',
    ranking: 'hybrid',
    hits: [hit()],
    estimatedTotal: 1,
    limit: 20,
    offset: 0,
    indexMissing: false,
    ...overrides,
  }
}

function answers(body: SearchResponse) {
  sdk.searchCorpus.mockResolvedValue({ data: body, error: undefined })
}

/** A promise plus the handle to settle it, so a test decides when a call returns. */
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((r) => {
    resolve = r
  })
  return { promise, resolve }
}

async function type(term: string) {
  const user = userEvent.setup()
  await user.type(screen.getByTestId('search-input'), term)
  return user
}

beforeEach(() => {
  sdk.searchCorpus.mockReset()
})

describe('CorpusSearch', () => {
  it('prompts rather than searching while the box is empty', async () => {
    render(<CorpusSearch />)
    expect(screen.getByTestId('search-prompt')).toBeInTheDocument()
    // A blank query is a 422 from the api. Never asking is better than
    // rendering that refusal as if the user had done something wrong.
    await waitFor(() => expect(sdk.searchCorpus).not.toHaveBeenCalled())
  })

  it('shows a loading state, then the results', async () => {
    const pending = deferred<{ data: SearchResponse; error: undefined }>()
    sdk.searchCorpus.mockReturnValue(pending.promise)

    render(<CorpusSearch />)
    await type('purchase order')

    expect(await screen.findByTestId('search-loading')).toBeInTheDocument()
    pending.resolve({ data: response(), error: undefined })
    expect(await screen.findByTestId('hit-moment-1')).toBeInTheDocument()
    expect(screen.queryByTestId('search-loading')).toBeNull()
  })

  it('passes the typed term to the api once, after the debounce', async () => {
    answers(response())
    render(<CorpusSearch />)
    await type('purchase order')

    await waitFor(() => expect(sdk.searchCorpus).toHaveBeenCalled())
    // Fourteen keystrokes, one search. `toBeLessThan(14)` passed at thirteen,
    // which is to say it passed with the debounce removed.
    expect(sdk.searchCorpus).toHaveBeenCalledTimes(1)
    expect(sdk.searchCorpus.mock.calls[0][0].query.q).toBe('purchase order')
  })

  it('renders highlighted runs as <mark> from the data, never from markup', async () => {
    answers(response())
    render(<CorpusSearch />)
    await type('purchase order')

    const snippet = await screen.findByTestId('hit-snippet-moment-1')
    const marks = within(snippet).getAllByText(/purchase|order/, {
      selector: 'mark',
    })
    expect(marks.map((mark) => mark.textContent)).toEqual(['purchase', 'order'])
    // The whole snippet reads as the api's plain text — no tags leaked in.
    expect(snippet).toHaveTextContent('And the purchase order still needs approval.')
    expect(snippet.innerHTML).not.toContain('&lt;')
  })

  it('names the api address when a search cannot be reached', async () => {
    sdk.searchCorpus.mockRejectedValue(new Error('connection refused'))
    render(<CorpusSearch />)
    await type('purchase order')

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('http://localhost:8000')
    expect(alert).toHaveTextContent('connection refused')
  })

  it('does not leave a first failed search wedged on "Searching…"', async () => {
    sdk.searchCorpus.mockRejectedValue(new Error('connection refused'))
    render(<CorpusSearch />)
    await type('purchase order')

    await screen.findByRole('alert')
    // `rows` stayed null before this fix, so the banner and a permanent
    // loading line rendered together and the panel never recovered.
    expect(screen.queryByTestId('search-loading')).toBeNull()
    // And no "no moments match" either: the api never gave that answer.
    expect(screen.queryByTestId('search-empty')).toBeNull()
  })

  it('reads back an api refusal instead of blaming the connection', async () => {
    // A 503 the api answered with. It is reachable — saying otherwise sends
    // the reader to restart the wrong process — and the RFC 9457 body was
    // written for a person, so it is shown rather than stringified.
    sdk.searchCorpus.mockResolvedValue({
      data: undefined,
      error: {
        type: 'urn:meetingminer:problem:embedder-unusable',
        title: 'Service Unavailable',
        status: 503,
        detail: "the configured embedder 'qwen3-embedding:0.6b' at 1024"
          + ' dimensions could not embed the query: wrong width',
      },
    })
    render(<CorpusSearch />)
    await type('purchase order')

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('http://localhost:8000')
    expect(alert).toHaveTextContent('Service Unavailable')
    expect(alert).toHaveTextContent('could not embed the query')
    expect(alert).not.toHaveTextContent('Cannot reach the api')
    // Raw JSON is not a message.
    expect(alert.textContent).not.toContain('urn:meetingminer:problem')
    expect(alert.textContent).not.toContain('{')
  })

  it('still says something when the api refuses with no readable body', async () => {
    sdk.searchCorpus.mockResolvedValue({ data: undefined, error: 'Gateway Timeout' })
    render(<CorpusSearch />)
    await type('purchase order')

    expect(await screen.findByRole('alert')).toHaveTextContent('Gateway Timeout')
  })

  it('still reports an unreadable circular refusal', async () => {
    const circular: { self?: unknown } = {}
    circular.self = circular
    sdk.searchCorpus.mockResolvedValue({ data: undefined, error: circular })
    render(<CorpusSearch />)
    await type('purchase order')

    expect(await screen.findByRole('alert')).toHaveTextContent('an unknown error')
  })

  it('names the timeout when the api accepts the request and never answers', async () => {
    // shouldAdvanceTime: testing-library's `waitFor` polls on a timer it does
    // not know is faked.
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      // A request that hangs rather than failing: only the component's own
      // expiry timer ends it, and only `AbortSignal.any` delivers that to the
      // fetch.
      sdk.searchCorpus.mockImplementation(
        ({ signal }: { signal: AbortSignal }) =>
          new Promise((_resolve, reject) => {
            signal.addEventListener('abort', () => reject(signal.reason))
          }),
      )
      render(<CorpusSearch />)
      // fireEvent rather than userEvent: the debounce is one of the timers
      // this test is driving, and typing character by character under fake
      // timers would drive it too.
      fireEvent.change(screen.getByTestId('search-input'), {
        target: { value: 'purchase order' },
      })
      await act(async () => {
        await vi.advanceTimersByTimeAsync(DEBOUNCE_MS + 10)
      })
      await waitFor(() => expect(sdk.searchCorpus).toHaveBeenCalled())

      await act(async () => {
        await vi.advanceTimersByTimeAsync(SEARCH_TIMEOUT_MS + 100)
      })

      const alert = await screen.findByRole('alert')
      expect(alert).toHaveTextContent(`timed out after ${SEARCH_TIMEOUT_MS}ms`)
    } finally {
      vi.useRealTimers()
    }
  })

  it('never lets a superseded search overwrite a newer result', async () => {
    // The same race App.test.tsx pins for the health check (story 1.10,
    // finding 22): the first search resolves *after* the second, and its
    // answer must be discarded because its controller was aborted.
    const first = deferred<{ data: SearchResponse; error: undefined }>()
    sdk.searchCorpus.mockImplementationOnce(() => first.promise)
    sdk.searchCorpus.mockResolvedValue({
      data: response({ hits: [hit({ momentId: 'moment-newer' })] }),
      error: undefined,
    })

    render(<CorpusSearch />)
    const user = await type('purchase')
    await waitFor(() => expect(sdk.searchCorpus).toHaveBeenCalledTimes(1))

    await user.type(screen.getByTestId('search-input'), ' order')
    await screen.findByTestId('hit-moment-newer')

    first.resolve({
      data: response({ hits: [hit({ momentId: 'moment-stale' })] }),
      error: undefined,
    })
    await waitFor(() => expect(screen.queryByTestId('hit-moment-stale')).toBeNull())
    expect(screen.getByTestId('hit-moment-newer')).toBeInTheDocument()
  })

  it('aborts the current request as soon as a newer term is typed', async () => {
    const first = deferred<{ data: SearchResponse; error: undefined }>()
    let firstSignal: AbortSignal | undefined
    sdk.searchCorpus.mockImplementationOnce(({ signal }: { signal: AbortSignal }) => {
      firstSignal = signal
      return first.promise
    })

    render(<CorpusSearch />)
    const user = await type('purchase')
    await waitFor(() => expect(sdk.searchCorpus).toHaveBeenCalledTimes(1))

    await user.type(screen.getByTestId('search-input'), ' order')

    await waitFor(() => expect(firstSignal?.aborted).toBe(true))
    first.resolve({
      data: response({ hits: [hit({ momentId: 'moment-stale' })] }),
      error: undefined,
    })
    await waitFor(() => expect(screen.queryByTestId('hit-moment-stale')).toBeNull())
  })

  it('does not accept data that arrives after the client deadline', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      const late = deferred<{ data: SearchResponse; error: undefined }>()
      sdk.searchCorpus.mockReturnValue(late.promise)
      render(<CorpusSearch />)
      fireEvent.change(screen.getByTestId('search-input'), {
        target: { value: 'purchase order' },
      })
      await act(async () => {
        await vi.advanceTimersByTimeAsync(DEBOUNCE_MS + SEARCH_TIMEOUT_MS + 10)
      })
      await waitFor(() => expect(sdk.searchCorpus).toHaveBeenCalled())

      late.resolve({ data: response(), error: undefined })

      const alert = await screen.findByRole('alert')
      expect(alert).toHaveTextContent(`timed out after ${SEARCH_TIMEOUT_MS}ms`)
      expect(screen.queryByTestId('hit-moment-1')).toBeNull()
    } finally {
      vi.useRealTimers()
    }
  })

  it('keeps the previous results standing when a later search fails', async () => {
    answers(response())
    render(<CorpusSearch />)
    const user = await type('purchase order')
    await screen.findByTestId('hit-moment-1')

    sdk.searchCorpus.mockRejectedValue(new Error('connection refused'))
    await user.type(screen.getByTestId('search-input'), 's')

    await screen.findByRole('alert')
    // Stale results beat a blank panel — the banner already says they may be.
    expect(screen.getByTestId('hit-moment-1')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('may be stale')
  })

  it('does not call first-search failure results stale', async () => {
    sdk.searchCorpus.mockRejectedValue(new Error('connection refused'))
    render(<CorpusSearch />)
    await type('purchase order')

    expect(await screen.findByRole('alert')).not.toHaveTextContent('may be stale')
  })

  it('reports an empty result as an empty result, not as a failure', async () => {
    answers(response({ hits: [], estimatedTotal: 0 }))
    render(<CorpusSearch />)
    await type('zzzzzzzz')

    expect(await screen.findByTestId('search-empty')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('says so when the search ranked on keywords alone', async () => {
    answers(response({ ranking: 'keyword' }))
    render(<CorpusSearch />)
    await type('purchase order')

    // The embedder was down. The results are good — BM25 carries the dominant
    // query shape — but the user is told which ranking produced them.
    expect(await screen.findByTestId('ranking-degraded')).toBeInTheDocument()
  })

  it('shows no degraded notice on a hybrid search', async () => {
    answers(response())
    render(<CorpusSearch />)
    await type('purchase order')

    await screen.findByTestId('hit-moment-1')
    expect(screen.queryByTestId('ranking-degraded')).toBeNull()
  })

  it('opens an inline replay at the hit offset and closes it again', async () => {
    answers(response())
    render(<CorpusSearch />)
    const user = await type('purchase order')
    await screen.findByTestId('hit-moment-1')

    expect(screen.queryByTestId('replay-player')).toBeNull()
    await user.click(screen.getByRole('button', { name: /^Replay Data Hub Demo/ }))

    const player = (await screen.findByTestId('replay-player')) as HTMLVideoElement
    expect(player).toHaveAttribute('src', 'http://localhost:8000/media/recordings/meeting-1')
    // 44_000 ms is 0:44 — the offset a reviewer verifies the citation at.
    expect(screen.getByTestId('hit-offset-moment-1')).toHaveTextContent('0:44')
    player.currentTime = 0
    act(() => {
      player.dispatchEvent(new Event('loadedmetadata'))
    })
    expect(player.currentTime).toBe(44)

    await user.click(screen.getByRole('button', { name: /^Hide Data Hub Demo/ }))
    expect(screen.queryByTestId('replay-player')).toBeNull()
  })

  it('offers the source deep link instead of replay on a transcript-only meeting', async () => {
    answers(
      response({
        hits: [
          hit({
            momentId: 'moment-2',
            hasRecording: false,
            screenshotId: null,
            sourceDeepLink: 'https://example-my.sharepoint.com/stream.aspx?id=x',
          }),
        ],
      }),
    )
    render(<CorpusSearch />)
    await type('purchase order')

    const link = await screen.findByTestId('hit-deep-link-moment-2')
    expect(link).toHaveAttribute(
      'href',
      'https://example-my.sharepoint.com/stream.aspx?id=x',
    )
    expect(screen.queryByRole('button', { name: /Replay/ })).toBeNull()
  })

  it('says plainly when a hit has neither a recording nor a link', async () => {
    answers(
      response({
        hits: [
          hit({ momentId: 'moment-3', hasRecording: false, sourceDeepLink: null }),
        ],
      }),
    )
    render(<CorpusSearch />)
    await type('purchase order')

    // A dead button would be worse than an honest sentence.
    expect(await screen.findByTestId('hit-no-evidence-moment-3')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Replay/ })).toBeNull()
  })

  it('says the corpus was never indexed rather than "nothing matched"', async () => {
    // A fresh install. Telling the user to try other words would be advice
    // that cannot work — nothing has been projected at all.
    answers(response({ hits: [], estimatedTotal: 0, indexMissing: true }))
    render(<CorpusSearch />)
    await type('purchase order')

    const message = await screen.findByTestId('search-index-missing')
    expect(message).toHaveTextContent(/Ingest a meeting/i)
    expect(screen.queryByTestId('search-empty')).toBeNull()
  })

  it('renders a source deep link with an unusable scheme as inert text', async () => {
    // `sourceDeepLink` is copied out of a source drop this app did not write,
    // and it lands inside an `<a href>`. A `javascript:` URL there executes.
    answers(
      response({
        hits: [
          hit({
            momentId: 'moment-4',
            hasRecording: false,
            screenshotId: null,
            sourceDeepLink: 'javascript:alert(1)',
          }),
        ],
      }),
    )
    render(<CorpusSearch />)
    await type('purchase order')

    const inert = await screen.findByTestId('hit-unsafe-link-moment-4')
    expect(inert).toHaveTextContent('javascript:alert(1)')
    expect(inert.tagName).toBe('SPAN')
    expect(screen.queryByTestId('hit-deep-link-moment-4')).toBeNull()
    expect(screen.queryByRole('link')).toBeNull()
  })

  it('says how much of the answer it is showing when the page is truncated', async () => {
    // Results stopping at the page size look exactly like the whole answer.
    answers(response({ hits: [hit()], estimatedTotal: 137 }))
    render(<CorpusSearch />)
    await type('purchase order')

    expect(await screen.findByTestId('search-truncated')).toHaveTextContent(
      'Showing 1 of about 137 matches',
    )
  })

  it('says nothing about truncation when the page is the whole answer', async () => {
    answers(response({ hits: [hit()], estimatedTotal: 1 }))
    render(<CorpusSearch />)
    await type('purchase order')

    await screen.findByTestId('hit-moment-1')
    expect(screen.queryByTestId('search-truncated')).toBeNull()
  })

  it('renders a visible placeholder for a hit with no snippet', async () => {
    // A purely semantic hit on a document the store had nothing to crop. An
    // empty paragraph reads as a rendering bug, not as an answer.
    answers(response({ hits: [hit({ momentId: 'moment-5', snippet: [] })] }))
    render(<CorpusSearch />)
    await type('purchase order')

    expect(await screen.findByTestId('hit-snippet-moment-5')).toHaveTextContent(
      /No preview/i,
    )
  })

  it('announces the results region as busy while a search is running', async () => {
    const pending = deferred<{ data: SearchResponse; error: undefined }>()
    sdk.searchCorpus.mockReturnValue(pending.promise)

    render(<CorpusSearch />)
    await type('purchase order')

    const live = await screen.findByTestId('search-loading')
    const region = live.parentElement!
    expect(region).toHaveAttribute('aria-live', 'polite')
    expect(region).toHaveAttribute('aria-busy', 'true')

    pending.resolve({ data: response(), error: undefined })
    await screen.findByTestId('hit-moment-1')
    await waitFor(() => expect(region).toHaveAttribute('aria-busy', 'false'))
  })

  it('is reachable by the words printed next to it', async () => {
    // WCAG 2.5.3: an `aria-label` here would override the visible text and
    // leave a voice user unable to say what they can read.
    render(<CorpusSearch />)
    expect(
      screen.getByLabelText(/Search the corpus/i),
    ).toBe(screen.getByTestId('search-input'))
  })

  it('returns to the prompt when the box is cleared', async () => {
    answers(response())
    render(<CorpusSearch />)
    const user = await type('purchase order')
    await screen.findByTestId('hit-moment-1')

    await user.clear(screen.getByTestId('search-input'))
    expect(await screen.findByTestId('search-prompt')).toBeInTheDocument()
    expect(screen.queryByTestId('hit-moment-1')).toBeNull()
  })

  it('offers Open moment on every hit, handing the shell the moment id', async () => {
    // The story-3.1 deferred destination: a hit dead-ended at inline replay
    // until the moment view existed; now every hit opens it via the shell.
    answers(response())
    const onOpenMoment = vi.fn()
    render(<CorpusSearch onOpenMoment={onOpenMoment} />)
    const user = await type('purchase order')
    await screen.findByTestId('hit-moment-1')

    await user.click(
      screen.getByRole('button', { name: /Open moment in Data Hub Demo at 0:44/ }),
    )
    expect(onOpenMoment).toHaveBeenCalledWith('moment-1')
  })

  it('offers no Open moment button when the shell wired no navigation', async () => {
    // An enabled button that silently does nothing is exactly the dead
    // affordance the replay states exist to avoid.
    answers(response())
    render(<CorpusSearch />)
    await type('purchase order')
    await screen.findByTestId('hit-moment-1')

    expect(screen.queryByRole('button', { name: /Open moment/ })).toBeNull()
  })

  it('renders a published-artifact hit with its kind badge, title and source line', async () => {
    answers(
      response({
        hits: [
          hit({
            artifactId: 'artifact-1',
            artifactKind: 'adr',
            artifactTitle: 'Move the feed to SFTP',
          }),
          hit(),
        ],
        estimatedTotal: 2,
      }),
    )
    render(<CorpusSearch />)
    await type('sftp')

    const artifactRow = await screen.findByTestId('hit-artifact-1')
    expect(within(artifactRow).getByTestId('hit-kind-artifact-1')).toHaveTextContent(
      'ADR',
    )
    expect(artifactRow).toHaveTextContent('Move the feed to SFTP')
    // The evidence trail names the source meeting — the offset already
    // appears once, in the header span above, and the replay affordance
    // below plays that moment back.
    expect(within(artifactRow).getByTestId('hit-source-artifact-1')).toHaveTextContent(
      'Published from Data Hub Demo',
    )
    // The artifact hit and the plain moment hit resolve to the same source
    // moment and still render as two distinct rows.
    const momentRow = screen.getByTestId('hit-moment-1')
    expect(within(momentRow).queryByTestId(/hit-kind/)).toBeNull()
  })

  it('announces an artifact hit and its source moment differently to a screen reader', async () => {
    // Both rows share the same meeting/offset — without the artifact's own
    // title in the label, a screen reader announces "Replay Data Hub Demo at
    // 0:44" twice for two different rows.
    answers(
      response({
        hits: [
          hit({
            artifactId: 'artifact-1',
            artifactKind: 'adr',
            artifactTitle: 'Move the feed to SFTP',
          }),
          hit(),
        ],
        estimatedTotal: 2,
      }),
    )
    render(<CorpusSearch />)
    await type('sftp')
    await screen.findByTestId('hit-artifact-1')

    expect(
      screen.getByRole('button', { name: /^Replay Move the feed to SFTP at 0:44/ }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /^Replay Data Hub Demo at 0:44/ }),
    ).toBeInTheDocument()
  })

  it('replays the source moment from an artifact hit', async () => {
    answers(
      response({
        hits: [
          hit({
            artifactId: 'artifact-1',
            artifactKind: 'action-item',
            artifactTitle: 'Send the revised PO',
          }),
        ],
      }),
    )
    render(<CorpusSearch />)
    await type('purchase order')
    const row = await screen.findByTestId('hit-artifact-1')

    fireEvent.click(within(row).getByRole('button', { name: /Replay/ }))
    expect(within(row).getByTestId('replay-player')).toBeInTheDocument()
  })
})

describe('hit display helpers', () => {
  it('formats an offset as minutes and seconds, and past an hour as h:mm:ss', () => {
    expect(offsetLabel(0)).toBe('0:00')
    expect(offsetLabel(44_000)).toBe('0:44')
    expect(offsetLabel(64_000)).toBe('1:04')
    expect(offsetLabel(3_849_000)).toBe('1:04:09')
  })

  it('never throws on an offset that is not a usable number', () => {
    // A moment whose offset was derived from something absent hands over NaN;
    // the top of the recording is the honest answer to "no known moment".
    expect(offsetLabel(Number.NaN)).toBe('0:00')
    expect(offsetLabel(-1)).toBe('0:00')
  })

  it('falls back to the meeting id when a meeting has no usable title', () => {
    expect(hitLabel(hit())).toBe('Data Hub Demo')
    expect(hitLabel(hit({ meetingTitle: null }))).toBe('meeting-1')
    // The column is nullable *and* the projection writes `title or ""`, so an
    // untitled meeting reaches the wire both ways. A blank header names
    // nothing either way.
    expect(hitLabel(hit({ meetingTitle: '' }))).toBe('meeting-1')
    expect(hitLabel(hit({ meetingTitle: '   ' }))).toBe('meeting-1')
  })

  it('accepts only http and https as a real link', () => {
    expect(safeHref('https://example.com/x')).toBe('https://example.com/x')
    expect(safeHref('http://example.com/x')).toBe('http://example.com/x')
    expect(safeHref('javascript:alert(1)')).toBeNull()
    expect(safeHref('data:text/html,<script>x</script>')).toBeNull()
    expect(safeHref('file:///etc/passwd')).toBeNull()
    // Relative: it would resolve against this app's origin, never the source.
    expect(safeHref('/stream.aspx?id=x')).toBeNull()
    expect(safeHref('')).toBeNull()
    expect(safeHref(null)).toBeNull()
  })

  it('reads the human sentence out of a problem body, or admits there is none', () => {
    expect(
      problemMessage({ title: 'Service Unavailable', detail: 'the store is down' }),
    ).toBe('Service Unavailable: the store is down')
    expect(problemMessage({ detail: 'just the detail' })).toBe('just the detail')
    expect(problemMessage({ title: 'just the title' })).toBe('just the title')
    expect(problemMessage({ status: 503 })).toBeNull()
    expect(problemMessage('a plain string')).toBeNull()
    expect(problemMessage(null)).toBeNull()
  })

  it('chooses replay, deep link, inert text, or neither', () => {
    expect(affordanceOf(hit())).toEqual({ kind: 'replay' })
    expect(
      affordanceOf(hit({ hasRecording: false, sourceDeepLink: 'https://x/y' })),
    ).toEqual({ kind: 'deepLink', href: 'https://x/y' })
    expect(
        affordanceOf(hit({ hasRecording: false, sourceDeepLink: 'javascript:x' })),
    ).toEqual({ kind: 'inertLink', text: 'javascript:x' })
    expect(affordanceOf(hit({ hasRecording: false, sourceDeepLink: null }))).toEqual({
      kind: 'none',
    })
  })

  it('prefers replay over a stale deep link when a recording exists', () => {
    // AD-15 clears `sourceDeepLink` once a recording arrives; if a stale one
    // survives, the recording still wins.
    expect(affordanceOf(hit({ sourceDeepLink: 'https://x/y' }))).toEqual({
      kind: 'replay',
    })
  })

  it('flattens a snippet to its plain text', () => {
    expect(snippetText(hit().snippet)).toBe('And the purchase order still needs approval.')
    expect(snippetText([])).toBe('')
  })

  it('keys a hit on its artifact id when it is one, and its moment id otherwise', () => {
    expect(hitKey(hit())).toBe('moment-1')
    expect(hitKey(hit({ artifactId: 'artifact-1' }))).toBe('artifact-1')
  })

  it('names the kind badge for artifact hits only', () => {
    expect(artifactBadge(hit())).toBeNull()
    expect(artifactBadge(hit({ artifactId: 'a', artifactKind: 'adr' }))).toBe('ADR')
    expect(artifactBadge(hit({ artifactId: 'a', artifactKind: 'action-item' }))).toBe(
      'Action item',
    )
    // A kind this app does not know yet still renders as itself.
    expect(artifactBadge(hit({ artifactId: 'a', artifactKind: 'decision' }))).toBe(
      'decision',
    )
  })
})
