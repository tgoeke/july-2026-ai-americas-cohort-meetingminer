import { useCallback, useEffect, useRef, useState } from 'react'
import {
  BrowserRouter,
  Link,
  NavLink,
  Outlet,
  matchPath,
  useLocation,
  useNavigate,
  useRoutes,
} from 'react-router'
import { getHealth } from '@/client/sdk.gen'
import type { HealthResponse } from '@/client/types.gen'
import { Button, buttonVariants } from '@/components/ui/button'
import { ChatPanel } from '@/features/chat/ChatPanel'
import { CorpusStats } from '@/features/home/CorpusStats'
import { MeetingsList } from '@/features/meetings/MeetingsList'
import { MomentsFeed } from '@/features/moments/MomentsFeed'
import { CorpusSearch } from '@/features/search/CorpusSearch'
import { StatusIndicator } from '@/features/status/StatusIndicator'
import { API_BASE } from '@/lib/api'
import { useOpenPath } from '@/routes/navigation'
import { childRoutes } from '@/routes/registry'

const REQUEST_TIMEOUT_MS = 5000

type HealthState =
  | { kind: 'loading' }
  | { kind: 'ok'; health: HealthResponse }
  | { kind: 'error'; message: string }

/**
 * The health panel stays, subordinate to the meetings list: it is still the
 * fastest "is my environment up" signal during development, and it answers a
 * different question than the stream does.
 */
function HealthPanel() {
  const [state, setState] = useState<HealthState>({ kind: 'loading' })
  // Held across renders so a re-click aborts the in-flight check before
  // starting a new one — an older response must never overwrite a newer
  // result (story 1.10, finding 22).
  const controllerRef = useRef<AbortController | null>(null)

  const check = useCallback(async () => {
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller
    const timeout = AbortSignal.timeout(REQUEST_TIMEOUT_MS)
    const signal = AbortSignal.any([controller.signal, timeout])
    setState({ kind: 'loading' })
    try {
      const { data, error } = await getHealth({ signal })
      if (controller.signal.aborted) return
      if (error !== undefined || data === undefined) {
        throw new Error(`api returned an error response: ${JSON.stringify(error)}`)
      }
      setState({ kind: 'ok', health: data })
    } catch (err) {
      // Superseded (re-click) or unmounted: never set state for a stale check.
      if (controller.signal.aborted) return
      const message = timeout.aborted
        ? `timed out after ${REQUEST_TIMEOUT_MS}ms`
        : err instanceof Error
          ? err.message
          : String(err)
      setState({ kind: 'error', message })
    }
  }, [])

  useEffect(() => {
    void check()
    return () => controllerRef.current?.abort()
  }, [check])

  return (
    <aside className="flex flex-col gap-3 rounded-lg border p-4">
      <div className="flex items-baseline justify-between gap-4">
        <h2 className="text-sm font-medium text-muted-foreground">api /health</h2>
        <Button size="sm" variant="outline" onClick={() => void check()}>
          Re-check
        </Button>
      </div>
      {state.kind === 'loading' && <p className="text-sm">checking…</p>}
      {state.kind === 'ok' && (
        <dl className="grid grid-cols-2 gap-1 text-sm">
          <dt className="text-muted-foreground">status</dt>
          <dd>{state.health.status}</dd>
          <dt className="text-muted-foreground">service</dt>
          <dd>{state.health.service}</dd>
          <dt className="text-muted-foreground">configVersion</dt>
          <dd>{state.health.configVersion}</dd>
        </dl>
      )}
      {state.kind === 'error' && (
        <p className="text-sm text-destructive">
          cannot reach the api at {API_BASE}: {state.message}
        </p>
      )}
    </aside>
  )
}

/** The standing destinations, in the order EXPERIENCE.md · Chrome states.
 * Moments is the front door and Threads the second primary view; the four
 * screens that existed before stay reachable from the same row. */
const PRIMARY_NAV = [
  { to: '/', label: 'Moments', end: true },
  { to: '/threads', label: 'Threads', end: false },
  { to: '/meetings', label: 'Meetings', end: true },
  { to: '/participants', label: 'Participants', end: false },
  { to: '/status', label: 'Status', end: false },
  { to: '/settings', label: 'Settings', end: false },
] as const

