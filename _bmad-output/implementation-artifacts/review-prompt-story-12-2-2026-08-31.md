# Review prompt — Story 12.2: The Meeting Summary

## What you must produce, before anything else

**Write your report to
`_bmad-output/implementation-artifacts/review-story-12-2-2026-08-31.md`.**

Each finding takes this structure:

- **Location** — `path/to/file.py:line`
- **Severity** — low / medium / high
- **Finding** — what is wrong
- **Evidence** — what you ran or read that shows it
- **Suggested direction** — not a patch, a direction

**The review lane applies its own patch findings.** This is the repository's
convention, corrected 2026-08-30. Report every finding in the report file
first, then fix the patchable ones yourself on `story/12-2-review`, cut from
`story/12-2`, in its own worktree (`make worktree STORY=12-2-review` — never
the main checkout). Fix red-first: write the test, observe it fail against the
unfixed code, then fix, then green.

**What you must NOT fix:** anything needing an owner decision, and anything
whose root cause is the frozen spec (the `<intent-contract>` block). Report
those, mark them open, and leave them for the owner. Never merge to `main`;
the owner runs `integrate`.

**REPORT-FIRST is mandatory.** Create and commit the report file as a skeleton
— scope, range, an empty findings section — **before you read any code**. Then
append each finding as you confirm it and commit incrementally. Four reviews in
this repository were completed in a session's terminal and never filed, every
one written report-last. A crashed or closed session must lose prose, never the
artifact.

**Closeout.** Before reporting completion, run `make check-reviews` (it fails
while any dispatched review lacks a committed report, including this one) and
state the SHA carrying the report's final version. A review reported in the
terminal but not filed does not exist.

---

## Repo, branch, range

- **Repo:** `/Users/devopsterus/current/cohort/meetingminer` (main checkout —
  do not work in it). Branch under review: `story/12-2`, pushed to
  `origin/story/12-2`.
- **Review range:** `d250cf89..HEAD` on `story/12-2`.

Commits in the range, oldest first:

| Revision | Subject |
|---|---|
| `858b737304491c62a52122d503e049c52da9efaf` | docs(12-2): plan the meeting summary — scope widens, citations do not |
| `d5aa77bb53ad979074bc6c0688a901c3a73aa177` | feat(12-2): the meeting summary — a meeting-scoped artifact |
| `0f7e6b892e5a4c851f466e5b1c01089503e1005d` | feat(12-2): read and publish a meeting-scoped artifact |
| `a927818ada80b0e738058e4a4751c390041c0624` | test(12-2): the scope constraint, the parser, and the stage |
| `dbff6854de0bb6d5ede95bca78ec56a4a0a72d08` | test(12-2): the meeting-scoped read, gesture and projection skip |
| `44dc07686b56b9906d8a45695658ad916a4349ae` | docs(12-2): sync AD-6, and regenerate the TS client |

Every commit in the range belongs to this story. None belongs to another.

## The spec, and which half is frozen

`_bmad-output/implementation-artifacts/spec-12-2-the-meeting-summary.md`.

- **Frozen intent** — everything inside `<intent-contract>`: Intent,
  Boundaries & Constraints, and the I/O & Edge-Case Matrix. A finding whose
  root cause is in there is reported and left open, never patched.
- **Planner work you may attack freely** — Code Map, Tasks & Acceptance,
  Design Notes, Spec Change Log, Verification.

## Architecture authority

- **AD-6 (citations are Postgres-minted moment ids)** — the decision this story
  turns on. Both `docs/architecture.md` and
  `_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md`
  now carry the meeting-scoped-artifact paragraph; they must agree at
  AD-1…AD-18 and the count line ("Eighteen decisions") is unchanged.
- **AD-15 (one citation wire format)** — why a citation must carry a `momentId`
  with `startMs`/`endMs`, and therefore why `meeting_id` may never be one.
- **AD-18 (degradation is never silent)** — why the projection's skip of a
  meeting-scoped artifact must be named rather than merely happen.
- **AD-4 / AD-5** — the single projection writer, and the disjoint column
  split the api and worker observe.

## Scope

**In scope** (the full changed-file list for the range):

