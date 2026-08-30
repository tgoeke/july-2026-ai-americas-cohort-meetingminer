# Epic 5 Context: Eval Harness & Runbook

<!-- Generated from planning artifacts. Regenerate with compile-epic-context if planning docs change. -->

## Goal

An operator can execute a complete eval run against scripted YAML ground truth using only a written runbook — no tribal knowledge required. The run exercises deterministic-first, tiered judging: machine-checked capture recall, over-capture guardrail, view classification, dedup quality, doc-index search recall@5, and a publish-gate projection assert, plus an optional LLM judge tier selected by a bake-off against human gold verdicts. Every run writes immutable artifacts with a full resolved config snapshot, so quality claims for the whole system are auditable rather than asserted. This epic is deliberately sequenced to complete before any demo-script work begins.

## Stories

- Story 5.1: Ground-Truth Schema & Scripted Fixtures
- Story 5.2: Deterministic Capture Checks with Immutable Run Artifacts
- Story 5.3: Retrieval & Publish-Gate Checks
- Story 5.4: LLM Judge Harness & Bake-Off (nice-to-have)
- Story 5.5: Eval Runbook & Documented-Only Designs

## Requirements & Constraints

- Ground-truth is machine-readable YAML per meeting script, declaring meeting metadata, archetype (slide-deck | ui-demo), slides/screens each with a unique distinctive `ocr_anchor`, participant segments, planted action items/decisions/phrases with timestamps, and `qa` entries. Missing or duplicate anchors fail validation. The expected screenshot count (recall denominator) equals slides/screens + participant segments.
- Eval subject selection is by corpus tag: only meetings with `corpus: "scripted"` are matched to ground-truth manifests, by `sourceId`. Meetings with `corpus: "real"` (the ~25-meeting pulled archive) are ingested demo corpus and are never eval subjects.
- Deterministic (tier-1/BUILD) checks and their pass bars:
  - Capture recall (2.1): every manifest `ocr_anchor` must match a captured screenshot's OCR text (normalized, fuzzy token-set ≥ 0.8); any recall below 100% fails the run — no exceptions.
  - Over-capture guardrail (2.2): captures must stay under one per minute of meeting duration (fails when count > ceil(duration_minutes)).
  - View classification accuracy (2.3): reported against manifest-implied labels.
  - Dedup quality candidates (2.4): sequential-capture OCR similarity > 0.9 pairs are listed for human judging, never auto-collapsed — the system stays biased toward over-capture over loss.
  - Doc-index search recall@5 (2.10): each planted phrase, queried against Meilisearch, must return a moment from its containing meeting in the top 5 (recall@5 = 1.0 or the run fails).
  - Publish-gate projection assert (2.11): asserts an artifact appears in neither retrieval store before approval, approves it via the public API, then asserts it appears in both with citations resolving to its source moment.
- The eval harness is a client only — it mutates state solely through the public API (`POST /ingests`, approval/publish endpoints) and asserts only through API reads and read-only store queries. It never imports server modules to mutate state, so it exercises the exact publish gate it verifies.
- Every run writes to an immutable `evals/runs/<run-id>/` folder containing `deterministic-report.yaml` (and, when tier-2 runs, `llm-judge-report.yaml`) plus the full resolved `config.yaml` snapshot; the folder is immutable after verdict.
- LLM judge (tier-2, nice-to-have): the model is chosen by a bake-off across three pools — frontier APIs, local Ollama, hosted open-weight — graded on agreement with prior human gold verdicts, run before the first full eval run, and pinned by exact model id in run metadata (`evals/runs/bakeoff-<date>/`). Cloud judge candidates receive derived data only (transcript snippets, extracted artifacts) — never recordings. A later judge-model change invalidates prior verdicts and triggers the rerun rule; the same rule fires on any pipeline change or embedder change (an embedder swap forces a full projection rebuild).
- A written runbook must let an operator without tribal knowledge complete: preconditions, deterministic suite, failure triage (pipeline bug | script error | genuine miss), optional LLM judging, human judging worksheets recorded in `human-verdicts.yaml` (human verdict wins any disagreement, one-line reason per item), final verdict in `verdict.md` (PASS only if recall = 100%, guardrail holds, and no human fail), archive, and the rerun rule.
- Documented-only (design, no implementation) commitments that close out this epic: the citation timestamp-window check (±15s), action-item fuzzy set-match, eval cadence (change-triggered + go-to-prod gate), and the full retrieval eval design (recall@k, exact-set graph traversal comparison).
- Sequencing: this epic must be complete before any demo-script work begins — a hard project-level gate, not a per-story concern.

