import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { MeetingDrilldownResponse } from '@/client/types.gen'
import { MeetingMoments } from './MeetingMoments'

/**
 * Story 7.4's one insertion into the meeting view, tested in its own module.
 *
 * Story 2.2 owns `MeetingMoments.test.tsx` and its fixtures; this file asserts
 * only the new control, so the two stories never edit one test module and the
 * 2.2 suite stays the check that this insertion restructured nothing.
 */

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
  listMeetingSpeakers: vi.fn(),
  assignMeetingSpeaker: vi.fn(),
}))

function drilldown(): MeetingDrilldownResponse {
  return {
    meetingId: 'meeting-1',
    title: 'Weekly community sync',
    hasRecording: true,
    corpus: 'real',
    startedAt: '2026-08-21T09:00:00Z',
    startedAtPrecision: 'second',
    sourceDeepLink: null,
    screenshots: [],
    segments: [
      {
        segmentId: 's-1',
        ordinal: 1,
        startMs: 0,
        endMs: 8000,
        speakerLabel: 'SPEAKER_00',
        speakerResolution: 'placeholder',
        participantId: null,
        text: 'The retrieval split held up.',
        momentId: null,
      },
    ],
  }
}

beforeEach(() => {
  sdk.getMeetingDrilldown.mockReset()
  sdk.listMeetingMoments.mockReset()
  sdk.getMoment.mockReset()
  sdk.getMeetingDrilldown.mockResolvedValue({ data: drilldown(), error: undefined })
  sdk.listMeetingMoments.mockResolvedValue({
    data: { meetingId: 'meeting-1', moments: [] },
    error: undefined,
  })
})

describe('reaching the speaker naming screen from the meeting view', () => {
  it('offers Name speakers and hands the navigation to the shell', async () => {
    const onOpenSpeakers = vi.fn()
    const user = userEvent.setup()
    render(<MeetingMoments meetingId="meeting-1" onOpenSpeakers={onOpenSpeakers} />)

    const control = await screen.findByTestId('meeting-name-speakers')
    await user.click(control)

    expect(onOpenSpeakers).toHaveBeenCalledTimes(1)
  })

  it('offers nothing when the shell gave it nowhere to go', async () => {
    // The same rule the moment links already follow: this view never invents
    // a destination, so with no handler there is no dead control.
    render(<MeetingMoments meetingId="meeting-1" />)
    await screen.findByTestId('meeting-participants')

    expect(screen.queryByTestId('meeting-name-speakers')).not.toBeInTheDocument()
  })
})
