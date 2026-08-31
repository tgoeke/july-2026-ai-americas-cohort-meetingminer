import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { childRoutes } from './routes/registry'

/**
 * The shell's composition, pinned (story 10.5; closes backlog B-13).
 *
 * Two invariants live here, and both are one careless edit away from silently
 * regressing:
 *
 * 1. **Search and Ask are controls inside the sticky chrome, and the child
 *    screen is the first flow-height content below it.** Their expanded
 *    surfaces overlay rather than pushing an opened moment thousands of
 *    pixels down the document. The assertion runs over `childRoutes` rather
 *    than a hand-written list, so a screen added later is covered immediately.
 *
 * 2. **The front door is Moments, Threads is second, and the four screens
 *    that came before stay reachable from the chrome** — with search and ask
 *    standing on every route, and the corpus counts and meeting cards of the
 *    reimagined home still reachable at `/meetings`.
 *
 * B-13 named the cost of covering this — mocking the whole generated client
 * surface plus every child route's reads — and that is what the factory below
 * is. Every child screen's fetch is answered with something inert, because
 * this file asserts *placement*, never a screen's contents.
 */

const sdk = vi.hoisted(() => ({
  getHealth: vi.fn(),
  listMeetings: vi.fn(),
  streamJobEvents: vi.fn(),
  getMeetingDrilldown: vi.fn(),
  getMoment: vi.fn(),
  listMeetingMoments: vi.fn(),
  listParticipants: vi.fn(),
  getCorpusStats: vi.fn(),
  getConfiguration: vi.fn(),
}))

vi.mock('@/client/sdk.gen', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/client/sdk.gen')>()),
  getHealth: sdk.getHealth,
  listMeetings: sdk.listMeetings,
  streamJobEvents: sdk.streamJobEvents,
  searchCorpus: vi.fn(() => Promise.reject(new Error('no api in this test'))),
  getMeetingDrilldown: sdk.getMeetingDrilldown,
  listMeetingMoments: sdk.listMeetingMoments,
  getMoment: sdk.getMoment,
  getJob: vi.fn(() => Promise.reject(new Error('no api in this test'))),
  createIngest: vi.fn(() => Promise.reject(new Error('no api in this test'))),
  getRecording: vi.fn(() => Promise.reject(new Error('no api in this test'))),
  getMediaFile: vi.fn(() => Promise.reject(new Error('no api in this test'))),
  listParticipants: sdk.listParticipants,
  renameParticipant: vi.fn(() => Promise.reject(new Error('no api in this test'))),
  mergeParticipants: vi.fn(() => Promise.reject(new Error('no api in this test'))),
  askCorpus: vi.fn(() => Promise.reject(new Error('no api in this test'))),
  approveMomentArtifacts: vi.fn(() => Promise.reject(new Error('no api in this test'))),
  getExtractionPrompts: vi.fn(() => Promise.reject(new Error('no api in this test'))),
  getCorpusStats: sdk.getCorpusStats,
  getSystemStatus: vi.fn(() => Promise.reject(new Error('no api in this test'))),
  getConfiguration: sdk.getConfiguration,
}))

/** A concrete url for a route pattern: `:param` gets a fixture id, a trailing
 * splat gets nothing. Derived from the pattern so a new screen needs no edit
 * here. */
function concretePath(pattern: string): string {
  const path = pattern
    .split('/')
    .map((segment) => (segment.startsWith(':') ? `${segment.slice(1)}-1` : segment))
    .join('/')
    .replace(/\/\*$/, '')
  return path === '' ? '/' : path
}

