# Review prompt — Story 6.5: Add-Meeting UI

Hand this file to the Codex `bmad-code-review` agent. It stands alone; the
reviewer has none of the build run's context.

## Required output — read this first

**Write the report to
`_bmad-output/implementation-artifacts/review-story-6-5-2026-08-31.md`.**

Each finding uses this structure:

- **Location** — `path:line`
- **Severity** — high | medium | low
- **Finding** — what is wrong
- **Evidence** — why it is real, cited to code or to a named authority file
- **Suggested direction** — what a fix must achieve

**REPORT-FIRST.** Create and commit the report file as a skeleton — scope,
range, an empty findings section — **before reading any code**. Then append
each finding as you confirm it and commit incrementally. Four reviews in this
repository were completed in a session's terminal and never filed, every one of
them written report-last. A crashed or closed session must lose prose, never
the artifact.

**This review lane applies its own patch findings** (repository convention,
corrected 2026-08-30). Report every finding in the report file first, then fix
the patchable ones yourself on `story/6-5-review`, cut from `story/6-5`, in its
own worktree (`make worktree STORY=6-5-review` — never the main checkout).
Work red-first: the test observed failing against the unfixed code, then the
fix, then green. Hand nothing back to a builder.

**Do not fix**: anything needing an owner decision, and anything whose root
cause is the frozen spec (`<intent-contract>`). Report those, mark them open,
and leave them for the owner. Never merge to `main`; the owner runs
`integrate`.

**Closeout.** Before reporting completion, run `make check-reviews` — it fails
while any dispatched review lacks a committed report, including this one — and
state the SHA carrying the report's final version. A review reported in the
terminal but not filed does not exist.

## Repo, branch, range

- Repo: `/Users/devopsterus/current/cohort/meetingminer` (main checkout — do
  not work in it). Build worktree: `/Users/devopsterus/current/cohort/meetingminer-wt/6-5`.
- Branch: `story/6-5`, cut from `main` at `2d68dcc6dba31007c7d6fd84f0884edbc79508d5`.
- Review range: `2d68dcc6dba31007c7d6fd84f0884edbc79508d5..HEAD`.

Commits in the range:

- `a6ec4dbfc2c825281fad98e707daa7d04e69b95a` — docs(6-5): plan the Add-meeting UI — the /add route and the YouTube URL flow
- `b415a70f…` — feat(6-5): the Add-meeting screen at /add, with the YouTube URL flow
- `5dbce863…` — test(6-5): cover the Add-meeting flow and every one of its failure states

