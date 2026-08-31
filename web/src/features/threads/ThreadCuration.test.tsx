import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { canSplit, groupDate, ThreadCuration } from './ThreadCuration'
import type { ThreadSummary } from './threadsApi'

/**
 * Thread curation from the row: Rename · Merge into… · Split… (story 10.2a).
 *
 * The api's own suite proves the correction survives the next re-derivation;
 * these tests prove the three gestures reach it, that a refusal is shown as a
 * refusal rather than drawn as a success, and that the checklist's rule —
 * at least one topic and fewer than all — is stated to the user before the
 * request rather than only enforced after it.
 */

const THREAD: ThreadSummary = {
  threadId: 'th-a',
  name: 'retrieval split',
  mentionCount: 12,
  meetingCount: 3,
  firstMentionAt: '2026-03-01T00:00:00Z',
  lastMentionAt: '2026-08-21T00:00:00Z',
  colorOrdinal: 1,
  nameIsCurated: false,
}

const OTHER: ThreadSummary = { ...THREAD, threadId: 'th-b', name: 'retrieval-split', colorOrdinal: 2 }

const TOPICS = {
  meetings: [
    {
      meetingId: 'm-1',
      title: 'Retrieval bake-off review',
      occurredAt: '2026-05-04T13:00:00Z',
      topics: [
        { topicId: 't-1', name: 'judge bake-off', linkedBy: 'seed' },
        { topicId: 't-2', name: 'run artifacts', linkedBy: 'normalized-name' },
      ],
    },
    {
      meetingId: 'm-2',
      title: 'Eval harness runbook',
      occurredAt: '2026-07-22T09:30:00Z',
      topics: [{ topicId: 't-3', name: 'immutable run folders', linkedBy: 'embedding-similarity' }],
    },
  ],
}

interface Served {
  topics?: unknown
  writeStatus?: number
  writeBody?: unknown
}

let served: Served = {}
let calls: Array<{ url: string; method: string; body: unknown }> = []

function response(payload: unknown, status = 200) {
  return {
    ok: status < 400,
    status,
    statusText: status === 200 ? 'OK' : 'Error',
    text: async () => JSON.stringify(payload),
  } as unknown as Response
}

const CURATED = {
  threadId: 'th-new',
  name: 'judge bake-off',
  derivedName: 'judge bake-off',
  nameIsCurated: true,
  colorOrdinal: 7,
  mergedIntoThreadId: null,
}

beforeEach(() => {
  served = {}
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      calls.push({
        url,
        method,
        body: init?.body === undefined ? null : JSON.parse(String(init.body)),
      })
      if (method === 'GET') return Promise.resolve(response(served.topics ?? TOPICS))
      const status = served.writeStatus ?? 200
      if (status !== 200 && status !== 201) {
        return Promise.resolve(
          response(
            served.writeBody ?? {
              type: 'urn:meetingminer:problem:already-merged',
              title: 'Conflict',
              status,
              detail: 'thread th-a was merged away and can no longer be renamed directly',
            },
            status,
          ),
        )
      }
      return Promise.resolve(response(served.writeBody ?? CURATED, status))
    }),
  )
})

afterEach(() => vi.unstubAllGlobals())

function mount(thread: ThreadSummary = THREAD) {
  const onCurated = vi.fn()
  render(
    <ThreadCuration thread={thread} mergeTargets={[OTHER]} onCurated={onCurated} />,
  )
  return onCurated
}

const writes = () => calls.filter((call) => call.method !== 'GET')

// --- the pure rules --------------------------------------------------------

describe('canSplit', () => {
  it('needs at least one topic, fewer than all of them, and a name', () => {
    expect(canSplit(new Set(), 3, 'x')).toBe(false)
    expect(canSplit(new Set(['a']), 3, '')).toBe(false)
    expect(canSplit(new Set(['a']), 3, '  ')).toBe(false)
    expect(canSplit(new Set(['a']), 3, 'x')).toBe(true)
    // Every topic is a rename, not a split: it would empty the original
    // thread and burn a colour ordinal to do what Rename does without either.
    expect(canSplit(new Set(['a', 'b', 'c']), 3, 'x')).toBe(false)
  })
})

it('prints a meeting group header date from its instant', () => {
  expect(groupDate('2026-05-04T13:00:00Z')).toBe('2026-05-04')
})

