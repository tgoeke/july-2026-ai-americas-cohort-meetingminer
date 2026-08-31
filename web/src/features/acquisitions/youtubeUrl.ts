/**
 * The offline shape check the Add-meeting URL field runs before any request.
 *
 * The authority is `server/meetingminer/youtube.py:video_id_from_url`, which
 * refuses before any subprocess runs. This mirrors its accepted shapes exactly
 * so Submit can stay disabled with a sentence saying why *before* a network
 * round trip is spent (EXPERIENCE.md · State Patterns, Add-meeting rows). It
 * is deliberately not a second opinion: anything it accepts still faces the
 * probe, and it never states a refusal the server would not make.
 *
 * A shape failure is **not** a refusal. Nothing was sent, so nothing refused
 * it: the screen renders muted helper text under the field, never a refusal
 * box (EXPERIENCE.md:132).
 */

/** `VIDEO_ID_PATTERN` in `server/meetingminer/youtube.py:114`, anchored. */
const VIDEO_ID = /^[A-Za-z0-9_-]{11}$/

export type YoutubeUrlShape =
  /** Nothing typed yet — not an error, just nothing to check. */
  | { kind: 'empty' }
  | { kind: 'valid'; videoId: string; normalized: string }
  /** A YouTube URL naming a list and no single video (F-19). */
  | { kind: 'playlist' }
  | { kind: 'invalid' }

/**
 * The sentence each non-valid shape shows. Wording is EXPERIENCE.md:132's,
 * verbatim, so the screen and the design agree word for word.
 */
export const SHAPE_MESSAGE: Record<'playlist' | 'invalid', string> = {
  playlist: "Playlist URLs are not accepted on this tab — paste one video's watch link.",
  invalid: 'Not a YouTube video URL — paste a watch or youtu.be link.',
}

/**
 * The canonical watch URL for a video id — `youtube.py:watch_url`'s spelling.
 *
 * The screen sends this rather than the pasted text, for the same reason the
 * server writes it into `provenance.url`: one video has one identity, so
 * `youtu.be/<id>`, a `shorts/` link and a watch URL carrying tracking
 * parameters are one probe and one acquisition, not three.
 */
export function watchUrl(videoId: string): string {
  return `https://www.youtube.com/watch?v=${videoId}`
}

/**
 * Classify what was typed, without sending anything.
 *
 * Accepted, matching the server: `youtube.com/watch?v=<id>` on any
 * `*.youtube.com` host with any extra query keys (a `list=` alongside a `v=`
 * is a single video, which is what the server acquires), `youtube.com/
 * shorts/<id>`, and `youtu.be/<id>`. HTTP(S) only.
 */
export function classifyYoutubeUrl(raw: string): YoutubeUrlShape {
  const trimmed = raw.trim()
  if (trimmed.length === 0) return { kind: 'empty' }

  let parsed: URL
  try {
    parsed = new URL(trimmed)
  } catch {
    return { kind: 'invalid' }
  }
  const scheme = parsed.protocol.toLowerCase()
  if (scheme !== 'http:' && scheme !== 'https:') return { kind: 'invalid' }

  const host = parsed.hostname.toLowerCase()
  const isYoutubeHost = host === 'youtube.com' || host.endsWith('.youtube.com')
  const segments = parsed.pathname.split('/').filter((segment) => segment.length > 0)

  let candidate: string | null = null
  if (host === 'youtu.be') {
    if (segments.length === 1) candidate = segments[0]
  } else if (isYoutubeHost) {
    if (segments.length === 1 && segments[0] === 'watch') {
      // Exactly one `v=`, as the server requires: two is ambiguous, and
      // guessing which video was meant is the kind of invention this screen
      // does not do.
      // Python's `parse_qs` drops blank values by default. Do the same before
      // enforcing the server's exactly-one-candidate rule.
      const values = parsed.searchParams.getAll('v').filter((value) => value.length > 0)
      if (values.length === 1) candidate = values[0]
    } else if (segments.length === 2 && segments[0] === 'shorts') {
      candidate = segments[1]
    }
  }

  if (candidate !== null && VIDEO_ID.test(candidate)) {
    return { kind: 'valid', videoId: candidate, normalized: watchUrl(candidate) }
  }
  // Checked only after the video branch fails, so `watch?v=…&list=…` stays a
  // single video exactly as the server treats it. A YouTube URL that names a
  // list and no video is the playlist case, which has its own sentence
  // because "not a YouTube video URL" would be misleading — it is one.
  if (isYoutubeHost && parsed.searchParams.getAll('list').length > 0) {
    return { kind: 'playlist' }
  }
  return { kind: 'invalid' }
}
