---
title: 'Story 4-4: Published Artifacts Become Citable Knowledge'
type: 'feature'
created: '2026-08-21'
status: 'done'
baseline_revision: '2d9705fb286098f9af08e2724d0106052244bc0f'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-4-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-4-3-per-moment-approval-publishing.md'
warnings: [oversized]
deferred: []
---

<intent-contract>

## Intent

**Problem:** Publishing (story 4-3) advances artifacts to `published` in Postgres and exports them, but nothing projects them into Neo4j or Meilisearch: `publish_gate.project_artifact` has no production caller, the `artifacts` index is never created, no Artifact graph node exists, and eval check 2.11's post-approval half fails by design ("projection-on-publish is not wired — story 4-4 backlog"). Published knowledge is invisible to search and chat.

**Approach:** Wire artifact projection through the projections module: a locked entrypoint projects `published` artifacts into the Meilisearch `artifacts` index and Neo4j `Artifact` nodes with a `CITES` edge to the source moment. The approve route calls it after its transaction commits; per-meeting projection and `rebuild` re-project published artifacts (and only those). The query layer gains an artifacts lane so corpus search and chat surface them, each hit resolved through its source moment so the evidence trail replays that moment. This flips eval check 2.11's post-approval half from expected-fail to required-pass.

## Boundaries & Constraints

**Always:**
- The API never imports `neo4j`/`meilisearch` — every store write/read goes through `meetingminer.projections` (enforced by `server/tests/test_projections_single_writer.py:101`).
- The publish gate runs before any client is touched, regardless of caller: `assert_publishable` on every artifact projected, and the Postgres read that feeds projection selects `WHERE state = 'published'` (defense in depth; index `artifact_meeting_state_idx` exists).
- The eval harness redeclares the contract by hand (AD-16) — these are frozen: index name literally `"artifacts"`, document id = artifact UUID, source moments in a `momentIds` field (`evals/harness/stores.py:38-50`); graph node keyed on the artifact UUID as `id` and adjacent (either direction) to a `:Moment` node (`evals/harness/stores.py:53`). The existing `artifact_document()` shape (`id/meetingId/corpus/kind/state/title/text/momentIds`) already satisfies this — keep it.
- Any store write takes `store_file_lock` then `projection_lock`, like the four existing entrypoints — this retires the deferred defect at `deferred-work.md:145-149`.
- `Artifact` becomes a meeting-scoped graph label and artifact documents carry `meetingId`, so per-meeting delete/re-project (worker settle points, augmenting re-ingest, `rebuild`) deletes and re-creates them from Postgres. Postgres stays authoritative; augment preserves moment ids, so `CITES` edges re-resolve.
- Chat citations stay moment-typed: the six-field `CitationModel` (`api/chat.py:223`) and the `[[moment:…]]` grammar in `api/citations.py` are untouched. An artifact retrieval hit contributes its source moment id(s) into the retrieved set, and its title/body enter that moment's context block, labeled as a published artifact.
- Search hits are re-read from Postgres in the request (AD-2/AD-6): an artifact hit resolves through `artifact JOIN moment JOIN meeting`, its replay fields (`start_ms`, `has_recording`, `source_deep_link`, `screenshot_id`) coming from the source moment; a hit whose artifact row is missing or no longer `published` is dropped and logged, mirroring `search.stale_hit`.
- The approve gesture never fails over a store (mirrors `pipeline/runner.py:452`): projection runs after the Postgres transaction commits; on any store/lock failure the route still returns the published rows and logs an event carrying the `rebuild --meeting <id>` recovery hint.
- The artifacts index is keyword-only: no vectors, no embedder involvement, excluded from embedder-dimension asserts and the embed-only rebuild pass.

**Block If:** None — remaining choices (index settings, Cypher shape, event names) are build-time decisions resolved in Design Notes.

