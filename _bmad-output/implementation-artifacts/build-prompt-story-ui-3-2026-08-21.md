# Build prompt — story ui-3

Dispatched 2026-08-21 from spec `_bmad-output/specs/spec-ui-reimagine/` (stories.yaml entry "3"). Overnight demo-rescue chain; demo 2026-08-22 morning. Prerequisite: story ui-1 merged (regenerated client on main). Rebase onto current main before starting work.

```text
Before you start, read AGENTS.md at the repository root and follow it. These
rules override any default in your harness that conflicts with them:

1. WORK IN YOUR OWN WORKTREE. Do not work in the main checkout — other agents
   are in it right now. Run:
       make worktree STORY=ui-3
       cd ../meetingminer-wt/ui-3 && make bootstrap
   Do all your work there, on branch story/ui-3.

2. COMMIT AND PUSH WITHOUT ASKING, AND COMMIT EARLY. You need no permission to
   commit or push. Commit each coherent unit as it completes — do not hold
   finished work in the working tree until the end of your run. Uncommitted
   work is the only work that can be lost, and it has been lost here before.

3. NEVER RESET A TREE YOU DO NOT EXCLUSIVELY OWN. No `git checkout -- .`, no
   `git reset --hard`, no whole-tree `git stash`, no `git clean` outside your
   own worktree. If you need a clean baseline, make a worktree — never revert
   the shared tree. Never `git add -A` or `git add .`; stage the specific paths
   you changed and check `git status --short` before committing.

4. THE DOCKER STORES ARE SHARED — worktrees do not isolate them. Server suites
   may run concurrently: each owns a per-run Postgres database, and the few
   projection tests serialize on a bounded, diagnostic cross-worktree file lock.
   `make evals-run` is still one at a time because it reads the shared stores and
   writes immutable run artifacts. `make web-test`, `make puller-test`, and
   `make evals-test` are store-free — run those freely.

5. REPORT ONLY WHAT YOU VERIFIED. If you claim to have written a file, confirm
   it exists on disk first (`test -f <path>`) and say which commit carries it.
   Do not report a file as written, a test as passing, or a range as reviewed
   unless you actually observed it. A claimed artifact that is not there costs
   the next agent a full verification pass.

6. STAY INSIDE YOUR STORY'S FILE BOUNDARY. The frozen contract in
   _bmad-output/implementation-artifacts/ names the files your story owns. If
   you need a file another in-flight story owns, say so instead of editing it.

When you finish: push your branch, state the commit SHAs you created, and name
anything you left undone.
```

## The work

Read first: `_bmad-output/specs/spec-ui-reimagine/SPEC.md` + companions (especially `reference-ui.md` and the screenshot `reference-competitor-meeting-view.png` beside it) and stories.yaml entry "3". This story is CAP-2: the dense meeting evidence view.

Recompose `/meetings/:meetingId` to the reference's three-column anatomy:
- Header stat line: title · date · duration · transcript turns · words · passages · source lineage (e.g. "Teams transcript (VTT) — speaker-attributed"), with transcript-only / augmentation state stated plainly.
- Left: screens film-strip — timestamped thumbnails (offset under each, `viewType`, `screenLabel`), click scrolls/jumps to the aligned transcript passage or opens the moment.
- Center: the full timestamped speaker-attributed transcript (existing drilldown segments), highlight preserved, click-through to moment and inline replay preserved.
- Right rail: extracted artifacts grouped by kind with counts in headers, each entry showing its moment offset anchor, publish state, and jump to its moment; participants (explicit one-sentence absence note when no graph exists); published documents.

Data: the existing `getMeetingDrilldown` payload plus the never-called surface catalogued in `current-ui-inventory.md` (`listMeetingMoments` with `segmentCount`/`preview`/`screenshotId`, artifact data) and ui-1's roll-ups. UI-only — no new endpoints, no hand-edits to `web/src/client/`. Render only kinds with backing data: no topics, no risks sections. Keep `/moments/:momentId` routes and behavior working — every element still clicks through to a moment or replays in place (parent constraint: no citation, no answer).

Tests: `make web-test` green. Push story/ui-3, report SHAs and anything undone.
