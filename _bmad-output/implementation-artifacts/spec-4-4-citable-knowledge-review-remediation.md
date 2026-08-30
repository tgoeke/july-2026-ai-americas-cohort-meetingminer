---
title: 'Story 4-4 Review Remediation: Preserve Citable Published Knowledge'
type: 'bugfix'
created: '2026-08-21'
status: 'done'
review_loop_iteration: 0
baseline_commit: 'b039a3021bb404a9fd38d8ac5a504eb421661eeb'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/review-story-4-4-2026-08-21.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-4-4-published-artifacts-become-citable-knowledge.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-4-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Story 4-4 publishes and retrieves artifacts, but follow-up review found nine defects that can make published knowledge unreachable, uncitable, incorrectly paged, or coupled to unrelated vector work.

**Approach:** Repair the projection, search, chat, configuration, and augmentation boundaries so every published artifact remains reachable and citable through deterministic live evidence, without weakening the publish gate or moment-shaped citation contract.

## Boundaries & Constraints

**Always:** Preserve AD-4's sole-writer and lock order, AD-5 column ownership, AD-6 Postgres-resolved moment citations, the six-field `CitationModel`, and the eval harness's literal artifacts index/document contract. When augmentation supersedes an artifact's source moment, remap it to one unique evidence-equivalent live moment and retain the original source identity plus remap evidence in artifact provenance. Search paging must expose each combined hit exactly once. Artifact-only projection and embed-only repair must remain independent of each other's store surfaces.

**Ask First:** Any proposed mapping rule that can select more than one live replacement, any schema migration, or any citation wire-format change.

**Never:** Guess an ambiguous replacement moment; leave a published artifact attached to an uncitable source; let embed-only work touch the artifacts index; run `make evals-run`; alter artifact ranking priority merely to fix pagination; broaden into upstream extraction deduplication.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Augment moves source | Published artifact's moment becomes superseded | Artifact points to the unique live evidence-equivalent moment; provenance retains original/remap evidence | Named stage failure before commit if zero or multiple replacements |
| Paged mixed search | Artifacts and moments exceed one page | Every match is reachable exactly once; total covers both lanes | No silent skips or duplicates |
| Artifact-only publish | Moment/chunk vector width is stale | Artifact schema/write proceeds under both locks without touching vector indexes | Artifact-store failures retain existing rebuild-hint behavior |
| Embed-only repair | Published artifacts exist | No artifacts-index call or document mutation | Existing embedding failure taxonomy |
| Full chat retrieval | Ordinary candidates fill prompt budget | Ranked artifact evidence retains capacity and relevance order | Cropping remains logged and citation-safe |

</frozen-after-approval>

## Code Map

- `server/meetingminer/pipeline/stages/moments.py` — supersession transaction; add deterministic published-artifact remap before marking old moments uncitable. Reuse planned live spans and artifact JSON provenance; worker owns both fields.
- `server/meetingminer/projections/{__init__,stores,search,publish_gate}.py` — split artifact schema ensure from vector schema, remove the unlocked legacy writer, and separate embed-only moment/chunk replacement from structural artifact replacement.
- `server/meetingminer/config.py` — artifacts-specific required query-surface validation (`state`, `title`).
- `server/meetingminer/projections/query.py`, `server/meetingminer/api/search.py` — carry artifact totals/offsets and implement one artifact-first combined paging sequence without cross-index score blending.
- `server/meetingminer/api/chat.py` — preserve artifact rank through Postgres, reserve artifact-backed prompt capacity, and report artifact retrieval in route metadata without double-counting source moments.
- `server/tests/test_worker_moments.py`, `test_projections_{search,rebuild,locks}.py`, `test_config.py`, `test_api_{search,chat}.py` — regression anchors; every new test must fail on `bb81382` before its fix is accepted.

## Tasks & Acceptance

**Execution:**
- [x] Implement and test deterministic artifact source remapping during moment supersession.
- [x] Isolate artifact schema/write setup and make embed-only projection artifacts-free.
- [x] Remove the public unlocked artifact writer and strengthen config validation.
- [x] Repair combined search pagination and totals.
- [x] Preserve artifact chat relevance/capacity and truthful route metadata.
- [x] Check off the nine follow-up findings in the Story 4-4 spec and finalize the review report only after verification.

