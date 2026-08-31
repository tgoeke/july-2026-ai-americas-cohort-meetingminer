# Reviewer handoff — Story 10.7: Threads Is a Query, Not a Catalogue

Branch `story/10-7`, built from `main` at `8bd54e8`. Spec:
`_bmad-output/implementation-artifacts/spec-10-7-threads-is-a-query-not-a-catalogue.md`
(`status: review`). Read `AGENTS.md` first.

## The review lane fixes what it finds

Owner ruling, 2026-08-30, and it governs this review:

> Report every finding in the report file first (report-first, committed before
> reading code), then FIX the patchable ones yourself on `story/10-7-review` in
> your own worktree, red-first — the test observed failing against the unfixed
> code, then the fix, then green — committing each with its finding number.
> Leave unfixed, and clearly marked open, only what needs an owner decision or
> is rooted in the frozen spec. Never commit to `main`, never work in the main
> checkout, never merge — the owner runs `integrate`.

Set up with `make worktree STORY=10-7-review BASE=story/10-7`, then
`make bootstrap` and `uv sync --project server` there.

**Do not start the api or the worker.** A corpus ingest is running and
extraction is bound to a paid model. Do not run `make evals-run`.

## What this story is, and why it exists

**The owner has corrected this view once already.** Story 10.6 built a zoom that
works and wrapped it in the wrong interaction: the view opened on a catalogue of
every derived thread — 1,090 on the current corpus, **976 of them involving
exactly one meeting** — and bottomed out at a moment when what the reader wants
is the meeting.

> "I go to the threads view and I type in a thread topic. Then I get an overview
> of all the meetings where that thread runs through those meetings … you're
> going to see a timeline across all your meetings where that gets surfaced …
> and then I can click into a meeting like I can do in the meeting view."

The design is taken from a working prototype the owner pointed at
(`/Volumes/nvmepool/mm_current/meetingminer`: `api/thread.js`, `web/src/Thread.tsx`,
`web/src/ZoomTimeline.tsx`). Where a criterion states a mechanism, that
mechanism is the prototype's and is deliberate; its comments are the
specification. Read them before proposing an alternative.

## Where to push hardest

1. **The zoom must be semantic, not magnification.** Layout is in world
   coordinates — pixels per day (`web/src/features/threads/trace.ts`) — and
   every label is drawn at a constant size. **Grep the whole feature for
   `transform: scale`, `zoom:` and any container-level scaling.** There must be
   none. The failure to hunt for is a change that makes the zoom *look* smoother
   by scaling a wrapper: it would be unreadable at the top and merely bigger at
   the bottom, and it would never reveal anything new.

2. **Lane packing is a function of the current altitude.** `packLanes(days, ppd,
   cardWidthPx)` is memoised on `ppd` in `TraceTimeline.tsx`. Check that nothing
   caches a lane assignment across a zoom. The test to read first is
   `trace.test.ts::packs against the pixel footprint at THIS altitude, not the
   date` — the same two stops need two lanes at 8 px/day and one at 210. If you
   can make lanes stale, that is a real finding.

3. **Capping is per meeting, never overall.** `_TRACE_MOMENTS` caps with
   `ROW_NUMBER() OVER (PARTITION BY mo.meeting_id …)`; `_TRACE_STOPS` has no
   limit at all, on purpose. Try to construct a thread whose late meetings fall
   off the timeline. Also check the two figures count the same row set — both
   statements exclude superseded moments, and if they diverged the cap would
   report as data loss.

4. **Completeness is stated in words, always.** `domain/thread_trace.py::
   completeness_note` is a function of the counts so the exhaustive and sample
   legs cannot describe themselves the same way. **Try to make it say "every
   mention" about a capped or sampled result.** On the web side,
   `traceApi.ts` never defaults `mode` or `completenessNote` — a payload missing
   either is a visible refusal, not a timeline drawn without its sentence. This
   is the AD-18 heart of the story: a sample presented as a full history is the
   same unverified-absence failure as claiming no recording exists.

5. **Suggestions must not become a frequency ranking.** `_SUGGESTIONS` orders on
   `last_at - first_at` first. The floor is `SUGGESTION_MIN_MEETINGS = 2`, which
   is lower than "middling" sounds — the reason is stated in the constant's
   comment (976 of 1,090 rows are single-meeting) and is worth challenging if
   you disagree.

6. **The no-screen reason.** The server ships facts (`hasRecording`,
   `screenCount`); the client renders the sentence (`trace.ts::noScreenReason`).
   Confirm a recorded meeting whose quoted moments carry no still is never
   described as having no recording.

## Known gaps, already filed

These are recorded rather than hidden. Confirm the reasoning; do not re-report
them as new findings unless you think the reasoning is wrong.

- **B-61 — the undated lane is unbuilt.** The criteria require an undated
  meeting to be named unplaceable. `meeting.started_at` is `NOT NULL`
  (migration 0002), so no such row can reach a trace; building the lane would be
  dead code shaped like a safeguard. The near neighbour *is* handled:
  `started_at_precision = 'day'` anchors at midnight and is labelled `date only`.
- **B-60 — no test covers a stop that actually carries screens.** Seeding a
  `screenshot` needs the whole `screen` chain. The absent case, which is the one
  AD-18 turns on, is covered on both sides.
- **B-59 — the generated TypeScript client does not know the two new
  operations.** `make client` needs a running api and this build was forbidden
  to start one, so `traceApi.ts` uses raw `fetch` with strict parsers.

Also deliberate: story 10.6's `Threads.tsx`, `TimelineCanvas.tsx`,
`useTimelineView.ts`, `timeline.ts` and `threadsApi.ts` are still on disk with
their tests passing, but **no route mounts them any more**. Retiring them and
`GET /threads` is story 10.7a; this story was told to leave that endpoint
working.

## Footprint

- `server/meetingminer/api/threads.py` (added to; story 10.3's routes untouched)
- `server/meetingminer/domain/thread_trace.py` (new — a file no story owns,
  outside `[tool.mypy] files`, added for the reason `domain/thread_timeline.py`
  exists)
- `server/tests/test_thread_trace.py`, `server/tests/test_api_thread_trace.py` (new)
- `web/src/features/threads/`: `trace.ts`, `traceApi.ts`, `TraceTimeline.tsx`,
  `ThreadTrace.tsx`, `trace.css` and two tests (new); the two `*.route.tsx`
  files repointed
- `docs/backlog.md` (appended: B-59, B-60, B-61)

Nothing else was touched. `config.yaml` was not committed.

## Gates as the builder left them

| Gate | Result |
|---|---|
| `make lint` | All checks passed |
| `tsc -b` | Clean |
| `oxlint src/features/threads` | No finding in any new file |
| `make web-test` | 784 passed / 65 files (746 before this story) |
| server thread suites | 88 passed |
| `make test` | See the spec's Verification section |

Re-run them yourself; the review does not inherit the builder's word for it.
