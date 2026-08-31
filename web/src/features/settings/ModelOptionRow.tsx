import type { HealthWord, ModelOption, ProviderHealth } from './models'

/**
 * The parts every model option draws, on both surfaces (story 8.3).
 *
 * The ask box's popover and the Settings page's per-role lists differ in how
 * they are opened and focused, not in what a row says — so the row lives here
 * once. Anything a reader could use to decide *what will be called* comes from
 * the payload: `label` and `binding` from the catalog, `provider` derived
 * server-side by the one spelling rule, locality and cost derived from that
 * provider, health joined from `GET /status`.
 */

/** Muted grey, destructive red, or the body colour — health decides. */
function healthClass(word: HealthWord): string {
  if (word === 'ok') return 'text-foreground'
  if (word === 'unknown') return 'text-muted-foreground'
  return 'text-destructive'
}

/**
 * Dot plus word, never the dot alone (EXPERIENCE.md § Health dot). The `●` is
 * `aria-hidden`: it carries no information the word does not.
 */
export function HealthBadge({ health, testId }: { health: ProviderHealth; testId?: string }) {
  return (
    <span
      data-testid={testId}
      className={`flex shrink-0 items-center gap-1 text-xs ${healthClass(health.word)}`}
    >
      <span aria-hidden="true">●</span>
      <span>{health.word}</span>
    </span>
  )
}

/**
 * One option's content: name, exact binding, where it runs and what it costs,
 * and its provider's health — plus the remediation when something is wrong.
 *
 * A failed option is muted and keeps every one of these parts. It is never
 * disabled and never removed: the failure has to surface where it happens, and
 * a reader who cannot see the broken binding cannot fix it (DESIGN.md
 * § Components › model-select).
 */
export function OptionBody({ option }: { option: ModelOption }) {
  return (
    <>
      <span aria-hidden="true" className="w-4 shrink-0 text-center">
        {option.active ? '✓' : ''}
      </span>
      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className={`text-sm ${option.muted ? 'text-muted-foreground' : ''}`}>
          {option.label}
          <code className="ml-2 break-all font-mono text-xs text-muted-foreground">
            {option.binding}
          </code>
        </span>
        <span className="text-xs text-muted-foreground">
          {option.provider ?? 'provider not identified'} · {option.trait.sentence}
        </span>
        {option.health.remediation !== null && (
          <span
            data-testid={`model-option-remediation-${option.binding}`}
            className="text-xs text-muted-foreground"
          >
            → {option.health.remediation}
          </span>
        )}
      </span>
      <HealthBadge health={option.health} testId={`model-option-health-${option.binding}`} />
    </>
  )
}
