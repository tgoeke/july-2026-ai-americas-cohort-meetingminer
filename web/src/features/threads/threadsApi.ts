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
  title: string
  /** Canonical UTC instant the meeting starts at. */
  occurredAt: string
  durationMs: number
  mentionCount: number
}

/** One moment at the moments tier. */
export interface TimelineMoment {
  momentId: string
  meetingId: string
  meetingTitle: string
  title: string
  /** Canonical UTC instant of the moment — the x this screen draws it at. */
  occurredAt: string
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

function requireString(row: Record<string, unknown>, key: string, where: string): string {
  const value = row[key]
  if (typeof value !== 'string' || value.length === 0) {
    throw new Error(`${where}: \`${key}\` must be a non-empty string`)
  }
  return value
}

function requireNumber(row: Record<string, unknown>, key: string, where: string): number {
  const value = row[key]
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new Error(`${where}: \`${key}\` must be a finite number`)
  }
  return value
}

function requireArray(body: unknown, key: string, where: string): Array<unknown> {
  if (Array.isArray(body)) return body
  if (isRecord(body) && Array.isArray(body[key])) return body[key] as Array<unknown>
  throw new Error(`${where}: expected an array of ${key}`)
}

function requireRow(value: unknown, where: string): Record<string, unknown> {
  if (!isRecord(value)) throw new Error(`${where}: each entry must be an object`)
  return value
}

/** An RFC 3339 instant as epoch ms; a value the platform cannot read refuses. */
export function instantOf(value: string, where: string): number {
  const t = Date.parse(value)
  if (Number.isNaN(t)) throw new Error(`${where}: \`${value}\` is not an RFC 3339 instant`)
  return t
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
      firstMentionAt: requireString(row, 'firstMentionAt', where),
      lastMentionAt: requireString(row, 'lastMentionAt', where),
      colorOrdinal: requireNumber(row, 'colorOrdinal', where),
    }
  })
}

/** A timeline body at one level → the drawable payload for that level. */
export function parseTimeline(level: TimelineLevel, body: unknown): TimelinePayload {
  const where = `GET /threads/{id}/timeline?level=${level}`
  if (level === 'bands') {
    return {
      level,
      buckets: requireArray(body, 'buckets', where).map((entry, i) => {
        const row = requireRow(entry, `${where}[${i}]`)
        return {
          from: requireString(row, 'from', `${where}[${i}]`),
          to: requireString(row, 'to', `${where}[${i}]`),
          mentionCount: requireNumber(row, 'mentionCount', `${where}[${i}]`),
        }
      }),
    }
  }
  if (level === 'meetings') {
    return {
      level,
      meetings: requireArray(body, 'meetings', where).map((entry, i) => {
        const row = requireRow(entry, `${where}[${i}]`)
        return {
          meetingId: requireString(row, 'meetingId', `${where}[${i}]`),
          title: requireString(row, 'title', `${where}[${i}]`),
          occurredAt: requireString(row, 'occurredAt', `${where}[${i}]`),
          durationMs: requireNumber(row, 'durationMs', `${where}[${i}]`),
          mentionCount: requireNumber(row, 'mentionCount', `${where}[${i}]`),
        }
      }),
    }
  }
  if (level === 'moments') {
    return {
      level,
      moments: requireArray(body, 'moments', where).map((entry, i) => {
        const row = requireRow(entry, `${where}[${i}]`)
        const speakers = row.speakers
        return {
          momentId: requireString(row, 'momentId', `${where}[${i}]`),
          meetingId: requireString(row, 'meetingId', `${where}[${i}]`),
          meetingTitle: requireString(row, 'meetingTitle', `${where}[${i}]`),
          title: requireString(row, 'title', `${where}[${i}]`),
          occurredAt: requireString(row, 'occurredAt', `${where}[${i}]`),
          startMs: requireNumber(row, 'startMs', `${where}[${i}]`),
          speakers: Array.isArray(speakers)
            ? speakers.filter((s): s is string => typeof s === 'string' && s.length > 0)
            : [],
        }
      }),
    }
  }
  throw new Error(`${where}: the evidence level is story 10.6a and is not drawn here`)
}

async function readJson(response: Response, url: string): Promise<unknown> {
  const text = await response.text()
  if (text.length === 0) return null
  try {
    return JSON.parse(text) as unknown
  } catch {
    throw new Error(`${url}: the api answered with a body that is not JSON`)
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

/** A request that carries both the caller's abort and this module's expiry. */
async function get(path: string, signal: AbortSignal | undefined): Promise<Response> {
  const expiry = new AbortController()
  const timer = setTimeout(() => expiry.abort(), THREADS_TIMEOUT_MS)
  try {
    const signals = signal === undefined ? [expiry.signal] : [signal, expiry.signal]
    return await fetch(`${API_BASE}${path}`, { signal: AbortSignal.any(signals) })
  } finally {
    clearTimeout(timer)
  }
}

/** Every thread in the corpus. */
export async function listThreads(
  signal?: AbortSignal,
): Promise<{ data?: Array<ThreadSummary>; error?: ThreadsFailure }> {
  try {
    const response = await get('/threads', signal)
    if (!response.ok) return { error: await refusalOf(response, 'GET /threads') }
    return { data: parseThreads(await readJson(response, 'GET /threads')) }
  } catch (err) {
    if (signal?.aborted === true) return {}
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
    const response = await get(path, signal)
    if (!response.ok) return { error: await refusalOf(response, `GET ${path}`) }
    return { data: parseTimeline(level, await readJson(response, `GET ${path}`)) }
  } catch (err) {
    if (signal?.aborted === true) return {}
    return { error: transportFailureOf(err) }
  }
}
