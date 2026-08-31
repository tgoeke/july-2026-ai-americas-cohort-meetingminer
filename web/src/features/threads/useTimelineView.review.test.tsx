import { useState } from 'react'
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

function RemountHarness() {
  const [shown, setShown] = useState(true)
  const timeline = useTimelineView({ from: 1_000, scale: 8_000 }, 0)
  return (
    <>
      {shown ? <div ref={timeline.rootRef} data-testid="remount-root" /> : null}
      <output data-testid="mount-revision">{timeline.mountRevision}</output>
      <output data-testid="measured">{String(timeline.measured)}</output>
      <output data-testid="width">{timeline.width}</output>
      <button type="button" onClick={() => setShown((value) => !value)}>
        toggle root
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

  it('publishes fresh measurement ownership when the same canvas root remounts', async () => {
    let rootWidth = 1162
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockImplementation(() => rootWidth)
    const user = userEvent.setup()
    render(<RemountHarness />)

    expect(screen.getByTestId('mount-revision')).toHaveTextContent('1')
    expect(screen.getByTestId('measured')).toHaveTextContent('true')
    expect(screen.getByTestId('width')).toHaveTextContent('1000')

    await user.click(screen.getByRole('button', { name: 'toggle root' }))
    expect(screen.getByTestId('measured')).toHaveTextContent('false')
    rootWidth = 1362
    await user.click(screen.getByRole('button', { name: 'toggle root' }))

    expect(screen.getByTestId('mount-revision')).toHaveTextContent('2')
    expect(screen.getByTestId('measured')).toHaveTextContent('true')
    expect(screen.getByTestId('width')).toHaveTextContent('1200')
  })
})
