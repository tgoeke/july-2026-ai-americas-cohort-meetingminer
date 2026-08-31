import { useParams } from 'react-router'
import { useOpenPath } from '@/routes/navigation'
import type { RouteModule } from '@/routes/registry'
import { MeetingMoments } from './MeetingMoments'

function MeetingRoute() {
  // The router only mounts this element when the pattern matched, so the
  // param is always present; the type just does not know that.
  const { meetingId } = useParams<'meetingId'>()
  const openPath = useOpenPath()
  return (
    <MeetingMoments
      meetingId={meetingId!}
      onOpenMoment={(momentId) => openPath(`/moments/${momentId}`)}
      onOpenSpeakers={() => openPath(`/meetings/${meetingId!}/speakers`)}
    />
  )
}

export const route: RouteModule = {
  path: '/meetings/:meetingId',
  element: <MeetingRoute />,
}
