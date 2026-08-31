import type { RoleSelectionView } from '@/client/types.gen'
import { API_BASE } from '@/lib/api'
import { OptionBody } from './ModelOptionRow'
import {
  CATALOG_IS_A_STARTUP_SNAPSHOT,
  EFFECTIVE_BINDING_IS_SNAPSHOTTED,
  NO_MODELS_CONFIGURED,
  optionAccessibleDescription,
  optionAccessibleName,
  optionsFor,
  rolesOf,
  sourceNotice,
  staleSelectionNotice,
  type ProviderHealth,
} from './models'
import { useModelSettings } from './useModelSettings'

/**
 * The Settings page's model picker (story 8.3): every role the api offers for
 * selection, each with its catalog, the binding in force marked ✓, and each
 * entry's provider, locality, cost and health.
 *
 * This is the one editable thing on an otherwise read-only page
 * (EXPERIENCE.md § Settings). It is editable because it is not a file edit:
 * a choice is stored by the api and read per request, so it applies to the
 * next call. Every other value on this page remains a `config.yaml` edit plus
 * a restart, and says so.
 *
 * The roles rendered are exactly the roles `GET /settings/models` serves. The
 * judge is not among them — it is file-only until a later story wires it, and
 * a `PUT` on it is refused by name (owner decision, story 8.2) — and nothing
 * here adds it back.
 */

function RoleBlock({
  role,
  health,
  pending,
  failure,
  onSelect,
}: {
  role: RoleSelectionView
  health: Map<string, ProviderHealth>
  pending: string | undefined
  failure: string | undefined
  onSelect: (role: RoleSelectionView, binding: string) => void
}) {
  const options = optionsFor(role, health)
  const stale = staleSelectionNotice(role)
  return (
    <div className="flex flex-col gap-2 rounded-md border p-3">
      <span className="font-medium">
        <code>llm.roles.{role.role}</code>
      </span>

      {options.length === 0 ? (
        <p data-testid={`model-roles-empty-${role.role}`} className="text-sm text-muted-foreground">
          {NO_MODELS_CONFIGURED}
        </p>
      ) : (
        <div
          role="listbox"
          aria-label={`Model bound to the ${role.role} role`}
          aria-busy={pending !== undefined}
          data-testid={`model-roles-listbox-${role.role}`}
          className="flex flex-col gap-1"
        >
          {options.map((option) => (
            <button
              key={option.binding}
              type="button"
              role="option"
              aria-selected={option.active}
              aria-label={optionAccessibleName(option)}
              aria-description={optionAccessibleDescription(option)}
              data-testid={`model-roles-option-${role.role}-${option.binding}`}
              // Never `aria-disabled`: a failed binding stays selectable so the
              // failure surfaces at the call, loudly, instead of being
              // filtered out of the list.
              onClick={() => onSelect(role, option.binding)}
              className="flex w-full items-start gap-2 rounded-sm p-1.5 text-left hover:bg-muted"
            >
              <OptionBody option={option} />
            </button>
          ))}
        </div>
      )}

      <p data-testid={`model-roles-source-${role.role}`} className="text-xs text-muted-foreground">
        {sourceNotice(role)}
      </p>

      {pending !== undefined && (
        <p data-testid={`model-roles-pending-${role.role}`} className="text-xs text-muted-foreground">
          binding {role.role} to {pending}…
        </p>
      )}

      {stale !== null && (
        <p data-testid={`model-roles-stale-${role.role}`} className="text-xs text-muted-foreground">
          {stale}
        </p>
      )}

      {failure !== undefined && (
        <p
          role="alert"
          data-testid={`model-roles-refusal-${role.role}`}
          className="rounded-md border border-destructive/40 p-2 text-xs text-destructive"
        >
          {failure}
        </p>
      )}
    </div>
  )
}

export function ModelRoles() {
  const { load, health, pending, failure, select } = useModelSettings()

  if (load.kind === 'loading') {
    return (
      <p data-testid="model-roles-loading" className="text-sm text-muted-foreground">
        reading the model catalog…
      </p>
    )
  }

  if (load.kind === 'failed') {
    return (
      <div data-testid="model-roles-unavailable" className="flex flex-col gap-1">
        <p className="text-sm text-destructive">
          cannot read the model catalog from {API_BASE}: {load.message}
        </p>
        <p className="text-sm">
          → start the api (`make api` or `make up`) and check it is listening at {API_BASE}
        </p>
      </div>
    )
  }

  const roles = rolesOf(load.payload)

  return (
    <div className="flex flex-col gap-3">
      <p className="text-xs text-muted-foreground">{CATALOG_IS_A_STARTUP_SNAPSHOT}</p>
      <p className="text-xs text-muted-foreground">{EFFECTIVE_BINDING_IS_SNAPSHOTTED}</p>
      {roles.length === 0 ? (
        <p data-testid="model-roles-none" className="text-sm text-muted-foreground">
          No role is offered for selection.
        </p>
      ) : (
        roles.map((role) => (
          <RoleBlock
            key={role.role}
            role={role}
            health={health}
            pending={pending[role.role]}
            failure={failure[role.role]}
            onSelect={(target, binding) => void select(target, binding)}
          />
        ))
      )}
    </div>
  )
}
