import type {
  DrilldownScreenshot,
  DrilldownSegment,
  ExtractionPrompt,
  MomentArtifact,
  SnippetRunModel,
} from '@/client/types.gen'
import { problemMessage, problemType } from '@/lib/problems'

/**
 * Pure display and decision helpers for the moment views.
 *
 * Same split as `features/meetings/rows.ts` and `features/search/hits.ts`:
 * the parts worth testing without rendering anything live here, and the
 * components stay about state and layout.
 */

/** How long a moment read waits for the api before it names the timeout. */
export const MOMENT_TIMEOUT_MS = 8000

/**
 * How long the "Active extraction prompts" fetch waits before giving up
 * (story 4.2). Short and separate from `MOMENT_TIMEOUT_MS`: the prompts are
 * global config, not per-moment data, and a slow or failed fetch must never
 * hold up — or fail — the rest of the moment view.
 */
export const EXTRACTION_PROMPTS_TIMEOUT_MS = 5000

/**
 * The right rail's seven categories — CAP-4's extracted analytics, verbatim,
 * in CAP-4's order. `kind` values are the api's `MomentArtifact.kind`
 * vocabulary (`server/meetingminer/api/moments.py`), pinned before Epic 4
 * delivers a single row so its arrival is data, not a rail rewrite.
 */
export const ARTIFACT_CATEGORIES = [
  { kind: 'action-item', label: 'Action items' },
  { kind: 'adr', label: 'ADRs' },
  { kind: 'decision', label: 'Decisions' },
  { kind: 'story', label: 'Stories' },
  { kind: 'requirement', label: 'Requirements' },
  { kind: 'bug-fix', label: 'Bug fixes' },
  { kind: 'change-request', label: 'Change requests' },
] as const satisfies ReadonlyArray<{ kind: MomentArtifact['kind']; label: string }>

/**
 * The labels for prompt kinds that are not artifact kinds: story 10.1's
 * topics are navigation metadata, never one of the rail's categories.
 */
const PROMPT_ONLY_LABELS: Partial<Record<ExtractionPrompt['kind'], string>> = {
  topic: 'Topics',
}

/**
 * The heading an extraction prompt's kind renders under. An artifact-kind
 * prompt reuses the rail's `ARTIFACT_CATEGORIES` label so "ADRs" and "Action
 * items" mean the same thing in both places; a non-artifact prompt kind
 * carries its own label; and a kind newer than this file renders as itself —
 * the section shows whatever the endpoint returns, never dropping an entry.
 */
export function extractionPromptLabel(kind: ExtractionPrompt['kind']): string {
  const category = ARTIFACT_CATEGORIES.find((entry) => entry.kind === kind)
  return category?.label ?? PROMPT_ONLY_LABELS[kind] ?? kind
}

/** The rail's artifacts for one category, in api order. */
export function artifactsOfKind(
  artifacts: Array<MomentArtifact>,
  kind: MomentArtifact['kind'],
): Array<MomentArtifact> {
  return artifacts.filter((artifact) => artifact.kind === kind)
}

/**
 * Whether the "Approve & publish" gesture (story 4.3) has anything to do.
 *
 * The gesture is per-moment, not per-artifact (epics AC1/AC2): it is offered
 * whenever at least one of this moment's artifacts is still `extracted`, and
 * hidden once none are — there is no way to re-run it per artifact.
 */
export function hasApprovableArtifacts(artifacts: Array<MomentArtifact>): boolean {
  return artifacts.some((artifact) => artifact.state === 'extracted')
}

/**
 * How a moment read failed, each kind needing a different sentence.
 *
 * `notViewable` is the api's 409 `meeting-not-viewable`: the meeting exists
 * and its evidence is still being prepared — transient, and blaming the
 * network or the reader for it would both be wrong. `notFound` is a 404: the
 * id resolves to nothing, which after an ingest wipe or a mistyped id is an
 * answer, not an outage. `problem` is any other refusal the api wrote a
 * sentence for, and `transport` means the api was never reached — naming its
 * address is the useful thing to say (`hits.ts` litigated the split).
 */
