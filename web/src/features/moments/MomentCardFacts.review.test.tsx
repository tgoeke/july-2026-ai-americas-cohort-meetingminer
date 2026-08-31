import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { MomentCard } from './MomentCard'
import type { MomentFeedItem } from './feed'

function item(overrides: Partial<MomentFeedItem> = {}): MomentFeedItem {
  return {
    momentId: 'moment-1',
    meetingId: 'meeting-1',
    meetingTitle: 'Review',
    startedAt: '2026-08-31T12:00:00Z',
    startedAtPrecision: 'second',
    startMs: 1_000,
    endMs: 2_000,
    corpus: 'real',
    hasRecording: true,
    sourceDeepLink: null,
    screenshotId: null,
    viewType: null,
    preview: null,
    threads: [{ threadId: 'thread-1', name: 'canonical thread', colorOrdinal: 1 }],
    reasons: [{ kind: 'thread', label: 'served reason label', ref: 'thread-1', at: null }],
    ...overrides,
  }
}

function renderCard(overrides: Partial<MomentFeedItem> = {}, expanded = false) {
  const actions = {
    onToggleReplay: vi.fn(),
    onOpenMoment: vi.fn(),
    onOpenMeeting: vi.fn(),
    onSelectKind: vi.fn(),
    onOpenThread: vi.fn(),
  }
  render(<MomentCard item={item(overrides)} expanded={expanded} {...actions} />)
  return actions
}

describe('review F5 — card facts and replay ownership', () => {
  it('renders a thread reason label verbatim while opening its referenced thread', async () => {
    const actions = renderCard()

    const chip = screen.getByRole('button', { name: 'thread served reason label' })
    expect(chip).toHaveTextContent('served reason label')
    expect(chip).not.toHaveTextContent('canonical thread')
    await userEvent.click(chip)
    expect(actions.onOpenThread).toHaveBeenCalledWith('thread-1')
  })

  it('keeps a refused recording source visible as inert provenance', () => {
    renderCard({ sourceDeepLink: 'javascript:alert(1)' })

    expect(screen.getByText(/Source link not opened — unsupported address/)).toHaveTextContent(
      'javascript:alert(1)',
    )
  })

  it.each([
    ['Open moment', 'onOpenMoment'],
    ['Open meeting', 'onOpenMeeting'],
  ] as const)('collapses replay before %s navigates', async (button, callback) => {
    const actions = renderCard({}, true)

    await userEvent.click(screen.getByRole('button', { name: new RegExp(button) }))
    expect(actions.onToggleReplay).toHaveBeenCalledTimes(1)
    expect(actions[callback]).toHaveBeenCalledTimes(1)
    expect(actions.onToggleReplay.mock.invocationCallOrder[0]).toBeLessThan(
      actions[callback].mock.invocationCallOrder[0],
    )
  })
})
