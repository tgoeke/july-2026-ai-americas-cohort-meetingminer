import type {
  CatalogEntryView,
  ModelSettingsResponse,
  RoleSelectionView,
  StatusResponse,
} from '@/client/types.gen'

/**
 * Pure helpers for the model picker (story 8.3, FR38, UX-DR15).
 *
 * Same split as `settings.ts` and `features/status/status.ts`: everything
 * worth testing without rendering lives here, the components stay about state
 * and layout.
 *
 * Two payloads meet in this module and nothing else joins them:
 *
 * * `GET /settings/models` (story 8.2) — per role, the catalog a user may
 *   choose from, the binding actually in force, and where it came from. Every
 *   entry's `provider` was derived server-side by the one spelling rule
 *   (`server/meetingminer/domain/model_providers.py`), so this file reads that
 *   field and never re-derives or hand-writes a provider for a binding.
 * * `GET /status` — each configured role's provider health: `keyState`,
 *   `state`, and the remediation sentence in the api's own words.
 *
 * The judge role is deliberately absent from `GET /settings/models` (owner
 * decision, story 8.2: it is file-only until a later story wires it, and a
 * `PUT` on it is refused by name). Nothing here adds a role the payload did
 * not carry — `rolesOf()` returns exactly what the api served.
 */

/** One model read must not hang the ask box; the payload is tiny. */
export const MODEL_SETTINGS_TIMEOUT_MS = 8_000

/** The role the ask box binds. Settings offers every role the api serves. */
export const ASK_BOX_ROLE = 'chat'

/**
 * What a reader is entitled to conclude about where a binding runs and what it
 * costs, keyed by the provider id the server derived.
 *
 * This is the picker's whole reason for existing: the difference between
 * `ollama/gpt-oss:120b` and `openai/gpt-5.2` is a machine in the next room
 * versus a metered remote API, and the screen must make that legible without
 * a human ever typing a label next to a binding. The table is keyed on
 * provider — the one identity the server derives — so a new catalog entry
 * inherits its provider's traits automatically, and a provider nobody has
 * classified yields NO claim rather than a wrong one.
 *
 * The four keys are `config.yaml`'s `llm.providers`. `ollama` is the only
 * local one; every other configured provider is a remote, paid API.
 */
const PROVIDER_TRAITS: Record<string, { locality: 'local'; cost: 'free' } | { locality: 'remote'; cost: 'paid' }> = {
  ollama: { locality: 'local', cost: 'free' },
  openai: { locality: 'remote', cost: 'paid' },
  anthropic: { locality: 'remote', cost: 'paid' },
  openrouter: { locality: 'remote', cost: 'paid' },
}

export interface ProviderTrait {
  locality: 'local' | 'remote' | 'unknown'
  cost: 'free' | 'paid' | 'unknown'
  /** The words shown beside a binding. Never hand-written per entry. */
  sentence: string
}

/**
 * Where a provider runs and what it costs — or an explicit refusal to say.
 *
 * An unclassified or absent provider returns `unknown/unknown` and a sentence
 * that says so: claiming "local · free" for a spelling this file does not
 * recognise is exactly the misleading label the story forbids.
 */
export function providerTrait(provider: string | null | undefined): ProviderTrait {
  const known = provider != null ? PROVIDER_TRAITS[provider] : undefined
  if (known === undefined) {
    return {
      locality: 'unknown',
      cost: 'unknown',
      sentence: 'where it runs and what it costs are not known here',
    }
  }
  return {
    locality: known.locality,
    cost: known.cost,
    sentence: `${known.locality} · ${known.cost}`,
  }
}

/**
 * The health word beside an option.
 *
 * `unknown` is a first-class outcome, not a default of convenience: when
 * `GET /status` could not be read, or no configured role names this provider,
 * the picker says so rather than drawing a green dot it cannot support.
 */
export type HealthWord = 'ok' | 'invalid' | 'missing' | 'unreachable' | 'unknown'

export interface ProviderHealth {
  word: HealthWord
  /** The api's own remediation sentence, or `null` when nothing is wrong. */
  remediation: string | null
}

export const UNKNOWN_HEALTH: ProviderHealth = { word: 'unknown', remediation: null }

/** Worse states win when several role rows name one provider. */
const SEVERITY: Record<HealthWord, number> = {
  invalid: 4,
  missing: 4,
  unreachable: 3,
  ok: 1,
  unknown: 0,
}

