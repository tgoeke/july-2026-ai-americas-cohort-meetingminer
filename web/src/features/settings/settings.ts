import type { ConfigResponse } from '@/client/types.gen'

/**
 * Pure helpers for the read-only configuration page (SPEC-ui-reimagine
 * CAP-3). Same split as `features/status/status.ts`: everything worth
 * testing without rendering lives here, the component stays about state
 * and layout.
 *
 * The page renders `GET /config` — ui-1's sanitized allowlist projection of
 * `Settings` — and nothing else. It never offers an edit affordance:
 * configuration is a file contract (`config.yaml` + restart), and every
 * section says so.
 */

/** One config read must not hang the page; the payload is tiny. */
export const CONFIG_TIMEOUT_MS = 8_000

export type ConfigLoad =
  | { kind: 'loading' }
  | { kind: 'loaded'; config: ConfigResponse }
  | { kind: 'failed'; message: string }

/**
 * The page-level read-only contract, stated once in the chrome of the page.
 * Mirrors `REMEDIATION_IS_A_FILE_EDIT` on the status page — status is live
 * health, this page is the declared stack.
 */
export const READ_ONLY_CONTRACT =
  'This page is read-only. Changing anything here is a file edit — ' +
  'config.yaml — plus a restart of the affected process; there is no edit ' +
  'control and never will be.'

/**
 * One section's change path. `projections.*` edits additionally need
 * `make rebuild` because the stores were projected under the old values.
 */
export function changePath(
  restart: 'the api (`make api`)' | 'the worker (`make worker`)' | 'the api and the worker (`make api`, `make worker`)',
  options: { rebuild?: boolean } = {},
): string {
  const base = `To change: edit config.yaml, then restart ${restart}.`
  return options.rebuild
    ? `${base} projections.* edits additionally need \`make rebuild\` — the stores were projected under the old values.`
    : base
}

/**
 * Key names that would mean a secret leaked into the sanitized payload or
 * onto the page. The endpoint is an allowlist projection precisely so none
 * of these can appear; the web test asserts it against both the payload
 * fixture and the rendered document. Lower-case with separators stripped —
 * `matchSecretMarker` normalizes its input the same way, so `api_key`,
 * `apiKey`, and `API-KEY` all match `apikey`.
 */
export const SECRET_KEY_MARKERS = [
  'apikey',
  'api_key',
  'openai_api_key',
  'anthropic_api_key',
  'meili_master_key',
  'masterkey',
  'password',
  'secret',
  'access_token',
  'authtoken',
  'credential',
] as const

/**
 * The first secret marker found in `text`, or null. Case-insensitive and
 * separator-insensitive (`_` and `-` removed) so a camelCase serialization
 * of a snake_case key still trips it.
 */
export function matchSecretMarker(text: string): string | null {
  const folded = text.toLowerCase().replace(/[_-]/g, '')
  for (const marker of SECRET_KEY_MARKERS) {
    if (folded.includes(marker.replace(/[_-]/g, ''))) return marker
  }
  return null
}

/** `pixelDiffThreshold` → `pixel diff threshold`, for threshold tables. */
export function labelize(key: string): string {
  return key.replace(/([a-z0-9])([A-Z])/g, '$1 $2').toLowerCase()
}

/** One scalar or array config value, rendered as text. */
export function formatValue(value: unknown): string {
  if (Array.isArray(value)) return value.map((entry) => String(entry)).join(', ')
  return String(value)
}