export type MomentLoadFailure =
  | { kind: 'notViewable'; message: string }
  | { kind: 'notFound'; message: string }
  | { kind: 'problem'; message: string }
  | { kind: 'transport'; message: string }

const NOT_VIEWABLE_TYPE = 'urn:meetingminer:problem:meeting-not-viewable'
const NOT_FOUND_TYPE = 'urn:meetingminer:problem:not-found'

function stringify(error: unknown): string {
  if (error instanceof Error) return error.message
  if (typeof error === 'string') return error
  try {
    return JSON.stringify(error) ?? 'an unknown error'
  } catch {
    return 'an unknown error'
  }
}

/** Classify an answered refusal — the `error` half of an sdk result. */
export function loadFailureOf(error: unknown): MomentLoadFailure {
  const type = problemType(error)
  const message = problemMessage(error) ?? stringify(error)
  if (type === NOT_VIEWABLE_TYPE) return { kind: 'notViewable', message }
  if (type === NOT_FOUND_TYPE) return { kind: 'notFound', message }
  return { kind: 'problem', message }
}

/** Classify a thrown/rejected read — the api was never reached. */
export function transportFailureOf(error: unknown): MomentLoadFailure {
  return { kind: 'transport', message: stringify(error) }
}

/**
 * What names a meeting wherever it appears, falling back to its id like
 * `hitLabel` does. One helper for both views — the list header carries the
 * title as `title`, the detail as `meetingTitle`, so the caller passes the
 * pair rather than this module knowing every payload's spelling.
 */
export function meetingLabelOf(
  title: string | null | undefined,
  meetingId: string,
): string {
  const trimmed = title?.trim()
  return trimmed ? trimmed : meetingId
}

/** A row's one-line preview, or the honest sentence for a span with none. */
export function previewLabel(preview: string | null | undefined): string {
  const text = preview?.trim()
  return text ? text : 'No transcript covers this span.'
}

/** The name a transcript line is attributed to — blank labels read as Unknown,
 * the same fallback the projection uses (`projections/evidence.py`). */
export function speakerName(label: string): string {
  return label.trim() || 'Unknown'
}

/**
 * Split one segment's text into highlight runs for a locally-typed term.
 *
 * Client-side on purpose (story 2.3): the search index is moment-grained
 * (AD-4), so segment-level mention highlighting cannot come from Meilisearch,
 * and the server sends no markup (the AD-15 principle) — the runs are built
 * here, in the `SnippetRunModel` shape `CorpusSearch` already renders with
 * `<mark>`. Case-insensitive; an empty (or all-space) term returns the whole
 * input as one un-highlighted run.
 */
export function highlightRuns(text: string, term: string): Array<SnippetRunModel> {
  const needle = term.trim().toLowerCase()
  if (needle === '') return [{ text, highlighted: false }]
  // Search in the whole string's lowercased coordinates, preserving its
  // context-sensitive semantics (for example, 'ΟΣ'.toLowerCase() is 'ος').
  // Map each lowercased code unit back to the original code-point boundaries
  // before slicing. A case fold such as 'İ' (U+0130) expands to two code
  // units; iterating by code point ensures that neither the expansion nor an
  // astral source character is split.
  const foldedSource: Array<{ start: number; end: number }> = []
  const haystack = text.toLowerCase()
  let sourceStart = 0
  let foldedStart = 0
  for (const character of text) {
    const sourceEnd = sourceStart + character.length
    const foldedEnd = text.slice(0, sourceEnd).toLowerCase().length
    for (let index = foldedStart; index < foldedEnd; index += 1) {
      foldedSource.push({ start: sourceStart, end: sourceEnd })
    }
    sourceStart = sourceEnd
    foldedStart = foldedEnd
  }
  const runs: Array<SnippetRunModel> = []
  let foldedFrom = 0
  let sourceFrom = 0
  for (;;) {
    const at = haystack.indexOf(needle, foldedFrom)
    if (at < 0) break
    const sourceMatchStart = foldedSource[at].start
    const sourceMatchEnd = foldedSource[at + needle.length - 1].end
    if (sourceMatchStart > sourceFrom) {
      runs.push({ text: text.slice(sourceFrom, sourceMatchStart), highlighted: false })
    }
    runs.push({ text: text.slice(sourceMatchStart, sourceMatchEnd), highlighted: true })
    foldedFrom = at + needle.length
    sourceFrom = sourceMatchEnd
  }
  if (sourceFrom < text.length || runs.length === 0) {
    runs.push({ text: text.slice(sourceFrom), highlighted: false })
  }
  return runs
}

