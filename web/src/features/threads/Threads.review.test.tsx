import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { Threads } from './Threads'

const A = {
  threadId: 'thread-a',
  name: 'alpha thread',
  mentionCount: 1,
  meetingCount: 1,
  firstMentionAt: '2026-01-01T00:00:00Z',
  lastMentionAt: '2026-08-20T00:00:00Z',
  colorOrdinal: 1,
}
const B = {
  threadId: 'thread-b',
  name: 'beta thread',
  mentionCount: 10,
  meetingCount: 1,
  firstMentionAt: '2026-01-01T00:00:00Z',
  lastMentionAt: '2026-08-01T00:00:00Z',
  colorOrdinal: 2,
}

function response(payload: unknown, status = 200): Response {
  return {
    ok: status < 400,
    status,
    statusText: status < 400 ? 'OK' : 'Unavailable',
    text: async () => JSON.stringify(payload),
  } as Response
}

function levelOf(url: string) {
  return new URL(url, 'http://meetingminer.test').searchParams.get('level')
}

function bands(threadId: string) {
  const count = threadId === B.threadId ? 10 : 1
  return {
    buckets: [
      {
        from: '2026-04-01T00:00:00Z',
        to: '2026-04-08T00:00:00Z',
        mentionCount: count,
      },
    ],
  }
}

function meetings(title: string) {
  return {
    meetings: [
      {
        meetingId: `meeting-${title}`,
        title,
        occurredAt: '2026-04-03T12:00:00Z',
        durationMs: 3_600_000,
        mentionCount: 1,
      },
    ],
  }
}

function mount(at = '/threads', navigation = false) {
  function Navigation() {
    const navigate = useNavigate()
    return navigation ? (
      <button type="button" onClick={() => navigate(`/threads/${B.threadId}`)}>
        open beta route
      </button>
    ) : null
  }
  return render(
    <MemoryRouter initialEntries={[at]}>
      <Navigation />
      <Routes>
        <Route path="/threads" element={<Threads />} />
        <Route path="/threads/:threadId" element={<Threads />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/threads')) return Promise.resolve(response([B, A]))
      const threadId = decodeURIComponent(/\/threads\/([^/?]+)/.exec(url)?.[1] ?? '')
      if (levelOf(url) === 'bands') return Promise.resolve(response(bands(threadId)))
      if (levelOf(url) === 'meetings') return Promise.resolve(response(meetings(`${threadId} meeting`)))
      return Promise.resolve(response({ moments: [] }))
    }),
  )
})

afterEach(() => vi.unstubAllGlobals())

async function loadedBands() {
  mount()
  await screen.findByRole('gridcell', { name: /beta thread, 2026-04-01/ })
}