**Never:**
- No provenance-based filtering anywhere in the gate or projection. State is the only criterion (epics AC2/AC4). The 133 legacy per-moment drafts (`provenance->>'source' IS NULL`) are `extracted` and stay invisible unless a human approves them — the operator caution and re-queue decision recorded in sprint-notes stand; do not resolve them in code here.
- No change to `CitationModel`, the citation marker grammar, or `api/citations.py` validation semantics.
- No change to the moment-view right rail's unfiltered artifact read (`api/moments.py:590`) — the sole surface for unpublished artifacts.
- No unpublish/unproject-single-artifact route; no migration (0011 columns suffice); no changes to `moments`/`chunks` index settings or graph vocabulary beyond adding `Artifact`/`CITES`; no worker restart (paid-backlog hold stands); no fix for the upstream adr/action-item duplication (recorded in `deferred-work.md` — both publish, both project).
- Never rename `ARTIFACTS_INDEX`, the `momentIds` field, or re-key graph nodes — the eval harness breaks silently otherwise.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Publish projects | `POST /moments/{id}/approve` succeeds, stores up | After response: doc in `artifacts` index (id, `momentIds`) and `(:Artifact {id})-[:CITES]->(:Moment)` in Neo4j | No error |
| Stores down/locked at publish | Approve succeeds; Meili/Neo4j unreachable or lock held past timeout | Rows are `published`, response unchanged; event logged with `rebuild --meeting` hint; later rebuild backfills | Gesture never 5xxs over a store |
| Gate refusal | `project` attempted on `extracted`/`approved`/unknown/None state | `PublishGateRefused` before any client call | Named refusal, no partial write |
| Search finds ADR | Query matching a published ADR's title/body | `SearchHit` with artifact fields + source-moment replay fields; renders in web with kind badge; replay plays the moment | No error |
| Unpublished stays invisible | `extracted`/`approved` artifacts exist | Never in either store, never a search hit or chat context block | Structural (gate + `state='published'` read) |
| Chat cites source moment | Question a published ADR answers | Artifact hit folds into retrieved moments; answer's citation is the source moment, passes `citations.validate` unchanged | No error |
| Rebuild after publish | `rebuild --all` | Artifacts index wiped + recreated + repopulated with published only; Artifact nodes restored; drafts excluded | Per-meeting failure capture as today |
| Meeting re-projection | Worker settle point / augment on a meeting with published artifacts | Artifact docs/nodes deleted and re-created in the same pass; `CITES` re-resolves to preserved moment ids | No error |
| Stale artifact hit | Ranked artifact id whose row is gone / no longer `published` | Dropped from results, logged | No error to caller |

</intent-contract>

## Code Map

**Projections (write side)**
- `server/meetingminer/projections/publish_gate.py` — the pre-wired contract: `ARTIFACT_STATES` :28, `ARTIFACTS_INDEX` :33, `PublishGateRefused` :36, `Artifact` dataclass :83 (`moment_ids` tuple — DB has one `moment_id`; map 1:1), `artifact_document` :102 (shape frozen), `project_artifact` :127 (`client=None` returns doc). Keep the gate/document here; fix the stale header ("no artifact table exists yet"). Add a Postgres read `published_artifacts(conn, meeting_id | artifact_ids) -> tuple[Artifact, ...]` (`corpus` joins from `meeting`; `WHERE state='published'`).
- `server/meetingminer/projections/graph.py` — add artifact write mirroring existing style (:310-370): `MERGE (:Artifact {id})` with `meetingId/kind/state/title/corpus`, `CITES` edge to `(:Moment {id})`. Vocabulary docstring :7-31 updated.
- `server/meetingminer/projections/stores.py` — `MEETING_SCOPED_LABELS` :50 gains `Artifact` (per-meeting delete + `meetingId` index via `ensure_graph_schema` :223); `ensure_search_schema` :326 creates/configures the artifacts index (keyword-only — no embedder block); `drop_all` :363 deletes it; keep it out of `SEARCH_INDEXES`-driven dimension asserts (or restructure so dimension checks skip it).
- `server/meetingminer/projections/search.py` — `artifact_documents(...)`; `delete_meeting` :179 loop gains the artifacts index; `project_meeting`/`counts` extended.
- `server/meetingminer/projections/__init__.py` — new public entrypoint `project_published_artifacts(conn, config, *, artifact_ids | meeting_id, log)` taking `store_file_lock` → `projection_lock` → open stores (pattern at :510, :719); fold artifact re-projection into the per-meeting structural pass (`_project_structural` :330 / `_project_one` :391) so worker settle points, `unproject_meeting` :550, and `rebuild` :626 handle artifacts automatically; `RebuildReport`/`ProjectionOutcome` (:108/:123) gain an `artifact_documents` count; `cli.py:_report` :128 formats it. Embed-only pass skips artifacts.
- `config.yaml` :411-462 + `config.py:463 SearchConfig` (strict model) — add `projections.search.artifacts` index block (searchable: title/text; filterable: meetingId, state, kind; no embedder).