/**
 * The 409 `meeting-not-viewable` extensions the drill-down empty state reads
 * — additive camelCase members beside the RFC 9457 body (story 2.3, AD-14).
 */
function notViewableExtensions(problem: unknown): { augmenting: boolean; jobStatus: string | null } {
  if (problem === null || typeof problem !== 'object') {
    return { augmenting: false, jobStatus: null }
  }
  const body = problem as { augmenting?: unknown; jobStatus?: unknown }
  return {
    augmenting: body.augmenting === true,
    jobStatus: typeof body.jobStatus === 'string' ? body.jobStatus : null,
  }
}

/**
 * The empty-state sentence for a 409 `meeting-not-viewable` problem.
 *
 * Three sentences in the `blockedReason` ordering precedent
 * (`features/meetings/rows.ts`): failure first, because "it reopens once the
 * re-run settles" is a lie about a run that will never settle — a failed
 * augmentation must read as failed, not as waiting. Then augmentation, then
 * the first-ingest default.
 */
/**
 * One extracted artifact with its moment anchor — the meeting rail's row
 * (story ui-3). The anchor fields come from the artifact's own moment read
 * (`getMoment`), because `MomentArtifact` itself does not carry them.
 */
export interface MeetingArtifactEntry {
  artifact: MomentArtifact
  momentId: string
  startMs: number
  endMs: number
}

/** One rail group: a kind with at least one entry, entries in offset order. */
export interface MeetingArtifactGroup {
  kind: MomentArtifact['kind']
  label: string
  entries: Array<MeetingArtifactEntry>
}

/**
 * The rail's groups, in `ARTIFACT_CATEGORIES` order, empty kinds omitted —
 * the spec's "render only kinds with backing data" (no topics, no risks, and
 * no zero-count headers padding the rail either).
 */
export function meetingArtifactGroups(
  entries: Array<MeetingArtifactEntry>,
): Array<MeetingArtifactGroup> {
  return ARTIFACT_CATEGORIES.map((category) => ({
    kind: category.kind,
    label: category.label,
    entries: entries
      .filter((entry) => entry.artifact.kind === category.kind)
      .sort((a, b) => a.startMs - b.startMs),
  })).filter((group) => group.entries.length > 0)
}

/** The published subset, in offset order — the "Published documents" section. */
export function publishedEntries(
  entries: Array<MeetingArtifactEntry>,
): Array<MeetingArtifactEntry> {
  return entries
    .filter((entry) => entry.artifact.state === 'published')
    .sort((a, b) => a.startMs - b.startMs)
}

/** Whitespace-separated word count over the whole transcript — the header's
 * "15,174 words" stat, computed client-side over served text. */
export function wordCountOf(segments: Array<{ text: string }>): number {
  return segments.reduce(
    (total, segment) => total + (segment.text.match(/\S+/g)?.length ?? 0),
    0,
  )
}

/**
 * The meeting's evidence extent in ms: the furthest end any screenshot or
 * segment reaches. The drilldown payload carries no duration column, so this
 * is the honest derivable number — "how far the evidence runs", zero when
 * the meeting has neither.
 */
export function evidenceDurationMs(data: {
  screenshots: Array<Pick<DrilldownScreenshot, 'endOffsetMs'>>
  segments: Array<Pick<DrilldownSegment, 'endMs'>>
}): number {
  let max = 0
  for (const shot of data.screenshots) max = Math.max(max, shot.endOffsetMs)
  for (const segment of data.segments) max = Math.max(max, segment.endMs)
  return max
}

