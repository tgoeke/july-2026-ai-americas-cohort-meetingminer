---
title: 'Story 12.2: The Meeting Summary'
type: 'feature'
created: '2026-08-31'
baseline_revision: 'd250cf89ee5eb40e401e7f2f8ded74d9fab81a33'
status: 'review'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/planning-artifacts/epics.md'
  - '{project-root}/docs/architecture.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-12-1-retain-the-extraction-documents.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-12-context.md'
warnings: []
deferred: []
---

<intent-contract>

## Intent

**Problem:** The architecture-summary document is a whole-meeting analysis, and
only its decision rows survive parsing. The executive-summary prose is read and
dropped, so the one thing the extraction wrote *about the meeting as a whole*
has no row, no lifecycle and no reader. Nothing in the schema can hold it
either: `artifact.moment_id` is `NOT NULL`, so every artifact must hang from a
moment.

**Approach:** Widen the scope, not the citation contract. Migration 0022 makes
`moment_id` nullable, adds `summary` to the kind CHECK, and adds one constraint
that declares — in exactly one place — which kinds are meeting-scoped. The
parser gains a `summary` field taken from the document's own executive-summary
section; the extract stage writes it as an `artifact` row with `moment_id NULL`,
into the same `extracted → approved → published` lifecycle, published by the
same function the per-moment gesture calls. Nothing becomes citable that was
not citable before.

## Boundaries & Constraints

**Always:**
- **Scope is declared in exactly ONE place.** `artifact_scope_matches_kind`
  CHECKs `(kind IN ('summary')) = (moment_id IS NULL)`. No Python, TypeScript or
  other SQL carries a second copy of the meeting-scoped kind list. Readers that
  must distinguish the two scopes branch on the observable fact
  `moment_id IS NULL`, never on a kind name.
- **Widening scope must not weaken the anchor.** Migration 0009's composite
  `FOREIGN KEY (moment_id, meeting_id) REFERENCES moment (id, meeting_id)` is
  left exactly as it stands. Postgres MATCH SIMPLE satisfies it when
  `moment_id` is NULL and enforces it in full when it is present, so no
  artifact can still name a moment belonging to another meeting. A test asserts
  the cross-meeting insert is refused *after* 0022, not only before it.
- **The citation contract does NOT widen, and this is not relitigated.**
  `meeting_id` is scope and provenance, never a citation. A meeting-scoped
  artifact is never written into Neo4j as an `Artifact` node with a `CITES`
  edge, and never into the Meilisearch artifacts index, because both records
  are citation-bearing (`momentIds` / `CITES`) and there is no non-citable
  artifact record shape. Its content reaches an answer only through the moments
  its individual claims anchor to — which for the summary prose means story
  12.4's document indexing, where the same text is findable, labelled
  unreviewed, and explicitly not a citation target.
- **The skip is named, never silent (AD-18).** Publishing a summary is allowed
  and does everything a publish does except invent a citation; the projection
  emits `projection.artifact_skipped` with a reason that says
  meeting-scoped-has-no-moment, not the pre-existing
  `not found in state 'published'`, which would be untrue.
- **One publish gesture, one function.** The export → git → `UPDATE` loop moves
  verbatim out of `approve_moment_artifacts` into
  `api/artifact_publish.py::publish_extracted`. The per-moment route calls it
  and behaves exactly as before; the meeting-scoped route calls the same
  function. "The same gesture" is a shared implementation, not a similar one.
- **No fabrication.** A document with no executive-summary section yields no
  summary artifact, and a section that is present but empty yields none either.
  `parse_extraction_document` returns `summary=None`, and the stage inserts
  nothing.
- **A NULL `moment_id` must not turn a `NOT IN` three-valued.** `_DELETE_DRAFTS`
  becomes a NULL-safe `NOT EXISTS ... IS NOT DISTINCT FROM`. This is not
  cosmetic: with the old statement, one approved summary makes the subquery
  return a NULL and `moment_id NOT IN (…)` evaluates to NULL for *every* row,
  so no meeting would ever replace a draft again — an idempotence failure that
  leaves no trace.
