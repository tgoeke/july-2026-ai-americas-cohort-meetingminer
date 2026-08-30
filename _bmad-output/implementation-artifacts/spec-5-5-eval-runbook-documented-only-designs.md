---
title: 'Story 5.5: Eval Runbook & Documented-Only Designs'
type: 'feature'
created: '2026-08-20'
status: 'done'
baseline_revision: '7e2dce571f03da3572dd5a9c04695973eaacb1f9'
review_loop_iteration: 0
followup_review_recommended: true
context: []
warnings: [multiple-goals, oversized]
deferred:
  - summary: >-
      No mechanical binding ties RUNBOOK.md and the design docs to the harness
      they describe; stories 5.3/5.4 can drift the runbook's check tables and
      step-6 gate with no failing signal.
    evidence: |-
      The runbook's check table, report-field table and PASS gate transcribe
      run.py/checks.py behavior by hand; verification is `make evals-test`
      unchanged plus manual walks, so a later harness change fails no test
      when the prose goes stale. The 5.3/5.4 builders must update the marked
      runbook sections when their checks land.
    location: >-
      evals/RUNBOOK.md
    severity: low
---

<intent-contract>

## Intent

**Problem:** The eval procedure lives as a design sketch (eval-design §4) plus harness mechanics scattered through `evals/README.md`; an operator without tribal knowledge cannot execute a full run and record a defensible verdict, and the four DOCUMENT-only check designs promised to instructors (±15s citation window, action-item fuzzy set-match, eval cadence, full retrieval eval design) exist only as few-line sketches (FR30, CAP-8).

**Approach:** Write `evals/RUNBOOK.md` — the self-contained operator procedure from preconditions through deterministic suite, triage, optional LLM judging, human judging worksheets, `human-verdicts.yaml`, `verdict.md`, archive, and the rerun rule — plus four standalone design documents under `evals/designs/`. Documentation only: no code, no schema, no Makefile change.

## Boundaries & Constraints

**Always:**
- Every command, file name, make target, option, threshold, and refusal behavior the runbook names must match the shipped code on this branch (story 5.1/5.2 harness). Verify each against the source before writing it down.
- State implementation status honestly: the deterministic suite today is the capture checks (eval-design §2.1–2.4 + duration agreement); retrieval/publish-gate checks arrive with story 5.3 and the LLM judge harness with story 5.4 (nice-to-have). Structure those procedure steps so the later stories slot in without restructuring.
- The runbook's success test is CAP-8's: an operator completes a run and records a verdict using only the runbook. Everything the operator must type, inspect, or write goes in the runbook itself.
- `verdict.md` PASS requires all three: capture recall = 100%, over-capture guardrail holds, no human verdict is a fail. Human verdict wins any disagreement, recorded per item with a one-line reason in `human-verdicts.yaml`.
- Threshold changes are recorded in the run's `verdict.md` and invalidate prior verdicts; any pipeline, embedder, or judge-model change triggers the rerun rule (fresh run folder, from step 1).
- Changes to `eval-design.md` are additive notes only — the discipline stories 5.1 and 5.2 used.

**Block If:**
- Documenting the procedure would require changing harness code, Makefile targets, or fixture files to make the documentation true.
- A file this story must edit is owned by an in-flight story (2-2, 4-1).

**Never:**
- No implementation of the four documented-only designs — deferred per `scope.md` ("design everything, build the slice").
- No new make targets, no `human-verdicts.yaml` schema validation code, no harness edits — `evals/harness/`, `evals/checks/`, `evals/tests/`, `evals/conftest.py`, `infra/`, `server/` stay untouched.
- No claim that a runnable command exists when it does not; no "TBD" sections.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Operator run today | Fixtures still carry placeholder `source_id`s | Runbook precondition step says the run exits non-zero at the zero-subject gate and this is an unmet precondition, not a FAIL verdict | Operator directed to the placeholder-replacement procedure (README:121) |
| Deterministic failure | `deterministic-report.yaml` shows a failed check | Runbook triage step classifies it: pipeline bug \| ground-truth script error \| genuine capture miss, using the report's named signatures | Script errors: fix YAML, note it, rerun; bugs and misses stay in the report |
| Human disagrees with a machine result | Deterministic or LLM-judge result contested | Human verdict recorded per item with one-line reason; human wins | Disagreement itself noted in `verdict.md` summary |
| Verdict already recorded | Run folder holds `verdict.md` | Harness refuses the folder (run.py behavior); runbook says start a new run | Rerun rule: new `--run-id`, from step 1 |
| Threshold recalibrated | Any §6 threshold changed | Change recorded in `verdict.md`; all prior verdicts invalidated | Fresh run required |

