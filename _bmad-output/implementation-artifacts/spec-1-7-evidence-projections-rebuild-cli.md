---
title: 'Story 1.7: Evidence Projections & Rebuild CLI'
type: 'feature'
created: '2026-08-19'
baseline_commit: '89a1a0b'
baseline_revision: '89a1a0b300838a1601414d4ea291cac08d0893d7'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
  - '{project-root}/_bmad-output/specs/spec-meetingminer/retrieval-prior-art.md'
deferred:
  - summary: >-
      Store-backed projection tests write to the developer's real Neo4j and Meilisearch, and the
      `meeting_projection` guard then stops the worker re-projecting what they erased.
    evidence: |-
      AD-4 fixes the index names and Neo4j Community has a single database, so the suites operate
      on the same stores the running system uses. Observed directly during this run: after
      `pytest -k projections`, Neo4j held 1 Meeting / 2 Moment and Meilisearch 2 moment documents
      (test fixtures), while `meeting_projection` still recorded 5 real meetings as
      structural+embedded. Because `projection_action` returns ACTION_NONE whenever a current row
      exists, the worker will not restore them -- the meetings are silently unsearchable until
      someone runs `rebuild`. `rebuild --all`'s Neo4j wipe is also unscoped
      (`MATCH (n) DETACH DELETE n`), so it removes anything else sharing that database.
    location: >-
      server/meetingminer/projections/stores.py (drop_all); server/tests/conftest.py
    severity: high
  - summary: >-
      `projection_action` compares recorded config, never evidence freshness, so re-ingested
      evidence for an already-projected meeting is never re-projected by the worker.
    evidence: |-
      It returns ACTION_NONE when the row's embedder model, dimension, and chunking match config,
      with no comparison of `structural_at` against the meeting's evidence timestamps. The story's
      own Boundaries state "Story 1.12 re-projects through exactly this path", so 1.12 will need
      this before re-ingest can refresh a projection. `rebuild --meeting <id>` forces it today.
    location: >-
      server/meetingminer/projections/__init__.py (projection_action)
    severity: medium
  - summary: >-
      `ARTIFACTS_INDEX` is written by `project_artifact` but never created or configured by
      `ensure_search_schema`.
    evidence: |-
      The first Epic 4 call would auto-create `artifacts` with Meilisearch defaults -- no
      configured searchable attributes, ranking rules, or synonyms -- which contradicts the
      module's rule that anything not in config.yaml is not a deliberate choice. There is no
      production caller yet, so this is Epic 4 wiring rather than a live defect.
    location: >-
      server/meetingminer/projections/publish_gate.py
    severity: low
  - summary: >-
      The rebuild-equivalence acceptance criterion is asserted as rebuild idempotence, not as
      ingest-time-versus-rebuild equivalence.
    evidence: |-
      `test_rebuild_regenerates_both_stores_equivalently_after_a_wipe` rebuilds, captures counts
      and sample bodies, rebuilds again, and compares the two rebuilds. The "wipe" is rebuild's own
      `drop_all()`, and content produced by the worker's ingest-time trigger is never compared
      against content produced by `rebuild`. The corpus-level check was performed by hand in this
      run but is not pinned by a test.
    location: >-
      server/tests/test_projections_rebuild.py
    severity: medium
  - summary: >-
      An embedder swap to a different model of identical dimension is not refused at the store
      level, though AD-8 names model and dimension together.
    evidence: |-
      `assert_dimension_matches` and `assert_recorded_dimension_matches` compare only
      `embedder_dimension`; the model name is read for the error message. `projection_action`
      does compare the model, but only per meeting and only on the path that re-projects that
      meeting anyway, so a swap at equal width can leave two vector spaces in one index.
    location: >-
      server/meetingminer/projections/stores.py
    severity: medium
  - summary: >-
      `search.project_meeting` deletes then re-adds a meeting's documents across separately
      awaited tasks, leaving a window where a concurrent reader sees the meeting partly absent.
    evidence: |-
      A full projection does this twice -- once with `_vectors: null`, once with vectors. The
      delete-and-reinsert rule is documented at length, but neither the module nor the spec states
      whether Epic 3's read path must tolerate the window.
    location: >-
      server/meetingminer/projections/search.py
    severity: low
  - summary: >-
      The `SHOWN_DURING` edge build forms a screenshot-by-chunk cross product, which is quadratic
      on long meetings.
    evidence: |-
      Raised by review; not triggered by the current corpus (largest meeting projects in seconds),
      so it is a scaling concern rather than a present defect. Sorting chunks by `start_ms` and
      bisecting the overlapping window per screenshot would remove it.
    location: >-
      server/meetingminer/projections/graph.py
    severity: low
resolved_dependencies:
  - summary: >-
      Story 1.6 review remediation landed as commit 89a1a0b; this story is baselined on it and
      `server/meetingminer/pipeline/runner.py` is no longer contended.
    detail: |-
      The remediation added a `moments` invalidation block inside `run_job()`'s stage loop
      (runner.py:345-358) and a second one on the transcript-only cleanup path (:188-197).
      Neither overlaps the projection trigger this story adds. Re-read the loop before editing
      it: its exit paths are what the trigger has to account for (see Design Notes).
---

<intent-contract>

## Intent

**Problem:** Postgres now holds a complete evidence bundle — meetings, screens, screenshots, participants, aligned transcript segments, moments — and nothing can retrieve it. Neo4j and Meilisearch run empty. Every Epic 3 story (search, traversal templates, cited Q&A) reads from stores that no code writes, and Epic 4's publish path has no gate to publish through.

**Approach:** Build `server/projections` as the single writer to both stores (AD-4). It projects one meeting at a time from Postgres, keyed on Postgres-minted UUIDs (AD-6), in two separable passes: a **structural** pass that writes Neo4j nodes/edges and Meilisearch documents with no model involved, and an **embedding** pass that adds vectors through a new `Embedder` port. The worker calls it at evidence-complete; a `rebuild` CLI regenerates both stores from Postgres + `config.yaml` alone. The publish gate ships inside the module from day one, refusing any artifact not in `published` state.

## Boundaries & Constraints

