---
title: 'Story 12.1: Retain the Extraction Documents'
type: 'feature'
created: '2026-08-31'
baseline_revision: '9fc760fe939922528826da9a54e891694e0c7bad'
status: 'review'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/planning-artifacts/epics.md'
  - '{project-root}/docs/architecture.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-10-4-moments-feed-ranking.md'
warnings: []
---

<intent-contract>

## Intent

**Problem:** Extraction already runs whole-transcript, and everything the model
wrote is thrown away. `extraction_source` records each run's kind, origin,
model, prompt hash, sha256, byte size, layout and counts — everything *about* a
run except the run's own output — because the table has no column for the text.
The document is parsed into artifacts and discarded. Measured on the live corpus
2026-08-31: **15 meetings, 45 extraction runs, 193 artifacts, and zero retained
documents.** The run whose text somebody needs to read is exactly the run that
yielded nothing worth approving, and today that run leaves nothing readable at
all.

**Approach:** One column and one endpoint. Migration 0019 adds
`extraction_source.document_text`; the extract stage writes it at all four
upsert call sites, on both origins — the document generated through the
`Llm(extraction)` port and the one a drop already carried. The stored text is
checked against the `sha256` and `byte_size` the same row records before it is
stored, so the checksum already there verifies against the bytes now kept.
`GET /meetings/{meeting_id}/extraction-documents` serves each run's document as
the markdown it is, beside the kind, model, prompt hash and item count that
describe it.

## Boundaries & Constraints

**Always:**
- **The stored bytes are the exact bytes the parser read.** Not a re-render,
  not a normalization, not the parse. `_retained_text` refuses any text that
  does not reproduce the recorded digest and length, and migration 0019 CHECKs
  `octet_length(document_text) = byte_size` in the database. Tests re-hash the
  stored text for every kind and both origins.
- **Both origins store it, and the reason is AD-4, not economy.** Every
  extraction document must be searchable (story 12.4); `projections/` never
  opens an evidence file and `rebuild` regenerates both stores from Postgres
  plus `config.yaml` alone, so text living only in a drop could not be indexed
  and would fall out of search on every rebuild. AD-3's anti-copy rule governs
  material the system *serves but does not retrieve over*, so it does not reach
  here (AD-3 as amended 2026-08-31). This was an owner ruling; it is not
  re-argued here.
- **An adopted document keeps its `drop_relative_path`.** The copy is what
  makes the document indexable; it does not replace provenance.
- **A rerun replaces the document wholesale.** `document_text` is set in the
  same `ON CONFLICT DO UPDATE` that sets the counts, inside the stage's own
  transaction, so there is no branch on which the artifacts change and the
  stored document does not.
- **A document that yielded nothing is retained regardless,** and the existing
  `stage.extract.zero_artifacts` signal fires unchanged. That is the case the
  story exists for.
- **`null` document text and `""` mean different things and stay different.**
  `null` is a run that predates retention and needs re-extracting; `""` is a
  document that really was empty. Collapsing them is the silent degradation
  AD-18 forbids, so they are distinct in the column, on the wire, and in the
  listing's log line, which names the unretained kinds.
- **The endpoint serves markdown, never a rendering of it.** Byte-identical,
  so a reader sees everything the parser ignored.
- **`extraction_source` stays worker-owned (AD-5).** The api reads it and
  writes nothing; the route makes no model call.

