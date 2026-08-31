import { useState } from 'react'
import { SourceLinkAnchor } from '@/components/SourceLinkAnchor'
import { Button } from '@/components/ui/button'
import { ReplayPlayer } from '@/features/replay/ReplayPlayer'
import { affordanceOf, offsetLabel } from '@/lib/affordance'
import { cn } from '@/lib/utils'
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
function ThreadChip({ thread, onOpen }: { thread: FeedThread; onOpen: () => void }) {
  const palette = threadPaletteOf(thread.colorOrdinal)
  return (
    <button
      type="button"
      onClick={onOpen}
      data-testid={`thread-chip-${thread.threadId}`}
      aria-label={threadChipName(thread)}
      className="inline-flex min-h-6 cursor-pointer items-center rounded-full border px-2 py-0.5 text-xs"
      style={{ color: `var(${palette.cssVar})`, borderColor: 'currentColor' }}
    >
      <span aria-hidden="true">#</span>
      {thread.name}
      {palette.lap === 2 && (
        // Lap 2 shares its hue with lap 1, so the chip carries the second
        // carrier the design requires: a hatched edge inside the chip.
        <span
          aria-hidden="true"
          data-testid={`thread-lap2-${thread.threadId}`}
          className="ml-1.5 h-3 w-1.5 rounded-[1px] bg-[repeating-linear-gradient(135deg,currentColor_0_3px,transparent_3px_7px)]"
        />
      )}
    </button>
  )
}

/**
 * The reason line: the api's reasons, in the api's order, each label verbatim
 * (EXPERIENCE.md · Reason line). Artifact kinds become kind chips, `thread`
 * becomes a thread chip, and every ranking-signal kind — `due`, `risk`,
 * `question`, `recency`, `published` — is plain muted text. No reason is
 * composed here, and a kind outside the seven is never drawn as a kind chip.
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
  const affordance = affordanceOf(item, item.startMs)
  const title = item.meetingTitle?.trim() || item.meetingId
  const offset = offsetLabel(item.startMs)
  const hasShot = item.screenshotId !== null && !shotFailed

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
          className="h-full w-full object-cover"
        />
      ) : (
        <p className="px-5 text-center text-xs text-muted-foreground">{NO_SCREENSHOT}</p>
      )}
      <span className="absolute bottom-2 left-2 rounded-sm bg-black/60 px-1.5 py-0.5 font-mono text-[11px] tabular-nums text-foreground">
        {offsetChipLabel(item)}
      </span>
    </div>
  )

  const media = (
    <div className="flex flex-col gap-2.5">
      {frame}
      {expanded && affordance.kind === 'replay' && (
        <ReplayPlayer
          meetingId={item.meetingId}
          startMs={item.startMs}
          label={`Recording of ${title} at ${offset}`}
          className="w-full rounded-md border border-border bg-background"
        />
      )}
    </div>
  )

  const body = (
    <div className="flex min-w-0 flex-col">
      <div className="mt-3">
        <button
          type="button"
          onClick={onOpenMoment}
          data-testid={`moment-title-${item.momentId}`}
          className="cursor-pointer text-left text-[15px] leading-snug font-semibold hover:underline"
        >
          {title}
        </button>
        <div className="mt-0.5 font-mono text-xs tabular-nums text-muted-foreground">
          {cardMetaLabel(item)}
        </div>
      </div>
      <div className="my-3">
        <ReasonLine
          reasons={item.reasons}
          threads={item.threads}
          onSelectKind={onSelectKind}
          onOpenThread={onOpenThread}
        />
      </div>
      {item.preview?.trim() && (
        <p className="mb-3.5 text-sm leading-relaxed text-foreground/90">
          “{item.preview.trim()}”
        </p>
      )}
      <div className="mt-auto flex flex-wrap items-center gap-2">
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
          onClick={onOpenMoment}
          data-testid={`open-moment-${item.momentId}`}
          aria-label={`Open moment at ${offset} in ${title}`}
        >
          Open moment
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={onOpenMeeting}
          data-testid={`open-meeting-${item.momentId}`}
          aria-label={`Open meeting ${title}`}
        >
          Open meeting
        </Button>
        {affordance.kind === 'replay' && affordance.source !== null && (
          <SourceLinkAnchor link={affordance.source} testId={`source-${item.momentId}`} />
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
    </div>
  )

  return (
    <article
      data-testid={`moment-card-${item.momentId}`}
      className={cn(
        'rounded-lg border border-border bg-card p-4 transition-colors hover:border-white/20',
        // Expanded: the card spans the grid and lays media beside the body, so
        // the player is large without pushing the reason line off screen.
        expanded && 'col-span-full grid gap-6 lg:grid-cols-[1.15fr_1fr]',
      )}
    >
      {media}
      {body}
    </article>
  )
}
