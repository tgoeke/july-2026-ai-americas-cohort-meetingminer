import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { API_BASE } from '@/lib/api'
import { OptionBody } from './ModelOptionRow'
import {
  ASK_BOX_ROLE,
  healthFor,
  NO_MODELS_CONFIGURED,
  optionAccessibleDescription,
  optionsFor,
  roleNamed,
  sourceNotice,
  staleSelectionNotice,
  triggerAccessibleName,
  triggerParts,
} from './models'
import { useModelSettings } from './useModelSettings'

/**
 * The ask box's model select (story 8.3, UX-DR15): a trigger that says which
 * model the next question will call, and a popover listing that role's catalog
 * with each entry's provider, locality, cost, and health.
 *
 * Mounted into `ChatPanel`'s control row as a single element — the ask box's
 * anatomy is unchanged, and the chrome around it belongs to story 10.5.
 *
 * What this component will not do:
 *
 * * **Never hide a broken binding.** An entry whose provider key is missing or
 *   invalid, or whose endpoint did not answer, renders muted with the api's
 *   remediation and stays selectable. Choosing it must fail loudly at the ask
 *   — where the failure actually is — rather than being filtered out here.
 * * **Never substitute.** A refused selection leaves the binding in force as
 *   the api last reported it, restated in the refusal sentence.
 * * **Never label by hand.** Every word beside a binding is derived: the
 *   provider by the server's one spelling rule, locality and cost from that
 *   provider, health from `GET /status`.
 */
export interface ModelSelectProps {
  /** The role this select binds. The ask box binds `chat`. */
  role?: string
}

