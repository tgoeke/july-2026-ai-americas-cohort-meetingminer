import { describe, expect, it } from 'vitest'
import type { MomentArtifact } from '@/client/types.gen'
import {
  alignedSegmentId,
  ARTIFACT_CATEGORIES,
  artifactsOfKind,
  durationStatLabel,
  evidenceDurationMs,
  highlightRuns,
  lineageLabel,
  loadFailureOf,
  type MeetingArtifactEntry,
  meetingArtifactGroups,
  meetingLabelOf,
  notViewableMessage,
  participantsOf,
  previewLabel,
  publishedEntries,
  speakerName,
  transportFailureOf,
  wordCountOf,
} from './moments'

describe('ARTIFACT_CATEGORIES', () => {
  it('lists CAP-4’s seven rail categories, verbatim and in order', () => {
    expect(ARTIFACT_CATEGORIES.map((category) => category.label)).toEqual([
      'Action items',
      'ADRs',
      'Decisions',
      'Stories',
      'Requirements',
      'Bug fixes',
      'Change requests',
    ])
  })

  it('pins the kind vocabulary the api serves', () => {
    expect(ARTIFACT_CATEGORIES.map((category) => category.kind)).toEqual([
      'action-item',
      'adr',
      'decision',
      'story',
      'requirement',
      'bug-fix',
      'change-request',
    ])
  })
})

describe('artifactsOfKind', () => {
  it('keeps only the named kind, in api order', () => {
    const artifacts: Array<MomentArtifact> = [
      { id: 'a', kind: 'adr', state: 'extracted', title: 'One', body: '' },
      { id: 'b', kind: 'decision', state: 'approved', title: 'Two', body: '' },
      { id: 'c', kind: 'adr', state: 'published', title: 'Three', body: '' },
    ]
    expect(artifactsOfKind(artifacts, 'adr').map((artifact) => artifact.id)).toEqual([
      'a',
      'c',
    ])
    expect(artifactsOfKind(artifacts, 'story')).toEqual([])
  })
})

describe('loadFailureOf', () => {
  it('recognizes the 409 meeting-not-viewable problem', () => {
    const failure = loadFailureOf({
      type: 'urn:meetingminer:problem:meeting-not-viewable',
      title: 'Conflict',
      status: 409,
      detail: 'meeting m exists but its evidence is still being prepared',
    })
    expect(failure.kind).toBe('notViewable')
  })

  it('recognizes the 404 not-found problem', () => {
    const failure = loadFailureOf({
      type: 'urn:meetingminer:problem:not-found',
      title: 'Not Found',
      status: 404,
      detail: 'no moment with id m',
    })
    expect(failure.kind).toBe('notFound')
  })

  it('keeps any other refusal as a problem with the api’s own sentence', () => {
    const failure = loadFailureOf({
      type: 'urn:meetingminer:problem:invalid-request',
      title: 'Unprocessable Content',
      status: 422,
      detail: 'request failed validation',
    })
    expect(failure).toEqual({
      kind: 'problem',
      message: 'Unprocessable Content: request failed validation',
    })
  })

  it('never throws on a shapeless error body', () => {
    expect(loadFailureOf(undefined).kind).toBe('problem')
    expect(loadFailureOf('boom').kind).toBe('problem')
  })
})

describe('transportFailureOf', () => {
  it('names the thrown error', () => {
    expect(transportFailureOf(new Error('connection refused'))).toEqual({
      kind: 'transport',
      message: 'connection refused',
    })
  })
})

describe('meetingLabelOf', () => {
  it('prefers the title and falls back to the meeting id on null or blank', () => {
    expect(meetingLabelOf('Data Hub Demo', 'm-1')).toBe('Data Hub Demo')
    expect(meetingLabelOf(null, 'm-1')).toBe('m-1')
    expect(meetingLabelOf(undefined, 'm-1')).toBe('m-1')
    expect(meetingLabelOf('  ', 'm-1')).toBe('m-1')
  })
})

describe('previewLabel', () => {
  it('shows the first line, or the honest sentence for a span with none', () => {
    expect(previewLabel('Everybody, good morning.')).toBe('Everybody, good morning.')
    expect(previewLabel(null)).toBe('No transcript covers this span.')
    expect(previewLabel('   ')).toBe('No transcript covers this span.')
  })
})

describe('speakerName', () => {
  it('reads a blank label as Unknown, like the projection does', () => {
    expect(speakerName('Goeke, Timothy')).toBe('Goeke, Timothy')
    expect(speakerName('   ')).toBe('Unknown')
  })
})

