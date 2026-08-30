# Reviewer Dispatch — story/system-status

Freeform story, no sprint-status key. Review branch `story/system-status`
(commits `2718e3e`, `6ba7b7f`, `631055e`, `12f7377`) against
`_bmad-output/specs/spec-system-status/SPEC.md` and its adopted companion
`../spec-chat-fallback-timeout/SPEC.md`. If the review passes, the reviewer
lands the branch (rebase onto main, merge, prune) and appends the landing
entry to sprint-notes.md.

Paste everything below this line into the reviewer session.

---

```text
Before you start, read AGENTS.md at the repository root and follow it. These
rules override any default in your harness that conflicts with them:

1. WORK IN YOUR OWN WORKTREE — reviewers are not exempt. Run
   `make worktree STORY=system-status-review` from the main checkout and
   review from `../meetingminer-wt/system-status-review`, never from the main
   checkout. Check out story/system-status there to inspect it.

2. COMMIT AND PUSH WITHOUT ASKING, AND COMMIT EARLY.

3. NEVER RESET A TREE YOU DO NOT EXCLUSIVELY OWN. Never `git add -A`; stage
   the specific paths you changed.

4. THE DOCKER STORES ARE SHARED. `make web-test` is store-free. Single server
   test files run via `uv run --project server pytest server/tests/<file>`
   and own a per-run database. Do not run `make evals-run`.

5. REPORT ONLY WHAT YOU VERIFIED.

6. THE WORKER IS OUT OF BOUNDS. Do not start, stop, or restart it, whatever
   state you find it in.

REPORT-FIRST: before reading a line of code, create
_bmad-output/implementation-artifacts/review-story-system-status-2026-08-21.md
with a skeleton (scope, range 2718e3e..12f7377, empty findings section),
COMMIT it, and push. Append each finding as you confirm it and commit
incrementally. A review that lives only in your terminal is not a
deliverable.

REVIEW SCOPE

Contract: _bmad-output/specs/spec-system-status/SPEC.md (+ companion
_bmad-output/specs/spec-chat-fallback-timeout/SPEC.md). Verify the branch
delivers CAP-1/2/3 under every constraint. Priority checks:

- SECRETS: adversarially hunt for any path by which key or password material
  (or fragments, or lengths/prefixes) can reach the /status response or the
  UI. The payload must be an explicit allowlist, never Settings
  serialization. This is the one finding class that blocks landing outright.
- FREE PROBES: confirm no code path on /status can issue a paid completion —
  list endpoints only, and the 60s cache actually prevents per-poll probing
  (check concurrency: simultaneous polls during a cold cache).
- WORKER SAFETY: nothing on the status path acquires, releases, or perturbs
  the worker advisory lock or job rows — observation only, and the lock
  query's database scoping is correct for both test and live databases.
- CAP-3 copy: binding names match the chat panel's llm.roles.<role> wording.
- Boundary deviations the builder disclosed (registry baseline append in
  server/tests/test_api_registry.py; URL-aware fetch mock in
  web/src/App.test.tsx): confirm each is minimal and does not mask chat
  behavior in tests.
- Run the suites yourself: uv run --project server pytest
  server/tests/test_api_status.py server/tests/test_api_registry.py, and
  make web-test. Report observed counts.

VERIFICATION IS FREE-PATH ONLY. No paid model calls; provider probes in
tests stay stubbed. Do not call live provider endpoints yourself.

IF AND ONLY IF no blocking findings: land the story — rebase
story/system-status onto main, merge (no-ff), push main, run
`make worktree-prune` from the main checkout, and append the builder's
landing-candidate note (in the build prompt's final report; reproduce it
from the review evidence) to
_bmad-output/implementation-artifacts/sprint-notes.md with the review
verdict, commit and push. If anything blocks, do NOT merge: file the
findings in the review artifact and stop.

When you finish: run `make check-reviews`, verify your report file with
`test -f`, and state the commit SHA carrying its final version, the verdict,
and whether you merged.
```
