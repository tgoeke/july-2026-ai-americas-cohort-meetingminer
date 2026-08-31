import { useCallback, useEffect, useRef, useState } from 'react'
import { searchCorpus } from '@/client/sdk.gen'
import type { DocumentHitModel, SearchHit, SearchResponse } from '@/client/types.gen'
import { SourceLinkAnchor } from '@/components/SourceLinkAnchor'
import { Button } from '@/components/ui/button'
import { ReplayPlayer } from '@/features/replay/ReplayPlayer'
import { API_BASE } from '@/lib/api'
import {
  affordanceOf,
  artifactBadge,
  DEBOUNCE_MS,
  documentKindLabel,
  documentProvenance,
  documentYield,
  hitKey,
  hitLabel,
  offsetLabel,
  problemMessage,
  SEARCH_TIMEOUT_MS,
  type SearchFailure,
  snippetText,
} from './hits'

function describe(error: unknown): string {
  if (error instanceof Error) return error.message
  if (typeof error === 'string') return error
  try {
    // An error payload is untrusted diagnostic data. Circular objects cannot
    // be JSON-encoded, and JSON.stringify(undefined) returns undefined rather
    // than a message; neither may turn the error-rendering path into a throw.
    return JSON.stringify(error) ?? 'an unknown error'
  } catch {
    return 'an unknown error'
  }
}

/**
 * Corpus search: type a term, get the moments where it was discussed.
 *
 * The first leg of UX-DR3's locate flow — search → candidate meetings and
 * moments → highlighted snippet → small inline replay. The transcript
 * drill-down page that the flow ends on is story 2.3's deliverable, so a hit
 * here opens its replay in place rather than navigating: there is no router
 * in this app, and inventing one for a page another story owns would collide
 * with it.
 *
 * Highlights are rendered from the `snippet` array, run by run. No
 * `dangerouslySetInnerHTML`, and nothing on the wire to parse — the api sends
 * `[{text, highlighted}]` precisely so this component never has to trust
 * markup (the AD-15 principle applied to snippets).
 */
export interface CorpusSearchProps {
  /**
   * Opening a hit's moment view is the shell's navigation to make — the
   * story-3.1 deferred destination, delivered by story 2.2. Optional for the
   * same reason `MeetingsList.onOpen` is: the affordance lives here, the
   * navigation lives in whatever mounts this.
   */
  onOpenMoment?: (momentId: string) => void
  /** Compact chrome keeps the field in-row and presents its complete output
   * in an anchored overlay without unmounting the search state. */
  presentation?: 'standalone' | 'chrome'
  expanded?: boolean
}