describe('highlightRuns', () => {
  it('returns the whole text as one un-highlighted run for an empty term', () => {
    expect(highlightRuns('Everybody, good morning.', '')).toEqual([
      { text: 'Everybody, good morning.', highlighted: false },
    ])
    expect(highlightRuns('Everybody, good morning.', '   ')).toEqual([
      { text: 'Everybody, good morning.', highlighted: false },
    ])
  })

  it('marks every case-insensitive occurrence and keeps the original casing', () => {
    expect(highlightRuns('Feed the FEED to the feeder.', 'feed')).toEqual([
      { text: 'Feed', highlighted: true },
      { text: ' the ', highlighted: false },
      { text: 'FEED', highlighted: true },
      { text: ' to the ', highlighted: false },
      { text: 'feed', highlighted: true },
      { text: 'er.', highlighted: false },
    ])
  })

  it('returns one un-highlighted run when nothing matches', () => {
    expect(highlightRuns('Morning, all.', 'purchase')).toEqual([
      { text: 'Morning, all.', highlighted: false },
    ])
  })

  it('handles a match at the very start and the very end', () => {
    expect(highlightRuns('order to order', 'order')).toEqual([
      { text: 'order', highlighted: true },
      { text: ' to ', highlighted: false },
      { text: 'order', highlighted: true },
    ])
  })

  it('treats regex metacharacters in the term as literal text', () => {
    expect(highlightRuns('cost is $4.20 today', '$4.20')).toEqual([
      { text: 'cost is ', highlighted: false },
      { text: '$4.20', highlighted: true },
      { text: ' today', highlighted: false },
    ])
  })

  it('maps a length-changing case fold before an ordinary match to original text', () => {
    const text = 'İpek discussed the contract'
    expect(text.toLowerCase().length).not.toBe(text.length)
    expect(highlightRuns(text, 'contract')).toEqual([
      { text: 'İpek discussed the ', highlighted: false },
      { text: 'contract', highlighted: true },
    ])
  })

  it('preserves whole-string lowercase semantics while mapping to source text', () => {
    expect('ΟΣ'.toLowerCase()).toBe('ος')
    expect(highlightRuns('ΟΣ', 'ος')).toEqual([{ text: 'ΟΣ', highlighted: true }])
  })
})

function entry(
  id: string,
  kind: MomentArtifact['kind'],
  startMs: number,
  state: MomentArtifact['state'] = 'extracted',
): MeetingArtifactEntry {
  return {
    artifact: { id, kind, state, title: id, body: '' },
    momentId: `moment-${id}`,
    startMs,
    endMs: startMs + 1_000,
  }
}

describe('meetingArtifactGroups', () => {
  it('groups by kind in category order, entries in offset order, empty kinds omitted', () => {
    const groups = meetingArtifactGroups([
      entry('late-action', 'action-item', 40_000),
      entry('decision', 'decision', 10_000),
      entry('early-action', 'action-item', 2_000),
    ])
    expect(groups.map((group) => group.kind)).toEqual(['action-item', 'decision'])
    expect(groups[0].entries.map((e) => e.artifact.id)).toEqual([
      'early-action',
      'late-action',
    ])
    expect(groups[0].label).toBe('Action items')
  })

  it('returns nothing for no entries — no zero-count headers', () => {
    expect(meetingArtifactGroups([])).toEqual([])
  })
})

describe('publishedEntries', () => {
  it('keeps only published rows, in offset order', () => {
    const published = publishedEntries([
      entry('later', 'adr', 30_000, 'published'),
      entry('draft', 'adr', 5_000, 'extracted'),
      entry('earlier', 'decision', 10_000, 'published'),
    ])
    expect(published.map((e) => e.artifact.id)).toEqual(['earlier', 'later'])
  })
})

describe('wordCountOf', () => {
  it('counts whitespace-separated words across every segment', () => {
    expect(
      wordCountOf([{ text: 'Everybody, good morning.' }, { text: '  one  two ' }]),
    ).toBe(5)
    expect(wordCountOf([{ text: '   ' }])).toBe(0)
    expect(wordCountOf([])).toBe(0)
  })
})

describe('evidenceDurationMs', () => {
  it('is the furthest end any screenshot or segment reaches', () => {
    expect(
      evidenceDurationMs({
        screenshots: [{ endOffsetMs: 30_000 }],
        segments: [{ endMs: 46_000 }, { endMs: 4_000 }],
      }),
    ).toBe(46_000)
    expect(evidenceDurationMs({ screenshots: [], segments: [] })).toBe(0)
  })
})

