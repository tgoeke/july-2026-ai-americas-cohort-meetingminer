---
title: 'Story 10.6: Threads Zoomable Timeline'
type: 'feature'
created: '2026-08-31'
baseline_revision: '3211a7f96b86d7df496cefa451b2cbd431e6d8b4'
status: 'in-progress'
review_loop_iteration: 1
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-10-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/build-prompt-story-10-6-2026-08-31.md'
  - '{project-root}/_bmad-output/implementation-artifacts/wave-2026-08-30-rules.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-meetingminer-2026-08-29/DESIGN.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-meetingminer-2026-08-29/EXPERIENCE.md'
warnings: []
deferred:
  - 'B-44 — the bands tier issues one request per thread; a corpus-wide bands level is an api change'
  - 'B-45 — timeline pins (`p`, up to three, in the URL)'
---

<intent-contract>

## Intent

**Problem:** Threads exist in the graph (story 10.2) and the api serves them at
four levels of detail (story 10.3), but there is no surface that walks a subject
from its shape across months down to one moment. FR43 / UX-DR18 ask for a
Google-Earth zoom: one screen, detail revealed per level, nothing invented.

**Approach:** A `/threads` screen in its own feature directory, built from a
pure decision core plus a DOM grid whose geometry is two CSS custom properties.

The core (`timeline.ts`) states the mapping `x = (t − from) / scale`, the tier
thresholds and their 1.25× hysteresis, zoom about a focus point, the bucket
unit, the padded and snapped fetch window, the density-alpha steps, and the
clustering rule. The tier is a function of `scale` alone, so a tier change
touches neither the window origin nor the scale — which is what makes *no
layout jump* a property rather than an intention, and what makes it provable
without a browser.

The canvas draws every item with its own `--t` and lets CSS compute x from the
canvas root's `--mm-from` and `--mm-scale`. A pan or a zoom therefore writes two
numbers to one element and the browser lays the whole tier out natively; React
does not re-render while a zoom eases. `useTimelineView` keeps the *target* view
in React state — the tier and the fetch read it the instant a threshold is
crossed — and eases the *drawn* view toward it over 120 ms, geometrically in
scale so equal ratios take equal time.

## Boundaries & Constraints

**Always:**
- Colour comes only from the api's immutable `colorOrdinal`:
  `(ordinal − 1) mod 8` selects the hue, `floor((ordinal − 1) / 8)` the lap.
  Never list position, never first mention.
- x comes from the served `occurredAt`. `startMs` is a replay offset and is only
  ever printed as a moment's anchor label.
- Nothing is drawn that a moment does not back. A bucket with no mentions is
  drawn at the 0.08 density step because its *span* is real; it is not a cell,
  carries no label, and cannot be focused.
- The outgoing tier stays drawn until the incoming one has data. A refusal keeps
  it drawn, shows the api's own words, and blocks zooming further in until Retry.
- Every tier fetch carries a generation; a response may only touch visible state
  while its generation is current. Late success is discarded exactly as late
  failure is.
- Focus is never lost to the page: when the cell under focus stops existing —
  a tier change, or two moments clustering as the view zooms out — focus is
  handed to the cell whose span contains the instant that was focused.
