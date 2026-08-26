import { createElement } from 'react'
import { describe, expect, it } from 'vitest'
import { childRoutes, routeOf, sortRoutes, type RouteModule } from './registry'

// Synthetic modules only: a fixture `*.route.tsx` under `features/` would be
// swept up by the eager glob and ship as a real production route.
function element() {
  return createElement('div')
}

describe('childRoutes', () => {
  it('discovers the two shipped screens, as a floor', () => {
    const paths = childRoutes.map((route) => route.path)
    expect(paths).toContain('/meetings/:meetingId')
    expect(paths).toContain('/moments/:momentId')
  })
})

describe('routeOf', () => {
  it('rejects a module with no route export, naming the file', () => {
    expect(() => routeOf('a.route.tsx', { other: 1 })).toThrow(
      /a\.route\.tsx.*must export `route`/,
    )
  })

  it('rejects a non-object route, naming the file', () => {
    expect(() => routeOf('b.route.tsx', { route: 'nope' })).toThrow(
      /b\.route\.tsx.*RouteModule object/,
    )
  })

  it('rejects a non-absolute path, naming the file', () => {
    expect(() =>
      routeOf('c.route.tsx', { route: { path: 'moments/:id', element: element() } }),
    ).toThrow(/c\.route\.tsx.*absolute path/)
  })

  it('rejects a non-element element, naming the file', () => {
    expect(() =>
      routeOf('d.route.tsx', { route: { path: '/x', element: () => null } }),
    ).toThrow(/d\.route\.tsx.*React element/)
  })

  it('rejects a non-number order, naming the file', () => {
    expect(() =>
      routeOf('e.route.tsx', {
        route: { path: '/x', element: element(), order: 'first' },
      }),
    ).toThrow(/e\.route\.tsx.*must be a number/)
  })

  it('accepts a valid module, order optional', () => {
    const route = routeOf('f.route.tsx', {
      route: { path: '/x/:id', element: element() },
    })
    expect(route.path).toBe('/x/:id')
    expect(route.order).toBeUndefined()
  })
})

describe('sortRoutes', () => {
  it('orders by (order ?? 100, path)', () => {
    const routes: Array<RouteModule> = [
      { path: '/c', element: element() },
      { path: '/b', element: element(), order: 100 },
      { path: '/a', element: element() },
      { path: '/z', element: element(), order: 10 },
      { path: '/y', element: element(), order: 200 },
    ]
    expect(sortRoutes(routes).map((route) => route.path)).toEqual([
      '/z', // explicit 10 beats every default
      '/a', // defaults and explicit 100 rank equal; path is the tie-break
      '/b',
      '/c',
      '/y', // explicit 200 last
    ])
    // Input untouched: the sort copies.
    expect(routes[0].path).toBe('/c')
  })
})
