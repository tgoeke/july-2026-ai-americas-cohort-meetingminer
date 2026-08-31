import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { RoleSelectionView, StatusResponse } from '@/client/types.gen'
import { ModelRoles } from './ModelRoles'

/**
 * The Settings page's model picker (story 8.3): every role the api offers for
 * selection, with the same catalog, provider, trait and health information the
 * ask box shows.
 *
 * The judge is deliberately absent from `GET /settings/models` — it is
 * file-only until a later story wires it, and a `PUT` on it is refused by name
 * (owner decision, story 8.2). These tests hold that boundary from the client
 * side: the surface renders the roles it was served and never adds one.
 */

function roleView(overrides: Partial<RoleSelectionView> = {}): RoleSelectionView {
  return {
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
    ...overrides,
  }
}

function extractionView(): RoleSelectionView {
  return roleView({
    role: 'extraction',
    catalog: [
      { binding: 'ollama/gpt-oss:120b', label: 'GPT-OSS 120B (local)', provider: 'ollama' },
      { binding: 'ollama/qwen3:30b', label: 'Qwen3 30B (local)', provider: 'ollama' },
    ],
    default: 'ollama/gpt-oss:120b',
    fileBinding: 'ollama/gpt-oss:120b',
    selected: 'ollama/qwen3:30b',
    effectiveBinding: 'ollama/qwen3:30b',
    provider: 'ollama',
    source: 'selection',
  })
}

function statusFixture(): StatusResponse {
  return {
    generatedAt: '2026-08-31T09:00:00Z',
    overall: 'degraded',
    api: { id: 'api', label: 'api', state: 'ok', detail: '', remediation: null },
    stores: [],
    llmRoles: [
      {
        role: 'chat',
        model: 'openai/gpt-5.2',
        fallback: null,
        provider: 'openai',
        keyState: 'invalid',
        state: 'degraded',
        detail: 'OPENAI_API_KEY is invalid',
        remediation: 'set a valid OPENAI_API_KEY in .env and restart the api (`make api`)',
      },
      {
        role: 'extraction',
        model: 'ollama/gpt-oss:120b',
        fallback: null,
        provider: 'ollama',
        keyState: 'not-required',
        state: 'ok',
        detail: 'endpoint answering',
        remediation: null,
      },
    ],
    worker: { state: 'running', jobs: {}, stageBacklog: {}, detail: '', remediation: null },
  }
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      'Content-Type': status >= 400 ? 'application/problem+json' : 'application/json',
    },
  })
}

