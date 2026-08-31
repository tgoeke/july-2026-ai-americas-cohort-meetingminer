/**
 * The Threads api, read through `fetch` rather than the generated client.
 *
 * Story 10.3 builds `GET /threads` and `GET /threads/{id}/timeline` in parallel
 * with this screen, so `web/src/client/` — which is generated from a running
 * api and committed — does not carry them yet. Rather than block, this module
 * states 10.3's acceptance-criteria field names as types and parses a response
 * against them, with a named refusal per shape violation. When the generated
 * client gains the operations, this is the one file that changes.
 *
 * Every parse refusal is deliberate: a body this screen cannot read is a
 * refusal box, never a half-drawn tier. Nothing is invented, interpolated, or
 * defaulted into existence — a moment must back everything drawn.
 */

import { API_BASE } from '@/lib/api'
import { problemMessage } from '@/lib/problems'

/** How long a thread or tier request is given before it is a transport failure. */
export const THREADS_TIMEOUT_MS = 8000

/** The levels `GET /threads/{id}/timeline` accepts (story 10.3). */
export type TimelineLevel = 'bands' | 'meetings' | 'moments' | 'evidence'

/** A row of `GET /threads`, in story 10.3's acceptance-criteria field names. */
export interface ThreadSummary {
  threadId: string
  name: string
  mentionCount: number
  meetingCount: number
  /** RFC 3339 UTC. */
  firstMentionAt: string
  /** RFC 3339 UTC. */
  lastMentionAt: string
  /** Immutable, assigned once, never recycled. The only source of colour. */
  colorOrdinal: number
}

/** One bucket of the bands tier. */
export interface BandBucket {
  from: string
  to: string
  mentionCount: number
}

/** One meeting on a band at the meetings tier. */
export interface TimelineMeeting {
  meetingId: string
  title: string | null
  /** Canonical UTC instant the meeting starts at. */
  occurredAt: string
  /** Last mention of this thread in the meeting, served by Story 10.3. */
  lastOccurredAt?: string
  /** Precision of the canonical wall-clock anchor. */
  occurredAtPrecision?: string
  durationMs: number
  mentionCount: number
}

/** One moment at the moments tier. */
export interface TimelineMoment {
  momentId: string
  meetingId: string
  meetingTitle?: string | null
  title: string
  /** Canonical UTC instant of the moment — the x this screen draws it at. */
  occurredAt: string
  occurredAtPrecision?: string
  /** Offset inside the recording. A replay offset, never a cross-meeting x. */
  startMs: number
  /** Named speakers, where diarization and naming have produced them. */
  speakers: Array<string>
}

/** A parsed timeline response, discriminated by the level asked for. */
export type TimelinePayload =
  | { level: 'bands'; buckets: Array<BandBucket> }
  | { level: 'meetings'; meetings: Array<TimelineMeeting> }
  | { level: 'moments'; moments: Array<TimelineMoment> }

/** A load or tier failure, kept apart so a refusal never reads as an outage. */
export type ThreadsFailure =
  | { kind: 'transport'; message: string }
  | { kind: 'problem'; message: string }

/** The transport failure's sentence, with the address that did not answer. */
export function transportFailureOf(error: unknown): ThreadsFailure {
  const detail = error instanceof Error ? error.message : String(error)
  return { kind: 'transport', message: `Cannot reach the api at ${API_BASE}: ${detail}` }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

class ThreadsContractError extends Error {}

function requireString(row: Record<string, unknown>, key: string, where: string): string {
  const value = row[key]
  if (typeof value !== 'string' || value.length === 0) {
    throw new ThreadsContractError(`${where}: \`${key}\` must be a non-empty string`)
  }
  return value
}

function requireNumber(row: Record<string, unknown>, key: string, where: string): number {
  const value = row[key]
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new ThreadsContractError(`${where}: \`${key}\` must be a finite number`)
  }
  return value
}

function requireArray(body: unknown, key: string, where: string): Array<unknown> {
  if (Array.isArray(body)) return body
  if (isRecord(body) && Array.isArray(body[key])) return body[key] as Array<unknown>
  throw new ThreadsContractError(`${where}: expected an array of ${key}`)
}

function requireRow(value: unknown, where: string): Record<string, unknown> {
  if (!isRecord(value)) throw new ThreadsContractError(`${where}: each entry must be an object`)
  return value
}

