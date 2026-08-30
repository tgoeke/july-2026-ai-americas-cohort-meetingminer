# Review handoff — Story 4.1: Artifact Extraction Pipeline Stage

You are reviewing with none of the build run's context. Everything you need is
named here. Report findings; do not apply fixes.

## Where the change lives

- Repo: `/Users/devopsterus/current/cohort/meetingminer` (work from your own
  worktree — `make worktree STORY=4-1-review` — never the shared checkout).
- Branch: `story/4-1`, pushed to origin.
- Review range: `f653a3d..6164610` (`main..story/4-1`), six commits:
  - `753ad6f` docs(4-1): compile epic 4 context from planning artifacts
  - `eb5d98e` docs(4-1): ready-for-dev spec for artifact extraction pipeline stage
  - `494fc12` feat(4-1): artifact table, Llm port, and the extract stage
  - `481c358` test(4-1): extraction tests; pause-at-extract assertions become completion
  - `de22eff` fix(4-1): apply the eleven review patches
  - `6164610` docs(4-1): file review triage, deferred findings, and auto-run result
- No commit in the range belongs to another story. `753ad6f` is epic-level
  context tooling, not product code.

## The spec, and what you may critique

`_bmad-output/implementation-artifacts/spec-4-1-artifact-extraction-pipeline-stage.md`.

- The `<intent-contract>` block (Intent, Boundaries, I/O Matrix) is **frozen
  intent** derived from `_bmad-output/planning-artifacts/epics.md` Story 4.1 —
  treat it as given.
- Everything outside that block — Code Map, Tasks, Design Notes, and every
  design decision below — is **planner work you should attack**.
- The frontmatter `deferred:` list holds four findings a prior review pass
  already triaged as future work; re-raising them verbatim is noise, but
  disputing their deferral is fair game.

## Architecture authority

`_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md`:

- **AD-5** — table ownership split by column: worker inserts `artifact` rows and
  owns extraction content; the API owns the lifecycle column. The stage's only
  lifecycle contact must be the insert default.
- **AD-8 / AD-10** — all model calls through configured ports; the `Llm` port is
  specified "via LiteLLM"; bindings only from `config.yaml`; secrets only in env.
- **AD-11** — checkpointed, idempotent stages; reruns overwrite only their own
  outputs, keyed to the job's meeting.
- **AD-4** — single projection writer; publish gate inside `projections/`;
  artifacts project only on publish (Story 4.4 — must NOT happen here).
- **AD-6** — moment ids are citation currency; nothing may re-key or delete them.
- SPEC constraints (`_bmad-output/specs/spec-meetingminer/SPEC.md`): "no silent
  zero", "augmentation adds, never destroys", NFR5 (models never write evidence),
  NFR7 (unpublished artifacts never reach search/chat).

## Scope

In scope (the whole change set):

- `server/meetingminer/migrations/0009_artifacts.sql`
- `server/meetingminer/adapters/llm/{__init__,port,litellm}.py`
- `server/meetingminer/pipeline/extraction.py`
- `server/meetingminer/pipeline/stages/extract.py`, `stages/__init__.py`
- `server/meetingminer/domain/jobs.py`, `server/meetingminer/projections/evidence.py` (comment-only)
- `server/pyproject.toml`, `server/uv.lock` (litellm dependency)
- `server/tests/`: `conftest.py`, `test_extraction_core.py`,
  `test_worker_extract.py`, `projection_seed.py`, and assertion updates in
  `test_worker_runner.py`, `test_worker_moments.py`, `test_augmentation.py`,
  `test_ingests.py`, `test_api_meetings.py`, `test_projections_rebuild.py`
- `_bmad-output/implementation-artifacts/` docs for this story

Out of scope: the right-rail/API read path (Story 2.2), approval/publish
endpoints (Story 4.3), artifact projection (Story 4.4), prompt visibility and
prompt-swap config (Story 4.2), and the four `deferred:` items in the spec
frontmatter.

## Design decisions to attack

Each is the planner's call resting on an assumption — test the assumption.

