# Review — story ui-2 (Corpus-revealing home)

**Reviewer:** claude (review agent), worktree `ui-2-review` on branch `story/ui-2-review`
**Date:** 2026-08-21
**Scope:** branch `story/ui-2`, commits `20e13d7` and `91e9ebb`, diffed against merge-base with `main` (`52e9ca0`)
**Contract:** `_bmad-output/specs/spec-ui-reimagine/SPEC.md` + companions (CAP-1), `stories.yaml` entry "2", build prompt `build-prompt-story-ui-2-2026-08-21.md`, dispatch amendment (sprint-notes.md ~L1561): ui-2 owns App.tsx/chrome (incl. nav links to /status and /settings), must NOT touch `web/src/features/moments/**`, `web/src/features/settings/**`, or `web/src/client/**`.

## Files changed (per git diff --stat, merge-base..91e9ebb)

- web/src/App.test.tsx
- web/src/App.tsx
- web/src/features/home/CorpusStats.tsx
- web/src/features/meetings/MeetingsList.test.tsx
- web/src/features/meetings/MeetingsList.tsx
- web/src/features/meetings/rows.ts

## Findings

### 1. Boundary — respected
`git diff --stat 52e9ca0 91e9ebb` touches only: `App.tsx`, `App.test.tsx`,
`features/home/CorpusStats.tsx` (new), `features/meetings/MeetingsList.tsx`,
`features/meetings/MeetingsList.test.tsx`, `features/meetings/rows.ts`. Nothing
under `features/moments/**`, `features/settings/**`, or `client/**`. `lib/media.ts`
is imported (`mediaUrl`) but not modified — pre-existing helper, read-only use.

### 2. Behavior preservation — verified
- `rows.ts`: diffed `applyEvent`, `blockedReason`, `meetingLabel`, `startedLabel`
  byte-for-byte against the merge-base version — unchanged. Only new, additive
  functions were introduced (`durationLabel`, `countParts`, `visibleRows`,
  `corporaOf`) for the card/filter/sort feature.
- `MeetingsList.tsx`: `StageProgress`/`StageLegend` usage and the SSE apply
  path (`onEvent` → `applyEvent` → `commit`) are untouched; filtering/sorting
  is a derived view (`visibleRows`) computed from the canonical, unfiltered
  `rows` state, so the stream keeps writing into every row regardless of the
  active filter. `MeetingsList.test.tsx`'s "keeps applying stream events to a
  filtered-out meeting" test pins this, and commit `91e9ebb` is a one-line
  test fix scoping that assertion to the correct card (`within(meeting-job-1)`)
  after an ambiguous multi-row match — not a behavior change.
- `App.tsx`: `CorpusSearch` and `ChatPanel` are moved out of the
  `hidden={childOpen}` block into always-mounted persistent chrome (matches
  CAP-1: "not home-only panels"); neither component's own source was touched.
  The home block (`CorpusStats` + `MeetingsList`) stays inside
  `hidden={childOpen}`, never conditionally rendered/unmounted. Confirmed by
  `App.test.tsx`'s new "keeps search, ask, and the nav links in the chrome on
  a child screen" test, which asserts the Meetings heading is inaccessible via
  `queryByRole` (RTL respects the `hidden` attribute) while search/chat
  inputs and nav links remain present — this is a real hidden-not-unmounted
  pin, not a placeholder.

### 3. No invented data — verified
- `CorpusStats.tsx`: all seven header figures (meetings, hours, moments,
  screens, artifacts, participants, published docs) come directly from
  `getCorpusStats()`'s response; the error branch renders "Corpus counts
  unavailable — cannot reach the api at {API_BASE}: {message}" with a Retry
  button, never a zero. `App.test.tsx` pins both: "states the corpus scale...
  from served counts only" checks each served number appears, and "says the
  corpus counts are unavailable rather than rendering invented zeros" asserts
  the unavailable text and `queryByText('0')` is null.
