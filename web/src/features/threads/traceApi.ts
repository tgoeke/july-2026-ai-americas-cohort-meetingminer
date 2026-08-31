/**
 * `GET /threads/suggestions` and `GET /threads/trace`, read strictly.
 *
 * Raw `fetch` rather than the generated client for the same reason
 * `threadsApi.ts` gives: `make client` regenerates `src/client/` from a running
 * api's OpenAPI document, and story 10.7 could not start one — a corpus ingest
 * was in flight against a paid extraction model. When the generated client next
 * gains `listThreadSuggestions` and `traceThread`, this is the one file that
 * changes.
 *
 * Every field is checked on the way in rather than cast. The parse is strict
 * because of what this view claims: a trace says in words whether it is the
 * whole history or a sample of it, and a payload that arrived without
 * `completenessNote` or with `mode` unset must be a refusal the reader can see,
 * never a screen that silently drops the sentence and keeps the timeline.
 */

import { API_BASE } from '@/lib/api'
import { problemMessage } from '@/lib/problems'

/** The api answers a trace from one query; 8s is the same budget 10.3 uses. */
export const TRACE_TIMEOUT_MS = 8000

export interface SubjectReach {
  meetingCount: number
  spanDays: number
  firstMentionAt: string
  lastMentionAt: string
}

export interface SuggestedSubject {
  threadId: string
  name: string
  colorOrdinal: number
  mentionCount: number
  reach: SubjectReach
}

export interface Suggestions {
  subjects: Array<SuggestedSubject>
  minMeetings: number
  maxMeetings: number
  minSpanDays: number
}

export interface SubjectCandidate {
  threadId: string
  name: string
  colorOrdinal: number
  meetingCount: number
  spanDays: number
}

export interface TraceMoment {
  momentId: string
  startMs: number
  occurredAt: string
  occurredAtPrecision: string
  speakers: Array<string>
  excerpt: string | null
  screenshotId: string | null
}

export interface TraceStop {
  meetingId: string
  title: string | null
  corpus: string
  hasRecording: boolean
  occurredAt: string
  lastOccurredAt: string
  occurredAtPrecision: string
  mentionCount: number
  momentCount: number
  quotedCount: number
  screenCount: number
  moments: Array<TraceMoment>
}

export interface TraceSpan {
  fromAt: string
  toAt: string
  days: number
  meetings: number
}

export interface TraceCounts {
  stops: number
  momentsQuoted: number
  mentionTotal: number
  meetingsMentioning: number
  withScreen: number
}

export interface RelatedSubject {
  threadId: string
  name: string
  colorOrdinal: number
  sharedMoments: number
}

export interface ThreadTrace {
  mode: 'exhaustive' | 'sample'
  label: string
  threadId: string | null
  colorOrdinal: number | null
  resolvedFrom: string | null
  ranking: 'hybrid' | 'keyword' | null
  complete: boolean
  completenessNote: string
  perMeetingLimit: number
  span: TraceSpan | null
  counts: TraceCounts
  candidates: Array<SubjectCandidate>
  relatedSubjects: Array<RelatedSubject>
  stops: Array<TraceStop>
}

export interface TraceFailure {
  kind: 'transport' | 'problem'
  message: string
}

export class TraceContractError extends Error {}

function object(value: unknown, where: string): Record<string, unknown> {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new TraceContractError(`${where}: expected an object`)
  }
  return value as Record<string, unknown>
}

function str(source: Record<string, unknown>, key: string, where: string): string {
  const value = source[key]
  if (typeof value !== 'string' || value.length === 0) {
    throw new TraceContractError(`${where}: \`${key}\` must be a non-empty string`)
  }
  return value
}

function optionalStr(
  source: Record<string, unknown>,
  key: string,
  where: string,
): string | null {
  const value = source[key]
  if (value === null || value === undefined) return null
  if (typeof value !== 'string') {
    throw new TraceContractError(`${where}: \`${key}\` must be a string or null`)
  }
  return value
}

function int(source: Record<string, unknown>, key: string, where: string): number {
  const value = source[key]
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new TraceContractError(`${where}: \`${key}\` must be a number`)
  }
  return value
}

function bool(source: Record<string, unknown>, key: string, where: string): boolean {
  const value = source[key]
  if (typeof value !== 'boolean') {
    throw new TraceContractError(`${where}: \`${key}\` must be a boolean`)
  }
  return value
}

