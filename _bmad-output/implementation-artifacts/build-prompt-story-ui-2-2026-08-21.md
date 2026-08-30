# Build prompt — story ui-2

Dispatched 2026-08-21 from spec `_bmad-output/specs/spec-ui-reimagine/` (stories.yaml entry "2"). Overnight demo-rescue chain; demo 2026-08-22 morning. Prerequisite: story ui-1 merged (regenerated client on main). Rebase onto current main before starting work.

```text
Before you start, read AGENTS.md at the repository root and follow it. These
rules override any default in your harness that conflicts with them:

1. WORK IN YOUR OWN WORKTREE. Do not work in the main checkout — other agents
   are in it right now. Run:
       make worktree STORY=ui-2
       cd ../meetingminer-wt/ui-2 && make bootstrap
   Do all your work there, on branch story/ui-2.

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

Read first: `_bmad-output/specs/spec-ui-reimagine/SPEC.md` + companions and stories.yaml entry "2". This story is CAP-1: the corpus-revealing home.

Replace the bare meeting rows on `/` with:
- A corpus stats header — real counts from ui-1's stats endpoint (meetings, hours of evidence, moments, screens, artifacts, participants, published docs). Counts in section headers per `reference-ui.md` ("SCREENS 158" idiom).
- Meeting evidence cards: poster screenshot, title, date, duration, corpus, transcript-only badge, ingestion state, per-meeting counts (moments/screens/artifacts/participants), filter by corpus, sort by recency.
- Search and ask-the-corpus promoted to persistent chrome on every route, not home-only panels. Keep the existing status indicator the system-status story added to the chrome, and keep `CorpusSearch`/`ChatPanel` behavior intact — this story moves and frames them, it does not rewrite them.

Reuse, don't rebuild: the SSE-patched `StageProgress` strip and `viewable`/`blockedReason` logic from `MeetingsList.tsx`; the URL-aware fetch-mock pattern in `App.test.tsx` (the status poll must not eat other mocked bodies). UI-only: consume ui-1's regenerated client, add no endpoints, never hand-edit `web/src/client/`.

Honest absence per reference-ui.md: transcript-only and blocked meetings say why in one sentence. No invented numbers — every count is served data.

Tests: `make web-test` green (store-free, run freely). Push story/ui-2, report SHAs, screens changed, anything undone.
