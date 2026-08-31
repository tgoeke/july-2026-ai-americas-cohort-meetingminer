import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from 'react'
import {
  assignMeetingSpeaker,
  getJob,
  getMeetingDrilldown,
  listMeetingSpeakers,
  listParticipants,
} from '@/client/sdk.gen'
import type { DrilldownSegment, ParticipantRow, SpeakerTag } from '@/client/types.gen'
import { Button } from '@/components/ui/button'
import { BAR_CLASS, LABEL_CLASS, asStageStatus } from '@/features/meetings/stageStyles'
import { useJobEvents } from '@/features/meetings/useJobEvents'
import { ReplayPlayer } from '@/features/replay/ReplayPlayer'
import { offsetLabel } from '@/lib/affordance'
import { API_BASE } from '@/lib/api'
import { cn } from '@/lib/utils'
import {
  applyJobEvent,
  assignmentBody,
  assignmentRefusal,
  choiceOf,
  CLIP_LENGTH_MS,
  durationLabel,
  failedSentence,
  failedStage,
  isReprocessing,
  landedSentence,
  loadFailureOf,
  NO_SPEAKER_TAGS,
  reprocessingSentence,
  reconcileRerunFromJob,
  resolvedName,
  rerunFrom,
  type RerunState,
  segmentsOfTag,
  speakerMetaLabel,
  speakerRowLabel,
  SPEAKERS_TIMEOUT_MS,
  suggestionsFor,
  SUGGESTION_NOTE,
  talkSharePercent,
  totalTalkTimeMs,
  transportFailureOf,
  UNRESOLVED_ON_RESOLVED_NOTE,
  type SpeakersLoadFailure,
} from './speakers'

export interface SpeakerNamingProps {
  /** The meeting whose voices are being named. */
  meetingId: string
  /** Leaving the screen is the shell's navigation to make (story 2.2's idiom). */
  onBack?: () => void
}

/** `2026-08-29 14:02:11` — the landed sentence's stamp, in the spine's format. */
function stampNow(): string {
  return new Date().toISOString().replace('T', ' ').slice(0, 19)
}

/**
 * Story 7.4: who spoke when, and who they are — named by a human.
 *
 * Three columns at full density (speakers · clips and naming · the selected
 * tag's transcript), one column below 900px in DOM order.
 *
 * The screen's defining constraint is not its layout but its relationship
 * with story 7.3's write route. That `PUT` is deliberately admitted while a
 * meeting's evidence is unsettled — the recovery path for a rerun that failed
 * on a bad naming — while both of this screen's own reads,
 * `GET …/speakers` and `GET …/drilldown`, keep refusing with 409
 * `meeting-not-viewable`. So a *successful* naming makes this screen's reads
 * start failing seconds later, every time.
 *
 * Everything below follows from that. A refused re-read never clears what is
 * on screen: the last-known rows and segments stay, labelled as the pre-rerun
 * reading, and every naming control stays live. Blanking on the 409 would
 * take the screen away at exactly the moment story 7.3 built an exception to
 * keep it.
 */
export function SpeakerNaming(props: SpeakerNamingProps) {
  // React Router reuses a route element when only a path parameter changes.
  // Key the stateful screen by the meeting identity so the old meeting's rows
  // cannot survive even one render with the new request path.
  return <SpeakerNamingForMeeting key={props.meetingId} {...props} />
}

