---
title: 'Story 1.7: Projection Review Remediation'
type: 'bugfix'
created: '2026-08-19'
baseline_commit: 'bebbcc7b7dd157407f4d534f8cfb1467ce1742b7'
status: 'done'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/spec-1-7-evidence-projections-rebuild-cli.md'
  - '{project-root}/_bmad-output/implementation-artifacts/review-story-1-7-2026-08-19.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Story 1.7's review found one projection-consistency defect, three contract defects, and three gaps that allow critical behavior to regress while the suite remains green. In particular, a scoped embedding-only rebuild after a chunking retune can leave search and graph views for the same meeting on different chunk boundaries.

**Approach:** Make embedding-only projection conditional on matching structural state, retain the required speaker-resolution metadata in both chunk stores, preflight vector mismatch before any schema mutation, make the console CLI locate repository config, and pin the affected contracts with targeted regressions.

## Boundaries & Constraints

**Always:** A chunking, model, or dimension mismatch must require a full projection; an embedding-only command must write neither store when its structural state is stale. Persist raw speaker labels with their resolution without inventing a Participant edge. A dimension refusal must happen before either store is mutated. The direct `cd server && uv run rebuild ...` command must retain explicit `MM_CONFIG_PATH` override behavior. Keep `Embedder` calls batched by config and preserve AD-4 as the only writer boundary.

**Ask First:** None.

**Never:** Do not change the underlying evidence computation, graph/search index names, schema identity model, live-store test isolation deferral, freshness deferral, same-width model-swap deferral, API/UI behavior, or the full-rebuild destructive semantics.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|---------------|---------------------------|----------------|
| Scoped embedding after retune | A projected meeting has recorded chunking different from config | No graph/search/state write occurs; operator is directed to full projection | Named refusal |
| Unresolved speaker | A chunk includes unresolved, ambiguous, or placeholder turns | Graph and search chunk representations retain label and resolution; no Participant edge is created | N/A |
| Stored width mismatch | Meilisearch has a conflicting dimension and Neo4j schema is fresh | Command refuses before any constraint/index/document change | Named refusal |
| Console invocation | `rebuild --all --dry-run` runs from `server/` | Root config resolves unless `MM_CONFIG_PATH` specifies another file | Config error only for an actually invalid path |

</frozen-after-approval>

## Code Map

- `server/meetingminer/projections/__init__.py` — `_project_one()` creates chunks before selecting the embedding path; `rebuild()`'s scoped branch bypasses `projection_action()`. Reuse recorded `meeting_projection` state to guard embed-only work.
- `server/meetingminer/projections/search.py` and `graph.py` — the two Chunk serializers currently project labels and participant IDs only; add an equivalent per-turn speaker-resolution value object to both.
- `server/meetingminer/projections/stores.py` — existing Meilisearch dimension inspection is non-mutating; call it before `ensure_graph_schema()` in `_open_stores()`.
- `server/meetingminer/projections/cli.py` and `config.py` — `load_config()` honors `MM_CONFIG_PATH` then cwd; the console entry point needs a repository-root default without defeating the environment override.
- `server/tests/test_projections_{rebuild,search,graph}.py` — extend the existing fixtures and `FakeEmbedder` tests; do not run the destructive store-backed suite against production data outside its established harness.

## Tasks & Acceptance

**Execution:**
- [x] `server/meetingminer/projections/__init__.py` -- validate recorded structural model, dimension, and chunking before every embed-only path; reject stale state before building documents or opening a write path.
- [x] `server/meetingminer/projections/{search,graph}.py` -- project per-turn speaker label and resolution with chunk data in the camelCase store shapes.
- [x] `server/meetingminer/projections/stores.py` -- reorder preflight so a known Meilisearch dimension mismatch precedes Neo4j schema setup.
- [x] `server/meetingminer/projections/cli.py` -- establish a reliable root-config default for the installed script while preserving explicit config environment overrides.
- [x] `server/tests/test_projections_{rebuild,search,graph}.py` -- add regressions for stale scoped embed-only, speaker resolution, no-schema-write dimension failure, from-`server` dry run, vector/text correspondence, batch bounds, and cross-meeting participant survival.

