# Review handoff — Story 7.4: Speaker Naming UI

## 1. What you must produce, before anything else

**Write your report to
`_bmad-output/implementation-artifacts/review-story-7-4-2026-08-31.md`.**

**REPORT-FIRST, and this is not negotiable.** Create that file as a skeleton —
scope, review range, an empty findings section — and **commit it before you
read a single line of code**. Then append each finding as you confirm it and
commit incrementally. Several reviews in this repository produced their report
only as terminal text and were lost; a crashed or closed session must lose
prose, never the artifact.

Each finding carries: **Location / Severity / Finding / Evidence / Suggested
direction.**

**The review lane fixes what it finds.** Report every finding in the report
file first (report-first, committed before reading code), then FIX the
patchable ones yourself on `story/7-4-review` (cut from `story/7-4`, in your
own worktree — `make worktree STORY=7-4-review BASE=story/7-4`), red-first —
the test observed failing against the unfixed code, then the fix, then green,
committing each with its finding number. Hand nothing back to a builder.

Do **not** fix: anything needing an owner decision, and anything whose root
cause is the frozen spec — report those, mark them clearly **open**, and leave
them for the owner. Never commit to `main`, never work in the main checkout,
never merge; the owner runs `integrate`.

**Closeout.** Before reporting completion, run `make check-reviews` (it fails
while any dispatched review lacks a committed report, including this one) and
state the SHA carrying the report's final version.

## 2. Repo, branch, range

- Repo: `/Users/devopsterus/current/cohort/meetingminer` (main checkout — do
  not work in it). Builder worktree: `../meetingminer-wt/7-4`.
- Branch under review: `story/7-4`, pushed to `origin/story/7-4`.
- Branch cut from `main` at `3211a7f`. Review range:
  `4e35269..HEAD` — the spec commit is the baseline, so the range is the
  implementation only:
  - `b5635a9` feat(7-4): an optional endMs so a speaker sample stops after eight seconds
  - `e9ae606` feat(7-4): the speaker naming screen
  - `325dea3` feat(7-4): reach the speakers screen from the meeting view
  - plus the closing docs/spec/sprint commit (see `git log` for its SHA).
- No commit in the range belongs to another story.

## 3. Spec and design sources

- Spec: `_bmad-output/implementation-artifacts/spec-7-4-speaker-naming-ui.md`
  (`status: review`). Its **Deviations from the design spines** section names
  three departures with reasons — treat those reasons as the thing to attack,
  not the departures themselves.
- Story: `epics.md` Story 7.4. Design:
  `_bmad-output/planning-artifacts/ux-designs/ux-meetingminer-2026-08-29/`
  — `DESIGN.md`, `EXPERIENCE.md`, and `mockups/speaker-naming.html`. **The
  spines win where a mockup disagrees with them.**
- Wave rules: `wave-2026-08-30-rules.md` in this directory.

## 4. Where to aim

This is a demo-critical screen built in one sitting against a hard deadline.
Aim at the four clauses that carry the risk, in this order:

1. **The unsettled-evidence clause, and it is the one to attack hardest.**
   Story 7.3's `PUT` is deliberately admitted while a meeting is unviewable
   (see the long comment in `server/meetingminer/api/speakers.py` at
   `assign_meeting_speaker`), while `GET …/speakers` and `GET …/drilldown`
   both still refuse it with 409. A successful naming therefore makes this
   screen's own reads start refusing seconds later. The screen's answer is to
   never clear on a refused re-read. **Find the state where that answer is
   wrong or incomplete** — a meeting change mid-rerun, a second naming during
   the refusal window, an aborted read landing after a fresh one, the
   selection pointing at a tag the kept rows no longer contain. The builder
   mutation-checked the main case (a blanking implementation fails three
   tests); the interesting failures are the ones the mutation did not reach.

2. **Never a guessed identity (AD-13).** `isResolved()` in
   `web/src/features/speakers/speakers.ts` is the whole rule. Look for any
   path where a name reaches the screen without it — the row, the accessible
   name, the field label, the landed sentence, the transcript column.

3. **All three assignment paths.** Existing participant, typed new name,
   `unresolved`. The api's rule is *exactly one* of three fields; the failure
   mode is sending two. `choiceOf()` drops a picked participant once the field
   no longer holds its name — test that boundary harder than the builder did
   (whitespace, a rename that restores the original text, two participants
   with the same display name).

4. **Surfacing the rerun rather than a hang.** `applyJobEvent()` folds
   `/jobs/events` frames; check the frames it ignores, the settle frame's
   "everything not failed is done" assumption, and whether a rerun that never
   emits anything leaves the strip lying.

Also worth a pass: the combobox's ARIA against WCAG 2.2 AA (the field is a
hand-rolled `role="combobox"`, not a library one); the `ReplayPlayer` latch
under a real media element rather than jsdom's stub; and whether the meeting
view insertion is genuinely minimal — story 2.2's suite passing is evidence,
not proof.

## 5. What is out of scope

- `server/**` — this story wrote none of it. B-41 and B-42 (`docs/backlog.md`)
  are the two api-side gaps found; both need an owner decision, so report
  anything you find about them as **open** rather than fixing it.
- The app shell (story 10.5), the ask box (story 8.3), and
  `web/src/client/*.gen.ts` (generated; both endpoints were already in it).

## 6. Verification the builder ran

- `make test-fast` — 2173 passed, 3 skipped (pyannote import, LAN diarization
  host, real yt-dlp — all pre-existing, all with named reasons).
- `make lint`, `make typecheck`, `make check-client` — clean.
- Full web suite — 365 passed across 20 files, story 2.2's own
  `MeetingMoments.test.tsx` unchanged and passing.
- The speakers suite run three times for flake: 62 passed each time.
- Mutation check on the load-bearing clause: making a refused read call
  `setSpeakers(null)` fails 3 tests.

Re-run all of it. `make bootstrap` then `uv sync --project server` first.
Never run `make evals-run`, never start the shared api or worker.
