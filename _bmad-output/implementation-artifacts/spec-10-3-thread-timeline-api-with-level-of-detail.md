---
title: 'Story 10.3: Thread Timeline API with Level-of-Detail'
type: 'feature'
created: '2026-08-31'
baseline_revision: '3211a7f96b86d7df496cefa451b2cbd431e6d8b4'
status: 'draft'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/build-prompt-story-10-3-2026-08-31.md'
  - '{project-root}/_bmad-output/implementation-artifacts/wave-2026-08-30-rules.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-10-2-threads-and-the-graph-projection.md'
deferred: []
---

<intent-contract>

## Intent

**Problem:** Story 10.2 landed `thread` / `topic_thread` and a graph traversal,
but nothing serves a thread to a client. The Threads view (story 10.6, building
in parallel) needs a thread's history at the detail level it is currently
rendering — a band across the corpus when zoomed out, moments with titles and
speakers when zoomed in — and it needs a colour identity per thread that does
not change when the list is re-sorted or a thread is merged. `thread` also has
no `color_ordinal` column (backlog B-40, deferred by 10.2 for this story to
decide the scope of).

**Approach:** Two read-only endpoints in one new auto-discovered router,
`api/threads.py`, over Postgres (AD-2, AD-5: SELECTs only, no store client).
`GET /threads` lists threads with their totals and their immutable
`colorOrdinal`. `GET /threads/{threadId}/timeline?from=&to=&level=` serves one
of four tiers and **exactly** that tier. Migration 0017 adds
`thread.color_ordinal`, allocated by a Postgres `SEQUENCE` — the only
allocator that does not duplicate under concurrency without locking — with a
trigger making the value immutable after insert. The wall-clock derivation, the
tie-break chain and the band bucket ladder are pure functions in a new
`domain/thread_timeline.py`, so they are unit-testable without a database.

## Boundaries & Constraints

**Always:**

- **Each level returns exactly its tier.** The four responses are four distinct
  models. A `bands` response carries no `meetings`, `moments` or `evidence`
  key at all; `moments` carries no transcript excerpt and no artifacts. This is
  asserted per level by comparing the response's whole key set, not by spot
  checks, so a leaked tier fails.
- **Never a storage path.** No level selects `screenshot.path`, `frame.path` or
  `meeting_media.drop_relative_path`, and no response body contains one. Media
  is ID-addressed (AD-17): `screenshotId` and, at `evidence`,
  `recordingMediaId`. Both are opaque ids the client resolves through a media
  route; the api never builds a URL and never leaks a root.
- **`colorOrdinal` is allocated once, positive, unique, and never recycled.**
  Allocation is `nextval('thread_color_ordinal_seq')`, which is transactional in
  the sense that matters here — two concurrent inserts can never receive the
  same value, whether or not either commits. It is deliberately *not*
  gap-free: a rolled-back insert burns its value rather than returning it,
  which is exactly "never recycled". A trigger refuses any `UPDATE` that
  changes it, so a merge survivor keeps its ordinal as a database fact rather
  than a convention; a split product is a new `thread` row and therefore
  receives a new ordinal from the sequence.
- **The scope of "per corpus" is the database of record.** B-40 left this open
  because `thread` has no corpus column and a thread may span `meeting.corpus`
  values. It is decided here: threads are derived corpus-wide from every
  meeting's topics, so a thread belongs to exactly one MeetingMiner corpus —
  the Postgres database — and one monotone sequence in that database is the
  only scope under which each thread has exactly one ordinal. Partitioning by
  `meeting.corpus` would give a cross-corpus thread two colours.
- **`occurredAt` is derived server-side**, never reconstructed by a client:
  `meeting.started_at + startMs`, serialized RFC 3339 UTC with an explicit `Z`.
  When the meeting's `started_at_precision` is `day` the anchor is truncated to
  `00:00:00Z` before `startMs` is added, so a day-precision source cannot leak
  a spurious time of day, and `occurredAtPrecision` is served as `day`.
