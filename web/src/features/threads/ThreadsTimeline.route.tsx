import type { RouteModule } from '@/routes/registry'
import { Threads } from './Threads'

/**
 * The Threads screen at `/threads` (story 10.6).
 *
 * Story 10.5 owns the shell and mounts a `/threads/*` splat placeholder from
 * its own `Threads.route.tsx`. This file is deliberately named differently and
 * claims the *literal* path, which react-router ranks above a splat — so the
 * two land side by side with no edit to 10.5's file and no conflict, exactly as
 * 10.5's own comment anticipates. `ThreadFocus.route.tsx` claims the deep link
 * beside it. Integration can then delete the placeholder module.
 */
export const route: RouteModule = {
  path: '/threads',
  element: <Threads />,
  order: 20,
}