function stubApi(
  roles: Array<RoleSelectionView>,
  put?: (role: string, binding: string) => Response,
): Array<{ role: string; binding: string }> {
  const puts: Array<{ role: string; binding: string }> = []
  vi.stubGlobal('fetch', async (input: unknown) => {
    const request = input as Request
    const path = new URL(request.url).pathname
    if (path === '/settings/models') return json({ roles })
    if (path === '/status') return json(statusFixture())
    if (path.startsWith('/settings/roles/')) {
      const role = path.slice('/settings/roles/'.length)
      const body = (await request.json()) as { binding: string }
      puts.push({ role, binding: body.binding })
      const served = roles.find((entry) => entry.role === role) ?? roleView({ role })
      return put
        ? put(role, body.binding)
        : json({
            ...served,
            selected: body.binding,
            effectiveBinding: body.binding,
            provider: body.binding.split('/')[0],
            source: 'selection',
          })
    }
    throw new Error(`unexpected request to ${request.url}`)
  })
  return puts
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('ModelRoles', () => {
  it('renders exactly the roles the api serves, with no judge among them', async () => {
    stubApi([extractionView(), roleView()])
    render(<ModelRoles />)

    expect(await screen.findByText('llm.roles.extraction')).toBeInTheDocument()
    expect(screen.getByText('llm.roles.chat')).toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/judge/i)
    expect(screen.getAllByRole('listbox')).toHaveLength(2)
  })

  it('marks each role’s binding in force and says how it was arrived at', async () => {
    stubApi([extractionView(), roleView()])
    render(<ModelRoles />)

    // Extraction is a stored choice; chat inherited the file default. The two
    // are told apart rather than both presented as deliberate picks.
    expect(await screen.findByTestId('model-roles-source-extraction')).toHaveTextContent(
      'In force by your selection',
    )
    expect(screen.getByTestId('model-roles-source-chat')).toHaveTextContent(
      'Inherited from the file default in config.yaml (openai/gpt-5.2)',
    )
    const chatOptions = screen.getAllByRole('option', { selected: true })
    expect(chatOptions.map((option) => option.getAttribute('data-testid'))).toEqual([
      'model-roles-option-extraction-ollama/qwen3:30b',
      'model-roles-option-chat-openai/gpt-5.2',
    ])
  })

  it('states that the catalog needs a restart and the choice does not', async () => {
    stubApi([roleView()])
    render(<ModelRoles />)

    const snapshot = await screen.findByText(/The catalog is config\.yaml as the api read it/)
    expect(snapshot).toHaveTextContent('api restart')
    expect(snapshot).toHaveTextContent('Choosing one of the bindings below is not')
  })

  it('persists a choice for the role whose list was clicked', async () => {
    const puts = stubApi([extractionView(), roleView()])
    const user = userEvent.setup()
    render(<ModelRoles />)

    await user.click(
      await screen.findByTestId('model-roles-option-chat-ollama/gpt-oss:120b'),
    )

    await waitFor(() => expect(puts).toEqual([{ role: 'chat', binding: 'ollama/gpt-oss:120b' }]))
    await waitFor(() =>
      expect(screen.getByTestId('model-roles-source-chat')).toHaveTextContent(
        'In force by your selection',
      ),
    )
    // The other role is untouched by a sibling's selection.
    expect(screen.getByTestId('model-roles-source-extraction')).toHaveTextContent(
      'In force by your selection',
    )
  })

  it('keeps a broken binding listed, muted, with its fix, and still selectable', async () => {
    const puts = stubApi([roleView()])
    const user = userEvent.setup()
    render(<ModelRoles />)

    const broken = await screen.findByTestId('model-roles-option-chat-openai/gpt-5.2')
    expect(screen.getByTestId('model-option-health-openai/gpt-5.2')).toHaveTextContent('invalid')
    expect(screen.getByTestId('model-option-remediation-openai/gpt-5.2')).toHaveTextContent(
      'set a valid OPENAI_API_KEY in .env',
    )
    expect(broken).not.toHaveAttribute('aria-disabled')
    await user.click(broken)
    await waitFor(() => expect(puts).toEqual([{ role: 'chat', binding: 'openai/gpt-5.2' }]))
  })

  it('substitutes nothing when the api refuses a role’s choice', async () => {
    stubApi([roleView()], () =>
      json(
        {
          type: 'urn:meetingminer:problem:role-file-only',
          title: 'Unprocessable Entity',
          detail: 'the judge binding is file-only today',
        },
        422,
      ),
    )
    const user = userEvent.setup()
    render(<ModelRoles />)

    await user.click(
      await screen.findByTestId('model-roles-option-chat-ollama/gpt-oss:120b'),
    )

    const refusal = await screen.findByTestId('model-roles-refusal-chat')
    expect(refusal).toHaveTextContent('still bound to openai/gpt-5.2')
    expect(refusal).toHaveTextContent('nothing was substituted')
    expect(
      screen.getByTestId('model-roles-option-chat-openai/gpt-5.2'),
    ).toHaveAttribute('aria-selected', 'true')
  })

  it('invents no default for a role whose catalog is empty', async () => {
    stubApi([roleView({ catalog: [] })])
    render(<ModelRoles />)

    expect(await screen.findByTestId('model-roles-empty-chat')).toHaveTextContent(
      'No models configured',
    )
    expect(screen.queryByRole('listbox')).toBeNull()
  })

  it('names the api and the fix when the catalog cannot be read', async () => {
    vi.stubGlobal('fetch', () => Promise.reject(new TypeError('Failed to fetch')))
    render(<ModelRoles />)

    expect(await screen.findByTestId('model-roles-unavailable')).toHaveTextContent(
      /cannot read the model catalog from .*Failed to fetch/,
    )
    expect(screen.getByText(/start the api/)).toBeInTheDocument()
  })
})
