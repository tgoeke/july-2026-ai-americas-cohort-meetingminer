import { act, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ReplayPlayer } from './ReplayPlayer'

/**
 * Story 7.4's one change to the shared player: an optional `endMs` that stops
 * a speaker sample after eight seconds. In its own file rather than appended
 * to `ReplayPlayer.test.tsx` — the wave's rule is that a story's tests are a
 * new module, so two branches editing the player cannot collide inside one.
 *
 * jsdom implements no media pipeline: `currentTime` is a plain property and
 * `timeupdate` never fires on its own, so the test plays the browser's part.
 * `pause` is spied rather than called for real because jsdom's is a stub.
 */

const MEETING = '0190a0f0-7c1e-7000-8000-0000000000aa'

const pause = vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})

function player(): HTMLVideoElement {
  return screen.getByTestId('replay-player') as HTMLVideoElement
}

function playsTo(video: HTMLVideoElement, seconds: number) {
  video.currentTime = seconds
  act(() => {
    video.dispatchEvent(new Event('timeupdate'))
  })
}

function seeksTo(video: HTMLVideoElement, seconds: number) {
  video.currentTime = seconds
  act(() => {
    video.dispatchEvent(new Event('seeked'))
  })
}

afterEach(() => {
  pause.mockClear()
})

describe('ReplayPlayer clip stop', () => {
  it('plays on with no endMs, however far the playhead runs', () => {
    render(<ReplayPlayer meetingId={MEETING} startMs={252_000} />)
    const video = player()

    playsTo(video, 400)

    // The existing callers — the moment view, the drill-down, search hits —
    // pass no end, and must keep open-ended playback.
    expect(pause).not.toHaveBeenCalled()
  })

  it('stops eight seconds into a sample clip', () => {
    render(<ReplayPlayer meetingId={MEETING} startMs={252_000} endMs={260_000} />)
    const video = player()

    playsTo(video, 255)
    expect(pause).not.toHaveBeenCalled()

    playsTo(video, 260)

    expect(pause).toHaveBeenCalledTimes(1)
  })

  it('stops once, so the viewer can play on past the clip', () => {
    render(<ReplayPlayer meetingId={MEETING} startMs={252_000} endMs={260_000} />)
    const video = player()

    playsTo(video, 260)
    playsTo(video, 261)
    playsTo(video, 262)

    expect(pause).toHaveBeenCalledTimes(1)
  })

  it('re-arms when the viewer seeks back before the boundary', () => {
    render(<ReplayPlayer meetingId={MEETING} startMs={252_000} endMs={260_000} />)
    const video = player()
    playsTo(video, 260)
    expect(pause).toHaveBeenCalledTimes(1)

    seeksTo(video, 253)
    playsTo(video, 260)

    expect(pause).toHaveBeenCalledTimes(2)
  })

  it('re-arms for the next clip of the same tag', () => {
    const { rerender } = render(
      <ReplayPlayer meetingId={MEETING} startMs={252_000} endMs={260_000} />,
    )
    const video = player()
    playsTo(video, 260)
    expect(pause).toHaveBeenCalledTimes(1)

    // Clip 2: the same mounted element re-pointed, as every other caller
    // re-points it.
    rerender(<ReplayPlayer meetingId={MEETING} startMs={1_180_000} endMs={1_188_000} />)
    playsTo(video, 1188)

    expect(pause).toHaveBeenCalledTimes(2)
  })

  it('ignores an end offset that is not a finite number', () => {
    render(<ReplayPlayer meetingId={MEETING} startMs={0} endMs={Number.NaN} />)
    const video = player()

    playsTo(video, 5000)

    expect(pause).not.toHaveBeenCalled()
  })

  it('stops listening once unmounted', () => {
    const { unmount } = render(
      <ReplayPlayer meetingId={MEETING} startMs={252_000} endMs={260_000} />,
    )
    const video = player()

    unmount()
    video.currentTime = 300
    video.dispatchEvent(new Event('timeupdate'))

    expect(pause).not.toHaveBeenCalled()
  })
})
