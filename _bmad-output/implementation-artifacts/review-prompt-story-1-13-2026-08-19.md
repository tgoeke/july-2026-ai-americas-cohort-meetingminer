# Review prompt — Story 1.13: Drops Carry the Participant Graph

You have none of the build run's context. Everything you need is here or on disk.

## Repo, branch, range

- Repo: `/Users/devopsterus/current/cohort/meetingminer` (the story was built in the worktree
  `/Users/devopsterus/current/cohort/meetingminer-wt/1-13`; either checkout works — the branch is
  pushed).
- Branch: `story/1-13`, pushed to `origin/story/1-13`.
- Review range: **`342519e..HEAD`** (`342519e` is where the branch was cut). The branch was
  fast-forwarded onto `origin/main` after cutting, so two commits in the range are **not this
  story's work** and are called out below.

Commits in the range, oldest first:

| Revision | Subject | Whose |
|---|---|---|
| `9978bc2` | docs(spec): flag the missing intake door for a participants-only drop | **Not this story** — architect, arrived on main mid-run |
| `fab568a` | docs(epics): make the missing intake door a story 1.13 acceptance criterion | **Not this story** — architect, arrived on main mid-run |
| `11d9cc7` | docs(story 1.13): plan the participant-graph bridge | this story (spec + regenerated `epic-1-context.md`) |
| `fc61abf` | docs(story 1.13): name the partial-re-emit identity split | this story (spec amendment) |
| `237fe79` | feat(story 1.13): drops carry the participant graph | this story (the implementation) |
| `c40cde4` | docs(story 1.13): record the two review corrections and the verification run | this story |

`git log --oneline 342519e..HEAD` reproduces this.

## Spec

`_bmad-output/implementation-artifacts/spec-1-13-drops-carry-the-participant-graph.md`.

- **Frozen intent** — everything between `<intent-contract>` and `</intent-contract>`: Intent,
  Boundaries & Constraints, I/O & Edge-Case Matrix. This is derived from epics.md story 1.13 and
  the architect's two added acceptance criteria. Critique it only if you believe it contradicts
  epics.md or the architecture; do not treat a disagreement with it as a code finding.
- **Planner work, open to attack** — Code Map, Tasks & Acceptance, Spec Change Log, Design Notes,
  Verification. The Design Notes and the Spec Change Log are where the judgement calls live.

## Architecture authority

- `_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md`
  - **AD-1 (one canonical inbox: the source drop)** — amended by this story. New text: the puller
    maps `<stem> org chart.json` into `participants`; and it emits augmenting drops under
    `--re-emit` with a sequence discriminator. The previous text asserted "the puller does not
    emit augmenting drops".
  - **AD-14 (one intake door)** — amended by this story. The augmentation exception changes from
    "the occurrence has no recording yet and the new drop carries a recording" to "the new drop
    brings evidence the occurrence lacks — a recording the meeting has not got, or a
    `participants` array its current drop has not got". Also new: which stages are re-armed now
    depends on whether a recording was added.
  - **AD-5 (table ownership is disjoint)** — *not* amended, deliberately. See design decision 5.
  - **AD-13 (drop contents read-only)**, **AD-11 (a stage overwrites its own outputs)**,
    **AD-4 (projection triggers)** — unchanged, but the change touches all three.
- `_bmad-output/specs/spec-meetingminer/SPEC.md` — the kernel is unchanged by this branch. A
  parallel session was generalizing its augmentation wording on `main`; if that landed, it is
  outside this range.
- `_bmad-output/specs/spec-meetingminer/corpus-facts.md` §4 — the measured facts about
  `org chart.json` the mapping relies on.

## Scope

**In scope (the files `237fe79` and `c40cde4` touch):**

- `pull_transcript/emit-drop.js`, `pull_transcript/test/emit-drop.test.js`, `pull_transcript/CLAUDE.md`
- `server/meetingminer/api/ingests.py`, `server/meetingminer/domain/jobs.py`,
  `server/meetingminer/pipeline/runner.py`
- `server/meetingminer/pipeline/stages/align.py` — **docstring only**, no behaviour change
- `server/tests/test_ingests.py`, `server/tests/test_augmentation.py`
- `docs/source-drop.schema.json` — descriptions only, no structural change
- `ARCHITECTURE-SPINE.md`, `deferred-work.md`, `sprint-status.yaml`, the story spec,
  `epic-1-context.md`

