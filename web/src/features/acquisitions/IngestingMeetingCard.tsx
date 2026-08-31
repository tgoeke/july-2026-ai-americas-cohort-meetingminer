import { useCallback, useEffect, useRef, useState } from 'react'
import { listMeetings } from '@/client/sdk.gen'
import type { JobEvent, MeetingListItem } from '@/client/types.gen'
import { Button } from '@/components/ui/button'
import {
  applyEvent,
  blockedReason,
  countParts,
  durationLabel,
  meetingLabel,
  startedLabel,
} from '@/features/meetings/rows'
import { StageProgress } from '@/features/meetings/StageProgress'
import type { RenderedStageStatus } from '@/features/meetings/stageStyles'
import { useJobEvents } from '@/features/meetings/useJobEvents'
import { API_BASE } from '@/lib/api'
import { mediaUrl } from '@/lib/media'
import { failureMessage, failureOf, transportFailure } from './acquisitions'

/** The ingest state the stepper's fourth bar shows, read from the job row. */
export function ingestStatusOf(row: MeetingListItem | null): RenderedStageStatus {
  if (row === null) return 'queued'
  if (row.status === 'failed' || row.stages.some((stage) => stage.status === 'failed')) {
    return 'failed'
  }
  // The api owns the verdict. `viewable` is the gate the whole app already
  // uses, so "done" here means exactly what "Open" being enabled means.
  if (row.viewable) return 'done'
  return 'running'
}

export interface IngestingMeetingCardProps {
  /** The job `POST /ingests` returned, reported by `GET /acquisitions/{id}`. */
  jobId: string
  /** True only when this new acquisition's served probe said captions were auto-generated. */
  speakerLabelsMissing: boolean
  onOpen: (meetingId: string) => void
  onNameSpeakers: (meetingId: string) => void
  onIngestStatus: (status: RenderedStageStatus) => void
}

/**
 * The meeting that just arrived, filling in live.
 *
 * Mounted **only once the acquisition reaches `posted`** — which is also why
 * the SSE subscription lives in this component rather than in the screen:
 * opening `/jobs/events` on an idle Add-meeting form would spend a connection
 * for nothing, and the story requires that merely opening `/add` issues no
 * request.
 *
 * The card is the meetings list's card, built from the same `rows.ts` helpers
 * and the same `StageProgress`, so a meeting looks the same here as it does
 * everywhere else and there is one stage renderer in the app.
 */
