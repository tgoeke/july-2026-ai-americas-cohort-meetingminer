import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { TimelineCanvas, type TimelineCanvasProps } from './TimelineCanvas'
import type { ThreadSummary, TimelineMoment } from './threadsApi'

const THREAD: ThreadSummary = {
  threadId: 'thread-a',
  name: 'thread a',
  mentionCount: 3,
  meetingCount: 1,
  firstMentionAt: '1970-01-01T00:00:00Z',
  lastMentionAt: '1970-01-01T01:00:00Z',
  colorOrdinal: 1,
  nameIsCurated: false,
}

function props(overrides: Partial<TimelineCanvasProps> = {}): TimelineCanvasProps {
  return {
    tier: 'bands',
    view: { from: 0, scale: 1_000 },
    width: 1_000,
    epochMs: 0,
    rootRef: vi.fn(),
    threads: [THREAD],
    focusedThreadId: null,
    bands: {
      [THREAD.threadId]: [
        { from: new Date(0).toISOString(), to: new Date(100_000).toISOString(), mentionCount: 3 },
      ],
    },
    meetings: null,
    moments: null,
    pending: false,
    onZoomAt: vi.fn(),
    onPan: vi.fn(),
    onPanPixels: vi.fn(),
    onFitTo: vi.fn(),
    onFitAll: vi.fn(),
    onFocusThread: vi.fn(),
    onOpenMoment: vi.fn(),
    ...overrides,
  }
}

describe('review regressions: keyboard and focus', () => {
  it('never makes a zero-mention bucket the roving target', async () => {
    render(
      <TimelineCanvas
        {...props({
          bands: {
            [THREAD.threadId]: [
              {
                from: new Date(0).toISOString(),
                to: new Date(100_000).toISOString(),
                mentionCount: 3,
              },
              {
                from: new Date(450_000).toISOString(),
                to: new Date(550_000).toISOString(),
                mentionCount: 0,
              },
            ],
          },
        })}
      />,
    )
    await waitFor(() =>
      expect(screen.getByRole('gridcell', { name: /3 mentions/ })).toHaveAttribute('tabindex', '0'),
    )
  })

  it('pans on Shift+Arrow and Enter on a bucket selects its thread before fitting', async () => {
    const user = userEvent.setup()
    const onPan = vi.fn()
    const onFocusThread = vi.fn()
    const onFitTo = vi.fn()
    render(<TimelineCanvas {...props({ onPan, onFocusThread, onFitTo })} />)
    const cell = await screen.findByRole('gridcell', { name: /3 mentions/ })
    cell.focus()
    await user.keyboard('{Shift>}{ArrowRight}{/Shift}')
    expect(onPan).toHaveBeenCalledWith(0.8)
    expect(cell).toHaveFocus()
    await user.keyboard('{Enter}')
    expect(onFocusThread).toHaveBeenCalledWith(THREAD.threadId)
    expect(onFitTo).toHaveBeenCalled()
  })

  it('moves focus to the grid root when the incoming tier has no cells', async () => {
    const rendered = render(<TimelineCanvas {...props()} />)
    const cell = await screen.findByRole('gridcell', { name: /3 mentions/ })
    cell.focus()
    rendered.rerender(
      <TimelineCanvas
        {...props({
          tier: 'meetings',
          focusedThreadId: THREAD.threadId,
          bands: null,
          meetings: [],
        })}
      />,
    )
    await waitFor(() => expect(screen.getByRole('grid')).toHaveFocus())
    expect(screen.getByText('No moments in view.')).toBeInTheDocument()
  })
})

