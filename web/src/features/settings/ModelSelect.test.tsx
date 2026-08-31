import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { RoleSelectionView, StatusResponse } from '@/client/types.gen'
import { ModelSelect } from './ModelSelect'

/**
 * The ask box's model select (story 8.3).
 *
 * Every test drives the real generated client against a stubbed `fetch`, so
 * the request shapes asserted here — `PUT /settings/roles/chat` with a
 * `binding` body — are the ones the browser would actually send. No test may
 * reach a live api, and none calls a model.
 *
 * The subjects are the four clauses that carry this story's risk: the screen
 * must not mislead about what is being called, a failed binding surfaces here
 * rather than being hidden, no other model is ever substituted for a failed
 * selection, and the judge role — file-only by owner decision (story 8.2) —
 * never appears.
 */

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

/** `openai` key missing, `ollama` reachable — the demo's own shape. */
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
        keyState: 'missing',
        state: 'degraded',
        detail: 'OPENAI_API_KEY is not set',
        remediation: 'set OPENAI_API_KEY in .env and restart the api (`make api`)',
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

interface ApiStub {
  models?: () => Response | Promise<Response>
  status?: () => Response | Promise<Response>
  put?: (binding: string) => Response | Promise<Response>
}

/** Routes the generated client's requests; records every `PUT` it made. */
function stubApi(stub: ApiStub = {}): Array<{ role: string; binding: string }> {
  const puts: Array<{ role: string; binding: string }> = []
  vi.stubGlobal('fetch', async (input: unknown) => {
    const request = input as Request
    const path = new URL(request.url).pathname
    if (path === '/settings/models') {
      return stub.models ? stub.models() : json({ roles: [chatRole()] })
    }
    if (path === '/status') {
      return stub.status ? stub.status() : json(statusFixture())
    }
    if (path.startsWith('/settings/roles/')) {
      const role = path.slice('/settings/roles/'.length)
      const body = (await request.json()) as { binding: string }
      puts.push({ role, binding: body.binding })
      return stub.put
        ? stub.put(body.binding)
        : json(
            chatRole({
              selected: body.binding,
              effectiveBinding: body.binding,
              provider: body.binding.split('/')[0],
              source: 'selection',
            }),
          )
    }
    throw new Error(`unexpected request to ${request.url}`)
  })
  return puts
}

