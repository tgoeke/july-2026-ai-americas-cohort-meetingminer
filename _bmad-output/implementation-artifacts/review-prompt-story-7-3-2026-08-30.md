# Review handoff — Story 7.3: Speaker Assignment

## 1. What you must produce, before anything else

**Write your report to
`_bmad-output/implementation-artifacts/review-story-7-3-2026-08-30.md`.**

**REPORT-FIRST, and this is not negotiable.** Create that file as a skeleton —
scope, review range, an empty findings section — and **commit it before you read
a single line of code**. Then append each finding as you confirm it and commit
incrementally. Six reviews in this repository produced their report only as
terminal text and were lost; a crashed or closed session must lose prose, never
the artifact.

Each finding carries: **Location / Severity / Finding / Evidence / Suggested
direction.**

**The review lane fixes what it finds.** Report every finding in the report file
first, then FIX the patchable ones yourself on `story/7-3-review` (cut from
`story/7-3`, in your own worktree — `make worktree STORY=7-3-review`), red-first:
the test observed failing against the unfixed code, then the fix, then green,
committing each with its finding number. Hand nothing back to a builder.

Do **not** fix: anything needing an owner decision, and anything whose root cause
is the frozen spec — report those, mark them clearly **open**, and leave them for
the owner. Never commit to `main`, never work in the main checkout, never merge;
the owner runs `integrate`.

**Closeout.** Before reporting completion, run `make check-reviews` (it fails
while any dispatched review lacks a committed report, including this one) and
state the SHA carrying the report's final version. A review reported in the
terminal but not filed does not exist.

## 2. Repo, branch, range

- Repo: `/Users/devopsterus/current/cohort/meetingminer` (main checkout — do not
  work in it). Builder worktree: `../meetingminer-wt/7-3`.
- Branch under review: `story/7-3`, pushed to `origin/story/7-3`.
- Review range: `4b7e60174f640f09f6e903255064193018ef223b..HEAD` — the spec commit
  is the baseline, so the range is the implementation only. `git log --oneline
  4b7e601..HEAD` lists:
  - `f6edccf` test(7-3): speaker assignment contract, red before the implementation
  - `8465a8c` feat(7-3): assign a speaker, and re-attribute without breaking a citation
  - `128ba24` chore(7-3): regenerate the typed client for assignMeetingSpeaker
  - `d8e0966` test(7-3): admit the write route to the speakers router's pinned path set
  - plus the closing docs/spec/sprint commit (see `git log` for its SHA).
- The branch was cut from `main` at `ea0c113`. No commit in the range belongs to
  another story.

## 3. Spec, and which parts are frozen

Spec: `_bmad-output/implementation-artifacts/spec-7-3-speaker-assignment.md`
(status `review`).

- **Frozen intent** — everything inside `<intent-contract>`: Intent, Boundaries &
  Constraints, and the I/O & Edge-Case Matrix. Critique it, but a defect rooted
  there is *reported open*, not patched.
- **Planner work you may attack freely** — the Code Map, Tasks & Acceptance,
  Design Notes, and every Spec Change Log entry.

**One deliberate mismatch you must not "fix" back.** The frozen matrix row "Assign
a new display name" says the minted participant's `identity_key` is the alias key.
The build proved that is a defect — `api/participants.py` reads "this row's
identity key appears as some alias key" as "merged away", so such a row could
never be merged, closing the recovery path the design depends on. The minted row
therefore uses a separate space, `curated:<meetingId>:<tag>`. The intent-contract
is read-only after planning, so the row was left alone and the correction recorded
in the Change Log and Auto Run Result. Reverting the code to match that row would
reintroduce the defect.

## 4. Architecture authority

- **AD-5 (table ownership is disjoint)** — the api writes `participant_alias` and
  `participant`; the worker writes evidence. The story adds a third alias-key
  space (`speaker:`) and a fourth identity space (`curated:`) beside `mail:` and
  `name:`. Check that no api path writes `transcript_segment`, `moment` or
  `artifact`, and that `align` only *reads* the api-owned table.
