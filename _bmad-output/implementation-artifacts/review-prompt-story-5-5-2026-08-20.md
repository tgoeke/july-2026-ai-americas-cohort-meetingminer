# Review prompt — Story 5.5: Eval Runbook & Documented-Only Designs (2026-08-20)

Hand this file to the Codex `bmad-code-review` agent. It assumes no context
from the build run.

## Repo, branch, range

- Repo: `/Users/devopsterus/current/cohort/meetingminer` (review in your own
  worktree per AGENTS.md — `make worktree STORY=5-5-review`; the story's build
  worktree at `../meetingminer-wt/5-5` belongs to the builder).
- Branch: `story/5-5`, pushed to `origin/story/5-5`.
- Review range: `cb19a41..HEAD` (merge base with `origin/main` is
  `cb19a41abae80a5a69468eb48dbd5da3e336b995`). Commits, oldest first:
  - `07472a7` docs(epic-5): regenerate context from amended spine (AD-17, two-root storage, augmentation intake)
  - `7e2dce5` docs(story 5.5): plan the eval runbook and documented-only designs
  - `d1e5017` docs(story 5.5): eval runbook and the four documented-only check designs
  - `8dd2976` chore(story 5.5): mark spec in-progress with baseline revision
  - `ca994d0` docs(story 5.5): apply review patch findings to runbook and designs
  - `dfc1bdf` chore(story 5.5): spec status in-review
  - `b412a3f` docs(story 5.5): close the run — triage log, deferred item, auto run result

## Spec: frozen intent vs planner work

Spec: `_bmad-output/implementation-artifacts/spec-5-5-eval-runbook-documented-only-designs.md`.

- **Frozen intent** is the `<intent-contract>` block (Intent, Boundaries &
  Constraints, I/O & Edge-Case Matrix). It derives from epics.md Story 5.5
  (FR30/CAP-8). Do not critique it; judge the artifacts against it.
- **Planner work you may critique:** the Code Map, Tasks & Acceptance,
  Design Notes, and every placement/format decision listed under "Design
  decisions to attack" below.

## Architecture authority