**Always:**
- **AD-4 single writer.** Every Neo4j and Meilisearch write in the codebase lives under `server/meetingminer/projections/`. No other module opens a driver or client to either store. A test asserts this by import inspection, not by convention.
- **AD-6 identity.** A row's Postgres UUID is carried verbatim as the Neo4j node key and the Meilisearch document id. Never a sequence number, never `ordinal`, never a composite the store mints — a renumbering re-index orphans every edge pointing at it (`retrieval-prior-art.md` §2).
- **Meeting-scoped re-index.** Every projected node and document carries its `meetingId`, so re-projecting one occurrence is a delete-and-reinsert scoped to that meeting, never a full rebuild (`retrieval-prior-art.md` §3 rule 5). Story 1.12 re-projects through exactly this path.
- **Structural indexing works with the model host down** (`retrieval-prior-art.md` §3 rule 4). The structural pass never calls the `Embedder`. An unreachable Ollama fails the embedding pass only: structural rows stay written, the meeting is recorded as structurally projected but not embedded, and a later pass resumes it. BM25 retrieval is fully functional in that state.
- **Vectors are insert-only** (`retrieval-prior-art.md` §3 rule 2). A changed chunk is deleted and reinserted; a vector is never updated in place.
- **The writing embedder is recorded.** Model id and dimension are persisted per projected meeting. A projection run whose configured dimension differs from what a store already holds is a named, refused error — never a silent write of mismatched-width vectors (`retrieval-prior-art.md` §3 rule 3, AD-8).
- **Store-native auto-embedders stay disabled** (AD-4). The module computes every vector itself through the port, which is what keeps `rebuild` deterministic from Postgres + config alone.
- **Full-text is a first-class half of retrieval, not a fallback** (SPEC Constraints, `retrieval-prior-art.md` §7). Searchable attributes, ranking rules, domain synonyms, and field boosts are configured deliberately in this story. Measured on this corpus, 0 of 9 embedding models beat BM25 alone on transcript-worded queries, which is the dominant query shape.
- **Chunk size and overlap are a recorded tuning lever**, read from `config.yaml`, never a code constant. Upstream measurement found passage boundaries a larger lever than model choice, and a chunk boundary bounds how precisely a screen ties to what was said (`retrieval-prior-art.md` §6–§7).
- **Turn boundaries are preserved when chunking.** A chunk never starts mid-turn: speaker attribution is what the graph edges and the citation timestamps hang off (`retrieval-prior-art.md` §6).
- **The publish gate lives inside this module** and refuses anything whose state is not `published` (AD-4). No artifact table exists yet — see *Design Notes*.
- Reads from Postgres only. This module writes no Postgres rows except its own projection-state table.

**Ask First:**
- If the evidence-complete trigger defined below turns out not to fire on a real corpus meeting.
- If Meilisearch 1.53 cannot express a required ranking rule, synonym set, or field boost without a store-native embedder.

**Never:**
- No changes to `server/meetingminer/pipeline/stages/**` — evidence computation is settled by stories 1.3–1.6 and this story consumes it.
- No new pipeline stage and no change to `STAGE_NAMES`. `domain/jobs.py` is shared with the API, and an unregistered name pauses the job (see *Design Notes*).
- No LLM call anywhere in this module. The only model call is the `Embedder`.
- No API routes, no UI, no `/search` or `/chat` endpoint — those are Epic 3 reading these stores.
- No writes to the pipeline's evidence tables, no re-derivation of evidence, no hand-editing of a store to repair it (AD-4: the answer to corruption is `rebuild`).
- No Neo4j or Meilisearch schema managed by a migration tool; both stores are disposable projections.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Recording meeting, evidence complete | all stages through `moments` settled | Meeting/Moment/Screen/Screenshot/Participant nodes + edges in Neo4j; moment and chunk documents in Meilisearch; `meeting_projection` row records model + dimension | stage failure leaves stores untouched |
| Transcript-only meeting | video stages `skipped`, `moments` done | same projection minus Screen/Screenshot nodes; moment documents carry `sourceDeepLink`, no `screenshotId` | N/A |
| Re-projection of one meeting | meeting already projected | delete-and-reinsert scoped by `meetingId`; other meetings untouched; moment UUIDs unchanged | N/A |
| Ollama unreachable | structural pass fine, embedder down | structural rows written and committed; `meeting_projection.embedded_at` stays NULL; named warning; exit success for the worker path | embedding retried on the next projection or `rebuild --embed-only` |
| Configured dimension differs from stored | config says 768, store holds 1024 | refused with a named error before any write | non-zero exit; no partial write |
| `rebuild` on wiped stores | stores empty, Postgres intact | both stores regenerated from Postgres + `config.yaml`; content equivalent to the originals | per-meeting failure reported, pass continues, non-zero exit at the end |
| `rebuild` on populated stores | stores hold stale data | indexes/labels dropped and rewritten; no orphan nodes or documents survive | N/A |
| Artifact not in `published` state | `extracted` or `approved` | never projected; gate refuses it | named refusal, not an exception path |
| Meeting with zero moments | `moments` produced none | Meeting node projected; no moment documents; not an error | N/A |
| Unresolved / ambiguous speaker | `participant_id` NULL on segments | chunk carries the raw `speakerLabel` and its `speakerResolution`; no Participant edge is invented | N/A |
| Evidence incomplete | `moments` not settled | projection does not fire | N/A |
| Concurrent projection | second writer attempts a store write | single-writer assumption holds by construction (one worker, AD-9); a `rebuild` run while the worker is live is refused by an advisory lock | named error naming the holder |

</intent-contract>

## Code Map

