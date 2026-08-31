import { matchRoutes } from 'react-router'
import { describe, expect, it } from 'vitest'
import { route as threadFocusRoute } from './ThreadFocus.route'
import { route as timelineRoute } from './ThreadsTimeline.route'

describe('Story 10.5 placeholder route integration', () => {
  const routes = [
    { path: timelineRoute.path },
    { path: threadFocusRoute.path },
    { path: '/threads/*' },
  ]

  it.each([
    ['/threads', '/threads'],
    ['/threads/thread-a', '/threads/:threadId'],
    ['/threads/not/a/timeline-route', '/threads/*'],
  ])('ranks %s to %s', (url, expectedPath) => {
    expect(matchRoutes(routes, url)?.at(-1)?.route.path).toBe(expectedPath)
  })
})
