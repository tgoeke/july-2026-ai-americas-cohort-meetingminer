import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  fetchThreadTopics,
  mergeThreads,
  renameThread,
  splitThread,
  type ThreadsFailure,
  type ThreadSummary,
  type ThreadTopicGroup,
} from './threadsApi'

/**
 * Thread curation: Rename · Merge into… · Split… (story 10.2a, FR42).
 *
 * The machine groups topics into threads and re-derives that grouping on
 * every pass. This is where a human corrects it — and the correction holds,
 * because the api stores it in its own tables and the worker resolves them
 * before it re-derives (`domain/thread_curation.py`). Nothing here renames,
 * merges or splits on its own initiative; every write is a button a person
 * pressed.
 *
 * **Why the controls live on the row.** `DESIGN.md · Split panel` and
 * `EXPERIENCE.md · Thread list` put them after the thread's name, with the
 * active panel opening beneath it: the thing being corrected stays on screen
 * while you correct it. Rename is an inline input with Save/Cancel and merge
 * is a select with Merge, mirroring `Participants` deliberately — a curator
 * who has used one screen should not have to learn the other.
 *
 * **A refusal never reads as a success.** A 4xx renders as a refusal box under
 * the row in the api's own words, the input keeps its text, and the panel
 * stays open with its checks intact, so a correction is never half-drawn as
 * though it took (AD-18).
 */

/** Which panel is open. Only one at a time, per row. */
type Mode = 'idle' | 'rename' | 'merge' | 'split'

export interface ThreadCurationProps {
  thread: ThreadSummary
  /** Every other thread, as merge targets. Already excludes this one. */
  mergeTargets: ReadonlyArray<ThreadSummary>
  /** Re-read `GET /threads` after a write landed. */
  onCurated: () => void
}

/** The date a split-panel group header prints, from an RFC 3339 instant. */
export function groupDate(occurredAt: string): string {
  return occurredAt.slice(0, 10)
}

/**
 * Whether `Split` may be pressed.
 *
 * At least one topic and fewer than all of them, plus a name: moving every
 * topic empties the original thread and is a rename, which the api refuses
 * too. Enforced in both places on purpose — the button explains the rule
 * before the request, the api guarantees it regardless of client.
 */
export function canSplit(checked: ReadonlySet<string>, total: number, name: string): boolean {
  return checked.size >= 1 && checked.size < total && name.trim().length > 0
}

function Refusal({ failure }: { failure: ThreadsFailure }) {
  return (
    <div
      role="alert"
      className="mt-2 rounded-md border border-destructive bg-destructive/12 p-2 text-sm"
    >
      <p className="font-mono text-xs text-destructive">threads: curation refused</p>
      <p className="mt-1">{failure.message}</p>
    </div>
  )
}