- `_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md`
  — specifically AD-16 (the eval harness is a client: mutates only through the
  public api, read-only store access; the designs must not propose harness
  writes) and the 2026-08-19 storage/provenance amendments (AD-3/AD-9/AD-17:
  two storage roots in env vars, evidence located via Postgres rows/api, never
  directory scans — the designs' data-source sections must respect this).
- `_bmad-output/specs/spec-meetingminer/eval-design.md` — the contract of
  record for every check the documents describe (§1–§7). This story added one
  additive note under §4 and must have changed nothing else in it.
- `_bmad-output/specs/spec-meetingminer/scope.md` — the "design everything,
  build the slice" line that makes the four designs documented-only.

## Scope

**In scope (the story's whole change set):**
- `evals/RUNBOOK.md` (new)
- `evals/designs/citation-timestamp-window.md`, `action-item-fuzzy-match.md`,
  `eval-cadence.md`, `retrieval-eval.md` (new)
- `evals/README.md` (edited pointer paragraph)
- `_bmad-output/specs/spec-meetingminer/eval-design.md` (one additive note)
- The spec file itself and its status/bookkeeping commits.

**Out of scope:**
- All harness/test/infra code: `evals/harness/`, `evals/checks/`,
  `evals/tests/`, `evals/conftest.py`, `infra/`, `server/` —
  `git diff --name-only cb19a41..HEAD` over those paths is empty; if you find
  otherwise, that is a finding.
- Story 5.3/5.4 functionality (retrieval/publish-gate checks, LLM judge) —
  the runbook deliberately documents them as arriving later.
- Already-recorded deferred items: the spec frontmatter's `deferred` list (doc
  drift risk) and `deferred-work.md` entries (placeholder `source_id`s).

**Off-story commit in the range:** `07472a7` regenerates
`_bmad-output/implementation-artifacts/epic-5-context.md` from the amended
spine. It is run bookkeeping, not a story deliverable; review it only for
factual fidelity to the spine.

## Design decisions to attack

Each stated as choice + the assumption it rests on:

1. **A dedicated `evals/RUNBOOK.md` instead of extending `evals/README.md`.**
   Assumes CAP-8's "using only the runbook" is best served by a linear
   procedure file separate from reference material, with links for depth. If
   you think the split leaves the operator flipping between files at a
   load-bearing step, say where.
2. **Designs live in `evals/designs/`, not the spec folder or `docs/`.**
   Assumes the next implementer starts in `evals/` and that eval-design.md's
   additive discipline forbids growing it by four documents.
3. **`verdict.md` and `human-verdicts.yaml` are operator-authored with no
   schema validation.** Assumes the documented format-as-contract is enough
   until a consumer exists; run.py's verdict-presence refusal is the only
   mechanical enforcement. The `machine:`/`completed_at:` fields were added in
   review — check the format is actually sufficient for a disagreement audit.
4. **The runbook documents the complete procedure while only 5.1/5.2 are
   built.** Assumes "[arrives with story 5.3/5.4]" markers keep the operator
   from typing nonexistent commands and that step 6's report-`passed`
   condition absorbs future blocking checks without a rewrite. Probe for any
   step where the marker discipline slipped.
5. **Step 6's PASS rule = report `passed: true` + 2.1 everywhere + 2.2
   everywhere + no human `fail`.** Assumes this equals "recall 100%, guardrail
   holds, no human fail" (the epics wording) plus the harness's own gate, and
   is not over- or under-strict. Check against `Run.passed`
   (`evals/harness/run.py:327-337`) and `REQUIRED_CHECKS`.
6. **citation-timestamp-window measures to the nearest edge of the cited
   moment's span, refining §2.5's point-distance sentence.** Assumes a moment
   containing the scripted instant is exactly right. The refinement is
   declared in the design and in the §4 note's wording; check that
   declaration reads as a refinement, not a silent contract change.
7. **action-item matching is greedy one-to-one at ≥ 0.75 via difflib**,
   deliberately unlike 2.1's independent matching. Assumes planted items are
   distinct tasks by construction and the shipped difflib convention
   (eval-design §2.4a) extends to peer-text comparison.
8. **The runbook transcribes harness facts by hand** (thresholds, refusal
   messages, report fields, Makefile guards). They were verified against the
   worktree during build and review, but verify a sample yourself — a
   transcription error is exactly the class of defect this review exists to
   catch.

## History the reviewer needs

- Stories 5.1/5.2 are `done` and their harness is on `main`; this branch
  fast-forwarded onto `cb19a41` before work began. There is no rebase or
  dropped variant in the range.
- `run.py` already carried `VERDICT_NAME = "verdict.md"` and the
  verdict-closed-folder refusal before this story; the runbook documents that
  behavior, it did not add it.
- An earlier build-run review pass (logged in the spec's Review Triage Log,
  2026-08-20) applied 28 patch findings in `ca994d0` — including the PASS-rule
  widening, the nearest-edge assert fix, and the worksheet app-URL/story
  markers. Re-finding those is expected; judge whether the fixes hold, and
  attack what that pass missed.

## Verification baseline

Run from a worktree of this branch; these are the results the build run
recorded (a deviation is a finding):

- `make evals-test` → 341 passed, store-free, and `evals/runs/` does not exist
  afterwards.
- `uvx ruff check --isolated evals/` → clean.
- `git diff --name-only cb19a41..HEAD -- evals/harness evals/checks evals/tests evals/conftest.py infra server` → empty.
- `git diff cb19a41..HEAD --numstat -- _bmad-output/specs/spec-meetingminer/eval-design.md` → `2 0` (additive).
- `make evals-run` is expected to FAIL today at the zero-subject gate
  (placeholder `source_id`s) — do not run it without holding the shared
  stores per AGENTS.md, and treat that failure as the documented state, not a
  finding.

## Required output

Write findings — do not apply fixes — to
`_bmad-output/implementation-artifacts/review-story-5-5-2026-08-20.md`, with:

1. A verdict line (approve / approve-with-findings / request-changes).
2. Findings, each with severity (high/medium/low), file:line, what is wrong,
   and what the fix must do — including doc-vs-code mismatches found by
   checking the runbook's claims against the harness.
3. The verification commands you ran and their real results.
4. Anything reviewed and found sound that the next agent should not re-derive.
