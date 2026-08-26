import { useCallback, useEffect, useRef, useState } from 'react'
import {
  BrowserRouter,
  Link,
  Outlet,
  matchPath,
  useLocation,
  useNavigate,
  useRoutes,
} from 'react-router'
import { getHealth } from '@/client/sdk.gen'
import type { HealthResponse } from '@/client/types.gen'
import { Button } from '@/components/ui/button'
import { ChatPanel } from '@/features/chat/ChatPanel'
import { CorpusStats } from '@/features/home/CorpusStats'
import { MeetingsList } from '@/features/meetings/MeetingsList'
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

/**
 * The layout route: shell plus home content, with every other screen a
 * discovered child rendered in `<Outlet />` (story 2.8). Screens are
 * `*.route.tsx` files beside their components — see `routes/registry.ts` —
 * so adding a screen no longer edits this file. Navigation is browser
 * history: the old hand-rolled view stack became real history entries, and
 * Back is `navigate(-1)` with a home fallback for deep links.
 */
function Shell() {
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const openPath = useOpenPath()
  // A child screen is open when a discovered route matches. The unknown-path
  // catch-all is deliberately not a discovered route, so a stray URL shows
  // home rather than a blank shell with a Back control.
  const childOpen = childRoutes.some((route) => matchPath(route.path, pathname) !== null)

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
    <main className="mx-auto flex min-h-screen max-w-5xl flex-col gap-8 p-8">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-wrap items-baseline gap-6">
          <h1 className="text-3xl font-semibold tracking-tight">MeetingMiner</h1>
          {/* SPEC-ui-reimagine CAP-1 chrome: the standing destinations, on
              every screen. `/settings` is story ui-4's configuration page —
              the link target is part of this chrome either way, and until
              that route lands the unknown-path catch-all shows home. */}
          <nav aria-label="Primary" className="flex items-center gap-4 text-sm text-muted-foreground">
            <Link to="/" className="hover:text-foreground">
              Home
            </Link>
            <Link to="/status" className="hover:text-foreground">
              Status
            </Link>
            <Link to="/settings" className="hover:text-foreground">
              Settings
            </Link>
          </nav>
        </div>
        {/* SPEC-system-status CAP-1: the persistent health indicator lives in
            the chrome, outside the hidden-on-child-screens home block, so it
            is visible on every screen and polls for the whole session. */}
        <StatusIndicator />
      </div>
      {childOpen && (
        <div>
          <Button size="sm" variant="outline" onClick={back}>
            ← Back
          </Button>
        </div>
      )}
      {/* The open child screen sits ABOVE the persistent search/ask chrome
          (2026-08-22 hot fix). It used to render in the last `<Outlet />`,
          after that chrome — and the chrome stays mounted on purpose so Back
          returns to the same result list. A full page of hits is taller than
          the viewport, so the opened moment landed ~4000px down a ~5000px
          document, where the browser cannot even scroll it to the top, and
          the click read as "Open moment does nothing". Replay looked fine
          throughout because its player opens inline beside the clicked hit,
          which is why only one of the two buttons appeared broken.

          Same remedy as `spec-meeting-artifacts-below-fold`: fix document
          order rather than chase it with scrolling, so DOM order (and
          therefore tab order and screen-reader linearization) matches what
          the eye should reach first. `hidden` rather than unmounting keeps
          `main`'s `gap-8` from opening a stray gap on home, and a
          display:none flex child takes part in neither layout nor gap. */}
      <div ref={childRef} hidden={!childOpen}>
        <Outlet />
      </div>
      {/* Persistent chrome, not home panels (SPEC-ui-reimagine CAP-1): search
          and ask-the-corpus stand on every route. Always mounted for the same
          reason home is hidden rather than unmounted — the verify-a-claim
          loop is search → moment → back → next hit, and unmounting would
          blank the query and results on every navigation. Search first:
          search answers "where was this discussed", chat answers a cited
          question over that same corpus (FR12, FR15, UX-DR3, UX-DR10); both
          open a citation's moment view by `momentId` alone. */}
      <div className="grid gap-8 lg:grid-cols-2">
        <CorpusSearch onOpenMoment={(momentId) => openPath(`/moments/${momentId}`)} />
        <ChatPanel onOpenMoment={(momentId) => openPath(`/moments/${momentId}`)} />
      </div>
      {/* Hidden, never unmounted, while a meeting or moment is open: the
          meetings stream stays subscribed and the list keeps its rows, so
          Back never re-seeds. This is why home lives in the layout route
          rather than being a discovered child — a `<Routes>` swap would
          unmount it. */}
      <div hidden={childOpen} className="flex flex-col gap-8">
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
        <div className="flex justify-end">
          {/* Story 2.4's one entry point into the curation screen — the
              spec's only App.tsx edit. */}
          <Button size="sm" variant="outline" onClick={() => openPath('/participants')}>
            Participants
          </Button>
        </div>
        <HealthPanel />
      </div>
    </main>
  )
}

function AppRoutes() {
  return useRoutes([
    {
      path: '/',
      element: <Shell />,
      children: [
        ...childRoutes.map(({ path, element }) => ({ path, element })),
        // Unknown path: render the shell with home visible, never a blank
        // screen or an error page.
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
