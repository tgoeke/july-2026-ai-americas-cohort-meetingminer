import { StrictMode, useState } from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { RoleSelectionView, StatusResponse } from '@/client/types.gen'
import { ModelRoles } from './ModelRoles'
import { ModelSelect } from './ModelSelect'

function chatRole(overrides: Partial<RoleSelectionView> = {}): RoleSelectionView {
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

function statusFixture(): StatusResponse {
  return {
    generatedAt: '2026-08-31T09:00:00Z',
    overall: 'ok',
    api: { id: 'api', label: 'api', state: 'ok', detail: '', remediation: null },
    stores: [],
    llmRoles: [],
    worker: { state: 'running', jobs: {}, stageBacklog: {}, detail: '', remediation: null },
  }
}

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

function SurfacePair() {
  const [showSettings, setShowSettings] = useState(true)
  return (
    <>
      <ModelSelect />
      {showSettings && <ModelRoles />}
      <button type="button" onClick={() => setShowSettings(false)}>
        close settings
      </button>
    </>
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('model-setting ownership across mounted surfaces', () => {
  it('updates the persistent ask trigger when Settings unmounts during its PUT', async () => {
    let resolvePut: ((response: Response) => void) | undefined
    vi.stubGlobal('fetch', async (input: unknown) => {
      const request = input as Request
      const path = new URL(request.url).pathname
      if (path === '/settings/models') return json({ roles: [chatRole()] })
      if (path === '/status') return json(statusFixture())
      if (path === '/settings/roles/chat') {
        return new Promise<Response>((resolve) => {
          resolvePut = resolve
        })
      }
      throw new Error(`unexpected request to ${request.url}`)
    })
    const user = userEvent.setup()
    render(<SurfacePair />)

    await user.click(
      await screen.findByTestId('model-roles-option-chat-ollama/gpt-oss:120b'),
    )
    await waitFor(() => expect(resolvePut).toBeTypeOf('function'))
    await user.click(screen.getByRole('button', { name: 'close settings' }))
    resolvePut?.(
      json(
        chatRole({
          selected: 'ollama/gpt-oss:120b',
          effectiveBinding: 'ollama/gpt-oss:120b',
          provider: 'ollama',
          source: 'selection',
        }),
      ),
    )

    await waitFor(() =>
      expect(screen.getByTestId('model-select-trigger')).toHaveTextContent(
        'ollama/gpt-oss:120b',
      ),
    )
  })

  it('does not add a role to a surface whose catalog read omitted it', async () => {
    let modelReads = 0
    vi.stubGlobal('fetch', async (input: unknown) => {
      const request = input as Request
      const path = new URL(request.url).pathname
      if (path === '/settings/models') {
        modelReads += 1
        return json({ roles: modelReads === 1 ? [chatRole()] : [] })
      }
      if (path === '/status') return json(statusFixture())
      if (path === '/settings/roles/chat') {
        return json(
          chatRole({
            selected: 'ollama/gpt-oss:120b',
            effectiveBinding: 'ollama/gpt-oss:120b',
            provider: 'ollama',
            source: 'selection',
          }),
        )
      }
      throw new Error(`unexpected request to ${request.url}`)
    })
    const user = userEvent.setup()
    render(
      <>
        <ModelSelect />
        <ModelRoles />
      </>,
    )

    expect(await screen.findByTestId('model-roles-none')).toBeInTheDocument()
    await user.click(await screen.findByTestId('model-select-trigger'))
    await user.click(await screen.findByTestId('model-option-ollama/gpt-oss:120b'))

    await waitFor(() =>
      expect(screen.getByTestId('model-select-trigger')).toHaveTextContent(
        'ollama/gpt-oss:120b',
      ),
    )
    expect(screen.getByTestId('model-roles-none')).toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/llm\.roles\.chat/)
  })

  it('does not let an aborted first StrictMode read overwrite the current read', async () => {
    let firstRead: ((response: Response) => void) | undefined
    let modelReads = 0
    vi.stubGlobal('fetch', async (input: unknown) => {
      const request = input as Request
      const path = new URL(request.url).pathname
      if (path === '/settings/models') {
        modelReads += 1
        if (modelReads === 1) {
          return new Promise<Response>((resolve) => {
            firstRead = resolve
          })
        }
        return json({
          roles: [
            chatRole({
              selected: 'ollama/gpt-oss:120b',
              effectiveBinding: 'ollama/gpt-oss:120b',
              provider: 'ollama',
              source: 'selection',
            }),
          ],
        })
      }
      if (path === '/status') return json(statusFixture())
      throw new Error(`unexpected request to ${request.url}`)
    })

    render(
      <StrictMode>
        <ModelSelect />
      </StrictMode>,
    )

    await waitFor(() => expect(modelReads).toBe(2))
    await waitFor(() =>
      expect(screen.getByTestId('model-select-trigger')).toHaveTextContent(
        'ollama/gpt-oss:120b',
      ),
    )
    firstRead?.(json({ roles: [chatRole()] }))

    await waitFor(() =>
      expect(screen.getByTestId('model-select-trigger')).toHaveTextContent(
        'ollama/gpt-oss:120b',
      ),
    )
    expect(screen.getByTestId('model-select-trigger')).not.toHaveTextContent('openai/gpt-5.2')
  })
})
