import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type {
  DrilldownSegment,
  JobEvent,
  ParticipantRow,
  SpeakerAssignmentResponse,
  SpeakerTag,
} from '@/client/types.gen'
import { SpeakerNaming } from './SpeakerNaming'

const sdk = vi.hoisted(() => ({
  listMeetingSpeakers: vi.fn(),
  getMeetingDrilldown: vi.fn(),
  listParticipants: vi.fn(),
  assignMeetingSpeaker: vi.fn(),
  getJob: vi.fn(),
}))

vi.mock('@/client/sdk.gen', () => ({
  listMeetingSpeakers: sdk.listMeetingSpeakers,
  getMeetingDrilldown: sdk.getMeetingDrilldown,
  listParticipants: sdk.listParticipants,
  assignMeetingSpeaker: sdk.assignMeetingSpeaker,
  getJob: sdk.getJob,
  streamJobEvents: vi.fn(),
}))

/**
 * The job stream is mocked at the hook rather than at the transport: this
 * screen's contract with it is "fold these frames", and `useJobEvents` has its
 * own tests for holding the connection. `emit` is the api pushing a frame.
 */
const stream = vi.hoisted(() => ({
  onEvent: null as ((event: JobEvent) => void) | null,
  onResync: null as (() => void) | null,
  connection: { kind: 'live' as const } as
    | { kind: 'live' }
    | { kind: 'lost'; message: string },
}))

vi.mock('@/features/meetings/useJobEvents', () => ({
  useJobEvents: ({
    onEvent,
    onResync,
  }: {
    onEvent: (event: JobEvent) => void
    onResync: () => void
  }) => {
    stream.onEvent = onEvent
    stream.onResync = onResync
    return stream.connection
  },
}))

function emit(event: Partial<JobEvent> & Pick<JobEvent, 'event' | 'jobId'>) {
  act(() => {
    stream.onEvent?.({ jobStatus: 'running', viewable: false, ...event } as JobEvent)
  })
}

function resync() {
  act(() => stream.onResync?.())
}

const MEETING = '0190a0f0-7c1e-7000-8000-0000000000aa'
const playMedia = vi
  .spyOn(HTMLMediaElement.prototype, 'play')
  .mockResolvedValue(undefined)

function tag(overrides: Partial<SpeakerTag> = {}): SpeakerTag {
  return {
    speakerLabel: 'SPEAKER_00',
    speakerResolution: 'placeholder',
    participantId: null,
    displayName: null,
    talkTimeMs: 1_431_000,
    segmentCount: 112,
    sampleOffsetsMs: [252_000, 1_180_000, 2_467_000],
    ...overrides,
  }
}

function participant(overrides: Partial<ParticipantRow> = {}): ParticipantRow {
  return {
    id: 'p-1',
    identityKey: 'name:priya natarajan',
    displayName: 'Priya Natarajan',
    normalizedName: 'priya natarajan',
    mergedIntoParticipantId: null,
    createdAt: '2026-08-05T12:00:00Z',
    updatedAt: '2026-08-05T12:00:00Z',
    ...overrides,
  }
}

function segment(overrides: Partial<DrilldownSegment> = {}): DrilldownSegment {
  return {
    segmentId: 's-1',
    ordinal: 1,
    startMs: 252_000,
    endMs: 260_000,
    speakerLabel: 'SPEAKER_00',
    speakerResolution: 'placeholder',
    participantId: null,
    text: 'The retrieval split held up.',
    momentId: null,
    ...overrides,
  }
}

function assignment(
  overrides: Partial<SpeakerAssignmentResponse> = {},
): SpeakerAssignmentResponse {
  return {
    meetingId: MEETING,
    speakerLabel: 'SPEAKER_00',
    participantId: 'p-1',
    displayName: 'Priya Natarajan',
    jobId: 'job-1',
    rearmedStages: ['align', 'moments', 'extract'],
    acceptedWhileUnviewable: false,
    previousJobStatus: 'done',
    ...overrides,
  }
}

