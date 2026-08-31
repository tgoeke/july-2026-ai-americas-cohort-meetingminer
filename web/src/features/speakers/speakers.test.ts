import { describe, expect, it } from 'vitest'
import type { DrilldownSegment, ParticipantRow, SpeakerTag } from '@/client/types.gen'
import {
  applyJobEvent,
  assignmentBody,
  assignmentRefusal,
  choiceOf,
  durationLabel,
  failedSentence,
  failedStage,
  isReprocessing,
  isResolved,
  landedSentence,
  loadFailureOf,
  reprocessingSentence,
  resolvedName,
  rerunFrom,
  segmentsOfTag,
  speakerMetaLabel,
  speakerRowLabel,
  suggestionsFor,
  talkSharePercent,
  totalTalkTimeMs,
  transportFailureOf,
} from './speakers'

function tag(overrides: Partial<SpeakerTag> = {}): SpeakerTag {
  return {
    speakerLabel: 'SPEAKER_00',
    speakerResolution: 'placeholder',
    participantId: null,
    displayName: null,
    talkTimeMs: 1_431_000,
    segmentCount: 112,
    sampleOffsetsMs: [252_000, 1_180_000, 2_467_000],
    ...overrides,
  }
}

function participant(overrides: Partial<ParticipantRow> = {}): ParticipantRow {
  return {
    id: 'p-1',
    identityKey: 'name:priya natarajan',
    displayName: 'Priya Natarajan',
    normalizedName: 'priya natarajan',
    mergedIntoParticipantId: null,
    createdAt: '2026-08-05T12:00:00Z',
    updatedAt: '2026-08-05T12:00:00Z',
    ...overrides,
  }
}

function segment(overrides: Partial<DrilldownSegment> = {}): DrilldownSegment {
  return {
    segmentId: 's-1',
    ordinal: 1,
    startMs: 252_000,
    endMs: 260_000,
    speakerLabel: 'SPEAKER_00',
    speakerResolution: 'placeholder',
    participantId: null,
    text: 'The retrieval split held up.',
    momentId: null,
    ...overrides,
  }
}

describe('never naming a tag the system has not resolved (AD-13)', () => {
  it.each(['placeholder', 'unresolved', 'ambiguous'])(
    'reports %s as unresolved and prints no name',
    (resolution) => {
      const row = tag({ speakerResolution: resolution })
      expect(isResolved(row)).toBe(false)
      expect(resolvedName(row)).toBeNull()
    },
  )

  it('refuses a name a resolution word does not back', () => {
    // A payload that carried a display name on a placeholder row would be a
    // server bug; printing it anyway would make this screen the place the
    // guess became visible.
    const row = tag({ speakerResolution: 'placeholder', displayName: 'Priya Natarajan' })
    expect(isResolved(row)).toBe(false)
    expect(resolvedName(row)).toBeNull()
  })

  it('refuses a resolution word no participant backs', () => {
    const row = tag({ speakerResolution: 'resolved', participantId: null })
    expect(isResolved(row)).toBe(false)
  })

  it('names a row the api actually resolved', () => {
    const row = tag({
      speakerResolution: 'resolved',
      participantId: 'p-1',
      displayName: 'Priya Natarajan',
    })
    expect(isResolved(row)).toBe(true)
    expect(resolvedName(row)).toBe('Priya Natarajan')
  })
})

describe('talk share and the meta line', () => {
  it('is the row over the sum, as an integer percent', () => {
    const rows = [tag({ talkTimeMs: 1_431_000 }), tag({ talkTimeMs: 943_000 })]
    const total = totalTalkTimeMs(rows)
    expect(total).toBe(2_374_000)
    expect(talkSharePercent(rows[0], total)).toBe(60)
    expect(talkSharePercent(rows[1], total)).toBe(40)
  })

  it('is zero rather than NaN when nothing was said', () => {
    const rows = [tag({ talkTimeMs: 0 })]
    expect(talkSharePercent(rows[0], totalTalkTimeMs(rows))).toBe(0)
  })

  it.each([
    [0, '0s'],
    [48_000, '48s'],
    [723_000, '12m 03s'],
    [1_431_000, '23m 51s'],
    [3_840_000, '1h 04m'],
  ])('renders %ims as %s', (ms, expected) => {
    expect(durationLabel(ms)).toBe(expected)
  })

  it('writes the meta line the mockup shows', () => {
    expect(speakerMetaLabel(tag())).toBe('23m 51s · 112 segments')
  })

  it('does not pluralize a single segment', () => {
    expect(speakerMetaLabel(tag({ talkTimeMs: 4000, segmentCount: 1 }))).toBe(
      '4s · 1 segment',
    )
  })
})

