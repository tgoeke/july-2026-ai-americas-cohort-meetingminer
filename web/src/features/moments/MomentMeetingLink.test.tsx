import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { MomentDetail } from '@/client/types.gen'
import { MOMENT_TIMEOUT_MS } from './moments'
import { MomentView } from './MomentView'

/**
 * The one insertion into the moment view: the way up to the meeting the
 * moment came from, tested in its own module.
 *
 * `MomentView.test.tsx` owns the view's anatomy and its fixtures; this file
 * asserts only the new control, so that suite stays the untouched check that
 * this insertion restructured nothing — the arrangement
 * `MeetingSpeakersLink.test.tsx` uses for story 7.4's insertion. The route
 * seam it hangs on is pinned separately, in `MomentMeetingRoute.test.tsx`.
 *
 * Queries go through the accessible name wherever they can: the name is the
 * contract a screen-reader or voice user meets, and asserting it means
 * deleting the `aria-label` fails a test rather than passing quietly.
 */

const NAME = /^Open the meeting:/

const sdk = vi.hoisted(() => ({
  getMoment: vi.fn(),
  getExtractionPrompts: vi.fn(),
}))

// Spread the real generated client rather than enumerating its exports
// (`AddMeetingRoute.test.tsx`'s idiom): `web/src/client/` is regenerated, so a
// hand-written list goes stale on the next `make client`.
vi.mock('@/client/sdk.gen', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/client/sdk.gen')>()),
  getMoment: sdk.getMoment,
  getExtractionPrompts: sdk.getExtractionPrompts,
  approveMomentArtifacts: vi.fn(),
}))

function detail(overrides: Partial<MomentDetail> = {}): MomentDetail {
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
    ...overrides,
  }
}

function answers(body: MomentDetail = detail()) {
  sdk.getMoment.mockResolvedValue({ data: body, error: undefined })
}

beforeEach(() => {
  sdk.getMoment.mockReset()
  sdk.getExtractionPrompts.mockReset()
  // Left pending, like the owning suite's default: the prompts section is
  // global config and irrelevant to this control.
  sdk.getExtractionPrompts.mockReturnValue(new Promise(() => {}))
})

