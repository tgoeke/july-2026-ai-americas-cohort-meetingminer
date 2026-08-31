import { useCallback, useEffect, useState } from 'react'
import { getModelSettings, getSystemStatus, selectRoleBinding } from '@/client/sdk.gen'
import type { ModelSettingsResponse, RoleSelectionView } from '@/client/types.gen'
import { problemMessage, problemType } from '@/lib/problems'
import {
  MODEL_SETTINGS_TIMEOUT_MS,
  providerHealthIndex,
  selectionRefusal,
  selectionUnconfirmed,
  type ProviderHealth,
} from './models'

/**
 * The one place the model picker talks to the api (story 8.3).
 *
 * Both surfaces — the ask box's popover and the Settings page's per-role
 * lists — mount this hook, so the read, the write, and the ownership rule
 * exist once. It reads `GET /settings/models` (the catalog and the binding in
 * force) and `GET /status` (provider health), and writes
 * `PUT /settings/roles/{role}`.
 *
 * Three properties this hook exists to hold:
 *
 * 1. **No substitution.** A refused or failed selection leaves the binding in
 *    force exactly as the api last reported it. The hook never picks another
 *    entry, never falls back to the default, and never re-orders the catalog
 *    so a broken option drifts out of reach.
 * 2. **Asynchronous ownership** (EXPERIENCE.md). Every selection carries a
 *    monotonically increasing generation; a response may update visible state
 *    only if its generation is still the latest. A slow first click can never
 *    overwrite a fast second one.
 * 3. **Health is never assumed.** If `GET /status` fails, the health index is
 *    empty and every option reads `unknown` — the picker draws no dot it
 *    cannot support, and the catalog still renders, because choosing a model
 *    must not depend on the health surface being up.
 */

export type ModelSettingsLoad =
  | { kind: 'loading' }
  | { kind: 'loaded'; payload: ModelSettingsResponse }
  | { kind: 'failed'; message: string }

export interface ModelSettingsController {
  load: ModelSettingsLoad
  /** Provider/role evidence → health, empty when `GET /status` could not be read. */
  health: Map<string, ProviderHealth>
  /** The binding whose `PUT` is in flight, per role — for `aria-busy`. */
  pending: Record<string, string | undefined>
  /** The api's refusal for a role's last selection, in the api's own words. */
  failure: Record<string, string | undefined>
  select: (role: RoleSelectionView, binding: string) => Promise<void>
}

function describe(error: unknown, fallback: string): string {
  const problem = problemMessage(error)
  if (problem !== null) return problem
  if (error instanceof Error) return error.message
  return fallback
}

function describeSelection(error: unknown, fallback: string): string {
  const message = describe(error, fallback)
  const type = problemType(error)
  if (type === null) return message
  const prefix = 'urn:meetingminer:problem:'
  const rule = type.startsWith(prefix) ? type.slice(prefix.length) : type
  return `${rule} — ${message}`
}

type SelectionEvent =
  | { kind: 'start'; role: string; binding: string }
  | { kind: 'success'; role: RoleSelectionView }
  | { kind: 'failure'; role: string; message: string; authoritative: RoleSelectionView }
  | { kind: 'finish'; role: string }

const selectionListeners = new Set<(event: SelectionEvent) => void>()
const selectionGenerations: Record<string, number> = {}
const selectionTails = new Map<string, Promise<void>>()
const confirmedRoles = new Map<string, RoleSelectionView>()
let modelRevision = 0

function emitSelection(event: SelectionEvent): void {
  for (const listener of selectionListeners) listener(event)
}

/**
 * All hook instances share this write boundary. Same-role writes are issued in
 * click order, while different roles have independent tails and can proceed in
 * parallel. Events update every mounted surface from the same authoritative
 * response.
 */
async function selectGlobally(role: RoleSelectionView, binding: string): Promise<void> {
  const name = role.role
  const generation = (selectionGenerations[name] ?? 0) + 1
  selectionGenerations[name] = generation
  const current = () => selectionGenerations[name] === generation
  emitSelection({ kind: 'start', role: name, binding })

  const previous = selectionTails.get(name) ?? Promise.resolve()
  const task = previous
    .catch(() => undefined)
    .then(async () => {
      // A third click can supersede a queued second click before it is sent.
      if (!current()) return

      const controller = new AbortController()
      let timedOut = false
      const timer = setTimeout(() => {
        timedOut = true
        controller.abort()
      }, MODEL_SETTINGS_TIMEOUT_MS)
      try {
        const result = await selectRoleBinding({
          path: { role: name },
          body: { binding },
          signal: controller.signal,
        })
        const { data, error, response } = result
        if (error !== undefined || data === undefined) {
          if (!current()) return
          const authoritative = confirmedRoles.get(name) ?? role
          emitSelection({
            kind: 'failure',
            role: name,
            authoritative,
            message:
              response !== undefined && !response.ok
                ? selectionRefusal(
                    authoritative,
                    binding,
                    describeSelection(error, 'the api refused the choice'),
                  )
                : selectionUnconfirmed(
                    authoritative,
                    binding,
                    describe(error, 'the api response could not be read'),
                  ),
          })
          return
        }

        if (data.role !== name) {
          if (!current()) return
          const authoritative = confirmedRoles.get(name) ?? role
          emitSelection({
            kind: 'failure',
            role: name,
            authoritative,
            message: selectionUnconfirmed(
              authoritative,
              binding,
              `the api returned role ${data.role} for requested role ${name}`,
            ),
          })
          return
        }

        // Record every successful write, including a response superseded while
        // it was in flight. If the later write is refused, this is the binding
        // the server most recently confirmed before that refusal.
        confirmedRoles.set(name, data)
        modelRevision += 1
        if (current()) emitSelection({ kind: 'success', role: data })
      } catch (thrown) {
        if (!current()) return
        const authoritative = confirmedRoles.get(name) ?? role
        emitSelection({
          kind: 'failure',
          role: name,
          authoritative,
          message: selectionUnconfirmed(
            authoritative,
            binding,
            timedOut
              ? `no answer within ${MODEL_SETTINGS_TIMEOUT_MS / 1000}s`
              : describe(thrown, 'the api could not be reached'),
          ),
        })
      } finally {
        clearTimeout(timer)
        if (current()) emitSelection({ kind: 'finish', role: name })
      }
    })

  selectionTails.set(name, task)
  await task
  if (selectionTails.get(name) === task) selectionTails.delete(name)
}