**Query + API (read side)**
- `server/meetingminer/projections/query.py` — `SEARCHABLE_INDEXES` :71 stays the moments allow-list for the semantic lane; add a keyword-only artifacts lane (its own search-parameter builder; filter `state = 'published'`), an `ArtifactHit` (id, moment_ids, score, snippet) beside `MomentHit` :110, and merge into the existing lane merge (:391) or return alongside.
- `server/meetingminer/api/search.py` — `SearchHit` :104 gains optional `artifact_id`, `artifact_kind`, `artifact_title`; `_resolve` :218 resolves artifact hits via `artifact JOIN moment JOIN meeting` (drop + log stale); `search_corpus` :294 threads the artifacts lane through.
- `server/meetingminer/api/chat.py` — `_search_leg` :445 (or its query call) also retrieves artifact hits; fold their source moment ids into `retrieved`; `_read_context` :684 / `build_synthesis_prompt` :802 append the artifact's title/body inside its source moment's block, labeled as a published artifact. `CitationModel` :223 and `citations.py` untouched.
- `server/meetingminer/api/moments.py` — `approve_moment_artifacts` :614: after the `with pool.connection()` block exits (:680, rows durably published), call `projections.project_published_artifacts` for the just-published ids; catch store/lock errors, log `artifacts.projection.failed` with the rebuild hint, still return 200.

**Web**
- `make client` regenerates `web/src/client/*` (api on :8000 required — announce; never hand-edit).
- `web/src/features/search/CorpusSearch.tsx` :274-400 + `hits.ts` — render artifact hits: kind badge + artifact title; replay/deep-link affordance unchanged (fields already come from the source moment). Chat UI unchanged (citations stay moment-shaped).

**Evals / docs**
- `evals/harness/checks.py:1085` — reword "projection-on-publish is not wired (story 4-4 backlog)" to a post-landing regression message; adjust `evals/tests/test_publish_gate_algorithm.py:92` docstring/assert accordingly. Harness algorithms otherwise untouched. `evals/RUNBOOK.md:264` already self-flips — no edit.
- `_bmad-output/implementation-artifacts/deferred-work.md:145-149` — retire the unlocked-`project_artifact` entry (fixed here).

