import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { getMeetingDrilldown, getMoment, listMeetingMoments } from '@/client/sdk.gen'
import type {
  DrilldownScreenshot,
  MeetingDrilldownResponse,
  MomentDetail,
  SnippetRunModel,
} from '@/client/types.gen'
import { SourceLinkAnchor } from '@/components/SourceLinkAnchor'
import { Button } from '@/components/ui/button'
import { ReplayPlayer } from '@/features/replay/ReplayPlayer'
import { affordanceOf, offsetLabel } from '@/lib/affordance'
import { API_BASE } from '@/lib/api'
import { mediaUrl } from '@/lib/media'
import {
  alignedSegmentId,
  durationStatLabel,
  evidenceDurationMs,
  highlightRuns,
  lineageLabel,
  loadFailureOf,
  MOMENT_TIMEOUT_MS,
  type MeetingArtifactEntry,
  type MomentLoadFailure,
  meetingArtifactGroups,
  meetingLabelOf,
  NO_PARTICIPANT_GRAPH,
  notViewableMessage,
  participantsOf,
  publishedEntries,
  speakerName,
  transportFailureOf,
  wordCountOf,
} from './moments'

export interface MeetingMomentsProps {
  /** The meeting whose evidence is drilled into. */
  meetingId: string
  /** Opening one moment is the shell's navigation to make (story 2.2). */
  onOpenMoment?: (momentId: string) => void
}

/**
 * How a drill-down read failed — the shared classification plus the raw
 * problem body, kept because the 409's `augmenting`/`jobStatus` extensions
 * decide which empty-state sentence to show (story 2.3, AD-14).
 */
interface DrilldownFailure {
  failure: MomentLoadFailure
  problem?: unknown
}

/**
 * The right rail's own read (story ui-3): the moments list plus the artifact
 * fan-out. Separate from the drill-down's failure state on purpose — the
 * transcript and screens must render even when the rail cannot, so a rail
 * failure is a sentence in the rail, never a page error.
 */
type RailState =
  | { kind: 'loading' }
  | { kind: 'unavailable'; message: string }
  | {
      kind: 'ready'
      /** How many live moments the meeting has — the header's passages stat. */
      passages: number
      entries: Array<MeetingArtifactEntry>
      /** True when some moment reads failed: the list may be incomplete. */
      partial: boolean
    }

/** One segment's precomputed runs, rendered with the `<mark>` idiom the
 * search snippets use — structured runs, never markup (`CorpusSearch.tsx`). */
function SegmentText({ runs }: { runs: Array<SnippetRunModel> }) {
  return (
    <span>
      {runs.map((run, index) =>
        run.highlighted ? (
          // eslint-disable-next-line react/no-array-index-key -- runs have no id; their order is their identity
          <mark key={index} className="bg-yellow-200 dark:bg-yellow-900">
            {run.text}
          </mark>
        ) : (
          // eslint-disable-next-line react/no-array-index-key -- same
          <span key={index}>{run.text}</span>
        ),
      )}
    </span>
  )
}

/**
 * One meeting's evidence, whole, in the reference's three-column anatomy
 * (story ui-3, CAP-2): a header stat line (date · duration · turns · words ·
 * passages · lineage), the screens film-strip left, the full speaker
 * transcript center, and a right rail of extracted artifacts grouped by kind
 * with moment anchors and publish state, participants (with the explicit
 * absence note), and published documents.
 *
 * Every live moment stays reachable: a covered segment, a moment-bearing
 * screenshot, and every rail entry open their moment view, so 2.2's "open a
 * moment from the meeting" behavior survives inside the denser surface. A
 * capture no moment names jumps to its aligned transcript passage instead.
 *
 * A locally-typed highlight term marks its mentions across the transcript —
 * client-side over served text, because the search index is moment-grained
 * (AD-4) and the server sends no markup (AD-15). One inline `ReplayPlayer`
 * at a time: `openReplay` names the open region (screenshot or segment) and
 * clicking another region moves the single player rather than adding one.
 *
 * Degraded shape (`hasRecording: false`): no film strip, no replay
 * affordances, and the meeting-level source deep link stands where the strip
 * would be, through the same `affordanceOf` decision the moment view uses
 * (UX-DR11).
 *
 * The rail's data is its own read: `listMeetingMoments` for the passages
 * count, then one `getMoment` per moment for the artifacts — the catalogued
 * never-called surface, no new endpoints. Its failure degrades the rail
 * alone.
 */
