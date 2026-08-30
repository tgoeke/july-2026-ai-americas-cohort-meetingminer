# Scoped verification review — Story 11-4 (Lint and Type Tooling in the Fast Loop), remediation round

## REQUIRED OUTPUT — read before any code

**Report file (mandatory):**
`_bmad-output/implementation-artifacts/review-story-11-4-verify-2026-08-30.md`

**REPORT-FIRST.** Create the report as a skeleton (scope, the exact range
below, an empty `## Findings`), commit and push it BEFORE reading code.
Append each finding as you confirm it and commit incrementally.

**Finding structure:** Location (`path:line`) · Severity · Finding · Evidence
· Resolution.

**You fix what you find** (repository convention): report the finding first,
then patch it yourself on this branch, red-first — the test observed failing
against the unfixed code, then the fix, then green — committing each with its
finding number. Leave unfixed, and mark clearly open, anything that needs an
owner decision or whose root cause is the frozen spec.

## Why this review exists — read this, it defines the job

Story 11-4 was reviewed, found defective, and then **remediated by the same
Codex session that found the defects**. That session wrote both the fixes and
the tests that prove them, so the fixes have never been examined by anyone
independent. You are that independent examiner. Assume the fixes are wrong
until the evidence says otherwise.

**This is NOT a re-review of the whole story.** Do not re-derive the original
review. Your scope is the remediation diff only.

## Scope

- Repository: `/Users/devopsterus/current/cohort/meetingminer`
- Branch: `story/11-4-review` (already pushed)
- **Remediation range: `dc1e64d..9b70dd1`** — the fix commits, nothing earlier.
- Prior report (what was claimed fixed):
  `_bmad-output/implementation-artifacts/review-story-11-4-2026-08-30.md`
- Work in your own worktree cut from `story/11-4-review`. **Never commit to
  `main`, never work in the main checkout, never merge** — the owner runs
  `integrate`.

## The mandate — mutation first

For **every** fix in the range, in this order:

1. **Break the fix** — revert it, or mutate the exact line it changed, in your
   own worktree.
2. **Run the test that claims to prove it.** If that test still passes, you
   have found a test that cannot fail: file it as a finding and write one that
   does fail, red-first.
3. Restore, confirm green, and record the mutation you used as the evidence.

A fix whose test survives its own mutation is the single most likely defect
class here. Report the mutation text in the evidence, not a description of it.

Then check, across the range:

- **Did any fix widen past the story's footprint?** Compare the changed paths
  against the story's spec footprint; an out-of-scope edit is a finding even
  if it is correct.
- **Did a fix break an adjacent behavior** the original suite did not cover?
- **Are the recorded resolutions honest** — does the report's claim for each
  finding match what the code actually does?
- **Story-specific trap:** the fixes hardened contract tests that pin ruff/mypy
  configuration. Those tests are the only thing standing between a future edit
  and a silently disabled linter, so mutate them hard: exit-zero lint, echo-only
  lint and typecheck, reordered prerequisites, broadened version ranges, and a
  fully retired per-file baseline. The prior round demonstrated all of these as
  bypasses — confirm each is now actually caught.
- **Constraint to police:** no lint/type sweep of existing source files was
  permitted. Any source edit made to satisfy a linter is a finding.

## Verification

Run the story's own suites and `make test-fast` in the FOREGROUND and read
the real output. Never run `make evals-run` (it calls paid model roles).

## Closeout

`make check-reviews` must pass. Push `story/11-4-review`. State the final SHA,
the verdict, every mutation you ran with its result, and anything left open.
