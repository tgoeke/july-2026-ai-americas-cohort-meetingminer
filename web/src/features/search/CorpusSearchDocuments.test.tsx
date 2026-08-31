import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { DocumentHitModel, SearchResponse } from '@/client/types.gen'
import { CorpusSearch } from './CorpusSearch'
import { documentKindLabel, documentProvenance, documentYield } from './hits'

/**
 * Extraction documents in the search UI (story 12.4).
 *
 * The api-side half of this story is proved in `test_projections_documents.py`
 * and `test_projections_search.py`: every document is indexed without passing
 * the publish gate, and the indexed record carries its unreviewed,
 * machine-written status. This file proves the other half of AD-18 — that a
 * surface which renders one *labels* it — and that the label the reader sees
 * is the api's own, not a sentence this component composed.
 *
 * A separate file from `CorpusSearch.test.tsx` because the property under test
 * is different: that one is about the citable moment lane, this one is about
 * the deliberately uncitable lane beside it.
 */

const sdk = vi.hoisted(() => ({ searchCorpus: vi.fn() }))

vi.mock('@/client/sdk.gen', () => ({
  getMeetingDrilldown: vi.fn(),
  searchCorpus: sdk.searchCorpus,
  getHealth: vi.fn(),
  listMeetings: vi.fn(),
  listMeetingMoments: vi.fn(),
  getMoment: vi.fn(),
  streamJobEvents: vi.fn(),
  getJob: vi.fn(),
  createIngest: vi.fn(),
  getRecording: vi.fn(),
  getMediaFile: vi.fn(),
  listParticipants: vi.fn(),
  renameParticipant: vi.fn(),
  mergeParticipants: vi.fn(),
}))

const LABEL =
  'Unreviewed — machine-written extraction output. No human approved this' +
  ' text, and it is not citable evidence.'

function document(overrides: Partial<DocumentHitModel> = {}): DocumentHitModel {
  return {
    documentId: 'document-1',
    meetingId: 'meeting-1',
    meetingTitle: 'Data Hub Demo',
    corpus: 'real',
    kind: 'arch-summary',
    origin: 'generated',
    model: 'test-model',
    promptHash: 'abcdef0123456789',
    layout: 'table',
    itemCount: 3,
    artifactCount: 3,
    byteSize: 120,
    reviewState: 'unreviewed',
    authorship: 'machine',
    reviewLabel: LABEL,
    citable: false,
    snippet: [
      { text: 'We moved the ', highlighted: false },
      { text: 'feed', highlighted: true },
      { text: ' to SFTP.', highlighted: false },
    ],
    score: 0.8,
    ...overrides,
  }
}

function response(overrides: Partial<SearchResponse> = {}): SearchResponse {
  return {
    query: 'feed',
    ranking: 'hybrid',
    hits: [],
    estimatedTotal: 0,
    limit: 20,
    offset: 0,
    indexMissing: false,
    documents: [document()],
    documentsTotal: 1,
    documentsIndexMissing: false,
    ...overrides,
  }
}

function answers(body: SearchResponse) {
  sdk.searchCorpus.mockResolvedValue({ data: body, error: undefined })
}

async function search(term: string) {
  const user = userEvent.setup()
  await user.type(screen.getByTestId('search-input'), term)
}

beforeEach(() => {
  sdk.searchCorpus.mockReset()
})

