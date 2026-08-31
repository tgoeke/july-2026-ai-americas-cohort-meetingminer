import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type {
  AcquisitionStatus,
  JobEvent,
  MeetingListItem,
  ProbeResult,
} from '@/client/types.gen'
import { API_BASE } from '@/lib/api'
import { AddMeeting, PROBE_DEBOUNCE_MS } from './AddMeeting'
import { POLL_INTERVAL_MS } from './useAcquisitionStatus'

const sdk = vi.hoisted(() => ({
  probeAcquisition: vi.fn(),
  startAcquisition: vi.fn(),
  getAcquisition: vi.fn(),
  listMeetings: vi.fn(),
}))

vi.mock('@/client/sdk.gen', () => ({
  probeAcquisition: sdk.probeAcquisition,
  startAcquisition: sdk.startAcquisition,
  getAcquisition: sdk.getAcquisition,
  listMeetings: sdk.listMeetings,
  streamJobEvents: vi.fn(),
}))

/**
 * The job stream is mocked at the hook, as `SpeakerNaming.test.tsx` does:
 * this screen's contract with it is "fold these frames", and `useJobEvents`
 * has its own tests for holding the connection. `subscriptions` is how the
 * "opening /add issues no request" case proves no connection was opened.
 */
const stream = vi.hoisted(() => ({
  onEvent: null as ((event: JobEvent) => void) | null,
  onAlive: null as (() => void) | null,
  onResync: null as (() => void) | null,
  subscriptions: 0,
  connection: { kind: 'live' as const },
}))

vi.mock('@/features/meetings/useJobEvents', () => ({
  useJobEvents: ({
    onEvent,
    onAlive,
    onResync,
  }: {
    onEvent: (event: JobEvent) => void
    onAlive?: () => void
    onResync: () => void
  }) => {
    stream.onEvent = onEvent
    stream.onAlive = onAlive ?? null
    stream.onResync = onResync
    stream.subscriptions += 1
    return stream.connection
  },
}))

const VIDEO_URL = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
const ACQUISITION = '0190a0f0-7c1e-7000-8000-0000000000aa'
const JOB = '8f3c1a2b-0000-7000-8000-0000000000cc'
const MEETING = '0190a0f0-7c1e-7000-8000-0000000000dd'

function probeResult(overrides: Partial<ProbeResult> = {}): ProbeResult {
  return {
    title: 'Retrieval bake-off review',
    durationMs: 5_040_000,
    captions: { kind: 'manual', language: 'en' },
    sourceId: 'youtube:dQw4w9WgXcQ',
    ...overrides,
  }
}

function acquisition(overrides: Partial<AcquisitionStatus> = {}): AcquisitionStatus {
  return {
    acquisitionId: ACQUISITION,
    sourceId: 'youtube:dQw4w9WgXcQ',
    url: VIDEO_URL,
    status: 'running',
    createdAt: '2026-08-31T10:00:00Z',
    updatedAt: '2026-08-31T10:00:05Z',
    logTail: [],
    ...overrides,
  }
}

function meetingRow(overrides: Partial<MeetingListItem> = {}): MeetingListItem {
  return {
    jobId: JOB,
    meetingId: MEETING,
    title: 'Retrieval bake-off review',
    sourceId: 'youtube:dQw4w9WgXcQ',
    corpus: 'real',
    startedAt: '2026-08-21T09:00:00Z',
    status: 'running',
    stages: [
      { name: 'probe', status: 'done', error: null },
      { name: 'frames', status: 'running', error: null },
      { name: 'transcribe', status: 'queued', error: null },
    ],
    viewable: false,
    ...overrides,
  } as MeetingListItem
}

/** `getAcquisition` answers these in order, then repeats the last one. */
function queueStatuses(...statuses: Array<AcquisitionStatus>) {
  let index = 0
  sdk.getAcquisition.mockImplementation(() => {
    const answer = statuses[Math.min(index, statuses.length - 1)]
    index += 1
    return Promise.resolve({ data: answer, error: undefined })
  })
}

let user: ReturnType<typeof userEvent.setup>

