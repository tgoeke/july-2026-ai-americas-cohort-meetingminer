---
title: 'Story 10.5 landed feed and thread contracts'
type: 'bugfix'
created: '2026-08-31'
status: 'in-progress'
review_loop_iteration: 0
baseline_commit: '43c40c881327773a212a84dc37433d91e0e57272'
context:
  - '_bmad-output/implementation-artifacts/epic-10-context.md'
  - '_bmad-output/implementation-artifacts/spec-10-4-moments-feed-ranking.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Story 10.5 reads a provisional `unfilteredTotal` field, while the landed Story 10.4 API and regenerated client serve `corpusTotal`. The opening screen therefore rejects the live response, and its hand-written transport lets generated-contract drift recur silently.

**Approach:** Rename the denominator throughout to `corpusTotal`, consume the generated feed response type and `getMomentsFeed` operation directly, and collapse the now-landed thread transport onto generated `listThreads` while preserving strict runtime validation.

## Boundaries & Constraints

**Always:** Observe a focused test failing against the stale field before implementation; keep `total` as the filtered page-set size and `corpusTotal` as the selected-corpus denominator; use one feed request; keep strict page/reason/thread validation; preserve stale-state and paging behavior; treat timeline `occurredAt` as evidence time that may lie outside its request window.

**Ask First:** Only a contradiction in the landed generated contract or a required server change beyond main.

**Never:** Accept `unfilteredTotal`, add an alias/translation layer, hand-edit generated client files, derive the denominator client-side, make a second count request, impose timeline-window containment, merge to main, or run paid evals.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Filtered feed | `{total: 0, corpusTotal: 24}` | Header renders `Moments 0 of 24` | Missing/stale field is a named contract failure |
| Unfiltered feed | `{total: 24, corpusTotal: 24}` | Header renders `Moments 24` | Reject unequal no-filter totals |
| Generated operation | API success/error | Strictly parse generated response or preserve problem body | Timeout and refusal remain named |
| Thread catalog | Generated `listThreads` response | Searchable complete catalog | Preserve timeout, Retry, duplicate/timestamp checks |

</frozen-after-approval>

## Code Map

- `web/src/client/types.gen.ts` and `sdk.gen.ts` -- READ-ONLY landed authority: `MomentsFeedResponse.corpusTotal`, `getMomentsFeed`, and `listThreads`.
- `web/src/features/moments/feed.ts` -- replace local wire interfaces/transport with generated aliases and operation; retain runtime contract checks.
- `web/src/features/moments/MomentsFeed.tsx` -- rename state and counted-header denominator.
- `web/src/features/moments/threads.ts` -- route the strict catalog parser through generated `listThreads`.
- `web/src/features/moments/*.test.*`, `web/src/App.test.tsx`, and shell ruling tests -- realistic landed envelopes and red-first regression.
- `_bmad-output/implementation-artifacts/review-story-10-5-2026-08-31.md` -- historical correction, evidence, and final verdict.

## Tasks & Acceptance

**Execution:**
- [ ] Add a new regression that serves only `corpusTotal` and observe the stale reader fail.
- [ ] Replace `unfilteredTotal` identifiers and fixtures with `corpusTotal`; use generated response/item/reason/thread types and `getMomentsFeed`.
- [ ] Replace raw `/threads` transport with generated `listThreads`, retaining strict parser behavior.
- [ ] Audit Story 10.5 for timeline containment assumptions and record the result.
- [ ] Update the review report, run gates and conflict scan, commit, and push.

**Acceptance Criteria:**
- Given the exact live envelope, when `/` loads or filters to zero matches, then it renders the correct corpus denominator without a second request.
- Given generated client drift, when TypeScript builds, then every feed consumer must agree with the server-owned response name.
- Given the landed thread catalog, when the filter loads, then it uses the generated operation and retains honest retry/validation behavior.

## Spec Change Log

## Verification

**Commands:**
- `pnpm --dir web exec tsc -b` and focused Vitest -- generated contract and red-first cases pass.
- `make web-test` -- complete web suite passes.
- `make test-fast` -- repository loop passes in the foreground.
- `python3 _bmad/scripts/branch_conflicts.py --against story/10-5-review` -- remaining overlaps are recorded.