- **AD-6 (citations are Postgres-minted moment ids)** — the story's primary
  clause. A rename must leave every moment id resolvable.
- **AD-13 (provided transcripts immutable; never guess)** — cue timing owns
  `start_ms`, which is what pins moment identity across the rerun; and a tag
  resolves to a person only where the source or an alias says so.
- **AD-9 (exactly one worker)** — why the route refuses to re-arm a `running` job.
- **AD-11 (idempotence)** — `extract` is delete-and-re-propose scoped to drafts.
- `docs/architecture.md`, plus `_bmad-output/implementation-artifacts/epic-7-context.md`.

## 5. Scope

**In scope (the whole change):**
- `server/meetingminer/domain/speaker_assignments.py` — NEW; both key spaces.
- `server/meetingminer/domain/jobs.py` — `SPEAKER_ASSIGNMENT_STAGES`.
- `server/meetingminer/api/speakers.py` — the PUT route only; 7.2's read route,
  `SpeakerTag` and `MeetingSpeakersResponse` are untouched and must stay so.
- `server/meetingminer/pipeline/stages/align.py` — assignment lookup, the
  resolution override, and attendance rows.
- `server/meetingminer/api/participants.py` — `_HAS_ABSORBED_ALIASES` excludes the
  `speaker:` namespace.
- `server/tests/test_api_speaker_assignment.py` — NEW, 27 tests.
- `server/tests/test_api_speakers.py`, `server/tests/test_compose_contract.py` —
  one forced line each.
- `web/src/client/*.gen.ts` — regenerated, additive only.
- `docs/backlog.md` — B-39, B-40.

**Out of scope:** story 7.4's naming UI; `pipeline/speakers.py`,
`pipeline/stages/transcribe.py` and `adapters/diarize/**` (story 7.1 / B-36);
`web/` UI beyond the generated client; anything already recorded in
`deferred-work.md`.

## 6. The design calls to attack

Each is a choice plus the assumption under it. The planner is not a neutral judge
of its own calls.

1. **`align.py` was edited although the build prompt's footprint table did not
   name it.** Assumption: without it no alias can reach a segment
   (`resolve_label` short-circuits a `SPEAKER_NN` tag to `placeholder` before any
   roster match, and the alias table is otherwise consulted only for *roster*
   identity keys), so the route would write a record that changes nothing and the
   story's primary criterion would be vacuous. Recorded in the Change Log and
   verified collision-free. Attack the reasoning and the size of the edit.
2. **`unresolved` is a deletion, not a stored negative.** Assumption:
   `participant_alias.participant_id` is `NOT NULL`, and the footprint admits only
   a `participant_alias` write. Consequence: a *source-attributed* label cannot be
   pushed back to `placeholder` (B-39). Is the reading of the AC right?
3. **A curator's typed name is keyed per meeting (`curated:<meetingId>:<tag>`),
   accepting a split.** Assumption: the api may not import `pipeline`, and a second
   `normalize_display_name` would be a second source of truth for identity keys —
   a silent merge, which is unrecoverable, versus a split, which is not (B-40).
   `normalized_name` is set to the key rather than a name so it can never match a
   transcript label later. Attack both halves.
4. **The re-arm includes `extract`, which both augmentation tuples exclude.**
   Assumption: those exclude it because *intake* must not re-propose over human
   approval; here the trigger is a human, the AC names the stage, and `extract`
   protects approvals itself. Verify the protection really is the stage's.
5. **A `running` job is refused with 409 `assignment-target-busy`.** Assumption:
   re-arming a claimed job races the single worker's final status write and could
   drop the assignment silently. Is the window actually closed, given the route is
   READ COMMITTED and takes no lock on the job row? **This is the sharpest place to
   look for a real defect.**
6. **READ COMMITTED, not the read routes' REPEATABLE READ.** Assumption: the checks
   span five tables and a frozen snapshot would decide against a stale job status.
