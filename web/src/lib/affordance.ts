/**
 * The replay-or-deep-link decision and its display helpers, shared by search
 * hits, the moment view, the drill-down, and chat citations.
 *
 * Moved out of `features/search/hits.ts` (story 2.2) because the moment view
 * makes the same decision and a feature must not deep-import a sibling
 * feature. `hits.ts` re-exports everything here so its callers and tests are
 * unchanged.
 *
 * Story 6.6 (UX-DR12) taught the decision about the source link's provider:
 * a YouTube link is offered *beside* replay, timed at the moment, while any
 * other host keeps story 2.2's "replay wins" rule.
 */

/**
 * A source deep link, classified by provider.
 *
 * `youtube` is the one provider whose link this app times to the moment
 * (UX-DR12): `href` already carries the `t` parameter when `offsetMs` is set,
 * and is the drop's URL untouched when it is `null` — a meeting-scoped link,
 * or a YouTube path whose time syntax has not been verified. `other` is every
 * remaining HTTP(S) host, offered exactly as the drop recorded it.
 */
export type SourceLink =
  | { provider: 'youtube'; href: string; offsetMs: number | null }
  | { provider: 'other'; href: string }

/**
 * A moment's replay affordance.
 *
 * Four states. `replay` is a meeting with a recording, where the player opens
 * at `startMs`; its `source` is the YouTube link to render beside the Replay
 * button, or `null` — another host's link is never offered next to replay
 * (story 2.2's rule, kept). `deepLink` is UX-DR11's transitional path: a
 * meeting with no replay evidence carries its source URL instead, and that
 * link is cleared once a recording arrives (AD-15). `inertLink` is a link the
 * app will not open, shown as text. `none` is a transcript-only meeting whose
 * drop carried no link either — it exists, and offering a dead button for it
 * would be worse than offering nothing.
 */
export type Affordance =
  | { kind: 'replay'; source: SourceLink | null }
  | { kind: 'deepLink'; source: SourceLink }
  | { kind: 'inertLink'; text: string }
  | { kind: 'none' }

/**
 * The schemes a source deep link may be rendered as a real `href` with.
 *
 * `sourceDeepLink` is copied from a trusted source drop and ends up inside an
 * `<a href>`. The trust boundary permits any absolute HTTP(S) source origin,
 * but `javascript:` and `data:` URLs in that position execute while `file:`
 * points at the reader's own disk. So the scheme is still checked here, and
 * anything else is shown as text.
 */
const SAFE_LINK_SCHEMES = ['http:', 'https:']

/** The link as an `href`, or `null` when it is not one this app will open. */
export function safeHref(raw: string | null | undefined): string | null {
  if (!raw) return null
  try {
    // Absolute only: a relative URL would resolve against *this* app's origin,
    // which is never where the source system lives.
    return SAFE_LINK_SCHEMES.includes(new URL(raw).protocol) ? raw : null
  } catch {
    return null
  }
}

/** `youtu.be`, `youtube.com`, or any `*.youtube.com` subdomain. */
function isYouTubeHost(hostname: string): boolean {
  return (
    hostname === 'youtu.be' || hostname === 'youtube.com' || hostname.endsWith('.youtube.com')
  )
}

/**
 * Whether `t=<seconds>` is a verified time syntax for this YouTube URL.
 *
 * Only the two forms whose time parameter is known are timed: `youtu.be/<id>`
 * and `youtube.com/watch`. Another path (`/shorts/`, `/embed/`, `/live/`)
 * is offered untimed rather than with an invented parameter.
 */
function hasTimedYouTubePath(url: URL): boolean {
  if (url.hostname === 'youtu.be') return /^\/[^/]+$/.test(url.pathname)
  return url.pathname === '/watch'
}

/** The offset clamped so a negative or NaN one opens at the start rather
 * than throwing or producing `t=NaN`. */
