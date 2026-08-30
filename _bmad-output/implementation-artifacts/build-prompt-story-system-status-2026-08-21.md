# Builder Dispatch — System status in the UI

Freeform story, `rebuild-crash-recovery` pattern: **no sprint-status key**.
Branch `story/system-status`; the record of this work is its spec's memlog
plus a sprint-notes landing entry, not sprint-status.yaml.

Contract: `_bmad-output/specs/spec-system-status/SPEC.md`.

Paste everything below this line into the builder session.

---

```text
Before you start, read AGENTS.md at the repository root and follow it. These
rules override any default in your harness that conflicts with them:

1. WORK IN YOUR OWN WORKTREE. Do not work in the main checkout — other agents
   are in it right now. Run:
       make worktree STORY=system-status
       cd ../meetingminer-wt/system-status && make bootstrap
   Do all your work there, on branch story/system-status.

2. COMMIT AND PUSH WITHOUT ASKING, AND COMMIT EARLY. You need no permission to
   commit or push. Commit each coherent unit as it completes — do not hold
   finished work in the working tree until the end of your run. Uncommitted
   work is the only work that can be lost, and it has been lost here before.

3. NEVER RESET A TREE YOU DO NOT EXCLUSIVELY OWN. No `git checkout -- .`, no
   `git reset --hard`, no whole-tree `git stash`, no `git clean` outside your
   own worktree. Never `git add -A` or `git add .`; stage the specific paths
   you changed and check `git status --short` before committing.

4. THE DOCKER STORES ARE SHARED — worktrees do not isolate them. `make
   web-test` is store-free — run it freely. Single server test files run via
   `uv run --project server pytest server/tests/<file>` and own a per-run
   database. Do not run `make evals-run` — nothing in this story needs it.

5. REPORT ONLY WHAT YOU VERIFIED. If you claim to have written a file, confirm
   it exists on disk first and say which commit carries it. Do not report a
   test as passing unless you observed it pass.

6. STAY INSIDE YOUR STORY'S FILE BOUNDARY. Your contract is
   _bmad-output/specs/spec-system-status/SPEC.md (read its companion too).
   Boundary:
     - server/meetingminer/api/status.py (new) and
       server/tests/test_api_status.py (new)
     - web/src/features/status/* (new, including its tests)
     - web/src/App.tsx, web/src/routes/navigation.ts,
       web/src/routes/registry.ts — chrome indicator and route registration
       only, minimal diffs: these are shared shell files another story may
       want next.
   NOT web/src/client/ (generated). Do not run `make client`; call the new
   endpoint with plain fetch via the existing helper in web/src/lib/api.ts.
   NOT web/src/features/chat/* — chat's error surfacing was just fixed by
   story/chat-fallback-timeout; align copy with it, do not edit it. If you
   believe you need any file outside this boundary, stop and say so instead
   of editing it.

YOUR TASK

Read, in order:
  1. _bmad-output/specs/spec-system-status/SPEC.md
  2. _bmad-output/specs/spec-chat-fallback-timeout/SPEC.md (adopted companion)

Then build the spec's three capabilities. Non-negotiables:

- CAP-1 server half: one read-only aggregate endpoint (GET /status in
  server/meetingminer/api/status.py, auto-discovered per story 2-8's registry
  convention) reporting: Postgres, Neo4j, Meilisearch liveness; each
  llm.roles.* binding with model tag and key state (present/missing/invalid);
  api (trivially up); worker liveness plus job-backlog counts by stage.
  Key-validity probes use FREE provider endpoints only (e.g. model list),
  never a completion, and the server caches probe results between UI polls so
  polling cannot hammer providers or spend money.
- CAP-1 web half: a persistent status indicator in the chrome (web/src/App.tsx)
  that expands on click, plus a dedicated /status page
  (web/src/features/status/), both fed by periodic polling while the app is
  open — state changes without a reload. Interval is your choice; document it.
- CAP-2: every degraded row states what is broken AND the concrete remediation
  ("OPENAI_API_KEY invalid — set it in .env and restart the api"). The
  worker-stopped state is deliberate right now (paused paid backlog): report
  it truthfully as stopped-with-N-paused-jobs, with the restart-is-a-spend
  caveat, not as a generic alarm.
- CAP-3: copy naming a failing binding must match the chat panel's wording
  (llm.roles.<role> style) so the in-flow error and the status surface tell
  one story. Read the chat feature for its copy; do not modify it.
- SECRETS NEVER SERIALIZE: no fragment of any key or password in any response.
  Build the payload as an explicit allowlist, never by serializing Settings.
- READ-ONLY: no endpoint mutates anything; the UI states the file-edit-plus-
  restart change path. Status must NEVER touch the worker: no start, restart,
  or resume from anything on this path.

VERIFICATION — free path only:

- make web-test (store-free) must pass, with new tests covering: healthy
  render, degraded row with remediation text, indicator state change on a
  poll response change.
- uv run --project server pytest server/tests/test_api_status.py must pass,
  with tests asserting: the allowlist payload shape carries no key material
  (assert on a settings object with known fake secrets), invalid-key state
  from a stubbed provider probe, and probe-result caching (a second request
  within the cache window does not re-probe).
- NO PAID MODEL CALLS anywhere, tests included: stub every provider probe.
- The worker STAYS STOPPED. Nothing here starts it.

When you finish: push your branch, state the commit SHAs you created, append a
landing-candidate note for sprint-notes.md (what changed, what the test runs
showed, any owed operations) to your final report, and name anything you left
undone. Do not merge to main yourself — the dispatcher lands the branch.
```
