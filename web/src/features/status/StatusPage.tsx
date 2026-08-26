import { API_BASE } from '@/lib/api'
import {
  API_UNREACHABLE_REMEDIATION,
  POLL_INTERVAL_MS,
  REMEDIATION_IS_A_FILE_EDIT,
  type ComponentStatus,
  type LlmRoleStatus,
  type SystemStatus,
} from './status'
import { useSystemStatus } from './useSystemStatus'

/**
 * The dedicated status page (CAP-1): every dependency the product needs, its
 * current state, and — for anything degraded — what is broken and what to do
 * about it, in the owner's own terms (CAP-2). Read-only by contract: the
 * remediation is always a file edit plus a restart, and the page says so.
 */

function stateBadge(state: 'ok' | 'degraded') {
  return state === 'ok' ? (
    <span className="text-green-600">ok</span>
  ) : (
    <span className="font-medium text-amber-600">degraded</span>
  )
}

function Row({ row }: { row: ComponentStatus }) {
  return (
    <li className="flex flex-col gap-0.5 rounded-md border p-3">
      <div className="flex items-baseline justify-between gap-4">
        <span className="font-medium">{row.label}</span>
        {stateBadge(row.state)}
      </div>
      <p className="text-sm text-muted-foreground">{row.detail}</p>
      {row.remediation != null && <p className="text-sm">→ {row.remediation}</p>}
    </li>
  )
}

function RoleRow({ row }: { row: LlmRoleStatus }) {
  return (
    <li className="flex flex-col gap-0.5 rounded-md border p-3">
      <div className="flex items-baseline justify-between gap-4">
        <span className="font-medium">
          <code>llm.roles.{row.role}</code>{' '}
          <span className="text-muted-foreground">({row.model})</span>
        </span>
        {stateBadge(row.state)}
      </div>
      <p className="text-sm text-muted-foreground">
        key: {row.keyState}
        {row.fallback != null && <> · fallback: {row.fallback}</>}
      </p>
      <p className="text-sm text-muted-foreground">{row.detail}</p>
      {row.remediation != null && <p className="text-sm">→ {row.remediation}</p>}
    </li>
  )
}

function backlogLine(counts: Record<string, number>): string {
  const entries = Object.entries(counts)
  if (entries.length === 0) return 'none'
  return entries.map(([name, count]) => `${name}: ${count}`).join(' · ')
}

function Loaded({ status }: { status: SystemStatus }) {
  const worker = status.worker
  return (
    <div className="flex flex-col gap-6">
      <p className="text-sm">
        Overall:{' '}
        {status.overall === 'ok' ? (
          <span className="text-green-600">everything healthy</span>
        ) : (
          <span className="font-medium text-amber-600">attention needed</span>
        )}
      </p>
      <section className="flex flex-col gap-2">
        <h3 className="text-sm font-medium text-muted-foreground">api</h3>
        <ul className="flex flex-col gap-2">
          <Row row={status.api} />
        </ul>
      </section>
      <section className="flex flex-col gap-2">
        <h3 className="text-sm font-medium text-muted-foreground">stores</h3>
        <ul className="flex flex-col gap-2">
          {status.stores.map((row) => (
            <Row key={row.id} row={row} />
          ))}
        </ul>
      </section>
      <section className="flex flex-col gap-2">
        <h3 className="text-sm font-medium text-muted-foreground">model bindings</h3>
        <ul className="flex flex-col gap-2">
          {status.llmRoles.map((row) => (
            <RoleRow key={row.role} row={row} />
          ))}
        </ul>
      </section>
      <section className="flex flex-col gap-2">
        <h3 className="text-sm font-medium text-muted-foreground">worker</h3>
        <div className="flex flex-col gap-0.5 rounded-md border p-3">
          <div className="flex items-baseline justify-between gap-4">
            <span className="font-medium">worker</span>
            {worker.state === 'running' ? (
              <span className="text-green-600">running</span>
            ) : (
              <span className="font-medium text-amber-600">{worker.state}</span>
            )}
          </div>
          <p className="text-sm text-muted-foreground">{worker.detail}</p>
          <p className="text-sm text-muted-foreground">
            jobs — {backlogLine(worker.jobs)}
          </p>
          <p className="text-sm text-muted-foreground">
            stage backlog — {backlogLine(worker.stageBacklog)}
          </p>
          {worker.remediation != null && (
            <p className="text-sm">→ {worker.remediation}</p>
          )}
        </div>
      </section>
    </div>
  )
}

export function StatusPage() {
  const poll = useSystemStatus()
  return (
    <section className="flex flex-col gap-4">
      <h2 className="text-xl font-semibold tracking-tight">System status</h2>
      {poll.kind === 'loading' && <p className="text-sm">checking…</p>}
      {poll.kind === 'unreachable' && (
        <div className="flex flex-col gap-1 rounded-md border p-3">
          <p className="text-sm text-destructive">
            cannot reach the api at {API_BASE}: {poll.message}
          </p>
          <p className="text-sm">→ {API_UNREACHABLE_REMEDIATION}</p>
        </div>
      )}
      {poll.kind === 'loaded' && <Loaded status={poll.status} />}
      <p className="text-xs text-muted-foreground">
        Refreshes every {POLL_INTERVAL_MS / 1000}s while open.{' '}
        {REMEDIATION_IS_A_FILE_EDIT}
      </p>
    </section>
  )
}
