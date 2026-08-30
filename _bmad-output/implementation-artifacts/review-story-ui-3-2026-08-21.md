# Review — story ui-3 (three-column meeting evidence anatomy)

- **Reviewer branch:** story/ui-3-review
- **Reviewed range:** origin/story/ui-3, commits 80e9550 + 5854c09, diff vs merge-base 52e9ca0 (main)
- **Date:** 2026-08-21
- **Contract:** `_bmad-output/specs/spec-ui-reimagine/SPEC.md` + CAP-2, reference-ui.md; stories.yaml entry "3"; `build-prompt-story-ui-3-2026-08-21.md`; dispatch amendment: only `web/src/features/moments/**` may change.

## Scope of review

1. Boundary: diff confined to `web/src/features/moments/**`.
2. Citation integrity: every artifact entry, thumbnail, passage clicks through to its moment or replays; `/moments/:momentId` untouched.
3. getMoment fan-out for artifacts: request volume, partial-failure degradation, no duplicate requests.
4. No invented data: header counts over served data only; lineage phrase; empty artifact kinds omitted; no topics/risks.
5. Reference fidelity vs reference-ui.md element map + honest-absence; quality of the +21 tests.

## Runs

- `make web-test` (from this worktree, story branch merged in): **13 files, 229 tests, all passed** (vitest 4.1.10, 11.36s). Observed directly.
- `pnpm run build` in `web/` (`tsc -b && vite build`): **clean** — no type errors, vite bundle built (342.62 kB js). Observed directly.

## Checks performed

### 1. Boundary — PASS

`git diff --stat 52e9ca0..origin/story/ui-3` touches exactly four files, all under
`web/src/features/moments/**`: `MeetingMoments.tsx`, `MeetingMoments.test.tsx`,
`moments.ts`, `moments.test.ts`. No change to `web/src/client/` (the
`listMeetingMoments`/`getMoment` sdk functions pre-exist in `sdk.gen.ts` from the
ui-1 regeneration), no server, no worker, no route files.

### 2. Citation integrity — PASS

- `MomentView.tsx`, `MomentView.route.tsx`, `MeetingMoments.route.tsx` are untouched;
  `/moments/:momentId` behavior is exactly what main has.
- Every rail artifact entry renders as a button `Open moment at <offset>: <title>`
  calling `onOpenMoment(entry.momentId)`; verified in the "groups rail artifacts"
  test which asserts the click reaches the handler with the right moment id.
- Published-documents entries click through the same way (asserted).
- Moment-bearing screenshots open their moment (pre-existing test kept); a capture
  no moment names jumps to its aligned transcript passage (`alignedSegmentId`,
  tested at the helper and the component level) — every element clicks through or
  replays, per CAP-2. Covered segments open their moment from the text; inline
  replay (single mounted `ReplayPlayer`, moved between regions) preserved and
  still tested.
- Outside a navigation shell (`onOpenMoment` absent) the controls degrade to plain
  content, tested ("omits open controls entirely outside a navigation shell").

### 3. getMoment fan-out — PASS with advisory findings (F1, F2)

- One `listMeetingMoments` then one `getMoment` per listed moment via
  `Promise.all` — no duplicate requests: the effect keys on `meetingId` only,
  its cleanup aborts the controller on meeting change/unmount, and every
  `setRail` is guarded by `controller.signal.aborted`.
- Partial failure is genuinely tolerant: each read is caught individually, a
  failed moment drops out and flips `partial`, and the rail shows the honest
  "may be incomplete" note while surviving artifacts render (tested). A failed
  moments list degrades the rail alone — transcript and screens still render,
  and no fan-out fires (tested, including `getMoment` not called).
- The whole rail read shares one 8s deadline (`MOMENT_TIMEOUT_MS`) on a joined
  `AbortSignal`; see F1/F2 below for the large-meeting consequence.

### 4. No invented data — PASS

- Header stats are all computed over served payloads: turns = `segments.length`,
  words = `wordCountOf` over served text, passages = live-moments count from
  `listMeetingMoments` (the server list filters `superseded`, verified in
  `server/meetingminer/api/moments.py` line 96), duration = `evidenceDurationMs`
  — the furthest served screenshot/segment end, explicitly documented as the
  honest derivable number since the drilldown carries no duration column.
  The passages stat is simply omitted until/unless the rail's list answers.
- Lineage phrase (`lineageLabel`) states only recording presence and speaker
  resolution, both served fields — it deliberately does not claim the reference
  example's "Teams transcript (VTT)" because the drilldown does not carry the
  source container format (F3).
