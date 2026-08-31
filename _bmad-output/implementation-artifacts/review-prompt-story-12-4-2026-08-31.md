# Reviewer handoff — Story 12.4: Extraction Documents Are Searchable

Branch `story/12-4`, cut from `d250cf89`. Spec:
`_bmad-output/implementation-artifacts/spec-12-4-extraction-documents-are-searchable.md`
(status `review`). Story: `epics.md`, "### Story 12.4: Extraction Documents Are
Searchable" under "## Epic 12: Meeting-Level Analysis".

**Work in your own worktree**, on `story/12-4-review`, cut from `story/12-4`.
Never work in the main checkout, never commit to `main`, never merge — the owner
runs `integrate`. Do **not** run `make worktree-prune`: the owner ran it earlier
today and it deleted another builder's worktree, because a worktree with no
commits yet looks clean and already-merged to it.

## The review lane fixes what it finds

Owner ruling, 2026-08-30:

> Report every finding in the report file first (report-first, committed
> before reading code), then FIX the patchable ones yourself on
> `story/12-4-review` in your own worktree, red-first — the test observed
> failing against the unfixed code, then the fix, then green — committing each
> with its finding number. Leave unfixed, and clearly marked open, only what
> needs an owner decision or is rooted in the frozen spec. Never commit to
> `main`, never work in the main checkout, never merge — the owner runs
> `integrate`.

## Why the story exists

Story 12.1 kept each run's document; nothing could find one. Search and chat
retrieved over evidence and *published* artifacts, so the case that matters most
was the one the gate could never serve: a run that parsed to zero items produced
no artifact to approve, so there was nothing for the gate to pass, and its
document — the only readable trace of that run — stayed invisible. 45 runs on
the live corpus, none findable.

## What was built

Six commits, `76a6a2dd..18f1f020`.

| Path | Change |
|---|---|
| `server/meetingminer/projections/review.py` | NEW, pure. What a projected row says about its own review status: `reviewState` / `authorship` / `reviewLabel` / `citable`, composed and guarded. Generic — see the course correction below. |
| `server/meetingminer/projections/documents.py` | NEW, pure. The record builder, both guards, `DOCUMENTS_INDEX`, and the indexed-identity decision. |
| `server/meetingminer/projections/publish_gate.py` | `UNGATED_INDEXED_ROW_TYPES` + `require_ungated()`; module docstring names the exception and points at AD-4. |
| `server/meetingminer/projections/evidence.py` | `ExtractionDocumentRow`, `extraction_documents()`, `MeetingEvidence.documents`. |
| `server/meetingminer/projections/stores.py` | `ensure_document_search_schema`, `ALL_SEARCH_INDEXES`, drop coverage. |
| `server/meetingminer/projections/search.py` | `document_documents` / `documents_of` / `project_documents` / `delete_meeting_documents`; `project_meeting` now returns four counts. |
| `server/meetingminer/projections/__init__.py` | `project_extraction_documents()` — the locked settle-point entrypoint; `ProjectionOutcome.extraction_documents`. |
| `server/meetingminer/projections/query.py` | `DocumentHit`, `DocumentSearchResult`, `search_documents`, `DOCUMENT_SEARCHABLE_INDEXES`. |
| `server/meetingminer/pipeline/runner.py` | `_maybe_project_documents` — the second settle point, fired when `extract` settles. |
| `server/meetingminer/api/search.py` | `DocumentHitModel`, `SearchResponse.documents`, `_resolve_documents`, the third lane. |
| `server/meetingminer/api/chat.py` | `RetrievedDocument`, `_document_leg`, `_read_document_context`, prompt rule 5 and the per-meeting document budget. |
| `server/meetingminer/api/extraction.py` | Story 12.1's endpoint carries the same four label fields. |
| `server/meetingminer/config.py`, `config.yaml` | The `documents` index, and a loader that refuses one naming `momentId`. |
| `web/src/features/search/*` | The documents region, its helpers, and its own test file. |
| `web/src/client/*` | Regenerated. |

Untouched, deliberately: `pipeline/extraction.py`, `pipeline/stages/extract.py`
and the artifact-scope migration (story 12.2); `api/threads.py` and
`web/src/features/threads/` (story 10.7); `api/uploads.py`, `api/acquisitions.py`
(story 6.4a). **No migration** — `extraction_source.document_text` already
exists (0019), so the reserved 0023 was not used. `docs/architecture.md` and
`ARCHITECTURE-SPINE.md` were **not** edited: both already carry the AD-4 ruling
and were verified in sync at AD-4.

