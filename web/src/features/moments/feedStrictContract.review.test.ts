import { describe, expect, it } from 'vitest'
import { FeedContractError, parseFeedResponse } from './feed'

function rawItem() {
  return {
    momentId: 'moment-1',
    meetingId: 'meeting-1',
    meetingTitle: 'Review',
    startedAt: '2026-08-31T12:00:00Z',
    startedAtPrecision: 'second',
    startMs: 1_000,
    endMs: 2_000,
    corpus: 'real',
    hasRecording: true,
    sourceDeepLink: null,
    screenshotId: null,
    viewType: null,
    preview: null,
    threads: [],
    reasons: [
      {
        kind: 'due',
        label: 'due 2026-09-01',
        ref: 'artifact-1',
        at: '2026-09-01T00:00:00Z',
      },
    ],
  }
}

function page(item: Record<string, unknown> = rawItem()) {
  return { items: [item], total: 1, corpusTotal: 1, limit: 24, offset: 0 }
}

describe('review F2 — the strict reader enforces Story 10.4', () => {
  it('preserves the endpoint timestamp spelling', () => {
    expect(parseFeedResponse(page()).items[0].reasons[0].at).toBe(
      '2026-09-01T00:00:00Z',
    )
  })

  it.each([
    [{ ...rawItem(), corpus: undefined }, 'corpus'],
    [{ ...rawItem(), hasRecording: 'yes' }, 'hasRecording'],
    [{ ...rawItem(), threads: undefined }, 'threads'],
    [{ ...rawItem(), reasons: [{ kind: 'topic', label: 'not declared' }] }, 'kind'],
    [{ ...rawItem(), reasons: [{ kind: 'risk', label: '   ' }] }, 'label'],
  ])('refuses a malformed required item field', (item, field) => {
    expect(() => parseFeedResponse(page(item))).toThrow(FeedContractError)
    expect(() => parseFeedResponse(page(item))).toThrow(String(field))
  })

  it.each([
    [{ items: [rawItem()], total: -1, corpusTotal: 1, limit: 24, offset: 0 }, 'total'],
    [{ items: [rawItem()], total: 1, corpusTotal: 1, limit: 0, offset: 0 }, 'limit'],
    [{ items: [rawItem()], total: 1, corpusTotal: 1, limit: 24, offset: -1 }, 'offset'],
  ])('refuses a malformed paging envelope', (body, field) => {
    expect(() => parseFeedResponse(body)).toThrow(String(field))
  })
})
