import { useCallback, useEffect, useRef, useState } from 'react'
import { approveMomentArtifacts, getExtractionPrompts, getMoment } from '@/client/sdk.gen'
import type { ExtractionPrompt, MomentDetail } from '@/client/types.gen'
import { SourceLinkAnchor } from '@/components/SourceLinkAnchor'
import { Button } from '@/components/ui/button'
import { affordanceOf, offsetLabel } from '@/lib/affordance'
import { API_BASE } from '@/lib/api'
import { mediaUrl } from '@/lib/media'
import { problemMessage } from '@/lib/problems'
import { ReplayPlayer } from '@/features/replay/ReplayPlayer'
import {
  ARTIFACT_CATEGORIES,
  artifactsOfKind,
  EXTRACTION_PROMPTS_TIMEOUT_MS,
  extractionPromptLabel,
  hasApprovableArtifacts,
  loadFailureOf,
  MOMENT_TIMEOUT_MS,
  type MomentLoadFailure,
  meetingLabelOf,
  notViewableMessage,
  speakerName,
  transportFailureOf,
} from './moments'

export interface MomentViewProps {
  /** The moment to render — a citation id, straight from a hit or a list. */
  momentId: string
}

/**
 * One moment, in CAP-4's anatomy: still screenshot on top, covering
 * transcript below, right rail of extracted artifacts, replay button.
 *
 * The degraded shape is the same view minus what does not exist: a
 * transcript-only meeting renders no screenshot and mounts no player —
 * `ReplayPlayer` has no failure surface, so this caller gates on
 * `hasRecording` — and the transitional source deep link stands exactly where
 * the replay button would be, through the same `affordanceOf` decision search
 * already litigated (UX-DR11).
 */
