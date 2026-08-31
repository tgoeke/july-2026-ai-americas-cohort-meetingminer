import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'

vi.mock('@/client/sdk.gen', () => ({
  getHealth: vi.fn(() => Promise.reject(new Error('offline'))),
  listMeetings: vi.fn(() => Promise.resolve({ data: { meetings: [] }, error: undefined })),
  streamJobEvents: vi.fn(() => Promise.reject(new Error('offline'))),
  searchCorpus: vi.fn(() => Promise.reject(new Error('offline'))),
  getMeetingDrilldown: vi.fn(() => Promise.reject(new Error('offline'))),
  listMeetingMoments: vi.fn(() => Promise.reject(new Error('offline'))),
  getMoment: vi.fn(() => Promise.reject(new Error('offline'))),
  getJob: vi.fn(() => Promise.reject(new Error('offline'))),
  createIngest: vi.fn(() => Promise.reject(new Error('offline'))),
  getRecording: vi.fn(() => Promise.reject(new Error('offline'))),
  getMediaFile: vi.fn(() => Promise.reject(new Error('offline'))),
  listParticipants: vi.fn(() => Promise.resolve({ data: [], error: undefined })),
  renameParticipant: vi.fn(() => Promise.reject(new Error('offline'))),
  mergeParticipants: vi.fn(() => Promise.reject(new Error('offline'))),
  askCorpus: vi.fn(() => Promise.reject(new Error('offline'))),
  approveMomentArtifacts: vi.fn(() => Promise.reject(new Error('offline'))),
  getExtractionPrompts: vi.fn(() => Promise.reject(new Error('offline'))),
  getCorpusStats: vi.fn(() => Promise.reject(new Error('offline'))),
  getSystemStatus: vi.fn(() => Promise.reject(new Error('offline'))),
  getConfiguration: vi.fn(() => Promise.reject(new Error('offline'))),
}))

beforeEach(() => {
  window.history.replaceState(null, '', '/')
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
    const path = new URL(String(input)).pathname
    return Promise.resolve(new Response(JSON.stringify(
      path.endsWith('/threads')
        ? { threads: [] }
        : { items: [], total: 0, unfilteredTotal: 0, limit: 24, offset: 0 },
    )))
  }))
})

describe('F10 owner ruling: compact Search and Ask chrome', () => {
  it('keeps both one-line controls in the sticky header and expands one at a time', async () => {
    render(<App />)
    const chrome = screen.getByTestId('search-ask-chrome')
    const header = chrome.closest('header')
    expect(header).not.toBeNull()
    expect(header).toContainElement(screen.getByTestId('search-input'))
    expect(header).toContainElement(screen.getByTestId('chat-question-input'))
    expect(screen.getByTestId('chat-question-input')).toHaveAttribute('rows', '1')
    expect(screen.getByTestId('moments-feed').closest('main')).not.toContainElement(chrome)

    const searchSurface = screen.getByTestId('chrome-search-surface')
    const askSurface = screen.getByTestId('chrome-ask-surface')
    expect(searchSurface).toHaveAttribute('aria-expanded', 'false')
    await userEvent.click(screen.getByTestId('search-input'))
    expect(searchSurface).toHaveAttribute('aria-expanded', 'true')
    await userEvent.click(screen.getByTestId('chat-question-input'))
    expect(searchSurface).toHaveAttribute('aria-expanded', 'false')
    expect(askSurface).toHaveAttribute('aria-expanded', 'true')
  })
})
