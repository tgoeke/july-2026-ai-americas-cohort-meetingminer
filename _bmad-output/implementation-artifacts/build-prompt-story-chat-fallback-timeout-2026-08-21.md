# Builder Dispatch — Break-fix: chat-fallback-timeout

Freeform bugfix, `rebuild-crash-recovery` pattern: **no sprint-status key**.
Branch `story/chat-fallback-timeout`; the record of this work is its spec's
memlog plus a sprint-notes landing entry, not sprint-status.yaml.

Paste everything below this line into the builder session.

---

```text
Before you start, read AGENTS.md at the repository root and follow it. These
rules override any default in your harness that conflicts with them:

1. WORK IN YOUR OWN WORKTREE. Do not work in the main checkout — other agents
   are in it right now. Run:
       make worktree STORY=chat-fallback-timeout
       cd ../meetingminer-wt/chat-fallback-timeout && make bootstrap
   Do all your work there, on branch story/chat-fallback-timeout.

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
   _bmad-output/specs/spec-chat-fallback-timeout/SPEC.md. Its boundary:
   web/src/features/chat/* (and its tests), server/meetingminer/api/chat.py
   and server/tests/test_api_chat.py. NOT web/src/client/ (generated — and the
   API's wire contract must not change, so it needs no regeneration). If you
   believe you need any file outside this boundary, stop and say so instead of
   editing it.

YOUR TASK

Read, in order:
  1. _bmad-output/specs/spec-chat-fallback-timeout/SPEC.md
  2. _bmad-output/specs/spec-chat-fallback-timeout/failure-evidence.md

Then execute the spec's two live capabilities. Non-negotiables:

- CAP-3: a client-side expiry on a request the server ACCEPTED must be
  reported as a timeout ("the api did not finish within Ns"-shaped copy), and
  the "Cannot reach the api" wording reserved for the case where no
  connection was established. The distinction the code must draw: a fetch
  that never connected vs an AbortError from the 60s expiry timer vs a stream
  that closed before chat.done. Look at classifyFailure in
  web/src/features/chat/chat.ts and the expiry path in ChatPanel.tsx.
- CAP-4: with no fallback configured (the current config), a model-call
  failure must reach the user promptly and name the failed binding. The
  server already returns 503 with a detail naming `llm.roles.chat` — verify
  that path end to end with fallback=None, and make the chat panel render
  that 503 detail as the failure message instead of a generic transport line.
- Story 3.3 invariant holds: the whole answer is validated before any
  chat.token is sent — do not stream earlier to beat the timeout.
- 422 no-citable-answer is final — never retried. Do not disturb that path.
- The API's wire contract (response shapes, event names) must not change;
  the generated client is out of boundary.

VERIFICATION — free path only:

- make web-test (store-free) must pass, with new tests covering: expiry →
  timeout wording (not "Cannot reach"), connection-refused → "Cannot reach"
  wording, 503-with-detail → rendered binding-naming message.
- uv run --project server pytest server/tests/test_api_chat.py must pass,
  with a test asserting the no-fallback primary-failure 503 shape.
- NO PAID MODEL CALLS. Server tests use the existing fake/stub Llm pattern in
  test_api_chat.py. Do not call Anthropic, OpenAI, or the live api's /chat.
- The worker STAYS STOPPED. Nothing here needs it.

When you finish: push your branch, state the commit SHAs you created, append a
landing-candidate note for sprint-notes.md (what changed, what the test runs
showed, any owed operations) to your final report, and name anything you left
undone. Do not merge to main yourself — the dispatcher lands the branch.
```