export function MomentView({ momentId }: MomentViewProps) {
  // `null` is "never answered": a moment that answers always has a detail.
  const [detail, setDetail] = useState<MomentDetail | null>(null)
  const [failure, setFailure] = useState<MomentLoadFailure | null>(null)
  // The raw refused body beside its classification: the 409's `augmenting`/
  // `jobStatus` extensions pick the not-viewable sentence (story 2.3, AD-14).
  const [problem, setProblem] = useState<unknown>(null)
  const [replayOpen, setReplayOpen] = useState(false)
  // The per-moment "Approve & publish" gesture's own request state (story
  // 4.3) — separate from the initial read's `failure`/`problem` so an
  // approve error never masquerades as a load failure and vice versa.
  const [approving, setApproving] = useState(false)
  const [approveError, setApproveError] = useState<string | null>(null)
  // The "Active extraction prompts" section's own read (story 4.2): `null`
  // until it answers, and stays `null` on any failure — the prompts are
  // global config, not per-moment data, so a failed fetch omits the section
  // rather than surfacing as a moment-view error.
  const [prompts, setPrompts] = useState<Array<ExtractionPrompt> | null>(null)
  // Held across renders so a moment change or unmount aborts the in-flight
  // read — an older response must never overwrite a newer result (story
  // 1.10, finding 22).
  const controllerRef = useRef<AbortController | null>(null)
  // Same guard, for the approve gesture (story 4.3): a moment change or
  // unmount while an approve request is in flight must not let its eventual
  // response overwrite state for the wrong moment (or update after unmount).
  const approveControllerRef = useRef<AbortController | null>(null)

  const load = useCallback(async () => {
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller
    // A moment change abandons any in-flight approve for the *old* moment
    // too — its eventual response must never land on the new one.
    approveControllerRef.current?.abort()
    approveControllerRef.current = null
    // A new read means the old answer no longer describes this view. Clear
    // everything up front so the loading state is honest when the moment prop
    // changes, a failure never renders beneath another moment's evidence, and
    // no player outlives the moment it was opened for.
    setDetail(null)
    setFailure(null)
    setProblem(null)
    setReplayOpen(false)
    setApproving(false)
    setApproveError(null)
    // An explicit timer rather than `AbortSignal.timeout`: that signal cannot
    // be cancelled, so a superseded read would leave a live timer behind, and
    // a real `setTimeout` is something a test can drive.
    const expiry = new AbortController()
    const timer = setTimeout(() => expiry.abort(), MOMENT_TIMEOUT_MS)
    try {
      const signal = AbortSignal.any([controller.signal, expiry.signal])
      const { data, error } = await getMoment({ path: { moment_id: momentId }, signal })
      if (controller.signal.aborted) return
      if (expiry.signal.aborted) {
        setFailure({ kind: 'transport', message: `timed out after ${MOMENT_TIMEOUT_MS}ms` })
        return
      }
      if (error !== undefined) {
        setFailure(loadFailureOf(error))
        setProblem(error)
        return
      }
      if (data === undefined) throw new Error('the api answered with no body')
      setDetail(data)
      setFailure(null)
      setReplayOpen(false)
    } catch (err) {
      if (controller.signal.aborted) return
      setFailure(
        expiry.signal.aborted
          ? { kind: 'transport', message: `timed out after ${MOMENT_TIMEOUT_MS}ms` }
          : transportFailureOf(err),
      )
    } finally {
      clearTimeout(timer)
    }
  }, [momentId])

  useEffect(() => {
    void load()
    return () => {
      controllerRef.current?.abort()
      approveControllerRef.current?.abort()
    }
  }, [load])

  // The "Active extraction prompts" section (story 4.2, epics AC1): the two
  // prompts are global config, not per-moment data, so this fetches once on
  // mount rather than on every moment change, and never blocks or errors the
  // rest of the view — a failed or slow fetch simply leaves `prompts` null,
  // which omits the section.
  useEffect(() => {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), EXTRACTION_PROMPTS_TIMEOUT_MS)
    void (async () => {
      try {
        const { data, error } = await getExtractionPrompts({ signal: controller.signal })
        if (controller.signal.aborted || error !== undefined || data === undefined) return
        setPrompts(data.prompts)
      } catch {
        // Tolerant of failure by design — see the comment above.
      } finally {
        clearTimeout(timer)
      }
    })()
    return () => {
      controller.abort()
      clearTimeout(timer)
    }
  }, [])

  // The per-moment "Approve & publish" gesture (story 4.3, epics AC1/AC2):
  // one request advances every `extracted` artifact under this moment
  // straight through to `published`. On success the rail is replaced with
  // the response in place — no re-fetch of the whole moment, since the
  // approve response already carries every artifact's post-publish shape.
  const handleApprove = useCallback(async () => {
    approveControllerRef.current?.abort()
    const controller = new AbortController()
    approveControllerRef.current = controller
    setApproving(true)
    setApproveError(null)
    // Match the moment read's cancellable deadline. A server connection can
    // stall without ever settling the SDK promise; expiry aborts that request
    // and lets the one publishing control recover without changing its rail.
    const expiry = new AbortController()
    const timer = setTimeout(() => {
      expiry.abort()
      // Fetch normally rejects on abort, but restore the control at the
      // deadline itself too: a transport wrapper that ignores its signal must
      // not strand the page in “Publishing…”.
      if (!controller.signal.aborted && approveControllerRef.current === controller) {
        setApproveError(`timed out after ${MOMENT_TIMEOUT_MS}ms`)
        setApproving(false)
      }
    }, MOMENT_TIMEOUT_MS)
    const clearExpiry = () => clearTimeout(timer)
    controller.signal.addEventListener('abort', clearExpiry, { once: true })
    try {
      const signal = AbortSignal.any([controller.signal, expiry.signal])
      const { data, error } = await approveMomentArtifacts({
        path: { moment_id: momentId },
        signal,
      })
      // The moment may have changed (or this component unmounted) while the
      // request was in flight — the same story 1.10 finding 22 guard `load`
      // uses: an older response must never overwrite a newer result.
      if (controller.signal.aborted) return
      if (expiry.signal.aborted) {
        setApproveError(`timed out after ${MOMENT_TIMEOUT_MS}ms`)
        return
      }
      if (error !== undefined) {
        setApproveError(problemMessage(error) ?? 'The api refused the approve request.')
        return
      }
      if (data === undefined) throw new Error('the api answered with no body')
      setDetail((current) => (current === null ? current : { ...current, artifacts: data }))
    } catch (err) {
      if (controller.signal.aborted) return
      setApproveError(
        expiry.signal.aborted
          ? `timed out after ${MOMENT_TIMEOUT_MS}ms`
          : err instanceof Error
            ? err.message
            : String(err),
      )
    } finally {
      clearTimeout(timer)
      controller.signal.removeEventListener('abort', clearExpiry)
      if (!controller.signal.aborted) setApproving(false)
    }
  }, [momentId])

  const loading = detail === null && failure === null
  // Timed at this moment: a YouTube source link carries `t=` from `startMs`.
  const affordance = detail === null ? null : affordanceOf(detail, detail.startMs)

  return (
    <section className="flex w-full flex-col gap-4">
      <header className="flex flex-col gap-1">
        <h2 className="text-lg font-semibold tracking-tight">
          {detail === null
            ? 'Moment'
            : `${meetingLabelOf(detail.meetingTitle, detail.meetingId)} at ${offsetLabel(detail.startMs)}`}
        </h2>
        {detail !== null && (
          <span className="text-xs text-muted-foreground">
            {[
              detail.startedAtPrecision === 'day'
                ? new Date(detail.startedAt).toLocaleDateString()
                : new Date(detail.startedAt).toLocaleString(),
              detail.corpus,
              detail.hasRecording ? null : 'transcript only',
            ]
              .filter((part) => part !== null)
              .join(' · ')}
          </span>
        )}
      </header>

      {detail?.superseded === true && (
        <p
          data-testid="moment-superseded"
          className="rounded-md border border-amber-400/60 p-3 text-sm text-muted-foreground"
        >
          This moment was superseded when the meeting was re-processed — the
          citation still resolves, but a newer moment now covers this span.
        </p>
      )}

      {failure !== null &&
        (failure.kind === 'transport' ? (
          <p role="alert" className="rounded-md border border-destructive/40 p-3 text-sm text-destructive">
            Cannot reach the api at {API_BASE}: {failure.message}.
          </p>
        ) : (
          <p
            role="alert"
            data-testid={`moment-${failure.kind}`}
            className="rounded-md border p-3 text-sm text-muted-foreground"
          >
            {failure.kind === 'notViewable'
              ? // The enriched 409 picks the sentence: failed ingest,
                // augmentation in flight, or first ingest still preparing.
                notViewableMessage(problem)
              : failure.kind === 'notFound'
                ? 'No moment has this id. It may never have been ingested.'
                : `The api could not answer: ${failure.message}.`}
          </p>
        ))}

      <div aria-live="polite" aria-busy={loading} className="flex flex-col gap-4">
        {loading ? (
          <p className="text-sm text-muted-foreground">Loading moment…</p>
        ) : detail === null ? null : (
          <div className="flex flex-col gap-6 md:flex-row">
            {/* Extracted artifacts: placed FIRST in document order — not just
                visually — so a keyboard/screen-reader user, and on a stacked
                narrow-viewport layout a sighted user, reaches it immediately
                rather than only after the screenshot/replay/transcript column.
                `md:order-2` restores it to the right rail once the two-column
                layout applies; the main column below carries the matching
                `md:order-1` to land back on the left. */}
            <aside
              data-testid="moment-artifact-rail"
              aria-label="Extracted artifacts"
              className="flex w-full flex-col gap-3 md:order-2 md:w-64 md:shrink-0"
            >
              {/* Story 4.2, epics AC1: the extraction area shows the complete
                  active prompt text and that a prompt/model edit is a
                  configuration change, not a code change. Global config, not
                  per-moment data — omitted entirely when the fetch has not
                  answered or failed. */}
              {prompts !== null && prompts.length > 0 && (
                <section
                  data-testid="extraction-prompts"
                  className="flex flex-col gap-2 border-b pb-3"
                >
                  <h3 className="text-sm font-medium text-muted-foreground">
                    Active extraction prompts
                  </h3>
                  <ul className="flex flex-col gap-1">
                    {prompts.map((prompt) => (
                      <li key={prompt.kind}>
                        <details className="text-xs">
                          <summary className="cursor-pointer select-none text-muted-foreground">
                            {extractionPromptLabel(prompt.kind)}
                          </summary>
                          <pre
                            data-testid={`extraction-prompt-${prompt.kind}`}
                            className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap rounded-md border bg-muted/30 p-2 text-xs"
                          >
                            {prompt.promptText}
                          </pre>
                        </details>
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              <div className="flex items-baseline justify-between gap-2">
                <h3 className="text-sm font-medium text-muted-foreground">Extracted artifacts</h3>
                {hasApprovableArtifacts(detail.artifacts) && (
                  <Button
                    size="sm"
                    variant="default"
                    disabled={approving}
                    onClick={() => void handleApprove()}
                  >
                    {approving ? 'Publishing…' : 'Approve & publish'}
                  </Button>
                )}
              </div>
              {approveError !== null && (
                <p role="alert" data-testid="moment-approve-error" className="text-xs text-destructive">
                  {approveError}
                </p>
              )}
              <ul className="flex flex-col gap-2">
                {ARTIFACT_CATEGORIES.map((category) => {
                  const entries = artifactsOfKind(detail.artifacts, category.kind)
                  return (
                    <li
                      key={category.kind}
                      data-testid={`artifact-category-${category.kind}`}
                      className="flex flex-col gap-1 text-sm"
                    >
                      <span className="flex items-baseline justify-between gap-2">
                        <span>{category.label}</span>
                        <span className="text-xs text-muted-foreground">{entries.length}</span>
                      </span>
                      {entries.length > 0 && (
                        <ul className="flex flex-col gap-1 pl-3">
                          {entries.map((artifact) => (
                            <li key={artifact.id} className="text-sm">
                              <span className="font-medium">{artifact.title}</span>{' '}
                              <span className="text-xs text-muted-foreground">({artifact.state})</span>
                              {artifact.state === 'published' && (
                                <div
                                  data-testid={`artifact-published-link-${artifact.id}`}
                                  className="text-xs text-muted-foreground"
                                >
                                  {artifact.publishRelativePath}
                                  {artifact.publishCommitSha != null &&
                                    ` @ ${artifact.publishCommitSha.slice(0, 12)}`}
                                </div>
                              )}
                            </li>
                          ))}
                        </ul>
                      )}
                    </li>
                  )
                })}
              </ul>
              {detail.artifacts.length === 0 && (
                <p
                  data-testid="artifact-rail-empty"
                  className="rounded-lg border border-dashed p-4 text-xs text-muted-foreground"
                >
                  Nothing extracted yet. Artifacts appear here for review once
                  extraction runs — nothing is published without approval.
                </p>
              )}
            </aside>

            <div className="flex min-w-0 flex-1 flex-col gap-4 md:order-1">
              {/* Still screenshot on top (CAP-4). The api sends the stored
                  content-root-relative path; `mediaUrl` is the one place a
                  /media address is built. */}
              {detail.screenshotPath != null && (
                <img
                  data-testid="moment-screenshot"
                  src={mediaUrl(detail.screenshotPath)}
                  alt={`Screen at ${offsetLabel(detail.startMs)}`}
                  className="w-full rounded-lg border"
                />
              )}

              {/* The replay affordance, or what stands in for it. */}
              <div className="flex flex-wrap items-center gap-3">
                {affordance?.kind === 'replay' && (
                  <Button
                    size="sm"
                    variant={replayOpen ? 'outline' : 'default'}
                    aria-expanded={replayOpen}
                    aria-label={`${replayOpen ? 'Hide' : 'Replay'} recording at ${offsetLabel(detail.startMs)}`}
                    onClick={() => setReplayOpen((open) => !open)}
                  >
                    {replayOpen ? 'Hide replay' : 'Replay'}
                  </Button>
                )}
                {affordance?.kind === 'replay' && affordance.source !== null && (
                  // UX-DR12: replay first, the source second — the YouTube
                  // link timed at this moment, secondary to the Replay button.
                  <SourceLinkAnchor link={affordance.source} testId="moment-youtube-link" />
                )}
                {affordance?.kind === 'deepLink' && (
                  // UX-DR11: the transitional source deep link, exactly where
                  // the replay button would be, until augmentation supplies
                  // real video. Labelled by provider (UX-DR12): a YouTube link
                  // is timed and named with its offset; any other host keeps
                  // the untimed "Open in Stream".
                  <SourceLinkAnchor link={affordance.source} testId="moment-deep-link" />
                )}
                {affordance?.kind === 'inertLink' && (
                  <span
                    data-testid="moment-unsafe-link"
                    className="break-all text-xs text-muted-foreground"
                  >
                    Source link not opened — unsupported address: {affordance.text}
                  </span>
                )}
                {affordance?.kind === 'none' && (
                  <span
                    data-testid="moment-no-evidence"
                    className="text-xs text-muted-foreground"
                  >
                    Transcript only — no recording and no source link.
                  </span>
                )}
              </div>

              {replayOpen && affordance?.kind === 'replay' && (
                <ReplayPlayer
                  meetingId={detail.meetingId}
                  startMs={detail.startMs}
                  label={`${meetingLabelOf(detail.meetingTitle, detail.meetingId)} at ${offsetLabel(detail.startMs)}`}
                  className="w-full rounded-md"
                />
              )}

              {/* Covering transcript below the still (CAP-4): the
                  `moment_segment` join, in ordinal order, as the api sent it. */}
              <section className="flex flex-col gap-2">
                <h3 className="text-sm font-medium text-muted-foreground">Transcript</h3>
                {detail.segments.length === 0 ? (
                  <p
                    data-testid="moment-no-transcript"
                    className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground"
                  >
                    No transcript covers this moment.
                  </p>
                ) : (
                  <ul data-testid="moment-transcript" className="flex flex-col gap-2">
                    {detail.segments.map((segment, index) => (
                      // eslint-disable-next-line react/no-array-index-key -- segments carry no id; ordinal order is their identity
                      <li key={index} className="flex flex-col gap-0.5 text-sm">
                        <span className="text-xs text-muted-foreground">
                          {offsetLabel(segment.startMs)} · {speakerName(segment.speakerLabel)}
                        </span>
                        <span>{segment.text}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </div>
          </div>
        )}
      </div>
    </section>
  )
}