**Explicitly out of scope:**

- `align`'s participant derivation, `speakers.identity_key_for`, migration `0005`, and the
  `participant` / `meeting_participant` schema. That half was built and reviewed in story 1.5;
  this story only makes it reachable.
- Whether `align` should union the drop graph with transcript labels rather than treat the graph
  as the roster authority. That is story 1.5's shipped reading (see design decision 6).
- Everything already in `deferred-work.md`, including the per-run test-database isolation that
  makes concurrent suite runs unsafe.
- The vendored `_bmad/`, `.agents/`, `.claude/` trees.
- The two architect commits named above.

## Design decisions to attack

Each is stated as the choice plus the assumption it rests on. The planner is not a neutral judge
of its own calls.

1. **The augmentation door is widened rather than a separate participant-import endpoint added.**
   Assumption: AD-14's "one intake door" is worth more than the narrowness of the augmentation
   contract, and "brings evidence the occurrence lacks" is a rule that stays coherent as more
   evidence kinds appear. If a third evidence kind cannot be expressed as "the target's drop
   lacks key X", the rule does not generalize and this is the wrong abstraction.

2. **A drop that adds nothing is `409 augment-adds-nothing`, not `422 invalid-augmenting-drop`.**
   Assumption: the drop is not invalid — the identical bytes are accepted against an occurrence
   that still lacks the evidence — so the refusal is about target state, and one problem type
   should map to one status. Attack: the API now has a `409` that a client cannot distinguish
   from the `409` duplicate-source-id conflict without reading `type`. Was that traded correctly?

3. **A participants-only augmentation re-arms only `align` and `moments`
   (`PARTICIPANT_AUGMENTATION_STAGES`), not the full `AUGMENTATION_STAGES`.**
   Assumption: nothing downstream of an unchanged recording depends on `align`'s participants, so
   `frames`/`ocr`/`screens` would re-derive identical evidence. Attack: is `moments` genuinely
   required here, and is there any path where a `done` video stage now holds output that
   disagrees with the re-run `align`?

4. **`runner.py` invalidates the meeting projection for *any* `augments`-declaring drop.**
   Assumption: every accepted augmentation changes something a projection describes. Attack: this
   widens a trigger that previously fired only on recording recovery — is there an accepted
   augmentation that should *not* cost a re-projection?

5. **The name-keyed/mail-keyed identity split is mitigated operationally, not structurally.**
   `--re-emit` is opt-in per occurrence, so the same person can be `mail:…` in one meeting and
   `name:…` in another with nothing linking the two `participant` rows, and the
   participants → meetings → topics → moments traversal then returns half that person's meetings.
   The mitigation is that the migration is one `--all --re-emit` pass and every pass reports how
   many drop prefixes still carry no `participants` key. The structural fix — `align` writing a
   `name:` → mail-keyed-participant alias — was **not** taken because AD-5 assigns
   `participant_alias` to the API. Assumption: an AD-5 amendment is too expensive for a
   29-occurrence corpus. Attack: is the reported count actually sufficient to notice a partial
   migration, given it is read from the drops folder and not from the database?

6. **The graph replaces the transcript-label roster rather than being unioned with it.** Story
   1.5's shipped behaviour, now observable for the first time. A transcript speaker absent from
   the chart becomes `unresolved` instead of a name-keyed participant. Assumption: the charts'
   `attendeeSources` record `transcript speakers (N)`, so the graph covers them in this corpus.
   This is the behaviour change most likely to surprise, and it is the one to check against real
   data if you check anything against real data.

7. **`participants: []` counts as "no graph" on both sides of the intake comparison, and the
   puller never emits `[]`.** Assumption: `align` reads `[]` as "the source looked and found
   nobody" and suppresses the transcript fallback, so emitting it for a broken chart would strip
   a meeting of everyone. Attack: is treating `[]` as absent at the door the right reading of a
   deliberate empty assertion?

