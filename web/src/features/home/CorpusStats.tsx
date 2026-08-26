import { useCallback, useEffect, useRef, useState } from 'react'
import { getCorpusStats } from '@/client/sdk.gen'
import type { CorpusStats as CorpusStatsModel } from '@/client/types.gen'
import { Button } from '@/components/ui/button'
import { API_BASE } from '@/lib/api'

type StatsState =
  | { kind: 'loading' }
  | { kind: 'ok'; stats: CorpusStatsModel }
  | { kind: 'error'; message: string }

/**
 * Hours of evidence, from the served total duration, to one decimal — the
 * header is a scale statement, not a stopwatch. Rendered only from a served
 * number, never invented.
 */
export function hoursLabel(totalDurationMs: number): string {
  return (totalDurationMs / 3_600_000).toFixed(1)
}

function describe(error: unknown): string {
  if (error instanceof Error) return error.message
  if (typeof error === 'string') return error
  try {
    return JSON.stringify(error) ?? 'an unknown error'
  } catch {
    return 'an unknown error'
  }
}

/**
 * The corpus's scale, stated in one strip at the top of home (SPEC-ui-reimagine
 * CAP-1): every number is `GET /corpus/stats`'s database-of-record count, none
 * is decorative. When the endpoint cannot be reached the strip says so in one
 * sentence rather than rendering zeros it did not observe.
 */
export function CorpusStats() {
  const [state, setState] = useState<StatsState>({ kind: 'loading' })
  // Held across renders so a re-fetch aborts the in-flight one — an older
  // response must never overwrite a newer result (story 1.10, finding 22).
  const controllerRef = useRef<AbortController | null>(null)

  const load = useCallback(async () => {
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller
    setState({ kind: 'loading' })
    try {
      const { data, error } = await getCorpusStats({ signal: controller.signal })
      if (controller.signal.aborted) return
      if (error !== undefined || data === undefined) {
        throw new Error(`api returned an error response: ${JSON.stringify(error)}`)
      }
      setState({ kind: 'ok', stats: data })
    } catch (err) {
      if (controller.signal.aborted) return
      setState({ kind: 'error', message: describe(err) })
    }
  }, [])

  useEffect(() => {
    void load()
    return () => controllerRef.current?.abort()
  }, [load])

  if (state.kind === 'loading') {
    return (
      <section data-testid="corpus-stats" aria-label="Corpus statistics">
        <p className="text-sm text-muted-foreground">Counting the corpus…</p>
      </section>
    )
  }

  if (state.kind === 'error') {
    return (
      <section data-testid="corpus-stats" aria-label="Corpus statistics">
        <p className="flex items-center gap-3 text-sm text-muted-foreground">
          <span>
            Corpus counts unavailable — cannot reach the api at {API_BASE}: {state.message}
          </span>
          <Button size="sm" variant="outline" onClick={() => void load()}>
            Retry
          </Button>
        </p>
      </section>
    )
  }

  const { stats } = state
  const items: Array<[string, string | number]> = [
    ['meetings', stats.meetings],
    ['hours of evidence', hoursLabel(stats.totalDurationMs)],
    ['moments', stats.moments],
    ['screens', stats.screens],
    ['artifacts', stats.artifacts.total],
    ['participants', stats.participants],
    ['published docs', stats.publishedDocuments],
  ]

  return (
    <section data-testid="corpus-stats" aria-label="Corpus statistics">
      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 rounded-lg border p-4 sm:grid-cols-4 lg:grid-cols-7">
        {items.map(([label, value]) => (
          <div key={label} className="flex flex-col">
            <dt className="text-[10px] font-medium tracking-widest text-muted-foreground uppercase">
              {label}
            </dt>
            <dd className="font-mono text-xl tabular-nums">{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}