**Tests (extend/new)**
- `server/tests/test_projections_search.py` :415-465 — extend publish-gate section: real projection into `projection_stores`, published-only, document shape.
- `server/tests/test_projections_graph.py` — Artifact node + `CITES` edge; meeting re-projection re-creates them; unproject removes them.
- `server/tests/test_projections_rebuild.py` — rebuild repopulates published artifacts, excludes drafts, wipes stale artifacts index on `--all`; embed-only skips artifacts.
- `server/tests/test_projections_locks.py` :49-220 — sibling test: `project_published_artifacts` refuses against a held file lock, touches neither store.
- `server/tests/test_artifact_publish.py` — approve triggers projection (stores-backed); store-failure path still returns 200 and logs.
- `server/tests/test_projections_query.py:65`, `server/tests/test_api_search.py:590-628` — rewrite the exclusion pins: artifacts now surface, published-only, resolved through the source moment; stale-hit drop.
- `server/tests/test_api_chat.py` (existing chat tests' file) — artifact hit contributes moment citation; context block labeled.
- `web/src/features/search/*.test.tsx` — artifact hit rendering.

## Tasks & Acceptance

**Execution:**
1. `projections/publish_gate.py` — `published_artifacts` Postgres read + header fix — the gate stays the single chokepoint (AD-4).
2. `projections/graph.py`, `projections/search.py`, `projections/stores.py`, `config.yaml`, `config.py` — Artifact node/edge, `artifact_documents`, index schema/scoping — both stores learn the artifact shape the eval harness pins.
3. `projections/__init__.py`, `projections/cli.py` — `project_published_artifacts` entrypoint (locked) + fold into per-meeting pass, rebuild, unproject, report counters — settle points, augment, and rebuild all restore artifacts automatically (epics AC1/AC4).
4. `projections/query.py`, `api/search.py` — artifacts lane + hit resolution through the source moment — search surfaces published artifacts with a replayable trail (epics AC3).
5. `api/chat.py` — artifact hits fold into retrieved moments + context labeling — chat answers cite the source moment through the unchanged gate (epics AC3).
6. `api/moments.py` — post-commit projection call with never-fail-the-gesture handling — publish triggers projection (epics AC1).
7. `make client`, `web/src/features/search/` — render artifact hits.
8. Tests per Code Map, including the I/O matrix edge cases.
9. `evals/harness/checks.py`, `evals/tests/test_publish_gate_algorithm.py`, `deferred-work.md` — retire the "4-4 backlog" wording and the lock defect entry — the eval expectation flips with the story, not later.

**Acceptance Criteria:**
- Given an artifact transitioning to `published` via the approve route, when the request completes, then the artifact is in the Meilisearch `artifacts` index and in Neo4j with a citation edge to its source moment, written through the projections module under both locks (epics AC1).
- Given any artifact whose state is not `published`, when projection is attempted through any caller, then `PublishGateRefused` is raised before a store client is touched, and no read path can return it (epics AC2).
- Given a published ADR, when I search for it or ask a question it answers, then it appears as a result/citation whose evidence trail replays the original source moment (epics AC3; CAP-9).
- Given `rebuild` run after publishing, then published artifacts are re-projected and unpublished ones remain excluded; a meeting re-projection or augment preserves citability (epics AC4).
- Given the eval harness, when check 2.11 runs post-approval after this story, then presence in both stores citing the source moment is required-pass — the standing expected-fail is retired.

### Review Findings — 2026-08-21 follow-up

- [x] [Review][Patch] Remap a published artifact to the deterministic live replacement moment when augmentation supersedes its source, retaining the original moment identity and remap evidence in provenance; fail augmentation by name before commit when no unique evidence-equivalent replacement exists [`server/meetingminer/pipeline/stages/moments.py:214`]
- [x] [Review][Patch] Make artifact-first search pagination preserve every displaced moment and later artifact match exactly once, with a truthful combined `estimatedTotal` [`server/meetingminer/api/search.py:407`]
- [x] [Review][Patch] Isolate artifact-only schema setup from vector-dimension checks and unrelated moment/chunk mutations, while actively enforcing a no-embedder artifacts index [`server/meetingminer/projections/__init__.py:620`]
- [x] [Review][Patch] Keep the artifacts index completely untouched during embed-only projection and rebuild [`server/meetingminer/projections/__init__.py:371`]
- [x] [Review][Patch] Guarantee artifact-backed source moments retain prompt capacity when ordinary chat retrieval is full [`server/meetingminer/api/chat.py:1116`]
- [x] [Review][Patch] Preserve Meilisearch artifact relevance order through Postgres read-back, grouping, and prompt cropping [`server/meetingminer/api/chat.py:197`]
- [x] [Review][Patch] Reject artifacts-index config without filterable `state` or searchable `title` [`server/meetingminer/config.py:463`]
- [x] [Review][Patch] Remove or lock the still-public direct-store `project_artifact` path so the retired lock defect is actually closed [`server/meetingminer/projections/publish_gate.py:189`]
- [x] [Review][Patch] Make chat route metadata count artifact-backed retrieval rather than reporting `searchHits: 0` [`server/meetingminer/api/chat.py:1128`]

## Spec Change Log

- 2026-08-21: Follow-up remediation completed: all nine review findings are
  checked off with fresh full-suite verification in the review report.

## Review Triage Log

### 2026-08-21 — Review pass

Four layers over `2d9705fb286098f9af08e2724d0106052244bc0f..088ad06`: blind
hunter, edge-case hunter, verification-gap, intent-alignment.

- intent_gap: 0
- bad_spec: 0
- patch: 15: (high 0, medium 6, low 9)
- defer: 0
- reject: 9
- addressed_findings:
  - `[medium]` `[patch]` Combined first-page hits could reach 2x the
    requested `limit` (artifacts fetched up to the limit *in addition
    to* a full moments page) — capped the combined page at
    `effective_limit`, artifacts leading; new test pins the cap.
  - `[medium]` `[patch]` The artifacts lane initially lacked a stable
    cross-page rule — remediation now treats ranked artifacts as one finite
    leading lane, followed by ranked moments, and store-backed tests reach
    artifact and moment hits at non-zero offsets exactly once.
  - `[medium]` `[patch]` A moment's chat context block grew unbounded
    with the number of published artifacts citing it, each up to a
    full moment's worth of prompt text — artifacts on one moment now
    share a single `ARTIFACTS_PER_MOMENT_MAX_CHARS` budget, cropped as
    a whole; crops counted in their own `cropped_artifacts` telemetry
    field instead of mislabeling `cropped_moments`.
  - `[medium]` `[patch]` Publishing into a Meilisearch store wiped
    mid-run could auto-create an unconfigured `artifacts` index
    (missing `state`/`meetingId` filterable attributes) — verified
    already correct: `project_published_artifacts` opens stores via
    `_open_stores(ensure=True)`, which configures the index before any
    write; closed with a test that wipes only the artifacts index and
    asserts it comes back correctly configured.
  - `[medium]` `[patch]` Chat's `state = 'published'` re-filter on
    artifact context was untested — a store-backed test now moves a
    published, indexed artifact's row to `extracted` and asserts its
    body never reaches the synthesis prompt and
    `chat.stale_artifact_hit` is logged.
  - `[medium]` `[patch]` Chat's artifact leg queries with no
    meeting/corpus scope — verified deliberate (the moments leg is
    equally unscoped; `ChatRequest` accepts neither today) and
    documented with a comment rather than changed.
  - `[low]` `[patch]` `search.completed`'s `returned`/`dropped` counted
    moment hits only while the response carries both lanes — added
    `capacity_truncated` (distinct from a stale-hit drop) and
    `total_returned` fields.
  - `[low]` `[patch]` `delete_meeting`'s per-meeting artifacts-index
    delete against a pre-4.4 store — verified already tolerant
    (`tolerate=("index_not_found",)` already covers `ARTIFACTS_INDEX`
    in the loop); no change needed.
  - `[low]` `[patch]` `MERGE`-deduplicated `CITES` edges could make the
    naive `expected_edges` sum exceed the real edge count, false-
    positiving a `ProjectionError`; a republished artifact whose source
    moment changed could keep a stale edge beside the new one — fixed
    both: dedupe `moment_ids` before counting, delete an artifact's
    existing `CITES` edges before re-merging.
  - `[low]` `[patch]` `PUBLISHED_STATE` was f-string-interpolated into
    three SQL statements instead of bound as a parameter — fixed in
    `publish_gate.py`, `chat.py`, `search.py`.
  - `[low]` `[patch]` `search_artifacts`'s allow-list guard compared a
    constant against a constant derived from it — unreachable dead
    code — removed; the docstring states the invariant directly.
  - `[low]` `[patch]` `insert_artifact`/`_insert_artifact` was copy-
    pasted across six test files — consolidated into one
    `projection_seed.insert_artifact` helper.
  - `[low]` `[patch]` An artifact hit and its source-moment hit sharing
    a search page had identical aria-labels/replay labels (both used
    only the meeting label) — disambiguated with the artifact's title;
    also removed a duplicated offset rendering. New test pins the
    disambiguation.
  - `[low]` `[patch]` The three new `SearchHit` fields had no
    description, so the generated client documented them as bare
    "Artifactid" etc. — added `Field(description=...)` and regenerated
    `web/src/client/types.gen.ts` from an offline schema dump (the
    shared `:8000` api was serving `main`'s stale code).
  - `[low]` `[patch]` `deferred-work.md`'s resolved unlocked-
    `project_artifact` entry replaced its `evidence:` field wholesale
    instead of adding `resolution:` alongside it — restored the
    original evidence text.
  - `[reject]` A misconfigured/degraded artifacts index taking down
    the whole `/chat` request with a 503 — matches `_search_leg`'s
    identical existing policy for the moments index; not a new
    behavior this story introduced.
  - `[reject]` The approve route calls projection even when nothing is
    pending, and a projection failure is log-only with no metric/UI
    surface — both are the spec's explicit "never fails the gesture
    over a store" design, not an oversight.
  - `[reject]` `make evals-run` has not executed post-landing — gated
    on explicit announcement per AGENTS.md; the flipped expectation is
    verified at the algorithm level and by a stores-backed integration
    test per the spec's own Verification section.
  - `[reject]` A `NULL` `moment_id` reaching the graph writer —
    unreachable: migration 0009 declares `moment_id uuid NOT NULL`.
  - `[reject]` An artifact's source moment being deleted while the
    artifact still cites it, with no log — unreachable: the composite
    FK `(moment_id, meeting_id) → moment(id, meeting_id)` has no
    cascade, so such a delete is blocked at the database.
  - `[reject]` Intent-alignment: chat citations stay moment-typed
    rather than artifact-typed — the spec's Design Notes state this
    choice and its rationale explicitly (reopening the frozen six-field
    contract for no AC gain); not an unresolved divergence.
  - `[reject]` Intent-alignment: AC1's outcome guarantee realized as
    attempt-plus-recovery rather than a hard post-condition — the
    spec's Design Notes state this choice explicitly (mirrors the
    worker's documented failure policy, `rebuild --meeting` as
    recovery); not an unresolved divergence.
  - `[reject]` Intent-alignment: AC2's "refuses" realized as structural
    exclusion (a `WHERE state = 'published'` read) plus a logged skip
    at the entrypoint surface, rather than an active raise at every
    surface — a stronger mechanism than the AC's literal wording, and
    the gate itself (`assert_publishable`) still raises; not a gap.

## Design Notes

- **Artifact is meeting-scoped in both stores, restored from Postgres on every meeting pass.** The alternative (exempt from per-meeting delete) breaks anyway: `DETACH DELETE` of `Moment` nodes severs `CITES` edges on every re-projection. Making the per-meeting pass re-read `WHERE state='published'` keeps Postgres authoritative and augment-safe. **Attack point:** the worker's settle-point projection now also writes artifact rows' projections — acceptable because the gate is state-based and "regardless of caller" is the epic's own wording.
- **Keyword-only artifacts index.** Embedding at publish time would make the human gesture depend on Ollama availability, and rebuild's embed-only pass would gain a third document family for marginal recall on short, title-rich documents. The eval harness checks presence by id, not ranking.
- **Projection after commit, never inside the transaction.** Holding a REPEATABLE READ transaction (with `FOR UPDATE` locks) across two store writes and a cross-process file lock (default timeout 300s) is the worst ordering. Publish-then-project with rebuild as recovery mirrors the worker's documented failure policy; the gap window is Postgres-visible (`published` but unprojected) and closed by `rebuild --meeting`.
- **Chat integration is retrieval-side only.** An `[[artifact:…]]` marker would reopen the frozen six-field citation contract, the validation grammar, and the web/eval consumers — for no AC gain, since the AC's citation target is the *source moment*.
- **Legacy drafts and duplicates are upstream, untouched.** Provenance-NULL drafts stay `extracted` unless a human approves; the adr/action-item duplication publishes and projects both. Both are recorded in deferred-work/sprint-notes with the decision holder named (the user).

## Verification

**Commands:**
- `cd server && uv run pytest tests/test_projections_search.py tests/test_projections_graph.py tests/test_projections_rebuild.py tests/test_projections_locks.py tests/test_projections_query.py -q` -- expected: all pass; store-backed (shared stack — announce per AGENTS.md; projection tests queue on the cross-worktree lock).
- `cd server && uv run pytest tests/test_artifact_publish.py tests/test_api_search.py tests/test_api_chat.py tests/test_api_moments.py tests/test_projections_single_writer.py -q` -- expected: all pass.
- `cd server && uv run pytest tests/ -q` -- expected: full regression passes.
- `make evals-test` -- expected: pass, store-free (algorithm wording change covered).
- `make web-test` -- expected: pass, including artifact-hit rendering cases.
- `make client` -- expected: regenerates `web/src/client/*`; diff shows only the new optional `SearchHit` fields.
- `rg -n "import neo4j|import meilisearch|from neo4j|from meilisearch" server/meetingminer/api` -- expected: no matches.

## Auto Run Result

**Status:** implemented and reviewed on branch `story/4-4` (worktree
`../meetingminer-wt/4-4`). One adversarial review pass ran (four parallel
layers: blind hunter, edge-case hunter, verification-gap, intent-alignment);
15 patch findings applied and verified, 9 rejected as either deliberate
Design-Notes decisions, spec-mandated behavior, or unreachable given the
schema/existing policy. No intent gaps, no bad-spec findings — the diff's
divergences the intent-alignment audit surfaced (moment-typed chat citations,
best-effort projection with rebuild recovery, structural-exclusion "refusal")
are all choices the spec's own Design Notes make explicitly.

**Summary of implemented change:** Publishing now projects. A locked
projections entrypoint (`project_published_artifacts` — store file lock first,
then the Postgres advisory lock) writes `published` artifacts into the
Meilisearch `artifacts` index (keyword-only, no embedder ever declared) and
into Neo4j as `(:Artifact {id})-[:CITES]->(:Moment)`. The approve route calls
it after its transaction commits and never fails the gesture over a store —
any failure logs `artifacts.projection.failed` with the `rebuild --meeting`
hint. `Artifact` is a meeting-scoped label, so every per-meeting structural
pass (worker settle points, augment, `unproject_meeting`, `rebuild`) deletes
and re-creates the meeting's published artifacts from Postgres
(`publish_gate.published_artifacts`, `WHERE state = 'published'`), and the
embed pass carries them unvectored. The query layer gained a keyword-only
artifacts lane (`query.search_artifacts`, `state = 'published'` pinned in
every request); `/search` resolves an artifact hit through
`artifact JOIN moment JOIN meeting` so its replay fields are the source
moment's, dropping and logging stale hits (`search.stale_artifact_hit`);
`/chat` folds artifact hits' source moments into the retrieved set and labels
the artifact's title/body inside that moment's context block — `CitationModel`
and the citation grammar are untouched. The web search view renders artifact
hits with a kind badge, the artifact title, and a "Published from …" evidence
line; replay affordances are unchanged. Eval check 2.11's post-approval half
is now a required-pass regression message, and deferred-work's
unlocked-`project_artifact` entry is marked resolved.

**Files changed:** `server/meetingminer/projections/{publish_gate,stores,graph,search,__init__,cli,query}.py`,
`server/meetingminer/config.py`, `config.yaml`,
`server/meetingminer/api/{search,chat,moments}.py`,
`web/src/client/types.gen.ts` (regenerated), `web/src/features/search/{hits.ts,CorpusSearch.tsx,CorpusSearch.test.tsx}`,
`evals/harness/checks.py`, `evals/tests/test_publish_gate_algorithm.py`,
`_bmad-output/implementation-artifacts/deferred-work.md`,
`server/tests/projection_seed.py`, and server tests:
`test_projections_{locks,graph,search,rebuild,query}.py`,
`test_api_{search,chat}.py`, `test_artifact_publish.py`, `test_config.py`,
`server/pyproject.toml` (marker registration).

**Review findings breakdown:** 15 patched (high 0, medium 6, low 9), 0
deferred, 9 rejected (deliberate design decisions, spec-mandated behavior, or
unreachable given the schema/existing policy — see Review Triage Log).

**Follow-up review recommendation:** `true`. Counting only this pass's
`patch` findings: high 0, medium 6, low 9; score = 3 × 6 + 1 × 9 = 27, at or
above the threshold of 5.

**Verification performed:**
- `cd server && uv run pytest tests/ -q` — full store-backed regression, run
  twice: pre-review-pass **1563 passed, 0 failed**; post-review-pass (all 15
  patches applied) **1568 passed, 0 failed** (9:29).
- `make evals-test` — 548 passed, store-free, both passes.
- `make web-test` — 206 passed pre-pass, **207 passed** post-pass (the new
  aria-label-disambiguation test), including the artifact-hit rendering and
  helper cases.
- `make client` equivalent — the api on :8000 was serving `main`'s code, so
  the schema was dumped offline from this branch's `app.openapi()` (via
  process-local env vars, no `.env` edits) and fed to the same hey-api
  generator, both for the initial build and again after adding the three
  `Field(description=...)` annotations; each diff touched only what it
  should.