describe('reviewed screen orchestration', () => {
  it('keeps a short corpus in the bands tier on initial fit', async () => {
    const short = {
      ...A,
      firstMentionAt: '2026-04-03T12:00:00Z',
      lastMentionAt: '2026-04-03T13:00:00Z',
    }
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (url.endsWith('/threads')) return Promise.resolve(response([short]))
        return Promise.resolve(response(bands(short.threadId)))
      }),
    )
    mount()
    expect(await screen.findByRole('grid', { name: /bands tier/i })).toBeInTheDocument()
    expect(await screen.findByRole('gridcell', { name: /alpha thread, 2026-04-01/ })).toBeInTheDocument()
  })

  it('retries a refused tier request instead of only hiding the refusal', async () => {
    let meetingAttempts = 0
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (url.endsWith('/threads')) return Promise.resolve(response([A]))
        if (levelOf(url) === 'bands') return Promise.resolve(response(bands(A.threadId)))
        meetingAttempts += 1
        return Promise.resolve(
          meetingAttempts === 1
            ? response({ title: 'unavailable', detail: 'try again' }, 503)
            : response(meetings('retry succeeded')),
        )
      }),
    )
    const user = userEvent.setup()
    mount()
    await user.click(await screen.findByRole('gridcell', { name: /alpha thread, 2026-04-01/ }))
    const alert = await screen.findByRole('alert')
    await user.click(within(alert).getByRole('button', { name: 'Retry' }))
    expect(await screen.findByRole('gridcell', { name: /retry succeeded/ })).toBeInTheDocument()
    expect(meetingAttempts).toBe(2)
  })

  it('invalidates an in-flight generation when a cached tier becomes current', async () => {
    let releaseBody: (() => void) | undefined
    const bodyGate = new Promise<void>((resolve) => {
      releaseBody = resolve
    })
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (url.endsWith('/threads')) return Promise.resolve(response([A]))
        if (levelOf(url) === 'bands') return Promise.resolve(response(bands(A.threadId)))
        return Promise.resolve({
          ok: true,
          status: 200,
          statusText: 'OK',
          text: async () => {
            await bodyGate
            return JSON.stringify(meetings('late meeting'))
          },
        } as Response)
      }),
    )
    const user = userEvent.setup()
    mount()
    await user.click(await screen.findByRole('gridcell', { name: /alpha thread, 2026-04-01/ }))
    await waitFor(() =>
      expect(
        vi.mocked(fetch).mock.calls.some((call) => levelOf(String(call[0])) === 'meetings'),
      ).toBe(true),
    )
    await user.click(screen.getByRole('button', { name: 'Fit (Home)' }))
    expect(screen.getByRole('grid', { name: /bands tier/i })).toBeInTheDocument()
    await act(async () => releaseBody?.())
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(screen.getByRole('grid', { name: /bands tier/i })).toBeInTheDocument()
    expect(screen.queryByText('late meeting')).not.toBeInTheDocument()
  })

  it('keeps an outgoing fine-tier payload paired with its owning thread', async () => {
    let releaseBeta: (() => void) | undefined
    const betaGate = new Promise<void>((resolve) => {
      releaseBeta = resolve
    })
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (url.endsWith('/threads')) return Promise.resolve(response([A, B]))
        const id = decodeURIComponent(/\/threads\/([^/?]+)/.exec(url)?.[1] ?? '')
        if (levelOf(url) === 'bands') return Promise.resolve(response(bands(id)))
        if (id === B.threadId) {
          return Promise.resolve({
            ok: true,
            status: 200,
            statusText: 'OK',
            text: async () => {
              await betaGate
              return JSON.stringify(meetings('beta payload'))
            },
          } as Response)
        }
        return Promise.resolve(response(meetings('alpha payload')))
      }),
    )
    const user = userEvent.setup()
    mount()
    await user.click(await screen.findByRole('gridcell', { name: /alpha thread, 2026-04-01/ }))
    expect(await screen.findByRole('gridcell', { name: /alpha payload/ })).toBeInTheDocument()
    const list = screen.getByRole('complementary', { name: 'Threads' })
    await user.click(within(list).getByRole('button', { name: /beta thread/ }))
    expect(screen.getByRole('rowheader', { name: 'alpha thread' })).toBeInTheDocument()
    expect(screen.queryByRole('rowheader', { name: 'beta thread' })).not.toBeInTheDocument()
    await act(async () => releaseBeta?.())
    expect(await screen.findByRole('rowheader', { name: 'beta thread' })).toBeInTheDocument()
  })

  it('applies the selected ordering to the list and the canvas rows', async () => {
    const user = userEvent.setup()
    await loadedBands()
    await user.click(screen.getByRole('button', { name: 'recency' }))
    const list = screen.getByRole('complementary', { name: 'Threads' })
    const listNames = within(list)
      .getAllByRole('listitem')
      .map((item) => item.textContent?.match(/(alpha|beta) thread/)?.[0])
    const canvasNames = within(screen.getByRole('grid'))
      .getAllByRole('rowheader')
      .map((item) => item.textContent)
    expect(listNames).toEqual(['alpha thread', 'beta thread'])
    expect(canvasNames).toEqual(listNames)
  })

  it('synchronizes selection when the route parameter changes without a remount', async () => {
    const user = userEvent.setup()
    mount(`/threads/${A.threadId}`, true)
    await screen.findByRole('gridcell', { name: /alpha thread, 2026-04-01/ })
    await user.click(screen.getByRole('button', { name: 'open beta route' }))
    const list = screen.getByRole('complementary', { name: 'Threads' })
    await waitFor(() =>
      expect(within(list).getByRole('button', { name: /beta thread/ }).closest('li')).toHaveAttribute(
        'aria-current',
        'true',
      ),
    )
  })
})