/**
 * The layout route: the persistent chrome, with every screen either a
 * discovered child in `<Outlet />` (story 2.8) or one of the two views the
 * shell itself composes.
 *
 * Story 10.5 recomposed the front door. `/` is **Moments** — the ranked feed,
 * the first thing the app shows — and `/threads` is the second primary view.
 * The reimagined home did not go anywhere: its corpus counts, meeting cards
 * and health panel moved to **`/meetings`**, whole and unchanged inside, and
 * the chrome links to it. Both views live in this layout route rather than
 * being discovered children for the reason home always did: a `<Routes>` swap
 * would unmount them, and the meetings stream must stay subscribed and the
 * feed must keep its page across a moment opened out of it.
 *
 * Adding a *screen* is still adding a `*.route.tsx` file; this file changes
 * only when the front door itself is recomposed.
 */
function Shell() {
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const openPath = useOpenPath()
  // A child screen is open when a discovered route matches. The unknown-path
  // catch-all is deliberately not a discovered route, so a stray URL shows the
  // front door rather than a blank shell with a Back control.
  const childOpen = childRoutes.some((route) => matchPath(route.path, pathname) !== null)
  // The two views this layout composes. `/meetings` is not a discovered route
  // (`/meetings/:meetingId` is), so it falls to the shell; every remaining
  // path — `/` and anything unknown — is the front door.
  const meetingsOpen = !childOpen && matchPath('/meetings', pathname) !== null
  const momentsOpen = !childOpen && !meetingsOpen

  // Dark is the only mode (DESIGN.md · Colors): the app's `.dark` tokens
  // exist but were never applied, so every screen rendered light. The shell
  // applies the class once, at the root, and `index.html` carries it too so
  // the first paint is already dark.
  useEffect(() => {
    document.documentElement.classList.add('dark')
  }, [])

  // The child screen is placed above the chrome (see the `<Outlet />` block
  // below), which is what actually fixes "Open moment does nothing". This
  // scroll covers the other half of the same gesture: the hit that was
  // clicked may sit hundreds of pixels down the result list, so opening it
  // must also return the reader to the top where the child now renders,
  // rather than leaving them parked at the old offset staring at more hits.
  //
  // Keyed on `pathname` as well as `childOpen` so moving from one screen
  // straight to another — a citation, a second hit — scrolls again instead of
  // only firing on the first open. `scrollIntoView` is optional-called for
  // the same reason `MeetingMoments.tsx` optional-calls it: jsdom implements
  // neither it nor `scrollTo`, and the component suite renders there.
  const childRef = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    if (!childOpen) return
    childRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })
  }, [childOpen, pathname])

  const back = useCallback(() => {
    // A deep link opens a child screen with no in-app entry beneath it, so
    // navigate(-1) would do nothing or leave the site. The old hand-rolled
    // stack always had home at the bottom; the router's history index
    // (react-router keeps `idx` in history.state) restores that floor.
    const idx = (window.history.state as { idx?: number } | null)?.idx ?? 0
    if (idx > 0) void navigate(-1)
    else void navigate('/', { replace: true })
  }, [navigate])

  return (
    <div className="flex min-h-screen flex-col">
      {/* SPEC-ui-reimagine CAP-1 chrome, recomposed by story 10.5: the brand,
          the standing destinations, the one primary action, and the health
          indicator, sticky at the top of every screen. */}
      <header className="sticky top-0 z-20 border-b border-border bg-background">
        <div className="mx-auto flex w-full max-w-[1600px] flex-wrap items-center gap-x-6 gap-y-2 px-8 py-3">
          <span className="text-lg font-semibold tracking-tight">MeetingMiner</span>
          <nav aria-label="Primary" className="flex flex-wrap items-center gap-4 text-sm">
            {PRIMARY_NAV.map((entry) => (
              <NavLink
                key={entry.to}
                to={entry.to}
                end={entry.end}
                className={({ isActive }) =>
                  isActive
                    ? 'border-b-2 border-primary pb-0.5 font-medium text-foreground'
                    : 'pb-0.5 text-muted-foreground hover:text-foreground'
                }
              >
                {entry.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-4">
            {/* Story 6.5's Add-meeting flow at `/add`. The chrome carries the
                link before that route lands, exactly as it carried
                `/settings` before story ui-4 — until then the unknown-path
                catch-all shows the front door. */}
            <Link
              to="/add"
              className={buttonVariants({ variant: 'default', size: 'sm' })}
            >
              Add meeting
            </Link>
            {/* SPEC-system-status CAP-1: the persistent health indicator lives
                in the chrome, outside the view blocks, so it is visible on
                every screen and polls for the whole session. */}
            <StatusIndicator />
          </div>
        </div>
      </header>
      <main className="mx-auto flex w-full max-w-[1600px] flex-1 flex-col gap-8 p-8">
        {childOpen && (
          <div>
            <Button size="sm" variant="outline" onClick={back}>
              ← Back
            </Button>
          </div>
        )}
        {/* The open child screen sits ABOVE the persistent search/ask chrome
            (2026-08-22 hot fix; pinned by `shellPlacement.test.tsx`, backlog
            B-13). It used to render in the last `<Outlet />`, after that
            chrome — and the chrome stays mounted on purpose so Back returns
            to the same result list. A full page of hits is taller than the
            viewport, so the opened moment landed ~4000px down a ~5000px
            document, where the browser cannot even scroll it to the top, and
            the click read as "Open moment does nothing". Replay looked fine
            throughout because its player opens inline beside the clicked hit,
            which is why only one of the two buttons appeared broken.

            Same remedy as `spec-meeting-artifacts-below-fold`: fix document
            order rather than chase it with scrolling, so DOM order (and
            therefore tab order and screen-reader linearization) matches what
            the eye should reach first. `hidden` rather than unmounting keeps
            `main`'s `gap-8` from opening a stray gap, and a display:none flex
            child takes part in neither layout nor gap.

            Child screens render at the reading width, not the shell's: they
            are columns of prose and evidence, not ranked grids
            (DESIGN.md · Layout & Spacing). */}
        <div
          ref={childRef}
          data-testid="child-screen"
          hidden={!childOpen}
          className="mx-auto w-full max-w-5xl"
        >
          <Outlet />
        </div>
        {/* Persistent chrome, not view panels (SPEC-ui-reimagine CAP-1):
            search and ask-the-corpus stand on every route. Always mounted for
            the same reason the views are hidden rather than unmounted — the
            verify-a-claim loop is search → moment → back → next hit, and
            unmounting would blank the query and results on every navigation.
            Search first: search answers "where was this discussed", chat
            answers a cited question over that same corpus (FR12, FR15,
            UX-DR3, UX-DR10); both open a citation's moment view by
            `momentId` alone. */}
        <div data-testid="search-ask-chrome" className="grid gap-8 lg:grid-cols-2">
          <CorpusSearch onOpenMoment={(momentId) => openPath(`/moments/${momentId}`)} />
          <ChatPanel onOpenMoment={(momentId) => openPath(`/moments/${momentId}`)} />
        </div>
        {/* The front door (story 10.5): the ranked feed, hidden but never
            unmounted while a moment opened out of it is on screen, so Back
            lands on the same page of cards rather than re-ranking. */}
        <div hidden={!momentsOpen}>
          <MomentsFeed
            onOpenMoment={(momentId) => openPath(`/moments/${momentId}`)}
            onOpenMeeting={(meetingId) => openPath(`/meetings/${meetingId}`)}
            onOpenThread={(threadId) => openPath(`/threads/${threadId}`)}
          />
        </div>
        {/* The reimagined home, relocated to `/meetings` whole: the corpus
            counts, the live meeting cards, and the health panel. Hidden,
            never unmounted, so the meetings stream stays subscribed and the
            list keeps its rows across a meeting opened out of it. */}
        <div hidden={!meetingsOpen} className="flex flex-col gap-8">
          {/* The corpus's scale, before its contents: CAP-1's one-screen
              answer to "how much evidence does this corpus hold". */}
          <CorpusStats />
          <MeetingsList
            onOpen={(row) => {
              // `meetingId` is null until the worker mints the meeting row; a
              // viewable row always has one, but the type does not know that.
              if (row.meetingId != null) openPath(`/meetings/${row.meetingId}`)
            }}
          />
          <HealthPanel />
        </div>
      </main>
    </div>
  )
}

function AppRoutes() {
  return useRoutes([
    {
      path: '/',
      element: <Shell />,
      children: [
        ...childRoutes.map(({ path, element }) => ({ path, element })),
        // Unknown path: render the shell with the front door visible, never a
        // blank screen or an error page.
        { path: '*', element: null },
      ],
    },
  ])
}

function App() {
  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  )
}

export default App
