---
title: 'Story 10.7: Threads Is a Query, Not a Catalogue'
type: 'feature'
created: '2026-08-31'
baseline_revision: '8bd54e868c591f000417ef916476500e768c7c18'
baseline_commit: '8bd54e868c591f000417ef916476500e768c7c18'
status: 'done'
review_loop_iteration: 1
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/planning-artifacts/epics.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-10-6-threads-zoomable-timeline.md'
  - '{project-root}/docs/architecture.md'
warnings: []
deferred:
  - 'B-59 — the generated TypeScript client does not know the trace operations'
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

### Review Findings — 2026-08-31

- [x] [Review][High] Count distinct traced moments so synonymous topics on one
  moment cannot falsely claim a cap. [`server/meetingminer/api/threads.py:283`]
- [x] [Review][High] Clear and invalidate trace state when a reused route
  component returns from `/threads/:threadId` to the empty `/threads` front
  door. [`web/src/features/threads/ThreadTrace.tsx:86`]
- [x] [Review][Medium] Fit the initial timeline only after its real rendered
  width is known, and key fit ownership to the trace extent.
  [`web/src/features/threads/TraceTimeline.tsx:79`]

## Code Map

**Server**

| File | What it holds |
|---|---|
| `server/meetingminer/domain/thread_trace.py` *(new)* | The three rules that are invisible from outside when they drift: the suggestion band and its span-first sort, near-duplicate dropping (`duplicate_key`, `drop_near_duplicates`), and `completeness_note`, which is a function of the counts so the two legs cannot describe themselves the same way. Database-free and model-free. |
| `server/meetingminer/api/threads.py` | `GET /threads/suggestions` and `GET /threads/trace` beside story 10.3's routes, with seven new SQL constants. Both new routes are declared **before** `/threads/{thread_id}/timeline`, the module's stated literals-first discipline. |
| `server/tests/test_thread_trace.py` *(new)* | The domain rules, 15 tests, no database. |
| `server/tests/test_api_thread_trace.py` *(new)* | Both endpoints, 28 tests. Postgres-only and fast: the sample leg replaces `search_moments` and `meili_client` at the module boundary, because what is under test is how the route assembles and *describes* a ranked list, not whether Meilisearch ranks. Review coverage includes band edges, synonymous topics, a positive screenshot chain, and day precision. |

**Web**

| File | What it holds |
|---|---|
| `web/src/features/threads/trace.ts` *(new)* | The semantic zoom as pure arithmetic: altitude thresholds, `metricsFor`, `packLanes`, `zoomAbout`, `fitPpd`, `focusOn`, `axisTicks`, `noScreenReason`. Nothing here returns a scale factor. |
| `web/src/features/threads/traceApi.ts` *(new)* | Both endpoints read through raw `fetch` with a strict parser. `completenessNote` and `mode` are never defaulted: a payload without them is a visible refusal, not a timeline drawn without its sentence. |
| `web/src/features/threads/TraceTimeline.tsx` *(new)* | The canvas. One payload, four altitudes, lanes repacked on every `ppd` change. No `transform` anywhere in the subtree. |
| `web/src/features/threads/ThreadTrace.tsx` *(new)* | The front door: empty state, box, suggestions, candidates, the completeness sentence, related subjects. |
| `web/src/features/threads/trace.css` *(new)* | Sizes in real pixels, colours from `index.css` tokens. |
| `web/src/features/threads/{ThreadsTimeline,ThreadFocus}.route.tsx` | Repointed from 10.6's `Threads` to `ThreadTrace`. Paths unchanged. |
| `web/src/features/threads/trace.test.ts`, `ThreadTrace.test.tsx` *(new)* | 24 + 18 tests. |

**Footprint note.** `domain/thread_trace.py` and `docs/backlog.md` are outside
the two paths the build prompt named. The first is a new file no story owns,
added for the reason `domain/thread_timeline.py` exists — the rules deserve
tests that no database has to be up for — and it is not in `[tool.mypy] files`,
so no config edit followed. The second is the house convention for a finding:
file it in `docs/backlog.md` or it does not exist.

## Change Log

| Commit | What landed |
|---|---|
| `9cd7dcb3` | The spec, and the sprint key moved to in-progress. |
| `c97f309d` | Both endpoints and `domain/thread_trace.py`, with the domain tests. |
| `795c1afc` | The endpoint tests, including an AD-17 path sweep written over every SQL constant the module holds rather than a listed few. |
| `30e237af` | The web feature: empty front door, semantic timeline, routes repointed. |
| `52d7c363` | The web tests, plus two robustness fixes to `TraceTimeline` found by writing them. |
| `853cad1a` | Review F1: red test and distinct-moment trace counts. |
| `aae85d0b` | Review F2: red route-reuse test and empty-front-door state invalidation. |
| `68f4cb9a` | Review F3: red narrow-viewport test and real-width fitting. |
| `d9b8fd83` | Review coverage for suggestion-band edges, screens, and day precision. |
| `f2fff78e` | Rebased review artifacts and backlog ids reconciled with current main. |

## Verification

Run in this worktree against its own stack (`meetingminer-10-7`, all five
containers healthy).