export function ThreadCuration({ thread, mergeTargets, onCurated }: ThreadCurationProps) {
  const [mode, setMode] = useState<Mode>('idle')
  const [failure, setFailure] = useState<ThreadsFailure | null>(null)
  const [busy, setBusy] = useState(false)

  const [draftName, setDraftName] = useState(thread.name)
  const [mergeTargetId, setMergeTargetId] = useState('')
  const [splitName, setSplitName] = useState('')
  const [checked, setChecked] = useState<ReadonlySet<string>>(new Set())
  const [groups, setGroups] = useState<Array<ThreadTopicGroup> | null>(null)

  // Focus returns to the control that opened the panel when it closes, so a
  // keyboard user is never dropped at the top of the list (EXPERIENCE.md).
  const renameRef = useRef<HTMLButtonElement>(null)
  const mergeRef = useRef<HTMLButtonElement>(null)
  const splitRef = useRef<HTMLButtonElement>(null)

  const close = useCallback(
    (returnTo: 'rename' | 'merge' | 'split') => {
      setMode('idle')
      setFailure(null)
      const target =
        returnTo === 'rename' ? renameRef : returnTo === 'merge' ? mergeRef : splitRef
      target.current?.focus()
    },
    [],
  )

  const open = useCallback(
    (next: Mode) => {
      setFailure(null)
      setMode(next)
      if (next === 'rename') setDraftName(thread.name)
      if (next === 'merge') setMergeTargetId('')
      if (next === 'split') {
        setSplitName('')
        setChecked(new Set())
      }
    },
    [thread.name],
  )

  // The checklist is fetched only when the panel opens: a list of forty rows
  // must not make forty timeline requests for panels nobody opened.
  useEffect(() => {
    if (mode !== 'split') return
    const controller = new AbortController()
    setGroups(null)
    void fetchThreadTopics(thread.threadId, controller.signal).then(({ data, error }) => {
      if (controller.signal.aborted) return
      if (error !== undefined) setFailure(error)
      if (data !== undefined) setGroups(data)
    })
    return () => controller.abort()
  }, [mode, thread.threadId])

  const totalTopics = useMemo(
    () => (groups ?? []).reduce((sum, group) => sum + group.topics.length, 0),
    [groups],
  )

  const settle = useCallback(
    async (write: Promise<{ error?: ThreadsFailure }>, returnTo: 'rename' | 'merge' | 'split') => {
      setBusy(true)
      const { error } = await write
      setBusy(false)
      if (error !== undefined) {
        // The panel stays open and the input keeps its text: a refusal is
        // something to correct, not something that discards the attempt.
        setFailure(error)
        return
      }
      close(returnTo)
      onCurated()
    },
    [close, onCurated],
  )

  const onKeyDown = (event: React.KeyboardEvent, returnTo: 'rename' | 'merge' | 'split') => {
    if (event.key === 'Escape') {
      event.stopPropagation()
      close(returnTo)
    }
  }

  const toggle = (topicId: string) => {
    setChecked((current) => {
      const next = new Set(current)
      if (next.has(topicId)) next.delete(topicId)
      else next.add(topicId)
      return next
    })
  }

  const splitReady = canSplit(checked, totalTopics, splitName)

  return (
    <div className="px-2 pb-1">
      <div role="group" aria-label={`Curate ${thread.name}`} className="flex flex-wrap gap-2 text-xs">
        <button
          type="button"
          ref={renameRef}
          onClick={() => open(mode === 'rename' ? 'idle' : 'rename')}
          aria-expanded={mode === 'rename'}
          className="mm-focusable min-h-6 rounded-md border border-white/34 px-2 text-muted-foreground"
        >
          Rename
        </button>
        <button
          type="button"
          ref={mergeRef}
          onClick={() => open(mode === 'merge' ? 'idle' : 'merge')}
          aria-expanded={mode === 'merge'}
          className="mm-focusable min-h-6 rounded-md border border-white/34 px-2 text-muted-foreground"
        >
          Merge into…
        </button>
        <button
          type="button"
          ref={splitRef}
          onClick={() => open(mode === 'split' ? 'idle' : 'split')}
          aria-expanded={mode === 'split'}
          className="mm-focusable min-h-6 rounded-md border border-white/34 px-2 text-muted-foreground"
        >
          Split…
        </button>
        {/*
          The provenance label. `machine-derived` is what threads are by
          default (AD-4/AD-5) and `curated` is what a human name makes this
          one; printing the pair rather than only the exception is what lets a
          reader tell the two apart at a glance instead of inferring it from
          an absence.
        */}
        <span className="ml-auto self-center font-mono text-[10px] uppercase tracking-wide text-muted-foreground">
          {thread.nameIsCurated ? 'curated' : 'machine-derived'}
        </span>
      </div>

      {mode === 'rename' ? (
        <form
          className="mt-2"
          onKeyDown={(event) => onKeyDown(event, 'rename')}
          onSubmit={(event) => {
            event.preventDefault()
            void settle(renameThread(thread.threadId, draftName), 'rename')
          }}
        >
          <input
            autoFocus
            value={draftName}
            onChange={(event) => setDraftName(event.target.value)}
            aria-label={`New name for ${thread.name}`}
            className="h-8 w-full rounded-md border border-white/34 bg-transparent px-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
          <div className="mt-2 flex gap-2 text-xs">
            <button
              type="submit"
              disabled={busy || draftName.trim().length === 0}
              className="mm-focusable min-h-6 rounded-md bg-primary px-2 text-primary-foreground disabled:opacity-50"
            >
              {busy ? 'Saving…' : 'Save'}
            </button>
            <button
              type="button"
              onClick={() => close('rename')}
              className="mm-focusable min-h-6 rounded-md border border-white/34 px-2"
            >
              Cancel
            </button>
            {thread.nameIsCurated ? (
              <button
                type="button"
                disabled={busy}
                onClick={() => void settle(renameThread(thread.threadId, null), 'rename')}
                className="mm-focusable ml-auto min-h-6 rounded-md px-2 text-muted-foreground underline"
              >
                Use the machine name
              </button>
            ) : null}
          </div>
        </form>
      ) : null}

      {mode === 'merge' ? (
        <form
          className="mt-2"
          onKeyDown={(event) => onKeyDown(event, 'merge')}
          onSubmit={(event) => {
            event.preventDefault()
            if (mergeTargetId.length === 0) return
            void settle(mergeThreads(thread.threadId, mergeTargetId), 'merge')
          }}
        >
          <select
            autoFocus
            value={mergeTargetId}
            onChange={(event) => setMergeTargetId(event.target.value)}
            aria-label={`Merge ${thread.name} into`}
            className="h-8 w-full rounded-md border border-white/34 bg-transparent px-2 text-sm"
          >
            <option value="">choose a thread</option>
            {mergeTargets.map((target) => (
              <option key={target.threadId} value={target.threadId}>
                {target.name}
              </option>
            ))}
          </select>
          <p className="mt-1 text-[11px] text-muted-foreground">
            {thread.name} is absorbed; the thread you choose keeps its colour and its name.
          </p>
          <div className="mt-2 flex gap-2 text-xs">
            <button
              type="submit"
              disabled={busy || mergeTargetId.length === 0}
              className="mm-focusable min-h-6 rounded-md bg-primary px-2 text-primary-foreground disabled:opacity-50"
            >
              {busy ? 'Merging…' : 'Merge'}
            </button>
            <button
              type="button"
              onClick={() => close('merge')}
              className="mm-focusable min-h-6 rounded-md border border-white/34 px-2"
            >
              Cancel
            </button>
          </div>
        </form>
      ) : null}

      {mode === 'split' ? (
        <form
          className="mt-2 rounded-md border border-white/34 bg-card p-3"
          onKeyDown={(event) => onKeyDown(event, 'split')}
          onSubmit={(event) => {
            event.preventDefault()
            if (!splitReady) return
            void settle(splitThread(thread.threadId, [...checked], splitName), 'split')
          }}
        >
          {groups === null ? (
            <p className="text-sm text-muted-foreground">Loading this thread&apos;s topics…</p>
          ) : totalTopics <= 1 ? (
            <p className="text-sm">This thread has one topic — nothing to split.</p>
          ) : (
            <div className="space-y-3">
              {groups.map((group) => (
                <div key={group.meetingId}>
                  <p className="text-xs font-semibold">
                    {group.title ?? 'Untitled meeting'}{' '}
                    <span className="font-mono text-[10px] font-normal text-muted-foreground">
                      {groupDate(group.occurredAt)}
                    </span>
                  </p>
                  <ul className="mt-1 space-y-1">
                    {group.topics.map((topic) => (
                      <li key={topic.topicId}>
                        <label className="flex items-center gap-2 text-sm">
                          <input
                            type="checkbox"
                            checked={checked.has(topic.topicId)}
                            onChange={() => toggle(topic.topicId)}
                          />
                          <span>{topic.name}</span>
                          <span className="font-mono text-[10px] text-muted-foreground">
                            {topic.linkedBy}
                          </span>
                        </label>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          )}

          <input
            value={splitName}
            onChange={(event) => setSplitName(event.target.value)}
            aria-label="Name for the new thread"
            placeholder="Name for the new thread"
            disabled={totalTopics <= 1}
            className="mt-3 h-8 w-full rounded-md border border-white/34 bg-transparent px-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
          <div className="mt-2 flex gap-2 text-xs">
            <button
              type="submit"
              disabled={busy || !splitReady}
              className="mm-focusable min-h-6 rounded-md bg-primary px-2 text-primary-foreground disabled:opacity-50"
            >
              {busy ? 'Splitting…' : 'Split'}
            </button>
            <button
              type="button"
              onClick={() => close('split')}
              className="mm-focusable min-h-6 rounded-md border border-white/34 px-2"
            >
              Cancel
            </button>
          </div>
        </form>
      ) : null}

      {failure !== null ? <Refusal failure={failure} /> : null}
    </div>
  )
}
