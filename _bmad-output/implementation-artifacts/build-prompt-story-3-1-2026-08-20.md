# Builder Handoff — Story 3.1 Corpus Search

## Context

- Repository: `/Users/devopsterus/current/cohort/meetingminer`
- Branch: `story/3-1`, currently `b725533b3b0a1f0ba1b52456bc3428e9bd9fc9bf`
- Original reviewed range: `65f0b1cabd724735842afab6c8bb2a912326c98b..7d41adc95d366d03a370c56dd82520f335046498`
- Review record: `_bmad-output/implementation-artifacts/spec-3-1-corpus-search.md`, `### Review Findings` and `### 2026-08-20 — Server review remediation`
- The branch moved after the reviewed range through review-record commits and
  `f90ef4e`, which implements the selected seven remediation items.

## Verdict

Story 3.1 does **not** yet pass review for merge. All seven Story 3.1 review
findings were fixed and their focused coverage passes, but the required full
server suite has one reproducible failure. Do not mark the story done or merge
it until the failure below is understood and the full suite is green.

## Fix now

### Projection-lock timing test

- Anchor: `server/tests/test_parallel_store_safety.py:283-349`
- Failure: `test_projection_lock_times_out_with_holder_details_then_releases`
  starts a holder for one second, then the waiter acquires the lock instead of
  timing out. The exact suite run produced `1014 passed, 1 failed`; rerunning
  this test alone produced the same result.
- Concrete outcome: the test's waiter imports the test infrastructure after the
  ready signal and can reach the lock after the holder's fixed one-second sleep
  has elapsed, so the test incorrectly treats a released lock as a lock-safety
  failure. This keeps Story 3.1's required verification red despite no changes
  in the lock implementation or this test on the remediation commit.
- Required result: make the test synchronization robust enough that the waiter
  attempts acquisition while the holder demonstrably owns the lock, without
  weakening the timeout/holder-metadata assertions or changing cross-process
  lock behavior. Confirm the regression test fails against its unfixed version
  before relying on it as proof.

## No action — already remediated

- `server/meetingminer/projections/query.py`: `semanticHitCount` was wrongly
  treated as page-local. Retrieval now executes separate keyword and
  pure-semantic lanes, floors only the semantic lane, then blends them
  deterministically. This was a specification correction and has been recorded
  in the frozen contract.
- `server/meetingminer/api/search.py`, `config.py`, and the search/query/config
  tests: pure keyword mode skips embedding; highlightable moment attributes are
  validated at config load; malformed store responses become safe named errors;
  query-time outages and configuration invariants are covered.

## Out of scope

- Reopening the intentionally deferred issues already recorded in the Story 3.1
  spec (scope re-verification, post-filter page backfill, OCR embedding,
  logging policy, request budgets, offset maximum, and drill-down ownership).
- Any web/UI change, Neo4j retrieval, chat/synthesis, or a corpus-wide rebuild.

## Verification required

Run the Story 3.1 `## Verification` commands, including:

1. `uv run --project server pytest server/tests/test_projections_query.py`
2. `uv run --project server pytest server/tests/test_api_search.py`
3. `uv run --project server pytest server/tests`
4. `make web-test`
5. `pnpm --dir web run build`
6. `pnpm --dir web lint`

Also run `server/tests/test_parallel_store_safety.py::test_projection_lock_times_out_with_holder_details_then_releases` directly before and after the repair. Commit and push the fix, then return the branch for a fresh review.
