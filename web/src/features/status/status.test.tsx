import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { StatusIndicator } from './StatusIndicator'
import { StatusPage } from './StatusPage'
import { degradedRows, POLL_INTERVAL_MS, type SystemStatus } from './status'

const EXTRACTION_PRIMARY = 'ollama/gpt-oss:120b'
const EXTRACTION_FALLBACK = 'openrouter/example:free'

function ok(id: string, label: string) {
  return { id, label, state: 'ok' as const, detail: `${label} answering`, remediation: null }
}

function healthy(overrides: Partial<SystemStatus> = {}): SystemStatus {
  return {
    generatedAt: '2026-08-21T12:00:00Z',
    overall: 'ok',
    api: ok('api', 'api'),
    stores: [ok('postgres', 'Postgres'), ok('neo4j', 'Neo4j'), ok('meilisearch', 'Meilisearch')],
    llmRoles: [
      {
        role: 'extraction',
        model: EXTRACTION_PRIMARY,
        fallback: EXTRACTION_FALLBACK,
        provider: 'ollama',
        keyState: 'not-required',
        state: 'ok',
        detail: `\`llm.roles.extraction\` (${EXTRACTION_PRIMARY}): endpoint answering`,
        remediation: null,
      },
      {
        role: 'chat',
        model: 'openai/gpt-5.2',
        fallback: null,
        provider: 'openai',
        keyState: 'present',
        state: 'ok',
        detail: '`llm.roles.chat` (openai/gpt-5.2): key present and verified',
        remediation: null,
      },
    ],
    worker: {
      state: 'running',
      jobs: { done: 28 },
      stageBacklog: {},
      detail: 'worker is running; 0 job(s) in flight or queued',
      remediation: null,
    },
    ...overrides,
  }
}

const CHAT_INVALID = {
  role: 'chat',
  model: 'openai/gpt-5.2',
  fallback: null,
  provider: 'openai',
  keyState: 'invalid' as const,
  state: 'degraded' as const,
  detail:
    '`llm.roles.chat` (openai/gpt-5.2): OPENAI_API_KEY is invalid — the provider refused the key (HTTP 401)',
  remediation:
    'set a valid OPENAI_API_KEY in .env and restart the api (`make api`); until then requests on this binding fail',
}

/**
 * The stopped-worker remediation exactly as the server composes it
 * (`server/meetingminer/api/status.py` `_worker_stopped_remediation`): current
 * paused work and the binding this API process loaded. It names the same
 * extraction binding `healthy()`'s `llmRoles[0]` carries — `degraded()`
 * inherits that row, so a fixture naming a different model here would be a
 * payload the server cannot emit.
 */
const WORKER_STOPPED_AUTHORED_PROSE = [
  'leaving it stopped is the current deliberate state; 3 job(s) are currently paused.' +
    " For the worker's only `llm.roles.*` call, this API process has loaded" +
    ' `llm.roles.extraction` (',
  ') with `extraction.fallback` (',
  '). A newly started worker reloads `config.yaml`, so its loaded binding may differ.' +
    ' This page only reports; it never starts, restarts, or resumes anything.',
] as const
const WORKER_STOPPED_REMEDIATION =
  WORKER_STOPPED_AUTHORED_PROSE[0] +
  EXTRACTION_PRIMARY +
  WORKER_STOPPED_AUTHORED_PROSE[1] +
  EXTRACTION_FALLBACK +
  WORKER_STOPPED_AUTHORED_PROSE[2]

/**
 * The whole vocabulary of a cost claim. The server states facts about the
 * worker and renders no spend verdict — an earlier version derived one from
 * the provider prefix and told the owner a key-required model was costless —
 * so what is pinned here is the absence of the judgement, not one phrasing.
 */
const COST_VOCABULARY = ['spend', 'paid', 'free', 'no money', 'costs', 'explicit yes']

function degraded(): SystemStatus {
  const base = healthy()
  return {
    ...base,
    overall: 'degraded',
    llmRoles: [base.llmRoles[0], CHAT_INVALID],
    worker: {
      state: 'stopped',
      jobs: { queued: 3, done: 28 },
      stageBacklog: { extract: 3 },
      detail: 'worker is stopped — deliberately, with 3 paused job(s) in the backlog',
      remediation: WORKER_STOPPED_REMEDIATION,
    },
  }
}

