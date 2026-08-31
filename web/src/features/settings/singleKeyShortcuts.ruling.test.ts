import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  areSingleKeyShortcutsEnabled,
  setSingleKeyShortcutsEnabled,
  SINGLE_KEY_SHORTCUTS_STORAGE_KEY,
} from './singleKeyShortcuts'

const values = new Map<string, string>()
const memoryStorage = {
  getItem: (key: string) => values.get(key) ?? null,
  setItem: (key: string, value: string) => values.set(key, value),
  removeItem: (key: string) => values.delete(key),
  clear: () => values.clear(),
}

describe('F13 owner ruling: persisted shortcut preference', () => {
  beforeEach(() => {
    memoryStorage.clear()
    vi.stubGlobal('localStorage', memoryStorage)
  })

  it('defaults on and persists an explicit opt-out', () => {
    expect(areSingleKeyShortcutsEnabled()).toBe(true)
    const listener = vi.fn()
    window.addEventListener('meetingminer:single-key-shortcuts', listener)
    setSingleKeyShortcutsEnabled(false)
    expect(localStorage.getItem(SINGLE_KEY_SHORTCUTS_STORAGE_KEY)).toBe('off')
    expect(areSingleKeyShortcutsEnabled()).toBe(false)
    expect(listener).toHaveBeenCalledOnce()
    window.removeEventListener('meetingminer:single-key-shortcuts', listener)
  })

  it('falls back without throwing when browser storage is denied', () => {
    setSingleKeyShortcutsEnabled(true)
    vi.stubGlobal('localStorage', {
      getItem: () => { throw new DOMException('denied') },
      setItem: () => { throw new DOMException('denied') },
    })
    expect(areSingleKeyShortcutsEnabled()).toBe(true)
    expect(() => setSingleKeyShortcutsEnabled(false)).not.toThrow()
    expect(areSingleKeyShortcutsEnabled()).toBe(false)
  })
})