/** An RFC 3339 instant as epoch ms; a value the platform cannot read refuses. */
export function instantOf(value: string, where: string): number {
  const t = Date.parse(value)
  if (Number.isNaN(t)) {
    throw new ThreadsContractError(`${where}: \`${value}\` is not an RFC 3339 instant`)
  }
  return t
}

function requireInstant(row: Record<string, unknown>, key: string, where: string): string {
  const value = requireString(row, key, where)
  instantOf(value, `${where}: \`${key}\``)
  return value
}

function optionalString(row: Record<string, unknown>, key: string, where: string): string | undefined {
  if (!(key in row)) return undefined
  return requireString(row, key, where)
}

function timelineRows(
  body: unknown,
  liveKey: string,
  legacyKey: string,
  where: string,
): Array<unknown> {
  if (Array.isArray(body)) return body
  if (isRecord(body) && Array.isArray(body[liveKey])) return body[liveKey] as Array<unknown>
  return requireArray(body, legacyKey, where)
}

function requireLevel(body: unknown, level: TimelineLevel, where: string): void {
  if (!isRecord(body) || body.level === undefined) return
  if (body.level !== level) {
    throw new ThreadsContractError(`${where}: response level must be \`${level}\``)
  }
}

/** `GET /threads` → rows, refusing a body that is not 10.3's shape. */
export function parseThreads(body: unknown): Array<ThreadSummary> {
  const rows = requireArray(body, 'threads', 'GET /threads')
  return rows.map((entry, i) => {
    const where = `GET /threads[${i}]`
    const row = requireRow(entry, where)
    return {
      threadId: requireString(row, 'threadId', where),
      name: requireString(row, 'name', where),
      mentionCount: requireNumber(row, 'mentionCount', where),
      meetingCount: requireNumber(row, 'meetingCount', where),
      firstMentionAt: requireInstant(row, 'firstMentionAt', where),
      lastMentionAt: requireInstant(row, 'lastMentionAt', where),
      colorOrdinal: requireNumber(row, 'colorOrdinal', where),
    }
  })
}

/** A timeline body at one level → the drawable payload for that level. */
export function parseTimeline(level: TimelineLevel, body: unknown): TimelinePayload {
  const where = `GET /threads/{id}/timeline?level=${level}`
  requireLevel(body, level, where)
  if (level === 'bands') {
    return {
      level,
      buckets: timelineRows(body, 'bands', 'buckets', where).map((entry, i) => {
        const row = requireRow(entry, `${where}[${i}]`)
        const rowWhere = `${where}[${i}]`
        const from =
          row.startAt === undefined
            ? requireInstant(row, 'from', rowWhere)
            : requireInstant(row, 'startAt', rowWhere)
        const to =
          row.endAt === undefined
            ? requireInstant(row, 'to', rowWhere)
            : requireInstant(row, 'endAt', rowWhere)
        if (Date.parse(to) < Date.parse(from)) {
          throw new ThreadsContractError(`${rowWhere}: bucket end is before its start`)
        }
        return {
          from,
          to,
          mentionCount: requireNumber(row, 'mentionCount', rowWhere),
        }
      }),
    }
  }
  if (level === 'meetings') {
    return {
      level,
      meetings: requireArray(body, 'meetings', where).map((entry, i) => {
        const rowWhere = `${where}[${i}]`
        const row = requireRow(entry, rowWhere)
        const occurredAt = requireInstant(row, 'occurredAt', rowWhere)
        let lastOccurredAt: string
        let durationMs: number
        if (row.lastOccurredAt !== undefined) {
          lastOccurredAt = requireInstant(row, 'lastOccurredAt', rowWhere)
          durationMs = Date.parse(lastOccurredAt) - Date.parse(occurredAt)
          if (durationMs < 0) {
            throw new ThreadsContractError(`${rowWhere}: lastOccurredAt is before occurredAt`)
          }
        } else {
          durationMs = requireNumber(row, 'durationMs', rowWhere)
          lastOccurredAt = new Date(Date.parse(occurredAt) + durationMs).toISOString()
        }
        const title = row.title
        if (title !== null && (typeof title !== 'string' || title.length === 0)) {
          throw new ThreadsContractError(`${rowWhere}: \`title\` must be null or a non-empty string`)
        }
        return {
          meetingId: requireString(row, 'meetingId', rowWhere),
          title,
          occurredAt,
          lastOccurredAt,
          occurredAtPrecision: optionalString(row, 'occurredAtPrecision', rowWhere),
          durationMs,
          mentionCount: requireNumber(row, 'mentionCount', rowWhere),
        }
      }),
    }
  }
  if (level === 'moments') {
    if (isRecord(body) && body.truncated === true) {
      throw new ThreadsContractError(`${where}: response is truncated; narrow the timeline window`)
    }
    if (isRecord(body) && body.truncated !== undefined && typeof body.truncated !== 'boolean') {
      throw new ThreadsContractError(`${where}: \`truncated\` must be a boolean`)
    }
    return {
      level,
      moments: requireArray(body, 'moments', where).map((entry, i) => {
        const rowWhere = `${where}[${i}]`
        const row = requireRow(entry, rowWhere)
        const speakers = row.speakers
        if (
          speakers !== null &&
          (!Array.isArray(speakers) || speakers.some((speaker) => typeof speaker !== 'string'))
        ) {
          throw new ThreadsContractError(`${rowWhere}: \`speakers\` must be an array of strings`)
        }
        return {
          momentId: requireString(row, 'momentId', rowWhere),
          meetingId: requireString(row, 'meetingId', rowWhere),
          meetingTitle: optionalString(row, 'meetingTitle', rowWhere),
          title: requireString(row, 'title', rowWhere),
          occurredAt: requireInstant(row, 'occurredAt', rowWhere),
          occurredAtPrecision: optionalString(row, 'occurredAtPrecision', rowWhere),
          startMs: requireNumber(row, 'startMs', rowWhere),
          speakers:
            speakers === null
              ? []
              : (speakers as Array<string>).filter((speaker) => speaker.length > 0),
        }
      }),
    }
  }
  throw new ThreadsContractError(`${where}: the evidence level is story 10.6a and is not drawn here`)
}

