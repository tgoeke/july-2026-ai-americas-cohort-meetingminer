/**
 * Reading the acquisition api's answers: refusals, transport failures, and the
 * four steps of the stepper.
 *
 * Pure, so every row of the story's edge-case matrix is a unit test with no
 * DOM and no network. The screen renders what these return and adds nothing.
 */

import type { AcquisitionStatus, ProbeResult } from '@/client/types.gen'
import type { RenderedStageStatus } from '@/features/meetings/stageStyles'
import { durationLabel } from '@/features/meetings/rows'
import { API_BASE } from '@/lib/api'
import { problemMessage } from '@/lib/problems'

/**
 * One refusal, in the api's own words.
 *
 * `rule` is story 6.2a's token when the api names one
 * (`server/meetingminer/api/acquisitions.py:_refusal_problem` sets it as an
 * RFC 9457 extension member); for a problem carrying no `rule` — a plain
 * validation refusal, a 409 conflict — the problem's `title` takes the slot,
 * so the box always leads with what kind of refusal this was.
 */
export interface Refusal {
  rule: string
  detail: string
  /** `null` when the api offered none; the box then omits the arrow line. */
  remediation: string | null
  /** `urn:meetingminer:problem:<slug>`, or `null` for a body without one. */
  type: string | null
}

/** The api did not answer at all. Distinct from a refusal, which it did. */
export interface TransportFailure {
  kind: 'transport'
  message: string
}

/** A refusal the api issued, or a failure to reach it at all. Never mixed. */
export type Failure =
  | { kind: 'refusal'; refusal: Refusal; body: Record<string, unknown> }
  | TransportFailure

/** The problem type of story 6.4's "one running acquisition per source id". */
export const IN_PROGRESS_PROBLEM = 'urn:meetingminer:problem:acquisition-in-progress'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function nonEmptyString(value: unknown): string | null {
  return typeof value === 'string' && value.trim().length > 0 ? value.trim() : null
}

/**
 * An RFC 9457 body → a refusal, or `null` when this is not one.
 *
 * The generated client returns the *parsed problem body* as `error` on a
 * non-2xx and the *thrown Error* on a transport failure
 * (`web/src/client/client/client.gen.ts:186-218`). Telling them apart is the
 * whole job here: an outage rendered as a rule refusal would blame the video
 * for the network.
 */
export function refusalOf(error: unknown): Refusal | null {
  if (error instanceof Error || !isRecord(error)) return null
  const type = nonEmptyString(error.type)
  const rule = nonEmptyString(error.rule)
  const title = nonEmptyString(error.title)
  const detail = nonEmptyString(error.detail)
  // A body with neither a problem type nor any sentence is not an RFC 9457
  // answer; treating it as one would put an empty box on screen.
  if (type === null && detail === null && title === null) return null
  return {
    rule: rule ?? title ?? 'the api refused this request',
    detail: detail ?? problemMessage(error) ?? 'the api gave no detail',
    remediation: nonEmptyString(error.remediation),
    type,
  }
}

/** The sentence for an api that did not answer, naming the address that did not. */
export function transportFailure(message: string): TransportFailure {
  return { kind: 'transport', message: `Cannot reach the api at ${API_BASE}: ${message}` }
}

/**
 * One sentence for either kind of failure, for the places that have room for a
 * line rather than a box. A refusal keeps its rule so the reader still learns
 * which rule fired.
 */
export function failureMessage(failure: Failure): string {
  return failure.kind === 'transport'
    ? failure.message
    : `${failure.refusal.rule}: ${failure.refusal.detail}`
}

/** Whatever the client handed back → the one failure this screen will show. */
export function failureOf(error: unknown): Failure {
  const refusal = refusalOf(error)
  if (refusal !== null) return { kind: 'refusal', refusal, body: error as Record<string, unknown> }
  if (error instanceof Error) return transportFailure(error.message)
  if (typeof error === 'string') return transportFailure(error)
  return transportFailure('the api answered with a body this client cannot read')
}

