import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SpeakerNaming } from './SpeakerNaming'

const sdk = vi.hoisted(() => ({
  listMeetingSpeakers: vi.fn(),
  getMeetingDrilldown: vi.fn(),
  listParticipants: vi.fn(),
  assignMeetingSpeaker: vi.fn(),
  getJob: vi.fn(),
}))

vi.mock('@/client/sdk.gen', () => ({
  ...sdk,
  streamJobEvents: vi.fn(),
}))

vi.mock('@/features/meetings/useJobEvents', () => ({
  useJobEvents: () => ({ kind: 'live' as const }),
}))

vi.mock('@/features/settings/singleKeyShortcuts', () => ({
  useSingleKeyShortcutsEnabled: () => false,
}))

vi.mock('@/features/replay/ReplayPlayer', () => ({
  ReplayPlayer: () => <div data-testid="shortcut-replay" />,
}))

const MEETING_ID = '0190a0f0-7c1e-7000-8000-0000000000aa'

beforeEach(() => {
  sdk.assignMeetingSpeaker.mockReset()
  sdk.getJob.mockReset()
  sdk.listMeetingSpeakers.mockResolvedValue({
    data: {
      meetingId: MEETING_ID,
      speakers: [
        {
          speakerLabel: 'SPEAKER_00',
          speakerResolution: 'placeholder',
          participantId: null,
          displayName: null,
          talkTimeMs: 1_000,
          segmentCount: 1,
          sampleOffsetsMs: [500, 1_500, 2_500],
        },
      ],
    },
    error: undefined,
  })
  sdk.getMeetingDrilldown.mockResolvedValue({
    data: {
      meetingId: MEETING_ID,
      title: 'Shortcut fixture',
      hasRecording: true,
      corpus: 'real',
      startedAt: '2026-08-21T09:00:00Z',
      startedAtPrecision: 'exact',
      sourceDeepLink: null,
      screenshots: [],
      segments: [
        {
          segmentId: 'segment-1',
          ordinal: 1,
          startMs: 500,
          endMs: 1_000,
          speakerLabel: 'SPEAKER_00',
          speakerResolution: 'placeholder',
          participantId: null,
          text: 'A short sample.',
          momentId: null,
        },
      ],
    },
    error: undefined,
  })
  sdk.listParticipants.mockResolvedValue({ data: [], error: undefined })
})

describe('F13 owner ruling: disabled screen shortcuts', () => {
  it('does not replay or mark unresolved when single-key shortcuts are off', async () => {
    render(<SpeakerNaming meetingId={MEETING_ID} />)

    const row = await screen.findByRole('button', { name: /SPEAKER_00/ })
    await userEvent.click(row)
    await waitFor(() => expect(row).toHaveAttribute('aria-pressed', 'true'))

    const panel = screen.getByTestId('naming-panel')
    fireEvent.keyDown(panel, { key: '1' })
    fireEvent.keyDown(panel, { key: 'u' })

    expect(screen.queryByTestId('shortcut-replay')).not.toBeInTheDocument()
    expect(sdk.assignMeetingSpeaker).not.toHaveBeenCalled()
  })
})
