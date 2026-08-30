# Review handoff — Story 3.2 "Graph Traversal Templates" (2026-08-20)

You are reviewing story 3.2 with no context from the build run. Everything you
need is below or in the named files. Report findings; do not apply fixes.

## Repo, branch, range

- Repo: `/Users/devopsterus/current/cohort/meetingminer` (or work from the
  worktree `/Users/devopsterus/current/cohort/meetingminer-wt/3-2` if it still
  exists). Branch: `story/3-2`, pushed to `origin/story/3-2`.
- Review range: `444469d..HEAD` on `story/3-2` (base = `main` at
  `444469d7b140bbc963baed30e5b04180371e2198`, the branch point). Commits in
  the range:
  - `4a555c9d7f11a706cc0aee84d219aab7d0234ca2` — docs(3-2): plan graph traversal templates story
  - `d7bc043b932f2240cc644497b407e7a28374ccf1` — feat(3-2): graph traversal templates over the evidence projection
  - `0cb9ee63eea9e3d9838439c46d09c66796b19c39` — docs(3-2): move graph traversal templates to review
  - `cba305f1071ce6f88cd3b0f609636df2a6acf75b` — fix(3-2): harden traversal templates per review
  - `1eac0ffdf032908fe54592c4553ae352e669edf5` — docs(3-2): record review pass and close story
  - `198d531` (this file) — docs(review): add story 3.2 reviewer handoff
- No commit in the range belongs to another story.

## Spec and what is frozen

- Spec: `_bmad-output/implementation-artifacts/spec-3-2-graph-traversal-templates.md`.
- The `<intent-contract>` block (Intent, Boundaries & Constraints, I/O &
  Edge-Case Matrix) is frozen intent — review the code against it, do not
  critique it. Everything outside that block (Code Map, Tasks, Design Notes,
  the triage/auto-run records) is planner work you may attack.
- Upstream intent authority: `_bmad-output/planning-artifacts/epics.md` §"Story
  3.2: Graph Traversal Templates" (four ACs, FR11).

## Architecture authority

- `_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md`:
  - **AD-7** — graph retrieval is hand-written, parameterized Cypher templates;
    no library builds, extracts, or owns graph structure; the model only
    classifies to a template and synthesizes.
  - **AD-6** — moment UUIDs minted once in Postgres, carried verbatim.
  - **AD-4** — store clients live only under `server/meetingminer/projections/`
    (enforced by `server/tests/test_projections_single_writer.py`).
- The written graph shape being read: `server/meetingminer/projections/graph.py`
  module docstring; its recorded traversal intent is in
  `_bmad-output/implementation-artifacts/spec-1-7-evidence-projections-rebuild-cli.md`
  (search "This shape answers both demo traversals").

## Scope

In scope (the whole change set):

- `server/meetingminer/projections/traversals.py` (new)
- `server/tests/test_projections_traversals.py` (new)
- `server/tests/projection_seed.py` (one pinned addition: keyword-only
  `started_at`, timezone-aware, default unchanged)
- `_bmad-output/implementation-artifacts/{spec-3-2-*.md,sprint-status.yaml,sprint-notes.md}`

Out of scope: any HTTP/chat surface (story 3.3 owns `/chat` and name→id
resolution), Topic nodes and topic extraction (Epic 4), the meeting drill-down
view (story 2.3, in flight), Meilisearch search (story 3.1, done), the eval
query driver (Epic 5, documented-deferred in `evals/designs/retrieval-eval.md`).

## Design decisions to attack

Each stated as choice + the assumption it rests on:

1. **Screen history walks `SHOWS` only** (`Screen ← Screenshot ← Moment →
   Meeting`). Assumption: spec-1-7's recorded shape is the right reading of
   "every meeting and moment where that screen appeared"; the broader
   `SHOWN_DURING`∘`COVERS` union (moments during which the screen was visible
   but represented by a different screenshot) is deliberately excluded and
   never exercised by any test.
2. **Topic = case-insensitive verbatim substring over `Moment.text`.**
   Assumption: scripted eval topics are authored as terms that appear verbatim;
   paraphrase matching belongs to the search index. Multi-word topics must
   appear verbatim or return empty.
3. **"Present" = `ATTENDED` the meeting, not `SPOKE_IN` the moment.**
   Assumption: the Rowan story is about a listener; no AC distinguishes the
   two.
4. **Templates take UUIDs, not names.** Assumption: name→id resolution is 3.3's
   router's job; a caller holding only "Rowan" cannot run these templates
   today.
5. **Anchor/empty split via one round trip** (`MATCH` anchor + `OPTIONAL MATCH`
   + `WHERE` on the optional part). Assumption: zero records ⇔ unknown anchor;
   one record with NULL moment ⇔ valid empty. Also assumes anchor properties
   are constant across records (records[0] is used).
6. **Time order = lexical `startedAt` (ISO-8601 string), then `meeting.id`,
   then `startMs`.** Assumption: every projected `startedAt` shares one format
   and UTC offset (the projection's `_iso` writes it); parse-side guards check
   ISO validity and tz-awareness but not offset uniformity.
7. **AC4 ("templates are the only graph retrieval path") is tested by proxy:**
   a four-name library denylist AST walk + registry cardinality + the
   pre-existing single-writer import walk. An unlisted graph library, or raw
   retrieval Cypher added elsewhere inside `projections/`, would pass.
8. **No result limit and no config knobs.** Assumption: the deferred retrieval
   eval's exact-set comparison forbids truncation and the corpus stays
   demo-sized.
9. **"Unit tests against known fixture data" read as store-backed tests over
   seeded fixtures** (live compose Neo4j via `projection_stores`), skipping by
   name when stores are down. The store-free half covers registry shape and
   refusals only — on an infra-down run nothing proves traversal results.

## History the reviewer needs

- The branch is linear off `main` at `444469d`; no rebase, no dropped variants.
- Commit `cba305f` is a review-remediation pass over `d7bc043` (14 patches from
  a four-layer review; the triage log in the spec lists them). If you find a
  defect in the hardened paths, check the triage log first to tell a new
  finding from an incompletely applied one.
- A transient full-suite failure in
  `test_projection_lock_times_out_with_holder_details_then_releases` occurred
  mid-run while another worktree's suite held the cross-worktree projection
  lock; it is that test's known sensitivity to a foreign holder, not a
  regression of this change, and passed on re-run.

## Verification baseline

Observed on `story/3-2` at `1eac0ff`, Docker stores up:

- `uv run --project server pytest server/tests/test_projections_traversals.py`
  → 23 passed, 0 skipped.
- `uv run --project server pytest server/tests` → 1186 passed, 0 failed,
  0 skipped (~7 min; store-backed tests queue on the shared projection lock).
- Store-backed tests skip by name when the stores are down — a skip in your run
  is an environment fact; a failure is a finding.

## Required output

Write findings (do not fix) to
`_bmad-output/implementation-artifacts/review-story-3-2-2026-08-20.md`, with:

- one section per finding: location (`file:line`), what is wrong, why it
  matters for the consumer (story 3.3's orchestrator / the Epic 5 eval), and
  severity (high/medium/low);
- a verdict section: whether the four epic ACs hold as implemented, and which
  of the nine listed design assumptions you judge unsafe;
- anything you could not verify, stated as such rather than omitted.