**Acceptance Criteria:**
- Given any review finding, when its regression runs against the remediated tree, then the specified failure is prevented and the test is non-vacuous against `bb81382`.
- Given all remediation, when the Story 4-4 verification suite runs, then server, eval, web, generated-client, and single-writer checks pass with no unresolved high/medium findings.

## Spec Change Log

- 2026-08-21: Implemented all nine follow-up findings and recorded fresh
  verification; frozen intent unchanged.
- 2026-08-21: Remediation re-review closed 13 findings in ten consolidated
  implementation/verification workstreams; one pre-existing embed-only Neo4j
  dependency was deferred.

## Design Notes

Artifact-first ordering is retained: the paging repair treats ranked artifacts as the leading finite lane, then moments, so offsets remain deterministic without pretending scores from different indexes are calibrated. “Evidence-equivalent” replacement means the unique live moment containing the old source instant; an exact-start replacement is naturally included. Provenance must preserve the first original source across repeated remaps and record each transition.

## Verification

**Commands:**
- `cd server && uv run pytest tests/test_worker_moments.py tests/test_projections_search.py tests/test_projections_rebuild.py tests/test_projections_locks.py tests/test_config.py tests/test_api_search.py tests/test_api_chat.py -q`
- `cd server && uv run pytest tests/ -q`
- `make evals-test`
- `make web-test`
- `make client` followed by a generated-client diff check
- `rg -n "import neo4j|import meilisearch|from neo4j|from meilisearch" server/meetingminer/api` — expected: no matches

**Result (2026-08-21):** 254 targeted server tests passed; the full server
suite passed (1,587 tests); `make evals-test` passed (548 tests); `make
web-test` passed (207 tests); regeneration from this worktree's OpenAPI schema
left `web/src/client/` unchanged; and the API store-import scan returned no
matches. `make evals-run` was not run, as prohibited by this remediation.
The focused regression set was also applied to `bb81382`: 13 of 14 selected
cases failed on the original defects. The one passing case checks mixed-lane
de-duplication; its paired artifact-only telemetry case failed there, so the
finding's regression remains non-vacuous.

## Suggested Review Order

**Augmentation evidence integrity**

- Lock, validate, and remap every artifact through its original evidence instant.
  [`moments.py:127`](../../server/meetingminer/pipeline/stages/moments.py#L127)

- Shift replacement spans across repeated remaps to expose source-instant drift.
  [`test_worker_moments.py:817`](../../server/tests/test_worker_moments.py#L817)

**Locked projections and keyword-only schema**

- Re-read published rows only after both projection locks are held.
  [`__init__.py:590`](../../server/meetingminer/projections/__init__.py#L590)

- Inspect artifact embedders before submitting any schema mutation.
  [`stores.py:416`](../../server/meetingminer/projections/stores.py#L416)

- Prove a lock-wait remap becomes the projected CITES edge and document.
  [`test_projections_search.py:757`](../../server/tests/test_projections_search.py#L757)

- Assert the artifact initializer's exact Neo4j schema delta.
  [`test_projections_graph.py:56`](../../server/tests/test_projections_graph.py#L56)

**Stable retrieval semantics**

- Partition the finite artifact-first sequence with an exhaustive lane count.
  [`search.py:407`](../../server/meetingminer/api/search.py#L407)

- Obtain exhaustive artifact totals without sacrificing arbitrary offsets.
  [`query.py:747`](../../server/meetingminer/projections/query.py#L747)

- Separate prompt-capacity priority from traversal-first presentation order.
  [`chat.py:925`](../../server/meetingminer/api/chat.py#L925)

- Pin stale-slot exact-once paging across adjacent global pages.
  [`test_api_search.py:1127`](../../server/tests/test_api_search.py#L1127)

- Fill the prompt budget while preserving traversal semantics and artifact evidence.
  [`test_api_chat.py:1616`](../../server/tests/test_api_chat.py#L1616)
