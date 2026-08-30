# Code Review: Story 4-4 — Published Artifacts Become Citable Knowledge

## Scope

- Repository: `meetingminer`
- Review branch: `story/4-4-review`
- Source branch: `story/4-4`
- Reviewed range: `2d9705fb286098f9af08e2724d0106052244bc0f..bb813821356dd295240dd5bee6e36271bd1ce58d`
- Review mode: full, against `spec-4-4-published-artifacts-become-citable-knowledge.md`
- Review method: unchunked adversarial review using blind-hunter, edge-case-hunter, verification-gap, and acceptance-auditor layers.

## Findings

### 1. Published artifacts can become uncitable when augmentation supersedes their source moment

- **Location:** `server/meetingminer/api/chat.py:787`
- **Severity:** high
- **Route:** patch — decision resolved by user on 2026-08-21
- **Finding:** Chat drops every superseded source moment before synthesis and the citation resolver refuses it again, but a published artifact remains FK-linked to that preserved moment. Augmentation may supersede a transcript moment while deliberately retaining its UUID, so the artifact stays projected and searchable yet cannot contribute to a citable chat answer.
- **Evidence:** `_read_context` skips rows whose provenance says `superseded` at lines 807-809, while `_RESOLVE_MOMENTS` applies `_LIVE_MOMENT` at lines 152-163. `pipeline/stages/moments.py:214-232` explicitly retains and marks unrecomputed moments, and migration `0009_artifacts.sql:39-43` retains artifact links so published artifacts remain valid across augmentation. Story 4-4's edge-case matrix requires augment re-projection to preserve citability. No test covers a published artifact whose source moment becomes superseded.
- **Concrete failure:** After augmentation moves a source boundary, `/search` can still return the published artifact, but `/chat` either drops it behind ordinary candidates or returns `no-evidence`; its original moment cannot pass citation validation.
- **Required outcome:** During augmentation, remap the artifact to the deterministic live replacement moment while retaining the original source moment identity and remap evidence in provenance. Projection, search, and chat must resolve through the live replacement. If no unique evidence-equivalent replacement exists, augmentation must fail by name before committing a state that makes the published artifact uncitable; it must never guess or silently leave the artifact attached to an uncitable source.

### 2. Artifact-first pagination permanently skips matching moments and hides later artifact matches

- **Location:** `server/meetingminer/api/search.py:407`
- **Severity:** medium
- **Route:** patch
- **Finding:** The first page fetches a normal moment page, prepends artifacts, and truncates displaced moments; later pages apply the caller's raw offset to moments and never query artifacts. Displaced moment hits and artifact matches beyond the first artifact page are therefore unreachable. `estimatedTotal` also reports the moments lane alone.
- **Evidence:** Artifacts run only for `offset == 0` at lines 417-433; lines 484-487 discard moment hits after their offset was already applied; lines 503-510 return only `result.estimated_total`. Existing tests assert the page cap and absence of artifacts at offset 1 but never assert continuity across pages.
- **Concrete failure:** With `limit=1`, one matching artifact, and two matching moments, page 0 returns the artifact and discards moment rank 1; page 1 starts moments at offset 1 and returns rank 2. Rank 1 appears on no page. An artifact-only result can simultaneously return one hit and report `estimatedTotal: 0`.
- **Suggested direction:** Define one stable combined paging sequence, keep every displaced moment and every artifact reachable exactly once, and make `estimatedTotal` describe that same sequence. Add a multi-page regression that fails against the current implementation.

### 3. Artifact publishing is coupled to unrelated vector schema and does not enforce a keyword-only existing index

- **Location:** `server/meetingminer/projections/__init__.py:620`
- **Severity:** medium
- **Route:** patch
- **Finding:** The artifact-only approval path opens stores through the all-index schema initializer. It can be refused by a moments/chunks vector-dimension mismatch and rewrites those unrelated index settings on every approval. Conversely, schema setup never removes an embedder already present on the artifacts index, so it does not actively enforce the declared keyword-only contract.
- **Evidence:** `project_published_artifacts` calls `_open_stores(...ensure=True)` at lines 620-623; `_open_stores` calls `ensure_search_schema` at lines 156-177; `stores.ensure_search_schema` first checks dimensions for `SEARCH_INDEXES`, updates moments/chunks settings and embedders, then only updates artifact settings at `stores.py:338-386`. It never resets artifact embedders.
- **Concrete failure:** After an embedder-width config change, approving an artifact logs a projection failure even though the artifact path needs no vector. Against an artifacts index carrying a stale auto/user-provided embedder, scoped recovery does not restore the configured keyword-only state.
- **Suggested direction:** Give artifact-only projection a schema preflight that touches only Artifact/`artifacts`, is independent of vector dimensions, and guarantees that the artifact index has no embedder. Preserve the existing lock order.

