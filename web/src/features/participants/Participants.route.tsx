import type { RouteModule } from '@/routes/registry'
import { Participants } from './Participants'

export const route: RouteModule = {
  path: '/participants',
  element: <Participants />,
}
