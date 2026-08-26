import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { JobEvent, MeetingListItem } from '@/client/types.gen'
import { createFakeStream, type FakeStream, type StreamOptions } from '@/test/fakeStream'
import { MeetingsList, SEED_TIMEOUT_MS } from './MeetingsList'
import { applyEvent, blockedReason, countParts, durationLabel, visibleRows } from './rows'

const sdk = vi.hoisted(() => ({
  listMeetings: vi.fn(),
  streamJobEvents: vi.fn(),
}))

vi.mock('@/client/sdk.gen', () => ({
  listMeetings: sdk.listMeetings,
  getMeetingDrilldown: vi.fn(),
  streamJobEvents: sdk.streamJobEvents,
  getHealth: vi.fn(),
  getJob: vi.fn(),
  createIngest: vi.fn(),
  listMeetingMoments: vi.fn(),
  getMoment: vi.fn(),
  listParticipants: vi.fn(),
  renameParticipant: vi.fn(),
  mergeParticipants: vi.fn(),
}))

const STAGE_NAMES = [
  'probe', 'frames', 'ocr', 'screens', 'transcribe', 'align', 'moments', 'extract',
] as const
const VIDEO_ONLY = ['probe', 'frames', 'ocr', 'screens', 'transcribe']

function stages(overrides: Record<string, { status: string; error?: string | null }> = {}) {
  return STAGE_NAMES.map((name) => ({
    name,
    status: overrides[name]?.status ?? 'queued',
    error: overrides[name]?.error ?? null,
  }))
}

function meeting(overrides: Partial<MeetingListItem> = {}): MeetingListItem {
  return {
    jobId: 'job-1',
    meetingId: null,
    title: 'Daily Standup',
    sourceId: 'source-1',
    corpus: 'real',
    startedAt: '2026-08-05T12:00:19Z',
    startedAtPrecision: 'second',
    hasRecording: true,
    status: 'queued',
    error: null,
    stages: stages(),
    viewable: false,
    ...overrides,
  }
}

function event(overrides: Partial<JobEvent> = {}): JobEvent {
  return {
    event: 'job.stage',
    jobId: 'job-1',
    jobStatus: 'running',
    viewable: false,
    stage: null,
    status: null,
    error: null,
    ...overrides,
  }
}

// Every connection this test file opened, newest last. Reset per test, so a
// wait for "a stream exists" can never be satisfied by the previous test's.
let streams: FakeStream[]

/** The connection currently open. */
function live(): FakeStream {
  expect(streams.length).toBeGreaterThan(0)
  return streams[streams.length - 1]
}

function seedWith(...rows: MeetingListItem[]) {
  sdk.listMeetings.mockResolvedValue({ data: { meetings: rows }, error: undefined })
}

/** The default: the api is up and greets every connection, as it really does. */
function connectableStream() {
  sdk.streamJobEvents.mockImplementation(async (options: StreamOptions) => {
    const stream = createFakeStream(options)
    streams.push(stream)
    // The api opens every connection with a `connected` comment, once its
    // baseline snapshot has been taken.
    queueMicrotask(() => stream.comment())
    return { stream: stream.stream }
  })
}

beforeEach(() => {
  streams = []
  sdk.listMeetings.mockReset()
  sdk.streamJobEvents.mockReset()
  connectableStream()
})

async function renderList() {
  render(<MeetingsList />)
  await waitFor(() => expect(sdk.listMeetings).toHaveBeenCalled())
  await waitFor(() => expect(streams).toHaveLength(1))
}

function stageStatus(name: string): string | null {
  return screen.getByTestId(`stage-${name}`).getAttribute('data-status')
}

/** The open affordance of the default fixture row, by its accessible name. */
function openButton(label = 'Daily Standup'): HTMLElement {
  return screen.getByRole('button', { name: `Open ${label}` })
}

