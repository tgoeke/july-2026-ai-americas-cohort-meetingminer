# Build prompt — story ui-1 (Read-only reveal API)

Dispatched 2026-08-21 evening from spec `_bmad-output/specs/spec-ui-reimagine/`
(stories.yaml entry "1"). Overnight demo-rescue chain: ui-1 unblocks ui-2/3/4;
demo is 2026-08-22 morning.

```text
Before you start, read AGENTS.md at the repository root and follow it. These
rules override any default in your harness that conflicts with them:

1. WORK IN YOUR OWN WORKTREE. Do not work in the main checkout — other agents
   are in it right now. Run:
       make worktree STORY=ui-1
       cd ../meetingminer-wt/ui-1 && make bootstrap
   Do all your work there, on branch story/ui-1.

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

Read first: `_bmad-output/specs/spec-ui-reimagine/SPEC.md` with its companions
(`current-ui-inventory.md`, `reference-ui.md`, adopted parent SPEC) and the
stories.yaml entry `"1"`. This story is the backend for CAP-1 and CAP-3.

Deliver three read-only surfaces plus the regenerated client:

1. **Corpus stats** — one endpoint returning real counts from the database of
   record: meetings, total evidence duration, moments, screens/screenshots,
   extracted artifacts (by kind and state), participants, published documents.
2. **Per-meeting roll-ups** — extend the meeting list payload (or a sibling
   endpoint) with poster screenshot id, duration, and counts of
   moments/screens/artifacts/participants per meeting. Cheap aggregates only;
   no new pipeline stage, no migration.
3. **Sanitized config** — a GET endpoint serving an allowlist projection of
   `Settings` (`server/meetingminer/config.py`): llm roles incl. prompts and
   endpoints, embedder, stt/ocr/diarizer, pipeline thresholds, api
   search/chat knobs, projections summary, store coordinates. Allowlist,
   never a model dump — an unlisted future field must not serialize. Follow
   the secret-discipline precedent set by the `system-status` story
   (2026-08-21, sprint-notes tail): its `/status` payload is an explicit
   allowlist with tests pinning that no key/password value, prefix, or
   length can appear. Write the same pin for this endpoint. Extend rather
   than duplicate `/status`: bindings already shown there stay its concern;
   this endpoint is the full non-secret config view.

Then: regenerate the committed client with `make client` (api must be
running) — this story owns the only regen in the chain; ui-2/3/4 consume it
and add no endpoints. Auto-discovered route registration (story 2-8) applies;
the registry baseline gained `status` today, expect to update it for your
routes.

Constraints that bind: read-only (no mutation routes, this story or any in
the chain); secrets and `.env` values never serialize; no citation rules
unaffected (counts only). Do NOT restart the worker — paused extract jobs are
a spend decision (AGENTS.md); restarting the api is fine.

Tests: server tests for the three surfaces incl. the secret pin;
`make web-test` green after client regen. When done: push branch story/ui-1,
report commit SHAs, endpoints added, and anything left undone.