describe('the row accessible name carries what the bar cannot say', () => {
  it('names an unresolved tag by its resolution, never by a person', () => {
    expect(speakerRowLabel(tag(), 41, false)).toBe(
      'SPEAKER_00, placeholder, 41 percent talk share',
    )
  })

  it('names a resolved tag and its selection', () => {
    const row = tag({
      speakerResolution: 'resolved',
      participantId: 'p-1',
      displayName: 'Priya Natarajan',
    })
    expect(speakerRowLabel(row, 41, true)).toBe(
      'SPEAKER_00, selected, resolved to Priya Natarajan, 41 percent talk share',
    )
  })
})

describe('the three assignment choices', () => {
  it('sends only the participant id when a suggestion was picked', () => {
    const choice = choiceOf('Priya Natarajan', participant())
    expect(choice).toEqual({
      kind: 'participant',
      participantId: 'p-1',
      displayName: 'Priya Natarajan',
    })
    expect(assignmentBody(choice!)).toEqual({ participantId: 'p-1' })
  })

  it('sends only the display name when the curator typed one', () => {
    const choice = choiceOf('Alice Chen', null)
    expect(choice).toEqual({ kind: 'newName', displayName: 'Alice Chen' })
    expect(assignmentBody(choice!)).toEqual({ displayName: 'Alice Chen' })
  })

  it('sends only the unresolved flag', () => {
    expect(assignmentBody({ kind: 'unresolved' })).toEqual({ unresolved: true })
  })

  it('drops a picked participant once the field no longer holds its name', () => {
    // Picking `Priya Natarajan` and then typing over it means the curator
    // changed their mind; sending the stale id would save the wrong person.
    const choice = choiceOf('Priyanka Rao', participant())
    expect(choice).toEqual({ kind: 'newName', displayName: 'Priyanka Rao' })
  })

  it('has nothing to send for an empty field', () => {
    expect(choiceOf('', null)).toBeNull()
    expect(choiceOf('   ', participant())).toBeNull()
  })
})

describe('suggestions are a filter, never a decision', () => {
  const roster = [
    participant(),
    participant({ id: 'p-2', displayName: 'Tim Goeke' }),
    participant({ id: 'p-3', displayName: 'Priyanka Rao' }),
    participant({ id: 'p-4', displayName: 'Old Row', mergedIntoParticipantId: 'p-1' }),
  ]

  it('suggests nothing for an untouched field', () => {
    expect(suggestionsFor(roster, '')).toEqual([])
  })

  it('matches case-insensitively anywhere in the name', () => {
    expect(suggestionsFor(roster, 'pri').map((row) => row.id)).toEqual(['p-1', 'p-3'])
    expect(suggestionsFor(roster, 'GOEKE').map((row) => row.id)).toEqual(['p-2'])
  })

  it('never suggests a merged-away row', () => {
    expect(suggestionsFor(roster, 'old')).toEqual([])
  })

  it('caps the list', () => {
    const many = Array.from({ length: 20 }, (_, index) =>
      participant({ id: `p-${index}`, displayName: `Priya ${index}` }),
    )
    expect(suggestionsFor(many, 'priya')).toHaveLength(8)
  })
})

describe('the tag-filtered transcript', () => {
  it('keeps only the selected tag, in transcript order', () => {
    const segments = [
      segment({ segmentId: 's-1', speakerLabel: 'SPEAKER_00' }),
      segment({ segmentId: 's-2', speakerLabel: 'SPEAKER_03' }),
      segment({ segmentId: 's-3', speakerLabel: 'SPEAKER_00' }),
    ]
    expect(segmentsOfTag(segments, 'SPEAKER_00').map((row) => row.segmentId)).toEqual([
      's-1',
      's-3',
    ])
  })
})