- **`extraction_source` stays worker-owned (AD-5)** and the api writes only the
  lifecycle and publish columns it already owns.

**Block If:** none. The two rulings that could have needed an owner — the scope
declaration site and the non-widening of citations — were made before this
story started and are recorded in AD-6 (spine) and in the epic.

**Never:**
- No change to the moment view, its rail, its approve route's observable
  behaviour, or `web/src/features/moments/`. The per-moment path keeps working
  unchanged.
- No meeting analysis panel and no web feature code — story 12.3. The generated
  TS client is regenerated because it is committed, and nothing else in `web/`
  is touched.
- No extraction-document indexing, chunking or `publish/publish_gate.py`
  docstring edit — story 12.4 owns those.
- No edit to `api/threads.py` or `web/src/features/threads/` (story 10.7), or to
  `api/uploads.py` / `api/acquisitions.py` (story 6.4a).
- **No change to `llm.roles.extraction.arch_summary_prompt`.** The generated
  prompt emits Decisions and Risks only, so the generate path produces no
  executive summary and therefore no summary artifact — which is the
  non-fabrication rule being observable rather than asserted. Adding a section
  would bump `PROMPT_VERSION`, invalidate every stored `prompt_hash`, and imply
  re-extracting the corpus through a paid model.
- No worker or api process started, no `make evals-run`, no real model call.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Adopted arch-summary with prose | `# 1️⃣ Executive Summary` + prose | one `summary` artifact, `moment_id NULL`, body = the prose verbatim | none |
| Heading spelling drift | `## 1. Header & Executive Summary`, `# 1 Executive Summary` | same artifact; matched on heading *text*, never numbering | none |
| Generated arch-summary | Decisions/Risks only, no such heading | no summary artifact; decisions unchanged | none |
| Empty section | the heading with only blank lines under it | `summary=None`; nothing inserted | none |
| Other document kinds | `action-items`, `topics`, `ranking-signals` | `summary` is always `None` | none |
| Decisions unchanged | any arch-summary | the same `adr` rows, ids, titles and anchors as before | none |
| Rerun | extract runs twice | the previous `extracted` summary is deleted and re-proposed | none |
| Rerun after approval | the meeting's summary is `approved`/`published` | no new summary proposed, the approved row untouched, named discard logged | none |
| Approved summary + moment drafts | one approved summary, drafts on unapproved moments | the moment drafts are still replaced (the `NOT IN` regression) | none |
| Insert with wrong scope | `kind='summary'` with a `moment_id` | refused | CHECK `artifact_scope_matches_kind` |
| Insert with wrong scope | `kind='adr'` with `moment_id NULL` | refused | CHECK `artifact_scope_matches_kind` |
| Cross-meeting anchor | `kind='adr'`, a moment of another meeting | still refused after 0022 | composite FK |
| GET summary, present | a meeting with a summary | `200`, the artifact with its state and publish fields | none |
| GET summary, absent | a meeting with none | `200`, `summary: null` | none |
| GET summary, unknown meeting | random UUID | `404 not-found`, `application/problem+json` | Problem |
| GET summary, malformed id | `not-a-uuid` | `422 invalid-request` | Problem |
| GET summary, unsettled meeting | augmentation in flight | `409 meeting-not-viewable` | Problem |
| Approve, present | one `extracted` summary | `200`, state `published`, exported under `summary/<id>.md`, no git commit | none |
| Approve, nothing pending | none extracted | `409 nothing-to-approve` | Problem |
| Publish projection | a published summary | not written to either store; `projection.artifact_skipped` names the reason | none |
| `rebuild --meeting` | a meeting with a published summary | rebuild succeeds; the summary is absent from both stores | none |
| Augmentation remap | moments recomputed | the summary's `moment_id` stays NULL and is not remapped | none |

</intent-contract>

## Code Map

- `server/meetingminer/migrations/0009_artifacts.sql` — READ-ONLY. The
  unnamed inline `CHECK (kind IN ('adr','action-item'))` is auto-named
  `artifact_kind_check`; the composite FK at the end of the table is what 0022
  must leave untouched.
