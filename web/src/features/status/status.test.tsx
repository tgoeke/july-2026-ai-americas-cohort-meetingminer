import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { StatusIndicator } from './StatusIndicator'
import { StatusPage } from './StatusPage'
import {
  attributionLine,
  degradedRows,
  POLL_INTERVAL_MS,
  sourceLabel,
  type LlmRoleStatus,
  type ProviderStatus,
  type SystemStatus,
} from './status'

const EXTRACTION_PRIMARY = 'ollama/gpt-oss:120b'
const EXTRACTION_FALLBACK = 'openrouter/example:free'

function ok(id: string, label: string) {
  return { id, label, state: 'ok' as const, detail: `${label} answering`, remediation: null }
}

/**
 * The attribution the server composes for a role the api does *not* call
 * (`server/meetingminer/api/status.py` `_role_attribution`). Carried verbatim
 * in the fixture because it is the sentence the 2026-08-31 incident bought:
 * the api and the worker hold independent `config.yaml` snapshots, so a
 * binding shown here describes the api process and nothing else.
 */
const EXTRACTION_ATTRIBUTION =
  'Read by the api process, which does not call `llm.roles.extraction` — the' +
  " worker does, from its own `config.yaml` snapshot and its own resolution of" +
  " the stored selection. This row is the api process's snapshot, not the" +
  " worker's, and the two disagree until both are restarted after a" +
  ' `config.yaml` edit.'

const CHAT_ATTRIBUTION =
  'Read by the api process, which is also the process that calls' +
  ' `llm.roles.chat`: this is the binding the next chat call from this' +
  ' process uses.'

/** The file half of a role binding, as the server serves it beside the active one. */
function fileDefault(binding: string) {
  return {
    source: 'file-default' as const,
    defaultBinding: binding,
    fileBinding: binding,
    selected: null,
    staleSelection: null,
    staleReason: null,
    observedBy: 'api',
  }
}

function providerOk(provider: string): ProviderStatus {
  return {
    provider,
    keyState: 'present',
    detail: `${provider} (https://example.invalid): key present and verified`,
    remediation: null,
    state: 'ok',
    observedBy: 'api',
  }
}

function healthy(overrides: Partial<SystemStatus> = {}): SystemStatus {
  return {
    generatedAt: '2026-08-21T12:00:00Z',
    overall: 'ok',
    observedBy: {
      process: 'api',
      configPath: '/repo/config.yaml',
      configLoadedAt: '2026-08-21T11:00:00Z',
      catalogNote:
        'Every binding, endpoint and key state below is the api process’s own' +
        ' reading, loaded it at startup.',
      selectionNote:
        'A stored selection applies with no restart; restart the api and the' +
        ' worker together after a `config.yaml` edit.',
    },
    api: ok('api', 'api'),
    stores: [ok('postgres', 'Postgres'), ok('neo4j', 'Neo4j'), ok('meilisearch', 'Meilisearch')],
    providers: [providerOk('ollama'), providerOk('openai')],
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
        ...fileDefault(EXTRACTION_PRIMARY),
        servedBy: 'worker',
        attribution: EXTRACTION_ATTRIBUTION,
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
        ...fileDefault('openai/gpt-5.2'),
        servedBy: 'api',
        attribution: CHAT_ATTRIBUTION,
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

const CHAT_INVALID: LlmRoleStatus = {
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
  ...fileDefault('openai/gpt-5.2'),
  servedBy: 'api',
  attribution: CHAT_ATTRIBUTION,
}

const OPENAI_KEY_INVALID: ProviderStatus = {
  provider: 'openai',
  keyState: 'invalid',
  detail:
    'openai (https://api.openai.com/v1): OPENAI_API_KEY is invalid — the provider refused the key (HTTP 401)',
  remediation:
    'set a valid OPENAI_API_KEY in .env and restart the api (`make api`) and the worker; until then requests on this provider fail',
  state: 'degraded',
  observedBy: 'api',
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
    providers: [providerOk('ollama'), OPENAI_KEY_INVALID],
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
    // The role row's own remediation ends "on this binding"; the provider row
    // for the same key ends "on this provider". Both are rendered, and each
    // assertion names the one it means.
    expect(
      screen.getByText(
        /set a valid OPENAI_API_KEY in \.env and restart the api .*requests on this binding fail/,
      ),
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
    expect(screen.getByText('api-observed dependencies healthy')).toBeInTheDocument()

    // The next poll returns a degraded payload: the indicator flips in place.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS)
    })
    expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText('attention needed')).toBeInTheDocument()
    expect(screen.queryByText('api-observed dependencies healthy')).not.toBeInTheDocument()
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
    expect(
      screen.getByText(/set a valid OPENAI_API_KEY in \.env.*requests on this binding fail/),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Open system status' })).toBeInTheDocument()
  })
})

describe('degradedRows', () => {
  it('is empty for a healthy status and lists every broken dependency otherwise', () => {
    expect(degradedRows(healthy())).toEqual([])
    const rows = degradedRows(degraded())
    expect(rows.map((row) => row.id)).toEqual([
      'provider.openai',
      'llm.roles.chat',
      'worker',
    ])
    for (const row of rows) {
      expect(row.remediation).toBeTruthy()
    }
  })
})

