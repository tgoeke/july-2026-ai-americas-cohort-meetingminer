---
title: 'Story 3.2 — Graph Traversal Templates'
type: 'feature'
created: '2026-08-20'
status: 'done'
baseline_revision: '4a555c9d7f11a706cc0aee84d219aab7d0234ca2'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-3-context.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md'
warnings: ['oversized']
deferred: []
---

<intent-contract>

## Intent

**Problem:** The Neo4j evidence projection is written (`projections/graph.py`) but nothing can read it — there is no deterministic retrieval path over the graph, so structural questions ("show every discussion of this screen over time", "I already explained this to Rowan") have no exact, testable, citable answer, and story 3.3's orchestrator has no traversal leg to classify questions onto (FR11, AD-7).

**Approach:** Add the graph query side of the projection module: hand-written, parameterized Cypher templates in a new `projections/traversals.py`, exposed through a named template registry that story 3.3's router will classify onto. Two templates: **screen-history** (screen → every meeting and moment where it appeared, in time order) and **participant-topic-moments** (participant → meetings attended → moments whose text discusses the topic — the Rowan query). Results carry Postgres-minted UUIDs verbatim (AD-6). No HTTP surface — the `/chat` orchestrator (3.3) and the deferred retrieval eval are the consumers; the template functions and registry are this story's outermost surface per its ACs.

## Boundaries & Constraints

**Always:**
- `neo4j` is imported only under `server/meetingminer/projections/` — `tests/test_projections_single_writer.py` asserts it by AST walk. The new module lives inside that package.
- Every Cypher statement is a hand-written, parameterized string: values travel as query parameters, never interpolated into the statement text (AD-7). No library builds, extracts, or owns graph structure; no neo4j-graphrag, APOC procedure, or auto-retriever.
- Every returned moment id is the Postgres-minted UUID carried verbatim from the graph node, parsed to `UUID`; a node whose `id` does not parse is a named `ProjectionError`, mirroring `projections/query.py`'s precedent (AD-6).
- "No silent zero": an unknown anchor (screen or participant id that matches no node) is distinguishable in the result from an anchor that exists but has no matching moments — the former reports the anchor as unresolved, the latter is a valid empty answer.
- Reuse the existing error taxonomy from `projections/stores.py` (`ProjectionError`, `StoreUnavailableError`); wrap driver/session failures rather than leaking raw `neo4j` exceptions to callers outside the package.
- Time order is deterministic: `meeting.startedAt` ascending, then `meeting.id`, then `moment.startMs` — the explicit tie-break matters because distinct meetings can share a `startedAt`.
- Topic matching is case-insensitive substring over `Moment.text` (`toLower(...) CONTAINS toLower($topic)`); a blank or whitespace-only topic is refused with `ValueError` (it would match the whole corpus — a silent everything is as wrong as a silent zero).
- No new config knobs and no result limit: the deferred retrieval eval (leg 2, `evals/designs/retrieval-eval.md`) compares **exact sets**, so templates return the complete result.

**Block If:**
- The graph projection turns out to lack an edge or property either template needs (e.g. `Moment.text` absent on projected nodes), forcing a change to `projections/graph.py`'s written shape — that is a projection-schema change with rebuild consequences, not a retrieval story.

