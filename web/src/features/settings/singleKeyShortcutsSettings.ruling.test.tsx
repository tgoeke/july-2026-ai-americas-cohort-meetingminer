import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SettingsPage } from './SettingsPage'
import { SINGLE_KEY_SHORTCUTS_STORAGE_KEY } from './singleKeyShortcuts'

const values = new Map<string, string>()
const memoryStorage = {
  getItem: (key: string) => values.get(key) ?? null,
  setItem: (key: string, value: string) => values.set(key, value),
  removeItem: (key: string) => values.delete(key),
  clear: () => values.clear(),
}

vi.mock('@/client/sdk.gen', () => ({
  getConfiguration: vi.fn(() => Promise.reject(new Error('offline'))),
}))

beforeEach(() => {
  memoryStorage.clear()
  vi.stubGlobal('localStorage', memoryStorage)
})

describe('F13 owner ruling: Settings toggle', () => {
  it('is on by default and persists opt-out even if config is unavailable', async () => {
    render(<SettingsPage />)
    const toggle = screen.getByRole('checkbox', { name: 'Single-key shortcuts' })
    expect(toggle).toBeChecked()
    await userEvent.click(toggle)
    expect(toggle).not.toBeChecked()
    expect(localStorage.getItem(SINGLE_KEY_SHORTCUTS_STORAGE_KEY)).toBe('off')
  })
})