- `rg -n "import neo4j|import meilisearch|from neo4j|from meilisearch" server/meetingminer/api`
  — no matches, both passes.
- Targeted re-verification per patch, before the final full regression:
  `test_api_search.py` (39 passed), `test_api_chat.py` (50 passed),
  `test_projections_search.py` + siblings (242 passed), `CorpusSearch.test.tsx`
  (44 passed).

**Residual risks / notes:**
- Search-result ordering is one finite artifact-first sequence followed by
  moment ranking; scores from the independent indexes are not blended. The
  combined page is capped at the caller's `limit`, and exhaustive artifact
  counts define the lane boundary at every offset.
- The approve route catches `Exception` around the projection call (the
  spec's "never fails over a store" is absolute, confirmed correct in
  review), so a programming error in projection also degrades to the
  logged-hint path rather than a 500 — triaged as a reject, not a defect.
- The eval loop (`make evals-run`) has not been run post-landing; check
  2.11's flipped expectation is verified at the algorithm level
  (`evals/tests`) and by the stores-backed approve test — triaged as a reject
  (announce-gated per AGENTS.md), not a gap.
- `test_artifact_publish.py` stubs projection for the pre-existing gesture
  tests (autouse fixture) and exercises the real stores in one
  marker-gated end-to-end test (`real_projection`); confirmed in review that
  the marker is organizational only (opts out of the stub) and not a pytest
  deselection filter — the test runs and passes under a plain
  `uv run pytest tests/test_artifact_publish.py -q`.
