import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type {
  CitationModel,
  CorpusStats,
  HealthResponse,
  MeetingDrilldownResponse,
  MeetingListItem,
  MomentDetail,
  ParticipantRow,
  RouteModel,
  SearchResponse,
} from '@/client/types.gen'
import { createFakeStream, type StreamOptions } from '@/test/fakeStream'
import App from './App'

const sdk = vi.hoisted(() => ({
  getHealth: vi.fn(),
  listMeetings: vi.fn(),
  streamJobEvents: vi.fn(),
  searchCorpus: vi.fn(),
  getMeetingDrilldown: vi.fn(),
  getMoment: vi.fn(),
  listParticipants: vi.fn(),
  getCorpusStats: vi.fn(),
}))

// The factory lists every export of the generated sdk, so a route added to the
// api and regenerated into the client shows up here as a missing mock rather
// than as an undefined call deep inside a component.
vi.mock('@/client/sdk.gen', () => ({
  getHealth: sdk.getHealth,
  listMeetings: sdk.listMeetings,
  streamJobEvents: sdk.streamJobEvents,
  searchCorpus: sdk.searchCorpus,
  getMeetingDrilldown: sdk.getMeetingDrilldown,
  listMeetingMoments: vi.fn(),
  getMoment: sdk.getMoment,
  getJob: vi.fn(),
  createIngest: vi.fn(),
  getRecording: vi.fn(),
  getMediaFile: vi.fn(),
  listParticipants: sdk.listParticipants,
  renameParticipant: vi.fn(),
  mergeParticipants: vi.fn(),
  askCorpus: vi.fn(),
  approveMomentArtifacts: vi.fn(),
  getExtractionPrompts: vi.fn(),
  getCorpusStats: sdk.getCorpusStats,
  getSystemStatus: vi.fn(),
  getConfiguration: vi.fn(),
}))

function health(service: string): { data: HealthResponse; error: undefined } {
  return { data: { status: 'ok', service, configVersion: 1 }, error: undefined }
}

function corpusStats(): CorpusStats {
  return {
    meetings: 12,
    totalDurationMs: 44_640_000, // 12.4 h
    moments: 340,
    screens: 41,
    screenshots: 158,
    artifacts: { total: 57, byKind: { action: 30, decision: 27 }, byState: { published: 9 } },
    participants: 23,
    publishedDocuments: 9,
  }
}

/** A promise plus the handle to settle it, so a test decides when a call returns. */
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((r) => {
    resolve = r
  })
  return { promise, resolve }
}

