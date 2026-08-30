import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { MomentDetail } from '@/client/types.gen'
import { ARTIFACT_CATEGORIES, EXTRACTION_PROMPTS_TIMEOUT_MS, MOMENT_TIMEOUT_MS } from './moments'
import { MomentView } from './MomentView'

const sdk = vi.hoisted(() => ({
  getMoment: vi.fn(),
  approveMomentArtifacts: vi.fn(),
  getExtractionPrompts: vi.fn(),
}))

vi.mock('@/client/sdk.gen', () => ({
  getMeetingDrilldown: vi.fn(),
  getMoment: sdk.getMoment,
  approveMomentArtifacts: sdk.approveMomentArtifacts,
  getExtractionPrompts: sdk.getExtractionPrompts,
  listMeetingMoments: vi.fn(),
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

function detail(overrides: Partial<MomentDetail> = {}): MomentDetail {
  return {
    momentId: 'moment-1',
    meetingId: 'meeting-1',
    meetingTitle: 'Data Hub Demo',
    corpus: 'real',
    hasRecording: true,
    startMs: 44_000,
    endMs: 46_000,
    startedAt: '2026-08-05T12:01:03Z',
    startedAtPrecision: 'second',
    screenshotId: 'screenshot-1',
    screenshotPath: 'meetings/meeting-1/screenshots/2.jpg',
    sourceDeepLink: null,
    superseded: false,
    segments: [
      {
        startMs: 40_000,
        endMs: 42_000,
        speakerLabel: 'Speaker 8',
        speakerResolution: 'unresolved',
        participantId: null,
        text: 'We moved that feed to SFTP last week.',
      },
      {
        startMs: 44_000,
        endMs: 46_000,
        speakerLabel: 'Whitmore, Ellis',
        speakerResolution: 'resolved',
        participantId: 'participant-2',
        text: 'And the purchase order still needs approval.',
      },
    ],
    artifacts: [],
    ...overrides,
  }
}

function answers(body: MomentDetail) {
  sdk.getMoment.mockResolvedValue({ data: body, error: undefined })
}

function refuses(problem: Record<string, unknown>) {
  sdk.getMoment.mockResolvedValue({ data: undefined, error: problem })
}

beforeEach(() => {
  sdk.getMoment.mockReset()
  sdk.approveMomentArtifacts.mockReset()
  sdk.getExtractionPrompts.mockReset()
  // The default: an unanswered promise, matching most tests below that never
  // exercise the prompts fetch at all — it stays pending, `prompts` stays
  // `null`, and the section never renders. Individual tests override this.
  sdk.getExtractionPrompts.mockReturnValue(new Promise(() => {}))
})

describe('MomentView', () => {
  it('renders the still on top, the covering transcript below', async () => {
    answers(detail())
    render(<MomentView momentId="moment-1" />)

    const screenshot = await screen.findByTestId('moment-screenshot')
    expect(screenshot).toHaveAttribute(
      'src',
      'http://localhost:8000/media/meetings/meeting-1/screenshots/2.jpg',
    )

    const transcript = screen.getByTestId('moment-transcript')
    expect(transcript).toHaveTextContent('Speaker 8')
    expect(transcript).toHaveTextContent('We moved that feed to SFTP last week.')
    expect(transcript).toHaveTextContent('Whitmore, Ellis')
    // The still precedes the transcript in document order — CAP-4's anatomy.
    expect(screenshot.compareDocumentPosition(transcript)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    )
  })

  it('places the artifact rail first in document order on the stacked layout, restoring the two-column order at md via matching order classes', async () => {
    answers(detail())
    render(<MomentView momentId="moment-1" />)

    const rail = await screen.findByTestId('moment-artifact-rail')
    const screenshot = await screen.findByTestId('moment-screenshot')
    const mainColumn = screenshot.closest('div[class*="min-w-0"]')
    expect(mainColumn).not.toBeNull()

    // Document order — and therefore the stacked (below-`md`) visual order,
    // tab order, and screen-reader linearization — is the rail, then the
    // screenshot/replay/transcript column: the rail is reachable without
    // passing through that column first.
    expect(rail.compareDocumentPosition(mainColumn as Element)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    )

    // At `md`+ each carries the order class that restores the original
    // left (main column) / right (rail) layout on top of that mobile-first order.
    expect(rail.className).toContain('md:order-2')
    expect((mainColumn as Element).className).toContain('md:order-1')
  })

  it('shows all seven rail categories with the explicit empty state', async () => {
    answers(detail())
    render(<MomentView momentId="moment-1" />)

    const rail = await screen.findByTestId('moment-artifact-rail')
    for (const category of ARTIFACT_CATEGORIES) {
      expect(
        screen.getByTestId(`artifact-category-${category.kind}`),
      ).toHaveTextContent(category.label)
    }
    expect(rail).toHaveTextContent('Nothing extracted yet')
    expect(screen.getByTestId('artifact-rail-empty')).toBeInTheDocument()
  })

  it('lists an artifact under its category and keeps the empty state away', async () => {
    answers(
      detail({
        artifacts: [
          {
            id: 'artifact-1',
            kind: 'decision',
            state: 'extracted',
            title: 'Move the feed to SFTP',
            body: 'Decided during the demo.',
          },
        ],
      }),
    )
    render(<MomentView momentId="moment-1" />)

    const category = await screen.findByTestId('artifact-category-decision')
    expect(category).toHaveTextContent('Move the feed to SFTP')
    expect(screen.queryByTestId('artifact-rail-empty')).toBeNull()
  })

  it('hides the approve gesture when no artifact is extracted', async () => {
    answers(
      detail({
        artifacts: [
          {
            id: 'artifact-1',
            kind: 'adr',
            state: 'published',
            title: 'Adopt SFTP',
            body: 'Body.',
            publishedAt: '2026-08-05T12:05:00Z',
            publishRelativePath: 'adr/artifact-1.md',
            publishCommitSha: 'a'.repeat(40),
          },
        ],
      }),
    )
    render(<MomentView momentId="moment-1" />)

    await screen.findByTestId('moment-artifact-rail')
    expect(screen.queryByRole('button', { name: 'Approve & publish' })).toBeNull()
  })

  it('shows the outbound export path (and commit sha) for a published artifact', async () => {
    answers(
      detail({
        artifacts: [
          {
            id: 'artifact-1',
            kind: 'adr',
            state: 'published',
            title: 'Adopt SFTP',
            body: 'Body.',
            publishedAt: '2026-08-05T12:05:00Z',
            publishRelativePath: 'adr/artifact-1.md',
            publishCommitSha: 'a'.repeat(40),
          },
        ],
      }),
    )
    render(<MomentView momentId="moment-1" />)

    const link = await screen.findByTestId('artifact-published-link-artifact-1')
    expect(link).toHaveTextContent('adr/artifact-1.md')
    expect(link).toHaveTextContent('a'.repeat(12))
  })

  it('offers the approve gesture, calls the api, and replaces the rail on success', async () => {
    answers(
      detail({
        artifacts: [
          {
            id: 'artifact-1',
            kind: 'adr',
            state: 'extracted',
            title: 'Adopt SFTP',
            body: 'Body.',
          },
        ],
      }),
    )
    sdk.approveMomentArtifacts.mockResolvedValue({
      data: [
        {
          id: 'artifact-1',
          kind: 'adr',
          state: 'published',
          title: 'Adopt SFTP',
          body: 'Body.',
          publishedAt: '2026-08-05T12:05:00Z',
          publishRelativePath: 'adr/artifact-1.md',
          publishCommitSha: 'b'.repeat(40),
        },
      ],
      error: undefined,
    })
    render(<MomentView momentId="moment-1" />)

    const approve = await screen.findByRole('button', { name: 'Approve & publish' })
    await userEvent.click(approve)

    expect(sdk.approveMomentArtifacts).toHaveBeenCalledWith(
      expect.objectContaining({ path: { moment_id: 'moment-1' } }),
    )
    expect(await screen.findByTestId('artifact-published-link-artifact-1')).toHaveTextContent(
      'adr/artifact-1.md',
    )
    expect(screen.queryByRole('button', { name: 'Approve & publish' })).toBeNull()
  })

  it('surfaces a message and leaves the rail unchanged when approve fails', async () => {
    answers(
      detail({
        artifacts: [
          {
            id: 'artifact-1',
            kind: 'adr',
            state: 'extracted',
            title: 'Adopt SFTP',
            body: 'Body.',
          },
        ],
      }),
    )
    sdk.approveMomentArtifacts.mockResolvedValue({
      data: undefined,
      error: {
        type: 'urn:meetingminer:problem:nothing-to-approve',
        title: 'Conflict',
        status: 409,
        detail: 'moment moment-1 has no extracted artifacts to approve',
      },
    })
    render(<MomentView momentId="moment-1" />)

    const approve = await screen.findByRole('button', { name: 'Approve & publish' })
    await userEvent.click(approve)

    expect(await screen.findByTestId('moment-approve-error')).toHaveTextContent(
      'no extracted artifacts to approve',
    )
    // The rail still shows the artifact as extracted — nothing was replaced.
    expect(screen.getByRole('button', { name: 'Approve & publish' })).toBeInTheDocument()
    expect(screen.queryByTestId('artifact-published-link-artifact-1')).toBeNull()
  })

  it('disables the approve button and shows the in-flight label while publishing', async () => {
    answers(
      detail({
        artifacts: [
          { id: 'artifact-1', kind: 'adr', state: 'extracted', title: 'Adopt SFTP', body: 'Body.' },
        ],
      }),
    )
    let resolveApprove!: (value: { data: unknown; error: undefined }) => void
    sdk.approveMomentArtifacts.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveApprove = resolve
        }),
    )
    render(<MomentView momentId="moment-1" />)

    const approve = await screen.findByRole('button', { name: 'Approve & publish' })
    await userEvent.click(approve)

    const pending = await screen.findByRole('button', { name: 'Publishing…' })
    expect(pending).toBeDisabled()

    await act(async () => {
      resolveApprove({
        data: [
          {
            id: 'artifact-1',
            kind: 'adr',
            state: 'published',
            title: 'Adopt SFTP',
            body: 'Body.',
            publishedAt: '2026-08-05T12:05:00Z',
            publishRelativePath: 'adr/artifact-1.md',
            publishCommitSha: 'c'.repeat(40),
          },
        ],
        error: undefined,
      })
    })

    expect(screen.queryByRole('button', { name: 'Publishing…' })).toBeNull()
    expect(await screen.findByTestId('artifact-published-link-artifact-1')).toBeInTheDocument()
  })

  it('re-enables the approve button after a failure, not stuck disabled', async () => {
    answers(
      detail({
        artifacts: [
          { id: 'artifact-1', kind: 'adr', state: 'extracted', title: 'Adopt SFTP', body: 'Body.' },
        ],
      }),
    )
    let resolveApprove!: (value: { data: undefined; error: Record<string, unknown> }) => void
    sdk.approveMomentArtifacts.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveApprove = resolve
        }),
    )
    render(<MomentView momentId="moment-1" />)

    const approve = await screen.findByRole('button', { name: 'Approve & publish' })
    await userEvent.click(approve)

    const pending = await screen.findByRole('button', { name: 'Publishing…' })
    expect(pending).toBeDisabled()

    await act(async () => {
      resolveApprove({
        data: undefined,
        error: {
          type: 'urn:meetingminer:problem:nothing-to-approve',
          title: 'Conflict',
          status: 409,
          detail: 'moment moment-1 has no extracted artifacts to approve',
        },
      })
    })

    const reenabled = await screen.findByRole('button', { name: 'Approve & publish' })
    expect(reenabled).not.toBeDisabled()
    expect(screen.getByTestId('moment-approve-error')).toBeInTheDocument()
  })

  it('ignores a stale approve response after the moment changes mid-request', async () => {
    answers(
      detail({
        artifacts: [
          { id: 'artifact-1', kind: 'adr', state: 'extracted', title: 'Adopt SFTP', body: 'Body.' },
        ],
      }),
    )
    let resolveApprove!: (value: { data: unknown; error: undefined }) => void
    sdk.approveMomentArtifacts.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveApprove = resolve
        }),
    )
    const { rerender } = render(<MomentView momentId="moment-1" />)

    const approve = await screen.findByRole('button', { name: 'Approve & publish' })
    await userEvent.click(approve)
    await screen.findByRole('button', { name: 'Publishing…' })

    // Switch to a different moment while the approve call is still in flight.
    answers(detail({ momentId: 'moment-2', meetingTitle: 'Sprint Review', artifacts: [] }))
    rerender(<MomentView momentId="moment-2" />)
    await screen.findByRole('heading', { name: 'Sprint Review at 0:44' })

    await act(async () => {
      resolveApprove({
        data: [
          {
            id: 'artifact-1',
            kind: 'adr',
            state: 'published',
            title: 'Adopt SFTP',
            body: 'Body.',
            publishedAt: '2026-08-05T12:05:00Z',
            publishRelativePath: 'adr/artifact-1.md',
            publishCommitSha: 'd'.repeat(40),
          },
        ],
        error: undefined,
      })
    })

    // The stale response must not resurrect moment-1's artifact under
    // moment-2's now-empty rail.
    expect(screen.getByTestId('artifact-rail-empty')).toBeInTheDocument()
    expect(screen.queryByTestId('artifact-published-link-artifact-1')).toBeNull()
  })

  it('times out approval, restores its control, and ignores a late response', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      answers(
        detail({
          artifacts: [
            { id: 'artifact-1', kind: 'adr', state: 'extracted', title: 'Adopt SFTP', body: 'Body.' },
          ],
        }),
      )
      let resolveApprove!: (value: { data: unknown; error: undefined }) => void
      let approveSignal: AbortSignal | undefined
      // Deliberately ignore its abort signal: a transport can settle after a
      // client deadline, and that late result must not replace the rail.
      sdk.approveMomentArtifacts.mockImplementation(
        ({ signal }: { signal?: AbortSignal }) =>
          new Promise((resolve) => {
            approveSignal = signal
            resolveApprove = resolve
          }),
      )
      render(<MomentView momentId="moment-1" />)

      const approve = await screen.findByRole('button', { name: 'Approve & publish' })
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
      await user.click(approve)
      expect(screen.getByRole('button', { name: 'Publishing…' })).toBeDisabled()

      await act(async () => {
        await vi.advanceTimersByTimeAsync(MOMENT_TIMEOUT_MS + 100)
      })

      expect(await screen.findByTestId('moment-approve-error')).toHaveTextContent(
        `timed out after ${MOMENT_TIMEOUT_MS}ms`,
      )
      expect(approveSignal?.aborted).toBe(true)
      expect(screen.getByRole('button', { name: 'Approve & publish' })).not.toBeDisabled()
      expect(screen.queryByTestId('artifact-published-link-artifact-1')).toBeNull()

      await act(async () => {
        resolveApprove({
          data: [
            {
              id: 'artifact-1',
              kind: 'adr',
              state: 'published',
              title: 'Adopt SFTP',
              body: 'Body.',
              publishedAt: '2026-08-05T12:05:00Z',
              publishRelativePath: 'adr/artifact-1.md',
              publishCommitSha: 'e'.repeat(40),
            },
          ],
          error: undefined,
        })
      })

      expect(screen.getByTestId('moment-approve-error')).toHaveTextContent(
        `timed out after ${MOMENT_TIMEOUT_MS}ms`,
      )
      expect(screen.queryByTestId('artifact-published-link-artifact-1')).toBeNull()
    } finally {
      vi.useRealTimers()
    }
  })

  it('mounts the player at the moment’s offset only when replay is pressed', async () => {
    answers(detail())
    render(<MomentView momentId="moment-1" />)

    const replay = await screen.findByRole('button', { name: 'Replay recording at 0:44' })
    expect(screen.queryByTestId('replay-player')).toBeNull()

    await userEvent.click(replay)
    const player = (await screen.findByTestId('replay-player')) as HTMLVideoElement
    expect(player).toHaveAttribute(
      'src',
      'http://localhost:8000/media/recordings/meeting-1',
    )
    expect(player).toHaveAccessibleName('Data Hub Demo at 0:44')
    // The player must be mounted with the *moment's* startMs, not a label
    // that merely reads it: drive the metadata event and assert the seek
    // landed at 44s (the CorpusSearch replay idiom).
    player.currentTime = 0
    act(() => {
      player.dispatchEvent(new Event('loadedmetadata'))
    })
    expect(player.currentTime).toBe(44)
  })

  it('names the timeout when the api accepts the request and never answers', async () => {
    // shouldAdvanceTime: testing-library's `waitFor` polls on a timer it does
    // not know is faked.
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      // A request that hangs rather than failing: only the component's own
      // expiry timer ends it, and only `AbortSignal.any` delivers that abort.
      sdk.getMoment.mockImplementation(
        ({ signal }: { signal: AbortSignal }) =>
          new Promise((_resolve, reject) => {
            signal.addEventListener('abort', () => reject(signal.reason))
          }),
      )
      render(<MomentView momentId="moment-1" />)
      await waitFor(() => expect(sdk.getMoment).toHaveBeenCalled())

      await act(async () => {
        await vi.advanceTimersByTimeAsync(MOMENT_TIMEOUT_MS + 100)
      })

      const alert = await screen.findByRole('alert')
      expect(alert).toHaveTextContent(`timed out after ${MOMENT_TIMEOUT_MS}ms`)
    } finally {
      vi.useRealTimers()
    }
  })

  it('offers the source deep link where replay would be on a transcript-only moment', async () => {
    answers(
      detail({
        hasRecording: false,
        screenshotId: null,
        screenshotPath: null,
        sourceDeepLink: 'https://example.sharepoint.com/stream.aspx?id=x',
      }),
    )
    render(<MomentView momentId="moment-1" />)

    const link = await screen.findByTestId('moment-deep-link')
    expect(link).toHaveAttribute('href', 'https://example.sharepoint.com/stream.aspx?id=x')
    // Another host keeps the untimed label (UX-DR12 changes YouTube only).
    expect(link).toHaveAccessibleName('Open in Stream')
    // No screenshot, and no player ever mounts — ReplayPlayer has no failure
    // surface, so the caller gates.
    expect(screen.queryByTestId('moment-screenshot')).toBeNull()
    expect(screen.queryByTestId('replay-player')).toBeNull()
    expect(screen.queryByRole('button', { name: /Replay/ })).toBeNull()
  })

  it('offers the timed YouTube link beside Replay, replay first, on a recorded moment', async () => {
    // UX-DR12: the source second — a YouTube meeting *with* a recording
    // carries its link beside the Replay button, timed at this moment.
    answers(detail({ sourceDeepLink: 'https://www.youtube.com/watch?v=abc' }))
    render(<MomentView momentId="moment-1" />)

    const replay = await screen.findByRole('button', { name: 'Replay recording at 0:44' })
    const link = screen.getByTestId('moment-youtube-link')
    // The accessible name carries the offset; the `↗` glyph is hidden.
    expect(link).toBe(screen.getByRole('link', { name: 'Open on YouTube at 0:44' }))
    expect(link).toHaveAttribute('href', 'https://www.youtube.com/watch?v=abc&t=44')
    expect(new URL(link.getAttribute('href')!).searchParams.getAll('t')).toEqual(['44'])
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noreferrer')
    // Replay precedes the link in document order.
    expect(replay.compareDocumentPosition(link)).toBe(Node.DOCUMENT_POSITION_FOLLOWING)
    // The sole `moment-deep-link` is the replay-less shape, not this one.
    expect(screen.queryByTestId('moment-deep-link')).toBeNull()
    // The player still opens only from Replay.
    expect(screen.queryByTestId('replay-player')).toBeNull()
    await userEvent.click(replay)
    expect(await screen.findByTestId('replay-player')).toBeInTheDocument()
  })

  it('offers no source link beside Replay for another host', async () => {
    // Story 2.2's rule, kept: a non-YouTube link beside a recording is the
    // stale-link case, and the recording wins.
    answers(detail({ sourceDeepLink: 'https://example.sharepoint.com/stream.aspx?id=x' }))
    render(<MomentView momentId="moment-1" />)

    await screen.findByRole('button', { name: 'Replay recording at 0:44' })
    expect(screen.queryByTestId('moment-youtube-link')).toBeNull()
    expect(screen.queryByTestId('moment-deep-link')).toBeNull()
    expect(screen.queryByRole('link')).toBeNull()
  })

  it('makes the timed YouTube link the sole affordance on a transcript-only moment', async () => {
    answers(
      detail({
        hasRecording: false,
        screenshotId: null,
        screenshotPath: null,
        sourceDeepLink: 'https://youtu.be/abc',
      }),
    )
    render(<MomentView momentId="moment-1" />)

    const link = await screen.findByTestId('moment-deep-link')
    expect(link).toBe(screen.getByRole('link', { name: 'Open on YouTube at 0:44' }))
    expect(link).toHaveAttribute('href', 'https://youtu.be/abc?t=44')
    expect(link).toHaveAttribute('target', '_blank')
    expect(screen.queryByTestId('moment-youtube-link')).toBeNull()
    expect(screen.queryByRole('button', { name: /Replay/ })).toBeNull()
    expect(screen.queryByTestId('replay-player')).toBeNull()
  })

  it('shows an unsafe deep link as inert text, never as an anchor', async () => {
    answers(
      detail({
        hasRecording: false,
        screenshotId: null,
        screenshotPath: null,
        sourceDeepLink: 'javascript:alert(1)',
      }),
    )
    render(<MomentView momentId="moment-1" />)

    const inert = await screen.findByTestId('moment-unsafe-link')
    expect(inert).toHaveTextContent('javascript:alert(1)')
    expect(screen.queryByTestId('moment-deep-link')).toBeNull()
  })

  it('says transcript only when there is no recording and no link', async () => {
    answers(
      detail({
        hasRecording: false,
        screenshotId: null,
        screenshotPath: null,
        sourceDeepLink: null,
      }),
    )
    render(<MomentView momentId="moment-1" />)

    expect(await screen.findByTestId('moment-no-evidence')).toBeInTheDocument()
  })

  it('flags a superseded moment and says its transcript moved on', async () => {
    answers(detail({ superseded: true, segments: [] }))
    render(<MomentView momentId="moment-1" />)

    expect(await screen.findByTestId('moment-superseded')).toBeInTheDocument()
    expect(screen.getByTestId('moment-no-transcript')).toBeInTheDocument()
  })

  it('says evidence is still being prepared on the 409 problem', async () => {
    refuses({
      type: 'urn:meetingminer:problem:meeting-not-viewable',
      title: 'Conflict',
      status: 409,
      detail: 'meeting meeting-1 exists but its evidence is still being prepared',
    })
    render(<MomentView momentId="moment-1" />)

    expect(await screen.findByTestId('moment-notViewable')).toHaveTextContent(
      'still preparing its evidence',
    )
  })

  it('shows augmentation copy when the 409 says an augmentation is in flight', async () => {
    refuses({
      type: 'urn:meetingminer:problem:meeting-not-viewable',
      title: 'Conflict',
      status: 409,
      detail: 'meeting meeting-1 exists but its evidence is still being prepared',
      augmenting: true,
      jobStatus: 'running',
    })
    render(<MomentView momentId="moment-1" />)

    expect(await screen.findByTestId('moment-notViewable')).toHaveTextContent(
      'being augmented',
    )
  })

  it('shows preparing copy when the 409 says a first ingest is in flight', async () => {
    refuses({
      type: 'urn:meetingminer:problem:meeting-not-viewable',
      title: 'Conflict',
      status: 409,
      detail: 'meeting meeting-1 exists but its evidence is still being prepared',
      augmenting: false,
      jobStatus: 'running',
    })
    render(<MomentView momentId="moment-1" />)

    expect(await screen.findByTestId('moment-notViewable')).toHaveTextContent(
      'first ingest has not settled',
    )
  })

  it('shows failed copy when the 409 carries a failed job status', async () => {
    refuses({
      type: 'urn:meetingminer:problem:meeting-not-viewable',
      title: 'Conflict',
      status: 409,
      detail: 'meeting meeting-1 exists but its evidence is still being prepared',
      augmenting: false,
      jobStatus: 'failed',
    })
    render(<MomentView momentId="moment-1" />)

    expect(await screen.findByTestId('moment-notViewable')).toHaveTextContent(
      'Ingestion failed',
    )
  })

  it('says the moment does not exist on the 404 problem', async () => {
    refuses({
      type: 'urn:meetingminer:problem:not-found',
      title: 'Not Found',
      status: 404,
      detail: 'no moment with id moment-1',
    })
    render(<MomentView momentId="moment-1" />)

    expect(await screen.findByTestId('moment-notFound')).toHaveTextContent(
      'No moment has this id',
    )
  })

  it('names the api address when the read never reaches it', async () => {
    sdk.getMoment.mockRejectedValue(new Error('connection refused'))
    render(<MomentView momentId="moment-1" />)

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('http://localhost:8000')
    expect(alert).toHaveTextContent('connection refused')
  })

  it('ignores an aborted old response after the moment changes', async () => {
    let resolveFirst!: (value: { data: MomentDetail; error: undefined }) => void
    sdk.getMoment
      .mockImplementationOnce(
        () =>
          new Promise<{ data: MomentDetail; error: undefined }>((resolve) => {
            resolveFirst = resolve
          }),
      )
      .mockResolvedValueOnce({
        data: detail({ momentId: 'moment-2', meetingTitle: 'Sprint Review' }),
        error: undefined,
      })

    const { rerender } = render(<MomentView momentId="moment-1" />)
    await waitFor(() => expect(sdk.getMoment).toHaveBeenCalledTimes(1))
    rerender(<MomentView momentId="moment-2" />)

    expect(
      await screen.findByRole('heading', { name: 'Sprint Review at 0:44' }),
    ).toBeInTheDocument()
    await act(async () => {
      resolveFirst({ data: detail(), error: undefined })
    })

    expect(
      screen.getByRole('heading', { name: 'Sprint Review at 0:44' }),
    ).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Data Hub Demo at 0:44' })).toBeNull()
  })

  it("shows both kinds' full active prompt text in the right rail", async () => {
    answers(detail())
    sdk.getExtractionPrompts.mockResolvedValue({
      data: {
        prompts: [
          { kind: 'adr', promptText: 'You are an enterprise-architecture analyst.' },
          { kind: 'action-item', promptText: 'You are an expert meeting analyst.' },
        ],
      },
      error: undefined,
    })
    render(<MomentView momentId="moment-1" />)

    const section = await screen.findByTestId('extraction-prompts')
    expect(section).toHaveTextContent('Active extraction prompts')
    expect(screen.getByTestId('extraction-prompt-adr')).toHaveTextContent(
      'You are an enterprise-architecture analyst.',
    )
    expect(screen.getByTestId('extraction-prompt-action-item')).toHaveTextContent(
      'You are an expert meeting analyst.',
    )
  })

  it('degrades silently when the extraction prompts fetch fails', async () => {
    answers(detail())
    sdk.getExtractionPrompts.mockRejectedValue(new Error('connection refused'))
    render(<MomentView momentId="moment-1" />)

    // The rest of the moment view renders normally...
    expect(await screen.findByTestId('moment-transcript')).toBeInTheDocument()
    // ...and the prompts section never appears, silently.
    expect(screen.queryByTestId('extraction-prompts')).toBeNull()
  })

  it('ignores a prompts response that arrives after its timeout', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      let resolvePrompts!: (value: {
        data: { prompts: Array<{ kind: 'adr' | 'action-item'; promptText: string }> }
        error: undefined
      }) => void
      sdk.getExtractionPrompts.mockImplementation(
        () =>
          new Promise((resolve) => {
            resolvePrompts = resolve
          }),
      )
      answers(detail())
      render(<MomentView momentId="moment-1" />)
      await waitFor(() => expect(sdk.getExtractionPrompts).toHaveBeenCalledTimes(1))

      await act(async () => {
        await vi.advanceTimersByTimeAsync(EXTRACTION_PROMPTS_TIMEOUT_MS + 100)
        resolvePrompts({
          data: { prompts: [{ kind: 'adr', promptText: 'late stale prompt' }] },
          error: undefined,
        })
      })

      expect(screen.queryByTestId('extraction-prompts')).toBeNull()
    } finally {
      vi.useRealTimers()
    }
  })
})