function stubFetch(...payloads: Array<SystemStatus>) {
  let call = 0
  const fetchMock = vi.fn(() => {
    const payload = payloads[Math.min(call, payloads.length - 1)]
    call += 1
    return Promise.resolve(
      new Response(JSON.stringify(payload), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('StatusPage', () => {
  it('renders every dependency and says so when everything is healthy', async () => {
    stubFetch(healthy())
    render(<StatusPage />)

    expect(await screen.findByText('everything healthy')).toBeInTheDocument()
    expect(screen.getByText('Postgres')).toBeInTheDocument()
    expect(screen.getByText('Neo4j')).toBeInTheDocument()
    expect(screen.getByText('Meilisearch')).toBeInTheDocument()
    expect(screen.getByText('llm.roles.chat')).toBeInTheDocument()
    expect(screen.getByText('running')).toBeInTheDocument()
    // The read-only contract is stated on the page.
    expect(screen.getByText(/never changes or starts anything/)).toBeInTheDocument()
  })

  it('shows what is broken AND the remediation on a degraded row', async () => {
    stubFetch(degraded())
    render(<StatusPage />)

    // CAP-2: the failing dependency is named with a concrete fix, and CAP-3:
    // the binding is spelled the way the chat panel spells it.
    expect(
      await screen.findByText(/`llm\.roles\.chat` \(openai\/gpt-5\.2\): OPENAI_API_KEY is invalid/),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/set a valid OPENAI_API_KEY in \.env and restart the api/),
    ).toBeInTheDocument()
    // The stopped worker reads as deliberate and reports the current queue
    // plus which binding this API loaded — never a generic alarm, never a
    // restart prediction, and never a claim about what it costs.
    expect(screen.getByText(/deliberately, with 3 paused job\(s\)/)).toBeInTheDocument()
    const remediation = screen.getByText(/3 job\(s\) are currently paused/)
    // The API-loaded binding, primary and fallback, spelled the same way the
    // extraction role row above spells it. A new worker loads config again.
    expect(remediation).toHaveTextContent(
      `this API process has loaded \`llm.roles.extraction\` (${EXTRACTION_PRIMARY})` +
        ` with \`extraction.fallback\` (${EXTRACTION_FALLBACK})`,
    )
    expect(remediation).toHaveTextContent(/A newly started worker reloads `config\.yaml`/)
    expect(remediation).toHaveTextContent(
      /This page only reports; it never starts, restarts, or resumes anything\./,
    )
    // Identifiers are exact configuration facts and may themselves contain a
    // banned token. Apply the invariant only to server-authored prose.
    const rendered = WORKER_STOPPED_AUTHORED_PROSE.join('').toLowerCase()
    for (const word of COST_VOCABULARY) {
      expect(rendered).not.toContain(word)
    }
  })
})

describe('StatusIndicator', () => {
  it('changes state when a poll response changes, without a reload', async () => {
    vi.useFakeTimers()
    const fetchMock = stubFetch(healthy(), degraded())
    render(
      <MemoryRouter>
        <StatusIndicator />
      </MemoryRouter>,
    )

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(screen.getByText('all systems healthy')).toBeInTheDocument()

    // The next poll returns a degraded payload: the indicator flips in place.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS)
    })
    expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText('attention needed')).toBeInTheDocument()
    expect(screen.queryByText('all systems healthy')).not.toBeInTheDocument()
  })

  it('expands on click to the degraded rows and their remediations', async () => {
    stubFetch(degraded())
    render(
      <MemoryRouter>
        <StatusIndicator />
      </MemoryRouter>,
    )

    const toggle = await screen.findByRole('button', { name: /attention needed/ })
    await userEvent.click(toggle)
    expect(
      screen.getByText(/`llm\.roles\.chat` \(openai\/gpt-5\.2\): OPENAI_API_KEY is invalid/),
    ).toBeInTheDocument()
    expect(screen.getByText(/set a valid OPENAI_API_KEY in \.env/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Open system status' })).toBeInTheDocument()
  })
})

describe('degradedRows', () => {
  it('is empty for a healthy status and lists every broken dependency otherwise', () => {
    expect(degradedRows(healthy())).toEqual([])
    const rows = degradedRows(degraded())
    expect(rows.map((row) => row.id)).toEqual(['llm.roles.chat', 'worker'])
    for (const row of rows) {
      expect(row.remediation).toBeTruthy()
    }
  })
})
