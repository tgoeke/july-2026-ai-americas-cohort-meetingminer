import { useEffect, useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import { getConfiguration } from '@/client/sdk.gen'
import type {
  ConfigResponse,
  LlmRoleView,
  SearchIndexView,
} from '@/client/types.gen'
import { API_BASE } from '@/lib/api'
import { ModelRoles } from './ModelRoles'
import {
  changePath,
  CONFIG_TIMEOUT_MS,
  formatValue,
  labelize,
  READ_ONLY_CONTRACT,
  type ConfigLoad,
} from './settings'

/**
 * The read-only configuration page (SPEC-ui-reimagine CAP-3): the live stack
 * as config.yaml binds it, rendered from ui-1's sanitized `GET /config`
 * endpoint and nothing else. Every section states its change path — edit
 * `config.yaml`, restart the affected process, `make rebuild` for
 * `projections.*` — and no section offers an edit control.
 *
 * Relation to `/status` (the system-status story): status is live health —
 * what answers right now — while this page is the declared stack — what the
 * file says should be running. The header links one to the other instead of
 * duplicating either.
 */

/** A `key: value` table over one flat object — thresholds, knobs. */
function KeyValues({ record }: { record: Record<string, unknown> }) {
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-0.5 text-sm">
      {Object.entries(record).map(([key, value]) => (
        <div key={key} className="contents">
          <dt className="text-muted-foreground">{labelize(key)}</dt>
          <dd className="font-mono">{formatValue(value)}</dd>
        </div>
      ))}
    </dl>
  )
}

/** One section card: heading, body, and the section's change path. */
function Section({
  title,
  path,
  children,
}: {
  title: string
  path: string
  children: ReactNode
}) {
  return (
    <section className="flex flex-col gap-2">
      <h3 className="text-sm font-medium text-muted-foreground">{title}</h3>
      <div className="flex flex-col gap-3 rounded-md border p-3">
        {children}
        <p className="text-xs text-muted-foreground">{path}</p>
      </div>
    </section>
  )
}

/** A full prompt text, collapsed by default — the texts run to pages. */
function PromptBlock({ label, text }: { label: string; text: string }) {
  return (
    <details className="rounded-md border p-2">
      <summary className="cursor-pointer text-sm font-medium">{label}</summary>
      <pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-xs">{text}</pre>
    </details>
  )
}

function RoleCard({ role }: { role: LlmRoleView }) {
  const binding: Record<string, unknown> = { model: role.model }
  if (role.fallback != null) binding.fallback = role.fallback
  if (role.provider != null) binding.provider = role.provider
  if (role.endpoint != null) binding.endpoint = role.endpoint
  if (role.fallbackEndpoint != null) binding.fallbackEndpoint = role.fallbackEndpoint
  if (role.timeoutSeconds != null) binding.timeoutSeconds = role.timeoutSeconds
  if (role.numCtx != null) binding.numCtx = role.numCtx
  return (
    <div className="flex flex-col gap-2 rounded-md border p-3">
      <span className="font-medium">
        <code>llm.roles.{role.role}</code>
      </span>
      <KeyValues record={binding} />
      {role.archSummaryPrompt != null && (
        <PromptBlock label="Architecture summary prompt (full text)" text={role.archSummaryPrompt} />
      )}
      {role.actionItemsPrompt != null && (
        <PromptBlock label="Action items prompt (full text)" text={role.actionItemsPrompt} />
      )}
    </div>
  )
}

function IndexCard({ name, index }: { name: string; index: SearchIndexView }) {
  return (
    <div className="flex flex-col gap-1 rounded-md border p-2">
      <span className="text-sm font-medium">{name}</span>
      <KeyValues
        record={{
          searchableAttributes: index.searchableAttributes,
          filterableAttributes: index.filterableAttributes,
          sortableAttributes: index.sortableAttributes,
          rankingRules: index.rankingRules,
        }}
      />
    </div>
  )
}

