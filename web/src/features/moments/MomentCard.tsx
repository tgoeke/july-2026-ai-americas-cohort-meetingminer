import { useEffect, useState } from 'react'
import { getMeetingDrilldown } from '@/client/sdk.gen'
import { SourceLinkAnchor } from '@/components/SourceLinkAnchor'
import { Button } from '@/components/ui/button'
import { webVttDataUrl } from '@/features/replay/captions'
import { affordanceOf, offsetLabel } from '@/lib/affordance'
import { cn } from '@/lib/utils'
import { CaptionedReplayPlayer } from './CaptionedReplayPlayer'
import { KindGlyph } from './KindGlyph'
import {
  cardMetaLabel,
  isArtifactKind,
  NO_SCREENSHOT,
  offsetChipLabel,
  screenshotAlt,
  screenshotUrl,
  TRANSCRIPT_ONLY,
  threadChipName,
  threadPaletteOf,
  type FeedReason,
  type FeedThread,
  type MomentFeedItem,
} from './feed'

/** A kind chip: glyph, one space, the api's label. Never one without the
 * other (`DESIGN.md` · Do's and Don'ts). */
function KindChip({
  kind,
  label,
  onSelect,
}: {
  kind: Parameters<typeof KindGlyph>[0]['kind']
  label: string
  onSelect?: () => void
}) {
  const style = {
    backgroundColor: `var(--kind-${kind}-fill)`,
    color: `var(--kind-${kind}-text)`,
    borderColor: `var(--kind-${kind}-border)`,
  }
  const className =
    'inline-flex min-h-6 items-center gap-1.5 rounded-sm border px-2 py-0.5 text-xs'
  if (onSelect === undefined) {
    return (
      <span className={className} style={style} data-testid={`reason-kind-${kind}`}>
        <KindGlyph kind={kind} />
        {label}
      </span>
    )
  }
  return (
    <button
      type="button"
      className={cn(className, 'cursor-pointer')}
      style={style}
      data-testid={`reason-kind-${kind}`}
      // The chip filters the feed by its kind (EXPERIENCE.md · Moment card);
      // its accessible name says so rather than repeating the label alone.
      aria-label={`Filter by kind ${kind}`}
      onClick={onSelect}
    >
      <KindGlyph kind={kind} />
      {label}
    </button>
  )
}

/** A thread chip: `#name` in the thread's hue, pill-shaped so shape separates
 * thread identity from moment kind before colour does. */
function ThreadChip({
  thread,
  label = thread.name,
  onOpen,
}: {
  thread: FeedThread
  label?: string
  onOpen: () => void
}) {
  const palette = threadPaletteOf(thread.colorOrdinal ?? null)
  return (
    <button
      type="button"
      onClick={onOpen}
      data-testid={`thread-chip-${thread.threadId}`}
      aria-label={threadChipName({ ...thread, name: label })}
      className="inline-flex min-h-6 cursor-pointer items-center rounded-full border px-2 py-0.5 text-xs"
      style={{ color: `var(${palette.textCssVar})`, borderColor: 'currentColor' }}
    >
      <span aria-hidden="true">#</span>
      {label}
      {palette.lap === 2 && (
        // Lap 2 shares its hue with lap 1, so the chip carries the second
        // carrier the design requires: a hatched edge inside the chip.
        <span
          aria-hidden="true"
          data-testid={`thread-lap2-${thread.threadId}`}
          className="ml-1.5 h-3 w-1.5 rounded-[1px] bg-[repeating-linear-gradient(135deg,currentColor_0_3px,transparent_3px_7px)]"
          style={{ color: `var(${palette.swatchCssVar})` }}
        />
      )}
    </button>
  )
}

/**
 * The reason line, followed by the card's remaining thread chips.
 *
 * The reasons come from the api, in the api's order, each label verbatim
 * (EXPERIENCE.md · Reason line): artifact kinds become kind chips, a `thread`
 * reason becomes a thread chip, and every ranking-signal kind — `due`,
 * `risk`, `question`, `recency`, `published` — is plain muted text. No reason
 * is composed here, and a kind outside the seven is never drawn as a kind
 * chip.
 *
 * A moment's `threads[]` is a separate served fact from its reasons: a thread
 * can hold a moment without being the reason it ranks. Every thread the item
 * carries therefore gets a chip, and one a thread reason already named is not
 * drawn twice.
 */
