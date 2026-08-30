# Addendum to the Story 11-2 remediation handoff — wave context, 2026-08-30

The binding remediation contract is **`build-prompt-story-11-2-2026-08-30.md`**
(written by the review lane at `013e0ff`: the ten findings as three themes plus
lows, red-first evidence rules, the ten-step verification, the completion
contract). Follow it. This addendum only adds what that file predates.

## 1. `_bmad-output` is tracked on `main` now

`main` moved to `5cdfce7` (2026-08-30): `_bmad-output/` is tracked and pushed
by owner decision; the ignore rule is gone. Your worktree still holds it as a
hand-made symlink. Once, before anything else:

```bash
cd /Users/devopsterus/current/cohort/meetingminer-wt/11-2
rm _bmad-output            # removes the symlink only
git fetch origin && git rebase origin/main
```

After the rebase the directory comes from git; commit spec, status and notes
edits on `story/11-2` like any other path. Never `git add -f` — nothing needs
it any more. Expect the handoff's mention of the symlink and of a
sandbox-denied main checkout to be stale after this step. Note `main` now also
carries the spec with the Remediation Plan section — the rebase replaces your
symlinked view with the identical content.

## 2. Five other lanes are building beside you

Read `wave-2026-08-30-rules.md` beside this file. `story/6-2`, `story/10-1`,
`story/7-1`, `story/11-3` and `story/11-4` were dispatched against your
current footprint (they avoid your files and regions). Before every push:

```bash
python3 _bmad/scripts/branch_conflicts.py --against story/11-2
```

`story/11-2-review` conflicting on the spec file is expected (main's copy is
the superset) and is resolved at integrate — every other pair must be clean.
If a fix genuinely needs a region another lane owns, stop that fix, record it
in the spec change log, and continue with the rest.

## 3. Docs wording owed by finding 10

When rewriting README / `project-context.md` / `docs/glossary.md` per finding
10, also correct any sentence there or in `AGENTS.md` that still says
`_bmad-output/` is local-only or never pushed — the owner reversed that rule.