8. **The re-emit discriminator is a zero-padded three-digit sequence, base name = sequence 1.**
   Assumptions: the 28 finalized drops must keep their names; emit order must survive as lexical
   order within an occurrence's `<date>-<slug>-<sha1_8>` prefix; 999 re-emits per occurrence is
   enough. Attack: `splitDropName` decides sequence-vs-prefix by the regex `^(.+)-(\d{3})$` —
   is there a drop name it can misparse?

9. **`--re-emit` emits only what intake will accept, not on any difference.** See the Spec Change
   Log. Assumption: a puller that finalizes a drop the door refuses creates a worse state than
   one that declines to migrate — because the refused drop is still write-once on disk and the
   next pass reads it as the newest. Consequence to weigh: a re-resolved chart can never reach an
   already-migrated meeting through this path at all.

## History a reviewer needs

- **The branch was fast-forwarded mid-run.** It was cut at `342519e`; `9978bc2` and `fab568a`
  arrived on `main` afterwards and were merged in before implementation. Story 1.13's acceptance
  criteria in `epics.md` therefore differ from what they were when the branch was cut — two were
  added, and the first of them (the missing intake door) is the reason this story touches the
  server at all.
- **The story text says 28 occurrences; the live archive now holds 29.** The corpus gained one
  since the 2026-08-18 measurement. The drops root holds 28 finalized drops, so one occurrence
  has never been emitted. Neither number is a defect; do not read the mismatch as one.
- **A pre-existing condition that is now fixed:** spec-1-5 recorded "two pre-existing suite
  failures make `make test` red". They were repaired in `f7f5ac1` before this branch. `make test`
  is green on this branch, so any red you see is a regression.
- **`pull_transcript/package-lock.json`** gains a 3-line `engines` block whenever `npm install`
  runs. It was restored, not committed. If it reappears in your tree, it is npm, not the story.
- **The real participant graphs are on an external mount**, `/Volumes/nvmepool/mm_current/pull_transcript/`,
  not in the repo checkout's `pull_transcript/`. An earlier story recorded (wrongly) that no
  `org chart.json` existed on this machine; that correction is in spec-1-5's Design Notes.

## Verification baseline

Run from the worktree or the main checkout. **The Docker stores are shared and the test fixture
drops a fixed-name database — hold them one agent at a time (`AGENTS.md`).**

| Command | Result on `c40cde4` |
|---|---|
| `make test` | 742 passed, 0 failed, 1 warning (pre-existing starlette/httpx deprecation), 248s, then a clean web build |
| `make puller-test` | 98 pass, 0 fail, **0 skipped** — the schema cases ran |
| `make web-test` | 38 pass, 3 files |
| `git status --porcelain` | empty |
| `git rev-list --left-right --count HEAD...@{u}` | `0	0` |

Corpus checks (read-only, no stores, external mount required):

- Sweep of all 29 occurrences through `planDrop` + ajv: 29 valid, 0 invalid, 29 carrying
  `participants`, 233 person rows, 230 with `mail`, 216 with `managerChain`, 3 `unresolved: true`,
  0 `guest: true`.
- `node pull_transcript/emit-drop.js --dry-run "<occurrence>"` prints `people 7` for the
  7.14.26 R2C occurrence, matching its chart's `people[]` length.
- `--dry-run --re-emit --drops /Users/devopsterus/current/meetingminer-drops` targets `…-002`
  with `schemaVersion 2` + `augments`, reports `participants: 28 of 28 drop prefixes still carry
  no participants key`, and writes nothing.

A skip or failure against this baseline is a finding, not noise. **No live `--re-emit` write pass
has been run** — it would create 28 drops and POST them — so the write path is proven by the test
suite and by dry runs only. That is the largest unexercised surface in this change.

## Required output

Write your review to
`_bmad-output/implementation-artifacts/review-story-1-13-2026-08-19.md`.

**Report findings; do not apply fixes.** Structure each finding as:

- **Severity** — `high` / `medium` / `low`
- **Location** — `path:line`
- **Claim** — one sentence
- **Failure scenario** — concrete inputs or state → wrong output, in enough detail that someone
  can reproduce it without re-deriving your reasoning
- **Evidence** — what you read or ran

Close with an overall verdict and, separately, a list of anything you checked and found sound —
the negative results matter, because they tell the next pass what not to re-audit.
