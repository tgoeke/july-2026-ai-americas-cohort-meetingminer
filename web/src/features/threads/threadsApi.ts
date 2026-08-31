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
  /**
   * Whether `name` came from a human (story 10.2a) or from the derivation's
   * seed topic. The view labels the two differently: a reader must be able to
   * tell a curated name from a machine-derived one.
   */
  nameIsCurated: boolean
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
    const threadId = requireString(row, 'threadId', where)
    const name = requireString(row, 'name', where)
    const mentionCount = requireNumber(row, 'mentionCount', where)
    const meetingCount = requireNumber(row, 'meetingCount', where)
    const firstMentionAt = requireInstant(row, 'firstMentionAt', where)
    const lastMentionAt = requireInstant(row, 'lastMentionAt', where)
    const colorOrdinal = requireNumber(row, 'colorOrdinal', where)
    // Optional on the wire and defaulted to false: an api that predates
    // story 10.2a serves a corpus with no curation in it, which is exactly
    // what `false` says. Any non-boolean is a contract violation, not a
    // truthiness question.
    if (row.nameIsCurated !== undefined && typeof row.nameIsCurated !== 'boolean') {
      throw new ThreadsContractError(`${where}: \`nameIsCurated\` must be a boolean`)
    }
    const nameIsCurated = row.nameIsCurated === true
    if (Date.parse(lastMentionAt) < Date.parse(firstMentionAt)) {
      throw new ThreadsContractError(`${where}: lastMentionAt is before firstMentionAt`)
    }
    return {
      threadId,
      name,
      mentionCount,
      meetingCount,
      firstMentionAt,
      lastMentionAt,
      colorOrdinal,
      nameIsCurated,
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

/* --- story 10.2a: curation ------------------------------------------------
 *
 * Merge, split and rename. Three writes against api-owned curation tables —
 * the machine never renames, merges or splits on its own, and a correction
 * made here survives the next re-derivation because the worker resolves the
 * same rows before it writes (`domain/thread_curation.py`).
 *
 * These share `parseThreads`' discipline: a body this screen cannot read is a
 * named refusal, never a half-applied correction drawn as if it took.
 */

/** One of a thread's topics, as one meeting carries it. */
export interface ThreadTopic {
  topicId: string
  name: string
  /** Which leg attached it — `curated` where a human decided (story 10.2a). */
  linkedBy: string
}

/** The thread's topics grouped by the meeting they were discussed in. */
export interface ThreadTopicGroup {
  meetingId: string
  title: string | null
  /** RFC 3339 UTC; the split panel prints its date. */
  occurredAt: string
  topics: Array<ThreadTopic>
}

/** The curated thread a write returns. */
export interface CuratedThread {
  threadId: string
  name: string
  derivedName: string
  nameIsCurated: boolean
  colorOrdinal: number
  mergedIntoThreadId: string | null
}

function parseCuratedThread(body: unknown, where: string): CuratedThread {
  const row = requireRow(body, where)
  if (typeof row.nameIsCurated !== 'boolean') {
    throw new ThreadsContractError(`${where}: \`nameIsCurated\` must be a boolean`)
  }
  if (!Object.hasOwn(row, 'mergedIntoThreadId')) {
    throw new ThreadsContractError(`${where}: missing \`mergedIntoThreadId\``)
  }
  const mergedInto = row.mergedIntoThreadId
  if (mergedInto !== null && typeof mergedInto !== 'string') {
    throw new ThreadsContractError(`${where}: \`mergedIntoThreadId\` must be a string or null`)
  }
  return {
    threadId: requireString(row, 'threadId', where),
    name: requireString(row, 'name', where),
    derivedName: requireString(row, 'derivedName', where),
    nameIsCurated: row.nameIsCurated,
    colorOrdinal: requireNumber(row, 'colorOrdinal', where),
    mergedIntoThreadId: mergedInto,
  }
}

/** The meetings tier over the thread's own span, read for its topics only. */
export function parseThreadTopicGroups(body: unknown, where: string): Array<ThreadTopicGroup> {
  return requireArray(body, 'meetings', where).map((entry, i) => {
    const rowWhere = `${where}[${i}]`
    const row = requireRow(entry, rowWhere)
    const title = row.title
    if (title !== null && title !== undefined && typeof title !== 'string') {
      throw new ThreadsContractError(`${rowWhere}: \`title\` must be null or a string`)
    }
    const topics = row.topics
    if (!Array.isArray(topics)) {
      throw new ThreadsContractError(`${rowWhere}: \`topics\` must be an array`)
    }
    return {
      meetingId: requireString(row, 'meetingId', rowWhere),
      title: typeof title === 'string' && title.length > 0 ? title : null,
      occurredAt: requireInstant(row, 'occurredAt', rowWhere),
      topics: topics.map((topic, j) => {
        const topicWhere = `${rowWhere}.topics[${j}]`
        const t = requireRow(topic, topicWhere)
        return {
          topicId: requireString(t, 'topicId', topicWhere),
          name: requireString(t, 'name', topicWhere),
          linkedBy: requireString(t, 'linkedBy', topicWhere),
        }
      }),
    }
  })
}

/** A write's expiry owns both headers and body consumption, like `withGet`. */
async function withWrite<T>(
  method: 'PATCH' | 'POST',
  path: string,
  body: unknown,
  consume: (response: Response) => Promise<T>,
): Promise<T> {
  const expiry = new AbortController()
  const timer = setTimeout(() => expiry.abort(), THREADS_TIMEOUT_MS)
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      method,
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
      signal: expiry.signal,
    })
    return await consume(response)
  } finally {
    clearTimeout(timer)
  }
}