describe('MeetingsList', () => {
  it('names how meetings arrive when the corpus is empty', async () => {
    seedWith()
    await renderList()

    const empty = await screen.findByTestId('empty-state')
    expect(empty).toHaveTextContent(/puller/i)
    expect(empty).toHaveTextContent(/ingests/)
  })

  it('advances stage progress live from job.stage events, with no reload and no polling', async () => {
    seedWith(meeting())
    await renderList()
    await screen.findByTestId('meeting-job-1')
    expect(stageStatus('probe')).toBe('queued')

    live().emit(event({ stage: 'probe', status: 'running' }))
    await waitFor(() => expect(stageStatus('probe')).toBe('running'))

    live().emit(event({ stage: 'probe', status: 'done' }))
    live().emit(event({ stage: 'frames', status: 'running' }))
    await waitFor(() => expect(stageStatus('frames')).toBe('running'))
    expect(stageStatus('probe')).toBe('done')

    // Progress came from the stream: the list was fetched exactly once.
    expect(sdk.listMeetings).toHaveBeenCalledTimes(1)
  })

  it('renders skipped stages as skipped — distinct from done and from failed', async () => {
    const skipped = Object.fromEntries(VIDEO_ONLY.map((name) => [name, { status: 'skipped' }]))
    seedWith(
      meeting({
        hasRecording: false,
        viewable: true,
        stages: stages({ ...skipped, align: { status: 'done' }, moments: { status: 'done' } }),
      }),
    )
    await renderList()
    await screen.findByTestId('meeting-job-1')

    for (const name of VIDEO_ONLY) {
      expect(stageStatus(name)).toBe('skipped')
    }
    expect(stageStatus('align')).toBe('done')
    // Not an error state, and labelled as its own thing.
    expect(screen.queryByTestId('stage-error-probe')).toBeNull()
    expect(screen.getByTestId('transcript-only-job-1')).toBeInTheDocument()
    // Skipped and done are drawn differently, not merely coloured differently.
    const skippedBar = screen.getByTestId('stage-probe').querySelector('span')
    const doneBar = screen.getByTestId('stage-align').querySelector('span')
    expect(skippedBar?.className).not.toEqual(doneBar?.className)
    // …and the meeting is still openable.
    expect(openButton()).toBeEnabled()
  })

  it('displays a failed stage error verbatim against that stage', async () => {
    const recorded = 'ffprobe exited 1: moov atom not found'
    seedWith(meeting())
    await renderList()
    await screen.findByTestId('meeting-job-1')

    live().emit(
      event({ stage: 'probe', status: 'failed', error: recorded, jobStatus: 'failed' }),
    )
    live().emit(
      event({
        event: 'job.error',
        stage: 'probe',
        status: 'failed',
        error: recorded,
        jobStatus: 'failed',
      }),
    )

    const shown = await screen.findByTestId('stage-error-probe')
    expect(shown).toHaveTextContent(recorded)
    expect(stageStatus('probe')).toBe('failed')
  })

  it('keeps a meeting unopenable, with the reason stated, until it is viewable', async () => {
    seedWith(meeting({ stages: stages({ probe: { status: 'done' } }) }))
    await renderList()
    await screen.findByTestId('meeting-job-1')

    const open = openButton()
    expect(open).toBeDisabled()
    expect(screen.getByText(/Evidence is still being built — frames is queued\./)).toBeInTheDocument()

    // The gate flips on the api's own verdict, carried by the event — the
    // list never recomputes viewability from the stages it happens to hold.
    live().emit(event({ stage: 'moments', status: 'done', viewable: true }))
    await waitFor(() => expect(openButton()).toBeEnabled())
    expect(screen.queryByText(/Evidence is still being built/)).toBeNull()
    expect(sdk.listMeetings).toHaveBeenCalledTimes(1)
  })

  it('hands the row to onOpen when a viewable meeting is opened', async () => {
    // The other half of the gate, and the half the component actually owns:
    // a disabled button swallows a click on its own, so asserting *that* would
    // pass with the handler deleted entirely.
    const onOpen = vi.fn()
    seedWith(meeting({ viewable: true }))
    render(<MeetingsList onOpen={onOpen} />)
    await screen.findByTestId('meeting-job-1')

    await userEvent.click(openButton())
    expect(onOpen).toHaveBeenCalledTimes(1)
    expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({ jobId: 'job-1' }))
  })

  it('gives each row an open affordance named for its meeting', async () => {
    // Every row rendering a button named just "Open" leaves them
    // indistinguishable to a screen reader.
    seedWith(
      meeting({ viewable: true }),
      meeting({ jobId: 'job-2', title: 'Architecture Review', viewable: true }),
    )
    await renderList()
    await screen.findByTestId('meeting-job-2')

    expect(openButton('Daily Standup')).toBeEnabled()
    expect(openButton('Architecture Review')).toBeEnabled()
  })

  it('falls back to the source id when a meeting has no title yet', async () => {
    seedWith(meeting({ title: null, viewable: true }))
    await renderList()
    await screen.findByTestId('meeting-job-1')

    expect(openButton('source-1')).toBeEnabled()
  })

  it('renders an unrecognised stage status as unknown rather than as queued', async () => {
    // Folding it into `queued` would draw a stage this build cannot interpret
    // as one it definitely can, and `blockedReason` would call it "not started".
    seedWith(meeting({ stages: stages({ probe: { status: 'quarantined' } }) }))
    await renderList()
    await screen.findByTestId('meeting-job-1')

    expect(stageStatus('probe')).toBe('unknown')
    expect(screen.getByTestId('stage-probe')).toHaveAttribute('data-raw-status', 'quarantined')
  })

  it('re-seeds when an event names a job it has never seen', async () => {
    seedWith(meeting())
    await renderList()
    await screen.findByTestId('meeting-job-1')

    seedWith(meeting({ jobId: 'job-2', title: 'Second' }), meeting())
    live().emit(event({ jobId: 'job-2', stage: 'probe', status: 'queued' }))

    await screen.findByTestId('meeting-job-2')
    expect(screen.getAllByTestId(/^meeting-/)).toHaveLength(2)
  })

  it('does not lose a stage event that overtakes the first seed', async () => {
    // The seed reads the list while `probe` is still queued; before that
    // response reaches the browser the worker starts `probe` and the api sends
    // `job.stage`. The event lands with no rows to apply it to, so the older
    // snapshot would otherwise win and the row would report `queued` until
    // some later transition happened to correct it.
    let releaseSeed = () => {}
    const held = new Promise<void>((resolve) => {
      releaseSeed = resolve
    })
    sdk.listMeetings
      .mockImplementationOnce(async () => {
        await held
        return { data: { meetings: [meeting()] }, error: undefined }
      })
      .mockResolvedValue({
        data: { meetings: [meeting({ stages: stages({ probe: { status: 'running' } }) })] },
        error: undefined,
      })

    render(<MeetingsList />)
    await waitFor(() => expect(streams).toHaveLength(1))

    // Delivered *and consumed* while `rows` is still null — that ordering is
    // the race. Flushing it after the seed resolves would exercise the
    // ordinary apply-to-existing-rows path and prove nothing.
    live().emit(event({ stage: 'probe', status: 'running' }))
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0))
    })
    expect(screen.getByText('Loading meetings…')).toBeInTheDocument()

    await act(async () => {
      releaseSeed()
      await new Promise((resolve) => setTimeout(resolve, 0))
    })

    // Converges on its own, without waiting for another pipeline transition.
    await waitFor(() => expect(stageStatus('probe')).toBe('running'))
    expect(sdk.listMeetings).toHaveBeenCalledTimes(2)
  })

  it('does not strand a meeting unopenable when job.done overtakes the first seed', async () => {
    // The terminal case of the race above, and the one that never heals:
    // `job.done` is the last event a job sends, so dropping it leaves
    // `viewable` false with no later event to correct it — Open stays disabled
    // forever on a meeting that is fully ingested.
    let releaseSeed = () => {}
    const held = new Promise<void>((resolve) => {
      releaseSeed = resolve
    })
    const settled = stages(
      Object.fromEntries(
        STAGE_NAMES.filter((name) => name !== 'extract').map((name) => [name, { status: 'done' }]),
      ),
    )
    sdk.listMeetings
      .mockImplementationOnce(async () => {
        await held
        return { data: { meetings: [meeting()] }, error: undefined }
      })
      .mockResolvedValue({
        data: { meetings: [meeting({ stages: settled, viewable: true })] },
        error: undefined,
      })

    render(<MeetingsList />)
    await waitFor(() => expect(streams).toHaveLength(1))

    live().emit(event({ event: 'job.done', viewable: true }))
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0))
    })
    expect(screen.getByText('Loading meetings…')).toBeInTheDocument()

    await act(async () => {
      releaseSeed()
      await new Promise((resolve) => setTimeout(resolve, 0))
    })

    await waitFor(() => expect(openButton()).toBeEnabled())
    expect(sdk.listMeetings).toHaveBeenCalledTimes(2)
  })

  it('names a connection error and keeps the rows it already had', async () => {
    seedWith(meeting({ title: 'Kept Meeting' }))
    await renderList()
    await screen.findByTestId('meeting-job-1')

    live().fail(new Error('Failed to fetch'))
    live().fail(new Error('Failed to fetch'))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Failed to fetch')
    expect(alert).toHaveTextContent('http://localhost:8000')
    // Rows survive the outage rather than being blanked.
    expect(screen.getByText('Kept Meeting')).toBeInTheDocument()
  })

  it('re-seeds on reconnect without duplicating or losing rows', async () => {
    seedWith(meeting())
    await renderList()
    await screen.findByTestId('meeting-job-1')

    live().fail(new Error('network down'))
    live().fail(new Error('network down'))
    await screen.findByRole('alert')

    // The same two meetings the api holds, returned again on reconnect.
    seedWith(meeting(), meeting({ jobId: 'job-2', title: 'Second' }))
    live().comment()

    await screen.findByTestId('meeting-job-2')
    expect(screen.getAllByTestId(/^meeting-/)).toHaveLength(2)
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
  })

  it('recovers from a failed first load once the api starts answering', async () => {
    // The wedge this guards: the seed fails while the api is down and the
    // stream never connects, so `rows` stays null — and on an idle system no
    // event will ever arrive to prompt another attempt. A heartbeat is the
    // only signal there is, and it has to be enough.
    sdk.streamJobEvents.mockImplementation(async (options: StreamOptions) => {
      const stream = createFakeStream(options)
      streams.push(stream)
      return { stream: stream.stream } // no greeting: the api is down
    })
    sdk.listMeetings.mockRejectedValue(new Error('connection refused'))

    render(<MeetingsList />)
    await screen.findByRole('alert')
    expect(screen.getByText('Loading meetings…')).toBeInTheDocument()
    expect(sdk.listMeetings).toHaveBeenCalledTimes(1)

    // Still down: a burst of frames must not become a burst of fetches.
    for (let i = 0; i < 5; i += 1) live().comment()
    await waitFor(() => expect(sdk.listMeetings).toHaveBeenCalledTimes(2))
    expect(sdk.listMeetings).toHaveBeenCalledTimes(2)

    seedWith(meeting({ title: 'Recovered' }))
    live().comment()

    expect(await screen.findByText('Recovered')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
  })

  it('names the timeout when the api accepts the request and never answers', async () => {
    // shouldAdvanceTime: testing-library's `waitFor` polls on a timer it does
    // not know is faked.
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      // A request that hangs rather than failing: only the seed's own timeout
      // ends it, and only `AbortSignal.any` delivers that to the fetch.
      sdk.listMeetings.mockImplementation(
        ({ signal }: { signal: AbortSignal }) =>
          new Promise((_resolve, reject) => {
            signal.addEventListener('abort', () => reject(signal.reason))
          }),
      )
      render(<MeetingsList />)
      await waitFor(() => expect(sdk.listMeetings).toHaveBeenCalled())

      await act(async () => {
        await vi.advanceTimersByTimeAsync(SEED_TIMEOUT_MS + 100)
      })

      const alert = await screen.findByRole('alert')
      expect(alert).toHaveTextContent(`timed out after ${SEED_TIMEOUT_MS}ms`)
    } finally {
      vi.useRealTimers()
    }
  })

  it('keeps rows when the seed itself fails', async () => {
    seedWith(meeting({ title: 'Kept Meeting' }))
    await renderList()
    await screen.findByTestId('meeting-job-1')

    sdk.listMeetings.mockRejectedValue(new Error('connection refused'))
    live().emit(event({ event: 'job.done', jobStatus: 'running', viewable: true }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('connection refused')
    expect(screen.getByText('Kept Meeting')).toBeInTheDocument()
  })
})

