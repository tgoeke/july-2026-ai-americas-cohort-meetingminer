---
title: 'Story 2.5: Series, Project & Product Assignment'
type: 'feature'
created: '2026-08-21'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md'
warnings: [oversized]
deferred:
  - summary: >-
      GET /series, /projects and /products are unbounded — every row plus
      every assigned meeting id, no pagination or cap.
    evidence: |-
      Same deliberate MVP scale posture already recorded for GET /meetings,
      GET /participants and story 2.3's drill-down payload in
      deferred-work.md — a posture for this corpus size, not a defect, but
      not yet recorded for these routes.
    location: >-
      server/meetingminer/api/structure.py (list_series, list_projects,
      list_products)
    severity: low
  - summary: >-
      No test exercises the API-written assignment rows end-to-end into the
      graph projection — the seam between the two surfaces rests on seed
      helpers re-implementing the router's upsert SQL.
    evidence: |-
      test_api_structure.py proves HTTP writes reach Postgres and read back;
      test_projections_graph.py seeds assignments via projection_seed.py
      helpers that duplicate the router's SQL. If the two drift, both halves
      stay green while declare-via-API-then-see-it-in-graph breaks. Same
      class as the deferred align.py alias-consumption seam recorded on
      story 2.4.
    location: >-
      server/tests/projection_seed.py (assign_meeting_series,
      assign_meeting_project)
    severity: medium
baseline_revision: 'e9479ec938c2f3f98e71608a38f8e83a68dcc953'
---

<intent-contract>

## Intent

**Problem:** The domain graph has no human-known structure: the ERD names `MEETING }o--o| SERIES`, `PROJECT ||--o{ MEETING` and `PRODUCT ||--o{ PROJECT`, and AD-5 assigns series membership and project/product assignment to the API as user-declared data the system never infers — but no table, no write path, and no graph projection for any of it exists (FR25). Epic 3's traversals can never walk structure nobody can declare.

**Approach:** Add migration `0013` with API-owned tables (`series`, `product`, `project` with nullable `product_id`, and one-row-per-meeting assignment tables `meeting_series` / `meeting_project` — AD-5 keeps the worker-owned `meeting` table untouched); a new auto-discovered `server/meetingminer/api/structure.py` router to create series/projects/products and assign meetings (and projects to products); and extend `projections/evidence.py` + `projections/graph.py` so the meeting's series/project/product appear as cross-meeting nodes and edges at the next projection or `rebuild`.

## Boundaries & Constraints

**Always:**
- AD-5 disjoint ownership: all five new tables are API-written only; the worker never reads or writes them, and no existing worker-owned table gains a column. Assignment lives in `meeting_series(meeting_id PK)` / `meeting_project(meeting_id PK)` — the PK is what enforces the ERD's at-most-one series and at-most-one project per meeting; reassignment is an upsert, `null` clears via DELETE of the row.
- API write pattern mirrors `participants.py` (story 2.4): `request.app.state.pool`, default READ COMMITTED, module-local `_PROBLEM_RESPONSES` including the `application/problem+json` OpenAPI media type (copy participants.py:143's shape, not moments.py's older one), camelCase `ConfigDict(alias_generator=to_camel, populate_by_name=True)`, `operation_id` on every route, name validation via the same `StringConstraints(strip_whitespace=True, min_length=1, max_length=200)` + NUL rejection idiom.
- `structure.py` exposes a module-level `router = APIRouter()`; zero `api/main.py` edits (registry auto-discovery, story 2.8); `test_api_registry.py`'s `BASELINE_ROUTER_ORDER` gains `"structure"` sorted by name among default-order modules (after `participants`).
- Graph naming follows graph.py's header conventions: cross-meeting nodes `Series`, `Project`, `Product` keyed by Postgres-minted UUID, upserted and never deleted per-meeting (same rule as `Screen`/`Participant`); edges `(Meeting)-[:IN_SERIES]->(Series)`, `(Project)-[:SCOPES]->(Meeting)`, `(Product)-[:OWNS]->(Project)` per the ERD verbs. Written inside `project_meeting`'s single per-meeting transaction; a meeting with no assignments writes nothing.
- No Neo4j/Meilisearch write from `api/` (AD-4/AD-5; the AST-walk guard `test_the_api_package_never_reaches_a_store` must stay green). Assignments reach the graph only at the next projection or `rebuild` — same documented lag as participant renames.
- `server/tests/conftest.py` `EVIDENCE_TABLES` gains all five new tables (pinned addition; the TRUNCATE fails loudly otherwise).
- Names are unique per entity type (`UNIQUE` on `series.name`, `project.name`, `product.name`); duplicate create → 409 `name-taken`.

