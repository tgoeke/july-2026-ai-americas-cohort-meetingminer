/**
 * Types and fetch helper for `GET /status` (SPEC-system-status, CAP-1).
 *
 * Plain `fetch` against `API_BASE` rather than the generated client: the
 * client under `web/src/client/` is generated (`make client`) and this story
 * does not regenerate it. The shapes below mirror
 * `server/meetingminer/api/status.py` field for field.
 */
import { API_BASE } from '@/lib/api'

/**
 * How often the status surfaces re-poll while mounted. 15s: fast enough that
 * a dependency breaking (or being fixed) shows up while the owner is still
 * looking, slow enough to be no load at all — and the server caches provider
 * probes for 60s (`PROBE_TTL_SECONDS`), so polling faster than this could
 * never hammer a provider anyway.
 */
export const POLL_INTERVAL_MS = 15_000

/** One poll must not hang the surface that exists to report hangs. */
export const STATUS_TIMEOUT_MS = 5_000

export type ComponentState = 'ok' | 'degraded'

export interface ComponentStatus {
  id: string
  label: string
  state: ComponentState
  detail: string
  remediation: string | null
}

export type KeyState = 'present' | 'missing' | 'invalid' | 'not-required'

export interface LlmRoleStatus {
  role: string
  model: string
  fallback: string | null
  provider: string | null
  keyState: KeyState
  state: ComponentState
  detail: string
  remediation: string | null
}

export interface WorkerStatus {
  state: 'running' | 'stopped' | 'unknown'
  jobs: Record<string, number>
  stageBacklog: Record<string, number>
  detail: string
  remediation: string | null
}

export interface SystemStatus {
  generatedAt: string
  overall: ComponentState
  api: ComponentStatus
  stores: Array<ComponentStatus>
  llmRoles: Array<LlmRoleStatus>
  worker: WorkerStatus
}

/**
 * What one poll produced. `unreachable` is its own kind rather than a
 * degraded row: when the api itself is down there is no payload to render,
 * and the surface must say the api is the broken dependency (CAP-2) —
 * with the same file-edit-plus-restart remediation shape as every other row.
 */
export type StatusPoll =
  | { kind: 'loading' }
  | { kind: 'loaded'; status: SystemStatus }
  | { kind: 'unreachable'; message: string }

export async function fetchStatus(signal?: AbortSignal): Promise<SystemStatus> {
  const response = await fetch(`${API_BASE}/status`, { signal })
  if (!response.ok) {
    throw new Error(`the api answered HTTP ${response.status}`)
  }
  return (await response.json()) as SystemStatus
}

/** Every row that needs attention, flattened for the indicator's summary. */
export function degradedRows(
  status: SystemStatus,
): Array<{ id: string; detail: string; remediation: string | null }> {
  const rows: Array<{ id: string; detail: string; remediation: string | null }> = []
  for (const store of status.stores) {
    if (store.state === 'degraded') {
      rows.push({ id: store.id, detail: store.detail, remediation: store.remediation })
    }
  }
  for (const role of status.llmRoles) {
    if (role.state === 'degraded') {
      rows.push({
        id: `llm.roles.${role.role}`,
        detail: role.detail,
        remediation: role.remediation,
      })
    }
  }
  if (status.worker.state !== 'running') {
    rows.push({
      id: 'worker',
      detail: status.worker.detail,
      remediation: status.worker.remediation,
    })
  }
  return rows
}

export const REMEDIATION_IS_A_FILE_EDIT =
  'Fixes are file edits (.env / config.yaml) plus a restart of the affected ' +
  'process — this page only reports and never changes or starts anything.'

export const API_UNREACHABLE_REMEDIATION = `start the api (\`make api\` or \`make up\`) and check it is listening at ${API_BASE}`