function job(
  overrides: Partial<{
    jobId: string
    status: string
    error: string | null
    stages: Array<{ name: string; status: string; error?: string | null }>
  }> = {},
) {
  return {
    jobId: 'job-1',
    status: 'queued',
    sourceId: 'source-1',
    dropPath: null,
    corpus: 'real',
    error: null,
    createdAt: '2026-08-21T09:00:00Z',
    stages: [
      { name: 'align', status: 'queued', error: null },
      { name: 'moments', status: 'queued', error: null },
      { name: 'extract', status: 'queued', error: null },
    ],
    ...overrides,
  }
}

const NOT_VIEWABLE = {
  type: 'urn:meetingminer:problem:meeting-not-viewable',
  title: 'meeting not viewable',
  detail: 'its evidence is being rebuilt',
}

function answers({
  speakers = [tag(), tag({ speakerLabel: 'SPEAKER_03', talkTimeMs: 943_000, segmentCount: 61 })],
  segments = [segment(), segment({ segmentId: 's-2', speakerLabel: 'SPEAKER_03' })],
  roster = [participant(), participant({ id: 'p-2', displayName: 'Tim Goeke' })],
  hasRecording = true,
}: {
  speakers?: Array<SpeakerTag>
  segments?: Array<DrilldownSegment>
  roster?: Array<ParticipantRow>
  hasRecording?: boolean
} = {}) {
  sdk.listMeetingSpeakers.mockResolvedValue({
    data: { meetingId: MEETING, speakers },
    error: undefined,
  })
  sdk.getMeetingDrilldown.mockResolvedValue({
    data: {
      meetingId: MEETING,
      title: 'Weekly community sync',
      hasRecording,
      corpus: 'real',
      startedAt: '2026-08-21T09:00:00Z',
      startedAtPrecision: 'exact',
      sourceDeepLink: null,
      screenshots: [],
      segments,
    },
    error: undefined,
  })
  sdk.listParticipants.mockResolvedValue({ data: roster, error: undefined })
}

/**
 * Both reads, not just the rows. The speakers list and the drill-down are two
 * requests that settle independently, and the clips column is drawn from the
 * drill-down's `hasRecording` — so a helper that waited only for the rows
 * would race the column it is about to assert on.
 */
async function loaded() {
  render(<SpeakerNaming meetingId={MEETING} />)
  await screen.findByTestId('speaker-row-SPEAKER_00')
  await screen.findByText(/Weekly community sync/)
}

beforeEach(() => {
  sdk.listMeetingSpeakers.mockReset()
  sdk.getMeetingDrilldown.mockReset()
  sdk.listParticipants.mockReset()
  sdk.assignMeetingSpeaker.mockReset()
  sdk.getJob.mockReset()
  sdk.getJob.mockResolvedValue({ data: job(), error: undefined })
  stream.onEvent = null
  stream.onResync = null
  stream.connection = { kind: 'live' }
  playMedia.mockClear()
})

