import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ConfigResponse, RoleSelectionView } from '@/client/types.gen'
import { SettingsPage } from './SettingsPage'
import { changePath, labelize, matchSecretMarker } from './settings'

/**
 * The payload fixture mirrors `GET /config` — ui-1's sanitized allowlist
 * projection — field for field. The secret assertion below runs over BOTH
 * this fixture's serialization and the rendered document, so a
 * secret-bearing key name creeping into either the endpoint shape or the
 * page copy fails here first.
 */
function configFixture(): ConfigResponse {
  return {
    service: 'meetingminer',
    configVersion: 1,
    llmRoles: [
      {
        role: 'extraction',
        model: 'ollama/gpt-oss:120b',
        fallback: 'ollama/qwen3:30b',
        provider: 'ollama',
        endpoint: 'http://10.77.0.52:11434',
        fallbackEndpoint: null,
        timeoutSeconds: 900,
        numCtx: 65536,
        archSummaryPrompt:
          'You are an enterprise-architecture analyst. Turn one meeting transcript into architecture-ready analysis. Produce ## Decisions and ## Risks and open questions.',
        actionItemsPrompt:
          'You are an expert meeting analyst. Extract every action item with owners. Produce ## Action items.',
      },
      {
        role: 'chat',
        model: 'openai/gpt-5.2',
        fallback: null,
        provider: 'openai',
        endpoint: 'https://api.openai.com/v1',
        fallbackEndpoint: null,
        timeoutSeconds: null,
        numCtx: null,
        archSummaryPrompt: null,
        actionItemsPrompt: null,
      },
    ],
    providers: {
      anthropic: 'https://api.anthropic.com',
      openai: 'https://api.openai.com/v1',
      openrouter: 'https://openrouter.ai/api/v1',
      ollama: 'http://localhost:11434',
    },
    embedder: { model: 'qwen3-embedding:0.6b', dimension: 1024 },
    stt: { engine: 'mlx-whisper', model: 'mlx-community/whisper-large-v3-turbo' },
    ocr: { engine: 'apple-vision', fallback: 'tesseract' },
    diarizer: { engine: 'noop' },
    pipeline: {
      frames: { intervalSeconds: 2, jpegQuality: 3 },
      screens: {
        analysisWidth: 320,
        pixelDiffThreshold: 16,
        whitePixelLevel: 200,
        changeThreshold: 0.1,
        settleThreshold: 0.02,
        settleTextGrowthRatio: 1.5,
        settleTimeoutSeconds: 10,
        cropSurveyFrames: 24,
        cropColumnWhiteMax: 0.25,
        cropMinRegionWidth: 0.6,
        cropRowStaticRangeMax: 80,
        cropMaxBottomStrip: 0.12,
        cameraMaxWhiteFraction: 0.046,
        cameraMinSaturation: 0.292,
        lineageThreshold: 0.35,
        minSignatureTokens: 4,
        galleryMaxBlocks: 6,
        galleryMaxTextDensity: 0.02,
        slideMinBlockHeight: 0.028,
        slideMaxBlocks: 40,
      },
      align: { anchorWindowSeconds: 30, minMatchScore: 0.35, maxSegmentMs: 30000 },
      moments: { gapSeconds: 90, maxDurationMs: 600000 },
    },
    projections: {
      chunking: { chunkMaxChars: 1800, chunkOverlapTurns: 2 },
      embedBatchSize: 32,
      momentsIndex: {
        searchableAttributes: ['title', 'preview'],
        filterableAttributes: ['corpus', 'meetingId'],
        sortableAttributes: ['startedAt'],
        rankingRules: ['words', 'typo', 'proximity'],
      },
      chunksIndex: {
        searchableAttributes: ['text'],
        filterableAttributes: ['corpus'],
        sortableAttributes: [],
        rankingRules: ['words', 'typo'],
      },
      synonyms: { adr: ['architecture decision record'] },
    },
    api: {
      jobEventsPollSeconds: 2,
      jobEventsHeartbeatSeconds: 15,
      search: {
        defaultLimit: 20,
        maxLimit: 50,
        semanticRatio: 0.5,
        cropLength: 30,
        semanticScoreFloor: 0.55,
      },
      chat: { retrievalLimit: 12, traversalRowLimit: 200 },
    },
    stores: {
      postgres: { host: 'localhost', port: 5433, database: 'meetingminer', user: 'meetingminer' },
      neo4j: { uri: 'bolt://localhost:7687', user: 'neo4j' },
      meilisearch: { url: 'http://localhost:7700' },
    },
  }
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

/**
 * Routes the page's three reads. `GET /config` is this file's subject; the two
 * the model picker makes (story 8.3) are answered with an empty catalog unless
 * a test asks otherwise, so the assertions below stay about the declared
 * stack. `ModelRoles.test.tsx` is where the picker itself is tested.
 */
function stubConfigFetch(payload: ConfigResponse, roles: Array<RoleSelectionView> = []) {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: unknown) => {
      const url = input instanceof Request ? new URL(input.url).pathname : String(input)
      if (url.endsWith('/settings/models')) return Promise.resolve(jsonResponse({ roles }))
      if (url.endsWith('/status')) {
        return Promise.resolve(
          jsonResponse({
            generatedAt: '2026-08-31T09:00:00Z',
            overall: 'ok',
            api: { id: 'api', label: 'api', state: 'ok', detail: '', remediation: null },
            stores: [],
            llmRoles: [],
            worker: {
              state: 'running',
              jobs: {},
              stageBacklog: {},
              detail: '',
              remediation: null,
            },
          }),
        )
      }
      return Promise.resolve(jsonResponse(payload))
    }),
  )
}