- `server/meetingminer/migrations/0014_topics.sql` — READ-ONLY. The precedent
  for widening an earlier migration's CHECK by drop-and-recreate.
- `server/meetingminer/pipeline/extraction.py` — `KIND_*` constants and
  `KNOWN_KINDS` (l.60–66); `_ARCH_TARGET_HEADINGS` (l.445); `ParsedDocument`
  (l.529); `parse_extraction_document`'s line loop, whose heading branch is
  l.1044–1047 and whose blank-line `continue` is l.1048.
- `server/meetingminer/pipeline/stages/extract.py` — `_SELECT_APPROVED_MOMENTS`
  (l.94, returns a NULL row once a summary is approved), `_DELETE_DRAFTS`
  (l.105, the `NOT IN`), `_INSERT_ARTIFACT` (l.155), the `DOCUMENT_KINDS` loop's
  artifact insert (l.494–546) and its `_UPSERT_EXTRACTION_SOURCE` (l.548).
- `server/meetingminer/api/moments.py` — `_EXTRACTED_ARTIFACTS_FOR_UPDATE`
  (l.143), `_PUBLISH_ARTIFACT` (l.149), `approve_moment_artifacts` (l.614) whose
  export/git/UPDATE loop l.642–671 is the block being extracted. `_require_viewable`
  is imported from here the way `api/speakers.py` and `api/extraction.py` do.
- `server/meetingminer/projections/publish_gate.py` — `_PUBLISHED_ARTIFACTS`
  (l.133) and `published_artifacts` (l.142), the single Postgres read feeding
  both store writers; `artifact_document` (l.104) already refuses an artifact
  with no moment.
- `server/meetingminer/projections/__init__.py` — `project_published_artifacts`
  (l.590) and its `projection.artifact_skipped` emit (l.631); `rebuild`'s
  per-meeting read at l.432 goes through the same function.
- `server/meetingminer/projections/graph.py` — `_write_artifacts` (l.549)
  verifies the `CITES` edge count, so a `(None,)` moment tuple would raise
  `ProjectionError` and fail the whole publish projection. This is why the
  exclusion lives in the read.
- `server/meetingminer/digest/generator.py` — l.71 SELECT and l.90's
  `bucket = "decisions" if kind == "adr" else "action_items"`, which would file
  a published summary as an action item.
- `server/meetingminer/pipeline/stages/moments.py` — l.147 INNER JOIN on
  `a.moment_id`; a NULL-moment artifact is excluded by construction, so the
  remap needs no change (pin it with a test).
- `server/meetingminer/api/search.py` (l.102) and `api/chat.py` (l.203) —
  READ-ONLY. Both hydrate from ids the artifacts index returned, and `search.py`
  INNER JOINs `moment`; unreachable once the projection excludes meeting-scoped
  rows.
- `server/meetingminer/api/registry.py` — READ-ONLY reference for router
  registration; both new paths have a literal second segment.
- `server/tests/test_migrations_topics.py` — the seeding style the new
  constraint test copies (`truncate_evidence`, minimal direct inserts).
- `server/tests/test_extraction_core.py` — `SUMMARY_TABLE` / `SUMMARY_BULLET`
  (l.216, l.245) already carry an executive-summary heading and a prose line.

## Tasks & Acceptance

**Execution:**
- `server/meetingminer/migrations/0022_meeting_scoped_artifacts.sql` — NEW: drop
  `NOT NULL` on `moment_id`, widen `artifact_kind_check` to add `summary`, add
  `artifact_scope_matches_kind`, and comment that the second constraint is the
  single declaration of which kinds are meeting-scoped.
- `server/meetingminer/pipeline/extraction.py` — ADD `KIND_SUMMARY`,
  `SUMMARY_TITLE`, the executive-summary heading marker and its predicate; ADD
  `KIND_SUMMARY` to `KNOWN_KINDS`; ADD `ParsedDocument.summary`; capture the
  section's lines in the parse loop *in addition to* existing per-line
  processing, so no current parse outcome changes; extend the module docstring.
