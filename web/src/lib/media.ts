import { API_BASE } from './api'

/**
 * The two addresses on the api's `/media` surface, built in one place.
 *
 * URL construction stays out of components for the same reason `API_BASE`
 * does: the moment two of them build a media url, one of them escapes
 * differently and a screenshot with a space in its name stops loading in
 * exactly one view.
 */

/**
 * Where a content-root-relative media file is served — a `screenshot.path` or
 * a `frame.path` exactly as the api returned it.
 *
 * Each segment is escaped individually so that `/` keeps meaning "directory"
 * while spaces, `#` and `?` stop meaning anything at all. Nothing else is
 * rewritten: whether a path is allowed to be served is the api's containment
 * guard to answer, not the browser's, and a path this function had quietly
 * "cleaned up" would be a path no server-side rejection could warn about.
 *
 * Two spellings do get rewritten, both so that the api keeps the last word.
 * A leading `/` is stripped, because a root-relative path names the same file
 * with or without it and leaving it on produces `/media//…`, which the api
 * reads as an absolute path and refuses. And a `.` or `..` segment has its
 * dots percent-encoded, because `encodeURIComponent` leaves them alone and
 * the browser then resolves them away before the request is sent — the api
 * would never see the path it is supposed to refuse. Encoded, the segment
 * survives the trip and comes back as a named 400.
 */
export function mediaUrl(path: string): string {
  const escaped = path
    .replace(/^\/+/, '')
    .split('/')
    .map((segment) =>
      segment === '.' || segment === '..'
        ? segment.replace(/\./g, '%2E')
        : encodeURIComponent(segment),
    )
    .join('/')
  return `${API_BASE}/media/${escaped}`
}

/**
 * Where a meeting's recording is served.
 *
 * Id-addressed rather than path-addressed because no table carries a path to
 * the recording — the api resolves it through the meeting's source drop — so
 * the meeting id is the only handle the browser has or needs.
 */
export function recordingUrl(meetingId: string): string {
  return `${API_BASE}/media/recordings/${encodeURIComponent(meetingId)}`
}
