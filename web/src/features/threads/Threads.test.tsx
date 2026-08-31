import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  CLUSTERED_MOMENTS,
  EVAL_HARNESS,
  EVAL_HARNESS_BANDS,
  MEETINGS,
  MOMENTS,
  RETRIEVAL_SPLIT,
  RETRIEVAL_SPLIT_BANDS,
  SCREEN_LINEAGE,
  SCREEN_LINEAGE_BANDS,
  THREADS,
} from './fixtures'
import { Threads } from './Threads'
import { xOf } from './timeline'

/**
 * The Threads screen over fixture data at every level — bands, meetings, and
 * moments — because story 10.3's api is being built in parallel and the
 * acceptance criteria ask for exactly this.
 */

const BANDS: Record<string, unknown> = {
  [RETRIEVAL_SPLIT.threadId]: RETRIEVAL_SPLIT_BANDS,
  [EVAL_HARNESS.threadId]: EVAL_HARNESS_BANDS,
  [SCREEN_LINEAGE.threadId]: SCREEN_LINEAGE_BANDS,
}

interface Served {
  threads?: unknown
  threadsStatus?: number
  moments?: unknown
  levelStatus?: Partial<Record<string, number>>
}

let served: Served = {}

function body(payload: unknown, status = 200) {
  return {
    ok: status < 400,
    status,
    statusText: status === 200 ? 'OK' : 'Error',
    text: async () => JSON.stringify(payload),
  } as unknown as Response
}

function answer(url: string, method = 'GET'): Response {
  if (method !== 'GET') {
    return body({
      threadId: EVAL_HARNESS.threadId,
      name: EVAL_HARNESS.name,
      derivedName: EVAL_HARNESS.name,
      nameIsCurated: false,
      colorOrdinal: EVAL_HARNESS.colorOrdinal,
      mergedIntoThreadId: null,
    })
  }
  if (url.endsWith('/threads')) {
    const status = served.threadsStatus ?? 200
    if (status !== 200) {
      return body({ title: 'threads unavailable', detail: 'the projection is rebuilding' }, status)
    }
    return body(served.threads ?? THREADS)
  }
  const match = /\/threads\/([^/?]+)\/timeline\?(.*)$/.exec(url)
  if (match === null) throw new Error(`unrouted fixture request: ${url}`)
  const threadId = decodeURIComponent(match[1])
  const level = new URLSearchParams(match[2]).get('level') ?? ''
  const status = served.levelStatus?.[level]
  if (status !== undefined) {
    return body({ title: 'threads: timeline unavailable', detail: `no ${level} for this window` }, status)
  }
  if (level === 'bands') return body({ buckets: BANDS[threadId] ?? [] })
  if (level === 'meetings') return body({ meetings: MEETINGS })
  if (level === 'moments') return body({ moments: served.moments ?? MOMENTS })
  throw new Error(`unrouted fixture level: ${level}`)
}

