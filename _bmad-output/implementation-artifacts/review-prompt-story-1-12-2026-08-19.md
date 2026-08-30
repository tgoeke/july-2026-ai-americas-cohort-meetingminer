# Review prompt — Story 1.12: Late-Recording Augmentation

You are reviewing a completed, pushed branch. You have none of the build run's
context; everything you need is below. **Report findings — do not apply fixes.**

## Repo, branch, range

- Repo: `/Users/devopsterus/current/cohort/meetingminer` (main checkout).
  The work is on a worktree: `/Users/devopsterus/current/cohort/meetingminer-wt/1-12`.
- Branch: `story/1-12`, pushed, in sync with `origin/story/1-12`.
- Review range: **`6ff87a4..HEAD`** (HEAD is `474fce0`). `6ff87a4` is `main` at branch time.

Commits in range, oldest first:

- `5e1aa35` docs(story-1.12): plan late-recording augmentation
- `f06b54e` feat(intake,worker): accept a late-recording augmenting drop
- `5857435` test(schema): pin schemaVersion 2 and the augments declaration
- `678a1ea` test(api): the intake matrix for an augmenting drop
- `9b44976` test(augmentation): the story's end-to-end acceptance evidence
- `db9292e` test(projections): augmentation re-projects one meeting, and only that one
- `643e48a` docs(architecture): record schemaVersion 2 and the augmenting-drop intake path
- `18f7c50` docs(story-1.12): mark late-recording augmentation done
- `e9d7f30` docs(story-1.12): say what is true about the constant, the race, and the puller
- `b4e4c1f` fix(api): an augmenting drop may not rewrite the meeting's wall clock
- `c3c3bbd` test(augmentation): pin AUGMENTATION_STAGES and witness the stages by outcome
- `2e9fe32` test(augmentation): drive the whole chain into both stores, end to end
- `5fdf19b` docs(api): state the augmenting-drop refusal count plainly
- `474fce0` docs(story-1.12): record the review pass and its deferrals

**Every commit in the range belongs to story 1.12.** No other story's work is mixed in.
Commits `e9d7f30` through `5fdf19b` are an in-run review-remediation pass, not new
feature work — they are already the product of one adversarial review, so findings
that merely restate them are not new.

## Spec

`_bmad-output/implementation-artifacts/spec-1-12-late-recording-augmentation.md`.

- The `<intent-contract>` block is **frozen intent** — Problem, Approach,
  Boundaries & Constraints, and the I/O & Edge-Case Matrix. Critique whether the
  code satisfies it, not whether it should have said something else.
- **Everything outside that block is planner work you may attack**: the Code Map,
  Tasks & Acceptance, Design Notes, the Review Triage Log, and the `deferred` list.
  The Design Notes carry the design decisions listed below and are the most
  valuable target.

Story text and ACs: `_bmad-output/planning-artifacts/epics.md`, "Story 1.12:
Late-Recording Augmentation" (FR32, FR3, FR4, UX-DR11).

## Architecture authority

These specific decision records govern the change, in
`_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md`:

- **AD-1** (one canonical inbox: the source drop) — owns the drop schema. **Amended by this branch.**
- **AD-14** (one intake door) — owns the `POST /ingests` conflict rule. **Amended by this branch.**
  Both amendments are in `643e48a`; judge whether the amended text matches what the code does.
- **AD-11** (jobs are Postgres rows; stages idempotent and restartable) — the rerun semantics augmentation relies on.
- **AD-13** (provided transcripts are immutable inputs; merge, never erase) — why intake refuses a drop that sheds a transcript.
- **AD-4** (projections have exactly one writer) — why the invalidation helper lives in `projections/` and the API never touches `meeting_projection`.
- **AD-5** (disjoint table ownership) — why the job row is re-armed rather than a second job created.

SPEC constraint that dominates: *"Augmentation adds, never destroys."*
(`_bmad-output/specs/spec-meetingminer/SPEC.md`, Constraints.)