/**
 * One `GET /status` LLM-role row, reduced to the provider-level question the
 * picker asks: can a call on this provider succeed right now?
 *
 * `keyState` is a property of the provider's credential, not of the role, so
 * `invalid`/`missing` transfer to every option on that provider. A `present`
 * or `not-required` key that is nonetheless `degraded` means the endpoint did
 * not answer — `unreachable`, which is a genuine failed binding too.
 */
export function healthOfRoleRow(row: {
  keyState: StatusResponse['llmRoles'][number]['keyState']
  state: 'ok' | 'degraded'
  remediation?: string | null
}): ProviderHealth {
  const remediation = row.remediation ?? null
  if (row.keyState === 'invalid') return { word: 'invalid', remediation }
  if (row.keyState === 'missing') return { word: 'missing', remediation }
  if (row.state === 'ok') return { word: 'ok', remediation: null }
  return { word: 'unreachable', remediation }
}

/**
 * Provider id → health, built from `GET /status.llmRoles[]`.
 *
 * Joined by exact provider id, as the design specifies. Story 8.2a will serve
 * `providers[]` directly; until it lands, the role rows are the only place the
 * api reports key state, and the worst row for a provider is the honest answer
 * for every option on it. A row whose `provider` is `null` (a spelling the one
 * rule cannot identify) joins to nothing and is skipped.
 */
export function providerHealthIndex(status: StatusResponse | null): Map<string, ProviderHealth> {
  const index = new Map<string, ProviderHealth>()
  if (status === null) return index
  for (const row of status.llmRoles) {
    if (row.provider == null) continue
    const health = healthOfRoleRow(row)
    const current = index.get(row.provider)
    if (current === undefined || SEVERITY[health.word] > SEVERITY[current.word]) {
      index.set(row.provider, health)
    }
  }
  return index
}

/** This provider's health, or an explicit `unknown` — never an assumed `ok`. */
export function healthFor(
  index: Map<string, ProviderHealth>,
  provider: string | null,
): ProviderHealth {
  if (provider == null) return UNKNOWN_HEALTH
  return index.get(provider) ?? UNKNOWN_HEALTH
}

/**
 * Whether an option renders muted.
 *
 * Muted means "choosing this will fail, and here is why" — it never means
 * disabled and never means hidden. The failure has to surface where it
 * happens: a picker that filtered a broken binding out would leave the reader
 * unable to see, or fix, what is actually wrong (DESIGN.md § model-select).
 */
export function isFailedHealth(word: HealthWord): boolean {
  return word === 'invalid' || word === 'missing' || word === 'unreachable'
}

/** One catalog entry, as a row renders it. */
export interface ModelOption {
  binding: string
  label: string
  provider: string | null
  trait: ProviderTrait
  health: ProviderHealth
  /** The binding actually in force for this role — drawn as ✓. */
  active: boolean
  /** Provider unavailable: muted, still selectable, remediation shown. */
  muted: boolean
}

/** The catalog in the api's order, annotated — never filtered, never sorted. */
export function optionsFor(
  role: RoleSelectionView,
  index: Map<string, ProviderHealth>,
): Array<ModelOption> {
  return role.catalog.map((entry: CatalogEntryView) => {
    const health = healthFor(index, entry.provider)
    return {
      binding: entry.binding,
      label: entry.label,
      provider: entry.provider,
      trait: providerTrait(entry.provider),
      health,
      active: entry.binding === role.effectiveBinding,
      muted: isFailedHealth(health.word),
    }
  })
}

/**
 * Every role the api serves, in its order. Judge is not among them.
 *
 * The array guard is not ceremony: `roles` is the whole payload, and a body
 * that is not this shape (a proxy error page, a stubbed fetch) must render as
 * "no role is offered" rather than throwing inside the picker and taking the
 * surface that mounts it down with it.
 */
export function rolesOf(payload: ModelSettingsResponse): Array<RoleSelectionView> {
  return Array.isArray(payload.roles) ? payload.roles : []
}

/** One role's view, or `null` when the api does not offer it for selection. */
export function roleNamed(
  payload: ModelSettingsResponse,
  role: string,
): RoleSelectionView | null {
  return rolesOf(payload).find((entry) => entry.role === role) ?? null
}

