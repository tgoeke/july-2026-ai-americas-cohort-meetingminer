/**
 * The five statuses `job_stage.status` may hold, plus `unknown`.
 *
 * `unknown` is not a database value — it is what a status this build does not
 * recognise renders as. Folding it into `queued` would draw a stage this
 * client cannot interpret as one it definitely can, which is the failure mode
 * `stage_sort_key` on the server deliberately avoids by sorting an unknown
 * stage *name* last rather than pretending it is a known one.
 */
export type StageStatus = 'queued' | 'running' | 'done' | 'skipped' | 'failed'
export type RenderedStageStatus = StageStatus | 'unknown'

const STATUSES: readonly StageStatus[] = ['queued', 'running', 'done', 'skipped', 'failed']

/** Narrow the api's plain `string` status; anything unrecognised renders as `unknown`. */
export function asStageStatus(status: string): RenderedStageStatus {
  return (STATUSES as readonly string[]).includes(status) ? (status as StageStatus) : 'unknown'
}

/**
 * Every status differs in fill *and* in texture, not in hue alone.
 *
 * `skipped` is the one that matters most: transcript-only drops are the common
 * case in this corpus, so five skipped stages must read as a legitimate path
 * rather than as damage. It gets its own hatched texture, distinct from the
 * solid block of `done` and from the solid red of `failed`. `unknown` is
 * loudly its own thing so a status this build cannot interpret is visible
 * rather than disguised.
 */
export const BAR_CLASS: Record<RenderedStageStatus, string> = {
  queued: 'bg-transparent border border-dashed border-muted-foreground/40',
  running: 'bg-amber-500 animate-pulse',
  done: 'bg-emerald-600',
  skipped:
    'border border-slate-400/60 bg-[repeating-linear-gradient(135deg,var(--color-slate-400)_0,var(--color-slate-400)_2px,transparent_2px,transparent_5px)]',
  failed: 'bg-rose-600',
  unknown: 'bg-fuchsia-600 border border-fuchsia-900',
}

export const LABEL_CLASS: Record<RenderedStageStatus, string> = {
  queued: 'text-muted-foreground/60',
  running: 'text-amber-700 dark:text-amber-400 font-medium',
  done: 'text-foreground',
  skipped: 'text-muted-foreground italic',
  failed: 'text-rose-700 dark:text-rose-400 font-medium',
  unknown: 'text-fuchsia-700 dark:text-fuchsia-400 font-medium',
}

/** `unknown` is deliberately absent: it is a defect indicator, not a state to advertise. */
export const STATUS_LEGEND: ReadonlyArray<[StageStatus, string]> = [
  ['queued', 'queued'],
  ['running', 'running'],
  ['done', 'done'],
  ['skipped', 'skipped (no recording)'],
  ['failed', 'failed'],
]