**Block If:** none — no decision here needed a human. The one open question
(should an adopted document's text be copied?) was ruled on by the owner
before the story started and recorded in AD-3.

**Never:**
- No indexing, no chunking, no projection change — that is story 12.4, which
  reads this column. Nothing here makes it harder: the text is a Postgres value
  on the row whose id 12.4 will key a chunk on.
- No `summary` artifact kind, no nullable `artifact.moment_id` (story 12.2), no
  meeting analysis panel or web work (story 12.3).
- No worker or api process started, no `make evals-run`, no real model call.
  The TS client is generated from a locally dumped OpenAPI schema rather than
  by starting the shared api on its fixed port.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Adopted document | drop carries `extraction-summary.md` | text stored byte-identical to the drop file; `drop_relative_path` unchanged | none |
| Generated document | drop carries none | the model's reply verbatim, prose the parser ignored included | none |
| Always-generated kinds | `topics`, `ranking-signals` | retained on the same terms as the two artifact documents | none |
| Checksum | any stored document | `sha256(document_text.encode())` equals the recorded `sha256` | `StageError` naming the document |
| Rerun | extract runs twice, different reply | document and artifacts replaced together; nothing of the prior run survives | none |
| Zero-item document | populated sections, no parsed items | retained; `stage.extract.zero_artifacts` still fires | none |
| Honestly empty document | bare table header | retained as its own bytes, not as `null` | none |
| Pre-12.1 row | `document_text IS NULL` | served as `null`, `byteSize` from its own row, named in the listing log | none |
| NUL in ignored prose | valid UTF-8, unstorable in Postgres `text` | refused by name, meeting fails | `StageError` naming the document |
| Length disagreement | text whose bytes differ from `byte_size` | refused | DB CHECK `extraction_source_text_matches_byte_size` |
| Endpoint, four kinds | a completed run | four documents ordered by `kind` | none |
| Endpoint, no rows | extract has not run | `200` with an empty list | none |
| Endpoint, unknown meeting | random UUID | `404 not-found`, `application/problem+json` | Problem |
| Endpoint, malformed id | `not-a-uuid` | `422 invalid-request` | Problem |
| Endpoint, unsettled meeting | an evidence stage running | `409 meeting-not-viewable` | Problem |

## Code Map

- `server/meetingminer/migrations/0010_extraction_sources.sql` — READ-ONLY.
  The table 0019 extends; its `UNIQUE (meeting_id, kind)` is what makes the
  rerun a replacement rather than an accumulation.
- `server/meetingminer/migrations/0018_ranking_signals.sql` — READ-ONLY. The
  most recent widening of the same table, and the shape 0019's comments follow.
- `server/meetingminer/pipeline/stages/extract.py` — four
  `_UPSERT_EXTRACTION_SOURCE` call sites: the `DOCUMENT_KINDS` loop (both
  origins), the topics pass, the ranking-signals pass.
- `server/meetingminer/api/moments.py` — READ-ONLY (story 2.2). Source of
  `_require_viewable`, imported the way `api/speakers.py` already imports it,
  so the new route passes the same gate every meeting-scoped read passes.
- `server/meetingminer/api/registry.py` — READ-ONLY. Checked: every existing
  `/meetings/{meeting_id}/…` route has a literal second segment, so
  `extraction-documents` introduces no literal-under-parameterized hazard and
  needs no `ROUTER_ORDER`.
- `server/tests/projection_seed.py` — READ-ONLY. `seed_meeting` is the api
  tests' entry point.

## Tasks & Acceptance

**Execution:**
- `server/meetingminer/migrations/0019_extraction_document_text.sql` — NEW:
  the `document_text` column, its column comment, and the
  length-equals-`byte_size` CHECK.
- `server/meetingminer/pipeline/stages/extract.py` — ADD `document_text` to the
  upsert's column list, values and `DO UPDATE SET`; keep the adopted text that
  was being discarded as `_text`; keep the generated reply text; ADD
  `_retained_text`; extend the module docstring.
- `server/meetingminer/api/extraction.py` — ADD `ExtractionDocument`,
  `MeetingExtractionDocumentsResponse`, `_MEETING_DOCUMENTS`, `_MEETING_EXISTS`,
  `_DOCUMENTS_PROBLEM_RESPONSES` and the route; extend the module docstring.
- `server/tests/test_worker_extract.py` — the `extraction_sources` helper reads
  the new column (so every existing exact-row assertion covers it), and five
  new tests.
- `server/tests/test_api_extraction_documents.py` — NEW: ten route tests.
- `web/src/client/*` — regenerated for `listMeetingExtractionDocuments`.
- `docs/architecture.md` — AD-3 and AD-4 carry the 2026-08-31 amendments the
  spine already carried.

**Acceptance Criteria:**
- Given the extract stage, when a document is produced or parsed, then its full
  text is persisted with the `extraction_source` row and the stored bytes are
  the exact bytes the parser read — asserted by re-hashing the stored text and
  comparing it to the recorded `sha256`, for every kind and both origins.
- Given a document a drop carried, when it is adopted, then its text is stored
  exactly as a generated one is and both are read back through one path.
- Given a rerun, when a meeting is extracted again, then the document is
  replaced wholesale alongside the artifacts derived from it.
- Given the api, when a meeting's extraction runs are requested, then each run's
  document text is served with its kind, model, prompt hash and item count, as
  the markdown it is.
- Given a document that parsed to zero items while plainly carrying content,
  when it is stored, then it is retained and the existing named signal fires.
- Given `make test`, then the full gate passes with no new ruff baseline entry.

## Spec Change Log

- **2026-08-31, implementation — `docs/architecture.md` edited, deliberately
  and on the record.** AD-3 and AD-4 were amended today (`726539b4`,
  `1349a37f`) in `ARCHITECTURE-SPINE.md` only; `docs/architecture.md` was last
  reconciled at `99e8535a`, before both. The two documents must agree at
  AD-1…AD-18, and these are precisely the two decisions this story turns on, so
  a reader of the shorter document would have found AD-3 arguing against the
  copy this story makes. The edit is additive to those two decisions, adds no
  AD, and leaves the count line ("Eighteen decisions") unchanged.
- **2026-08-31, implementation — the column is nullable rather than
  `NOT NULL DEFAULT ''`.** 45 rows exist on the live corpus with no text to
  backfill. `''` would have made "predates retention" indistinguishable from
  "the document was empty", which are different facts calling for different
  actions. `NULL` says the first and only the first, and story 12.4 can label
  or skip such a row rather than indexing an empty string as a document.
- **2026-08-31, implementation — the DB constraint is a length equality, not a
  digest equality.** Postgres has no built-in sha256 over text without
  `pgcrypto`, which this build does not install. `octet_length` catches every
  realistic re-rendering; the digest half is enforced in `_retained_text` at
  the write and re-verified in the tests.
- **2026-08-31, implementation — a NUL is refused by name.** It is valid UTF-8,
  valid in a Python string, and unstorable in Postgres `text`. In the parsed
  fields it already failed on the artifact insert; in prose the parser ignores,
  it would have reached psycopg as an unattributed `DataError` naming no
  document. The test places it in ignored prose for exactly that reason.
- **2026-08-31, implementation — the TS client was generated from a locally
  dumped OpenAPI schema.** `make client` requires a live api on the fixed port
  `:8000`, which is shared across checkouts (backlog B-35) and was forbidden to
  this lane. The schema was dumped from `app.openapi()` with a
  `servers: [{url: http://localhost:8000}]` entry added, which reproduces
  `client.gen.ts` byte-identically — verified: the only diff is the new
  operation.

- **2026-08-31, implementation — one known cross-branch overlap.**
  `branch_conflicts.py --against story/12-1` reports `main × story/12-1` clean.
  The only conflicting pair this branch introduces is
  `story/12-1 × story/8-2a` on `web/src/client/index.ts`: both lanes
  regenerated the committed client, which is one sorted export line. Resolved
  by regenerating after the merge — `make client` is integration-owned.

## Review Triage Log

### Review Findings — 2026-08-31

- [ ] [Review][Decision] F5 — A rerun can orphan surviving approved artifacts
  from their retained source document. Story 4.1 preserves an approved
  moment's complete artifact set, while Story 12.1 overwrites the only source
  row with the new reply. Correct remediation requires an owner choice among
  versioned sources and links, freezing reruns, or a lifecycle change; the
  review lane does not silently choose one.
- [ ] [Review][Patch] F1 — Make `documentText` required-but-nullable in OpenAPI
  and the generated client. [`server/meetingminer/api/extraction.py:135`]
- [ ] [Review][Patch] F2 — Type 404 and 409 `application/problem+json` bodies as
  `ProblemDetails`. [`server/meetingminer/api/extraction.py:95`]
- [ ] [Review][Patch] F3 — Turn lone-surrogate encoding failures into a named
  document-specific `StageError`. [`server/meetingminer/pipeline/stages/extract.py:468`]
- [ ] [Review][Patch] F4 — Align the route's public description with AD-4's
  claim-about-evidence boundary. [`server/meetingminer/api/extraction.py:174`]
- [ ] [Review][Patch] F6 — Add negative verification for digest disagreement,
  adopted two-read disagreement, and the database length CHECK.
  [`server/meetingminer/pipeline/stages/extract.py:919`]

## Design Notes

**Why the check lives in `_retained_text` and not at the call sites.** On the
adopt path the digest and the text come from **two separate reads** of the same
file (`sha256_and_size(path)` then `path.read_bytes()`). A drop is write-once so
the two agreeing is expected, but "expected" is not "checked", and the failure
mode is a row whose recorded checksum describes bytes nobody has — invisible
afterwards, which is the AD-18 shape. One function, called at every site, makes
the guarantee a property of the write rather than of each caller's care.

**Why the endpoint passes `_require_viewable`.** Not because a document is
evidence, but because every other meeting-scoped read answers 409 while
augmentation is in flight, and a route that answered 200 from the same
half-settled meeting would be a second policy for readers to learn. Importing
the gate rather than copying it is the precedent `api/speakers.py` set.

**Why an empty list rather than a 404 for a meeting with no runs.** A meeting
whose extract stage has not run is a state, not a missing resource. The 404 is
reserved for a meeting id that names nothing, so a client can tell "not
extracted yet" from "no such meeting" without parsing a message.

**Why ordering is by `kind`.** The four rows describe four documents of one
run, not a sequence. Alphabetical is a contract a test can hold and a client can
render without inventing a ranking the data does not carry.

## Verification

**Commands:**
- `uv run --project server pytest -m "" server/tests/test_worker_extract.py server/tests/test_api_extraction_documents.py -q`
- `make lint` / `make typecheck`
- `make web-test`
- `make test` — the full gate with this worktree's private stack up.
- `python3 _bmad/scripts/branch_conflicts.py --against story/12-1`

## Auto Run Result

Completed 2026-08-31 on `story/12-1`, cut from `9fc760f`. Status `review`, not
`done`: the review lane has not run and this lane does not merge.

**Commits (pushed to `origin/story/12-1`):**

- `ceed8ef7` — migration 0019 and the stage: `document_text` on both paths,
  `_retained_text`, the docstring.
- `7c018963` — `GET /meetings/{meeting_id}/extraction-documents` and the five
  stage tests.
- `8fd76ceb` — the ten route tests and the regenerated TS client.
- `3d79a91f` — this spec, the review prompt, the sprint key, the AD-3/AD-4 sync.

**Gates, all run in the foreground against this worktree's private stack
(`meetingminer-12-1`):**

- `make test` — **2741 passed, 3 skipped, exit 0**, 714.71s (11m54s), followed
  by the web production build (`tsc -b && vite build`, exit 0). The three skips
  are the suite's standing named skips, not new ones.
- `make lint` — all checks passed, no new baseline entry.
- `make typecheck` — success, no issues in 13 source files.
- `make web-test` — 24 files, 441 tests passed.
- `uv run --project server pytest -m "" server/tests/test_worker_extract.py -q`
  — 29 passed (24 pre-existing plus the 5 new).
- `uv run --project server pytest -m "" server/tests/test_api_extraction_documents.py -q`
  — 10 passed.
- `python3 _bmad/scripts/branch_conflicts.py --against story/12-1` —
  `main × story/12-1` **clean**; one introduced pair,
  `story/12-1 × story/8-2a` on `web/src/client/index.ts` (see the change log).

**Not run, deliberately:** `make evals-run`, the shared worker, the shared api.
A corpus ingest is running on the main stack and extraction is bound to a paid
model; no real model call was made anywhere in this lane.

**One observed-red moment worth recording.** The NUL test was written first
against a document whose NUL sat in a *parsed* field; it failed with
`unexpected DataError: PostgreSQL text fields cannot contain NUL (0x00) bytes`,
raised by the `artifact` insert rather than by `_retained_text`. That is the
pre-existing behaviour and not what this story adds, so the test was moved to a
NUL in prose the parser ignores — the only path on which the retained document
is the thing that carries it — where `_retained_text`'s named refusal is what
fires. The guard is therefore demonstrated to be reachable and load-bearing
rather than defensive decoration.

</intent-contract>