beforeEach(() => {
  // shouldAdvanceTime: `waitFor` and userEvent both poll on timers they do not
  // know are faked, so the clock has to keep moving on its own — the same
  // reason `CorpusSearch.test.tsx` sets it while driving its debounce.
  vi.useFakeTimers({ shouldAdvanceTime: true })
  user = userEvent.setup()
  stream.onEvent = null
  stream.onAlive = null
  stream.onResync = null
  stream.subscriptions = 0
  sdk.probeAcquisition.mockReset()
  sdk.startAcquisition.mockReset()
  sdk.getAcquisition.mockReset()
  sdk.listMeetings.mockReset()
  sdk.listMeetings.mockResolvedValue({ data: { meetings: [] }, error: undefined })
})

afterEach(() => {
  vi.useRealTimers()
})

/** Let the debounce elapse and the probe promise settle. */
async function settleProbe() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(PROBE_DEBOUNCE_MS + 10)
  })
}

/** Let one poll interval elapse and its promise settle. */
async function settlePoll() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS + 10)
  })
}

/**
 * Put a URL in the field and let its probe answer.
 *
 * `fireEvent.change` rather than `user.type`, for the reason
 * `CorpusSearch.test.tsx` states: the debounce is one of the timers this suite
 * drives, and typing character by character under fake timers would drive it
 * too.
 */
async function typeUrl(url: string) {
  fireEvent.change(screen.getByTestId('youtube-url'), { target: { value: url } })
  await settleProbe()
}

/** Get to a launched acquisition with the given status sequence. */
async function launch(...statuses: Array<AcquisitionStatus>) {
  sdk.probeAcquisition.mockResolvedValue({ data: probeResult(), error: undefined })
  sdk.startAcquisition.mockResolvedValue({
    data: { acquisitionId: ACQUISITION, sourceId: 'youtube:dQw4w9WgXcQ', status: 'queued' },
    error: undefined,
  })
  queueStatuses(...statuses)
  render(<AddMeeting />)
  await typeUrl(VIDEO_URL)
  await user.click(screen.getByTestId('submit-acquisition'))
}

