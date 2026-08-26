import { useCallback, useEffect, useRef, useState } from 'react'
import { listParticipants, mergeParticipants, renameParticipant } from '@/client/sdk.gen'
import type { ParticipantRow } from '@/client/types.gen'
import { Button } from '@/components/ui/button'
import { API_BASE } from '@/lib/api'
import {
  canonicalRows,
  groupByNormalizedName,
  loadFailureOf,
  PARTICIPANTS_TIMEOUT_MS,
  problemCopy,
  transportFailureOf,
  type ParticipantsLoadFailure,
} from './curation'

/**
 * Story 2.4's curation screen: every `participant` row, canonical rows
 * editable (rename, merge into another canonical row), merged-away rows
 * shown read-only with their survivor.
 *
 * The mutation idiom copies `MomentView.tsx`'s `handleApprove`:
 * abort-controller-per-request, an explicit 8s expiry via `AbortSignal.any`,
 * a mutation error state kept apart from the load failure so a rename/merge
 * refusal never masquerades as a load failure and vice versa.
 */
export function Participants() {
  const [rows, setRows] = useState<Array<ParticipantRow> | null>(null)
  const [failure, setFailure] = useState<ParticipantsLoadFailure | null>(null)
  const controllerRef = useRef<AbortController | null>(null)

  // Rename: which row is in edit mode, its draft text, and this gesture's
  // own request state.
  const [editingId, setEditingId] = useState<string | null>(null)
  const [draftName, setDraftName] = useState('')
  const [renamePending, setRenamePending] = useState(false)
  const [renameError, setRenameError] = useState<string | null>(null)
  const renameControllerRef = useRef<AbortController | null>(null)

  // Merge: the chosen target per absorbed row (so more than one picker can
  // hold a selection at once), one merge request's own in-flight state, and
  // a per-row error map — a curator working several rows needs to tell which
  // merge failed, the same per-row association rename's error already has.
  const [mergeTargets, setMergeTargets] = useState<Record<string, string>>({})
  const [mergingId, setMergingId] = useState<string | null>(null)
  const [mergeErrors, setMergeErrors] = useState<Record<string, string>>({})
  const mergeControllerRef = useRef<AbortController | null>(null)

  const load = useCallback(async () => {
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller
    setFailure(null)
    const expiry = new AbortController()
    const timer = setTimeout(() => expiry.abort(), PARTICIPANTS_TIMEOUT_MS)
    try {
      const signal = AbortSignal.any([controller.signal, expiry.signal])
      const { data, error } = await listParticipants({ signal })
      if (controller.signal.aborted) return
      if (expiry.signal.aborted) {
        setFailure({ kind: 'transport', message: `timed out after ${PARTICIPANTS_TIMEOUT_MS}ms` })
        return
      }
      if (error !== undefined) {
        setFailure(loadFailureOf(error))
        return
      }
      if (data === undefined) throw new Error('the api answered with no body')
      setRows(data)
      setFailure(null)
    } catch (err) {
      if (controller.signal.aborted) return
      setFailure(
        expiry.signal.aborted
          ? { kind: 'transport', message: `timed out after ${PARTICIPANTS_TIMEOUT_MS}ms` }
          : transportFailureOf(err),
      )
    } finally {
      clearTimeout(timer)
    }
  }, [])

  useEffect(() => {
    void load()
    return () => {
      controllerRef.current?.abort()
      renameControllerRef.current?.abort()
      mergeControllerRef.current?.abort()
    }
  }, [load])

  const startRename = useCallback((row: ParticipantRow) => {
    setEditingId(row.id)
    setDraftName(row.displayName)
    setRenameError(null)
  }, [])

  const cancelRename = useCallback(() => {
    setEditingId(null)
    setDraftName('')
    setRenameError(null)
  }, [])

  const saveRename = useCallback(
    async (participantId: string) => {
      renameControllerRef.current?.abort()
      const controller = new AbortController()
      renameControllerRef.current = controller
      setRenamePending(true)
      setRenameError(null)
      const expiry = new AbortController()
      const timer = setTimeout(() => expiry.abort(), PARTICIPANTS_TIMEOUT_MS)
      try {
        const signal = AbortSignal.any([controller.signal, expiry.signal])
        const { data, error } = await renameParticipant({
          path: { participant_id: participantId },
          body: { displayName: draftName },
          signal,
        })
        if (controller.signal.aborted) return
        if (expiry.signal.aborted) {
          setRenameError(`timed out after ${PARTICIPANTS_TIMEOUT_MS}ms`)
          return
        }
        if (error !== undefined) {
          setRenameError(problemCopy(error))
          return
        }
        if (data === undefined) throw new Error('the api answered with no body')
        // Replace the one row in place — no full reload, matching
        // `handleApprove`'s rail-replacement idiom.
        setRows((current) =>
          current === null
            ? current
            : current.map((row) => (row.id === data.id ? data : row)),
        )
        setEditingId(null)
        setDraftName('')
      } catch (err) {
        if (controller.signal.aborted) return
        setRenameError(
          expiry.signal.aborted
            ? `timed out after ${PARTICIPANTS_TIMEOUT_MS}ms`
            : err instanceof Error
              ? err.message
              : String(err),
        )
      } finally {
        clearTimeout(timer)
        if (!controller.signal.aborted) setRenamePending(false)
      }
    },
    [draftName],
  )

  const chooseMergeTarget = useCallback((absorbedId: string, targetId: string) => {
    setMergeTargets((current) => ({ ...current, [absorbedId]: targetId }))
  }, [])

  const runMerge = useCallback(
    async (absorbedId: string) => {
      const targetId = mergeTargets[absorbedId]
      if (targetId == null || targetId === '') return
      const controller = new AbortController()
      mergeControllerRef.current = controller
      setMergingId(absorbedId)
      setMergeErrors((current) => {
        const next = { ...current }
        delete next[absorbedId]
        return next
      })
      const expiry = new AbortController()
      const timer = setTimeout(() => expiry.abort(), PARTICIPANTS_TIMEOUT_MS)
      try {
        const signal = AbortSignal.any([controller.signal, expiry.signal])
        const { data, error } = await mergeParticipants({
          path: { participant_id: absorbedId },
          body: { intoParticipantId: targetId },
          signal,
        })
        if (controller.signal.aborted) return
        if (expiry.signal.aborted) {
          setMergeErrors((current) => ({
            ...current,
            [absorbedId]: `timed out after ${PARTICIPANTS_TIMEOUT_MS}ms`,
          }))
          return
        }
        if (error !== undefined) {
          setMergeErrors((current) => ({ ...current, [absorbedId]: problemCopy(error) }))
          return
        }
        if (data === undefined) throw new Error('the api answered with no body')
        // The merge response is the whole refreshed list (AD-5's contract) —
        // replace state wholesale rather than patching two rows by hand.
        setRows(data)
        setMergeTargets((current) => {
          const next = { ...current }
          delete next[absorbedId]
          return next
        })
      } catch (err) {
        if (controller.signal.aborted) return
        setMergeErrors((current) => ({
          ...current,
          [absorbedId]: expiry.signal.aborted
            ? `timed out after ${PARTICIPANTS_TIMEOUT_MS}ms`
            : err instanceof Error
              ? err.message
              : String(err),
        }))
      } finally {
        clearTimeout(timer)
        if (!controller.signal.aborted) setMergingId(null)
      }
    },
    [mergeTargets],
  )

  const loading = rows === null && failure === null
  const duplicateGroups = rows === null ? [] : groupByNormalizedName(rows)

  return (
    <section className="flex w-full flex-col gap-4">
      <header>
        <h2 className="text-lg font-semibold tracking-tight">Participants</h2>
        <p className="text-xs text-muted-foreground">
          Rename a participant, or merge a duplicate identity into its
          survivor. A merge reaches already-ingested meetings after their next
          re-ingest, then projection (AD-5).
        </p>
      </header>

      {failure !== null &&
        (failure.kind === 'transport' ? (
          <p role="alert" className="rounded-md border border-destructive/40 p-3 text-sm text-destructive">
            Cannot reach the api at {API_BASE}: {failure.message}.
          </p>
        ) : (
          <p role="alert" className="rounded-md border p-3 text-sm text-muted-foreground">
            {failure.message}
          </p>
        ))}

      {duplicateGroups.length > 0 && (
        <div
          data-testid="duplicate-hint-groups"
          className="flex flex-col gap-1 rounded-md border border-dashed p-3 text-xs text-muted-foreground"
        >
          <span className="font-medium">Possible duplicates (same normalized name):</span>
          {duplicateGroups.map((group) => (
            <div key={group.normalizedName} data-testid={`duplicate-hint-${group.normalizedName}`}>
              {group.rows.map((row) => row.displayName).join(' · ')}
            </div>
          ))}
        </div>
      )}

      <div aria-live="polite" aria-busy={loading}>
        {loading ? (
          <p className="text-sm text-muted-foreground">Loading participants…</p>
        ) : rows === null ? null : rows.length === 0 ? (
          <p data-testid="participants-empty" className="text-sm text-muted-foreground">
            No participants yet.
          </p>
        ) : (
          <ul data-testid="participants-list" className="flex flex-col gap-2">
            {rows.map((row) => {
              const canonical = row.mergedIntoParticipantId == null
              const isEditing = editingId === row.id
              const targets = canonicalRows(rows).filter((other) => other.id !== row.id)
              return (
                <li
                  key={row.id}
                  data-testid={`participant-row-${row.id}`}
                  className="flex flex-col gap-1 rounded-md border p-3 text-sm"
                >
                  {!canonical ? (
                    <span data-testid={`merged-away-${row.id}`} className="text-muted-foreground">
                      {row.displayName} — merged into{' '}
                      {rows.find((r) => r.id === row.mergedIntoParticipantId)?.displayName ??
                        row.mergedIntoParticipantId}
                    </span>
                  ) : isEditing ? (
                    <div className="flex items-center gap-2">
                      <input
                        data-testid={`rename-input-${row.id}`}
                        aria-label={`Rename ${row.displayName}`}
                        className="rounded border px-2 py-1 text-sm"
                        value={draftName}
                        onChange={(event) => setDraftName(event.target.value)}
                      />
                      <Button
                        size="sm"
                        data-testid={`rename-save-${row.id}`}
                        disabled={renamePending}
                        onClick={() => void saveRename(row.id)}
                      >
                        {renamePending ? 'Saving…' : 'Save'}
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        data-testid={`rename-cancel-${row.id}`}
                        disabled={renamePending}
                        onClick={cancelRename}
                      >
                        Cancel
                      </Button>
                    </div>
                  ) : (
                    <div className="flex items-center justify-between gap-2">
                      <span>{row.displayName}</span>
                      <Button
                        size="sm"
                        variant="outline"
                        data-testid={`rename-start-${row.id}`}
                        onClick={() => startRename(row)}
                      >
                        Rename
                      </Button>
                    </div>
                  )}
                  {isEditing && renameError !== null && (
                    <p role="alert" data-testid={`rename-error-${row.id}`} className="text-xs text-destructive">
                      {renameError}
                    </p>
                  )}

                  {canonical && !isEditing && targets.length > 0 && (
                    <div className="flex items-center gap-2">
                      <select
                        data-testid={`merge-select-${row.id}`}
                        aria-label={`Merge ${row.displayName} into`}
                        className="rounded border px-2 py-1 text-xs"
                        value={mergeTargets[row.id] ?? ''}
                        onChange={(event) => chooseMergeTarget(row.id, event.target.value)}
                      >
                        <option value="">Merge into…</option>
                        {targets.map((target) => (
                          <option key={target.id} value={target.id}>
                            {target.displayName} ({target.identityKey})
                          </option>
                        ))}
                      </select>
                      <Button
                        size="sm"
                        variant="outline"
                        data-testid={`merge-button-${row.id}`}
                        disabled={mergingId !== null || !mergeTargets[row.id]}
                        onClick={() => void runMerge(row.id)}
                      >
                        {mergingId === row.id ? 'Merging…' : 'Merge'}
                      </Button>
                    </div>
                  )}
                  {canonical && !isEditing && mergeErrors[row.id] != null && (
                    <p
                      role="alert"
                      data-testid={`merge-error-${row.id}`}
                      className="text-xs text-destructive"
                    >
                      {mergeErrors[row.id]}
                    </p>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </section>
  )
}
