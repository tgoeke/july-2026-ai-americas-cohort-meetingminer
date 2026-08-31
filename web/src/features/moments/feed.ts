import { API_BASE } from '@/lib/api'
import { offsetLabel } from '@/lib/affordance'

/**
 * The Moments feed's wire shape, its reader, and the pure display decisions
 * the front door is built from (story 10.5, FR40, UX-DR16/17).
 *
 * Same split as `features/meetings/rows.ts` and `features/search/hits.ts`:
 * everything worth testing without rendering lives here, and the components
 * stay about state and layout.
 *
 * **Why a hand-written reader rather than the generated sdk.** `GET
 * /moments/feed` is story 10.4, built in parallel with this screen, so
 * `client/sdk.gen.ts` carries no operation for it yet and regenerating it here
 * would fight that lane for the same file. The field names below are 10.4's
 * acceptance criteria verbatim; when the api lands and the client is
 * regenerated, `fetchMomentsFeed` collapses into the generated call and
 * nothing else on this screen moves.
 */

/** The api's `MomentArtifact.kind` vocabulary — the seven publishable kinds. */
export const ARTIFACT_KINDS = [
  'decision',
  'adr',
  'action-item',
  'story',
  'requirement',
  'bug-fix',
  'change-request',
] as const

export type ArtifactKind = (typeof ARTIFACT_KINDS)[number]

const SIGNAL_REASON_KINDS = ['due', 'risk', 'question', 'recency', 'published', 'thread'] as const
const REASON_KINDS: ReadonlySet<string> = new Set([...ARTIFACT_KINDS, ...SIGNAL_REASON_KINDS])

/** Whether a reason's `kind` is one of the seven artifact kinds — the only
 * kinds that may ever be drawn as a kind chip (`DESIGN.md` · Moment kinds). */
export function isArtifactKind(kind: string): kind is ArtifactKind {
  return (ARTIFACT_KINDS as ReadonlyArray<string>).includes(kind)
}

/**
 * One ranking reason, exactly as story 10.4 serves it. `kind` is an artifact
 * kind or one of the ranking-signal kinds (`due | risk | question | recency |
 * published | thread`); `label` is the sentence to render verbatim — this
 * client never composes a reason.
 */
export interface FeedReason {
  kind: string
  label: string
  ref?: string | null
  at?: string | null
}

/** A thread the moment belongs to. `colorOrdinal` is the persisted immutable
 * ordinal that decides the hue — never list position (`DESIGN.md` · Threads). */
export interface FeedThread {
  threadId: string
  name: string
  colorOrdinal: number | null
}

/** One ranked moment. Field names are story 10.4's acceptance criteria. */
export interface MomentFeedItem {
  momentId: string
  meetingId: string
  meetingTitle: string | null
  startedAt: string | null
  startedAtPrecision?: string | null
  startMs: number
  endMs?: number | null
  corpus: string
  hasRecording: boolean
  sourceDeepLink?: string | null
  screenshotId: string | null
  viewType: string | null
  preview: string | null
  threads: Array<FeedThread>
  reasons: Array<FeedReason>
}

/** The paged envelope. `total` is filtered; `unfilteredTotal` is the same
 * eligible set before any optional feed filter is applied. */
export interface MomentFeedResponse {
  items: Array<MomentFeedItem>
  total: number
  unfilteredTotal: number
  limit: number
  offset: number
}

/** One page of the feed — the "Show 24 more" step and the api's default. */
export const FEED_PAGE_SIZE = 24

/** How long a feed read waits before it names the timeout, matching
 * `MOMENT_TIMEOUT_MS` on the moment view. */
export const FEED_TIMEOUT_MS = 8000

/** The three filters the feed is narrowed by, plus the hidden meeting filter
 * set when arriving from a meeting. `null` is "any". */
export interface FeedFilters {
  corpus: string | null
  thread: string | null
  kind: string | null
  meeting: string | null
}

export const NO_FILTERS: FeedFilters = { corpus: null, thread: null, kind: null, meeting: null }

/** Whether anything is narrowing the feed — decides `Moments 6 of 24` versus
 * `Moments 24`, and which empty sentence is honest. */
export function hasActiveFilters(filters: FeedFilters): boolean {
  return (
    filters.corpus !== null ||
    filters.thread !== null ||
    filters.kind !== null ||
    filters.meeting !== null
  )
}

/**
 * The query string for one page. Filters are URL query params on this screen
 * so a filtered view is a link (EXPERIENCE.md · Filters row); they are passed
 * through to the api under the same names story 10.4 accepts.
 */
