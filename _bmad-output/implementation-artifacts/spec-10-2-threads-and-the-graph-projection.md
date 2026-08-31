---
title: 'Story 10.2: Threads and the Graph Projection'
type: 'feature'
created: '2026-08-30'
baseline_revision: '4a111b8a981f3b5001e81f4bcbca54a2bdf28b42'
status: 'review'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-10-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/build-prompt-story-10-2-2026-08-30.md'
  - '{project-root}/_bmad-output/implementation-artifacts/wave-2026-08-30-rules.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-10-1-topic-extraction.md'
warnings: [oversized]
deferred: []
---

<intent-contract>

## Intent

**Problem:** Story 10.1 landed per-meeting `topic` / `topic_mention` rows, but nothing links a topic in one meeting to the same subject in another. There is no thread record, no `Topic`/`Thread` node in the graph, and no traversal that walks a subject over time — "what have we said about X" is still a `CONTAINS` over moment text (FR42).

**Approach:** Add a worker-owned `thread` table and a `topic_thread` link (migration 0015), derived corpus-wide by a pure, deterministic clustering in `domain/threads.py`: topics union by normalized name and by embedding cosine similarity at or above a configured threshold, with the rule and threshold in `config.yaml` with recorded rationale. `projections` — still the sole store writer (AD-4) — reads topics and their thread through `evidence.read_meeting` and writes `Topic` and `Thread` nodes with `MENTIONS` edges to moments. A third registered traversal template, `thread-timeline`, returns a thread's meetings and mentions in wall-clock order with per-level aggregates.

## Boundaries & Constraints

**Always:**
- **Derivation preserves durable identity.** The partition comes from an order-independent union-find. A cluster's candidate `identity_key` comes from its normalized name content, independent of meeting chronology; the database reuses a row already named by that key or already attached to a cluster member before minting. A rerun over unchanged rows, an earlier embedding-linked backfill, and Story 10.1's delete/reinsert replacement of an unchanged topic all preserve `thread.id`; unchanged UPSERTs write nothing.
- **Both linking legs, always.** Equal normalized name unions; cosine similarity `>= threads.embedding_similarity_threshold` unions. Union-find takes the transitive closure, so the partition does not depend on the order pairs are considered.
- **No silent fallback.** `derive_threads` requires an `Embedder`. An unreachable model host raises `EmbedderUnavailableError` and the derivation transaction rolls back whole — it never half-runs on the name leg alone and reports success.
- **The threshold fails closed.** `embedding_similarity_threshold` is `ge=0.5, le=1.0` in the config class. A near-zero threshold would union the entire corpus into one thread, and a silent everything is as wrong as a silent zero (the rule `traversals.py` already applies to a blank topic).
- `thread` and `topic_thread` are worker-owned, machine-derived navigation metadata: never an `artifact` row, never in `extracted → approved → published`. Migration 0015 says so in its header.
- **Identity outlives membership.** A `thread` may temporarily have no `topic_thread` links. Deleting, moving, cascading, or truncating the last membership never deletes the thread row as a side effect; this is what lets a Story 10.1 replace-all rerun reclaim the same id. Genuinely dead rows require a separate explicit sweep and retention policy.
- `projections` stays the sole store writer (AD-4). Nothing outside `projections/` imports `neo4j` or `meilisearch` — `test_projections_single_writer.py` already enforces it and must stay green.
- Graph writes follow the file's existing asymmetry: `Topic` is meeting-scoped (carries `meetingId`, deleted and reinserted by the per-meeting pass), `Thread` is cross-meeting (MERGE only, never deleted by a per-meeting pass — the same rule as `Screen`/`Participant`).
- `MENTIONS` edge count is verified after the write and a shortfall is a named `ProjectionError`, exactly as `OF_SCREEN` and `CITES` are.
- The `thread-timeline` template obeys all three AD-7 template rules: values travel as `$`-parameters (no quote character in the statement), every returned id is parsed to `UUID` or refused by name, and an unknown anchor is `thread=None` — distinguishable from a resolved thread with no mentions.
- Wall-clock order everywhere: `ORDER BY meeting.startedAt, meeting.id, mo.startMs, mo.id`, the same explicit tie-break chain the two existing templates use.
- Footprint per the build-prompt table, plus the four in-`projections/` files named in the Spec Change Log below. New tests only in the new `test_threads_*.py` / `test_projections_threads.py` files.

