import { useCallback, useEffect, useRef, useState } from 'react'
import { getAcquisition } from '@/client/sdk.gen'
import type { AcquisitionStatus } from '@/client/types.gen'
import { type Failure, failureOf, isLive } from './acquisitions'

/** EXPERIENCE.md:93 — poll every 2s while the acquisition is `queued | running`. */
export const POLL_INTERVAL_MS = 2000

export interface AcquisitionStatusState {
  /** The last status actually read. Never cleared by a failed poll. */
  status: AcquisitionStatus | null
  /** A poll that did not answer. The stepper keeps its last state beneath it. */
  failure: Failure | null
  /** Resume polling after a failure. */
  retry: () => void
}

/**
 * Follow one acquisition until it settles.
 *
 * Polling stops for good on `posted | failed`: those are terminal in story
 * 6.4's state machine, and from `posted` onward the truth lives on the job,
 * which already streams through `useJobEvents`. Continuing to poll would be
 * the second progress mechanism this story exists to avoid.
 *
 * A poll that does not answer keeps the last status on screen and surfaces the
 * transport failure with a Retry. Nothing is inferred about the acquisition
 * from a failure to reach the api: the process on the host is unaffected by
 * this browser's ability to ask about it.
 */
export function useAcquisitionStatus(acquisitionId: string | null): AcquisitionStatusState {
  const [status, setStatus] = useState<AcquisitionStatus | null>(null)
  const [failure, setFailure] = useState<Failure | null>(null)
  const [attempt, setAttempt] = useState(0)
  // Bumped whenever the followed acquisition changes, so a reply in flight for
  // the previous one can never write over the new one's state.
  const generation = useRef(0)

  const retry = useCallback(() => {
    setFailure(null)
    setAttempt((value) => value + 1)
  }, [])

  useEffect(() => {
    // A different acquisition is a different subject: drop the old one's
    // status rather than showing it under the new id.
    generation.current += 1
    setStatus(null)
    setFailure(null)
  }, [acquisitionId])

  useEffect(() => {
    if (acquisitionId === null) return
    generation.current += 1
    const mine = generation.current
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    let stopped = false

    const owned = () => !stopped && generation.current === mine

    const poll = async () => {
      try {
        const { data, error } = await getAcquisition({
          path: { acquisition_id: acquisitionId },
          signal: controller.signal,
        })
        if (!owned()) return
        if (error !== undefined || data === undefined) {
          setFailure(failureOf(error))
          return
        }
        setStatus(data)
        setFailure(null)
        // Terminal: stop rather than schedule. `isLive` reads story 6.4's
        // vocabulary, so a status this build does not recognise also stops
        // instead of polling forever.
        if (!isLive(data.status)) return
        timer = setTimeout(() => void poll(), POLL_INTERVAL_MS)
      } catch (err) {
        if (!owned() || controller.signal.aborted) return
        setFailure(failureOf(err))
      }
    }

    void poll()
    return () => {
      stopped = true
      controller.abort()
      if (timer !== undefined) clearTimeout(timer)
    }
  }, [acquisitionId, attempt])

  return { status, failure, retry }
}