describe('provider health on the status surface (story 8.2a)', () => {
  it('names the provider and its remediation on the page', async () => {
    stubFetch(degraded())
    render(<StatusPage />)

    // FR39: key validity per configured provider, with the fix, before any
    // question is asked. The provider is named on its own row — not only
    // inside whichever role happens to bind it.
    expect(await screen.findByText('openai')).toBeInTheDocument()
    expect(
      screen.getByText(/openai \(https:\/\/api\.openai\.com\/v1\): OPENAI_API_KEY is invalid/),
    ).toBeInTheDocument()
    expect(
      screen.getByText(
        /set a valid OPENAI_API_KEY in \.env and restart the api \(`make api`\) and the worker/,
      ),
    ).toBeInTheDocument()
  })

  it('names the provider and its remediation in the chrome indicator', async () => {
    stubFetch(degraded())
    render(
      <MemoryRouter>
        <StatusIndicator />
      </MemoryRouter>,
    )

    const toggle = await screen.findByRole('button', { name: /attention needed/ })
    await userEvent.click(toggle)
    expect(screen.getByText(/openai \(https:\/\/api\.openai\.com\/v1\)/)).toBeInTheDocument()
    expect(
      screen.getByText(/set a valid OPENAI_API_KEY in \.env.*requests on this provider fail/),
    ).toBeInTheDocument()
  })

  it('renders no key material anywhere, whichever branch is rendered', async () => {
    // The server is what guarantees this (`test_api_status.py` scans the
    // payload for windows of every secret); the surface's own obligation is
    // never to reconstruct or echo one. Rendering both branches and scanning
    // the DOM is how that stays true as rows are added here.
    stubFetch(degraded())
    const { container } = render(<StatusPage />)
    await screen.findByText('openai')
    const rendered = container.textContent ?? ''
    for (const fragment of ['sk-', 'API_KEY=', 'Bearer ']) {
      expect(rendered).not.toContain(fragment)
    }
  })
})

describe('whose view the surface reports (story 8.2a, AD-10 as amended)', () => {
  it('attributes every reading to the process that answered, on the page', async () => {
    stubFetch(healthy())
    render(<StatusPage />)

    // The reading is the api process's, out of the file the api loaded.
    expect(await screen.findByText(/Read by the api process, from \/repo\/config\.yaml/)).toBeInTheDocument()
    // The extraction row says the worker makes that call from its own
    // snapshot — the exact failure of 2026-08-31, said out loud.
    expect(screen.getByText(EXTRACTION_ATTRIBUTION)).toBeInTheDocument()
    // And the row for the role this process does call says that instead.
    expect(screen.getByText(CHAT_ATTRIBUTION)).toBeInTheDocument()
  })

  it('attributes the chrome indicator too, healthy or not', async () => {
    stubFetch(healthy())
    render(
      <MemoryRouter>
        <StatusIndicator />
      </MemoryRouter>,
    )

    const toggle = await screen.findByRole('button', { name: /api-observed dependencies healthy/ })
    await userEvent.click(toggle)
    expect(
      screen.getByText('Every dependency observed by this api process is healthy.'),
    ).toBeInTheDocument()
    // A summary may drop rows; it may not drop whose reading it is summarising.
    expect(
      screen.getByText(/Bindings and key states below describe this process only/),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/the worker holds its own snapshot this page cannot observe/),
    ).toBeInTheDocument()
  })

  it('never lets one answer stand for both processes', () => {
    const line = attributionLine(healthy())
    expect(line).toContain('Read by the api process')
    expect(line).toContain('describe this process only')
    // The wording rule from the acceptance criterion, applied to the one
    // sentence this module authors rather than relays.
    for (const phrase of ['the system is', 'the system uses', 'both processes are']) {
      expect(line.toLowerCase()).not.toContain(phrase)
    }
  })
})

describe('sourceLabel', () => {
  const chat = healthy().llmRoles[1]

  it('says a selection is in force and still names the file default', () => {
    expect(
      sourceLabel({
        ...chat,
        source: 'selection',
        selected: 'ollama/gpt-oss:120b',
        model: 'ollama/gpt-oss:120b',
      }),
    ).toBe('in force by your selection (file default: openai/gpt-5.2)')
  })

  it('names a stored choice that was not applied', () => {
    expect(
      sourceLabel({
        ...chat,
        source: 'file-default',
        staleSelection: 'openrouter/withdrawn',
        staleReason: 'it is no longer in this role’s catalog',
      }),
    ).toContain('your choice openrouter/withdrawn was not applied')
  })

  it('says the binding in force could not be read rather than showing the default as in force', () => {
    // AD-18: with Postgres down the api cannot read the selection. Reporting
    // the file default as if it were in force would be the surface claiming a
    // state it cannot support.
    expect(sourceLabel({ ...chat, source: 'unknown' })).toBe(
      'the binding in force could not be read',
    )
  })
})