- **Ties break by `meetingId`, then `momentId`.** Every ordered level uses the
  same explicit chain — `occurred_at, meeting_id, moment_id` — in SQL, and the
  same chain is available as a pure key function for unit tests.
- **Coarse levels are bounded aggregates that never scan `moment`.** `bands`
  and `meetings` aggregate over `topic_thread → topic_mention → meeting` only.
  `topic_mention` carries both `meeting_id` and `anchor_ms`, so the wall clock
  of a mention is computable without joining `moment` at all. The row set is
  bounded first by the thread (index `topic_thread_thread_id_idx`, then the
  `topic_mention` primary-key prefix `topic_id`) and then by the window. Proven
  two ways: a static assertion that the coarse SQL references no `moment`
  relation, and a live `EXPLAIN` asserting the plan contains no scan of
  `moment` and does bound by thread.
- **The band response size is bounded by the bucket ladder, not by the
  window.** Bucket width is the smallest step of a fixed ladder for which the
  window needs at most `TARGET_BUCKETS` buckets, so a one-day window and a
  ten-year window both return a bounded number of rows.
- Read-only (AD-5/AD-11): SELECTs only, no writes, no store client, no model
  call. All reads for one response happen on one connection under
  `REPEATABLE READ`, the house rule the moments routes already follow.
- Wire fields are camelCase through `alias_generator=to_camel`, the house
  boundary convention.
- Footprint per the build-prompt table: `api/threads.py`,
  `migrations/0017_thread_color_ordinal.sql`, `domain/thread_timeline.py`,
  `tests/test_api_threads.py`, `tests/test_thread_timeline_levels.py`, plus the
  spec/sprint/notes/backlog process files. Nothing else.

**Block If:** none — no decision here needs a human.

**Never:**

- No `/media/files/{mediaId}` route. AD-17's id-addressed media route does not
  exist in the tree today (`api/media.py` serves `/media/recordings/{meetingId}`
  by id and `/media/{path:path}` by path), and `api/media.py` is outside this
  footprint. This story serves the opaque ids that route will take and no path;
  the missing route is filed rather than built.
- No thread curation (10.2a owns merge/split/rename and its alias rows). The
  ordinal rules a merge and a split depend on are enforced at the record here
  and tested there directly, so 10.2a inherits them rather than inventing them.
- No edit to `api/moments.py`, `api/media.py`, `conftest.py`, `test_config.py`,
  `test_migrations.py`, `test_compose_contract.py`, `config.yaml`, or anything
  under `web/`.