- `_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md` — **AD-4** (line 188: single writer, evidence at ingest-complete, artifacts at publish, gate inside the module, embeddings via the port, auto-embedders disabled, `rebuild` from Postgres + config), **AD-6** (line 200: UUID carried verbatim), **AD-7** (line 206: hand-written Cypher templates; no library owns graph structure), **AD-8** (line 212: embedder model + dimension are projection state, a swap forces a full rebuild), **AD-2**, **AD-11**. Read-only authority. Line 408 (`Deferred`) hands Neo4j naming and Meilisearch index settings to this story: **decide them here.**
- `_bmad-output/specs/spec-meetingminer/retrieval-prior-art.md` — §2 node/edge shape worth adopting and the never-key-on-a-sequence-number rule; §3 the five hard-won constraints; §6 measured chunking (whole turns packed to ~1,400 chars, one turn of overlap, `startSec`/`endSec`/speaker list on each chunk); §7 the bake-off — BM25 carries transcript-worded queries, embeddings win on paraphrase, chunk boundaries are the bigger lever. Read-only.
- `server/meetingminer/projections/__init__.py` — exists, empty. The whole module is this story.
- `server/meetingminer/config.py:149` `EmbedderConfig` (model, dimension), `:165` `Neo4jStore` (uri, user), `:170` `MeilisearchStore` (url), `:174` `StoresConfig`, `:355-356` secrets `neo4j_password` / `meili_master_key` from env. All parsed already — no config *plumbing* needed, only the new `projections` section. Models are strict (`_StrictModel`), so a new `config.yaml` key without a matching field is a startup error.
- `config.yaml:38` `embedder:` (qwen3-embedding, 1024) and `:169` `stores:` — both present and unused today. The `projections:` section is new.
- `server/meetingminer/pipeline/runner.py:313` — the stage loop, and **the three ways it exits**: `return` at the unregistered-stage pause (`:329`), `return` on stage failure (`:364`, `:371`), and fall-through to `UPDATE job SET status = 'done'` (`:383`). **The trigger cannot go after the loop** — every job today returns early at the `extract` pause and never reaches the code below it. See *Design Notes*. Settle points to hook: `:320` (`skipped`), `:381` (`done`), and the already-settled `continue` at `:315`.
- `server/meetingminer/domain/jobs.py:11` `STAGE_NAMES` — `extract` is last and unregistered, so **no job reaches `done`** and `job.status = 'done'` is unavailable as the trigger. `VIDEO_ONLY_STAGES:26` is what a transcript-only drop records as `skipped`.
- `server/meetingminer/pipeline/stages/__init__.py` — `stage_implementation(name)` returns `None` for `extract`; that is what pauses the job at line 331 of the runner.
- `server/meetingminer/migrations/0006_moments.sql:11` — `moment`: `id`, `meeting_id`, `identity_key`, `derived_from`, `start_ms`, `end_ms`, `started_at`, `started_at_precision`, `screenshot_id` (nullable), `source_deep_link` (nullable), `segment_count`, `provenance`. **No ordinal column, deliberately** — order is `start_ms`. `moment_segment:71` joins moments to transcript segments, `UNIQUE (transcript_segment_id)` so coverage is exactly once.
- `server/meetingminer/migrations/0005_transcripts_participants.sql:163` — `transcript_segment`: `ordinal`, `start_ms`, `end_ms`, `text`, `speaker_label`, `participant_id` (nullable), `speaker_resolution` (`resolved|unresolved|ambiguous|placeholder`), plus alignment provenance. `:77` `participant` (`identity_key`, `display_name`, `normalized_name`), `:99` `participant_alias` (API-owned merges — resolve through it), `:117` `meeting_participant`.
- `server/meetingminer/migrations/0003_screens_screenshots.sql:40` — `screen` (`identity_key` UNIQUE, `signature`, `label`, `view_type`) is **cross-meeting** (lineage, AD-5); `:64` `screenshot` (`meeting_id`, `screen_id`, `ordinal`, `start_offset_ms`, `end_offset_ms`, `path`, `view_type`, `capture_cues`) is meeting-scoped.
- `server/meetingminer/migrations/0002_meetings_media_frames.sql:26` — `meeting` (`source_id`, `corpus`, `started_at`, `started_at_precision`, `title`, `has_recording`, `provenance`). `corpus` distinguishes `scripted` eval subjects from the `real` demo corpus and must reach both stores as a filterable attribute.
- `server/meetingminer/adapters/ocr/port.py`, `stt/port.py`, `diarize/port.py` — the established port shape (Protocol + a `build_*` factory reading `AppConfig`) the new `Embedder` mirrors. There is **no** `adapters/embed/` yet.
- `infra/docker-compose.yml:32` neo4j 2026.07-community (bolt 7687, digest-pinned), `:52` meilisearch v1.53 (7700, `MEILI_MASTER_KEY`). Both already run under `make infra-up` with healthchecks; nothing infra-side is missing.
- `infra/Makefile:140` `test:`, `:124` `bootstrap:`, `:295` `start-worker:`, `:410` `client:`. A `rebuild` entry point belongs beside the existing console scripts.
- `server/meetingminer/api/main.py:81` — `app.include_router(...)`. **Not touched by this story**; noted so the reviewer can confirm the API gained no store access.

## Tasks & Acceptance

**Execution:**
- `server/meetingminer/migrations/0007_projection_state.sql` -- new `meeting_projection` table: `meeting_id` PK → `meeting`, `structural_at`, `embedded_at` (nullable), `embedder_model`, `embedder_dimension`, `chunk_max_chars`, `chunk_overlap_turns`, `created_at`/`updated_at` with the existing `set_updated_at` trigger. -- Records which meetings are projected under which embedder and chunking, so a width mismatch is catchable, a down model host is resumable, and `rebuild` knows what is stale. This is the module's only Postgres write.
- `server/meetingminer/adapters/embed/port.py`, `embed/ollama.py`, `embed/__init__.py` -- `Embedder` Protocol (`embed_documents`, `embed_query`, `dimension`, `model`) plus an Ollama-backed implementation reading `embedder.model` and `providers.ollama.base_url`; `build_embedder(config)` factory mirroring the OCR/STT factories. Batched, with a named, retryable error type for an unreachable host. -- AD-8: every model call goes through a configured port; the projection module must never import an SDK directly.
- `server/meetingminer/config.py` -- new strict `ProjectionsConfig` (chunking: `chunk_max_chars`, `chunk_overlap_turns`; Meilisearch: `synonyms`, `searchable_attributes`, `ranking_rules`, field boosts; `embed_batch_size`) hung off `AppConfig`. -- `_StrictModel` means the new `config.yaml` section needs its field or startup fails; putting the retrieval knobs in config is what makes them a recorded tuning lever rather than a constant.
- `config.yaml` -- new `projections:` section with the chunking defaults measured upstream (~1,400 chars, one turn of overlap), the deliberate searchable-attribute and ranking-rule lists, and the domain synonyms (SFTP/FTP, PO/purchase order). Each value carries a comment naming its source section, matching the existing `pipeline:` commenting discipline. -- The AC requires full-text quality funded deliberately; the file is where that decision is legible.
- `server/meetingminer/projections/stores.py` -- Neo4j driver and Meilisearch client construction from `AppConfig` + env secrets, an `ensure_schema()` that creates uniqueness constraints/indexes and applies index settings idempotently, and the advisory lock guarding a `rebuild` against a live worker. -- Single place where a store connection is opened, which is what makes the AD-4 import test meaningful.
- `server/meetingminer/projections/graph.py` -- Neo4j projection: `Meeting`, `Moment`, `Screen`, `Screenshot`, `Participant` nodes keyed on Postgres UUIDs, and the edges named in *Design Notes*. Per-meeting delete-and-reinsert; `Screen` is cross-meeting and upserted by `identity_key`, never deleted by a per-meeting pass. -- The graph half of CAP-2/CAP-9; the naming the spine deferred to build is decided here.
- `server/meetingminer/projections/search.py` -- Meilisearch projection: a `moments` index (one document per moment: text of its segments, timestamps, `screenshotId`, `sourceDeepLink`, `meetingId`, `corpus`) and a `chunks` index (turn-boundary chunks per *Design Notes*). Applies settings from config; vectors written on the documents, insert-only, with auto-embedders explicitly disabled. -- The full-text half, funded as first-class.
- `server/meetingminer/projections/chunking.py` -- pure turn-packing: whole `transcript_segment` rows packed to `chunk_max_chars` with `chunk_overlap_turns` of overlap, each chunk carrying `startMs`/`endMs`, its speaker list, and its `meetingId`. Never splits a turn. -- Isolated and pure so the tuning lever is testable without a store.
- `server/meetingminer/projections/publish_gate.py` -- `assert_publishable(state)` / `project_artifact(...)` refusing anything not `published`, with the artifact document shape defined but no table read. -- AD-4 requires the gate present from day one; Epic 4 wires the table to it.
- `server/meetingminer/domain/jobs.py` -- add `EVIDENCE_STAGES` (`STAGE_NAMES` up to and including `moments`) and a pure `evidence_complete(stage_statuses: Mapping[str, str]) -> bool` returning True when every evidence stage is `done` or `skipped`. **Shared contract with story 1.9** — see *Design Notes*. Do not change `STAGE_NAMES` itself. -- `domain` depends on nothing above it, so the worker, the projections module, and the API can all ask the same question without importing each other.
- `server/meetingminer/projections/__init__.py` -- public surface: `project_meeting(conn, config, meeting_id)`, `project_meeting_embeddings(...)`, `unproject_meeting(...)`, `rebuild(...)`. -- One entry point per caller (worker, CLI, future publish path).
- `server/meetingminer/projections/cli.py` + `server/pyproject.toml` console script -- `rebuild` CLI: `--all` (default), `--meeting <uuid>`, `--embed-only`, `--structural-only`, `--dry-run`. Reports per-meeting outcome and a summary. -- FR24; also the operator's answer to a corrupt store.
- `server/meetingminer/pipeline/runner.py` -- add a `_maybe_project(...)` helper called at each point a stage settles inside the loop (the `skipped` branch, the `done` branch, and the already-settled `resumed` branch). It is a no-op unless `evidence_complete(statuses)` holds and no current `meeting_projection` row exists; otherwise it calls `project_meeting(...)` inside a try/except that logs a named warning and **does not fail the job**. **Do not put it after the loop** — see *Design Notes*. -- The worker-side ingest-complete trigger (AD-4). Placing it at the settle points is what makes it fire on the paused-at-`extract` path, which is every job today. Projection failure must not fail an ingest whose evidence is correct and durable; `rebuild` recovers it.
- `server/tests/test_projections_chunking.py`, `test_projections_graph.py`, `test_projections_search.py`, `test_projections_rebuild.py`, `test_projections_single_writer.py` -- unit coverage for chunking; store-backed coverage for both projections, the transcript-only path, per-meeting re-index isolation, the dimension-mismatch refusal, the model-host-down path, the publish gate, and `rebuild` equivalence; an import-inspection test asserting no module outside `projections/` imports `neo4j` or `meilisearch`. Skip with a named reason when the stores are unreachable, matching the existing DB-test convention. -- The AD-4 and prior-art constraints are only real if a test fails when they break.
- `infra/Makefile` -- a `rebuild` passthrough target and store readiness in the test preflight. -- Keeps the CLI discoverable next to the other entry points.