beforeEach(() => {
  window.history.replaceState(null, '', '/')
  document.documentElement.classList.remove('dark')
  for (const mock of Object.values(sdk)) mock.mockReset()
  sdk.getHealth.mockRejectedValue(new Error('no api in this test'))
  sdk.listMeetings.mockResolvedValue({ data: { meetings: [] }, error: undefined })
  sdk.streamJobEvents.mockRejectedValue(new Error('no api in this test'))
  sdk.getMeetingDrilldown.mockRejectedValue(new Error('no api in this test'))
  sdk.getMoment.mockRejectedValue(new Error('no api in this test'))
  sdk.listMeetingMoments.mockRejectedValue(new Error('no api in this test'))
  sdk.listParticipants.mockResolvedValue({ data: [], error: undefined })
  sdk.getCorpusStats.mockRejectedValue(new Error('no api in this test'))
  sdk.getConfiguration.mockRejectedValue(new Error('no api in this test'))
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => {
      const path = new URL(input instanceof Request ? input.url : String(input)).pathname
      if (path.endsWith('/moments/feed')) {
        return Promise.resolve(
          new Response(JSON.stringify({ items: [], total: 0, corpusTotal: 0, limit: 24, offset: 0 }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          }),
        )
      }
      if (path.endsWith('/threads')) {
        return Promise.resolve(
          new Response(JSON.stringify({ threads: [] }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          }),
        )
      }
      return Promise.reject(new Error('no api in this test'))
    }),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('shell placement', () => {
  it('discovers at least the front door, Threads, and the screens that came before', () => {
    // A floor, not an equality: another lane adding a screen must not fail
    // this file. Threads is story 10.6's real screen; 10.5's placeholder
    // was deleted at integration once that landed.
    const paths = childRoutes.map((route) => route.path)
    expect(paths).toContain('/threads')
    expect(paths).toContain('/moments/:momentId')
    expect(paths).toContain('/meetings/:meetingId')
    expect(paths).toContain('/participants')
    expect(paths).toContain('/status')
    expect(paths).toContain('/settings')
  })

  it.each(childRoutes.map((route) => route.path))(
    'renders %s beside the standing search and ask controls',
    (pattern) => {
      window.history.replaceState(null, '', concretePath(pattern))
      render(<App />)

      const child = screen.getByTestId('child-screen')
      const chrome = screen.getByTestId('search-ask-chrome')
      const rail = chrome.closest('aside')
      // The child screen is open…
      expect(child).not.toHaveAttribute('hidden')
      // …and the controls live in their own rail rather than in a
      // flow-height block between Back and Outlet.
      //
      // Owner revision 2026-08-31: they used to sit inside the sticky header
      // (story 10.5's F10 ruling). On a wide display the rail is a left column
      // beside the content and the header keeps the nav; below the breakpoint
      // it is the same short strip. What B-13 actually forbids — a growing
      // block that pushes the opened screen down — is unchanged, because the
      // results still expand as overlays.
      expect(rail).not.toBeNull()
      expect(rail).toHaveClass('min-[1400px]:sticky')
      expect(rail).toContainElement(screen.getByTestId('search-input'))
      expect(rail).toContainElement(screen.getByTestId('chat-question-input'))
      expect(child.compareDocumentPosition(chrome)).toBe(Node.DOCUMENT_POSITION_PRECEDING)
      // The Back control belongs to an open child screen.
      expect(child.previousElementSibling).toHaveTextContent('← Back')
    },
  )

  it('keeps the hidden child container directly below the chrome on the front door too', () => {
    render(<App />)

    const child = screen.getByTestId('child-screen')
    const chrome = screen.getByTestId('search-ask-chrome')
    // Hidden, because no child screen matched — but still after the sticky
    // chrome and before the composed primary views.
    expect(child).toHaveAttribute('hidden')
    expect(child.compareDocumentPosition(chrome)).toBe(Node.DOCUMENT_POSITION_PRECEDING)
    expect(screen.queryByRole('button', { name: '← Back' })).toBeNull()
  })
})

describe('front door', () => {
  it('opens on Moments', async () => {
    render(<App />)

    expect(await screen.findByRole('region', { name: 'Moments' })).toBeInTheDocument()
    // The relocated home is not what greets the reader.
    expect(screen.queryByRole('heading', { name: 'Meetings' })).toBeNull()
  })

  it('puts Threads second in the primary nav, before the screens that came before', () => {
    render(<App />)

    const nav = screen.getByRole('navigation', { name: 'Primary' })
    const labels = Array.from(nav.querySelectorAll('a')).map((link) => link.textContent)
    expect(labels).toEqual([
      'Moments',
      'Threads',
      'Meetings',
      'Participants',
      'Status',
      'Settings',
    ])
  })

  it('marks the current view in the nav', async () => {
    render(<App />)
    expect(screen.getByRole('link', { name: 'Moments' })).toHaveAttribute('aria-current', 'page')

    window.history.replaceState(null, '', '/status')
    render(<App />)
    const status = screen.getAllByRole('link', { name: 'Status' })
    expect(status.some((link) => link.getAttribute('aria-current') === 'page')).toBe(true)
  })

  it('keeps search, ask and Add meeting standing on every route', () => {
    for (const path of ['/', '/meetings', '/threads', '/status', '/moments/moment-1']) {
      window.history.replaceState(null, '', path)
      const view = render(<App />)
      expect(screen.getByTestId('search-input')).toBeInTheDocument()
      expect(screen.getByTestId('chat-question-input')).toBeInTheDocument()
      expect(screen.getByRole('link', { name: 'Add meeting' })).toHaveAttribute('href', '/add')
      view.unmount()
    }
  })

  it('resolves the Threads route to the Threads screen rather than the catch-all', async () => {
    window.history.replaceState(null, '', '/threads')
    render(<App />)

    expect(
      await screen.findByRole('heading', { name: 'Threads', level: 1 }),
    ).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Moments' })).toBeNull()
  })

  it('resolves a thread deep link to the same route', async () => {
    window.history.replaceState(null, '', '/threads/thread-1')
    render(<App />)

    expect(
      await screen.findByRole('heading', { name: 'Threads', level: 1 }),
    ).toBeInTheDocument()
  })

  it('keeps the corpus counts and meeting cards reachable at /meetings', async () => {
    window.history.replaceState(null, '', '/meetings')
    render(<App />)

    // The reimagined home, whole: counts, the meetings list, and the health
    // panel that answers "is my environment up".
    expect(await screen.findByRole('heading', { name: 'Meetings' })).toBeInTheDocument()
    expect(screen.getByTestId('corpus-stats')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'api /health' })).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Moments' })).toBeNull()
  })

  it('applies the dark theme class at the root', () => {
    expect(document.documentElement.classList.contains('dark')).toBe(false)
    render(<App />)
    // Dark is the only mode; the tokens exist but were never applied before.
    expect(document.documentElement.classList.contains('dark')).toBe(true)
  })
})