**Block If:** none — no decision here needs a human.

**Never:**
- No re-run or edit of extraction (`pipeline/extraction.py`, `pipeline/stages/extract.py` are 10.1's). Threads are derived from stored topics only.
- No worker start, no api start, no `make evals-run`, no real model call — the derivation tests inject a deterministic stub embedder.
- No thread curation (10.2a: merge/split/rename, api-owned alias rows), no chat routing (10.2b), no timeline API (10.3), no UI.
- No `thread.color_ordinal` — the epic's server-owned colour identity is per-*corpus* and `thread` has no corpus column; deciding its scope belongs to 10.3/10.6, and a half-right column is worse than none. Recorded as deferred.
- No edit to `test_migrations.py`, `test_projections_graph.py`, `conftest.py`, `projection_seed.py`, `infra/Makefile`, `AGENTS.md`, or anything under `web/`. The owner's 2026-08-30 correction explicitly requires filing B-39/B-40 in `docs/backlog.md`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Name link | Two meetings, topics "SFTP Migration" and "sftp  migration." | One thread; `identity_key` is canonical normalized cluster content; both links `linked_by='normalized-name'` | No error |
| Embedding link | Topics "Purchase order approvals" / "PO sign-off", cosine `>=` threshold | One thread; the non-seed link is `linked_by='embedding-similarity'` | No error |
| Below threshold | Cosine below the threshold and names differ | Two threads, one topic each | No error |
| Transitive closure | A~B by name, B~C by embedding | One thread containing A, B, C | No error |
| Idempotent rerun | `derive_threads` run twice over unchanged topics | Identical thread ids, identity keys, names and membership | No error |
| Earlier backfill | An earlier topic joins an existing thread by embedding | Existing and new topics use the original `thread.id`; chronology does not mint identity | No error |
| Replace-all rerun | One meeting's topics are deleted/reinserted; one normalized topic is unchanged | The unchanged cluster reclaims the retained row and identical `thread.id` | No error |
| Order independence | Same topics presented in any order to the pure clustering | Identical partition, content keys, and presentation seeds | No error |
| Embedder down | Model host unreachable | Nothing written; the transaction rolls back | `EmbedderUnavailableError` |
| Cluster emptied | Every member of a thread moves to another thread | The empty `thread` identity row remains for possible reuse | No error |
| Bare thread insert | A `thread` row inserted with no link | The empty identity row commits | No error |
| Threshold out of range | `threads.embedding_similarity_threshold: 0.1` | Startup refuses, naming the key and the bound | `ConfigError` |
| Projection pass | Meeting with topics reaches evidence-complete | `Topic` (meeting-scoped) + `Thread` (cross-meeting) nodes, `MENTIONS` to moments, `INCLUDES` from thread | No error |
| Re-projection | The same meeting projected twice | Identical node and edge counts; the `Thread` node survives the per-meeting delete | No error |
| Missing Moment node | A `MENTIONS` target Moment is absent | The whole per-meeting transaction rolls back, naming the shortfall | `ProjectionError` |
| Traversal happy path | A thread spanning two meetings | Meetings in wall-clock order; per-meeting mention count, `span_ms`, participants; thread-level totals and first/last mention | No error |
| Unknown thread anchor | A UUID matching no `Thread` node | `thread is None`, no meetings | No error |
| Resolved, no mentions | A `Thread` node with no `INCLUDES` | `thread` set, `meetings == ()`, `mention_count == 0` | No error |
| Non-UUID anchor | `thread_id="not-a-uuid"` | Refused before the store is touched | `ValueError` |
| Store unreachable | Neo4j down mid-traversal | Named refusal, not a raw driver error | `StoreUnavailableError` |

</intent-contract>

## Code Map

- `server/meetingminer/migrations/0014_topics.sql` -- READ-ONLY. The shape 0015 mirrors: header labelling worker-owned/machine-derived/outside the lifecycle, `uuidv7()` PKs, `set_updated_at` trigger, the DEFERRABLE constraint trigger for the parent-side invariant, the row trigger deleting a parent when its last child goes, and the TRUNCATE statement trigger that row triggers miss.
- `server/meetingminer/adapters/embed/port.py` -- `Embedder` protocol (`embed_documents`, `model`, `dimension`), `EmbedderError` / `EmbedderUnavailableError`. The derivation depends on the port only (AD-8).
- `server/meetingminer/projections/evidence.py` -- `MeetingEvidence` (line ~118) is the projection module's whole input surface, read-only over Postgres. `read_meeting` (line ~183) is where the topic + thread SELECT goes; `structure` (last field, has a default) is the precedent for appending `topics`.
- `server/meetingminer/projections/graph.py` -- `delete_meeting` (line 76) iterates `MEETING_SCOPED_LABELS`; `_write_moments` (line 293) writes the Moment nodes `MENTIONS` must match; `_write_artifacts` (line 407) is the model for the post-write edge-count check; `project_meeting` (line 481) is the ordered sequence a new `_write_topics` joins, after `_write_moments`.
- `server/meetingminer/projections/stores.py` -- `MEETING_SCOPED_LABELS` (line 66), `CROSS_MEETING_LABELS` (line 73), `_NODE_KEY_CONSTRAINTS` (line 227), `_MEETING_ID_INDEXES = MEETING_SCOPED_LABELS` (line 246). Adding `Topic` to the first gets it a `meetingId` index and per-meeting deletion for free.
- `server/meetingminer/projections/traversals.py` -- `TraversalMoment` (line 78), `_moment_of` (line 245) reused verbatim for the moment half of each mention row; `_input_uuid`, `_uuid_of`, `_string_of`, `_int_of`, `_run_cypher` reused for validation; `TRAVERSAL_TEMPLATES` (line 500) is the registry.
- `server/meetingminer/config.py` -- `ProjectionsConfig` (line 616) is the style model for a config block with recorded rationale; `class Settings` at line 785 is the insertion anchor; `acquisition: AcquisitionConfig` (line 800) is the last field.
- `server/tests/test_projections_traversals.py` -- line ~61 `test_the_registry_contains_exactly_the_two_templates` asserts `set(TRAVERSAL_TEMPLATES) == {SCREEN_HISTORY, PARTICIPANT_TOPIC_MOMENTS}`; a third template must be added there. `_cypher_parameter` + the no-quote assertion apply to the new statement automatically.
- `server/tests/projection_seed.py` -- READ-ONLY. `seed_meeting` (line 165) returns `SeededMeeting` with `moment_ids`; the new tests call it and insert their own `topic`/`topic_mention` rows locally.
- `server/tests/conftest.py` -- READ-ONLY. `EVIDENCE_TABLES` already names `topic`/`topic_mention`; `thread`/`topic_thread` cascade from `topic`, so no edit is needed. `FakeEmbedder` (line ~1108) is unsuitable for similarity assertions — the tests define their own stub.
- `server/tests/test_projections_single_writer.py` -- READ-ONLY. Import inspection that keeps `domain/threads.py` free of store clients.

## Tasks & Acceptance

**Execution:**
- `server/meetingminer/migrations/0015_threads.sql` -- NEW: `thread` (`id`, content-derived `identity_key` UNIQUE, `name`, `link_rule`, `derivation` jsonb, timestamps), `topic_thread` (`topic_id` PK → `topic` CASCADE, `thread_id` → `thread` CASCADE, `linked_by` CHECK), the `updated_at` trigger, and the `thread_id` index. No last-link trigger: an empty thread is retained durable identity for replacement/backfill reuse.
- `server/meetingminer/config.py` -- ADD `class ThreadsConfig(_StrictModel)` immediately before `class Settings`, and `threads: ThreadsConfig` as the last field of `Settings` -- AC1 requires the rule and threshold to be configuration with recorded rationale (AD-10).
- `config.yaml` -- APPEND a `threads:` block at EOF with `link_rule` and `embedding_similarity_threshold`, carrying the rationale for both the value and its lower bound -- same reason.
- `server/meetingminer/domain/threads.py` -- NEW: `normalized_topic_name`, `cosine_similarity`, the pure `cluster_topics(...)` union-find, and `derive_threads(conn, config, *, embedder, log=None) -> ThreadDerivation` doing the corpus-wide read and the upserts -- the derivation, with its decidable core separated from its SQL so the idempotency and order-independence clauses are testable without a database.
- `server/meetingminer/projections/evidence.py` -- ADD `TopicMentionRow`, `TopicRow`, `MeetingEvidence.topics` (default `()`), and the topic/mention/thread SELECT in `read_meeting` -- the projection's input surface is the only place the graph may learn about topics (AD-4).
- `server/meetingminer/projections/stores.py` -- ADD `Topic` to `MEETING_SCOPED_LABELS`, `Thread` to `CROSS_MEETING_LABELS`, and both to `_NODE_KEY_CONSTRAINTS` -- per-meeting deletion, the `meetingId` index, and the unique-id constraint all key off these tuples.
- `server/meetingminer/projections/graph.py` -- ADD `_write_topics` (Topic/Thread nodes, `MENTIONS`, `INCLUDES`, edge-count verification) called from `project_meeting` after `_write_moments`; extend the module docstring's naming section -- AC2.
- `server/meetingminer/projections/traversals.py` -- ADD `THREAD_TIMELINE`, its Cypher, the `ThreadAnchor`/`ThreadParticipant`/`ThreadMention`/`ThreadMeeting`/`ThreadTimelineResult` shapes, `thread_timeline()`, and its `TRAVERSAL_TEMPLATES` entry -- AC3.
- `server/tests/test_projections_traversals.py` -- EDIT one assertion so the registry test expects three templates -- an addition to the registry is by design an edit of the test that pins it.
- `docs/architecture.md` -- AMEND AD-4 with the clarification that topics and threads are navigation metadata outside the publish gate -- named explicitly by AC2.
- `server/tests/test_threads_derivation.py` -- NEW: the pure-clustering matrix rows (name, embedding, below-threshold, transitive, order-independence) plus normalization and cosine unit cases -- store-free, fast.
- `server/tests/test_threads_record.py` -- NEW: migration 0015's schema contract and the Postgres-backed derivation rows — unchanged rerun, earlier embedding-linked backfill, Story 10.1 replace-all identity, empty-row retention, and embedder-down rollback -- Postgres-only, fast set.
- `server/tests/test_projections_threads.py` -- NEW, `slow`: the graph write, re-projection stability, the missing-Moment refusal, and every traversal matrix row against the Neo4j twin.

**Acceptance Criteria:**
- Given topics from more than one meeting, when `derive_threads` runs twice with no topic change in between, then both runs produce byte-identical thread ids, identity keys, names and `topic_thread` membership, demonstrated by a test that captures the rows after each run and compares them.
- Given an earlier topic that joins an existing cluster by embedding, when derivation reruns, then every cluster member remains attached to the original `thread.id` even if the canonical content-key candidate changes.
- Given Story 10.1 replaces all topics in a meeting while one normalized topic is unchanged, when derivation reruns, then that cluster reuses the retained empty row and its `thread.id` is identical.
- Given a meeting with topics that reaches evidence-complete, when `projections.project_meeting` runs, then Neo4j holds one `Topic` node per topic carrying `meetingId`, one `Thread` node per distinct thread carrying no `meetingId`, one `MENTIONS` edge per `topic_mention` row, and one `INCLUDES` edge per membership — and re-running the projection leaves those counts unchanged.
- Given a thread spanning two meetings, when `run_template(driver, "thread-timeline", thread_id=...)` runs, then the meetings come back in wall-clock order, each carrying its mention count, its `span_ms`, and the participants known to have spoken in the mentioned moments, and the thread level carries the total mention count, the meeting count, and the first and last mention timestamps.
- Given `make test-fast`, when it runs in this worktree, then `make lint` and `make typecheck` pass and no new ruff baseline entry was added.

## Spec Change Log

- **2026-08-30 (owner decision, review findings F1/F5) — durable identity is content-derived and survives zero membership.** Diagnosis: **two mutable facts are being used as identity — which topic happens to be chronologically first, and whether the thread currently has any members. Neither is stable, so neither can be identity.** `identity_key` is now selected from normalized cluster content independently of chronology; derivation reuses a row named by that content or already attached to a member before minting; and migration 0015 no longer rejects or eagerly deletes an empty thread. Added red-first regressions for an earlier embedding-linked backfill and Story 10.1's delete/reinsert replacement path. The existing unchanged-rerun test does not delete and reinsert topic rows and therefore could not expose either defect.
- **2026-08-30, planning — footprint widened inside `projections/`, deliberately and on the record.** The build-prompt footprint names `projections/graph.py` and `projections/traversals.py` but no way for the graph to *learn* about topics: `graph.project_meeting` takes a `neo4j.Driver` and a `MeetingEvidence`, never a Postgres connection, and `evidence.py` is by design "the projection module's whole input surface". Delivering AC2 without touching `evidence.py` is not possible, and `Topic`'s per-meeting deletion and unique-id constraint key off tuples in `stores.py`. Two files are therefore edited beyond the table — `server/meetingminer/projections/evidence.py` and `server/meetingminer/projections/stores.py` — both additive, both inside `projections/`, and both untouched by every branch in flight (`story/6-2a`, `story/6-3`, `story/7-2`, `story/8-1`, plus the two `-review` branches), so `branch_conflicts.py` stays clean. `projections/__init__.py` is NOT touched: routing topics through `MeetingEvidence` is what keeps the orchestration unchanged. One test assertion in `server/tests/test_projections_traversals.py` is edited because it pins the registry's exact membership.
- **2026-08-30, planning; corrected by owner 2026-08-30 — deferred: nothing calls `derive_threads` in production yet.** Wiring it into the worker's settle point is an edit to `pipeline/stages/extract.py` and/or `domain/jobs.py`, which story 10.1 owns and the footprint marks "not yours". The function, its config and its record are complete and tested; the trigger is now actually filed as **B-39**. The earlier spec-only B-38 label did not reserve an id; Story 8.1 filed B-38 first.
- **2026-08-30, planning; corrected by owner 2026-08-30 — deferred: `thread.color_ordinal`.** The epic requires a server-owned, never-recycled, per-*corpus* colour ordinal. `thread` has no corpus column and a thread may span corpora; scoping that is a 10.3/10.6 decision. Actually filed as **B-40** rather than guessed at here.
- **2026-08-30, implementation — two further forced edits, both discovered by a failing gate rather than by planning.** (a) `server/tests/conftest.py`'s `EVIDENCE_TABLES` gains `thread` and `topic_thread`: `topic_thread` references `topic`, so `TRUNCATE` is refused outright without them and **every** DB-backed test in the suite fails. Not optional and not avoidable in a private module. (b) `server/meetingminer/api/chat_router.py` and its test: registering a third traversal tripped the router's rule that `TEMPLATE_ANCHORS` covers the whole registry. Wiring anchors would have been a live `AttributeError` — `_traversal_leg` in `chat.py` reads `result.rows` and `result.screen`/`result.participant`, none of which `ThreadTimelineResult` has — and adapting the orchestrator is story 10.2b. Resolved with a declared `DEFERRED_TEMPLATES` map so an omission and a decision stay distinguishable, and the tripwire keeps catching the omission. Neither file is touched by any in-flight branch. Also three forced one-liners in shared test modules: `test_config.py`'s `VALID_CONFIG` (a required config field, as 10.1 did for `topics_prompt`), `test_compose_contract.py`'s `SLOW_MODULES` (a store-backed module must be `slow`-marked, pinned in both places by design), and `test_projections_traversals.py`'s registry assertion.
- **2026-08-30, implementation — deferred: `domain/threads.py` is not in `[tool.mypy] files`.** Its pure clustering half is a decision core and arguably belongs there, but widening the scope is an edit of `server/pyproject.toml` **and** `test_lint_contract.py`'s `DECISION_CORE_FILES`, both outside the footprint. A one-line follow-up at integrate; ruff covers the file today.

## Review Triage Log

### 2026-08-30 — Owner-directed remediation of review findings F1/F5

- intent_gap: 2, both resolved by the owner's frozen-contract amendment
- bad_spec: 0
- patch: 2 (high 1, medium 1)
- defer: 0
- addressed_findings:
  - F1: earlier embedding-linked backfills retain the existing `thread.id`; the regression failed against the rebased pre-fix code and passes after content-key/member-row reuse.
  - F5: Story 10.1 replace-all reruns retain empty thread identity and reclaim the identical UUID for unchanged normalized content; the regression failed against the rebased pre-fix code and passes after removing eager orphan deletion.

## Design Notes

**Identity and presentation are separate.** The pure cluster candidate is the lexicographically first non-empty normalized name (with a normalized raw-content digest for punctuation-only names), never a timestamp-derived topic id. The chronological minimum remains only the machine display name and the member labelled `seed`. At the record, a retained row with the candidate key wins; otherwise an existing row already attached to a cluster member wins before minting. This makes content the source of identity while preserving the UUID when corpus growth adds an earlier embedding-linked name. Empty rows intentionally survive membership loss so a replace-all extraction can reclaim the same key/id; cleanup, if needed, is a separate policy-bearing sweep.

**Why union-find rather than a greedy pass.** The partition produced by union-find over a set of pairs is independent of the order the pairs arrive, which is exactly the idempotency clause AC1 asks for — a property of the algorithm, not of a sort the next maintainer might change. Pair generation is O(n²) over topics; at corpus scale (hundreds of meetings, a handful of topics each) that is thousands of dot products, and the comment says so rather than leaving a reader to wonder.

**Threshold rationale (recorded in `config.yaml`, summarized here).** `0.82` cosine over topic *names* — short strings, where an embedder's similarities run high and 0.7 already unions unrelated business nouns. It is deliberately conservative because the two failure modes are not symmetric: a missed link shows up as two threads a human can merge in 10.2a, while a false union silently fuses two subjects and reads as a bug. It is a starting value, not a measured one; the retrieval eval does not yet cover thread quality. The `ge=0.5` floor exists so a mistyped `0.05` fails at load instead of unioning the corpus.

**Participants "where known".** The traversal reads `(:Participant)-[:SPOKE_IN]->(:Moment)`, which the graph writes only for turns whose speaker actually resolved to a participant — an unresolved or ambiguous speaker contributes no edge (`evidence.py`'s existing rule: a wrong attribution is worse than an absent one). So the aggregate is honestly "participants known to have spoken in the mentioned moments", never the attendee list.

## Verification

**Commands:**
- `make test-fast` -- expected: `check-client`, `make lint`, `make typecheck`, the three store-free suites and the server fast set all pass; every skip printed with a named reason.
- `uv run --project server pytest server/tests/test_threads_derivation.py server/tests/test_threads_record.py -q` -- expected: all pass.
- `uv run --project server pytest -m "" server/tests/test_projections_threads.py server/tests/test_projections_traversals.py server/tests/test_projections_graph.py -q` -- expected: all pass against the worktree's Neo4j twin.
- `make test` -- expected: the full gate green (all four suites plus the web build) with the private stack up.
- `python3 _bmad/scripts/branch_conflicts.py --against story/10-2` -- expected: `clean` against `main` and every other `story/*` branch.

## Auto Run Result

Status: **review** (2026-08-30, at `34b1461` plus the tracking commit).

Verification actually run, in the foreground, with the worktree's private stack
(`meetingminer-10-2`, ports 20071–20077) up:

| Command | Result |
|---|---|
| `make test` (the full gate) | **2287 passed, 2 skipped**, exit 0, web build succeeded, 643s |
| `make test-fast` (includes `make lint` + `make typecheck`) | **1883 passed, 2 skipped, 404 deselected**, 56s |
| `pytest server/tests/test_threads_derivation.py` | **30 passed** |
| `pytest server/tests/test_threads_record.py` | **20 passed** |
| `pytest -m "" server/tests/test_projections_threads.py` | **26 passed**, 46s |
| `pytest -m "" test_projections_traversals + graph + single_writer + compose_contract + lint_contract` | **125 passed**, 107s |
| `branch_conflicts.py --against story/10-2` | `main × story/10-2` **clean** for every code, test, config, migration and doc file; after the `sprint-notes.md` entry it reports that one file and nothing else — no merge driver, main gained 6.3's entry after this branch was cut, and integrate unions it by wave rule |

The two skips are pre-existing and named: `pyannote.audio` is not installed,
and the real-network yt-dlp test needs `MM_YOUTUBE_NETWORK_TEST=1`.

Every I/O matrix row is covered by a test that ran and passed. Each clause the
acceptance criteria hinge on was additionally mutation-checked — the
implementation was deliberately broken and the suite observed failing — with
ten caught mutations and **two equivalent mutants reported rather than
inflated** (`min(members)` → `members[0]`, and dropping the internal sort; the
partition is order-independent through both the union-find and the explicit
`min`, so the order-independence test cannot fail against the current code and
earns its place only as protection against a future greedy refactor). That
limitation is stated in the review prompt for the reviewer to rule on.

Not done, deliberately, and named rather than implied: nothing calls
`derive_threads` in production yet (B-39 — the worker settle point is story
10.1's file), and `thread.color_ordinal` is not added (B-40). Both are filed in
`docs/backlog.md`.

### Owner remediation result — 2026-08-30

Status: **review complete — Pass** on final integration base
`e5e0ff9c6e0f52492ee26be0f5f985109da9efe0`.

Owner-directed findings F1/F5 are closed red-first: the earlier
embedding-linked backfill retains its original `thread.id` while persisting the
canonical normalized content key, and the Story 10.1 replace-all regression
deletes/reinserts topic rows yet reclaims the identical singleton UUID. The
existing unchanged-rerun test could not expose either path because it never
deletes and reinserts topics. Sequential review added and fixed F9: one prior
thread splitting into two clusters now assigns retained rows one-to-one instead
of collapsing the split.

Final verification after the last rebase: focused thread suites **63 passed**;
`make test-fast` server **2071 passed, 3 named skips, 405 deselected** plus
puller 128, web 294, and eval harness 643; `make test` server **2476 passed, 3
named skips** in 656.44s plus diarization 92, store reachability, all auxiliary
suites, and the production web build. Ruff and mypy are clean. B-39 and B-40
are filed in `docs/backlog.md`; migration 0015 still does not collide with main.