</intent-contract>

## Code Map

- `evals/README.md:24-28` -- says 5.5 ("the runbook with its human verdicts") is still to come; this story replaces that with links to `RUNBOOK.md` and `designs/`. `:237-338` already documents `make evals-run`, `EVAL_ARGS`, run-folder contents, immutability, zero-subject failure, and concrete triage signatures — the runbook links to and builds on these, never contradicts them.
- `evals/harness/run.py:52-55` -- artifact names: `deterministic-report.yaml`, `config-snapshot.yaml`, `VERDICT_NAME = "verdict.md"` ("its presence is what marks a folder closed"). `:236-252` refusal rules (verdict-closed folder; interrupted-run folder). `:327-337` `Run.passed`; `:116-124` the five `REQUIRED_CHECKS`. The runbook describes these behaviors verbatim-faithfully.
- `evals/harness/run.py:135-155,363-375` -- `--run-id`/`--run-label` validation (`^[A-Za-z0-9][A-Za-z0-9._-]*$`, ≤96 chars) and the default id `<UTC date>-<label|HHMMSS>`.
- `evals/harness/checks.py:45-76` -- check names and thresholds the runbook and design docs cite: anchor match ≥ 0.8, token similarity ≥ 0.85, recall 1.0, dedup > 0.9, duration tolerance 1.0 min; 2.3 and 2.4 advisory (`blocking=False` at :519, :569).
- `infra/Makefile:283-284` -- `evals-run` = `pytest evals/checks --api-base-url $(CLIENT_URL) $(EVAL_ARGS)` behind `check-env infra-up check-stores check-api`; `check-env` (:153-162) demands `MM_DROPS_ROOT` in `.env`. Preconditions section sources from here.
- `_bmad-output/specs/spec-meetingminer/eval-design.md:180-196` -- §4, the runbook skeleton being operationalized; `:144-149` §2.5/§2.6, `:155-161` §2.8/§2.9, `:198-201` §5 — the sketches the four design docs expand; `:203-211` §6 threshold policy; `:213-224` §7 bake-off (feeds the optional-LLM-judging step and `evals/runs/bakeoff-<date>/`).
- `_bmad-output/specs/spec-meetingminer/scope.md:26-29` -- "Document (not implement): the retrieval eval strategy… Produce designs for ALL retrieval items" — the deferral each design doc cites.
- `docs/README.md:15-157` -- the repo's runbook heading convention (what has to exist first / the command / what it prints / when it refuses); mirror its shape.
- `_bmad-output/implementation-artifacts/deferred-work.md:86` -- the two NDA demo recordings are the assets that replace the placeholder `source_id`s; the precondition section points here for "when will a run actually pass".

## Tasks & Acceptance