describe('extraction documents in search', () => {
  it('renders a matching document even when no moment matched', async () => {
    // The case story 12.4 exists for, end to end in the UI: the run that
    // yielded nothing worth approving produced no citable moment, and its
    // text is exactly what the reader came for.
    answers(response())
    render(<CorpusSearch />)
    await search('feed')

    expect(await screen.findByTestId('search-documents')).toBeInTheDocument()
    expect(screen.getByTestId('document-document-1')).toBeInTheDocument()
  })

  it('labels every document as unreviewed machine-written output', async () => {
    // AD-18 on the rendering side. The badge is the glance, the sentence is
    // the explanation, and both are present — an exception to *reach* must
    // never become an exception to legibility.
    answers(response())
    render(<CorpusSearch />)
    await search('feed')

    expect(await screen.findByTestId('document-badge-document-1')).toHaveTextContent(
      'Unreviewed',
    )
    expect(screen.getByTestId('search-documents-caveat')).toHaveTextContent(
      /not citable evidence/i,
    )
  })

  it('renders the api-supplied label verbatim rather than one of its own', async () => {
    // The label was written into the indexed record so it could not be lost
    // between the store and a reader. A component that regenerated it would
    // keep rendering a plausible sentence for a record that had stopped
    // carrying one — which is the failure the record-side label prevents.
    answers(
      response({
        documents: [document({ reviewLabel: 'A different sentence from the api.' })],
      }),
    )
    render(<CorpusSearch />)
    await search('feed')

    expect(await screen.findByTestId('document-label-document-1')).toHaveTextContent(
      'A different sentence from the api.',
    )
  })

  it('offers no replay, no moment link and no citation for a document', async () => {
    // A document is a claim *about* evidence, never a citation target (AD-6).
    // There is nothing to open at a second and nothing to cite, so the row
    // offers neither — a dead "Open moment" would be worse than its absence.
    const onOpenMoment = vi.fn()
    answers(response())
    render(<CorpusSearch onOpenMoment={onOpenMoment} />)
    await search('feed')

    const row = await screen.findByTestId('document-document-1')
    expect(row.querySelectorAll('button')).toHaveLength(0)
    expect(row.querySelectorAll('a')).toHaveLength(0)
  })

  it('says a zero-yield run produced nothing rather than hiding it', async () => {
    // The named signal story 12.1 keeps, carried through to the reader: a run
    // that parsed to nothing is why the document is worth reading at all.
    answers(
      response({ documents: [document({ itemCount: 0, artifactCount: 0 })] }),
    )
    render(<CorpusSearch />)
    await search('feed')

    expect(await screen.findByTestId('document-yield-document-1')).toHaveTextContent(
      /produced no items/i,
    )
  })

  it('does not report a bare "no moments match" when documents did', async () => {
    // Precision over brevity. "No results" would hide exactly what this
    // feature surfaces, and the two facts are different answers.
    answers(response())
    render(<CorpusSearch />)
    await search('feed')

    expect(await screen.findByTestId('search-empty')).toHaveTextContent(
      /unreviewed analysis below/i,
    )
  })

  it('keeps the documents region out of the citable hit list', async () => {
    // Rendered as its own region, never interleaved. A list that mixed the two
    // would present unreviewed prose as citable evidence at a glance.
    answers(response())
    render(<CorpusSearch />)
    await search('feed')

    const region = await screen.findByTestId('search-documents')
    expect(region.querySelector('[data-testid^="hit-"]')).toBeNull()
  })

  it('shows nothing when the api returned no documents', async () => {
    answers(response({ documents: [], documentsTotal: 0 }))
    render(<CorpusSearch />)
    await search('feed')

    await waitFor(() => expect(sdk.searchCorpus).toHaveBeenCalled())
    expect(screen.queryByTestId('search-documents')).toBeNull()
  })

  it('distinguishes a missing documents index from no document matches', async () => {
    answers(
      response({
        documents: [],
        documentsTotal: 0,
        documentsIndexMissing: true,
      }),
    )
    render(<CorpusSearch />)
    await search('feed')

    expect(await screen.findByTestId('search-documents-index-missing')).toHaveTextContent(
      /rebuild/i,
    )
  })

  it('does not claim nothing is indexed when documents matched', async () => {
    answers(response({ indexMissing: true }))
    render(<CorpusSearch />)
    await search('feed')

    expect(await screen.findByTestId('search-empty')).toHaveTextContent(
      /unreviewed analysis below/i,
    )
    expect(screen.queryByTestId('search-index-missing')).toBeNull()
  })

  it('warns when preserved document-only results belong to a failed prior query', async () => {
    const user = userEvent.setup()
    answers(response())
    render(<CorpusSearch />)
    await user.type(screen.getByTestId('search-input'), 'feed')
    await screen.findByTestId('document-document-1')

    sdk.searchCorpus.mockRejectedValue(new Error('connection refused'))
    await user.type(screen.getByTestId('search-input'), 's')

    expect(await screen.findByRole('alert')).toHaveTextContent('may be stale')
    expect(screen.getByTestId('document-document-1')).toBeInTheDocument()
  })
})

describe('document display helpers', () => {
  it('names a known kind and passes an unknown one through', () => {
    // `extraction_source` widens its kind CHECK by migration, and migration
    // 0010 says that is a story. A renderer that enumerated today's kinds
    // would turn the next one into a blank heading.
    expect(documentKindLabel(document())).toBe('Architecture summary')
    expect(documentKindLabel(document({ kind: 'action-items' }))).toBe('Action items')
    expect(documentKindLabel(document({ kind: 'something-new' }))).toBe('something-new')
  })

  it('names the model that wrote a generated document', () => {
    expect(documentProvenance(document())).toContain('written by test-model')
  })

  it('does not claim a model for an adopted document', () => {
    // The drop's summariser is not something this side observed, and implying
    // this system wrote it would be a provenance claim nothing supports.
    const adopted = document({ origin: 'adopted', model: null })
    expect(documentProvenance(adopted)).toContain('arrived in the source drop')
    expect(documentProvenance(adopted)).not.toContain('written by')
  })

  it('states the parse yield, singular and plural', () => {
    expect(documentYield(document({ itemCount: 1, artifactCount: 1 }))).toContain(
      '1 item parsed',
    )
    expect(documentYield(document({ itemCount: 4, artifactCount: 2 }))).toContain(
      '4 items parsed, 2 kept',
    )
  })
})
