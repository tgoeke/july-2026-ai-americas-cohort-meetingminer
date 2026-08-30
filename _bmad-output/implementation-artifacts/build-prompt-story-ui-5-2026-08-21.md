# Build prompt — story ui-5

Dispatched 2026-08-21 from spec `_bmad-output/specs/spec-ui-reimagine/` (stories.yaml entry "5"). Overnight demo-rescue chain; demo 2026-08-22 morning. Prerequisite: story ui-1 merged (regenerated client on main). Rebase onto current main before starting work.

```text
Before you start, read AGENTS.md at the repository root and follow it. These
rules override any default in your harness that conflicts with them:

1. WORK IN YOUR OWN WORKTREE. Do not work in the main checkout — other agents
   are in it right now. Run:
       make worktree STORY=ui-5
       cd ../meetingminer-wt/ui-5 && make bootstrap
   Do all your work there, on branch story/ui-5.

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

Read first: `_bmad-output/specs/spec-ui-reimagine/SPEC.md` + companions and stories.yaml entry "5". This story is CAP-4: the demo dry-run gate. Prerequisites: ui-2/3/4 merged (or explicitly recorded as fallen back).

1. Run the three-minute demo path end-to-end against the running app through the new chrome: corpus search → ask the corpus → cited answer → open a cited moment → replay its evidence. Also open the home dashboard, one dense meeting view, and the configuration page.
2. SPEND AUTHORIZATION — READ CAREFULLY: you may issue AT MOST 5 live `/chat` calls; they run on the paid `openai gpt-5.2` role. Authorization was granted 2026-08-21 for this dry-run only. Do not exceed 5, do not re-run the suite to "double-check", and NEVER restart the worker (its paused extract backlog is a large spend decision that is not yours).
3. Fix regressions you find in the new UI stories' files; anything unfixable tonight falls back to the existing screen — record every fallback.
4. Verify: existing web test suite (`make web-test`) and the `make test` web build pass; report exact results observed.

Deliverable: a demo-readiness report committed as `_bmad-output/implementation-artifacts/demo-readiness-2026-08-22.md` — what the demo path shows screen by screen, chat calls spent (count), regressions fixed, fallbacks in effect, anything the presenter must know. Commit it before polishing anything (report-first discipline). Push story/ui-5, report SHAs.