**Execution:**
- `evals/RUNBOOK.md` -- new -- the operator procedure, in order: (1) Preconditions — stores/api up (`make up`), `.env` with `MM_DROPS_ROOT`, manifests validated with real `source_id`s (`make evals-test` green; placeholder state = expected zero-subject failure), one-agent-at-a-time rule for `make evals-run`; (2) Deterministic suite — `make evals-run EVAL_ARGS='--run-label <label>'`, what lands in `evals/runs/<run-id>/`, reading `deterministic-report.yaml` (per-check `passed`/`blocking`/`metrics`, per-entry detail); (3) Failure triage — classify each failure pipeline bug | ground-truth script error | genuine capture miss using the report's signatures; script errors fixed in YAML, noted, suite rerun; (4) Optional LLM judging — marked not-yet-built (story 5.4): bake-off prerequisite, pinned model id in run metadata, `llm-judge-report.yaml`, advisory only; (5) Human judging — one worksheet per human-judged check (capture-recall failures, dedup candidates, action-item non-exact matches, ADR/decision quality, Q&A right-moment-cited), worksheet template inline, results recorded per item in `human-verdicts.yaml` (format given in full: run id, judge, per-worksheet items with `item`, `verdict`, one-line `reason`); human verdict wins disagreements; (6) Final verdict — `verdict.md` format and the PASS rule (recall 100% ∧ guardrail holds ∧ no human fail), threshold changes recorded here; (7) Archive — folder immutable once `verdict.md` exists, harness enforces refusal; (8) Rerun rule — pipeline/embedder/judge-model change invalidates verdicts; new run folder, from step 1.
- `evals/designs/citation-timestamp-window.md` -- new -- eval-design §2.5 expanded: for every citation resolving to a planted item, assert |cited ms offset − scripted `at`| ≤ 15 000 ms; data source is the API's structured citation array vs the manifest's `planted.*.at`; failure modes, why deferred, what implementing needs (planted-item↔citation join).
- `evals/designs/action-item-fuzzy-match.md` -- new -- §2.6 expanded: normalized-text set-match ≥ 0.75 → found/missing/extra; escalation to LLM judge on non-exact matches, human final; relationship to the shipped `normalize_anchor`/difflib conventions; deferral.
- `evals/designs/eval-cadence.md` -- new -- §5 expanded: capstone = one full pre-demo run (after bake-off, before demo-script work — the NFR12 gate); documented-only cadence = change-triggered runs (prompt or screenshot-algorithm change) + go-to-prod gate run; each trigger tied to the rerun rule.
- `evals/designs/retrieval-eval.md` -- new -- §2.8/§2.9 expanded into the full retrieval eval design: recall@k on planted phrases/topics, exact-set graph-traversal comparison (participants→meetings→topics→moments), cited-Q&A rubric (§2.7) + right-moment-cited; notes that the doc-index slice (§2.10) and publish-gate (§2.11) are BUILD items landing with story 5.3.
- `evals/README.md` -- edit -- replace the ":24-28 still to come" paragraph with pointers to `RUNBOOK.md` (operating procedure) and `designs/` (documented-only checks); keep everything else.
- `_bmad-output/specs/spec-meetingminer/eval-design.md` -- edit, additive only -- a dated note recording that §4 is operationalized at `evals/RUNBOOK.md` and §2.5/§2.6/§2.9/§5's full designs live under `evals/designs/`; existing text unchanged.

**Acceptance Criteria:**
- Given `evals/RUNBOOK.md` alone, when an operator reads it start to finish, then every FR30 element is present in order: preconditions, deterministic suite, triage (three named classes), optional LLM judging, human judging worksheets, `human-verdicts.yaml` per-item format with one-line reasons and the human-wins rule, the `verdict.md` PASS rule, archive/immutability, and the rerun rule.
- Given today's placeholder fixtures, when the operator reaches the precondition step, then the runbook states the run exits non-zero at the zero-subject gate and frames it as an unmet precondition with the pointer to the placeholder-replacement procedure — never as a recordable FAIL verdict.
- Given any command, path, option, threshold, or refusal message named in the runbook, when checked against the shipped harness and Makefile, then it exists and behaves as written; steps for 5.3/5.4 functionality are explicitly marked as arriving with those stories.
- Given the four files under `evals/designs/`, when read, then each states the algorithm, thresholds, data sources, and what implementing requires, and cites the deferral (documented-only per scope.md) — no placeholders.
- Given `git diff` for this story, when inspected, then `evals/harness/`, `evals/checks/`, `evals/tests/`, `evals/conftest.py`, `infra/`, and `server/` are untouched, and the `eval-design.md` change is additive.
- Given `make evals-test`, when run after the change, then it passes unchanged with no run folder created.

