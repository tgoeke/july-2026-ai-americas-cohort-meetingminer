import type { RouteModule } from '@/routes/registry'
import { Threads } from './Threads'

/**
 * `/threads/:threadId` — where every thread chip in the app points.
 *
 * The same screen, opened with that thread already entered. A param segment
 * ranks above a splat, which is what let this route coexist with story 10.5's
 * `/threads/*` placeholder before integration deleted it.
 */
export const route: RouteModule = {
  path: '/threads/:threadId',
  element: <Threads />,
  order: 20,
}
