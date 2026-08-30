# Reviewer handoff: Story 4-4 — Published Artifacts Become Citable Knowledge

## Required output (read this first)

Write your report to
`_bmad-output/implementation-artifacts/review-story-4-4-2026-08-21.md`. Each
finding uses this structure: **Location** (file:line) / **Severity**
(high/medium/low) / **Finding** / **Evidence** / **Suggested direction**.
Report findings — do not fix them.

**REPORT-FIRST.** Before reading any code, create and commit the report file
as a skeleton: scope, the review range below, an empty findings section.
Append each finding as you confirm it and commit incrementally. A crashed or
closed session must lose prose, never the artifact — six prior reviews in
this repo were completed only as terminal text and never filed, every one
written report-last.

**Closeout check.** Before reporting completion, run `make check-reviews` —
it fails while any dispatched review lacks a committed report, including
this one. State the SHA carrying the report's final version. A review
reported in the terminal but not filed does not exist.

## Repo, branch, range

- Repo: `meetingminer`, worktree `../meetingminer-wt/4-4`, branch `story/4-4`.
- Review range: `2d9705fb286098f9af08e2724d0106052244bc0f..HEAD` (currently
  `adec487`).
- Commits in range, oldest first:
  - `e07f5d4` feat(projections): project published artifacts into both stores (story 4-4 write side)
  - `7fa44b8` feat(api): surface published artifacts in search and chat; project on approve (story 4-4 read side)
  - `51b62ee` docs(evals): flip check 2.11's post-approval half to required-pass; retire the unlocked-project_artifact deferral
  - `c134986` feat(web): render published-artifact search hits with kind badge and source line
  - `98a5647` test(projections): pin artifact projection — gate, shape, locks, re-projection, rebuild
  - `4352abe` test(api): artifacts surface published-only through search and chat; approve projects
  - `5267bd0` test(fixtures): teach the synthetic config and the camelCase pin the artifacts additions
  - `df9cdde` test(projections): fold the artifacts index into the settings read-back
  - `60b006c` test(fixtures): counts pins and the torn-projection stub learn the artifacts additions
  - `088ad06` docs(spec): record story 4-4 build result — implemented, full regression 1563 passed
  - `251d480` fix(review): dedup CITES edges, param-bind PUBLISHED_STATE, drop dead allow-list check, consolidate artifact seed helper
  - `4c4c2d0` fix(review): bound search page size, bound per-moment artifact context, chat stale-artifact coverage
  - `57e875d` fix(review): screen-reader disambiguation, generated-client field docs, restore deferred-work evidence
  - `adec487` docs(spec): story 4-4 review pass complete — 15 patches applied, status done

  Every commit in this range belongs to story 4-4. None is another story's
  work landing incidentally.

## Spec: frozen intent vs. planner work

Read fully: `_bmad-output/implementation-artifacts/spec-4-4-published-artifacts-become-citable-knowledge.md`.

- The `<intent-contract>` block (Intent, Boundaries & Constraints, I/O &
  Edge-Case Matrix) is **frozen** — it was written before implementation and
  not touched during it. Treat deviations from it as findings.
- Everything after `</intent-contract>` (Code Map, Tasks & Acceptance, Design
  Notes, Verification, Review Triage Log, Auto Run Result) is the planner's
  and implementer's own work — fair game to critique, including the design
  choices named below.
- This spec already carries one completed adversarial review pass (see its
  `## Review Triage Log`, dated 2026-08-21): four parallel layers found 15
  patch findings (all applied) and 9 rejected findings. Read that log before
  you start — do not re-surface a finding it already triaged as rejected
  without new evidence; do surface anything it missed.

## Architecture authority

From `_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md`:

- **AD-4 — Projections have exactly one writer.** Only `server/meetingminer/projections/`
  may write Neo4j/Meilisearch. This story's approve-route call and the
  worker's per-meeting pass must both go through it — verify no direct store
  client import leaked into `api/` (`server/tests/test_projections_single_writer.py`
  is the automated check; confirm it actually covers the new call sites).