| Gate | Result |
|---|---|
| `make lint` | All checks passed. |
| `web/node_modules/.bin/tsc -b` | Clean, exit 0. |
| `oxlint src/features/threads` | No finding in any new file; the seven warnings are all pre-existing 10.6 modules. |
| `make web-test` | **788 passed, 65 files.** 746 before this story, so 42 were added by the build and review. |
| `pytest server/tests/test_api_thread_trace.py test_thread_trace.py test_api_threads.py test_thread_timeline_levels.py` | **92 passed** — the 43 story/review tests alongside story 10.3's existing 49. |
| `make test` (full gate, `-m ""`) | Puller 128 passed; web 788 passed; eval harness 655 passed; isolated worker/STT/diarization 92 passed; store probe 1 passed; complete server suite **2901 passed, 3 skipped**; production web build clean; exit 0. |

The review gate ran in the foreground against the review worktree's own stack.
The API and worker were not started, `make evals-run` was not invoked, and no
paid model was called.

**What each acceptance criterion is held by**

| Criterion | Held by |
|---|---|
| Opens empty | `ThreadTrace.test.tsx` "opens empty — a box and suggestions, never a catalogue", plus the review's deep-link-to-root route-reuse regression |
| Suggestions rank by span, not frequency | `test_api_thread_trace.py::test_suggestions_rank_by_span_not_by_mention_count` and `test_suggestion_band_includes_both_edges_without_widening` |
| One-meeting rows never offered | `test_a_one_meeting_subject_is_never_offered` |
| Near-duplicates dropped | `test_near_duplicates_do_not_take_two_slots`, `test_thread_trace.py::test_plural_twins_do_not_take_two_slots` and the containment case |
| Two ways in, stated in words | `test_a_typed_phrase_that_names_a_subject_takes_the_exhaustive_leg`, `test_free_text_is_a_sample_and_says_so`, and both `data-mode` assertions in the screen tests |
| Adjacent candidates offered, not guessed | `test_adjacent_candidates_are_offered_rather_than_one_guessed`, "offers the adjacent candidates rather than guessing between them" |
| Cap per meeting, never overall | `test_every_meeting_stays_a_stop_when_the_cap_bites` — 3 meetings × 8 mentions at `perMeeting=2` keeps all 3 stops and reports 6 of 24 |
| Left to right in time, one timeline | `test_stops_run_left_to_right_in_time_on_one_timeline`, "draws one stop per meeting, in time order" |
| Semantic zoom, constant labels | `trace.test.ts` — the altitude block, and "draws fewer ticks as the view zooms out, never smaller ones" |
| Lanes packed at the current altitude | `trace.test.ts::packs against the pixel footprint at THIS altitude, not the date` — the same two stops need two lanes at 8 px/day and one at 210 |
| Zoom about the cursor | "keeps what is under the pointer under the pointer" and the 60-step no-drift case |
| Opens at the altitude where the span fits | `fitPpd` tests plus "fits the whole span to the rendered width, not the fallback width" |
| Meeting click opens the meeting view | "opens the meeting view when a meeting is clicked" |
| No screens states its reason, never over-claims | `test_a_stop_carries_the_facts_a_no_screen_reason_is_built_from`, `noScreenReason` tests, `test_a_stop_with_a_screen_carries_its_opaque_id_and_count`, and "renders the opaque screenshot carried by a stop" |
| Co-occurring subjects offered | `test_related_subjects_never_offer_the_one_already_open`, "offers the neighbouring subjects" |
| Nothing matched says so plainly | `test_a_wording_that_matches_nothing_offers_nothing_it_cannot_back` |
| Day precision does not invent a time | `test_day_precision_is_anchored_at_midnight_and_preserved` and "labels day-precision stops as date only" |

## Deferred and deliberately retained

**The undated lane (B-61) is closed as not applicable.** Migration 0002 makes
`meeting.started_at` `NOT NULL`, so no undated row can reach a trace. Review
tests pin the reachable near-neighbour end to end:
`started_at_precision = 'day'` anchors at midnight and is labelled `date only`,
so no clock is invented (AD-18).

**Positive screen coverage (B-60) is closed.** The review found that the
required `screen`/`screenshot` seed is compact and added server and browser
regressions for `screenCount`, opaque `screenshotId`, and rendered media.

**The generated client (B-59).** `make client` needs a running api and the
build was told not to start one; `traceApi.ts` therefore reads both endpoints
through raw `fetch`, the same reason `threadsApi.ts` gives for story 10.3.

**Story 10.6's catalogue still on disk.** `Threads.tsx`, `TimelineCanvas.tsx`,
`useTimelineView.ts`, `timeline.ts` and `threadsApi.ts` are no longer mounted by
any route, and their tests still pass. Deleting them, and retiring
`GET /threads`, is story 10.7a — this story was told to leave that endpoint
working.

**No curation.** Rename, merge and split are story 10.2a, parked.

## Suggested Review Order

1. `domain/thread_trace.py` and `test_thread_trace.py` — the three rules, in
   isolation. If `completeness_note` can be made to say "every mention" about a
   capped or sampled result, everything downstream is wrong.
2. `api/threads.py`'s new SQL, particularly `_TRACE_STOPS` and `_TRACE_MOMENTS`
   — that the cap is a window function per meeting and that neither statement
   can drop a stop.
3. `trace.ts` and `trace.test.ts` — the geometry. `packLanes` and `zoomAbout`
   are where a defect is invisible.
4. `TraceTimeline.tsx` — read it for a `transform` that scales the subtree.
   There must not be one.
5. `ThreadTrace.tsx` — that the completeness sentence is unconditional and
   never defaulted away.

**The review lane fixes what it finds.** Findings are remediated on this branch
rather than filed forward, except where a finding is genuinely a separate
story, in which case it goes to `docs/backlog.md` with its reason.
