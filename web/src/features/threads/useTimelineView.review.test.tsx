import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useTimelineView } from './useTimelineView'

function Harness({ onRender }: { onRender: () => void }) {
  onRender()
  const timeline = useTimelineView({ from: 1_000, scale: 8_000 }, 0)
  return (
    <>
      <div ref={timeline.rootRef} data-testid="timeline-root" data-target={timeline.view.scale} />
      <button type="button" onClick={() => timeline.zoomAt(0.5, 100)}>
        zoom
      </button>
    </>
  )
}

describe('reviewed animation ownership', () => {
  let now = 0
  let nextFrame = 1
  let frames: Map<number, FrameRequestCallback>

  beforeEach(() => {
    frames = new Map()
    vi.spyOn(performance, 'now').mockImplementation(() => now)
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      const id = nextFrame
      nextFrame += 1
      frames.set(id, callback)
      return id
    })
    vi.stubGlobal('cancelAnimationFrame', (id: number) => frames.delete(id))
  })

  afterEach(() => vi.unstubAllGlobals())

  function runFrame(at: number) {
    now = at
    const pending = [...frames.values()]
    frames.clear()
    act(() => pending.forEach((callback) => callback(at)))
  }

  it('accumulates rapid zoom targets and restarts from the drawn view without frame renders', async () => {
    const user = userEvent.setup()
    const onRender = vi.fn()
    render(<Harness onRender={onRender} />)
    runFrame(120)
    const root = screen.getByTestId('timeline-root')
    const rendersAfterMount = onRender.mock.calls.length

    await user.click(screen.getByRole('button', { name: 'zoom' }))
    expect(root).toHaveAttribute('data-target', '4000')
    runFrame(180)
    const drawnMidGesture = Number(root.style.getPropertyValue('--mm-scale'))
    const rendersAfterTarget = onRender.mock.calls.length
    expect(drawnMidGesture).toBeGreaterThan(4_000)
    expect(drawnMidGesture).toBeLessThan(8_000)

    await user.click(screen.getByRole('button', { name: 'zoom' }))
    expect(root).toHaveAttribute('data-target', '2000')
    runFrame(180)
    expect(Number(root.style.getPropertyValue('--mm-scale'))).toBeCloseTo(drawnMidGesture, 8)
    runFrame(240)
    expect(Number(root.style.getPropertyValue('--mm-scale'))).toBeLessThan(drawnMidGesture)
    expect(onRender.mock.calls.length).toBe(rendersAfterTarget + 1)
    expect(rendersAfterMount).toBeGreaterThan(0)
  })

  it('applies the target synchronously under reduced motion', async () => {
    vi.stubGlobal('matchMedia', () => ({ matches: true }))
    const user = userEvent.setup()
    render(<Harness onRender={vi.fn()} />)
    await user.click(screen.getByRole('button', { name: 'zoom' }))
    expect(screen.getByTestId('timeline-root').style.getPropertyValue('--mm-scale')).toBe('4000')
    expect(frames.size).toBe(0)
  })
})