function ReasonLine({
  reasons,
  threads,
  onSelectKind,
  onOpenThread,
}: {
  reasons: Array<FeedReason>
  threads: Array<FeedThread>
  onSelectKind: (kind: string) => void
  onOpenThread: (threadId: string) => void
}) {
  const named = new Set(
    reasons
      .filter((reason) => reason.kind === 'thread' && typeof reason.ref === 'string')
      .map((reason) => reason.ref as string),
  )
  const remaining = threads.filter((thread) => !named.has(thread.threadId))
  return (
    <div className="flex flex-wrap items-center gap-1.5" data-testid="reason-line">
      {reasons.map((reason, index) => {
        const key = `${reason.kind}-${reason.ref ?? index}`
        if (isArtifactKind(reason.kind)) {
          return (
            <KindChip
              key={key}
              kind={reason.kind}
              label={reason.label}
              onSelect={() => onSelectKind(reason.kind)}
            />
          )
        }
        if (reason.kind === 'thread') {
          const thread = threads.find((candidate) => candidate.threadId === reason.ref)
          if (thread !== undefined) {
            return (
              <ThreadChip
                key={key}
                thread={thread}
                label={reason.label}
                onOpen={() => onOpenThread(thread.threadId)}
              />
            )
          }
        }
        return (
          <span key={key} className="text-xs text-muted-foreground" data-testid="reason-text">
            {reason.label}
          </span>
        )
      })}
      {remaining.map((thread) => (
        <ThreadChip
          key={thread.threadId}
          thread={thread}
          onOpen={() => onOpenThread(thread.threadId)}
        />
      ))}
    </div>
  )
}

export interface MomentCardProps {
  item: MomentFeedItem
  /** Whether this card's inline player is the one open on the grid. */
  expanded: boolean
  /** Toggle this card's player. At most one is open across the whole feed. */
  onToggleReplay: () => void
  onOpenMoment: () => void
  onOpenMeeting: () => void
  onSelectKind: (kind: string) => void
  onOpenThread: (threadId: string) => void
}

/**
 * One ranked moment (`DESIGN.md` · Moment card; `mockups/moments.html`).
 *
 * Screenshot, meeting and offset, the stated reason, thread chips; it replays
 * in place and links to its moment and its meeting (story 10.5's first
 * acceptance clause). Expanded, the card spans the grid and the player opens
 * under the screenshot — the single-open pattern `MeetingMoments` already
 * uses, so opening one card's player closes another's rather than stacking
 * players down the page.
 *
 * The replay-or-deep-link decision is `affordanceOf`, unchanged: a recording
 * gets Replay with the YouTube link beside it, a meeting without one gets the
 * link instead, and a transcript-only moment says so in a sentence rather
 * than offering a dead button.
 */
