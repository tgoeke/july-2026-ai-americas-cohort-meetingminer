import { useCallback, useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { BAR_CLASS, LABEL_CLASS } from '@/features/meetings/stageStyles'
import { cn } from '@/lib/utils'
import type { Step } from './acquisitions'

export interface AcquisitionStepperProps {
  steps: Array<Step>
  /** `GET /acquisitions/{id}`'s bounded tail. Empty means nothing logged yet. */
  logTail: Array<string>
}

/**
 * The acquisition's four checkpoints, then the log the tool actually wrote.
 *
 * The bars are `stageStyles`' own classes — the same values the meeting card's
 * stage bars use — because `DESIGN.md` · Colors · States extends those exact
 * state tokens to the acquisition machine rather than inventing a second
 * palette for it. Each step is `role="img"` named `<step> <state>`, so the
 * state is available to a screen reader and is never carried by colour alone
 * (EXPERIENCE.md:212).
 *
 * The log is diagnostic and nothing else reads it: the refusal fields are
 * complete on their own (story 6.4), so no failure on this screen is ever
 * parsed out of these lines. It is `aria-live="off"` because it is noise, and
 * it follows new lines only while the reader is already at the bottom —
 * scrolling up to read something pauses the follow until they return.
 */
export function AcquisitionStepper({ steps, logTail }: AcquisitionStepperProps) {
  const logRef = useRef<HTMLDivElement | null>(null)
  // Starts true: a log region that has never been scrolled is at its bottom.
  const followRef = useRef(true)
  const [copied, setCopied] = useState(false)

  const onScroll = useCallback(() => {
    const node = logRef.current
    if (node === null) return
    // A 4px tolerance: sub-pixel layout and zoom leave a fractional remainder
    // at a genuine bottom, and an exact comparison would silently stop
    // following.
    followRef.current = node.scrollHeight - node.scrollTop - node.clientHeight <= 4
  }, [])

  useEffect(() => {
    const node = logRef.current
    if (node === null || !followRef.current) return
    node.scrollTop = node.scrollHeight
  }, [logTail])

  const copy = useCallback(() => {
    // `navigator.clipboard` is absent in jsdom and on an insecure origin. The
    // button reports what happened rather than throwing into the console.
    void navigator.clipboard
      ?.writeText(logTail.join('\n'))
      .then(() => setCopied(true))
      .catch(() => setCopied(false))
  }, [logTail])

  return (
    <div className="flex flex-col gap-3" data-testid="acquisition-stepper">
      <ol className="flex items-end gap-2" aria-label="acquisition progress">
        {steps.map((step) => (
          <li
            key={step.name}
            data-testid={`step-${step.name}`}
            data-status={step.status}
            role="img"
            aria-label={`${step.label} ${step.status}`}
            className="flex min-w-0 flex-1 flex-col items-stretch gap-1"
          >
            <span className={cn('h-1.5 w-full rounded-sm', BAR_CLASS[step.status])} />
            <span className={cn('truncate text-xs leading-none', LABEL_CLASS[step.status])}>
              {step.label}
            </span>
          </li>
        ))}
      </ol>

      {logTail.length > 0 && (
        <div className="flex flex-col gap-2">
          <div
            ref={logRef}
            onScroll={onScroll}
            role="region"
            aria-label="acquisition log"
            aria-live="off"
            data-testid="acquisition-log"
            className="max-h-40 overflow-y-auto rounded-md bg-muted/40 p-3 font-mono text-xs leading-relaxed text-muted-foreground"
          >
            {logTail.map((line, index) => (
              // The tail is a bounded window of a text file with no ids of its
              // own, and identical lines repeat legitimately, so position is
              // the only key available.
              <div key={`${index}-${line}`}>{line}</div>
            ))}
          </div>
          <div className="flex items-center gap-3">
            <Button size="sm" variant="outline" onClick={copy}>
              Copy log
            </Button>
            {copied && (
              <span className="text-xs text-muted-foreground" data-testid="log-copied">
                Copied {logTail.length} lines.
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
