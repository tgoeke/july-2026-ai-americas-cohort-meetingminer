# Code review — Story 4-1a: Whole-Transcript Extraction

**Verdict: pass after remediation.** The specification interpretation and all
three implementation findings are resolved and verified below.

## Scope

- Initial reviewed range: `100b0992..d6a1b40`; remediation through `5dce88b`
  on `story/4-1a`.
- Review mode: full, against the frozen Story 4-1a contract and its listed
  Epic 4 and Story 4.1 context documents.
- Report initialized before implementation inspection; findings are appended
  only after they are independently confirmed.

## Findings

### Decision needed — CAP-5 contradicts the frozen Story 4-1a generation shape

**Evidence:** `_bmad-output/specs/spec-meetingminer/SPEC.md:47`,
`config.yaml:25`, and
`_bmad-output/implementation-artifacts/spec-4-1a-whole-transcript-extraction.md:184-189`.

CAP-5 says extraction runs "in one pass per meeting", while the committed
configuration says it invokes the local model twice per meeting and the frozen
I/O matrix requires one whole-transcript generation per document kind. The
implementation at `server/meetingminer/pipeline/stages/extract.py:325-352`
correctly follows the latter shape and the adopt path expects two independent
markdown documents. **Resolved 2026-08-20:** CAP-5 means one logical
whole-meeting extraction pass, so the implementation remains two
document-kind calls. The spec kernel needs an explicit clarification; a
single-call redesign is not required.

### Medium — unrelated markdown is accepted as a successful zero-result

**Evidence:** `server/meetingminer/pipeline/extraction.py:807-825,905-922`.

`structure_seen` becomes true for any markdown table row or bullet, before the
parser establishes that it belongs to a target section or carries a recognized
item. Consequently, an adopted architecture-summary document containing only
`# Notes` and a normal `| Topic | Detail |` table returns an empty
`ParsedDocument(layout="none")`; the stage writes an extraction-source row and
completes, with neither a malformed-document refusal nor the target-section
zero-artifact signal. This violates the matrix's "Neither layout matches a
required section → StageError" path. Require recognizable target-section
structure before accepting a document, and add both adopted and generated
regressions that fail on the unfixed parser.

### High — a drop can adopt summariser output from a different transcript

**Evidence:** `pull_transcript/grab-teams-transcript.js:987-992,1037-1047`
and `pull_transcript/emit-drop.js:389-416`.

Generated documents are written directly to persistent same-stem paths, and
`emitDrop()` carries any documents it finds there. A `--no-summary` rerun after
the transcript changes therefore emits existing documents from the earlier
transcript. The same outcome occurs if the architecture summary generation
succeeds but action-item generation fails: the newly written summary is paired
with a prior action-items file. The worker then adopts those bytes as arrived
material without any transcript association check, yielding artifacts and
citations for the wrong meeting content. Ensure a new drop carries only a
complete, freshly generated document pair for its current transcript (or no
documents for a missing kind), including failure and `--no-summary` paths; add
tests that demonstrate the stale-file cases against the unfixed behavior.

### Low — a valid final Ollama stream record is ignored without a trailing newline

**Evidence:** `pull_transcript/grab-teams-transcript.js:940-956`.

The decoder processes records only while `buf.indexOf("\\n") >= 0`; on EOF it
never flushes `buf` (or the `TextDecoder`) before testing `out`. A conforming
NDJSON stream whose final record has no terminating newline loses that response
content, commonly resulting in the named empty-response failure and a drop
that needlessly lacks documents. Flush the decoder and parse the non-empty
residual buffer under the same error handling, with a regression test.

## Remediation

- `dffbb3b` rejects unrelated architecture-summary markdown, makes the pull
  handoff authorize only current-run document kinds, retains a fresh partial
  result, and consumes a final unterminated NDJSON record.
- `5dce88b` preserves the pull handoff's non-fatal behavior while making
  standalone `--summarize` report returned document failures and exit nonzero.
  It also directly tests independent default generation after a sibling failure.

The remediation review's only real follow-up was the standalone CLI regression;
it was fixed and the complete verification set was re-run. Other suggestions
were either the deliberately named target-section zero-artifact signal, internal
test-double hardening, or an out-of-scope concurrent re-pull design question.

## Verification run by reviewer

- `cd server && uv run pytest tests/test_extraction_core.py -q` — 103 passed.
- `cd server && uv run pytest tests/test_extraction_core.py tests/test_worker_extract.py -q` — 126 passed.
- `cd server && uv run pytest tests/ -q` — 1,329 passed, 0 failed (5m33s).
- `make puller-test` — 124 passed.
- `make web-test` — 157 passed.
- `rg -n 'import litellm|from litellm' server/meetingminer --glob '!server/meetingminer/adapters/llm/**'` — no matches.

## Scope conformance

The implementation changes are inside the frozen Story 4-1a boundary. CAP-5's
conflicting wording is spec-kernel text and needs a spec-owner decision rather
than a story-branch edit.