describe('the speakers rail', () => {
  it('lists every tag with its share, time and segment count', async () => {
    answers()
    await loaded()

    const row = screen.getByTestId('speaker-row-SPEAKER_00')
    expect(within(row).getByText('SPEAKER_00')).toBeInTheDocument()
    expect(within(row).getByText('60%')).toBeInTheDocument()
    expect(within(row).getByText('23m 51s · 112 segments')).toBeInTheDocument()
    // The header carries the count and the speech total, both served.
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Speakers 2')
    expect(screen.getByText('39m 34s')).toBeInTheDocument()
  })

  it('never puts a name on a tag the system has not resolved (AD-13)', async () => {
    answers({ speakers: [tag()] })
    await loaded()

    const row = screen.getByTestId('speaker-row-SPEAKER_00')
    expect(within(row).getByRole('button', { name: /SPEAKER_00, selected, placeholder/ }))
      .toBeInTheDocument()
    expect(within(row).queryByText('Priya Natarajan')).not.toBeInTheDocument()
    // The correction affordance belongs to a row that already has a name.
    expect(within(row).queryByRole('button', { name: 'Correct' })).not.toBeInTheDocument()
  })

  it('names a resolved row and offers Correct instead', async () => {
    answers({
      speakers: [
        tag({
          speakerLabel: 'SPEAKER_02',
          speakerResolution: 'resolved',
          participantId: 'p-2',
          displayName: 'Tim Goeke',
        }),
      ],
    })
    render(<SpeakerNaming meetingId={MEETING} />)
    const row = await screen.findByTestId('speaker-row-SPEAKER_02')

    expect(within(row).getByText('Tim Goeke')).toBeInTheDocument()
    expect(within(row).getByText('resolved')).toBeInTheDocument()
    expect(within(row).getByRole('button', { name: 'Correct' })).toBeInTheDocument()
  })

  it('states the absence when the meeting has no speaker tags', async () => {
    answers({ speakers: [] })
    render(<SpeakerNaming meetingId={MEETING} />)

    expect(await screen.findByTestId('no-speaker-tags')).toHaveTextContent(
      'No speaker tags for this meeting — the transcript arrived speaker-attributed,' +
        ' or the diarizer is noop (config.yaml: diarizer.engine).',
    )
  })
})

describe('meeting ownership', () => {
  it('drops the old meeting before reads for a changed route parameter settle', async () => {
    answers({ speakers: [tag()] })
    const { rerender } = render(<SpeakerNaming meetingId={MEETING} />)
    await screen.findByTestId('speaker-row-SPEAKER_00')

    sdk.listMeetingSpeakers.mockReturnValue(new Promise<never>(() => {}))
    sdk.getMeetingDrilldown.mockReturnValue(new Promise<never>(() => {}))
    sdk.listParticipants.mockReturnValue(new Promise<never>(() => {}))

    rerender(<SpeakerNaming meetingId="meeting-2" />)

    expect(screen.queryByTestId('speaker-row-SPEAKER_00')).not.toBeInTheDocument()
    expect(screen.getByText('meeting-2')).toBeInTheDocument()
  })
})

