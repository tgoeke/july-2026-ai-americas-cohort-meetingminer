import { useOpenPath } from '@/routes/navigation'
import type { RouteModule } from '@/routes/registry'
import { AddMeeting } from './AddMeeting'

function AddMeetingRoute() {
  const openPath = useOpenPath()
  return (
    <AddMeeting
      onOpenMeeting={(meetingId) => openPath(`/meetings/${meetingId}`)}
      onNameSpeakers={(meetingId) => openPath(`/meetings/${meetingId}/speakers`)}
    />
  )
}

/**
 * `/add` — the destination the chrome's **Add meeting** button and the `n`
 * shortcut have pointed at since story 10.5, with nothing claiming it. Adding
 * this file is the whole registration: `routes/registry.ts` globs
 * `features/**` for `*.route.tsx` (story 2.8), so `App.tsx` is untouched.
 */
export const route: RouteModule = {
  path: '/add',
  element: <AddMeetingRoute />,
}
