/**
 * The replay-or-deep-link decision and its display helpers, shared by search
 * hits and the moment view.
 *
 * Moved out of `features/search/hits.ts` (story 2.2) because the moment view
 * makes the same decision and a feature must not deep-import a sibling
 * feature. Behavior is identical; `hits.ts` re-exports everything here so its
 * callers and tests are unchanged.
 */

/**
 * A moment's replay affordance.
 *
 * Three states, not two. `replay` is a meeting with a recording, where the
 * player opens at `startMs`. `deepLink` is UX-DR11's transitional path: a
 * meeting with no replay evidence carries its source URL instead, and that
 * link is cleared once a recording arrives (AD-15). `none` is a
 * transcript-only meeting whose drop carried no link either — it exists, and
 * offering a dead button for it would be worse than offering nothing.
 */
export type Affordance =
  | { kind: 'replay' }
  | { kind: 'deepLink'; href: string }
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

/** The two fields the decision reads — a `SearchHit` and a `MomentDetail`
 * both satisfy it structurally. */
export interface ReplayEvidence {
  hasRecording: boolean
  sourceDeepLink?: string | null
}

export function affordanceOf(evidence: ReplayEvidence): Affordance {
  if (evidence.hasRecording) return { kind: 'replay' }
  if (evidence.sourceDeepLink) {
    const href = safeHref(evidence.sourceDeepLink)
    // Shown but not offered: the drop recorded *something* here, and hiding it
    // would lose the only pointer back to the source. Rendering it as an
    // anchor would be worse than losing it.
    return href === null
      ? { kind: 'inertLink', text: evidence.sourceDeepLink }
      : { kind: 'deepLink', href }
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
