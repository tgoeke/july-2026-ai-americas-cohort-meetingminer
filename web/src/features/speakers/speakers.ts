import type {
  AssignSpeakerRequest,
  DrilldownSegment,
  ParticipantRow,
  SpeakerTag,
} from '@/client/types.gen'
import { problemMessage, problemType } from '@/lib/problems'

/**
 * Pure display and decision helpers for the speaker naming screen.
 *
 * Same split as `features/moments/moments.ts` and `features/participants/
 * curation.ts`: the parts worth testing without rendering anything live here,
 * and the component stays about state and layout. The failure classifiers are
 * this feature's own rather than an import from a sibling — `problems.ts`
 * exists because features must not deep-import each other, and `curation.ts`
 * set the precedent of a per-feature classifier over the shared reader.
 */

/** How long a speakers or drill-down read waits before it names the timeout. */
export const SPEAKERS_TIMEOUT_MS = 8000

/**
 * How long one sample clip plays. Story 7.4's acceptance criterion: the clip
 * ends at `startMs + 8000`, which is enough of a voice to recognize without
 * running into whoever speaks next.
 */
export const CLIP_LENGTH_MS = 8000

/** The three sentences the screen states rather than a spinner or a blank. */
export const NO_SPEAKER_TAGS =
  'No speaker tags for this meeting — the transcript arrived speaker-attributed,' +
  ' or the diarizer is noop (config.yaml: diarizer.engine).'

export const SUGGESTION_NOTE =
  'Suggestions are shown, never applied — pick one or type a name.'

/**
 * Why `Unresolved` is offered on a row that already carries a name, and what
 * it does and does not do there (backlog B-39). The api accepts the choice on
 * any tag; on a label the *source* attributed, `align` re-derives the same
 * attribution, so the tag stays resolved. Saying so is cheaper than a curator
 * pressing it twice and concluding the screen is broken.
 */
export const UNRESOLVED_ON_RESOLVED_NOTE =
  'Unresolved removes an assignment made here. A name the source supplied is' +
  ' re-derived by align and stays resolved (backlog B-39).'

/**
 * The stages a naming re-arms, as story 7.3's response reports them. Not a
 * constant the client asserts: `rearmedStages` comes back on every 200 and is
 * what the strip draws, so a change on the server is a change on screen
 * without a client edit. This is only the fallback for a body that somehow
 * carried none.
 */
export const REARMED_STAGES_FALLBACK = ['align', 'moments', 'extract'] as const

/**
 * How a speakers or drill-down read failed.
 *
 * `notViewable` is the api's 409 `meeting-not-viewable`, and on this screen it
 * is not merely an error state: story 7.3's `PUT` is deliberately admitted
 * while a meeting is unviewable, so a successful naming makes both of this
 * screen's own reads start refusing with it seconds later. The component uses
 * this kind to keep what it already has on screen rather than to blank it.
 */
export type SpeakersLoadFailure =
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
export function loadFailureOf(error: unknown): SpeakersLoadFailure {
  const type = problemType(error)
  const message = problemMessage(error) ?? stringify(error)
  if (type === NOT_VIEWABLE_TYPE) return { kind: 'notViewable', message }
  if (type === NOT_FOUND_TYPE) return { kind: 'notFound', message }
  return { kind: 'problem', message }
}

/** Classify a thrown or rejected read — the api was never reached. */
export function transportFailureOf(error: unknown): SpeakersLoadFailure {
  return { kind: 'transport', message: stringify(error) }
}

/** The sentence a refused assignment shows, in the api's own words. */
export function assignmentRefusal(error: unknown): string {
  return problemMessage(error) ?? stringify(error)
}

/**
 * Whether a tag names a person the system actually knows.
 *
 * AD-13, stated as a predicate: a `placeholder`, `unresolved` or `ambiguous`
 * tag has no participant and no display name on the wire, and this screen
 * shows neither. It renders `SPEAKER_03` and the resolution word, which is
 * the whole truth about it — anything warmer would be the guess the pipeline
 * spent three stories refusing to make.
 */
export function isResolved(tag: SpeakerTag): boolean {
  return (
    tag.speakerResolution === 'resolved' &&
    tag.participantId !== null &&
    (tag.displayName ?? '').trim() !== ''
  )
}

/** The name to print beside a tag, or `null` when the system knows none. */
export function resolvedName(tag: SpeakerTag): string | null {
  return isResolved(tag) ? (tag.displayName as string).trim() : null
}

/** Every tag's talk time added up — the denominator of a share, and the
 * header's total. */
export function totalTalkTimeMs(speakers: Array<SpeakerTag>): number {
  return speakers.reduce(
    (total, tag) => total + (Number.isFinite(tag.talkTimeMs) ? tag.talkTimeMs : 0),
    0,
  )
}

