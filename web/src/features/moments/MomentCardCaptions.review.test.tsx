import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MomentCard } from './MomentCard'
import type { MomentFeedItem } from './feed'

const sdk = vi.hoisted(() => ({ getMeetingDrilldown: vi.fn() }))
const stored = new Map<string, string>()
const memoryStorage = {
  clear: () => stored.clear(),
  getItem: (key: string) => stored.get(key) ?? null,
  key: (index: number) => [...stored.keys()][index] ?? null,
  removeItem: (key: string) => stored.delete(key),
  setItem: (key: string, value: string) => stored.set(key, value),
  get length() {
    return stored.size
  },
}

vi.mock('@/client/sdk.gen', () => ({ getMeetingDrilldown: sdk.getMeetingDrilldown }))

const feedItem: MomentFeedItem = {
  momentId: 'moment-1',
  meetingId: 'meeting-1',
  meetingTitle: 'Caption review',
  startedAt: '2026-08-31T12:00:00Z',
  startedAtPrecision: 'second',
  startMs: 1_250,
  endMs: 2_500,
  corpus: 'real',
  hasRecording: true,
  sourceDeepLink: null,
  screenshotId: null,
  viewType: null,
  preview: null,
  threads: [],
  reasons: [{ kind: 'recency', label: 'recently recorded', at: null }],
}

const actions = {
  onToggleReplay: () => undefined,
  onOpenMoment: () => undefined,
  onOpenMeeting: () => undefined,
  onSelectKind: () => undefined,
  onOpenThread: () => undefined,
}

function answerDrilldown() {
  sdk.getMeetingDrilldown.mockResolvedValue({
    data: {
      meetingId: 'meeting-1',
      title: 'Caption review',
      hasRecording: true,
      corpus: 'real',
      startedAt: '2026-08-31T12:00:00Z',
      startedAtPrecision: 'second',
      sourceDeepLink: null,
      screenshots: [],
      segments: [
        {
          segmentId: 'segment-1',
          ordinal: 1,
          startMs: 1_250,
          endMs: 2_500,
          speakerLabel: 'Alex & Sam',
          speakerResolution: 'resolved',
          participantId: null,
          text: 'First <draft>\nwith a second line.',
          momentId: 'moment-1',
        },
      ],
    },
    error: undefined,
  })
}

beforeEach(() => {
  sdk.getMeetingDrilldown.mockReset()
  memoryStorage.clear()
  vi.stubGlobal('localStorage', memoryStorage)
  answerDrilldown()
})

afterEach(() => vi.unstubAllGlobals())

describe('review F9 — inline replay captions', () => {
  it('attaches escaped client-generated WebVTT from the meeting drilldown', async () => {
    render(<MomentCard item={feedItem} expanded {...actions} />)

    await waitFor(() =>
      expect(sdk.getMeetingDrilldown).toHaveBeenCalledWith(
        expect.objectContaining({ path: { meeting_id: 'meeting-1' } }),
      ),
    )
    const track = await screen.findByTestId('replay-captions-track')
    expect(track).toHaveAttribute('kind', 'captions')
    expect(track).not.toHaveAttribute('default')
    const src = track.getAttribute('src') ?? ''
    expect(src).toMatch(/^data:text\/vtt;charset=utf-8,/)
    const webVtt = decodeURIComponent(src.slice(src.indexOf(',') + 1))
    expect(webVtt).toContain('WEBVTT')
    expect(webVtt).toContain('00:00:01.250 --> 00:00:02.500')
    expect(webVtt).toContain('Alex &amp; Sam: First &lt;draft&gt; with a second line.')
  })

  it('starts off and remembers an explicit viewer choice in this browser', async () => {
    const first = render(<MomentCard item={feedItem} expanded {...actions} />)

    const show = await screen.findByRole('button', { name: 'Show captions' })
    expect(show).toHaveAttribute('aria-pressed', 'false')
    await userEvent.click(show)
    expect(localStorage.getItem('meetingminer.replay.captions')).toBe('showing')
    first.unmount()

    answerDrilldown()
    render(<MomentCard item={feedItem} expanded {...actions} />)
    expect(await screen.findByRole('button', { name: 'Hide captions' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
  })
})
