import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { CitationModel, RouteModel } from '@/client/types.gen'
import { ChatPanel } from './ChatPanel'
import { questionProblem } from './chat'

/**
 * Every test here mocks `fetch` — no test may call the live `/chat` endpoint
 * (AGENTS.md, the Anthropic key is revoked). `chatStream.ts` is a hand-rolled
 * `fetch` reader rather than the generated SSE client precisely so a 422 body
 * can be read on the same request that would otherwise open the stream, so
 * these mocks build a real `Response` — a `ReadableStream` body for the
 * happy path, a JSON body with `response.ok === false` for the rejection.
 */

function sseFrame(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`
}

function streamResponse(chunks: Array<string>): Response {
  const encoder = new TextEncoder()
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
      controller.close()
    },
  })
  return new Response(stream, {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  })
}

/** A stream response plus the handle to push chunks and close it whenever the
 * test decides — for a request whose answer is still arriving. */
function openStreamResponse(): {
  response: Response
  push: (chunk: string) => void
  close: () => void
} {
  const encoder = new TextEncoder()
  let controllerRef!: ReadableStreamDefaultController<Uint8Array>
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controllerRef = controller
    },
  })
  const response = new Response(stream, {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  })
  return {
    response,
    push: (chunk: string) => controllerRef.enqueue(encoder.encode(chunk)),
    close: () => controllerRef.close(),
  }
}

function problemResponse(status: number, body: Record<string, unknown>): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/problem+json' },
  })
}

function citation(overrides: Partial<CitationModel> = {}): CitationModel {
  return {
    momentId: 'moment-1',
    meetingId: 'meeting-1',
    startMs: 65_000,
    endMs: 70_000,
    screenshotId: 'screenshot-1',
    sourceDeepLink: null,
    ...overrides,
  }
}

function route(overrides: Partial<RouteModel> = {}): RouteModel {
  return {
    template: null,
    anchorResolved: null,
    traversalOutcome: 'not-dispatched',
    fallbackReason: null,
    searchHits: 1,
    traversalRows: 0,
    traversalTruncated: false,
    retrieved: 1,
    ...overrides,
  }
}

let fetchMock: ReturnType<typeof vi.fn>

/**
 * The ask box now mounts the model select (story 8.3), which reads
 * `GET /settings/models` and `GET /status` on mount through the generated
 * client. Those reads are not this file's subject, and the assertions below
 * count `fetchMock` calls to prove one submitted question makes exactly one
 * request — so they are answered here and never reach `fetchMock`.
 *
 * The router matches exact endpoint paths. Call shape is deliberately not a
 * discriminator: a future generated `/chat` client must still reach the chat
 * mock, and an unexpected generated-client read must fail by name.
 */
function pickerResponse(pathname: string): Response {
  const body = pathname === '/status'
    ? {
        generatedAt: '2026-08-31T00:00:00Z',
        overall: 'ok',
        api: { id: 'api', label: 'api', state: 'ok', detail: '', remediation: null },
        stores: [],
        llmRoles: [],
        worker: { state: 'running', jobs: {}, stageBacklog: {}, detail: '', remediation: null },
      }
    : { roles: [] }
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

beforeEach(() => {
  fetchMock = vi.fn()
  // `vi.fn()`'s type is not callable on its own; the chat half of the router
  // needs the signature `chatStream()` actually uses.
  const chatFetch = fetchMock as unknown as (
    url: unknown,
    init?: RequestInit,
  ) => Promise<Response>
  vi.stubGlobal('fetch', (input: unknown, init?: RequestInit) => {
    const url = new URL(input instanceof Request ? input.url : String(input), 'http://test')
    if (url.pathname === '/settings/models' || url.pathname === '/status') {
      return Promise.resolve(pickerResponse(url.pathname))
    }
    if (url.pathname === '/chat') return chatFetch(input, init)
    return Promise.reject(new Error(`unexpected ChatPanel request: ${url.pathname}`))
  })
})

async function ask(question: string) {
  const user = userEvent.setup()
  await user.type(screen.getByTestId('chat-question-input'), question)
  await user.click(screen.getByTestId('chat-submit'))
  return user
}

describe('ChatPanel', () => {
  it('does not mistake a Request-shaped chat call for a picker read', async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }))
    const request = new Request('http://localhost:8000/chat', { method: 'POST' })

    await globalThis.fetch(request)

    expect(fetchMock).toHaveBeenCalledExactlyOnceWith(request, undefined)
  })

  it('streams the validated answer, renders citations, and opens the moment on click', async () => {
    fetchMock.mockResolvedValue(
      streamResponse([
        sseFrame('chat.token', { event: 'chat.token', text: 'The order ' }),
        sseFrame('chat.token', { event: 'chat.token', text: 'was approved.' }),
        sseFrame('chat.citations', { event: 'chat.citations', citations: [citation()] }),
        sseFrame('chat.done', { event: 'chat.done', route: route() }),
      ]),
    )
    const onOpenMoment = vi.fn()
    render(<ChatPanel onOpenMoment={onOpenMoment} />)

    expect(await screen.findByTestId('model-select-not-offered')).toHaveTextContent(
      'chat role is not offered for selection',
    )

    await ask('What happened with the purchase order?')

    // Exactly one request for the one submitted question — never the JSON
    // askCorpus() call in addition (Boundaries).
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(init.method).toBe('POST')
    expect(new Headers(init.headers).get('accept')).toBe('text/event-stream')
    expect(JSON.parse(init.body as string)).toEqual({
      question: 'What happened with the purchase order?',
    })

    // Concatenating every chat.token text reproduces the answer verbatim —
    // no client-side reformatting.
    await waitFor(() =>
      expect(screen.getByTestId('chat-answer')).toHaveTextContent(
        'The order was approved.',
      ),
    )
    await waitFor(() => expect(screen.getByTestId('chat-route-summary')).toHaveTextContent(
      'answered from 1 moment',
    ))

    // `-0`: the index disambiguates a citation list keyed on `momentId` alone,
    // which would collide if the same moment were cited twice.
    const citationRow = screen.getByTestId('chat-citation-moment-1-0')
    await userEvent.click(within(citationRow).getByRole('button', { name: /open moment/i }))
    // Opens by momentId alone — no branch on screenshotId/sourceDeepLink.
    expect(onOpenMoment).toHaveBeenCalledExactlyOnceWith('moment-1')
  })

  it('links a YouTube citation back to the video at its offset beside Open moment', async () => {
    // UX-DR12 on chat citations: YouTube only — another host or a null link
    // leaves the row exactly as before.
    fetchMock.mockResolvedValue(
      streamResponse([
        sseFrame('chat.token', { event: 'chat.token', text: 'The order was approved.' }),
        sseFrame('chat.citations', {
          event: 'chat.citations',
          citations: [
            citation({ sourceDeepLink: 'https://www.youtube.com/watch?v=abc' }),
            citation({
              momentId: 'moment-2',
              startMs: 5_000,
              sourceDeepLink: 'https://example.sharepoint.com/stream.aspx?id=x',
            }),
            citation({ momentId: 'moment-3', startMs: 6_000, sourceDeepLink: null }),
          ],
        }),
        sseFrame('chat.done', { event: 'chat.done', route: route() }),
      ]),
    )
    const onOpenMoment = vi.fn()
    render(<ChatPanel onOpenMoment={onOpenMoment} />)

    await ask('What happened with the purchase order?')

    const row = await screen.findByTestId('chat-citation-moment-1-0')
    const link = within(row).getByTestId('chat-citation-youtube-moment-1-0')
    // The name carries the offset (65 000 ms); the `↗` glyph is hidden.
    expect(link).toBe(within(row).getByRole('link', { name: 'Open on YouTube at 1:05' }))
    expect(link).toHaveAttribute('href', 'https://www.youtube.com/watch?v=abc&t=65')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noreferrer')
    // `Open moment` is unchanged, precedes the link, and still opens by
    // `momentId` alone.
    const open = within(row).getByRole('button', { name: /open moment/i })
    expect(open.compareDocumentPosition(link)).toBe(Node.DOCUMENT_POSITION_FOLLOWING)
    await userEvent.click(open)
    expect(onOpenMoment).toHaveBeenCalledExactlyOnceWith('moment-1')
    // Another host, or no link at all: offset and `Open moment` only.
    for (const id of ['chat-citation-moment-2-1', 'chat-citation-moment-3-2']) {
      const other = screen.getByTestId(id)
      expect(within(other).queryByRole('link')).toBeNull()
      expect(within(other).getByRole('button', { name: /open moment/i })).toBeInTheDocument()
    }
  })

  it('renders an explicit no-citable-answer state on a 422 gate rejection, not a chat bubble', async () => {
    fetchMock.mockResolvedValue(
      problemResponse(422, {
        type: 'urn:meetingminer:problem:no-citable-answer',
        title: 'Unprocessable Content',
        status: 422,
        detail: 'no moment in the corpus matched the question',
        reason: 'no-evidence',
        route: route({ retrieved: 0 }),
      }),
    )
    render(<ChatPanel />)

    await ask('Who approved the invoice nobody discussed?')

    await waitFor(() => expect(screen.getByTestId('chat-rejected')).toBeInTheDocument())
    expect(screen.getByTestId('chat-rejected')).toHaveTextContent(
      'no moment in the corpus matched the question',
    )
    expect(screen.queryByTestId('chat-answer')).not.toBeInTheDocument()
    expect(screen.queryByTestId('chat-failure')).not.toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('shows a failure banner on a transport failure, with no partial answer', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'))
    render(<ChatPanel />)

    await ask('What did we decide?')

    await waitFor(() => expect(screen.getByTestId('chat-failure')).toBeInTheDocument())
    // A fetch that never connected is the one case that earns the "Cannot
    // reach" wording (SPEC CAP-3) — and it is not a timeout.
    expect(screen.getByTestId('chat-failure')).toHaveTextContent('Cannot reach the api')
    expect(screen.getByTestId('chat-failure')).toHaveTextContent('Failed to fetch')
    expect(screen.getByTestId('chat-failure')).not.toHaveTextContent('did not finish within')
    expect(screen.queryByTestId('chat-answer')).not.toBeInTheDocument()
    expect(screen.queryByTestId('chat-rejected')).not.toBeInTheDocument()
  })

  it('names what is unreachable on a 503 store/model outage, without retrying', async () => {
    fetchMock.mockResolvedValue(
      problemResponse(503, {
        type: 'urn:meetingminer:problem:chat-graph-store-unavailable',
        title: 'Service Unavailable',
        status: 503,
        detail: 'the graph store could not be reached: connection refused',
        store: 'neo4j',
      }),
    )
    render(<ChatPanel />)

    await ask('What happened over time on this screen?')

    await waitFor(() => expect(screen.getByTestId('chat-failure')).toBeInTheDocument())
    expect(screen.getByTestId('chat-failure')).toHaveTextContent('graph store could not be reached')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('renders a chat-model 503 in the server\'s words, naming the failed binding', async () => {
    // SPEC CAP-4: with no fallback configured, the primary model failing is a
    // prompt 503 whose detail names the `llm.roles.chat` binding — and the
    // panel must show that sentence, not a generic transport line.
    fetchMock.mockResolvedValue(
      problemResponse(503, {
        type: 'urn:meetingminer:problem:chat-model-unavailable',
        title: 'Service Unavailable',
        status: 503,
        detail:
          "the `llm.roles.chat` binding ('openai/gpt-5.2', no fallback"
          + ' configured) could not be reached for classification: Incorrect'
          + ' API key provided',
        purpose: 'classification',
        binding: 'llm.roles.chat',
        model: 'openai/gpt-5.2',
      }),
    )
    render(<ChatPanel />)

    await ask('What happened with the purchase order?')

    await waitFor(() => expect(screen.getByTestId('chat-failure')).toBeInTheDocument())
    const banner = screen.getByTestId('chat-failure')
    expect(banner).toHaveTextContent('llm.roles.chat')
    expect(banner).toHaveTextContent('openai/gpt-5.2')
    // The api answered — it is not unreachable, and the failure is final:
    // exactly one request, never a retry.
    expect(banner).not.toHaveTextContent('Cannot reach')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('refuses a blank or over-length question client-side, sending no request', async () => {
    render(<ChatPanel />)
    expect(screen.getByTestId('chat-submit')).toBeDisabled()

    act(() => {
      fireEvent.change(screen.getByTestId('chat-question-input'), {
        target: { value: 'x'.repeat(1001) },
      })
    })
    expect(screen.getByTestId('chat-submit')).toBeDisabled()
    expect(screen.getByTestId('chat-question-problem')).toHaveTextContent(
      'limited to 1000 characters',
    )
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('counts Unicode code points so an API-valid emoji question is not refused locally', () => {
    // 501 astral characters are 1,002 UTF-16 code units but only 501 Python
    // characters, so the client must match the API's code-point bound.
    expect(questionProblem('😀'.repeat(501))).toBeNull()
  })

  it('surfaces a failure, not a silent partial answer, when the stream closes before chat.done', async () => {
    fetchMock.mockResolvedValue(
      streamResponse([
        sseFrame('chat.token', { event: 'chat.token', text: 'The order ' }),
        sseFrame('chat.citations', { event: 'chat.citations', citations: [citation()] }),
        // No chat.done: the connection was cut mid-stream.
      ]),
    )
    render(<ChatPanel />)

    await ask('What happened with the purchase order?')

    await waitFor(() => expect(screen.getByTestId('chat-failure')).toBeInTheDocument())
    expect(screen.getByTestId('chat-failure')).toHaveTextContent(
      'connection closed before the answer completed',
    )
    // The connection was established and the server was answering — this is
    // an interruption, never an unreachable api (SPEC CAP-3).
    expect(screen.getByTestId('chat-failure')).not.toHaveTextContent('Cannot reach')
    // Not shown as if it were the complete, validated answer.
    expect(screen.queryByTestId('chat-answer')).not.toBeInTheDocument()
    expect(screen.queryByTestId('chat-citations')).not.toBeInTheDocument()
    expect(screen.queryByTestId('chat-route-summary')).not.toBeInTheDocument()
  })

  it('aborts the first request and shows only the second answer on a re-submit before the first resolves', async () => {
    const first = openStreamResponse()
    fetchMock.mockImplementationOnce(() => Promise.resolve(first.response))
    fetchMock.mockImplementationOnce(() =>
      Promise.resolve(
        streamResponse([
          sseFrame('chat.token', { event: 'chat.token', text: 'Second answer.' }),
          sseFrame('chat.citations', {
            event: 'chat.citations',
            citations: [citation({ momentId: 'moment-2' })],
          }),
          sseFrame('chat.done', { event: 'chat.done', route: route() }),
        ]),
      ),
    )
    render(<ChatPanel onOpenMoment={vi.fn()} />)

    const user = userEvent.setup()
    await user.type(screen.getByTestId('chat-question-input'), 'first question')
    await user.click(screen.getByTestId('chat-submit'))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    first.push(sseFrame('chat.token', { event: 'chat.token', text: 'First partial…' }))
    await waitFor(() => expect(screen.getByTestId('chat-answer')).toHaveTextContent('First partial'))

    const firstSignal = (fetchMock.mock.calls[0] as [string, RequestInit])[1].signal
    expect(firstSignal?.aborted).toBe(false)

    await user.clear(screen.getByTestId('chat-question-input'))
    await user.type(screen.getByTestId('chat-question-input'), 'second question')
    await user.click(screen.getByTestId('chat-submit'))

    // The first request's stream is aborted, not left to resolve into stale
    // state — an older answer must never overwrite a newer one.
    expect(firstSignal?.aborted).toBe(true)

    await waitFor(() =>
      expect(screen.getByTestId('chat-answer')).toHaveTextContent('Second answer.'),
    )
    expect(screen.queryByTestId('chat-citation-moment-1-0')).not.toBeInTheDocument()
    expect(screen.getByTestId('chat-citation-moment-2-0')).toBeInTheDocument()

    first.close()
  })

  it('finishes on chat.done without waiting for the transport to close', async () => {
    const stream = openStreamResponse()
    fetchMock.mockResolvedValue(stream.response)
    render(<ChatPanel />)

    await ask('What happened with the purchase order?')
    stream.push(sseFrame('chat.token', { event: 'chat.token', text: 'Approved.' }))
    stream.push(sseFrame('chat.citations', { event: 'chat.citations', citations: [citation()] }))

    await waitFor(() => expect(screen.getByTestId('chat-answer')).toHaveTextContent('Approved.'))
    // Citations are held until the terminal protocol event, rather than made
    // actionable during a turn that can still fail.
    expect(screen.queryByTestId('chat-citations')).not.toBeInTheDocument()

    stream.push(sseFrame('chat.done', { event: 'chat.done', route: route() }))

    await waitFor(() => expect(screen.getByTestId('chat-route-summary')).toBeInTheDocument())
    expect(screen.getByTestId('chat-citations')).toBeInTheDocument()
    expect(screen.getByTestId('chat-route-summary').parentElement).toHaveAttribute(
      'aria-busy',
      'false',
    )
    stream.close()
  })

  it('reports the chat-timeout expiry as a timeout, never as an unreachable api', async () => {
    vi.useFakeTimers()
    try {
      fetchMock.mockImplementation((_url: string, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener(
            'abort',
            () => reject(new DOMException('The operation was aborted.', 'AbortError')),
            { once: true },
          )
        }),
      )
      render(<ChatPanel />)

      fireEvent.change(screen.getByTestId('chat-question-input'), {
        target: { value: 'What happened with the purchase order?' },
      })
      fireEvent.submit(screen.getByTestId('chat-submit').closest('form')!)
      await act(async () => {
        await Promise.resolve()
      })
      expect(fetchMock).toHaveBeenCalledTimes(1)

      await act(async () => {
        await vi.advanceTimersByTimeAsync(60_000)
      })

      // SPEC CAP-3: the expiry names the wait, not the transport. The recorded
      // failure rendered "Cannot reach the api ... timed out after 60000ms"
      // for a server that was up and still answering (failure-evidence.md).
      expect(screen.getByTestId('chat-failure')).toHaveTextContent(
        'did not finish within 60s',
      )
      expect(screen.getByTestId('chat-failure')).not.toHaveTextContent('Cannot reach')
      expect(screen.queryByTestId('chat-answer')).not.toBeInTheDocument()
      expect(screen.queryByTestId('chat-citations')).not.toBeInTheDocument()
    } finally {
      vi.useRealTimers()
    }
  })

  it('yields the final frame even when the server closes the stream with no trailing blank line', async () => {
    // Every other test's frames all end in `\n\n` (the SSE record separator).
    // A server that writes its last frame and closes the connection right
    // after, with no trailing separator, still has to be read to the end.
    const chunks = [
      sseFrame('chat.token', { event: 'chat.token', text: 'Approved.' }),
      sseFrame('chat.citations', { event: 'chat.citations', citations: [citation()] }),
      `event: chat.done\ndata: ${JSON.stringify({ event: 'chat.done', route: route() })}`,
    ]
    fetchMock.mockResolvedValue(streamResponse(chunks))
    render(<ChatPanel />)

    await ask('What happened with the purchase order?')

    await waitFor(() =>
      expect(screen.getByTestId('chat-route-summary')).toHaveTextContent('answered from 1 moment'),
    )
    expect(screen.getByTestId('chat-answer')).toHaveTextContent('Approved.')
    expect(screen.queryByTestId('chat-failure')).not.toBeInTheDocument()
  })
})
