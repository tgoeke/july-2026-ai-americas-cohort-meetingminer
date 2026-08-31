import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '@/App'
import type { MeetingDrilldownResponse, MomentDetail } from '@/client/types.gen'
import { childRoutes } from '@/routes/registry'
import { route as momentRoute } from './MomentView.route'

/**
 * The seam the moment view's "Open the meeting" control hangs on, pinned.
 *
 * `MomentMeetingLink.test.tsx` renders `MomentView` with its own handler, so
 * it proves the control calls back with the right meeting id and nothing
 * more: a typo'd path, or a route that stopped passing `onOpenMeeting` at
 * all, would leave every one of its assertions green while the reader landed
 * on `App.tsx`'s catch-all — a control that looks like it works and does
 * nothing. This mounts the real shell at `/moments/:momentId` and follows the
 * control to the meeting screen, the way `AddMeetingRoute.test.tsx` and
 * `threadsRoutes.review.test.tsx` pin that same class of failure.
 */

const sdk = vi.hoisted(() => ({
  getMoment: vi.fn(),
  getMeetingDrilldown: vi.fn(),
  listMeetingMoments: vi.fn(),
}))

vi.mock('@/client/sdk.gen', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/client/sdk.gen')>()),
  getMoment: sdk.getMoment,
  getMeetingDrilldown: sdk.getMeetingDrilldown,
  listMeetingMoments: sdk.listMeetingMoments,
  // The shell's own reads are not what this test is about; each one refuses
  // loudly rather than reaching an api that is not running.
  getHealth: vi.fn(() => Promise.reject(new Error('no api in this test'))),
  listMeetings: vi.fn(() => Promise.reject(new Error('no api in this test'))),
  streamJobEvents: vi.fn(() => Promise.reject(new Error('no api in this test'))),
  searchCorpus: vi.fn(() => Promise.reject(new Error('no api in this test'))),
  askCorpus: vi.fn(() => Promise.reject(new Error('no api in this test'))),
  getCorpusStats: vi.fn(() => Promise.reject(new Error('no api in this test'))),
  getSystemStatus: vi.fn(() => Promise.reject(new Error('no api in this test'))),
  getConfiguration: vi.fn(() => Promise.reject(new Error('no api in this test'))),
  getMomentsFeed: vi.fn(() => Promise.reject(new Error('no api in this test'))),
  getExtractionPrompts: vi.fn(() => Promise.reject(new Error('no api in this test'))),
}))

function momentDetail(): MomentDetail {
  return {
    momentId: 'moment-1',
    meetingId: 'meeting-1',
    meetingTitle: 'Data Hub Demo',
    corpus: 'real',
    hasRecording: false,
    startMs: 44_000,
    endMs: 46_000,
    startedAt: '2026-08-05T12:01:03Z',
    startedAtPrecision: 'second',
    screenshotId: null,
    screenshotPath: null,
    sourceDeepLink: null,
    superseded: false,
    segments: [],
    artifacts: [],
  }
}

function drilldown(): MeetingDrilldownResponse {
  return {
    meetingId: 'meeting-1',
    title: 'Data Hub Demo',
    hasRecording: false,
    corpus: 'real',
    startedAt: '2026-08-05T12:00:00Z',
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
        text: 'We moved that feed to SFTP last week.',
        momentId: null,
      },
    ],
  }
}

beforeEach(() => {
  sdk.getMoment.mockReset()
  sdk.getMeetingDrilldown.mockReset()
  sdk.listMeetingMoments.mockReset()
  sdk.getMoment.mockResolvedValue({ data: momentDetail(), error: undefined })
  sdk.getMeetingDrilldown.mockResolvedValue({ data: drilldown(), error: undefined })
  sdk.listMeetingMoments.mockResolvedValue({
    data: { meetingId: 'meeting-1', moments: [] },
    error: undefined,
  })
  window.history.replaceState(null, '', '/moments/moment-1')
})

afterEach(() => {
  window.history.replaceState(null, '', '/')
})

describe('reaching the meeting from a moment, through the real shell', () => {
  it('mounts the moment route from the registry, so App.tsx needs no edit', () => {
    expect(momentRoute.path).toBe('/moments/:momentId')
    expect(childRoutes.map((route) => route.path)).toContain('/moments/:momentId')
  })

  it('lands on the meeting drill-down, not the unknown-path catch-all', async () => {
    render(<App />)

    await userEvent.click(
      await screen.findByRole('button', { name: /^Open the meeting:/ }),
    )

    // The meeting screen itself, reached by URL: the path the route composed
    // matched `/meetings/:meetingId` and asked the api for this moment's
    // meeting — the whole point of the control.
    expect(await screen.findByTestId('drilldown-transcript')).toBeInTheDocument()
    expect(window.location.pathname).toBe('/meetings/meeting-1')
    expect(sdk.getMeetingDrilldown).toHaveBeenCalledWith(
      expect.objectContaining({ path: { meeting_id: 'meeting-1' } }),
    )
  })
})
