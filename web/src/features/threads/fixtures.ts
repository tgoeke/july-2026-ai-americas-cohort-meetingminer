/**
 * Fixture data at every level the Threads screen draws.
 *
 * The api (story 10.3) is built in parallel with this screen, so the acceptance
 * criteria call for fixture-driven web tests rather than a wait. These are
 * shaped to story 10.3's acceptance-criteria field names exactly.
 *
 * **Test-only.** No module the app ships imports this file — the screen draws
 * what the api serves and nothing else, and a fixture that leaked into the app
 * would be a moment-less thing on the canvas.
 */

import type {
  BandBucket,
  ThreadSummary,
  TimelineMeeting,
  TimelineMoment,
} from './threadsApi'

/** The corpus the mockups depict: 2026-03-01 to 2026-08-29. */
export const CORPUS_FROM = '2026-03-01T00:00:00Z'
export const CORPUS_TO = '2026-08-29T00:00:00Z'

export const RETRIEVAL_SPLIT: ThreadSummary = {
  threadId: 'th-retrieval-split',
  name: 'retrieval split',
  mentionCount: 47,
  meetingCount: 9,
  firstMentionAt: CORPUS_FROM,
  lastMentionAt: '2026-08-21T00:00:00Z',
  colorOrdinal: 1,
}

export const EVAL_HARNESS: ThreadSummary = {
  threadId: 'th-eval-harness',
  name: 'eval harness',
  mentionCount: 41,
  meetingCount: 8,
  firstMentionAt: '2026-03-08T00:00:00Z',
  lastMentionAt: '2026-08-17T00:00:00Z',
  colorOrdinal: 4,
}

/** Ordinal 9 — lap 2 of hue 1, so the swatch, not the name, carries the lap. */
export const SCREEN_LINEAGE: ThreadSummary = {
  threadId: 'th-screen-lineage',
  name: 'screen lineage',
  mentionCount: 15,
  meetingCount: 3,
  firstMentionAt: '2026-05-01T00:00:00Z',
  lastMentionAt: '2026-07-26T00:00:00Z',
  colorOrdinal: 9,
}

export const THREADS: Array<ThreadSummary> = [RETRIEVAL_SPLIT, EVAL_HARNESS, SCREEN_LINEAGE]

/** Weekly buckets, including empty ones — an empty week is a real span. */
export function bandsFor(counts: ReadonlyArray<number>, startIso = CORPUS_FROM): Array<BandBucket> {
  const start = Date.parse(startIso)
  const week = 604_800_000
  return counts.map((mentionCount, i) => ({
    from: new Date(start + i * week).toISOString(),
    to: new Date(start + (i + 1) * week).toISOString(),
    mentionCount,
  }))
}

export const RETRIEVAL_SPLIT_BANDS = bandsFor([4, 0, 9, 14, 2, 0, 11, 7])
export const EVAL_HARNESS_BANDS = bandsFor([4, 3, 0, 6, 12, 5, 0, 2])
export const SCREEN_LINEAGE_BANDS = bandsFor([0, 0, 5, 4, 0, 6, 0, 0])

/** The meeting Flow 6 zooms into, and two more on the same band. */
export const EMBEDDING_BAKE_OFF: TimelineMeeting = {
  meetingId: 'mt-embedding-bake-off',
  title: 'Embedding bake-off',
  occurredAt: '2026-05-13T15:00:00Z',
  durationMs: 5_400_000,
  mentionCount: 11,
}

export const RETRIEVAL_BAKE_OFF_REVIEW: TimelineMeeting = {
  meetingId: 'mt-retrieval-bake-off-review',
  title: 'Retrieval bake-off review',
  occurredAt: '2026-05-20T15:00:00Z',
  durationMs: 3_600_000,
  mentionCount: 6,
}

export const MEETINGS: Array<TimelineMeeting> = [EMBEDDING_BAKE_OFF, RETRIEVAL_BAKE_OFF_REVIEW]

function momentAt(
  id: string,
  offsetMs: number,
  title: string,
  speakers: Array<string>,
): TimelineMoment {
  return {
    momentId: id,
    meetingId: EMBEDDING_BAKE_OFF.meetingId,
    meetingTitle: EMBEDDING_BAKE_OFF.title,
    title,
    occurredAt: new Date(Date.parse(EMBEDDING_BAKE_OFF.occurredAt) + offsetMs).toISOString(),
    startMs: offsetMs,
    speakers,
  }
}

export const MOMENTS: Array<TimelineMoment> = [
  momentAt('mo-kickoff', 252_000, 'Kickoff: framing the bake-off', ['Priya Natarajan']),
  momentAt('mo-bm25-baseline', 707_000, 'BM25 baseline numbers reviewed', ['Tim Goeke']),
  momentAt('mo-candidates', 1_143_000, 'Embedding model candidates compared', []),
  momentAt('mo-hybrid-demo', 1_735_000, 'Hybrid retrieval prototype demo', ['Priya Natarajan']),
  momentAt('mo-why-bm25-wins', 3_849_000, 'Why BM25 wins on reused wording', ['Tim Goeke']),
  momentAt('mo-publish-gate', 4_722_000, 'Next steps for publish gate', []),
]

/** Two moments 32 seconds apart — one cell at anything coarser than 1.3 s/px. */
export const CLUSTERED_MOMENTS: Array<TimelineMoment> = [
  momentAt('mo-cluster-a', 2_240_000, 'Judge model shortlist', ['Tim Goeke']),
  momentAt('mo-cluster-b', 2_272_000, 'Judge model rejected', ['Priya Natarajan']),
]