describe('evidence cards', () => {
  it('renders poster, duration, and served counts on a card', async () => {
    seedWith(
      meeting({
        viewable: true,
        durationMs: 3_720_000,
        posterScreenshotPath: 'meetings/meeting-1/screenshots/1.jpg',
        posterScreenshotId: 'screenshot-1',
        momentCount: 12,
        screenshotCount: 158,
        artifactCount: 7,
        participantCount: 4,
      }),
    )
    await renderList()
    await screen.findByTestId('meeting-job-1')

    const poster = screen.getByTestId('poster-job-1') as HTMLImageElement
    expect(poster.src).toContain('/media/meetings/meeting-1/screenshots/1.jpg')
    expect(screen.getByTestId('counts-job-1')).toHaveTextContent(
      '12 moments · 158 screens · 7 artifacts · 4 participants',
    )
    expect(screen.getByText(/1h 02m/)).toBeInTheDocument()
    expect(screen.getByTestId('meetings-count')).toHaveTextContent('1')
  })

  it('omits counts it was not served rather than inventing zeros', async () => {
    seedWith(meeting({ viewable: true }))
    await renderList()
    await screen.findByTestId('meeting-job-1')

    expect(screen.queryByTestId('counts-job-1')).toBeNull()
    expect(screen.queryByTestId('poster-job-1')).toBeNull()
    expect(screen.getByTestId('no-poster-job-1')).toHaveTextContent('No screens captured yet.')
  })

  it('says in one sentence why a transcript-only meeting has no poster', async () => {
    seedWith(meeting({ viewable: true, hasRecording: false }))
    await renderList()
    await screen.findByTestId('meeting-job-1')

    expect(screen.getByTestId('no-poster-job-1')).toHaveTextContent(
      'Transcript only — no recording, so no screens were captured.',
    )
    expect(screen.getByTestId('transcript-only-job-1')).toBeInTheDocument()
  })

  it('filters cards by corpus and restores them with All', async () => {
    seedWith(
      meeting({ viewable: true }),
      meeting({ jobId: 'job-2', title: 'Demo Run', corpus: 'demo', viewable: true }),
    )
    await renderList()
    await screen.findByTestId('meeting-job-2')

    await userEvent.click(screen.getByTestId('corpus-filter-demo'))
    expect(screen.queryByTestId('meeting-job-1')).toBeNull()
    expect(screen.getByTestId('meeting-job-2')).toBeInTheDocument()
    expect(screen.getByTestId('meetings-count')).toHaveTextContent('1 of 2')

    await userEvent.click(screen.getByTestId('corpus-filter-all'))
    expect(screen.getByTestId('meeting-job-1')).toBeInTheDocument()
    expect(screen.getAllByTestId(/^meeting-/)).toHaveLength(2)
  })

  it('keeps applying stream events to a filtered-out meeting', async () => {
    // The filter is a view, not a subscription: an event for a hidden row
    // still lands, so lifting the filter shows current progress, not stale.
    seedWith(
      meeting({ viewable: true }),
      meeting({ jobId: 'job-2', title: 'Demo Run', corpus: 'demo', viewable: true }),
    )
    await renderList()
    await screen.findByTestId('meeting-job-2')

    await userEvent.click(screen.getByTestId('corpus-filter-demo'))
    live().emit(event({ stage: 'probe', status: 'running' }))
    await userEvent.click(screen.getByTestId('corpus-filter-all'))

    // Scoped to the card: with two meetings rendered, `stage-probe` exists
    // once per row, and the event above named job-1.
    await waitFor(() =>
      expect(
        within(screen.getByTestId('meeting-job-1'))
          .getByTestId('stage-probe')
          .getAttribute('data-status'),
      ).toBe('running'),
    )
    expect(sdk.listMeetings).toHaveBeenCalledTimes(1)
  })

  it('sorts by recency, newest first, and toggles to oldest first', async () => {
    seedWith(
      meeting({ startedAt: '2026-08-01T09:00:00Z', viewable: true }),
      meeting({
        jobId: 'job-2',
        title: 'Newer Meeting',
        startedAt: '2026-08-10T09:00:00Z',
        viewable: true,
      }),
    )
    await renderList()
    await screen.findByTestId('meeting-job-2')

    const order = () => screen.getAllByTestId(/^meeting-/).map((el) => el.getAttribute('data-testid'))
    expect(order()).toEqual(['meeting-job-2', 'meeting-job-1'])

    await userEvent.click(screen.getByTestId('sort-toggle'))
    expect(order()).toEqual(['meeting-job-1', 'meeting-job-2'])
  })
})

