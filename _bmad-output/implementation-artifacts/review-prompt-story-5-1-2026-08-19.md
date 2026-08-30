# Review handoff — Story 5.1: Ground-Truth Schema & Scripted Fixtures

You are reviewing a completed, unattended build. You have none of that run's
context, so everything you need is below. Report findings; do not apply fixes.

## Repository, branch, range

- Repo: `/Users/devopsterus/current/cohort/meetingminer` (a git worktree for this
  branch exists at `/Users/devopsterus/current/cohort/meetingminer-wt/5-1`).
- Branch: `story/5-1`, pushed to `origin/story/5-1`.
- Review range: `5a0a49956c24e4f6578fe1b3f80d0c4d8c51818d..HEAD` — the whole branch.
  `5a0a499` is the merge base with `main`; nothing on `main` has moved since.

Commits in the range, oldest first — every one belongs to story 5.1:

| Revision | Subject |
|---|---|
| `5d6b78fce1f6e8f00739dad76334152fc18e5166` | docs(epic-5): compile the epic 5 eval-harness context |
| `5336aec3d5ce93304306da2c7da9d648a367b40a` | docs(spec): plan story 5.1 — ground-truth schema and scripted fixtures |
| `490e797fc451fda1f89e107a8aa8d3222e6ac924` | feat(evals): ground-truth schema, validating loader, and scripted fixtures |
| `ce598934aa127364433615bf89a80202c06418ab` | feat(evals): make evals-test a first-class store-free target, rewrite the README |
| `d4cdca516f5b9d66bb8a759cf1a610e4f37c1496` | fix(evals): close the review's coverage and error-handling gaps in the harness |
| `04165d953fe33e4a7c26f6390a5109f5d91503bd` | docs(evals): reconcile eval-design §1 with the schema, and the docs with the harness |
| `3cceac161c448fa7cb618bde5f3f6827024e96a2` | docs(spec): finalize story 5.1 — review triage, deferrals, run result |

No commit in the range belongs to a different story.

Note on reading the range: `d4cdca5` and `04165d9` are the build's own in-run
review patches. If you review commit-by-commit you will find defects in `490e797`
that `d4cdca5` already closed. Judge the tip, not the intermediate states.

## Specification

- Story spec (the frozen contract): `_bmad-output/implementation-artifacts/spec-5-1-ground-truth-schema-scripted-fixtures.md`.
- Everything inside the `<intent-contract>` block — Intent, Boundaries & Constraints,
  I/O & Edge-Case Matrix — is **frozen intent**. Critique whether the code satisfies
  it, not whether it was the right contract.
- Everything outside that block — Code Map, Tasks & Acceptance, Design Notes,
  Verification, Review Triage Log, Auto Run Result — is **planner work and is fair
  game**. The Design Notes in particular record calls the planner made and is not a
  neutral judge of.
- The authored story text this contract was distilled from is
  `_bmad-output/planning-artifacts/epics.md`, section "Story 5.1: Ground-Truth
  Schema & Scripted Fixtures". Its five acceptance criteria are the outermost
  statement of intent.

## Architecture authority

The decision records that govern this change, in
`_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md`:

- **AD-16 — "The eval harness is a client, not a housemate."** The binding rule:
  the harness mutates only through the public API and asserts through read-only
  access; it never imports server modules to change state. This is the decision
  `evals/tests/test_harness_boundary.py` claims to make falsifiable, and the one
  most worth attacking.
- **AD-1 — One canonical inbox: the source drop.** Defines `sourceId` and the
  `corpus: scripted | real` tag that eval-subject selection turns on. The drop
  contract itself is `docs/source-drop.schema.json` (unchanged by this story, and
  the schema-authoring convention the new schema deliberately mirrors).
- **AD-14 — `POST /ingests` is the only door.** Relevant as a boundary: this story
  calls it nowhere, and must not.
- **AD-10 — one versioned `config.yaml`.** Relevant only as a non-goal here; the
  per-run config snapshot it requires belongs to story 5.2.