describe('the three assignment paths', () => {
  it('assigns an existing participant by id, never by the typed text', async () => {
    answers()
    sdk.assignMeetingSpeaker.mockResolvedValue({ data: assignment(), error: undefined })
    const user = userEvent.setup()
    await loaded()

    await user.type(screen.getByRole('combobox'), 'pri')
    await user.click(await screen.findByRole('option', { name: 'Priya Natarajan' }))
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(sdk.assignMeetingSpeaker).toHaveBeenCalledTimes(1))
    expect(sdk.assignMeetingSpeaker.mock.calls[0][0]).toMatchObject({
      path: { meeting_id: MEETING, tag: 'SPEAKER_00' },
      body: { participantId: 'p-1' },
    })
  })

  it('shows the response-confirmed identity on the row while its rerun is queued', async () => {
    answers()
    sdk.assignMeetingSpeaker.mockResolvedValue({
      data: assignment({ displayName: 'Priya Natarajan-Renamed' }),
      error: undefined,
    })
    const user = userEvent.setup()
    await loaded()

    await user.type(screen.getByRole('combobox'), 'pri')
    await user.click(await screen.findByRole('option', { name: 'Priya Natarajan' }))
    await user.click(screen.getByRole('button', { name: 'Save' }))

    const row = screen.getByTestId('speaker-row-SPEAKER_00')
    expect(await within(row).findByText('Priya Natarajan-Renamed')).toBeInTheDocument()
    expect(within(row).getByText('rerun · queued')).toBeInTheDocument()
  })

  it('keeps a picked participant through harmless surrounding whitespace', async () => {
    answers()
    sdk.assignMeetingSpeaker.mockResolvedValue({ data: assignment(), error: undefined })
    const user = userEvent.setup()
    await loaded()

    const field = screen.getByRole('combobox')
    await user.type(field, 'pri')
    await user.click(await screen.findByRole('option', { name: 'Priya Natarajan' }))
    await user.type(field, '  ')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(sdk.assignMeetingSpeaker).toHaveBeenCalledTimes(1))
    expect(sdk.assignMeetingSpeaker.mock.calls[0][0].body).toEqual({ participantId: 'p-1' })
  })

  it('restores the picked participant when edited text returns to its name', async () => {
    answers()
    sdk.assignMeetingSpeaker.mockResolvedValue({ data: assignment(), error: undefined })
    const user = userEvent.setup()
    await loaded()

    const field = screen.getByRole('combobox')
    await user.type(field, 'pri')
    await user.click(await screen.findByRole('option', { name: 'Priya Natarajan' }))
    await user.clear(field)
    await user.type(field, 'Priya Natarajan')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(sdk.assignMeetingSpeaker).toHaveBeenCalledTimes(1))
    expect(sdk.assignMeetingSpeaker.mock.calls[0][0].body).toEqual({ participantId: 'p-1' })
  })

  it('keeps the selected id when two participants have the same display name', async () => {
    answers({
      roster: [
        participant(),
        participant({ id: 'p-2', displayName: 'Priya Natarajan' }),
      ],
    })
    sdk.assignMeetingSpeaker.mockResolvedValue({
      data: assignment({ participantId: 'p-2' }),
      error: undefined,
    })
    const user = userEvent.setup()
    await loaded()

    const field = screen.getByRole('combobox')
    await user.type(field, 'pri')
    const options = await screen.findAllByRole('option', { name: 'Priya Natarajan' })
    await user.click(options[1])
    await user.type(field, ' ')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(sdk.assignMeetingSpeaker).toHaveBeenCalledTimes(1))
    expect(sdk.assignMeetingSpeaker.mock.calls[0][0].body).toEqual({ participantId: 'p-2' })
  })

  it('assigns a typed new name', async () => {
    answers()
    sdk.assignMeetingSpeaker.mockResolvedValue({
      data: assignment({ participantId: 'p-9', displayName: 'Alice Chen' }),
      error: undefined,
    })
    const user = userEvent.setup()
    await loaded()

    await user.type(screen.getByRole('combobox'), 'Alice Chen')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(sdk.assignMeetingSpeaker).toHaveBeenCalledTimes(1))
    expect(sdk.assignMeetingSpeaker.mock.calls[0][0].body).toEqual({
      displayName: 'Alice Chen',
    })
  })

  it('marks a tag unresolved as a choice of equal weight', async () => {
    answers()
    sdk.assignMeetingSpeaker.mockResolvedValue({
      data: assignment({ participantId: null, displayName: null }),
      error: undefined,
    })
    const user = userEvent.setup()
    await loaded()

    await user.click(screen.getByRole('button', { name: 'Unresolved — keep the tag' }))

    await waitFor(() => expect(sdk.assignMeetingSpeaker).toHaveBeenCalledTimes(1))
    expect(sdk.assignMeetingSpeaker.mock.calls[0][0].body).toEqual({ unresolved: true })
  })

  it('shows suggestions but never applies one', async () => {
    answers()
    sdk.assignMeetingSpeaker.mockResolvedValue({ data: assignment(), error: undefined })
    const user = userEvent.setup()
    await loaded()

    const field = screen.getByRole('combobox')
    await user.type(field, 'pri')

    // The suggestion is on screen and highlighted by nothing; the field still
    // holds exactly what was typed.
    expect(await screen.findByRole('option', { name: 'Priya Natarajan' })).toBeInTheDocument()
    expect(field).toHaveValue('pri')
    expect(screen.getByText('Suggestions are shown, never applied — pick one or type a name.'))
      .toBeInTheDocument()

    // Saving without picking sends the typed text, not the suggestion's id.
    await user.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(sdk.assignMeetingSpeaker).toHaveBeenCalledTimes(1))
    expect(sdk.assignMeetingSpeaker.mock.calls[0][0].body).toEqual({ displayName: 'pri' })
  })

  it('drops a picked participant once the curator types over it', async () => {
    answers()
    sdk.assignMeetingSpeaker.mockResolvedValue({ data: assignment(), error: undefined })
    const user = userEvent.setup()
    await loaded()

    const field = screen.getByRole('combobox')
    await user.type(field, 'pri')
    await user.click(await screen.findByRole('option', { name: 'Priya Natarajan' }))
    await user.clear(field)
    await user.type(field, 'Priyanka Rao')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(sdk.assignMeetingSpeaker).toHaveBeenCalledTimes(1))
    expect(sdk.assignMeetingSpeaker.mock.calls[0][0].body).toEqual({
      displayName: 'Priyanka Rao',
    })
  })

  it('cannot save an empty field, and says why', async () => {
    answers()
    await loaded()

    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
    expect(
      screen.getByText(/Save is disabled until a name is typed or chosen/),
    ).toBeInTheDocument()
  })

  it('renders a refused assignment in the api’s own words', async () => {
    answers()
    sdk.assignMeetingSpeaker.mockResolvedValue({
      data: undefined,
      error: {
        type: 'urn:meetingminer:problem:assignment-target-busy',
        title: 'assignment target busy',
        detail: "meeting's job is still running",
      },
    })
    const user = userEvent.setup()
    await loaded()

    await user.type(screen.getByRole('combobox'), 'Alice Chen')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByTestId('assignment-refusal')).toHaveTextContent(
      "assignment target busy: meeting's job is still running",
    )
    // The row is still a tag, and the field still holds what was typed.
    expect(screen.getByRole('combobox')).toHaveValue('Alice Chen')
  })
})

