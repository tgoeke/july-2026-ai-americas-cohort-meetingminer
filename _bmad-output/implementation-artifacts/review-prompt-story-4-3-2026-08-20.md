# Reviewer handoff — Story 4-3: Per-Moment Approval & Publishing

## REQUIRED OUTPUT — read this section first

Write your findings to
`_bmad-output/implementation-artifacts/review-story-4-3-2026-08-20.md`. Use
this finding structure for every entry:

```
### Location
<file:line>

### Severity
<high|medium|low>

### Finding
<one or two sentences>

### Evidence
<why this is real — quote or cite the exact lines>

### Suggested direction
<what a fix would need to address, not a diff>
```

**Report findings; do not fix them.** This handoff is for an independent
review, not another implementation pass. Do not edit any file under
`server/`, `web/`, or `pull_transcript/`.

**REPORT-FIRST.** Before reading any code, create and commit the report file
as a skeleton: scope, review range, an empty findings section. Append each
finding as you confirm it and commit incrementally. A crashed or closed
session must lose prose, never the artifact.

**Closeout check.** Before reporting completion, run `make check-reviews` — it
fails while any dispatched review lacks a committed report, including this
one — and state the exact SHA carrying the report's final version. A review
reported only in the terminal, never filed, does not exist.

---

## Repo, branch, range

- Repo: this checkout (or a fresh worktree — `make worktree STORY=4-3-review`
  is fine; do not reuse the builder's worktree at `../meetingminer-wt/4-3`,
  which is a live checkout another agent may still be using).
- Branch: `story/4-3`, currently at `9706385`, rebased onto `main` at
  `69b767b` (current as of 2026-08-20; re-fetch and confirm `main` hasn't
  moved further before you start).