export function feedSearchParams(
  filters: FeedFilters,
  limit: number,
  offset: number,
): URLSearchParams {
  const params = new URLSearchParams()
  if (filters.corpus !== null) params.set('corpus', filters.corpus)
  if (filters.thread !== null) params.set('thread', filters.thread)
  if (filters.kind !== null) params.set('kind', filters.kind)
  if (filters.meeting !== null) params.set('meeting', filters.meeting)
  params.set('limit', String(limit))
  params.set('offset', String(offset))
  return params
}

/**
 * A feed page the client refuses to render.
 *
 * Story 10.4 validates reasons *before* pagination and drops an item with no
 * valid reason, so `items`, `total` and the offsets are computed only from
 * serializable rows. An item that escapes that guard would silently make the
 * header count a lie, so it is one page-level error here rather than a card
 * quietly rendered without the thing that justifies its rank
 * (EXPERIENCE.md · Reason line).
 */
export class FeedContractError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'FeedContractError'
  }
}

function requireString(row: Record<string, unknown>, key: string, where: string): string {
  const value = row[key]
  if (typeof value !== 'string' || value.trim() === '') {
    throw new FeedContractError(`${where}: ${key} must be a non-empty string`)
  }
  return value
}

function optionalString(row: Record<string, unknown>, key: string): string | null {
  const value = row[key]
  return typeof value === 'string' ? value : null
}

function requireNumber(row: Record<string, unknown>, key: string, where: string): number {
  const value = row[key]
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new FeedContractError(`${where}: ${key} must be a number`)
  }
  return value
}

function requireBoolean(row: Record<string, unknown>, key: string, where: string): boolean {
  const value = row[key]
  if (typeof value !== 'boolean') {
    throw new FeedContractError(`${where}: ${key} must be a boolean`)
  }
  return value
}

function requireArray(row: Record<string, unknown>, key: string, where: string): Array<unknown> {
  const value = row[key]
  if (!Array.isArray(value)) {
    throw new FeedContractError(`${where}: ${key} must be an array`)
  }
  return value
}

function requirePageInteger(
  row: Record<string, unknown>,
  key: string,
  minimum: number,
): number {
  const value = row[key]
  if (!Number.isInteger(value) || (value as number) < minimum) {
    throw new FeedContractError(`the feed response: ${key} must be an integer >= ${minimum}`)
  }
  return value as number
}

function reasonOf(raw: unknown, where: string): FeedReason {
  if (raw === null || typeof raw !== 'object') {
    throw new FeedContractError(`${where}: each reason must be an object`)
  }
  const row = raw as Record<string, unknown>
  const kind = requireString(row, 'kind', where)
  if (!REASON_KINDS.has(kind)) {
    throw new FeedContractError(`${where}: kind must be a declared reason kind`)
  }
  const at = row.at
  if (at !== undefined && at !== null && typeof at !== 'string') {
    throw new FeedContractError(`${where}: at must be an RFC 3339 string or null`)
  }
  return {
    kind,
    label: requireString(row, 'label', where),
    ref: optionalString(row, 'ref'),
    at: at ?? null,
  }
}

function threadOf(raw: unknown, where: string): FeedThread {
  if (raw === null || typeof raw !== 'object') {
    throw new FeedContractError(`${where}: each thread must be an object`)
  }
  const row = raw as Record<string, unknown>
  return {
    threadId: requireString(row, 'threadId', where),
    name: requireString(row, 'name', where),
    colorOrdinal:
      row.colorOrdinal === null ? null : requireNumber(row, 'colorOrdinal', where),
  }
}

function itemOf(raw: unknown, index: number): MomentFeedItem {
  const where = `items[${index}]`
  if (raw === null || typeof raw !== 'object') {
    throw new FeedContractError(`${where}: each item must be an object`)
  }
  const row = raw as Record<string, unknown>
  const reasons = requireArray(row, 'reasons', where).map((reason) => reasonOf(reason, where))
  if (reasons.length === 0) {
    // The card's whole promise is that it says why it is here.
    throw new FeedContractError(`${where}: reasons[] must be non-empty`)
  }
  return {
    momentId: requireString(row, 'momentId', where),
    meetingId: requireString(row, 'meetingId', where),
    meetingTitle: optionalString(row, 'meetingTitle'),
    startedAt: optionalString(row, 'startedAt'),
    startedAtPrecision: optionalString(row, 'startedAtPrecision'),
    startMs: requireNumber(row, 'startMs', where),
    endMs: typeof row.endMs === 'number' ? row.endMs : null,
    corpus: requireString(row, 'corpus', where),
    hasRecording: requireBoolean(row, 'hasRecording', where),
    sourceDeepLink: optionalString(row, 'sourceDeepLink'),
    screenshotId: optionalString(row, 'screenshotId'),
    viewType: optionalString(row, 'viewType'),
    preview: optionalString(row, 'preview'),
    threads: requireArray(row, 'threads', where).map((thread) => threadOf(thread, where)),
    reasons,
  }
}

