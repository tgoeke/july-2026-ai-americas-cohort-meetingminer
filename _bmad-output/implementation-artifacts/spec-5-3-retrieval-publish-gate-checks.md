---
title: 'Story 5.3: Retrieval & Publish-Gate Checks'
type: 'feature'
created: '2026-08-21'
status: 'done'
baseline_revision: 'b82ff7e7689844579154e397e87c16c360ef6ad9'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/specs/spec-meetingminer/eval-design.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-5-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-5-2-deterministic-capture-checks.md'
warnings:
  - 'oversized'
  - 'Story 4-4 (published artifacts projected into the stores) is backlog. Check 2.11''s post-approval half asserts a contract with no implementation yet: once real eval subjects exist it will FAIL until 4-4 lands. That failure is the check working. Never weaken, skip, or green it.'
  - 'Both ground-truth fixtures still carry placeholder source_id values, so every live run fails the zero-subject gate before these checks execute. Expected; do not relax anything to get green.'
  - 'Story 2-8 is in flight; zero file overlap. `make evals-run` is one-at-a-time and this story never runs it.'
deferred:
  - summary: >-
      The harness's HTTP timeouts are hardcoded (10s) with no override path
      from `make evals-run`.
    evidence: |-
      retrieval.py's DEFAULT_TIMEOUT is 10.0 and the check callers pass no
      override. A hybrid search waiting on the embedder, or an approve that
      fans out projections once story 4-4 lands, has no configurable timeout
      from the make target, and a timeout surfaces as a whole-check
      not-applicable rather than a per-phrase record. Will matter at the
      first live run after 4-4; harmless until then.
    location: >-
      evals/harness/retrieval.py
    severity: low
---

<intent-contract>

## Intent

**Problem:** The SPEC's two hardest promises — a verbatim planted phrase is findable, and an
unpublished artifact never reaches a retrieval store — are asserted by nobody. Tier-1 (5.2) covers
capture only; checks 2.10 and 2.11 exist solely as design text.

**Approach:** Add checks 2.10 (doc-index search recall@5) and 2.11 (publish-gate projection assert)
to the existing tier-1 harness: pure result-assembly in `evals/harness/`, a search call through the
public `GET /search`, read-only Meilisearch/Neo4j membership reads, approval through
`POST /moments/{id}/approve`, results appended to the same run's `deterministic-report.yaml` under
the same immutability and completeness rules.

## Boundaries & Constraints

**Always:**
- AD-16 holds: the harness mutates the system **only** through the public API — the one sanctioned
  mutation here is `POST /moments/{moment_id}/approve` — and asserts only through API reads,
  read-only store queries, and run artifacts.
- Check 2.10 queries the public `GET /search` (per `evals/designs/retrieval-eval.md` leg 1), one
  query per `planted.phrases` entry, `limit=5`, no corpus filter — the index gets no help. Pass per
  phrase iff some hit's `meetingId` equals the subject's meeting id; recall@5 = 1.0 or the run
  fails (blocking). Per-phrase rank, `ranking` mode, and `indexMissing` are recorded in details.
- Check 2.11 discovers artifacts and their lifecycle state through the read-only corpus connection
  (`artifacts_for`), asserts store membership through direct **read-only** Meilisearch and Neo4j
  reads, and approves through the public API only. Sequence per subject: assert every
  non-`published` artifact absent from both stores → approve → assert every newly `published`
  artifact present in both, with citations resolving to its source moment (Meilisearch document
  `momentIds` contains `artifact.moment_id`; the graph node relates to that `Moment`). Any
  violation fails the run (blocking).
- 2.11 mutates only meetings whose `corpus` is `scripted`. Refuse (named failure, no API call) if a
  selected subject's meeting is not scripted — the real corpus is never approved by a machine.
- Both check names join `REQUIRED_CHECKS`: every selected subject must record both results
  (measured or not-applicable) or the run fails on completeness.
- Unmeasurable states are recorded, never skipped: no planted phrases, no artifacts, no
  `extracted` artifacts, store unreachable, `indexMissing` — each records a blocking
  not-applicable/failed result naming the cause, mirroring the `CorpusQueryError` pattern.