describe('the rerun a naming starts', () => {
  const started = () =>
    rerunFrom('job-1', 'SPEAKER_00', 'Priya Natarajan', ['align', 'moments', 'extract'], false)

  it('opens with every re-armed stage queued', () => {
    expect(started().stages).toEqual([
      { name: 'align', status: 'queued', error: null },
      { name: 'moments', status: 'queued', error: null },
      { name: 'extract', status: 'queued', error: null },
    ])
    expect(isReprocessing(started())).toBe(true)
  })

  it('falls back to the three stages when the body named none', () => {
    expect(rerunFrom('job-1', 'SPEAKER_00', null, [], false).stages.map((s) => s.name)).toEqual(
      ['align', 'moments', 'extract'],
    )
  })

  it('applies a stage frame for its own job', () => {
    const next = applyJobEvent(
      started(),
      { jobId: 'job-1', event: 'job.stage', stage: 'align', status: 'running' },
      '2026-08-31T12:00:00Z',
    )
    expect(next.stages[0]).toEqual({ name: 'align', status: 'running', error: null })
  })

  it('ignores another job entirely', () => {
    const before = started()
    expect(
      applyJobEvent(
        before,
        { jobId: 'job-2', event: 'job.stage', stage: 'align', status: 'running' },
        '2026-08-31T12:00:00Z',
      ),
    ).toBe(before)
  })

  it('ignores a stage this naming did not re-arm', () => {
    // The same job carries the whole pipeline; a strip labelled "rerun" must
    // not claim `ocr` re-ran.
    const before = started()
    expect(
      applyJobEvent(
        before,
        { jobId: 'job-1', event: 'job.stage', stage: 'ocr', status: 'running' },
        '2026-08-31T12:00:00Z',
      ),
    ).toBe(before)
  })

  it('lands on job.done and stamps when', () => {
    const landed = applyJobEvent(
      started(),
      { jobId: 'job-1', event: 'job.done', jobStatus: 'done' },
      '2026-08-29 14:02:11',
    )
    expect(landed.stages.every((stage) => stage.status === 'done')).toBe(true)
    expect(landed.landedAt).toBe('2026-08-29 14:02:11')
    expect(isReprocessing(landed)).toBe(false)
    expect(landedSentence(landed)).toBe(
      'Rerun landed 2026-08-29 14:02:11 — transcript, graph, and extractions now' +
        ' name SPEAKER_00 as Priya Natarajan. Moment ids and citations unchanged.',
    )
  })

  it('states the unresolved landing without inventing a name', () => {
    const rerun = rerunFrom('job-1', 'SPEAKER_03', null, ['align'], false)
    const landed = applyJobEvent(
      rerun,
      { jobId: 'job-1', event: 'job.done' },
      '2026-08-29 14:05:00',
    )
    expect(landedSentence(landed)).toContain('now leave SPEAKER_03 unresolved')
  })

  it('keeps a failed stage failed through the settle frame', () => {
    const failed = applyJobEvent(
      started(),
      { jobId: 'job-1', event: 'job.error', stage: 'moments', error: 'ollama refused' },
      '2026-08-31T12:00:00Z',
    )
    const settled = applyJobEvent(
      failed,
      { jobId: 'job-1', event: 'job.done' },
      '2026-08-31T12:01:00Z',
    )
    expect(failedStage(settled)).toEqual({
      name: 'moments',
      status: 'failed',
      error: 'ollama refused',
    })
    expect(failedSentence(failedStage(settled)!)).toBe(
      'Rerun failed at moments — ollama refused. Names are saved; the transcript' +
        ' still shows tags.',
    )
    expect(isReprocessing(settled)).toBe(false)
  })

  it('says the meeting is reprocessing rather than leaving it looking hung', () => {
    expect(reprocessingSentence(started())).toBe(
      'Reprocessing this meeting — align, moments, extract re-armed by naming' +
        ' SPEAKER_00. The transcript below is the pre-rerun reading.',
    )
  })
})

describe('classifying what the api refused', () => {
  it('recognises the not-viewable 409 this screen must survive', () => {
    expect(
      loadFailureOf({
        type: 'urn:meetingminer:problem:meeting-not-viewable',
        title: 'meeting not viewable',
        detail: 'its evidence is being rebuilt',
      }),
    ).toEqual({
      kind: 'notViewable',
      message: 'meeting not viewable: its evidence is being rebuilt',
    })
  })

  it('recognises a 404 and any other refusal', () => {
    expect(
      loadFailureOf({ type: 'urn:meetingminer:problem:not-found', detail: 'no meeting' }).kind,
    ).toBe('notFound')
    expect(loadFailureOf({ title: 'something else' }).kind).toBe('problem')
  })

  it('names a transport failure when the api never answered', () => {
    expect(transportFailureOf(new Error('fetch failed'))).toEqual({
      kind: 'transport',
      message: 'fetch failed',
    })
  })

  it('reads an assignment refusal as the api wrote it', () => {
    expect(
      assignmentRefusal({
        title: 'assignment target busy',
        detail: "meeting's job is still running",
      }),
    ).toBe("assignment target busy: meeting's job is still running")
  })
})