## Scope

**In scope — the files this branch changed:**

- `docs/source-drop.schema.json`
- `server/meetingminer/api/ingests.py`
- `server/meetingminer/domain/jobs.py`
- `server/meetingminer/domain/drops.py`
- `server/meetingminer/pipeline/runner.py`
- `server/meetingminer/projections/__init__.py`
- `server/tests/test_augmentation.py` (new), `test_ingests.py`, `test_drop_schema.py`, `test_projections_rebuild.py`
- `pull_transcript/test/emit-drop.test.js`, `pull_transcript/CLAUDE.md`
- `_bmad-output/...` (spec, deferred-work, ARCHITECTURE-SPINE)

**Explicitly out of scope:**

- `pull_transcript/emit-drop.js` — deliberately unmodified. See "Design decisions" #5.
- Any moment API route or moment UI — Epic 2 owns those. There is no moment
  endpoint and no moment view in this codebase; UX-DR11's "renders a true replay
  button" is discharged at the data layer (`source_deep_link` NULL,
  `screenshot_id` non-NULL). Do not report the absent UI as a defect; do report
  it if you think the data-layer substitution is unsound.
- The `extract` stage (Epic 4) and the citation validator (AD-15) — neither
  exists in this tree, which is why AC 5 ("citations still resolve") is
  discharged as moment-id stability. Attack that reduction if you think it fails.
- The nine items already recorded in the spec's frontmatter `deferred` list, and
  everything in `_bmad-output/implementation-artifacts/deferred-work.md`. Re-reporting
  a recorded deferral is noise; *disagreeing that it is safe to defer* is a finding.

## Design decisions to attack

Each is stated as the choice plus the assumption it rests on. The planner is not
a neutral judge of its own calls.

1. **Augmentation re-arms the occurrence's existing job in place** rather than
   creating a second job.
   *Assumption:* `meeting.job_id UNIQUE`, `meeting.source_id UNIQUE` and
   `job_source_id_live_key` are load-bearing, and AD-14's "a rerun of its
   existing job, never a second Meeting row" is prescriptive rather than
   descriptive of the failure case only. If that reading is wrong, the whole
   shape is wrong.

2. **`augments` is an object keyed by `sourceId`, and the drop's own `sourceId`
   may differ from it.**
   *Assumption:* the SPEC's "declares which meeting it augments *rather than
   colliding on `sourceId`*" means the declaration is the link. A consequence
   worth attacking: when the two differ, the recovered recording's own identity
   is persisted nowhere in Postgres.

3. **`schemaVersion` becomes `enum: [1, 2]` with `augments` implying version 2.**
   *Assumption:* fail-closed matters more than letting a v1-pinned consumer
   accept the drop. Check the `allOf`/`if-then` actually achieves this and that
   no v1 drop can smuggle `augments` past it.

4. **The re-run set is `AUGMENTATION_STAGES` = the five video stages + `align` +
   `moments`** — seven, where AC 2 names six ("plus align").
   *Assumption:* `moments` must re-run or ACs 3, 4 and 6 are unobservable, and
   AC 2's "does not re-run stages whose outputs already exist" means "stages the
   recording does not invalidate", which is only `extract`. This is the clearest
   place the implementation reads past the AC's literal words.

5. **The puller is scoped out.**
   *Assumption:* `emit-drop.js`'s directory-name identity
   (`<date>-<title-slug>-<sha1(sourceId)[0:8]>` + `existsSync`) makes a
   video-bearing re-pull return `exists`, so extending it is a separate story.
   Consequence: this path is exercised only by hand-authored/fixture drops.

6. **Intake refuses a `startedAt`/`startedAtPrecision` mismatch, but allows
   `title` and `provenance` to be restated.**
   *Assumption:* `mint_meeting`'s `ON CONFLICT` would otherwise shift every
   preserved moment's wall clock (moments stamp `meeting.started_at + start_ms`),
   and that is destruction; renaming is not. Note this also refuses a genuine
   `day`→`second` precision upgrade — recorded as a deferral, not fixed.