7. **Attendance rows are written by `align` with `derived_from='transcript'`.**
   Assumption: without them `projections/graph.py`'s `MATCH (p:Participant …)`
   silently drops the `SPOKE_IN` edge.
8. **Exactly one merge hop** from an assignment, matching `merge_participants`'
   flat-map rule.
9. **The tag travels in the URL path.** A label with a comma and space is tested;
   one containing `/` is not, and is named as a residual risk.

## 7. History you need to tell a regression from a pre-existing condition

- Story 7.2 landed today; `api/speakers.py` and `test_api_speakers.py` are its
  work, and its "named and unnamed sources share one shape" criterion is pinned by
  tests that still pass unchanged.
- `test_compose_contract.py::test_the_per_test_slow_set_is_exactly_the_measured_four`
  was already named "four" while listing five entries *before* this branch; it now
  lists six. The name drifted earlier and was left alone as out of footprint.
- `test_frame_image.py::test_an_unreadable_frame_raises_a_named_error` tripped the
  2.0s fast-set budget once at 2.39s during a run concurrent with a sibling
  worktree's suite, and ran at 0.01s alone. Contention, which the budget plugin's
  own message says is not a reason to mark. It is not this story's test.
- The two suite skips are pre-existing environment skips: no `pyannote` module in
  the default venv, and the network-gated yt-dlp test.

## 8. Verification baseline

So a skip or failure during review reads as a finding rather than noise. All run
in the builder's worktree against its private stack `meetingminer-7-3`
(ports 22701–22707).

- `uv run --project server pytest -m "" server/tests/test_api_speaker_assignment.py -q`
  — **27 passed**.
- `make test-fast` — **1984 passed, 2 skipped, 383 deselected, 59.24s**; lint and
  typecheck inside the target, both green.
- Slow half in three batches (the whole gate exceeds one foreground call):
  projections **152 passed** (244.67s); api/augmentation/extract/this story
  **111 passed** (183.54s); infra/migrations/parallel-safety **120 passed**
  (123.64s). 152+111+120 = **383**, exactly the 383 the fast run deselected, so
  fast + slow = 2367 accounts for `-m ""` entirely.
- `make check-client puller-test web-test evals-test diarize-extra-test` — green;
  measured individually: puller `# pass 128 / # fail 0`, web 16 files / 294 tests,
  evals **643 passed**, diarize-extra **92 passed**.
- `pnpm --dir web run build` — built in 393ms.
- `python3 _bmad/scripts/branch_conflicts.py --against story/7-3` — see the run
  report; re-run it yourself before you push.

**Coverage was demonstrated, not asserted.** The test module was written first and
observed failing whole. Eight mutations were then applied and reverted, each
producing the named reds: align ignoring the assignment (3 red); the re-arm
dropping `extract` (2 red); `extract` deleting drafts on an approved moment (the
citation test red); no attendance row (1 red); no merge hop (1 red); the
`speaker:` filter removed from the merge predicate (1 red); and an assignment
perturbing segment timing by 1 ms, which re-keys `transcript:40000` to
`transcript:40001` — caught precisely by the citation test. One attempted mutation
(re-keying every moment symmetrically) was a **non**-mutation and is reported as
such rather than as coverage.

## 9. Where a reviewer should look hardest

1. The `running`-job window in `assign_meeting_speaker` (design call 5).
2. Whether anything else in the codebase assumes every `participant_alias` row is
   a merge record. `_HAS_ABSORBED_ALIASES` was found and fixed; `_IS_ALIASED` was
   judged safe because a `speaker:` key is never a participant's `identity_key`.
   Confirm that, and sweep for other readers of that table
   (`grep -rn participant_alias server/`).
3. Whether a re-armed job that fails mid-rerun leaves the meeting permanently
   unviewable, and what the curator sees then.
4. The `augmenting: false` extension during a speaker rerun (named in the spec's
   residual risks) — is that misleading enough to matter for story 7.4?
