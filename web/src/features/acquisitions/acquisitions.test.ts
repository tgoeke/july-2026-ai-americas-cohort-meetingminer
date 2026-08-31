import { describe, expect, it } from 'vitest'
import type { AcquisitionStatus, ProbeResult } from '@/client/types.gen'
import { API_BASE } from '@/lib/api'
import {
  failureMessage,
  failureOf,
  isLive,
  postedWordFor,
  probeSummary,
  refusalOf,
  refusalOfStatus,
  stepperSteps,
} from './acquisitions'

/** A refusal body exactly as `api/acquisitions.py:_refusal_problem` builds it. */
const DURATION_REFUSAL = {
  type: 'urn:meetingminer:problem:acquisition-refused',
  title: 'Unprocessable Content',
  status: 422,
  detail: '4h 02m exceeds the configured 180 minutes.',
  rule: 'duration-cap',
  remediation: 'Raise acquisition.youtube.maxDurationMinutes in config.yaml and restart the worker.',
}

function status(overrides: Partial<AcquisitionStatus> = {}): AcquisitionStatus {
  return {
    acquisitionId: '0190a0f0-7c1e-7000-8000-0000000000aa',
    sourceId: 'youtube:dQw4w9WgXcQ',
    url: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
    status: 'running',
    createdAt: '2026-08-31T10:00:00Z',
    updatedAt: '2026-08-31T10:00:05Z',
    logTail: [],
    ...overrides,
  }
}

describe('refusalOf', () => {
  it('reads the rule, detail and remediation the api sent', () => {
    expect(refusalOf(DURATION_REFUSAL)).toEqual({
      rule: 'duration-cap',
      detail: '4h 02m exceeds the configured 180 minutes.',
      remediation:
        'Raise acquisition.youtube.maxDurationMinutes in config.yaml and restart the worker.',
      type: 'urn:meetingminer:problem:acquisition-refused',
    })
  })

  it('falls back to the problem title when the body carries no rule', () => {
    // The 409 conflict: a problem with no `rule` extension. Leading with
    // "Conflict" beats leading with nothing.
    const conflict = {
      type: 'urn:meetingminer:problem:acquisition-in-progress',
      title: 'Conflict',
      status: 409,
      detail: 'acquisition 0190… is already running for youtube:dQw4w9WgXcQ',
      acquisitionId: '0190a0f0-7c1e-7000-8000-0000000000bb',
      sourceId: 'youtube:dQw4w9WgXcQ',
    }
    expect(refusalOf(conflict)).toMatchObject({
      rule: 'Conflict',
      detail: 'acquisition 0190… is already running for youtube:dQw4w9WgXcQ',
      remediation: null,
      type: 'urn:meetingminer:problem:acquisition-in-progress',
    })
  })

  it('is not fooled by a thrown transport error', () => {
    // The generated client hands back a parsed problem body on a non-2xx and a
    // thrown Error on a transport failure. An outage rendered as a rule
    // refusal would blame the video for the network.
    expect(refusalOf(new TypeError('Failed to fetch'))).toBeNull()
    expect(refusalOf(undefined)).toBeNull()
    expect(refusalOf('boom')).toBeNull()
    expect(refusalOf({})).toBeNull()
  })
})

describe('failureOf', () => {
  it('classifies a problem body as a refusal', () => {
    const failure = failureOf(DURATION_REFUSAL)
    expect(failure.kind).toBe('refusal')
    expect(failureMessage(failure)).toBe(
      'duration-cap: 4h 02m exceeds the configured 180 minutes.',
    )
  })

  it('classifies a thrown error as transport, naming the address that did not answer', () => {
    const failure = failureOf(new TypeError('Failed to fetch'))
    expect(failure).toEqual({
      kind: 'transport',
      message: `Cannot reach the api at ${API_BASE}: Failed to fetch`,
    })
  })

  it('preserves an error-like DOM timeout message as transport', () => {
    expect(failureOf(new DOMException('The operation timed out', 'TimeoutError'))).toEqual({
      kind: 'transport',
      message: `Cannot reach the api at ${API_BASE}: The operation timed out`,
    })
  })

  it('never leaves a failure unexplained', () => {
    expect(failureOf(undefined)).toEqual({
      kind: 'transport',
      message: `Cannot reach the api at ${API_BASE}: the api answered with a body this client cannot read`,
    })
  })
})