- Every threshold (k=5, recall 1.0) is written into the report beside its result (eval-design §6).
- Boundary guards are extended, never weakened: the new network module joins the exact httpx set;
  new `meilisearch`/`neo4j` one-module guards pin the store-reads module; the store-reads module is
  pinned to read-only usage (no write-method references) by a boundary test.
- `make evals-test` stays store-free: no store, no api, no run folder.
- Store credentials come through `meetingminer.config` (the one named allowance) — never a second
  `.env` parsing path.

**Block If:**
- The Meilisearch key or Neo4j password are not reachable through `AppConfig` secrets and the only
  alternative is parsing `.env` directly or importing a forbidden server module — halt rather than
  widen the boundary.

**Never:**
- No change under `server/`. Story 4-4 owns the projection-on-publish wiring; this story verifies
  the contract, it does not implement it.
- No new dependency: `httpx`, `meilisearch`, `neo4j`, `psycopg` are already in `server/pyproject.toml`.
- No topic probes, no graph-traversal leg, no Q&A leg — documented-only (`retrieval-eval.md`).
- No store writes of any kind; no `make evals-run`; no fixture `source_id` edits.
- No direct Meilisearch query for 2.10 — the public `/search` is the surface under test.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Phrase found | Hit with subject's meetingId at rank ≤ 5 | Per-phrase pass, rank recorded | No error expected |
| Phrase missed | No such hit in top 5 | Run fails naming phrase id, text, and the top-5 (momentId, meetingId, score) it got | Check failure |
| Manifest has no phrases | `planted.phrases` absent/empty | Blocking not-applicable naming the manifest — never a vacuous pass | Named failure |
| Index never built | `indexMissing: true` | Blocking failure naming the missing index | Check failure |
| Degraded ranking | `ranking: "keyword"` (embedder down) | Recorded in details; verbatim plants must still be found — not itself a failure | No error expected |
| Search API refuses | 503 `search-store-unavailable` etc. | Blocking not-applicable carrying the problem slug | Named failure |
| Gate violated pre-approval | Non-published artifact found in either store | Run fails naming store, artifact id, state — the headline violation | Check failure |
| Approve then absent | Published artifact missing from either store | Run fails naming the absent store (expected until 4-4) | Check failure |
| Citation unresolved | Present in store but `momentIds`/graph edge lacks `artifact.moment_id` | Run fails naming artifact and moment | Check failure |
| No artifacts at all | Extract stage never ran for the subject | Blocking not-applicable naming the meeting | Named failure |
| Nothing left to approve | Artifacts exist but none `extracted` | Positive half still asserted for `published` rows; gate half blocking not-applicable naming the state distribution (one-way lifecycle consumed it) | Named failure |
| Approve refused | 409 `nothing-to-approve` / `meeting-not-viewable`, 404 | Blocking failure carrying the problem slug | Named failure |
| Store unreachable | Meilisearch or Neo4j down | Blocking not-applicable; diagnosis kept in run problems | Named failure |
| Store-free suite | `make evals-test` | All unit tests pass; no store, api, or folder touched | No error expected |

</intent-contract>

## Code Map

- `evals/harness/checks.py:45-70` — check-name constants and thresholds; add `DOC_INDEX_SEARCH_RECALL`
  and `PUBLISH_GATE_PROJECTION` beside them. `CheckResult` :111 (`blocking`, `thresholds`,
  `to_dict`), `RecallResult` :188, `not_applicable` :200 — the result vocabulary; add nothing new.
- `evals/harness/run.py:117-125` `REQUIRED_CHECKS` — add both names; `_completeness_problems` :309
  and `Run.passed` :328 then enforce them per subject. `:352-359` the report payload's hardcoded
  `"story": "5.2 — ..."` string — update to cover 2.1–2.4 + 2.10–2.11. `Run.record` :304,
  `Run.note` :277.
- `evals/harness/subjects.py:43` `Subject` (`meeting_id`, `viewable`); `:198` `fetch_meetings` —
  the httpx idiom (timeout, injectable `transport`) the new search call mirrors.
- `evals/harness/groundtruth.py:165` `Manifest.planted`; `PLANTED_SECTIONS` :52; phrases items are
  `{id, text, speaker, at}` (schema `$defs/planted_item`); `planted` is not required top-level.
- `evals/harness/corpus.py:285` `artifacts_for` → `ArtifactRow(id, moment_id, kind, state, title,
  body)` — 2.11's discovery/state read already exists; no new SQL needed.