/**
 * One tag's share of the speech, 0–100, rounded to an integer.
 *
 * Zero rather than NaN when nothing was said: a meeting whose segments all
 * carry zero duration is a real (if odd) corpus row, and `NaN%` on screen
 * would be this screen inventing a defect.
 */
export function talkSharePercent(tag: SpeakerTag, totalMs: number): number {
  if (!Number.isFinite(totalMs) || totalMs <= 0) return 0
  if (!Number.isFinite(tag.talkTimeMs) || tag.talkTimeMs <= 0) return 0
  return Math.round((tag.talkTimeMs / totalMs) * 100)
}

/**
 * A duration as the design spine writes one: `1h 04m` over an hour, `12m 04s`
 * under it, `48s` under a minute. Distinct from `offsetLabel`, which renders a
 * *position* in a recording (`1:04:09`) — a length and an offset read the same
 * in digits and mean different things, so they are spelled differently.
 */
export function durationLabel(ms: number): string {
  if (!Number.isFinite(ms) || ms <= 0) return '0s'
  const total = Math.round(ms / 1000)
  const seconds = total % 60
  const minutes = Math.floor(total / 60) % 60
  const hours = Math.floor(total / 3600)
  if (hours > 0) return `${hours}h ${String(minutes).padStart(2, '0')}m`
  if (minutes > 0) return `${minutes}m ${String(seconds).padStart(2, '0')}s`
  return `${seconds}s`
}

/** `23m 51s · 112 segments` — the meta line under a row's share. */
export function speakerMetaLabel(tag: SpeakerTag): string {
  const segments = tag.segmentCount === 1 ? '1 segment' : `${tag.segmentCount} segments`
  return `${durationLabel(tag.talkTimeMs)} · ${segments}`
}

/**
 * A row's accessible name: the tag, whether it is selected, whether it
 * resolved and to whom, and its share. Everything the row draws, in words —
 * the share bar is a graphic and carries none of it on its own.
 */
export function speakerRowLabel(
  tag: SpeakerTag,
  percent: number,
  selected: boolean,
): string {
  const name = resolvedName(tag)
  const parts = [tag.speakerLabel]
  if (selected) parts.push('selected')
  parts.push(name === null ? tag.speakerResolution : `resolved to ${name}`)
  parts.push(`${percent} percent talk share`)
  return parts.join(', ')
}

/**
 * The three choices the screen can send, as one value.
 *
 * A union rather than three call sites building `AssignSpeakerRequest`
 * themselves, because the api's "exactly one of three" rule is easiest to
 * break by sending two — a picked participant whose name is still in the
 * field is precisely the state that produces both fields at once.
 */
export type AssignmentChoice =
  | { kind: 'participant'; participantId: string; displayName: string }
  | { kind: 'newName'; displayName: string }
  | { kind: 'unresolved' }

/**
 * The two choices the *name field* can produce. `unresolved` is not one of
 * them: it comes from its own button, never from text, so the field's reader
 * can never accidentally return it.
 */
export type NamedAssignmentChoice = Extract<AssignmentChoice, { displayName: string }>

/** The request body for a choice — exactly one field set, as the api requires. */
export function assignmentBody(choice: AssignmentChoice): AssignSpeakerRequest {
  if (choice.kind === 'unresolved') return { unresolved: true }
  if (choice.kind === 'participant') return { participantId: choice.participantId }
  return { displayName: choice.displayName }
}

/**
 * What the name field and the picked suggestion add up to, or `null` when
 * Save has nothing to send.
 *
 * The picked participant wins only while the field still holds that
 * participant's name: typing after picking a suggestion means the curator
 * changed their mind, and sending the stale id would save a different person
 * than the one on screen.
 */
export function choiceOf(
  draft: string,
  picked: ParticipantRow | null,
): NamedAssignmentChoice | null {
  const name = draft.trim()
  if (name === '') return null
  if (picked !== null && picked.displayName.trim() === name) {
    return { kind: 'participant', participantId: picked.id, displayName: name }
  }
  return { kind: 'newName', displayName: name }
}

/**
 * The participants a typed fragment suggests, in the api's order.
 *
 * Canonical rows only: a merged-away participant is not a name to assign a
 * voice to — `POST /participants/{id}/merge` already decided that row is the
 * other one. An empty fragment suggests nothing, so the list opens on a
 * keystroke rather than sitting under an untouched field.
 */
export function suggestionsFor(
  participants: Array<ParticipantRow>,
  draft: string,
  limit = 8,
): Array<ParticipantRow> {
  const needle = draft.trim().toLowerCase()
  if (needle === '') return []
  return participants
    .filter((row) => (row.mergedIntoParticipantId ?? null) === null)
    .filter((row) => row.displayName.toLowerCase().includes(needle))
    .slice(0, limit)
}

/** The segments of one tag, in transcript order — filtered client-side, as
 * the drill-down serves the whole meeting and nothing narrower exists. */
