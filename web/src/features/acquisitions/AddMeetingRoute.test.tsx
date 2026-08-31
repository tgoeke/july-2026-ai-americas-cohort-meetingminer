import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '@/App'
import { childRoutes } from '@/routes/registry'
import { route as addMeetingRoute } from './AddMeeting.route'

/**
 * The defect this story exists to fix, pinned.
 *
 * The chrome's **Add meeting** button and the `n` shortcut have pointed at
 * `/add` since story 10.5. Nothing claimed the path, so react-router fell
 * through to `App.tsx`'s unknown-path catch-all and quietly showed the front
 * door — a primary action that looked like it worked and did nothing. Modelled
 * on `threadsRoutes.review.test.tsx`, which pins the same class of failure for
 * `/threads`.
 */

const sdk = vi.hoisted(() => ({
  probeAcquisition: vi.fn(),
  startAcquisition: vi.fn(),
  getAcquisition: vi.fn(),
}))

vi.mock('@/client/sdk.gen', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/client/sdk.gen')>()),
  probeAcquisition: sdk.probeAcquisition,
  startAcquisition: sdk.startAcquisition,
  getAcquisition: sdk.getAcquisition,
  getHealth: vi.fn(() => Promise.reject(new Error('no api in this test'))),
  listMeetings: vi.fn(() => Promise.reject(new Error('no api in this test'))),
  streamJobEvents: vi.fn(() => Promise.reject(new Error('no api in this test'))),
  searchCorpus: vi.fn(() => Promise.reject(new Error('no api in this test'))),
  askCorpus: vi.fn(() => Promise.reject(new Error('no api in this test'))),
  getCorpusStats: vi.fn(() => Promise.reject(new Error('no api in this test'))),
  getSystemStatus: vi.fn(() => Promise.reject(new Error('no api in this test'))),
  getConfiguration: vi.fn(() => Promise.reject(new Error('no api in this test'))),
  getMomentsFeed: vi.fn(() => Promise.reject(new Error('no api in this test'))),
}))

beforeEach(() => {
  sdk.probeAcquisition.mockReset()
  sdk.startAcquisition.mockReset()
  sdk.getAcquisition.mockReset()
  window.history.replaceState(null, '', '/add')
})

afterEach(() => {
  window.history.replaceState(null, '', '/')
})

describe('the /add route', () => {
  it('is discovered by the registry, so App.tsx needs no edit', () => {
    // Story 2.8: adding a screen is adding a `*.route.tsx` file. If this
    // fails, either the glob no longer covers the file or the export shape
    // changed — both would put the button back on the catch-all.
    expect(addMeetingRoute.path).toBe('/add')
    expect(childRoutes.map((route) => route.path)).toContain('/add')
  })

  it('resolves /add to the Add-meeting screen rather than the front-door catch-all', () => {
    render(<App />)

    expect(screen.getByRole('tablist', { name: 'Meeting source' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Add a meeting' })).toBeInTheDocument()
    // The shell treats it as an open child screen: visible, with Back.
    expect(screen.getByTestId('child-screen')).not.toHaveAttribute('hidden')
    expect(screen.getByRole('button', { name: '← Back' })).toBeInTheDocument()
  })

  it('opens without touching the acquisition api', () => {
    render(<App />)

    // Nothing is written, requested, or probed by arriving. The first request
    // this screen makes is the probe, 600ms after a shape-valid URL is typed.
    expect(sdk.probeAcquisition).not.toHaveBeenCalled()
    expect(sdk.startAcquisition).not.toHaveBeenCalled()
    expect(sdk.getAcquisition).not.toHaveBeenCalled()
  })

  it('keeps the chrome standing, so Add meeting is reachable from itself', () => {
    render(<App />)

    expect(screen.getByRole('link', { name: 'Add meeting' })).toHaveAttribute('href', '/add')
    expect(screen.getByTestId('search-input')).toBeInTheDocument()
    expect(screen.getByTestId('chat-question-input')).toBeInTheDocument()
  })
})
