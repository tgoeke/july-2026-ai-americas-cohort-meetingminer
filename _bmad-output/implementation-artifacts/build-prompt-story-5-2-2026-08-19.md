# Story 5.2 follow-up review handoff — 2026-08-19

Repository: `meetingminer`

Initial review target: `story/5-2`, exact range
`e3efde8d825e0ac8c660328d349f98132efaf964..3da0a65`.

Review artifact: `_bmad-output/implementation-artifacts/spec-5-2-deterministic-capture-checks.md`,
under **Review Findings — 2026-08-19 Follow-up Review**.

The review fixes landed on `story/5-2-review` in
`bb358f6 fix(evals): complete deterministic run artifacts`; that branch is the
reviewed branch's remediation successor. The findings-record commit is
`77145d0 docs(review): record story 5.2 follow-up findings`.

## Review verdict

**Story 5.2 passes review as it stands. No builder implementation work remains.**
The four follow-up findings were fixed, tested, committed, and pushed. The
story contract and sprint status are `done`.

Do not look for additional work in this handoff. If you are asked to act on
this story, verify the current branch state, preserve the completed review
record, and report that no patch is required.

## Fixed findings

All actions below are complete; they are retained so a future reviewer can
reconstruct the bug and the required regression guarantee.

1. **Fix completed — partial reports cannot pass** (`evals/harness/run.py:308`).
   A run containing only a non-blocking classification result could serialize
   `passed: true` while checks 2.1 and 2.2 (and the zero-subject gate) had not
   run. The report now requires the full tier-1 check set for every selected
   subject, names missing checks, and cannot pass when collection is filtered
   or interrupted.

2. **Fix completed — report the rule actually applied**
   (`evals/harness/checks.py:477`). The implementation used
   `count <= ceil(duration_minutes)` but claimed a fixed 1.0
   captures-per-minute threshold. A 11.2-minute recording with 12 captures
   passed while reporting 1.071 against 1.0. The result now records the
   computed `max_captures` and `ceil(duration_minutes)` formula; CPM remains a
   metric.

3. **Fix completed — redact additional secret forms** (`evals/harness/run.py:66`).
   `private_key`, `authorization`, and a token-only URL authority could reach
   a committed configuration snapshot. Those forms, including authorization
   query parameters, are redacted with artifact-level regression tests.

4. **Fix completed — retain corpus-read diagnostics** (`evals/conftest.py:263`).
   A `CorpusQueryError` during fixture setup previously prevented all check
   results from being recorded, leaving a failed but diagnostic-free report.
   It now becomes named unmeasurable evidence, so every requested check is
   recorded as not applicable and the report names the read failure.

## Deferred / no action

- The corpus `LEFT JOIN` needs a store-backed SQL-shape integration test, and
  `check-api` needs process-test coverage. Both are already recorded in the
  story's `deferred` frontmatter. They are not duplicated or changed here.
- The five parametrized capture checks cannot execute against a real subject
  until the scripted meetings are recorded, ingested, and their placeholder
  `source_id` values are replaced. This is the designed state, not a patch for
  Story 5.2.
- No finding has a specification root cause. No spec amendment or re-derivation
  is required.

## Verification observed

- The four regression cases were demonstrated against the unfixed code before
  the patch.
- `make evals-test` — **341 passed**; store-free and leaves no `evals/runs/`
  folder.
- `uvx ruff check --isolated evals/` — passed.
- `uv run --project server pytest evals/checks -q` — **2 failed, 1 passed,
  5 skipped**, the specified result: both failures name the placeholder
  manifests; the live read-only write probe passes.
- The original contract's server-suite verification was previously observed as
  **816 passed** before this eval-only remediation. No file under `server/`
  changed in `bb358f6`.

If future code touches these surfaces, run the contract's complete
`## Verification` commands and confirm any new regression test fails against
the unfixed code before reporting completion.
