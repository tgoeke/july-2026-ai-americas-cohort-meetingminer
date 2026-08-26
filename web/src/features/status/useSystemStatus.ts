import { useEffect, useState } from 'react'
import {
  fetchStatus,
  POLL_INTERVAL_MS,
  STATUS_TIMEOUT_MS,
  type StatusPoll,
} from './status'

/**
 * Poll `GET /status` while the caller is mounted (CAP-1): one fetch on mount,
 * then one every `POLL_INTERVAL_MS`, so a dependency that breaks — or gets
 * fixed — while the app is open changes the surface without a reload.
 *
 * A slow or dead poll times out at `STATUS_TIMEOUT_MS` and reads as
 * `unreachable`; the interval keeps ticking, so recovery is also automatic.
 * A stale response never overwrites a newer one: each tick's result is only
 * applied while the effect is still live, and ticks are serialized by the
 * interval rather than raced.
 */
export function useSystemStatus(): StatusPoll {
  const [poll, setPoll] = useState<StatusPoll>({ kind: 'loading' })

  useEffect(() => {
    let cancelled = false
    let inFlight = false

    const tick = async () => {
      // A hung request must not stack a second one behind it; the next
      // interval tick will find the flag cleared once the timeout fires.
      if (inFlight) return
      inFlight = true
      try {
        const status = await fetchStatus(AbortSignal.timeout(STATUS_TIMEOUT_MS))
        if (!cancelled) setPoll({ kind: 'loaded', status })
      } catch (error) {
        if (!cancelled) {
          const message =
            error instanceof Error ? error.message : String(error)
          setPoll({ kind: 'unreachable', message })
        }
      } finally {
        inFlight = false
      }
    }

    void tick()
    const timer = setInterval(() => void tick(), POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [])

  return poll
}