## Settled — do not re-argue

- **Documents bypass the publish gate.** Owner ruling 2026-08-31, already in
  AD-4 before the story started. Not a proposal, not this builder's decision.
- **A document is never a citation target.** Also AD-4/AD-6. If you think a
  document should be citable, that is an owner question, not a finding.
- **Both origins are indexed.** Owner ruling in AD-3 as amended, settled by
  story 12.1.

## Where to look hardest

1. **The AD-18 label, in the indexed record.** The story is explicit that a
   test must pin it in the record, not only in the UI. It is pinned in
   `test_projections_search.py::test_the_indexed_record_itself_carries_the_unreviewed_label`
   (against Meilisearch) and again in `test_projections_documents.py`. Is there
   a path that reaches a store without it?
2. **The five ways a document is kept uncitable** — record builder, both hit
   types, config loader, citation gate. Is there a sixth path?
   `_resolve_documents` re-reads from Postgres; check it cannot acquire a
   moment.
3. **The indexed identity.** One record per `extraction_source` row, keyed on
   that row's UUID, unchunked. Stated in `documents.py`'s docstring and pinned
   in three tests. The claim that a rerun *replaces* rests on `UNIQUE
   (meeting_id, kind)` plus the extract stage's upsert — verify the upsert
   really preserves the id (the test asserts `first == second`).
4. **The second settle point.** `_maybe_project_documents` fires once per pass
   when `extract` has settled, never fails the job, and touches only the
   documents index. Does it fire on the resumed-stage path as well as the
   done-stage path? Both call sites are there; confirm neither double-projects
   nor misses a shape of run.
5. **The chat leg.** It must contribute **no** moment id — verify `ordered` in
   `_answer` is unchanged by it (pinned by
   `test_a_document_adds_no_marker_and_no_citable_moment`). Prompt rule 5 tells
   the model documents are uncitable; the gate enforces it regardless. A
   meeting's documents are given to the **first** of its retrieved moment
   blocks and no other — the builder found and fixed a per-block repetition
   during the story, pinned by
   `test_a_meetings_documents_are_given_once_not_once_per_moment`. Check the
   ordering assumption that makes "first" well defined, and that a document
   whose meeting yielded no retrieved moment reaches nobody (also pinned).
6. **`documents_of` vs `document_documents`.** Two builders over one record
   function, for the settle point and the bundle pass. Confirm they cannot
   diverge.

## Course correction taken mid-story

The coordinator relayed an owner ruling that **artifacts must also be indexed
before they are published** (story 12.5). This story was **not** widened to
cover artifacts — an artifact is moment-anchored and genuinely citable where a
document never is. What changed instead, so 12.5 reuses rather than copies:

- The marking reports **which state** a row is in, not the boolean that it is
  unreviewed. A document has no lifecycle and reports `unreviewed`; an artifact
  will report `extracted` / `approved` / `published`.
- **Citability is carried, never derived from the state.** Deriving it would
  make 12.5's artifacts uncitable or this story's documents citable.
- The gate exception is a **declaration** (`UNGATED_INDEXED_ROW_TYPES`) that
  12.5 adds an entry to, not a documents-only branch.

Review this as a reusable mechanism, not only as this story's needs. One thing
12.5 will owe: `ARCHITECTURE-SPINE.md` and `docs/architecture.md` both say
extraction documents are "the one deliberate exception" to the gate. That is
true today and stops being true when 12.5 lands. Not a finding against this
story; a note for the next.

## Verification to reproduce

- `make lint` — clean, no new baseline entry.
- `make typecheck` — clean, 13 files.
- `make test-fast` — 2385 passed.
- `make test` — **2820 passed, 3 skipped, 0 failed, exit 0** (15m48s, at
  `53e354bf`). The three skips are the standing ones: `pyannote` not installed,
  and the two network tests that need an explicit env var. An earlier complete
  run found 3 failures, all shape pins this change legitimately widens
  (`search.counts()` covering a fourth index, in two suites, and
  `SearchResponse` gaining its documents array); all three were updated and the
  run above is post-fix. An independent re-run is still worth having.
- `python3 _bmad/scripts/branch_conflicts.py --against story/12-4`.

## Owed at integration, not by this story

`docs/project-record.md` has no entry for this story. It was left alone
deliberately: story 12.2 is in flight and touches the same file, and the
story's done-criteria do not include it. Add it at `integrate` time.