function Loaded({ config }: { config: ConfigResponse }) {
  return (
    <div className="flex flex-col gap-6">
      <p className="text-sm text-muted-foreground">
        <code>{config.service}</code> · config version {config.configVersion} ·{' '}
        declared stack as <code>config.yaml</code> binds it — live health lives
        on <Link to="/status" className="underline">system status</Link>, which
        reports whether each of these actually answers.
      </p>

      {/* Story 8.3: the page's one editable thing, and deliberately its own
          block rather than part of "LLM roles" below — that section's
          change path is a file edit plus a restart, which is exactly what
          choosing a model is not. */}
      <section className="flex flex-col gap-2">
        <h3 className="text-sm font-medium text-muted-foreground">Model per role</h3>
        <div className="flex flex-col gap-3 rounded-md border p-3">
          <ModelRoles />
        </div>
      </section>

      <Section
        title="LLM roles"
        path={changePath('the api and the worker (`make api`, `make worker`)')}
      >
        <div className="flex flex-col gap-2">
          {config.llmRoles.map((role) => (
            <RoleCard key={role.role} role={role} />
          ))}
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-sm font-medium">providers</span>
          <KeyValues record={config.providers} />
        </div>
      </Section>

      <Section
        title="Embedder"
        path={changePath('the api and the worker (`make api`, `make worker`)')}
      >
        <KeyValues
          record={{ model: config.embedder.model, dimension: config.embedder.dimension }}
        />
      </Section>

      <Section title="Speech, vision, and speakers" path={changePath('the worker (`make worker`)')}>
        <KeyValues
          record={{
            'stt engine': config.stt.engine,
            'stt model': config.stt.model,
            'ocr engine': config.ocr.engine,
            ...(config.ocr.fallback != null ? { 'ocr fallback': config.ocr.fallback } : {}),
            'diarizer engine': config.diarizer.engine,
          }}
        />
      </Section>

      <Section title="Pipeline capture thresholds" path={changePath('the worker (`make worker`)')}>
        <div className="flex flex-col gap-3">
          {(
            [
              ['frames', config.pipeline.frames],
              ['screens', config.pipeline.screens],
              ['align', config.pipeline.align],
              ['moments', config.pipeline.moments],
            ] as const
          ).map(([name, group]) => (
            <div key={name} className="flex flex-col gap-1">
              <span className="text-sm font-medium">{name}</span>
              <KeyValues record={group} />
            </div>
          ))}
        </div>
      </Section>

      <Section title="API search and chat knobs" path={changePath('the api (`make api`)')}>
        <KeyValues
          record={{
            jobEventsPollSeconds: config.api.jobEventsPollSeconds,
            jobEventsHeartbeatSeconds: config.api.jobEventsHeartbeatSeconds,
          }}
        />
        <div className="flex flex-col gap-1">
          <span className="text-sm font-medium">search</span>
          <KeyValues record={config.api.search} />
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-sm font-medium">chat</span>
          <KeyValues record={config.api.chat} />
        </div>
      </Section>

      <Section
        title="Projections"
        path={changePath('the api and the worker (`make api`, `make worker`)', { rebuild: true })}
      >
        <KeyValues
          record={{
            chunkMaxChars: config.projections.chunking.chunkMaxChars,
            chunkOverlapTurns: config.projections.chunking.chunkOverlapTurns,
            embedBatchSize: config.projections.embedBatchSize,
          }}
        />
        <IndexCard name="moments index" index={config.projections.momentsIndex} />
        <IndexCard name="chunks index" index={config.projections.chunksIndex} />
        <div className="flex flex-col gap-1">
          <span className="text-sm font-medium">synonyms</span>
          {Object.keys(config.projections.synonyms).length === 0 ? (
            <p className="text-sm text-muted-foreground">none configured</p>
          ) : (
            <KeyValues record={config.projections.synonyms} />
          )}
        </div>
      </Section>

      <Section
        title="Store coordinates"
        path={changePath('the api and the worker (`make api`, `make worker`)')}
      >
        <KeyValues
          record={{
            postgres: `${config.stores.postgres.host}:${config.stores.postgres.port}/${config.stores.postgres.database} as ${config.stores.postgres.user}`,
            neo4j: `${config.stores.neo4j.uri} as ${config.stores.neo4j.user}`,
            meilisearch: config.stores.meilisearch.url,
          }}
        />
        <p className="text-xs text-muted-foreground">
          Coordinates only — anything sensitive lives in <code>.env</code> and
          never serializes out of the server.
        </p>
      </Section>
    </div>
  )
}

export function SettingsPage() {
  const [load, setLoad] = useState<ConfigLoad>({ kind: 'loading' })

  // One fetch on mount: the config is static until a restart, so there is
  // nothing to poll — a reader wanting fresher data reloads the page.
  useEffect(() => {
    let cancelled = false
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), CONFIG_TIMEOUT_MS)
    void (async () => {
      try {
        const { data, error } = await getConfiguration({ signal: controller.signal })
        if (cancelled) return
        if (error !== undefined || data === undefined) {
          // A network failure also lands here: the generated client returns
          // the thrown error in `error` rather than rethrowing it.
          const message =
            error instanceof Error
              ? error.message
              : 'the api refused the config read'
          setLoad({ kind: 'failed', message })
          return
        }
        setLoad({ kind: 'loaded', config: data })
      } catch (thrown) {
        if (cancelled) return
        const message = controller.signal.aborted
          ? `no answer within ${CONFIG_TIMEOUT_MS / 1000}s`
          : thrown instanceof Error
            ? thrown.message
            : String(thrown)
        setLoad({ kind: 'failed', message })
      } finally {
        clearTimeout(timer)
      }
    })()
    return () => {
      cancelled = true
      controller.abort()
      clearTimeout(timer)
    }
  }, [])

  return (
    <section className="flex flex-col gap-4">
      <h2 className="text-xl font-semibold tracking-tight">Configuration</h2>
      {load.kind === 'loading' && <p className="text-sm">reading the declared stack…</p>}
      {load.kind === 'failed' && (
        <div className="flex flex-col gap-1 rounded-md border p-3">
          <p className="text-sm text-destructive">
            cannot read the configuration from {API_BASE}: {load.message}
          </p>
          <p className="text-sm">
            → start the api (`make api` or `make up`) and check it is listening
            at {API_BASE}
          </p>
        </div>
      )}
      {load.kind === 'loaded' && <Loaded config={load.config} />}
      <p className="text-xs text-muted-foreground">{READ_ONLY_CONTRACT}</p>
    </section>
  )
}
