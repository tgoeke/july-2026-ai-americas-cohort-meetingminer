import type { ReactNode } from 'react'
import type { Refusal } from './acquisitions'

export interface RefusalBoxProps {
  refusal: Refusal
  /** Distinguishes the boxes on one screen for tests and for `aria-describedby`. */
  testId: string
  /** An action the refusal offers — the 409's "Open the running acquisition". */
  action?: ReactNode
}

/**
 * One refusal, in place, in the api's own words.
 *
 * `DESIGN.md` · Component Patterns · refusal-box: a rose tint with a rose
 * border, the rule name first in mono, then the detail, then `→ remediation`
 * in muted text. `role="alert"` and inserted into the DOM on appearance, so a
 * screen reader hears the rule first while the trigger keeps focus
 * (EXPERIENCE.md:99).
 *
 * Never a toast, and never paraphrased: every string here came off the wire.
 * A refusal with no remediation renders no arrow line rather than an invented
 * suggestion.
 */
export function RefusalBox({ refusal, testId, action }: RefusalBoxProps) {
  return (
    <div
      role="alert"
      data-testid={testId}
      className="flex flex-col gap-1 rounded-md border border-rose-600/60 bg-rose-600/10 px-4 py-3"
    >
      <p className="font-mono text-sm font-medium text-rose-700 dark:text-rose-400">
        {refusal.rule}
      </p>
      <p className="text-sm">{refusal.detail}</p>
      {refusal.remediation !== null && (
        <p className="text-sm text-muted-foreground">
          <span aria-hidden="true">→ </span>
          {refusal.remediation}
        </p>
      )}
      {action !== undefined && <div className="pt-1">{action}</div>}
    </div>
  )
}

/**
 * The api could not be reached. Deliberately not a `RefusalBox`: nothing
 * refused anything, and dressing an outage as a rule refusal would blame the
 * source for the network. It carries a Retry, which a refusal never does.
 */
export function TransportNotice({
  message,
  onRetry,
  testId,
}: {
  message: string
  onRetry?: () => void
  testId: string
}) {
  return (
    <div
      role="alert"
      data-testid={testId}
      className="flex flex-wrap items-center gap-3 rounded-md border border-destructive/40 px-4 py-3 text-sm text-destructive"
    >
      <span>{message}</span>
      {onRetry !== undefined && (
        <button
          type="button"
          onClick={onRetry}
          className="rounded-md border border-current px-2 py-0.5 text-xs font-medium"
        >
          Retry
        </button>
      )}
    </div>
  )
}
