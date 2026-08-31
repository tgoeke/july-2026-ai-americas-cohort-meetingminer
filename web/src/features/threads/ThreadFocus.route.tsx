import type { RouteModule } from '@/routes/registry'
import { Threads } from './Threads'

/**
 * `/threads/:threadId` — where every thread chip in the app points.
 *
 * The same screen, opened with that thread already entered. A param segment
 * ranks above story 10.5's `/threads/*` placeholder, so a deep link reaches the
 * timeline rather than the placeholder.
 */
export const route: RouteModule = {
  path: '/threads/:threadId',
  element: <Threads />,
  order: 20,
}