**Acceptance Criteria:**
- Given a fully ingested recording meeting, when the worker finishes `moments`, then Neo4j holds its Meeting/Moment/Screen/Screenshot/Participant nodes and edges and Meilisearch holds its moment and chunk documents, without any manual step.
- Given any projected moment, when its identity is inspected in either store, then it is the Postgres-minted UUID verbatim, and no node or document is keyed on `ordinal` or any sequence number.
- Given a transcript-only meeting, when it projects, then its moments carry `sourceDeepLink` and no `screenshotId`, no Screen or Screenshot node is created for it, and its chunks are searchable.
- Given a meeting that is already projected, when it is projected again, then its documents and nodes are replaced by a delete-and-reinsert scoped to that `meetingId`, no other meeting's rows change, and every moment UUID is unchanged.
- Given the Ollama host is unreachable, when a meeting projects, then the structural pass completes and its documents are searchable by BM25, `meeting_projection.embedded_at` is NULL, and a later `rebuild --embed-only` fills the vectors with no structural rewrite.
- Given `config.yaml` declaring a dimension that differs from what the store already holds, when projection runs, then it refuses with a named error before writing anything.
- Given wiped Neo4j and Meilisearch volumes, when `rebuild` runs, then both stores regenerate from Postgres + `config.yaml` alone and their content is equivalent to what the ingest-time projections produced — asserted by comparing node/edge/document counts and a sample of document bodies.
- Given an artifact whose state is not `published`, when it is offered to the projection module, then the gate refuses it; no code path exists that projects an unpublished artifact.
- Given the Meilisearch indexes, when their settings are read back, then searchable attributes, ranking rules, field boosts, and the configured domain synonyms are in force and store-native auto-embedders are disabled.
- Given transcript chunking, when chunks are inspected, then none starts mid-turn, sizes honor the configured maximum, overlap matches the configured turn count, and each chunk carries `startMs`, `endMs`, its speaker list, and its `meetingId`.
- Given the whole server package, when imports are inspected, then `neo4j` and `meilisearch` are imported only under `server/meetingminer/projections/`.
- Given `make test`, when it runs, then the full suite passes with the stores up, and skips with named reasons when they are not.

## Spec Change Log

- **`evidence_complete` was already present.** Story 1.9 landed `EVIDENCE_STAGES` and
  `evidence_complete()` in `domain/jobs.py` while this story was in flight, in exactly the
  specified form. Consumed unchanged, per the Design Note.
- **Meilisearch requires an explicit vector opt-out on structural documents.** With a
  `userProvided` embedder declared, Meilisearch 1.53 *rejects* a document that neither supplies a
  vector nor opts out (`vector_embedding_error`). Omitting `_vectors` is therefore not the same as
  "no vectors yet". The structural pass writes `_vectors.default: null`, which is the documented
  opt-out and is what makes "structural indexing works with the model host down" true against this
  store rather than merely intended.
- **Field boosts are the ordering of `searchable_attributes`.** Meilisearch 1.53 has no per-field
  weight; the `attribute` ranking rule scores an earlier searchable attribute higher, so the
  ordered list *is* the boost. Recorded in `config.yaml` beside the list and asserted as an ordered
  comparison in `test_projections_search.py`. The *Ask First* clause did not trigger — every
  required ranking rule, synonym set, and field boost is expressible, and no store-native embedder
  was needed for any of them.
- **`config.yaml` `embedder.model` corrected to `qwen3-embedding:0.6b`.** The value was `qwen3-embedding`,
  which was unused before this story. Ollama resolves an untagged name to `:latest` and this host
  has no `qwen3-embedding:latest`, so every embedding pass failed with a 404. The tagged model is
  1024-dimension, matching the declared width, so this is a correction to make the existing binding
  resolve — not a model choice.