beforeEach(() => {
  served = {}
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
      Promise.resolve(answer(String(input), init?.method ?? 'GET')),
    ),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

function mount(at = '/threads') {
  return render(
    <MemoryRouter initialEntries={[at]}>
      <Routes>
        <Route path="/threads" element={<Threads />} />
        <Route path="/threads/:threadId" element={<Threads />} />
        <Route path="/moments/:momentId" element={<p>moment view</p>} />
      </Routes>
    </MemoryRouter>,
  )
}

const grid = () => screen.getByRole('grid')

/** The view the canvas is currently drawing, read off the grid. */
function viewOf() {
  const node = grid()
  return {
    from: Number(node.getAttribute('data-from')),
    scale: Number(node.getAttribute('data-scale')),
    tier: node.getAttribute('data-tier'),
  }
}

async function bandsTier() {
  mount()
  await screen.findByRole('grid', { name: /bands tier/i })
  // The bands level is debounced and fetched per thread; wait for the drawn
  // tier, not just the axis the canvas renders before any data arrives.
  await screen.findByRole('gridcell', { name: /^retrieval split, 2026-03-01/ })
}

async function meetingsTier(user: ReturnType<typeof userEvent.setup>) {
  await bandsTier()
  // 2026-03-15 to 2026-03-22 is retrieval split's densest early week.
  await user.click(screen.getByRole('gridcell', { name: /retrieval split, 2026-03-15/ }))
  await screen.findByRole('grid', { name: /meetings tier/i })
}

async function momentsTier(user: ReturnType<typeof userEvent.setup>) {
  await meetingsTier(user)
  await user.click(screen.getByRole('gridcell', { name: /^Embedding bake-off/ }))
  await screen.findByRole('grid', { name: /moments tier/i })
}

describe('the bands tier — how the screen opens', () => {
  it('opens zoomed out, every thread a band across the corpus span', async () => {
    await bandsTier()
    expect(viewOf().tier).toBe('bands')
    // Every thread has a row header on the canvas and a row in the list.
    for (const thread of THREADS) {
      expect(screen.getAllByText(thread.name).length).toBeGreaterThan(0)
    }
    expect(screen.getByRole('grid')).toHaveAttribute('aria-rowcount', String(THREADS.length))
  })

  it('names every bucket with its thread, its dates and its count', async () => {
    await bandsTier()
    expect(
      screen.getByRole('gridcell', { name: 'retrieval split, 2026-03-01 to 2026-03-08, 4 mentions' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('gridcell', { name: 'eval harness, 2026-03-08 to 2026-03-15, 3 mentions' }),
    ).toBeInTheDocument()
  })

  it('makes an empty bucket a span, never a target — nothing invented', async () => {
    await bandsTier()
    // retrieval split's second week has no mentions; it is drawn (the band keeps
    // its span) but it is not a cell and carries no label.
    expect(
      screen.queryByRole('gridcell', { name: /retrieval split, 2026-03-08.*0 mentions/ }),
    ).toBeNull()
    expect(screen.queryByRole('gridcell', { name: /0 mentions/ })).toBeNull()
  })

  it('colours a lap-2 thread from its ordinal and says so in the list', async () => {
    await bandsTier()
    const swatch = screen.getByTestId(`lap-swatch-${SCREEN_LINEAGE.threadId}`)
    expect(swatch).toHaveAttribute('data-lap', '2')
    expect(screen.getByTestId(`lap-swatch-${RETRIEVAL_SPLIT.threadId}`)).toHaveAttribute(
      'data-lap',
      '1',
    )
  })

  it('asks the api for the bands level, for the window on screen', async () => {
    await bandsTier()
    const urls = vi.mocked(fetch).mock.calls.map((call) => String(call[0]))
    expect(urls.some((u) => u.endsWith('/threads'))).toBe(true)
    expect(urls.filter((u) => u.includes('level=bands'))).toHaveLength(THREADS.length)
    const banded = urls.find((u) => u.includes('level=bands')) ?? ''
    expect(banded).toMatch(/from=.+&to=.+&level=bands/)
  })
})

describe('the list column', () => {
  it('invalidates timeline data after curation instead of leaving the corrected list on a stale canvas', async () => {
    const user = userEvent.setup()
    await bandsTier()
    const bandRequests = () =>
      vi.mocked(fetch).mock.calls.filter((call) => String(call[0]).includes('level=bands')).length
    const before = bandRequests()

    const list = screen.getByRole('complementary', { name: 'Threads' })
    await user.click(within(list).getAllByRole('button', { name: 'Merge into…' })[0])
    await user.selectOptions(
      within(list).getByRole('combobox', { name: /merge retrieval split into/i }),
      EVAL_HARNESS.threadId,
    )
    await user.click(within(list).getByRole('button', { name: 'Merge' }))

    await waitFor(() => expect(bandRequests()).toBeGreaterThan(before))
  })

  it('searches by name and says so when nothing matches', async () => {
    const user = userEvent.setup()
    await bandsTier()
    // Not "eval": "retrieval" contains it, and a substring search is meant to.
    await user.type(screen.getByLabelText('Search threads by name'), 'harness')
    const list = screen.getByRole('complementary', { name: 'Threads' })
    expect(within(list).getByText('eval harness')).toBeInTheDocument()
    expect(within(list).queryByText('retrieval split')).toBeNull()

    await user.clear(screen.getByLabelText('Search threads by name'))
    await user.type(screen.getByLabelText('Search threads by name'), 'publ')
    expect(screen.getByText('No threads match "publ".')).toBeInTheDocument()
    // The canvas keeps every band.
    expect(screen.getByRole('grid')).toHaveAttribute('aria-rowcount', String(THREADS.length))
  })

  it('sorts by activity and by recency', async () => {
    const user = userEvent.setup()
    await bandsTier()
    const list = screen.getByRole('complementary', { name: 'Threads' })
    const names = () =>
      within(list)
        .getAllByRole('button')
        .map((b) => b.textContent ?? '')
        .filter((t) => THREADS.some((thread) => t.includes(thread.name)))

    expect(names()[0]).toContain('retrieval split')
    await user.click(screen.getByRole('button', { name: 'recency' }))
    expect(screen.getByRole('button', { name: 'recency' })).toHaveAttribute('aria-pressed', 'true')
    // retrieval split's last mention (2026-08-21) is the most recent of the three.
    expect(names()[0]).toContain('retrieval split')
    expect(names()[names().length - 1]).toContain('screen lineage')
  })
})

describe('crossing the level-of-detail thresholds', () => {
  it('reveals meetings when a bucket is drilled, fetched at the meetings level', async () => {
    const user = userEvent.setup()
    await meetingsTier(user)
    expect(viewOf().tier).toBe('meetings')
    expect(
      screen.getByRole('gridcell', { name: 'Embedding bake-off, 2026-05-13, 11 mentions' }),
    ).toBeInTheDocument()
    expect(screen.getByText(/11 mentions/)).toBeInTheDocument()
    const urls = vi.mocked(fetch).mock.calls.map((call) => String(call[0]))
    expect(urls.some((u) => u.includes('level=meetings'))).toBe(true)
    // Only the entered thread is asked for — not all eleven bands.
    expect(urls.filter((u) => u.includes('level=meetings')).length).toBe(1)
  })

  it('reveals moments with their titles and speakers, fetched at the moments level', async () => {
    const user = userEvent.setup()
    await momentsTier(user)
    expect(viewOf().tier).toBe('moments')
    expect(screen.getByText('Why BM25 wins on reused wording')).toBeInTheDocument()
    expect(screen.getAllByText('Tim Goeke').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Priya Natarajan').length).toBeGreaterThan(0)
    // A moment whose speaker diarization has not produced a name says so
    // rather than borrowing one.
    expect(screen.getAllByText('speaker unknown').length).toBeGreaterThan(0)
    expect(
      vi
        .mocked(fetch)
        .mock.calls.map((c) => String(c[0]))
        .some((u) => u.includes('level=moments')),
    ).toBe(true)
  })

  it('clusters moments whose hit areas collide rather than dropping any', async () => {
    const user = userEvent.setup()
    served.moments = CLUSTERED_MOMENTS
    await meetingsTier(user)
    await user.click(screen.getByRole('gridcell', { name: /^Retrieval bake-off review/ }))
    await screen.findByRole('grid', { name: /moments tier/i })
    // The two are 32 seconds apart inside a window an hour wide: one cell,
    // named for both, that drills rather than hiding one of them.
    expect(screen.getByRole('gridcell', { name: /2 moments, 0:37:20 to 0:37:52/ })).toBeInTheDocument()
  })

  it('links a moment to the moment view', async () => {
    const user = userEvent.setup()
    await momentsTier(user)
    await user.click(screen.getByRole('gridcell', { name: /^Why BM25 wins on reused wording/ }))
    expect(await screen.findByText('moment view')).toBeInTheDocument()
  })
})

describe('no layout jump', () => {
  it('leaves the focused item at the same x after a threshold crossing', async () => {
    const user = userEvent.setup()
    await momentsTier(user)

    const cell = screen.getByRole('gridcell', { name: /^Why BM25 wins on reused wording/ })
    const t = Number(cell.getAttribute('data-t'))
    act(() => {
      cell.focus()
    })
    const before = viewOf()
    const x0 = xOf(t, before)
    expect(before.tier).toBe('moments')

    // Zoom out about the focused item until the moments/meetings threshold is
    // crossed. The tier redraws; the item the reader was looking at does not
    // move a pixel.
    for (let press = 0; press < 12; press += 1) await user.keyboard('-')

    const after = viewOf()
    expect(after.scale).toBeGreaterThanOrEqual(300_000)
    expect(xOf(t, after)).toBeCloseTo(x0, 6)

    await waitFor(() => expect(viewOf().tier).toBe('meetings'))
    // Still the same x once the incoming tier has actually been drawn.
    expect(xOf(t, viewOf())).toBeCloseTo(x0, 6)
  })

  it('keeps the outgoing tier drawn while the next one is being fetched', async () => {
    const user = userEvent.setup()
    await meetingsTier(user)
    // Hold the moments level back; the meetings tier must stay on screen.
    served.levelStatus = { moments: 503 }
    await user.click(screen.getByRole('gridcell', { name: /^Embedding bake-off/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/timeline unavailable/)
    expect(screen.getByRole('grid', { name: /meetings tier/i })).toBeInTheDocument()
    expect(screen.getByRole('gridcell', { name: /^Embedding bake-off/ })).toBeInTheDocument()
  })
})

describe('refusals', () => {
  it('shows the api its own words when the thread list refuses, with a Retry', async () => {
    served.threadsStatus = 503
    mount()
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('threads unavailable: the projection is rebuilding')
    expect(within(alert).getByRole('button', { name: 'Retry' })).toBeInTheDocument()
  })

  it('says the corpus has no threads yet in the words the state pattern fixes', async () => {
    served.threads = []
    mount()
    expect(await screen.findByText(/No threads yet\./)).toBeInTheDocument()
  })

  it('names the address when the api cannot be reached at all', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.reject(new Error('fetch failed'))),
    )
    mount()
    expect(await screen.findByRole('alert')).toHaveTextContent(/Cannot reach the api at .*fetch failed/)
    expect(screen.getByText(/start the api/)).toBeInTheDocument()
  })
})

describe('the timeline controls', () => {
  it('offers zoom, fit and pan without a wheel or a drag, each naming its key', async () => {
    await bandsTier()
    for (const name of [
      'Zoom out (−)',
      'Zoom in (+)',
      'Fit (Home)',
      'Pan left (Shift+←)',
      'Pan right (Shift+→)',
    ]) {
      expect(screen.getByRole('button', { name })).toBeInTheDocument()
    }
  })

  it('pans without changing the scale, and Fit returns to the corpus span', async () => {
    const user = userEvent.setup()
    await bandsTier()
    const opening = viewOf()
    await user.click(screen.getByRole('button', { name: 'Pan right (Shift+→)' }))
    expect(viewOf().from).toBeGreaterThan(opening.from)
    expect(viewOf().scale).toBe(opening.scale)
    await user.click(screen.getByRole('button', { name: 'Fit (Home)' }))
    expect(viewOf().from).toBeCloseTo(opening.from, 6)
    expect(viewOf().scale).toBeCloseTo(opening.scale, 6)
  })
})

describe('the deep link every thread chip points at', () => {
  it('opens /threads/:threadId with that thread already entered', async () => {
    mount(`/threads/${RETRIEVAL_SPLIT.threadId}`)
    await screen.findByRole('gridcell', { name: /^retrieval split, 2026-03-01/ })
    const list = screen.getByRole('complementary', { name: 'Threads' })
    const entered = within(list)
      .getAllByRole('listitem')
      .find((li) => li.getAttribute('aria-current') === 'true')
    expect(entered).toBeDefined()
    expect(entered?.textContent).toContain('retrieval split')
  })

  it('says so when the id resolves to nothing, and offers the way back', async () => {
    mount('/threads/th-merged-away')
    expect(
      await screen.findByText(/No thread has this id — it may have been merged away\./),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'All threads' })).toHaveAttribute('href', '/threads')
  })
})
