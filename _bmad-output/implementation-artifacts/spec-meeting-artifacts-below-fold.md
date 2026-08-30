---
title: 'Attached Documents No Longer Buried Below the Fold on Narrow Viewports'
type: 'bugfix'
created: '2026-08-21'
status: 'done'
route: 'one-shot'
baseline_revision: 'dc7b9a641e25da1ed7cd88a9f26b3bb2f8459a02'
review_loop_iteration: 0
context: []
---

# Attached Documents No Longer Buried Below the Fold on Narrow Viewports

## Intent

**Problem:** Extracted/published documents (ADRs, action items, participants) were already fetched and rendered correctly by both the meeting drill-down page (`MeetingMoments.tsx`) and the per-moment view (`MomentView.tsx`) — confirmed via API and DOM inspection. But below the `lg`/`md` breakpoint both pages stack into a single column in DOM order with the evidence rail *last*, after a film-strip and a full transcript that can each run to thousands of pixels for a heavily-screenshotted or long meeting. A user on a normal (non-maximized, or laptop-width) browser window has to scroll past all of that before reaching the documents, and reasonably reports seeing none at all.

**Approach:** Move the evidence/artifact rail to be the first element in document order in both files, so it is the first thing a reader — sighted, keyboard, or screen-reader — reaches on a stacked layout, with no scrolling required. Restore the original desktop layout (film-strip/main-column left, transcript center, rail right) purely via explicit `lg:order-*`/`md:order-*` classes on the three siblings, so DOM order (and therefore tab order and AT linearization) matches the mobile-first visual order, while the `lg`/`md`+ 3-column/2-column layouts are pixel-identical to before.

**Trade-off, accepted deliberately:** prioritizing the evidence rail first on narrow viewports means the transcript (previously 2nd) can now sit behind both the rail and the film-strip. The evidence rail is normally short (a handful of extracted items) relative to a full transcript or a large screenshot series, so this is a net improvement for the reported complaint; no attempt was made to solve all three sections being reachable within one screenful simultaneously (would need a bigger redesign — tabs/accordion — out of scope for this fix).

## Suggested Review Order

**Layout reorder — meeting drill-down page**

- Entry point: the evidence rail moved to the top of the grid, now DOM-first with `lg:order-3` restoring it to the right column.
  [`MeetingMoments.tsx:501`](../../../web/src/features/moments/MeetingMoments.tsx#L501)

- Film-strip (and its no-recording fallback) carries `lg:order-1` to land back in the left column at `lg`+.
  [`MeetingMoments.tsx:674`](../../../web/src/features/moments/MeetingMoments.tsx#L674)

- Transcript carries `lg:order-2` to land back in the center column; comment documents the accepted trade-off.
  [`MeetingMoments.tsx:730`](../../../web/src/features/moments/MeetingMoments.tsx#L730)

**Layout reorder — per-moment view**

- Identical pattern applied to the sibling bug the review found: the artifact rail moved before the main column, `md:order-2` restores it to the right at `md`+.
  [`MomentView.tsx:277`](../../../web/src/features/moments/MomentView.tsx#L277)

- Main column (screenshot/replay/transcript) carries `md:order-1` to land back on the left.
  [`MomentView.tsx:389`](../../../web/src/features/moments/MomentView.tsx#L389)

**Regression coverage**

- Pins DOM order (rail before film-strip before transcript) and the three `lg:order-*` classes that reset it at the wide breakpoint.
  [`MeetingMoments.test.tsx:275`](../../../web/src/features/moments/MeetingMoments.test.tsx#L275)

- Same pin for the per-moment view's two-element order.
  [`MomentView.test.tsx:110`](../../../web/src/features/moments/MomentView.test.tsx#L110)