function replaceRole(
  state: ModelSettingsLoad,
  role: RoleSelectionView,
): ModelSettingsLoad {
  if (state.kind !== 'loaded') return state
  return {
    kind: 'loaded',
    payload: {
      ...state.payload,
      roles: state.payload.roles.map((entry) =>
        entry.role === role.role ? role : entry,
      ),
    },
  }
}

export function useModelSettings(): ModelSettingsController {
  const [load, setLoad] = useState<ModelSettingsLoad>({ kind: 'loading' })
  const [health, setHealth] = useState<Map<string, ProviderHealth>>(new Map())
  const [pending, setPending] = useState<Record<string, string | undefined>>({})
  const [failure, setFailure] = useState<Record<string, string | undefined>>({})

  useEffect(() => {
    let cancelled = false
    const controller = new AbortController()
    let timedOut = false
    const timer = setTimeout(() => {
      timedOut = true
      controller.abort()
    }, MODEL_SETTINGS_TIMEOUT_MS)
    void (async () => {
      while (!cancelled) {
        const revision = modelRevision
        try {
          const { data, error } = await getModelSettings({ signal: controller.signal })
          if (cancelled) return
          if (controller.signal.aborted) {
            setLoad({
              kind: 'failed',
              message: timedOut
                ? `no answer within ${MODEL_SETTINGS_TIMEOUT_MS / 1000}s`
                : 'the model settings read was cancelled',
            })
            return
          }
          if (error !== undefined || data === undefined) {
            setLoad({
              kind: 'failed',
              message: describe(error, 'the api refused the model-settings read'),
            })
            return
          }
          if (revision !== modelRevision) continue
          for (const role of data.roles) confirmedRoles.set(role.role, role)
          setLoad({ kind: 'loaded', payload: data })
          return
        } catch (thrown) {
          if (cancelled) return
          setLoad({
            kind: 'failed',
            message: timedOut
              ? `no answer within ${MODEL_SETTINGS_TIMEOUT_MS / 1000}s`
              : describe(thrown, 'the model settings could not be read'),
          })
          return
        }
      }
    })().finally(() => clearTimeout(timer))
    return () => {
      cancelled = true
      controller.abort()
      clearTimeout(timer)
    }
  }, [])

  // A separate request from the catalog read, and deliberately not awaited
  // together with it: health decorates the options, it does not gate them. A
  // status outage leaves every option reading `unknown` and still selectable.
  useEffect(() => {
    let cancelled = false
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), MODEL_SETTINGS_TIMEOUT_MS)
    void (async () => {
      try {
        const { data, error } = await getSystemStatus({ signal: controller.signal })
        if (cancelled || controller.signal.aborted || error !== undefined || data === undefined) return
        setHealth(providerHealthIndex(data))
      } catch {
        // Nothing to say: the picker's own contract is that unread health
        // renders as `unknown`, which is already the initial state.
      } finally {
        clearTimeout(timer)
      }
    })()
    return () => {
      cancelled = true
      controller.abort()
      clearTimeout(timer)
    }
  }, [])

  useEffect(() => {
    const listener = (event: SelectionEvent) => {
      if (event.kind === 'start') {
        setPending((state) => ({ ...state, [event.role]: event.binding }))
        setFailure((state) => ({ ...state, [event.role]: undefined }))
      } else if (event.kind === 'success') {
        setLoad((state) => replaceRole(state, event.role))
      } else if (event.kind === 'failure') {
        setLoad((state) => replaceRole(state, event.authoritative))
        setFailure((state) => ({ ...state, [event.role]: event.message }))
      } else {
        setPending((state) => ({ ...state, [event.role]: undefined }))
      }
    }
    selectionListeners.add(listener)
    return () => {
      selectionListeners.delete(listener)
    }
  }, [])

  const select = useCallback(
    async (role: RoleSelectionView, binding: string) => selectGlobally(role, binding),
    [],
  )

  return { load, health, pending, failure, select }
}
