import { API_BASE } from '@/lib/api'

export interface ThreadOption {
  threadId: string
  name: string
}

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

/** Strict local seam for Story 10.3's generated `listThreads` operation. */
export function parseThreadsResponse(body: unknown): Array<ThreadOption> {
  const envelope = objectOf(body, 'the threads response')
  if (!Array.isArray(envelope.threads)) {
    throw new ThreadsContractError('the threads response.threads must be an array')
  }
  return envelope.threads.map((raw, index) => {
    const where = `threads[${index}]`
    const row = objectOf(raw, where)
    countOf(row, 'mentionCount', where)
    countOf(row, 'meetingCount', where)
    stringOf(row, 'firstMentionAt', where)
    stringOf(row, 'lastMentionAt', where)
    const ordinal = countOf(row, 'colorOrdinal', where)
    if (ordinal < 1) throw new ThreadsContractError(`${where}.colorOrdinal must be >= 1`)
    return {
      threadId: stringOf(row, 'threadId', where),
      name: stringOf(row, 'name', where),
    }
  })
}

export async function fetchThreadOptions(signal?: AbortSignal): Promise<Array<ThreadOption>> {
  const response = await fetch(`${API_BASE}/threads`, {
    headers: { Accept: 'application/json' },
    signal,
  })
  const body: unknown = await response.json().catch(() => null)
  if (!response.ok) throw new Error(`the threads endpoint refused the request (${response.status})`)
  return parseThreadsResponse(body)
}
