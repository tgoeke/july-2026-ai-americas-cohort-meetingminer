import { useEffect, useState } from 'react'

export const SINGLE_KEY_SHORTCUTS_STORAGE_KEY = 'meetingminer.single-key-shortcuts'
const CHANGE_EVENT = 'meetingminer:single-key-shortcuts'

export function areSingleKeyShortcutsEnabled(): boolean {
  return typeof localStorage === 'undefined' ||
    localStorage.getItem(SINGLE_KEY_SHORTCUTS_STORAGE_KEY) !== 'off'
}

export function setSingleKeyShortcutsEnabled(enabled: boolean): void {
  if (typeof localStorage !== 'undefined') {
    localStorage.setItem(SINGLE_KEY_SHORTCUTS_STORAGE_KEY, enabled ? 'on' : 'off')
  }
  window.dispatchEvent(new Event(CHANGE_EVENT))
}

export function useSingleKeyShortcutsEnabled(): boolean {
  const [enabled, setEnabled] = useState(areSingleKeyShortcutsEnabled)
  useEffect(() => {
    const refresh = () => setEnabled(areSingleKeyShortcutsEnabled())
    window.addEventListener(CHANGE_EVENT, refresh)
    window.addEventListener('storage', refresh)
    return () => {
      window.removeEventListener(CHANGE_EVENT, refresh)
      window.removeEventListener('storage', refresh)
    }
  }, [])
  return enabled
}