- `server/meetingminer/migrations/0022_meeting_scoped_artifacts.sql`
- `server/meetingminer/pipeline/extraction.py`
- `server/meetingminer/pipeline/stages/extract.py`
- `server/meetingminer/api/artifact_publish.py` (new)
- `server/meetingminer/api/artifacts.py` (new)
- `server/meetingminer/api/moments.py`
- `server/meetingminer/projections/publish_gate.py`
- `server/meetingminer/projections/__init__.py`
- `server/meetingminer/digest/generator.py`
- `server/pyproject.toml` (one marker description)
- `docs/architecture.md` (AD-6)
- `server/tests/test_migrations_artifact_scope.py` (new),
  `test_extraction_core.py`, `test_worker_extract.py`,
  `test_artifact_publish.py`, `test_api_registry.py`
- `web/src/client/*` (generated)

**Explicitly out of scope:**

- **Story 12.3** — the meeting analysis panel, the meeting-wide artifacts
  endpoint, and the artifact-kind list in `web/src/features/moments/moments.ts`.
  This story built the data and the API, deliberately not the panel.
- **Story 12.4** — extraction-document indexing, chunking, and
  `publish/publish_gate.py`'s module docstring. Do not edit those.
- **Story 10.7** — `api/threads.py`, `web/src/features/threads/`.
- **Story 6.4a** — `api/uploads.py`, `api/acquisitions.py`.
- Already-recorded deferred items and the vendored `tools/puller` tree.

## Design decisions to attack

These are the calls the planner made. The planner is not a neutral judge of its
own work, so each is stated as the choice plus the assumption under it.

1. **A meeting-scoped artifact is excluded from BOTH stores, in
   `published_artifacts`' own SQL (`AND a.moment_id IS NOT NULL`).**
   *Assumption:* both stores' artifact records are citation-bearing
   (Meilisearch's `momentIds`, Neo4j's `CITES`) and there is no non-citable
   artifact record shape, so a summary has nothing to project that would not be
   a citation it cannot honour. *Attack:* is a published summary being
   unsearchable acceptable? The planner's answer is that story 12.4 indexes the
   extraction document containing the same prose, labelled unreviewed and
   non-citable — check whether that actually holds, and whether the exclusion
   should instead have been a new non-citable record shape.

2. **The skip is named via a second query (`meeting_scoped_published`).**
   *Assumption:* reporting a published-but-meeting-scoped id as "not found in
   state 'published'" is untrue and AD-18 forbids it. *Attack:* the extra query
   runs inside the projection lock; is the cost justified, and is the reason
   string the right granularity?

3. **`_DELETE_DRAFTS` restated as `NOT EXISTS` with `IS NOT DISTINCT FROM`.**
   *Assumption:* "a draft survives only when a human has acted in its own
   scope" is the same rule for both scopes, and NULL-safe equality states it
   once. *Attack:* verify the semantics against the old statement for the
   moment-anchored case — this is a rewrite of a rule that protects approved
   human judgment, and a regression here destroys work silently. Note the
   pre-existing bug it fixes: with the old `NOT IN`, one approved
   meeting-scoped row makes the subquery yield NULL and the predicate NULL for
   every row, so no draft would ever be replaced again for that meeting.

4. **`SUMMARY_TITLE` is a constant, not the document's own heading.**
   *Assumption:* the heading is drifting boilerplate (numbering, emoji) and the
   prose in `body` is the content, so a stable label invents nothing.
   *Attack:* is losing the document's own heading a loss of provenance?

5. **The executive-summary section is captured *in addition to* the existing
   per-line handling, not instead of it.** *Assumption:* that section is
   already a target section, so consuming it would silently change the
   populated-section signal and drop any `D`-row inside it. *Attack:* the
   consequence is that a decisions table appearing inside the executive-summary
   section lands in the summary body as well as becoming an ADR. Is that right?

6. **The section runs to the next heading of ANY level.** *Assumption:* real
   documents mix heading levels across sections. *Attack:* a sub-heading inside
   the executive summary would truncate the body at it.