describe('durationLabel', () => {
  it('renders nothing for a duration the api did not serve', () => {
    expect(durationLabel(null)).toBeNull()
    expect(durationLabel(undefined)).toBeNull()
  })

  it('renders seconds, minutes, and hours in the terse idiom', () => {
    expect(durationLabel(35_000)).toBe('35s')
    expect(durationLabel(42 * 60_000)).toBe('42m')
    expect(durationLabel(3_720_000)).toBe('1h 02m')
  })
})

describe('countParts', () => {
  it('keeps only served counts, pluralised', () => {
    expect(countParts(meeting({ momentCount: 1, artifactCount: 7 }))).toEqual([
      '1 moment',
      '7 artifacts',
    ])
    expect(countParts(meeting())).toEqual([])
  })
})

describe('visibleRows', () => {
  it('sorts rows with no start time last in both directions', () => {
    const rows = [
      meeting({ jobId: 'undated', startedAt: null }),
      meeting({ jobId: 'old', startedAt: '2026-08-01T09:00:00Z' }),
      meeting({ jobId: 'new', startedAt: '2026-08-10T09:00:00Z' }),
    ]
    expect(visibleRows(rows, null, 'newest').map((r) => r.jobId)).toEqual([
      'new', 'old', 'undated',
    ])
    expect(visibleRows(rows, null, 'oldest').map((r) => r.jobId)).toEqual([
      'old', 'new', 'undated',
    ])
  })
})