describe('the rerun a naming starts', () => {
  it('says the meeting is reprocessing rather than leaving it looking hung', async () => {
    answers()
    sdk.assignMeetingSpeaker.mockResolvedValue({ data: assignment(), error: undefined })
    const user = userEvent.setup()
    await loaded()

    await user.type(screen.getByRole('combobox'), 'Alice Chen')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    const strip = await screen.findByTestId('rerun-strip')
    expect(within(strip).getByRole('img', { name: 'align queued' })).toBeInTheDocument()
    expect(within(strip).getByRole('img', { name: 'moments queued' })).toBeInTheDocument()
    expect(within(strip).getByRole('img', { name: 'extract queued' })).toBeInTheDocument()
    expect(screen.getByTestId('reprocessing-note')).toHaveTextContent(
      'Reprocessing this meeting — align, moments, extract re-armed by naming SPEAKER_00.',
    )
  })

  it('fills the strip from the job stream and states the landing', async () => {
    answers()
    sdk.assignMeetingSpeaker.mockResolvedValue({ data: assignment(), error: undefined })
    const user = userEvent.setup()
    await loaded()

    await user.type(screen.getByRole('combobox'), 'Priya Natarajan')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    await screen.findByTestId('rerun-strip')

    emit({ event: 'job.stage', jobId: 'job-1', stage: 'align', status: 'running' })
    expect(screen.getByTestId('rerun-stage-align')).toHaveAttribute('data-status', 'running')

    sdk.getJob.mockResolvedValue({ data: job({ status: 'done' }), error: undefined })
    emit({ event: 'job.done', jobId: 'job-1', jobStatus: 'done', viewable: true })

    const landed = await screen.findByTestId('rerun-landed')
    expect(landed).toHaveTextContent(
      /transcript, graph, and extractions now name SPEAKER_00 as Priya Natarajan\./,
    )
    expect(landed).toHaveTextContent('Moment ids and citations unchanged.')
  })

  it('re-reads both sources once the rerun lands', async () => {
    answers()
    sdk.assignMeetingSpeaker.mockResolvedValue({ data: assignment(), error: undefined })
    const user = userEvent.setup()
    await loaded()
    expect(sdk.listMeetingSpeakers).toHaveBeenCalledTimes(1)

    await user.type(screen.getByRole('combobox'), 'Priya Natarajan')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    await screen.findByTestId('rerun-strip')

    // Deliberately not re-read on the 200: the re-arm the PUT just performed
    // is what makes the meeting unviewable, so an immediate re-read answers
    // 409 and would replace a working screen with a refusal.
    expect(sdk.listMeetingSpeakers).toHaveBeenCalledTimes(1)

    sdk.getJob.mockResolvedValue({ data: job({ status: 'done' }), error: undefined })
    emit({ event: 'job.done', jobId: 'job-1', jobStatus: 'done', viewable: true })

    await waitFor(() => expect(sdk.listMeetingSpeakers).toHaveBeenCalledTimes(2))
    expect(sdk.getMeetingDrilldown).toHaveBeenCalledTimes(2)
  })

  it('shows the guarded resolved name in the transcript after the landed reread', async () => {
    answers()
    sdk.assignMeetingSpeaker.mockResolvedValue({ data: assignment(), error: undefined })
    const user = userEvent.setup()
    await loaded()

    await user.type(screen.getByRole('combobox'), 'Priya Natarajan')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    await screen.findByTestId('rerun-strip')

    sdk.listMeetingSpeakers.mockResolvedValue({
      data: {
        meetingId: MEETING,
        speakers: [
          tag({
            speakerResolution: 'resolved',
            participantId: 'p-1',
            displayName: 'Priya Natarajan',
          }),
        ],
      },
      error: undefined,
    })
    sdk.getMeetingDrilldown.mockResolvedValue({
      data: {
        meetingId: MEETING,
        title: 'Weekly community sync',
        hasRecording: true,
        corpus: 'real',
        startedAt: '2026-08-21T09:00:00Z',
        startedAtPrecision: 'exact',
        sourceDeepLink: null,
        screenshots: [],
        segments: [
          segment({ speakerResolution: 'resolved', participantId: 'p-1' }),
        ],
      },
      error: undefined,
    })

    sdk.getJob.mockResolvedValue({ data: job({ status: 'done' }), error: undefined })
    emit({ event: 'job.done', jobId: 'job-1', jobStatus: 'done', viewable: true })

    const transcript = await screen.findByRole('region', {
      name: 'Transcript filtered to SPEAKER_00',
    })
    await waitFor(() =>
      expect(within(transcript).getByRole('heading', { level: 3 })).toHaveTextContent(
        'Transcript · SPEAKER_00 · Priya Natarajan',
      ),
    )
  })

  it('names the stage a failed rerun broke at, and keeps the names saved', async () => {
    answers()
    sdk.assignMeetingSpeaker.mockResolvedValue({ data: assignment(), error: undefined })
    const user = userEvent.setup()
    await loaded()

    await user.type(screen.getByRole('combobox'), 'Priya Natarajan')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    await screen.findByTestId('rerun-strip')

    sdk.getJob.mockResolvedValue({
      data: job({
        status: 'failed',
        error: 'ollama refused',
        stages: [
          { name: 'align', status: 'done', error: null },
          { name: 'moments', status: 'failed', error: 'ollama refused' },
          { name: 'extract', status: 'queued', error: null },
        ],
      }),
      error: undefined,
    })
    emit({ event: 'job.error', jobId: 'job-1', stage: 'moments', error: 'ollama refused' })

    expect(await screen.findByTestId('rerun-failed')).toHaveTextContent(
      'Rerun failed at moments — ollama refused. Names are saved; the transcript' +
        ' still shows tags.',
    )
    expect(screen.queryByTestId('reprocessing-note')).not.toBeInTheDocument()
  })

  it('recovers a terminal transition missed while the event stream was disconnected', async () => {
    answers()
    sdk.assignMeetingSpeaker.mockResolvedValue({ data: assignment(), error: undefined })
    const user = userEvent.setup()
    await loaded()

    await user.type(screen.getByRole('combobox'), 'Priya Natarajan')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    await screen.findByTestId('rerun-strip')

    sdk.getJob.mockResolvedValue({
      data: job({
        status: 'running',
        stages: [
          { name: 'align', status: 'done' },
          { name: 'moments', status: 'done' },
          { name: 'extract', status: 'queued' },
        ],
      }),
      error: undefined,
    })
    resync()

    expect(await screen.findByTestId('rerun-landed')).toBeInTheDocument()
  })

  it('rejects a delayed terminal frame when the current re-arm is still queued', async () => {
    answers()
    sdk.assignMeetingSpeaker
      .mockResolvedValueOnce({ data: assignment({ displayName: 'First Name' }), error: undefined })
      .mockResolvedValueOnce({ data: assignment({ displayName: 'Second Name' }), error: undefined })
    const user = userEvent.setup()
    await loaded()

    const field = screen.getByRole('combobox')
    await user.type(field, 'First Name')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(sdk.assignMeetingSpeaker).toHaveBeenCalledTimes(1))
    await user.type(field, 'Second Name')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(sdk.assignMeetingSpeaker).toHaveBeenCalledTimes(2))

    emit({ event: 'job.done', jobId: 'job-1', jobStatus: 'running', viewable: true })

    await waitFor(() => expect(sdk.getJob).toHaveBeenCalled())
    expect(screen.queryByTestId('rerun-landed')).not.toBeInTheDocument()
    expect(screen.getByTestId('reprocessing-note')).toBeInTheDocument()
  })

  it('surfaces a lost live-progress connection beside an active rerun', async () => {
    stream.connection = { kind: 'lost', message: 'stream closed' }
    answers()
    sdk.assignMeetingSpeaker.mockResolvedValue({ data: assignment(), error: undefined })
    const user = userEvent.setup()
    await loaded()

    await user.type(screen.getByRole('combobox'), 'Priya Natarajan')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByText(/Live rerun progress is unavailable/)).toHaveTextContent(
      'stream closed',
    )
  })
})

