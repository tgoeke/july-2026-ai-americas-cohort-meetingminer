---
title: 'Return to the parent meeting from a moment'
type: 'feature'
created: '2026-08-31'
status: 'done'
review_loop_iteration: 0
baseline_commit: '483bcb438d72cec39a4ae29f7cb6ce7b1136bc50'
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `/moments/:momentId` names its parent meeting in the header but renders it as
plain text, so a reader who jumped to a moment from the feed, a search hit, a thread, or a
pasted link has no affordance back to `/meetings/:meetingId` — only the browser's Back
button, which returns to wherever they came from rather than to the meeting.

**Approach:** Add one control to the moment view's header that navigates to the parent
meeting, wired through the route file the way `MeetingMoments` and `SpeakerNaming` already
wire their navigation, so the component stays router-free.

## Boundaries & Constraints

**Always:** Navigation is the shell's to make — `MomentView` takes an optional callback prop
and the `*.route.tsx` file supplies it via `useOpenPath`, matching `MeetingMoments.route.tsx`.
The control renders only once the moment detail has answered (the meeting id comes from
`detail.meetingId`). Test the insertion in a new test module, leaving `MomentView.test.tsx`
untouched, as `MeetingSpeakersLink.test.tsx` does for story 7.4's insertion.

**Ask First:** Any change to `MomentDetail`, the api, or the generated client under
`web/src/client/`. None should be needed — `meetingId` is already on the payload.

**Never:** No new endpoint, no api change, no route added or renamed, no restructuring of the
moment header, artifact rail, replay affordance, or transcript. Do not edit
`MomentView.test.tsx`'s existing 35 router-free `render()` calls. Do not add the same control
to moment cards, thread views, or search hits.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Loaded moment | `detail` present, callback supplied | Control renders in the header; activating it navigates to `/meetings/{detail.meetingId}` | N/A |
| Still loading | `detail === null`, no failure | No control — nothing yet names a meeting | N/A |
| Load refused | `failure` set (404 / 409 / transport) | No control — the failure sentence stands alone | N/A |
| No callback | Component rendered without the prop | No control, no crash — the prop is optional | N/A |
| Moment changed | Prop changes to another moment | Control targets the new moment's meeting, never the previous one | N/A |

</frozen-after-approval>

## Code Map

- `web/src/features/moments/MomentView.tsx` -- the view. `MomentViewProps` at L26–29 (add the
  optional callback); `MomentView(...)` signature L42; `const loading` L217; header
  `<header className="flex flex-col gap-1">` L223–242, whose `<h2>` (L224) already renders
  `meetingLabelOf(detail.meetingTitle, detail.meetingId)` as plain text. `detail.meetingId`
  is on `MomentDetail` already — no api or client change.
- `web/src/features/moments/MomentView.route.tsx` -- mounts `/moments/:momentId`; currently
  passes only `momentId`. Wire the callback here with `useOpenPath` from `@/routes/navigation`.
- `web/src/features/moments/MeetingMoments.route.tsx` -- the pattern to copy verbatim:
  `useOpenPath()` + `onOpenMoment`/`onOpenSpeakers` callbacks (L8–18).
- `web/src/features/speakers/SpeakerNaming.tsx` L484–492 -- the back-control precedent:
  `Button variant="ghost" size="sm" className="self-start px-0 text-muted-foreground"`,
  rendered only when the optional callback is defined. `SpeakerNaming.route.tsx` supplies it.
- `web/src/features/moments/MeetingSpeakersLink.test.tsx` -- read-only; the convention for
  testing one inserted control in its own module rather than editing the owning suite. Copy
  its `vi.mock('@/client/sdk.gen', ...)` shape.
- `web/src/features/moments/MomentView.test.tsx` -- read-only. 35 `render(<MomentView …/>)`
  calls with no router; this is why the control must not mount a react-router `Link`.
- `web/src/features/moments/moments.ts` L134–140 -- `meetingLabelOf(title, id)`, for the
  control's accessible name.
- `web/src/routes/navigation.ts` -- `useOpenPath`, which already suppresses a duplicate push.

## Tasks & Acceptance