### 4. Embed-only rebuild rewrites the keyword-only artifacts index

- **Location:** `server/meetingminer/projections/__init__.py:371`
- **Severity:** medium
- **Route:** patch
- **Finding:** The embedding-only pass reads artifacts and sends them through the shared delete-and-reinsert search projection, contradicting the frozen constraint that artifacts are excluded from the embed-only pass.
- **Evidence:** `_project_embeddings` passes `artifacts` to `search.project_meeting` at lines 371-404; `search.project_meeting` deletes the meeting from all three indexes and re-adds artifacts at `projections/search.py:231-258`. `test_projections_rebuild.py:1454-1483` currently pins this contradictory “ride along” behavior instead of the contract.
- **Concrete failure:** `rebuild --embed-only` can delete a meeting's published artifact documents and then fail while re-adding them, making unrelated vector repair remove citable knowledge.
- **Suggested direction:** Keep artifact documents and the artifacts index completely untouched during embed-only operations. Replace the contradictory test with one that proves no artifact-index call occurs.

### 5. Chat can drop a relevant artifact behind lower-priority ordinary candidates

- **Location:** `server/meetingminer/api/chat.py:1116`
- **Severity:** medium
- **Route:** patch
- **Finding:** Artifact source moments are appended after traversal rows and all ordinary search hits. The 32,000-character prompt cap drops later whole blocks, so a successfully retrieved artifact can be excluded from synthesis.
- **Evidence:** Lines 1116-1127 order traversal, moment search, then artifact source moments. `build_synthesis_prompt` drops later blocks once the cap is reached at lines 969-975. The configured limits permit 20 traversal rows and 30 moment-search hits before up to 30 artifact hits. Tests cover prompt cropping and a single artifact, but not artifact survival under a full ordinary retrieval leg.
- **Concrete failure:** A question with many semantic moment candidates and one strong artifact hit can build a prompt containing only the earlier ordinary candidates; the published artifact's title/body never reaches the model, violating the chat half of AC3.
- **Suggested direction:** Reserve or prioritize prompt capacity for artifact-backed source moments while retaining deterministic traversal semantics. Add a regression that fills the ordinary candidate budget and proves the matching artifact remains prompted and citable.

### 6. Chat discards Meilisearch artifact relevance order during Postgres read-back

- **Location:** `server/meetingminer/api/chat.py:197`
- **Severity:** medium
- **Route:** patch
- **Finding:** Ranked artifact IDs are re-read with `ORDER BY a.created_at, a.id`, and the resulting row order determines both source-moment order and which per-moment artifact text survives cropping.
- **Evidence:** `_ARTIFACT_CONTEXT` orders by creation time at lines 197-202; `_read_artifact_context` iterates those rows directly at lines 575-600; `_answer` iterates the mapping in that insertion order at lines 1111-1123. Search's resolver already demonstrates the correct pattern by rebuilding rows in incoming hit order.
- **Concrete failure:** When a newer artifact ranks above an older artifact, the older one enters the prompt first and can consume the bounded prompt/per-moment budget, cropping or dropping the better answer source.
- **Suggested direction:** Reconstruct Postgres rows in the incoming ranked-ID order before grouping and preserve that order through prompt construction. Add cross-moment and same-moment reversed-creation/ranking tests.

### 7. Config validation accepts artifact settings that make mandatory queries fail or miss titles

- **Location:** `server/meetingminer/config.py:463`
- **Severity:** medium
- **Route:** patch
- **Finding:** The strict model never requires `state` to be filterable or `title` to be searchable for the artifacts index, although every artifact query filters on `state` and the story contract requires title/body search.
- **Evidence:** `SearchIndexConfig` requires only `meetingId`, `corpus`, and searchable `text` at lines 425-460; `SearchConfig` validates only the moments highlight surface at lines 482-497. `query.build_artifact_search_parameters` always emits `state = "published"` and requests title highlighting at `projections/query.py:628-662`.
- **Concrete failure:** Removing `state` from the tracked config still passes startup validation but makes every artifact search/chat query fail at runtime; removing `title` silently makes a title-only ADR undiscoverable.
- **Suggested direction:** Fail config loading unless artifact settings contain every field the artifact query and declared search surface require. Add negative config tests for both omissions.