1. **Extraction input is `projections.evidence.read_meeting`** (pipeline imports
   a projections module). Assumption: one assembly of "what a moment says" beats
   a third SQL derivation, and `evidence.py` being store-free/read-only makes the
   layering acceptable.
2. **One LLM call per eligible moment inside the runner's open transaction**
   (minutes-long transactions). Assumption: single-user machine, `transcribe`
   precedent, and rollback-atomicity of a meeting's drafts outweigh transaction
   hygiene.
3. **Sticky call-time fallback**: any `LlmError` from the primary — including
   auth refusals — permanently engages the fallback for that meeting, logged
   once, recorded per-artifact as `fallback_engaged`. Assumption: a degraded
   local answer beats a failed job, and provenance makes the substitution
   auditable.
4. **Rerun semantics**: delete only `extracted` drafts on non-approved moments;
   skip moments carrying any approved/published artifact entirely. Assumption:
   the matrix row "their moments skipped" licenses protecting draft siblings
   rather than deleting-and-not-re-proposing them.
5. **Composite FK** `(moment_id, meeting_id) → moment (id, meeting_id)` with no
   cascade, added by review patch. Assumption: a loud FK failure on a
   moment-deleting rerun is better than silently losing artifacts, and no
   realistic path deletes a moment that yielded artifacts.
6. **`extract` stays out of `AUGMENTATION_STAGES`**. Assumption: augmentation
   must never silently re-propose over human-reviewed artifacts; re-extraction
   is a deliberate manual re-queue.
7. **Strict parser with one retry** per moment, unknown kinds refused, fences
   tolerated. Assumption: a failed job names a problem better than a silently
   empty rail ("no silent zero").
8. **Kinds limited to `adr`/`action-item`** despite the UX spine's seven
   right-rail types. Assumption: FR19 scopes extraction to ADR + action items;
   the CHECK constraint can widen later.
9. **No API/web surface at all** (AC "appear in the right rail" is discharged as
   rows-only). Assumption: epics.md line 621 assigns the rail — including its
   pre-Epic-4 empty state — to Story 2.2.

## History you need

- Before this change, `extract` was in `STAGE_NAMES` with no implementation:
  every job deliberately paused there, `running` with `extract: queued`, and no
  job had ever reached `done`. Tests asserting that pause were updated by
  `481c358` — an assertion that changed is the story's intended behavior change,
  not a regression.
- Two projection-trigger tests in `test_projections_rebuild.py` were re-anchored
  (extract-fails path; explicit crash-window reconstruction for the reclaim
  case) because the old paused-state premise no longer occurs naturally. Judge
  whether the replacement coverage is equivalent.
- `projections/publish_gate.py` predates this story (Epic 1) — comments citing
  it are not dangling references.
- `moment_id_meeting_id_key` UNIQUE on `moment` was added inside 0009 by a
  review patch; 0009 has never shipped, so in-place amendment is legitimate.

## Verification baseline (all run post-patch on `6164610`)

- `cd server && uv run pytest tests/ -q` → **1141 passed** in 5m54s (store-backed;
  per-run database, projection tests queue on the cross-worktree lock).
- `make web-test` → **90 passed**.
- `rg 'import litellm|from litellm' server/meetingminer` outside `adapters/llm/`
  → no matches.
- No test reaches a real LLM (autouse `_no_real_llm` guards the stage binding;
  the SDK boundary is tested against a stubbed `litellm` module).

A skip or failure against this baseline is a finding, not noise.

Operational note (not a finding): the 28 real-corpus jobs are paused at
`extract`; a worker restart on this code advances them through ~850 real
`claude-sonnet-5` calls. `make migrate` must run before that restart.

## Required output

Write your report to
`_bmad-output/implementation-artifacts/review-story-4-1-2026-08-20.md` — the
file must exist on disk before you report completion (this repo has had three
unfiled reviews; sprint validation now checks). Structure: verdict
(pass / pass-with-findings / fail), findings ordered by severity with
file:line evidence and a concrete failure scenario each, the verification
commands you ran with their real results, and a scope-conformance note
(anything touched outside the file list above). Report findings only — do not
apply fixes.