describe('refusalOfStatus', () => {
  it('reads a failed acquisition’s refusal fields, never its log', () => {
    const failed = status({
      status: 'failed',
      logTail: ['yt-dlp: duration 4:02:17', 'youtube-drop: duration over cap'],
      refusal: {
        rule: 'duration-cap',
        detail: '4h 02m exceeds the configured 180 minutes.',
        remediation: 'Choose a shorter video.',
      },
    })
    expect(refusalOfStatus(failed)).toEqual({
      rule: 'duration-cap',
      detail: '4h 02m exceeds the configured 180 minutes.',
      remediation: 'Choose a shorter video.',
      type: null,
    })
  })

  it('is null while nothing has been refused', () => {
    expect(refusalOfStatus(status())).toBeNull()
  })
})

describe('isLive', () => {
  it('polls only the two non-terminal statuses', () => {
    expect(isLive('queued')).toBe(true)
    expect(isLive('running')).toBe(true)
    expect(isLive('posted')).toBe(false)
    expect(isLive('failed')).toBe(false)
    // A status this build does not recognise stops polling rather than
    // spinning forever against a state machine it cannot read.
    expect(isLive('something-new')).toBe(false)
    expect(isLive(null)).toBe(false)
  })
})

describe('stepperSteps', () => {
  const names = (steps: ReturnType<typeof stepperSteps>) => steps.map((step) => step.name)
  const statuses = (steps: ReturnType<typeof stepperSteps>) => steps.map((step) => step.status)

  it('always names the four steps in flow order', () => {
    expect(names(stepperSteps('queued', 'queued'))).toEqual([
      'launch',
      'running',
      'posted',
      'ingesting',
    ])
  })

  it('marks launch done as soon as the acquisition exists', () => {
    // 202 means accepted: the record exists whatever it says next.
    expect(statuses(stepperSteps('queued', 'queued'))).toEqual([
      'done',
      'queued',
      'queued',
      'queued',
    ])
  })

  it('pulses running while the tool works', () => {
    expect(statuses(stepperSteps('running', 'queued'))).toEqual([
      'done',
      'running',
      'queued',
      'queued',
    ])
  })

  it('renders an unrecognised acquisition status loudly instead of as queued', () => {
    const steps = stepperSteps('warming-cache', 'queued')
    expect(statuses(steps)).toEqual(['done', 'unknown', 'queued', 'queued'])
    expect(steps[1].label).toBe('running — unknown (warming-cache)')
  })

  it('hands the fourth bar to the ingesting job once posted', () => {
    expect(statuses(stepperSteps('posted', 'running'))).toEqual([
      'done',
      'done',
      'done',
      'running',
    ])
    expect(statuses(stepperSteps('posted', 'done'))).toEqual(['done', 'done', 'done', 'done'])
  })

  it('shows a failed acquisition as failed, with ingestion never started', () => {
    const steps = stepperSteps('failed', 'queued')
    // `running` reads done because `acquisitions.run_acquisition` writes
    // status="running" before it does any work, so every failed record ran.
    expect(statuses(steps)).toEqual(['done', 'done', 'failed', 'queued'])
    // The third word is the verdict: nothing was posted, so it does not say so.
    expect(steps[2].label).toBe('failed')
    expect(steps[3].status).toBe('queued')
  })

  it('carries the job id in the posted word when there is one', () => {
    const steps = stepperSteps('posted', 'running', postedWordFor(status({
      status: 'posted',
      jobId: '8f3c1a2b-0000-7000-8000-0000000000cc',
    })))
    expect(steps[2].label).toBe('posted — job 8f3c1a2b…')
  })

  it('says plain "posted" when no job id has been reported', () => {
    expect(postedWordFor(status({ status: 'posted' }))).toBe('posted')
  })
})

describe('probeSummary', () => {
  const probe = (overrides: Partial<ProbeResult> = {}): ProbeResult => ({
    title: 'Retrieval bake-off review',
    durationMs: 5_040_000,
    captions: { kind: 'manual', language: 'en' },
    sourceId: 'youtube:dQw4w9WgXcQ',
    ...overrides,
  })

  it('reads back exactly what the probe answered', () => {
    expect(probeSummary(probe())).toBe(
      'Retrieval bake-off review · 1h 24m · captions: manual en · youtube:dQw4w9WgXcQ',
    )
  })

  it('says captions: none rather than staying silent', () => {
    // A recording-only drop is valid, so this is a fact, not a refusal — and
    // omitting the clause would leave the reader unsure it was checked.
    expect(probeSummary(probe({ captions: null }))).toBe(
      'Retrieval bake-off review · 1h 24m · captions: none · youtube:dQw4w9WgXcQ',
    )
  })
})
