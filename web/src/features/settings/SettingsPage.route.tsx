import type { RouteModule } from '@/routes/registry'
import { SettingsPage } from './SettingsPage'

export const route: RouteModule = {
  path: '/settings',
  element: <SettingsPage />,
}
