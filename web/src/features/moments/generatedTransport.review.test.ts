import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  FeedContractError,
  NO_FILTERS,
  fetchMomentsFeed,
} from './feed'
import {
  ThreadsContractError,
  fetchThreadOptions,
} from './threads'

const emptyFeed = (overrides: Record<string, unknown> = {}) => ({
  items: [],
  total: 0,
  corpusTotal: 0,
  limit: 24,
  offset: 0,
  ...overrides,
})

const json = (body: unknown) => new Response(JSON.stringify(body), {
  status: 200,
  headers: { 'Content-Type': 'application/json' },
})

afterEach(() => vi.unstubAllGlobals())

describe('C2-C6 generated transport contract', () => {
  it('requires equality when corpus is the only scope', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(json(emptyFeed({ corpusTotal: 24 })))))

    await expect(fetchMomentsFeed({ ...NO_FILTERS, corpus: 'real' }, 24, 0)).rejects.toThrow(
      'total must equal corpusTotal',
    )
  })

  it('classifies malformed successful feed JSON as a feed contract error', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response('{', {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))))

    await expect(fetchMomentsFeed(NO_FILTERS, 24, 0)).rejects.toBeInstanceOf(FeedContractError)
  })

  it('classifies malformed successful thread JSON as a threads contract error', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response('{', {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))))

    await expect(fetchThreadOptions()).rejects.toBeInstanceOf(ThreadsContractError)
  })

  it('sends the hidden meeting filter through the generated operation', async () => {
    const requests: Array<URL> = []
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      requests.push(new URL(input instanceof Request ? input.url : String(input)))
      return Promise.resolve(json(emptyFeed({ corpusTotal: 24 })))
    }))

    await fetchMomentsFeed({ ...NO_FILTERS, meeting: 'meeting-42' }, 24, 0)

    expect(requests).toHaveLength(1)
    expect(requests[0].pathname).toBe('/moments/feed')
    expect(requests[0].searchParams.get('meeting')).toBe('meeting-42')
    expect(requests[0].searchParams.get('limit')).toBe('24')
    expect(requests[0].searchParams.get('offset')).toBe('0')
  })

  it('forwards abort to the generated feed request', async () => {
    const aborted = vi.fn()
    let requestStarted!: () => void
    const started = new Promise<void>((resolve) => {
      requestStarted = resolve
    })
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => new Promise<Response>((_, reject) => {
      const signal = input instanceof Request ? input.signal : null
      requestStarted()
      signal?.addEventListener('abort', () => {
        aborted()
        reject(signal.reason)
      }, { once: true })
    })))
    const controller = new AbortController()

    const read = fetchMomentsFeed(NO_FILTERS, 24, 0, controller.signal)
    await started
    controller.abort(new Error('feed superseded'))

    await expect(read).rejects.toThrow('feed superseded')
    expect(aborted).toHaveBeenCalledOnce()
  })

  it('forwards abort to the generated thread request', async () => {
    const aborted = vi.fn()
    let requestStarted!: () => void
    const started = new Promise<void>((resolve) => {
      requestStarted = resolve
    })
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => new Promise<Response>((_, reject) => {
      const signal = input instanceof Request ? input.signal : null
      requestStarted()
      signal?.addEventListener('abort', () => {
        aborted()
        reject(signal.reason)
      }, { once: true })
    })))
    const controller = new AbortController()

    const read = fetchThreadOptions(controller.signal)
    await started
    controller.abort(new Error('catalog superseded'))

    await expect(read).rejects.toThrow('catalog superseded')
    expect(aborted).toHaveBeenCalledOnce()
  })
})
