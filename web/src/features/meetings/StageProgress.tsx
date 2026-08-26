import type { JobStage } from '@/client/types.gen'
import { cn } from '@/lib/utils'
import { BAR_CLASS, LABEL_CLASS, STATUS_LEGEND, asStageStatus } from './stageStyles'

export function StageLegend() {
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
      {STATUS_LEGEND.map(([status, label]) => (
        <li key={status} className="flex items-center gap-1.5">
          <span className={cn('h-1.5 w-6 rounded-sm', BAR_CLASS[status])} />
          {label}
        </li>
      ))}
    </ul>
  )
}

export interface StageProgressProps {
  stages: Array<JobStage>
}

/**
 * The eight checkpoints of one job, in pipeline order as the api returns them.
 *
 * A stage that failed shows its recorded error verbatim underneath — the
 * pipeline records failures precisely so they are not swallowed, and
 * paraphrasing one here would swallow it at the last step.
 */
export function StageProgress({ stages }: StageProgressProps) {
  const failed = stages.filter((stage) => stage.status === 'failed')

  return (
    <div className="flex flex-col gap-1.5">
      <ol className="flex items-end gap-1" aria-label="ingestion stages">
        {stages.map((stage) => {
          const status = asStageStatus(stage.status)
          // An unrecognised status keeps its raw text everywhere it is read,
          // so the thing this build could not interpret stays visible.
          const label = status === 'unknown' ? `unknown (${stage.status})` : status
          return (
            <li
              key={stage.name}
              data-testid={`stage-${stage.name}`}
              data-status={status}
              data-raw-status={stage.status}
              className="flex min-w-0 flex-1 flex-col items-stretch gap-1"
              title={`${stage.name}: ${label}${stage.error ? ` — ${stage.error}` : ''}`}
            >
              <span className={cn('h-1.5 w-full rounded-sm', BAR_CLASS[status])} />
              <span className={cn('truncate text-[10px] leading-none', LABEL_CLASS[status])}>
                {stage.name}
              </span>
              <span className="sr-only">{label}</span>
            </li>
          )
        })}
      </ol>
      {failed.map((stage) => (
        <p
          key={stage.name}
          data-testid={`stage-error-${stage.name}`}
          className="text-xs text-rose-700 dark:text-rose-400"
        >
          <span className="font-medium">{stage.name} failed:</span>{' '}
          <span className="font-mono">{stage.error ?? 'no error was recorded'}</span>
        </p>
      ))}
    </div>
  )
}
