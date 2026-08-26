import type { StreamEvent } from '@/client/core/serverSentEvents.gen'

/**
 * A hand-driven stand-in for one open `GET /jobs/events` connection.
 *
 * The tests need to decide exactly when an event lands, when the connection
 * drops, and when it comes back, which a real stream cannot give them. This
 * mirrors the generated client's surface: an async-iterable `stream`, the
 * `onSseEvent` / `onSseError` callbacks the hook listens on, and the
 * `signal` it passes for teardown.
 */
export interface StreamOptions {
  signal?: AbortSignal
  onSseEvent?: (event: StreamEvent<unknown>) => void
  onSseError?: (error: unknown) => void
}

export interface FakeStream {
  /** Deliver one event payload to the consumer. */
  emit: (value: unknown) => void
  /** Deliver a comment frame — what the api's `connected`/`heartbeat` look like. */
  comment: () => void
  /** Report a connection failure without ending the stream (the client retries). */
  fail: (error: unknown) => void
  /** End the stream the way the api does when no job is live any more. */
  close: () => void
  /** True once the consumer aborted the request (unmount). */
  readonly aborted: boolean
  stream: AsyncIterable<unknown>
}

export function createFakeStream(options: StreamOptions): FakeStream {
  const buffered: unknown[] = []
  const waiting: Array<(result: IteratorResult<unknown>) => void> = []
  let closed = false

  const close = () => {
    closed = true
    let waiter = waiting.shift()
    while (waiter) {
      waiter({ value: undefined, done: true })
      waiter = waiting.shift()
    }
  }

  // The real client aborts its fetch on this signal and the stream ends. A
  // helper that ignored it would leave every unmount-while-streaming path
  // untested — and a leaked connection invisible.
  options.signal?.addEventListener('abort', close)

  const emit = (value: unknown) => {
    if (closed) return
    options.onSseEvent?.({ data: value })
    const waiter = waiting.shift()
    if (waiter) waiter({ value, done: false })
    else buffered.push(value)
  }

  const comment = () => {
    if (closed) return
    options.onSseEvent?.({ data: undefined })
  }

  const stream: AsyncIterable<unknown> = {
    async *[Symbol.asyncIterator]() {
      while (true) {
        if (buffered.length > 0) {
          yield buffered.shift()
          continue
        }
        if (closed) return
        const result = await new Promise<IteratorResult<unknown>>((resolve) =>
          waiting.push(resolve),
        )
        if (result.done) return
        yield result.value
      }
    },
  }

  return {
    emit,
    comment,
    fail: (error) => options.onSseError?.(error),
    close,
    get aborted() {
      return options.signal?.aborted ?? false
    },
    stream,
  }
}
