import { useParams } from 'react-router'
import type { RouteModule } from '@/routes/registry'
import { MomentView } from './MomentView'

function MomentRoute() {
  // The router only mounts this element when the pattern matched, so the
  // param is always present; the type just does not know that.
  const { momentId } = useParams<'momentId'>()
  return <MomentView momentId={momentId!} />
}

export const route: RouteModule = {
  path: '/moments/:momentId',
  element: <MomentRoute />,
}