/** Read a feed body into the typed envelope, or refuse it by name. */
export function parseFeedResponse(body: unknown): MomentFeedResponse {
  if (body === null || typeof body !== 'object') {
    throw new FeedContractError('the feed response must be an object')
  }
  const row = body as Record<string, unknown>
  if (!Array.isArray(row.items)) {
    throw new FeedContractError('the feed response must carry an items array')
  }
  const items = row.items.map(itemOf)
  const total = requirePageInteger(row, 'total', 0)
  const unfilteredTotal = requirePageInteger(row, 'unfilteredTotal', 0)
  const limit = requirePageInteger(row, 'limit', 1)
  const offset = requirePageInteger(row, 'offset', 0)
  if (offset + items.length > total) {
    throw new FeedContractError('the feed response: offset + items.length must not exceed total')
  }
  if (total > unfilteredTotal) {
    throw new FeedContractError('the feed response: total must not exceed unfilteredTotal')
  }
  return { items, total, unfilteredTotal, limit, offset }
}

/**
 * One page of the ranked feed.
 *
 * A refusal body is RFC 9457 like every other api error, so the caller reads
 * it with `problemMessage()`; a transport failure throws and the caller names
 * `API_BASE` in the sentence, as every other screen does.
 */
export async function fetchMomentsFeed(
  filters: FeedFilters,
  limit: number,
  offset: number,
  signal?: AbortSignal,
): Promise<MomentFeedResponse> {
  const query = feedSearchParams(filters, limit, offset)
  const response = await fetch(`${API_BASE}/moments/feed?${query.toString()}`, {
    headers: { Accept: 'application/json' },
    signal,
  })
  const body: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    // Thrown with the problem body attached so the caller can run it through
    // `problemMessage()` — the same shape the generated sdk hands back.
    throw Object.assign(new Error(`the feed refused the request (${response.status})`), {
      problem: body,
    })
  }
  const page = parseFeedResponse(body)
  if (page.limit !== limit || page.offset !== offset) {
    throw new FeedContractError('the feed response page does not match the request')
  }
  if (!hasActiveFilters(filters) && page.total !== page.unfilteredTotal) {
    throw new FeedContractError(
      'the unfiltered feed response: total must equal unfilteredTotal',
    )
  }
  return page
}

/**
 * Where an opaque `screenshotId` is served (AD-17, story 10.4's route).
 *
 * ID-addressed, never a storage path: the feed serves an id precisely so the
 * browser never learns where a file lives on disk. Kept in this module rather
 * than `lib/media.ts` because the id-addressed media route arrives with the
 * feed; when a second screen needs it, it moves down to `lib/media.ts`.
 */
export function screenshotUrl(screenshotId: string): string {
  return `${API_BASE}/media/files/${encodeURIComponent(screenshotId)}`
}

/**
 * The counted section header (`DESIGN.md` · Section header): `Moments 24`
 * unfiltered, `Moments 6 of 24` once a filter narrows it.
 */
export function momentsHeaderCount(
  total: number,
  unfilteredTotal: number,
  filtered: boolean,
): string {
  return filtered && total !== unfilteredTotal
    ? `${total} of ${unfilteredTotal}`
    : String(unfilteredTotal)
}

/** The ISO date a moment is dated by — `2026-08-14` — or `null` when the api
 * served no start. Day-precision dates never show a time, so only the date
 * half of an RFC 3339 value is ever rendered. */
export function isoDateOf(startedAt: string | null | undefined): string | null {
  if (!startedAt) return null
  const match = /^(\d{4}-\d{2}-\d{2})/.exec(startedAt)
  return match ? match[1] : null
}

/**
 * The card's meta line: `2026-08-14 · 12:40–14:05 · real`.
 *
 * Every part is a served value, and a part the api did not serve is left out
 * rather than filled in — a card for a meeting with no recorded start reads
 * `12:40 · real`, never `unknown · 12:40 · real`.
 */
