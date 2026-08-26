import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createFakeStream, type FakeStream, type StreamOptions } from '@/test/fakeStream'
import { REOPEN_DELAY_MS, isJobEvent, useJobEvents } from './useJobEvents'

const sdk = vi.hoisted(() => ({ streamJobEvents: vi.fn(), getMeetingDrilldown: vi.fn() }))

vi.mock('@/client/sdk.gen', () => ({
  streamJobEvents: sdk.streamJobEvents,
  getMeetingDrilldown: sdk.getMeetingDrilldown,
  listMeetings: vi.fn(),
  getHealth: vi.fn(),
  getJob: vi.fn(),
  createIngest: vi.fn(),
}))

let streams: FakeStream[]

beforeEach(() => {
  streams = []
  sdk.streamJobEvents.mockReset()
  sdk.streamJobEvents.mockImplementation(async (options: StreamOptions) => {
    const stream = createFakeStream(options)
    streams.push(stream)
    return { stream: stream.stream }
  })
})

function mount() {
  const onEvent = vi.fn()
  const onResync = vi.fn()
  const onAlive = vi.fn()
  const view = renderHook(() => useJobEvents({ onEvent, onResync, onAlive }))
  return { ...view, onEvent, onResync, onAlive }
}

describe('useJobEvents', () => {
  it('reopens the stream after the api closes it, and re-seeds on the new connection', async () => {
    // The api deliberately ends the stream once every job it was watching has
    // settled (pinned server-side by
    // `test_stream_closes_once_every_watched_job_has_settled`). Reopening is
    // what keeps the view live afterwards.
    // shouldAdvanceTime: testing-library's `waitFor` polls on a timer it does
    // not know is faked, so without this every wait in the test would hang.
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      const { onResync, onAlive } = mount()
      await waitFor(() => expect(streams).toHaveLength(1))
      act(() => streams[0].comment())
      await waitFor(() => expect(onAlive).toHaveBeenCalled())
      expect(onResync).not.toHaveBeenCalled() // first connection: the list seeds itself

      act(() => streams[0].close())
      await act(async () => {
        await vi.advanceTimersByTimeAsync(REOPEN_DELAY_MS + 10)
      })

      expect(sdk.streamJobEvents).toHaveBeenCalledTimes(2)
      act(() => streams[1].comment())
      await waitFor(() => expect(onResync).toHaveBeenCalledTimes(1))
    } finally {
      vi.useRealTimers()
    }
  })

  it('stops reporting a live connection while it is between streams', async () => {
    // shouldAdvanceTime: testing-library's `waitFor` polls on a timer it does
    // not know is faked, so without this every wait in the test would hang.
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      const { result } = mount()
      await waitFor(() => expect(streams).toHaveLength(1))
      act(() => streams[0].comment())
      await waitFor(() => expect(result.current.kind).toBe('live'))

      act(() => streams[0].close())
      await waitFor(() => expect(result.current.kind).toBe('connecting'))

      await act(async () => {
        await vi.advanceTimersByTimeAsync(REOPEN_DELAY_MS + 10)
      })
      act(() => streams[1].comment())
      await waitFor(() => expect(result.current.kind).toBe('live'))
    } finally {
      vi.useRealTimers()
    }
  })

  it('aborts the request on unmount and opens nothing further', async () => {
    // shouldAdvanceTime: testing-library's `waitFor` polls on a timer it does
    // not know is faked, so without this every wait in the test would hang.
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      const { unmount } = mount()
      await waitFor(() => expect(streams).toHaveLength(1))

      unmount()
      expect(streams[0].aborted).toBe(true)

      await act(async () => {
        await vi.advanceTimersByTimeAsync(REOPEN_DELAY_MS * 3)
      })
      expect(sdk.streamJobEvents).toHaveBeenCalledTimes(1)
    } finally {
      vi.useRealTimers()
    }
  })

  it('surfaces a lost connection only after the retries stop looking momentary', async () => {
    const { result } = mount()
    await waitFor(() => expect(streams).toHaveLength(1))

    act(() => streams[0].fail(new Error('Failed to fetch')))
    expect(result.current.kind).toBe('connecting')

    act(() => streams[0].fail(new Error('Failed to fetch')))
    await waitFor(() => expect(result.current).toEqual({ kind: 'lost', message: 'Failed to fetch' }))
  })

  it('passes through only payloads that look like the pinned wire contract', async () => {
    const { onEvent } = mount()
    await waitFor(() => expect(streams).toHaveLength(1))

    const valid = { event: 'job.stage', jobId: 'job-1', jobStatus: 'running', viewable: false }
    act(() => {
      streams[0].emit({ event: 'stage.started', jobId: 'job-1', viewable: false })
      streams[0].emit({ event: 'job.stage', jobId: 'job-1' })
      streams[0].emit(valid)
    })

    await waitFor(() => expect(onEvent).toHaveBeenCalledTimes(1))
    expect(onEvent).toHaveBeenCalledWith(valid)
  })
})

describe('isJobEvent', () => {
  it('rejects a worker log-event name', () => {
    expect(
      isJobEvent({ event: 'stage.done', jobId: 'job-1', jobStatus: 'running', viewable: true }),
    ).toBe(false)
  })

  it('accepts each pinned wire name', () => {
    for (const name of ['job.stage', 'job.done', 'job.error']) {
      expect(isJobEvent({ event: name, jobId: 'j', jobStatus: 'running', viewable: true })).toBe(true)
    }
  })
})