export function IngestingMeetingCard({
  jobId,
  speakerLabelsMissing,
  onOpen,
  onNameSpeakers,
  onIngestStatus,
}: IngestingMeetingCardProps) {
  const [row, setRow] = useState<MeetingListItem | null>(null)
  const [seedError, setSeedError] = useState<string | null>(null)
  const [announcement, setAnnouncement] = useState('')
  const rowRef = useRef<MeetingListItem | null>(null)
  const seedStateRef = useRef({ inFlight: false, pending: false })
  const firstAliveRef = useRef(false)
  const unmountedRef = useRef(false)

  const commit = useCallback((next: MeetingListItem | null) => {
    rowRef.current = next
    setRow(next)
  }, [])

  const fetchSeed = useCallback(async () => {
    try {
      const { data, error } = await listMeetings({})
      if (unmountedRef.current) return
      if (error !== undefined || data === undefined) {
        setSeedError(failureMessage(failureOf(error)))
        return
      }
      const found = data.meetings.find((meeting) => meeting.jobId === jobId) ?? null
      setSeedError(null)
      // `/meetings` is job-backed, so the job appears before its left-joined
      // meeting does. A null meeting id is still the pre-mint state, not enough
      // information to render a meeting card.
      if (found?.meetingId != null) commit(found)
    } catch (err) {
      if (unmountedRef.current) return
      setSeedError(transportFailure(err instanceof Error ? err.message : String(err)).message)
    }
  }, [commit, jobId])

  // At most one seed is in flight. A stream frame that arrives during it asks
  // for one follow-up snapshot instead of disappearing into the race window.
  const requestSeed = useCallback(() => {
    const state = seedStateRef.current
    if (state.inFlight) {
      state.pending = true
      return
    }
    void (async () => {
      state.inFlight = true
      try {
        do {
          state.pending = false
          await fetchSeed()
        } while (state.pending && !unmountedRef.current)
      } finally {
        state.inFlight = false
      }
    })()
  }, [fetchSeed])

  const onEvent = useCallback(
    (event: JobEvent) => {
      if (event.jobId !== jobId) return
      if (event.stage != null) {
        setAnnouncement(`${event.stage} ${event.status ?? 'unknown'}`)
      }
      const current = rowRef.current
      if (current === null) {
        // The event is for our job but no row is held yet — the seed has not
        // landed, or ran before the row existed. Re-seed rather than build a
        // half-row out of an event that carries no title, source or start.
        requestSeed()
        return
      }
      const next = applyEvent([current], event)
      if (next === null) {
        requestSeed()
        return
      }
      commit(next[0])
      // A finished job has just acquired its counts and poster; pick them up.
      if (event.event === 'job.done') requestSeed()
    },
    [commit, jobId, requestSeed],
  )

  const onResync = useCallback(() => {
    requestSeed()
  }, [requestSeed])

  const onAlive = useCallback(() => {
    // The server's first frame follows a silent baseline. Seed on that frame
    // even if the mount seed already produced a row, so the two snapshots
    // bracket transitions that occurred between them. While no row exists,
    // later heartbeats keep providing retry opportunities without a poll loop.
    if (!firstAliveRef.current || rowRef.current === null) {
      firstAliveRef.current = true
      requestSeed()
    }
  }, [requestSeed])

  const connection = useJobEvents({ onEvent, onResync, onAlive })

  useEffect(() => {
    unmountedRef.current = false
    firstAliveRef.current = false
    requestSeed()
    return () => {
      unmountedRef.current = true
    }
  }, [requestSeed])

  // Reported up so the stepper's `ingesting` bar and this card never disagree
  // about the same job.
  useEffect(() => {
    onIngestStatus(ingestStatusOf(row))
  }, [onIngestStatus, row])

  if (row === null) {
    return (
      <div
        data-testid="meeting-pending"
        className="flex flex-col gap-2 rounded-lg border border-dashed p-4 text-sm text-muted-foreground"
      >
        <p
          className="sr-only"
          aria-live="polite"
          aria-atomic="true"
          data-testid="ingestion-announcement"
        >
          {announcement}
        </p>
        <p>
          Posted to <code>/ingests</code>. The meeting row appears once the worker claims the
          job — nothing to show for job {jobId.slice(0, 8)}… yet.
        </p>
        {seedError !== null && (
          <p role="alert" className="text-destructive">
            {seedError}
          </p>
        )}
        {connection.kind === 'lost' && (
          <p role="alert" className="text-destructive">
            Lost the progress stream from the api at {API_BASE}: {connection.message}. Retrying.
          </p>
        )}
      </div>
    )
  }

  const label = meetingLabel(row)
  const reason = row.viewable ? null : blockedReason(row)
  const meta = [startedLabel(row), durationLabel(row.durationMs), row.corpus, row.status]
    .filter((part) => part != null)
    .join(' · ')
  const counts = countParts(row)
  const transcribeDone = row.stages.some(
    (stage) => stage.name === 'transcribe' && stage.status === 'done',
  )

  return (
    <div
      data-testid="acquired-meeting"
      data-viewable={row.viewable}
      className="flex gap-4 rounded-lg border p-4"
    >
      <p
        className="sr-only"
        aria-live="polite"
        aria-atomic="true"
        data-testid="ingestion-announcement"
      >
        {announcement}
      </p>
      {row.posterScreenshotPath != null ? (
        <img
          src={mediaUrl(row.posterScreenshotPath)}
          alt={`${label} poster screenshot`}
          loading="lazy"
          className="h-20 w-32 shrink-0 rounded border object-cover"
        />
      ) : (
        <div className="flex h-20 w-32 shrink-0 items-center justify-center rounded border border-dashed p-2 text-center text-[10px] leading-tight text-muted-foreground">
          {row.hasRecording === false
            ? 'Transcript only — no recording, so no screens were captured.'
            : 'No screens captured yet.'}
        </div>
      )}

      <div className="flex min-w-0 grow flex-col gap-2">
        {seedError !== null && (
          <p role="alert" className="text-sm text-destructive">
            {seedError}
          </p>
        )}
        {connection.kind === 'lost' && (
          <p role="alert" className="text-sm text-destructive">
            Lost the progress stream from the api at {API_BASE}: {connection.message}. Retrying.
          </p>
        )}
        <div className="flex min-w-0 flex-col">
          <span className="truncate font-medium">{label}</span>
          <span className="text-xs text-muted-foreground">{meta}</span>
        </div>

        {counts.length > 0 && (
          <p className="font-mono text-xs text-muted-foreground">{counts.join(' · ')}</p>
        )}

        <StageProgress stages={row.stages} />

        {row.error != null && (
          <p className="font-mono text-xs text-rose-700 dark:text-rose-400">{row.error}</p>
        )}

        <div className="flex flex-wrap items-center gap-3">
          <Button
            type="button"
            size="sm"
            disabled={!row.viewable}
            title={reason ?? undefined}
            aria-label={`Open ${label}`}
            aria-describedby={reason ? 'acquired-open-reason' : undefined}
            onClick={() => {
              if (row.meetingId != null) onOpen(row.meetingId)
            }}
          >
            Open
          </Button>
          {speakerLabelsMissing && transcribeDone && row.meetingId != null && (
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => onNameSpeakers(row.meetingId!)}
            >
              Name speakers
            </Button>
          )}
          {reason !== null && (
            <span id="acquired-open-reason" className="text-xs text-muted-foreground">
              {reason}
            </span>
          )}
        </div>
      </div>
    </div>
  )
}
