import { useCallback } from 'react'
import { useLocation, useNavigate } from 'react-router'

/**
 * Navigate to `path` unless the app is already there: a rapid double-click on
 * an Open control must not push the identical entry twice and make the reader
 * press Back twice to leave once. The live `window.location` is checked as
 * well as the render-time snapshot, so the second click of a double-click is
 * caught even before React has re-rendered with the new location.
 */
export function useOpenPath(): (path: string) => void {
  const navigate = useNavigate()
  const { pathname } = useLocation()
  return useCallback(
    (path: string) => {
      // Comparing against `window.location.pathname` assumes the app runs
      // under `BrowserRouter` with no `basename` (it does — see App.tsx): with
      // a basename or a memory router, the window path would not equal the
      // router path and this guard would need `useHref`/router state instead.
      if (path === pathname || path === window.location.pathname) return
      void navigate(path)
    },
    [navigate, pathname],
  )
}