describe('Add-meeting, idle and the shape check', () => {
  it('opens without sending anything, with Submit disabled and a reason why', async () => {
    render(<AddMeeting />)

    expect(sdk.probeAcquisition).not.toHaveBeenCalled()
    expect(sdk.startAcquisition).not.toHaveBeenCalled()
    expect(sdk.getAcquisition).not.toHaveBeenCalled()
    expect(sdk.listMeetings).not.toHaveBeenCalled()
    // No job stream either: an idle form must not spend a connection.
    expect(stream.subscriptions).toBe(0)

    expect(screen.getByTestId('submit-acquisition')).toBeDisabled()
    expect(screen.getByText('Paste a YouTube watch or youtu.be link to begin.')).toBeInTheDocument()
    // The YouTube tab is the one that opens.
    expect(screen.getByRole('tab', { name: 'YouTube URL' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    expect(screen.getByTestId('youtube-url')).toHaveFocus()
  })

  it('refuses a non-YouTube URL in place, without sending a probe', async () => {
    render(<AddMeeting />)
    await typeUrl('https://vimeo.com/12345')

    expect(
      screen.getByText('Not a YouTube video URL — paste a watch or youtu.be link.'),
    ).toBeInTheDocument()
    expect(sdk.probeAcquisition).not.toHaveBeenCalled()
    expect(screen.getByTestId('submit-acquisition')).toBeDisabled()
    // Nothing was refused by anyone, so this is not a refusal box.
    expect(screen.queryByTestId('probe-refusal')).not.toBeInTheDocument()
  })

  it('names a playlist URL as a playlist rather than as "not a YouTube URL"', async () => {
    render(<AddMeeting />)
    await typeUrl('https://www.youtube.com/playlist?list=PL9abcdef')

    expect(
      screen.getByText("Playlist URLs are not accepted on this tab — paste one video's watch link."),
    ).toBeInTheDocument()
    expect(sdk.probeAcquisition).not.toHaveBeenCalled()
  })
})

describe('Add-meeting, the pre-flight probe', () => {
  it('waits for the debounce, then probes the normalized URL exactly once', async () => {
    sdk.probeAcquisition.mockResolvedValue({ data: probeResult(), error: undefined })
    render(<AddMeeting />)

    fireEvent.change(screen.getByTestId('youtube-url'), {
      target: { value: 'https://youtu.be/dQw4w9WgXcQ' },
    })
    // Before the debounce elapses nothing has been sent.
    expect(sdk.probeAcquisition).not.toHaveBeenCalled()

    await settleProbe()
    expect(sdk.probeAcquisition).toHaveBeenCalledTimes(1)
    // Normalized: one video has one identity, whichever spelling was pasted.
    expect(sdk.probeAcquisition.mock.calls[0][0].body).toEqual({ url: VIDEO_URL })
  })

  it('shows Probing… while the probe is in flight, with Submit disabled', async () => {
    let resolve: ((value: unknown) => void) | undefined
    sdk.probeAcquisition.mockReturnValue(
      new Promise((r) => {
        resolve = r as (value: unknown) => void
      }),
    )
    render(<AddMeeting />)
    await typeUrl(VIDEO_URL)

    expect(screen.getByTestId('probe-running')).toHaveTextContent('Probing…')
    expect(screen.getByTestId('submit-acquisition')).toBeDisabled()
    expect(screen.getByTestId('youtube-url')).toHaveAttribute('aria-busy', 'true')

    await act(async () => {
      resolve?.({ data: probeResult(), error: undefined })
    })
    expect(screen.queryByTestId('probe-running')).not.toBeInTheDocument()
  })

  it('reads back what the probe answered and enables Submit, having written nothing', async () => {
    sdk.probeAcquisition.mockResolvedValue({ data: probeResult(), error: undefined })
    render(<AddMeeting />)
    await typeUrl(VIDEO_URL)

    expect(screen.getByTestId('probe-answered')).toHaveTextContent(
      'Retrieval bake-off review · 1h 24m · captions: manual en · youtube:dQw4w9WgXcQ',
    )
    expect(screen.getByText('Nothing has been written.')).toBeInTheDocument()
    expect(screen.getByTestId('submit-acquisition')).toBeEnabled()
    expect(sdk.startAcquisition).not.toHaveBeenCalled()
  })

  it('disables Submit immediately when an answered URL is replaced', async () => {
    sdk.probeAcquisition.mockResolvedValue({ data: probeResult(), error: undefined })
    render(<AddMeeting />)
    await typeUrl(VIDEO_URL)
    expect(screen.getByTestId('submit-acquisition')).toBeEnabled()

    fireEvent.change(screen.getByTestId('youtube-url'), {
      target: { value: 'https://youtu.be/aaaaaaaaaaa' },
    })

    expect(screen.getByTestId('submit-acquisition')).toBeDisabled()
    expect(screen.getByText('Waiting for the pre-flight check.')).toBeInTheDocument()
    expect(sdk.probeAcquisition).toHaveBeenCalledTimes(1)
  })

  it('reports a video with no captions as a fact, not a refusal', async () => {
    sdk.probeAcquisition.mockResolvedValue({
      data: probeResult({ captions: null }),
      error: undefined,
    })
    render(<AddMeeting />)
    await typeUrl(VIDEO_URL)

    expect(screen.getByTestId('probe-answered')).toHaveTextContent('captions: none')
    // A recording-only drop is valid, so Submit stays available.
    expect(screen.getByTestId('submit-acquisition')).toBeEnabled()
    expect(screen.queryByTestId('probe-refusal')).not.toBeInTheDocument()
  })

  it('renders a probe refusal with the rule, detail and remediation the api sent', async () => {
    sdk.probeAcquisition.mockResolvedValue({
      data: undefined,
      error: {
        type: 'urn:meetingminer:problem:acquisition-refused',
        title: 'Unprocessable Content',
        status: 422,
        detail: '4h 02m exceeds the configured 180 minutes.',
        rule: 'duration-cap',
        remediation: 'Raise acquisition.youtube.maxDurationMinutes in config.yaml.',
      },
    })
    render(<AddMeeting />)
    await typeUrl(VIDEO_URL)

    const box = screen.getByTestId('probe-refusal')
    expect(box).toHaveAttribute('role', 'alert')
    expect(box).toHaveTextContent('duration-cap')
    expect(box).toHaveTextContent('4h 02m exceeds the configured 180 minutes.')
    expect(box).toHaveTextContent('Raise acquisition.youtube.maxDurationMinutes in config.yaml.')
    expect(screen.getByTestId('submit-acquisition')).toBeDisabled()
    expect(
      screen.getByText('Nothing was sent — the probe answered before submit.'),
    ).toBeInTheDocument()
  })

  it('reports an unreachable api as an outage, not as a refused video', async () => {
    sdk.probeAcquisition.mockRejectedValue(new TypeError('Failed to fetch'))
    render(<AddMeeting />)
    await typeUrl(VIDEO_URL)

    expect(screen.getByTestId('probe-transport')).toHaveTextContent(
      `Cannot reach the api at ${API_BASE}: Failed to fetch`,
    )
    expect(screen.queryByTestId('probe-refusal')).not.toBeInTheDocument()
    expect(screen.getByText('Retry the pre-flight check before submitting.')).toBeInTheDocument()
    expect(screen.queryByText('The pre-flight check refused this URL.')).not.toBeInTheDocument()
    expect(screen.getByTestId('submit-acquisition')).toBeDisabled()
  })

  it('retries the current probe after a transport failure', async () => {
    sdk.probeAcquisition
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockResolvedValueOnce({ data: probeResult(), error: undefined })
    render(<AddMeeting />)
    await typeUrl(VIDEO_URL)

    await user.click(screen.getByRole('button', { name: 'Retry' }))
    await settleProbe()

    expect(sdk.probeAcquisition).toHaveBeenCalledTimes(2)
    expect(screen.getByTestId('probe-answered')).toHaveTextContent('Retrieval bake-off review')
    expect(screen.getByTestId('submit-acquisition')).toBeEnabled()
  })

  it('discards a superseded probe: the answer for an edited-away URL never lands', async () => {
    const first = probeResult({ title: 'THE OLD ONE', sourceId: 'youtube:aaaaaaaaaaa' })
    let resolveFirst: ((value: unknown) => void) | undefined
    sdk.probeAcquisition
      .mockReturnValueOnce(
        new Promise((r) => {
          resolveFirst = r as (value: unknown) => void
        }),
      )
      .mockResolvedValue({
        data: probeResult({ title: 'THE NEW ONE' }),
        error: undefined,
      })

    render(<AddMeeting />)
    await typeUrl('https://youtu.be/aaaaaaaaaaa')
    // Edit to a different video while the first probe is still outstanding.
    await typeUrl(VIDEO_URL)

    await act(async () => {
      resolveFirst?.({ data: first, error: undefined })
    })

    expect(screen.getByTestId('probe-answered')).toHaveTextContent('THE NEW ONE')
    expect(screen.getByTestId('probe-answered')).not.toHaveTextContent('THE OLD ONE')
  })
})

describe('Add-meeting, submitting', () => {
  it('locks the form and shows the stepper once the api accepts', async () => {
    await launch(acquisition({ status: 'queued' }))

    expect(sdk.startAcquisition).toHaveBeenCalledTimes(1)
    expect(sdk.startAcquisition.mock.calls[0][0].body).toEqual({ url: VIDEO_URL })
    expect(screen.getByTestId('acquisition-stepper')).toBeInTheDocument()
    expect(screen.getByTestId('step-launch')).toHaveAttribute('data-status', 'done')
    expect(screen.getByTestId('youtube-url')).toHaveAttribute('readonly')
    expect(screen.getByText('The form is locked while the acquisition runs.')).toBeInTheDocument()
  })

  it('offers the running acquisition when the api refuses a second one for the same source', async () => {
    sdk.probeAcquisition.mockResolvedValue({ data: probeResult(), error: undefined })
    sdk.startAcquisition.mockResolvedValue({
      data: undefined,
      error: {
        type: 'urn:meetingminer:problem:acquisition-in-progress',
        title: 'Conflict',
        status: 409,
        detail: 'acquisition 0190… is already running for youtube:dQw4w9WgXcQ',
        acquisitionId: ACQUISITION,
        sourceId: 'youtube:dQw4w9WgXcQ',
      },
    })
    queueStatuses(acquisition({ status: 'running' }))

    render(<AddMeeting />)
    await typeUrl(VIDEO_URL)
    await user.click(screen.getByTestId('submit-acquisition'))

    const box = screen.getByTestId('submit-refusal')
    expect(box).toHaveTextContent('acquisition 0190… is already running for youtube:dQw4w9WgXcQ')
    // The form stays unlocked: nothing of this user's was started.
    expect(screen.getByTestId('youtube-url')).not.toHaveAttribute('readonly')

    await user.click(screen.getByTestId('open-running-acquisition'))
    expect(sdk.getAcquisition).toHaveBeenCalledWith(
      expect.objectContaining({ path: { acquisition_id: ACQUISITION } }),
    )
    expect(screen.getByTestId('acquisition-stepper')).toBeInTheDocument()
  })

  it('renders any other refusal in place and leaves the form usable', async () => {
    sdk.probeAcquisition.mockResolvedValue({ data: probeResult(), error: undefined })
    sdk.startAcquisition.mockResolvedValue({
      data: undefined,
      error: {
        type: 'urn:meetingminer:problem:acquisition-refused',
        title: 'Service Unavailable',
        status: 503,
        detail: 'yt-dlp is not installed',
        rule: 'tool-missing',
        remediation: 'Install yt-dlp and restart the api.',
      },
    })
    render(<AddMeeting />)
    await typeUrl(VIDEO_URL)
    await user.click(screen.getByTestId('submit-acquisition'))

    expect(screen.getByTestId('submit-refusal')).toHaveTextContent('tool-missing')
    expect(screen.getByTestId('submit-refusal')).toHaveTextContent('Install yt-dlp and restart the api.')
    expect(screen.queryByTestId('open-running-acquisition')).not.toBeInTheDocument()
    expect(screen.queryByTestId('acquisition-stepper')).not.toBeInTheDocument()
  })
})

describe('Add-meeting, progress', () => {
  it('shows the tool running, with its log', async () => {
    await launch(
      acquisition({
        status: 'running',
        logTail: ['yt-dlp: downloading 1080p mp4 … captions: manual en'],
      }),
    )

    expect(screen.getByTestId('step-running')).toHaveAttribute('data-status', 'running')
    expect(screen.getByTestId('step-posted')).toHaveAttribute('data-status', 'queued')
    const log = screen.getByTestId('acquisition-log')
    expect(log).toHaveTextContent('yt-dlp: downloading 1080p mp4 … captions: manual en')
    // The log is noise, never announced, and never the source of a failure.
    expect(log).toHaveAttribute('aria-live', 'off')
  })

  it('polls every two seconds while live and stops once the acquisition settles', async () => {
    await launch(
      acquisition({ status: 'running' }),
      acquisition({ status: 'posted', result: 'created', jobId: JOB, meetingId: MEETING }),
    )
    expect(sdk.getAcquisition).toHaveBeenCalledTimes(1)

    await settlePoll()
    expect(sdk.getAcquisition).toHaveBeenCalledTimes(2)
    expect(screen.getByTestId('step-posted')).toHaveAttribute('data-status', 'done')

    // Terminal: no further polls, whatever time passes.
    await settlePoll()
    await settlePoll()
    expect(sdk.getAcquisition).toHaveBeenCalledTimes(2)
  })

  it('hands over to the meeting card on posted, and fills it from the job stream', async () => {
    sdk.listMeetings.mockResolvedValue({ data: { meetings: [meetingRow()] }, error: undefined })
    await launch(
      acquisition({ status: 'posted', result: 'created', jobId: JOB, meetingId: MEETING }),
    )

    await waitFor(() => expect(screen.getByTestId('acquired-meeting')).toBeInTheDocument())
    expect(screen.getByTestId('step-posted')).toHaveTextContent('posted — job 8f3c…')
    // The existing stage renderer, not a second one.
    expect(screen.getByTestId('stage-frames')).toHaveAttribute('data-status', 'running')
    expect(screen.getByRole('button', { name: /^Open/ })).toBeDisabled()
    expect(screen.getByTestId('step-ingesting')).toHaveAttribute('data-status', 'running')

    // A stage moves: the bar patches in place, with no reload and no re-fetch.
    await act(async () => {
      stream.onEvent?.({
        jobId: JOB,
        event: 'job.stage',
        stage: 'frames',
        status: 'done',
        jobStatus: 'running',
        viewable: false,
        error: null,
      } as JobEvent)
    })
    await waitFor(() =>
      expect(screen.getByTestId('stage-frames')).toHaveAttribute('data-status', 'done'),
    )
    // The gate is the api's: still not viewable, so Open is still refused and
    // says why.
    expect(screen.getByRole('button', { name: /^Open/ })).toBeDisabled()
    expect(screen.getByTestId('step-ingesting')).toHaveAttribute('data-status', 'running')

    // The job finishes. `job.done` re-seeds — the row now carries its counts
    // and the api's viewable verdict — and the card converges without a reload.
    sdk.listMeetings.mockResolvedValue({
      data: {
        meetings: [
          meetingRow({
            status: 'succeeded',
            viewable: true,
            momentCount: 6,
            stages: [
              { name: 'probe', status: 'done', error: null },
              { name: 'frames', status: 'done', error: null },
              { name: 'transcribe', status: 'done', error: null },
            ],
          }),
        ],
      },
      error: undefined,
    })
    await act(async () => {
      stream.onEvent?.({
        jobId: JOB,
        event: 'job.done',
        jobStatus: 'succeeded',
        viewable: true,
        error: null,
      } as JobEvent)
    })

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /^Open/ })).toBeEnabled(),
    )
    expect(screen.getByTestId('stage-transcribe')).toHaveAttribute('data-status', 'done')
    expect(screen.getByText('6 moments')).toBeInTheDocument()
    expect(screen.getByTestId('step-ingesting')).toHaveAttribute('data-status', 'done')
  })

  it('re-seeds after the stream baseline races an in-flight stale seed', async () => {
    let resolveFirst: ((value: unknown) => void) | undefined
    sdk.listMeetings
      .mockReturnValueOnce(
        new Promise((resolve) => {
          resolveFirst = resolve as (value: unknown) => void
        }),
      )
      .mockResolvedValueOnce({
        data: {
          meetings: [meetingRow({ status: 'succeeded', viewable: true })],
        },
        error: undefined,
      })
    await launch(
      acquisition({ status: 'posted', result: 'created', jobId: JOB, meetingId: MEETING }),
    )
    await waitFor(() => expect(sdk.listMeetings).toHaveBeenCalledTimes(1))

    // The stream takes its silent baseline after the job transition and emits
    // only its connected comment while the older seed is still in flight.
    act(() => stream.onAlive?.())
    await act(async () => {
      resolveFirst?.({ data: { meetings: [meetingRow()] }, error: undefined })
    })

    await waitFor(() => expect(sdk.listMeetings).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(screen.getByTestId('acquired-meeting')).toHaveAttribute('data-viewable', 'true'))
  })

  it('says the meeting row does not exist yet rather than inventing one', async () => {
    sdk.listMeetings.mockResolvedValue({
      data: {
        meetings: [meetingRow({ meetingId: null, title: null, status: 'queued', stages: [] })],
      },
      error: undefined,
    })
    await launch(
      acquisition({ status: 'posted', result: 'created', jobId: JOB, meetingId: null }),
    )

    await waitFor(() => expect(screen.getByTestId('meeting-pending')).toBeInTheDocument())
    expect(screen.queryByTestId('acquired-meeting')).not.toBeInTheDocument()
    expect(screen.getByTestId('step-ingesting')).toHaveAttribute('data-status', 'queued')
  })

  it('reports an already-ingested video as posted with nothing downloaded', async () => {
    sdk.listMeetings.mockResolvedValue({
      data: { meetings: [meetingRow({ status: 'succeeded', viewable: true })] },
      error: undefined,
    })
    await launch(
      acquisition({ status: 'posted', result: 'exists', jobId: JOB, meetingId: MEETING }),
    )

    expect(screen.getByTestId('already-in-corpus')).toHaveTextContent(
      'Already in the corpus — nothing downloaded.',
    )
    await waitFor(() => expect(screen.getByTestId('acquired-meeting')).toBeInTheDocument())
  })

  it('names the rule when the tool refuses, and unlocks the form', async () => {
    await launch(
      acquisition({
        status: 'failed',
        logTail: ['yt-dlp: duration 4:02:17', 'youtube-drop: duration over cap'],
        refusal: {
          rule: 'duration-cap',
          detail: '4h 02m exceeds the configured 180 minutes.',
          remediation: 'Raise acquisition.youtube.maxDurationMinutes in config.yaml.',
        },
      }),
    )

    const box = screen.getByTestId('acquisition-refusal')
    expect(box).toHaveTextContent('duration-cap')
    expect(box).toHaveTextContent('4h 02m exceeds the configured 180 minutes.')
    expect(box).toHaveTextContent('Raise acquisition.youtube.maxDurationMinutes in config.yaml.')

    expect(screen.getByTestId('step-posted')).toHaveAttribute('data-status', 'failed')
    // Ingestion never started, so its bar does not claim otherwise.
    expect(screen.getByTestId('step-ingesting')).toHaveAttribute('data-status', 'queued')
    expect(screen.getByTestId('youtube-url')).not.toHaveAttribute('readonly')
    // The log stays for diagnosis but was never the source of the refusal.
    expect(screen.getByTestId('acquisition-log')).toHaveTextContent('youtube-drop: duration over cap')
  })

  it('does not claim nothing was finalized when intake fails after acquisition', async () => {
    await launch(
      acquisition({
        status: 'failed',
        refusal: {
          rule: 'intake-failed',
          detail: 'POST /ingests returned 503.',
          remediation: 'The drop is finalized; re-POST this exact drop rather than re-downloading it.',
        },
      }),
    )

    expect(screen.getByTestId('acquisition-refusal')).toHaveTextContent('The drop is finalized')
    expect(
      screen.queryByText('Nothing was downloaded, nothing minted, no meeting row exists.'),
    ).not.toBeInTheDocument()
  })

  it('keeps the last state when a poll fails, and resumes on Retry', async () => {
    await launch(acquisition({ status: 'running' }))
    expect(screen.getByTestId('step-running')).toHaveAttribute('data-status', 'running')

    sdk.getAcquisition.mockRejectedValueOnce(new TypeError('Failed to fetch'))
    await settlePoll()

    expect(screen.getByTestId('poll-transport')).toHaveTextContent(
      `Cannot reach the api at ${API_BASE}: Failed to fetch`,
    )
    // Nothing is inferred: the stepper still says what it last knew.
    expect(screen.getByTestId('step-running')).toHaveAttribute('data-status', 'running')

    queueStatuses(acquisition({ status: 'posted', result: 'created', jobId: JOB }))
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    await waitFor(() =>
      expect(screen.getByTestId('step-posted')).toHaveAttribute('data-status', 'done'),
    )
    expect(screen.queryByTestId('poll-transport')).not.toBeInTheDocument()
  })

  it('keeps the last state and retries when a poll returns Problem Details', async () => {
    await launch(acquisition({ status: 'running' }))
    sdk.getAcquisition.mockResolvedValueOnce({
      data: undefined,
      error: {
        type: 'urn:meetingminer:problem:acquisition-state-unreadable',
        title: 'Acquisition state unreadable',
        detail: 'The status file could not be read.',
        remediation: 'Retry after the api host recovers.',
      },
    })
    await settlePoll()

    expect(screen.getByTestId('poll-refusal')).toHaveTextContent('Acquisition state unreadable')
    expect(screen.getByTestId('step-running')).toHaveAttribute('data-status', 'running')

    queueStatuses(acquisition({ status: 'posted', result: 'created', jobId: JOB }))
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    await waitFor(() =>
      expect(screen.getByTestId('step-posted')).toHaveAttribute('data-status', 'done'),
    )
  })
})

