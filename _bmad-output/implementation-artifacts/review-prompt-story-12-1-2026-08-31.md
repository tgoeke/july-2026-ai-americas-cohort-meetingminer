# Reviewer handoff — Story 12.1: Retain the Extraction Documents

Branch `story/12-1`, cut from `9fc760f`. Spec:
`_bmad-output/implementation-artifacts/spec-12-1-retain-the-extraction-documents.md`
(status `review`). Story: `epics.md`, "### Story 12.1: Retain the Extraction
Documents" under "## Epic 12: Meeting-Level Analysis" at the end of the file.

**Work in your own worktree**, on `story/12-1-review`, cut from `story/12-1`.
Never work in the main checkout, never commit to `main`, never merge — the
owner runs `integrate`.

## The review lane fixes what it finds

Owner ruling, 2026-08-30:

> Report every finding in the report file first (report-first, committed
> before reading code), then FIX the patchable ones yourself on
> `story/12-1-review` in your own worktree, red-first — the test observed
> failing against the unfixed code, then the fix, then green — committing each
> with its finding number. Leave unfixed, and clearly marked open, only what
> needs an owner decision or is rooted in the frozen spec. Never commit to
> `main`, never work in the main checkout, never merge — the owner runs
> `integrate`.

## Why the story exists

Measured on the live corpus 2026-08-31: 15 meetings, 45 extraction runs, 193
artifacts, and **zero retained documents**. `extraction_source` recorded
everything about a run except what the model wrote. The run whose text somebody
needs to read is exactly the run that yielded nothing worth approving.

## What was built

| Path | Change |
|---|---|
| `server/meetingminer/migrations/0019_extraction_document_text.sql` | NEW. `extraction_source.document_text` (nullable), a column comment stating what `NULL` means, and CHECK `octet_length(document_text) = byte_size`. |
| `server/meetingminer/pipeline/stages/extract.py` | `document_text` added to the upsert's columns, values and `DO UPDATE SET`; the adopted text that was discarded as `_text` is kept; the generated reply text is kept; new `_retained_text` guard; module docstring extended. |
| `server/meetingminer/api/extraction.py` | NEW route `GET /meetings/{meeting_id}/extraction-documents` (`listMeetingExtractionDocuments`), its two wire models, its two queries and its problem responses; module docstring rewritten for two routes. |
| `server/tests/test_worker_extract.py` | `extraction_sources` helper reads the new column; five new tests. |
| `server/tests/test_api_extraction_documents.py` | NEW. Ten route tests. |
| `web/src/client/*` | Regenerated for the new operation. |
| `docs/architecture.md` | AD-3 and AD-4 carry the 2026-08-31 amendments the spine already carried. |

`server/meetingminer/api/moments.py`, `pipeline/extraction.py` and
`config.yaml` are untouched.

## Settled — do not re-argue

- **Both origins store the text.** Owner ruling, recorded in AD-3 as amended
  2026-08-31. The reason is AD-4, not economy: `projections/` never opens an
  evidence file and `rebuild` regenerates both stores from Postgres plus
  `config.yaml` alone, so text living only in a drop could not be indexed and
  would fall out of search on every rebuild. A finding that cites AD-3's
  anti-copy rule against the adopted-document copy is a finding the amendment
  already answers.
- **The extraction-document search exception is story 12.4's**, not this
  story's. Nothing here indexes, chunks or projects.

## Where to look hardest

1. **"The stored bytes are the exact bytes the parser read" is the whole AC.**
   `_retained_text` re-encodes and re-hashes before the write; migration 0019
   CHECKs the length in the database. Attack it: is there any input for which
   `text.encode("utf-8")` is not the bytes that were hashed? A BOM, a lone
   `\r`, an astral-plane character, a drop file whose bytes changed between
   `sha256_and_size(path)` and `path.read_bytes()` (two separate reads, in
   `_read_drop_document`). If you find one, it is a high finding.
2. **The four upsert call sites.** The loop covers `arch-summary` and
   `action-items`; `topics` and `ranking-signals` have their own. Confirm all
   four pass `document_text` and that no future fifth kind can be added
   without one — is there a shape that would make omission impossible rather
   than merely noticed? A parameter-object or a single writer function is a
   legitimate finding if you think the four call sites will drift.
3. **`NULL` versus `""`.** These are different facts (predates retention vs.
   the document was empty) and the story's AD-18 argument rests on them
   staying different in the column, on the wire, and in the log. Check that no
   path can turn one into the other — Pydantic defaults, the generated TS
   client's optional field, `or ""` anywhere.
4. **The rerun replacement.** `document_text = EXCLUDED.document_text` sits in
   the same `ON CONFLICT DO UPDATE` as the counts. Is there any path that
   updates the counts without the text, or writes artifacts and then fails
   before the upsert in a way that survives? The stage runs inside the
   runner's transaction; verify that claim rather than taking it.
5. **The endpoint's gate and status codes.** It imports `_require_viewable`
   from `api/moments.py`, the way `api/speakers.py` does. Is the 409 right for
   a read of extraction output, or is it a policy borrowed without thought?
   Also: `200` with an empty list for a meeting whose extract stage never ran,
   `404` only for an id that names nothing. Argue with both if you disagree.
6. **Size.** A retained document is a few KB today, but nothing bounds it. A
   model that answers with 2 MB of markdown now puts 2 MB in a Postgres column
   and, later, in a search document. Is a bound needed, and if so is its
   absence a finding here or a backlog entry for 12.4?
7. **Story 12.4 must not be made harder.** It will index these documents
   ungated and label them unreviewed, keying chunk identity on the
   `extraction_source` row. Does anything here obstruct that — the nullable
   column, the ordering, the absence of an `id` on the wire? The response does
   **not** currently carry the `extraction_source` id; if 12.4 needs it, say
   so now.

## One known cross-branch overlap

`python3 _bmad/scripts/branch_conflicts.py --against story/12-1` reports
`main × story/12-1` **clean**. The only conflicting pair this branch introduces
is `story/12-1 × story/8-2a` on `web/src/client/index.ts` — both lanes
regenerated the committed TS client, and that file is one sorted export line.
It is the known recurring generated-artifact conflict the `integrate` skill
resolves by regenerating after the merge, not a design collision: the two
lanes add different operations and touch no other file in common. Every other
conflicting pair in that report is between two other branches, or is a stale
landed branch (`story/10-3`, `story/10-4`) diffing against the amended version
already on `main`.

## Verification to reproduce

- `uv run --project server pytest -m "" server/tests/test_worker_extract.py server/tests/test_api_extraction_documents.py -q`
- `make lint`, `make typecheck`, `make web-test`
- `make test` — the full gate, with your worktree's private stack up
- `python3 _bmad/scripts/branch_conflicts.py --against story/12-1-review`

Do not start the shared worker or api (a corpus ingest runs on the main stack
and extraction is bound to a paid model), and never run `make evals-run`. The
TS client here was generated from a locally dumped OpenAPI schema for that
reason; the method is recorded in the spec's change log and reproduces
`client.gen.ts` byte-identically.
