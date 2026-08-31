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
import { areSingleKeyShortcutsEnabled } from '@/features/settings/singleKeyShortcuts'
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
  const chordArmed = useRef(false)
  // A child screen is open when a discovered route matches. The unknown-path
  // catch-all is deliberately not a discovered route, so a stray URL shows the
  // front door rather than a blank shell with a Back control.
  const childOpen = childRoutes.some((route) => matchPath(route.path, pathname) !== null)
  // The two views this layout composes. `/meetings` is not a discovered route
  // (`/meetings/:meetingId` is), so it falls to the shell; every remaining
  // path — `/` and anything unknown — is the front door.
  const meetingsOpen = !childOpen && matchPath('/meetings', pathname) !== null
  const momentsOpen = !childOpen && !meetingsOpen
  // The traced-thread timeline is a map, and a map wants the whole width.
  // On this one route the Search/Ask rail collapses back to the horizontal
  // strip it is below the breakpoint — still standing on every route, as
  // story 10.5's ruling requires, but not taking 24rem from the screen the
  // timeline needs most.
  const wideCanvas = matchPath('/threads', pathname) !== null
    || matchPath('/threads/*', pathname) !== null
  const [expandedChrome, setExpandedChrome] = useState<'search' | 'ask' | null>(null)

  // Dark is the only mode (DESIGN.md · Colors): the app's `.dark` tokens
  // exist but were never applied, so every screen rendered light. The shell
  // applies the class once, at the root, and `index.html` carries it too so
  // the first paint is already dark.
  useEffect(() => {
    document.documentElement.classList.add('dark')
  }, [])

  useEffect(() => {
    setExpandedChrome(null)
    chordArmed.current = false
  }, [pathname])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && expandedChrome !== null) {
        event.preventDefault()
        setExpandedChrome(null)
        chordArmed.current = false
        if (document.activeElement instanceof HTMLElement) document.activeElement.blur()
        return
      }
      const target = event.target
      const editable =
        target instanceof HTMLElement &&
        (target.matches('input, textarea, select') || target.isContentEditable)
      if (
        !areSingleKeyShortcutsEnabled() ||
        editable ||
        event.defaultPrevented ||
        event.repeat ||
        event.metaKey ||
        event.ctrlKey ||
        event.altKey
      ) {
        chordArmed.current = false
        return
      }

      const key = event.key.toLocaleLowerCase()
      if (chordArmed.current) {
        chordArmed.current = false
        const destination = key === 'm' ? '/' : key === 't' ? '/threads' : key === 'e' ? '/meetings' : null
        if (destination !== null) {
          event.preventDefault()
          void navigate(destination)
        }
        return
      }
      if (key === 'g') {
        chordArmed.current = true
      } else if (key === '/') {
        event.preventDefault()
        document.querySelector<HTMLInputElement>('[data-testid="search-input"]')?.focus()
      } else if (key === 'a') {
        event.preventDefault()
        document.querySelector<HTMLTextAreaElement>('[data-testid="chat-question-input"]')?.focus()
      } else if (key === 'n') {
        event.preventDefault()
        void navigate('/add')
      }
    }
    const cancelChord = () => {
      chordArmed.current = false
    }
    window.addEventListener('keydown', onKey)
    window.addEventListener('pointerdown', cancelChord)
    window.addEventListener('blur', cancelChord)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('pointerdown', cancelChord)
      window.removeEventListener('blur', cancelChord)
    }
  }, [expandedChrome, navigate])

  // The child screen is the first flow-height content below the compact
  // sticky chrome. This scroll covers the other half of the same gesture: the hit that was
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
      {/* The corpus metrics ride in the chrome, small, the way the prototype
          carries them — "240 meetings · 10,173 passages · …" beside the brand.
          They answer "how much evidence is in here" without taking a slab of
          the screen before the reader has looked at anything. */}
      {/* Column on a normal display, two columns on a wide one: the chrome
          becomes a left rail so Search and Ask stand beside the content
          instead of above it (owner request, for a full-screen 32" demo).
          The DOM order is unchanged — only the axis — so the chrome keeps the
          placement `chromeSearchAsk.ruling.test.tsx` pins. */}
      {/* SPEC-ui-reimagine CAP-1 chrome, recomposed by story 10.5: the brand,
          the standing destinations, the one primary action, and the health
          indicator, sticky at the top of every screen. */}
      <header className="sticky top-0 z-20 border-b border-border bg-background">
        <div className="mx-auto flex min-h-14 w-full max-w-[1600px] flex-wrap items-center gap-3 px-4 py-2 min-[1200px]:h-14 min-[1200px]:flex-nowrap min-[1200px]:px-8 min-[1200px]:py-0">
          <span className="text-lg font-semibold tracking-tight">MeetingMiner</span>
          <nav aria-label="Primary" className="flex flex-wrap items-center gap-3 text-sm min-[1200px]:flex-nowrap">
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
          <div className="flex shrink-0 items-center gap-3">
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
          <div
            data-testid="corpus-stats-banner"
            className="order-last w-full min-[1200px]:order-none min-[1200px]:w-auto"
          >
            <CorpusStats compact />
          </div>
        </div>
      </header>
      {/* Owner request 2026-08-31, for a full-screen 32" demo: on a wide
          display Search and Ask stand in a left column and the content takes
          the rest, instead of both stacking down a narrow centre column. The
          nav stays where it was, in the horizontal bar above. Below the
          breakpoint this is the same one-line pair under the chrome that
          story 10.5 landed. */}
      {/* One column, always. An earlier revision made Search and Ask a 24rem
          left rail on a wide display; the owner rejected it against the
          working prototype, which has no left card on any view — a compact
          header, then one full-width input, then its suggestions. A rail also
          took a third of the screen from the timeline that needed it most. */}
      <div className="flex flex-1 flex-col">
        {/* Not on the Threads route. That view owns its own input — "name a
            subject to trace" — and its own suggestions, exactly as the
            prototype's Thread view does. Rendering the Search and Ask bar above
            it stacked two input areas on one screen, which is what the owner
            was seeing as a bad left-hand slab. Each view gets one input. */}
        <aside
          hidden={wideCanvas}
          data-testid="search-ask-rail"
          className="w-full border-b border-border px-4 py-3 min-[1200px]:px-8" 
        >
        <div
          data-testid="search-ask-chrome"
          className="mx-auto flex w-full max-w-[1600px] flex-col gap-3 min-[900px]:flex-row min-[900px]:items-start min-[900px]:gap-4"
        >
          <div
            className="relative min-w-0 flex-1"
            onFocusCapture={() => setExpandedChrome('search')}
            onBlurCapture={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget)) setExpandedChrome(null)
            }}
          >
            <CorpusSearch
              presentation="chrome"
              expanded={expandedChrome === 'search'}
              onOpenMoment={(momentId) => openPath(`/moments/${momentId}`)}
            />
          </div>
          <div
            className="relative min-w-0 flex-[2]"
            onFocusCapture={() => setExpandedChrome('ask')}
            onBlurCapture={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget)) setExpandedChrome(null)
            }}
          >
            <ChatPanel
              presentation="chrome"
              expanded={expandedChrome === 'ask'}
              onOpenMoment={(momentId) => openPath(`/moments/${momentId}`)}
            />
          </div>
        </div>
        </aside>
      <main
        className={
          wideCanvas
            ? 'flex w-full min-w-0 flex-1 flex-col gap-6 px-0 pt-0 pb-0'
            : 'mx-auto flex w-full max-w-[1600px] min-w-0 flex-1 flex-col gap-6 px-8 pt-6 pb-12'
        }
      >
        {/* Back belongs to a screen opened OUT of something. Threads is a
            standing destination in the nav, so it has nothing to go back to. */}
        {childOpen && !wideCanvas && (
          <div>
            <Button size="sm" variant="outline" onClick={back}>
              ← Back
            </Button>
          </div>
        )}
        {/* The open child screen is the first flow-height content below the
            persistent 56px chrome (pinned by `shellPlacement.test.tsx`,
            backlog B-13). Search and Ask stay mounted inside the header, but
            their results expand as overlays, so a full result list can never
            push the opened screen thousands of pixels down the document.

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
          // Child screens render at the reading width because they are columns
          // of prose and evidence. The traced-thread timeline is neither: it is
          // a map, and capping a map at 64rem on a 32" display is the whole
          // reason it did not feel like one.
          className={wideCanvas ? 'w-full min-w-0' : 'mx-auto w-full max-w-5xl'}
        >
          <Outlet />
        </div>
        {/* The front door (story 10.5): the ranked feed, hidden but never
            unmounted while a moment opened out of it is on screen, so Back
            lands on the same page of cards rather than re-ranking. */}
        <div hidden={!momentsOpen}>
          <MomentsFeed
            active={momentsOpen}
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
          {/* The corpus counts used to sit here. They moved to the banner above
              the chrome (owner request) so they are answered on every screen,
              not only this one — one instance, not two. */}
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
