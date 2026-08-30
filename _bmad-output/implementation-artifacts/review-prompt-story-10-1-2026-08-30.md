# Review handoff — Story 10.1: Topic Extraction

## REQUIRED OUTPUT — read this before any code

Your report goes to
`_bmad-output/implementation-artifacts/review-story-10-1-2026-08-30.md`.
Findings use: Location / Severity / Finding / Evidence / Suggested direction.
Report findings — do not fix.

**REPORT-FIRST:** create and commit the report file as a skeleton (scope, the
review range below, an empty findings section) BEFORE reading any code, then
append each finding as it is confirmed and commit incrementally. A crashed or
closed session must lose prose, never the artifact. Six reviews in this repo
were produced only as terminal text; a review reported in the terminal but not
filed does not exist.

**Closeout:** before reporting completion, run `make check-reviews` (it fails
while any dispatched review lacks a committed report — including this one) and
state the SHA carrying the report's final version.

## Repo, branch, range

- Repo: `/Users/devopsterus/current/cohort/meetingminer` — take your own
  worktree: `make worktree STORY=10-1-review`, never the main checkout.
- Branch: `story/10-1`. Review range: `5cdfce7..<branch head>`:
  - `5e44534` docs(10-1): plan Story 10.1 topic extraction — spec, epic-10 context, sprint status
  - `865544e` feat(10-1): topic extraction — third document through the extraction port
  - `1a03ebc` test(10-1): update the counts the third extraction document changes
  - plus the finalization commit (spec to review, review prompt, sprint files).

## Spec and intent

- Spec: `_bmad-output/implementation-artifacts/spec-10-1-topic-extraction.md`.
  The `<intent-contract>` block is frozen intent derived from epics.md
  "Story 10.1: Topic Extraction" (FR41, three Given/When/Then clauses) — do
  not critique its goals. Everything outside that block (Code Map, task
  order, design notes) is planner work you may attack.
- Builder contract with the frozen footprint table:
  `_bmad-output/implementation-artifacts/build-prompt-story-10-1-2026-08-30.md`;
  wave rules: `wave-2026-08-30-rules.md` (same directory).

## Architecture authorities

- `docs/architecture.md` AD-8 (one `Llm(extraction)` port — the topics
  document must go through the same port and parser discipline), AD-2
  (Postgres is the record — topics are rows there, nowhere else), AD-4/AD-5
  (one projection writer; worker-owned tables; nothing projected in this
  story), AD-10 (prompt is config, no code default), AD-11 (idempotent rerun).
- Story 4.1a/4.2 specs pin the whole-transcript extraction pattern and the
  visible-prompt contract this story extends; story 6.7's spec pins the
  prompt-wording generalisation the new prompt must honor.

## Scope

In scope: `config.yaml` (topics_prompt block), `server/meetingminer/config.py`
(one field), `pipeline/extraction.py`, `pipeline/stages/extract.py`,
`api/extraction.py`, `migrations/0014_topics.sql`, `docs/architecture.md`
(data-model note), `web/src/features/moments/*`, `web/src/client/` (regenerated),
the three new test files (`test_extraction_topics.py`,
`test_migrations_topics.py`, `test_api_extraction_prompts_topics.py`), and
four consequential edits outside the frozen footprint, each recorded in the
spec's change log with its mechanical necessity:
`server/tests/conftest.py` (EVIDENCE_TABLES append), `test_worker_extract.py`
(expectation counts only), `test_config.py` (one fixture line),
`test_api_prompts.py` (2 → 3 entries). Judge whether each stayed minimal.

Out of scope: threads/derivation/projection (10.2), thread curation (10.2a),
chat (10.2b), all Epic 10 UI views, the worker being run for real, and the
pre-existing `main × story/11-2` conflict on 11-2's own spec file (remediation
divergence, resolves at 11-2's integrate — not this story's).

## Design decisions to attack

1. **Permissive target sections for the topics document** (any heading is a
   target, like the action document) — rests on: strictness lives in the
   T-id/anchor rules plus a stage-level zero-topics signal keyed on meeting
   content, and the shared zero-artifact default document must parse to zero
   topics in every existing worker test. Attack: does this readmit the §8
   silent-zero shape anywhere the signal does not cover?
2. **One mention per (topic, containing moment), earliest stamp wins**, PK
   `(topic_id, moment_id)` — rests on: the moment is the citation unit, two
   stamps in one moment are one discussion.
3. **`topic_mention` cascades from `moment`** (unlike `artifact`'s deliberate
   refusal) — rests on: mentions are navigation metadata, not cited evidence.
4. **A topic whose every mention lands on superseded moments is dropped
   (logged)** rather than stored mention-less — rests on: a mention-less topic
   is navigation to nowhere.
5. **`anchors_ms` added to `ProposedArtifact`** (additive field) instead of a
   separate topic dataclass — rests on: one parser, one row shape.
6. **`extraction_source` widened to a third kind** (0014 drops/re-adds the
   named CHECK) with origin always `generated` — rests on: 0010's comment that
   widening is a story, and no drop declares a topics file.
7. **`PROMPT_VERSION` stays 2** — it tracks code constants; the config
   template is identified by `prompt_hash`.
8. **`topic_gist`** extracts the gist from the parsed body by dropping
   timestamp bookkeeping — attack its label heuristics.

## History a reviewer needs

- The build was interrupted once mid-lane by an API rate limit and resumed
  from the committed tree; commit `865544e` therefore carries the whole
  implementation and `1a03ebc` the consequential test-count updates.
- `web/src/client/` was regenerated from an in-process `app.openapi()` dump
  with an injected `servers` entry (story 2.2 precedent — never `make client`
  against a possibly-foreign :8000); the only diff is the kind union.

## Verification baseline

- `uv run --project server pytest server/tests/test_extraction_topics.py server/tests/test_api_extraction_prompts_topics.py server/tests/test_migrations_topics.py -q` — 31 passed, 0 skipped, ~9s (DB-backed parts against the per-run Postgres database).
- `make test-fast` — 1432 passed, 326 deselected (the slow set), 0 skips, 50s.
- `make web-test` — 294 passed (16 files).
- `make test` — full gate green, exit 0: server suite 1758 passed (slow set included, per-run database, twins up), 13m17s; web production build succeeded.
- `python3 _bmad/scripts/branch_conflicts.py --against story/10-1` — every pair involving `story/10-1` clean except `story/10-1 × story/11-2-review` (exempt); `main × story/11-2` conflicts pre-exist this story on 11-2's own spec file.

A skip or failure you see that this baseline does not carry is a finding, not
noise.