export function cardMetaLabel(item: MomentFeedItem): string {
  const parts: Array<string> = []
  const date = isoDateOf(item.startedAt)
  if (date !== null) parts.push(date)
  const span =
    typeof item.endMs === 'number' && item.endMs > item.startMs
      ? `${offsetLabel(item.startMs)}–${offsetLabel(item.endMs)}`
      : offsetLabel(item.startMs)
  parts.push(span)
  if (item.corpus !== '') parts.push(item.corpus)
  return parts.join(' · ')
}

/** The chip over the screenshot: `slide · 12:40`, or just the offset when the
 * api served no view type. */
export function offsetChipLabel(item: MomentFeedItem): string {
  const offset = offsetLabel(item.startMs)
  const view = item.viewType?.trim()
  return view ? `${view} · ${offset}` : offset
}

/** A screenshot's `alt`: `<viewType> at <offset>, <meetingTitle>`
 * (EXPERIENCE.md · Accessibility Floor). */
export function screenshotAlt(item: MomentFeedItem): string {
  const view = item.viewType?.trim() || 'screenshot'
  const title = item.meetingTitle?.trim()
  const anchor = `${view} at ${offsetLabel(item.startMs)}`
  return title ? `${anchor}, ${title}` : anchor
}

/** The sentence a frame with no screenshot carries (State Patterns · Card
 * without screenshot). */
export const NO_SCREENSHOT = 'No screenshot — transcript-anchored moment.'

/** The action row of a moment with neither recording nor source link (State
 * Patterns · Card without recording). */
export const TRANSCRIPT_ONLY = 'Transcript only — no recording and no source link.'

/** Cold load (State Patterns · Moments): no skeleton cards, because a
 * skeleton is an invented card. */
export const RANKING_SENTENCE = 'Ranking the corpus…'

/** Empty corpus (State Patterns · Moments). */
export const EMPTY_CORPUS =
  'No moments yet. Add a meeting — Moments fills once one is ingested.'

/** The signals the ranking uses, as nouns (Voice and Tone). */
export const RANKED_BY = 'ranked by decision, due date, recency, thread'

/**
 * The filter-empty sentence, naming the active filters:
 * `No moments match corpus real · thread #retrieval split · kind decision.`
 *
 * `threadName` is the thread's served name when it is known, so the sentence
 * reads the way the reader chose it rather than echoing an opaque id.
 */
export function filterEmptySentence(filters: FeedFilters, threadName?: string | null): string {
  const parts: Array<string> = []
  if (filters.corpus !== null) parts.push(`corpus ${filters.corpus}`)
  if (filters.thread !== null) parts.push(`thread #${threadName?.trim() || filters.thread}`)
  if (filters.kind !== null) parts.push(`kind ${filters.kind}`)
  if (filters.meeting !== null) parts.push(`meeting ${filters.meeting}`)
  return `No moments match ${parts.join(' · ')}.`
}

/**
 * A thread's place in the palette, from its persisted immutable
 * `colorOrdinal` (`DESIGN.md` · Threads).
 *
 * Eight hues; ordinals 9–16 are the same hues at lap 2 (darker, hatched);
 * past 16 the band is grey and the name alone identifies the thread. The api
 * owns identity, the client owns only this mapping — never list position.
 */
export interface ThreadPalette {
  /** 1–8 within the palette, or `null` beyond it. */
  hue: number | null
  /** 1 or 2 within the palette, or `null` beyond it. */
  lap: number | null
  /** The lap-one CSS custom property used for the readable thread name. */
  textCssVar: string
  /** The CSS custom property used by the lap swatch. */
  swatchCssVar: string
}

export function threadPaletteOf(colorOrdinal: number | null): ThreadPalette {
  if (
    colorOrdinal === null ||
    !Number.isInteger(colorOrdinal) ||
    colorOrdinal < 1 ||
    colorOrdinal > 16
  ) {
    return {
      hue: null,
      lap: null,
      textCssVar: '--thread-beyond-band',
      swatchCssVar: '--thread-beyond-band',
    }
  }
  const hue = ((colorOrdinal - 1) % 8) + 1
  const lap = Math.floor((colorOrdinal - 1) / 8) + 1
  return {
    hue,
    lap,
    textCssVar: `--thread-${hue}-band`,
    swatchCssVar: lap === 1 ? `--thread-${hue}-band` : `--thread-${hue}-band-lap2`,
  }
}

/** A thread chip's accessible name — the `#` is decoration and never read. */
export function threadChipName(thread: FeedThread): string {
  return `thread ${thread.name}`
}