export function MeetingMoments({ meetingId, onOpenMoment }: MeetingMomentsProps) {
  // `null` is "never answered"; an answered meeting always has a header, and
  // an answered-empty one carries empty arrays.
  const [data, setData] = useState<MeetingDrilldownResponse | null>(null)
  const [refusal, setRefusal] = useState<DrilldownFailure | null>(null)
  const [rail, setRail] = useState<RailState>({ kind: 'loading' })
  // Which region's inline replay is open — `shot:<id>` or `seg:<id>`; one key,
  // one mounted player (the `CorpusSearch` single-`openReplay` pattern).
  const [openReplay, setOpenReplay] = useState<string | null>(null)
  // The term the transcript highlights. Drill-down-local input state, not
  // view state: the shell's view union never learns it.
  const [term, setTerm] = useState('')
  // The transcript passage a film-strip or participant jump last targeted —
  // it gets a visible ring so the scroll's destination is unmistakable.
  const [jumpTarget, setJumpTarget] = useState<string | null>(null)
  // Held across renders so a meeting change or unmount aborts the in-flight
  // read — an older response must never overwrite a newer result (story
  // 1.10, finding 22).
  const controllerRef = useRef<AbortController | null>(null)

  const load = useCallback(async () => {
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller
    // A new read means the old answer no longer describes this view. Clear
    // states up front so the loading state is honest when the meeting prop
    // changes, a failure can never sit above another meeting's evidence, no
    // player outlives the meeting it was opened for, and the previous
    // meeting's highlight term never silently applies to a new transcript.
    setData(null)
    setRefusal(null)
    setOpenReplay(null)
    setTerm('')
    setJumpTarget(null)
    // An explicit timer rather than `AbortSignal.timeout`: that signal cannot
    // be cancelled, so a superseded read would leave a live timer behind, and
    // a real `setTimeout` is something a test can drive.
    const expiry = new AbortController()
    const timer = setTimeout(() => expiry.abort(), MOMENT_TIMEOUT_MS)
    try {
      const signal = AbortSignal.any([controller.signal, expiry.signal])
      const { data: body, error } = await getMeetingDrilldown({
        path: { meeting_id: meetingId },
        signal,
      })
      if (controller.signal.aborted) return
      if (expiry.signal.aborted) {
        setRefusal({
          failure: { kind: 'transport', message: `timed out after ${MOMENT_TIMEOUT_MS}ms` },
        })
        return
      }
      if (error !== undefined) {
        setRefusal({ failure: loadFailureOf(error), problem: error })
        return
      }
      if (body === undefined) throw new Error('the api answered with no body')
      setData(body)
      setRefusal(null)
    } catch (err) {
      if (controller.signal.aborted) return
      setRefusal({
        failure: expiry.signal.aborted
          ? { kind: 'transport', message: `timed out after ${MOMENT_TIMEOUT_MS}ms` }
          : transportFailureOf(err),
      })
    } finally {
      clearTimeout(timer)
    }
  }, [meetingId])

  useEffect(() => {
    void load()
    return () => controllerRef.current?.abort()
  }, [load])

  // The rail's read runs beside the drill-down's, on its own controller and
  // deadline: the moments list, then the artifact fan-out. Any failure —
  // refusal, transport, timeout, or an sdk that answered with no body —
  // degrades to the rail's "unavailable" sentence and never touches the
  // transcript's state.
  useEffect(() => {
    const controller = new AbortController()
    const expiry = new AbortController()
    const timer = setTimeout(() => expiry.abort(), MOMENT_TIMEOUT_MS)
    setRail({ kind: 'loading' })
    void (async () => {
      try {
        const signal = AbortSignal.any([controller.signal, expiry.signal])
        const listed = await listMeetingMoments({
          path: { meeting_id: meetingId },
          signal,
        })
        if (controller.signal.aborted) return
        if (expiry.signal.aborted) {
          setRail({
            kind: 'unavailable',
            message: `timed out after ${MOMENT_TIMEOUT_MS}ms`,
          })
          return
        }
        if (listed?.error !== undefined || listed?.data === undefined) {
          setRail({
            kind: 'unavailable',
            message: loadFailureOf(listed?.error).message,
          })
          return
        }
        const moments = listed.data.moments
        // One read per moment, tolerant per read: a failed moment drops out
        // of the artifact list and flips `partial` rather than sinking the
        // rail — the honest note beats an all-or-nothing failure.
        const details = await Promise.all(
          moments.map(async (moment): Promise<MomentDetail | null> => {
            try {
              const read = await getMoment({
                path: { moment_id: moment.momentId },
                signal,
              })
              if (read?.error !== undefined || read?.data === undefined) return null
              return read.data
            } catch {
              return null
            }
          }),
        )
        if (controller.signal.aborted) return
        const entries: Array<MeetingArtifactEntry> = []
        let partial = false
        for (const detail of details) {
          if (detail === null) {
            partial = true
            continue
          }
          for (const artifact of detail.artifacts) {
            entries.push({
              artifact,
              momentId: detail.momentId,
              startMs: detail.startMs,
              endMs: detail.endMs,
            })
          }
        }
        setRail({ kind: 'ready', passages: moments.length, entries, partial })
      } catch (err) {
        if (controller.signal.aborted) return
        setRail({
          kind: 'unavailable',
          message: expiry.signal.aborted
            ? `timed out after ${MOMENT_TIMEOUT_MS}ms`
            : transportFailureOf(err).message,
        })
      } finally {
        clearTimeout(timer)
      }
    })()
    return () => {
      controller.abort()
      clearTimeout(timer)
    }
  }, [meetingId])

  const loading = data === null && refusal === null
  const failure = refusal?.failure ?? null
  const hasRecording = data?.hasRecording === true
  // Runs for the whole transcript, recomputed only when the term or the
  // transcript changes — a keystroke over a hundreds-of-segments meeting
  // must not re-split every segment on every unrelated render.
  const highlightedSegments = useMemo(
    () =>
      (data?.segments ?? []).map((segment) => ({
        segment,
        runs: highlightRuns(segment.text, term),
      })),
    [data, term],
  )
  const participants = useMemo(
    () => participantsOf(data?.segments ?? []),
    [data],
  )
  const artifactGroups = useMemo(
    () => (rail.kind === 'ready' ? meetingArtifactGroups(rail.entries) : []),
    [rail],
  )
  const published = useMemo(
    () => (rail.kind === 'ready' ? publishedEntries(rail.entries) : []),
    [rail],
  )
  // The meeting-level affordance only stands in when there is no series
  // (UX-DR11 at meeting scope); with a recording the replays are the strip's.
  const headerAffordance = data === null ? null : affordanceOf(data)
  const canOpenMoment = typeof onOpenMoment === 'function'

  const toggleReplay = (key: string) =>
    setOpenReplay((current) => (current === key ? null : key))

  // The film-strip and participant jump: scroll the aligned passage into
  // view and ring it. `scrollIntoView` is optional-called because jsdom (and
  // an unmounted target) has none — the ring alone still marks the passage.
  const jumpToSegment = (segmentId: string) => {
    setJumpTarget(segmentId)
    document
      .getElementById(`transcript-seg-${segmentId}`)
      ?.scrollIntoView?.({ behavior: 'smooth', block: 'center' })
  }

  const replayControls = (key: string, where: string) => {
    if (!hasRecording || data === null) return null
    const isOpen = openReplay === key
    return (
      <Button
        size="sm"
        variant={isOpen ? 'outline' : 'default'}
        aria-expanded={isOpen}
        // The visible text is a prefix of the accessible name (WCAG 2.5.3
        // label-in-name): "Hide replay" / "Replay" must open the label.
        aria-label={`${isOpen ? 'Hide replay' : 'Replay'} recording at ${where}`}
        onClick={() => toggleReplay(key)}
      >
        {isOpen ? 'Hide replay' : 'Replay'}
      </Button>
    )
  }

  // UX-DR12: beside each row's Replay, the meeting's YouTube link timed at
  // that row's own offset — the same `affordanceOf` decision the header
  // makes, given the offset. Nothing for another host (replay wins), and
  // nothing without a recording: the degraded header carries the meeting-
  // scoped link then.
  const sourceControls = (key: string, startMs: number) => {
    if (data === null) return null
    const rowAffordance = affordanceOf(data, startMs)
    if (rowAffordance.kind !== 'replay') return null
    if (rowAffordance.source !== null) {
      return (
        <SourceLinkAnchor link={rowAffordance.source} testId={`drilldown-youtube-link-${key}`} />
      )
    }
    return rowAffordance.inertSource === null ? null : (
      <span
        data-testid={`drilldown-unsafe-link-${key}`}
        className="break-all text-xs text-muted-foreground"
      >
        Source link not opened — unsupported address: {rowAffordance.inertSource}
      </span>
    )
  }

  const inlinePlayer = (key: string, startMs: number, where: string) => {
    if (!hasRecording || data === null || openReplay !== key) return null
    return (
      // Rendered with the region's offset rather than remounted per seek:
      // ReplayPlayer re-seeks on a `startMs` change (`CorpusSearch.tsx`).
      <ReplayPlayer
        meetingId={data.meetingId}
        startMs={startMs}
        label={`${meetingLabelOf(data.title, data.meetingId)} at ${where}`}
        className="w-full rounded-md"
      />
    )
  }

  // The header stat line (reference anatomy): date · duration · turns ·
  // words · passages. Every number is counted over served data; the passages
  // stat appears once the rail's moments list answers.
  const statLine =
    data === null
      ? null
      : [
          data.startedAtPrecision === 'day'
            ? new Date(data.startedAt).toLocaleDateString()
            : new Date(data.startedAt).toLocaleString(),
          durationStatLabel(evidenceDurationMs(data)),
          `${data.segments.length} turns`,
          `${wordCountOf(data.segments).toLocaleString()} words`,
          rail.kind === 'ready' ? `${rail.passages} passages` : null,
        ]
          .filter((part): part is string => part !== null)
          .join(' · ')

  const filmStrip = (shot: DrilldownScreenshot) => {
    const where = offsetLabel(shot.startOffsetMs)
    const key = `shot:${shot.screenshotId}`
    const momentId = shot.momentId
    const screenLabel = shot.screenLabel?.trim() || null
    const alignedId =
      data === null ? null : alignedSegmentId(data.segments, shot.startOffsetMs)
    const image = (
      <img
        src={mediaUrl(shot.path)}
        // The human label names the screen better than a classification
        // does, when curation set one.
        alt={screenLabel ?? `${shot.viewType} at ${where}`}
        // First many-image consumer: a real series is a hundred-plus
        // captures, so off-screen ones must not all fetch on open.
        loading="lazy"
        className="w-full rounded-md border"
      />
    )
    return (
      <li
        key={shot.screenshotId}
        data-testid={`drilldown-screenshot-${shot.screenshotId}`}
        className="flex flex-col gap-1.5 rounded-lg border p-2"
      >
        {/* The thumbnail is the affordance: a moment-bearing capture opens
            its moment, an unaligned one jumps to the aligned transcript
            passage — every element clicks through (CAP-2). */}
        {momentId != null && canOpenMoment ? (
          <button
            type="button"
            aria-label={`Open moment at ${where}`}
            onClick={() => onOpenMoment(momentId)}
            className="w-full cursor-pointer border-0 bg-transparent p-0 text-left"
          >
            {image}
          </button>
        ) : alignedId !== null ? (
          <button
            type="button"
            aria-label={`Show transcript at ${where}`}
            onClick={() => jumpToSegment(alignedId)}
            className="w-full cursor-pointer border-0 bg-transparent p-0 text-left"
          >
            {image}
          </button>
        ) : (
          image
        )}
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
          <span className="font-mono">{where}</span>
          <span data-testid={`screenshot-view-type-${shot.screenshotId}`}>
            {shot.viewType}
          </span>
          {screenLabel !== null && (
            <span
              data-testid={`screenshot-label-${shot.screenshotId}`}
              className="font-medium text-foreground"
            >
              {screenLabel}
            </span>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {replayControls(key, where)}
          {sourceControls(key, shot.startOffsetMs)}
        </div>
        {inlinePlayer(key, shot.startOffsetMs, where)}
      </li>
    )
  }

  const artifactAnchor = (entry: MeetingArtifactEntry) => (
    <span className="font-mono text-xs text-muted-foreground">
      {offsetLabel(entry.startMs)}–{offsetLabel(entry.endMs)}
    </span>
  )

  return (
    <section className="flex w-full flex-col gap-4">
      <header className="flex flex-col gap-1">
        <h2 className="text-lg font-semibold tracking-tight">
          {data === null ? 'Meeting' : meetingLabelOf(data.title, data.meetingId)}
        </h2>
        {data !== null && (
          <>
            <span
              data-testid="meeting-stat-line"
              className="font-mono text-xs text-muted-foreground"
            >
              {statLine}
            </span>
            <span
              data-testid="meeting-lineage"
              className="text-xs text-muted-foreground"
            >
              {lineageLabel(data.hasRecording, data.segments)} · {data.corpus}
            </span>
          </>
        )}
      </header>

      {failure !== null &&
        (failure.kind === 'transport' ? (
          <p role="alert" className="rounded-md border border-destructive/40 p-3 text-sm text-destructive">
            Cannot reach the api at {API_BASE}: {failure.message}.
          </p>
        ) : (
          <p
            role="alert"
            data-testid={`moments-${failure.kind}`}
            className="rounded-md border p-3 text-sm text-muted-foreground"
          >
            {failure.kind === 'notViewable'
              ? // The 409's `augmenting`/`jobStatus` extensions pick the
                // sentence: augmentation, failed ingest, or first ingest.
                notViewableMessage(refusal?.problem)
              : failure.kind === 'notFound'
                ? 'No meeting has this id. It may never have been ingested.'
                : `The api could not answer: ${failure.message}.`}
          </p>
        ))}

      <div aria-live="polite" aria-busy={loading} className="flex flex-col gap-6">
        {loading ? (
          <p className="text-sm text-muted-foreground">Loading meeting evidence…</p>
        ) : data === null ? null : (
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-[200px_minmax(0,1fr)_280px] lg:items-start">
            {/* Extracted evidence: ADRs, action items, participants, published
                documents. Placed FIRST in document order — not just visually —
                so it is what a keyboard/screen-reader user (and, on a stacked
                narrow-viewport layout, a sighted user) reaches immediately,
                rather than only after the film-strip and the full transcript,
                either of which can run to thousands of pixels for a
                long/heavily-screenshotted meeting. `lg:order-3` restores this
                to the right rail once the 3-column layout applies; the
                film-strip and transcript below carry the matching
                `lg:order-1`/`lg:order-2` to land back in their original
                left/center columns. */}
            <aside
              data-testid="meeting-rail"
              aria-label="Extracted evidence"
              className="flex flex-col gap-5 lg:order-3 lg:max-h-[75vh] lg:overflow-y-auto lg:pr-1"
            >
              <section data-testid="meeting-artifacts" className="flex flex-col gap-2">
                <h3 className="text-sm font-medium text-muted-foreground">
                  Extracted{rail.kind === 'ready' ? ` ${rail.entries.length}` : ''}
                </h3>
                {rail.kind === 'loading' && (
                  <p className="text-xs text-muted-foreground">
                    Loading extracted artifacts…
                  </p>
                )}
                {rail.kind === 'unavailable' && (
                  <p
                    data-testid="meeting-artifacts-unavailable"
                    className="text-xs text-muted-foreground"
                  >
                    Extracted artifacts unavailable — {rail.message}.
                  </p>
                )}
                {rail.kind === 'ready' && rail.partial && (
                  <p
                    data-testid="meeting-artifacts-partial"
                    className="text-xs text-muted-foreground"
                  >
                    Some moments could not be read — this list may be incomplete.
                  </p>
                )}
                {rail.kind === 'ready' && rail.entries.length === 0 && (
                  <p
                    data-testid="meeting-artifacts-empty"
                    className="rounded-lg border border-dashed p-3 text-xs text-muted-foreground"
                  >
                    Nothing extracted from this meeting yet — artifacts appear
                    here once extraction runs.
                  </p>
                )}
                {artifactGroups.map((group) => (
                  <section
                    key={group.kind}
                    data-testid={`meeting-artifact-group-${group.kind}`}
                    className="flex flex-col gap-1.5"
                  >
                    <h4 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      {group.label} {group.entries.length}
                    </h4>
                    <ul className="flex flex-col gap-1.5">
                      {group.entries.map((entry) => (
                        <li
                          key={entry.artifact.id}
                          data-testid={`meeting-artifact-${entry.artifact.id}`}
                          className="flex flex-col gap-0.5 rounded-md border p-2 text-sm"
                        >
                          {canOpenMoment ? (
                            <button
                              type="button"
                              aria-label={`Open moment at ${offsetLabel(entry.startMs)}: ${entry.artifact.title}`}
                              onClick={() => onOpenMoment(entry.momentId)}
                              className="flex cursor-pointer flex-col items-start gap-0.5 border-0 bg-transparent p-0 text-left"
                            >
                              {artifactAnchor(entry)}
                              <span className="font-medium">{entry.artifact.title}</span>
                            </button>
                          ) : (
                            <>
                              {artifactAnchor(entry)}
                              <span className="font-medium">{entry.artifact.title}</span>
                            </>
                          )}
                          <span className="text-xs text-muted-foreground">
                            {entry.artifact.state}
                            {entry.artifact.state === 'published' &&
                              entry.artifact.publishRelativePath != null && (
                                <>
                                  {' · '}
                                  {entry.artifact.publishRelativePath}
                                  {entry.artifact.publishCommitSha != null &&
                                    ` @ ${entry.artifact.publishCommitSha.slice(0, 12)}`}
                                </>
                              )}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </section>
                ))}
              </section>

              <section data-testid="meeting-participants" className="flex flex-col gap-2">
                <h3 className="text-sm font-medium text-muted-foreground">
                  Participants {participants.length}
                </h3>
                {participants.length === 0 ? (
                  <p
                    data-testid="participants-absence"
                    className="rounded-lg border border-dashed p-3 text-xs text-muted-foreground"
                  >
                    {NO_PARTICIPANT_GRAPH}
                  </p>
                ) : (
                  <ul className="flex flex-col gap-1">
                    {participants.map((participant) => (
                      <li key={participant.participantId} className="text-sm">
                        <button
                          type="button"
                          aria-label={`Show ${participant.name} in transcript`}
                          onClick={() => jumpToSegment(participant.firstSegmentId)}
                          className="cursor-pointer border-0 bg-transparent p-0 text-left"
                        >
                          <span className="font-medium">{participant.name}</span>{' '}
                          <span className="text-xs text-muted-foreground">
                            {participant.turns} turns
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              {published.length > 0 && (
                <section
                  data-testid="meeting-published-docs"
                  className="flex flex-col gap-2"
                >
                  <h3 className="text-sm font-medium text-muted-foreground">
                    Published documents {published.length}
                  </h3>
                  <ul className="flex flex-col gap-1.5">
                    {published.map((entry) => (
                      <li
                        key={entry.artifact.id}
                        data-testid={`meeting-published-${entry.artifact.id}`}
                        className="flex flex-col gap-0.5 text-sm"
                      >
                        {canOpenMoment ? (
                          <button
                            type="button"
                            aria-label={`Open moment at ${offsetLabel(entry.startMs)}: ${entry.artifact.title}`}
                            onClick={() => onOpenMoment(entry.momentId)}
                            className="cursor-pointer border-0 bg-transparent p-0 text-left font-medium"
                          >
                            {entry.artifact.title}
                          </button>
                        ) : (
                          <span className="font-medium">{entry.artifact.title}</span>
                        )}
                        <span className="break-all text-xs text-muted-foreground">
                          {entry.artifact.publishRelativePath}
                          {entry.artifact.publishCommitSha != null &&
                            ` @ ${entry.artifact.publishCommitSha.slice(0, 12)}`}
                        </span>
                      </li>
                    ))}
                  </ul>
                </section>
              )}
            </aside>

            {/* Film-strip: `lg:order-1` puts it back in the left column at
                lg+ (reference "SCREENS 158"); on a stacked narrow viewport it
                follows the evidence rail above. */}
            {hasRecording ? (
              <section className="flex flex-col gap-3 lg:order-1 lg:max-h-[75vh] lg:overflow-y-auto lg:pr-1">
                <h3 className="text-sm font-medium text-muted-foreground">
                  Screens {data.screenshots.length}
                </h3>
                {data.screenshots.length === 0 ? (
                  <p
                    data-testid="drilldown-no-screenshots"
                    className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground"
                  >
                    No screenshots were captured for this recording.
                  </p>
                ) : (
                  <ul className="flex flex-col gap-3">
                    {data.screenshots.map(filmStrip)}
                  </ul>
                )}
              </section>
            ) : (
              // Degraded mode: the meeting-level recap link stands where the
              // strip would be (UX-DR11), through the affordance decision —
              // an unsafe scheme is shown inert, never offered.
              <div className="flex flex-wrap items-center gap-3 lg:order-1">
                {headerAffordance?.kind === 'deepLink' && (
                  // Labelled by provider (UX-DR12). Meeting scope, so a
                  // YouTube link here is untimed: "Open on YouTube".
                  <SourceLinkAnchor link={headerAffordance.source} testId="drilldown-deep-link" />
                )}
                {headerAffordance?.kind === 'inertLink' && (
                  <span
                    data-testid="drilldown-unsafe-link"
                    className="break-all text-xs text-muted-foreground"
                  >
                    Source link not opened — unsupported address: {headerAffordance.text}
                  </span>
                )}
                {headerAffordance?.kind === 'none' && (
                  <span
                    data-testid="drilldown-no-evidence"
                    className="text-xs text-muted-foreground"
                  >
                    Transcript only — no recording and no source link.
                  </span>
                )}
              </div>
            )}

            {/* Full timestamped speaker-attributed transcript. `lg:order-2`
                puts it back in the center column at lg+; on a stacked narrow
                viewport it comes last — after the evidence rail and the
                film-strip — since a long transcript is the most likely of the
                three to run well past one screenful. */}
            <section className="flex min-w-0 flex-col gap-3 lg:order-2">
              <h3 className="text-sm font-medium text-muted-foreground">
                Transcript {data.segments.length} turns
              </h3>
              <label className="flex flex-col gap-1 text-sm">
                {/* Visible text is the accessible name, the `CorpusSearch`
                    rule (WCAG 2.5.3). */}
                <span className="text-muted-foreground">
                  Highlight a term across this transcript
                </span>
                <input
                  data-testid="highlight-input"
                  type="search"
                  value={term}
                  placeholder="purchase order"
                  onChange={(event) => setTerm(event.target.value)}
                  className="rounded-md border px-3 py-2 text-sm"
                />
              </label>
              {data.segments.length === 0 ? (
                <p
                  data-testid="drilldown-no-transcript"
                  className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground"
                >
                  This meeting has no transcript segments.
                </p>
              ) : (
                <ul
                  data-testid="drilldown-transcript"
                  className="flex flex-col gap-3 lg:max-h-[75vh] lg:overflow-y-auto lg:pr-1"
                >
                  {highlightedSegments.map(({ segment, runs }) => {
                    const where = offsetLabel(segment.startMs)
                    const key = `seg:${segment.segmentId}`
                    const momentId = segment.momentId
                    const openSegmentMoment =
                      momentId != null && canOpenMoment
                        ? () => onOpenMoment(momentId)
                        : null
                    return (
                      <li
                        key={segment.segmentId}
                        id={`transcript-seg-${segment.segmentId}`}
                        data-testid={`drilldown-segment-${segment.segmentId}`}
                        data-jump-target={jumpTarget === segment.segmentId || undefined}
                        className={`flex flex-col gap-1 rounded-lg border p-3 text-sm ${
                          jumpTarget === segment.segmentId
                            ? 'ring-2 ring-amber-400/70'
                            : ''
                        }`}
                      >
                        <span className="text-xs text-muted-foreground">
                          <span className="font-mono">{where}</span> ·{' '}
                          {speakerName(segment.speakerLabel)}
                        </span>
                        {openSegmentMoment !== null ? (
                          <Button
                            variant="link"
                            aria-label={`Open moment at ${where}: ${segment.text}`}
                            className="h-auto justify-start whitespace-normal p-0 text-left font-normal"
                            onClick={openSegmentMoment}
                          >
                            <SegmentText runs={runs} />
                          </Button>
                        ) : (
                          <SegmentText runs={runs} />
                        )}
                        <div className="flex flex-wrap items-center gap-3">
                          {replayControls(key, where)}
                          {sourceControls(key, segment.startMs)}
                        </div>
                        {inlinePlayer(key, segment.startMs, where)}
                      </li>
                    )
                  })}
                </ul>
              )}
            </section>
          </div>
        )}
      </div>
    </section>
  )
}