/** `99 min` (or `42 s` under a minute) — the header stat's duration, or
 * `null` when there is no evidence extent to state. */
export function durationStatLabel(ms: number): string | null {
  if (!Number.isFinite(ms) || ms <= 0) return null
  const seconds = Math.round(ms / 1000)
  if (seconds < 60) return `${seconds} s`
  return `${Math.round(seconds / 60)} min`
}

/**
 * The header's source-lineage phrase, derived from what the payload actually
 * says: recording presence, and how the transcript's speakers resolved. No
 * invented provenance — the drilldown does not carry the source container
 * format, so this states evidence shape and attribution, nothing more.
 */
export function lineageLabel(
  hasRecording: boolean,
  segments: Array<Pick<DrilldownSegment, 'speakerResolution'>>,
): string {
  const source = hasRecording
    ? 'Recording + transcript'
    : 'Transcript only — no recording'
  if (segments.length === 0) return `${source} · no transcript segments`
  const attribution = segments.some(
    (segment) => segment.speakerResolution === 'resolved',
  )
    ? 'speaker-attributed'
    : segments.every((segment) => segment.speakerResolution === 'placeholder')
      ? 'diarized speaker slots only'
      : 'speakers unresolved'
  return `${source} · ${attribution}`
}

/** One meeting participant as the rail lists them: resolved identity, how
 * often they spoke, and where they first did. */
export interface MeetingParticipant {
  participantId: string
  name: string
  turns: number
  firstSegmentId: string
}

/**
 * The participants this transcript actually resolved — distinct
 * `participantId`s in first-spoken order. Derived from the drilldown
 * segments because no per-meeting participant endpoint exists; a segment
 * without a `participantId` (unresolved, ambiguous, placeholder) counts for
 * nobody, which is exactly the never-guess rule the pipeline records.
 */
export function participantsOf(
  segments: Array<
    Pick<DrilldownSegment, 'segmentId' | 'speakerLabel' | 'participantId'>
  >,
): Array<MeetingParticipant> {
  const byId = new Map<string, MeetingParticipant>()
  for (const segment of segments) {
    if (segment.participantId == null) continue
    const existing = byId.get(segment.participantId)
    if (existing !== undefined) {
      existing.turns += 1
    } else {
      byId.set(segment.participantId, {
        participantId: segment.participantId,
        name: speakerName(segment.speakerLabel),
        turns: 1,
        firstSegmentId: segment.segmentId,
      })
    }
  }
  return [...byId.values()]
}

/** The one-sentence absence note the rail shows when no transcript line
 * resolved to a participant record (reference-ui.md's honest-absence rule). */
export const NO_PARTICIPANT_GRAPH =
  'No participant graph for this meeting — no transcript speaker resolved to a participant record.'

/**
 * The transcript passage a film-strip capture aligns to: the last segment
 * starting at or before the capture's offset, or the first segment when the
 * capture precedes them all. `null` only for an empty transcript.
 */
export function alignedSegmentId(
  segments: Array<Pick<DrilldownSegment, 'segmentId' | 'startMs'>>,
  offsetMs: number,
): string | null {
  if (segments.length === 0) return null
  let aligned = segments[0]
  for (const segment of segments) {
    if (segment.startMs <= offsetMs) aligned = segment
    else break
  }
  return aligned.segmentId
}

export function notViewableMessage(problem: unknown): string {
  const { augmenting, jobStatus } = notViewableExtensions(problem)
  if (jobStatus === 'failed') {
    return 'Ingestion failed for this meeting — nothing to open until it is re-queued.'
  }
  if (augmenting) {
    return 'This meeting is being augmented — a recovered recording or late metadata is being folded into its evidence. It reopens once the re-run settles.'
  }
  return 'This meeting is still preparing its evidence — its first ingest has not settled yet. It opens once every evidence stage is done or skipped.'
}
