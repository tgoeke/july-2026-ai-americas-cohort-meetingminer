# Build prompt — story ui-4

Dispatched 2026-08-21 from spec `_bmad-output/specs/spec-ui-reimagine/` (stories.yaml entry "4"). Overnight demo-rescue chain; demo 2026-08-22 morning. Prerequisite: story ui-1 merged (regenerated client on main). Rebase onto current main before starting work.

```text
Before you start, read AGENTS.md at the repository root and follow it. These
rules override any default in your harness that conflicts with them:

1. WORK IN YOUR OWN WORKTREE. Do not work in the main checkout — other agents
   are in it right now. Run:
       make worktree STORY=ui-4
       cd ../meetingminer-wt/ui-4 && make bootstrap
   Do all your work there, on branch story/ui-4.

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

Read first: `_bmad-output/specs/spec-ui-reimagine/SPEC.md` + companions and stories.yaml entry "4". This story is CAP-3's UI: the read-only configuration transparency page.

Build a settings/configuration page fed solely by ui-1's sanitized config endpoint:
- Sections: LLM roles (model, fallback, endpoint, context, timeouts, both extraction prompt texts), embedder, STT/OCR/diarizer, pipeline capture thresholds, api search/chat knobs, projections summary, store coordinates.
- Every section states its change path: edit `config.yaml`, restart api and/or worker; `projections.*` edits additionally need `make rebuild`. The page says this — it never offers an edit affordance.
- Link it from the persistent chrome; relate it to (don't duplicate) the `/status` page the system-status story added — status is live health, this page is the declared stack.
- Move/absorb the "Active extraction prompts" block in `MomentView.tsx` by linking here rather than keeping two prompt renderings, if that stays inside your file boundary; otherwise leave it and note the duplication in your report.

Tests: a web test asserting no known secret-bearing key name or value (API keys, passwords, MEILI key) appears in the rendered page or its fetched payload fixture; `make web-test` green. UI-only — no endpoints, no `web/src/client/` hand-edits. Push story/ui-4, report SHAs and anything undone.