export function CorpusSearch({
  onOpenMoment,
  presentation = 'standalone',
  expanded = false,
}: CorpusSearchProps = {}) {
  const [term, setTerm] = useState('')
  // `null` is "no search has answered yet", `[]` is "answered, nothing
  // matched". Collapsing them is how an empty corpus renders as a permanent
  // loading state.
  const [rows, setRows] = useState<Array<SearchHit> | null>(null)
  const [ranking, setRanking] = useState<SearchResponse['ranking'] | null>(null)
  // Meilisearch's estimate for the whole corpus. Kept so a truncated page can
  // say it is one: results stopping at the page size look exactly like the
  // complete answer otherwise.
  const [estimatedTotal, setEstimatedTotal] = useState(0)
  // True when the moments index does not exist yet. A different sentence from
  // "nothing matched", because it asks for a different action.
  const [indexMissing, setIndexMissing] = useState(false)
  // Extraction documents (story 12.4), held apart from `rows` because they are
  // apart on the wire and apart in kind: a moment is citable evidence, a
  // document is unreviewed machine-written analysis *about* evidence. Merging
  // the two lists here would be the first step towards a UI that presents them
  // as the same thing, which is what AD-18 forbids.
  const [documents, setDocuments] = useState<Array<DocumentHitModel>>([])
  const [documentsTotal, setDocumentsTotal] = useState(0)
  const [documentsIndexMissing, setDocumentsIndexMissing] = useState(false)
  const [failure, setFailure] = useState<SearchFailure | null>(null)
  const [busy, setBusy] = useState(false)
  const [openReplay, setOpenReplay] = useState<string | null>(null)
  // Held across renders so a new keystroke aborts the in-flight search before
  // starting another — an older response must never overwrite a newer result
  // (story 1.10, finding 22).
  const controllerRef = useRef<AbortController | null>(null)

  const runSearch = useCallback(async (query: string) => {
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller
    // An explicit timer rather than `AbortSignal.timeout`: that signal cannot
    // be cancelled, so every superseded search would leave a live timer behind
    // for its full duration, and a real `setTimeout` is something a test can
    // drive.
    const expiry = new AbortController()
    const timer = setTimeout(() => expiry.abort(), SEARCH_TIMEOUT_MS)
    setBusy(true)
    try {
      // Inside the `try` so the `finally` owns the timer from the moment it
      // exists: `AbortSignal.any` throwing here would otherwise leak a live
      // timer that aborts a controller nothing is listening to.
      const signal = AbortSignal.any([controller.signal, expiry.signal])
      const { data, error } = await searchCorpus({ query: { q: query }, signal })
      if (controller.signal.aborted) return
      // A client normally rejects once its signal is aborted. This guard also
      // handles a client that settles despite the abort, so a response arriving
      // after the deadline cannot replace the timeout diagnosis with late data.
      if (expiry.signal.aborted) {
        setRows((current) => current ?? [])
        setFailure({
          kind: 'transport',
          message: `timed out after ${SEARCH_TIMEOUT_MS}ms`,
        })
        return
      }
      if (error !== undefined) {
        // The api answered and refused. That body is RFC 9457 and was written
        // for a person to read, so it is shown rather than stringified into
        // the unreachable-api sentence — which would also be the wrong
        // diagnosis, because the api is plainly reachable.
        setRows((current) => current ?? [])
        setFailure({
          kind: 'problem',
          message: problemMessage(error) ?? describe(error),
        })
        return
      }
      if (data === undefined) {
        throw new Error('the api answered with no body')
      }
      setRows(data.hits)
      setRanking(data.ranking)
      setEstimatedTotal(data.estimatedTotal)
      setIndexMissing(data.indexMissing ?? false)
      setDocuments(data.documents ?? [])
      setDocumentsTotal(data.documentsTotal ?? 0)
      setDocumentsIndexMissing(data.documentsIndexMissing ?? false)
      setFailure(null)
      setOpenReplay(null)
    } catch (err) {
      // Superseded or unmounted: never set state for a search nobody awaits.
      if (controller.signal.aborted) return
      // Rows are left standing on purpose: stale results beat a blank panel
      // while the api is briefly unreachable. But a *first* search that fails
      // has no rows to leave standing, and leaving them `null` would render
      // the banner and a permanent "Searching…" side by side.
      setRows((current) => current ?? [])
      setFailure({
        kind: 'transport',
        message: expiry.signal.aborted
          ? `timed out after ${SEARCH_TIMEOUT_MS}ms`
          : describe(err),
      })
    } finally {
      clearTimeout(timer)
      // A superseded search leaves `busy` alone: the one that superseded it is
      // still running, and clearing the flag here would announce an idle
      // results region while a request is in flight.
      if (!controller.signal.aborted) setBusy(false)
    }
  }, [])

  const trimmed = term.trim()

  useEffect(() => {
    if (trimmed === '') {
      // An empty box is not an empty result. Abort whatever is in flight and
      // go back to the prompt rather than searching for nothing — the api
      // refuses a blank query, and rendering that refusal as an error would
      // blame the user for clearing the field.
      controllerRef.current?.abort()
      setRows(null)
      setRanking(null)
      setEstimatedTotal(0)
      setIndexMissing(false)
      setDocuments([])
      setDocumentsTotal(0)
      setFailure(null)
      setBusy(false)
      setOpenReplay(null)
      return
    }
    // Abort at the keystroke rather than after the debounce. Otherwise an old
    // request has a 300 ms window to resolve and overwrite this newer intent.
    // The live region is busy for that window too: its contents are about to
    // change even before the next request starts.
    controllerRef.current?.abort()
    setBusy(true)
    const timer = setTimeout(() => void runSearch(trimmed), DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [trimmed, runSearch])

  useEffect(() => () => controllerRef.current?.abort(), [])

  const searching = trimmed !== '' && rows === null
  const shown = rows?.length ?? 0
  const documentsShown = documents.length
  const truncated = rows !== null && shown > 0 && estimatedTotal > shown
  const compact = presentation === 'chrome'

  return (
    <section
      className={compact ? 'relative w-full' : 'flex w-full flex-col gap-4'}
      data-testid={compact ? 'chrome-search-surface' : undefined}
      aria-expanded={compact ? expanded : undefined}
    >
      <header className={compact ? 'sr-only' : 'flex items-baseline justify-between gap-4'}>
        <h2 className="text-lg font-semibold tracking-tight">Search</h2>
        {ranking === 'keyword' && !compact && (
          <span
            data-testid="ranking-degraded"
            className="text-xs text-muted-foreground"
            title="The embedding model host is unreachable, so this search ranked on keywords alone."
          >
            keyword ranking only
          </span>
        )}
      </header>

      <label className={compact ? 'block text-sm' : 'flex flex-col gap-1 text-sm'}>
        {/* No `aria-label` here on purpose. One would override the words below
            and leave the visible text unable to activate the field by voice
            (WCAG 2.5.3), so the visible text *is* the accessible name. */}
        <span className={compact ? 'sr-only' : 'text-muted-foreground'}>
          Search the corpus for the moments where something was discussed
        </span>
        <input
          data-testid="search-input"
          type="search"
          value={term}
          placeholder="purchase order"
          onChange={(event) => setTerm(event.target.value)}
          aria-expanded={compact ? expanded : undefined}
          aria-controls={compact ? 'chrome-search-results' : undefined}
          className={
            compact
              ? 'h-8 w-full rounded-md border px-2 text-sm'
              : 'rounded-md border px-3 py-2 text-sm'
          }
        />
      </label>

      <div
        id={compact ? 'chrome-search-results' : undefined}
        hidden={compact && !expanded}
        className={
          compact
            ? 'absolute top-[calc(100%+0.75rem)] left-0 z-40 flex max-h-[min(38rem,calc(100vh-5rem))] w-[min(38rem,calc(100vw-2rem))] flex-col gap-4 overflow-y-auto rounded-lg border bg-popover p-4 shadow-md'
            : 'contents'
        }
      >
        {compact && ranking === 'keyword' && (
          <span
            data-testid="ranking-degraded"
            className="text-xs text-muted-foreground"
            title="The embedding model host is unreachable, so this search ranked on keywords alone."
          >
            keyword ranking only
          </span>
        )}
        {failure !== null && (
        <p
          role="alert"
          className="rounded-md border border-destructive/40 p-3 text-sm text-destructive"
        >
          {failure.kind === 'transport'
            ? `Cannot reach the api at ${API_BASE}: ${failure.message}.`
            : `The api at ${API_BASE} could not answer that search: ${failure.message}.`}
          {rows !== null && (rows.length > 0 || documents.length > 0) &&
            ' The results below may be stale.'}
        </p>
      )}

      {/* One live region around every result state, so the "Searching…" → "N
          results" transition is announced rather than changing silently under
          a screen reader. */}
        <div
        aria-live="polite"
        // Busy from the keystroke, not from the request: the debounce window
        // is still time in which this region's contents are known to be about
        // to change, and announcing it as settled during it would be wrong.
        aria-busy={busy || searching}
        className="flex flex-col gap-3"
      >
        {!searching &&
          trimmed !== '' &&
          failure === null &&
          documentsIndexMissing && (
            <p
              data-testid="search-documents-index-missing"
              className="rounded-lg border border-dashed p-3 text-sm text-muted-foreground"
            >
              The extraction-documents index is missing. Run a rebuild to make
              retained analysis searchable.
            </p>
          )}
        {trimmed === '' ? (
          <p data-testid="search-prompt" className="text-sm text-muted-foreground">
            Type a name, a topic, or a phrase someone said.
          </p>
        ) : searching ? (
          <p data-testid="search-loading" className="text-sm text-muted-foreground">
            Searching…
          </p>
        ) : shown === 0 ? (
          // A failed search has no result to report, so the banner stands
          // alone: "no moments match" would be an answer the api never gave.
          failure !== null ? null : (
            <p
              data-testid={
                indexMissing && documentsShown === 0
                  ? 'search-index-missing'
                  : 'search-empty'
              }
              className="rounded-lg border border-dashed p-6 text-sm text-muted-foreground"
            >
              {indexMissing && documentsShown === 0
                ? 'Nothing has been indexed yet, so there is nothing to search. Ingest a meeting, then search again.'
                : documentsShown > 0
                  ? // Precise, because the difference matters here: no moment
                    // matched, and the analysis below still did. Saying only
                    // "no results" would hide exactly what story 12.4 exists
                    // to surface — the run that yielded nothing citable.
                    'No moments match that search. The unreviewed analysis below mentions it.'
                  : 'No moments match that search.'}
            </p>
          )
        ) : (
          <>
            {truncated && (
              <p
                data-testid="search-truncated"
                className="text-xs text-muted-foreground"
              >
                Showing {shown} of about {estimatedTotal} matches — narrow the
                search to see the rest.
              </p>
            )}
            <ul className="flex flex-col gap-3">
              {(rows ?? []).map((hit) => {
                // Timed at the hit: a YouTube source link carries `t=` from
                // `startMs` (UX-DR12).
                const affordance = affordanceOf(hit, hit.startMs)
                const label = hitLabel(hit)
                // A published-artifact hit shares its source moment's replay
                // fields with any plain moment hit for the same moment, so
                // list identity keys on the artifact id when there is one.
                const key = hitKey(hit)
                const badge = artifactBadge(hit)
                const isOpen = openReplay === key
                // An artifact hit and its source-moment hit can share one
                // page with the same meeting `label` — disambiguate every
                // announced/labeled affordance with the artifact's own title
                // when there is one, so a screen reader (or ReplayPlayer's
                // own label) never announces two rows identically.
                const describedLabel = badge !== null ? (hit.artifactTitle ?? label) : label
                return (
                  <li
                    key={key}
                    data-testid={`hit-${key}`}
                    className="flex flex-col gap-3 rounded-lg border p-4"
                  >
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <span className="flex min-w-0 items-baseline gap-2">
                        {badge !== null && (
                          <span
                            data-testid={`hit-kind-${key}`}
                            className="shrink-0 rounded bg-secondary px-1.5 py-0.5 text-xs font-medium uppercase tracking-wide text-secondary-foreground"
                          >
                            {badge}
                          </span>
                        )}
                        <span className="truncate font-medium">
                          {badge !== null ? (hit.artifactTitle ?? label) : label}
                        </span>
                      </span>
                      <span
                        data-testid={`hit-offset-${key}`}
                        className="text-xs text-muted-foreground"
                      >
                        {offsetLabel(hit.startMs)}
                      </span>
                    </div>
                    {badge !== null && (
                      // The evidence trail: a published artifact is cited
                      // knowledge, and the meeting/moment it came from is what
                      // the replay affordance below plays back.
                      <p
                        data-testid={`hit-source-${key}`}
                        className="text-xs text-muted-foreground"
                      >
                        {/* The offset already appears once, in the header
                            span above — this line names only the source,
                            not a second copy of the same timestamp. */}
                        Published from {label}
                      </p>
                    )}

                    <p
                      data-testid={`hit-snippet-${key}`}
                      className="text-sm text-muted-foreground"
                      // The words without the emphasis, for a hover and for any
                      // reader that flattens the marked runs.
                      title={snippetText(hit.snippet)}
                    >
                      {hit.snippet.length === 0 ? (
                        // A moment the store had nothing to crop for — a purely
                        // semantic hit on an untexted document. An empty
                        // paragraph would read as a rendering bug rather than
                        // as an answer.
                        <span className="italic">No preview for this moment.</span>
                      ) : (
                        hit.snippet.map((run, index) =>
                          run.highlighted ? (
                            // eslint-disable-next-line react/no-array-index-key -- runs have no id; their order is their identity
                            <mark
                              key={index}
                              className="bg-yellow-200 dark:bg-yellow-900"
                            >
                              {run.text}
                            </mark>
                          ) : (
                            // eslint-disable-next-line react/no-array-index-key -- same
                            <span key={index}>{run.text}</span>
                          ),
                        )
                      )}
                    </p>

                    <div className="flex flex-wrap items-center gap-3">
                      {/* Only when a shell wired the navigation: an enabled
                          button that silently does nothing is exactly the dead
                          affordance this file's replay states exist to avoid. */}
                      {onOpenMoment !== undefined && (
                        <Button
                          size="sm"
                          variant="outline"
                          // Every row would otherwise render a button named just
                          // "Open moment" — same disambiguation as Replay below.
                          aria-label={`Open moment in ${describedLabel} at ${offsetLabel(hit.startMs)}`}
                          onClick={() => onOpenMoment(hit.momentId)}
                        >
                          Open moment
                        </Button>
                      )}
                      {affordance.kind === 'replay' && (
                        <Button
                          size="sm"
                          variant={isOpen ? 'outline' : 'default'}
                          // Every row would otherwise render a button named just
                          // "Replay", leaving the rows indistinguishable to a
                          // screen reader and ambiguous to any by-name query.
                          aria-label={`${isOpen ? 'Hide' : 'Replay'} ${describedLabel} at ${offsetLabel(hit.startMs)}`}
                          aria-expanded={isOpen}
                          onClick={() => setOpenReplay(isOpen ? null : key)}
                        >
                          {isOpen ? 'Hide replay' : 'Replay'}
                        </Button>
                      )}
                      {affordance.kind === 'replay' && affordance.source !== null && (
                        // UX-DR12: replay first, the source second — the
                        // YouTube link timed at this hit, secondary to Replay.
                        <SourceLinkAnchor
                          link={affordance.source}
                          testId={`hit-youtube-link-${key}`}
                        />
                      )}
                      {affordance.kind === 'replay' && affordance.inertSource !== null && (
                        <span
                          data-testid={`hit-unsafe-link-${key}`}
                          className="break-all text-xs text-muted-foreground"
                        >
                          Source link not opened — unsupported address: {affordance.inertSource}
                        </span>
                      )}
                      {affordance.kind === 'deepLink' && (
                        // Labelled by provider (UX-DR12): a YouTube link is
                        // timed and named with its offset; any other host
                        // keeps the untimed "Open in Stream".
                        <SourceLinkAnchor
                          link={affordance.source}
                          testId={`hit-deep-link-${key}`}
                        />
                      )}
                      {affordance.kind === 'inertLink' && (
                        // Shown, never offered. The drop recorded something
                        // here and hiding it would lose the only pointer back
                        // to the source; rendering it as an anchor would be
                        // worse than losing it.
                        <span
                          data-testid={`hit-unsafe-link-${key}`}
                          className="break-all text-xs text-muted-foreground"
                        >
                          Source link not opened — unsupported address:{' '}
                          {affordance.text}
                        </span>
                      )}
                      {affordance.kind === 'none' && (
                        <span
                          data-testid={`hit-no-evidence-${key}`}
                          className="text-xs text-muted-foreground"
                        >
                          Transcript only — no recording and no source link.
                        </span>
                      )}
                    </div>

                    {isOpen && affordance.kind === 'replay' && (
                      // Rendered with the hit's `startMs` rather than remounted
                      // per seek: ReplayPlayer re-seeks on a `startMs` change, and
                      // remounting would reload the whole recording.
                      <ReplayPlayer
                        meetingId={hit.meetingId}
                        startMs={hit.startMs}
                        label={`${describedLabel} at ${offsetLabel(hit.startMs)}`}
                        className="w-full rounded-md"
                      />
                    )}
                  </li>
                )
              })}
            </ul>
          </>
        )}

        {/* Extraction documents (story 12.4). Rendered outside the
            moment-results branch on purpose: a document matching when no
            moment does is the case this whole feature exists for — the run
            that yielded nothing worth approving is the run whose text somebody
            needs to read.

            A separate region, never interleaved with the hits above. The two
            are different kinds of thing: a moment is citable evidence, a
            document is unreviewed machine-written analysis *about* evidence,
            and a list that mixed them would present the second as the first
            (AD-18). Every card states its status from the api's own
            `reviewLabel` rather than from a sentence written here, so what the
            reader sees is what the indexed record says. */}
        {!searching && trimmed !== '' && documentsShown > 0 && (
          <section
            data-testid="search-documents"
            aria-label="Unreviewed extraction documents"
            className="flex flex-col gap-3 border-t pt-4"
          >
            <header className="flex flex-wrap items-baseline justify-between gap-2">
              <h3 className="text-sm font-semibold tracking-tight">
                Extraction documents
              </h3>
              <span
                data-testid="search-documents-caveat"
                className="text-xs text-muted-foreground"
              >
                Unreviewed machine-written analysis — not citable evidence
              </span>
            </header>
            {documentsTotal > documentsShown && (
              <p
                data-testid="search-documents-truncated"
                className="text-xs text-muted-foreground"
              >
                Showing {documentsShown} of {documentsTotal} documents — narrow
                the search to see the rest.
              </p>
            )}
            <ul className="flex flex-col gap-3">
              {documents.map((document) => (
                <li
                  key={document.documentId}
                  data-testid={`document-${document.documentId}`}
                  className="flex flex-col gap-2 rounded-lg border border-dashed p-4"
                >
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="flex min-w-0 items-baseline gap-2">
                      <span
                        data-testid={`document-badge-${document.documentId}`}
                        className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-xs font-medium uppercase tracking-wide text-muted-foreground"
                      >
                        Unreviewed
                      </span>
                      <span className="truncate font-medium">
                        {documentKindLabel(document)}
                      </span>
                    </span>
                  </div>
                  <p
                    data-testid={`document-source-${document.documentId}`}
                    className="text-xs text-muted-foreground"
                  >
                    {documentProvenance(document)}
                  </p>
                  <p
                    data-testid={`document-snippet-${document.documentId}`}
                    className="text-sm text-muted-foreground"
                    title={snippetText(document.snippet)}
                  >
                    {document.snippet.length === 0 ? (
                      <span className="italic">No preview for this document.</span>
                    ) : (
                      document.snippet.map((run, index) =>
                        run.highlighted ? (
                          // eslint-disable-next-line react/no-array-index-key -- runs have no id; their order is their identity
                          <mark key={index} className="bg-yellow-200 dark:bg-yellow-900">
                            {run.text}
                          </mark>
                        ) : (
                          // eslint-disable-next-line react/no-array-index-key -- same
                          <span key={index}>{run.text}</span>
                        ),
                      )
                    )}
                  </p>
                  <p
                    data-testid={`document-yield-${document.documentId}`}
                    className="text-xs text-muted-foreground"
                  >
                    {documentYield(document)}
                  </p>
                  {/* Straight from the indexed record. Not a sentence this
                      component composed: the label was written into the record
                      so it could not be lost between the store and a reader,
                      and regenerating it here would defeat that (AD-18). */}
                  <p
                    data-testid={`document-label-${document.documentId}`}
                    className="text-xs italic text-muted-foreground"
                  >
                    {document.reviewLabel}
                  </p>
                </li>
              ))}
            </ul>
          </section>
        )}
        </div>
      </div>
    </section>
  )
}