## Spec Change Log

## Review Triage Log

### 2026-08-20 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 28: (high 0, medium 4, low 24)
- defer: 1: (high 0, medium 0, low 1)
- reject: 1: (high 0, medium 0, low 1)
- addressed_findings:
  - `[medium]` `[patch]` RUNBOOK step 6's PASS rule was narrower than `Run.passed` — duration
    agreement, inapplicable blocking checks and run-level problems could all fail the run while the
    written rule still read PASS. The report's overall `passed: true` is now the leading condition,
    marked as absorbing the 5.3 blocking checks when they land.
  - `[medium]` `[patch]` Worksheets 3–5 said to judge "in the app" with no stated way to reach it,
    breaking the runbook's self-containment promise. The web URL (`http://127.0.0.1:5173`, verified
    against the Makefile) is now stated, and surfaces that do not exist yet are marked with the
    stories that bring them (3.3/3.4, 4.1), recorded empty until then.
  - `[medium]` `[patch]` citation-timestamp-window's displayed assert (point-to-start distance)
    contradicted its own nearest-edge rule; the code block now states the nearest-edge form.
  - `[medium]` `[patch]` The nearest-edge rule silently deviated from eval-design §2.5 while the
    story's eval-design note claimed the designs "change nothing". The design now declares the
    refinement explicitly (provisional under §6) and the note says designs that sharpen a sketch
    declare it.
  - `[low]` `[patch]` RUNBOOK: check-2.1-vs-recall conflation in the verdict criteria; missing
    human-verdicts.yaml presence/`run:`-matches-folder preconditions for verdict.md; optional
    `machine:` and required `completed_at:` added to human-verdicts.yaml; pass|fail-only rule for
    unrulable items; check 2.3 given a consumer (verdict.md Notes); honest no-per-stage-rerun
    statement (re-POST requeue is the one path); run-label recommendation and defaulted-id
    discovery; store-hold end state and `make down`; drops-root existence check; partial-corpus
    semantics (matched subjects measured, run still fails); triage is per `problems` line; rerun
    triggers extended with config.yaml changes and post-verdict manifest edits. (13 findings)
  - `[low]` `[patch]` citation-timestamp-window: failure-mode table rows missing their triage-class
    cells; join tiebreak for boundary/overlap cases; recording-start-equals-meeting-start assumption
    stated. (3 findings)
  - `[low]` `[patch]` action-item-fuzzy-match: "check 5.1" corrected to story 5.1's authoring rules;
    deterministic tiebreak for equal-score greedy assignment; authoring guard against planted pairs
    folding within the match threshold. (3 findings)
  - `[low]` `[patch]` eval-cadence: NFR12 label attributed to epics.md with the actual SPEC
    Constraints bullet cited; FAIL branch added to the capstone flow. (2 findings)
  - `[low]` `[patch]` retrieval-eval: topic probes now carry an authored expected-meeting set, each
    required within top k. (1 finding)
  - `[low]` `[patch]` eval-cadence NFR12 wording and step-6 5.3 marker are counted within the
    groups above; remaining low findings: worksheet/YAML "same fields" claim aligned via the
    `machine:` field, and human-verdicts date via `completed_at:`. (2 findings)

## Design Notes

**A dedicated `RUNBOOK.md`, not more README.** CAP-8's success test is "a full run using only the runbook". `evals/README.md` is the harness's reference (authoring rules, layout, check semantics) and already 338 lines; folding an operator procedure in would leave the operator extracting a linear procedure from reference material — the exact tribal-knowledge shape FR30 exists to remove. The README stays the reference half; the runbook is the procedure half and may link to README sections for depth, but every step the operator must perform is stated in the runbook itself.

**Designs live beside the harness they would extend.** `evals/designs/` rather than the spec folder: eval-design.md is a frozen-discipline spec companion (additive notes only), and four full designs would bloat it past its role; `docs/` holds cross-cutting operator docs. An implementer of story 5.3+ or a post-capstone check starts in `evals/`, so the designs sit there, each pointing back to its eval-design section as the contract of record.

