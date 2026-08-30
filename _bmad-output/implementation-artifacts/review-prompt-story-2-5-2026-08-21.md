# Independent review — Story 2.5: Series, Project & Product Assignment

## REQUIRED OUTPUT — READ THIS FIRST, ACT ON IT FIRST

Your review does not exist until its report file is **committed**. Six reviews
in this repository produced their findings only as terminal text because this
requirement sat at the end of a long prompt.

- **Report path:**
  `_bmad-output/implementation-artifacts/review-story-2-5-2026-08-21.md`
- **Finding structure** (one block per finding):
  Location / Severity (high|medium|low) / Finding / Evidence / Suggested
  direction. **Report findings — do not fix them.**
- **REPORT-FIRST:** before reading ANY code, create the report file as a
  skeleton (scope, review range, empty findings section) and **commit it**.
  Then read the code and append each finding as you confirm it, committing
  incrementally. A crashed or closed session must lose prose, never the
  artifact.
- **Closeout:** before reporting completion, run `make check-reviews` (it
  fails while any dispatched review — including this one — lacks a committed
  report) and state the SHA carrying the report's final version. A review
  reported in the terminal but not filed does not exist.

## Repo, branch, range

- Repo: `/Users/devopsterus/current/cohort/meetingminer` — but work in your
  OWN worktree: `make worktree STORY=2-5-review`, then
  `cd ../meetingminer-wt/2-5-review && make bootstrap`. Never review from the
  shared checkout (AGENTS.md; a reviewer once mistook another agent's
  in-progress files for repository state).
- Branch under review: `story/2-5` (pushed to origin).
- Review range: `e9479ec938c2f3f98e71608a38f8e83a68dcc953..story/2-5`
  (base = origin/main at dispatch). Commits in the range:
  - `a37ee4921b4e858a59354eaa5ca2e89a302eb885` docs(2-5): plan series/project/product assignment — spec ready-for-dev
  - `06048902d2163d6fe755ca907e8ea7fc0c5f0fbb` feat(2-5): series/project/product assignment — API write path + graph projection
  - `770cb4e76787c643c9e7cf6506bff4df1a61c34a` chore(2-5): regenerate TS client — structure operations tracked in OpenAPI schema
  - `ace7bf0c57b3874eb99f78f5a69b60adce989956` fix(2-5): review triage — OWNS reconciliation, race guards, accurate OpenAPI errors, FK indexes
  - `0359268e246543e0b19348c84a08b0ef26c2977f` docs(2-5): review pass complete — 14 patched, 2 deferred, story done

  Every commit in the range belongs to story 2-5; none is another story's.

## Spec: frozen intent vs planner work