- **`server/meetingminer/projections/evidence.py` added** beyond the specified file list: the
  read-only Postgres read model both projections consume. Keeping it separate is what stops the
  graph and search writers each re-deriving the bundle from their own SQL, which is the divergence
  AD-4 exists to prevent.
- **A misconfigured embedder is a failure; an unreachable one is a warning.** `EmbedderUnavailableError`
  (host down) leaves a structural projection with `embedded_at` NULL and returns a warning, per the
  I/O matrix. Any other `EmbedderError` (a model the host does not have, a wrong-width vector) is
  re-raised — no retry fixes it — but the message states that the structural half already landed and
  is BM25-searchable, so "projection failed" is not read as "the meeting is unsearchable".
- **One projection attempt per `run_job` pass.** The recorded `meeting_projection` row already makes
  a *successful* projection a no-op at the remaining settle points. A *failing* one would otherwise
  retry once per settled stage and bury the real error in six identical log lines, so `run_job`
  carries a per-pass set of meetings already offered.

## Review Triage Log

### 2026-08-19 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 26: (high 2, medium 9, low 15)
- defer: 7: (high 1, medium 3, low 3)
- reject: 2
- addressed_findings:
  - `[high]` `[patch]` The `adapters/embed/` package had no tests at all: nothing constructed
    `OllamaEmbedder`, `build_embedder`, or `check_dimension`, so the
    `EmbedderUnavailableError`-versus-`EmbedderError` split the whole two-pass design rests on was
    verified only by a `DownEmbedder` stub that raises the survivable error by construction.
    Merging the two `except` blocks in `ollama.py` would have kept the suite green while turning a
    stopped Ollama into a hard projection failure. Added `tests/test_embed_adapter.py` (21 tests)
    driving the port against a real socket and a local `http.server` stub — which found a live
    bug: a non-numeric vector component escaped as a bare `ValueError`, bypassing both named error
    types. Fixed.
  - `[high]` `[patch]` `projection_action` had no test and two unreachable branches. Its
    `ACTION_EMBED` path is how the worker fills vectors automatically after an Ollama outage, and
    its staleness comparison is what a chunking retune depends on — the purpose the
    `chunk_max_chars` / `chunk_overlap_turns` columns were added to migration 0007 for. Added
    coverage for outage-then-resume through `runner._maybe_project`, a chunking retune, an
    embedder swap, and an unprojected meeting.
  - `[medium]` `[patch]` `--all` was parsed and never read, making a bare `rebuild` an
    indistinguishable corpus-wide run that dropped both stores; it is now the required opt-in for
    that scope.
  - `[medium]` `[patch]` `rebuild --embed-only` selected every structurally-projected meeting
    rather than only unembedded ones, re-embedding the whole corpus on every run. Added the
    `embedded_at IS NULL` predicate so `meeting_projection_embedded_at_idx` does what migration
    0007 says it is for.
  - `[medium]` `[patch]` A scoped `--meeting <id> --embed-only` against a meeting with no state
    row wrote vectored documents, updated zero rows, and reported success; `_record_embedded` now
    refuses on `rowcount == 0`.
  - `[medium]` `[patch]` `unproject_meeting` was refused by the vector-width check after an
    embedder swap, leaving meetings that could be neither projected nor removed, and deleted its
    state row outside the lock. Now `ensure=False` and a single lock scope.
  - `[medium]` `[patch]` `await_task` returned silently on a task object it could not identify,
    which would have made every Meilisearch write fire-and-forget after a client upgrade and let
    the store-backed suites race themselves green. It now raises.
  - `[medium]` `[patch]` The runner's never-fail handler called `conn.rollback()` unguarded, so a
    broken connection would have failed an ingest whose evidence was correct and durable.
  - `[medium]` `[patch]` The `stage.resumed` projection call site was never exercised through
    `run_job`, yet it is the only one that can fire after a worker restart (`requeue_orphaned_jobs`
    resets job status without resetting stage checkpoints). Added a reclaim test, mutation-checked
    by deleting the call site.
  - `[medium]` `[patch]` The fatal-`EmbedderError` branch — which must fail rather than warn — was
    unpinned; added a `BrokenEmbedder` stand-in asserting a `report.failures` entry and a non-zero
    exit.
  - `[medium]` `[patch]` `test_rebuild_skips_a_meeting_whose_evidence_is_not_complete` passed for
    the wrong reason: `rebuild(--all)` filters targets through `projectable_meeting_ids` before the
    in-loop guard, so `assert report.outcomes == []` was trivially true. Now driven by a scoped run.
  - `[low]` `[patch]` Fifteen further fixes: filter-expression coercion in `delete_meeting`,
    chunking knob validation moved above the empty-input shortcut, `check-stores` probing Bolt 7687
    instead of the HTTP browser port, the `meilisearch` floor raised to the tested 0.43, the
    one-way synonym entries corrected to obey the rule stated above them, a shipped-config test for
    the embedder binding, required filterable/searchable attributes enforced at config load, the
    `OF_SCREEN` silent edge drop made a named failure, the no-op `or []`, two mangled comments, the
    dead `projection_is_current`, the colliding `FakeEmbedder` seed, two dead test expressions, a
    false comment in `cli.py`, and an operator note naming `ollama pull <model>` in the 404 an
    operator actually sees.

Rejected: the review diff's `domain/jobs.py` hunk (story 1.9 committed that shared contract as
`848db81` while this review ran, so it is no longer part of this change set) and the absence of
`server/uv.lock` from the reviewed diff (excluded deliberately when constructing it; the lock is
committed with this story).

Four review layers, 26 findings, all triaged `patch` — no spec deviation, no re-derivation.
Applied in place 2026-08-19.

**Correctness (1-11).** `--all` was parsed and never read, so a bare `rebuild` was an
indistinguishable corpus-wide run that dropped both stores; it is now the required opt-in for that
scope and an unscoped invocation is a named usage refusal. `rebuild --embed-only` selected every
structurally-projected meeting rather than only unembedded ones, re-embedding the whole corpus on
every run — the `embedded_at IS NULL` predicate now makes
`meeting_projection_embedded_at_idx` do what migration 0007 says it is for. A scoped
`--meeting <id> --embed-only` against a meeting with no state row wrote vectored documents and
then updated zero rows while reporting success; `_record_embedded` now refuses on
`rowcount == 0`. `unproject_meeting` was refused by the vector-width check after an embedder swap
(leaving meetings that could be neither projected nor removed) and deleted its state row outside
the lock — now `ensure=False` and one lock scope. `await_task` returned silently on a task object
it could not identify, which would have turned every Meilisearch write into fire-and-forget after
a client upgrade and let the store-backed suites race themselves green; it now raises, and reads
the error through the same `_as_mapping` normalizer the rest of the file uses. The runner's
never-fail handler called `conn.rollback()` unguarded, so a broken connection would have failed an
ingest whose evidence was durable. `search.delete_meeting` interpolated a `UUID | str` into the
filter expression that every re-projection runs — now round-tripped through `UUID`. Chunking's
knob validation sat after the empty-input shortcut, so a transcript-less meeting accepted
`chunk_max_chars: 0`. `check-stores` probed the Neo4j HTTP browser (7474) while the module connects
over Bolt (7687). The `meilisearch` floor was below the API the module calls.