- `server/meetingminer/api/search.py:265-303` `GET /search` — params `q` (1–512 chars), `limit`,
  `offset`, `meetingId`, `corpus`; `SearchHit` :103 (`momentId`, `meetingId`, `score`),
  `SearchResponse` :135 (`ranking`, `indexMissing`). Read-only reference; do not edit.
- `server/meetingminer/api/moments.py:607-613` `POST /moments/{moment_id}/approve` — no body,
  returns all the moment's artifacts post-call; 404 / 409 `meeting-not-viewable` /
  409 `nothing-to-approve`. `GET /meetings/{meetingId}/moments` :482. Read-only reference.
- `server/meetingminer/projections/publish_gate.py:33` `ARTIFACTS_INDEX = "artifacts"`;
  `artifact_document` :102 (`momentIds` list) — the document shape 2.11's positive half expects.
  **No production caller exists** (4-4 backlog): grep confirms nothing projects artifacts.
- `server/meetingminer/projections/stores.py:91-122` — how the server builds Neo4j
  (`stores.neo4j.uri` + `NEO4J_PASSWORD`) and Meilisearch (`stores.meilisearch.url` +
  `MEILI_MASTER_KEY`) clients from settings+secrets; mirror in the harness store-reads module,
  read-only. `graph.py` writes labels `Meeting/Moment/Screenshot/Chunk/Screen/Participant` — no
  `Artifact` label yet; 2.11 asserts on artifact id, tolerant of the label 4-4 chooses (match any
  node whose `id` property equals the artifact UUID).
- `evals/tests/test_harness_boundary.py:96` walked-files pin; `:173` exact per-file server-import
  dict; `:222` httpx set `{"subjects.py", "judge.py"}`; `:246` psycopg set `{"corpus.py"}` — all
  four extend. Precedent for widening: judge.py in 5.4.
- `evals/checks/test_capture_checks.py:29` `_record` — run-or-record-why with `blocking` threaded
  through; reuse the shape. `evals/checks/test_corpus_artifacts.py:40-124` — seed/cleanup template
  if store-backed tests need artifact rows.
- `evals/conftest.py:153` subject parametrization; `:260` `read_evidence`'s unmeasurable-Evidence
  pattern to mirror for store-reachability failures.
- `infra/Makefile:88-93` help text names "capture checks (2.1-2.4)"; `:322` `evals-run` prereqs
  already include `check-stores check-api` — no new prerequisite.
- `evals/README.md:24-34` stale "still to come"; `:202-208` check table; `:324-343` triage.
  `evals/RUNBOOK.md:13-16`, `:190-196` thresholds table, `:204-206` `[arrives with story 5.3]`
  markers, Step 3 triage classes.
