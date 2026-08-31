import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { setSingleKeyShortcutsEnabled } from './features/settings/singleKeyShortcuts'

const values = new Map<string, string>()
const memoryStorage = {
  getItem: (key: string) => values.get(key) ?? null,
  setItem: (key: string, value: string) => values.set(key, value),
  removeItem: (key: string) => values.delete(key),
  clear: () => values.clear(),
}

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
  memoryStorage.clear()
  vi.stubGlobal('localStorage', memoryStorage)
  window.history.replaceState(null, '', '/')
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
    const path = new URL(String(input)).pathname
    const body = path.endsWith('/threads')
      ? { threads: [] }
      : { items: [], total: 0, unfilteredTotal: 0, limit: 24, offset: 0 }
    return Promise.resolve(new Response(JSON.stringify(body)))
  }))
})

describe('F13 owner ruling: global bindings', () => {
  it('focuses and routes by the documented keys while guarding text fields and opt-out', async () => {
    render(<App />)

    await userEvent.keyboard('/')
    expect(screen.getByTestId('search-input')).toHaveFocus()
    await userEvent.keyboard('a')
    expect(screen.getByTestId('search-input')).toHaveValue('a')
    expect(screen.getByTestId('chat-question-input')).not.toHaveFocus()

    screen.getByTestId('search-input').blur()
    await userEvent.keyboard('a')
    expect(screen.getByTestId('chat-question-input')).toHaveFocus()
    screen.getByTestId('chat-question-input').blur()

    await userEvent.keyboard('ge')
    await waitFor(() => expect(window.location.pathname).toBe('/meetings'))
    await userEvent.keyboard('gm')
    await waitFor(() => expect(window.location.pathname).toBe('/'))
    await userEvent.keyboard('gt')
    await waitFor(() => expect(window.location.pathname).toBe('/threads'))
    await userEvent.keyboard('n')
    await waitFor(() => expect(window.location.pathname).toBe('/add'))

    screen.getByTestId('chat-question-input').blur()
    setSingleKeyShortcutsEnabled(false)
    await userEvent.keyboard('a')
    expect(screen.getByTestId('chat-question-input')).not.toHaveFocus()
  })

  it('ignores modifiers and repeats and cancels an armed chord on pointer activity', async () => {
    render(<App />)
    fireEvent.keyDown(window, { key: 'a', ctrlKey: true })
    fireEvent.keyDown(window, { key: '/', repeat: true })
    expect(screen.getByTestId('chat-question-input')).not.toHaveFocus()
    expect(screen.getByTestId('search-input')).not.toHaveFocus()

    await userEvent.keyboard('g')
    fireEvent.pointerDown(document.body)
    await userEvent.keyboard('t')
    expect(window.location.pathname).toBe('/')
  })
})