async function openPicker() {
  const user = userEvent.setup()
  await user.click(await screen.findByTestId('model-select-trigger'))
  await screen.findByTestId('model-select-listbox')
  return user
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('ModelSelect', () => {
  it('names the role, the exact binding, the provider and its health on the trigger', async () => {
    stubApi()
    render(<ModelSelect />)

    const trigger = await screen.findByTestId('model-select-trigger')
    expect(trigger).toHaveTextContent('chat')
    expect(trigger).toHaveTextContent('openai/gpt-5.2')
    expect(trigger).toHaveTextContent('openai')
    // The accessible name carries the health word and the traits, because the
    // `●` is hidden from assistive technology.
    await waitFor(() =>
      expect(trigger).toHaveAccessibleName(
        expect.stringContaining('health missing') as unknown as string,
      ),
    )
    expect(trigger).toHaveAccessibleName(
      expect.stringContaining('remote · paid') as unknown as string,
    )
  })

  it('says local and free for the ollama entry and remote and paid for the openai one', async () => {
    stubApi()
    render(<ModelSelect />)
    await openPicker()

    expect(screen.getByTestId('model-option-openai/gpt-5.2')).toHaveTextContent('remote · paid')
    expect(screen.getByTestId('model-option-ollama/gpt-oss:120b')).toHaveTextContent(
      'local · free',
    )
    // Both spell out the binding itself: the reader can see what is called.
    expect(screen.getByTestId('model-option-ollama/gpt-oss:120b')).toHaveTextContent(
      'ollama/gpt-oss:120b',
    )
  })

  it('marks the binding in force and offers the whole catalog, unfiltered', async () => {
    stubApi()
    render(<ModelSelect />)
    await openPicker()

    const options = screen.getAllByRole('option')
    expect(options).toHaveLength(2)
    expect(options[0]).toHaveAttribute('aria-selected', 'true')
    expect(options[1]).toHaveAttribute('aria-selected', 'false')
  })

  it('renders a failed binding muted, with its remediation, and still selectable', async () => {
    const puts = stubApi()
    render(<ModelSelect />)
    const user = await openPicker()

    const broken = screen.getByTestId('model-option-openai/gpt-5.2')
    expect(screen.getByTestId('model-option-health-openai/gpt-5.2')).toHaveTextContent('missing')
    expect(screen.getByTestId('model-option-remediation-openai/gpt-5.2')).toHaveTextContent(
      'set OPENAI_API_KEY in .env and restart the api',
    )
    expect(broken.getAttribute('aria-description')).toContain('set OPENAI_API_KEY')
    // Not disabled and not hidden — the failure must surface at the ask.
    expect(broken).not.toHaveAttribute('aria-disabled')
    await user.click(broken)
    await waitFor(() => expect(puts).toEqual([{ role: 'chat', binding: 'openai/gpt-5.2' }]))
  })

  it('persists the choice and names the new binding as the one the next question uses', async () => {
    const puts = stubApi()
    render(<ModelSelect />)
    const user = await openPicker()

    await user.click(screen.getByTestId('model-option-ollama/gpt-oss:120b'))

    await waitFor(() =>
      expect(puts).toEqual([{ role: 'chat', binding: 'ollama/gpt-oss:120b' }]),
    )
    const trigger = await screen.findByTestId('model-select-trigger')
    await waitFor(() => expect(trigger).toHaveTextContent('ollama/gpt-oss:120b'))
    // No restart language anywhere on the selection path: the api stores the
    // choice and reads it per request.
    expect(document.body.textContent).not.toMatch(/restart the api to apply/i)
  })

  it('substitutes nothing when the api refuses the choice', async () => {
    const puts = stubApi({
      put: () =>
        json(
          {
            type: 'urn:meetingminer:problem:binding-not-in-catalog',
            title: 'Unprocessable Entity',
            detail: "`chat` does not offer 'ollama/gpt-oss:120b'",
          },
          422,
        ),
    })
    render(<ModelSelect />)
    const user = await openPicker()

    await user.click(screen.getByTestId('model-option-ollama/gpt-oss:120b'))

    const refusal = await screen.findByTestId('model-select-refusal')
    expect(refusal).toHaveTextContent("does not offer 'ollama/gpt-oss:120b'")
    expect(refusal).toHaveTextContent('still bound to openai/gpt-5.2')
    expect(refusal).toHaveTextContent('nothing was substituted')
    // The trigger still names the binding the api last reported, and no other
    // entry was marked in its place.
    expect(screen.getByTestId('model-select-trigger')).toHaveTextContent('openai/gpt-5.2')
    expect(screen.getAllByRole('option')[0]).toHaveAttribute('aria-selected', 'true')
    expect(puts).toHaveLength(1)
  })

  it('keeps the later of two rapid choices, whichever response lands first', async () => {
    const resolvers: Array<(response: Response) => void> = []
    stubApi({
      put: (binding) =>
        new Promise<Response>((resolve) => {
          resolvers.push((response) => resolve(response))
          void binding
        }),
    })
    render(<ModelSelect />)
    const user = await openPicker()

    await user.click(screen.getByTestId('model-option-ollama/gpt-oss:120b'))
    await user.click(screen.getByTestId('model-option-openai/gpt-5.2'))
    await waitFor(() => expect(resolvers).toHaveLength(2))

    // The SECOND request answers first, then the first answers late. The late
    // one is discarded: it belongs to a superseded generation.
    resolvers[1](
      json(
        chatRole({
          selected: 'openai/gpt-5.2',
          effectiveBinding: 'openai/gpt-5.2',
          provider: 'openai',
          source: 'selection',
        }),
      ),
    )
    await waitFor(() =>
      expect(screen.getByTestId('model-select-source')).toHaveTextContent('your selection'),
    )
    resolvers[0](
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
      expect(screen.getByTestId('model-select-trigger')).toHaveTextContent('openai/gpt-5.2'),
    )
    expect(screen.getByTestId('model-select-trigger')).not.toHaveTextContent('ollama/gpt-oss:120b')
  })

  it('moves with the arrow keys and selects with Enter', async () => {
    const puts = stubApi()
    render(<ModelSelect />)
    const user = await openPicker()

    const listbox = screen.getByTestId('model-select-listbox')
    expect(listbox).toHaveAttribute('aria-activedescendant', 'model-select-chat-option-0')
    await user.keyboard('{ArrowDown}')
    expect(listbox).toHaveAttribute('aria-activedescendant', 'model-select-chat-option-1')
    await user.keyboard('{Enter}')
    await waitFor(() =>
      expect(puts).toEqual([{ role: 'chat', binding: 'ollama/gpt-oss:120b' }]),
    )
  })

  it('closes on Escape and returns focus to the trigger', async () => {
    stubApi()
    render(<ModelSelect />)
    const user = await openPicker()

    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByTestId('model-select-listbox')).toBeNull())
    expect(screen.getByTestId('model-select-trigger')).toHaveFocus()
  })

  it('dismisses on a pointer down outside it', async () => {
    stubApi()
    render(
      <div>
        <ModelSelect />
        <button type="button">elsewhere</button>
      </div>,
    )
    const user = await openPicker()

    await user.click(screen.getByRole('button', { name: 'elsewhere' }))
    await waitFor(() => expect(screen.queryByTestId('model-select-listbox')).toBeNull())
  })

  it('reports unknown health rather than a green dot when status cannot be read', async () => {
    stubApi({ status: () => Promise.reject(new TypeError('Failed to fetch')) })
    render(<ModelSelect />)
    await openPicker()

    expect(screen.getByTestId('model-option-health-openai/gpt-5.2')).toHaveTextContent('unknown')
    expect(screen.queryByTestId('model-option-remediation-openai/gpt-5.2')).toBeNull()
    // The catalog still renders and stays selectable: choosing a model does
    // not depend on the health surface being up.
    expect(screen.getAllByRole('option')).toHaveLength(2)
  })

  it('invents no default for an empty catalog and opens nothing', async () => {
    stubApi({ models: () => json({ roles: [chatRole({ catalog: [] })] }) })
    render(<ModelSelect />)

    const trigger = await screen.findByTestId('model-select-trigger')
    expect(await screen.findByTestId('model-select-empty')).toHaveTextContent(
      'No models configured',
    )
    await userEvent.setup().click(trigger)
    expect(screen.queryByTestId('model-select-listbox')).toBeNull()
  })

  it('offers no control for a role the api does not serve — the judge stays absent', async () => {
    stubApi({ models: () => json({ roles: [chatRole({ role: 'extraction' })] }) })
    render(<ModelSelect />)

    expect(await screen.findByTestId('model-select-not-offered')).toHaveTextContent(
      'the chat role is not offered for selection',
    )
    expect(document.body.textContent).not.toMatch(/judge/i)
  })

  it('names the api and the failure when the catalog cannot be read', async () => {
    stubApi({ models: () => Promise.reject(new TypeError('Failed to fetch')) })
    render(<ModelSelect />)

    expect(await screen.findByTestId('model-select-unavailable')).toHaveTextContent(
      /cannot read the model catalog from .*Failed to fetch/,
    )
  })

  it('says a discarded selection is not in force instead of degrading quietly', async () => {
    stubApi({
      models: () =>
        json({
          roles: [
            chatRole({
              selected: 'openai/gpt-4o',
              staleSelection: 'openai/gpt-4o',
              staleReason: 'it is no longer in the catalog for this role',
            }),
          ],
        }),
    })
    render(<ModelSelect />)
    await openPicker()

    const stale = screen.getByTestId('model-select-stale')
    expect(stale).toHaveTextContent('openai/gpt-4o')
    expect(stale).toHaveTextContent('no longer in the catalog')
    expect(stale).toHaveTextContent('file default openai/gpt-5.2')
  })
})