- The capability row for **CAP-7** in the spine's traceability table states the
  corpus rule this story implements: eval subjects are `corpus: scripted` meetings
  matched to manifests by `sourceId`; `corpus: real` meetings are never subjects.

Companion specifications that carry the substance:

- `_bmad-output/specs/spec-meetingminer/eval-design.md` §1 (ground-truth schema and
  the unique-anchor authoring rule) and §2.1 (capture recall, including the OCR
  normalization the anchor rule mirrors). **This file was modified by the change** —
  see the design decisions below.
- `_bmad-output/specs/spec-meetingminer/scope.md`, section "Corpus" — scripted
  meetings are the sole eval basis; real pulled meetings never are.

## Scope

In scope — the files this story owns and changed:

- `evals/ground-truth.schema.json` — the manifest contract.
- `evals/harness/groundtruth.py`, `evals/harness/subjects.py` — loader, validator,
  subject selector.
- `evals/ground-truth/demo-001-orders-ui-demo.yaml`,
  `evals/ground-truth/demo-002-q3-architecture-review.yaml` — one fixture per archetype.
- `evals/tests/` — `conftest.py` plus five test modules (194 tests).
- `evals/__init__.py`, `evals/harness/__init__.py`, `evals/tests/__init__.py`,
  `evals/README.md`.
- `infra/Makefile` — the `evals-test` target and its place in `make test`.
- `AGENTS.md` — one paragraph: the store-free concurrent-suite list.
- `_bmad-output/specs/spec-meetingminer/eval-design.md` — one appended note (see below).
- `_bmad-output/implementation-artifacts/` — the story spec and the epic-5 context file.

Explicitly out of scope — do not report these as gaps:

- Every eval **check**: capture recall (2.1), over-capture guardrail (2.2), view
  classification (2.3), dedup quality (2.4), doc-index recall@5 (2.10), publish-gate
  projection (2.11). Those are stories 5.2 and 5.3.
- `evals/runs/<run-id>/` creation, `deterministic-report.yaml`, the resolved-config
  snapshot, and run immutability — story 5.2.
- The LLM judge harness and bake-off — story 5.4. The runbook — story 5.5.
- Any OCR, ingestion, store query, or `POST /ingests` call.
- `server/`, `web/`, `pull_transcript/` (vendored), `docs/source-drop.schema.json`,
  `config.yaml` — all untouched, deliberately.
- The six items already recorded in the spec's frontmatter `deferred:` list. They
  were found, judged real, and consciously left. Re-reporting them costs a pass;
  disagreeing with the *judgment* to defer one is useful.

## Design decisions to attack

Each is stated as the choice plus the assumption under it. These are the planner's
calls and the places a fresh reviewer earns the most.

1. **The schema requires `meeting.source_id`, which `eval-design.md` §1 does not have.**
   The story matches manifests to ingested meetings by `sourceId`; §1's example keys
   only on `meeting.id`. Rather than overload `meeting.id`, the schema adds a required
   `source_id`. *Assumption:* that the two identifiers should stay separate — one a
   human-facing manifest label, one the join key. *Consequence to weigh:* the change
   appends a note to §1 rather than editing the example, so the canonical example
   still does not validate as written; the note says so explicitly. Is amending a
   preservation-validated spec companion from a story build the right move at all?

2. **Fixtures ship with placeholder `source_id` values and a test that pins them as
   placeholders.** The scripted meetings do not exist yet. *Assumption:* that a
   fixture describing an unrecorded meeting is still a useful deliverable, and that
   a tripwire test (delete it, do not edit it, when real ids land) is better than
   silence. *Consequence to weigh:* the shipped ground truth is asserted to match
   nothing, and no meeting script exists for either fixture to have been transcribed
   from — so eval-design's independence rule holds only in its negative half.

