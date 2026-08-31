import '@/lib/api'
import { listThreads } from '@/client/sdk.gen'
import type { ThreadSummary, ThreadsResponse } from '@/client/types.gen'

export type ThreadOption = Pick<ThreadSummary, 'threadId' | 'name'>

export const THREADS_TIMEOUT_MS = 8000

export class ThreadsContractError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'ThreadsContractError'
  }
}

function objectOf(raw: unknown, where: string): Record<string, unknown> {
  if (raw === null || typeof raw !== 'object') {
    throw new ThreadsContractError(`${where} must be an object`)
  }
  return raw as Record<string, unknown>
}

function stringOf(row: Record<string, unknown>, key: string, where: string): string {
  const value = row[key]
  if (typeof value !== 'string' || value.trim() === '') {
    throw new ThreadsContractError(`${where}.${key} must be a non-empty string`)
  }
  return value
}

function countOf(row: Record<string, unknown>, key: string, where: string): number {
  const value = row[key]
  if (!Number.isInteger(value) || (value as number) < 0) {
    throw new ThreadsContractError(`${where}.${key} must be an integer >= 0`)
  }
  return value as number
}

function timestampOf(row: Record<string, unknown>, key: string, where: string): string {
  const value = stringOf(row, key, where)
  if (!/^\d{4}-\d{2}-\d{2}T/.test(value) || !Number.isFinite(Date.parse(value))) {
    throw new ThreadsContractError(`${where}.${key} must be an RFC 3339 timestamp`)
  }
  return value
}

/** Strict runtime seam around Story 10.3's generated thread response. */
export function parseThreadsResponse(body: unknown): Array<ThreadOption> {
  const envelope = objectOf(body, 'the threads response')
  if (!Array.isArray(envelope.threads)) {
    throw new ThreadsContractError('the threads response.threads must be an array')
  }
  const seen = new Set<string>()
  const threads: ThreadsResponse['threads'] = envelope.threads.map((raw, index) => {
    const where = `threads[${index}]`
    const row = objectOf(raw, where)
    const mentionCount = countOf(row, 'mentionCount', where)
    const meetingCount = countOf(row, 'meetingCount', where)
    const first = timestampOf(row, 'firstMentionAt', where)
    const last = timestampOf(row, 'lastMentionAt', where)
    if (Date.parse(first) > Date.parse(last)) {
      throw new ThreadsContractError(`${where}.firstMentionAt must not follow lastMentionAt`)
    }
    const ordinal = countOf(row, 'colorOrdinal', where)
    if (ordinal < 1) throw new ThreadsContractError(`${where}.colorOrdinal must be >= 1`)
    const threadId = stringOf(row, 'threadId', where)
    if (seen.has(threadId)) throw new ThreadsContractError(`${where}: duplicate threadId`)
    seen.add(threadId)
    return {
      threadId,
      name: stringOf(row, 'name', where),
      mentionCount,
      meetingCount,
      firstMentionAt: first,
      lastMentionAt: last,
      colorOrdinal: ordinal,
    }
  })
  return threads.map(({ threadId, name }) => ({ threadId, name }))
}

export async function fetchThreadOptions(signal?: AbortSignal): Promise<Array<ThreadOption>> {
  const result = await listThreads({ signal, parseAs: 'json' })
  if (result.error !== undefined) {
    if (result.response?.ok) {
      throw new ThreadsContractError('the threads response must be valid JSON')
    }
    if (result.response === undefined) {
      if (result.error instanceof Error) throw result.error
      throw new Error(String(result.error))
    }
    throw new Error(`the threads endpoint refused the request (${result.response.status})`)
  }
  return parseThreadsResponse(result.data)
}
