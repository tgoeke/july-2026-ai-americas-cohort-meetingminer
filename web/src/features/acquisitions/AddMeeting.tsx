import { useCallback, useEffect, useRef, useState } from 'react'
import { probeAcquisition, startAcquisition } from '@/client/sdk.gen'
import type { ProbeResult } from '@/client/types.gen'
import { Button } from '@/components/ui/button'
import type { RenderedStageStatus } from '@/features/meetings/stageStyles'
import {
  type Failure,
  IN_PROGRESS_PROBLEM,
  failureOf,
  isLive,
  postedWordFor,
  probeSummary,
  refusalOfStatus,
  stepperSteps,
} from './acquisitions'
import { AcquisitionStepper } from './AcquisitionStepper'
import { IngestingMeetingCard } from './IngestingMeetingCard'
import { RefusalBox, TransportNotice } from './RefusalBox'
import { useAcquisitionStatus } from './useAcquisitionStatus'
import { SHAPE_MESSAGE, classifyYoutubeUrl } from './youtubeUrl'

/** EXPERIENCE.md:133 — the pre-flight probe waits this long after typing stops. */
export const PROBE_DEBOUNCE_MS = 600

const TABS = [
  { id: 'youtube', label: 'YouTube URL' },
  { id: 'local', label: 'Local files' },
  { id: 'zoom', label: 'Zoom export' },
  { id: 'teams', label: 'Teams export' },
] as const

type TabId = (typeof TABS)[number]['id']

/**
 * What the three file tabs say until story 6.5a fills them.
 *
 * A tab that is present but empty would be a disabled control with no sentence
 * saying why, which EXPERIENCE.md bans. This names the missing piece and gives
 * the procedure that still works today (`docs/README.md`), rather than leaving
 * the reader at a dead end.
 */
const FILE_TAB_NOTE =
  'Not available yet — bringing files in through the browser needs the api upload endpoint, which is not built. Use the YouTube URL tab, or mint a drop from the command line: make mint-drop MINT_ARGS="\'<file>\' --corpus real --title \'<title>\'".'

type ProbeState =
  | { kind: 'idle' }
  | { kind: 'probing' }
  | { kind: 'answered'; probe: ProbeResult }
  | { kind: 'failed'; failure: Failure }

export interface AddMeetingProps {
  /** Where Open goes once the meeting is viewable. Injected so the screen has no router dependency in tests. */
  onOpenMeeting?: (meetingId: string) => void
  /** Where Name speakers goes once an auto-captioned meeting has been transcribed. */
  onNameSpeakers?: (meetingId: string) => void
}

/**
 * Add-meeting: one flow, four source tabs, the YouTube URL tab built.
 *
 * The order of events is the whole design (EXPERIENCE.md · Flow 1): an offline
 * shape check, then a probe that writes nothing, then Submit, then progress —
 * so a user learns that a video is too long, private, or already in the corpus
 * *before* anything is downloaded or minted.
 *
 * Nothing here is a second implementation of something the app already has.
 * Progress after `posted` is the existing `/jobs/events` stream through
 * `useJobEvents`, and the meeting is the existing card built from the existing
 * `rows.ts` helpers.
 */