- `meetingArtifactGroups` omits empty kinds (tested: "no zero-count headers");
  no topics section, no risks section anywhere in the component.
- Participants derive from served `participantId`s only; unresolved speakers
  count for nobody (tested: 'Speaker 8' never listed), and the absence note is
  the explicit one-sentence `NO_PARTICIPANT_GRAPH` (tested).

### 5. Reference fidelity + test quality — PASS

- Element map coverage: header stat line yes; film-strip with mono `HH:MM` offset
  under each thumbnail plus `viewType` and curated `screenLabel` yes; counted
  section headers ("Screens 2", "Action items 2", "Participants 2", "Published
  documents 1") yes — the reference's counts-everywhere idiom; artifact entries
  carry offset-range anchor, state, and publish path @ short commit; participants
  absence note verbatim-patterned; published documents listed (no file sizes —
  not served, honestly omitted). RISKS and TOPICS correctly absent.
- Honest-absence directions honored: transcript-only meetings get the lineage
  phrase "Transcript only — no recording", the UX-DR11 deep-link/inert/none
  fallbacks where the strip would be (pre-existing tests kept), empty rail gets
  "Nothing extracted from this meeting yet".
- Tests: exactly **+21 `it(` added, 0 removed** across the two test files
  (matching the claimed +21). The additions are behavioral, not snapshotty:
  helper-level tables for grouping/order/omission, word/duration/lineage/
  participants/alignment edge cases (empty transcript, capture before first
  segment, NaN duration), and component-level tests for the stat line counted
  from fixture data, rail grouping + click-through, empty rail, rail-only
  degradation (with the no-fan-out assertion), partial-failure note, participant
  jump with visible target ring, and unaligned-capture jump. Pre-existing 2.2/2.3
  behaviors (single replay, seek offsets, abort of stale responses, 409/404/
  transport/timeout copy) all retained and passing.

## Findings

**F1 (advisory, non-blocking) — unbounded fan-out under one shared 8s budget.**
`MeetingMoments.tsx` fires one `getMoment` per listed moment in a single
`Promise.all` with no concurrency cap, and the list read plus the whole fan-out
share one `MOMENT_TIMEOUT_MS` (8s) expiry. For the demo corpus (local api,
per-meeting moment counts in the dozens) the browser's per-host connection cap
serializes this harmlessly and degradation is correct — but a large meeting on a
slow api will routinely land in the `partial` state as later reads cross the
shared deadline. Each answer also carries the moment's full `segments` array,
which the rail discards — payload weight inherent to reusing the catalogued
never-called surface (the spec's recomposition-over-invention makes this the
right tonight call). Post-demo: a bounded-concurrency fan-out or a per-meeting
artifacts listing endpoint.

**F2 (advisory, non-blocking) — timeout mid-fan-out reads as "incomplete", not
"timed out".** If the 8s expiry fires after `listMeetingMoments` answered but
during the fan-out, every remaining read rejects, drops to `null`, and the rail
shows "Some moments could not be read — this list may be incomplete" rather than
the timeout sentence. Not wrong — the list genuinely is incomplete — but the
cause is masked. Copy nuance only.

**F3 (observation, compliant) — lineage phrase is narrower than the reference
example.** reference-ui.md's element map cites `transcript_source` as backing for
"Teams transcript (VTT)", but that column is not in the drilldown payload the
page reads, and the builder derived only what is served (recording presence +
speaker resolution) — the correct call under "render only data that exists"
rather than a new endpoint. If the fuller phrase is wanted post-demo it needs
`transcript_source` added to the drilldown response (server change, out of this
story's boundary).

**F4 (observation, non-blocking) — duration is evidence extent, not recorded
duration.** ui-1's meeting-list roll-up carries a served `durationMs`, but that
is a different endpoint this page does not read; the header instead states the
furthest evidence offset, documented as such in `evidenceDurationMs`. Honest and
within scope; worth unifying post-demo if the two numbers visibly disagree.

**F5 (minor, non-blocking) — no test for the rail's abort-on-meeting-change or
rail-timeout paths.** The drilldown read has both (stale-response and timeout
tests); the rail effect's equivalent paths are code-reviewed correct (guarded
`setRail`, cleanup abort, expiry branch) but untested. Worth a follow-up test,
not a blocker.

## Verdict

**PASS with findings** — all five priorities check out; findings F1–F5 are
advisory/observational, none blocking. Both commits (80e9550, 5854c09) are
coherent, within boundary, and the suite plus type build are green as observed
from this review worktree.
