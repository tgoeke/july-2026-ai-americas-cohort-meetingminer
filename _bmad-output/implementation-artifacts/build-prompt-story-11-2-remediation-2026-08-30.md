# Builder handoff — remediate Story 11-2 "Per-Run Store Isolation"

Agent: `bmad-build-auto`. Standalone remediation contract; do not rely on the
review session. Read `wave-2026-08-30-rules.md` in this directory for the
wave-wide rules (five other stories are building beside you).

## Outcome and source of truth

Story 11-2 **does not pass its follow-up review**: 10 patch findings (4 high,
3 medium, 3 low), 0 decisions needed, 0 specification defects. Fix all ten,
verify, push, and dispatch the re-review. Do not mark the story done.

- Review report: `_bmad-output/implementation-artifacts/review-story-11-2-2026-08-30.md`
  (also committed on `story/11-2-review` at `d3792db`).
- Spec: `_bmad-output/implementation-artifacts/spec-11-2-per-run-store-isolation.md`
- Repository: `/Users/devopsterus/current/cohort/meetingminer`
- Worktree: `/Users/devopsterus/current/cohort/meetingminer-wt/11-2` (its own
  stack `meetingminer-11-2`, ports 21761–21767), branch `story/11-2` at `fa86b86`.
- Reviewed range: `de0fc08..fa86b86`.

## Before you touch code — `_bmad-output` is now tracked

`main` tracks `_bmad-output/` as of 2026-08-30. Your worktree has it as a
hand-made symlink to the main checkout. Do this once, in this order:

```bash
cd /Users/devopsterus/current/cohort/meetingminer-wt/11-2
rm _bmad-output            # removes the symlink only; the target is untouched
git fetch origin && git rebase origin/main
```

After the rebase the directory comes from git. Commit spec, status and notes
edits on `story/11-2` like any other file. Never `git add -f`; nothing needs it
any more.

## The ten findings, grouped as the review groups them

**Theme A — worktree metadata validation (finding 1, high).** Every
linked-worktree entry point (`check-env`, `linked_worktree_without_stack()`,
`conftest.py`'s session import) fails closed on one exact generated-file
schema: expected project name for this checkout, all seven ports valid and
distinct, both twin URLs derived from the declared test ports, no foreign
keys. Publish `.env.worktree` atomically (write-then-rename). Replace the test
that accepts a name-only file with one that refuses it.

**Theme B — destructive pruner ownership (findings 2, 3, 7; high, high,
medium).** `_is_worktree_project()` requires the suffix to satisfy the
provisioner's slug rule before a project can enter pruning; every candidate's
labelled volumes are validated before `down -v` regardless of container
labels; `prune()` takes the provision lock (or re-resolves ownership
immediately before each `down -v`). Regressions: malformed-prefix foreign
project, container-plus-foreign-volume, stale-project reuse racing
`test-db-prune`.

**Theme C — pre-11.2 recovery routing (findings 4, 5; high, medium).** Every
printed retry for an old-ref worktree runs through a post-11.2 invoking
Makefile and compose file with the new worktree's env/project-directory
overrides — never `cd <old> && make …`. The Docker-down retry performs the
same stale-owner sweep as normal creation before starting Compose.

**Finding 6 (medium).** `stack_down` treats inventory failure as a named
nonzero result; `worktree-remove`/`worktree-prune` propagate every teardown
failure (drop the `|| true` that masks `down -v`). Fakes that fail inventory
and `down -v` separately.

**Finding 8 (low).** A coordinated two-process provisioning test proving the
`flock` gives disjoint ports.

**Finding 9 (low).** `_KEY_RE.fullmatch()` in `projections/locks.py`; trailing-
newline regression cases.

**Finding 10 (low).** README, `project-context.md` and `docs/glossary.md`
each state the measured OrbStack VM bound and its operational implication
themselves (AGENTS.md remains the detailed source).

Each fix: demonstrate the new test against the unfixed code (or a deliberate
mutation) before claiming it. Record each finding's resolution in the spec's
Review Triage Log.

## Footprint

The story's own 24 files. Additionally allowed by finding 10: the three docs
named. Do not widen: `config.yaml`, `web/`, `evals/`, migrations, `server/
meetingminer/` outside `config.py` and `projections/locks.py` stay untouched.
Run `python3 _bmad/scripts/branch_conflicts.py --against story/11-2` before the
final push — 6-2, 10-1, 7-1, 11-3 and 11-4 were dispatched against your
current footprint; if you must touch a region they own, stop and record it.

## Verification

- `uv run --project server pytest server/tests/test_worktree_stack.py server/tests/test_config.py server/tests/test_compose_contract.py server/tests/test_projections_locks.py -q`
- `uv run --project server pytest -m "" server/tests/test_makefile_procs.py server/tests/test_parallel_store_safety.py -q`
- `make test-fast`; `make test` (in your private stack) before `review`.
- Two worktrees running `make test` at once, timings re-recorded if the
  changes affect them.

## Completion

Spec `status: review` with the triage log filled, `11-2-per-run-store-isolation:
review` in `sprint-status.yaml`, `review-prompt-story-11-2-<date>.md` written
for the re-review (report-first, committed on the review branch — the
directory is tracked now), all pushed, SHAs reported.