async function readJson(response: Response, url: string): Promise<unknown> {
  const text = await response.text()
  if (text.length === 0) return null
  try {
    return JSON.parse(text) as unknown
  } catch {
    throw new ThreadsContractError(`${url}: the api answered with a body that is not JSON`)
  }
}

/** A non-2xx answer, said in the api's own words when it is RFC 9457. */
async function refusalOf(response: Response, url: string): Promise<ThreadsFailure> {
  let body: unknown = null
  try {
    body = await readJson(response, url)
  } catch {
    body = null
  }
  const message = problemMessage(body)
  return {
    kind: 'problem',
    message: message ?? `${url} answered ${response.status} ${response.statusText}`.trim(),
  }
}

/** A request whose expiry owns both headers and body consumption. */
async function withGet<T>(
  path: string,
  signal: AbortSignal | undefined,
  consume: (response: Response) => Promise<T>,
): Promise<T> {
  const expiry = new AbortController()
  const timer = setTimeout(() => expiry.abort(), THREADS_TIMEOUT_MS)
  try {
    const signals = signal === undefined ? [expiry.signal] : [signal, expiry.signal]
    const response = await fetch(`${API_BASE}${path}`, { signal: AbortSignal.any(signals) })
    return await consume(response)
  } finally {
    clearTimeout(timer)
  }
}

/** Every thread in the corpus. */
export async function listThreads(
  signal?: AbortSignal,
): Promise<{ data?: Array<ThreadSummary>; error?: ThreadsFailure }> {
  try {
    return await withGet('/threads', signal, async (response) => {
      if (!response.ok) return { error: await refusalOf(response, 'GET /threads') }
      return { data: parseThreads(await readJson(response, 'GET /threads')) }
    })
  } catch (err) {
    if (signal?.aborted === true) return {}
    if (err instanceof ThreadsContractError) return { error: { kind: 'problem', message: err.message } }
    return { error: transportFailureOf(err) }
  }
}

/** One thread's timeline at one level, over one window. */
export async function fetchTimeline(
  request: {
    threadId: string
    level: TimelineLevel
    from: number
    to: number
  },
  signal?: AbortSignal,
): Promise<{ data?: TimelinePayload; error?: ThreadsFailure }> {
  const { threadId, level, from, to } = request
  const query = new URLSearchParams({
    from: new Date(from).toISOString(),
    to: new Date(to).toISOString(),
    level,
  })
  const path = `/threads/${encodeURIComponent(threadId)}/timeline?${query.toString()}`
  try {
    return await withGet(path, signal, async (response) => {
      if (!response.ok) return { error: await refusalOf(response, `GET ${path}`) }
      return { data: parseTimeline(level, await readJson(response, `GET ${path}`)) }
    })
  } catch (err) {
    if (signal?.aborted === true) return {}
    if (err instanceof ThreadsContractError) return { error: { kind: 'problem', message: err.message } }
    return { error: transportFailureOf(err) }
  }
}