describe('Add-meeting, the source tabs', () => {
  it('carries all four sources and says what the file tabs wait on', async () => {
    render(<AddMeeting />)
    const tablist = screen.getByRole('tablist', { name: 'Meeting source' })
    expect(within(tablist).getAllByRole('tab').map((tab) => tab.textContent)).toEqual([
      'YouTube URL',
      'Local files',
      'Zoom export',
      'Teams export',
    ])

    await user.click(screen.getByRole('tab', { name: 'Zoom export' }))
    expect(screen.getByTestId('panel-zoom')).not.toHaveAttribute('hidden')
    // A tab with nothing in it and no sentence would be a dead end.
    expect(screen.getByTestId('panel-zoom')).toHaveTextContent('Not available yet')
    expect(screen.getByTestId('panel-zoom')).toHaveTextContent('make mint-drop')
    expect(screen.getByTestId('panel-youtube')).toHaveAttribute('hidden')
  })

  it('moves with the arrow keys and never submits on a switch', async () => {
    sdk.probeAcquisition.mockResolvedValue({ data: probeResult(), error: undefined })
    render(<AddMeeting />)
    await typeUrl(VIDEO_URL)

    const youtubeTab = screen.getByRole('tab', { name: 'YouTube URL' })
    youtubeTab.focus()
    await user.keyboard('{ArrowRight}')
    expect(screen.getByRole('tab', { name: 'Local files' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    expect(sdk.startAcquisition).not.toHaveBeenCalled()

    // Back again: a partially filled tab keeps its state.
    await user.keyboard('{ArrowLeft}')
    expect(screen.getByTestId('youtube-url')).toHaveValue(VIDEO_URL)
    expect(screen.getByTestId('probe-answered')).toBeInTheDocument()
    // And it was probed once, not once per tab switch.
    expect(sdk.probeAcquisition).toHaveBeenCalledTimes(1)
  })
})