- `_bmad-output/specs/spec-meetingminer/eval-design.md:163-170` §2.10/§2.11 — contract of record;
  gains an additive note (same discipline as 5.2's §2.4a).

## Tasks & Acceptance

**Execution:**
- `evals/harness/checks.py` — extend, pure: the two name constants and thresholds;
  `search_recall(manifest, hits_by_phrase)` scoring per-phrase containing-meeting membership in the
  top 5; `publish_gate(artifacts, pre_membership, approve_outcome, post_membership)` assembling the
  2.11 result from observations gathered by the test layer. No I/O here.
- `evals/harness/retrieval.py` — new, httpx: `search_hits(base_url, phrase, *, limit=5, timeout,
  transport=None)` returning hits plus `ranking`/`indexMissing`, mirroring `fetch_meetings`'s shape.
- `evals/harness/stores.py` — new, the only module importing `meilisearch`/`neo4j`: read-only
  membership reads `artifact_in_search(artifact_id)` (get-document against `artifacts`; a missing
  index reads as absent) and `artifact_in_graph(artifact_id)` (match any node with that `id`,
  session `default_access_mode=READ`), each returning presence plus cited moment ids; built from
  `AppConfig` settings+secrets. Connection failures raise a named error the test layer records.
- `evals/harness/run.py` — extend: both names into `REQUIRED_CHECKS`; report `story` string.
- `evals/checks/test_retrieval_checks.py` — new, store-backed: check 2.10 per subject via
  `retrieval.search_hits`, recording through the `_record` shape; phrase-less manifests record the
  blocking not-applicable.
- `evals/checks/test_publish_gate.py` — new, store-backed: check 2.11 per subject — corpus
  discovery, scripted-corpus refusal, pre-assert, API approve, post-assert, citation resolution;
  unmeasurable states recorded per the matrix.
- `evals/tests/test_retrieval.py` — new, store-free: `search_recall` over synthetic hits (every
  matrix row that is not store-backed: rank boundary at 5, missing phrase, empty phrases,
  indexMissing, keyword ranking recorded).
- `evals/tests/test_publish_gate_algorithm.py` — new, store-free: `publish_gate` assembly over
  synthetic observations (pre-violation, post-absence per store, citation mismatch, consumed
  lifecycle, refusal outcomes).
- `evals/tests/test_run_artifacts.py`, `evals/tests/test_check_recording.py` — extend: the
  completeness assertions now expect seven required checks.
- `evals/tests/test_harness_boundary.py` — extend: walked-files pin, per-file import dict, httpx
  set + `retrieval.py`, new one-module guards for `meilisearch` and `neo4j` pinned to `stores.py`,
  and a read-only pin that `stores.py` never references the write-method names
  (`add_documents`, `delete`, `update`, `execute_write`).
- `evals/README.md`, `evals/RUNBOOK.md` — extend: shipped-so-far, check table rows for 2.10/2.11
  with gate semantics, thresholds-in-force, triage classes (verbatim-phrase miss = pipeline bug;
  post-approval absence = missing 4-4 wiring vs regression), remove the arrival markers, and the
  2.11 state-consumption note (one-way lifecycle: a full gate measurement needs an unconsumed
  `extracted` artifact; rerun implications).
- `infra/Makefile` — help text: checks 2.1–2.4 → 2.1–2.4, 2.10–2.11.
- `_bmad-output/specs/spec-meetingminer/eval-design.md` — additive note (§2.10a/§2.11a style)
  recording the decisions made precise here: 2.10 is asserted through the public `GET /search`
  (AD-16), unfiltered; 2.11's "before approval" means every non-`published` row, membership is
  asserted by direct read-only store reads because absence has no API surface (AD-4), and
  "citations resolving" means the projected document's `momentIds` / graph edge reaching the
  artifact's `moment_id`.

**Acceptance Criteria:**
- Given a subject with planted phrases all findable, when 2.10 runs, then recall is 1.0, the check
  passes, and each phrase's rank, the ranking mode, and thresholds are in the report.
- Given any phrase absent from the top 5, when 2.10 runs, then the run fails naming the phrase and
  the hits it got instead.
- Given a subject with artifacts, when 2.11 runs, then the report carries the pre-approval
  membership of every artifact, the approve outcome, and the post-approval membership with
  citation resolution — and any violation fails the run.
- Given both checks recorded, when the report is written, then their results sit in the same
  `deterministic-report.yaml` under the same write-once rule, and a subject missing either check
  fails the run on completeness.
- Given `make evals-test`, when it runs, then it passes with no store, no api, and no run folder.
- Given the boundary tests, when a second module imports httpx, meilisearch, neo4j, or psycopg, or
  `stores.py` references a store write method, then a test fails naming it.

## Design Notes

**2.10 rides `GET /search`, not raw Meilisearch.** `retrieval-eval.md` leg 1 says "through the
public api (AD-16)" explicitly. The surface users hit is what the promise is about; a raw index
query would pass while the route is broken. `ranking: "keyword"` degradation is recorded, not
failed — verbatim plants must survive keyword ranking, and failing on embedder downtime would
misattribute the miss.

**2.11 membership is a direct read-only store read, by necessity and by license.** AD-4 makes
unpublished artifacts visible *only* through Postgres API reads — absence from the stores has no
API surface, and `/search` deliberately excludes the `artifacts` index, so "assert it appears in
NEITHER store" cannot be an API read. AD-16 sanctions "read-only store queries" for exactly this.
`retrieval-eval.md`'s looser sentence ("api-visible behavior plus the corpus connection") cannot
implement eval-design §2.11's literal store assert; the contract of record wins and the additive
eval-design note records the resolution.

**The positive half asserts a contract that does not exist yet.** Story 4-4 (backlog) wires
projection-on-publish; today nothing writes an artifact to either store. Pre-approval absence will
pass; post-approval presence will fail once real subjects exist. That is the check defending the
gate, exactly as 5.2's zero-subject failure defends *no silent zero*. Graph assertion matches on
the artifact's UUID as a node `id` property rather than a label, so 4-4's label choice cannot
quietly evade it.

**2.11 consumes state.** The lifecycle is one-way with no unpublish; approving during a run means
the next run finds nothing `extracted` and records the gate half unmeasurable. That is inherent to
verifying a one-way gate against a shared corpus, documented in the RUNBOOK rather than papered
over with a store write the harness must never make.

## Verification

**Commands:**
- `make evals-test` -- expected: passes, store-free; includes the new algorithm, guard, and
  completeness tests; no run folder afterwards.
- `uvx ruff check --isolated evals/` -- expected: clean.
- `uv run --project server pytest evals/checks -q` -- expected: **fails** on the zero-subject gate
  naming both placeholder manifests (a green run means the selector or a failure was weakened).
  Store-backed — concurrency-safe since 2.7; announce before running. Never `make evals-run`.
- `git diff --name-only main...HEAD -- server/` -- expected: empty; this story touches nothing
  under `server/`.

**Manual checks:**
- Confirm each new store-free regression test fails against the unmodified code before completion.
- Confirm `evals/runs/` holds no folder after `make evals-test`.

## Review Triage Log

### Review Findings — External code review (2026-08-21)

- [x] [Review][Patch] Reject a non-local API target before publish-gate observation or approval [evals/checks/test_publish_gate.py:165] — decision resolved 2026-08-21: 2.11 is local-only because its Postgres/Meilisearch/Neo4j reads come from local `AppConfig`; fixed in `3fdf03a`.
- [x] [Review][Patch] Reject malformed search metadata instead of converting it into a passing observation [evals/harness/retrieval.py:145] — fixed in `3fdf03a`.
- [x] [Review][Patch] Translate malformed Neo4j result records into the named store-read failure [evals/harness/stores.py:206] — fixed in `3fdf03a`.
- [x] [Review][Patch] Make the retrieval observation-set guard symmetric [evals/harness/checks.py:815] — fixed in `3fdf03a`.
- [x] [Review][Patch] Persist the effective API endpoint in the immutable run snapshot [evals/conftest.py:197] — fixed in `3fdf03a`.

### 2026-08-21 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 14: (high 0, medium 7, low 7)
- defer: 1: (high 0, medium 0, low 1)
- reject: 9: (high 0, medium 0, low 9)
- addressed_findings:
  - `[medium]` `[patch]` Boundary read-only pin missed suffixed write methods
    (`update_documents` etc.) — now matches stems, with self-tests over the
    real write surface.
  - `[medium]` `[patch]` `publish_gate` silently skipped the citation assert
    for an approve-returned id discovery never saw — now a loud divergence.
  - `[low]` `[patch]` A successful approval with an empty publish set could
    pass the positive half having verified nothing — now a divergence.
  - `[medium]` `[patch]` `artifact_in_search` coupled to the client Document's
    `__dict__` — now attribute-first/mapping-fallback, unreadable shape is a
    named `StoreAssertError`.
  - `[low]` `[patch]` `artifact_in_graph` `.single()` raised on duplicated
    node ids — now collects and merges, with a multiplicity note.
  - `[low]` `[patch]` Retrieval status guards were `>= 400`, letting 3xx die
    as a JSON shape error — now `!= 200`.
  - `[medium]` `[patch]` One phrase-query failure aborted check 2.10 and
    discarded gathered evidence, without `run.note` — per-phrase capture now,
    not-applicable only when nothing was measurable.
  - `[low]` `[patch]` The corpus-refusal CheckResult carried no
    thresholds/metrics — now shares `PUBLISH_GATE_THRESHOLDS`.
  - `[medium]` `[patch]` Store-handle construction errors other than
    `StoreAssertError` left the check unrecorded — record-and-reraise now,
    closing a partially constructed driver.
  - `[medium]` `[patch]` `Corpus.meeting_corpus` had zero executed coverage —
    seeded/missing-row pair added to `test_corpus_artifacts.py`.
  - `[medium]` `[patch]` The scripted-corpus refusal was unreachable by any
    test — extracted as pure `publish_gate_refusal`, pinned store-free,
    distinguishing a vanished row from a mis-tagged one.
  - `[low]` `[patch]` `search_recall` hardened: hits sliced to k, stray
    outcome keys reported as divergence.
  - `[low]` `[patch]` Detail key `published_after_approval` was untrue for
    already-published rows — renamed `asserted_published`.
  - `[low]` `[patch]` The artifact's assert-set note cited §2.11a text that
    did not exist — §2.11a gained the bullet.

Rejected as noise: duplicate phrase ids and empty phrase text (the 5-1
schema/loader makes both unreachable on the validated path), the meilisearch
client "never closed" (the client exposes no close API), README narrating
story 5.4 (5.4 is done; reviewer asymmetry), check fixtures "missing from the
diff" (they pre-date this story in `evals/conftest.py`), special-casing a
`ranking: "unknown"` fallback (informational field, recorded verbatim),
`int()` timeout truncation and a list `not in` (cosmetic), stale-state
concern on partial approve (the approve route commits atomically), and the
approved-state misattribution (the state distribution is already named).

## Auto Run Result

Status: done

**Review findings breakdown.** 14 patches applied (0 high, 7 medium, 7 low),
1 deferred (frontmatter), 9 rejected. Follow-up review recommended: **true**
— score = 3×7 + 1×7 = 28 ≥ 5, no high.

**Implemented change.** Checks 2.10 and 2.11 in the tier-1 harness. Pure
result assembly in `evals/harness/checks.py` (`search_recall`,
`publish_gate`, plus `SearchHit`/`PhraseSearch`/`StorePresence`/
`ApproveOutcome` and the name/threshold constants); `evals/harness/retrieval.py`
(httpx: unfiltered `GET /search` at `limit=5`, and `POST /moments/{id}/approve`
— the one sanctioned mutation — both carrying RFC 9457 problem slugs into
named errors); `evals/harness/stores.py` (the only meilisearch/neo4j importer:
`artifact_in_search` via get-document against `artifacts` — a missing index
reads as absent — and `artifact_in_graph` matching any node by `id` property,
session `default_access_mode=READ`, built from `AppConfig` settings+secrets).
`corpus.py` gained `meeting_corpus(meeting_id)` so 2.11's scripted-corpus
refusal re-reads the tag from the database the approval would mutate, before
any api call. Both names joined `REQUIRED_CHECKS`; the report `story` string
now covers §2.1-2.4 + §2.10-2.11.

**Files changed.**
- `evals/harness/checks.py`, `retrieval.py` (new), `stores.py` (new),
  `corpus.py`, `run.py`
- `evals/checks/test_retrieval_checks.py` (new), `test_publish_gate.py` (new)
- `evals/tests/test_retrieval.py` (new), `test_publish_gate_algorithm.py`
  (new), `test_run_artifacts.py`, `test_check_recording.py`,
  `test_harness_boundary.py` (walked-files pin, httpx set + `retrieval.py`,
  meilisearch/neo4j one-module guards scoped over the whole `evals/` tree,
  word-bounded write-method pin on `stores.py`)
- `evals/README.md`, `evals/RUNBOOK.md` (check table rows, gate semantics,
  triage classes, state-consumption note, arrival markers removed),
  `infra/Makefile` help text, `eval-design.md` additive §2.11a.

**Verification performed.**
- `make evals-test` → **499 passed**, store-free; `evals/runs/` absent after.
- `uvx ruff check --isolated evals/` → clean (after fixing three ISC004).
- `uv run --project server pytest evals/checks -q` → **2 failed, 5 passed,
  7 skipped** — the designed result: both failures are the zero-subject gate
  naming both placeholder manifests; the 7 skips are the per-subject checks
  (five capture + the two new) with an empty parametrization. The
  verification run folder it created was deleted (it measured nothing).
- `git diff --name-only main...HEAD -- server/` → empty.
- Mutation-bite checks: weakening `indexMissing` handling, disabling the
  pre-approval GATE VIOLATION branch, and dropping the two names from
  `REQUIRED_CHECKS` each made the corresponding new store-free test fail.

**Residual risks.**
- The two store-backed check tests have never executed against a real
  subject (placeholder `source_id`s). When they do, 2.11's post-approval half
  will FAIL until story 4-4 wires projection-on-publish — that is the check
  working (frontmatter warning; §2.11a; RUNBOOK step 3).
- `stores.py`'s live reads (get-document shape, the label-agnostic Cypher)
  are exercised only through the store-free error/shape paths until real
  subjects and 4-4 exist; the read functions themselves have no store-backed
  seed test the way `corpus.artifacts_for` does, because seeding a store
  would be the write the harness must never make.
- `retrieval.approve_moment` treats any `state == "published"` row in the
  response as part of the positive assert set, so a row published by an
  earlier call is asserted too. Recorded in eval-design §2.11a (the
  positive-half-assert-set bullet, added in the review pass) and in
  `publish_gate`'s docstring: the assert binds the published *state*, not
  the transition this run happened to drive.

## Review Remediation — 2026-08-21

14 triaged patches applied (medium 7, low 7); the intent-contract is
unchanged. What each fixed:

- **P1** boundary read-only pin now matches write-method *stems* with a
  `\b<stem>\w*` pattern (`add_document`, `delete`, `update`, `create_index`,
  `execute_write`), so `update_documents`/`delete_index`/
  `add_documents_in_batches` are caught — the exact-name `\b...\b` version
  missed every suffixed form (underscore is a word character). Self-tests
  pin the real Meilisearch/Neo4j write surface and benign read vocabulary.
- **P2/P3** `publish_gate` now reports two more divergences loudly: a
  published id discovery never saw (citation unverified), and a successful
  approval with an empty publish set (the positive half verified nothing).
- **P4** `stores.artifact_in_search` reads `momentIds` attribute-first then
  mapping, and a present-but-unreadable document shape is a named
  `StoreAssertError` — never a silent empty citation list.
- **P5** `stores.artifact_in_graph` collects all records instead of
  `.single()`: duplicated ids merge moments and carry a multiplicity `note`
  on the presence (new `StorePresence.note` field) rather than softening
  into a not-applicable.
- **P6** both retrieval status guards are `!= 200`, so a 3xx is a named
  "the api answered 307" refusal.
- **P7** check 2.10's query loop captures per-phrase `RetrievalReadError`s
  (new `search_recall(..., unqueried=...)` channel), keeps successful
  outcomes, notes the run, and records the blocking not-applicable only when
  nothing was measurable.
- **P8/P11** the scripted-corpus refusal is the pure
  `checks.publish_gate_refusal(meeting_id, tag)` — carrying the shared
  `PUBLISH_GATE_THRESHOLDS` and metrics, distinguishing a vanished meeting
  row from a mis-tagged one (never "corpus None") — pinned store-free in
  `test_publish_gate_algorithm.py`, so deleting the guard fails a test.
- **P9** store-handle construction in `test_publish_gate.py` records any
  non-`StoreAssertError` exception as a blocking not-applicable + run note
  and re-raises (the 5-2 record-and-reraise shape), closing the graph driver
  when partially constructed.
- **P10** `Corpus.meeting_corpus` gained executed store-backed coverage in
  `test_corpus_artifacts.py` (seeded tag and missing-row cases).
- **P12** `search_recall` slices hits to k before rank scanning and reports
  stray `hits_by_phrase` keys as a divergence.
- **P13** detail key `published_after_approval` renamed `asserted_published`.
- **P14** this artifact's assert-set note now points at real text
  (eval-design §2.11a gained the positive-half-assert-set bullet).

Teammate's `evals/tests/test_store_asserts.py` kept green and extended
(mapping-shaped document, unreadable shape, duplicated graph node); its
graph fakes now yield record lists to match the iteration read.

**Verification.** `make evals-test` → **536 passed**, store-free, no run
folder; `uvx ruff check --isolated evals/` clean;
`uv run --project server pytest evals/checks -q` → **2 failed, 7 passed,
7 skipped** (the designed zero-subject gate; the two new `meeting_corpus`
tests pass; the verification run folder was deleted). Mutation-bite runs
confirmed the new regressions fail against the unfixed behavior: the porous
write-method pin (planted `update_documents`), the disabled P2/P3
divergences, the `__dict__`-only document read, and the `>= 400` status
guard each failed their new test. One tooling note: `cp`-restoring a
mutated module can leave a stale `__pycache__` entry — cleared during
verification.