## Technical Decisions

- Implementation shape is a pytest project: YAML fixtures under `evals/ground-truth/`, tier-1 checks as plain pytest tests, tier-2 as marked tests, and a small plugin that creates the run folder and writes immutable artifacts (models, prompts, thresholds recorded per run).
- Ingest submission semantics the harness must respect: a `sourceId` that already has a non-failed job gets an RFC 9457 conflict — re-processing is a rerun of the existing job, never a second Meeting row. No folder watcher exists; dropping files never ingests anything. (A drop declaring it augments an existing meeting is the one accepted exception; scripted eval fixtures should not need it.)
- Evidence files live under two configured storage roots — arrived material under the drops root, pipeline-produced files (frames, screenshots) under the content root keyed by meeting id — each with a Postgres row carrying its root-relative path, sha256, and byte size. The harness locates captured screenshots via API reads or those rows resolved against configured roots, never by scanning directories. Both root locations are environment variables, deliberately kept outside the versioned config, so they never appear in a run's config snapshot.
- All model interaction, including the judge, goes through project-owned adapter ports (judge role via LiteLLM); a single versioned `config.yaml` declares every binding, and its fully resolved contents are snapshotted per run. Swapping a candidate is a config edit, never a code change.
- Citation and retrieval assertions read the API's structured `citations` array (`momentId`, `meetingId`, `startMs`, `endMs`, optional `screenshotId`, optional `sourceDeepLink`) — resolved from inline `[[moment:<uuid>]]` markers by the API's deterministic validator — never parsed inline markers directly.
- Entity identifiers are UUIDv7 minted in Postgres and carried verbatim into both retrieval stores, API payloads, and citations, so checks can assert identity across stores directly. Video offsets are integer milliseconds from recording start; wall-clock times are ISO 8601 UTC.
- Egress is unrestricted system-wide; the one standing restriction scoped to eval is that cloud judges receive derived data only — enforced at the judge role itself, not via a separate allowlist component ("allowed endpoints" resolves to provider endpoints already declared in `config.yaml`).

## Cross-Story Dependencies

- Story 5.1's validated schema and scripted fixtures are the shared ground truth every later story checks against; 5.2 and 5.3 cannot run meaningfully without it.
- Stories 5.2 and 5.3 both append to the same run's `deterministic-report.yaml` under one immutability rule — two check batches over one run artifact, not independent runs.
- Story 5.4 (LLM judge, nice-to-have) depends on tier-1 (5.2, 5.3) running first; its bake-off must complete before the first full eval run so the winning model is pinned going in, and the runbook must treat LLM judging as optional.
- Story 5.5's runbook packages and sequences 5.1–5.4 into one operator-executable procedure and carries the documented-only design commitments that close the epic.
- This epic depends on Epic 1 (ingestion pipeline and evidence bundle, including the capture-density retune), Epic 3 (Meilisearch-backed search and the citation validator), and Epic 4 (artifact lifecycle and the projection publish gate) already being in place, since its checks assert against their behavior via the public API.
- Project-level: NFR12 makes this epic a hard predecessor to demo-script work — nothing downstream may begin that work until Epic 5 is declared done.