**Block If:**
- Applying migration 0013 to the shared dev database fails or `make migrate` is needed against a database another agent is actively migrating — announce, do not force.

**Never:**
- No columns added to `meeting` (worker-owned, AD-5); no writes to any worker-owned table.
- No inference, bulk auto-assignment, or name-matching suggestion endpoint — membership is declared row by row by a human (FR25).
- No web UI: the story's acceptance surface is the API and the graph projection. No `web/src/features/*` screen; the generated client is regenerated and committed only so `web/src/client/` tracks the OpenAPI schema.
- No Meilisearch document changes; no new traversal templates (Epic 3 owns those).
- No delete endpoints for series/project/product entities themselves (only assignment clearing) — entity deletion semantics against projected graphs is future work; record in deferred-work.md if wanted.
- No hand-edits to `web/src/client/*.gen.ts`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Create series | `POST /series` `{name}` | 201: `{id, name, createdAt, updatedAt}` | No error expected |
| Create duplicate name | `POST /series\|/projects\|/products`, name already exists (same type) | 409 | `name-taken` |
| Blank name | Empty/whitespace/NUL name, any create/rename | 422 | `invalid-request` |
| Create project with product | `POST /projects` `{name, productId?}` | 201: row with `productId` set (or null) | Unknown `productId` → 404 `not-found` |
| Assign project→product | `PATCH /projects/{id}` `{productId}` | 200: updated row | Unknown project or product → 404 |
| Clear project's product | `PATCH /projects/{id}` `{productId: null}` | 200: `productId` null | No error expected |
| Assign meeting→series | `PUT /meetings/{meetingId}/series` `{seriesId}` | 200: `{meetingId, seriesId}`; repeat with another series replaces (upsert) | Unknown meeting or series → 404 |
| Clear meeting's series | `PUT /meetings/{meetingId}/series` `{seriesId: null}` | 200: `{meetingId, seriesId: null}`, row deleted | No error expected |
| Assign meeting→project | `PUT /meetings/{meetingId}/project` `{projectId}` (and null-clear) | Same shape as series assignment | Same 404 handling |
| List | `GET /series`, `GET /projects`, `GET /products` | 200: all rows; projects carry `productId`; each series/project row carries `meetingIds` (assigned meetings, ordered) | No error expected |
| Malformed id | Non-UUID path param, any route | 422 | `invalid-request` |
| Projection | Meeting with series+project(+product) assigned, then `project_meeting`/`rebuild` | `Series`/`Project`/`Product` nodes exist; `IN_SERIES`, `SCOPES`, `OWNS` edges present; unassigned meeting projects no such nodes/edges | No error expected |
| Re-projection after clear | Assignment cleared, meeting re-projected | `IN_SERIES`/`SCOPES` edge to that meeting gone (meeting-scoped delete removes it); orphaned `Series`/`Project`/`Product` nodes may remain until `rebuild --all` | No error expected |

</intent-contract>

## Code Map

Read on `story/2-5` at baseline `e9479ec938c2f3f98e71608a38f8e83a68dcc953` (= origin/main).

