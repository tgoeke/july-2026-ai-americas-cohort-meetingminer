import type { RouteModule } from '@/routes/registry'
import { Threads } from './Threads'

/**
 * The Threads screen, second primary view (story 10.5's chrome links here).
 *
 * Story 10.5 owns the shell and the nav entry; this file owns what the route
 * mounts. If 10.5 landed a placeholder at this path first, this replaces it.
 */
export const route: RouteModule = {
  path: '/threads',
  element: <Threads />,
}
