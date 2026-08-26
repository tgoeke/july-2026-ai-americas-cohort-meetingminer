import type { RouteModule } from '@/routes/registry'
import { StatusPage } from './StatusPage'

export const route: RouteModule = {
  path: '/status',
  element: <StatusPage />,
}