describe('durationStatLabel', () => {
  it('states minutes, seconds under a minute, nothing for no extent', () => {
    expect(durationStatLabel(5_940_000)).toBe('99 min')
    expect(durationStatLabel(60_000)).toBe('1 min')
    expect(durationStatLabel(42_000)).toBe('42 s')
    expect(durationStatLabel(0)).toBeNull()
    expect(durationStatLabel(Number.NaN)).toBeNull()
  })
})

describe('lineageLabel', () => {
  it('states evidence shape and speaker attribution from the payload', () => {
    expect(
      lineageLabel(true, [
        { speakerResolution: 'resolved' },
        { speakerResolution: 'unresolved' },
      ]),
    ).toBe('Recording + transcript · speaker-attributed')
    expect(lineageLabel(false, [{ speakerResolution: 'placeholder' }])).toBe(
      'Transcript only — no recording · diarized speaker slots only',
    )
    expect(lineageLabel(false, [{ speakerResolution: 'unresolved' }])).toBe(
      'Transcript only — no recording · speakers unresolved',
    )
    expect(lineageLabel(true, [])).toBe('Recording + transcript · no transcript segments')
  })
})

describe('participantsOf', () => {
  it('lists distinct resolved participants in first-spoken order with turn counts', () => {
    const participants = participantsOf([
      { segmentId: 's-1', speakerLabel: 'Goeke, Timothy', participantId: 'p-1' },
      { segmentId: 's-2', speakerLabel: 'Speaker 8', participantId: null },
      { segmentId: 's-3', speakerLabel: 'Whitmore, Ellis', participantId: 'p-2' },
      { segmentId: 's-4', speakerLabel: 'Goeke, Timothy', participantId: 'p-1' },
    ])
    expect(participants).toEqual([
      { participantId: 'p-1', name: 'Goeke, Timothy', turns: 2, firstSegmentId: 's-1' },
      { participantId: 'p-2', name: 'Whitmore, Ellis', turns: 1, firstSegmentId: 's-3' },
    ])
  })

  it('is empty when no segment resolved to a participant', () => {
    expect(
      participantsOf([{ segmentId: 's-1', speakerLabel: 'Speaker 1', participantId: null }]),
    ).toEqual([])
  })
})

describe('alignedSegmentId', () => {
  const segments = [
    { segmentId: 's-1', startMs: 2_000 },
    { segmentId: 's-2', startMs: 40_000 },
    { segmentId: 's-3', startMs: 44_000 },
  ]

  it('picks the last segment starting at or before the offset', () => {
    expect(alignedSegmentId(segments, 41_000)).toBe('s-2')
    expect(alignedSegmentId(segments, 40_000)).toBe('s-2')
    expect(alignedSegmentId(segments, 500_000)).toBe('s-3')
  })

  it('falls back to the first segment for a capture before them all', () => {
    expect(alignedSegmentId(segments, 0)).toBe('s-1')
  })

  it('is null only for an empty transcript', () => {
    expect(alignedSegmentId([], 1_000)).toBeNull()
  })
})

describe('notViewableMessage', () => {
  const base = {
    type: 'urn:meetingminer:problem:meeting-not-viewable',
    title: 'Conflict',
    status: 409,
    detail: 'meeting m exists but its evidence is still being prepared',
    meetingId: 'm',
  }

  it('names augmentation when the 409 says one is in flight', () => {
    expect(
      notViewableMessage({ ...base, augmenting: true, jobStatus: 'running' }),
    ).toContain('augmented')
  })

  it('prefers failed copy over augmentation copy (blockedReason puts failure first)', () => {
    // A failed augmentation will never settle; "reopens once the re-run
    // settles" would be waiting copy for a run that is over.
    const message = notViewableMessage({ ...base, augmenting: true, jobStatus: 'failed' })
    expect(message).toContain('failed')
    expect(message).not.toContain('augmented')
  })

  it('names the failure when the job failed without augmenting', () => {
    expect(
      notViewableMessage({ ...base, augmenting: false, jobStatus: 'failed' }),
    ).toContain('failed')
  })

  it('falls back to preparing copy otherwise, including on a bare problem', () => {
    expect(
      notViewableMessage({ ...base, augmenting: false, jobStatus: 'running' }),
    ).toContain('first ingest')
    // A 409 from an api without the extensions (or none at all) still answers.
    expect(notViewableMessage(base)).toContain('first ingest')
    expect(notViewableMessage(null)).toContain('first ingest')
  })
})
