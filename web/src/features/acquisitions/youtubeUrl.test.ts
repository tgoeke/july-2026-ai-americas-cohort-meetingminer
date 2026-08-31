import { describe, expect, it } from 'vitest'
import { SHAPE_MESSAGE, classifyYoutubeUrl, watchUrl } from './youtubeUrl'

/**
 * The authority for every row here is
 * `server/meetingminer/youtube.py:video_id_from_url` (and `playlist_id_from_url`
 * for the playlist sentence). This table is the record that the client check
 * mirrors it rather than holding a second opinion: a shape the server accepts
 * must not be refused here, and a shape it refuses must not be sent.
 */
describe('classifyYoutubeUrl', () => {
  const VIDEO = 'dQw4w9WgXcQ'

  it('accepts every shape the server accepts, and normalizes them to one identity', () => {
    const accepted = [
      `https://www.youtube.com/watch?v=${VIDEO}`,
      `http://www.youtube.com/watch?v=${VIDEO}`,
      `https://youtube.com/watch?v=${VIDEO}`,
      `https://m.youtube.com/watch?v=${VIDEO}`,
      // Extra query keys are ignored — the server acquires the single video.
      `https://www.youtube.com/watch?v=${VIDEO}&t=42s&si=abc`,
      // A `list=` alongside a `v=` is still one video (youtube.py:220-222).
      `https://www.youtube.com/watch?v=${VIDEO}&list=PL9abcdef`,
      // Python's `parse_qs` drops blank values, so this still has one candidate.
      `https://www.youtube.com/watch?v=${VIDEO}&v=`,
      `https://youtu.be/${VIDEO}`,
      `https://youtu.be/${VIDEO}?si=abc`,
      `https://www.youtube.com/shorts/${VIDEO}`,
      `  https://www.youtube.com/watch?v=${VIDEO}  `,
    ]
    for (const url of accepted) {
      const shape = classifyYoutubeUrl(url)
      expect(shape, url).toEqual({
        kind: 'valid',
        videoId: VIDEO,
        normalized: `https://www.youtube.com/watch?v=${VIDEO}`,
      })
    }
  })

  it('reports an empty field as empty rather than invalid', () => {
    expect(classifyYoutubeUrl('')).toEqual({ kind: 'empty' })
    expect(classifyYoutubeUrl('   ')).toEqual({ kind: 'empty' })
  })

  it('names a playlist URL as a playlist, not as "not a YouTube URL"', () => {
    // It *is* a YouTube URL, so the generic sentence would misdescribe it (F-19).
    expect(classifyYoutubeUrl('https://www.youtube.com/playlist?list=PL9abcdef')).toEqual({
      kind: 'playlist',
    })
    expect(classifyYoutubeUrl('https://youtube.com/watch?list=PL9abcdef')).toEqual({
      kind: 'playlist',
    })
  })

  it('refuses everything the server refuses', () => {
    const refused = [
      'https://vimeo.com/12345',
      'https://example.com/watch?v=dQw4w9WgXcQ',
      // Scheme: HTTP(S) only.
      `ftp://www.youtube.com/watch?v=${VIDEO}`,
      `javascript:alert(1)//youtube.com/watch?v=${VIDEO}`,
      // A host that merely ends in the string, not in the domain.
      `https://notyoutube.com/watch?v=${VIDEO}`,
      `https://evil-youtube.com/watch?v=${VIDEO}`,
      // Video ids are exactly 11 chars of `[A-Za-z0-9_-]`.
      'https://www.youtube.com/watch?v=short',
      'https://www.youtube.com/watch?v=waytoolongvideoid',
      'https://youtu.be/short',
      // Two `v=` keys is ambiguous; the server takes exactly one.
      `https://www.youtube.com/watch?v=${VIDEO}&v=abcdefghijk`,
      // A YouTube path with no video and no list.
      'https://www.youtube.com/feed/subscriptions',
      'not a url at all',
    ]
    for (const url of refused) {
      expect(classifyYoutubeUrl(url), url).toEqual({ kind: 'invalid' })
    }
  })

  it('states the two sentences the design specifies, verbatim', () => {
    expect(SHAPE_MESSAGE.invalid).toBe(
      'Not a YouTube video URL — paste a watch or youtu.be link.',
    )
    expect(SHAPE_MESSAGE.playlist).toBe(
      "Playlist URLs are not accepted on this tab — paste one video's watch link.",
    )
  })

  it('builds the canonical watch URL the server writes into provenance', () => {
    expect(watchUrl(VIDEO)).toBe(`https://www.youtube.com/watch?v=${VIDEO}`)
  })
})
