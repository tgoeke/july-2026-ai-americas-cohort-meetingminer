import { useParams } from 'react-router'
import { useOpenPath } from '@/routes/navigation'
import type { RouteModule } from '@/routes/registry'
import { MomentView } from './MomentView'

function MomentRoute() {
  // The router only mounts this element when the pattern matched, so the
  // param is always present; the type just does not know that.
  const { momentId } = useParams<'momentId'>()
  const openPath = useOpenPath()
  return (
    <MomentView
      momentId={momentId!}
      onOpenMeeting={(meetingId) => openPath(`/meetings/${meetingId}`)}
    />
  )
}

export const route: RouteModule = {
  path: '/moments/:momentId',
  element: <MomentRoute />,
}