// --- provenance ------------------------------------------------------------

it('says whether the name is curated or machine-derived', async () => {
  mount()
  expect(screen.getByText('machine-derived')).toBeInTheDocument()
  screen.getByText('machine-derived').remove()
  mount({ ...THREAD, nameIsCurated: true })
  expect(await screen.findByText('curated')).toBeInTheDocument()
})

// --- rename ----------------------------------------------------------------

it('renames a thread and re-reads the list', async () => {
  const user = userEvent.setup()
  const onCurated = mount()
  await user.click(screen.getByRole('button', { name: 'Rename' }))
  const input = screen.getByRole('textbox', { name: /new name for retrieval split/i })
  await user.clear(input)
  await user.type(input, 'File transfer cutover')
  await user.click(screen.getByRole('button', { name: 'Save' }))

  await waitFor(() => expect(writes()).toHaveLength(1))
  expect(writes()[0].method).toBe('PATCH')
  expect(writes()[0].url).toContain('/threads/th-a')
  expect(writes()[0].body).toEqual({ name: 'File transfer cutover' })
  await waitFor(() => expect(onCurated).toHaveBeenCalledTimes(1))
})

it('offers the machine name back only for a thread that carries a curated one', async () => {
  const user = userEvent.setup()
  mount()
  await user.click(screen.getByRole('button', { name: 'Rename' }))
  expect(screen.queryByRole('button', { name: /use the machine name/i })).toBeNull()
})

it('clears a curated name by sending null, restoring whatever the machine now says', async () => {
  const user = userEvent.setup()
  mount({ ...THREAD, nameIsCurated: true })
  await user.click(screen.getByRole('button', { name: 'Rename' }))
  await user.click(screen.getByRole('button', { name: /use the machine name/i }))
  await waitFor(() => expect(writes()).toHaveLength(1))
  expect(writes()[0].body).toEqual({ name: null })
})

// --- merge -----------------------------------------------------------------

it('merges into another thread and never offers itself as the target', async () => {
  const user = userEvent.setup()
  const onCurated = mount()
  await user.click(screen.getByRole('button', { name: 'Merge into…' }))
  const select = screen.getByRole('combobox', { name: /merge retrieval split into/i })
  expect(within(select).queryByRole('option', { name: 'retrieval split' })).toBeNull()
  await user.selectOptions(select, 'th-b')
  await user.click(screen.getByRole('button', { name: 'Merge' }))

  await waitFor(() => expect(writes()).toHaveLength(1))
  expect(writes()[0].method).toBe('POST')
  expect(writes()[0].url).toContain('/threads/th-a/merge')
  expect(writes()[0].body).toEqual({ intoThreadId: 'th-b' })
  await waitFor(() => expect(onCurated).toHaveBeenCalled())
  expect(onCurated).toHaveBeenCalledWith(CURATED, 'merge')
})