- `server/meetingminer/pipeline/stages/extract.py` — REPLACE `_DELETE_DRAFTS`
  with the NULL-safe `NOT EXISTS`/`IS NOT DISTINCT FROM` form; rename
  `approved_moments` to `approved_scopes` and document that `None` is the
  meeting scope; insert the summary inside the `DOC_ARCH_SUMMARY` iteration,
  skipping with a named log when the meeting scope is already approved; count it
  in `artifact_count` and in the stage summary; extend the module docstring.
- `server/meetingminer/api/artifact_publish.py` — NEW: `publish_extracted`,
  holding the export → git → `UPDATE` loop verbatim.
- `server/meetingminer/api/moments.py` — REPLACE the inline loop with a call to
  `publish_extracted`. No other change.
- `server/meetingminer/api/artifacts.py` — NEW: `GET /meetings/{id}/summary` and
  `POST /meetings/{id}/artifacts/approve`, both behind `_require_viewable`.
- `server/meetingminer/api/registry.py` — REGISTER the new router.
- `server/meetingminer/projections/publish_gate.py` — ADD
  `AND a.moment_id IS NOT NULL` to `_PUBLISHED_ARTIFACTS` with its reason; ADD
  `meeting_scoped_published` so the skip can be named accurately.
- `server/meetingminer/projections/__init__.py` — USE it to emit the accurate
  `projection.artifact_skipped` reason.
- `server/meetingminer/digest/generator.py` — SCOPE the SELECT to
  `a.moment_id IS NOT NULL` so a summary is never bucketed as an action item.
- `docs/architecture.md` — SYNC AD-6 with the spine's meeting-scoped-artifact
  paragraph. No new AD; the count line is unchanged.
- `server/tests/test_migrations_artifact_scope.py` — NEW: the constraint matrix.
- `server/tests/test_extraction_core.py` — the parser cases from the matrix.
- `server/tests/test_worker_extract.py` — the stage cases, including the
  approved-summary idempotence regression.
- `server/tests/test_api_meeting_summary.py` — NEW: the two routes.
- `server/tests/test_projections_publish_gate.py` (or the existing publish-gate
  suite) — the exclusion and the named skip.
- `web/src/client/*` — regenerated for the two new operations.

**Acceptance Criteria:**
- Given an arch-summary document carrying an executive summary, when it is
  parsed and stored, then exactly one `summary` artifact exists for that meeting
  with `moment_id IS NULL` and a body equal to the section's prose, and the
  document's decision rows still produce the identical `adr` rows.
- Given the artifact schema after 0022, when any of the four wrong-scope or
  cross-meeting inserts in the matrix is attempted, then the database refuses
  it by constraint, and the meeting-scoped kind list appears in no source file
  other than `0022_meeting_scoped_artifacts.sql`.
- Given a meeting whose summary is `extracted`, when the meeting-scoped approve
  route is called, then the row becomes `published` with its export path set,
  and the per-moment approve route's behaviour and response are unchanged.
- Given a published summary, when the publish projection or `rebuild --meeting`
  runs, then neither store receives an artifact record for it and the skip is
  logged with a reason naming its meeting scope.
- Given `make test`, then the full gate passes with no new ruff baseline entry.

## Spec Change Log

- **2026-08-31, implementation — the summary counts in `item_count` as well as
  `artifact_count`.** Planning said it should count in `artifact_count` only,
  reasoning that `item_count` counts ID-keyed item rows and the summary is not
  one. Migration 0010 refused it: `extraction_source_inserted_within_parsed`
  CHECKs `artifact_count <= item_count`, and the run failed by name on the
  first stage test. The constraint is right and the plan was wrong — 0010
  defines `item_count` as *what the parser found* and `artifact_count` as
  *what became a row*, and the executive summary is both. Counting it in one
  column only would have reported an insert the document never yielded. The
  two now differ by exactly one in the case the columns exist for: a summary
  found but not stored because the meeting scope was already approved.

- **2026-08-31, implementation — no meeting-scoped artifact reaches either
  store, and the skip is named.** The spec called for this; what the code
  showed is how close the alternative was to shipping silently.
  `published_artifacts` built `moment_ids=(row[7],)` unconditionally, so a
  published summary would have become `momentIds: ["None"]` in Meilisearch and
  an expected-but-unwritable `CITES` edge in Neo4j — the first a citation that
  cannot replay, the second a `ProjectionError` that would have failed
  `rebuild --meeting` for the whole meeting. The filter is in the statement,
  on `moment_id IS NOT NULL`.

