import type { SearchHit, SnippetRunModel } from '@/client/types.gen'

/**
 * Pure display helpers for a search hit.
 *
 * Split out of the component for the same reason `features/meetings/rows.ts`
 * is: these are the parts worth testing without rendering anything, and the
 * component stays about state and layout.
 *
 * The replay-affordance decision (`Affordance`, `safeHref`, `affordanceOf`)
 * and the offset formatter moved to `@/lib/affordance` in story 2.2, because
 * the moment view makes the same decision and features must not deep-import
 * each other. Re-exported here so this feature's callers and tests are
 * unchanged.
 */

export {
  type Affordance,
  affordanceOf,
  offsetLabel,
  safeHref,
} from '@/lib/affordance'
export { problemMessage } from '@/lib/problems'

/** How long the input waits after the last keystroke before it searches. */
export const DEBOUNCE_MS = 300

/** How long a search waits for the api before it names the timeout. */
export const SEARCH_TIMEOUT_MS = 8000

/** What names the meeting in the result header.
 *
 * An untitled meeting can reach the wire as `null` *or* as `""` — the column
 * is nullable and the projection writes `evidence.title or ""` — and a blank
 * header names nothing either way, so both fall back to the id.
 */
export function hitLabel(hit: SearchHit): string {
  const title = hit.meetingTitle?.trim()
  return title ? title : hit.meetingId
}

/**
 * The sentence for a failed search, and which kind of failure it was.
 *
 * The two need different words. A transport failure means the api was never
 * reached, and naming its address is the useful thing to say. An RFC 9457
 * problem response means the api answered and refused — it already carries a
 * `title` and a `detail` written for a person, and folding that into "cannot
 * reach the api" both misdiagnoses it and shows the reader raw JSON.
 */
export type SearchFailure = {
  kind: 'transport' | 'problem'
  message: string
}

/**
 * The plain text of a snippet, with no markup anywhere in the path.
 *
 * The api sends runs rather than a marked-up string (AD-15's principle: the
 * consumer renders from the array, it does not parse), so the visible snippet
 * is rendered run by run and this is what a caller uses when it needs the
 * words without the emphasis — an accessible label, a title attribute, an
 * assertion.
 */
export function snippetText(snippet: Array<SnippetRunModel>): string {
  return snippet.map((run) => run.text).join('')
}

/**
 * One hit's stable identity in a rendered list (story 4.4).
 *
 * A published-artifact hit and a moment hit can resolve to the *same* source
 * moment — that is the point of the evidence trail — so `momentId` alone is
 * no longer unique across a page of results. The artifact's own UUID is the
 * citation key everywhere else in the system, so it wins when present.
 */
export function hitKey(hit: SearchHit): string {
  return hit.artifactId ?? hit.momentId
}

/**
 * The kind badge for a published-artifact hit, or `null` for a moment hit.
 *
 * The api's `artifactKind` is the Postgres CHECK-constrained value
 * (`adr` / `action-item` today); the display name is decided here so a later
 * kind still renders — as itself — rather than as a blank badge.
 */
export function artifactBadge(hit: SearchHit): string | null {
  if (!hit.artifactId) return null
  if (hit.artifactKind === 'adr') return 'ADR'
  if (hit.artifactKind === 'action-item') return 'Action item'
  return hit.artifactKind ?? 'Artifact'
}