(plus the finalization commit adding this file, the spec's `## Auto Run
Result`, and the sprint-status key.)

No commit in the range belongs to another story.

## Spec

`_bmad-output/implementation-artifacts/spec-6-5-add-meeting-ui.md`.

- **Frozen intent** — everything inside `<intent-contract>`: Intent,
  Boundaries & Constraints, and the I/O & Edge-Case Matrix. A finding whose
  root cause is in there is reported and left open, not fixed.
- **Planner work, fair game for critique** — `## Code Map`,
  `## Tasks & Acceptance`, `## Design Notes`, `## Verification`, and
  `## Auto Run Result`. The Code Map's line anchors, the reuse choices, and the
  Design Notes' four rationales are the planner's own calls and are not
  privileged.

## Architecture authority

- `docs/architecture.md` and
  `_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md`
  — the two must stay in sync (AD-1…AD-18).
  - **AD-11** — the api performs no download, conversion, or pipeline work
    in-process. This change is client-side only, so the relevant check is that
    it asks the api for nothing that would violate it.
  - **AD-14** — `POST /ingests` is the only intake door. This screen never
    posts a drop; it starts an acquisition whose detached child reaches intake.
  - **AD-18** — failures surface visibly and by name; no silent fallback. This
    is the decision most of the diff is answering to.
- `AGENTS.md` — the operating rules (worktree, no `git add -A`, commit early).
- Design authority, adopted 2026-08-29:
  `_bmad-output/planning-artifacts/ux-designs/ux-meetingminer-2026-08-29/`
  — `EXPERIENCE.md` (`:93` acquisition stepper, `:99` refusal box, `:131-142`
  every Add-meeting state, `:170-172` banned patterns and asynchronous
  ownership, `:212` focus order, `:298-307` the data contract, `:370-383`
  Flows 1 and 2) and `DESIGN.md` (`:292-315` component tokens, `:440`
  acquisition state colours, `:616` form width, `:646-648`). Mockups:
  `mockups/add-meeting-youtube.html`, `mockups/add-meeting-refusal.html`.
- Acceptance criteria: `_bmad-output/planning-artifacts/epics.md`,
  "### Story 6.5: Add-Meeting UI" (line 1407).

## Scope

**In scope** — 13 files, all additions:

```
web/src/features/acquisitions/youtubeUrl.ts
web/src/features/acquisitions/youtubeUrl.test.ts
web/src/features/acquisitions/acquisitions.ts
web/src/features/acquisitions/acquisitions.test.ts
web/src/features/acquisitions/RefusalBox.tsx
web/src/features/acquisitions/AcquisitionStepper.tsx
web/src/features/acquisitions/useAcquisitionStatus.ts
web/src/features/acquisitions/IngestingMeetingCard.tsx
web/src/features/acquisitions/AddMeeting.tsx
web/src/features/acquisitions/AddMeeting.route.tsx
web/src/features/acquisitions/AddMeeting.test.tsx
web/src/features/acquisitions/AddMeetingRoute.test.tsx
_bmad-output/implementation-artifacts/spec-6-5-add-meeting-ui.md
```

No existing file was edited. `App.tsx`, `web/src/routes/`, `server/`, and
`web/src/client/` are untouched by design — route discovery (story 2.8) makes
the route file sufficient, and story 6.4 already generated the client.

**Explicitly out of scope:**

- The local-files, Zoom-export and Teams-export tabs (story 6.5a) and the
  upload-session endpoint they need (story 6.4a, in flight on `story/6-4a`).
  The three file tabs deliberately render chrome plus one sentence.
- YouTube deep links (story 6.6, already done elsewhere).
- Anything in `web/src/features/threads/` (story 10.2a, in flight).
- `web/src/client/` — generated and committed; never hand-edited.
- The residual risks already recorded under `## Auto Run Result`, including the
  absent "Name speakers" link, which is recorded with its reason.

## Design decisions to attack

Each is the choice plus the assumption under it. The planner is not a neutral
judge of its own calls.

1. **The client re-implements the server's URL shape check**
   (`youtubeUrl.ts`). *Assumption:* keeping Submit disabled with an explanation
   before spending a probe round trip is worth a second copy of the rule, and
   the copy stays honest because `youtubeUrl.test.ts` names
   `server/meetingminer/youtube.py:video_id_from_url` as its authority. Attack
   the drift risk: is there a shape the server accepts that this refuses, or
   vice versa? Check `shorts/`, hosts ending in `.youtube.com`, multiple `v=`
   keys, and `watch?v=…&list=…`.

2. **The pasted URL is normalized to the canonical watch URL before being
   sent** (`youtubeUrl.ts:watchUrl`, used for both probe and submit).
   *Assumption:* one video has one identity, so `youtu.be`, `shorts/` and a
   tracking-laden watch URL should be one probe and one acquisition — and the
   server writes `watch_url(video_id)` into provenance anyway. Attack: does
   sending something other than what the user typed lose information the api
   or its record needed?

3. **Polling stops permanently at `posted`** (`useAcquisitionStatus.ts`).
   *Assumption:* `posted | failed` are terminal in story 6.4's state machine and
   the remaining truth lives on the job, which already streams. Attack: is
   there any state after `posted` that `GET /acquisitions/{id}` would still
   report and this screen now misses? Note `isLive` also stops on an
   unrecognised status — deliberate, but check the consequence.

4. **`running` is drawn `done` on a failed acquisition**
   (`acquisitions.ts:stepperSteps`). *Assumption:* `run_acquisition` writes
   `status="running"` before doing any work, so every `failed` record passed
   through `running`; this is read from the server's state machine, not
   assumed. Attack: verify that claim against
   `server/meetingminer/acquisitions.py:run_acquisition`. If a record can fail
   without ever being `running`, this bar states something untrue.

5. **The SSE subscription lives in `IngestingMeetingCard`, mounted only after
   `posted`.** *Assumption:* opening `/jobs/events` on an idle form would spend
   a connection for nothing, and the story requires that arriving at `/add`
   issues no request. Attack: does deferring the subscription lose events
   emitted between the ingest POST and the card mounting? The card re-seeds
   from `GET /meetings` on mount and on `job.done`, which is the intended
   cover — is it sufficient?

6. **A transport failure is rendered by a different component from a
   refusal** (`RefusalBox.tsx` vs `TransportNotice`). *Assumption:* an outage
   dressed as a rule refusal would blame the video for the network, and only
   one of the two can honestly offer Retry. Attack the classification boundary
   in `acquisitions.ts:refusalOf` — a non-2xx yields the parsed problem body, a
   transport failure yields a thrown `Error`. Is there a real case that lands
   on the wrong side (an HTML error page from a proxy, a 502 with no body, an
   aborted request)?

7. **The three file tabs are selectable rather than disabled.**
   *Assumption:* a complete, testable keyboard model now means story 6.5a fills
   three panels and changes nothing else, and EXPERIENCE.md bans a disabled
   control with no sentence saying why. Attack whether the sentence is the
   right one and whether an unusable-but-focusable tab is the better trade.

8. **`ingestStatusOf` derives the fourth bar from `viewable`.**
   *Assumption:* `viewable` is the api's own verdict and the gate the whole app
   already uses, so "done" here means exactly what an enabled `Open` means.
   Attack: a job that is `succeeded` but not `viewable`, or `viewable` while
   stages still run.

## History the reviewer needs

- The shell was recomposed on 2026-08-31 (`2d68dcc6`, the baseline): the corpus
  metrics became a full-width banner above the chrome, and Search/Ask became a
  left rail at ≥1400px. That is **pre-existing**, not part of this story.
- `/add` has been linked from the chrome and bound to the `n` shortcut since
  story 10.5, with no route claiming it. Clicks fell through `App.tsx`'s
  unknown-path catch-all to the front door. That is the defect this story
  fixes; `AddMeetingRoute.test.tsx` pins it.
- Story 6.4 landed the acquisition api and regenerated `web/src/client/`
  already, so the generated client in the range is unchanged and is not this
  story's work.
- No rebase was performed. The branch is three commits on top of `2d68dcc6`
  plus the finalization commit.

## Verification baseline

Run these before reviewing, so a later skip or failure reads as a finding
rather than as noise. In the build worktree, after `make bootstrap` and
`uv sync --project server`:

| Command | Result at handoff |
|---|---|
| `make web-test` | 63 files, **720 tests, all passed** |
| `make lint` | ruff — all checks passed |
| `make typecheck` | mypy — no issues in 13 source files |
| `pnpm --dir web run lint` | oxlint clean; 2 `only-export-components` warnings on the new files, matching every existing `*.route.tsx` |
| `pnpm --dir web run build` | `tsc -b` then vite — built in 446 ms |
| `python3 _bmad/scripts/branch_conflicts.py --against story/6-5` | `story/6-5 × story/6-4a` clean, `story/6-5 × story/10-2a` clean; every other conflict row is identical to its `main × <branch>` row and touches no file this branch changed |

Not run, and why:

- `make test` (the full gate) — this change is web-only and touches no server
  file; the server suites need the worktree's store twins and the run was told
  not to claim shared resources. `make lint` and `make typecheck` did run.
- Nothing was exercised against a live api. Every acquisition response in the
  suite is a fixture typed against `web/src/client/types.gen.ts`. A live smoke
  test of `/add` against a running api and worker is an owner operation
  (starting the worker is currently a paid operation) and is still owed.

## One process note

The build run did **not** execute the workflow's in-run reviewer subagents. It
was dispatched with an explicit instruction to work synchronously with no
background agents, and this harness executes subagents detached. This review
lane is the substitute named in that same dispatch, so treat this diff as
having had **no** prior automated review pass — not a second opinion on one.
