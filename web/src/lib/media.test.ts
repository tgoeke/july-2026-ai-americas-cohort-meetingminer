import { describe, expect, it } from 'vitest'
import { API_BASE } from './api'
import { mediaUrl, recordingUrl } from './media'

describe('mediaUrl', () => {
  it('serves a root-relative screenshot path under /media', () => {
    expect(mediaUrl('meetings/abc/screenshots/shot-01.jpg')).toBe(
      `${API_BASE}/media/meetings/abc/screenshots/shot-01.jpg`,
    )
  })

  it('escapes each segment but keeps the separators', () => {
    expect(mediaUrl('meetings/a b/shot #2.jpg')).toBe(
      `${API_BASE}/media/meetings/a%20b/shot%20%232.jpg`,
    )
  })

  it('drops a leading slash so the api never sees an absolute path', () => {
    expect(mediaUrl('/meetings/abc/shot.jpg')).toBe(`${API_BASE}/media/meetings/abc/shot.jpg`)
  })

  it('escapes rather than sanitises — the api owns the containment guard', () => {
    // Dots encoded, separators intact: the browser would otherwise resolve
    // `..` away before sending and the api would never get to refuse it. Only
    // the api can tell whether a path escapes the content root.
    expect(mediaUrl('../../etc/passwd')).toBe(`${API_BASE}/media/%2E%2E/%2E%2E/etc/passwd`)
  })
})

describe('recordingUrl', () => {
  it('addresses the recording by meeting id', () => {
    expect(recordingUrl('0190a0f0-7c1e-7000-8000-0000000000aa')).toBe(
      `${API_BASE}/media/recordings/0190a0f0-7c1e-7000-8000-0000000000aa`,
    )
  })
})
