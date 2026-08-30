---
name: integrate
description: Run the seam between stories — land a reviewed story branch onto main, resolve the known recurring conflicts, run the post-merge operations in their mandated order, record status, clean up worktrees, and dispatch the next wave. Use when the user says "integrate", "land this story", "merge and clean up", "run the between-stories loop", or asks what operations are owed after a merge.
---

# Integrate — the between-stories loop

**Goal:** take a reviewed story branch from "done on a branch" to "merged, the
tree's operations are current, status recorded, worktrees cleaned, next wave
dispatched" — without re-learning the orderings this repo has already paid for.

This skill owns the seam *between* stories. `bmad-build` owns the work *within*
one. If you are implementing, you are in the wrong skill.

## Conventions

- Bare paths (`conflict-playbook.md`) resolve from this skill's directory.
- Repo paths are relative to the repo root. `sprint-status.yaml`,
  `sprint-notes.md`, and `deferred-work.md` live in
  `_bmad-output/implementation-artifacts/`.
- Every rule here is encoded from `AGENTS.md`, `sprint-notes.md`, and
  `deferred-work.md`. When they disagree with this file, they win — and fix
  this file.

## Non-negotiables

From `AGENTS.md`. These override any default in the driving harness.

- **Commit and push without asking.** Commit each coherent unit as it
  completes. Uncommitted work is the only work another agent can destroy.
- **Never** `git checkout -- .`, `git reset --hard`, `git stash` over the whole
  tree, or `git clean` outside a worktree you exclusively own.
- **Never** `git add -A` or `git add .`. Stage only paths you changed, and run
  `git status --short` before committing to confirm it.
- If you need a clean baseline, make a worktree. Never revert the shared tree.
- Report accurately. Do not claim a file you did not write or a command you did
  not run.

## Two hard gates

Stop and get a fresh explicit "yes" before either. Neither is implied by "go
ahead and integrate."

1. **Starting the worker** (`make start-worker`, `make worker`, `make up`).
   Restarting the worker is a paid operation: it drains queued jobs through
   whatever extraction stage is on the merged code. Check `sprint-notes.md` for
   the current hold and the count of paused jobs before you even offer it.
2. **Deleting remote branches** and anything else outward-facing.

`make evals-run` is serial across the whole machine — announce it, run it, say
when it's released. Never start one concurrently with another.

## Phase 0 — Orient

Read the ground truth before touching anything:

```bash
git status --short
git branch -a --sort=-committerdate | head -20
make worktree-list
git log --oneline -8
```

Then read `_bmad-output/implementation-artifacts/sprint-status.yaml` (statuses)
and `sprint-notes.md` (the reasoning, the holds, the merge-day cautions filed
by whoever built the branch). The notes routinely carry a caution that this
skill cannot infer — read them, do not skim them.

Report: what is on `main`, what branches are unlanded, which stories sit in
`review`, which worktrees exist, and any operational hold in force.

## Phase 1 — Land the branch

For each branch being landed, in sequence (never two at once into `main`):

1. **Confirm it is reviewed.** A story reaching `main` should have a committed
   `review-story-<id>-<date>.md`. Verify mechanically:
   ```bash
   make check-reviews
   ```
   It fails if any dispatched review prompt lacks its committed report. A
   missing report is a stop, not a warning. `_bmad-output/` is tracked
   (owner decision 2026-08-30), so the report must be committed on the
   review branch, not merely present on disk.
2. **Rebase onto main**, so the reviewed range is the range that lands:
   ```bash
   git -C <worktree> fetch origin && git -C <worktree> rebase origin/main
   ```
3. **Resolve conflicts** — see `conflict-playbook.md`. Do not accept an
   auto-merge on any file that file names.
4. **Re-run the suites the branch owns**, plus any suite the playbook says a
   conflict resolution invalidated. Store-free suites (`make web-test`,
   `make puller-test`, `make evals-test`) are always concurrency-safe. Server
   suites are safe to run concurrently since story 2.7 — they serialize on the
   projection lock and run parallel elsewhere.
5. **Merge to main and push.**

## Phase 2 — Post-merge operations

This is the phase people skip and pay for. Work `ops-order.md` top to bottom;
it decides which commands are owed by what the merge actually changed, and
fixes the order among them. The recurring lesson in one line: **`make migrate`
runs before the worker ever sees the new code.**

## Phase 3 — Record

1. Flip the story's line in `sprint-status.yaml`. **That file takes
   `story-id: status` lines only.**
2. Put the narrative in `sprint-notes.md` under the matching story id: what
   landed, what a follow-on agent needs to know, any caution for the next
   merge. Narrative in `sprint-status.yaml` is silently dropped by the merge
   driver — see `conflict-playbook.md`.
3. Commit both, push.

Write the same kind of note the existing ones are: what is true now, what is
deliberately not done, and what will bite the next person. Skip the adjectives.

## Phase 4 — Clean up

```bash
make worktree-remove STORY=<slug>     # one landed worktree
make worktree-prune                   # every clean worktree already merged into origin/main
make test-db-prune                    # only if a suite was SIGKILLed
```

Then list merged remote branches and **ask before deleting any**:

```bash
git branch -r --merged origin/main | grep -v 'origin/main\|origin/HEAD'
```

## Phase 5 — Dispatch the next wave

Apply the standing dispatch rule in `dispatch.md`. Recommend work as *parallel*
only when it is completely caveat-free and completely independent; anything
carrying a condition is a sequence, not a parallel recommendation.

Close by telling the user, in this order: what landed, what operations ran,
what operations are owed but gated, and what to dispatch next.
