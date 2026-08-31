import type { RouteModule } from '@/routes/registry'
import ThreadTrace from './ThreadTrace'

/**
 * The Threads screen at `/threads` (story 10.7).
 *
 * It opens **empty**: a box and a handful of subjects the corpus suggests, not
 * a catalogue of every derived thread. Story 10.6's list screen (`Threads.tsx`)
 * is no longer mounted anywhere; retiring it, and the `GET /threads` endpoint
 * it reads, is story 10.7a.
 */
export const route: RouteModule = {
  path: '/threads',
  element: <ThreadTrace />,
  order: 20,
}