function list(source: Record<string, unknown>, key: string, where: string): Array<unknown> {
  const value = source[key]
  if (!Array.isArray(value)) {
    throw new TraceContractError(`${where}: \`${key}\` must be an array`)
  }
  return value
}

export function parseSuggestions(body: unknown): Suggestions {
  const where = 'GET /threads/suggestions'
  const root = object(body, where)
  return {
    subjects: list(root, 'subjects', where).map((raw, index) => {
      const at = `${where}[${index}]`
      const subject = object(raw, at)
      const reach = object(subject['reach'], `${at}.reach`)
      return {
        threadId: str(subject, 'threadId', at),
        name: str(subject, 'name', at),
        colorOrdinal: int(subject, 'colorOrdinal', at),
        mentionCount: int(subject, 'mentionCount', at),
        reach: {
          meetingCount: int(reach, 'meetingCount', `${at}.reach`),
          spanDays: int(reach, 'spanDays', `${at}.reach`),
          firstMentionAt: str(reach, 'firstMentionAt', `${at}.reach`),
          lastMentionAt: str(reach, 'lastMentionAt', `${at}.reach`),
        },
      }
    }),
    minMeetings: int(root, 'minMeetings', where),
    maxMeetings: int(root, 'maxMeetings', where),
    minSpanDays: int(root, 'minSpanDays', where),
  }
}

function parseMoment(raw: unknown, at: string): TraceMoment {
  const moment = object(raw, at)
  return {
    momentId: str(moment, 'momentId', at),
    startMs: int(moment, 'startMs', at),
    occurredAt: str(moment, 'occurredAt', at),
    occurredAtPrecision: str(moment, 'occurredAtPrecision', at),
    speakers: list(moment, 'speakers', at).map((speaker, index) => {
      if (typeof speaker !== 'string') {
        throw new TraceContractError(`${at}.speakers[${index}]: expected a string`)
      }
      return speaker
    }),
    excerpt: optionalStr(moment, 'excerpt', at),
    screenshotId: optionalStr(moment, 'screenshotId', at),
  }
}

function parseStop(raw: unknown, at: string): TraceStop {
  const stop = object(raw, at)
  return {
    meetingId: str(stop, 'meetingId', at),
    title: optionalStr(stop, 'title', at),
    corpus: str(stop, 'corpus', at),
    hasRecording: bool(stop, 'hasRecording', at),
    occurredAt: str(stop, 'occurredAt', at),
    lastOccurredAt: str(stop, 'lastOccurredAt', at),
    occurredAtPrecision: str(stop, 'occurredAtPrecision', at),
    mentionCount: int(stop, 'mentionCount', at),
    momentCount: int(stop, 'momentCount', at),
    quotedCount: int(stop, 'quotedCount', at),
    screenCount: int(stop, 'screenCount', at),
    moments: list(stop, 'moments', at).map((moment, index) =>
      parseMoment(moment, `${at}.moments[${index}]`),
    ),
  }
}

