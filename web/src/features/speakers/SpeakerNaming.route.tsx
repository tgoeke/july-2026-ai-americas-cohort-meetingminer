import { useNavigate, useParams } from 'react-router'
import type { RouteModule } from '@/routes/registry'
import { SpeakerNaming } from './SpeakerNaming'

function SpeakerNamingRoute() {
  // The router only mounts this element when the pattern matched, so the
  // param is always present; the type just does not know that.
  const { meetingId } = useParams<'meetingId'>()
  const navigate = useNavigate()
  return (
    <SpeakerNaming
      meetingId={meetingId!}
      onBack={() => void navigate(`/meetings/${meetingId!}`)}
    />
  )
}

/**
 * `/meetings/:meetingId/speakers` (story 7.4). More specific than
 * `/meetings/:meetingId`, and react-router ranks child routes by path
 * specificity rather than array position, so the two never contend.
 */
export const route: RouteModule = {
  path: '/meetings/:meetingId/speakers',
  element: <SpeakerNamingRoute />,
}