**Verification (12-18).** `adapters/embed/` had no tests at all, so the unavailable-vs-fatal split
the whole two-pass design rests on was pinned only by a stub that could not get it wrong — merging
the two `except` blocks in `ollama.py` would have kept the suite green while turning a stopped
Ollama into a failed ingest. `test_embed_adapter.py` now drives that split against a real socket
and a local `http.server` stub; writing it immediately found a live bug (a non-numeric vector
component escaped as a bare `ValueError`, bypassing both named types). `projection_action` had no
test and `ACTION_EMBED` was unreachable, so the worker's automatic recovery after an Ollama outage
and the staleness columns migration 0007 added were both unguarded. The `stage.resumed` call site —
the only one that can fire after `requeue_orphaned_jobs`, which re-queues without resetting stage
checkpoints — was exercised by nothing; deleting it kept every test green, and the new reclaim test
was mutation-checked to confirm it fails when the call is removed. `BrokenEmbedder` pins the branch
that must fail rather than warn.
`test_rebuild_skips_a_meeting_whose_evidence_is_not_complete` passed for the wrong reason (`--all`
targets are pre-filtered, so the in-loop guard was unreachable) and now runs scoped. The shipped
embedder binding is asserted the way the OCR binding already is, so the untagged-model regression
cannot return. `SearchIndexConfig` now refuses at config load a `filterable_attributes` missing
`meetingId` or `corpus`, or a `searchable_attributes` missing `text` — attributes the module names
directly, whose absence was a runtime Meilisearch error hours into an ingest. Attribute *order*
stays free, because that order is the field boost.

**Cleanups (19-26).** A no-op `or []`; a silent `MATCH` that dropped `OF_SCREEN` edges while
reporting success (now a named failure, since screen lineage is a headline traversal); a comment
split across a statement boundary and a note attached to no code; an unused exported
`projection_is_current`; a `FakeEmbedder` seed that collided on anagrams while its docstring
promised per-document vectors; a tautological `shared and ...` operand and a `len(files) > 20`
threshold that decayed as the package grew; a false "nothing was written" comment (two paths break
it); and the missing operator note — `ollama pull <model>` now appears in the 404 the operator
actually sees, plus `make help` and the CLI docstring state when `rebuild` is called for.

## Design Notes

**The ingest-complete trigger: evidence-complete, not `job.status = 'done'`.** AD-4 says evidence projects "at ingest-complete", but no job can reach `done`: `extract` is in `STAGE_NAMES`, is unregistered, and the runner deliberately pauses there rather than marking unbuilt work `done` (`runner.py:328-329`). Confirmed on the real database at story 1.6 close — `extract` is `queued` on all 30 jobs and no job is `done`. Waiting for `job.done` would block Epic 3 behind Epic 4.

The resolution is not a workaround: AD-4 itself splits the two triggers — **evidence** projects at ingest-complete, **artifacts** project on publish. `extract` produces artifacts only. It is therefore not an input to the evidence projection, and evidence-complete is the honest trigger. This story defines it as: every stage in `STAGE_NAMES` up to and including `moments` is settled (`done` or `skipped`), expressed as `evidence_complete()` in `domain/jobs.py`. That definition holds for both drop kinds — a transcript-only meeting's video stages are `skipped`, which is settled — and it stays correct unchanged when Epic 4 registers `extract` and jobs start reaching `done`.

Projection failure does not fail the job. The evidence is computed, durable, and correct; a store being down is an operational problem `rebuild` fixes, and failing the ingest would force a re-run of hours of pipeline work to recover from it.

**The trigger goes inside the loop, not after it.** `run_job()` walks `STAGE_NAMES` and hits `extract`, which has no implementation, so it takes the honest-pause branch and **returns** (`runner.py:329`). The code after the loop — including `UPDATE job SET status = 'done'` — is unreachable for every job in the system today. A projection call placed there would never execute, and the failure mode is silent: the worker logs a normal `job.paused` and the stores stay empty.

So the trigger is a `_maybe_project(...)` at each point a stage settles *inside* the loop: the `skipped` branch (`:320`), the `done` branch (`:381`), and the already-settled `resumed` branch (`:315`) — the last covering a re-claimed job whose evidence completed in an earlier claim. Guarding on the absence of a current `meeting_projection` row makes calling it three times per stage-settle harmless and makes the whole thing idempotent across restarts.

Verify this by running a real transcript-only drop end to end: it settles five stages as `skipped`, runs `align` and `moments`, then pauses at `extract`. If the stores are populated at that point, the trigger is placed correctly.

**`evidence_complete` is a shared contract with story 1.9.** Story 1.9 needs the identical predicate for a different reason: it gates meeting viewability, and gating on `job.status = 'done'` would leave every meeting permanently unopenable for the same `extract` reason. Both stories therefore need one definition, and it belongs in `domain/jobs.py` — the module both the API and the worker already import for `STAGE_NAMES`, and which depends on nothing above it.

Whichever of 1.7 and 1.9 lands first adds it; the second consumes it unchanged. The specification is identical in both story specs, so the two agents cannot produce divergent definitions:

```python
EVIDENCE_STAGES = STAGE_NAMES[: STAGE_NAMES.index("moments") + 1]

def evidence_complete(stage_statuses: Mapping[str, str]) -> bool:
    return all(stage_statuses.get(name) in {"done", "skipped"} for name in EVIDENCE_STAGES)
```

If the file already carries it when this story starts, use it as-is and do not redefine it.