- **AD-5 — Table ownership is disjoint.** The worker owns
  `moment_id/meeting_id/kind/title/body/provenance` on `artifact`; the API
  owns `state` + the four publish-metadata columns. This story's Postgres
  reads (`publish_gate.published_artifacts`) must not write anything.
- **AD-6 — Citations are Postgres-minted moment IDs, gated in code.** Confirm
  every artifact-derived citation still resolves through a real moment row,
  never through the Meilisearch/Neo4j documents directly.
- **AD-8 — All model calls go through configured ports.** The artifacts
  index is keyword-only by design — confirm no embedder call was
  accidentally introduced on the artifact path.
- **AD-10 — One config file drives everything.** The new
  `projections.search.artifacts` block in `config.yaml` should follow the
  same shape/validation discipline as `moments`/`chunks`.
- **AD-15 — One citation wire format.** `CitationModel` in `api/chat.py` is
  six fields, frozen; this story must not have added a seventh.
- **AD-16 — The eval harness is a client, not a housemate.** The harness
  (`evals/harness/stores.py`) redeclares `ARTIFACTS_INDEX` and the
  `momentIds` field name by hand rather than importing
  `meetingminer.projections`. Confirm the story kept those two values
  literally unchanged.

Also relevant: `_bmad-output/specs/spec-meetingminer/eval-design.md` §2.11
(the publish-gate check this story's own Design Notes and Auto Run Result
say it flips from expected-fail to required-pass) and
`spec-4-3-per-moment-approval-publishing.md` (the prior story whose Design
Notes explicitly hand off `publish_gate.project_artifact`'s wiring to this
one).

## Scope

