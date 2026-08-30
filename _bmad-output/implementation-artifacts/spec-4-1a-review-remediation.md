---
title: 'Story 4-1a review remediation: trustworthy extraction documents'
type: 'bugfix'
created: '2026-08-20'
status: 'done'
review_loop_iteration: 0
baseline_commit: '9bc2aa4a7846a08fd788b319422121bf119c4d8e'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/spec-4-1a-whole-transcript-extraction.md'
  - '{project-root}/_bmad-output/implementation-artifacts/review-story-4-1a-2026-08-20.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Whole-transcript extraction can accept an unrelated markdown document
as a successful empty result, and a new source drop can carry documents from a
prior version of the transcript. The puller's streaming reader also ignores a
valid final NDJSON record when it is not newline-terminated.

**Approach:** Tighten parser acceptance to the contract's target sections and
make the pull-to-drop handoff select only the documents produced for its current
transcript run. Flush and consume the final Ollama stream record before deciding
whether generation produced output.

## Boundaries & Constraints

**Always:** Keep Story 4-1a's one strict parser for adoption and generation,
the named malformed-document failure/retry behavior, generation non-fatal, and
drop emission unconditional. A pull may carry either document kind, but every
carried document must be fresh for the transcript handed off in that run. Keep
action-item owner headings free-form and preserve both table and bullet layouts.

**Ask First:** Halt if preventing stale documents requires changing intake,
re-emitting finalized drops, or changing the adopted/generated provenance
contract.

**Never:** Do not start the worker or make a real model call. Do not alter CAP-5,
the two-document generation interpretation, API code, finalized drops, or the
existing deferred backfill limitation.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Unrelated markdown | Architecture-summary has only an unrelated heading/table | Parser refuses it as malformed; generated path retries once and adopted path fails by name | Job fails at `extract`; no source row/artifacts commit |
| Prior documents with `--no-summary` | Same-stem docs exist but current pull does not generate | New drop declares and carries no extraction docs | Emit/post still runs |
| Partial generation | Fresh summary succeeds; action generation fails with old action file present | Drop carries/declares only the fresh summary, never the old action document | Named generation diagnostic; emit/post still runs |
| Unterminated final NDJSON | Ollama ends stream after a valid non-newline JSON record | Generated markdown contains that record's content | Normal success |

</frozen-after-approval>

## Code Map

- `server/meetingminer/pipeline/extraction.py` --
  `parse_extraction_document()` currently treats any parsed table/bullet as
  structure (`:807-905`). Tighten recognition only for architecture-summary
  target sections; `DOC_ACTION_ITEMS` deliberately permits free-form owner
  headings through `_section_is_target()`.
- `server/meetingminer/pipeline/stages/extract.py` -- `_adopt()` and
  `_generate()` already turn parser failures into the required named failure and
  one retry (`:210-261`); no new stage policy should be introduced.
- `server/tests/test_extraction_core.py` -- rejection table around `:623-645`
  and parser acceptance fixtures are the store-free regression location.
- `server/tests/test_worker_extract.py` -- malformed adopted/generated document
  tests around `:603` prove the retry and zero-call behavior end to end.
- `pull_transcript/grab-teams-transcript.js` -- `summarizeTranscript()` drains
  only newline records (`:938-956`); `generateDocs()` writes stable same-stem
  names (`:987-992`); `finishPull()` controls summary, emit, and post ordering
  (`:1018-1064`).
- `pull_transcript/emit-drop.js` -- `planDrop()` discovers summaries from disk
  and `emitDrop()` stages them. Add a narrowly-scoped handoff override for an
  explicit current-run document selection while preserving normal standalone
  and backfill discovery.
- `pull_transcript/test/finish-pull.test.js` -- ordering/injection seam for
  stale-document and partial-generation coverage; add or expose a small
  stream-parser seam for the final-record test.
- `pull_transcript/test/emit-drop.test.js` -- protects summary declaration and
  staging behavior; retain its standalone discovery and schema assertions.

## Tasks & Acceptance

**Execution:**
- [x] `server/meetingminer/pipeline/extraction.py`, `server/tests/test_extraction_core.py`, and `server/tests/test_worker_extract.py` -- reject markdown that has no recognized architecture-summary target structure, while retaining flexible valid headings/layouts; add core and stage regressions for adopted refusal and generated retry.
- [x] `pull_transcript/grab-teams-transcript.js` and `pull_transcript/emit-drop.js` -- pass an explicit per-run extraction-document selection from the pull tail to the emitter so stale on-disk files cannot enter a new handoff; retain standalone emitter discovery and non-fatal generation.
- [x] `pull_transcript/grab-teams-transcript.js` and `pull_transcript/test/finish-pull.test.js` -- flush decoder bytes and parse a final buffered NDJSON record through the same validation path; cover stale `--no-summary`, partial generation, and unterminated-stream behavior.

**Acceptance Criteria:**
- Given an unrelated architecture-summary table, when either path parses it,
  then it follows the malformed-document path rather than a successful empty
  extraction.
- Given changed transcript content and prior same-stem markdown files, when the
  pull emits without generation, then the new drop has no extraction declaration
  or markdown files.
- Given only one current-run document generation succeeds, when the pull emits,
  then it carries only that fresh document and its matching declaration.
- Given a valid final Ollama NDJSON object without a newline, when the stream
  closes, then its message content is written to the generated document.

## Spec Change Log

## Design Notes

The puller must distinguish documents discovered by a standalone/backfill
`emit-drop.js` invocation from documents authorized by the active pull run. An
explicit, possibly empty selection is the safest boundary: it preserves the
existing manual behavior while letting `finishPull()` refuse stale same-stem
files without making drop emission conditional on model success.

## Verification

**Commands:**
- `cd server && uv run pytest tests/test_extraction_core.py tests/test_worker_extract.py -q` -- expected: parser and stage regressions pass with no real LLM.
- `make puller-test` -- expected: all puller tests pass, including stale-file,
  partial-generation, and final-NDJSON coverage.
- `cd server && uv run pytest tests/ -q` -- expected: full server suite passes.
- `make web-test` -- expected: web suite remains unaffected.

## Suggested Review Order

**Current-run document authority**

- The pull tail authorizes only documents produced for this transcript run.
  [grab-teams-transcript.js:1072](../../pull_transcript/grab-teams-transcript.js#L1072)

- The emitter honors an explicit selection while preserving standalone discovery.
  [emit-drop.js:441](../../pull_transcript/emit-drop.js#L441)

- Independent calls preserve a fresh partial result and record the failed sibling.
  [grab-teams-transcript.js:1001](../../pull_transcript/grab-teams-transcript.js#L1001)

**Stream and parser refusals**

- EOF flush sends every valid Ollama record through the existing validation path.
  [grab-teams-transcript.js:938](../../pull_transcript/grab-teams-transcript.js#L938)

- Only target-section markdown establishes a recognizable extraction document.
  [extraction.py:807](../../server/meetingminer/pipeline/extraction.py#L807)

- Standalone backfills surface document failures rather than falsely succeeding.
  [grab-teams-transcript.js:1029](../../pull_transcript/grab-teams-transcript.js#L1029)

**Regression coverage**

- Tests cover stale files, partial success, and final unterminated NDJSON.
  [finish-pull.test.js:109](../../pull_transcript/test/finish-pull.test.js#L109)

- Direct and CLI tests cover independent generation and standalone failure status.
  [summarize-docs.test.js:13](../../pull_transcript/test/summarize-docs.test.js#L13)