export function AddMeeting({ onOpenMeeting, onNameSpeakers }: AddMeetingProps = {}) {
  const [tab, setTab] = useState<TabId>('youtube')
  const [url, setUrl] = useState('')
  const [probeState, setProbeState] = useState<ProbeState>({ kind: 'idle' })
  const [probeAttempt, setProbeAttempt] = useState(0)
  const [submitting, setSubmitting] = useState(false)
  const [submitFailure, setSubmitFailure] = useState<Failure | null>(null)
  const [acquisitionId, setAcquisitionId] = useState<string | null>(null)
  const [ingesting, setIngesting] = useState<RenderedStageStatus>('queued')

  const urlRef = useRef<HTMLInputElement | null>(null)
  const tabRefs = useRef<Partial<Record<TabId, HTMLButtonElement | null>>>({})
  /**
   * Asynchronous ownership (EXPERIENCE.md:172): a probe reply may update the
   * screen only while both the generation that issued it and the normalized
   * URL it was issued for are still current. Late success and late failure are
   * discarded rather than racing each other onto the field.
   */
  const probeOwner = useRef({ generation: 0, key: '' })

  const shape = classifyYoutubeUrl(url)
  const probeKey = shape.kind === 'valid' ? shape.normalized : null
  const { status, failure: pollFailure, retry } = useAcquisitionStatus(acquisitionId)

  useEffect(() => {
    urlRef.current?.focus()
  }, [])

  // The debounced pre-flight probe. Re-runs on every keystroke: the cleanup
  // cancels the pending timer and aborts an in-flight request, so exactly one
  // probe is ever outstanding for the URL currently in the field.
  useEffect(() => {
    if (probeKey === null) {
      probeOwner.current = { generation: probeOwner.current.generation + 1, key: '' }
      setProbeState({ kind: 'idle' })
      return
    }
    const key = probeKey
    // A successful answer belongs only to the normalized URL that produced it.
    // Clear it before the next URL's debounce so that URL cannot be submitted
    // during the window before its own probe begins.
    setProbeState({ kind: 'idle' })
    const controller = new AbortController()
    const generation = probeOwner.current.generation + 1
    probeOwner.current = { generation, key }
    const owned = () => probeOwner.current.generation === generation && probeOwner.current.key === key

    const timer = setTimeout(() => {
      setProbeState({ kind: 'probing' })
      void (async () => {
        try {
          const { data, error } = await probeAcquisition({
            body: { url: key },
            signal: controller.signal,
          })
          if (!owned()) return
          if (error !== undefined || data === undefined) {
            setProbeState({ kind: 'failed', failure: failureOf(error) })
            return
          }
          setProbeState({ kind: 'answered', probe: data })
        } catch (err) {
          if (!owned() || controller.signal.aborted) return
          setProbeState({ kind: 'failed', failure: failureOf(err) })
        }
      })()
    }, PROBE_DEBOUNCE_MS)

    return () => {
      clearTimeout(timer)
      controller.abort()
    }
    // Keyed on the *normalized* URL, not the raw text: two spellings of one
    // video are one probe. The explicit attempt changes only when Retry asks
    // this effect to issue the same normalized request again.
  }, [probeAttempt, probeKey])

  const submit = useCallback(
    async (target: string) => {
      setSubmitFailure(null)
      setSubmitting(true)
      try {
        const { data, error } = await startAcquisition({ body: { url: target } })
        if (error !== undefined || data === undefined) {
          setSubmitFailure(failureOf(error))
          return
        }
        setIngesting('queued')
        setAcquisitionId(data.acquisitionId)
      } catch (err) {
        setSubmitFailure(failureOf(err))
      } finally {
        setSubmitting(false)
      }
    },
    [],
  )

  const onTabKey = useCallback(
    (event: React.KeyboardEvent<HTMLButtonElement>, index: number) => {
      const delta = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0
      const target =
        delta !== 0
          ? (index + delta + TABS.length) % TABS.length
          : event.key === 'Home'
            ? 0
            : event.key === 'End'
              ? TABS.length - 1
              : -1
      if (target < 0) return
      event.preventDefault()
      const next = TABS[target].id
      setTab(next)
      tabRefs.current[next]?.focus()
    },
    [],
  )

  // Locked from Submit until the acquisition settles. `status === null` is the
  // window between the 202 and the first poll — live, not idle.
  const locked =
    submitting || (acquisitionId !== null && (status === null || isLive(status.status)))
  const posted = status?.status === 'posted'
  const statusRefusal = status === null ? null : refusalOfStatus(status)
  const submitDisabled = locked || probeState.kind !== 'answered'

  const submitReason = submitting
    ? 'Submitting…'
    : locked
      ? 'The form is locked while the acquisition runs.'
      : shape.kind === 'empty'
        ? 'Paste a YouTube watch or youtu.be link to begin.'
        : shape.kind !== 'valid'
          ? 'The URL must be a single YouTube video before it can be submitted.'
          : probeState.kind === 'probing'
            ? 'Waiting for the pre-flight check to answer.'
            : probeState.kind === 'failed'
              ? probeState.failure.kind === 'transport'
                ? 'Retry the pre-flight check before submitting.'
                : 'The pre-flight check refused this URL.'
              : probeState.kind === 'idle'
                ? 'Waiting for the pre-flight check.'
                : null

  return (
    <section className="mx-auto flex w-full max-w-[720px] flex-col gap-6">
      <header>
        <h2 className="text-lg font-semibold tracking-tight">Add a meeting</h2>
      </header>

      <div role="tablist" aria-label="Meeting source" className="flex flex-wrap gap-1 border-b border-border">
        {TABS.map((entry, index) => (
          <button
            key={entry.id}
            ref={(node) => {
              tabRefs.current[entry.id] = node
            }}
            role="tab"
            type="button"
            id={`tab-${entry.id}`}
            aria-selected={tab === entry.id}
            aria-controls={`panel-${entry.id}`}
            tabIndex={tab === entry.id ? 0 : -1}
            onClick={() => setTab(entry.id)}
            onKeyDown={(event) => onTabKey(event, index)}
            className={
              tab === entry.id
                ? 'border-b-2 border-primary px-4 py-2 text-sm font-medium text-foreground'
                : 'border-b-2 border-transparent px-4 py-2 text-sm text-muted-foreground hover:text-foreground'
            }
          >
            {entry.label}
          </button>
        ))}
      </div>

      {TABS.filter((entry) => entry.id !== 'youtube').map((entry) => (
        <div
          key={entry.id}
          role="tabpanel"
          id={`panel-${entry.id}`}
          aria-labelledby={`tab-${entry.id}`}
          hidden={tab !== entry.id}
          data-testid={`panel-${entry.id}`}
        >
          <p className="rounded-lg border border-dashed p-6 text-sm text-muted-foreground">
            {FILE_TAB_NOTE}
          </p>
        </div>
      ))}

      {/* The YouTube panel keeps its state while another tab is shown —
          `hidden` rather than unmounted — so switching away and back does not
          discard a typed URL or a running acquisition (EXPERIENCE.md:98). */}
      <form
        role="tabpanel"
        id="panel-youtube"
        aria-labelledby="tab-youtube"
        hidden={tab !== 'youtube'}
        data-testid="panel-youtube"
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault()
          if (!submitDisabled && shape.kind === 'valid') void submit(shape.normalized)
        }}
      >
        <div className="flex flex-col gap-2">
          <label htmlFor="youtube-url" className="text-sm font-medium">
            YouTube URL
          </label>
          <input
            id="youtube-url"
            ref={urlRef}
            type="url"
            data-testid="youtube-url"
            value={url}
            readOnly={locked}
            aria-busy={probeState.kind === 'probing'}
            aria-describedby="youtube-url-help"
            onChange={(event) => {
              setUrl(event.target.value)
              // The cause of a submit refusal just changed, so its box goes;
              // a refusal is dismissed only by changing what caused it.
              setSubmitFailure(null)
            }}
            placeholder="https://www.youtube.com/watch?v=…"
            className="w-full rounded-md border border-input bg-card px-3 py-2 font-mono text-sm read-only:opacity-70"
          />
          <p id="youtube-url-help" className="text-xs text-muted-foreground">
            {shape.kind === 'playlist'
              ? SHAPE_MESSAGE.playlist
              : shape.kind === 'invalid'
                ? SHAPE_MESSAGE.invalid
                : 'Nothing is written until the acquisition tool accepts the URL.'}
          </p>

          {probeState.kind === 'probing' && (
            <p data-testid="probe-running" className="font-mono text-xs text-muted-foreground">
              Probing…
            </p>
          )}
          {probeState.kind === 'answered' && (
            <>
              <p data-testid="probe-answered" className="font-mono text-xs text-muted-foreground">
                {probeSummary(probeState.probe)}
              </p>
              {probeState.probe.captions?.kind === 'auto' && (
                <p data-testid="auto-caption-warning" className="text-xs text-amber-800 dark:text-amber-300">
                  Auto-generated captions do not include speaker labels. Segments will initially
                  appear as <span className="font-mono">Unknown</span>.
                </p>
              )}
              <p className="text-xs text-muted-foreground">Nothing has been written.</p>
            </>
          )}
          {probeState.kind === 'failed' && probeState.failure.kind === 'refusal' && (
            <>
              <RefusalBox testId="probe-refusal" refusal={probeState.failure.refusal} />
              <p className="text-xs text-muted-foreground">
                Nothing was sent — the probe answered before submit.
              </p>
            </>
          )}
          {probeState.kind === 'failed' && probeState.failure.kind === 'transport' && (
            <TransportNotice
              testId="probe-transport"
              message={probeState.failure.message}
              onRetry={() => {
                // Re-run the probe for the same URL by clearing the owner key.
                probeOwner.current = { generation: probeOwner.current.generation + 1, key: '' }
                setProbeState({ kind: 'idle' })
                setProbeAttempt((value) => value + 1)
              }}
            />
          )}
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <Button
            type="submit"
            data-testid="submit-acquisition"
            disabled={submitDisabled}
            aria-describedby={submitReason === null ? undefined : 'submit-reason'}
          >
            Submit
          </Button>
          {submitReason !== null && (
            <span id="submit-reason" className="text-xs text-muted-foreground">
              {submitReason}
            </span>
          )}
        </div>

        {submitFailure !== null && submitFailure.kind === 'refusal' && (
          <RefusalBox
            testId="submit-refusal"
            refusal={submitFailure.refusal}
            action={
              submitFailure.refusal.type === IN_PROGRESS_PROBLEM &&
              typeof submitFailure.body.acquisitionId === 'string' ? (
                <Button
                  size="sm"
                  variant="outline"
                  data-testid="open-running-acquisition"
                  onClick={() => {
                    setSubmitFailure(null)
                    setIngesting('queued')
                    setAcquisitionId(submitFailure.body.acquisitionId as string)
                  }}
                >
                  Open the running acquisition
                </Button>
              ) : undefined
            }
          />
        )}
        {submitFailure !== null && submitFailure.kind === 'transport' && (
          <TransportNotice testId="submit-transport" message={submitFailure.message} />
        )}

        {acquisitionId !== null && (
          <div className="flex flex-col gap-4">
            <AcquisitionStepper
              steps={stepperSteps(
                status?.status ?? 'queued',
                ingesting,
                status !== null && status.status === 'posted' ? postedWordFor(status) : undefined,
              )}
              logTail={status?.logTail ?? []}
            />

            {pollFailure !== null && pollFailure.kind === 'transport' && (
              <TransportNotice
                testId="poll-transport"
                message={pollFailure.message}
                onRetry={retry}
              />
            )}
            {pollFailure !== null && pollFailure.kind === 'refusal' && (
              <RefusalBox
                testId="poll-refusal"
                refusal={pollFailure.refusal}
                action={
                  <Button size="sm" variant="outline" onClick={retry}>
                    Retry
                  </Button>
                }
              />
            )}

            {statusRefusal !== null && (
              <RefusalBox testId="acquisition-refusal" refusal={statusRefusal} />
            )}

            {posted && status?.result === 'exists' && (
              <p data-testid="already-in-corpus" className="text-sm">
                Already in the corpus — nothing downloaded.
              </p>
            )}

            {posted && status?.jobId != null && (
              <IngestingMeetingCard
                jobId={status.jobId}
                speakerLabelsMissing={
                  status.result === 'created' &&
                  probeState.kind === 'answered' &&
                  probeState.probe.captions?.kind === 'auto'
                }
                onIngestStatus={setIngesting}
                onOpen={(meetingId) => onOpenMeeting?.(meetingId)}
                onNameSpeakers={(meetingId) => onNameSpeakers?.(meetingId)}
              />
            )}
          </div>
        )}
      </form>
    </section>
  )
}
