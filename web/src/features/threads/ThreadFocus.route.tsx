import type { RouteModule } from '@/routes/registry'
import ThreadTrace from './ThreadTrace'

/**
 * `/threads/:threadId` — where every thread chip in the app points.
 *
 * The same screen, opened with that subject already traced: the deep link names
 * a known thread, so it takes the exhaustive leg rather than being re-resolved
 * from its name.
 */
export const route: RouteModule = {
  path: '/threads/:threadId',
  element: <ThreadTrace />,
  order: 20,
}