- Spec: `_bmad-output/implementation-artifacts/spec-2-5-series-project-product-assignment.md`.
- The `<intent-contract>` block (Intent, Boundaries & Constraints, I/O &
  Edge-Case Matrix) is **frozen intent** — review the code against it, do not
  critique it, with one recorded exception: the Blank-name matrix row says
  "any create/rename" but no rename route exists or was ever intended (the
  epic's ACs are create + assign only); the word is vestigial.
- Everything else (Code Map, Tasks, Design Notes, triage/change logs, Auto
  Run Result) is **planner and builder work you may critique**.
- The upstream intent is `_bmad-output/planning-artifacts/epics.md` § Story
  2.5 (FR25) — three ACs: assignment via the API, PRODUCT → PROJECT → MEETING
  per the ERD written only by the API, relationships in the graph projection
  at next projection or `rebuild`.

## Architecture authority

`_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md`:

- **AD-5 (table ownership is disjoint)** — the decision this story
  implements: series/project/product are API-written user-declared data; the
  worker never touches them. Check no worker-owned table gained a column and
  no worker code path reads the five new tables.
- **AD-4 (projections have exactly one writer)** — all Neo4j writes must stay
  inside `server/meetingminer/projections/`; the API must reach no store
  (`test_the_api_package_never_reaches_a_store`).
- **Core-entity ERD (spine ~line 366)** — `MEETING }o--o| SERIES`,
  `PROJECT ||--o{ MEETING`, `PRODUCT ||--o{ PROJECT`. The spine's Deferred
  section explicitly leaves exact DDL and Neo4j naming to the code.
- **AD-2** (Postgres sole database of record), **AD-6** (Postgres-minted
  UUIDs carried verbatim into stores).

## Scope

In-scope files (the whole diff):
- `server/meetingminer/migrations/0013_series_projects_products.sql` (new)
- `server/meetingminer/api/structure.py` (new)
- `server/meetingminer/projections/{evidence,graph,stores}.py`
- `server/tests/{conftest,projection_seed,test_api_structure,test_projections_graph,test_projections_rebuild,test_api_registry}.py`
- `web/src/client/{index,sdk.gen,types.gen}.ts` (generated — regenerated via
  the pinned fallback, review only that they were not hand-edited)
- `_bmad-output/implementation-artifacts/spec-2-5-series-project-product-assignment.md`

Out of scope:
- Web UI (deliberately none — the epic's ACs anchor the surface at the API;
  the epic context states "human-declared via the API only").
- Traversal templates over the new nodes (Epic 3's), Meilisearch documents,
  entity delete endpoints, pagination on the list routes (deferred, recorded
  in the spec frontmatter `deferred:` list with evidence).
- Applying migration 0013 to the shared dev database — deliberately left to
  the integration loop (`make migrate`, announced). Test suites used per-run
  databases.

## Design decisions to attack

Each is the planner/builder's own call plus the assumption it rests on — the
planner is not a neutral judge of these; attack them.

1. **Assignment tables, not `meeting` columns.** Assumes AD-5's column-split
   list (artifact, participant) is closed and a `meeting.series_id` would be
   an undeclared third split. Rests on reading the spine's silence as
   prohibition.
2. **`meeting_id` as PRIMARY KEY of the assignment tables** enforces
   at-most-one series/project per meeting. Assumes the ERD's `}o--o|` and
   `||--o{` cardinalities mean at-most-one from the meeting side and that
   nullable-FK-via-separate-table is the right reading of `||` (a mandatory
   project for every meeting is unimplementable for pre-existing meetings).
3. **`PUT` with nullable id clears via row DELETE** (no DELETE routes).
   Assumes idempotent-replace semantics are what a curator needs and that
   missing-key-vs-explicit-null is a meaningful 422/200 distinction
   (tested).
4. **Graph shape: `IN_SERIES`/`SCOPES`/`OWNS`, cross-meeting nodes upserted
   never per-meeting-deleted.** Assumes the Screen/Participant asymmetry
   generalizes; orphaned entity nodes lingering until `rebuild --all` is
   accepted as the disposable-projection posture.
5. **`OWNS` reconciliation added in review** (`ace7bf0`): stale
   product→project edges are deleted when one of the project's meetings
   re-projects. Assumes per-meeting projection is the right place to
   reconcile an edge between two cross-meeting nodes, and accepts the lag
   when none of the project's meetings re-project. Check the Cypher against
   concurrent projections of two meetings sharing the project.
6. **Per-route OpenAPI response subsets** replaced one shared
   `_PROBLEM_RESPONSES`. Assumes the declared subsets exactly match raisable
   paths — verify no route can raise a status it no longer declares.
7. **No end-to-end API→projection test** — projection tests seed via
   `projection_seed.py` helpers that re-implement the router's upsert SQL.
   Deferred with evidence in the spec frontmatter; judge whether deferral is
   acceptable or the seam is cheap enough to close now.
8. **`name` is the only entity attribute** (no description, no external key),
   unique per type, 200-char cap. Assumes the capstone corpus needs nothing
   richer.

## History a reviewer needs

- Baseline `e9479ec` was origin/main at dispatch; no rebase occurred; the
  branch is fast-forward from it.
- `ace7bf0` is a post-review patch commit produced by this run's own triage
  (14 findings patched: OWNS reconciliation, FK-race 404 guards, a
  `fetchone()` None guard, FK indexes added to the still-unapplied 0013,
  accurate per-route OpenAPI errors, six test additions, two cosmetics).
  Findings already patched there are not regressions; re-finding them means
  checking the fix, not re-reporting the original.
- The client was regenerated twice (`770cb4e`, then inside `ace7bf0` after
  the response-subset change), both via the pinned fallback because `:8000`
  may serve another checkout's api.

## Verification baseline

Run in the story worktree by the orchestrating run after `ace7bf0` — a skip
or failure during your review is a finding, not noise:

- `uv run --project server pytest server/tests/test_api_structure.py -q` — 22 passed.
- `uv run --project server pytest server/tests/test_projections_graph.py server/tests/test_projections_rebuild.py -q` — 55 passed (store-backed; queues on the cross-worktree projection lock).
- `uv run --project server pytest server/tests/test_migrations.py server/tests/test_api_registry.py server/tests/test_projections_single_writer.py -q` — 26 passed.
- `uv run --project server pytest server/tests/ -q` — 1566 passed, 0 failed, 0 skipped (13:42).
- `make web-test` — 202 passed (12 files). `pnpm --dir web run build` — clean.

Store notes (AGENTS.md): server suites are concurrent-safe (per-run
databases); projection suites queue on the shared file lock; `make evals-run`
is not needed and must not be run for this review.