/** `GET /acquisitions/{id}`'s `refusal` object → the same shape the box renders. */
export function refusalOfStatus(status: AcquisitionStatus): Refusal | null {
  if (status.refusal == null) return null
  return {
    rule: status.refusal.rule,
    detail: status.refusal.detail,
    remediation: nonEmptyString(status.refusal.remediation),
    type: null,
  }
}

export type StepName = 'launch' | 'running' | 'posted' | 'ingesting'

export interface Step {
  name: StepName
  /** The word rendered beside the bar, and read by a screen reader. */
  label: string
  status: RenderedStageStatus
}

/** The acquisition statuses story 6.4 defines (`acquisitions.py:96`). */
const LIVE = new Set(['queued', 'running'])
const KNOWN = new Set(['queued', 'running', 'posted', 'failed'])

/** True only for a state this client can interpret. The generated field is an open string. */
export function isKnownAcquisitionStatus(status: string | null | undefined): boolean {
  return status != null && KNOWN.has(status)
}

/** True while `GET /acquisitions/{id}` is still worth polling. */
export function isLive(status: string | null | undefined): boolean {
  return status != null && LIVE.has(status)
}

/**
 * The four bars, from the acquisition status and the ingesting job.
 *
 * `launch` is done the moment `POST /acquisitions` is accepted — 202 means
 * accepted, so the record exists whatever it says next.
 *
 * `running` reads `done` on a `failed` acquisition because the record passed
 * through it: `acquisitions.run_acquisition` writes `status="running"` before
 * it does any work, so every `failed` record ran. That is read from the
 * server's state machine, not assumed.
 *
 * The third bar carries the acquisition's verdict, so on `failed` its word is
 * `failed` rather than `posted` — the mockup's shape, and the honest one:
 * nothing was posted.
 *
 * `ingesting` is not an acquisition status at all. It is the job, and it stays
 * `queued` on a failed acquisition because ingestion never started.
 */
export function stepperSteps(
  status: string | null,
  ingesting: RenderedStageStatus,
  postedWord?: string,
): Array<Step> {
  const failed = status === 'failed'
  const posted = status === 'posted'
  const unknown = status !== null && !isKnownAcquisitionStatus(status)
  return [
    { name: 'launch', label: 'launch', status: 'done' },
    {
      name: 'running',
      label: unknown ? `running — unknown (${status})` : 'running',
      status: unknown
        ? 'unknown'
        : status === 'running'
          ? 'running'
          : posted || failed
            ? 'done'
            : 'queued',
    },
    {
      name: 'posted',
      label: failed ? 'failed' : (postedWord ?? 'posted'),
      status: failed ? 'failed' : posted ? 'done' : 'queued',
    },
    { name: 'ingesting', label: 'ingesting', status: failed ? 'queued' : ingesting },
  ]
}

/** `posted — job 8f3c1a2b…`, the contract's eight-char prefix, or plain `posted`. */
export function postedWordFor(status: AcquisitionStatus): string {
  const jobId = nonEmptyString(status.jobId)
  return jobId === null ? 'posted' : `posted — job ${jobId.slice(0, 8)}…`
}

/**
 * The one line a successful probe puts under the field.
 *
 * `captions: none` is not a refusal — a recording-only drop is valid, and the
 * server's `ProbeResult.captions` is `None` when the video publishes no
 * English track. Saying "none" is the honest reading; omitting the clause
 * would leave the reader unsure whether it was checked.
 */
export function probeSummary(probe: ProbeResult): string {
  const captions =
    probe.captions == null
      ? 'captions: none'
      : `captions: ${probe.captions.kind} ${probe.captions.language}`
  return [
    probe.title,
    durationLabel(probe.durationMs) ?? `${probe.durationMs} ms`,
    captions,
    probe.sourceId,
  ].join(' · ')
}
