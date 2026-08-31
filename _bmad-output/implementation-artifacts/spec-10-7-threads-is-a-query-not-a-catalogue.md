---
title: 'Story 10.7: Threads Is a Query, Not a Catalogue'
type: 'feature'
created: '2026-08-31'
baseline_revision: '8bd54e868c591f000417ef916476500e768c7c18'
baseline_commit: '8bd54e868c591f000417ef916476500e768c7c18'
status: 'in-progress'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/planning-artifacts/epics.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-10-6-threads-zoomable-timeline.md'
  - '{project-root}/docs/architecture.md'
warnings: []
deferred: []
---

<intent-contract>

## Intent

**Problem:** Story 10.6 built a working zoom and wrapped it in the wrong
interaction. The Threads view opens on a catalogue of every derived thread —
1,090 on the corpus of 2026-08-31, 976 of which involve exactly one meeting — so
the reader arrives at a wall of rows that are not subjects followed across
meetings at all. And the deepest altitude bottoms out at a moment, when the
thing the reader wants is the meeting.

**Approach:** Threads becomes a query. The view opens empty, with a box and a
handful of suggested subjects drawn from the corpus. Naming a subject builds one
left-to-right timeline of every meeting where it surfaced, and clicking a
meeting opens the meeting view. The thread was the route; the meeting is the
destination.

Two new read-only endpoints on `api/threads.py`, and a new front door plus a
world-coordinate timeline under `web/src/features/threads/`.

The zoom is **semantic, not magnification**. Layout is computed in world
coordinates — pixels per day — and every label is drawn at a constant readable
size, the way a map keeps its place names legible at any altitude. A CSS
transform on a container is explicitly wrong: unreadable at the top of the zoom,
merely bigger at the bottom, and never showing anything new. What a meeting *is*
changes with altitude, rendered from one payload already in hand rather than by
refetching a tier per threshold.

## Boundaries & Constraints

**Always:**
- The view opens **empty**. No thread list, no bands, no derived catalogue.
- **Two ways in, and the response says which one it took.** An unambiguous name
  match walks the stored mentions and is exhaustive within the corpus; anything
  else is a top-k retrieval sample. The completeness of what is on screen is
  stated in words, always — a sample shown as a full history is the same
  unverified-absence failure as claiming no recording exists.
- **Capping is per meeting, never overall.** Every meeting that mentions the
  subject stays a stop; only the moments quoted at each stop are limited, and
  both figures are reported.
- **Suggestions rank by calendar span over a middling meeting count**, never by
  mention frequency, and near-duplicates are dropped.
- **Lanes pack against each card's actual pixel footprint at the current
  altitude**, never against the calendar date.
- One timeline. Meetings from different recurring settings interleave by date.
- Clicking a meeting opens `/meetings/:meetingId`.
- A meeting with no screens is a legitimate stop with its reason stated, never a
  blank, and never "no recording" unless `hasRecording` is actually `false`
  (AD-18).
- Read-only over Postgres for the exhaustive leg (AD-2/AD-5/AD-11). Never a
  storage path on the wire (AD-17).
- Footprint: `server/meetingminer/api/threads.py`,
  `web/src/features/threads/`, their tests, and the story's own artifacts.

**Block If:** none.

**Never:**
- No CSS-transform zoom.
- No lane assignment fixed at load time.
- No overall cap that drops stops off the tail of a long-running subject.
- No refetch-per-altitude: story 10.3's per-level endpoint is the wrong shape
  for this and is not reused.
- No edit to `domain/threads.py`, the shell, `App.tsx` or `web/src/index.css`.
- No curation (rename, merge, split) — story 10.2a, parked.
- `GET /threads` keeps working; retiring it is story 10.7a.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| Opens | `/threads` | Empty: a box and suggested subjects with their reach | suggestions that fail leave the box usable and say so |
| Suggestions | corpus of threads | middling meeting count, ranked by span in days, near-duplicates dropped | empty band is stated, never widened silently |
| Unambiguous name | `q` exactly names a thread or one of its topics | `mode: exhaustive`, every stored mention | — |
| Anything else | free text | `mode: sample`, top-k re-sorted by time, plus adjacent candidates | Meilisearch down → named 503 |
| Ambiguous phrase | "trail closures" | sample, with both adjacent candidates offered to pick from | — |
| Long subject | more mentions than can be drawn | every meeting stays a stop; moments per stop capped; both figures reported | — |
| Nothing matches | free text with no hits | says so plainly and offers nothing it cannot back | — |
| No screens | stop whose quoted moments carry no screenshot | reason stated from `hasRecording` + `screenCount` | never "no recording" when `hasRecording` is true |
| Day-precision meeting | `startedAtPrecision = 'day'` | anchored at midnight and labelled as date-only | time of day is never invented |

</intent-contract>

## Tasks & Acceptance

1. `GET /threads/suggestions` — span-ranked middling band, near-duplicates
   dropped, reach reported per subject.
2. `GET /threads/trace` — exhaustive by `threadId` or by an unambiguously
   resolved `q`; otherwise a retrieval sample carrying adjacent candidates.
   Per-meeting capping, both figures reported.
3. Web front door: empty state, query box, suggestions, candidates,
   completeness sentence.
4. Web semantic timeline: world coordinates, constant label size, altitude-aware
   representation, lane packing at the current altitude, meeting click-through.

## Code Map

To be completed as the work lands.

## Change Log

To be completed as the work lands.

## Verification

To be completed as the work lands.

## Not built here

To be completed as the work lands.
