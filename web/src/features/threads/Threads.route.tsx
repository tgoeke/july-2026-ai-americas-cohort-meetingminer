import type { RouteModule } from '@/routes/registry'
import { ThreadsPlaceholder } from './ThreadsPlaceholder'

/**
 * Threads, the second primary view (story 10.5's front-door composition).
 *
 * Story 10.5 creates this route and fills it with a placeholder; story 10.6
 * swaps the element for its timeline. `order` puts it directly after the
 * front door in the registry's deterministic array.
 *
 * The path is a splat so that both `/threads` and a thread deep link
 * (`/threads/<id>` — where every thread chip in the app points) resolve here
 * rather than falling through the unknown-path catch-all to the front door.
 * Story 10.6 replaces it with its own pattern; react-router ranks a literal
 * and a param segment above a splat, so a narrower route added beside it
 * wins without this one needing to move first.
 */
export const route: RouteModule = {
  path: '/threads/*',
  element: <ThreadsPlaceholder />,
  order: 20,
}