**Never:**
- No API route, no web changes — the traversal HTTP/chat surface is story 3.3's (`/chat`), and the eval query driver is Epic 5's.
- No Topic nodes and no topic hop: topic extraction is Epic 4; spec-1-7 records that Epic 3 templates must not assume it. Topic = text term over `Moment.text`.
- Do not modify `projections/graph.py`, `stores.py`, or any written graph shape; do not add Neo4j full-text indexes (schema is `ensure_graph_schema`'s, and the corpus scale does not need one yet).
- Do not run `make evals-run` (serial, AGENTS.md).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Screen history, cross-meeting | Two projected meetings sharing a `Screen`; `screen_history(driver, screen_id=<id>)` | Rows for every moment SHOWS-ing a screenshot of that screen in both meetings, ordered by (`startedAt`, `meeting.id`, `startMs`); each row carries momentId, meetingId, meetingTitle, startMs, endMs, screenshotId, sourceDeepLink | No error expected |
| Unknown screen | `screen_id` matching no `Screen` node | Result reports anchor unresolved (`screen is None`), rows empty | Not an exception — a lookup miss is an answer |
| Screen with no moment | `Screen` exists, no moment SHOWS its screenshots | Anchor resolved, rows empty | Valid empty, distinct from unknown anchor |
| Rowan happy path | Participant ATTENDED a meeting whose moment text contains the topic | Those moments returned with the anchor participant's id/identityKey/displayName | No error expected |
| Participant not present | Topic discussed in a meeting the participant did not attend | That meeting's moments excluded | No error expected |
| Case-insensitive topic | Topic `"sftp"` vs seeded text `"SFTP"` | Same rows either way | No error expected |
| Unknown participant | `participant_id` matching no node | Anchor unresolved, rows empty | Not an exception |
| Blank topic | `topic=""` or `"   "` | Refused | `ValueError` naming the parameter |
| Registry dispatch | `run_template(driver, "screen-history", screen_id=...)` | Same result as calling the function directly | Unknown template name → `ProjectionError` listing registered names |
| Store down | Neo4j unreachable when a template runs | Named failure | `StoreUnavailableError` via `stores.neo4j_driver` / wrapped session error |
| Corrupt node id | A graph node whose `id` is not a UUID | Named failure, no partial silent result | `ProjectionError` naming the node |

</intent-contract>

## Code Map

- `server/meetingminer/projections/graph.py:1-32` -- the written graph shape this story reads: nodes `Meeting`/`Moment`/`Screen`/`Screenshot`/`Participant`/`Chunk`; edges `HAS_MOMENT`, `SHOWS` (only when the moment names a screenshot), `OF_SCREEN`, `SHOWN_DURING`, `ATTENDED`, `SPOKE_IN`, `COVERS`. Node properties written at `:79-338` — `Meeting.startedAt` is an ISO-8601 string via `_iso`, `Moment.text`/`startMs`/`endMs`/`screenshotId`/`sourceDeepLink` are set in `_write_moments`.
- `server/meetingminer/projections/stores.py:65-84` error taxonomy (`ProjectionError`, `StoreUnavailableError`); `:91` `neo4j_driver(config)` context manager; `:50` `MEETING_SCOPED_LABELS`; `:223` `ensure_graph_schema` (read-only fact: id-uniqueness constraints exist per label).
- `server/meetingminer/projections/query.py:1-41` -- the Meilisearch query half: module-docstring style, error wrapping, and the non-UUID-id → `ProjectionError` precedent (`:468` area) this module mirrors for Neo4j.
- `server/tests/test_projections_single_writer.py:71` -- the AST walk that forces the new module under `projections/`; `:101` the api package check.
- `server/tests/test_projections_graph.py:31-48` -- house style for graph tests: `pool` fixture truncating evidence, `project()` helper calling `projections.project_meeting(conn, config, meeting_id, embedder_factory=...)`, `query()` helper; `:208` `test_a_participant_traversal_spans_meetings` is the nearest existing precedent.
- `server/tests/projection_seed.py:75` `seed_meeting(conn, *, source_id, has_recording, title, corpus, turns, participants, screen_identity_keys, with_moments, stage_overrides)`; `:28` `STARTED_AT` constant (every seeded meeting/moment gets it — the reason a `started_at` override is needed for time-order tests); `:42` `DEFAULT_TURNS` (text includes "SFTP", "purchase order"; participants Blake/Reed; `Speaker 8` unresolved); `:50` `DEFAULT_PARTICIPANTS` (`mail:` identity keys).
- `server/tests/conftest.py:989` `projection_stores` (wipes both stores, re-schemas, holds the cross-process file lock; yields `(driver, meili_client)`), `:825` `fake_embedder`, `:186` `app_config`, `:236` `test_pool`, `:285` `truncate_evidence`.
- `server/meetingminer/projections/evidence.py:79` `MomentRow` / `:160` `read_meeting` -- read-only context for what the projection carries.
- `_bmad-output/implementation-artifacts/spec-1-7-evidence-projections-rebuild-cli.md:407` -- records the intended traversal shapes: screen history = `Screen ← Screenshot ← Moment → Meeting` ordered by `startedAt`; Rowan = `Participant → Meeting → Moment` with **no topic hop until Epic 4**.
- `evals/designs/retrieval-eval.md:51-74` -- deferred leg-2 contract: exact-set comparison over `(participant, meeting, topic, moment)` tuples; participant identity compared by `identityKey` — why result rows must expose it.

## Tasks & Acceptance

**Execution:**
- `server/meetingminer/projections/traversals.py` (new) -- the graph query half of AD-7: frozen dataclasses (`TraversalMoment` row carrying `moment_id`, `meeting_id`, `meeting_title`, `meeting_started_at`, `start_ms`, `end_ms`, `screenshot_id`, `source_deep_link`; anchor types `ScreenAnchor(id, identity_key, label, view_type)` and `ParticipantAnchor(id, identity_key, display_name)`; results pairing `anchor | None` with `rows`), the two template functions `screen_history(driver, *, screen_id)` and `participant_topic_moments(driver, *, participant_id, topic)`, each backed by hand-written parameterized Cypher (anchor lookup + traversal), and the registry: a frozen `TraversalTemplate(name, parameters, cypher, run)` per template, `TRAVERSAL_TEMPLATES` mapping exactly `{"screen-history", "participant-topic-moments"}`, and `run_template(driver, name, **params)` dispatching by name -- the registry is what 3.3's router classifies onto, and the dataclass carrying the Cypher text is what makes "hand-written, parameterized" reviewable in one place.
- `server/tests/projection_seed.py` -- add keyword-only `started_at: datetime = STARTED_AT` to `seed_meeting`, used for both the `meeting.started_at` INSERT and each moment's `started_at` -- pinned shared addition (AGENTS.md): time-order assertions across meetings need distinct `startedAt` values, and 3.3's tests will want the same lever. No other seed behavior changes.
- `server/tests/test_projections_traversals.py` (new) -- store-free tests: registry completeness (exactly the two names, declared parameters, Cypher text contains `$`-parameters and never an interpolated value), unknown template name → `ProjectionError`, blank topic → `ValueError`, non-UUID node id → `ProjectionError` (via the row parser), and an import-inspection assertion that no graph-building/auto-retriever library (`neo4j_graphrag`, `graphdatascience`, `langchain`, `llama_index`) is imported anywhere under `meetingminer/` (AC4). Store-backed tests (declare `projection_stores`, seed with `seed_meeting`, project via the `test_projections_graph.py` `project()` pattern): every I/O-matrix row above that touches the store, including cross-meeting screen history in time order (two meetings, distinct `started_at`, shared `screen_identity_keys`), UUID-verbatim carriage (returned ids equal the seeded UUIDs as `UUID` values), Rowan inclusion/exclusion, and case-insensitivity.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` + `sprint-notes.md` -- move `3-2-graph-traversal-templates` to `review`; record what landed and that no API surface exists yet (3.3's).

**Acceptance Criteria:**
- Given two projected meetings that both showed the same screen, when `screen_history` runs for that screen's id, then every meeting-and-moment pair where the screen appeared returns in (meeting `startedAt`, meeting id, moment `startMs`) order, via the parameterized Cypher recorded on the registered template (AC1, AD-7).
- Given a participant who attended meeting A but not meeting B, both discussing a topic, when `participant_topic_moments` runs for that participant and topic, then only meeting A's matching moments return, each row exposing the participant's `identityKey` (AC2; eval leg-2 comparison key).
- Given any template result, when its rows are inspected, then every `moment_id` equals a Postgres-minted moment UUID from the seeded corpus, as a parsed `UUID`, and each template has store-backed tests against seeded fixture data (AC3, AD-6).
- Given the registry, when reviewed and tested, then `TRAVERSAL_TEMPLATES` contains exactly the two named templates, each carrying its hand-written Cypher, `run_template` is the only dispatch, and no graph-auto-extraction library import exists in the server package (AC4, AD-7).
- Given the full server suite on this branch, when run, then every new test passes and no existing test regresses — including `test_projections_single_writer.py`.

## Spec Change Log

## Review Triage Log

### Review Findings

- [x] [Review][Patch] Complete the deterministic row-order key [server/meetingminer/projections/traversals.py:158] — both queries now end with `moment.id`, with a same-offset regression fixture.
- [x] [Review][Patch] Refuse non-UTC graph timestamps [server/meetingminer/projections/traversals.py:265] — non-zero offsets are named `ProjectionError` corruption and are covered store-free.
- [x] [Review][Patch] Refuse impossible moment intervals [server/meetingminer/projections/traversals.py:280] — negative and inverted offsets are named `ProjectionError` corruption and are covered store-free.
- [x] [Review][Patch] Keep the traversal result surface type-safe [server/meetingminer/projections/traversals.py:278] — nullable display fields now refuse non-string graph values, with canned-driver coverage.
- [x] [Review][Patch] Prove participant traversal time order [server/tests/test_projections_traversals.py:415] — a multi-meeting SFTP assertion independently pins the Rowan template's order.

### 2026-08-20 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 14: (high 0, medium 5, low 9)
- defer: 0
- reject: 4: (high 0, medium 0, low 4)
- addressed_findings:
  - `[medium]` `[patch]` `run_template` leaked a raw `TypeError` on missing/extra/misspelled kwargs — now validates the parameter set against the registration and raises `ProjectionError` naming the template, its parameters, and what was passed.
  - `[medium]` `[patch]` A malformed input anchor id collapsed into the "unknown anchor" shape — both templates now parse the id up front (`_input_uuid`) and raise `ValueError` naming the parameter, so a typo'd id is an input error, not a silent miss.
  - `[medium]` `[patch]` `startMs`/`endMs` passed `None` (or any non-int) into int-typed fields silently — `_int_of` now names the corruption as `ProjectionError`, per the module's own rule.
  - `[medium]` `[patch]` `ScreenAnchor.identity_key`, `ParticipantAnchor.identity_key`, and `display_name` could carry `None` — `_string_of` refuses missing values by name; `identity_key` is the eval's comparison key.
  - `[medium]` `[patch]` The `Neo4jError → ProjectionError` branch of `_run_cypher` was untested (only `ServiceUnavailable` was exercised) — added `_RefusingDriver` raising `ClientError` and a store-free test pinning the answered-and-refused half of the taxonomy.
  - `[low]` `[patch]` `topic=None` slipped past the blank guard as the string `"None"` — an `isinstance(topic, str)` check now precedes the blank check.
  - `[low]` `[patch]` A padded topic (`" SFTP"`) was matched literally, returning a false empty — the topic is stripped before it travels; a canned-driver test asserts what was actually sent to the store.
  - `[low]` `[patch]` A naive `meetingStartedAt` parsed without complaint though lexical time-order depends on offset-aware UTC — `tzinfo is None` is now a named `ProjectionError`.
  - `[low]` `[patch]` The parameterization test never checked the converse (an undeclared `$`-parameter would pass) and its no-quote claim overreached — now asserts set equality of all `$`-tokens with the declared parameters, claim scoped to string literals.
  - `[low]` `[patch]` `TraversalTemplate.parameters` could drift from the function signature unnoticed — the registry test now derives expectations from `inspect.signature(template.run)`.
  - `[low]` `[patch]` The tie-break test asserted only deduplicated meeting grouping — now asserts the exact full `(meeting_id, moment_id)` row order, with the str-sort/UUID-ordering premise stated.
  - `[low]` `[patch]` The unknown-template test passed `object()` as the driver — now `_UntouchableDriver()`, honest against dispatch reordering.
  - `[low]` `[patch]` `seed_meeting`'s docstring pointed at AGENTS.md for the `started_at` pin that actually lives in this spec — reworded.
  - `[low]` `[patch]` `seed_meeting` accepted a naive `started_at`, which Postgres would interpret in session timezone — now asserted timezone-aware.

## Design Notes

**Screen history walks `SHOWS`, not `SHOWN_DURING∘COVERS`.** spec-1-7 (the graph's author) records the intended shape: `Screen ← Screenshot ← Moment → Meeting` ordered by `startedAt`. The alternative — moments covering chunks the screen was `SHOWN_DURING` — would also count moments whose representative visual is a different screen. This story follows the recorded shape. *Assumption to attack: "where that screen appeared" could defensibly union both paths; the recorded design was chosen over the broader reading, and 3.3/eval can revisit with ground truth.*

**Templates take UUIDs, not names.** The demo question carries names ("Rowan"), but name→participant and label→screen resolution is classification — story 3.3's router owns it (AD-6: "the model's jobs are classifying the question to a template and synthesizing"). Templates stay deterministic on stable identifiers, which is also what the graph indexes (`id` uniqueness constraints). *Assumption to attack: 3.3 may need a deterministic name-resolver template added to the registry; the registry is a mapping precisely so that is an addition, not a rework.*

**Topic = case-insensitive substring over `Moment.text`.** No Topic nodes exist until Epic 4 (spec-1-7, recorded); `Moment.text` is the projected transcript text of the moment, so "the topic was discussed" is a text-term match at moment granularity. Substring, not tokenized: deterministic, explainable, and the scripted eval authors its topics as terms. *Assumption to attack: multi-word topics must appear verbatim; synonym/paraphrase topic matching is the search index's job (3.1/3.3 hybrid leg), not the graph's.*

**"Present" means ATTENDED the meeting, not SPOKE_IN the moment.** The Rowan story is "I already explained this *to* Rowan" — Rowan was in the room, not necessarily speaking. `ATTENDED` is meeting-scoped presence; `SPOKE_IN` would silently drop the listener case the demo is about.

**Graph fields on rows are projection reads, not citations.** Rows carry what the graph holds (title, offsets, deep link) for ordering and display context; story 3.3's citation validator re-resolves every cited moment against Postgres before anything reaches the wire ("Meilisearch/Neo4j rank, Postgres cites"). Nothing here claims citation authority.

## Verification

**Commands:**
- `cd <repo> && uv run --project server pytest server/tests/test_projections_traversals.py` -- expected: store-free tests always pass; store-backed tests pass with the Docker stores up (skip by name when down).
- `cd <repo> && uv run --project server pytest server/tests/test_projections_graph.py server/tests/test_projections_single_writer.py` -- expected: green — the seed change and the new module regress neither.
- `cd <repo> && uv run --project server pytest server/tests` -- expected: full server suite green, no regressions.

**Manual checks (if no CLI):**
- With a projected corpus, `python -c` invoking `run_template` for each name returns rows whose moment ids also resolve through the existing evidence reads.

## Auto Run Result

Status: done
Blocking condition: none

### What was implemented

The graph query half of AD-7: `server/meetingminer/projections/traversals.py`
holds two hand-written, parameterized Cypher templates — `screen-history`
(`Screen ← Screenshot ← Moment → Meeting`, ordered by `startedAt`, then
`meeting.id`, then `startMs`) and `participant-topic-moments` (the Rowan
query: `ATTENDED` presence, no topic hop, case-insensitive substring over
`Moment.text`, topic stripped and type-checked) — exposed through
`TRAVERSAL_TEMPLATES` and `run_template`, the registry story 3.3's router
classifies onto. Results carry Postgres-minted UUIDs parsed to `UUID`; every
corruption path (non-UUID node id, missing offsets, missing anchor identity,
naive `startedAt`) is a named `ProjectionError`; malformed caller input
(bad anchor id, blank/None topic, wrong dispatch kwargs) is a named refusal
before the store is touched. No API surface — deliberate; the template
functions and registry are this story's outermost surface.

### Files changed

- `server/meetingminer/projections/traversals.py` (new) — templates, result
  dataclasses, anchor/empty split, error taxonomy, registry, dispatch.
- `server/tests/test_projections_traversals.py` (new) — 23 tests: store-free
  (registry completeness derived from signatures, `$`-token set equality,
  refusal taxonomy incl. the answered-and-refused `ClientError` branch, AC4
  import walk) and store-backed (every I/O-matrix row, time order with
  tie-break, UUID carriage, Rowan inclusion/exclusion).
- `server/tests/projection_seed.py` — pinned shared addition: keyword-only
  `started_at` (timezone-aware, default unchanged) for cross-meeting
  time-order tests.
- `_bmad-output/implementation-artifacts/{sprint-status.yaml,sprint-notes.md}`
  — story status and narrative.

### Review findings breakdown

Four layers (blind hunter, edge-case hunter, verification-gap,
intent-alignment). 14 patches applied, 0 deferred, 4 rejected as noise. No
intent gap and no spec repair loopback: the intent-alignment audit found every
ambiguity resolved to a reading pre-recorded in this contract or spec-1-7,
each flagged divergence already listed under Design Notes as an assumption to
attack.

### Follow-up review recommendation

`true`. Patched this pass: high 0, medium 5, low 9. Score = 3 × 5 + 1 × 9 =
24, at or above the threshold of 5.

### Verification performed

Run in the story worktree after the patch pass, results observed directly:

- `uv run --project server pytest server/tests/test_projections_traversals.py`
  — **23 passed**, 0 skipped (stores up, so the store-backed half ran live).
- `uv run --project server pytest server/tests/test_projections_graph.py
  server/tests/test_projections_single_writer.py` — **20 passed** (pre-patch
  pass; both files unchanged by the patches).
- `uv run --project server pytest server/tests` — **1186 passed**, 0 skipped,
  0 failed (436s). An earlier mid-patch full run showed 1 failure in
  `test_projection_lock_times_out_with_holder_details_then_releases` caused by
  story 2-3's concurrently running suite holding the cross-worktree projection
  lock — that test spawns its own 10s-deadline holder and cannot tolerate a
  foreign one; re-run after that suite exited, it passes. Not a regression of
  this change.
- Matrix audit: all 12 I/O rows (including registry dispatch and the two
  refusal rows added by review) are covered by tests that ran and passed.

### Residual risks

- **Screen history walks `SHOWS` only.** Moments during which the screen was
  visible via `SHOWN_DURING`∘`COVERS` but represented by a different
  screenshot are excluded — the recorded spec-1-7 shape, flagged in Design
  Notes; eval ground truth can revisit.
- **Topic is a verbatim substring.** Multi-word topics must appear verbatim in
  `Moment.text`; paraphrase topic matching belongs to the search index's
  semantic lane, not the graph.
- **AC4 exclusivity is tested by proxy** — a four-name library denylist plus
  registry cardinality plus the single-writer import walk. An unlisted graph
  library, or raw retrieval Cypher added elsewhere inside `projections/`,
  would pass the tests and be caught only by review.
- **Traversal correctness is proven store-backed only** — those tests skip by
  name when the Docker stores are down; the store-free half covers refusals
  and registry shape, not traversal results.
- **Templates take UUIDs.** Story 3.3's router owns name→id resolution
  ("Rowan", "this screen"); a deterministic resolver template is a likely
  registry addition there.