it('keeps the merge panel open when a malformed success body violates the contract', async () => {
  const user = userEvent.setup()
  served.writeBody = { ...CURATED, nameIsCurated: 'yes' }
  const onCurated = mount()
  await user.click(screen.getByRole('button', { name: 'Merge into…' }))
  await user.selectOptions(
    screen.getByRole('combobox', { name: /merge retrieval split into/i }),
    'th-b',
  )
  await user.click(screen.getByRole('button', { name: 'Merge' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('nameIsCurated')
  expect(screen.getByRole('combobox', { name: /merge retrieval split into/i })).toHaveValue('th-b')
  expect(onCurated).not.toHaveBeenCalled()
})

it('cannot merge before a target is chosen', async () => {
  const user = userEvent.setup()
  mount()
  await user.click(screen.getByRole('button', { name: 'Merge into…' }))
  expect(screen.getByRole('button', { name: 'Merge' })).toBeDisabled()
})

// --- split -----------------------------------------------------------------

it('lists the thread topics grouped by meeting and splits the checked ones', async () => {
  const user = userEvent.setup()
  const onCurated = mount()
  await user.click(screen.getByRole('button', { name: 'Split…' }))

  // The whole span, not the canvas window: a checklist that omitted topics
  // outside the visible window would make "split off these" mean something
  // other than what the user could see.
  await waitFor(() => expect(calls[0].url).toContain('level=meetings'))
  expect(calls[0].url).not.toContain('from=')

  expect(await screen.findByText('Retrieval bake-off review')).toBeInTheDocument()
  expect(screen.getByText('2026-05-04')).toBeInTheDocument()
  expect(screen.getByText('Eval harness runbook')).toBeInTheDocument()

  const name = screen.getByRole('textbox', { name: /name for the new thread/i })
  await user.type(name, 'judge bake-off')
  // A name with nothing checked is not yet a split.
  expect(screen.getByRole('button', { name: 'Split' })).toBeDisabled()

  await user.click(screen.getByRole('checkbox', { name: /judge bake-off/i }))
  await user.click(screen.getByRole('button', { name: 'Split' }))

  await waitFor(() => expect(writes()).toHaveLength(1))
  expect(writes()[0].url).toContain('/threads/th-a/split')
  expect(writes()[0].body).toEqual({ topicIds: ['t-1'], name: 'judge bake-off' })
  await waitFor(() => expect(onCurated).toHaveBeenCalled())
})

it('refuses to split every topic away, which is a rename', async () => {
  const user = userEvent.setup()
  mount()
  await user.click(screen.getByRole('button', { name: 'Split…' }))
  await screen.findByText('Retrieval bake-off review')
  await user.type(screen.getByRole('textbox', { name: /name for the new thread/i }), 'all')
  for (const box of screen.getAllByRole('checkbox')) await user.click(box)
  expect(screen.getByRole('button', { name: 'Split' })).toBeDisabled()
  expect(writes()).toHaveLength(0)
})

it('says a one-topic thread has nothing to split', async () => {
  const user = userEvent.setup()
  served.topics = {
    meetings: [
      {
        meetingId: 'm-1',
        title: 'Only meeting',
        occurredAt: '2026-05-04T13:00:00Z',
        topics: [{ topicId: 't-1', name: 'only topic', linkedBy: 'seed' }],
      },
    ],
  }
  mount()
  await user.click(screen.getByRole('button', { name: 'Split…' }))
  expect(
    await screen.findByText('This thread has one topic — nothing to split.'),
  ).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Split' })).toBeDisabled()
})

// --- refusals --------------------------------------------------------------

it('shows a refused curation as a refusal and keeps the text the user typed', async () => {
  const user = userEvent.setup()
  served.writeStatus = 409
  const onCurated = mount()
  await user.click(screen.getByRole('button', { name: 'Rename' }))
  const input = screen.getByRole('textbox', { name: /new name for retrieval split/i })
  await user.clear(input)
  await user.type(input, 'Cutover')
  await user.click(screen.getByRole('button', { name: 'Save' }))

  const alert = await screen.findByRole('alert')
  expect(alert).toHaveTextContent(/merged away/i)
  // The attempt is not discarded: a refusal is something to correct.
  expect(screen.getByRole('textbox', { name: /new name for retrieval split/i })).toHaveValue(
    'Cutover',
  )
  // And the list is never told a correction landed when it did not.
  expect(onCurated).not.toHaveBeenCalled()
})

it('keeps the split panel and its checks open when the api refuses', async () => {
  const user = userEvent.setup()
  served.writeStatus = 409
  mount()
  await user.click(screen.getByRole('button', { name: 'Split…' }))
  await screen.findByText('Retrieval bake-off review')
  await user.type(screen.getByRole('textbox', { name: /name for the new thread/i }), 'judge')
  const box = screen.getByRole('checkbox', { name: /judge bake-off/i })
  await user.click(box)
  await user.click(screen.getByRole('button', { name: 'Split' }))

  await screen.findByRole('alert')
  expect(screen.getByRole('checkbox', { name: /judge bake-off/i })).toBeChecked()
  expect(screen.getByRole('textbox', { name: /name for the new thread/i })).toHaveValue('judge')
})

// --- keyboard --------------------------------------------------------------

it('closes a panel on Escape and returns focus to the control that opened it', async () => {
  const user = userEvent.setup()
  mount()
  const rename = screen.getByRole('button', { name: 'Rename' })
  await user.click(rename)
  const input = screen.getByRole('textbox', { name: /new name for retrieval split/i })
  await user.type(input, '{Escape}')
  await waitFor(() =>
    expect(screen.queryByRole('textbox', { name: /new name for retrieval split/i })).toBeNull(),
  )
  expect(rename).toHaveFocus()
})