- Footprint: `web/src/features/threads/` (new files) and `docs/backlog.md`
  (appended, per the build prompt's "file in docs/backlog.md or it does not
  exist"). Nothing else.

**Block If:** none.

**Never:**
- No evidence tier, no LOD card, no inline replay — story 10.6a.
- No edit to the shell, `App.tsx`, `web/src/index.css`, the ask box or the nav —
  story 10.5 owns those.
- No edit to `web/src/client/` — story 10.3's operations are not generated yet,
  so `threadsApi.ts` reads them through `fetch` and is the one file that changes
  when they are.
- No curation (rename, merge, split) — story 10.2a.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| Opens | `GET /threads` lands | Bands tier fitted to the corpus span; every thread a band; list sorted by activity | — |
| Cold load | list landed, bands not | Axis drawn, `Loading bands…` in the canvas area | — |
| Empty bucket | `mentionCount: 0` | Band drawn at 0.08 alpha; not a gridcell, no label | — |
| Drill a bucket | click or `Enter` | Enters that bucket's thread and fits its span → meetings tier | — |
| Drill a meeting | click or `Enter` | Fits the meeting's duration → moments tier | — |
| Moments collide | two moments 32 s apart at 4 min/px | One cell named `2 moments, 0:37:20 to 0:37:52`, drills on Enter | Neither is dropped |
| Open a moment | click, or `o` | `/moments/:momentId` | — |
| Threshold crossed | zoom about a focused item | Tier redraws; the focused instant keeps its exact x | — |
| Hysteresis | one notch past a threshold | 1.25× the ceiling is needed to go back | — |
| Tier fetch pending | request in flight | Outgoing tier stays; a running progress line at the canvas top | — |
| Tier fetch failed | non-2xx or transport | Refusal box under the canvas in the api's words; outgoing tier stays; zoom-in blocked until Retry | RFC 9457 via `problemMessage()` |
| List refused | `GET /threads` non-2xx | Refusal box with Retry | RFC 9457 |
| Api unreachable | fetch rejects | `Cannot reach the api at <base>: …` + `→ start the api` | — |
| No threads | `[]` | `No threads yet. Threads appear once two meetings share a topic…` | — |
| Search no match | query matches nothing | `No threads match "<q>".` + Clear; canvas keeps every band | — |
| Beyond palette | `colorOrdinal` > 16 | Grey band and swatch; `beyond the palette (8 hues × 2 laps) — identified by name` | — |
| Malformed body | a field missing | Named refusal quoting the endpoint, the index and the field | Never a half-drawn tier |
| Evidence level | `parseTimeline('evidence', …)` | Refuses by name: that tier is story 10.6a | — |
| Reduced motion | `prefers-reduced-motion` | Drawn view applied synchronously; tier swap and progress line do not animate | — |

</intent-contract>

## Code Map

All paths under `web/src/features/threads/`, all new.

- `timeline.ts` — the decision core. `xOf` / `timeAtX` / `visibleSpan`;
  `TIER_MIN_SCALE` / `TIER_MAX_SCALE` / `HYSTERESIS` and `tierForScale` (a
  bounded loop, so a `Fit` that jumps two tiers applies the same rule at each
  step); `zoomAbout` (the identity `xOf(timeAtX(focusX, before), after) ===
  focusX`); `clampScale` at 2 s/px, which is where story 10.6a begins;
  `fitView` (centred on the span's midpoint, so a span short enough to clamp
  still lands in the middle); `panByWindow` / `panByPixels`; `bucketUnitFor`
  (smallest unit ≥ 8px); `fetchSpan` (visible window padded 50% each side, both
  edges snapped to a quarter of the span so a small pan reuses the cache);
  `cacheKey` (sorted thread ids, so pin membership is part of identity —
  B-42's groundwork); `densityAlpha` (0.08 for zero, quartiles of the nonzero
  counts across every visible band, top step when there is one distinct value);
  `clusterByX` / `clusterSpan`; `isoDay` / `offsetLabel` / `axisTicks`.
- `palette.ts` — `paintFor(colorOrdinal)` → hue, lap, and the colour the *name*
  is set in (always lap 1 — the swatch carries the lap). `swatchStyle`,
  `bandFillStyle`, `hatch`, `BEYOND_PALETTE_NOTE`. Literal hex rather than CSS
  variables: story 10.5 owns `index.css` and the Ember & Ink theme it will
  carry, so the thread palette cannot depend on tokens that do not exist yet.
  Every other colour on the screen is a semantic Tailwind token and follows the
  theme when it lands.
- `threadsApi.ts` — story 10.3's acceptance-criteria field names as types, a
  parser that refuses anything else by name, and `listThreads` / `fetchTimeline`
  over `fetch` with an 8 s expiry. **Assumed response shapes**, since 10.3's
  bodies are not fixed by the acceptance criteria: bands `{buckets: [{from, to,
  mentionCount}]}`, meetings `{meetings: [{meetingId, title, occurredAt,
  durationMs, mentionCount}]}`, moments `{moments: [{momentId, meetingId,
  meetingTitle, title, occurredAt, startMs, speakers}]}`. A bare array is
  accepted as well as an envelope. If 10.3 serves a different shape, this
  parser is the one place that changes.
- `useTimelineView.ts` — target view in state, drawn view in two CSS custom
  properties written by a rAF ease; `ResizeObserver` for the width, falling back
  to 1000px where there is no layout (jsdom, first paint).
- `threads.css` — `.mm-at`, `.mm-span`, `.mm-hit` (the ≥ 24 × 24 target centred
  on a possibly 3px-wide drawn bucket), `.mm-layer` (the 160 ms cross-fade),
  `.mm-progress`, `.mm-focusable` (the two-tone ring), and a reduced-motion block.
- `TimelineCanvas.tsx` — the `role="grid"`, the axis, the three tier renderers,
  the collapsed 4px strips, the `− + Fit ‹ ›` controls, the roving-tabindex
  keyboard model (`← →`, `↑ ↓`, `+`/`−`, `Home`, `Enter`, `Backspace`, `o`),
  ctrl/⌘-wheel zoom about the pointer and horizontal-wheel pan, and the polite
  live region that announces a tier change once.
- `ThreadList.tsx` — search, the activity/recency sort, rows with the lap swatch.
- `Threads.tsx` — the screen: list load, corpus span, tier derivation, the
  debounced generation-owned tier fetch with its cache, the refusal box, and the
  zoom-in block while a tier stands refused.
- `ThreadsTimeline.route.tsx` — `/threads`, and `ThreadFocus.route.tsx` —
  `/threads/:threadId`. Both `order: 20`. Story 10.5 mounts a `/threads/*`
  splat placeholder from its own `Threads.route.tsx`; these two claim the
  literal and the param path, which react-router ranks above a splat, so both
  branches land side by side with no edit to 10.5's file — which is what 10.5's
  own comment anticipates. Integration should then delete
  `ThreadsPlaceholder.tsx` and 10.5's route module.
- `fixtures.ts` — test-only fixture data at every level.
- Tests: `timeline.test.ts` (25), `palette.test.ts` (10), `threadsApi.test.ts`
  (6), `Threads.test.tsx` (20) — 61 in all.

## Change Log

- **Review remediation (`story/10-6-review`).** The adversarial review recorded
  18 findings before remediation, then fixed all 16 patchable findings
  red-first in four commits. The API now matches Story 10.3's implemented wire
  contract; request generations own both their desired key and payload/thread
  context; list and canvas share ordering; short corpora retain the bands-floor
  opening; keyboard, pointer, focus, density, clustering and track geometry are
  pinned by new regression files; and tier replacement is a real cross-fade.
  Two decisions remain open: a durable real-browser geometry harness/Chrome
  connection, and the time-anchor semantics absent from `/threads/:threadId`.
  See `review-story-10-6-2026-08-31.md`.

- **Footprint kept.** Only `web/src/features/threads/` (new) and an append to
  `docs/backlog.md`, which the build prompt names explicitly.
- **The route collision with story 10.5 was found and removed, not left.**
  `branch_conflicts.py` reported `web/src/features/threads/Threads.route.tsx`
  against `story/10-5`, which had by then landed a `/threads/*` splat
  placeholder whose own comment says a narrower route added beside it wins
  without the placeholder needing to move. This story's route module was
  therefore renamed to `ThreadsTimeline.route.tsx` and a
  `ThreadFocus.route.tsx` added, so nothing in 10.5's footprint is touched and
  the pair reports clean.
- **`/threads/:threadId` was built rather than deferred.** It was initially
  filed as backlog on the evidence that nothing linked to it; story 10.5's route
  comment then stated that *every thread chip in the app* points there, which
  would have sent a demo deep link to a placeholder. Two small route modules and
  a `useParams` read, with the `No thread has this id — it may have been merged
  away.` state the experience spine fixes.
- **The backlog counter was raced by three lanes.** The build prompt said the
  highest id in use was B-40; `main` already carried a B-41, `story/7-4` had
  taken B-41 and B-42, and `story/8-3` B-42 and B-43. These entries were
  renumbered to **B-44** and **B-45**, which are unclaimed on every branch
  checked at `5410fb2`.
- **Response shapes assumed**, as recorded above. Named here so integration
  reconciles against 10.3 rather than discovering it at the demo.
- **Three findings the tests produced**, each fixed with the test that found it:
  focus was dropped to the page when a focused cell clustered away; the zoom
  re-anchored on the recomputed cell and drifted ~4px over a dozen steps;
  `fitView` anchored a clamped span on its left edge instead of centring it.
- **One claim corrected against measurement.** A comment asserted that
  epoch-relative `--t` values were needed to avoid single-precision loss.
  Measured in Chrome 151 against the same CSS rules, absolute and relative land
  on the identical pixel — Blink evaluates the calc in double. The anchoring
  stays as a portability safeguard and the comment now says what was measured.

## Verification

- `make test-fast` — green at `39ccfba`: ruff `All checks passed!`, mypy
  `Success: no issues found in 13 source files`, vitest `353 passed (20 files)`,
  pytest `2173 passed, 3 skipped, 411 deselected in 103.27s`. The three skips
  are the standing named ones (pyannote absent, the LAN diarization host, real
  yt-dlp).
- `pnpm exec tsc -b --force` — exit 0.
- The CSS geometry was measured in a real browser rather than assumed: a probe
  page carrying the same `.mm-at` / `.mm-span` rules, driven through Chrome 151,
  reproduced `(t − from) / scale` exactly across four view states including a
  negative offset and a fractional scale. jsdom computes no layout, so no vitest
  test could have shown this.

## Not built here

B-44 (per-thread bands fetch — an api-shape question) and B-45 (pins). The
evidence tier and inline replay are story 10.6a. Curation is story 10.2a.