### 8. The public legacy `project_artifact` function remains an unlocked store writer

- **Location:** `server/meetingminer/projections/publish_gate.py:189`
- **Severity:** low
- **Route:** patch
- **Finding:** Story 4-4 marks the deferred unlocked-writer defect resolved, but `project_artifact(client, artifact)` still writes directly to Meilisearch without either lock or schema setup and remains publicly re-exported.
- **Evidence:** Lines 189-206 call `client.index(ARTIFACTS_INDEX).add_documents`; `projections/__init__.py:56-63,78-99` re-exports it. Repository search finds no production caller today, only its refusal test, which limits current severity but leaves the claimed invariant false.
- **Concrete failure:** Any new caller using the public helper can race rebuild/projection and auto-create an unconfigured artifacts index while all lock tests remain green.
- **Suggested direction:** Remove the store-writing public path or route every real write through the locked entrypoint; retain a pure document/gate helper if compatibility needs it. Add an invariant test that no exported artifact helper can write without the composed locks.

### 9. Artifact-only chat answers report zero search hits

- **Location:** `server/meetingminer/api/chat.py:1128`
- **Severity:** low
- **Route:** patch
- **Finding:** `RouteModel.search_hits` counts only moment-index IDs, so an answer retrieved entirely from a published artifact reports `searchHits: 0`.
- **Evidence:** Both route constructions use `len(search_ids)` at lines 1128-1157 and omit `artifact_ids`. The existing artifact-answer test verifies citations and prompt content but not route telemetry.
- **Concrete failure:** Operators and clients see a successful artifact-backed answer whose route metadata says the search leg found nothing, obscuring how the answer was obtained.
- **Suggested direction:** Make route metadata account for artifact retrieval without double-counting source moments, and pin the artifact-only response plus mixed-lane semantics in tests.

## Dismissed candidates

Four normalized candidates were dismissed:

- The response-level `ranking` value describes whether the request ran the hybrid moments query, not a promise that every returned lane used vectors.
- Artifact-first ordering across indexes is an explicit, documented product choice; the continuity defect above is actionable, but cross-index score calibration is not required by the story.
- Fetching `retrieval_limit` independently for each chat lane is bounded by the prompt cap and not forbidden; the actionable defect is allowing relevant artifact blocks to lose all prompt capacity.
- Per-meeting projection opens stores before reading its structurally filtered artifact set, but no unpublished artifact can reach an artifact write: the SQL gate filters first and each artifact is asserted before its artifact-specific graph/search write.

## Remediation re-review

Three fresh layers reviewed the complete remediation diff: blind-hunter,
edge-case-hunter, and verification-gap. After deduplication and root-agent
triage they produced 13 patch findings, one confident pre-existing defer, and
three dismissed candidates.

All 13 patches were applied and verified. They close exhaustive artifact-lane
counting, stale-slot paging, concurrent approval/remap serialization, original
source-instant preservation, malformed provenance refusal, post-lock
projection reads, embedder-inspection failure handling, exact artifact-only
schema coverage, absent-index/stale-embedder separation, search-rank readback,
traversal-first prompt presentation, and two stale contract descriptions.

The one defer records that embed-only projection still health-checks Neo4j
despite writing only Meilisearch vectors. That behavior predates Story 4-4 and
is now filed in `deferred-work.md`; it does not weaken artifact citability.

## Verification

Remediation completed on this review branch. Fresh verification passed:

- Targeted remediation set: 254 passed.
- Full server regression: 1,587 passed.
- Eval harness: 548 passed (`make evals-test`).
- Web: 207 passed (`make web-test`).
- Generated client: regenerated from this worktree's OpenAPI schema; no diff.
- API single-writer import scan: no Neo4j or Meilisearch imports.

The regression set covers deterministic artifact remapping (including zero and
ambiguous replacement rollback), combined paging continuity/totals,
artifact-only schema isolation and embedder removal, artifact-free embed-only
repair, prompt capacity and ranking, required config surfaces, removal of the
unlocked writer, and artifact-aware route telemetry.

## Verdict

**Passes after remediation.** All nine original findings and all 13
remediation re-review patches are implemented and pinned by regressions. Fresh
verification is green; no unresolved high or medium finding remains.