- **2026-08-31, implementation — `api/registry.py` needed no edit.** Routers
  are auto-discovered by attribute and type, so the new module registers
  itself. Its baseline order list in `test_api_registry.py` is updated instead,
  which is where the ordering contract is actually pinned.

## Review Triage Log

## Design Notes

**Why the summary is a field on `ParsedDocument`, not a `ProposedArtifact`.**
Every `ProposedArtifact` carries `anchor_ms`, and the parser raises when an item
has no `[m:ss]` anchor, because an unanchored item could never be cited. A
summary has no anchor by definition. Making it a `ProposedArtifact` would either
require a sentinel anchor — a fabricated citation — or weaken the invariant that
makes the raise meaningful. A separate field keeps both true.

**Why the section is captured *in addition to*, not instead of, the existing
line handling.** `_ARCH_TARGET_HEADINGS` contains `"summary"`, so the executive
summary is already a *target section*: its bullets mark it populated and feed
the no-silent-zero signal, and a stray `D1` row inside it already becomes an
ADR. Consuming the section as prose and skipping the rest of the loop would
change both of those quietly. Appending the raw lines and then letting the loop
run exactly as before means the only observable difference is a field that used
to be absent.

**Why the executive-summary heading is matched by the substring
`"executive summary"`.** It is what all three sampled spellings share
(`# 1️⃣ Executive Summary`, `## 1. Header & Executive Summary`,
`# 1 Executive Summary`) and it never touches numbering, which is the parser's
standing rule. A bare `"summary"` would also match `Rebuilt meeting summary`,
which is a different section.

**Why the section ends at the next heading of any level, not the next heading
of the same or shallower level.** The sampled documents mix levels across
sections — `# 1️⃣ Executive Summary` is followed by `## 3. Decisions made` — so
a same-or-shallower rule would swallow the decisions table into the summary
body.

**Why the title is a constant.** `artifact.title` is NOT NULL and the heading it
would otherwise come from is drifting boilerplate carrying section numbering and
emoji. The prose is the content and it is stored verbatim in `body`; a stable
title makes the artifact identifiable across meetings without inventing
anything, since nothing in the document is being paraphrased.

**Why the meeting-scoped exclusion lives in `published_artifacts`' statement.**
It is the module's stated role — "the one Postgres read that feeds artifact
projection" — and both callers (the approve route and `rebuild`) go through it,
so one filter covers both. Filtering at the two call sites instead would be the
same rule written twice. The filter is on `a.moment_id IS NOT NULL`, the
observable fact, so it is not a second copy of the kind list.

**Why `_DELETE_DRAFTS` becomes `NOT EXISTS ... IS NOT DISTINCT FROM`.** It states
the existing rule once for both scopes — "delete a draft unless a human has
already acted on something in its own scope" — where the scope is the moment for
an anchored artifact and the meeting itself for a meeting-scoped one.
`IS NOT DISTINCT FROM` is NULL-safe equality, so no three-valued logic can
reappear if another meeting-scoped kind is added later.

## Verification

**Commands:**
- `uv run --project server pytest -m "" server/tests/test_extraction_core.py server/tests/test_worker_extract.py -q` — expected: all pass, including the new parser and stage cases.
- `uv run --project server pytest -m "" server/tests/test_migrations_artifact_scope.py server/tests/test_api_meeting_summary.py -q` — expected: all pass.
- `make lint` — expected: all checks passed, no new baseline entry.
- `make typecheck` — expected: success.
- `make web-test` — expected: the existing suite unchanged.
- `make test` — the full gate, against this worktree's private stack.
- `python3 _bmad/scripts/branch_conflicts.py --against story/12-2` — expected: `main × story/12-2` clean; any introduced pair named.

## Auto Run Result

Completed 2026-08-31 on `story/12-2`, cut from `d250cf89`. Status `review`, not
`done`: the review lane has not run and this lane does not merge.