export function segmentsOfTag(
  segments: Array<DrilldownSegment>,
  tag: string,
): Array<DrilldownSegment> {
  return segments.filter((segment) => segment.speakerLabel === tag)
}

/** One rerun stage as the strip draws it. */
export interface RerunStage {
  name: string
  status: string
  error: string | null
}

/**
 * The rerun a naming started: which job, which tag, what the curator chose,
 * and how far the re-armed stages have got.
 */
export interface RerunState {
  jobId: string
  speakerLabel: string
  /** What the curator chose, for the landed sentence. `null` for unresolved. */
  assignedName: string | null
  stages: Array<RerunStage>
  landedAt: string | null
  /** Set when the meeting's evidence was already unsettled when the PUT was
   * accepted — story 7.3's recovery exception, worth saying out loud. */
  acceptedWhileUnviewable: boolean
}

/** A fresh rerun: every re-armed stage queued, nothing landed yet. */
export function rerunFrom(
  jobId: string,
  speakerLabel: string,
  assignedName: string | null,
  rearmedStages: Array<string>,
  acceptedWhileUnviewable: boolean,
): RerunState {
  const names = rearmedStages.length > 0 ? rearmedStages : [...REARMED_STAGES_FALLBACK]
  return {
    jobId,
    speakerLabel,
    assignedName,
    stages: names.map((name) => ({ name, status: 'queued', error: null })),
    landedAt: null,
    acceptedWhileUnviewable,
  }
}

/**
 * Fold one `/jobs/events` frame into a rerun.
 *
 * Only frames for this rerun's job are applied, and only the stages it
 * re-armed: the same job carries the meeting's whole pipeline, and drawing
 * `probe` or `ocr` in a strip labelled "rerun" would claim the naming
 * re-ran stages it deliberately did not.
 */
export function applyJobEvent(
  rerun: RerunState,
  event: {
    jobId: string
    event: string
    stage?: string | null
    status?: string | null
    error?: string | null
    jobStatus?: string
  },
  at: string,
): RerunState {
  if (event.jobId !== rerun.jobId) return rerun
  if (event.event === 'job.stage' && typeof event.stage === 'string') {
    if (!rerun.stages.some((stage) => stage.name === event.stage)) return rerun
    return {
      ...rerun,
      stages: rerun.stages.map((stage) =>
        stage.name === event.stage
          ? { ...stage, status: event.status ?? stage.status, error: event.error ?? null }
          : stage,
      ),
    }
  }
  if (event.event === 'job.done') {
    return {
      ...rerun,
      // The job settled, so any stage the stream never delivered a frame for
      // is done — the alternative is a strip stuck at `queued` under a
      // sentence saying the rerun landed.
      stages: rerun.stages.map((stage) =>
        stage.status === 'failed' ? stage : { ...stage, status: 'done' },
      ),
      landedAt: at,
    }
  }
  if (event.event === 'job.error') {
    const failing = typeof event.stage === 'string' ? event.stage : null
    return {
      ...rerun,
      stages: rerun.stages.map((stage) =>
        failing === null || stage.name === failing
          ? { ...stage, status: 'failed', error: event.error ?? stage.error }
          : stage,
      ),
    }
  }
  return rerun
}

/** The stage a rerun failed at, with its recorded error — or `null`. */
export function failedStage(rerun: RerunState): RerunStage | null {
  return rerun.stages.find((stage) => stage.status === 'failed') ?? null
}

/** Whether the rerun is still moving — the sentence that keeps a curator from
 * reading a re-armed meeting as a hung one. */
export function isReprocessing(rerun: RerunState | null): boolean {
  return (
    rerun !== null &&
    rerun.landedAt === null &&
    failedStage(rerun) === null
  )
}

/** `Reprocessing this meeting — align, moments, extract re-armed by naming
 * SPEAKER_00. The transcript below is the pre-rerun reading.` */
export function reprocessingSentence(rerun: RerunState): string {
  const stages = rerun.stages.map((stage) => stage.name).join(', ')
  return (
    `Reprocessing this meeting — ${stages} re-armed by naming` +
    ` ${rerun.speakerLabel}. The transcript below is the pre-rerun reading.`
  )
}

/** The Flow 3 climax sentence, in the spine's words. */
export function landedSentence(rerun: RerunState): string {
  const naming =
    rerun.assignedName === null
      ? `now leave ${rerun.speakerLabel} unresolved`
      : `now name ${rerun.speakerLabel} as ${rerun.assignedName}`
  return (
    `Rerun landed ${rerun.landedAt} — transcript, graph, and extractions` +
    ` ${naming}. Moment ids and citations unchanged.`
  )
}

/** The failure sentence: what broke, and what is nonetheless saved. */
export function failedSentence(stage: RerunStage): string {
  return (
    `Rerun failed at ${stage.name} — ${stage.error ?? 'no error was recorded'}.` +
    ' Names are saved; the transcript still shows tags.'
  )
}
