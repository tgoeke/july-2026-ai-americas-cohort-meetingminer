import { describe, expect, it } from 'vitest'
import { affordanceOf, sourceLinkLabel, sourceLinkOf } from './affordance'

/** Story 6.6's I/O matrix: the URL rows pin replace-or-insert, the host and
 * path rules, and clamping; the affordance rows pin "replay first, the source
 * second" and "other host with replay → no link". */

const WATCH = 'https://www.youtube.com/watch?v=abc'
const SHAREPOINT = 'https://example.sharepoint.com/stream.aspx?id=x'

describe('sourceLinkOf', () => {
  it('inserts t= on a watch URL with a query and keeps other params', () => {
    expect(sourceLinkOf(WATCH, 754_000)).toEqual({
      provider: 'youtube',
      href: 'https://www.youtube.com/watch?v=abc&t=754',
      offsetMs: 754_000,
    })
  })

  it('replaces an existing t= in place, leaving the other params intact', () => {
    const link = sourceLinkOf('https://www.youtube.com/watch?v=abc&t=10s&list=x', 65_000)
    expect(link?.href).toBe('https://www.youtube.com/watch?v=abc&t=65&list=x')
    // Exactly one `t`, never a second appended.
    expect(new URL(link!.href).searchParams.getAll('t')).toEqual(['65'])
  })

  it('adds the first query to a bare youtu.be link', () => {
    const link = sourceLinkOf('https://youtu.be/abc', 3_661_000)
    expect(link).toEqual({
      provider: 'youtube',
      href: 'https://youtu.be/abc?t=3661',
      offsetMs: 3_661_000,
    })
    expect(sourceLinkLabel(link!)).toBe('Open on YouTube at 1:01:01')
  })

  it('drops a #t= fragment once a t= parameter is set', () => {
    expect(sourceLinkOf('https://youtu.be/abc?si=z#t=30s', 5_000)?.href).toBe(
      'https://youtu.be/abc?si=z&t=5',
    )
  })

  it('leaves a non-watch YouTube path untimed rather than inventing a syntax', () => {
    const link = sourceLinkOf('https://www.youtube.com/shorts/abc', 5_000)
    expect(link).toEqual({
      provider: 'youtube',
      href: 'https://www.youtube.com/shorts/abc',
      offsetMs: null,
    })
    expect(sourceLinkLabel(link!)).toBe('Open on YouTube')
    // Same for a youtu.be path that is not the bare id form.
    expect(sourceLinkOf('https://youtu.be/embed/abc', 5_000)).toEqual({
      provider: 'youtube',
      href: 'https://youtu.be/embed/abc',
      offsetMs: null,
    })
  })

  it('recognises youtube.com, any *.youtube.com subdomain, and youtu.be — over http(s) only', () => {
    for (const host of ['youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com']) {
      expect(sourceLinkOf(`https://${host}/watch?v=abc`, 1_000)?.provider).toBe('youtube')
    }
    expect(sourceLinkOf('http://youtu.be/abc', 1_000)?.provider).toBe('youtube')
    // A look-alike host is not YouTube.
    expect(sourceLinkOf('https://notyoutube.com/watch?v=abc', 1_000)?.provider).toBe('other')
    expect(sourceLinkOf('https://youtube.com.example.net/watch?v=abc', 1_000)?.provider).toBe(
      'other',
    )
    // The scheme rule still gates everything.
    expect(sourceLinkOf('ftp://youtube.com/watch?v=abc', 1_000)).toBeNull()
    expect(sourceLinkOf('javascript:alert(1)', 1_000)).toBeNull()
  })

  it('leaves a meeting-scoped (no offset) YouTube link untimed and named without an offset', () => {
    const link = sourceLinkOf(WATCH)
    expect(link).toEqual({ provider: 'youtube', href: WATCH, offsetMs: null })
    expect(sourceLinkLabel(link!)).toBe('Open on YouTube')
  })

  it('clamps a negative or NaN offset to t=0', () => {
    for (const offset of [-1, Number.NaN]) {
      const link = sourceLinkOf(WATCH, offset)
      expect(link?.href).toBe('https://www.youtube.com/watch?v=abc&t=0')
      expect(sourceLinkLabel(link!)).toBe('Open on YouTube at 0:00')
    }
  })

  it('returns another host verbatim with the existing Stream label', () => {
    const link = sourceLinkOf(SHAREPOINT, 5_000)
    expect(link).toEqual({ provider: 'other', href: SHAREPOINT })
    expect(sourceLinkLabel(link!)).toBe('Open in Stream')
  })

  it('is null for an empty link', () => {
    expect(sourceLinkOf(null, 1_000)).toBeNull()
    expect(sourceLinkOf(undefined, 1_000)).toBeNull()
    expect(sourceLinkOf('', 1_000)).toBeNull()
  })
})

describe('affordanceOf', () => {
  it('carries the timed YouTube link beside replay', () => {
    expect(affordanceOf({ hasRecording: true, sourceDeepLink: WATCH }, 754_000)).toEqual({
      kind: 'replay',
      source: {
        provider: 'youtube',
        href: 'https://www.youtube.com/watch?v=abc&t=754',
        offsetMs: 754_000,
      },
    })
  })

  it('offers no source link beside replay for another host — replay wins', () => {
    expect(affordanceOf({ hasRecording: true, sourceDeepLink: SHAREPOINT }, 754_000)).toEqual({
      kind: 'replay',
      source: null,
    })
    expect(affordanceOf({ hasRecording: true, sourceDeepLink: null })).toEqual({
      kind: 'replay',
      source: null,
    })
    // An unsafe scheme beside a recording is simply not offered either.
    expect(affordanceOf({ hasRecording: true, sourceDeepLink: 'javascript:x' }, 1)).toEqual({
      kind: 'replay',
      source: null,
    })
  })

  it('makes the timed YouTube link the sole affordance without replay', () => {
    expect(affordanceOf({ hasRecording: false, sourceDeepLink: WATCH }, 65_000)).toEqual({
      kind: 'deepLink',
      source: {
        provider: 'youtube',
        href: 'https://www.youtube.com/watch?v=abc&t=65',
        offsetMs: 65_000,
      },
    })
  })

  it('keeps another host untimed as the sole affordance without replay', () => {
    expect(affordanceOf({ hasRecording: false, sourceDeepLink: SHAREPOINT }, 65_000)).toEqual({
      kind: 'deepLink',
      source: { provider: 'other', href: SHAREPOINT },
    })
  })

  it('shows an unsafe link inert and says none when there is nothing', () => {
    expect(affordanceOf({ hasRecording: false, sourceDeepLink: 'javascript:x' }, 1)).toEqual({
      kind: 'inertLink',
      text: 'javascript:x',
    })
    expect(affordanceOf({ hasRecording: false, sourceDeepLink: null })).toEqual({ kind: 'none' })
  })
})