- Review range: `69b767b..9706385` (`69b767b` is `main`'s tip this branch is
  based on — everything in the range is this story's own work).

Commits in range, in order:

```
2e375a7 docs(4-3): plan story 4-3 (per-moment approval & publishing)
6fd4dbb feat(4-3): per-moment approval & publishing
5e694e7 docs(4-3): mark spec in-progress with baseline revision
ef876fc docs(4-3): mark spec in-review
771a6db docs(4-3): record review pass triage and deferred findings
f692f7a fix(4-3): close review findings on publish error handling and stale responses
6661f44 docs(4-3): close out story 4-3 (done)
9706385 docs(4-3): write the Codex reviewer handoff prompt
```

No commit in this range belongs to a different story. This branch was
rebased once already (onto an earlier `main` tip, to pick up an unrelated
sprint-notes/spec-2-8 commit) and again just now (onto `69b767b`, to pick up
3-4's landing) — both rebases are clean history rewrites with no dropped or
reapplied story content; the range above is the current, correct one.

## Spec: frozen vs. reviewable

`_bmad-output/implementation-artifacts/spec-4-3-per-moment-approval-publishing.md`.

- **Frozen (do not second-guess the choice, only whether the code honors
  it):** the `<intent-contract>` block — Intent, Boundaries & Constraints,
  I/O & Edge-Case Matrix.
- **Planner work, fair game to critique:** everything below
  `</intent-contract>` — Code Map, Tasks & Acceptance, Design Notes,
  Verification. The Design Notes section in particular states several
  build-time decisions (per-moment single gesture collapsing two lifecycle
  transitions, lazy git-repo init, filesystem/git-before-Postgres-write
  ordering, `{artifact_id}.md` filenames) with their own stated attack
  points — treat those as the planner's self-identified risk list, not as
  settled.
- The spec already carries one completed review pass (`## Review Triage Log`,
  `## Auto Run Result`) from this same build-auto run — 8 patch findings
  applied, 4 deferred to frontmatter `deferred`, 3 rejected. Read the
  deferred items before re-raising the same four; they are known, evidenced,
  and intentionally left open rather than missed.

## Architecture authority

- **AD-4** (`_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md`):
  projections have exactly one writer, gate lives inside `server/projections`,
  artifacts project only on `published`, one-way lifecycle with no unpublish.
  This story does **not** touch projections — verify it stays that way (no
  call to `publish_gate.project_artifact`, no Neo4j/Meilisearch client
  import).
- **AD-5**: table ownership disjoint by column — worker owns extraction
  content, API owns lifecycle state + publish metadata. Verify migration
  `0011` and every `UPDATE`/`INSERT` this story adds touch only
  `state`/`approved_at`/`published_at`/`publish_relative_path`/`publish_commit_sha`,
  never `kind`/`title`/`body`/`provenance`/`moment_id`/`meeting_id`.
- **AD-10**: config-driven bindings, machine-specific paths carried by env
  vars, not `config.yaml`. Verify `MM_PUBLISH_ROOT` follows the same
  `Secrets`/`_load_secrets`/fail-fast-at-startup shape as
  `MM_CONTENT_ROOT`/`MM_DROPS_ROOT`.
- `_bmad-output/specs/spec-meetingminer/storage-layout.md` §1: the publish
  folder is explicitly "a third configured location, deliberately not a
  third root" — no row anywhere should store a path relative to it the way
  drops/content paths are stored; this story's publish-relative-path column
  is this story's own convention, not a reuse of the two-anchor scheme.

## Scope

**In scope (touched by this story):**
- `server/meetingminer/migrations/0011_artifact_publish_metadata.sql`
- `server/meetingminer/config.py`, `.env.example`
- `server/meetingminer/publish/` (new package: `export.py`, `__init__.py`)
- `server/meetingminer/api/moments.py`, `api/main.py`
- `web/src/features/moments/moments.ts`, `MomentView.tsx`,
  `MomentView.test.tsx`
- `web/src/client/*` (generated, via `make client`)
- `server/tests/test_publish_export.py`, `test_publish_root.py`,
  `test_artifact_publish.py` (new), `conftest.py` (minor)
- `_bmad-output/implementation-artifacts/epic-4-context.md` (recompiled — see
  History below)

**Out of scope, do not flag as missing:**
- Story 4.4's re-indexing (`publish_gate.project_artifact` wiring to
  Neo4j/Meilisearch) — deliberately not called anywhere in this diff.
- Story 4.2's prompt-visibility/config-swap UI.
- Any worker/pipeline change — this story is API + web only.
- Vendored trees (`web/src/client/*` beyond the two touched files' diff
  shape — it's fully generated).

## Design decisions to attack

Handed over deliberately, not for rediscovery:

1. **One human gesture collapses two lifecycle transitions.** The endpoint
   advances every `extracted` artifact under a moment through both
   `approved` and `published` in one request; there is no API path that
   stops at `approved`. Rests on reading epics AC1 ("I'm offered the
   per-moment approval gesture to publish its artifacts") as one click, not
   two. Attack: is there a defensible reading where a human needs to approve
   without immediately publishing (e.g. review before the git commit
   happens)?
2. **Filesystem/git side effects run before the Postgres `UPDATE`, inside the
   same request, but each artifact's `UPDATE` executes immediately after its
   own export/commit — not batched after the whole loop.** Rests on the
   claim that a single shared Postgres transaction rolling back on any
   exception is sufficient to keep the DB always correct, even though it
   does **not** undo an earlier artifact's already-written file or
   already-made git commit within the same failed batch. This is flagged as
   deferred risk #1 in the spec's frontmatter — attack whether "self-healing
   on retry" actually holds for every failure mode, not only the ones tested.
3. **The publish folder becomes a git repo lazily on first ADR publish**, and
   `ensure_git_repo` rejects (via `PublishRootNotOwnedError`) a
   `MM_PUBLISH_ROOT` that already resolves to a foreign repo's toplevel via
   `git rev-parse --show-toplevel`, comparing `Path.resolve()`'d paths on
   both sides. Attack: is there a path-equivalence case (bind mount, hard
   link, case-insensitive filesystem) the resolve-based comparison misses?
4. **`{artifact_id}.md` filenames, not slugified titles** — rests on the
   artifact UUID already being the citation key everywhere else (AD-6).
   Attack: does anything downstream (a human browsing the publish folder, a
   future digest generator) actually need a human-readable filename, making
   this a usability regression the spec didn't weigh?
5. **No confirmation dialog before the bulk, irreversible publish click** —
   rejected as a finding during this run's own review pass on the grounds
   that the click itself is the explicit gesture epics AC1/AC2 call for.
   Attack that call directly if you disagree.

## History / regression vs. pre-existing

- `epic-4-context.md` was recompiled from scratch at the start of this run
  because the cached version predated a same-day `epics.md` rewrite. The diff
  against the old cached version is a full rewrite, not a targeted edit —
  don't read line-level diff noise there as a signal; compare its content
  against current `epics.md` §Epic 4 for accuracy instead.
- This branch was rebased twice on top of unrelated same-day work landing on
  `main` while the story was in flight — once to pick up sprint-notes
  reservations and story 2-8's spec, and again (most recently) to pick up
  story 3-4's landing. Both were clean rebases with no dropped or reapplied
  story content; the commit list above is the current, post-rebase state.
- No prior story touched `server/meetingminer/publish/` or
  `POST /moments/{moment_id}/approve` — there is no earlier baseline to
  regress against for this endpoint; everything here is new surface.
- `GET /moments/{moment_id}`'s `artifacts` field existed before this story as
  a hardcoded `[]` (story 2.2) — this story is what first makes it read real
  rows. A reviewer diffing against a pre-2.2 baseline would see more churn
  than this story actually owns; diff against `69b767b`, not further back.

## Operational finding worth surfacing, not a defect in this story

The first authorized extraction run tonight (story 4.1a, whole-transcript
extraction) surfaced that its two independent per-document-kind model calls
can describe the same real decision as two artifacts of different `kind` with
an **identical `anchor_ms`** — e.g. one real meeting minted both:

```
A9 @ 2736s  action-item  "Make contract-value column non-mandatory for teaming agreements"
D4 @ 2736s  adr          "The 'contract value' field should be non-mandatory for teaming agreements"
```

(2 of 5 ADRs on that meeting duplicated an action item; recorded in
`sprint-notes.md` at `69b767b`.) This story's approve endpoint advances
*every* `extracted` artifact under a moment in one call — by contract,
correctly — so a duplicated pair like this publishes both: one commits into
the git repo as an ADR, the other exports as an action item, and (once story
4.4 wires indexing) both become independently citable. This is not a defect
in 4-3 — 4.3's contract is "publish everything extracted under this moment,"
and the duplication is upstream, in 4.1a's per-document-kind extraction not
deduplicating against itself. Flag it as a cross-story finding for whoever
owns triage, not as something to fix in this diff. It's also a concrete,
already-observed instance of the same shape as the deferred partial-batch
finding below: a filesystem/git side effect the API contract permits turning
out more surprising in real operation than in the spec's own reasoning about
it.

## Verification baseline

Run these yourself; treat any skip or failure as a finding, not noise:

- `cd server && uv run pytest tests/test_publish_export.py tests/test_publish_root.py tests/test_artifact_publish.py tests/test_api_moments.py -q` — expected 66 passed (measured, post-rebase-onto-69b767b run).
- `cd server && uv run pytest tests/ -q` — expected all pass. Measured 1472 passed, 0 failed, post-rebase.
  An earlier pre-rebase run hit one transient failure
  (`test_projections_graph.py::test_graph_chunks_retain_nonresolved_speaker_turn_metadata`),
  reproduced as a pass in isolation immediately after — cross-worktree Neo4j
  projection-lock contention per AGENTS.md, not caused by this story. If you
  see it fail, re-run it alone before treating it as a regression; if it
  fails alone too, that IS a finding.
- `npx vitest run` (in `web/`) — expected all pass. Measured 176 passed
  post-rebase (up from 164 pre-rebase — the extra cases are story 3-4's,
  picked up by the rebase, not this story's).
- `npx tsc --noEmit` (in `web/`) — expected clean.
- `rg -n "import git|GitPython" server/meetingminer --glob '!server/meetingminer/publish/**'` — expected no matches (AD-8-style boundary: git subprocess calls confined to one module).
- The Docker stores are shared across worktrees (Postgres/Neo4j/Meilisearch, fixed ports) — announce before running the store-backed suites above and confirm no other agent holds them, per AGENTS.md.

---

This file is ready to hand to the Codex `bmad-code-review` agent.
