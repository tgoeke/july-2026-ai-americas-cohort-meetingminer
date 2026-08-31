---
title: 'Story 12.4: Extraction Documents Are Searchable'
type: 'feature'
created: '2026-08-31'
baseline_revision: 'd250cf89ee5eb40e401e7f2f8ded74d9fab81a33'
status: 'in-progress'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/planning-artifacts/epics.md'
  - '{project-root}/docs/architecture.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-12-1-retain-the-extraction-documents.md'
warnings: []
---

<intent-contract>

## Intent

**Problem:** Story 12.1 kept each extraction run's document on its
`extraction_source` row, and nothing can find one. Search and chat retrieve over
evidence and *published* artifacts, so the analysis a run produced is reachable
only by knowing which meeting to open. The case that matters is the one the
publish gate cannot serve at all: a run that parsed to zero items produced no
artifact to approve, so there is nothing the gate would ever pass, and its
document — the only readable trace of that run — stays invisible. Measured on
the live corpus 2026-08-31: 45 extraction runs, and not one of them findable.

**Approach:** A fourth Meilisearch index, `documents`, written by `projections`
like every other (AD-4's sole writer is unchanged). Every extraction document
is indexed **as soon as it is stored, approved or not** — the first deliberate
exception to the publish gate in this build, by owner ruling 2026-08-31 already
recorded in AD-4. `evidence.py` reads the retained text from Postgres, so the
projection module still opens no file and `rebuild` re-indexes from the row
alone. Two constraints ride with the exception and are enforced in code, not
prose: the record carries its unreviewed, machine-written status (AD-18), and it
carries no field a citation could resolve (AD-6). `/search` returns documents in
their own array; `/chat` reads them as labelled, uncitable context.

## Boundaries & Constraints

**Always:**
- **The exception is to reach, never to legibility.** Every indexed record
  carries `reviewState`, `authorship`, `reviewLabel` and `citable`, and the
  builder refuses one that lost them. Pinned in the *indexed record*, in the
  store — not only in the UI — because a label a renderer adds is a label the
  next renderer forgets (AD-18).
- **A document is never a citation target.** Pinned five ways: the record
  builder refuses any citation field, `DocumentHit` and `DocumentHitModel` have
  nowhere to put one, the config loader refuses a `documents` index that makes
  `momentId` filterable or sortable, and the citation gate refuses a marker
  naming a document. Content reaches an answer only through the moments its
  claims anchor to (AD-6).
- **The gate exception is declared, not carved.**
  `publish_gate.UNGATED_INDEXED_ROW_TYPES` names each ungated row type and why;
  `documents.py` reads its permission back through `require_ungated()` at
  import. A second row type joining is an entry, not a second bypass.
- **`projections/` opens no evidence file.** The text is a Postgres column
  (story 12.1). Asserted by making `open` raise inside the three modules that
  touch a document while a full `rebuild` runs.
- **The documents index is keyword-only.** No embedder is ever declared on it,
  so a model-host outage cannot withhold the documents the exception exists to
  keep reachable.
- **`null` and `""` stay different.** A pre-12.1 run has no text and is skipped;
  an empty document is indexed as itself. Collapsing them is the silent
  degradation AD-18 forbids.

**Block If:** none. The one decision that needed a human — whether documents
bypass the gate — was ruled on by the owner before the story started and is in
AD-4; it is not re-argued here.

**Never:**
- No `Document` graph node. The graph is traversed to reach citable evidence,
  and a document is never citable.
- No change to what an artifact may do. `published_artifacts()` still selects
  `WHERE state = 'published'`; story 12.5 is what changes that.
- No `pipeline/extraction.py`, `pipeline/stages/extract.py` or artifact-scope
  migration (story 12.2); no `api/threads.py` or `web/src/features/threads/`
  (story 10.7); no `api/uploads.py` or `api/acquisitions.py` (story 6.4a).
- No migration. `extraction_source.document_text` already exists (0019); 0023
  was available and not needed.
- No worker or api process started, no `make evals-run`, no model call. The TS
  client is generated from a locally dumped OpenAPI schema.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Unapproved document | any retained run | indexed; no gate consulted | none |
| Zero-yield document | `item_count = 0`, prose present | indexed with its zero counts | none |
| Pre-12.1 row | `document_text IS NULL` | not indexed; counted as `unretained` in the log | none |
| Honestly empty document | `""`, `byte_size` 0 | indexed as itself | none |
| Adopted document | `origin = 'adopted'`, no model | indexed; `model`/`promptHash` null, never invented | none |
| Re-extraction | extract runs twice | one record, replaced — keyed on the upserted row id | none |
| Record without its label | a builder that dropped a field | refused before a store sees it | `DocumentRecordRefused` |
| Record with a citation field | `momentId` added | refused by name | `DocumentRecordRefused` |
| Index hit missing its label | a store holding a foreign record | refused, naming `rebuild` as the repair | `ProjectionError` |
| `rebuild --all` | both stores dropped | documents re-indexed from Postgres alone | none |
| Meeting retired | `unproject_meeting` | its documents removed with everything else | none |
| Settle point | `extract` settles after evidence projection | documents indexed, moments/chunks untouched | logged, never fails the job |
| Documents index absent | store predates 12.4 | `documentsIndexMissing: true`, logged | none |
| Citation naming a document | `[[moment:<extraction_source id>]]` | whole answer discarded | `unresolvable-marker` |
| Search matched documents only | no moment matched | documents shown; the empty line says so precisely | none |
| Config names `momentId` | a hand-edited `config.yaml` | refused at load | `ConfigError` |

## Code Map

- `server/meetingminer/projections/publish_gate.py` — the gate's own account of
  itself, plus `UNGATED_INDEXED_ROW_TYPES` / `require_ungated`.
- `server/meetingminer/projections/review.py` — NEW, pure: what a projected row
  says about its own review status. Generic so story 12.5 reuses it.
- `server/meetingminer/projections/documents.py` — NEW, pure: the record
  builder, both guards, and the indexed-identity decision.
- `server/meetingminer/projections/evidence.py` — `ExtractionDocumentRow` and
  the Postgres read; the module's input surface, unchanged in kind.
- `server/meetingminer/projections/search.py` / `stores.py` / `__init__.py` —
  the fourth index: schema, write, delete, counts, the structural ride-along
  and the settle-point entrypoint.
- `server/meetingminer/pipeline/runner.py` — the second settle point.
- `server/meetingminer/projections/query.py` — the third lane.
- `server/meetingminer/api/search.py` / `chat.py` / `extraction.py` — the wire.
- `web/src/features/search/` — the rendering surface and its label.

## Tasks & Acceptance

**Execution:** see the six commits on `story/12-4`, `76a6a2dd..18f1f020`.

**Acceptance Criteria:**
- Given a stored extraction document, when it is stored, then it is indexed
  without passing the publish gate and `rebuild` re-indexes it from its
  Postgres row alone, with no file opened — asserted against Meilisearch and
  with `open` made to raise.
- Given AD-18, when a document is indexed or rendered, then it carries its
  unreviewed, machine-written status in the indexed record, and `/search`,
  `/chat` and the extraction-documents endpoint all render it from the same
  constants.
- Given AD-6, when a document's content appears in an answer, then no citation
  can resolve to it — asserted at the record, both hit types, the config loader
  and the citation gate.
- Given `chunking.py`, when a document is indexed, then it takes no identity
  from a transcript segment: one record per `extraction_source` row, keyed on
  that row's UUID, unchunked — stated and pinned.
- Given `publish_gate.py`, then its module docstring names the exception and
  points at AD-4.
- Given `make test`, then the full gate passes with no new ruff baseline entry.

### Review Findings

- [ ] [Review][Decision] Prevent document claims from borrowing an unrelated
  moment citation — the document schema has no claim-to-moment anchors, so the
  current prompt fold can supply a claim while an arbitrary retrieved moment
  supplies the marker. Owner must choose removal from synthesis or a
  deterministic claim-to-moment relation. See F-03 in
  `review-story-12-4-2026-08-31.md`.
- [ ] [Review][Decision] Define the finite indexed-document size policy —
  arbitrary length, exact full text, and one unchunked record cannot all hold
  under Meilisearch's finite HTTP payload ceiling. Owner must choose a retained
  source limit, configured store limit, searchable truncation, or revised
  chunking/identity. See F-11 in `review-story-12-4-2026-08-31.md`.
- [x] [Review][Patch] Ten patchable findings fixed red-first on
  `story/12-4-review`; full private-stack gate green. See F-01, F-02, F-04
  through F-07, F-09, F-10, and F-12 in the review report.

## Spec Change Log

- **2026-08-31, implementation — the indexed identity is one record per row,
  unchunked.** The story left this a build decision because a document is not
  citable. Chunking exists to make a passage citable at speaker-turn
  granularity and to bound what an embedder is handed; this index carries no
  vectors and nothing cites a document, so sub-document addressing would buy
  nothing and would invent a `sourceId#seq` id space that a re-extraction
  renumbers — the exact failure `chunking.py` refuses for chunks. Keyed on the
  row, the identity is a pure function of Postgres and `UNIQUE (meeting_id,
  kind)` makes a rerun a replacement.
- **2026-08-31, implementation — documents are a separate array on `/search`,
  not a third kind of `SearchHit`.** `SearchHit.momentId` is required because
  it is the citation shape. Widening it with a null would put an unreplayable
  citation where every consumer expects a replayable one, which is the silent
  degradation AD-18 forbids. A `DocumentHit` with no moment field is the
  mechanism: a consumer cannot build a citation because there is nothing there.
- **2026-08-31, implementation — a second settle point in the runner.**
  Evidence projects at evidence-complete; `extract` runs *after* that and is not
  an evidence stage, so its rows do not exist when the bundle is projected. The
  structural ride-along is what makes `rebuild` work; the settle point is what
  makes "as soon as it is stored" true. `pipeline/stages/extract.py` is story
  12.2's and was not touched.
- **2026-08-31, implementation — the documents index is keyword-only.** Not
  economy: an embedder on this index would let an Ollama outage withhold
  exactly the material the gate exception exists to keep reachable.
- **2026-08-31, implementation — the chat leg contributes no moment.** A ranked
  document is folded into the blocks of moments the other legs already found in
  its meeting, as labelled uncitable context under a new prompt rule. A document
  that ranks for a meeting no moment was retrieved from reaches nobody, which is
  correct: there would be nothing for a sentence drawn from it to cite. The
  citation gate and `CitationModel` are untouched.
- **2026-08-31, mid-story course correction from the coordinator — the
  mechanism was generalised.** The owner ruled that artifacts must also be
  indexed before publish (story 12.5). The story was **not** widened to cover
  artifacts — an artifact is moment-anchored and genuinely citable, and
  conflating the two would be wrong — but the marking now reports *which state*
  a row is in rather than the boolean that it is unreviewed, and the gate
  exception became a declaration (`UNGATED_INDEXED_ROW_TYPES`) rather than a
  documents-only code path. Citability is carried, never derived from the
  state: deriving it would make 12.5's artifacts uncitable or this story's
  documents citable. The composed document label is byte-identical to the
  constant it replaced.
- **2026-08-31, implementation — the TS client was generated from a locally
  dumped OpenAPI schema**, with a `servers: [{url: http://localhost:8000}]`
  entry, exactly as story 12.1 did and for the same reason: `make client`
  requires a live api on the shared fixed port `:8000`, which was forbidden to
  this lane while a corpus ingest runs. Verified byte-identical to a
  regeneration.
- **2026-08-31, implementation — three existing shape pins widened.**
  `search.counts()` now covers a fourth index (asserted in two suites) and
  `SearchResponse` gained its documents array. All three are the assertions
  doing their job, not incidental churn.

</intent-contract>