export function MomentCard({
  item,
  expanded,
  onToggleReplay,
  onOpenMoment,
  onOpenMeeting,
  onSelectKind,
  onOpenThread,
}: MomentCardProps) {
  const [shotFailed, setShotFailed] = useState(false)
  const [captionsSrc, setCaptionsSrc] = useState<string | null>(null)
  const affordance = affordanceOf(item, item.startMs)
  const title = item.meetingTitle?.trim() || item.meetingId
  const offset = offsetLabel(item.startMs)
  const hasShot = item.screenshotId !== null && !shotFailed
  const openMoment = () => {
    if (expanded) onToggleReplay()
    onOpenMoment()
  }
  const openMeeting = () => {
    if (expanded) onToggleReplay()
    onOpenMeeting()
  }

  useEffect(() => {
    setCaptionsSrc(null)
    if (!expanded || affordance.kind !== 'replay') return
    const controller = new AbortController()
    const load = async () => {
      try {
        const { data, error } = await getMeetingDrilldown({
          path: { meeting_id: item.meetingId },
          signal: controller.signal,
        })
        if (controller.signal.aborted || error !== undefined || data === undefined) return
        setCaptionsSrc(webVttDataUrl(data.segments))
      } catch {
        // Replay remains usable when its optional transcript read fails.
      }
    }
    void load()
    return () => controller.abort()
  }, [affordance.kind, expanded, item.meetingId])

  const frame = (
    <div
      className="relative flex aspect-video items-center justify-center overflow-hidden rounded-md bg-muted"
      data-testid={`moment-shot-${item.momentId}`}
    >
      {hasShot ? (
        <img
          src={screenshotUrl(item.screenshotId!)}
          alt={screenshotAlt(item)}
          onError={() => setShotFailed(true)}
          className="h-full w-full object-contain"
        />
      ) : (
        <p className="px-5 text-center text-xs text-muted-foreground">{NO_SCREENSHOT}</p>
      )}
      <span className="absolute bottom-2 left-2 rounded-sm bg-black/60 px-1.5 py-0.5 font-mono text-[11px] tabular-nums text-foreground">
        {offsetChipLabel(item)}
      </span>
    </div>
  )

  return (
    <article
      data-testid={`moment-card-${item.momentId}`}
      className={cn(
        'flex flex-col gap-3 rounded-lg border border-border bg-card p-4 transition-colors hover:border-white/20',
        expanded && 'col-span-full',
      )}
    >
      {/* The screenshot and title are one first focus stop. This keeps the
          visible evidence target generous without creating a duplicate
          keyboard action before the title (Accessibility Floor). */}
      <button
        type="button"
        onClick={openMoment}
        data-testid={`moment-title-${item.momentId}`}
        data-moment-title-id={item.momentId}
        aria-label={`Open moment ${title}`}
        className={cn(
          'grid w-full cursor-pointer gap-3 text-left',
          expanded && 'lg:grid-cols-[1.15fr_1fr] lg:items-start',
        )}
      >
        {frame}
        <span className="block min-w-0">
          <span className="block text-[15px] leading-snug font-semibold hover:underline">
            {title}
          </span>
          <span className="mt-0.5 block font-mono text-xs tabular-nums text-muted-foreground">
            {cardMetaLabel(item)}
          </span>
        </span>
      </button>

      <div className="flex flex-wrap items-center gap-2">
        {affordance.kind === 'replay' && (
          <Button
            size="sm"
            onClick={onToggleReplay}
            aria-expanded={expanded}
            data-testid={`replay-${item.momentId}`}
            aria-label={`Replay recording at ${offset}`}
          >
            <span aria-hidden="true">▶</span> Replay{' '}
            <span className="font-mono tabular-nums">{offset}</span>
          </Button>
        )}
        <Button
          size="sm"
          variant="outline"
          onClick={openMoment}
          data-testid={`open-moment-${item.momentId}`}
          aria-label={`Open moment at ${offset} in ${title}`}
        >
          Open moment
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={openMeeting}
          data-testid={`open-meeting-${item.momentId}`}
          aria-label={`Open meeting ${title}`}
        >
          Open meeting
        </Button>
        {affordance.kind === 'replay' && affordance.source !== null && (
          <SourceLinkAnchor link={affordance.source} testId={`source-${item.momentId}`} />
        )}
        {affordance.kind === 'replay' && affordance.inertSource !== null && (
          <span className="text-xs text-muted-foreground">
            Source link not opened — unsupported address: {affordance.inertSource}
          </span>
        )}
        {affordance.kind === 'deepLink' && (
          <SourceLinkAnchor link={affordance.source} testId={`source-${item.momentId}`} />
        )}
        {affordance.kind === 'inertLink' && (
          <span className="text-xs text-muted-foreground">{affordance.text}</span>
        )}
        {affordance.kind === 'none' && (
          <span className="text-xs text-muted-foreground">{TRANSCRIPT_ONLY}</span>
        )}
      </div>

      {expanded && affordance.kind === 'replay' && (
        <CaptionedReplayPlayer
          meetingId={item.meetingId}
          startMs={item.startMs}
          label={`Recording of ${title} at ${offset}`}
          className="w-full rounded-md border border-border bg-background"
          captions={
            captionsSrc === null
              ? undefined
              : { src: captionsSrc, label: `Transcript captions for ${title}` }
          }
        />
      )}

      <ReasonLine
        reasons={item.reasons}
        threads={item.threads}
        onSelectKind={onSelectKind}
        onOpenThread={onOpenThread}
      />

      {item.preview?.trim() && (
        <p className="line-clamp-2 text-sm leading-relaxed text-foreground/90">
          “{item.preview.trim()}”
        </p>
      )}
    </article>
  )
}