**`verdict.md` and `human-verdicts.yaml` stay operator-authored files, not code.** run.py already treats the presence of `verdict.md` as "folder closed" and refuses it; nothing more is needed for the immutability story. Adding schema validation for `human-verdicts.yaml` would be new harness surface in a documentation story and would couple 5.5 to code owned by nobody's contract — the runbook gives the exact format instead, and later stories may pin it with validation if a need appears.

**The runbook documents the complete procedure while only 5.1/5.2 are built.** The alternative — waiting for 5.3/5.4 — inverts the epic's dependency: the runbook is the epic's closing artifact and eval-design already scopes LLM judging as conditional ("if harness built"). Honest status markers per step keep the operator from typing commands that do not exist, and the 5.3/5.4 builders get the slot their output drops into.

## Verification

**Commands:**
- `make evals-test` -- expected: passes unchanged (store-free, no api, no folder under `evals/runs/` afterwards).
- `git diff --name-only origin/main...HEAD -- evals/harness evals/checks evals/tests evals/conftest.py infra server` -- expected: empty for this story's commits.
- `uvx ruff check --isolated evals/` -- expected: clean (proves no stray .py landed).

**Manual checks:**
- Walk the runbook against FR30's element list and tick each: preconditions, deterministic suite, triage classes, optional LLM judging, worksheets, `human-verdicts.yaml`, `verdict.md` PASS rule, archive, rerun rule.
- For every backticked command/path in RUNBOOK.md, confirm it exists on this branch (`make` target in `infra/Makefile`, file on disk, or option in `evals/conftest.py`).
- Confirm the eval-design.md diff only adds lines (no deletions/rewrites of existing text).

## Auto Run Result

Status: done

**Implemented change.** The epic-5 closing documentation: `evals/RUNBOOK.md`, the self-contained
operator procedure from preconditions through deterministic suite, triage, optional LLM judging,
human judging worksheets, `human-verdicts.yaml`, `verdict.md`, archive, and the rerun rule — plus
the four documented-only check designs under `evals/designs/`. Documentation only: no harness,
Makefile, or server code changed.

**Files changed.**
- `evals/RUNBOOK.md` — new; the eight-step operator procedure, every command and threshold
  transcribed from the shipped 5.1/5.2 harness, 5.3/5.4-dependent steps honestly marked.
- `evals/designs/citation-timestamp-window.md` — new; §2.5 expanded (nearest-edge ±15 s window,
  planted-item↔moment join, Q&A driver requirement).
- `evals/designs/action-item-fuzzy-match.md` — new; §2.6 expanded (difflib set-match at ≥ 0.75,
  greedy one-to-one with tiebreaks, escalation tiers).
- `evals/designs/eval-cadence.md` — new; §5 expanded (capstone run as the NFR12 gate with FAIL
  loop; change-triggered + go-to-prod cadence as rerun-rule instances).
- `evals/designs/retrieval-eval.md` — new; §2.8/§2.9 expanded (recall@k with authored expected
  meeting sets, exact-set graph traversal, cited-Q&A legs; §2.10/§2.11 noted as story-5.3 BUILD).
- `evals/README.md` — edit; the "still to come" paragraph now points to RUNBOOK.md and designs/.
- `_bmad-output/specs/spec-meetingminer/eval-design.md` — edit, additive (2 insertions, 0
  deletions); dated note pointing §4 at the runbook and the DOCUMENT-only sections at the designs.