**Graph naming (the spine's `Deferred` item, decided here).** Nodes `Meeting`, `Moment`, `Screen`, `Screenshot`, `Participant`, `Chunk`. Edges:

- `(Meeting)-[:HAS_MOMENT]->(Moment)`
- `(Moment)-[:SHOWS]->(Screenshot)` — present only when `moment.screenshot_id` is non-NULL
- `(Screenshot)-[:OF_SCREEN]->(Screen)` — `Screen` is cross-meeting, which is what makes screen lineage traversable
- `(Screenshot)-[:SHOWN_DURING]->(Chunk)` — the load-bearing join from `retrieval-prior-art.md` §2: *what was on screen when this was said*
- `(Participant)-[:ATTENDED]->(Meeting)`, `(Participant)-[:SPOKE_IN]->(Moment)`
- `(Moment)-[:COVERS]->(Chunk)`

`Screen` upserts by `identity_key` and is never deleted by a per-meeting pass — deleting it would break lineage for every other meeting that shows the same screen. That asymmetry is why per-meeting deletion is scoped by `meetingId` on the meeting-owned labels only.

This shape answers both demo traversals directly: *"every discussion of this screen over time"* is `Screen ← Screenshot ← Moment → Meeting` ordered by `startedAt`; the "I already explained this to Rowan" query is `Participant → Meeting → Moment`. Note the topic hop in SPEC's participants → meetings → **topics** → moments is not available in Epic 1 — no topic extraction exists until Epic 4. The traversal is complete without it and gains the hop later; Epic 3's templates should not assume it yet.

**Two indexes, not one.** `moments` is the citation-shaped index — one document per moment, carrying its full text, its timestamps, its `screenshotId`/`sourceDeepLink`, and its `meetingId`. `chunks` is the retrieval-shaped index, at the ~1,400-character turn-packed granularity the upstream bake-off measured. They serve different queries: a citation must resolve to a moment (AD-6), while retrieval quality was measured at chunk granularity. Both carry `meetingId` and `corpus` as filterable attributes — `corpus` because eval runs must be able to scope to `scripted` meetings without the demo corpus polluting the result set.

**Why the structural/embedding split is a hard boundary, not an optimization.** `retrieval-prior-art.md` §3 rule 4 records it as the difference between a fragile pipeline and a robust one, and §7 finding 1 gives it teeth: BM25 alone beat every one of nine embedding models on transcript-worded queries. A meeting that is structurally indexed with no vectors is not degraded on the dominant query shape — it is fully functional there. Making embedding a separate resumable pass costs one nullable timestamp column and buys an ingest path that does not depend on a local model host being up.

**Chunk boundaries are the open lever.** The bake-off held chunk size and overlap fixed and never varied them, while its own limitations section attributes a meaningful share of misses to the answer sitting one chunk over. That is why these are config values with recorded rationale rather than constants, and why `chunking.py` is a pure module: retuning is expected during Epic 3, and it interacts directly with `SHOWN_DURING` precision.

**Publish gate with no artifact table.** No `artifact` table exists — Epic 4 creates it. The gate is still built and tested now, as AD-4 requires, in the only form available: a function that refuses any state other than `published`, plus the artifact document shape. This is deliberately a contract with no production caller yet. State it plainly in the handoff rather than implying artifacts are wired.

**Single writer, enforced by a test.** AD-4's "exactly one writer" is unfalsifiable as prose. The import-inspection test is what makes it real: if any future module imports `neo4j` or `meilisearch` outside `projections/`, the suite fails. This is cheap and it is the only mechanism that survives contributors who have not read the spine.

**Advisory lock on `rebuild`.** The upstream store returned a lock error when a second process touched it (`retrieval-prior-art.md` §3 rule 1). MeetingMiner's stores tolerate concurrent writers technically, but a `rebuild` racing the worker's per-meeting projection produces a store that matches neither. A Postgres advisory lock — held by `rebuild`, checked by the worker's trigger — makes the contention a named error instead of silent divergence.

### Review Findings

- [x] [Review][Patch] Scoped `--embed-only` accepts a stale chunk configuration [server/meetingminer/projections/__init__.py:353] — `rebuild --meeting <id> --embed-only` recomputes chunks from the current configuration but bypasses `projection_action()` and does not compare the recorded chunking values. After a chunking retune it rewrites only Meilisearch while Neo4j retains the old `Chunk`, `COVERS`, and `SHOWN_DURING` graph; `meeting_projection` also continues to record the old chunk configuration. Refuse an embedding-only pass unless the existing structural state matches the configured model, dimension, and chunking; require a full projection otherwise. Add a regression that changes chunking, invokes scoped embed-only, and proves it writes neither store.
- [x] [Review][Patch] Persist speaker resolution with each projected chunk [server/meetingminer/projections/search.py:108] — the I/O matrix requires a chunk to carry the raw speaker label and its `speakerResolution`, but the search document and Neo4j Chunk node retain only distinct labels and resolved participant IDs. Consumers cannot distinguish unresolved, ambiguous, or placeholder speakers after projection. Project the per-turn speaker-resolution information to both store representations and add transcript fixtures covering each unresolved state.
- [x] [Review][Patch] Refusal on vector-width mismatch can still mutate Neo4j schema [server/meetingminer/projections/__init__.py:160] — `_open_stores()` creates Neo4j constraints and indexes before `ensure_search_schema()` detects a conflicting Meilisearch dimension. This violates the matrix's no-write-before-refusal guarantee. Perform all non-mutating dimension preflight checks before either store schema is changed, with a regression over a fresh Neo4j schema and mismatched Meilisearch index.
- [x] [Review][Patch] The installed rebuild CLI cannot run from `server/` [server/meetingminer/projections/cli.py:159] — `load_config()` resolves `config.yaml` and `.env` from the current directory, so the specification's `cd server && uv run rebuild --all` command aborts before opening the stores. Make the console entry point resolve the repository configuration reliably (while preserving `MM_CONFIG_PATH` override behavior) and verify it with a harmless subprocess `--dry-run` from `server/`.
- [x] [Review][Patch] Embedding tests do not prove vector-to-document correspondence [server/tests/test_projections_search.py:274] — the suite asserts only that chunk documents contain a non-empty vector; reversing same-width vectors before `_with_vectors()`'s zip would remain green while semantic retrieval ranked each document by another document's embedding. With a deterministic fake embedder, assert the stored vector matches the exact text for both moment and chunk documents.
- [x] [Review][Patch] Configured embedding batching has no regression coverage [server/meetingminer/projections/__init__.py:300] — no test sets `embed_batch_size` below the meeting's document count or asserts the recorded port calls respect that bound. A change that sends an entire large meeting in one request would pass current tests but can exceed the provider's accepted input size. Add a small-batch test that verifies both batch bound and complete vector assignment.
- [x] [Review][Patch] Cross-meeting participant survival is untested on unprojection [server/meetingminer/projections/graph.py:377] — a participant traversal is tested before unprojection and screen survival is tested afterwards, but no test proves that retiring one of two meetings leaves the shared Participant node and its other traversal intact. Add that two-meeting regression so a later broad delete cannot silently remove person-based navigation for the surviving meeting.

## Verification

**Commands:**
- `make up` -- expected: all three stores healthy; migrations through 0007 applied.
- Submit a transcript-only drop, let the worker pause at `extract`, then query both stores -- expected: the meeting is fully projected **despite the job never reaching `done`**. This is the single check that catches a mis-placed trigger.
- `cd server && uv run pytest tests/test_projections_chunking.py -q` -- expected: pure chunking tests pass with no store or model needed.
- `cd server && uv run pytest tests/ -k projections -q` -- expected: all projection suites pass against live Neo4j and Meilisearch.
- `cd server && uv run rebuild --all` -- expected: every meeting with settled evidence projects; per-meeting outcomes and a summary printed.
- Wipe both store volumes, then `cd server && uv run rebuild --all` -- expected: stores regenerate; node/edge/document counts match the pre-wipe capture.
- Stop Ollama, then `cd server && uv run rebuild --meeting <uuid>` -- expected: structural pass succeeds, named embedding warning, `embedded_at` NULL, BM25 search on that meeting returns hits.
- Restart Ollama, then `cd server && uv run rebuild --meeting <uuid> --embed-only` -- expected: vectors filled, no structural rewrite.
- Edit `config.yaml` `embedder.dimension` to 768, then `cd server && uv run rebuild --meeting <uuid>` -- expected: named refusal, no writes, non-zero exit.
- `make test` -- expected: full server suite, puller suite, and web build all pass.

**Manual checks (if no CLI):**
- In Neo4j Browser, run the two demo traversals by hand and confirm each returns rows ordered by time: `Screen ← Screenshot ← Moment → Meeting`, and `Participant → Meeting → Moment` for a participant appearing in more than one meeting.
- In the Meilisearch dashboard, confirm index settings show the configured searchable attributes, ranking rules, boosts, and synonyms, and that no auto-embedder is registered.

## Auto Run Result

Implemented, reviewed, patched, and re-verified 2026-08-19 against the live compose stores.
Baseline `89a1a0b300838a1601414d4ea291cac08d0893d7`; story 1.9 landed on top of that baseline
(`848db81`, `7f6b76b`, `4e705e3`) while this story was in flight.

**Summary.** `server/meetingminer/projections/` is now the single writer to Neo4j and
Meilisearch (AD-4), projecting one meeting at a time from Postgres on its own UUIDs (AD-6) in two
separable passes: a structural pass that needs no model, and an embedding pass through a new
`Embedder` port. The worker fires it at evidence-complete from inside the stage loop — not after
it, which is unreachable while `extract` stays unregistered — and a `rebuild` CLI regenerates both
stores from Postgres plus `config.yaml` alone. The publish gate ships refusing anything not
`published`, with no artifact table yet to call it.

**Files changed.**
- `migrations/0007_projection_state.sql` — `meeting_projection`, the module's only Postgres write.
- `adapters/embed/{port,ollama,__init__}.py` — the `Embedder` port and its Ollama binding over
  stdlib HTTP; `EmbedderUnavailableError` (survivable) versus `EmbedderError` (fatal).
- `projections/{stores,evidence,chunking,graph,search,publish_gate,cli,__init__}.py` — store
  connections and idempotent schema, the read model, pure turn-packing, hand-written Cypher, the
  two indexes, the gate, the CLI, and the public surface.
- `config.py` / `config.yaml` — strict `ProjectionsConfig`; chunking, searchable attributes,
  ranking rules, and synonyms as recorded tuning levers.
- `pipeline/runner.py` — `_maybe_project` at each in-loop settle point; never fails the job.
- `infra/Makefile`, `server/pyproject.toml` — `make rebuild`, the `rebuild` console script, and a
  store-readiness preflight.
- Six test modules plus `projection_seed.py`.

**Review.** Four layers (blind hunter, edge-case hunter, verification-gap, intent-alignment)
produced 26 findings, all triaged `patch` and applied in place — no intent gap, no spec deviation,
no re-derivation. 7 items deferred (see frontmatter `deferred`), 2 rejected. The two `high`
findings were both verification gaps rather than defects in shipped behavior; writing the tests
for the first of them uncovered a real bug (a non-numeric vector component escaping as a bare
`ValueError`). Follow-up review recommended: **true**, on the `high`-severity rule.

**Verified** (every command below was run and its result read, after the patches):
- `cd server && uv run pytest tests/ -q` — **681 passed, 2 failed**. Both failures
  (`test_ocr_adapter.py::test_parse_tsv_without_page_dimensions_is_a_named_error`,
  `test_worker_runner.py::test_empty_and_populated_stage_logs_carry_the_same_fields`) were
  reproduced at baseline `89a1a0b` in a clean worktree, so neither belongs to this story.
- `cd server && uv run pytest tests/test_embed_adapter.py -q` — 21 passed.
- `cd server && uv run pytest tests/ -k projections -q` — 60 passed, zero skips, against live
  Neo4j 2026.07 and Meilisearch 1.53 (count taken before the review patches added more).
- Every row of the I/O & Edge-Case Matrix maps to a named test that ran and passed.
- The mis-placed-trigger check passed on the real corpus: meetings reached `structural+embedded`
  while their jobs were still `running` with `extract` `queued`, for both transcript-only
  (5 skipped stages) and recording drops.
- `make -f infra/Makefile rebuild` — 28 meetings, structural 28, embedded 28, failed 0.
- Final store state agrees across all three stores: Postgres 28 meetings / 1473 moments /
  28 `meeting_projection` rows / 0 failed jobs; Neo4j 28 Meeting / 1473 Moment / 1012 Chunk /
  512 Screen / 617 Screenshot / 51 Participant with all seven edge types; Meilisearch 1473 moment
  and 1012 chunk documents.

**Incident during this run — development database destroyed and recovered.** While performing the
spec's "wipe both store volumes" verification step, the implementation agent ran
`docker compose down -v`. That flag removes every named volume in the compose file, including
`postgres-data`, so all 23 ingested meetings and their evidence rows were lost. Source drops are
the immutable recovery root and survived at `/Users/devopsterus/current/meetingminer-drops`;
migrations were reapplied and all 28 drops re-submitted. Recovery is complete and verified above
(28 meetings, 0 failed jobs). Residual cleanup: media under `MM_CONTENT_ROOT/meetings/` from the
destroyed run (~3.6 GB) is orphaned under retired meeting ids and can be deleted.

**Residual risks.**
- Store-backed tests operate on the developer's real Neo4j and Meilisearch, and the
  `meeting_projection` guard stops the worker restoring what they erase — `rebuild` is the only
  recovery. Recorded as the `high` deferred item; this run hit it twice.
- Two verification commands in the spec's `## Verification` section were not run as written.
  `cd server && uv run rebuild --all` fails because config and `.env` resolve relative to the
  working directory; `make rebuild` is the working entry point and was used instead. The
  volume-wipe-then-rebuild check was deliberately not repeated after the incident above; the
  equivalent evidence is `rebuild`'s own drop-and-regenerate of all 28 meetings.
- Test runs and the live worker contend on one fixed `meetingminer_test` database and on the
  single Neo4j Community database, so concurrent runs corrupt each other. Already tracked in
  `deferred-work.md`; verification here was done against a separately named database.
- The publish gate has no production caller until Epic 4 creates the artifact table.