**In scope (this story's files):**
- `server/meetingminer/projections/{publish_gate,stores,graph,search,__init__,cli,query}.py`
- `server/meetingminer/config.py`, `config.yaml`
- `server/meetingminer/api/{search,chat,moments}.py`
- `web/src/client/types.gen.ts` (regenerated, no hand edits — verify)
- `web/src/features/search/{hits.ts,CorpusSearch.tsx,CorpusSearch.test.tsx}`
- `evals/harness/checks.py`, `evals/tests/test_publish_gate_algorithm.py`
- `_bmad-output/implementation-artifacts/deferred-work.md`
- `server/tests/projection_seed.py` and
  `test_projections_{locks,graph,search,rebuild,query}.py`,
  `test_api_{search,chat}.py`, `test_artifact_publish.py`, `test_config.py`
- `server/pyproject.toml` (one new pytest marker registration)

**Explicitly out of scope — do not flag as missing:**
- Fixing the upstream ADR/action-item duplication from extraction (story
  4-1a/epic-4 triage) — this story publishes and projects whatever Postgres
  already marked `published`, by design (spec's Never list).
- Resolving the 5 meetings' 133 legacy per-moment drafts
  (`provenance->>'source' IS NULL`) — a human decision, recorded in
  `sprint-notes.md`, not this story's to make.
- An `[[artifact:…]]` citation marker type, or any change to
  `api/citations.py`'s validation semantics — the spec's Design Notes reject
  this explicitly (see "Chat integration is retrieval-side only" below).
- A per-artifact approve/publish endpoint, an unpublish route, or a new
  migration — all explicitly Never-listed in the spec.
- Running `make evals-run` — announce-gated per `AGENTS.md`; not performed
  this pass, and not expected of the review either.

## Design decisions to attack

Each is a choice this story's Design Notes made, plus the assumption it
rests on. The planner is not a neutral judge of its own calls — attack these
directly rather than waiting for them to be rediscovered.

1. **Artifact is meeting-scoped in both stores, restored from Postgres on
   every meeting pass**, rather than exempted from per-meeting delete.
   Assumption: `DETACH DELETE` of `Moment` nodes on every re-projection would
   sever `CITES` edges anyway, so scoping artifacts to the same delete/
   re-create cycle is the only option that stays correct across augment and
   worker settle points. Attack point: does every call site that re-projects
   a meeting (worker, augment, `unproject_meeting`, `rebuild`) actually
   re-read published artifacts, or could one path leave a meeting's
   artifacts stale after its moments changed?
2. **Keyword-only artifacts index — no embedder ever declared.** Assumption:
   short, title-rich documents don't need vector search, and the eval
   harness checks presence by id, not ranking. Attack point: does this
   degrade the "it appears as a result" AC for a paraphrased search query
   that shares no keywords with the artifact's title/body?
3. **Projection runs after the Postgres commit, never inside the
   transaction — best-effort, with `rebuild --meeting` as the recovery
   path.** Assumption: this mirrors the worker's documented
   "never fail the job over a projection" policy, and the alternative
   (projecting inside the open `REPEATABLE READ` transaction, across a
   cross-process file lock with a 300s default timeout) is strictly worse.
   Attack point: is there any code path a human relies on to *know* a
   publish silently failed to project, beyond a log line? Is that
   sufficient for AC1's "it is indexed" as a functional guarantee, or does
   it need a stronger observable signal?
4. **Chat integration is retrieval-side only — citations stay moment-typed,
   never artifact-typed.** Assumption: an `[[artifact:…]]` marker would
   reopen the frozen `CitationModel` contract for no AC gain, since the AC's
   citation target is explicitly "the source moment." Attack point: does a
   user asking specifically about a *decision* (not a *moment*) get an
   answer that reads as if the model is citing the ADR, when the wire
   citation is actually the moment that produced it — is that surface
   mismatch a problem for this feature's actual users (a lead architect,
   per the epic's persona)?
5. **`published_artifacts`'s Postgres read is the sole gate enforcement at
   the entrypoint surface** (`WHERE state = 'published'`, filter-and-skip
   for a requested-but-unpublished id) rather than an active raise at every
   call site. `assert_publishable` still raises inside the gate itself.
   Attack point: is "regardless of caller" (the epic's literal AC2 wording)
   actually satisfied by a read that structurally cannot select the wrong
   rows, or does some caller exist that could still reach the gate with a
   pre-fetched, stale `Artifact` object bypassing the fresh read?

## History a reviewer needs

- This is a first-time build, not a rebase or superseded-baseline situation
  — no history context needed there.
- One session already ran a full adversarial review pass on this same range
  (see the spec's Review Triage Log) and applied 15 fixes across three
  commits (`251d480`, `4c4c2d0`, `57e875d`). Treat those as already-reviewed
  code, not fresh territory, unless you have new evidence a fix was wrong or
  incomplete.
- `deferred-work.md`'s unlocked-`project_artifact` entry is the *resolution*
  of a defect recorded during a prior story (`rebuild-crash-recovery`,
  2026-08-21) — read that entry's restored `evidence:` field for the
  original defect's full context if you want to verify the fix actually
  closes it.

## Verification baseline

Commands and their last-known-good results (this session, post-review-pass):

- `cd server && uv run pytest tests/ -q` → **1568 passed, 0 failed**
  (full regression, store-backed — announce before running, per `AGENTS.md`;
  shared Docker stack, projection tests queue on the cross-worktree lock).
- `make evals-test` → **548 passed** (store-free).
- `make web-test` → **207 passed**.
- `rg -n "import neo4j|import meilisearch|from neo4j|from meilisearch" server/meetingminer/api`
  → no matches.
- `make evals-run` was **not** run this pass (paid/announce-gated); check
  2.11's flipped expectation is verified at the algorithm level
  (`evals/tests/test_publish_gate_algorithm.py`) and by one stores-backed
  integration test (`test_artifact_publish.py::test_approve_projects_into_both_stores`),
  not by a full corpus run. A skip or failure of `make evals-run` during
  your review (if you choose to run it) is a finding, not noise — read it
  against this baseline, not as ambient risk.

If any of these commands produce a different result in your environment,
that mismatch is itself worth reporting.