describe('staying usable while the evidence is unsettled', () => {
  it('keeps the rows and the controls when a re-read refuses mid-rerun', async () => {
    // Story 7.3 admits the PUT while a meeting is unviewable so a curator can
    // correct a failed rerun; both of this screen's reads keep refusing with
    // 409 through that window. Blanking here would take the screen away at
    // exactly the moment the exception exists to keep it.
    answers()
    sdk.assignMeetingSpeaker.mockResolvedValue({ data: assignment(), error: undefined })
    const user = userEvent.setup()
    await loaded()

    await user.type(screen.getByRole('combobox'), 'Priya Natarajan')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    await screen.findByTestId('rerun-strip')

    sdk.listMeetingSpeakers.mockResolvedValue({ data: undefined, error: NOT_VIEWABLE })
    sdk.getMeetingDrilldown.mockResolvedValue({ data: undefined, error: NOT_VIEWABLE })
    sdk.getJob.mockResolvedValue({ data: job({ status: 'done' }), error: undefined })
    emit({ event: 'job.done', jobId: 'job-1', jobStatus: 'done', viewable: true })

    expect(await screen.findByTestId('speakers-failure')).toHaveTextContent(
      'The rows below are the pre-rerun reading',
    )
    // Every row is still listed, and every control still works.
    expect(screen.getByTestId('speaker-row-SPEAKER_00')).toBeInTheDocument()
    expect(screen.getByTestId('speaker-row-SPEAKER_03')).toBeInTheDocument()
    expect(screen.getByTestId('transcript-failure')).toHaveTextContent(
      'The lines below are the pre-rerun reading',
    )
    expect(screen.getByRole('button', { name: 'Unresolved — keep the tag' })).toBeEnabled()

    // And a second correction still goes through — the recovery path.
    await user.click(screen.getByRole('button', { name: 'Unresolved — keep the tag' }))
    await waitFor(() => expect(sdk.assignMeetingSpeaker).toHaveBeenCalledTimes(2))
  })

  it('states the refusal and offers Retry when nothing has ever loaded', async () => {
    sdk.listMeetingSpeakers.mockResolvedValue({ data: undefined, error: NOT_VIEWABLE })
    sdk.getMeetingDrilldown.mockResolvedValue({ data: undefined, error: NOT_VIEWABLE })
    sdk.listParticipants.mockResolvedValue({ data: [], error: undefined })
    render(<SpeakerNaming meetingId={MEETING} />)

    expect(await screen.findByTestId('speakers-failure')).toHaveTextContent(
      'meeting not viewable: its evidence is being rebuilt',
    )
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
  })

  it('names the api when it cannot be reached at all', async () => {
    sdk.listMeetingSpeakers.mockRejectedValue(new Error('fetch failed'))
    sdk.getMeetingDrilldown.mockRejectedValue(new Error('fetch failed'))
    sdk.listParticipants.mockResolvedValue({ data: [], error: undefined })
    render(<SpeakerNaming meetingId={MEETING} />)

    expect(await screen.findByTestId('speakers-failure')).toHaveTextContent(
      /Cannot reach the api at .*: fetch failed\./,
    )
  })
})

