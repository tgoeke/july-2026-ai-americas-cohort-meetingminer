---
title: 'Story 10.5 owner-rulings remediation'
type: 'bugfix'
created: '2026-08-31'
status: 'ready-for-dev'
review_loop_iteration: 0
context:
  - '_bmad-output/implementation-artifacts/epic-10-context.md'
  - '_bmad-output/planning-artifacts/ux-designs/ux-meetingminer-2026-08-29/EXPERIENCE.md'
  - '_bmad-output/planning-artifacts/ux-designs/ux-meetingminer-2026-08-29/DESIGN.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The demo front door still pushes Moments below two full-width tools, cannot express filtered-versus-corpus counts, lacks the specified card focus order and shortcuts, and offers only an incomplete non-searchable thread selector.

**Approach:** Compose Search and Ask as persistent compact chrome controls with usable overlays, extend the feed reader with one server-supplied unfiltered count, source a searchable thread filter from Story 10.3's documented endpoint, and implement the design spine's interaction order and global shortcuts.

## Boundaries & Constraints

**Always:** Keep the desktop chrome 56px and sticky; preserve all Search/Ask behavior and state on every route; keep feed `total` as the filtered pageable size and use required `unfilteredTotal` for the denominator; preserve URL filters and honest unavailable states; ignore global shortcut keys in editable controls; keep every reason label verbatim; add new regression tests in new files and observe each ruling red before fixing it.

**Ask First:** Only a newly discovered requirement contradiction or a server-envelope decision beyond the owner-ratified `unfilteredTotal` contract.

**Never:** Make a second feed-count request, fake or derive a complete thread list from served cards, edit generated client files, invent shortcut bindings, downgrade Search/Ask features, merge to main, or run paid evals.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Filtered feed | 6 matching of 24 unfiltered | Header is `Moments 6 of 24`; paging uses 6 | Reject malformed or inconsistent counts |
| Empty filtered feed | 0 matching of 24 | Header is `Moments 0 of 24` and filtered-empty action | Keep prior cards on transient feed failure |
| Chrome interaction | Search or Ask receives focus | One bounded overlay expands without changing document flow; full feature works | Collapse on outside focus or route change without losing state |
| Thread catalog | `/threads` returns a nonempty list including off-page threads | Searchable selection writes `threadId` to URL | Retain deep-linked ID and name endpoint unavailability; never claim page-derived completeness |
| Global key | Binding outside editable control and preference enabled | `/`, `a`, `n`, `g m`, `g t`, `g e` perform specified focus/navigation | Disabled preference or editable target does nothing |

</frozen-after-approval>

## Code Map

- `web/src/App.tsx` -- persistent shell, chrome composition, routing, and shortcut targets.
- `web/src/features/search/CorpusSearch.tsx` -- Search state and compact presentation seam.
- `web/src/features/chat/ChatPanel.tsx` -- Ask state, model selector, and compact presentation seam.
- `web/src/features/moments/feed.ts` -- strict feed envelope reader.
- `web/src/features/moments/MomentsFeed.tsx` -- counted header and searchable thread filtering.
- `web/src/features/moments/MomentCard.tsx` -- card DOM/focus order.
- `web/src/features/settings/SettingsPage.tsx` and `web/src/features/speakers/SpeakerNaming.tsx` -- shortcut preference surfaces/consumers; locate exact current paths before editing.
- `_bmad-output/implementation-artifacts/review-story-10-5-2026-08-31.md` -- ruling resolution and Story 10.4/10.3 integration obligations.

## Tasks & Acceptance

**Execution:**
- [ ] `web/src/features/moments/feed.ts`, `MomentsFeed.tsx` -- require `unfilteredTotal`, enforce count invariants, and render the counted-header shapes.
- [ ] `web/src/App.tsx`, Search/Ask components -- put compact, focus-expanding, fully functional surfaces inside the sticky chrome.
- [ ] Moments thread filtering -- consume strict `GET /threads` contract with searchable selection and honest unavailable/deep-link behavior.
- [ ] `web/src/features/moments/MomentCard.tsx` -- order title, actions, source, player controls, then kind/thread chips; the spine wins the frozen story's visual-description conflict.
- [ ] Shell/Settings/SpeakerNaming shortcut modules -- implement the specified bindings and default-on localStorage preference.
- [ ] New ruling test files and affected fixtures -- prove red-first behavior, realistic envelopes, async-safe assertions, and update the review report.

**Acceptance Criteria:**
- Given `/` at desktop width, when no compact surface is active, then Moments follows the 56px sticky chrome without a flow-height Search/Ask block.
- Given either compact control, when focused and used, then its complete results/answer workflow is keyboard-usable and persists across routes.
- Given filtered and unfiltered counts in one response, when the feed renders, then its header and paging use their distinct meanings.
- Given the documented thread catalog, card content, and shortcut preference, when users filter or navigate by keyboard, then the design-spine order and bindings are honored without invented data.

## Spec Change Log

## Design Notes

`unfilteredTotal` is a non-negative integer computed from the same otherwise eligible, reason-validated set with all optional feed filters absent. Require `offset + items.length <= total <= unfilteredTotal`; without active filters, require equality. Story 10.4 must add `MomentsFeedResponse.unfiltered_total: int` serialized as `unfilteredTotal` and compute it in the same request before optional filters.

The `/threads` seam reads `{threads: [{threadId,name,mentionCount,meetingCount,firstMentionAt,lastMentionAt,colorOrdinal}]}`. Until Story 10.3 integrates, a named unavailable state is honest; observed card threads are not a completeness fallback.

## Verification

**Commands:**
- `make web-test` -- all web tests pass, including every new red-first regression.
- `pnpm --dir web exec tsc -b` and `make lint` -- type and lint checks pass with only documented baseline warnings.
- `make test-fast` -- repository fast gate passes in the foreground.
- `python3 _bmad/scripts/branch_conflicts.py --against story/10-5-review` -- only sanctioned or explicitly reported integration overlaps remain.

**Manual checks (if no CLI):**
- Inspect `/` at 1280×800: chrome is 56px, Moments begins at the fold, both overlays remain usable, and focus order follows the spine.
