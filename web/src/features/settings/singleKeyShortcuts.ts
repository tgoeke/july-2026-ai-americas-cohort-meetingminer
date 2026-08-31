import { useEffect, useState } from 'react'

export const SINGLE_KEY_SHORTCUTS_STORAGE_KEY = 'meetingminer.single-key-shortcuts'
const CHANGE_EVENT = 'meetingminer:single-key-shortcuts'
let volatileEnabled = true

export function areSingleKeyShortcutsEnabled(): boolean {
  if (typeof localStorage === 'undefined') return volatileEnabled
  try {
    const stored = localStorage.getItem(SINGLE_KEY_SHORTCUTS_STORAGE_KEY)
    if (stored === null) {
      volatileEnabled = true
      return true
    }
    volatileEnabled = stored !== 'off'
    return volatileEnabled
  } catch {
    return volatileEnabled
  }
}

export function setSingleKeyShortcutsEnabled(enabled: boolean): void {
  volatileEnabled = enabled
  if (typeof localStorage !== 'undefined') {
    try {
      localStorage.setItem(SINGLE_KEY_SHORTCUTS_STORAGE_KEY, enabled ? 'on' : 'off')
    } catch {
      // The in-memory preference remains authoritative for this session when
      // storage is denied or full.
    }
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