describe('clips and the tag-filtered transcript', () => {
  it('offers one clip per sample offset, named by its position and offset', async () => {
    answers()
    await loaded()

    expect(
      screen.getByRole('button', { name: 'Play clip 1 of SPEAKER_00 at 4:12' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Play clip 2 of SPEAKER_00 at 19:40' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Play clip 3 of SPEAKER_00 at 41:07' }),
    ).toBeInTheDocument()
  })

  it('opens the one player at the clip it was asked for', async () => {
    answers()
    const user = userEvent.setup()
    await loaded()

    await user.click(screen.getByRole('button', { name: 'Play clip 2 of SPEAKER_00 at 19:40' }))

    const player = screen.getByTestId('replay-player')
    expect(player).toHaveAttribute('aria-label', 'Clip 2 of SPEAKER_00 at 19:40')
  })

  it('plays on activation and restarts when the same clip is pressed again', async () => {
    answers()
    const user = userEvent.setup()
    await loaded()

    const clipButton = await screen.findByRole('button', {
      name: 'Play clip 1 of SPEAKER_00 at 4:12',
    })
    await user.click(clipButton)
    await waitFor(() => expect(playMedia).toHaveBeenCalledTimes(1))
    const firstPlayer = screen.getByTestId('replay-player')

    await user.click(clipButton)

    await waitFor(() => expect(playMedia).toHaveBeenCalledTimes(2))
    expect(screen.getByTestId('replay-player')).not.toBe(firstPlayer)
  })

  it('offers no clip for a transcript-only meeting, and says so', async () => {
    answers({ hasRecording: false })
    await loaded()

    expect(screen.queryByRole('button', { name: /Play clip/ })).not.toBeInTheDocument()
    expect(screen.getByText(/Transcript only — no recording/)).toBeInTheDocument()
  })

  it('shows only the selected tag’s lines, and follows the selection', async () => {
    answers({
      segments: [
        segment({ segmentId: 's-1', speakerLabel: 'SPEAKER_00', text: 'Zero speaking.' }),
        segment({ segmentId: 's-2', speakerLabel: 'SPEAKER_03', text: 'Three speaking.' }),
      ],
    })
    const user = userEvent.setup()
    await loaded()

    expect(screen.getByText('Zero speaking.')).toBeInTheDocument()
    expect(screen.queryByText('Three speaking.')).not.toBeInTheDocument()

    await user.click(
      within(screen.getByTestId('speaker-row-SPEAKER_03')).getByRole('button', {
        name: /SPEAKER_03/,
      }),
    )

    expect(screen.getByText('Three speaking.')).toBeInTheDocument()
    expect(screen.queryByText('Zero speaking.')).not.toBeInTheDocument()
  })
})
