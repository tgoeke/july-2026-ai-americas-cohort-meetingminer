import { client } from '@/client/client.gen'
import type { ChatRequest } from '@/client/types.gen'
import {
  ChatHttpError,
  isChatCitationsFrame,
  isChatDoneFrame,
  isChatTokenFrame,
  type ChatFrame,
} from './chat'

/**
 * A hand-rolled `fetch`-based reader for `POST /chat`.
 *
 * Not the generated `client.sse.post`/`createSseClient`
 * (`web/src/client/core/serverSentEvents.gen.ts:135,228`): that client throws
 * away the response body on a non-2xx status and retries indefinitely by
 * default. A `422 no-citable-answer` is the server's final word on this
 * question, not a transient failure — resubmitting it would double a real,
 * config-bound `Llm(chat)` call for nothing. So this makes exactly one
 * request and reads either outcome from it: a `2xx` opens the event stream,
 * anything else is parsed as the JSON problem body and thrown as a
 * `ChatHttpError` that keeps its status and body intact.
 */
export interface ChatStreamOptions {
  signal?: AbortSignal
  /** Substituted in tests; defaults to the global `fetch`. */
  fetchImpl?: typeof fetch
}

function parseFrame(chunk: string): ChatFrame | null {
  const lines = chunk.split('\n')
  const dataLines: Array<string> = []
  for (const line of lines) {
    if (line.startsWith('data:')) dataLines.push(line.replace(/^data:\s*/, ''))
  }
  if (dataLines.length === 0) return null
  let data: unknown
  try {
    data = JSON.parse(dataLines.join('\n'))
  } catch {
    // A non-JSON data line is not one of this endpoint's frames — nothing
    // else on this stream is meant to be parsed.
    return null
  }
  if (isChatTokenFrame(data)) return data
  if (isChatCitationsFrame(data)) return data
  if (isChatDoneFrame(data)) return data
  return null
}

async function parseProblemBody(response: Response): Promise<unknown> {
  try {
    return await response.json()
  } catch {
    return undefined
  }
}

/**
 * Ask one question and stream its already-validated answer.
 *
 * Yields `chat.token`, `chat.citations`, then `chat.done`, in that order —
 * the order `/chat` writes them in (`server/meetingminer/api/chat.py`'s
 * `_sse_events`). Throws `ChatHttpError` for a non-2xx response (its `status`
 * distinguishes a 422 gate rejection from a 503 store/model outage) or
 * whatever `fetch` itself threw for a transport failure.
 */
export async function* chatStream(
  question: string,
  options: ChatStreamOptions = {},
): AsyncGenerator<ChatFrame, void, unknown> {
  const fetchImpl = options.fetchImpl ?? globalThis.fetch
  const url = client.buildUrl({ url: '/chat' })
  const response = await fetchImpl(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    },
    // `satisfies ChatRequest` type-binds the hand-built body to the
    // generated contract, the same way the response frames are bound via
    // `CitationModel`/`RouteModel` — a server-side rename of `question`
    // fails the build here instead of drifting silently.
    body: JSON.stringify({ question } satisfies ChatRequest),
    signal: options.signal,
  })

  if (!response.ok) {
    const body = await parseProblemBody(response)
    throw new ChatHttpError(
      response.status,
      body,
      `the api refused the question with status ${response.status}`,
    )
  }
  if (response.body === null) {
    throw new Error('the api answered with no body')
  }

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += value
      buffer = buffer.replace(/\r\n?/g, '\n')
      const chunks = buffer.split('\n\n')
      buffer = chunks.pop() ?? ''
      for (const chunk of chunks) {
        const frame = parseFrame(chunk)
        if (frame !== null) yield frame
      }
    }
    // The final chunk may arrive with no trailing blank line if the server
    // closes the connection right after writing it.
    if (buffer.trim() !== '') {
      const frame = parseFrame(buffer)
      if (frame !== null) yield frame
    }
  } finally {
    reader.releaseLock()
  }
}