async function curationWrite(
  method: 'PATCH' | 'POST',
  path: string,
  body: unknown,
): Promise<{ data?: CuratedThread; error?: ThreadsFailure }> {
  try {
    return await withWrite(method, path, body, async (response) => {
      if (!response.ok) return { error: await refusalOf(response, `${method} ${path}`) }
      return {
        data: parseCuratedThread(await readJson(response, `${method} ${path}`), `${method} ${path}`),
      }
    })
  } catch (err) {
    if (err instanceof ThreadsContractError) return { error: { kind: 'problem', message: err.message } }
    return { error: transportFailureOf(err) }
  }
}

/**
 * Give a thread a human name, or clear one by passing `null`.
 *
 * Clearing restores whatever the machine currently calls the thread rather
 * than a name this client remembered — the api owns that value and it moves
 * with every derivation.
 */
export function renameThread(threadId: string, name: string | null) {
  return curationWrite('PATCH', `/threads/${encodeURIComponent(threadId)}`, { name })
}

/** Absorb one thread into another. Resolves to the survivor. */
export function mergeThreads(threadId: string, intoThreadId: string) {
  return curationWrite('POST', `/threads/${encodeURIComponent(threadId)}/merge`, {
    intoThreadId,
  })
}

/** Move the named topics onto a new thread of their own. */
export function splitThread(threadId: string, topicIds: Array<string>, name: string) {
  return curationWrite('POST', `/threads/${encodeURIComponent(threadId)}/split`, {
    topicIds,
    name,
  })
}

/**
 * The thread's topics, grouped by meeting — the split panel's checklist.
 *
 * No window is sent, so the api answers over the thread's own whole span
 * (story 10.3's default). A split must offer every topic the thread holds,
 * not only the ones inside whatever window the canvas happens to be showing:
 * a checklist that silently omitted the rest would make "split off these"
 * mean something different from what the user could see.
 */
export async function fetchThreadTopics(
  threadId: string,
  signal?: AbortSignal,
): Promise<{ data?: Array<ThreadTopicGroup>; error?: ThreadsFailure }> {
  const path = `/threads/${encodeURIComponent(threadId)}/timeline?level=meetings`
  try {
    return await withGet(path, signal, async (response) => {
      if (!response.ok) return { error: await refusalOf(response, `GET ${path}`) }
      return { data: parseThreadTopicGroups(await readJson(response, `GET ${path}`), `GET ${path}`) }
    })
  } catch (err) {
    if (signal?.aborted === true) return {}
    if (err instanceof ThreadsContractError) return { error: { kind: 'problem', message: err.message } }
    return { error: transportFailureOf(err) }
  }
}
