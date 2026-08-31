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

export type KeyState = 'present' | 'missing' | 'invalid' | 'not-required' | 'unknown'

/**
 * One configured provider's key validity (story 8.2a, FR39).
 *
 * Served whether or not a role binds the provider today, because the question
 * it answers — "is my key good" — is asked before anything is selected.
 */
export interface ProviderStatus {
  provider: string
  keyState: KeyState
  detail: string
  remediation: string | null
  state: ComponentState
  /** The process whose `.env` and `config.yaml` snapshot produced this. */
  observedBy: string
}

/** How the binding in force was arrived at, as `GET /status` resolves it. */
export type RoleBindingSource = 'selection' | 'file-default' | 'unknown'

export interface LlmRoleStatus {
  role: string
  /**
   * The binding **in force**, not the file's `model` field — a stored
   * selection may name a different provider entirely, and `fileBinding` /
   * `defaultBinding` carry the file half beside it rather than in its place.
   */
  model: string
  fallback: string | null
  provider: string | null
  keyState: KeyState
  state: ComponentState
  detail: string
  remediation: string | null
  source: RoleBindingSource
  defaultBinding: string
  fileBinding: string
  selected: string | null
  staleSelection: string | null
  staleReason: string | null
  observedBy: string
  /** The process that actually issues this role's calls, when it is known. */
  servedBy: string | null
  /** What this row's reading covers, and what it does not. Server-authored. */
  attribution: string
}

/**
 * Whose reading the payload is (AD-10 as amended 2026-08-31, AD-18).
 *
 * The catalog and every role binding are a snapshot the answering process took
 * at startup, while a selection is read per request — so a status payload
 * describes *one process*, never "the system". The worker holds its own
 * snapshot the api cannot observe, which is how, on 2026-08-31, this endpoint
 * reported local extraction while the worker was calling a paid provider.
 * These fields exist so no surface can render that reading unattributed.
 */
export interface ObservedBy {
  process: string
  configPath: string
  configLoadedAt: string | null
  catalogNote: string
  selectionNote: string
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
  observedBy: ObservedBy
  api: ComponentStatus
  stores: Array<ComponentStatus>
  providers: Array<ProviderStatus>
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
  // Providers before roles: a bad key is one fact that explains every role row
  // bound to it, and the indicator's summary reads top down.
  for (const provider of status.providers) {
    if (provider.state === 'degraded') {
      rows.push({
        id: `provider.${provider.provider}`,
        detail: provider.detail,
        remediation: provider.remediation,
      })
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

/**
 * The one sentence a surface may not omit when it shows a binding or a key
 * state: which process produced the reading, and out of which file.
 *
 * A summary that renders only degraded rows still renders this, because the
 * failure it guards against is not an unrendered row — it is a rendered row
 * read as a statement about the system. The api and the worker hold
 * independent `config.yaml` snapshots, and this page can only speak for the
 * one that answered (AD-10 as amended 2026-08-31, AD-18).
 */
export function attributionLine(status: SystemStatus): string {
  const observed = status.observedBy
  const loaded =
    observed.configLoadedAt === null
      ? 'at startup'
      : `at ${new Date(observed.configLoadedAt).toLocaleString()}`
  return (
    `Read by the ${observed.process} process, from ${observed.configPath} as it ` +
    `loaded that file ${loaded}. Bindings and key states below describe this ` +
    `process only — the worker holds its own snapshot this page cannot observe.`
  )
}

/**
 * How the binding in force was arrived at, for a role row on the page.
 *
 * The server already authored the full sentence into `detail`; this is the
 * short badge beside the binding, and it never invents a state the payload
 * does not carry — `unknown` says the selection could not be read rather than
 * falling back to the file default's wording.
 */
export function sourceLabel(row: LlmRoleStatus): string {
  switch (row.source) {
    case 'selection':
      return `in force by your selection (file default: ${row.defaultBinding})`
    case 'file-default':
      return row.staleSelection === null
        ? 'in force by the config.yaml default'
        : `in force by the config.yaml default — your choice ${row.staleSelection} was not applied`
    case 'unknown':
      return 'the binding in force could not be read'
  }
}