function renderSettings() {
  return render(
    <MemoryRouter>
      <SettingsPage />
    </MemoryRouter>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Settings', () => {
  it('renders every section of the declared stack from the sanitized payload', async () => {
    stubConfigFetch(configFixture())
    renderSettings()

    expect(await screen.findByText('LLM roles')).toBeInTheDocument()
    // Role bindings: model, fallback, endpoint, context, timeout.
    expect(screen.getByText('llm.roles.extraction')).toBeInTheDocument()
    expect(screen.getByText('ollama/gpt-oss:120b')).toBeInTheDocument()
    expect(screen.getByText('ollama/qwen3:30b')).toBeInTheDocument()
    expect(screen.getByText('http://10.77.0.52:11434')).toBeInTheDocument()
    expect(screen.getByText('65536')).toBeInTheDocument()
    expect(screen.getByText('900')).toBeInTheDocument()
    // Both extraction prompt texts render, complete.
    expect(screen.getByText(/enterprise-architecture analyst/)).toBeInTheDocument()
    expect(screen.getByText(/expert meeting analyst/)).toBeInTheDocument()
    // The remaining sections.
    expect(screen.getByText('Embedder')).toBeInTheDocument()
    expect(screen.getByText('qwen3-embedding:0.6b')).toBeInTheDocument()
    expect(screen.getByText('Speech, vision, and speakers')).toBeInTheDocument()
    expect(screen.getByText('mlx-whisper')).toBeInTheDocument()
    expect(screen.getByText('Pipeline capture thresholds')).toBeInTheDocument()
    expect(screen.getByText('pixel diff threshold')).toBeInTheDocument()
    expect(screen.getByText('API search and chat knobs')).toBeInTheDocument()
    expect(screen.getByText('Projections')).toBeInTheDocument()
    expect(screen.getByText('Store coordinates')).toBeInTheDocument()
    expect(screen.getByText('http://localhost:7700')).toBeInTheDocument()
  })

  it('states the change path on every section and offers no edit affordance', async () => {
    stubConfigFetch(configFixture())
    renderSettings()

    await screen.findByText('LLM roles')
    // Every section carries a change-path sentence.
    const paths = screen.getAllByText(/To change: edit config\.yaml, then restart/)
    expect(paths.length).toBe(7)
    // The projections section additionally names `make rebuild`.
    expect(screen.getByText(/additionally need `make rebuild`/)).toBeInTheDocument()
    // The page-level contract is stated, and it names its one exception:
    // story 8.3's model selection is stored by the api, not a file edit.
    expect(
      screen.getByText(/Everything on this page is read-only except the model bound/),
    ).toBeInTheDocument()
    expect(screen.getByText(/no other edit control exists/)).toBeInTheDocument()
    // Still no free-text edit of the declared stack, and the only controls on
    // the page are the model options — this fixture's `GET /settings/models`
    // stub serves no role, so there are none of those either.
    expect(screen.queryAllByRole('textbox')).toHaveLength(0)
    expect(screen.queryAllByRole('button')).toHaveLength(0)
    // It relates to /status instead of duplicating it.
    expect(screen.getByRole('link', { name: 'system status' })).toHaveAttribute(
      'href',
      '/status',
    )
  })

  it('mounts the model picker with the roles the api offers for selection', async () => {
    stubConfigFetch(configFixture(), [
      {
        role: 'chat',
        catalog: [
          { binding: 'openai/gpt-5.2', label: 'GPT-5.2', provider: 'openai' },
          { binding: 'ollama/gpt-oss:120b', label: 'GPT-OSS 120B (local)', provider: 'ollama' },
        ],
        default: 'openai/gpt-5.2',
        fileBinding: 'openai/gpt-5.2',
        selected: null,
        effectiveBinding: 'openai/gpt-5.2',
        provider: 'openai',
        source: 'file-default',
        staleSelection: null,
        staleReason: null,
      },
    ])
    renderSettings()

    expect(await screen.findByText('Model per role')).toBeInTheDocument()
    expect(
      await screen.findByRole('listbox', { name: 'Model bound to the chat role' }),
    ).toBeInTheDocument()
    expect(screen.getAllByRole('option')).toHaveLength(2)
    // The judge is file-only (story 8.2) and the api does not serve it here.
    expect(document.body.textContent).not.toMatch(/judge/i)
  })

  it('exposes no secret-bearing key name or value — payload fixture and rendered page', async () => {
    const fixture = configFixture()
    // The fixture serialization first: the endpoint contract is that no
    // secret-bearing key (API keys, store logins, the MEILI master key) is
    // in the payload shape at all.
    expect(matchSecretMarker(JSON.stringify(fixture))).toBeNull()

    stubConfigFetch(fixture)
    renderSettings()
    await screen.findByText('LLM roles')
    // Then the whole rendered document, prompts and copy included.
    expect(matchSecretMarker(document.body.textContent ?? '')).toBeNull()
  })

  it('names the api and the fix when the config read fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.reject(new Error('connection refused'))),
    )
    renderSettings()

    expect(
      await screen.findByText(/cannot read the configuration from .*connection refused/),
    ).toBeInTheDocument()
    expect(screen.getByText(/start the api/)).toBeInTheDocument()
  })
})

describe('matchSecretMarker', () => {
  it('catches secret-bearing key names across casings and separators', () => {
    expect(matchSecretMarker('OPENAI_API_KEY=sk-live')).toBe('apikey')
    expect(matchSecretMarker('meiliMasterKey')).toBe('meili_master_key')
    expect(matchSecretMarker('postgres password')).toBe('password')
    expect(matchSecretMarker('model: ollama/gpt-oss:120b')).toBeNull()
  })
})

describe('labelize', () => {
  it('spaces camelCase for the threshold tables', () => {
    expect(labelize('pixelDiffThreshold')).toBe('pixel diff threshold')
    expect(labelize('numCtx')).toBe('num ctx')
  })
})

describe('changePath', () => {
  it('adds make rebuild only when asked', () => {
    expect(changePath('the api (`make api`)')).not.toMatch(/rebuild/)
    expect(
      changePath('the worker (`make worker`)', { rebuild: true }),
    ).toMatch(/make rebuild/)
  })
})