function clampOffsetMs(offsetMs: number): number {
  return Number.isFinite(offsetMs) && offsetMs > 0 ? offsetMs : 0
}

/**
 * Classify a source deep link and, for YouTube, time it at `offsetMs`.
 *
 * `null` when the link is empty or `safeHref` refuses its scheme — the caller
 * decides whether that is "inert text" or "nothing". The timed URL is built
 * by parsing with `URL` and `searchParams.set('t', …)`: replace-or-insert,
 * never string concatenation, so an existing `t` is replaced and a URL with
 * or without a query gets exactly one `t` (UX-DR12, story 6.6). A `#t=`
 * fragment — the only other carrier of a time — is dropped when `t` is set;
 * any other fragment is the drop's and survives. With `offsetMs === null`
 * (meeting scope) or an unverified path the drop's URL is returned verbatim.
 */
export function sourceLinkOf(
  raw: string | null | undefined,
  offsetMs: number | null = null,
): SourceLink | null {
  const href = safeHref(raw)
  if (href === null) return null
  const url = new URL(href)
  if (!isYouTubeHost(url.hostname)) return { provider: 'other', href }
  if (offsetMs === null || !hasTimedYouTubePath(url)) {
    return { provider: 'youtube', href, offsetMs: null }
  }
  const clamped = clampOffsetMs(offsetMs)
  url.searchParams.set('t', String(Math.floor(clamped / 1000)))
  if (/^#t=/i.test(url.hash)) url.hash = ''
  return { provider: 'youtube', href: url.toString(), offsetMs: clamped }
}

/** The anchor's accessible name: `Open on YouTube at 12:34`, `Open on
 * YouTube` (untimed), or the existing `Open in Stream` for any other host. */
export function sourceLinkLabel(link: SourceLink): string {
  if (link.provider === 'other') return 'Open in Stream'
  return link.offsetMs === null
    ? 'Open on YouTube'
    : `Open on YouTube at ${offsetLabel(link.offsetMs)}`
}

/** The two fields the decision reads — a `SearchHit`, a `MomentDetail`, and a
 * `MeetingDrilldownResponse` all satisfy it structurally. */
export interface ReplayEvidence {
  hasRecording: boolean
  sourceDeepLink?: string | null
}

/**
 * One decision for every consumer. `offsetMs` times a YouTube link at the
 * moment; `null` (the default) is meeting scope, where the link is untimed.
 */
export function affordanceOf(evidence: ReplayEvidence, offsetMs: number | null = null): Affordance {
  if (evidence.hasRecording) {
    // Replay first, the source second — and only YouTube's: another host's
    // link beside a recording is the stale-link case AD-15 clears, so the
    // recording wins (story 2.2's rule, now a tested branch rather than four
    // `if`s in four components).
    const source = sourceLinkOf(evidence.sourceDeepLink, offsetMs)
    return { kind: 'replay', source: source?.provider === 'youtube' ? source : null }
  }
  if (evidence.sourceDeepLink) {
    const source = sourceLinkOf(evidence.sourceDeepLink, offsetMs)
    // Shown but not offered: the drop recorded *something* here, and hiding it
    // would lose the only pointer back to the source. Rendering it as an
    // anchor would be worse than losing it.
    return source === null
      ? { kind: 'inertLink', text: evidence.sourceDeepLink }
      : { kind: 'deepLink', source }
  }
  return { kind: 'none' }
}

/** `1:04:09`, or `4:09` under an hour — the offset a citation is verified at. */
export function offsetLabel(startMs: number): string {
  if (!Number.isFinite(startMs) || startMs < 0) return '0:00'
  const total = Math.floor(startMs / 1000)
  const seconds = total % 60
  const minutes = Math.floor(total / 60) % 60
  const hours = Math.floor(total / 3600)
  const mm = hours > 0 ? String(minutes).padStart(2, '0') : String(minutes)
  return `${hours > 0 ? `${hours}:` : ''}${mm}:${String(seconds).padStart(2, '0')}`
}
