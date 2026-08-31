import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { MomentCard } from './MomentCard'
import type { MomentFeedItem } from './feed'

vi.mock('@/client/sdk.gen', () => ({
  getMeetingDrilldown: vi.fn(() => Promise.resolve({ data: { segments: [] }, error: undefined })),
}))

const item: MomentFeedItem = {
  momentId: 'moment-order',
  meetingId: 'meeting-order',
  meetingTitle: 'Keyboard review',
  startedAt: '2026-08-31T12:00:00Z',
  startedAtPrecision: 'second',
  startMs: 3_000,
  endMs: 5_000,
  corpus: 'real',
  hasRecording: true,
  sourceDeepLink: 'https://www.youtube.com/watch?v=abc123',
  screenshotId: 'shot-1',
  viewType: 'slide',
  preview: 'Evidence preview',
  threads: [{ threadId: 'thread-1', name: 'launch', colorOrdinal: 1 }],
  reasons: [
    { kind: 'decision', label: 'decision at 0:03' },
    { kind: 'thread', label: 'launch path', ref: 'thread-1' },
  ],
}

function before(left: HTMLElement, right: HTMLElement) {
  expect(left.compareDocumentPosition(right)).toBe(Node.DOCUMENT_POSITION_FOLLOWING)
}

describe('F12 owner ruling: card keyboard order', () => {
  it('orders title, actions, source, player, then reason chips', async () => {
    render(
      <MomentCard
        item={item}
        expanded
        onToggleReplay={() => {}}
        onOpenMoment={() => {}}
        onOpenMeeting={() => {}}
        onSelectKind={() => {}}
        onOpenThread={() => {}}
      />,
    )

    const title = screen.getByTestId('moment-title-moment-order')
    const replay = screen.getByTestId('replay-moment-order')
    const openMoment = screen.getByTestId('open-moment-moment-order')
    const source = screen.getByTestId('source-moment-order')
    const player = await screen.findByTestId('replay-player')
    const kind = screen.getByTestId('reason-kind-decision')
    const thread = screen.getByTestId('thread-chip-thread-1')

    before(title, replay)
    before(replay, openMoment)
    before(openMoment, source)
    before(source, player)
    before(player, kind)
    before(kind, thread)
  })
})
