import { useCallback, useEffect, useRef, useState } from 'react'
import { getModelSettings, getSystemStatus, selectRoleBinding } from '@/client/sdk.gen'
import type { ModelSettingsResponse, RoleSelectionView } from '@/client/types.gen'
import { problemMessage } from '@/lib/problems'
import {
  MODEL_SETTINGS_TIMEOUT_MS,
  providerHealthIndex,
  selectionRefusal,
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
  /** Provider id → health, empty when `GET /status` could not be read. */
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

export function useModelSettings(): ModelSettingsController {
  const [load, setLoad] = useState<ModelSettingsLoad>({ kind: 'loading' })
  const [health, setHealth] = useState<Map<string, ProviderHealth>>(new Map())
  const [pending, setPending] = useState<Record<string, string | undefined>>({})
  const [failure, setFailure] = useState<Record<string, string | undefined>>({})

  // One counter per role: two roles selecting at once are independent, and a
  // stale response is recognised by comparing its own generation with the
  // latest issued for *its* role.
  const generations = useRef<Record<string, number>>({})
  const mounted = useRef(true)

  useEffect(() => {
    mounted.current = true
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), MODEL_SETTINGS_TIMEOUT_MS)
    void (async () => {
      try {
        const { data, error } = await getModelSettings({ signal: controller.signal })
        if (!mounted.current) return
        if (error !== undefined || data === undefined) {
          setLoad({
            kind: 'failed',
            message: describe(error, 'the api refused the model-settings read'),
          })
          return
        }
        setLoad({ kind: 'loaded', payload: data })
      } catch (thrown) {
        if (!mounted.current) return
        setLoad({
          kind: 'failed',
          message: controller.signal.aborted
            ? `no answer within ${MODEL_SETTINGS_TIMEOUT_MS / 1000}s`
            : describe(thrown, 'the model settings could not be read'),
        })
      } finally {
        clearTimeout(timer)
      }
    })()
    return () => {
      mounted.current = false
      controller.abort()
      clearTimeout(timer)
    }
  }, [])

  // A separate request from the catalog read, and deliberately not awaited
  // together with it: health decorates the options, it does not gate them. A
  // status outage leaves every option reading `unknown` and still selectable.
  useEffect(() => {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), MODEL_SETTINGS_TIMEOUT_MS)
    void (async () => {
      try {
        const { data, error } = await getSystemStatus({ signal: controller.signal })
        if (!mounted.current || error !== undefined || data === undefined) return
        setHealth(providerHealthIndex(data))
      } catch {
        // Nothing to say: the picker's own contract is that unread health
        // renders as `unknown`, which is already the initial state.
      } finally {
        clearTimeout(timer)
      }
    })()
    return () => {
      controller.abort()
      clearTimeout(timer)
    }
  }, [])

  const select = useCallback(async (role: RoleSelectionView, binding: string) => {
    const name = role.role
    const generation = (generations.current[name] ?? 0) + 1
    generations.current[name] = generation
    const current = () => generations.current[name] === generation

    setPending((state) => ({ ...state, [name]: binding }))
    setFailure((state) => ({ ...state, [name]: undefined }))
    try {
      const { data, error } = await selectRoleBinding({
        path: { role: name },
        body: { binding },
      })
      // Superseded by a newer click, or unmounted: discard both outcomes.
      // Late success and late failure are equally unwelcome — either would
      // report a binding that is not the one the reader last asked for.
      if (!mounted.current || !current()) return
      if (error !== undefined || data === undefined) {
        setFailure((state) => ({
          ...state,
          [name]: selectionRefusal(role, describe(error, 'the api refused the choice')),
        }))
        return
      }
      // The api's re-resolved view replaces this role's, so the trigger and
      // the ✓ show what the *next call* will use — answered by the same
      // function `GET /settings/models` answers with.
      setLoad((state) =>
        state.kind === 'loaded'
          ? {
              kind: 'loaded',
              payload: {
                ...state.payload,
                roles: state.payload.roles.map((entry) =>
                  entry.role === name ? data : entry,
                ),
              },
            }
          : state,
      )
    } catch (thrown) {
      if (!mounted.current || !current()) return
      setFailure((state) => ({
        ...state,
        [name]: selectionRefusal(role, describe(thrown, 'the api could not be reached')),
      }))
    } finally {
      if (mounted.current && current()) {
        setPending((state) => ({ ...state, [name]: undefined }))
      }
    }
  }, [])

  return { load, health, pending, failure, select }
}
