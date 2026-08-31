import { useEffect, useState } from 'react'
import { listMeetingExtractionDocuments } from '@/client/sdk.gen'

/**
 * The markdown an extraction run produced, for one meeting (story 12.1).
 *
 * **Why this exists.** The owner's word for an artifact is a markdown
 * *document* — the thing you would merge, publish to Obsidian, or hand to
 * someone. Until story 12.1 the pipeline generated one per run, parsed it into
 * rows, and discarded the text; the corpus held 205 runs and zero retained
 * documents. 12.1 kept the text and served it, but nothing rendered it, so a
 * reader opening a meeting still saw no artifacts. This is that surface.
 *
 * A document is a property of the MEETING, not of a moment. The `[m:ss]`
 * anchors inside it cite moments; they do not make the document belong to one.
 *
 * The markdown is shown as the text it is, not re-rendered into HTML. What the
 * model wrote is evidence, and a renderer that silently drops a malformed table
 * row would hide exactly the defect a reader opens this to find. It is also the
 * form the owner copies out.
 */
type DocumentRow = {
  kind: string
  origin: string
  model: string | null
  promptHash: string | null
  itemCount: number | null
  artifactCount: number | null
  byteSize: number | null
  documentText: string | null
}

const LABELS: Record<string, string> = {
  'arch-summary': 'Decisions & risks',
  'action-items': 'Action items',
  topics: 'Topics',
  'ranking-signals': 'Ranking signals',
}

export function MeetingDocuments({ meetingId }: { meetingId: string }) {
  const [rows, setRows] = useState<DocumentRow[] | null>(null)
  const [failed, setFailed] = useState<string | null>(null)
  const [open, setOpen] = useState<string | null>('arch-summary')

  useEffect(() => {
    let live = true
    setRows(null)
    setFailed(null)
    // Wrapped rather than chained: this panel is a guest in the meeting view,
    // and a read that throws synchronously — an unreachable api, a transport
    // that rejects before returning a promise — must not take the transcript,
    // the screenshots and the moments down with it. It degrades to a line of
    // text saying it could not read them.
    try {
      void listMeetingExtractionDocuments({ path: { meeting_id: meetingId } })
        .then(({ data, error }) => {
          if (!live) return
          if (error !== undefined || data === undefined) {
            setFailed('the extraction documents could not be read')
            return
          }
          setRows((data as { documents: DocumentRow[] }).documents)
        })
        .catch(() => live && setFailed('the extraction documents could not be read'))
    } catch {
      setFailed('the extraction documents could not be read')
    }
    return () => {
      live = false
    }
  }, [meetingId])

  if (failed !== null) {
    return (
      <section data-testid="meeting-documents" className="flex flex-col gap-2">
        <h3 className="text-sm font-medium text-muted-foreground">Documents</h3>
        <p className="text-xs text-muted-foreground">{failed}.</p>
      </section>
    )
  }
  if (rows === null) return null

  // A run that predates story 12.1 has a row but no text. Saying so is the
  // point: "no document" and "this run was never retained" are different
  // facts, and conflating them is what made 205 discarded documents look like
  // a meeting that produced nothing.
  const withText = rows.filter((row) => row.documentText !== null)
  const unretained = rows.filter((row) => row.documentText === null)

  return (
    <section data-testid="meeting-documents" className="flex flex-col gap-2">
      <h3 className="text-sm font-medium text-muted-foreground">
        Documents{withText.length > 0 ? ` ${withText.length}` : ''}
      </h3>

      {withText.length === 0 && (
        <p data-testid="meeting-documents-none" className="text-xs text-muted-foreground">
          {unretained.length > 0
            ? `${unretained.length} extraction run(s) ran before documents were retained, so their text was not kept. Re-extracting this meeting produces them.`
            : 'This meeting has not been extracted yet.'}
        </p>
      )}

      {withText.map((row) => (
        <div key={row.kind} className="rounded-md border">
          <button
            type="button"
            data-testid={`meeting-document-${row.kind}`}
            className="flex w-full items-baseline justify-between gap-2 px-3 py-2 text-left text-xs"
            aria-expanded={open === row.kind}
            onClick={() => setOpen(open === row.kind ? null : row.kind)}
          >
            <span className="font-medium">{LABELS[row.kind] ?? row.kind}</span>
            <span className="text-muted-foreground">
              {row.itemCount ?? 0} items · {row.model ?? 'unknown model'}
            </span>
          </button>
          {open === row.kind && (
            // No height cap and no overflow here on purpose. The rail this
            // sits in already scrolls, and a scrolling box inside a scrolling
            // box gives a reader two bars to fight over one document. The
            // document runs to its full length and the rail carries it.
            <pre
              data-testid={`meeting-document-text-${row.kind}`}
              className="border-t px-3 py-2 font-mono text-[11px] break-words whitespace-pre-wrap"
            >
              {row.documentText}
            </pre>
          )}
        </div>
      ))}
    </section>
  )
}