function SpeakerNamingForMeeting({ meetingId, onBack }: SpeakerNamingProps) {
  // `null` is "never answered". Once a read has answered, its rows survive a
  // later refusal — see the class comment.
  const [speakers, setSpeakers] = useState<Array<SpeakerTag> | null>(null)
  const [speakersFailure, setSpeakersFailure] = useState<SpeakersLoadFailure | null>(null)
  const [segments, setSegments] = useState<Array<DrilldownSegment> | null>(null)
  const [transcriptFailure, setTranscriptFailure] = useState<SpeakersLoadFailure | null>(null)
  const [meetingTitle, setMeetingTitle] = useState<string | null>(null)
  const [startedAt, setStartedAt] = useState<string | null>(null)
  const [hasRecording, setHasRecording] = useState(false)
  const [participants, setParticipants] = useState<Array<ParticipantRow>>([])

  const [selectedTag, setSelectedTag] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [picked, setPicked] = useState<ParticipantRow | null>(null)
  const [highlighted, setHighlighted] = useState(-1)
  const [listOpen, setListOpen] = useState(false)

  // The one clip playing, as `<tag>#<index>` — the single-open-player key
  // `CorpusSearch` and `MeetingMoments` already use.
  const [clip, setClip] = useState<{
    tag: string
    index: number
    startMs: number
    playId: number
  } | null>(null)

  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [rerun, setRerun] = useState<RerunState | null>(null)
  const [pendingAssignments, setPendingAssignments] = useState<
    Record<string, { displayName: string | null }>
  >({})

  const readControllerRef = useRef<AbortController | null>(null)
  const saveControllerRef = useRef<AbortController | null>(null)
  const nameInputRef = useRef<HTMLInputElement>(null)
  const rowRefs = useRef(new Map<string, HTMLButtonElement>())
  const clipSequenceRef = useRef(0)
  const rerunRef = useRef<RerunState | null>(null)

  const load = useCallback(async (settledReread = false) => {
    readControllerRef.current?.abort()
    const controller = new AbortController()
    readControllerRef.current = controller
    const expiry = new AbortController()
    const timer = setTimeout(() => expiry.abort(), SPEAKERS_TIMEOUT_MS)
    const signal = AbortSignal.any([controller.signal, expiry.signal])
    const timedOut = (): SpeakersLoadFailure => ({
      kind: 'transport',
      message: `timed out after ${SPEAKERS_TIMEOUT_MS}ms`,
    })

    const readSpeakers = async () => {
      try {
        const { data, error } = await listMeetingSpeakers({
          path: { meeting_id: meetingId },
          signal,
        })
        if (controller.signal.aborted) return
        if (expiry.signal.aborted) return setSpeakersFailure(timedOut())
        if (error !== undefined) return setSpeakersFailure(loadFailureOf(error))
        if (data === undefined) throw new Error('the api answered with no body')
        setSpeakers(data.speakers)
        if (settledReread) setPendingAssignments({})
        setSpeakersFailure(null)
      } catch (err) {
        if (controller.signal.aborted) return
        setSpeakersFailure(expiry.signal.aborted ? timedOut() : transportFailureOf(err))
      }
    }

    // The transcript is a separate read with a separate failure: a drill-down
    // that refuses must cost the transcript column and nothing else, because
    // naming a voice needs the speakers list, not the transcript.
    const readTranscript = async () => {
      try {
        const { data, error } = await getMeetingDrilldown({
          path: { meeting_id: meetingId },
          signal,
        })
        if (controller.signal.aborted) return
        if (expiry.signal.aborted) return setTranscriptFailure(timedOut())
        if (error !== undefined) return setTranscriptFailure(loadFailureOf(error))
        if (data === undefined) throw new Error('the api answered with no body')
        setSegments(data.segments)
        setMeetingTitle(data.title ?? null)
        setStartedAt(data.startedAt)
        setHasRecording(data.hasRecording)
        setTranscriptFailure(null)
      } catch (err) {
        if (controller.signal.aborted) return
        setTranscriptFailure(expiry.signal.aborted ? timedOut() : transportFailureOf(err))
      }
    }

    // Suggestions are a convenience; a roster that will not load costs the
    // suggestion list, never the ability to type a name.
    const readParticipants = async () => {
      try {
        const { data } = await listParticipants({ signal })
        if (controller.signal.aborted || data === undefined) return
        setParticipants(data)
      } catch {
        /* the field still takes a typed name */
      }
    }

    await Promise.all([readSpeakers(), readTranscript(), readParticipants()])
    clearTimeout(timer)
  }, [meetingId])

  useEffect(() => {
    void load()
    return () => {
      readControllerRef.current?.abort()
      saveControllerRef.current?.abort()
    }
  }, [load])

  const installRerun = useCallback((next: RerunState | null) => {
    rerunRef.current = next
    setRerun(next)
  }, [])

  const reconcileRerun = useCallback(
    async (expected: RerunState | null) => {
      if (expected === null) return
      try {
        const { data, error } = await getJob({
          path: { job_id: expected.jobId },
        })
        if (error !== undefined || data === undefined) return
        // Object identity is the rerun generation. The job id is reused, so
        // a snapshot requested for an older assignment may not overwrite a
        // newer re-arm even though both responses carry the same id.
        if (rerunRef.current !== expected) return
        installRerun(reconcileRerunFromJob(expected, data, stampNow()))
      } catch {
        // The live-connection state below names an unavailable stream. A
        // failed one-shot reconciliation leaves the last honest state drawn.
      }
    },
    [installRerun],
  )

  // One `/jobs/events` connection for the life of the screen. Stage frames
  // can fold directly; terminal frames reconcile through GET /jobs because
  // consecutive assignments reuse this meeting's job id.
  const onJobEvent = useCallback(
    (event: Parameters<typeof applyJobEvent>[1]) => {
      const current = rerunRef.current
      if (current === null || event.jobId !== current.jobId) return
      if (event.event === 'job.done' || event.event === 'job.error') {
        void reconcileRerun(current)
        return
      }
      installRerun(applyJobEvent(current, event, stampNow()))
    },
    [installRerun, reconcileRerun],
  )
  const onResync = useCallback(() => {
    void reconcileRerun(rerunRef.current)
  }, [reconcileRerun])
  const jobConnection = useJobEvents({ onEvent: onJobEvent, onResync })

  // When the rerun lands, both reads become legal again and the transcript
  // that now carries the name is one fetch away. This is Flow 3's climax, and
  // it is the only automatic re-read on the screen.
  const landedAt = rerun?.landedAt ?? null
  useEffect(() => {
    if (landedAt === null) return
    void load(true)
  }, [landedAt, load])

  // Memoized so the empty case is one stable array rather than a fresh one
  // per render: `rows` is a dependency of the selection effect below, and a
  // new identity every render would re-run it forever.
  const rows = useMemo(() => speakers ?? [], [speakers])
  const totalMs = useMemo(() => totalTalkTimeMs(rows), [rows])
  const selected = rows.find((row) => row.speakerLabel === selectedTag) ?? null

  // The loudest voice is the one a curator names first; selecting it saves a
  // click on arrival and gives the clips and transcript columns something to
  // show. Only ever on the first answered read — a re-read after a rerun must
  // not move the selection out from under whoever is mid-naming.
  useEffect(() => {
    setSelectedTag((current) => {
      if (current !== null) return current
      return rows.length > 0 ? rows[0].speakerLabel : null
    })
  }, [rows])

  const selectTag = useCallback((tag: string, focusField = false) => {
    setSelectedTag(tag)
    setDraft('')
    setPicked(null)
    setListOpen(false)
    setHighlighted(-1)
    setSaveError(null)
    setClip(null)
    if (focusField) window.setTimeout(() => nameInputRef.current?.focus(), 0)
  }, [])

  const suggestions = useMemo(
    () => suggestionsFor(participants, draft),
    [participants, draft],
  )
  const choice = useMemo(() => choiceOf(draft, picked), [draft, picked])

  const save = useCallback(
    async (kind: 'choice' | 'unresolved') => {
      if (selected === null) return
      const body =
        kind === 'unresolved'
          ? assignmentBody({ kind: 'unresolved' })
          : choice === null
            ? null
            : assignmentBody(choice)
      if (body === null) return
      saveControllerRef.current?.abort()
      const controller = new AbortController()
      saveControllerRef.current = controller
      setSaving(true)
      setSaveError(null)
      const expiry = new AbortController()
      const timer = setTimeout(() => expiry.abort(), SPEAKERS_TIMEOUT_MS)
      try {
        const { data, error } = await assignMeetingSpeaker({
          path: { meeting_id: meetingId, tag: selected.speakerLabel },
          body,
          signal: AbortSignal.any([controller.signal, expiry.signal]),
        })
        if (controller.signal.aborted) return
        if (expiry.signal.aborted) {
          setSaveError(`timed out after ${SPEAKERS_TIMEOUT_MS}ms`)
          return
        }
        if (error !== undefined) {
          setSaveError(assignmentRefusal(error))
          return
        }
        if (data === undefined) throw new Error('the api answered with no body')
        const assignedName = data.displayName ?? null
        setPendingAssignments((current) => ({
          ...current,
          [data.speakerLabel]: { displayName: assignedName },
        }))
        const startedRerun = rerunFrom(
          data.jobId,
          data.speakerLabel,
          assignedName,
          data.rearmedStages,
          data.acceptedWhileUnviewable,
        )
        installRerun(startedRerun)
        void reconcileRerun(startedRerun)
        setDraft('')
        setPicked(null)
        setListOpen(false)
        // Deliberately no re-read here. The re-arm this PUT just performed is
        // what makes the meeting unviewable, so an immediate `GET …/speakers`
        // answers 409 and would replace a screen that works with a refusal.
        // The re-read happens when the rerun lands.
      } catch (err) {
        if (controller.signal.aborted) return
        setSaveError(
          expiry.signal.aborted
            ? `timed out after ${SPEAKERS_TIMEOUT_MS}ms`
            : err instanceof Error
              ? `Cannot reach the api at ${API_BASE}: ${err.message}.`
              : `Cannot reach the api at ${API_BASE}.`,
        )
      } finally {
        clearTimeout(timer)
        setSaving(false)
      }
    },
    [choice, installRerun, meetingId, reconcileRerun, selected],
  )

  const playClip = useCallback(
    (tag: string, index: number, startMs: number) => {
      setClip({ tag, index, startMs, playId: ++clipSequenceRef.current })
    },
    [],
  )

  /**
   * The screen's single-key shortcuts, scoped to this region rather than the
   * window. EXPERIENCE.md puts `1` `2` `3` and `u` behind story 10.5's
   * Single-key shortcuts toggle; that toggle does not exist yet, and a
   * window-level handler with no way to turn it off is the WCAG 2.1.4 problem
   * the toggle exists to solve. Scoped here, the keys act only while focus is
   * inside the panel, and never inside its text field.
   */
  const onPanelKeyDown = useCallback(
    (event: KeyboardEvent<HTMLDivElement>) => {
      const target = event.target as HTMLElement
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA') return
      if (selected === null) return
      if (event.key === 'u') {
        event.preventDefault()
        void save('unresolved')
        return
      }
      const index = ['1', '2', '3'].indexOf(event.key)
      if (index >= 0) {
        const offset = selected.sampleOffsetsMs[index]
        if (offset === undefined) return
        event.preventDefault()
        playClip(selected.speakerLabel, index, offset)
      }
    },
    [playClip, save, selected],
  )

  /** The speakers rail is a roving group: `↑` `↓` walk the tags. */
  const onRowKeyDown = useCallback(
    (event: KeyboardEvent<HTMLButtonElement>, position: number) => {
      const step = event.key === 'ArrowDown' ? 1 : event.key === 'ArrowUp' ? -1 : 0
      if (step === 0) return
      event.preventDefault()
      const next = rows[(position + step + rows.length) % rows.length]
      if (next === undefined) return
      selectTag(next.speakerLabel)
      rowRefs.current.get(next.speakerLabel)?.focus()
    },
    [rows, selectTag],
  )

  const onFieldKeyDown = useCallback(
    (event: KeyboardEvent<HTMLInputElement>) => {
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        if (suggestions.length === 0) return
        event.preventDefault()
        setListOpen(true)
        setHighlighted((current) => {
          const step = event.key === 'ArrowDown' ? 1 : -1
          const next = current + step
          if (next < 0) return suggestions.length - 1
          if (next >= suggestions.length) return 0
          return next
        })
        return
      }
      if (event.key === 'Escape') {
        setListOpen(false)
        setHighlighted(-1)
        return
      }
      if (event.key !== 'Enter') return
      event.preventDefault()
      // Enter on a highlighted suggestion fills the field and closes the list;
      // Enter with the list closed does what Save does. Never both at once —
      // a single keystroke must not both choose a person and commit them.
      if (listOpen && highlighted >= 0 && suggestions[highlighted] !== undefined) {
        const row = suggestions[highlighted]
        setDraft(row.displayName)
        setPicked(row)
        setListOpen(false)
        setHighlighted(-1)
        return
      }
      void save('choice')
    },
    [highlighted, listOpen, save, suggestions],
  )

  const speechTotal = durationLabel(totalMs)
  const reprocessing = isReprocessing(rerun)
  const failed = rerun === null ? null : failedStage(rerun)

  return (
    <section className="mx-auto flex w-full max-w-5xl flex-col gap-6 p-6">
      <header className="flex flex-col gap-1">
        {onBack !== undefined && (
          <Button
            variant="ghost"
            size="sm"
            className="self-start px-0 text-muted-foreground"
            onClick={onBack}
          >
            ← Back
          </Button>
        )}
        <h2 className="text-lg font-semibold tracking-tight">
          Speakers <span className="font-mono tabular-nums">{rows.length}</span>
          <span className="ml-2 text-sm font-normal text-muted-foreground">
            · <span className="font-mono tabular-nums">{speechTotal}</span> of speech
          </span>
        </h2>
        <p className="text-xs text-muted-foreground">
          {meetingTitle ?? meetingId}
          {startedAt !== null && (
            <>
              {' — '}
              <span className="font-mono tabular-nums">{startedAt.slice(0, 10)}</span>
            </>
          )}
        </p>
      </header>

      {rerun !== null && (
        <div
          data-testid="rerun-strip"
          role="group"
          aria-label={`Rerun progress for ${rerun.speakerLabel}`}
          className="flex flex-col gap-2 rounded-md border border-border bg-card p-3"
        >
          <ol className="flex flex-wrap items-center gap-x-6 gap-y-2">
            {rerun.stages.map((stage) => {
              const status = asStageStatus(stage.status)
              return (
                <li
                  key={stage.name}
                  data-testid={`rerun-stage-${stage.name}`}
                  data-status={status}
                  className="flex items-center gap-2"
                >
                  <span className="min-w-14 font-mono text-[11px] text-muted-foreground">
                    {stage.name}
                  </span>
                  <span
                    role="img"
                    aria-label={`${stage.name} ${status}`}
                    className={cn('h-1.5 w-14 rounded-sm', BAR_CLASS[status])}
                  />
                  <span className={cn('font-mono text-[11px]', LABEL_CLASS[status])}>
                    {status}
                  </span>
                </li>
              )
            })}
          </ol>
          {reprocessing && (
            <p data-testid="reprocessing-note" className="text-sm">
              {reprocessingSentence(rerun)}
            </p>
          )}
          {reprocessing && jobConnection.kind === 'lost' && (
            <p role="status" className="text-xs text-muted-foreground">
              Live rerun progress is unavailable — {jobConnection.message}. Reconnecting;
              the last confirmed stage state remains on screen.
            </p>
          )}
          {rerun.acceptedWhileUnviewable && failed === null && (
            <p className="text-xs text-muted-foreground">
              This meeting&apos;s evidence was already unsettled — the assignment was
              accepted anyway so a failed rerun can be corrected.
            </p>
          )}
          {failed !== null && (
            <p data-testid="rerun-failed" role="alert" className="text-sm">
              {failedSentence(failed)}
            </p>
          )}
          {rerun.landedAt !== null && failed === null && (
            <p data-testid="rerun-landed" className="text-sm">
              {landedSentence(rerun)}
            </p>
          )}
        </div>
      )}

      <div className="grid gap-5 lg:grid-cols-[280px_1fr_280px]">
        {/* Speakers rail */}
        <section aria-label="Speakers, sorted by talk share" className="flex flex-col gap-2">
          <h3 className="text-sm font-medium text-muted-foreground">Speakers</h3>
          {speakers === null && speakersFailure === null && (
            <p className="text-sm text-muted-foreground">Loading speakers…</p>
          )}
          {rows.length === 0 && speakers !== null && (
            <p data-testid="no-speaker-tags" className="text-sm text-muted-foreground">
              {NO_SPEAKER_TAGS}
            </p>
          )}
          {speakersFailure !== null && (
            <p
              data-testid="speakers-failure"
              className={cn(
                'rounded-md border border-border p-3 text-sm',
                speakers === null ? 'text-foreground' : 'text-muted-foreground',
              )}
            >
              {speakers === null
                ? speakersFailure.kind === 'transport'
                  ? `Cannot reach the api at ${API_BASE}: ${speakersFailure.message}.`
                  : speakersFailure.message
                : `The rows below are the pre-rerun reading — ${speakersFailure.message}.`}{' '}
              <Button variant="outline" size="xs" onClick={() => void load()}>
                Retry
              </Button>
            </p>
          )}
          <div className="flex flex-col gap-1">
            {rows.map((row, position) => {
              const percent = talkSharePercent(row, totalMs)
              const resolved = resolvedName(row)
              const pending = pendingAssignments[row.speakerLabel]
              const name = pending?.displayName ?? resolved
              const isSelected = row.speakerLabel === selectedTag
              const accessibleLabel =
                pending === undefined
                  ? speakerRowLabel(row, percent, isSelected)
                  : `${speakerRowLabel(row, percent, isSelected)}, ${
                      pending.displayName === null
                        ? 'unresolved choice saved'
                        : `${pending.displayName} assignment saved`
                    }, rerun queued`
              return (
                <div
                  key={row.speakerLabel}
                  data-testid={`speaker-row-${row.speakerLabel}`}
                  className={cn(
                    'rounded-md border p-2.5',
                    isSelected ? 'border-border bg-card' : 'border-transparent',
                  )}
                >
                  <button
                    type="button"
                    ref={(element) => {
                      if (element === null) rowRefs.current.delete(row.speakerLabel)
                      else rowRefs.current.set(row.speakerLabel, element)
                    }}
                    aria-pressed={isSelected}
                    aria-label={accessibleLabel}
                    className="w-full cursor-pointer text-left"
                    onClick={() => selectTag(row.speakerLabel)}
                    onKeyDown={(event) => onRowKeyDown(event, position)}
                  >
                    <span className="flex flex-wrap items-baseline justify-between gap-2">
                      <span className="font-mono text-xs">{row.speakerLabel}</span>
                      {name !== null && <span className="text-xs">{name}</span>}
                    </span>
                    {/* The share bar is a graphic: the row's accessible name
                        already carries the percent, so it is hidden here
                        rather than announced twice. */}
                    <span
                      aria-hidden="true"
                      className="my-2 block h-1.5 w-full overflow-hidden rounded-sm bg-muted"
                    >
                      <span
                        data-testid={`share-bar-${row.speakerLabel}`}
                        className="block h-full bg-primary/70"
                        style={{ width: `${percent}%` }}
                      />
                    </span>
                    <span className="flex items-baseline justify-between gap-2">
                      <span className="font-mono text-sm tabular-nums">{percent}%</span>
                      <span className="font-mono text-[11px] text-muted-foreground">
                        {speakerMetaLabel(row)}
                      </span>
                    </span>
                  </button>
                  {(name !== null || pending !== undefined) && (
                    <div className="mt-1.5 flex items-center justify-between gap-2">
                      {/* The api's own resolution word, not a provenance
                          claim: the wire carries no field saying whether the
                          source or a curator resolved this row (B-42). */}
                      <span className="font-mono text-[11px] text-muted-foreground">
                        {pending === undefined ? row.speakerResolution : 'rerun · queued'}
                      </span>
                      {name !== null && (
                        <Button
                          variant="outline"
                          size="xs"
                          onClick={() => selectTag(row.speakerLabel, true)}
                        >
                          Correct
                        </Button>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </section>

        {/* Clips and naming */}
        <div
          className="flex flex-col gap-4"
          onKeyDown={onPanelKeyDown}
          data-testid="naming-panel"
        >
          {selected === null ? (
            <p className="text-sm text-muted-foreground">
              Select a speaker to hear a clip and name the voice.
            </p>
          ) : (
            <section aria-label={`Name ${selected.speakerLabel}`} className="flex flex-col gap-4">
              <h3 className="text-sm font-medium text-muted-foreground">
                <span className="font-mono">{selected.speakerLabel}</span> —{' '}
                {speakerMetaLabel(selected)}
              </h3>

              {hasRecording && selected.sampleOffsetsMs.length > 0 ? (
                <div className="flex flex-wrap gap-2">
                  {selected.sampleOffsetsMs.map((offset, index) => (
                    <Button
                      key={offset}
                      variant="outline"
                      size="sm"
                      className={cn(
                        'font-mono',
                        clip?.tag === selected.speakerLabel &&
                          clip.index === index &&
                          'border-ring',
                      )}
                      aria-label={`Play clip ${index + 1} of ${selected.speakerLabel} at ${offsetLabel(offset)}`}
                      onClick={() => playClip(selected.speakerLabel, index, offset)}
                    >
                      ▶ {offsetLabel(offset)}
                    </Button>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">
                  {hasRecording
                    ? 'No sample offsets for this tag — name it from the transcript beside it.'
                    : 'Transcript only — no recording, so there is no clip to play. Name the voice from the transcript beside it.'}
                </p>
              )}

              {clip !== null && clip.tag === selected.speakerLabel && (
                <ReplayPlayer
                  key={clip.playId}
                  meetingId={meetingId}
                  startMs={clip.startMs}
                  endMs={clip.startMs + CLIP_LENGTH_MS}
                  autoPlay
                  label={`Clip ${clip.index + 1} of ${selected.speakerLabel} at ${offsetLabel(clip.startMs)}`}
                  className="w-full rounded-md border border-border"
                />
              )}

              <div className="flex flex-col gap-1.5">
                <label
                  htmlFor="speaker-name"
                  className="text-xs text-muted-foreground"
                >
                  {resolvedName(selected) === null ? 'Name' : 'Correct'}{' '}
                  {selected.speakerLabel}
                </label>
                <input
                  id="speaker-name"
                  ref={nameInputRef}
                  type="text"
                  role="combobox"
                  autoComplete="off"
                  aria-autocomplete="list"
                  aria-expanded={listOpen && suggestions.length > 0}
                  aria-controls="speaker-name-suggestions"
                  aria-activedescendant={
                    listOpen && highlighted >= 0 && suggestions[highlighted] !== undefined
                      ? `speaker-suggestion-${suggestions[highlighted].id}`
                      : undefined
                  }
                  value={draft}
                  className="w-full rounded-md border border-input bg-card px-2.5 py-2 text-sm"
                  onChange={(event) => {
                    setDraft(event.target.value)
                    // Keep the pick as provenance while the field changes.
                    // `choiceOf` applies its id only while trimmed text still
                    // equals that row's name, so typing another name is safe,
                    // while harmless whitespace or restoring the exact name
                    // does not lose an identity the curator explicitly chose.
                    setHighlighted(-1)
                    setListOpen(true)
                    setSaveError(null)
                  }}
                  onKeyDown={onFieldKeyDown}
                />
                {listOpen && suggestions.length > 0 && (
                  <ul
                    id="speaker-name-suggestions"
                    role="listbox"
                    aria-label="Existing participants"
                    className="rounded-md border border-border bg-popover p-1"
                  >
                    {suggestions.map((row, index) => (
                      <li
                        key={row.id}
                        id={`speaker-suggestion-${row.id}`}
                        role="option"
                        aria-selected={index === highlighted}
                        className={cn(
                          'cursor-pointer rounded-sm px-2 py-1.5 text-xs',
                          index === highlighted
                            ? 'bg-muted text-foreground'
                            : 'text-muted-foreground',
                        )}
                        onMouseDown={(event) => {
                          // `mousedown`, not `click`: the field must not lose
                          // focus and close the list before the pick lands.
                          event.preventDefault()
                          setDraft(row.displayName)
                          setPicked(row)
                          setListOpen(false)
                          setHighlighted(-1)
                        }}
                      >
                        {row.displayName}
                      </li>
                    ))}
                  </ul>
                )}
                <p className="text-xs text-muted-foreground">{SUGGESTION_NOTE}</p>
              </div>

              <div className="flex flex-wrap items-center gap-2.5">
                <Button
                  disabled={choice === null || saving}
                  onClick={() => void save('choice')}
                >
                  {saving ? 'Saving…' : 'Save'}
                </Button>
                <Button variant="outline" disabled={saving} onClick={() => void save('unresolved')}>
                  Unresolved — keep the tag
                </Button>
                <p className="w-full text-[11px] text-muted-foreground">
                  {choice === null
                    ? 'Save is disabled until a name is typed or chosen; Unresolved is always available.'
                    : choice.kind === 'participant'
                      ? `Save assigns the existing participant ${choice.displayName}.`
                      : `Save creates a new participant named ${choice.displayName}.`}
                </p>
                {resolvedName(selected) !== null && (
                  <p className="w-full text-[11px] text-muted-foreground">
                    {UNRESOLVED_ON_RESOLVED_NOTE}
                  </p>
                )}
              </div>

              {saveError !== null && (
                <p
                  data-testid="assignment-refusal"
                  role="alert"
                  className="rounded-md border border-destructive/60 bg-destructive/10 p-3 text-sm"
                >
                  {saveError}
                </p>
              )}
            </section>
          )}
        </div>

        {/* Tag-filtered transcript */}
        <section
          aria-label={
            selected === null
              ? 'Transcript'
              : `Transcript filtered to ${selected.speakerLabel}`
          }
          className="flex flex-col gap-2"
        >
          <h3 className="text-sm font-medium text-muted-foreground">
            Transcript
            {selected !== null && (
              <>
                {' · '}
                <span className="font-mono">{selected.speakerLabel}</span>
                {resolvedName(selected) !== null && (
                  <>
                    {' · '}
                    {resolvedName(selected)}
                  </>
                )}
              </>
            )}
          </h3>
          {segments === null && transcriptFailure === null && (
            <p className="text-sm text-muted-foreground">Loading transcript…</p>
          )}
          {transcriptFailure !== null && (
            <p data-testid="transcript-failure" className="text-sm text-muted-foreground">
              {segments === null
                ? transcriptFailure.kind === 'transport'
                  ? `Cannot reach the api at ${API_BASE}: ${transcriptFailure.message}.`
                  : transcriptFailure.message
                : `The lines below are the pre-rerun reading — ${transcriptFailure.message}.`}
            </p>
          )}
          {segments !== null && selected !== null && (
            <ol className="flex flex-col gap-2.5">
              {segmentsOfTag(segments, selected.speakerLabel).map((segment) => (
                <li key={segment.segmentId} className="flex gap-2">
                  <span className="min-w-11 font-mono text-[11px] tabular-nums text-muted-foreground">
                    {offsetLabel(segment.startMs)}
                  </span>
                  <span className="text-xs">{segment.text}</span>
                </li>
              ))}
            </ol>
          )}
          {segments !== null &&
            selected !== null &&
            segmentsOfTag(segments, selected.speakerLabel).length === 0 && (
              <p className="text-sm text-muted-foreground">
                No transcript line carries {selected.speakerLabel}.
              </p>
            )}
        </section>
      </div>
    </section>
  )
}
