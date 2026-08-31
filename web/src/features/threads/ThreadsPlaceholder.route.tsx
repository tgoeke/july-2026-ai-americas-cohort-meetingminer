import type { RouteModule } from '@/routes/registry'
import { ThreadsPlaceholder } from './ThreadsPlaceholder'

/**
 * Threads, the second primary view (story 10.5's front-door composition).
 *
 * The shell's nav links to `/threads` from every screen, so the route has to
 * resolve to something rather than falling through the unknown-path catch-all
 * to the front door. Story 10.6 owns the screen itself and builds it in
 * parallel; this is the placeholder that keeps the destination honest until
 * that lands.
 *
 * **This file is meant to be deleted.** Story 10.6 ships its own
 * `Threads.route.tsx` at `/threads`, so integration removes this file and
 * `ThreadsPlaceholder.tsx` with it. It is deliberately *not* named
 * `Threads.route.tsx`: both lanes were told 10.5 creates the route and 10.6
 * fills it, and two branches creating one file is a merge conflict rather
 * than a seam (`branch_conflicts.py`, 2026-08-31). A separate filename lets
 * either land first.
 *
 * The path is a splat so a thread chip's deep link (`/threads/<id>` — where
 * every thread chip in the app points) resolves here too. react-router ranks
 * a literal segment above a splat, so once 10.6's `/threads` exists beside
 * this one it wins, and this route only ever answers what nothing narrower
 * claims.
 */
export const route: RouteModule = {
  path: '/threads/*',
  element: <ThreadsPlaceholder />,
  order: 20,
}