7. **The runner infers augmentation from state** (`drop.has_recording and
   persisted has_recording is False`), never from the `augments` field.
   *Assumption:* the state transition is the real trigger, so the pre-existing
   failed-job re-queue path with a recording-bearing drop correctly takes the
   same branch. The log event is nonetheless named `job.augmenting`.

8. **Invalidation drops only the `meeting_projection` row**, rather than calling
   `unproject_meeting`.
   *Assumption:* keeping the meeting searchable from its transcript during the
   re-run is worth the race window (a concurrent `rebuild` re-inserting the row
   restores `ACTION_NONE` and the augmented bundle never projects). The docstring
   states that window; check it is honest.

## History you need

- The branch was cut from `main` at `6ff87a4` and has never been rebased. No
  commits were dropped or amended after pushing.
- Commit `18f7c50` set the spec `status: done` prematurely; `474fce0` is the real
  finalization after the review pass. Read `474fce0`'s version of the spec, not
  `18f7c50`'s.
- One process deviation to be aware of, already reported: the implementation
  agent ran `git stash` once inside its own worktree while establishing a
  baseline. It captured only a spec frontmatter edit and was popped back
  immediately; nothing was lost, and the tree is clean. It is on the AGENTS.md
  prohibited list and should not have been used.

## Verification baseline

Run from the worktree. These are the results observed at `474fce0` — a *new*
failure or skip during your review is a finding, not noise.

| Command | Observed |
|---|---|
| `cd server && uv run pytest tests/test_drop_schema.py tests/test_moments_core.py tests/test_projections_single_writer.py -q` | 66 passed |
| `make puller-test` | 74 pass, 0 fail, `emit-drop.js` byte-identical to baseline |
| `cd server && uv run pytest tests/test_ingests.py tests/test_augmentation.py tests/test_worker_runner.py tests/test_worker_moments.py tests/test_drop_schema.py tests/test_projections_rebuild.py tests/test_projections_graph.py tests/test_projections_search.py -q` | 202 passed, 1 failed |
| `make test` | **727 passed, 2 failed** |

**The 2 failures are pre-existing and inherited from `main`.** Verified by checking
out `6ff87a4` over `server/` and `docs/` — none of this story's code present — and
re-running; both still fail. Do not attribute them to this branch:

- `tests/test_ocr_adapter.py::test_parse_tsv_without_page_dimensions_is_a_named_error`
- `tests/test_worker_runner.py::test_empty_and_populated_stage_logs_carry_the_same_fields`
  — asserts `stage.screens.captured.directory is None` on a zero-capture run; the
  stage now reports the directory. Most likely story 1.11's capture retune.

**Store-backed suites need the shared Docker stack** (Postgres 5433, Neo4j 7687,
Meilisearch 7700) and the fixture drops `meetingminer_test WITH FORCE`. Hold the
stores one agent at a time — announce before running (AGENTS.md).

A mutation check was performed on the key new test: disabling the runner's
`invalidate_meeting_projection` call makes
`test_augmentation_replaces_the_meetings_documents_in_both_stores` fail, so it
witnesses the chain rather than restating it. Consider whether the other new
assertions would survive the same treatment.

## Required output

Write your findings to:

`_bmad-output/implementation-artifacts/review-story-1-12-2026-08-19.md`

Structure each finding as:

```
### <short title>
- **Severity:** high | medium | low
- **Location:** file:line
- **Finding:** what is wrong
- **Evidence:** why it is real — the failing input/state and the resulting behaviour
- **Suggested direction:** what a fix would have to do (do not apply it)
```

Order most-severe first. Close with a short verdict: whether the branch is safe to
merge as-is, safe with follow-ups, or should not merge.

**Report findings; do not apply fixes.** If you cannot verify a suspicion, say so
and mark it unconfirmed rather than asserting it — two findings in the in-run
review pass were confidently stated and factually wrong.
