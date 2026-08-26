import { isValidElement, type ReactElement } from 'react'

/**
 * The contract a `*.route.tsx` file exports as `route` (story 2.8): adding a
 * screen is adding a file beside its component, with no edit to `App.tsx`.
 * The web-side equivalent of `server/meetingminer/api/registry.py`.
 *
 * Only files under `web/src/features/` are globbed — a `*.route.tsx` placed
 * anywhere else is silently not discovered. Route files live beside the
 * components they mount.
 */
export interface RouteModule {
  /** Absolute path pattern, e.g. `/moments/:momentId`. */
  path: string
  /** The element the router mounts in the shell's `<Outlet />`. */
  element: ReactElement
  /**
   * Position in the exported array (lower first; default 100, path as the
   * tie-break). This makes the array — and so the mounted route list —
   * deterministic across builds; it does *not* decide which route wins a
   * URL, because react-router ranks child routes by path specificity, not
   * array position.
   */
  order?: number
}

const DEFAULT_ORDER = 100

// Vite resolves the glob at build time, so a new `*.route.tsx` is picked up
// on the next build — the discovery is static, not a runtime filesystem walk.
const modules = import.meta.glob('../features/**/*.route.tsx', { eager: true })

/** Validate one glob entry; a malformed module throws at load, naming the
 * file. Exported for its tests. */
export function routeOf(file: string, mod: unknown): RouteModule {
  if (typeof mod !== 'object' || mod === null || !('route' in mod)) {
    throw new Error(`${file}: a *.route.tsx file must export \`route\``)
  }
  const route = (mod as { route: unknown }).route
  if (typeof route !== 'object' || route === null) {
    throw new Error(`${file}: \`route\` must be a RouteModule object`)
  }
  const { path, element, order } = route as Partial<RouteModule>
  if (typeof path !== 'string' || !path.startsWith('/')) {
    throw new Error(`${file}: route.path must be an absolute path string`)
  }
  if (!isValidElement(element)) {
    throw new Error(`${file}: route.element must be a React element`)
  }
  if (order !== undefined && typeof order !== 'number') {
    throw new Error(`${file}: route.order must be a number when present`)
  }
  return { path, element, order }
}

/** Deterministic array order: `(order ?? 100, path)`. Exported for its tests. */
export function sortRoutes(routes: Array<RouteModule>): Array<RouteModule> {
  return [...routes].sort(
    (a, b) =>
      (a.order ?? DEFAULT_ORDER) - (b.order ?? DEFAULT_ORDER) ||
      a.path.localeCompare(b.path),
  )
}

/** Every discovered child route, in deterministic array order. */
export const childRoutes: Array<RouteModule> = sortRoutes(
  Object.entries(modules).map(([file, mod]) => routeOf(file, mod)),
)