- `server/meetingminer/migrations/0002_meetings_media_frames.sql:1-47` — conventions to copy: `uuid PRIMARY KEY DEFAULT uuidv7()`, `set_updated_at()` trigger per table, header comment naming the story and ADs. Next file is `0013_series_projects_products.sql`; the runner auto-discovers by sort order (`test_migration_files_are_discovered_in_order` checks sorting only, no edit needed).
- `_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md:366-369` (ERD), AD-4 (:189), AD-5 (:195) — the frozen relationship shape and ownership rules; quote AD-5 in the router docstring the way `participants.py` does.
- `server/meetingminer/api/participants.py` — the router to mirror end to end: module docstring citing AD-5, `DisplayName`-style `StringConstraints` + NUL `field_validator` (:36-46 plus validator), `_PROBLEM_RESPONSES` with the problem+json media type (:143), `request.app.state.pool` + `pool.connection()` per route (:205-300), 404/409/422 raising via `Problem`.
- `server/meetingminer/api/problems.py:52-69` — `Problem(status, slug, detail, ...)`; `_STATUS_TITLES` already covers 404/409/422.
- `server/meetingminer/api/registry.py` + `server/tests/test_api_registry.py:28-44,116` — auto-discovery; append `"structure"` to `BASELINE_ROUTER_ORDER` (default-order module, sorts after `"participants"` by name). `/meetings/{id}/series|project` collides with nothing in `meetings.py`/`moments.py` (distinct literal tail segments).
- `server/meetingminer/projections/evidence.py:103-123,160-320` — `MeetingEvidence` dataclass and `read_meeting`: add a frozen `StructureRow` (series id+name, project id+name, product id+name, all optional) or three optional fields; one extra SELECT joining `meeting_series`→`series`, `meeting_project`→`project`→`product` by `meeting_id`. Read-only module — SELECTs only.
- `server/meetingminer/projections/graph.py:81-96,372-396` — `_write_meeting` and `project_meeting`'s ordered transaction: add `_write_structure(tx, evidence)` after `_write_meeting` (needs the `Meeting` node to exist). MERGE-never-CREATE like `_write_screens` (:136-158); nodes carry `id` + `name`, no `meetingId` property (cross-meeting, survives `delete_meeting` — `MEETING_SCOPED_LABELS` at `projections/stores.py:50` is NOT extended). `delete_meeting`'s DETACH DELETE on `Meeting` already removes stale `IN_SERIES`/`SCOPES` edges on re-projection.
- `server/meetingminer/projections/stores.py:220` — `_MEETING_ID_INDEXES = MEETING_SCOPED_LABELS`: check whether unique-id constraints/indexes are created per label near there; if cross-meeting labels (`Screen`, `Participant`) get id constraints, give `Series`/`Project`/`Product` the same.
- `server/tests/conftest.py:275-303` — `EVIDENCE_TABLES` + `truncate_evidence`; add `series`, `product`, `project`, `meeting_series`, `meeting_project` (assignment tables before their targets is irrelevant — one TRUNCATE statement).
- `server/tests/projection_seed.py:103` (`seed_meeting`), `:75-101` (`seed_participant` shape) — add `seed_series`/`seed_product`/`seed_project`/assignment helpers in the same direct-INSERT style for projection tests.
- `server/tests/test_projections_graph.py:1-80` — store-backed test conventions: `projection_stores` fixture, `truncate_evidence`, label/edge count assertions; extend with a structure-projection test and a no-assignment test.
- `server/tests/test_api_participants.py` — API test conventions to copy for `test_api_structure.py` (TestClient via the `client` fixture, one test per matrix row).
- `server/tests/test_projections_single_writer.py:101` — the AST guard that must stay green: `structure.py` imports no store client.
- `web/src/client/` — regenerate via `make client` (api running) or the pinned fallback (dump `app.openapi()` in-process, then `pnpm --dir web run client -i <dump>`; 2.4 note: `:8000` may be another checkout's api — verify before trusting `make client`). No web feature code; SDK mock factories need no edits (they mock whole modules and no component calls the new ops).
- Do not touch: `api/main.py`, `pipeline/**`, `worker/**`, `api/meetings.py`, `api/moments.py`, `projections/search.py`, `projections/traversals.py`.

## Tasks & Acceptance

**Execution:**
1. `server/meetingminer/migrations/0013_series_projects_products.sql` (new) — `series`, `product`, `project` (`product_id uuid NULL REFERENCES product(id)`), `meeting_series` (`meeting_id uuid PRIMARY KEY REFERENCES meeting(id) ON DELETE CASCADE`, `series_id uuid NOT NULL REFERENCES series(id)`), `meeting_project` (same shape → `project(id)`); `UNIQUE` names; `set_updated_at` triggers on the three entity tables; header comment citing story 2.5, AD-5, ERD — because the ERD's cardinalities must be schema-enforced, not convention.
2. `server/meetingminer/api/structure.py` (new) — models + routes per the I/O matrix: `POST /series` (`createSeries`), `GET /series` (`listSeries`), `POST /products` (`createProduct`), `GET /products` (`listProducts`), `POST /projects` (`createProject`), `PATCH /projects/{project_id}` (`assignProjectProduct`), `GET /projects` (`listProjects`), `PUT /meetings/{meeting_id}/series` (`assignMeetingSeries`), `PUT /meetings/{meeting_id}/project` (`assignMeetingProject`) — because this is AD-5's API-owned write path.
3. `server/tests/conftest.py` — extend `EVIDENCE_TABLES` with the five tables — test isolation.
4. `server/tests/projection_seed.py` — `seed_series`/`seed_product`/`seed_project`/`assign_meeting_series`/`assign_meeting_project` direct-INSERT helpers — projection tests must not run the API.
5. `server/tests/test_api_structure.py` (new) — one test per I/O-matrix row plus: series reassignment replaces (one row, new target); assignment survives being read back through `GET /series` `meetingIds`.
6. `server/meetingminer/projections/evidence.py` — structure fields on `MeetingEvidence` + the SELECT in `read_meeting` — the projection's only input surface.
7. `server/meetingminer/projections/graph.py` — `_write_structure` + call in `project_meeting`; module docstring's node/edge list updated — AD-4's single writer.
8. `server/tests/test_projections_graph.py` — tests: assigned meeting projects `Series`/`Project`/`Product` nodes and `IN_SERIES`/`SCOPES`/`OWNS` edges; unassigned meeting projects none; re-projection after clearing drops the meeting's edges; two meetings sharing a series yield one `Series` node.
9. `server/tests/test_api_registry.py` — append `"structure"` to `BASELINE_ROUTER_ORDER` — the registry contract test.
10. `web/src/client/` — regenerate and commit — the committed client must track the OpenAPI schema.

**Acceptance Criteria:**
- Given an ingested meeting and a created series, when the meeting is assigned via `PUT /meetings/{id}/series`, then the membership persists in `meeting_series`, is visible in `GET /series` `meetingIds`, and nothing infers or alters it on any worker run.
- Given a product, a project assigned to it, and a meeting assigned to the project, when evidence is next projected (or `rebuild` runs), then `(Product)-[:OWNS]->(Project)-[:SCOPES]->(Meeting)` and any `(Meeting)-[:IN_SERIES]->(Series)` exist in Neo4j with Postgres-minted UUIDs verbatim.
- Given a meeting with no assignments, when it projects, then no structure nodes or edges are written for it and projection succeeds unchanged.
- Given the API package, when the AST single-writer guard runs, then `structure.py` reaches no store.

## Spec Change Log

## Review Triage Log

### 2026-08-21 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 14: (high 0, medium 1, low 13)
- defer: 2: (high 0, medium 1, low 1)
- reject: 8: (high 0, medium 0, low 8)
- addressed_findings:
  - `[medium]` `[patch]` Reassigning a project's product left the old
    `(Product)-[:OWNS]->(Project)` edge in Neo4j until `rebuild --all` —
    both endpoints are cross-meeting nodes that MERGE-only writing and the
    per-meeting DETACH DELETE never touch, so the graph showed two owners.
    `_write_structure` now reconciles the project's `OWNS` edges to its
    current product (deleting stale ones, all of them when the product is
    cleared) inside the per-meeting transaction, with regression tests for
    reassign and clear.
  - `[low]` `[patch]` Both meeting-assignment PUTs lacked the
    `ForeignKeyViolation` → named 404 handling their sibling
    `create_project` already had, and `assign_project_product` could 500 on
    either side of its check-then-write race (`row[0]` on `None`, unguarded
    FK violation). All three now refuse with the named 404.
  - `[low]` `[patch]` `read_meeting`'s structure `fetchone()` was indexed
    with no `None` guard; now raises the module's established `LookupError`.
  - `[low]` `[patch]` Migration 0013 gained the three missing FK indexes
    (`project.product_id`, `meeting_series.series_id`,
    `meeting_project.project_id`) — edited in place, 0013 having reached
    only per-run test databases.
  - `[low]` `[patch]` The shared `_PROBLEM_RESPONSES` advertised impossible
    errors (404 on creates that cannot return one, 409 on routes with no
    conflict path); replaced with accurate per-route response subsets, and
    the 422 description now names every enforced cause. Client regenerated.
  - `[low]` `[patch]` Test gaps closed: missing-key `{}` is 422 on both
    PUTs and the PATCH; null-clear on an unassigned meeting is 200; non-UUID
    body ids are 422; `PATCH /projects/{id}` advances `updatedAt` with
    `createdAt` fixed (pins the 0013 trigger the suite otherwise never
    observes); structure asserted through the real `rebuild` path (AC3 names
    it explicitly).
  - `[low]` `[patch]` Cosmetics: graph.py's truncated docstring bullet
    completed; the one structure test missing its sibling `conn.commit()`
    aligned.

## Design Notes

**Assignment tables, not `meeting` columns.** AD-5 splits `artifact` and `participant` by column explicitly and lists nothing else; putting `series_id` on the worker-owned `meeting` row would create a third undeclared column split. A one-row-per-meeting table with `meeting_id` as PK gives the API sole ownership and enforces the ERD's at-most-one cardinality in schema.

**Cross-meeting nodes upserted, never deleted per-meeting** — same asymmetry as `Screen`/`Participant` (graph.py header). A cleared assignment loses its edge at the meeting's next re-projection (DETACH DELETE on the `Meeting` node takes the edge); an entity node with no remaining edges lingers until `rebuild --all`, which is the documented disposable-projection remedy, not a defect.

**`OWNS` is reconciled, not merely upserted.** `(Product)-[:OWNS]->(Project)` connects two cross-meeting nodes, so no per-meeting DETACH DELETE ever removes a stale one — under MERGE-only writing a project PATCHed from product A to product B would show two owners until `rebuild --all`. `_write_structure` therefore reconciles the project's `OWNS` edges to exactly its current state inside the per-meeting transaction: when the meeting's project is written, every `OWNS` edge into that `Project` node from a product other than the current one is deleted, and all of them when the project has no product. Stale `Product` *nodes* still linger per the orphan-node note above; only the ownership edge is reconciled eagerly, because a wrong edge misleads Epic 3 traversals in a way an unconnected node does not.

**`PUT` with nullable id for assignment** — the assignment is a single-valued property of the meeting; `PUT` replaces it idempotently and `null` clears it, avoiding a second DELETE route per relation.

## Verification

**Commands:**
- `uv run --project server pytest server/tests/test_api_structure.py -q` — expected: green (per-run database, concurrent-safe since 2.7).
- `uv run --project server pytest server/tests/test_projections_graph.py -q` — expected: green (queues on the cross-worktree projection lock if contended).
- `uv run --project server pytest server/tests/test_migrations.py server/tests/test_api_registry.py server/tests/test_projections_single_writer.py -q` — expected: green.
- `uv run --project server pytest server/tests/ -q` — expected: no regressions beyond the documented contention-only flakes (`test_api_chat.py`, `test_parallel_store_safety.py`).
- `make client` (or the pinned fallback if `:8000` is foreign) then `pnpm --dir web run build` — expected: new operations in `web/src/client/`, clean build.
- `make web-test` — expected: all vitest suites still pass (no web code changed).

## Auto Run Result

Status: done
Blocking condition: none

**What was built.** FR25's human-declared structure: migration 0013 adds five
API-owned tables (`series`, `product`, `project` with nullable `product_id`,
and one-row-per-meeting `meeting_series`/`meeting_project` whose `meeting_id`
PRIMARY KEY schema-enforces the ERD's at-most-one cardinality — no column
touches the worker-owned `meeting` table, per AD-5). A new auto-discovered
`api/structure.py` router creates series/projects/products and assigns
meetings (`PUT /meetings/{id}/series|project`, null clears) and projects to
products (`PATCH /projects/{id}`), with 409 name-uniqueness, named 404/422
problems, and per-route-accurate OpenAPI error contracts. The graph
projection gains `StructureRow` on the evidence bundle and
`_write_structure`: cross-meeting `Series`/`Project`/`Product` nodes
(upserted, never deleted per-meeting, like `Screen`/`Participant`) with
`IN_SERIES`/`SCOPES`/`OWNS` edges written inside the per-meeting
transaction — and `OWNS` is *reconciled*, not merely merged, so a product
reassignment converges instead of accumulating owners. No web UI (the
acceptance surface is the API and the projection); the TS client is
regenerated so `web/src/client/` tracks the schema.

**Files changed**
- `server/meetingminer/migrations/0013_series_projects_products.sql` (new) —
  five tables, UNIQUE names, `set_updated_at` triggers, FK indexes.
- `server/meetingminer/api/structure.py` (new) — nine routes, FK-race → named
  404 guards, accurate per-route problem responses.
- `server/meetingminer/projections/evidence.py` — `StructureRow` +
  meeting-anchored LEFT-JOIN read with `LookupError` guard.
- `server/meetingminer/projections/graph.py` — `_write_structure` with OWNS
  reconciliation; docstring updated.
- `server/meetingminer/projections/stores.py` — the three labels gain the
  same unique-id constraints as `Screen`/`Participant`.
- `server/tests/conftest.py` — five tables in `EVIDENCE_TABLES`.
- `server/tests/projection_seed.py` — structure seed/assign/clear helpers.
- `server/tests/test_api_structure.py` (new, 22 tests) — one per I/O-matrix
  row plus reassignment-replaces, read-back, missing-key/body-UUID 422s,
  clear-of-nothing 200s, `updatedAt` trigger pin.
- `server/tests/test_projections_graph.py` — six structure tests including
  OWNS-reconciliation regression and shared-series single-node.
- `server/tests/test_projections_rebuild.py` — structure through the real
  `rebuild` path (AC3 names it).
- `server/tests/test_api_registry.py` — `"structure"` in
  `BASELINE_ROUTER_ORDER`.
- `web/src/client/{index,sdk.gen,types.gen}.ts` — regenerated (pinned
  fallback both times; `:8000` not trusted).

**Review findings breakdown.** 14 patched (0 high, 1 medium, 13 low),
2 deferred (1 medium: the API→projection seam tested in halves; 1 low:
unbounded list endpoints), 8 rejected, 0 intent gaps, 0 spec defects — no
loopback. Follow-up review recommendation: **true** — patched counts 1
medium + 13 low give score 3×1 + 13 = 16 ≥ 5.

**Verification performed** (every command run directly by the orchestrating
run after the patch commit, not accepted from the implementation subagent):
- `pytest server/tests/test_api_structure.py -q` — 22 passed.
- `pytest server/tests/test_projections_graph.py server/tests/test_projections_rebuild.py -q`
  — 55 passed (store-backed, 4:26 including lock waits).
- `pytest server/tests/test_migrations.py server/tests/test_api_registry.py server/tests/test_projections_single_writer.py -q`
  — 26 passed (includes the AST single-writer guard over `structure.py`).
- `pytest server/tests/ -q` (full suite) — **1566 passed, 0 failed, 0
  skipped** in 13:42; not even the documented contention-only flakes fired.
- `make web-test` — 202 passed, 12 files. `pnpm --dir web run build` — clean.
- Matrix Test Audit: all matrix rows have covering tests that ran and passed.
- Client regeneration used the pinned fallback (in-process `app.openapi()`
  dump → `pnpm --dir web run client -i`), since `:8000` may serve another
  checkout's api.

**Residual risks**
- Migration 0013 has not been applied to the shared dev database (test
  suites use per-run databases; the Block-If never triggered). The
  between-stories integration loop must run `make migrate` — announced —
  before the new routes work against the dev stack.
- The OWNS reconciliation fires when one of the project's meetings
  re-projects; a project whose product is PATCHed while none of its meetings
  re-project shows the old edge until then or `rebuild` — the documented
  AD-4 lag posture, now recorded in Design Notes.
- The API→projection seam rests on seed helpers duplicating the router's
  upsert SQL (deferred, medium); unbounded list endpoints (deferred, low,
  matching the recorded MVP posture).