export function parseTrace(body: unknown): ThreadTrace {
  const where = 'GET /threads/trace'
  const root = object(body, where)
  const mode = str(root, 'mode', where)
  if (mode !== 'exhaustive' && mode !== 'sample') {
    throw new TraceContractError(
      `${where}: \`mode\` must be "exhaustive" or "sample" — a trace that does` +
        ' not say which way in it took cannot state what it is showing',
    )
  }
  const ranking = optionalStr(root, 'ranking', where)
  if (ranking !== null && ranking !== 'hybrid' && ranking !== 'keyword') {
    throw new TraceContractError(`${where}: \`ranking\` must be hybrid, keyword or null`)
  }
  const rawSpan = root['span']
  const counts = object(root['counts'], `${where}.counts`)
  return {
    mode,
    label: str(root, 'label', where),
    threadId: optionalStr(root, 'threadId', where),
    colorOrdinal:
      root['colorOrdinal'] === null || root['colorOrdinal'] === undefined
        ? null
        : int(root, 'colorOrdinal', where),
    resolvedFrom: optionalStr(root, 'resolvedFrom', where),
    ranking,
    complete: bool(root, 'complete', where),
    // Never defaulted. A trace whose sentence went missing is a refusal, not a
    // timeline drawn without one.
    completenessNote: str(root, 'completenessNote', where),
    perMeetingLimit: int(root, 'perMeetingLimit', where),
    span:
      rawSpan === null || rawSpan === undefined
        ? null
        : {
            fromAt: str(object(rawSpan, `${where}.span`), 'fromAt', `${where}.span`),
            toAt: str(object(rawSpan, `${where}.span`), 'toAt', `${where}.span`),
            days: int(object(rawSpan, `${where}.span`), 'days', `${where}.span`),
            meetings: int(object(rawSpan, `${where}.span`), 'meetings', `${where}.span`),
          },
    counts: {
      stops: int(counts, 'stops', `${where}.counts`),
      momentsQuoted: int(counts, 'momentsQuoted', `${where}.counts`),
      mentionTotal: int(counts, 'mentionTotal', `${where}.counts`),
      meetingsMentioning: int(counts, 'meetingsMentioning', `${where}.counts`),
      withScreen: int(counts, 'withScreen', `${where}.counts`),
    },
    candidates: list(root, 'candidates', where).map((raw, index) => {
      const at = `${where}.candidates[${index}]`
      const candidate = object(raw, at)
      return {
        threadId: str(candidate, 'threadId', at),
        name: str(candidate, 'name', at),
        colorOrdinal: int(candidate, 'colorOrdinal', at),
        meetingCount: int(candidate, 'meetingCount', at),
        spanDays: int(candidate, 'spanDays', at),
      }
    }),
    relatedSubjects: list(root, 'relatedSubjects', where).map((raw, index) => {
      const at = `${where}.relatedSubjects[${index}]`
      const related = object(raw, at)
      return {
        threadId: str(related, 'threadId', at),
        name: str(related, 'name', at),
        colorOrdinal: int(related, 'colorOrdinal', at),
        sharedMoments: int(related, 'sharedMoments', at),
      }
    }),
    stops: list(root, 'stops', where).map((stop, index) =>
      parseStop(stop, `${where}.stops[${index}]`),
    ),
  }
}

function transportFailureOf(error: unknown): TraceFailure {
  return {
    kind: 'transport',
    message:
      `The api at ${API_BASE} could not be reached (${String(
        (error as Error)?.message ?? error,
      )}). Nothing is shown rather than a guess at what it would have said.`,
  }
}

async function readJson(response: Response): Promise<unknown> {
  const text = await response.text()
  try {
    return JSON.parse(text) as unknown
  } catch {
    throw new TraceContractError('the response body was not valid JSON')
  }
}

async function get<T>(
  path: string,
  parse: (body: unknown) => T,
  signal?: AbortSignal,
): Promise<{ data?: T; error?: TraceFailure }> {
  const timeout = new AbortController()
  const timer = setTimeout(() => timeout.abort(), TRACE_TIMEOUT_MS)
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      signal: signal ? AbortSignal.any([signal, timeout.signal]) : timeout.signal,
      headers: { accept: 'application/json' },
    })
    if (!response.ok) {
      let detail: unknown = null
      try {
        detail = await readJson(response)
      } catch {
        detail = null
      }
      // The api's own words when it gave any, its status when it did not.
      // Never a sentence this module invented about what probably went wrong.
      return {
        error: {
          kind: 'problem',
          message:
            problemMessage(detail) ??
            `the api refused the request (${response.status} ${response.statusText})`,
        },
      }
    }
    return { data: parse(await readJson(response)) }
  } catch (error) {
    // A caller that aborted asked for nothing; answering it with a refusal
    // would paint an error over a view the reader has already moved on from.
    if (signal?.aborted === true) return {}
    if (error instanceof TraceContractError) {
      return { error: { kind: 'problem', message: error.message } }
    }
    return { error: transportFailureOf(error) }
  } finally {
    clearTimeout(timer)
  }
}

export async function fetchSuggestions(
  signal?: AbortSignal,
): Promise<{ data?: Suggestions; error?: TraceFailure }> {
  return get('/threads/suggestions', parseSuggestions, signal)
}

export async function fetchTrace(
  query: { q?: string; threadId?: string },
  signal?: AbortSignal,
): Promise<{ data?: ThreadTrace; error?: TraceFailure }> {
  const params = new URLSearchParams()
  if (query.threadId !== undefined) params.set('threadId', query.threadId)
  else if (query.q !== undefined) params.set('q', query.q)
  return get(`/threads/trace?${params.toString()}`, parseTrace, signal)
}