describe('the moment view’s way to its meeting', () => {
  it('hands the shell the loaded moment’s meeting id when activated', async () => {
    answers()
    const onOpenMeeting = vi.fn()
    render(<MomentView momentId="moment-1" onOpenMeeting={onOpenMeeting} />)

    await userEvent.click(await screen.findByRole('button', { name: NAME }))

    expect(onOpenMeeting).toHaveBeenCalledTimes(1)
    expect(onOpenMeeting).toHaveBeenCalledWith('meeting-1')
  })

  it('names the meeting, and reads the same by eye and by ear', async () => {
    answers()
    render(<MomentView momentId="moment-1" onOpenMeeting={vi.fn()} />)

    const control = await screen.findByRole('button', {
      name: 'Open the meeting: Data Hub Demo',
    })
    // The visible label is a whole substring of the accessible name
    // (WCAG 2.5.3), so a voice user saying what they see reaches this
    // control — which is why the label carries no decorative glyph.
    expect(control.textContent).toBe('Open the meeting')
  })

  it('is the first thing the keyboard reaches, above the heading', async () => {
    answers()
    render(<MomentView momentId="moment-1" onOpenMeeting={vi.fn()} />)
    const control = await screen.findByRole('button', { name: NAME })

    // Tabbed to, not focused programmatically: this is the assertion that
    // the control is in the tab order at all, and first — the view's way out
    // must not sit behind the artifact rail and the transcript.
    await userEvent.tab()
    expect(control).toHaveFocus()

    // And it precedes the heading in document order, which is what puts it
    // first for a screen reader too, not only for the tab key.
    const heading = screen.getByRole('heading', { level: 2 })
    expect(control.compareDocumentPosition(heading)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    )
  })

  it('activates from the keyboard', async () => {
    answers()
    const onOpenMeeting = vi.fn()
    render(<MomentView momentId="moment-1" onOpenMeeting={onOpenMeeting} />)
    await screen.findByRole('button', { name: NAME })

    await userEvent.tab()
    await userEvent.keyboard('{Enter}')

    expect(onOpenMeeting).toHaveBeenCalledWith('meeting-1')
  })

  it('falls back to the meeting id when the moment carries no title', async () => {
    answers(detail({ meetingTitle: null }))
    render(<MomentView momentId="moment-1" onOpenMeeting={vi.fn()} />)

    expect(
      await screen.findByRole('button', { name: 'Open the meeting: meeting-1' }),
    ).toBeInTheDocument()
  })

  it('offers nothing while the read is still in flight', () => {
    sdk.getMoment.mockReturnValue(new Promise(() => {}))
    render(<MomentView momentId="moment-1" onOpenMeeting={vi.fn()} />)

    // Nothing has named a meeting yet, so there is nowhere honest to go.
    expect(screen.getByText('Loading moment…')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: NAME })).not.toBeInTheDocument()
  })

  it.each([
    [
      'a moment that does not exist',
      {
        type: 'urn:meetingminer:problem:not-found',
        title: 'Not Found',
        status: 404,
        detail: 'no moment has id moment-1',
      },
      'moment-notFound',
    ],
    [
      'a meeting whose evidence is still being prepared',
      {
        type: 'urn:meetingminer:problem:meeting-not-viewable',
        title: 'Conflict',
        status: 409,
        detail: 'meeting meeting-1 exists but its evidence is still being prepared',
      },
      'moment-notViewable',
    ],
  ])('offers nothing when the read was refused — %s', async (_case, problem, testId) => {
    sdk.getMoment.mockResolvedValue({ data: undefined, error: problem })
    render(<MomentView momentId="moment-1" onOpenMeeting={vi.fn()} />)

    expect(await screen.findByTestId(testId)).toBeInTheDocument()
    // Deliberate, including for the 409: this view offers a way out only to a
    // meeting the loaded moment named. It never guesses one out of a refusal.
    expect(screen.queryByRole('button', { name: NAME })).not.toBeInTheDocument()
  })

  it('offers nothing when the api was never reached', async () => {
    // shouldAdvanceTime: testing-library's `waitFor` polls on a timer it does
    // not know is faked — the owning suite's timeout idiom.
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      // A request that hangs rather than failing: only the component's own
      // expiry timer ends it.
      sdk.getMoment.mockImplementation(
        ({ signal }: { signal: AbortSignal }) =>
          new Promise((_resolve, reject) => {
            signal.addEventListener('abort', () => reject(signal.reason))
          }),
      )
      render(<MomentView momentId="moment-1" onOpenMeeting={vi.fn()} />)
      await waitFor(() => expect(sdk.getMoment).toHaveBeenCalled())

      await act(async () => {
        await vi.advanceTimersByTimeAsync(MOMENT_TIMEOUT_MS + 100)
      })

      expect(await screen.findByRole('alert')).toHaveTextContent(
        `timed out after ${MOMENT_TIMEOUT_MS}ms`,
      )
      expect(screen.queryByRole('button', { name: NAME })).not.toBeInTheDocument()
    } finally {
      vi.useRealTimers()
    }
  })

  it('renders no control when the shell supplied nowhere to go', async () => {
    answers()
    render(<MomentView momentId="moment-1" />)

    // The view still answers — the prop is optional, not required.
    expect(await screen.findByText(/Data Hub Demo at/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: NAME })).not.toBeInTheDocument()
  })

  it('retargets when the view is pointed at a moment in another meeting', async () => {
    answers()
    const onOpenMeeting = vi.fn()
    const { rerender } = render(
      <MomentView momentId="moment-1" onOpenMeeting={onOpenMeeting} />,
    )
    await screen.findByRole('button', { name: NAME })

    answers(
      detail({
        momentId: 'moment-2',
        meetingId: 'meeting-2',
        meetingTitle: 'Ingest Review',
      }),
    )
    rerender(<MomentView momentId="moment-2" onOpenMeeting={onOpenMeeting} />)

    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Open the meeting: Ingest Review' }),
      ).toBeInTheDocument(),
    )
    await userEvent.click(screen.getByRole('button', { name: NAME }))

    // The previous meeting is never the destination of the new moment.
    expect(onOpenMeeting).toHaveBeenCalledTimes(1)
    expect(onOpenMeeting).toHaveBeenCalledWith('meeting-2')
  })
})