export function ModelSelect({ role: roleName = ASK_BOX_ROLE }: ModelSelectProps = {}) {
  const { load, health, pending, failure, select } = useModelSettings()
  const [open, setOpen] = useState(false)
  const [activeIndex, setActiveIndex] = useState(0)
  const triggerRef = useRef<HTMLButtonElement | null>(null)
  const listRef = useRef<HTMLDivElement | null>(null)
  const containerRef = useRef<HTMLSpanElement | null>(null)

  const close = useCallback(() => {
    setOpen(false)
    triggerRef.current?.focus()
  }, [])

  // Focus moves into the list when it opens, so the arrow keys act on it
  // immediately; `Esc` returns focus to the trigger (EXPERIENCE.md § Popovers:
  // popovers trap nothing).
  useEffect(() => {
    if (open) listRef.current?.focus()
  }, [open])

  // A pointer down anywhere else dismisses it, the way every popover in the
  // product does. Focus is not forced back to the trigger here: the reader
  // aimed at something else, and stealing focus would fight that.
  useEffect(() => {
    if (!open) return
    const dismiss = (event: MouseEvent) => {
      const target = event.target
      if (target instanceof Node && containerRef.current?.contains(target)) return
      setOpen(false)
    }
    document.addEventListener('mousedown', dismiss)
    return () => document.removeEventListener('mousedown', dismiss)
  }, [open])

  if (load.kind === 'loading') {
    return (
      <span data-testid="model-select-loading" className="text-xs text-muted-foreground">
        reading the model catalog…
      </span>
    )
  }

  if (load.kind === 'failed') {
    // Named, not silent, and not fatal to the ask box: a question can still be
    // asked on whatever binding the api resolves server-side.
    return (
      <span data-testid="model-select-unavailable" className="text-xs text-muted-foreground">
        cannot read the model catalog from {API_BASE}: {load.message}
      </span>
    )
  }

  const role = roleNamed(load.payload, roleName)
  if (role === null) {
    // The api serves only the roles that genuinely adopt persisted selection —
    // the judge is file-only by owner decision (story 8.2) and never appears.
    // Saying so beats inventing a control that a `PUT` would refuse.
    return (
      <span data-testid="model-select-not-offered" className="text-xs text-muted-foreground">
        the {roleName} role is not offered for selection
      </span>
    )
  }

  const options = optionsFor(role, health)
  const activeHealth = healthFor(health, role.provider)
  const parts = triggerParts(role, activeHealth)
  const listboxId = `model-select-${role.role}-listbox`
  const optionId = (index: number) => `model-select-${role.role}-option-${index}`
  const stale = staleSelectionNotice(role)
  const refusal = failure[role.role]
  const busyBinding = pending[role.role]

  const choose = async (binding: string) => {
    await select(role, binding)
  }

  const onListKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (options.length === 0) return
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setActiveIndex((index) => (index + 1) % options.length)
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActiveIndex((index) => (index - 1 + options.length) % options.length)
    } else if (event.key === 'Home') {
      event.preventDefault()
      setActiveIndex(0)
    } else if (event.key === 'End') {
      event.preventDefault()
      setActiveIndex(options.length - 1)
    } else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      const option = options[activeIndex]
      if (option !== undefined) void choose(option.binding)
    } else if (event.key === 'Escape') {
      event.preventDefault()
      close()
    }
  }

  return (
    <span ref={containerRef} className="relative flex flex-col gap-1">
      <button
        ref={triggerRef}
        type="button"
        data-testid="model-select-trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listboxId : undefined}
        aria-disabled={options.length === 0 || undefined}
        aria-label={triggerAccessibleName(role, activeHealth)}
        className="flex items-center gap-2 rounded-md border px-2 py-1 text-xs"
        onClick={() => {
          // An empty catalog opens nothing: there is no choice to present, and
          // no default is invented to fill the gap.
          if (options.length === 0) return
          setOpen((current) => {
            if (!current) {
              const active = options.findIndex((option) => option.active)
              setActiveIndex(active === -1 ? 0 : active)
            }
            return !current
          })
        }}
      >
        <span>{parts.role}</span>
        <span aria-hidden="true">·</span>
        <code className="font-mono">{parts.binding}</code>
        <span aria-hidden="true">·</span>
        <span>{parts.provider}</span>
        <span aria-hidden="true">●</span>
        <span aria-hidden="true">{parts.health}</span>
      </button>

      {options.length === 0 && (
        <span data-testid="model-select-empty" className="text-xs text-muted-foreground">
          {NO_MODELS_CONFIGURED}
        </span>
      )}

      {open && options.length > 0 && (
        <div
          ref={listRef}
          id={listboxId}
          role="listbox"
          tabIndex={0}
          aria-label={`Choose the model bound to the ${role.role} role`}
          aria-activedescendant={optionId(activeIndex)}
          aria-busy={busyBinding !== undefined}
          data-testid="model-select-listbox"
          onKeyDown={onListKeyDown}
          className="absolute top-full left-0 z-50 mt-1 flex w-max max-w-[min(28rem,90vw)] flex-col gap-1 rounded-md border bg-popover p-2 shadow-md"
        >
          {options.map((option, index) => (
            <div
              key={option.binding}
              id={optionId(index)}
              role="option"
              aria-selected={option.active}
              aria-description={optionAccessibleDescription(option)}
              data-testid={`model-option-${option.binding}`}
              className={`flex cursor-pointer items-start gap-2 rounded-sm p-1.5 ${
                index === activeIndex ? 'bg-muted' : ''
              }`}
              onClick={() => {
                setActiveIndex(index)
                void choose(option.binding)
              }}
            >
              <OptionBody option={option} />
            </div>
          ))}
        </div>
      )}

      {busyBinding !== undefined && (
        <span data-testid="model-select-pending" className="text-xs text-muted-foreground">
          binding {role.role} to {busyBinding}…
        </span>
      )}

      {open && (
        // Where the binding in force came from: a stored choice that applies
        // to the next call, or the file default it inherited. Never restart
        // language — a selection needs none.
        <span data-testid="model-select-source" className="text-xs text-muted-foreground">
          {sourceNotice(role)}
        </span>
      )}

      {stale !== null && (
        <span data-testid="model-select-stale" className="text-xs text-muted-foreground">
          {stale}
        </span>
      )}

      {refusal !== undefined && (
        // In place, under the select, with the rule first — never a toast
        // (EXPERIENCE.md § Refusal box).
        <span
          role="alert"
          data-testid="model-select-refusal"
          className="rounded-md border border-destructive/40 p-2 text-xs text-destructive"
        >
          {refusal}
        </span>
      )}
    </span>
  )
}