describe('applyEvent', () => {
  it('returns null for a job the list has never seen', () => {
    expect(applyEvent([meeting()], event({ jobId: 'unknown' }))).toBeNull()
  })

  it('updates only the named stage and never mutates the input', () => {
    const rows = [meeting()]
    const next = applyEvent(rows, event({ stage: 'ocr', status: 'running' }))
    expect(next?.[0].stages.find((s) => s.name === 'ocr')?.status).toBe('running')
    expect(next?.[0].stages.find((s) => s.name === 'probe')?.status).toBe('queued')
    expect(rows[0].stages.find((s) => s.name === 'ocr')?.status).toBe('queued')
  })

  it('takes viewability from the event rather than recomputing it', () => {
    const next = applyEvent([meeting()], event({ event: 'job.done', viewable: true }))
    expect(next?.[0].viewable).toBe(true)
  })

  it('clears the job error once the job is no longer failed', () => {
    const failed = meeting({ status: 'failed', error: 'stage probe failed: boom' })
    const next = applyEvent([failed], event({ jobStatus: 'queued', stage: 'probe', status: 'queued' }))
    expect(next?.[0].error).toBeNull()
  })

  it('records a stage-less job failure on the row, leaving every stage alone', () => {
    // The runner fails a job with no stage implicated at three sites (an
    // unreadable drop, a meeting mint that raised, video-evidence cleanup),
    // and the job row's own error is then the only text there is.
    const recorded = 'source drop unreadable: metadata.json is not valid JSON'
    const next = applyEvent(
      [meeting()],
      event({
        event: 'job.error',
        jobStatus: 'failed',
        stage: null,
        status: null,
        error: recorded,
      }),
    )
    expect(next?.[0].error).toBe(recorded)
    expect(next?.[0].status).toBe('failed')
    expect(next?.[0].stages.every((stage) => stage.status === 'queued')).toBe(true)
  })

  it('writes a stage error exactly as the event sends it', () => {
    // One rule for both stage fields: the event carries that stage's complete
    // current reading. A null error is a real value — it is how a requeue
    // clears a recorded failure — so holding the previous text would leave a
    // resolved error on screen forever.
    const failed = meeting({ stages: stages({ probe: { status: 'failed', error: 'boom' } }) })

    const restated = applyEvent([failed], event({ stage: 'probe', status: 'failed', error: 'boom' }))
    expect(restated?.[0].stages.find((s) => s.name === 'probe')?.error).toBe('boom')

    const requeued = applyEvent(
      [failed],
      event({ jobStatus: 'queued', stage: 'probe', status: 'queued', error: null }),
    )
    expect(requeued?.[0].stages.find((s) => s.name === 'probe')?.error).toBeNull()
    expect(requeued?.[0].stages.find((s) => s.name === 'probe')?.status).toBe('queued')
  })
})

