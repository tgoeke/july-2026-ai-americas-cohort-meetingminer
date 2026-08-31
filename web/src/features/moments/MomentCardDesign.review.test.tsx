import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { BrowserRouter } from 'react-router'
import { MomentCard } from './MomentCard'
import { MomentsFeed } from './MomentsFeed'
import type { MomentFeedItem } from './feed'

function item(overrides: Partial<MomentFeedItem> = {}): MomentFeedItem {
  return {
    momentId: 'moment-1',
    meetingId: 'meeting-1',
    meetingTitle: 'Design review',
    startedAt: '2026-08-31T12:00:00Z',
    startedAtPrecision: 'second',
    startMs: 1_000,
    endMs: 2_000,
    corpus: 'real',
    hasRecording: false,
    sourceDeepLink: null,
    screenshotId: 'shot-1',
    viewType: 'slide',
    preview: 'A deliberately long excerpt that must never make one card much taller than its peers.',
    threads: [],
    reasons: [{ kind: 'decision', label: 'decision recorded', ref: 'artifact-1', at: null }],
    ...overrides,
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('review F6 — adopted card and control treatments', () => {
  it('opens the moment from its screenshot without cropping the evidence', async () => {
    const onOpenMoment = vi.fn()
    render(
      <MomentCard
        item={item()}
        expanded={false}
        onToggleReplay={() => undefined}
        onOpenMoment={onOpenMoment}
        onOpenMeeting={() => undefined}
        onSelectKind={() => undefined}
        onOpenThread={() => undefined}
      />,
    )

    const screenshotLink = screen.getByRole('button', { name: 'Open screenshot for Design review' })
    await userEvent.click(screenshotLink)
    expect(onOpenMoment).toHaveBeenCalledTimes(1)
    expect(screen.getByAltText('slide at 0:01, Design review')).toHaveClass('object-contain')
  })

  it('clamps the served preview to the designed two-line excerpt', () => {
    render(
      <MomentCard
        item={item()}
        expanded={false}
        onToggleReplay={() => undefined}
        onOpenMoment={() => undefined}
        onOpenMeeting={() => undefined}
        onSelectKind={() => undefined}
        onOpenThread={() => undefined}
      />,
    )

    expect(screen.getByText(/deliberately long excerpt/)).toHaveClass('line-clamp-2')
  })

  it('uses the measured control border for the new feed filters', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve(
          new Response(
            JSON.stringify({ items: [item()], total: 1, unfilteredTotal: 1, limit: 24, offset: 0 }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          ),
        ),
      ),
    )
    render(
      <BrowserRouter>
        <MomentsFeed
          onOpenMoment={() => undefined}
          onOpenMeeting={() => undefined}
          onOpenThread={() => undefined}
        />
      </BrowserRouter>,
    )

    const select = await screen.findByTestId('filter-corpus')
    expect(select.closest('label')?.getAttribute('style')).toContain(
      'border-color: var(--control-border)',
    )
  })
})
