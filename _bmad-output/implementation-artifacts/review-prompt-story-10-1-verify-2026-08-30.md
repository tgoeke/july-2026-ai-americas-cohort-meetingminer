# Scoped verification review — Story 10-1 (Topic Extraction), remediation round

## REQUIRED OUTPUT — read before any code

**Report file (mandatory):**
`_bmad-output/implementation-artifacts/review-story-10-1-verify-2026-08-30.md`

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

Story 10-1 was reviewed, found defective, and then **remediated by the same
Codex session that found the defects**. That session wrote both the fixes and
the tests that prove them, so the fixes have never been examined by anyone
independent. You are that independent examiner. Assume the fixes are wrong
until the evidence says otherwise.

**This is NOT a re-review of the whole story.** Do not re-derive the original
review. Your scope is the remediation diff only.

## Scope

- Repository: `/Users/devopsterus/current/cohort/meetingminer`
- Branch: `story/10-1-review` (already pushed)
- **Remediation range: `93215b8..7d68ef4`** — the fix commits, nothing earlier.
- Prior report (what was claimed fixed):
  `_bmad-output/implementation-artifacts/review-story-10-1-2026-08-30.md`
- Work in your own worktree cut from `story/10-1-review`. **Never commit to
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
- **Owner rulings to audit:** two findings were closed by owner decision, so
  verify the implementations match the rulings rather than approximating them.
  #5 was ruled FAIRLY STRICT — a contentful foreign table (`## Decisions`,
  `## Notes`, a task list) must fail by name and earn the generate-path retry,
  while genuine heading drift stays accepted and a header-only shared document
  stays an honest zero. #9 was ruled DELETE THE TOPIC — a topic with no
  surviving mention must not exist, enforced at the database level so it holds
  no matter which stage or transaction removed the last mention, including an
  augmentation that re-arms `moments` while leaving `extract` settled. Probe
  both rulings adversarially; the second is a data-integrity invariant, so try
  to construct a surviving mention-less topic by any path.
- **Story-specific trap:** the prior round reported this story reached a Pass
  verdict with zero open findings. Treat that as a claim to falsify, not a
  reason to look less hard.

## Verification

Run the story's own suites and `make test-fast` in the FOREGROUND and read
the real output. Never run `make evals-run` (it calls paid model roles).

## Closeout

`make check-reviews` must pass. Push `story/10-1-review`. State the final SHA,
the verdict, every mutation you ran with its result, and anything left open.