describe('blockedReason', () => {
  it('names the stage that is holding the meeting up', () => {
    const row = meeting({ stages: stages({ probe: { status: 'done' }, frames: { status: 'running' } }) })
    expect(blockedReason(row)).toBe('Evidence is still being built — frames is running.')
  })

  it('names the failure when a stage failed', () => {
    const row = meeting({ stages: stages({ probe: { status: 'failed', error: 'boom' } }) })
    expect(blockedReason(row)).toBe('Ingestion failed at probe — nothing to open.')
  })

  it('reports a stage-less job failure as a failure, not as progress', () => {
    // Every checkpoint stays `queued` on this path, so reading the stages
    // alone would claim evidence is being built right beside the job error.
    const row = meeting({ status: 'failed', error: 'source drop unreadable' })
    expect(blockedReason(row)).toBe('Ingestion failed — nothing to open.')
  })

  it('says there are no checkpoints when the job has none', () => {
    expect(blockedReason(meeting({ stages: [] }))).toBe(
      'Ingestion has not started — no checkpoints yet.',
    )
  })

  it('does not claim ingestion never started when every stage has settled', () => {
    const settled = STAGE_NAMES.map((name) => ({ name, status: 'done', error: null }))
    expect(blockedReason(meeting({ stages: settled }))).toBe(
      'Every stage has settled, but the api has not marked this meeting viewable.',
    )
  })
})
