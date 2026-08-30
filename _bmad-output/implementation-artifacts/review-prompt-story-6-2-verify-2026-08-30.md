# Scoped verification review — Story 6-2 (YouTube Acquisition Command), remediation round

## REQUIRED OUTPUT — read before any code

**Report file (mandatory):**
`_bmad-output/implementation-artifacts/review-story-6-2-verify-2026-08-30.md`

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

Story 6-2 was reviewed, found defective, and then **remediated by the same
Codex session that found the defects**. That session wrote both the fixes and
the tests that prove them, so the fixes have never been examined by anyone
independent. You are that independent examiner. Assume the fixes are wrong
until the evidence says otherwise.

**This is NOT a re-review of the whole story.** Do not re-derive the original
review. Your scope is the remediation diff only.

## Scope

- Repository: `/Users/devopsterus/current/cohort/meetingminer`
- Branch: `story/6-2-review` (already pushed)
- **Remediation range: `9b51bc7..a0a3da6`** — the fix commits, nothing earlier.
- Prior report (what was claimed fixed):
  `_bmad-output/implementation-artifacts/review-story-6-2-2026-08-30.md`
- Work in your own worktree cut from `story/6-2-review`. **Never commit to
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
- **Story-specific traps:** this story's fixes covered five high-severity
  findings, the densest in the wave. Probe hardest at the refusal matrix (does
  every refusal still fire *before* anything is written to the drops root?),
  the `exists` short-circuit (prove no media network call can occur when a drop
  already exists), and the metadata mapping (a wrong `startedAt` precision or a
  missing provenance field is silent corruption of the corpus).
- **F13 is an owner decision and is NOT yours to implement** — whether the
  acquisition duration cap may carry a code default or must be declared in
  `config.yaml` per AD-10. Leave it open and clearly marked.
- **Known integration item, not a finding:** `server/meetingminer/mintdrop.py`
  must be reconciled with `story/6-3`, which is extending the same keyword
  override path by contract. Do not try to resolve that here.

## Verification

Run the story's own suites and `make test-fast` in the FOREGROUND and read
the real output. Never run `make evals-run` (it calls paid model roles).

## Closeout

`make check-reviews` must pass. Push `story/6-2-review`. State the final SHA,
the verdict, every mutation you ran with its result, and anything left open.
