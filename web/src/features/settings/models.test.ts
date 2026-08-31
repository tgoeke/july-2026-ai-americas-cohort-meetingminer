import { describe, expect, it } from 'vitest'
import type { RoleSelectionView, StatusResponse } from '@/client/types.gen'
import {
  CATALOG_IS_A_STARTUP_SNAPSHOT,
  healthFor,
  healthOfRoleRow,
  isFailedHealth,
  NO_MODELS_CONFIGURED,
  optionAccessibleDescription,
  optionsFor,
  providerHealthIndex,
  providerTrait,
  roleNamed,
  rolesOf,
  selectionRefusal,
  sourceNotice,
  staleSelectionNotice,
  triggerAccessibleName,
} from './models'

/**
 * The rules behind the model picker (story 8.3), tested without rendering.
 *
 * Every one of these is a truthfulness rule rather than a formatting
 * preference: what a provider means, when an option is muted, what is said
 * after a refusal, and what is *not* claimed when the answer is not known.
 */

function role(overrides: Partial<RoleSelectionView> = {}): RoleSelectionView {
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

function statusRow(
  overrides: Partial<StatusResponse['llmRoles'][number]> = {},
): StatusResponse['llmRoles'][number] {
  return {
    role: 'chat',
    model: 'openai/gpt-5.2',
    fallback: null,
    provider: 'openai',
    keyState: 'present',
    state: 'ok',
    detail: '',
    remediation: null,
    ...overrides,
  }
}

function status(rows: Array<StatusResponse['llmRoles'][number]>): StatusResponse {
  return {
    generatedAt: '2026-08-31T09:00:00Z',
    overall: 'ok',
    api: { id: 'api', label: 'api', state: 'ok', detail: '', remediation: null },
    stores: [],
    llmRoles: rows,
    worker: { state: 'running', jobs: {}, stageBacklog: {}, detail: '', remediation: null },
  }
}

describe('providerTrait', () => {
  it('says local and free for ollama, remote and paid for the metered APIs', () => {
    expect(providerTrait('ollama')).toMatchObject({ locality: 'local', cost: 'free' })
    expect(providerTrait('openai')).toMatchObject({ locality: 'remote', cost: 'paid' })
    expect(providerTrait('anthropic')).toMatchObject({ locality: 'remote', cost: 'paid' })
    expect(providerTrait('openrouter')).toMatchObject({ locality: 'remote', cost: 'paid' })
    expect(providerTrait('ollama').sentence).toBe('local · free')
    expect(providerTrait('openai').sentence).toBe('remote · paid')
  })

  it('claims nothing for a provider it does not recognise, or for none at all', () => {
    for (const provider of ['bedrock', '', null, undefined]) {
      const trait = providerTrait(provider)
      expect(trait).toMatchObject({ locality: 'unknown', cost: 'unknown' })
      // The one thing it must never do is guess: no "local", no "free".
      expect(trait.sentence).not.toMatch(/local|free|paid|remote/)
      expect(trait.sentence).toMatch(/not known/)
    }
  })
})

describe('healthOfRoleRow', () => {
  it('maps a provider key state onto the word the picker shows', () => {
    expect(healthOfRoleRow(statusRow({ keyState: 'present', state: 'ok' })).word).toBe('ok')
    expect(
      healthOfRoleRow(statusRow({ keyState: 'not-required', state: 'ok' })).word,
    ).toBe('ok')
    expect(
      healthOfRoleRow(statusRow({ keyState: 'missing', state: 'degraded' })).word,
    ).toBe('missing')
    expect(
      healthOfRoleRow(statusRow({ keyState: 'invalid', state: 'degraded' })).word,
    ).toBe('invalid')
  })

  it('calls a present-but-degraded binding unreachable, and keeps the api’s fix', () => {
    const health = healthOfRoleRow(
      statusRow({ keyState: 'not-required', state: 'degraded', remediation: 'check the host' }),
    )
    expect(health).toEqual({ word: 'unreachable', remediation: 'check the host' })
  })

  it('drops the remediation when nothing is wrong', () => {
    expect(healthOfRoleRow(statusRow({ remediation: 'stale advice' })).remediation).toBeNull()
  })
})

describe('providerHealthIndex', () => {
  it('joins by exact provider id and keeps the worst state for a provider', () => {
    const index = providerHealthIndex(
      status([
        statusRow({ role: 'chat', provider: 'openai', keyState: 'present', state: 'ok' }),
        statusRow({
          role: 'judge',
          provider: 'openai',
          keyState: 'invalid',
          state: 'degraded',
          remediation: 'set a valid OPENAI_API_KEY in .env',
        }),
        statusRow({ role: 'extraction', provider: 'ollama', keyState: 'not-required', state: 'ok' }),
      ]),
    )
    expect(index.get('openai')).toEqual({
      word: 'invalid',
      remediation: 'set a valid OPENAI_API_KEY in .env',
    })
    expect(index.get('ollama')?.word).toBe('ok')
  })

  it('skips a row whose provider the spelling rule could not identify', () => {
    expect(providerHealthIndex(status([statusRow({ provider: null })])).size).toBe(0)
  })

  it('is empty when status could not be read — health is never assumed ok', () => {
    const index = providerHealthIndex(null)
    expect(index.size).toBe(0)
    expect(healthFor(index, 'openai')).toEqual({ word: 'unknown', remediation: null })
  })
})

describe('isFailedHealth', () => {
  it('mutes exactly the states that mean a call on this binding fails now', () => {
    expect(isFailedHealth('invalid')).toBe(true)
    expect(isFailedHealth('missing')).toBe(true)
    expect(isFailedHealth('unreachable')).toBe(true)
    // Not muted: `ok` is fine, and `unknown` is an absence of evidence, which
    // must not be rendered as evidence of a failure either.
    expect(isFailedHealth('ok')).toBe(false)
    expect(isFailedHealth('unknown')).toBe(false)
  })
})

describe('optionsFor', () => {
  const index = providerHealthIndex(
    status([
      statusRow({
        provider: 'openai',
        keyState: 'missing',
        state: 'degraded',
        remediation: 'set OPENAI_API_KEY in .env and restart the api (`make api`)',
      }),
      statusRow({ role: 'extraction', provider: 'ollama', keyState: 'not-required', state: 'ok' }),
    ]),
  )

  it('keeps the api’s catalog order and marks the binding in force', () => {
    const options = optionsFor(role(), index)
    expect(options.map((option) => option.binding)).toEqual([
      'openai/gpt-5.2',
      'ollama/gpt-oss:120b',
    ])
    expect(options[0].active).toBe(true)
    expect(options[1].active).toBe(false)
  })

  it('mutes the broken binding, keeps it in the list, and carries its fix', () => {
    const options = optionsFor(role(), index)
    expect(options[0]).toMatchObject({ muted: true, provider: 'openai' })
    expect(options[0].health.remediation).toMatch(/set OPENAI_API_KEY/)
    expect(options[1].muted).toBe(false)
    // Muted is not removed: both entries are still offered.
    expect(options).toHaveLength(2)
  })

  it('derives the trait from the served provider, never from the label', () => {
    // A label that lies about the provider changes nothing: the provider the
    // server derived is the only input to what this row claims.
    const misleading = role({
      catalog: [{ binding: 'openai/gpt-5.2', label: 'Local free model', provider: 'openai' }],
    })
    expect(optionsFor(misleading, index)[0].trait.sentence).toBe('remote · paid')
  })

  it('reports unknown health for a provider status did not name', () => {
    const other = role({
      catalog: [{ binding: 'anthropic/claude-sonnet-5', label: 'Claude Sonnet 5', provider: 'anthropic' }],
    })
    const option = optionsFor(other, index)[0]
    expect(option.health).toEqual({ word: 'unknown', remediation: null })
    expect(option.muted).toBe(false)
  })
})

describe('rolesOf and roleNamed', () => {
  it('serves exactly the roles the api sent, in order', () => {
    const payload = { roles: [role({ role: 'extraction' }), role()] }
    expect(rolesOf(payload).map((entry) => entry.role)).toEqual(['extraction', 'chat'])
    expect(roleNamed(payload, 'chat')?.role).toBe('chat')
  })

  it('never invents a role the payload omits — the judge stays absent', () => {
    const payload = { roles: [role({ role: 'extraction' }), role()] }
    expect(roleNamed(payload, 'judge')).toBeNull()
    expect(rolesOf(payload).some((entry) => entry.role === 'judge')).toBe(false)
  })

  it('reads a payload that is not this shape as no roles rather than throwing', () => {
    expect(rolesOf({ roles: undefined } as unknown as { roles: Array<RoleSelectionView> })).toEqual([])
  })
})

describe('the sentences the picker says', () => {
  it('names the binding, provider, traits and health in the trigger’s label', () => {
    const name = triggerAccessibleName(role(), { word: 'invalid', remediation: null })
    expect(name).toContain('chat role')
    expect(name).toContain('openai/gpt-5.2')
    expect(name).toContain('remote · paid')
    expect(name).toContain('health invalid')
  })

  it('describes an option with its traits and, when broken, its remediation', () => {
    const [broken] = optionsFor(
      role(),
      providerHealthIndex(
        status([
          statusRow({
            provider: 'openai',
            keyState: 'invalid',
            state: 'degraded',
            remediation: 'set a valid OPENAI_API_KEY in .env',
          }),
        ]),
      ),
    )
    const description = optionAccessibleDescription(broken)
    expect(description).toContain('remote · paid')
    expect(description).toContain('health invalid')
    expect(description).toContain('set a valid OPENAI_API_KEY in .env')
  })

  it('tells a stored choice from an inherited default, with no restart language', () => {
    const chosen = sourceNotice(role({ source: 'selection', selected: 'ollama/gpt-oss:120b' }))
    expect(chosen).toMatch(/your selection/)
    expect(chosen).toMatch(/applied immediately/)
    // A selection is a stored row read per request: nothing restarts.
    expect(chosen).not.toMatch(/restart/i)

    const inherited = sourceNotice(role())
    expect(inherited).toMatch(/Inherited from the file default/)
    expect(inherited).toContain('openai/gpt-5.2')
  })

  it('states the catalog’s own change path once, and only for the catalog', () => {
    expect(CATALOG_IS_A_STARTUP_SNAPSHOT).toMatch(/api restart/)
    expect(CATALOG_IS_A_STARTUP_SNAPSHOT).toMatch(/Choosing one of the bindings below is not/)
  })

  it('names a discarded selection instead of degrading quietly', () => {
    const notice = staleSelectionNotice(
      role({ staleSelection: 'openai/gpt-4o', staleReason: 'it is no longer in the catalog' }),
    )
    expect(notice).toContain('openai/gpt-4o')
    expect(notice).toContain('it is no longer in the catalog')
    expect(notice).toContain('openai/gpt-5.2')
    expect(staleSelectionNotice(role())).toBeNull()
  })

  it('restates the binding in force after a refusal and substitutes nothing', () => {
    const message = selectionRefusal(role(), 'binding-not-in-catalog')
    expect(message).toContain('binding-not-in-catalog')
    expect(message).toContain('still bound to openai/gpt-5.2')
    expect(message).toMatch(/nothing was substituted/)
  })

  it('invents no default for an empty catalog', () => {
    expect(NO_MODELS_CONFIGURED).toMatch(/config\.yaml/)
    expect(NO_MODELS_CONFIGURED).toMatch(/restart the api/)
  })
})