describe('review regressions: geometry and pointer interaction', () => {
  it('measures pointer zoom from the data-track origin, not the padded outer region', () => {
    const onZoomAt = vi.fn()
    render(<TimelineCanvas {...props({ onZoomAt })} />)
    const region = screen.getByRole('region', { name: /Scrollable Threads timeline data/ })
    const grid = screen.getByRole('grid')
    vi.spyOn(region, 'getBoundingClientRect').mockReturnValue({
      x: 100,
      y: 0,
      left: 100,
      top: 0,
      right: 1_100,
      bottom: 200,
      width: 1_000,
      height: 200,
      toJSON: () => ({}),
    })
    vi.spyOn(grid, 'getBoundingClientRect').mockReturnValue({
      x: 117,
      y: 0,
      left: 117,
      top: 0,
      right: 1_117,
      bottom: 200,
      width: 1_000,
      height: 200,
      toJSON: () => ({}),
    })
    region.dispatchEvent(
      new WheelEvent('wheel', {
        bubbles: true,
        cancelable: true,
        ctrlKey: true,
        clientX: 379,
        deltaY: -1,
      }),
    )
    expect(onZoomAt).toHaveBeenCalledWith(expect.any(Number), 100)
  })

  it('pans by pointer drag', () => {
    const onPanPixels = vi.fn()
    render(<TimelineCanvas {...props({ onPanPixels })} />)
    const region = screen.getByRole('region', { name: /Scrollable Threads timeline data/ })
    fireEvent.pointerDown(region, { clientX: 300, pointerId: 1, button: 0 })
    fireEvent.pointerMove(region, { clientX: 250, pointerId: 1 })
    fireEvent.pointerUp(region, { clientX: 250, pointerId: 1 })
    expect(onPanPixels).toHaveBeenCalledWith(-50)
  })

  it('clusters moments at the width of their rendered interactive labels', () => {
    const moments: Array<TimelineMoment> = [
      {
        momentId: 'm1',
        meetingId: 'meeting',
        title: 'first',
        occurredAt: new Date(100_000).toISOString(),
        startMs: 100_000,
        speakers: [],
      },
      {
        momentId: 'm2',
        meetingId: 'meeting',
        title: 'second',
        occurredAt: new Date(200_000).toISOString(),
        startMs: 200_000,
        speakers: [],
      },
    ]
    render(
      <TimelineCanvas
        {...props({
          tier: 'moments',
          view: { from: 0, scale: 2_000 },
          focusedThreadId: THREAD.threadId,
          bands: null,
          moments,
        })}
      />,
    )
    expect(screen.getByRole('gridcell', { name: /2 moments/ })).toBeInTheDocument()
    expect(screen.queryByRole('gridcell', { name: /^first/ })).toBeNull()
  })

  it('computes density only from buckets intersecting the visible window', () => {
    render(
      <TimelineCanvas
        {...props({
          bands: {
            [THREAD.threadId]: [
              {
                from: new Date(0).toISOString(),
                to: new Date(100_000).toISOString(),
                mentionCount: 1,
              },
              {
                from: new Date(2_000_000).toISOString(),
                to: new Date(2_100_000).toISOString(),
                mentionCount: 100,
              },
            ],
          },
        })}
      />,
    )
    const visible = screen.getByRole('gridcell', { name: /1 mentions/ })
    const fill = visible.parentElement?.querySelector('[aria-hidden="true"]')
    expect(fill).toHaveStyle({ opacity: '1' })
  })
})

describe('review regression: tier transition', () => {
  it('keeps the previous tier mounted while the incoming tier cross-fades', () => {
    const rendered = render(<TimelineCanvas {...props()} />)
    expect(screen.getByRole('gridcell', { name: /3 mentions/ })).toBeInTheDocument()
    rendered.rerender(
      <TimelineCanvas
        {...props({
          tier: 'meetings',
          focusedThreadId: THREAD.threadId,
          bands: null,
          meetings: [
            {
              meetingId: 'meeting-a',
              title: 'incoming meeting',
              occurredAt: new Date(100_000).toISOString(),
              durationMs: 100_000,
              mentionCount: 1,
            },
          ],
        })}
      />,
    )
    expect(screen.getByTestId('outgoing-tier-layer')).toHaveAttribute('aria-hidden', 'true')
    expect(screen.getByTestId('incoming-tier-layer')).toHaveClass('mm-layer-incoming')
  })
})
