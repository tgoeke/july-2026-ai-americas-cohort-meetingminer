import { act, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { API_BASE } from '@/lib/api'
import { ReplayPlayer } from './ReplayPlayer'

const MEETING = '0190a0f0-7c1e-7000-8000-0000000000aa'

function player(): HTMLVideoElement {
  return screen.getByTestId('replay-player') as HTMLVideoElement
}

/**
 * jsdom loads no media, so `loadedmetadata` never fires on its own — the test
 * plays the browser's part. `currentTime` is reset to 0 first so that a pass
 * can only come from the listener, never from the assignment the effect
 * already made.
 */
function metadataLoads(video: HTMLVideoElement) {
  video.currentTime = 0
  act(() => {
    video.dispatchEvent(new Event('loadedmetadata'))
  })
}

describe('ReplayPlayer', () => {
  it('points at the meeting recording route', () => {
    render(<ReplayPlayer meetingId={MEETING} startMs={0} />)
    expect(player().getAttribute('src')).toBe(`${API_BASE}/media/recordings/${MEETING}`)
  })

  it('seeks to startMs once metadata loads', () => {
    render(<ReplayPlayer meetingId={MEETING} startMs={90_000} />)
    const video = player()

    metadataLoads(video)

    expect(video.currentTime).toBe(90)
  })

  it('re-seeks when startMs changes', () => {
    const { rerender } = render(<ReplayPlayer meetingId={MEETING} startMs={90_000} />)
    const video = player()
    metadataLoads(video)
    expect(video.currentTime).toBe(90)

    // 2.2 and 2.3 both re-point one mounted player at the next moment rather
    // than mounting a new one, so the element survives and the effect re-runs.
    rerender(<ReplayPlayer meetingId={MEETING} startMs={12_500} />)

    expect(video.currentTime).toBe(12.5)
    metadataLoads(video)
    expect(video.currentTime).toBe(12.5)
  })

  it('leaves the playhead alone when nothing changed', () => {
    const { rerender } = render(<ReplayPlayer meetingId={MEETING} startMs={90_000} />)
    const video = player()
    metadataLoads(video)
    video.currentTime = 120 // the viewer scrubbed forward

    rerender(<ReplayPlayer meetingId={MEETING} startMs={90_000} />)

    expect(video.currentTime).toBe(120)
  })

  it.each([
    ['NaN', Number.NaN],
    ['Infinity', Number.POSITIVE_INFINITY],
    ['-Infinity', Number.NEGATIVE_INFINITY],
    ['a negative offset', -5_000],
  ])('opens at the top rather than throwing on %s', (_label, startMs) => {
    // An unclamped assignment throws inside the effect, which unmounts the
    // whole tree — a moment with no usable offset must cost the recording,
    // not the view.
    render(<ReplayPlayer meetingId={MEETING} startMs={startMs} />)
    const video = player()

    metadataLoads(video)

    expect(video.currentTime).toBe(0)
  })

  it('stops seeking once unmounted', () => {
    const { unmount } = render(<ReplayPlayer meetingId={MEETING} startMs={90_000} />)
    const video = player()

    unmount()
    video.currentTime = 7
    video.dispatchEvent(new Event('loadedmetadata'))

    expect(video.currentTime).toBe(7)
  })
})