- `rows.ts` `countParts`: per-meeting counts (moments/screens/artifacts/
  participants) are filtered to only counts the api served
  (`count != null`); an omitted field renders nothing, not `0`.
  `MeetingsList.test.tsx`'s "omits counts it was not served rather than
  inventing zeros" pins this, and also pins the honest-absence poster copy
  ("No screens captured yet." / "Transcript only — no recording, so no
  screens were captured.").
- Corpus filter buttons are built from `corporaOf(rows)` — corpora actually
  present in served rows, never a static/invented list.

### 4. CAP-1 completeness vs SPEC — met
- Stats header fields match the SPEC prose (meetings, hours of evidence,
  moments, screens, extracted artifacts [as `artifacts.total`], participants,
  published documents) 1:1.
- Card fields present: poster screenshot (`posterScreenshotPath` → `mediaUrl`,
  with honest-absence fallback), title, date (`startedLabel`), duration
  (`durationLabel`), corpus, transcript-only badge, ingestion state
  (`row.status` in the meta line, plus the full `StageProgress` strip),
  per-meeting counts (moments/screens/artifacts/participants via
  `countParts`).
- Corpus filter (`role="group"` of buttons, "All" plus one per distinct
  corpus) and recency sort (`sort-toggle`, newest/oldest, `null`-`startedAt`
  rows always sort last in both directions) both present and both tested
  (`MeetingsList.test.tsx`: "filters cards by corpus and restores them with
  All", "sorts by recency, newest first, and toggles to oldest first",
  `visibleRows`'s "sorts rows with no start time last in both directions").
- Minor note, non-blocking: the served `CorpusStats` type carries both
  `screens` and `screenshots` fields; the header renders `stats.screens`
  (matching the SPEC's literal wording for CAP-1, distinct from CAP-2's
  "SCREENS 158" film-strip idiom which is a screenshot count on a different
  screen). This is a correct read of two differently-scoped fields, not a
  defect — noting it only because the field names are easy to confuse in a
  future story.
- Nav link to `/settings` (dispatch amendment: ui-2 owns the nav links to
  `/status` and `/settings`) points at a route ui-4 has not landed yet; until
  then the catch-all (`{ path: '*', element: null }`) renders home under that
  URL rather than a blank/error screen. This is called out in-line in
  `App.tsx`'s own comment and is consistent with the SPEC's "any unfinished
  piece falls back to the existing screen" constraint — not a defect of ui-2.
  `/status` is already live (`StatusPage.route.tsx` landed by the
  system-status story) and is exercised end-to-end by the new "opens the
  status page from the chrome nav" test.

### 5. Test quality — good
- The pre-existing URL-aware raw-`fetch` mock in `App.test.tsx` ("opens the
  moment view straight from a chat citation") — which keeps the status poll
  from consuming the `/chat` stream body — is untouched by this diff (not in
  the changed-line ranges); the new stats/nav tests use the existing
  `vi.mock('@/client/sdk.gen')` pattern (`sdk.getCorpusStats`), so they don't
  interact with that raw-fetch mock at all and can't regress it.
  `sdk.getCorpusStats.mockResolvedValue(...)` is set in the shared
  `beforeEach`, so every pre-existing test in the file also exercises the
  corpus-stats fetch path without needing per-test wiring.
  New assertions are behavior-focused (served values render, unavailable
  text on failure, hidden-but-mounted chrome, nav routing, filter/sort
  outcomes) rather than implementation trivia.

## Test / build results

Ran from the worktree, detached to `91e9ebb` (story tip) after
`make bootstrap`, then returned to `story/ui-2-review` (HEAD `9d01ab4`)
afterward — no changes left in the working tree from the detached run.

- `make web-test`: **222 passed (13 test files)**, matches the count in
  commit `91e9ebb`'s message.
- Web build (`pnpm --dir web run build`, i.e. `tsc -b && vite build`):
  **succeeded** — 96 modules transformed, no type errors, `dist/` emitted
  (`index-BscJp0Dw.js` 340.02 kB / gzip 103.80 kB).

## Verdict

**Pass.** No blocking findings. Boundary respected, SSE apply path and
StageProgress/viewable logic genuinely unchanged and pinned by tests, home
block still hidden-not-unmounted, all rendered numbers trace to served data
with honest-absence failure states, CAP-1 fields/filter/sort all present and
tested, `make web-test` and the web build both pass clean. The two notes
above (`screens` vs `screenshots` field choice; `/settings` link pointing at
a not-yet-landed route) are informational, not defects — both are correct
given the current state of the sprint and are already explained in-repo by
comments or the SPEC's fallback constraint.