**Review findings.** 28 patches applied (0 high, 4 medium, 24 low), 1 deferred (frontmatter), 1
rejected (duplicate `source_id` across manifests is already refused by the story-5.1 loader
validation the runbook's precondition step requires green). No intent gaps, no bad-spec findings.

**Follow-up review recommendation.** Patched this pass: 0 high, 4 medium, 24 low.
Score = 3×4 + 1×24 = 36 ≥ 5, so `followup_review_recommended: true`.

**Verification performed.** All commands run by me in this worktree after the patch pass:
- `make evals-test` → **341 passed in 0.41s**, store-free, and `evals/runs/` does not exist.
- `uvx ruff check --isolated evals/` → **All checks passed!**
- `git diff --name-only origin/main...HEAD -- evals/harness evals/checks evals/tests
  evals/conftest.py infra server` → **empty**.
- `git diff origin/main...HEAD --numstat -- _bmad-output/specs/spec-meetingminer/eval-design.md`
  → **2 insertions, 0 deletions** (additive).
- Manual: read RUNBOOK.md end to end against FR30's element list — all eight elements present in
  order; spot-checked the patched claims (web port 5173 = `WEB_PORT` in `infra/Makefile:28`, the
  report-`passed` verdict condition, `completed_at`/`machine:` fields) against the files.

**Residual risks.**
- The runbook describes the harness by hand-verified transcription; nothing mechanical fails when
  5.3/5.4 change the check set. Recorded as the deferred item.
- The end-to-end procedure has never been executed against a real eval subject and cannot be until
  the scripted meetings are recorded and the placeholder `source_id`s replaced (deferred-work.md,
  story-2.1b entry). The runbook frames that state as an unmet precondition by design.
- Worksheet 3–5 story attributions (3.3/3.4, 4.1) reflect sprint-status.yaml on this branch; if
  those stories land under different splits, the markers should be refreshed.

### Review Findings

- [x] [Review][Patch] Make human-final judgment override the deterministic gate [evals/RUNBOOK.md:345] — **Resolved (2026-08-20):** `evals.harness.verdict` generates hash-audited final verdicts from immutable reports plus versioned, reasoned human reconciliations.

- [x] [Review][Patch] Failed-job requeue describes stale checkpoint behavior [evals/RUNBOOK.md:217] — Resolved: the runbook now states that retry resets and runs the full stage set.
- [x] [Review][Patch] Human-review workflow depends on an unavailable meeting view [evals/RUNBOOK.md:289] — Resolved: report-first/current inspection and explicit unavailable-evidence failure are documented.
- [x] [Review][Patch] Preconditions omit the required content-storage root [evals/RUNBOOK.md:48] — Resolved: both absolute writable roots and loader validation are documented.
- [x] [Review][Patch] Drops-root hand check breaks on quoted dotenv values [evals/RUNBOOK.md:56] — Resolved: the fragile parser was replaced with loader validation.
- [x] [Review][Patch] Final-verdict audit can make human evidence vacuously complete [evals/RUNBOOK.md:337] — Resolved: finalization validates metadata, worksheets, record shape, and complete reconciliation before writing.
- [x] [Review][Patch] Citation design calls an unsigned distance a signed delta [evals/designs/citation-timestamp-window.md:28] — Resolved: `nearest_edge_delta_ms` has a precise sign convention.
- [x] [Review][Patch] Citation-window population and failure path are ambiguous [evals/designs/citation-timestamp-window.md:22] — Resolved: the one-top-citation population and hard result states are specified.
- [x] [Review][Patch] Greedy fuzzy matching can create avoidable misses [evals/designs/action-item-fuzzy-match.md:40] — Resolved: maximum-cardinality then maximum-score matching is specified.
- [x] [Review][Patch] Topic recall@5 can be impossible by construction [evals/designs/retrieval-eval.md:35] — Resolved: authoring rejects `len(expected_meetings) > k`.
- [x] [Review][Patch] Graph exact-set ground truth is not reproducibly specified [evals/designs/retrieval-eval.md:54] — Resolved: a versioned companion and canonical projection are specified.
- [x] [Review][Patch] Cadence permits reuse of a verdict after measured input changes [evals/designs/eval-cadence.md:44] — Resolved: input/corpus/evidence invalidators and integrity evidence are required.

- [x] [Review][Defer] Stale subject-selection explanation in the reference README [evals/README.md:148] — deferred, pre-existing. It says a failed job leaves a row and re-ingestion creates another subject, but `POST /ingests` re-queues an all-failed source ID in place. This pre-dates the story’s pointer-only README edit and should be corrected in the reference documentation separately.
