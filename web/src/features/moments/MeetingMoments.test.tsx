import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type {
  MeetingDrilldownResponse,
  MeetingMomentsResponse,
  MomentArtifact,
  MomentDetail,
} from '@/client/types.gen'
import { MeetingMoments } from './MeetingMoments'
import { MOMENT_TIMEOUT_MS } from './moments'

const sdk = vi.hoisted(() => ({
  getMeetingDrilldown: vi.fn(),
  listMeetingMoments: vi.fn(),
  getMoment: vi.fn(),
}))

vi.mock('@/client/sdk.gen', () => ({
  getMeetingDrilldown: sdk.getMeetingDrilldown,
  listMeetingMoments: sdk.listMeetingMoments,
  getMoment: sdk.getMoment,
  getHealth: vi.fn(),
  listMeetings: vi.fn(),
  streamJobEvents: vi.fn(),
  searchCorpus: vi.fn(),
  getJob: vi.fn(),
  createIngest: vi.fn(),
  getRecording: vi.fn(),
  getMediaFile: vi.fn(),
  listParticipants: vi.fn(),
  renameParticipant: vi.fn(),
  mergeParticipants: vi.fn(),
}))

function response(
  overrides: Partial<MeetingDrilldownResponse> = {},
): MeetingDrilldownResponse {
  return {
    meetingId: 'meeting-1',
    title: 'Data Hub Demo',
    hasRecording: true,
    corpus: 'real',
    startedAt: '2026-08-05T12:00:19Z',
    startedAtPrecision: 'second',
    sourceDeepLink: 'https://example-my.sharepoint.com/recap',
    screenshots: [
      {
        screenshotId: 'shot-1',
        ordinal: 1,
        startOffsetMs: 0,
        endOffsetMs: 30_000,
        path: 'meetings/meeting-1/screenshots/1.jpg',
        viewType: 'slide',
        screenLabel: 'Revenue deck',
        classificationTags: [],
        momentId: 'moment-1',
      },
      {
        screenshotId: 'shot-2',
        ordinal: 2,
        startOffsetMs: 30_000,
        endOffsetMs: 60_000,
        path: 'meetings/meeting-1/screenshots/2.jpg',
        viewType: 'participant-gallery',
        screenLabel: null,
        classificationTags: ['avatar-gallery-unresolved'],
        momentId: null,
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
      {
        segmentId: 'seg-2',
        ordinal: 2,
        startMs: 40_000,
        endMs: 42_000,
        speakerLabel: 'Whitmore, Ellis',
        speakerResolution: 'resolved',
        participantId: 'participant-2',
        text: 'We moved that feed to SFTP last week.',
        momentId: 'moment-2',
      },
      {
        segmentId: 'seg-3',
        ordinal: 3,
        startMs: 44_000,
        endMs: 46_000,
        speakerLabel: 'Speaker 8',
        speakerResolution: 'unresolved',
        participantId: null,
        text: 'And the purchase order still needs approval.',
        momentId: null,
      },
    ],
    ...overrides,
  }
}

function answers(body: MeetingDrilldownResponse) {
  sdk.getMeetingDrilldown.mockResolvedValue({ data: body, error: undefined })
}

function momentsResponse(
  overrides: Partial<MeetingMomentsResponse> = {},
): MeetingMomentsResponse {
  return {
    meetingId: 'meeting-1',
    title: 'Data Hub Demo',
    hasRecording: true,
    corpus: 'real',
    startedAt: '2026-08-05T12:00:19Z',
    startedAtPrecision: 'second',
    moments: [
      {
        momentId: 'moment-1',
        startMs: 2_000,
        endMs: 11_000,
        startedAt: '2026-08-05T12:00:21Z',
        startedAtPrecision: 'second',
        screenshotId: 'shot-1',
        sourceDeepLink: null,
        segmentCount: 1,
        preview: 'Everybody, good morning.',
      },
      {
        momentId: 'moment-2',
        startMs: 40_000,
        endMs: 46_000,
        startedAt: '2026-08-05T12:00:59Z',
        startedAtPrecision: 'second',
        screenshotId: 'shot-2',
        sourceDeepLink: null,
        segmentCount: 2,
        preview: 'We moved that feed to SFTP last week.',
      },
    ],
    ...overrides,
  }
}

function artifact(overrides: Partial<MomentArtifact> = {}): MomentArtifact {
  return {
    id: 'artifact-1',
    kind: 'action-item',
    state: 'extracted',
    title: 'Confirm the SFTP cutover date',
    body: 'Confirm with Ellis.',
    publishedAt: null,
    publishRelativePath: null,
    publishCommitSha: null,
    ...overrides,
  }
}

function momentDetail(
  momentId: string,
  startMs: number,
  endMs: number,
  artifacts: Array<MomentArtifact>,
): MomentDetail {
  return {
    momentId,
    meetingId: 'meeting-1',
    meetingTitle: 'Data Hub Demo',
    corpus: 'real',
    hasRecording: true,
    startMs,
    endMs,
    startedAt: '2026-08-05T12:00:21Z',
    startedAtPrecision: 'second',
    screenshotId: null,
    screenshotPath: null,
    sourceDeepLink: null,
    superseded: false,
    segments: [],
    artifacts,
  }
}

/** Rail data: the moments list plus each moment's own detail answer — a
 * moment missing from `details` answers 404, exercising the tolerant read. */
function railAnswers(
  body: MeetingMomentsResponse,
  details: Record<string, MomentDetail>,
) {
  sdk.listMeetingMoments.mockResolvedValue({ data: body, error: undefined })
  sdk.getMoment.mockImplementation(({ path }: { path: { moment_id: string } }) => {
    const detail = details[path.moment_id]
    return Promise.resolve(
      detail === undefined
        ? {
            data: undefined,
            error: {
              type: 'urn:meetingminer:problem:not-found',
              title: 'Not Found',
              status: 404,
              detail: `no moment with id ${path.moment_id}`,
            },
          }
        : { data: detail, error: undefined },
    )
  })
}

function refuses(problem: Record<string, unknown>) {
  sdk.getMeetingDrilldown.mockResolvedValue({ data: undefined, error: problem })
}

function notViewable(extensions: Record<string, unknown>): Record<string, unknown> {
  return {
    type: 'urn:meetingminer:problem:meeting-not-viewable',
    title: 'Conflict',
    status: 409,
    detail: 'meeting meeting-1 exists but its evidence is still being prepared',
    meetingId: 'meeting-1',
    ...extensions,
  }
}

beforeEach(() => {
  sdk.getMeetingDrilldown.mockReset()
  sdk.listMeetingMoments.mockReset()
  sdk.getMoment.mockReset()
  // Default rail: an answered-empty moments list, so the pre-existing tests
  // exercise the page with a quiet rail unless a test overrides it.
  sdk.listMeetingMoments.mockResolvedValue({
    data: momentsResponse({ moments: [] }),
    error: undefined,
  })
})

describe('MeetingMoments', () => {
  it('renders the header and the screenshot series in ordinal order, labeled', async () => {
    answers(response())
    render(<MeetingMoments meetingId="meeting-1" />)

    expect(
      await screen.findByRole('heading', { name: 'Data Hub Demo' }),
    ).toBeInTheDocument()
    expect(sdk.getMeetingDrilldown.mock.calls[0][0].path.meeting_id).toBe('meeting-1')

    const first = await screen.findByTestId('drilldown-screenshot-shot-1')
    const second = screen.getByTestId('drilldown-screenshot-shot-2')
    // Series order is the payload's ordinal order, top to bottom.
    expect(first.compareDocumentPosition(second)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    )
    // Classification + human label + offset on each item.
    expect(screen.getByTestId('screenshot-view-type-shot-1')).toHaveTextContent('slide')
    expect(screen.getByTestId('screenshot-label-shot-1')).toHaveTextContent('Revenue deck')
    expect(first).toHaveTextContent('0:00')
    expect(screen.getByTestId('screenshot-view-type-shot-2')).toHaveTextContent(
      'participant-gallery',
    )
    expect(screen.queryByTestId('screenshot-label-shot-2')).toBeNull()
    expect(second).toHaveTextContent('0:30')
    // The image src goes through mediaUrl over the stored relative path.
    expect(within(first).getByRole('img')).toHaveAttribute(
      'src',
      expect.stringContaining('/media/meetings/meeting-1/screenshots/1.jpg'),
    )
  })

  it('places extracted evidence first in document order on the stacked layout, restoring the 3-column order at lg via matching order classes', async () => {
    answers(response())
    render(<MeetingMoments meetingId="meeting-1" />)

    const rail = await screen.findByTestId('meeting-rail')
    const filmStripSection = screen.getByRole('heading', { name: /^Screens/ }).closest('section')
    const transcriptSection = screen.getByTestId('drilldown-transcript').closest('section')
    expect(filmStripSection).not.toBeNull()
    expect(transcriptSection).not.toBeNull()

    // Document order — and therefore the stacked (below-`lg`) visual order,
    // tab order, and screen-reader linearization — is evidence, then
    // film-strip, then transcript: the evidence rail is reachable without
    // passing through a potentially very long film-strip or transcript first.
    expect(rail.compareDocumentPosition(filmStripSection as Element)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    )
    expect(
      (filmStripSection as Element).compareDocumentPosition(transcriptSection as Element),
    ).toBe(Node.DOCUMENT_POSITION_FOLLOWING)

    // At `lg`+ each carries the order class that restores the original
    // 3-column left/center/right layout on top of that mobile-first order.
    expect(rail.className).toContain('lg:order-3')
    expect((filmStripSection as Element).className).toContain('lg:order-1')
    expect((transcriptSection as Element).className).toContain('lg:order-2')
  })

  it('opens a moment by clicking the screenshot image itself', async () => {
    answers(response())
    const onOpenMoment = vi.fn()
    render(<MeetingMoments meetingId="meeting-1" onOpenMoment={onOpenMoment} />)

    const first = await screen.findByTestId('drilldown-screenshot-shot-1')
    // The image is the affordance: the open-moment button contains the img.
    const control = within(first).getByRole('button', { name: /Open moment/ })
    expect(within(control).getByRole('img')).toBeInTheDocument()
    await userEvent.click(within(control).getByRole('img'))
    expect(onOpenMoment).toHaveBeenCalledWith('moment-1')

    // A screenshot only a superseded moment (or none) named offers no link —
    // its image renders bare, outside any button.
    const second = screen.getByTestId('drilldown-screenshot-shot-2')
    expect(within(second).queryByRole('button', { name: /Open moment/ })).toBeNull()
    expect(within(second).getByRole('img')).toBeInTheDocument()
  })

  it('prefers the curated screen label in the image alt text', async () => {
    answers(response())
    render(<MeetingMoments meetingId="meeting-1" />)

    const first = await screen.findByTestId('drilldown-screenshot-shot-1')
    expect(within(first).getByRole('img')).toHaveAttribute('alt', 'Revenue deck')
    // Without a label the classification + offset stand in.
    const second = screen.getByTestId('drilldown-screenshot-shot-2')
    expect(within(second).getByRole('img')).toHaveAttribute(
      'alt',
      'participant-gallery at 0:30',
    )
    // The series lazy-loads: a real meeting is a hundred-plus captures.
    expect(within(first).getByRole('img')).toHaveAttribute('loading', 'lazy')
  })

  it('treats an untyped null navigation handler as absent', async () => {
    answers(response())
    render(
      <MeetingMoments
        meetingId="meeting-1"
        onOpenMoment={null as unknown as (momentId: string) => void}
      />,
    )

    await screen.findByTestId('drilldown-segment-seg-1')
    expect(screen.queryByRole('button', { name: /Open moment/ })).toBeNull()
  })

  it('opens a covered segment from its text while replay remains independent', async () => {
    answers(response())
    const onOpenMoment = vi.fn()
    render(<MeetingMoments meetingId="meeting-1" onOpenMoment={onOpenMoment} />)

    const covered = await screen.findByTestId('drilldown-segment-seg-2')
    expect(covered).toHaveTextContent('Whitmore, Ellis')
    expect(covered).toHaveTextContent('We moved that feed to SFTP last week.')
    const momentButton = within(covered).getByRole('button', {
      name: 'Open moment at 0:40: We moved that feed to SFTP last week.',
    })
    await userEvent.click(within(momentButton).getByText('We moved that feed to SFTP last week.'))
    expect(onOpenMoment).toHaveBeenCalledWith('moment-2')

    await userEvent.click(within(covered).getByRole('button', { name: /^Replay/ }))
    expect(within(covered).getByTestId('replay-player')).toBeInTheDocument()
    expect(onOpenMoment).toHaveBeenCalledTimes(1)

    // An uncovered segment is listed but offers no moment to open.
    const uncovered = screen.getByTestId('drilldown-segment-seg-3')
    expect(uncovered).toHaveTextContent('And the purchase order still needs approval.')
    expect(within(uncovered).queryByRole('button', { name: /Open moment/ })).toBeNull()
  })

  it('omits open controls entirely outside a navigation shell', async () => {
    answers(response())
    render(<MeetingMoments meetingId="meeting-1" />)

    await screen.findByTestId('drilldown-segment-seg-1')
    expect(screen.queryByRole('button', { name: /Open moment/ })).toBeNull()
  })

  it('marks every case-insensitive occurrence of the typed highlight term', async () => {
    answers(response())
    render(<MeetingMoments meetingId="meeting-1" />)

    await screen.findByTestId('drilldown-segment-seg-1')
    await userEvent.type(screen.getByTestId('highlight-input'), 'PURCHASE order')

    const uncovered = screen.getByTestId('drilldown-segment-seg-3')
    const marks = uncovered.querySelectorAll('mark')
    expect(marks).toHaveLength(1)
    expect(marks[0]).toHaveTextContent('purchase order')
    // No term in the other segments: no marks there.
    expect(
      screen.getByTestId('drilldown-segment-seg-1').querySelectorAll('mark'),
    ).toHaveLength(0)
  })

  it('mounts exactly one inline replay and moves it between regions', async () => {
    answers(response())
    render(<MeetingMoments meetingId="meeting-1" />)

    const first = await screen.findByTestId('drilldown-screenshot-shot-1')
    await userEvent.click(within(first).getByRole('button', { name: /^Replay/ }))
    expect(screen.getAllByTestId('replay-player')).toHaveLength(1)
    expect(within(first).getByTestId('replay-player')).toBeInTheDocument()

    // Clicking another region moves the single player rather than adding one.
    const segment = screen.getByTestId('drilldown-segment-seg-2')
    await userEvent.click(within(segment).getByRole('button', { name: /^Replay/ }))
    expect(screen.getAllByTestId('replay-player')).toHaveLength(1)
    expect(within(segment).getByTestId('replay-player')).toBeInTheDocument()
    expect(within(first).queryByTestId('replay-player')).toBeNull()

    // Toggling the open region closed unmounts the player entirely.
    await userEvent.click(within(segment).getByRole('button', { name: /^Hide/ }))
    expect(screen.queryByTestId('replay-player')).toBeNull()
  })

  it('seeks the inline replay to the screenshot’s own offset', async () => {
    answers(response())
    render(<MeetingMoments meetingId="meeting-1" />)

    const second = await screen.findByTestId('drilldown-screenshot-shot-2')
    await userEvent.click(within(second).getByRole('button', { name: /^Replay/ }))

    const player = within(second).getByTestId('replay-player') as HTMLVideoElement
    expect(player).toHaveAttribute(
      'src',
      'http://localhost:8000/media/recordings/meeting-1',
    )
    // 30_000 ms is 0:30 — the capture's startOffsetMs, not zero.
    player.currentTime = 0
    act(() => {
      player.dispatchEvent(new Event('loadedmetadata'))
    })
    expect(player.currentTime).toBe(30)
  })

  it('seeks the inline replay to the segment’s own offset', async () => {
    answers(response())
    render(<MeetingMoments meetingId="meeting-1" />)

    const segment = await screen.findByTestId('drilldown-segment-seg-2')
    await userEvent.click(within(segment).getByRole('button', { name: /^Replay/ }))

    const player = within(segment).getByTestId('replay-player') as HTMLVideoElement
    // 40_000 ms is 0:40 — the segment's startMs, not zero.
    player.currentTime = 0
    act(() => {
      player.dispatchEvent(new Event('loadedmetadata'))
    })
    expect(player.currentTime).toBe(40)
  })

  it('clears the highlight term when pointed at a different meeting', async () => {
    answers(response())
    const { rerender } = render(<MeetingMoments meetingId="meeting-1" />)
    await screen.findByTestId('drilldown-segment-seg-1')
    await userEvent.type(screen.getByTestId('highlight-input'), 'feed')
    expect(
      screen.getByTestId('drilldown-segment-seg-2').querySelectorAll('mark'),
    ).toHaveLength(1)

    answers(response({ meetingId: 'meeting-2', title: 'Sprint Review' }))
    rerender(<MeetingMoments meetingId="meeting-2" />)
    await screen.findByRole('heading', { name: 'Sprint Review' })

    // The previous meeting's term must not silently apply to a new transcript.
    expect((screen.getByTestId('highlight-input') as HTMLInputElement).value).toBe('')
    expect(
      screen.getByTestId('drilldown-segment-seg-2').querySelectorAll('mark'),
    ).toHaveLength(0)
  })

  it('renders the degraded transcript-only shape with the recap link', async () => {
    answers(
      response({
        hasRecording: false,
        screenshots: [],
        sourceDeepLink: 'https://example-my.sharepoint.com/recap',
      }),
    )
    render(<MeetingMoments meetingId="meeting-1" />)

    await screen.findByTestId('drilldown-segment-seg-1')
    // No film-strip section and no replay affordances anywhere.
    expect(screen.queryByText(/^Screens \d/)).toBeNull()
    expect(screen.queryByRole('button', { name: /Replay/ })).toBeNull()
    // The meeting-level recap link stands where the series would be.
    expect(screen.getByTestId('drilldown-deep-link')).toHaveAttribute(
      'href',
      'https://example-my.sharepoint.com/recap',
    )
    // Another host keeps the untimed label (UX-DR12 changes YouTube only).
    expect(screen.getByTestId('drilldown-deep-link')).toHaveAccessibleName('Open in Stream')
    expect(screen.getByTestId('drilldown-deep-link')).toHaveAttribute('rel', 'noreferrer')
    // Highlighting still works without a recording.
    await userEvent.type(screen.getByTestId('highlight-input'), 'feed')
    expect(
      screen.getByTestId('drilldown-segment-seg-2').querySelectorAll('mark'),
    ).toHaveLength(1)
  })

  it('times the YouTube link at each row beside Replay when the meeting has a recording', async () => {
    // UX-DR12 on the drill-down: every screenshot row and transcript row
    // carries the meeting's link timed at that row's own offset.
    answers(response({ sourceDeepLink: 'https://www.youtube.com/watch?v=abc' }))
    render(<MeetingMoments meetingId="meeting-1" />)

    await screen.findByTestId('drilldown-segment-seg-1')
    const shot1 = screen.getByTestId('drilldown-youtube-link-shot:shot-1')
    const shot2 = screen.getByTestId('drilldown-youtube-link-shot:shot-2')
    const seg1 = screen.getByTestId('drilldown-youtube-link-seg:seg-1')
    const seg2 = screen.getByTestId('drilldown-youtube-link-seg:seg-2')
    expect(shot1).toHaveAttribute('href', 'https://www.youtube.com/watch?v=abc&t=0')
    expect(shot2).toHaveAttribute('href', 'https://www.youtube.com/watch?v=abc&t=30')
    expect(seg1).toHaveAttribute('href', 'https://www.youtube.com/watch?v=abc&t=2')
    expect(seg2).toHaveAttribute('href', 'https://www.youtube.com/watch?v=abc&t=40')
    // Each name carries its own offset; the `↗` glyph is hidden from it.
    expect(
      within(screen.getByTestId('drilldown-segment-seg-2')).getByRole('link', {
        name: 'Open on YouTube at 0:40',
      }),
    ).toBe(seg2)
    expect(seg2).toHaveAttribute('target', '_blank')
    expect(seg2).toHaveAttribute('rel', 'noreferrer')
    // Replay first: the row's Replay button precedes its link.
    const replay = within(screen.getByTestId('drilldown-screenshot-shot-2')).getByRole(
      'button',
      { name: 'Replay recording at 0:30' },
    )
    expect(replay.compareDocumentPosition(shot2)).toBe(Node.DOCUMENT_POSITION_FOLLOWING)
    // The meeting-scoped header link is the degraded shape only.
    expect(screen.queryByTestId('drilldown-deep-link')).toBeNull()
  })

  it('offers no source link beside Replay for another host', async () => {
    // The default fixture: a SharePoint recap link and a recording. Story
    // 2.2's rule, kept — the recording wins.
    answers(response())
    render(<MeetingMoments meetingId="meeting-1" />)

    await screen.findByTestId('drilldown-segment-seg-1')
    expect(screen.getAllByRole('button', { name: /^Replay recording/ }).length).toBeGreaterThan(0)
    expect(screen.queryByTestId(/^drilldown-youtube-link-/)).toBeNull()
    expect(screen.queryByTestId('drilldown-deep-link')).toBeNull()
  })

  it('labels the degraded header link Open on YouTube, untimed at meeting scope', async () => {
    answers(
      response({
        hasRecording: false,
        screenshots: [],
        sourceDeepLink: 'https://www.youtube.com/watch?v=abc',
      }),
    )
    render(<MeetingMoments meetingId="meeting-1" />)

    await screen.findByTestId('drilldown-segment-seg-1')
    const link = screen.getByTestId('drilldown-deep-link')
    expect(link).toBe(screen.getByRole('link', { name: 'Open on YouTube' }))
    // Meeting scope: no `t`, the drop's URL verbatim.
    expect(link).toHaveAttribute('href', 'https://www.youtube.com/watch?v=abc')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noreferrer')
    expect(screen.queryByRole('button', { name: /Replay/ })).toBeNull()
    expect(screen.queryByTestId(/^drilldown-youtube-link-/)).toBeNull()
  })

  it('shows an unsafe recap link inert rather than as an anchor', async () => {
    answers(
      response({
        hasRecording: false,
        screenshots: [],
        sourceDeepLink: 'javascript:alert(1)',
      }),
    )
    render(<MeetingMoments meetingId="meeting-1" />)

    const inert = await screen.findByTestId('drilldown-unsafe-link')
    expect(inert).toHaveTextContent('javascript:alert(1)')
    expect(inert.querySelector('a')).toBeNull()
    expect(screen.queryByTestId('drilldown-deep-link')).toBeNull()
  })

  it('shows augmentation copy when the 409 says an augmentation is in flight', async () => {
    refuses(notViewable({ augmenting: true, jobStatus: 'running' }))
    render(<MeetingMoments meetingId="meeting-1" />)

    const notice = await screen.findByTestId('moments-notViewable')
    expect(notice).toHaveTextContent('being augmented')
  })

  it('shows preparing copy when the 409 says a first ingest is in flight', async () => {
    refuses(notViewable({ augmenting: false, jobStatus: 'running' }))
    render(<MeetingMoments meetingId="meeting-1" />)

    const notice = await screen.findByTestId('moments-notViewable')
    expect(notice).toHaveTextContent('first ingest has not settled')
  })

  it('shows failed copy when the 409 carries a failed job status', async () => {
    refuses(notViewable({ augmenting: false, jobStatus: 'failed' }))
    render(<MeetingMoments meetingId="meeting-1" />)

    const notice = await screen.findByTestId('moments-notViewable')
    expect(notice).toHaveTextContent('Ingestion failed')
  })

  it('says the meeting does not exist on the 404 problem', async () => {
    refuses({
      type: 'urn:meetingminer:problem:not-found',
      title: 'Not Found',
      status: 404,
      detail: 'no meeting with id meeting-1',
    })
    render(<MeetingMoments meetingId="meeting-1" />)

    const notice = await screen.findByTestId('moments-notFound')
    expect(notice).toHaveTextContent('No meeting has this id')
  })

  it('names the api address when the read never reaches it', async () => {
    sdk.getMeetingDrilldown.mockRejectedValue(new Error('connection refused'))
    render(<MeetingMoments meetingId="meeting-1" />)

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('http://localhost:8000')
    expect(alert).toHaveTextContent('connection refused')
  })

  it('names the timeout when the api accepts the request and never answers', async () => {
    // shouldAdvanceTime: testing-library's `waitFor` polls on a timer it does
    // not know is faked.
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      // A request that hangs rather than failing: only the component's own
      // expiry timer ends it, and only `AbortSignal.any` delivers that abort.
      sdk.getMeetingDrilldown.mockImplementation(
        ({ signal }: { signal: AbortSignal }) =>
          new Promise((_resolve, reject) => {
            signal.addEventListener('abort', () => reject(signal.reason))
          }),
      )
      render(<MeetingMoments meetingId="meeting-1" />)
      await waitFor(() => expect(sdk.getMeetingDrilldown).toHaveBeenCalled())

      await act(async () => {
        await vi.advanceTimersByTimeAsync(MOMENT_TIMEOUT_MS + 100)
      })

      const alert = await screen.findByRole('alert')
      expect(alert).toHaveTextContent(`timed out after ${MOMENT_TIMEOUT_MS}ms`)
    } finally {
      vi.useRealTimers()
    }
  })

  it('re-reads when pointed at a different meeting', async () => {
    answers(response())
    const { rerender } = render(<MeetingMoments meetingId="meeting-1" />)
    await screen.findByTestId('drilldown-screenshot-shot-1')

    answers(
      response({
        meetingId: 'meeting-2',
        title: 'Sprint Review',
        screenshots: [],
        segments: [],
      }),
    )
    rerender(<MeetingMoments meetingId="meeting-2" />)

    await waitFor(() =>
      expect(sdk.getMeetingDrilldown.mock.calls.at(-1)?.[0].path.meeting_id).toBe(
        'meeting-2',
      ),
    )
    expect(
      await screen.findByRole('heading', { name: 'Sprint Review' }),
    ).toBeInTheDocument()
  })

  it('ignores an aborted old response after the meeting changes', async () => {
    let resolveFirst!: (value: {
      data: MeetingDrilldownResponse
      error: undefined
    }) => void
    sdk.getMeetingDrilldown
      .mockImplementationOnce(
        () =>
          new Promise<{ data: MeetingDrilldownResponse; error: undefined }>(
            (resolve) => {
              resolveFirst = resolve
            },
          ),
      )
      .mockResolvedValueOnce({
        data: response({
          meetingId: 'meeting-2',
          title: 'Sprint Review',
          screenshots: [],
          segments: [],
        }),
        error: undefined,
      })

    const { rerender } = render(<MeetingMoments meetingId="meeting-1" />)
    await waitFor(() => expect(sdk.getMeetingDrilldown).toHaveBeenCalledTimes(1))
    rerender(<MeetingMoments meetingId="meeting-2" />)

    expect(
      await screen.findByRole('heading', { name: 'Sprint Review' }),
    ).toBeInTheDocument()
    await act(async () => {
      resolveFirst({ data: response(), error: undefined })
    })

    expect(screen.getByRole('heading', { name: 'Sprint Review' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Data Hub Demo' })).toBeNull()
  })

  it('states the header stat line from counted served data', async () => {
    answers(response())
    railAnswers(momentsResponse(), {
      'moment-1': momentDetail('moment-1', 2_000, 11_000, []),
      'moment-2': momentDetail('moment-2', 40_000, 46_000, []),
    })
    render(<MeetingMoments meetingId="meeting-1" />)

    const stats = await screen.findByTestId('meeting-stat-line')
    // Evidence extent: the furthest end any capture or segment reaches
    // (60_000 ms) — one minute.
    expect(stats).toHaveTextContent('1 min')
    expect(stats).toHaveTextContent('3 turns')
    // 3 + 8 + 7 words across the three segments.
    expect(stats).toHaveTextContent('18 words')
    // Passages arrive with the moments list.
    await waitFor(() => expect(stats).toHaveTextContent('2 passages'))
    // Lineage: recording present, at least one resolved speaker.
    expect(screen.getByTestId('meeting-lineage')).toHaveTextContent(
      'Recording + transcript · speaker-attributed',
    )
    // Counted section headers (reference idiom: "SCREENS 158").
    expect(screen.getByText('Screens 2')).toBeInTheDocument()
    expect(screen.getByText('Transcript 3 turns')).toBeInTheDocument()
  })

  it('states the transcript-only lineage plainly', async () => {
    answers(response({ hasRecording: false, screenshots: [] }))
    render(<MeetingMoments meetingId="meeting-1" />)

    const lineage = await screen.findByTestId('meeting-lineage')
    expect(lineage).toHaveTextContent('Transcript only — no recording')
    expect(lineage).toHaveTextContent('speaker-attributed')
  })

  it('groups rail artifacts by kind with counts, anchors, and publish state', async () => {
    answers(response())
    railAnswers(momentsResponse(), {
      'moment-1': momentDetail('moment-1', 2_000, 11_000, [
        artifact({ id: 'a-1', kind: 'action-item', title: 'Confirm the SFTP cutover date' }),
        artifact({
          id: 'a-2',
          kind: 'decision',
          state: 'published',
          title: 'Feed moves to SFTP',
          publishedAt: '2026-08-06T09:00:00Z',
          publishRelativePath: 'decisions/feed-moves-to-sftp.md',
          publishCommitSha: 'abcdef1234567890',
        }),
      ]),
      'moment-2': momentDetail('moment-2', 40_000, 46_000, [
        artifact({ id: 'a-3', kind: 'action-item', title: 'Notify the vendor' }),
      ]),
    })
    const onOpenMoment = vi.fn()
    render(<MeetingMoments meetingId="meeting-1" onOpenMoment={onOpenMoment} />)

    // Counted group headers, only for kinds with backing data.
    const actions = await screen.findByTestId('meeting-artifact-group-action-item')
    expect(within(actions).getByText('Action items 2')).toBeInTheDocument()
    expect(screen.getByTestId('meeting-artifact-group-decision')).toBeInTheDocument()
    expect(screen.queryByTestId('meeting-artifact-group-adr')).toBeNull()
    expect(screen.queryByTestId('meeting-artifact-group-story')).toBeNull()

    // Each entry: moment offset anchor, title, state; published rows carry
    // their publish path and short commit.
    const first = screen.getByTestId('meeting-artifact-a-1')
    expect(first).toHaveTextContent('0:02–0:11')
    expect(first).toHaveTextContent('extracted')
    const decision = screen.getByTestId('meeting-artifact-a-2')
    expect(decision).toHaveTextContent('published')
    expect(decision).toHaveTextContent('decisions/feed-moves-to-sftp.md')
    expect(decision).toHaveTextContent('@ abcdef123456')

    // Entries within a group are in offset order.
    const second = screen.getByTestId('meeting-artifact-a-3')
    expect(second).toHaveTextContent('0:40–0:46')
    expect(first.compareDocumentPosition(second)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    )

    // The entry clicks through to its moment.
    await userEvent.click(
      within(second).getByRole('button', {
        name: 'Open moment at 0:40: Notify the vendor',
      }),
    )
    expect(onOpenMoment).toHaveBeenCalledWith('moment-2')

    // The published subset repeats under Published documents, clickable too.
    const docs = screen.getByTestId('meeting-published-docs')
    expect(within(docs).getByText('Published documents 1')).toBeInTheDocument()
    expect(screen.getByTestId('meeting-published-a-2')).toHaveTextContent(
      'decisions/feed-moves-to-sftp.md',
    )
    await userEvent.click(
      within(screen.getByTestId('meeting-published-a-2')).getByRole('button'),
    )
    expect(onOpenMoment).toHaveBeenCalledWith('moment-1')
  })

  it('says the rail has nothing extracted when the moments carry no artifacts', async () => {
    answers(response())
    railAnswers(momentsResponse(), {
      'moment-1': momentDetail('moment-1', 2_000, 11_000, []),
      'moment-2': momentDetail('moment-2', 40_000, 46_000, []),
    })
    render(<MeetingMoments meetingId="meeting-1" />)

    expect(await screen.findByTestId('meeting-artifacts-empty')).toHaveTextContent(
      'Nothing extracted from this meeting yet',
    )
    expect(screen.queryByTestId('meeting-published-docs')).toBeNull()
  })

  it('degrades the rail alone when the moments list cannot be read', async () => {
    answers(response())
    sdk.listMeetingMoments.mockResolvedValue({
      data: undefined,
      error: {
        type: 'urn:meetingminer:problem:not-found',
        title: 'Not Found',
        status: 404,
        detail: 'no meeting with id meeting-1',
      },
    })
    render(<MeetingMoments meetingId="meeting-1" />)

    // The transcript still renders; only the rail says why it cannot.
    expect(await screen.findByTestId('drilldown-segment-seg-1')).toBeInTheDocument()
    expect(
      await screen.findByTestId('meeting-artifacts-unavailable'),
    ).toHaveTextContent('Extracted artifacts unavailable')
    // No artifact fan-out happens without a moments list.
    expect(sdk.getMoment).not.toHaveBeenCalled()
  })

  it('marks the artifact list incomplete when a moment read fails', async () => {
    answers(response())
    // moment-2 is missing from the details map, so its read answers 404.
    railAnswers(momentsResponse(), {
      'moment-1': momentDetail('moment-1', 2_000, 11_000, [
        artifact({ id: 'a-1' }),
      ]),
    })
    render(<MeetingMoments meetingId="meeting-1" />)

    expect(await screen.findByTestId('meeting-artifacts-partial')).toHaveTextContent(
      'may be incomplete',
    )
    // The surviving moment's artifacts still render.
    expect(screen.getByTestId('meeting-artifact-a-1')).toBeInTheDocument()
  })

  it('lists resolved participants with turn counts and jumps to their first line', async () => {
    answers(response())
    render(<MeetingMoments meetingId="meeting-1" />)

    const rail = await screen.findByTestId('meeting-participants')
    expect(within(rail).getByText('Participants 2')).toBeInTheDocument()
    expect(within(rail).getByText('Goeke, Timothy')).toBeInTheDocument()
    expect(within(rail).getByText('Whitmore, Ellis')).toBeInTheDocument()
    // The unresolved 'Speaker 8' never became a participant — never guessed.
    expect(within(rail).queryByText('Speaker 8')).toBeNull()

    await userEvent.click(
      within(rail).getByRole('button', { name: 'Show Whitmore, Ellis in transcript' }),
    )
    expect(screen.getByTestId('drilldown-segment-seg-2')).toHaveAttribute(
      'data-jump-target',
      'true',
    )
  })

  it('states the participant absence note when no speaker resolved', async () => {
    answers(
      response({
        segments: [
          {
            segmentId: 'seg-1',
            ordinal: 1,
            startMs: 2_000,
            endMs: 4_000,
            speakerLabel: 'Speaker 1',
            speakerResolution: 'unresolved',
            participantId: null,
            text: 'Everybody, good morning.',
            momentId: null,
          },
        ],
      }),
    )
    render(<MeetingMoments meetingId="meeting-1" />)

    expect(await screen.findByTestId('participants-absence')).toHaveTextContent(
      'No participant graph for this meeting',
    )
  })

  it('jumps an unaligned film-strip capture to its aligned transcript passage', async () => {
    answers(response())
    render(<MeetingMoments meetingId="meeting-1" />)

    // shot-2 (offset 30s) names no moment; its aligned passage is the last
    // segment starting at or before 30s — seg-1.
    const second = await screen.findByTestId('drilldown-screenshot-shot-2')
    await userEvent.click(
      within(second).getByRole('button', { name: 'Show transcript at 0:30' }),
    )
    expect(screen.getByTestId('drilldown-segment-seg-1')).toHaveAttribute(
      'data-jump-target',
      'true',
    )
  })
})