3. **Anchor uniqueness is exact-match after normalization; no distinctiveness
   threshold was invented.** The story's acceptance names missing and duplicate
   anchors only, while check 2.1 will match fuzzily at ≥ 0.8. *Assumption:* that
   inventing a similarity threshold at authoring time overreaches the intent, and
   that documenting the residual collision risk discharges it. A test deliberately
   admits `"Order Search Results"` / `"Order Search Filters"` as distinct.

4. **`normalize_anchor` claims to fold text the way check 2.1 will, but nothing
   forces 2.1 to call it.** *Assumption:* that a docstring and a shared function are
   enough coupling until 5.2 exists. Note the contrast: the same change goes to real
   trouble (an AST walk) to make AD-16 falsifiable rather than hoped for.

5. **Validation is two layers — JSON Schema for shape, Python for everything that
   spans entries — reporting through one message list.** *Assumption:* that an
   author is better served seeing every problem at once than peeling them off, which
   is why the loader rules are written to tolerate schema-invalid input.

6. **`select_subjects` is a pure function over rows; `fetch_meetings` is the only
   impure one.** *Assumption:* that unit-testing the selection matrix over synthetic
   `GET /meetings` payloads is adequate coverage of an acceptance criterion phrased
   "Given the ingested corpus". The row shape is hand-copied from
   `server/meetingminer/api/meetings.py` and nothing binds the two — AD-16 forbids
   importing the response model. A server-side rename of `corpus` or `viewable`
   leaves this suite green while every manifest silently lands in `unmatched`.

7. **A manifest matching several rows for one `sourceId` yields a Subject per row.**
   A failed job leaves its row and a re-ingest adds another. *Assumption:* that story
   5.2 should decide what a duplicate means, so `Subject` carries `status` and the
   selector does not choose.

8. **`make evals-test` was added to `make test`'s store-free group.** *Assumption:*
   that a suite needing no Docker store and no api belongs in the project's only
   gate. `AGENTS.md` was amended to match, because it is the file every agent reads
   before deciding what it may run concurrently.

## History you need to tell a regression from a pre-existing condition

- The branch is a clean fast-forward from `main` at `5a0a499`. No rebase, no
  dropped variant, no superseded baseline.
- `evals/` existed before this change as a README placeholder only — one paragraph,
  no code. Everything under it is new.
- `epic-5-context.md` is generated from planning artifacts, not hand-authored. It is
  in the range because epic 5 had none; it is an input to the build, not a deliverable.
- `pull_transcript/package-lock.json` picks up an `engines` block whenever `npm
  install` runs. It was reverted during this run and is **not** in the range. If you
  see it dirty in a worktree, that is bootstrap churn, not this story.
- Story 1.13 (`_bmad-output/implementation-artifacts/sprint-status.yaml`) is still
  `backlog` and epics 2–4 are unstarted. Epic 5 depends on ingestion output that
  exists (epic 1 is done through 1.12) but on search, chat and publishing that do
  not. That is sequencing, not an omission.

## Verification baseline

Run these; all four are store-free, so a failure or skip during review is a finding,
not noise. Do **not** run `make test` or the full `pytest server/tests/` — the Docker
stores are shared between agents and the server fixture drops a fixed database.

| Command | Result observed at `3cceac1` |
|---|---|
| `make evals-test` | 194 passed in 0.58s, no Docker store and no api running |
| `uv run --project server pytest evals/tests -q` | 194 passed |
| `uv run --project server pytest server/tests/test_drop_schema.py -q` | 34 passed, unchanged |
| `make web-test` | 38 passed (3 files), unchanged |

The build's own review pass mutation-tested 15 lines and reported no survivors. If
you can break a line the suite should catch and it stays green, that is a finding.

## Required output

Write your findings to
`_bmad-output/implementation-artifacts/review-story-5-1-2026-08-19.md`.

Structure each finding as: file and line, what is wrong, the concrete failure
scenario (inputs or state → wrong behavior), and severity (high / medium / low)
judged by consequence for an eval operator running story 5.2's checks against this
ground truth.

Report findings. Do not apply fixes.
