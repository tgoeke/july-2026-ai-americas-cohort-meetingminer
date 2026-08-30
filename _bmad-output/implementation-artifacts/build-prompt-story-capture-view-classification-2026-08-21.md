# Builder Dispatch — Break-fix: capture-view-classification

Freeform bugfix, `rebuild-crash-recovery` pattern: **no sprint-status key**.
Branch `story/capture-view-classification`; the record of this work is its
spec's memlog plus a sprint-notes landing entry, not sprint-status.yaml.

Paste everything below this line into the builder session.

---

```text
Before you start, read AGENTS.md at the repository root and follow it. These
rules override any default in your harness that conflicts with them:

1. WORK IN YOUR OWN WORKTREE. Do not work in the main checkout — other agents
   are in it right now. Run:
       make worktree STORY=capture-view-classification
       cd ../meetingminer-wt/capture-view-classification && make bootstrap
   Do all your work there, on branch story/capture-view-classification.

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

6. STAY INSIDE YOUR STORY'S FILE BOUNDARY. Your contract is
   _bmad-output/specs/spec-capture-view-classification/SPEC.md. Its boundary:
   server/meetingminer/pipeline/frameimage.py,
   server/meetingminer/pipeline/screens.py, ScreensConfig
   (server/meetingminer/config.py and config.yaml), their tests, and demo-002
   ground truth under evals/ground-truth/ only if the evidence shows a
   manifest error. Stories 2-5 and 4-4 are in flight in parallel right now —
   if you believe you need any file outside this boundary, stop and say so
   instead of editing it.

YOUR TASK

Read, in order:
  1. _bmad-output/specs/spec-capture-view-classification/SPEC.md
  2. _bmad-output/specs/spec-capture-view-classification/failure-evidence.md
  3. _bmad-output/specs/spec-meetingminer/capture-measurements.md

Then execute the spec. Non-negotiables from it:

- VERIFY BEFORE CHANGING. Task one is reading the recorded share-region crop
  method/detected for demo-002's ingest. That evidence decides the fix path
  (survey fallback vs classification thresholds) — the mechanism in
  failure-evidence.md is a hypothesis, not a finding. Commit what you observe
  before you change code.
- Three view types only: the migration-0003 CHECK and downstream consumers
  stay valid. Express new ambiguity via tags (precedent:
  avatar-gallery-unresolved), never a fourth type.
- Story 1-11 retune discipline: justify any threshold or geometry change
  against the measured baselines in capture-measurements.md; no regression on
  the 63 hand-labelled shots or prior corpus baselines; region detection stays
  survey-based — no model, no template match.
- Done means: make evals-run on the scripted demos reports 21/23, with only
  the two expected 2.11 publish-gate failures remaining (story 4-4 retires
  those — they are NOT yours), and prior corpus classification baselines show
  no regression. Check 2.2 is re-measure-only: fix nothing for it until the
  2.3 fix has landed and a re-run still shows residue.
- Out of scope: check 2.1 on demo-001 (dense-screen threshold decision),
  anything about the 2.11 failures, and the 28-meeting real corpus.

OPERATIONAL HOLDS — these are live, not boilerplate:

- The worker STAYS STOPPED. Jobs are parked at the extract stage and a worker
  start runs them (real cost). Nothing in this story needs the worker.
- No paid model calls. Capture and evals are local and free.
- make evals-run is strictly one at a time, and the 2-5/4-4 agents may also
  want it — announce in your commit messages when you take a run.
- If you run any projection-store test suite (including via make test), the
  shared stores now hold fixture data: a make rebuild is owed afterward. Say
  so in your handoff if you leave one owed.

When you finish: push your branch, state the commit SHAs you created, append a
landing-candidate note for sprint-notes.md (what changed, what the eval run
showed, any owed operations) to your final report, and name anything you left
undone. Do not merge to main yourself — this repo lands branches through a
review (make worktree STORY=capture-view-classification-review) and the
integrate flow.
```