- No worker start, no api start, no `make evals-run`, no model call.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Thread list | Two threads over three meetings | `{threads:[…]}` with `threadId`, `name`, `mentionCount`, `meetingCount`, `firstMentionAt`, `lastMentionAt`, `colorOrdinal` | No error |
| Empty identity row | A `thread` with no `topic_thread` link | Omitted from `GET /threads` — 0015 retains it as a reuse target, it is not navigable | No error |
| Ordinal allocated at insert | A thread inserted naming no ordinal | Positive, unique `color_ordinal` | No error |
| Concurrent creates | Two sessions inserting threads at once, both open | Two different ordinals; neither blocks | No error |
| Merge survivor | Survivor row updated (name, membership moved onto it) | Its `color_ordinal` is unchanged | No error |
| Ordinal update refused | `UPDATE thread SET color_ordinal = …` | Refused by trigger, naming the column | `raise_exception` |
| Split product | A second thread row minted from a split | A new ordinal, greater than every issued one | No error |
| No recycling after delete | A thread deleted, another created | The new thread's ordinal is not the deleted one's | No error |
| Explicit import ordinal | Insert naming `color_ordinal = 5000` | Accepted, and the sequence advances past it so no later `nextval` collides | No error |
| Non-positive ordinal | Insert naming `color_ordinal = 0` | Refused | `check_violation` |
| Level `bands` | Window over a two-meeting thread | `bands[]` of `{startAt,endAt,mentionCount,meetingCount}`; no `meetings`/`moments` key | No error |
| Level `meetings` | Same window | `meetings[]` with counts and `topics[]{topicId,name,linkedBy}`; no `moments` key | No error |
| Level `moments` | Same window | `moments[]` with exactly `momentId, meetingId, title, startMs, occurredAt, occurredAtPrecision, speakers, screenshotId` | No error |
| Level `evidence` | Same window | The moments tier plus `excerpt`, `artifacts[]`, `hasRecording`, `recordingMediaId` | No error |
| Unknown level | `?level=galaxy` | Refused before any query | 422 `invalid-request` |
| Unknown thread | A UUID matching no row | 404 `not-found` | `Problem` |
| Malformed thread id | `not-a-uuid` | Refused by the route parameter | 422 `invalid-request` |
| Window default | No `from`/`to` | The thread's own first→last mention span | No error |
| Inverted window | `from` after `to` | Refused, naming both bounds | 400 `invalid-window` |
| Window excludes a meeting | `from`/`to` inside one meeting only | Only that meeting's mentions at every level; counts agree across levels | No error |
| Day-precision meeting | `started_at_precision='day'`, `started_at` carrying a time | `occurredAt` anchors at `00:00:00Z + startMs`; `occurredAtPrecision` is `day` | No error |
| Equal anchors | Two moments at the same instant in two meetings | Ordered by `meetingId`, then `momentId` | No error |
| Speakers where known | Covered segments, some `resolved`, some `placeholder` | Only `resolved` labels, in first-appearance order, deduplicated | No error |
| Moment with no screenshot | `screenshot_id IS NULL` | `screenshotId: null`, row still served | No error |
| Storage path leak | A screenshot with a distinctive stored path | The path appears in no response at any level | No error |
| Coarse query shape | `bands` / `meetings` SQL | References no `moment` relation; `EXPLAIN` shows no scan of `moment` | No error |
| Band bucket ladder | A ten-year window | Bucket count is bounded; width comes from the ladder | No error |
| Empty window | A window before every mention | Every level returns an empty tier with the envelope intact | No error |

</intent-contract>

## Code Map

- `server/meetingminer/migrations/0015_threads.sql` — READ-ONLY. The table 0017
  extends, and the source of the worker-owned/machine-derived labelling 0017
  repeats. Its retention rule (identity outlives membership) is why the ordinal
  must survive an emptied thread.
- `server/meetingminer/migrations/0014_topics.sql` — READ-ONLY.
  `topic_mention (topic_id, moment_id, meeting_id, anchor_ms)` is what makes the
  coarse levels cheap: the mention already carries its meeting and its offset,
  so a band never joins `moment`.
- `server/meetingminer/api/moments.py` — READ-ONLY reference. The house shapes
  copied here: SQL as module constants with the reasoning above each, one
  connection under `REPEATABLE READ`, `Problem` for 404, `to_camel` models,
  `ROUTER_ORDER` for registration order.
- `server/meetingminer/api/registry.py` — READ-ONLY. `threads.py` is discovered
  by exposing `router`; `main.py` is never edited. `ROUTER_ORDER` matters:
  `/threads` (literal) and `/threads/{threadId}/timeline` live in one router and
  are declared literal-first inside it, the `media.py` way.
- `server/meetingminer/domain/thread_timeline.py` — NEW. Pure: `occurred_at`,
  `format_rfc3339`, `timeline_sort_key`, `plan_buckets`, the level vocabulary.
- `server/meetingminer/api/threads.py` — NEW. The two routes, the four level
  queries, the four response models.

## Spec Change Log

- 2026-08-31 — B-40's open question ("decide the corpus ownership model with
  Stories 10.3/10.6") is answered by this story: the sequence is per database
  of record. Recorded in `docs/backlog.md` as part of closing B-40.
