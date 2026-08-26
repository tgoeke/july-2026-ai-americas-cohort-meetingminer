import type { JobEvent, MeetingListItem } from '@/client/types.gen'

const SETTLED_STAGE_STATUSES = new Set(['done', 'skipped'])

/**
 * Apply one streamed event to the list.
 *
 * Returns `null` when the event names a job the list has never seen — a drop
 * submitted while this view was open. Its title, source and start time are not
 * on the stream, so the caller re-seeds rather than inventing a half-row.
 *
 * One rule governs the stage fields: **an event that names a stage carries
 * that stage's complete current reading, and both fields are written as
 * sent.** `error: null` is a real value, not "unspecified" — it is how a
 * requeue clears a recorded failure, and holding the previous text would leave
 * a resolved error on screen forever. `status` falls back to the held value
 * only as a guard against a payload that names a stage without one, which this
 * api never emits.
 */
export function applyEvent(
  rows: Array<MeetingListItem>,
  event: JobEvent,
): Array<MeetingListItem> | null {
  const index = rows.findIndex((row) => row.jobId === event.jobId)
  if (index < 0) return null

  const row = rows[index]
  const stages = event.stage
    ? row.stages.map((stage) =>
        stage.name === event.stage
          ? { ...stage, status: event.status ?? stage.status, error: event.error ?? null }
          : stage,
      )
    : row.stages

  const updated: MeetingListItem = {
    ...row,
    stages,
    status: event.jobStatus,
    // The gate is the api's to decide; every payload carries its verdict, so a
    // client that missed an event still converges on the next one.
    viewable: event.viewable,
    // The job row's own error, which is a different thing from a stage's: the
    // runner fails a job with no stage implicated (an unreadable drop, a
    // meeting mint that raised, video-evidence cleanup that failed), and that
    // text arrives on a `job.error` carrying no stage.
    error:
      event.jobStatus !== 'failed'
        ? null
        : event.event === 'job.error' && !event.stage
          ? (event.error ?? row.error ?? null)
          : row.error,
  }

  const next = rows.slice()
  next[index] = updated
  return next
}

/** Why this meeting cannot be opened yet, in the user's terms. */
export function blockedReason(row: MeetingListItem): string {
  const failed = row.stages.find((stage) => stage.status === 'failed')
  if (failed) return `Ingestion failed at ${failed.name} — nothing to open.`
  // A job can fail with no stage implicated at all, leaving every checkpoint
  // `queued`. Reading the stages alone would report evidence "still being
  // built" directly beside the rendered job error.
  if (row.status === 'failed') return 'Ingestion failed — nothing to open.'
  if (row.stages.length === 0) return 'Ingestion has not started — no checkpoints yet.'
  const pending = row.stages.find((stage) => !SETTLED_STAGE_STATUSES.has(stage.status))
  if (!pending) {
    // Every stage this row knows about has settled, yet the api says the
    // evidence bundle is not complete. Say exactly that rather than guessing.
    return 'Every stage has settled, but the api has not marked this meeting viewable.'
  }
  return `Evidence is still being built — ${pending.name} is ${pending.status}.`
}

export function meetingLabel(row: MeetingListItem): string {
  return row.title ?? row.sourceId
}

export function startedLabel(row: MeetingListItem): string | null {
  if (!row.startedAt) return null
  const started = new Date(row.startedAt)
  if (Number.isNaN(started.getTime())) return row.startedAt
  return row.startedAtPrecision === 'day'
    ? started.toLocaleDateString()
    : started.toLocaleString()
}

/**
 * A meeting's duration, in the reference UI's terse idiom: `1h 02m`, `42m`,
 * `35s`. Null when the api has not served one — a missing duration renders as
 * nothing, never as an invented `0m` (SPEC-ui-reimagine: every number is
 * served data).
 */
export function durationLabel(durationMs: number | null | undefined): string | null {
  if (durationMs == null || durationMs < 0) return null
  const totalSeconds = Math.round(durationMs / 1000)
  if (totalSeconds < 60) return `${totalSeconds}s`
  const totalMinutes = Math.round(totalSeconds / 60)
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60
  if (hours === 0) return `${totalMinutes}m`
  return `${hours}h ${String(minutes).padStart(2, '0')}m`
}

/**
 * The per-meeting evidence counts, in display order, keeping only what the
 * api actually served. An older api (or a row minted before the roll-up
 * fields existed) omits them, and an omitted count is not zero — it is
 * unknown, so it does not render.
 */
export function countParts(row: MeetingListItem): Array<string> {
  const parts: Array<[number | undefined, string, string]> = [
    [row.momentCount, 'moment', 'moments'],
    [row.screenshotCount, 'screen', 'screens'],
    [row.artifactCount, 'artifact', 'artifacts'],
    [row.participantCount, 'participant', 'participants'],
  ]
  return parts
    .filter(([count]) => count != null)
    .map(([count, one, many]) => `${count} ${count === 1 ? one : many}`)
}

export type MeetingSort = 'newest' | 'oldest'

/**
 * The card view over the canonical rows: filtered by corpus, ordered by
 * recency. Derived at render time so the SSE apply path keeps writing into
 * the unfiltered list — an event for a filtered-out meeting must still land.
 * Rows with no `startedAt` sort last either way; ties keep seed order.
 */
export function visibleRows(
  rows: Array<MeetingListItem>,
  corpusFilter: string | null,
  sort: MeetingSort,
): Array<MeetingListItem> {
  const filtered =
    corpusFilter === null ? rows : rows.filter((row) => row.corpus === corpusFilter)
  const time = (row: MeetingListItem): number | null => {
    if (!row.startedAt) return null
    const parsed = new Date(row.startedAt).getTime()
    return Number.isNaN(parsed) ? null : parsed
  }
  const direction = sort === 'newest' ? -1 : 1
  return filtered
    .map((row, index) => ({ row, index, at: time(row) }))
    .sort((a, b) => {
      if (a.at === null && b.at === null) return a.index - b.index
      if (a.at === null) return 1
      if (b.at === null) return -1
      return direction * (a.at - b.at) || a.index - b.index
    })
    .map(({ row }) => row)
}

/** The corpora present in the list, sorted, for the filter control. */
export function corporaOf(rows: Array<MeetingListItem>): Array<string> {
  return [...new Set(rows.map((row) => row.corpus))].sort()
}