/**
 * The trigger's visible text: `chat · openai/gpt-5.2 · openai ● invalid`.
 *
 * The binding is shown in full rather than a friendly name alone, because the
 * whole point is that the reader can see which model the next question will
 * actually call.
 */
export function triggerParts(
  role: RoleSelectionView,
  health: ProviderHealth,
): { role: string; binding: string; provider: string; health: HealthWord } {
  return {
    role: role.role,
    binding: role.effectiveBinding,
    provider: role.provider ?? 'provider not identified',
    health: health.word,
  }
}

/**
 * The trigger's accessible name. Includes the health word (the `●` is hidden
 * from assistive technology) and the locality/cost sentence, so a screen
 * reader hears exactly what the sighted reader sees.
 */
export function triggerAccessibleName(
  role: RoleSelectionView,
  health: ProviderHealth,
): string {
  const parts = triggerParts(role, health)
  const trait = providerTrait(role.provider)
  return (
    `Model bound to the ${parts.role} role: ${parts.binding} — ` +
    `${parts.provider}, ${trait.sentence}, health ${parts.health}. ` +
    'Choose a different model.'
  )
}

/** One option's accessible description: its traits and, if broken, the fix. */
export function optionAccessibleDescription(option: ModelOption): string {
  const head = `${option.provider ?? 'provider not identified'}, ${option.trait.sentence}, health ${option.health.word}`
  return option.health.remediation === null ? head : `${head}; ${option.health.remediation}`
}

/**
 * Shown when a role's catalog is empty. No default is invented and no
 * substitute is offered — the file is the only place a binding comes from.
 */
export const NO_MODELS_CONFIGURED =
  'No models configured — add a binding to this role’s catalog in config.yaml and restart the api.'

/**
 * Why the stored choice is not the binding in force.
 *
 * `GET /settings/models` reports a selection the catalog no longer offers
 * rather than applying it, and this sentence carries that to the reader:
 * a discarded choice is never silent (story 8.2, "nothing degrades quietly").
 */
export function staleSelectionNotice(role: RoleSelectionView): string | null {
  if (role.staleSelection == null) return null
  const reason = role.staleReason ?? 'it is no longer in this role’s catalog'
  return (
    `Your previous choice ${role.staleSelection} is not in force: ${reason}. ` +
    `${role.role} is running on the file default ${role.default}.`
  )
}

/**
 * How the binding in force was arrived at, said plainly.
 *
 * The two halves reach the api by different mechanisms and the difference is
 * visible to the reader, so the picker states it rather than blurring it:
 *
 * * A **selection** is a Postgres `app_setting` row (story 8.2), read per
 *   request. Choosing a model applies immediately — the next call uses it,
 *   with no restart. This surface therefore carries no restart language on
 *   the selection path, because there is nothing to restart.
 * * A **file default** is `config.yaml` as the api read it *at startup*
 *   (`api/main.py` loads the configuration at module level). Nothing here
 *   edits that file, and an inherited default is reported as inherited — never
 *   dressed up as a deliberate choice.
 */
export function sourceNotice(role: RoleSelectionView): string {
  if (role.source === 'selection') {
    return `In force by your selection — applied immediately; the next ${role.role} call uses it.`
  }
  return (
    `Inherited from the file default in config.yaml (${role.default}) — ` +
    `no choice is stored for ${role.role}.`
  )
}

/**
 * Stated once on the Settings surface, because the two halves of this screen
 * change by different means: the choice is live, the list of choices is not.
 */
export const CATALOG_IS_A_STARTUP_SNAPSHOT =
  'The catalog is config.yaml as the api read it at startup: adding or ' +
  'removing a binding is a file edit plus an api restart. Choosing one of ' +
  'the bindings below is not — it is stored by the api and takes effect on ' +
  'the next call.'

/**
 * What the picker says when the api refused, or never answered, a choice.
 *
 * The binding in force is restated in the same breath, because the one thing
 * a reader must never have to guess after a failed selection is which model
 * the next question will call. No other model is ever put in its place.
 */
export function selectionRefusal(role: RoleSelectionView, message: string): string {
  return (
    `The api did not accept ${role.role} on that binding: ${message}. ` +
    `${role.role} is still bound to ${role.effectiveBinding} — nothing was substituted.`
  )
}