**Acceptance Criteria:**
- Given stale structural projection state, when any embed-only entry point is invoked, then it performs no store/state write and returns a named full-projection requirement.
- Given a chunk with every non-resolved speaker state, when projected, then both store representations retain each label's state and graph participants remain resolved-only.
- Given a Meilisearch width mismatch, when a normal projection starts, then Neo4j schema has not changed.
- Given the installed command starts in `server/`, when it is passed `--all --dry-run`, then it loads the repository config; a supplied `MM_CONFIG_PATH` continues to win.
- Given deterministic vectors and a small configured batch, when a meeting embeds, then each moment/chunk document carries the vector from its own text and each provider call is within the bound.
- Given two meetings share a participant, when one is unprojected, then the other remains reachable through that participant.

## Design Notes

The embed-only guard belongs at the public/pass boundary, not only in worker action selection: the CLI's scoped path deliberately calls the same internal pass directly. Speaker metadata must be serializable and parallel to the source turns so a label occurring with different resolution states does not collapse into an unsafe single value.

## Verification

**Commands:**
- `cd server && uv run pytest tests/test_projections_rebuild.py tests/test_projections_search.py tests/test_projections_graph.py -q` -- expected: all affected regression coverage passes against the configured test stores.
- `cd server && uv run rebuild --all --dry-run` -- expected: repository config resolves from the server directory without opening or changing stores.
- `cd server && uv run pytest tests/test_embed_adapter.py tests/test_projections_chunking.py -q` -- expected: pure adapter/chunking coverage remains green.

**Run:** The affected projection suite initially produced one float32 round-trip
assertion failure; the assertion now compares the stored Meilisearch vector with
the deterministic float64 test vector at an explicit tolerance. The first
complete run otherwise passed 63 tests; the corrected vector regression passed
alone, and the five final guard/metadata regressions passed together. The pure
adapter/chunking and CLI-from-`server` checks passed (36 tests). Every
store-backed pass was followed by `make -f infra/Makefile rebuild`; the final
run restored 28 meetings, structural 28, embedded 28, failed 0.

## Suggested Review Order

**Embed-only consistency**

- Reject drift before opening stores, and recheck after lock acquisition.
  [`__init__.py:216`](../../server/meetingminer/projections/__init__.py#L216)

- Preserve per-meeting continuation while detecting stale corpus-wide state.
  [`__init__.py:597`](../../server/meetingminer/projections/__init__.py#L597)

- Keep the direct resume path subject to the same locked guard.
  [`__init__.py:511`](../../server/meetingminer/projections/__init__.py#L511)

**Store and command boundaries**

- Preflight Meilisearch width before Neo4j schema writes.
  [`__init__.py:145`](../../server/meetingminer/projections/__init__.py#L145)

- Resolve checkout configuration while retaining explicit environment overrides.
  [`cli.py:49`](../../server/meetingminer/projections/cli.py#L49)

**Projected speaker evidence**

- Retain ordered raw-label/resolution pairs in the graph-compatible representation.
  [`graph.py:211`](../../server/meetingminer/projections/graph.py#L211)

- Mirror the ordered speaker evidence in search documents.
  [`search.py:105`](../../server/meetingminer/projections/search.py#L105)

**Regression evidence**

- Exercise stale, all-target, mixed-target, and no-store-write guard behavior.
  [`test_projections_rebuild.py:984`](../../server/tests/test_projections_rebuild.py#L984)

- Verify duplicate speaker labels, bounded batching, and text/vector correspondence.
  [`test_projections_search.py:133`](../../server/tests/test_projections_search.py#L133)

- Verify participant survival and graph speaker metadata after projection changes.
  [`test_projections_graph.py:232`](../../server/tests/test_projections_graph.py#L232)
