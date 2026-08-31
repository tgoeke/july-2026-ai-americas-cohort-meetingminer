/**
 * The Threads front door (story 10.7).
 *
 * What is asserted here is what the owner corrected once already: the view
 * opens EMPTY, it says in words which of the two ways in it took, it offers
 * adjacent candidates rather than guessing between them, and a meeting on the
 * timeline opens the meeting view.
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Link, MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import ThreadTrace from './ThreadTrace'

const SUGGESTIONS = {
  subjects: [
    {
      threadId: 'thread-trail',
      name: 'Cedar Lake Trail closure',
      colorOrdinal: 1,
      mentionCount: 31,
      reach: {
        meetingCount: 9,
        spanDays: 118,
        firstMentionAt: '2026-04-01T12:00:00Z',
        lastMentionAt: '2026-07-28T12:00:00Z',
      },
    },
  ],
  minMeetings: 2,
  maxMeetings: 45,
  minSpanDays: 14,
}

function stop(overrides: Record<string, unknown> = {}) {
  return {
    meetingId: 'meeting-1',
    title: 'Parks Board · April',
    corpus: 'real',
    hasRecording: true,
    occurredAt: '2026-04-01T12:00:00Z',
    lastOccurredAt: '2026-04-01T12:30:00Z',
    occurredAtPrecision: 'second',
    mentionCount: 9,
    momentCount: 9,
    quotedCount: 2,
    screenCount: 0,
    moments: [
      {
        momentId: 'moment-1',
        startMs: 95_000,
        occurredAt: '2026-04-01T12:01:35Z',
        occurredAtPrecision: 'second',
        speakers: ['Dana Whitfield'],
        excerpt: 'The north approach stays closed until the culvert is replaced.',
        screenshotId: null,
      },
    ],
    ...overrides,
  }
}

const EXHAUSTIVE = {
  mode: 'exhaustive',
  label: 'Cedar Lake Trail closure',
  threadId: 'thread-trail',
  colorOrdinal: 1,
  resolvedFrom: null,
  ranking: null,
  complete: false,
  completenessNote:
    '12 of 31 moments, quoting at most 6 per meeting so that all 2 meetings that' +
    ' mention it stay on the timeline. The span is the true span; only the quoting is capped.',
  perMeetingLimit: 6,
  span: { fromAt: '2026-04-01T12:00:00Z', toAt: '2026-07-28T12:00:00Z', days: 118, meetings: 2 },
  counts: {
    stops: 2,
    momentsQuoted: 12,
    mentionTotal: 31,
    meetingsMentioning: 2,
    withScreen: 0,
  },
  candidates: [],
  relatedSubjects: [
    { threadId: 'thread-culvert', name: 'Culvert replacement', colorOrdinal: 2, sharedMoments: 4 },
  ],
  stops: [
    stop(),
    stop({
      meetingId: 'meeting-2',
      title: 'Parks Board · July',
      occurredAt: '2026-07-28T12:00:00Z',
      lastOccurredAt: '2026-07-28T12:40:00Z',
      hasRecording: false,
    }),
  ],
}

const SAMPLE = {
  ...EXHAUSTIVE,
  mode: 'sample',
  label: 'trail closures',
  threadId: null,
  colorOrdinal: null,
  ranking: 'hybrid',
  completenessNote:
    'The 12 best-matching moments for this wording by hybrid ranking, re-sorted by' +
    ' date across 2 meetings. This is a sample, not every mention — name a subject' +
    ' exactly for an exhaustive trace.',
  candidates: [
    {
      threadId: 'thread-trail',
      name: 'Cedar Lake Trail closure',
      colorOrdinal: 1,
      meetingCount: 9,
      spanDays: 118,
    },
    {
      threadId: 'thread-outlook',
      name: 'Trail reopening outlook',
      colorOrdinal: 2,
      meetingCount: 4,
      spanDays: 60,
    },
  ],
}

const EMPTY_SAMPLE = {
  ...SAMPLE,
  completenessNote:
    'Nothing in the corpus matches this wording. Nothing is shown rather than a nearest guess.',
  span: null,
  counts: { stops: 0, momentsQuoted: 0, mentionTotal: 0, meetingsMentioning: 0, withScreen: 0 },
  candidates: [],
  relatedSubjects: [],
  stops: [],
}

let served: {
  suggestions?: unknown
  suggestionsStatus?: number
  trace?: unknown
  traceByThread?: Record<string, unknown>
} = {}

function body(payload: unknown, status = 200): Response {
  return {
    ok: status < 400,
    status,
    statusText: status === 200 ? 'OK' : 'Error',
    text: async () => JSON.stringify(payload),
  } as unknown as Response
}

function answer(url: string): Response {
  if (url.includes('/threads/suggestions')) {
    const status = served.suggestionsStatus ?? 200
    if (status !== 200) {
      return body({ title: 'suggestions unavailable', detail: 'the projection is rebuilding' }, status)
    }
    return body(served.suggestions ?? SUGGESTIONS)
  }
  if (url.includes('/threads/trace')) {
    const threadId = new URL(url).searchParams.get('threadId')
    if (threadId !== null && served.traceByThread?.[threadId] !== undefined) {
      return body(served.traceByThread[threadId])
    }
    return body(served.trace ?? EXHAUSTIVE)
  }
  throw new Error(`unrouted fixture request: ${url}`)
}

beforeEach(() => {
  served = {}
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => Promise.resolve(answer(String(input)))),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

function mount(at = '/threads') {
  return render(
    <MemoryRouter initialEntries={[at]}>
      <Link to="/threads">Threads root</Link>
      <Routes>
        <Route path="/threads" element={<ThreadTrace />} />
        <Route path="/threads/:threadId" element={<ThreadTrace />} />
        <Route path="/meetings/:meetingId" element={<p>meeting view</p>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('the empty front door', () => {
  it('opens empty — a box and suggestions, never a catalogue', async () => {
    mount()

    expect(screen.getByLabelText('Subject to trace')).toBeInTheDocument()
    expect(await screen.findByText('Cedar Lake Trail closure')).toBeInTheDocument()
    // Nothing is traced until a subject is named.
    expect(screen.queryByRole('region', { name: /^Timeline for/ })).toBeNull()
    expect(fetch).toHaveBeenCalledTimes(1)
  })

  it('shows each suggestion’s reach, so the choice is a considered one', async () => {
    mount()
    expect(await screen.findByText('9 meetings over 118 days')).toBeInTheDocument()
  })

  it('says so when the band is empty rather than rendering a blank', async () => {
    served.suggestions = { ...SUGGESTIONS, subjects: [] }
    mount()

    expect(
      await screen.findByText(/No subject in this corpus recurs across between 2 and 45 meetings/),
    ).toBeInTheDocument()
  })

  it('keeps the box usable when suggestions are refused', async () => {
    served.suggestionsStatus = 503
    mount()

    expect(await screen.findByText(/Suggestions could not be loaded/)).toBeInTheDocument()
    expect(screen.getByText(/the projection is rebuilding/)).toBeInTheDocument()
    expect(screen.getByLabelText('Subject to trace')).toBeEnabled()
  })
})

describe('the two ways in', () => {
  it('states in words that an exhaustive trace is capped per meeting', async () => {
    const user = userEvent.setup()
    mount()

    await user.click(await screen.findByRole('button', { name: /Cedar Lake Trail closure/ }))

    const note = await screen.findByText(/12 of 31 moments/)
    expect(note).toHaveAttribute('data-mode', 'exhaustive')
    expect(note).toHaveTextContent('all 2 meetings that mention it stay on the timeline')
  })

  it('never lets a sample read as a full history', async () => {
    served.trace = SAMPLE
    const user = userEvent.setup()
    mount()

    await user.type(screen.getByLabelText('Subject to trace'), 'trail closures')
    await user.click(screen.getByRole('button', { name: 'Trace' }))

    const note = await screen.findByText(/This is a sample, not every mention/)
    expect(note).toHaveAttribute('data-mode', 'sample')
  })

  it('offers the adjacent candidates rather than guessing between them', async () => {
    served.trace = SAMPLE
    const user = userEvent.setup()
    mount()

    await user.type(screen.getByLabelText('Subject to trace'), 'trail closures')
    await user.click(screen.getByRole('button', { name: 'Trace' }))

    expect(await screen.findByText('Did you mean one of these?')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Cedar Lake Trail closure/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Trail reopening outlook/ })).toBeInTheDocument()
  })

  it('traces the candidate the reader picks, exhaustively', async () => {
    served.trace = SAMPLE
    served.traceByThread = { 'thread-trail': EXHAUSTIVE }
    const user = userEvent.setup()
    mount()

    await user.type(screen.getByLabelText('Subject to trace'), 'trail closures')
    await user.click(screen.getByRole('button', { name: 'Trace' }))
    await user.click(await screen.findByRole('button', { name: /Cedar Lake Trail closure/ }))

    expect(await screen.findByText(/12 of 31 moments/)).toHaveAttribute('data-mode', 'exhaustive')
  })

  it('says plainly when nothing matches, and offers nothing it cannot back', async () => {
    served.trace = EMPTY_SAMPLE
    const user = userEvent.setup()
    mount()

    await user.type(screen.getByLabelText('Subject to trace'), 'no such thing')
    await user.click(screen.getByRole('button', { name: 'Trace' }))

    expect(await screen.findByText(/Nothing in the corpus matches this wording/)).toBeInTheDocument()
    expect(screen.getByText(/Nothing in the corpus mentions this, so nothing is drawn/))
      .toBeInTheDocument()
    expect(screen.queryByText('Did you mean one of these?')).toBeNull()
  })

  it('traces a deep-linked subject on arrival', async () => {
    mount('/threads/thread-trail')
    expect(await screen.findByText(/12 of 31 moments/)).toBeInTheDocument()
    // Deep links name a known thread, so they never take the sampling leg.
    expect(String(vi.mocked(fetch).mock.calls[1]?.[0])).toContain('threadId=thread-trail')
  })

  it('returns to the empty front door from a deep-linked subject', async () => {
    const user = userEvent.setup()
    mount('/threads/thread-trail')
    expect(await screen.findByText(/12 of 31 moments/)).toBeInTheDocument()

    await user.click(screen.getByRole('link', { name: 'Threads root' }))

    expect(await screen.findByText('Trace one subject across your meetings')).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: /^Timeline for/ })).toBeNull()
    expect(screen.getByLabelText('Subject to trace')).toHaveValue('')
  })
})

describe('the timeline', () => {
  it('fits the whole span to the rendered width, not the fallback width', async () => {
    const width = vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(500)
    const user = userEvent.setup()
    try {
      mount()
      await user.click(await screen.findByRole('button', { name: /Cedar Lake Trail closure/ }))

      const timeline = await screen.findByRole('region', {
        name: 'Timeline for Cedar Lake Trail closure',
      })
      await waitFor(() => {
        expect(timeline.querySelector('.mm-trace-view')).toHaveAttribute('data-ppd', '3.22')
      })
    } finally {
      width.mockRestore()
    }
  })

  it('draws one stop per meeting, in time order', async () => {
    const user = userEvent.setup()
    mount()
    await user.click(await screen.findByRole('button', { name: /Cedar Lake Trail closure/ }))

    const timeline = await screen.findByRole('region', {
      name: 'Timeline for Cedar Lake Trail closure',
    })
    expect(timeline).toBeInTheDocument()
    // Both meetings are on ONE timeline, interleaved by date rather than
    // separated into per-series lanes.
    expect(timeline.querySelectorAll('.mm-trace-bar-item')).toHaveLength(2)
  })

  it('opens the meeting view when a meeting is clicked', async () => {
    const user = userEvent.setup()
    mount()
    await user.click(await screen.findByRole('button', { name: /Cedar Lake Trail closure/ }))

    // Descend onto the first meeting, which is what turns bars into cards.
    const timeline = await screen.findByRole('region', {
      name: 'Timeline for Cedar Lake Trail closure',
    })
    await user.click(timeline.querySelectorAll('.mm-trace-bar-item')[0] as HTMLElement)

    await user.click((await screen.findAllByRole('button', { name: 'Open this meeting →' }))[0])
    expect(await screen.findByText('meeting view')).toBeInTheDocument()
  })

  it('states why a stop shows no screens, and never over-claims', async () => {
    const user = userEvent.setup()
    mount()
    await user.click(await screen.findByRole('button', { name: /Cedar Lake Trail closure/ }))
    const timeline = await screen.findByRole('region', {
      name: 'Timeline for Cedar Lake Trail closure',
    })
    // Each stop is visited in turn: at the deepest altitude the other meeting
    // is four months away and correctly culled off screen.
    const reasonAfterDescending = async (index: number) => {
      const bars = timeline.querySelectorAll('.mm-trace-bar-item')
      await user.click(bars[index] as HTMLElement)
      await waitFor(() => {
        expect(document.querySelector('.mm-trace-absent')).not.toBeNull()
      })
      const reason = document.querySelector('.mm-trace-absent')?.textContent
      await user.keyboard('{Escape}')
      return reason
    }

    // A recorded meeting whose quoted moments carry no still is an OBSERVED
    // absence and must never be described as having no recording.
    expect(await reasonAfterDescending(0)).toBe('No screen was captured at these moments.')
    // Transcript-only is an ESTABLISHED absence, and says so.
    expect(await reasonAfterDescending(1)).toBe(
      'Transcript only — no recording, so no screens were captured.',
    )
  })

  it('renders the opaque screenshot carried by a stop', async () => {
    served.trace = {
      ...EXHAUSTIVE,
      span: { fromAt: '2026-04-01T00:00:00Z', toAt: '2026-04-01T00:00:00Z', days: 0, meetings: 1 },
      counts: { stops: 1, momentsQuoted: 1, mentionTotal: 1, meetingsMentioning: 1, withScreen: 1 },
      stops: [
        stop({
          screenCount: 1,
          mentionCount: 1,
          momentCount: 1,
          quotedCount: 1,
          moments: [
            {
              momentId: 'moment-screen',
              startMs: 95_000,
              occurredAt: '2026-04-01T00:01:35Z',
              occurredAtPrecision: 'second',
              speakers: ['Dana Whitfield'],
              excerpt: 'The culvert is visible on screen.',
              screenshotId: 'screenshot-1',
            },
          ],
        }),
      ],
    }
    const user = userEvent.setup()
    mount()
    await user.click(await screen.findByRole('button', { name: /Cedar Lake Trail closure/ }))

    const image = await waitFor(() => {
      const element = document.querySelector('.mm-trace-moments img')
      expect(element).not.toBeNull()
      return element as HTMLImageElement
    })
    expect(image.src).toContain('/media/files/screenshot-1')
  })

  it('labels day-precision stops as date only', async () => {
    served.trace = {
      ...EXHAUSTIVE,
      span: { fromAt: '2026-04-01T00:15:00Z', toAt: '2026-04-01T00:15:00Z', days: 0, meetings: 1 },
      counts: { stops: 1, momentsQuoted: 1, mentionTotal: 1, meetingsMentioning: 1, withScreen: 0 },
      stops: [
        stop({
          occurredAt: '2026-04-01T00:15:00Z',
          lastOccurredAt: '2026-04-01T00:15:00Z',
          occurredAtPrecision: 'day',
        }),
      ],
    }
    const user = userEvent.setup()
    mount()
    await user.click(await screen.findByRole('button', { name: /Cedar Lake Trail closure/ }))

    expect(await screen.findByText(/date only/)).toBeInTheDocument()
  })

  it('offers the neighbouring subjects so a trace leads somewhere', async () => {
    const user = userEvent.setup()
    mount()
    await user.click(await screen.findByRole('button', { name: /Cedar Lake Trail closure/ }))

    expect(await screen.findByRole('button', { name: 'Culvert replacement' })).toBeInTheDocument()
  })
})