beforeEach(() => {
  // `App` owns a real browser router now (story 2.8), and jsdom's URL
  // persists across tests in this file — pin each test's starting location
  // to home. A mechanical consequence of the router; no assertion changed.
  window.history.replaceState(null, '', '/')
  sdk.getHealth.mockReset()
  sdk.listMeetings.mockReset()
  sdk.streamJobEvents.mockReset()
  sdk.searchCorpus.mockReset()
  sdk.getMeetingDrilldown.mockReset()
  sdk.getMoment.mockReset()
  sdk.listParticipants.mockReset()
  sdk.getCorpusStats.mockReset()
  sdk.getCorpusStats.mockResolvedValue({ data: corpusStats(), error: undefined })
  sdk.listMeetings.mockResolvedValue({ data: { meetings: [] }, error: undefined })
  sdk.streamJobEvents.mockImplementation(async (options: StreamOptions) => {
    const live = createFakeStream(options)
    return { stream: live.stream }
  })
  sdk.listParticipants.mockResolvedValue({ data: [], error: undefined })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

const STAGE_NAMES = [
  'probe', 'frames', 'ocr', 'screens', 'transcribe', 'align', 'moments', 'extract',
] as const

function viewableMeeting(): MeetingListItem {
  return {
    jobId: 'job-1',
    meetingId: 'meeting-1',
    title: 'Data Hub Demo',
    sourceId: 'source-1',
    corpus: 'real',
    startedAt: '2026-08-05T12:00:19Z',
    startedAtPrecision: 'second',
    hasRecording: true,
    status: 'running',
    error: null,
    stages: STAGE_NAMES.map((name) => ({
      name,
      status: name === 'extract' ? 'queued' : 'done',
      error: null,
    })),
    viewable: true,
  }
}

function drilldownResponse(): MeetingDrilldownResponse {
  return {
    meetingId: 'meeting-1',
    title: 'Data Hub Demo',
    hasRecording: true,
    corpus: 'real',
    startedAt: '2026-08-05T12:00:19Z',
    startedAtPrecision: 'second',
    sourceDeepLink: null,
    screenshots: [
      {
        screenshotId: 'screenshot-1',
        ordinal: 1,
        startOffsetMs: 0,
        endOffsetMs: 30_000,
        path: 'meetings/meeting-1/screenshots/1.jpg',
        viewType: 'ui-screen',
        screenLabel: null,
        classificationTags: [],
        momentId: 'moment-1',
      },
    ],
    segments: [
      {
        segmentId: 'seg-1',
        ordinal: 1,
        startMs: 2_000,
        endMs: 4_000,
        speakerLabel: 'Goeke, Timothy',
        speakerResolution: 'resolved',
        participantId: 'participant-1',
        text: 'Everybody, good morning.',
        momentId: 'moment-1',
      },
    ],
  }
}

function momentDetail(): MomentDetail {
  return {
    momentId: 'moment-1',
    meetingId: 'meeting-1',
    meetingTitle: 'Data Hub Demo',
    corpus: 'real',
    hasRecording: true,
    startMs: 2_000,
    endMs: 11_000,
    startedAt: '2026-08-05T12:00:21Z',
    startedAtPrecision: 'second',
    screenshotId: 'screenshot-1',
    screenshotPath: 'meetings/meeting-1/screenshots/1.jpg',
    sourceDeepLink: null,
    superseded: false,
    segments: [
      {
        startMs: 2_000,
        endMs: 4_000,
        speakerLabel: 'Goeke, Timothy',
        speakerResolution: 'resolved',
        participantId: 'participant-1',
        text: 'Everybody, good morning.',
      },
    ],
    artifacts: [],
  }
}

// The one raw-`fetch` endpoint in the app shell: `ChatPanel` reads `/chat`
// through `chatStream.ts`'s hand-rolled reader, not the generated sdk
// (Boundaries — a 422 must be read on the same request rather than retried),
// so it needs its own mock rather than a `sdk.*` entry.
function sseFrame(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`
}

function chatStreamResponse(citations: Array<CitationModel>, route: RouteModel): Response {
  const encoder = new TextEncoder()
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(
        encoder.encode(sseFrame('chat.token', { event: 'chat.token', text: 'Approved.' })),
      )
      controller.enqueue(
        encoder.encode(sseFrame('chat.citations', { event: 'chat.citations', citations })),
      )
      controller.enqueue(encoder.encode(sseFrame('chat.done', { event: 'chat.done', route })))
      controller.close()
    },
  })
  return new Response(stream, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
}

function searchResponse(): SearchResponse {
  return {
    query: 'purchase order',
    ranking: 'hybrid',
    hits: [
      {
        momentId: 'moment-1',
        meetingId: 'meeting-1',
        meetingTitle: 'Data Hub Demo',
        startMs: 2_000,
        endMs: 11_000,
        startedAt: '2026-08-05T12:00:21Z',
        startedAtPrecision: 'second',
        screenshotId: 'screenshot-1',
        sourceDeepLink: null,
        hasRecording: true,
        corpus: 'real',
        snippet: [{ text: 'purchase order', highlighted: true }],
        score: 0.99,
      },
    ],
    estimatedTotal: 1,
    limit: 20,
    offset: 0,
    indexMissing: false,
  }
}

describe('App', () => {
  it('opens participant curation through the Shell entry point', async () => {
    sdk.getHealth.mockResolvedValue(health('meetingminer-api'))
    sdk.listParticipants.mockResolvedValue({
      data: [
        {
          id: 'participant-1',
          identityKey: 'mail:participant@contoso.com',
          displayName: 'Participant',
          normalizedName: 'participant',
          mergedIntoParticipantId: null,
          createdAt: '2026-08-05T12:00:00Z',
          updatedAt: '2026-08-05T12:00:00Z',
        } satisfies ParticipantRow,
      ],
      error: undefined,
    })
    render(<App />)

    await userEvent.click(await screen.findByRole('button', { name: 'Participants' }))

    expect(await screen.findByRole('heading', { name: 'Participants' })).toBeInTheDocument()
    expect(screen.getByTestId('participant-row-participant-1')).toBeInTheDocument()
  })

  it('shows the meetings list as the main view, with the health panel beside it', async () => {
    sdk.getHealth.mockResolvedValue(health('meetingminer-api'))
    render(<App />)

    expect(await screen.findByRole('heading', { name: 'Meetings' })).toBeInTheDocument()
    expect(await screen.findByText('meetingminer-api')).toBeInTheDocument()
  })

  it('states the corpus scale on home from served counts only', async () => {
    sdk.getHealth.mockResolvedValue(health('meetingminer-api'))
    render(<App />)

    const stats = await screen.findByTestId('corpus-stats')
    await waitFor(() => expect(within(stats).getByText('340')).toBeInTheDocument())
    // Every figure is the served count: meetings, hours (44,640,000 ms →
    // 12.4 h), screens, artifact total, participants, published docs.
    expect(within(stats).getByText('12')).toBeInTheDocument()
    expect(within(stats).getByText('12.4')).toBeInTheDocument()
    expect(within(stats).getByText('41')).toBeInTheDocument()
    expect(within(stats).getByText('57')).toBeInTheDocument()
    expect(within(stats).getByText('23')).toBeInTheDocument()
    expect(within(stats).getByText('9')).toBeInTheDocument()
    expect(sdk.getCorpusStats).toHaveBeenCalledTimes(1)
  })

  it('says the corpus counts are unavailable rather than rendering invented zeros', async () => {
    sdk.getHealth.mockResolvedValue(health('meetingminer-api'))
    sdk.getCorpusStats.mockRejectedValue(new Error('connection refused'))
    render(<App />)

    const stats = await screen.findByTestId('corpus-stats')
    await waitFor(() =>
      expect(stats).toHaveTextContent(/Corpus counts unavailable/),
    )
    expect(stats).toHaveTextContent('connection refused')
    expect(within(stats).queryByText('0')).toBeNull()
  })

  it('keeps search, ask, and the nav links in the chrome on a child screen', async () => {
    sdk.getHealth.mockResolvedValue(health('meetingminer-api'))
    sdk.getMoment.mockResolvedValue({ data: momentDetail(), error: undefined })
    window.history.replaceState(null, '', '/moments/moment-1')

    render(<App />)
    await screen.findByTestId('moment-artifact-rail')

    // Home content is hidden — but the chrome is not: search, ask, and the
    // standing destinations survive on every route (SPEC-ui-reimagine CAP-1).
    expect(screen.queryByRole('heading', { name: 'Meetings' })).toBeNull()
    expect(screen.getByTestId('search-input')).toBeInTheDocument()
    expect(screen.getByTestId('chat-question-input')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Home' })).toHaveAttribute('href', '/')
    expect(screen.getByRole('link', { name: 'Status' })).toHaveAttribute('href', '/status')
    // `/settings` is story ui-4's page; the chrome links to it either way.
    expect(screen.getByRole('link', { name: 'Settings' })).toHaveAttribute('href', '/settings')
  })

  it('opens the status page from the chrome nav', async () => {
    sdk.getHealth.mockResolvedValue(health('meetingminer-api'))
    render(<App />)
    await screen.findByRole('heading', { name: 'Meetings' })

    await userEvent.click(screen.getByRole('link', { name: 'Status' }))

    expect(await screen.findByRole('heading', { name: 'System status' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Meetings' })).toBeNull()
  })

  it('mounts corpus search above the meetings list, idle until asked', async () => {
    sdk.getHealth.mockResolvedValue(health('meetingminer-api'))
    render(<App />)

    const search = await screen.findByRole('heading', { name: 'Search' })
    const meetings = await screen.findByRole('heading', { name: 'Meetings' })
    // Document order: search first. `compareDocumentPosition` returns
    // FOLLOWING (4) when the argument comes after the node.
    expect(search.compareDocumentPosition(meetings)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    )
    expect(screen.getByTestId('search-prompt')).toBeInTheDocument()
    expect(sdk.searchCorpus).not.toHaveBeenCalled()
  })

  it('never lets a superseded health check overwrite a newer result', async () => {
    // Pins story 1.10 finding 22: the deferred first call resolves *after* the
    // second one, and its answer must be discarded because its controller was
    // aborted. Without the post-await abort guards this test fails.
    const first = deferred<ReturnType<typeof health>>()
    sdk.getHealth.mockImplementationOnce(() => first.promise)
    sdk.getHealth.mockResolvedValue(health('second-response'))

    render(<App />)
    await waitFor(() => expect(sdk.getHealth).toHaveBeenCalledTimes(1))

    await userEvent.click(screen.getByRole('button', { name: 'Re-check' }))
    await screen.findByText('second-response')

    first.resolve(health('stale-response'))
    await waitFor(() => expect(screen.queryByText('stale-response')).toBeNull())
    expect(screen.getByText('second-response')).toBeInTheDocument()
  })

  it('names the api address when health cannot be reached', async () => {
    sdk.getHealth.mockRejectedValue(new Error('connection refused'))
    render(<App />)

    const message = await screen.findByText(/cannot reach the api at/i)
    expect(message).toHaveTextContent('http://localhost:8000')
    expect(message).toHaveTextContent('connection refused')
  })

  it('opens a viewable meeting from the list and comes back home', async () => {
    sdk.getHealth.mockResolvedValue(health('meetingminer-api'))
    sdk.listMeetings.mockResolvedValue({
      data: { meetings: [viewableMeeting()] },
      error: undefined,
    })
    sdk.getMeetingDrilldown.mockResolvedValue({ data: drilldownResponse(), error: undefined })

    render(<App />)
    await userEvent.click(
      await screen.findByRole('button', { name: 'Open Data Hub Demo' }),
    )

    // The meeting's drill-down replaces the home view.
    expect(await screen.findByTestId('drilldown-segment-seg-1')).toBeInTheDocument()
    expect(sdk.getMeetingDrilldown.mock.calls[0][0].path.meeting_id).toBe('meeting-1')
    expect(screen.queryByRole('heading', { name: 'Meetings' })).toBeNull()

    await userEvent.click(screen.getByRole('button', { name: '← Back' }))
    expect(await screen.findByRole('heading', { name: 'Meetings' })).toBeInTheDocument()
  })

  it('opens the moment view from a meeting list row', async () => {
    sdk.getHealth.mockResolvedValue(health('meetingminer-api'))
    sdk.listMeetings.mockResolvedValue({
      data: { meetings: [viewableMeeting()] },
      error: undefined,
    })
    sdk.getMeetingDrilldown.mockResolvedValue({ data: drilldownResponse(), error: undefined })
    sdk.getMoment.mockResolvedValue({ data: momentDetail(), error: undefined })

    render(<App />)
    await userEvent.click(
      await screen.findByRole('button', { name: 'Open Data Hub Demo' }),
    )
    await userEvent.click(
      await screen.findByRole('button', {
        name: 'Open moment at 0:02: Everybody, good morning.',
      }),
    )

    expect(await screen.findByTestId('moment-artifact-rail')).toBeInTheDocument()
    expect(sdk.getMoment.mock.calls[0][0].path.moment_id).toBe('moment-1')
  })

  it('opens the moment view straight from a chat citation', async () => {
    sdk.getHealth.mockResolvedValue(health('meetingminer-api'))
    sdk.getMoment.mockResolvedValue({ data: momentDetail(), error: undefined })
    // URL-aware, not a blanket resolved value: the shell now carries a second
    // raw-`fetch` reader — the status indicator polls `GET /status`
    // (SPEC-system-status) — and a single shared Response body would be
    // consumed by whichever request lands first. Only `/chat` gets the
    // stream; the status poll gets a refusal and reads as unreachable, which
    // is irrelevant to this citation-navigation test.
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      if (!String(input).endsWith('/chat')) {
        return Promise.reject(new Error('no api in this test'))
      }
      return Promise.resolve(
        chatStreamResponse(
          [
            {
              momentId: 'moment-1',
              meetingId: 'meeting-1',
              startMs: 2_000,
              endMs: 11_000,
              screenshotId: 'screenshot-1',
              sourceDeepLink: null,
            },
          ],
          {
            template: null,
            anchorResolved: null,
            traversalOutcome: 'not-dispatched',
            fallbackReason: null,
            searchHits: 1,
            traversalRows: 0,
            traversalTruncated: false,
            retrieved: 1,
          },
        ),
      )
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    await userEvent.type(
      screen.getByTestId('chat-question-input'),
      'What happened with the purchase order?',
    )
    await userEvent.click(screen.getByTestId('chat-submit'))

    await userEvent.click(
      await screen.findByRole('button', { name: /open moment at/i }),
    )

    // The same navigation wiring `App.tsx` gives `CorpusSearch` — proves the
    // `<ChatPanel onOpenMoment={...} />` line, not just `ChatPanel`'s own
    // prop call.
    expect(await screen.findByTestId('moment-artifact-rail')).toBeInTheDocument()
    expect(sdk.getMoment.mock.calls[0][0].path.moment_id).toBe('moment-1')
  })

  it('opens the moment view straight from a search hit', async () => {
    sdk.getHealth.mockResolvedValue(health('meetingminer-api'))
    sdk.searchCorpus.mockResolvedValue({ data: searchResponse(), error: undefined })
    sdk.getMoment.mockResolvedValue({ data: momentDetail(), error: undefined })

    render(<App />)
    await userEvent.type(screen.getByTestId('search-input'), 'purchase order')
    await userEvent.click(
      await screen.findByRole('button', { name: /Open moment in Data Hub Demo/ }),
    )

    expect(await screen.findByTestId('moment-artifact-rail')).toBeInTheDocument()
    expect(sdk.getMoment.mock.calls[0][0].path.moment_id).toBe('moment-1')
  })

  it('returns from a moment to the meeting list it was opened from', async () => {
    sdk.getHealth.mockResolvedValue(health('meetingminer-api'))
    sdk.listMeetings.mockResolvedValue({
      data: { meetings: [viewableMeeting()] },
      error: undefined,
    })
    sdk.getMeetingDrilldown.mockResolvedValue({ data: drilldownResponse(), error: undefined })
    sdk.getMoment.mockResolvedValue({ data: momentDetail(), error: undefined })

    render(<App />)
    await userEvent.click(
      await screen.findByRole('button', { name: 'Open Data Hub Demo' }),
    )
    await userEvent.click(
      await screen.findByRole('button', {
        name: 'Open moment at 0:02: Everybody, good morning.',
      }),
    )
    await screen.findByTestId('moment-artifact-rail')

    // The stack, not a home reset: Back lands on the meeting this moment was
    // opened out of, with its rows intact.
    await userEvent.click(screen.getByRole('button', { name: '← Back' }))
    expect(await screen.findByTestId('drilldown-segment-seg-1')).toBeInTheDocument()
    expect(screen.queryByTestId('moment-artifact-rail')).toBeNull()

    await userEvent.click(screen.getByRole('button', { name: '← Back' }))
    expect(await screen.findByRole('heading', { name: 'Meetings' })).toBeInTheDocument()
  })

  it('keeps the search state alive behind a moment opened from a hit', async () => {
    sdk.getHealth.mockResolvedValue(health('meetingminer-api'))
    sdk.searchCorpus.mockResolvedValue({ data: searchResponse(), error: undefined })
    sdk.getMoment.mockResolvedValue({ data: momentDetail(), error: undefined })

    render(<App />)
    await userEvent.type(screen.getByTestId('search-input'), 'purchase order')
    await userEvent.click(
      await screen.findByRole('button', { name: /Open moment in Data Hub Demo/ }),
    )
    await screen.findByTestId('moment-artifact-rail')

    // Home is hidden, never unmounted: Back must land on the same query and
    // results, or the verify-a-claim loop re-searches on every return.
    await userEvent.click(screen.getByRole('button', { name: '← Back' }))
    const input = screen.getByTestId('search-input') as HTMLInputElement
    expect(input.value).toBe('purchase order')
    expect(screen.getByTestId('hit-moment-1')).toBeInTheDocument()
    expect(sdk.searchCorpus).toHaveBeenCalledTimes(1)
  })

  it('never stacks a double-clicked Open twice', async () => {
    sdk.getHealth.mockResolvedValue(health('meetingminer-api'))
    sdk.listMeetings.mockResolvedValue({
      data: { meetings: [viewableMeeting()] },
      error: undefined,
    })
    sdk.getMeetingDrilldown.mockResolvedValue({ data: drilldownResponse(), error: undefined })

    render(<App />)
    await userEvent.dblClick(
      await screen.findByRole('button', { name: 'Open Data Hub Demo' }),
    )
    await screen.findByTestId('drilldown-segment-seg-1')

    // One Back must be enough: the identical view was not pushed twice.
    await userEvent.click(screen.getByRole('button', { name: '← Back' }))
    expect(await screen.findByRole('heading', { name: 'Meetings' })).toBeInTheDocument()
  })

  it('renders home rather than a blank shell on an unknown path', async () => {
    sdk.getHealth.mockResolvedValue(health('meetingminer-api'))
    window.history.replaceState(null, '', '/no/such/screen')

    render(<App />)

    expect(await screen.findByRole('heading', { name: 'Meetings' })).toBeInTheDocument()
    // Home is the current view, not a hidden layer behind a matched child.
    expect(screen.queryByRole('button', { name: '← Back' })).not.toBeInTheDocument()
  })

  it('falls back to home when Back is pressed on a deep-linked moment', async () => {
    sdk.getHealth.mockResolvedValue(health('meetingminer-api'))
    sdk.getMoment.mockResolvedValue({ data: momentDetail(), error: undefined })
    // A fresh tab straight onto a child URL: no in-app history entry exists
    // beneath it, so navigate(-1) alone would do nothing (or leave the site).
    window.history.replaceState(null, '', '/moments/moment-1')

    render(<App />)
    await screen.findByTestId('moment-artifact-rail')

    await userEvent.click(screen.getByRole('button', { name: '← Back' }))
    expect(await screen.findByRole('heading', { name: 'Meetings' })).toBeInTheDocument()
    expect(screen.queryByTestId('moment-artifact-rail')).toBeNull()
  })
})