**Execution:**
- [x] `web/src/features/moments/MomentView.tsx` -- add `onOpenMeeting?: (meetingId: string) => void` to
      `MomentViewProps`, destructure it, and render a ghost `Button` at the top of the header
      (before the `<h2>`) when both `detail !== null` and the prop is defined -- gives the
      reader one gesture back to the meeting without disturbing the existing header.
- [x] `web/src/features/moments/MomentView.route.tsx` -- supply `onOpenMeeting` via
      `useOpenPath`, navigating to `/meetings/${meetingId}` for the meeting the loaded moment
      names -- the shell owns navigation, so the view stays router-free and testable.
- [x] `web/src/features/moments/MomentMeetingLink.test.tsx` -- new module covering the matrix
      rows: control present and clicked once loaded, absent while loading, absent on a refused
      read, absent without the prop, and retargeted when the moment prop changes -- keeps
      story 2.2's suite the untouched check that nothing else moved.
- [x] `web/src/features/moments/MomentMeetingRoute.test.tsx` -- added during review: mounts
      the real shell at `/moments/:momentId` and follows the control to the meeting
      drill-down -- the component tests pass their own handler, so nothing else would
      catch a typo'd path or a route that stopped supplying the prop
      (`AddMeetingRoute.test.tsx`'s idiom). Verified by mutation: breaking the path in
      the route file fails this test and only this test.

**Acceptance Criteria:**
- Given a moment view whose read has answered, when the reader activates the header control,
  then the app navigates to that moment's parent meeting page and the meeting view loads.
- Given the moment view is rendered by the router, when the reader uses only the keyboard,
  then the control is reachable and carries an accessible name that names the meeting.
- Given the existing moment-view suite, when it runs unchanged, then it still passes — the
  insertion adds no router requirement to `MomentView`.

## Design Notes

The control's target must come from `detail.meetingId`, not from the route param — the route
knows only the moment id, and the meeting id arrives with the loaded moment. So the callback
is invoked by the view (which holds `detail`) and the path is built by the route file from the
id the view hands it: `onOpenMeeting?: (meetingId: string) => void` is the honest signature.

```tsx
// MomentView.route.tsx
const openPath = useOpenPath()
return (
  <MomentView
    momentId={momentId!}
    onOpenMeeting={(meetingId) => openPath(`/meetings/${meetingId}`)}
  />
)
```

## Verification

**Commands:**
- `cd web && pnpm vitest run src/features/moments/` -- expected: the new module and the untouched moment suites all pass
- `cd web && pnpm lint && pnpm build` -- expected: clean (`build` runs `tsc -b`)

**Manual checks (if no CLI):**
- Open a moment from the feed, activate the header control, and confirm the meeting drill-down
  for that moment's meeting loads with no full-page reload.

## Suggested Review Order

**The control, and what it promises**

- The whole design in one hunk: renders only with a loaded meeting and somewhere to go.
  [`MomentView.tsx:246`](../../web/src/features/moments/MomentView.tsx#L246)

- Why "Open", not "Back" — the shell already owns `← Back`, and this pushes rather than pops.
  [`MomentView.tsx:236`](../../web/src/features/moments/MomentView.tsx#L236)

- The prop, and why the meeting id is an argument rather than closed over.
  [`MomentView.tsx:36`](../../web/src/features/moments/MomentView.tsx#L36)

**The route seam**

- The one place the destination path exists; `useOpenPath` suppresses a double push.
  [`MomentView.route.tsx:14`](../../web/src/features/moments/MomentView.route.tsx#L14)

**Verification**

- Mounts the real shell and follows the control through to the meeting screen.
  [`MomentMeetingRoute.test.tsx:113`](../../web/src/features/moments/MomentMeetingRoute.test.tsx#L113)

- The matrix rows, queried by accessible name so deleting the label fails a test.
  [`MomentMeetingLink.test.tsx:147`](../../web/src/features/moments/MomentMeetingLink.test.tsx#L147)

- Tab order and document position, pinned: the way out is the first thing reached.
  [`MomentMeetingLink.test.tsx:98`](../../web/src/features/moments/MomentMeetingLink.test.tsx#L98)