7. **A new meeting-scoped approve route rather than extending the per-moment
   one.** *Assumption:* the AC requires a summary to be publishable by the same
   gesture, and sharing `publish_extracted` makes them one implementation.
   *Attack:* is `POST /meetings/{id}/artifacts/approve` the right shape, given
   story 12.3 owns the meeting-wide read endpoint? Check for a seam collision.

8. **`GET /meetings/{id}/summary` serves drafts.** *Assumption:* it is a read
   of stored artifact state, not an answer, exactly as the moment rail already
   serves unpublished artifacts. *Attack:* confirm no answer path can reach it.

9. **The digest is scoped to `moment_id IS NOT NULL`.** *Assumption:* its
   two-way bucketing (`adr` or else action item) would otherwise file a
   published summary as an action item. *Attack:* silently omitting the summary
   from the digest is itself a choice — should it have a bucket instead?

## History you need to tell a regression from a pre-existing condition

- **Story 12.1 landed first** and is this story's foundation
  (`extraction_source.document_text`, `GET /meetings/{id}/extraction-documents`).
  Its spec is `spec-12-1-retain-the-extraction-documents.md`, status `done`.
  Its review recorded **B-55** as a known latent defect, owner-ruled
  non-blocking: a rerun can orphan surviving approved artifacts from their
  retained source document. That is pre-existing and out of scope here.
- **Migration numbering has a deliberate gap.** `main` is at 0019; this story
  takes **0022** and story 12.4 was told to take 0023, leaving 0020/0021 for
  other lanes. The runner sorts a glob and does not require contiguity.
- **One planning decision was reversed during implementation** and is recorded
  in the Spec Change Log: the summary counts in `extraction_source.item_count`
  as well as `artifact_count`. Migration 0010's
  `extraction_source_inserted_within_parsed` CHECK (`artifact_count <=
  item_count`) refused the original plan by name on the first stage test.
- **`api/registry.py` is unchanged on purpose** — routers are auto-discovered
  by attribute and type. The ordering contract lives in
  `test_api_registry.py`'s `BASELINE_ROUTER_ORDER`, which is updated.
- **The TS client was generated from a locally dumped OpenAPI schema**, not by
  `make client`, which needs a live api on the shared fixed port `:8000`
  (backlog B-35) while a corpus ingest is running. The generated diff is
  additive only, which is the evidence the dump reproduces the committed
  client.

## Verification baseline

Run these; a skip or a failure during your review should read as a finding, not
as noise. All were run in the foreground against this worktree's private stack
(`meetingminer-12-2`), never through `tail`.

| Command | Result at `44dc0768` |
|---|---|
| `make lint` | All checks passed; no new baseline entry |
| `make typecheck` | Success, no issues in 13 source files |
| `uv run --project server pytest -m "" server/tests/test_extraction_core.py -q` | 115 passed |
| `uv run --project server pytest -m "" server/tests/test_worker_extract.py -q` | 38 passed |
| `uv run --project server pytest -m "" server/tests/test_artifact_publish.py -q` | 25 passed |
| `uv run --project server pytest -m "" server/tests/test_migrations_artifact_scope.py -q` | 6 passed |
| `make test` | see the spec's `## Auto Run Result` for the recorded figure |
| `python3 _bmad/scripts/branch_conflicts.py --against story/12-2` | see `## Auto Run Result` |

**Not run, deliberately:** `make evals-run`, the shared worker, the shared api.
A corpus ingest is running on the main stack and `llm.roles.extraction` is
bound to a paid model — **no real model call was made anywhere in this lane,
and none may be made in yours.** Never commit `config.yaml` from the main
checkout; it holds uncommitted ingest bindings.

## One thing worth checking hardest

The story's whole risk is that scope widened and something quietly started
accepting a citation that cannot replay. The places where that would show up
are `projections/publish_gate.py:published_artifacts`,
`projections/graph.py:_write_artifacts` (its `CITES` edge-count check),
`api/search.py:_RESOLVE_ARTIFACTS` and `api/chat.py:_ARTIFACT_CONTEXT`. The
planner's claim is that the last two are unreachable for a meeting-scoped row
because nothing meeting-scoped ever enters the artifacts index. Verify that
claim rather than accepting it.
