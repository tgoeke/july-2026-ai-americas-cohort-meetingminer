import type { ParticipantRow } from '@/client/types.gen'
import { problemMessage, problemType } from '@/lib/problems'

/**
 * Pure display and decision helpers for the participants curation screen.
 *
 * Same split as `features/moments/moments.ts`: the parts worth testing
 * without rendering anything live here, the component stays about state and
 * layout. Named `curation.ts` rather than `participants.ts` (the spec's
 * literal name) because this directory's component is `Participants.tsx` —
 * on a case-insensitive filesystem (macOS default) a `participants.ts`
 * beside it makes TypeScript's module resolution nondeterministic between
 * the two, and it broke locally during this story's own build.
 */

/** How long a participants request waits for the api before it names the timeout. */
export const PARTICIPANTS_TIMEOUT_MS = 8000

/** Rows the api has not already merged away — the only valid rename target
 * and the only valid side of a new merge (server-enforced; this is the
 * client-side mirror so the picker never even offers an invalid choice). */
export function canonicalRows(rows: Array<ParticipantRow>): Array<ParticipantRow> {
  return rows.filter((row) => row.mergedIntoParticipantId == null)
}

/**
 * Group canonical rows by `normalizedName`, duplicate-hint groups only
 * (size > 1) — a client-side hint for a curator eyeballing likely merges, not
 * a server-side match (Never section: no bulk/fuzzy duplicate-detection
 * endpoint). Merged-away rows are excluded: they are already resolved and
 * would only clutter the hint with pairs already merged.
 */
export function groupByNormalizedName(
  rows: Array<ParticipantRow>,
): Array<{ normalizedName: string; rows: Array<ParticipantRow> }> {
  const byName = new Map<string, Array<ParticipantRow>>()
  for (const row of canonicalRows(rows)) {
    const existing = byName.get(row.normalizedName)
    if (existing) existing.push(row)
    else byName.set(row.normalizedName, [row])
  }
  return [...byName.entries()]
    .filter(([, group]) => group.length > 1)
    .map(([normalizedName, group]) => ({ normalizedName, rows: group }))
    .sort((a, b) => a.normalizedName.localeCompare(b.normalizedName))
}

/** How a participants request failed — same load/mutation split as
 * `features/moments/moments.ts`'s `MomentLoadFailure`. */
export type ParticipantsLoadFailure =
  | { kind: 'problem'; message: string }
  | { kind: 'transport'; message: string }

function stringify(error: unknown): string {
  if (error instanceof Error) return error.message
  if (typeof error === 'string') return error
  try {
    return JSON.stringify(error) ?? 'an unknown error'
  } catch {
    return 'an unknown error'
  }
}

/** Classify an answered refusal — the `error` half of an sdk result. */
export function loadFailureOf(error: unknown): ParticipantsLoadFailure {
  return { kind: 'problem', message: problemMessage(error) ?? stringify(error) }
}

/** Classify a thrown/rejected read — the api was never reached. */
export function transportFailureOf(error: unknown): ParticipantsLoadFailure {
  return { kind: 'transport', message: stringify(error) }
}

const ALREADY_MERGED_TYPE = 'urn:meetingminer:problem:already-merged'
const MERGE_TARGET_NOT_CANONICAL_TYPE = 'urn:meetingminer:problem:merge-target-not-canonical'
const NOT_FOUND_TYPE = 'urn:meetingminer:problem:not-found'

/**
 * The sentence a rename or merge mutation failure shows, one per problem
 * slug the I/O matrix names for the write routes. Falls back to the api's
 * own `problemMessage` for anything else (422 invalid-request, transport).
 */
export function problemCopy(error: unknown): string {
  const type = problemType(error)
  if (type === ALREADY_MERGED_TYPE) {
    return 'That participant was already merged away and can no longer be changed directly.'
  }
  if (type === MERGE_TARGET_NOT_CANONICAL_TYPE) {
    return 'The merge target was itself merged into someone else — merge onto its survivor instead.'
  }
  if (type === NOT_FOUND_TYPE) {
    return 'That participant no longer exists. Reload the list.'
  }
  return problemMessage(error) ?? stringify(error)
}