**Commits (pushed to `origin/story/12-2`):**

- `858b7373` — the frozen spec and the compiled Epic 12 context.
- `d5aa77bb` — migration 0022, the parser's `summary` field, the stage's
  meeting-scoped insert, the publish-gate exclusion, the digest scoping.
- `0f7e6b89` — `GET /meetings/{id}/summary`, `POST /meetings/{id}/artifacts/approve`,
  and `api/artifact_publish.py` (the shared gesture the per-moment route now calls).
- `a927818a` — the constraint matrix, the parser cases, the stage cases.
- `dbff6854` — the route tests and the two projection tests.
- `44dc0768` — the AD-6 sync, the split error-response maps, the regenerated client.

**Gates, run in the foreground against this worktree's private stack
(`meetingminer-12-2`):**

- `make lint` — all checks passed, no new baseline entry.
- `make typecheck` — success, no issues in 13 source files.
- `uv run --project server pytest -m "" server/tests/test_extraction_core.py -q` — 115 passed.
- `uv run --project server pytest -m "" server/tests/test_worker_extract.py -q` — 38 passed.
- `uv run --project server pytest -m "" server/tests/test_artifact_publish.py -q` — 25 passed.
- `uv run --project server pytest -m "" server/tests/test_migrations_artifact_scope.py -q` — 6 passed.
- `make test` — **1 failed, 2794 passed, 3 skipped**, 784.12s (13m04s). See below.

**The one gate failure is a contention artifact on an untouched test, and it is
recorded rather than waved away.** `test_mint_drop.py::test_independent_processes_share_the_source_identity_lock`
*passed* but its call phase took **2.61s** against the 2.00s
`mm_fast_test_budget_seconds`, which `fast_budget.py` reports as a failure. The
budget message names this exact case: "If it only exceeds the budget while
another suite, a rebuild, or the worker is running, re-run it alone before
marking it slow: contention is not a reason to mark." Story 12.4's full suite
was running in a sibling worktree for the whole of this gate (verified with
`pgrep` during and after). Re-run alone at the same revision, the same test's
call phase is **1.18s** — 1 passed in 1.93s, comfortably inside the budget.

The test is untouched by this branch (`git diff d250cf89..HEAD --
server/tests/test_mint_drop.py` is empty) and concerns drop minting and a source
identity lock, which this story does not reach. **No `slow` mark was added**:
marking it would be the thing the budget message forbids, and it would hide a
real budget signal from a later run that is not contended. The three skips are
the suite's standing named skips, unchanged from story 12.1's gate.

- `python3 _bmad/scripts/branch_conflicts.py --against story/12-2` —
  **`main × story/12-2` clean.** The pairs this branch introduces against other
  live branches are all on the generated TS client: `story/12-4` and
  `story/6-4a-review` on `web/src/client/index.ts` (plus `sdk.gen.ts` for the
  latter), both of which are clean against `main` today. This is story 12.1's
  recorded shape and the resolution is the same: `make client` is regenerated
  at integration. Every other conflicting pair listed already conflicts with
  `main` and is not introduced here.

**Not run, deliberately:** `make evals-run`, the shared worker, the shared api.
A corpus ingest is running on the main stack and `llm.roles.extraction` is bound
to a paid model; **no real model call was made anywhere in this lane.**
`config.yaml` in the main checkout was never touched.

**One deviation from the workflow, stated plainly.** Step 03 directs the
implementation to a subagent invoked synchronously. This harness only launches
agents in the background, and the dispatch for this story forbids background
agents outright. The implementation was therefore done directly in this lane
with the spec as the contract, which the dispatch anticipated ("if unavailable,
follow them directly with the same rigor"). The epic-context compilation *was*
delegated, and returned before it was used.

**Two things the code showed that the plan had not.** Both are in the Spec
Change Log above and both are the reason this story touched files beyond the
obvious ones: the `NOT IN` that goes three-valued the moment a NULL `moment_id`
exists, and the `(None,)` moment tuple that would have reached both stores. The
first is a pre-existing statement whose latent defect this story would have
*activated*; it is fixed rather than worked around.
