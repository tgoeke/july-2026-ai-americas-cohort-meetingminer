import { useEffect, useRef, useState } from 'react'
import { streamJobEvents } from '@/client/sdk.gen'
import type { JobEvent } from '@/client/types.gen'

/**
 * The three names the api streams (FR8). The generated client types the
 * stream's payload as `unknown` — OpenAPI 3.2 describes an SSE body in a shape
 * the generator does not read — so the narrowing happens here, against the
 * generated `JobEvent` type.
 */
export const WIRE_EVENT_NAMES = ['job.stage', 'job.done', 'job.error'] as const

export function isJobEvent(value: unknown): value is JobEvent {
  if (typeof value !== 'object' || value === null) return false
  const candidate = value as Record<string, unknown>
  return (
    typeof candidate.jobId === 'string' &&
    typeof candidate.event === 'string' &&
    (WIRE_EVENT_NAMES as readonly string[]).includes(candidate.event) &&
    typeof candidate.viewable === 'boolean'
  )
}

export type ConnectionState =
  | { kind: 'connecting' }
  | { kind: 'live' }
  | { kind: 'lost'; message: string }

/**
 * A dropped connection is normal — the api restarts, the laptop sleeps — and
 * the generated client reconnects on its own with backoff. Surfacing the first
 * failure would make routine recovery look like breakage, so the banner waits
 * until the retries have stopped looking momentary.
 */
export const RECONNECT_NOISE_THRESHOLD = 2

/** Pause before reopening a stream the server closed because nothing is live. */
export const REOPEN_DELAY_MS = 1000

function describe(error: unknown): string {
  if (error instanceof Error) return error.message
  if (typeof error === 'string') return error
  return 'the connection was closed'
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

export interface JobEventsOptions {
  /** Applied to the list as it arrives. */
  onEvent: (event: JobEvent) => void
  /**
   * Called when the stream comes back after a break. Events emitted while the
   * connection was down are gone, so the list re-seeds from `GET /meetings`
   * rather than trying to replay them.
   */
  onResync: () => void
  /**
   * Called for every frame the stream delivers, heartbeat comments included.
   *
   * This is the api answering, nothing more — but it is the signal a list that
   * has never loaded needs: the seed may have failed while the api was down,
   * and a heartbeat is proof it is worth asking again. It is what keeps a
   * failed first load from wedging on an idle system, where no event will ever
   * arrive to prompt a retry, without introducing a browser-side poll.
   */
  onAlive?: () => void
}

/**
 * Hold one `GET /jobs/events` connection for the life of the component.
 *
 * One stream carries every job, keyed by `jobId` — browsers cap concurrent
 * connections per origin, and a per-job endpoint would spend that budget for
 * nothing. There is deliberately no polling loop here: the stream is the
 * mechanism, and the seed fetch only gives it a starting point.
 */
export function useJobEvents({ onEvent, onResync, onAlive }: JobEventsOptions): ConnectionState {
  const [connection, setConnection] = useState<ConnectionState>({ kind: 'connecting' })
  // Held in a ref so a re-render with fresh closures never restarts the
  // stream: the effect below must run exactly once per mount. Written in an
  // effect rather than in the render body — a ref write during render is
  // unsafe under StrictMode and concurrent rendering, which may render a
  // component whose output is then thrown away.
  const handlers = useRef({ onEvent, onResync, onAlive })
  useEffect(() => {
    handlers.current = { onEvent, onResync, onAlive }
  }, [onEvent, onResync, onAlive])

  useEffect(() => {
    const controller = new AbortController()
    let cancelled = false
    let live = false
    let everConnected = false
    let consecutiveFailures = 0

    const markLive = () => {
      consecutiveFailures = 0
      handlers.current.onAlive?.()
      if (live) return
      live = true
      setConnection({ kind: 'live' })
      // Not on the first connection: the list seeds itself on mount, and the
      // stream's own baseline is taken at that same moment.
      if (everConnected) handlers.current.onResync()
      everConnected = true
    }

    const markLost = (error: unknown) => {
      live = false
      consecutiveFailures += 1
      if (consecutiveFailures >= RECONNECT_NOISE_THRESHOLD) {
        setConnection({ kind: 'lost', message: describe(error) })
      }
    }

    const run = async () => {
      while (!cancelled) {
        try {
          const { stream } = await streamJobEvents({
            signal: controller.signal,
            // A frame with no data is one of the stream's comments
            // (`connected`, `heartbeat`). Those are the only proof the
            // connection is alive while no stage is moving.
            onSseEvent: (frame) => {
              if (cancelled || frame.data !== undefined) return
              markLive()
            },
            onSseError: (error) => {
              if (cancelled) return
              markLost(error)
            },
          })
          for await (const data of stream) {
            if (cancelled) return
            // Any payload at all means bytes are flowing, comment or not.
            markLive()
            if (isJobEvent(data)) handlers.current.onEvent(data)
          }
        } catch (error) {
          if (cancelled) return
          markLost(error)
        }
        // The stream ended: either the api closed it because no job is live
        // any more (its documented behaviour), or the client gave up retrying.
        // Either way there is no connection until the reopen below succeeds,
        // and saying "live" through that window would be a lie.
        live = false
        if (cancelled) return
        setConnection((previous) => (previous.kind === 'live' ? { kind: 'connecting' } : previous))
        await sleep(REOPEN_DELAY_MS)
      }
    }

    void run()
    return () => {
      cancelled = true
      controller.abort()
    }
  }, [])

  return connection
}
