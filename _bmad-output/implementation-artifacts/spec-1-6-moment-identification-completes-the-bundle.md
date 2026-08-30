---
title: 'Story 1.6: Moment Identification Completes the Bundle'
type: 'feature'
created: '2026-08-18'
baseline_revision: '2d301b6d7db1f48fc5f631707c34ea52dc21db86'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true
context: []
warnings: ['oversized']
deferred:
  - summary: >-
      No automated test drives a real multi-screenshot recording through the actual
      `screens` stage into `moments`; every multi-screenshot case inserts screenshot
      rows directly and calls the stage function.
    evidence: |-
      test_worker_moments.py's multi-screenshot cases use insert_screenshot() plus
      run_moments_only(), bypassing runner.run_once. The one end-to-end recording test
      uses the 6-second synthetic fixture with a single OCR screen, so it produces one
      screenshot. Verified instead by hand against the real corpus this run: 9 recording
      meetings, 6463 transcript segments, every segment covered exactly once. Closing it
      properly needs the scripted fixtures Epic 5 story 5.1 builds.
    location: >-
      server/tests/test_worker_moments.py
    severity: medium
  - summary: >-
      Story 1.7's "at ingest-complete" projection trigger has nothing to fire on, because
      no job can reach `done` until Epic 4 builds the `extract` stage.
    evidence: |-
      `extract` is in STAGE_NAMES and unregistered, so run_job() returns at the pause
      before the `UPDATE job SET status = 'done'` line. Confirmed on the real database:
      `extract` is `queued` on all 30 jobs and no job is `done`. Not caused by this story
      (the pause was at `moments` before), but 1.7 needs a decision on what signals
      ingest-complete.
    location: >-
      server/meetingminer/pipeline/runner.py:351
    severity: medium
  - summary: >-
      Capture density breaches the NFR2 under-one-per-minute guardrail on eight of the
      nine recordings in the corpus; story 1.11 tuned `screens` against a single meeting.
    evidence: |-
      Measured on the real database this run, screenshots per minute of media duration:
      0.80 (the 57-minute meeting story 1.11 tuned against), then 1.23, 2.19, 3.00, 4.36,
      6.42, 6.61, 7.63 and 16.99 — the last being 580 screenshots on a 34-minute
      recording. Moments inherit the density directly, since every screenshot start is a
      boundary. A `screens` tuning problem, not a `moments` one.
    location: >-
      config.yaml (pipeline.screens)
    severity: medium
---

<intent-contract>

## Intent

**Problem:** The pipeline pauses at `moments`: screenshots and speaker-attributed transcript
segments exist, but nothing joins them into the addressable unit every later epic cites, replays,
and extracts from. Without it there is no citation target, so "no citation, no answer" cannot be
enforced at all.

**Approach:** Build the `moments` stage. It reads this meeting's `transcript_segment` and
`screenshot` rows, cuts the meeting timeline at transcript-derived and screenshot-derived
boundaries, and writes one `moment` row per span — carrying video-offset milliseconds, ISO 8601 UTC
wall clock, the evidencing screenshot (or, on a transcript-only meeting, the drop's Stream URL as a
transitional source deep link), provenance, and the transcript segments it covers.

## Boundaries & Constraints

**Always:**
- A moment id is minted once by Postgres (`uuidv7()`) and is a citation target for the rest of the
  system (AD-2, AD-6). **Augmentation adds, never destroys** (SPEC Constraints): a rerun must not
  delete, renumber, or re-key a moment that already exists. Consequences, all binding:
  - The moment table has **no ordinal column**. Order is `start_ms`. An ordinal cannot survive a new
    moment being inserted between two existing ones, which is exactly what story 1.12 does.
  - Idempotence is **upsert by `(meeting_id, identity_key)`**, not the delete-then-insert every
    other meeting-scoped stage uses. `identity_key` is derived from the moment's own start offset,
    which comes from the provided transcript and does not move when a recording arrives later.
  - The only rows the stage may delete are moments whose `derived_from = 'screen'` that the current
    run did not recompute — a screen-anchored moment exists only because a screenshot did.
- Transcript-derived boundaries are computed from `transcript_segment` alone and screenshot-derived
  boundaries from `screenshot` alone; the two sets are unioned, never interleaved during
  computation. Otherwise the transcript boundary set would shift when video arrives and every
  pre-existing moment would be re-keyed.
- Every threshold the stage compares against comes from `config.yaml` (AD-10). No model call reads
  any of them — moment identification is deterministic code (AD-13).
- The drop directory is read-only (AD-13). The stage writes no file at all.
- Rows are meeting-scoped only (AD-11): no cross-meeting table is written or deleted.
- The stage runs on a transcript-only drop (`moments` is not in `VIDEO_ONLY_STAGES`).

**Block If:**
- The measured corpus contradicts the boundary defaults chosen below (see Design Notes) — i.e. the
  28 real transcripts no longer parse or the gap/duration distribution has moved materially.

**Never:**
- Never register or fake the `extract` stage. It is Epic 4. After this story a job legitimately
  pauses at `extract`; nothing may be marked `done` or `skipped` on its behalf.
- Never add a `/moments` API route, projection, or UI — Epic 2 and story 1.7 own those.
- The `moments` stage never deletes a `screenshot`, `transcript_segment`, `screen`, or
  `participant` row. (The runner's existing `_clear_replaced_video_evidence` does delete
  screenshots on a transcript-only retry; that is the runner's job, not the stage's.)
- Never fabricate a time parameter on the source deep link. The verified value is the recap URL the
  drop carries; a `?t=` this project has not tested against SharePoint Stream is invented behaviour.
- Never store a deep link whose scheme is not `http` or `https`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Recording meeting | segments + screenshots | one moment per boundary; each covers the segments starting inside its span and names the screenshot on display at its start; `source_deep_link` NULL | No error expected |
| Transcript-only meeting | segments, no screenshots | moments from transcript boundaries alone; `screenshot_id` NULL; every moment carries the drop's `provenance.url` | No error expected |
| Transcript-only, no `provenance.url` | segments, provenance without a usable url | moments written, `source_deep_link` NULL, count logged as `moments_without_link` | No error expected |
| Non-http deep link | `provenance.url` is `javascript:...` or similar | treated as absent: `source_deep_link` NULL, counted as above | No error expected |
| Silence gap | consecutive segment starts more than `gap_seconds` apart | a new moment starts at the later segment; `provenance.boundary = "silence-gap"` | No error expected |
| Long unbroken block | a run of segments spanning more than `max_duration_ms` | split at the first segment past the cap; `provenance.boundary = "max-duration"` | No error expected |
| Screenshot inside a block | screenshot starts mid-block | block is cut there; the tail is a new `derived_from = 'screen'` moment; the head keeps its id | No error expected |
| Coincident boundary | a screenshot starts exactly at a transcript boundary | one moment, `derived_from = 'both'`, keyed on the transcript anchor | No error expected |
| Screenshot before the first turn | screenshot span ends before any segment starts | its own moment covering zero segments | No error expected |
| Empty meeting | no segments and no screenshots | zero moments; the same log fields as the populated path with zeroes | No error expected |
| Rerun, unchanged inputs | stage run twice | identical moment ids, no duplicates, no deletions | No error expected |
| Rerun after screenshots vanish | transcript-only retry of a failed recording job | screen-anchored moments removed, transcript-anchored moments keep their ids and gain the deep link | No error expected |

</intent-contract>

## Code Map

- `server/meetingminer/pipeline/stages/__init__.py` — `STAGE_IMPLEMENTATIONS` (`:28`) is the
  registry; an unregistered name is the pause signal. Add `moments` (one line) and update the module
  docstring: after this story the pause is at `extract`, not `moments`.
- `server/meetingminer/domain/jobs.py` — `STAGE_NAMES` (`:11`) already contains `moments`;
  `VIDEO_ONLY_STAGES` (`:25`) correctly excludes it. **No change**, and its docstring line
  "`moments` then falls back to transcript segmentation" is the contract this story implements.
- `server/meetingminer/pipeline/runner.py` — `_clear_replaced_video_evidence()` (`:141`) already
  re-queues `align` when it clears the STT lane; it must also re-queue `moments`, because it deletes
  every `screenshot` row (`:168`) and a `done` `moments` checkpoint would then sit over moments that
  still name a screen this meeting no longer has. `run_job()`'s trailing comment (`:349-350`) says
  "today every job pauses at `moments`" — correct it to `extract`. `UPDATE job SET status = 'done'`
  (`:351`) needs no change: it is already reached only after every stage in `STAGE_NAMES` settles.
- `server/meetingminer/pipeline/stages/ocr.py` — the stage shape to imitate at its simplest: build
  once, replace this meeting's rows including on the empty path, emit the same log fields for zero
  as for many (`:86`).
- `server/meetingminer/pipeline/stages/screens.py` — the richer precedent: `run()` (`:316`) reads
  its inputs with one ordered SELECT, calls a pure core, then writes. `_ScreenUpserter.resolve`
  (`:247`) is the in-stage upsert pattern to mirror for moments. `_INSERT_SCREENSHOT` (`:54`) shows
  the named-parameter INSERT house style. Screenshot spans are `[first frame offset, last frame
  offset]` and are **disjoint and ordered** — `segment_captures` (`screens.py:265`) gives each frame
  to exactly one capture — which is what makes "the screenshot on display at this moment's start"
  single-valued.
- `server/meetingminer/pipeline/stages/align.py` — writes the `transcript_segment` rows this stage
  reads (`_INSERT` at `:77`) and replaces them wholesale on a rerun, so `moment_segment` must
  cascade from `transcript_segment` and be rebuilt by this stage, never assumed durable.
- `server/meetingminer/pipeline/screens.py` — the precedent for a pure, DB-free stage core that is
  unit-testable without Postgres. `server/meetingminer/pipeline/moments.py` follows the same shape.
- `server/meetingminer/pipeline/stage.py` — `StageContext` (`:31`), `StageError` (`:21`). This stage
  needs neither `meeting_dir()` (`:49`) nor `relative_path()` (`:58`): it writes no file.
- `server/meetingminer/domain/drops.py` — `DropContents` (`:48`); `provenance` property (`:93`) and
  `title` (`:98`) are the pattern for the new `stream_url` property. `has_recording` (`:58`) decides
  whether the deep link stands in for replay. Read-only from stages.
- `server/meetingminer/migrations/0005_transcripts_participants.sql` — `transcript_segment` (`:163`)
  with `ordinal`, `start_ms`, `end_ms`, `speaker_label`, `participant_id`, and the index
  `transcript_segment_meeting_start_idx` (`:212`) whose comment already says it exists for this
  story. Next migration file is `0006_`.
- `server/meetingminer/migrations/0003_screens_screenshots.sql` — `screenshot` (`:64`) with
  `ordinal`, `start_offset_ms`, `end_offset_ms`, `view_type`, `capture_cues`; migration house style
  (`uuidv7()` PKs, `set_updated_at` triggers, CHECK-constraint enums, meeting-scoped indexes).
- `server/meetingminer/migrations/0002_meetings_media_frames.sql` — `meeting` (`:26`) with
  `started_at`, `started_at_precision` (`'second' | 'day'`), `has_recording`, `provenance`;
  `set_updated_at()` (`:7`).
- `server/meetingminer/config.py` — `PipelineConfig` (`:306`) gains `moments`; `AlignConfig` (`:281`)
  is the closest model to copy (documented, bounded fields). `_StrictModel` is `extra="forbid"`
  (`:92`), so `config.yaml` and every test fixture must gain the block together.
- `config.yaml` — `pipeline:` (`:53`), `align:` (`:152`). The new `moments:` block goes after it.
- `server/tests/conftest.py` — `EVIDENCE_TABLES` (`:149`) must name `moment` and `moment_segment` or
  isolation leaks. `TEAMS_TRANSCRIPT` (`:170`) is three turns 2 s/5 s/9 s apart — under any sane
  `gap_seconds`, so it yields exactly one transcript moment; `make_drop` (`:213`), `content_root`
  (`:260`), `synthetic_recording` (`:268`), `requires_ffmpeg` (`:246`), `requires_ocr` (`:306`).
- `server/tests/test_worker_runner.py` — `enqueue()` (`:53`), `stage_statuses()` (`:75`),
  `make_recording_drop` (`:40`). `test_recording_drop_runs_through_align_then_pauses` (`:217`) and
  the transcript-only pause assertion (`:315-318`) **must move** from `moments` to `extract`; a
  third at `:999`.
- `server/tests/test_worker_transcripts.py` — `pool` (`:51`), `segments` (`:109`), `only_meeting`
  (`:156`), `rerun_align` (`:515`) are the fixtures/helpers the new DB test module mirrors.
- `server/tests/test_config.py` — the inline `valid_config` YAML (`:44-70`) must gain the `moments:`
  block or every config test fails on the new required field.
- `server/tests/test_migrations.py` — `test_migration_files_are_discovered_in_order` (`:101`) asserts
  only the first three filenames and the sorted order; `0006_` needs no edit there.
- **Read-only authority:**
  `_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md`
  — AD-2 (Postgres-minted UUIDv7), AD-5 (`:198`, table ownership), AD-6 (`:200`, moment ids are the
  citation currency), AD-10 (`:228`, config-only thresholds), AD-11 (meeting-scoped idempotence),
  AD-13 (evidence never model-written), stage list (`:132`), transcript-only fallback (`:137`),
  ERD `MOMENT }o--o| SCREENSHOT` and `MOMENT ||--o{ TRANSCRIPT_SEGMENT` (`:362-363`).
  `_bmad-output/specs/spec-meetingminer/SPEC.md` — "Augmentation adds, never destroys" (`:67`).
  `_bmad-output/planning-artifacts/epics.md` — story 1.6 (`:317`), story 1.12 (`:505`) whose ACs this
  table design must not foreclose, UX-DR11 (`:113`).
- **Read-only corpus evidence (measured this run against
  `/Users/devopsterus/current/meetingminer-drops`, do not re-derive):**
  - 28 finalized drops; 8 carry `recording.mp4`, 20 are transcript-only.
  - **`provenance.url` is present and non-empty on all 28** — it is the Stream URL the AC names,
    and it matches the `url` in each `_source.json`. There is no other URL field in a drop.
  - All 28 `transcript.txt` files parse: 7 983 turns, median 268.5 per meeting, last-turn start
    spanning 14-104 minutes.
  - Inter-turn **start-to-start** spacing: p50 5 s, p75 12 s, p90 20 s, p95 32 s, p99 72 s, max 406 s.
  - At a 20 s gap rule: 823 blocks, median 30.5 per meeting (range 9-57); block span p50 30 s,
    p75 71 s, p90 127 s, p95 174 s; 4.6 % run past 180 s.

## Tasks & Acceptance

**Execution:**
- `server/meetingminer/migrations/0006_moments.sql` -- new migration creating `moment` and
  `moment_segment` -- the bundle's citation targets must be Postgres rows with `uuidv7()` ids from
  creation (AD-2). `moment`: `id`, `meeting_id` (FK CASCADE), `identity_key`, `derived_from` CHECK
  in (`transcript`, `screen`, `both`), `start_ms`, `end_ms` (CHECK `end_ms >= start_ms`),
  `started_at timestamptz`, `started_at_precision` CHECK in (`second`, `day`), `screenshot_id` FK
  **ON DELETE SET NULL** (a screens rerun must leave the dangling reference visible, never delete
  moment evidence), `source_deep_link`, `segment_count`, `provenance jsonb`, timestamps,
  `set_updated_at` trigger, `UNIQUE (meeting_id, identity_key)`, indexes on
  `(meeting_id, start_ms)` and `(screenshot_id)`. **No ordinal column** — comment why.
  `moment_segment`: `(moment_id CASCADE, transcript_segment_id CASCADE)` PK plus
  `UNIQUE (transcript_segment_id)`, which is the ERD's `MOMENT ||--o{ TRANSCRIPT_SEGMENT` enforced
  in the schema rather than assumed.
- `server/meetingminer/pipeline/moments.py` -- new pure core, no psycopg import -- boundary
  computation and coverage, unit-testable without Postgres. Provide: `transcript_boundaries()`
  (first segment start, plus each start more than `gap_seconds` after the previous start, plus each
  start past `max_duration_ms` from the current block's start, each tagged
  `first-segment | silence-gap | max-duration`); `plan_moments()` unioning those with one boundary
  per screenshot start, deduplicating a coincident pair to a single `both` boundary keyed on the
  transcript anchor, assigning each segment to the span its `start_ms` falls in, closing the last
  span at `max(last segment end, last screenshot end)`, and selecting for each span the screenshot
  with the greatest `start_offset_ms <= span start`; `identity_key_for()` returning
  `transcript:<start_ms>` or `screen:<start_ms>`.
- `server/meetingminer/pipeline/stages/moments.py` -- new stage -- one ordered SELECT per input
  table, call the core, upsert by `(meeting_id, identity_key)`, delete only the
  `derived_from = 'screen'` rows this run did not recompute, rebuild `moment_segment` for this
  meeting, and emit one `stage.moments.identified` event carrying `moment_count`,
  `transcript_anchored`, `screen_anchored`, `with_screenshot`, `moments_without_link`,
  `segments_covered`, `retained_stale` (transcript-anchored moments left in place because this run
  did not recompute them), `boundaries` (per-reason counts) and the config used — with the same fields on
  the empty path.
- `server/meetingminer/pipeline/stages/__init__.py` -- register `moments`; update the docstring so
  the documented pause is `extract` -- an unregistered name is the pause signal and the docstring is
  the only place that states which one.
- `server/meetingminer/domain/drops.py` -- add a `stream_url` property returning
  `provenance["url"]` only when it is a non-empty `http`/`https` string, else `None` -- one place
  decides what counts as a usable source link, and a non-http scheme never reaches a rendered link.
- `server/meetingminer/pipeline/runner.py` -- re-queue `moments` inside
  `_clear_replaced_video_evidence()`; correct the stale "pauses at `moments`" comment -- the function
  deletes every screenshot, so a `done` moments checkpoint would describe evidence that is gone.
- `server/meetingminer/config.py` -- add `MomentsConfig` (`gap_seconds` float > 0,
  `max_duration_ms` int > 0) and wire it into `PipelineConfig` -- every threshold the stage compares
  against is configuration, never a code constant (AD-10).
- `config.yaml` -- add the `pipeline.moments` block with the measured defaults and comments naming
  the measurement -- a threshold whose rationale is not written down is retuned blind.
- `server/tests/test_moments_core.py` -- new -- unit-test every I/O Matrix row that does not need a
  database: gap split, max-duration split, screenshot split, coincident boundary, screenshot before
  the first turn, empty inputs, identity-key derivation, and the invariant that transcript
  boundaries are unchanged by adding screenshots.
- `server/tests/test_worker_moments.py` -- new -- drive the real runner over a transcript-only drop
  and a recording drop: rows written, `screenshot_id` and `source_deep_link` set as specified,
  segments covered exactly once, rerun stability (same ids, no duplicates), a screenshot arriving
  later splitting a block while the head keeps its id, and the non-http and missing-url link cases.
- `server/tests/conftest.py` -- add `moment` and `moment_segment` to `EVIDENCE_TABLES` -- a new table
  missing from TRUNCATE leaks rows between tests silently.
- `server/tests/test_worker_runner.py` -- move the three pause assertions from `moments` to
  `extract` -- the pause is real and must stay asserted at its new location, not deleted.
- `server/tests/test_config.py` -- add the `moments:` block to the inline `valid_config` YAML -- the
  settings model forbids extras and requires the new section.

**Acceptance Criteria:**
- Given a drop with a recording, screenshots and derived transcript segments, when the `moments`
  stage runs, then every moment row carries `start_ms`/`end_ms` in integer milliseconds, an ISO 8601
  UTC `started_at` equal to the meeting's `started_at` plus `start_ms` with the meeting's precision
  copied alongside, a `derived_from` value, a `provenance` object naming the boundary reason and the
  config used, and the screenshot on display at its start.
- Given a transcript-only drop, when the stage runs, then moments derive from transcript
  segmentation alone, every `screenshot_id` is NULL, and every moment carries the drop's
  `provenance.url` as `source_deep_link`.
- Given a meeting whose drop carries no usable `provenance.url`, when the stage runs, then moments
  are still written with `source_deep_link` NULL and the count appears in the stage log.
- Given a completed `moments` stage, when the job continues, then it pauses at `extract` with
  `extract` still `queued` and the job still `running`; no job reaches `done` and nothing is marked
  `done` or `skipped` on `extract`'s behalf.
- Given a meeting already carrying moments, when the stage runs again over the same inputs, then
  every moment id is unchanged, no moment is deleted, and no duplicate row appears.
- Given a meeting already carrying transcript-anchored moments, when screenshots are introduced and
  the stage runs again, then every pre-existing moment keeps its id and start, gains its screenshot
  where one was on display, loses its deep link, and any new span appears as an additional
  `derived_from = 'screen'` moment.
- Given every row this story writes, when it is created, then it is a Postgres row with a
  Postgres-minted UUIDv7 primary key.
- Given the whole server suite, when it runs, then it passes with no new failures beyond the two
  pre-existing ones recorded in story 1.5's Auto Run Result.

## Spec Change Log

## Review Triage Log

### Review Findings — 2026-08-18

- [x] [Review][Patch] Upstream evidence reruns leave `moments` settled over replaced inputs [server/meetingminer/pipeline/stages/screens.py:323] — A supported runner rerun can queue only `screens` (as `test_screens_rerun_replaces_screenshots_and_keeps_screen_rows` does) while `moments` remains `done`. `screens` deletes the old screenshots, so `ON DELETE SET NULL` clears every current `moment.screenshot_id`; the runner then resumes rather than reruns `moments`, leaving no moment for new captures or restored references. The equivalent `align` rerun at `server/meetingminer/pipeline/stages/align.py:598` deletes `transcript_segment` rows and cascades `moment_segment`, leaving a settled moment with stale `segment_count`. Ensure successful re-execution of either upstream producer invalidates and reruns `moments`, preserving moment ids, and prove both paths through the real runner.
- [x] [Review][Patch] The required missing-link event field is absent [server/meetingminer/pipeline/stages/moments.py:249] — The frozen I/O matrix requires `moments_without_link`, but the summary emits only `degraded_moments_without_link`. A transcript-only drop with missing or non-HTTP provenance therefore produces no field a contract-following log consumer can read. Restore the specified event field (an additive compatibility field is acceptable) and cover the exact field name.
- [x] [Review][Patch] `retained_stale` counts superseded screen moments [server/meetingminer/pipeline/stages/moments.py:224] — The required metric is the number of transcript-anchored moments retained because they were not recomputed. The broad `NOT id = ANY(...)` update also returns a `screen` moment that a transcript boundary supersedes, so the reported count conflates two distinct cases. Count only retained transcript-anchored rows while continuing to mark any preserved screen row superseded.
- [x] [Review][Patch] Replay does not retire deep links on newly superseded moments [server/meetingminer/pipeline/stages/moments.py:224] — Start with transcript-only moments carrying the source link, then add replay evidence and rederive transcript boundaries so an old transcript moment is retained as superseded rather than upserted. The supersession update leaves its `source_deep_link` intact even though the schema and stage contract say the link is cleared once replay arrives. Retire that fallback link for retained rows when replay evidence is present, without deleting the citation target.
- [x] [Review][Patch] A hostless HTTP(S) value is accepted as a deep link [server/meetingminer/domain/drops.py:123] — `urlsplit("https:")` yields the allowed `https` scheme, so the property returns `"https:"`; it is not a usable recap link and will be stored/rendered rather than counted as absent. Require a valid authority component for HTTP(S) links and add malformed hostless examples to the property tests.

### 2026-08-18 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 19: (high 0, medium 7, low 12)
- defer: 3: (high 0, medium 3, low 0)
- reject: 12
- addressed_findings:
  - `[medium]` `[patch]` `plan_moments`'s on-display scan ignored `end_offset_ms`, so a
    moment starting after the last capture ended still named it — factually wrong on a
    meeting whose transcript outruns the recording. Bounded at the last capture's end;
    captures are still carried across the gaps between consecutive captures.
  - `[medium]` `[patch]` `urlsplit` raises `ValueError` on a malformed URL such as
    `http://[::1`, which would have failed the whole stage on a data quirk. Guarded; an
    unparseable URL is treated as absent.
  - `[medium]` `[patch]` The `derived_from = 'screen'` delete sweep re-keyed a moment: a
    `screen:X` row taken over by a later coincident transcript boundary was deleted and
    re-minted as `transcript:X` with a new UUID. The sweep now spares any screen moment
    whose `start_ms` a recomputed moment shares.
  - `[medium]` `[patch]` Retained-stale moments were half-updated and unmarked, so ghost
    moments interleaved with live ones with nothing to tell them apart. They now carry
    `provenance.superseded`, merged rather than overwritten, and the upsert un-marks a
    row whose boundary comes back.
  - `[medium]` `[patch]` No test observed a moment with a non-NULL `screenshot_id`
    surviving its screenshot's deletion with the same id; flipping the FK to CASCADE
    would have broken AD-6 with the suite green. Test added.
  - `[medium]` `[patch]` `test_zero_frames_completes_ocr_and_screens_with_no_outputs` had
    its `moments` pause assertion replaced rather than moved, leaving the one
    recording-without-screenshots case — the branch that decides the deep link —
    asserting nothing about the new stage. Re-asserted.
  - `[medium]` `[patch]` `sprint-status.yaml` still recorded the story as `backlog`.
  - `[low]` `[patch]` A covered segment may end after the moment covering it; documented
    as a stated consequence of contiguous tiling and pinned by a test rather than left
    accidental. Tiling unchanged.
  - `[low]` `[patch]` `moments_without_link` did not mean what its name said; renamed to
    `degraded_moments_without_link` with the definition stated.
  - `[low]` `[patch]` No test drove a `startedAtPrecision: "day"` meeting, so hardcoding
    `'second'` would have passed. Test added.
  - `[low]` `[patch]` `stream_url`'s docstring claimed the value is returned verbatim
    while the code strips whitespace.
  - `[low]` `[patch]` No unit test for `stream_url` alongside the sibling `title`
    property; eleven parametrized URL cases added.
  - `[low]` `[patch]` `config.yaml` embedded a machine-specific absolute path.
  - `[low]` `[patch]` `test_adding_screenshots_does_not_move_a_single_transcript_boundary`
    compared two identical calls and could not fail; rewritten against `plan_moments`.
  - `[low]` `[patch]` `stage.moments.identified` was missing from the shared
    empty-vs-populated log-parity check.
  - `[low]` `[patch]` The SELECT ordered by `ordinal` and the core then re-sorted by UUID
    text; `SegmentFacts` now carries `ordinal` and both sorts use it.
  - `[low]` `[patch]` `ctx.conn.cursor().executemany(...)` left the cursor unclosed.
  - `[low]` `[patch]` No progress heartbeat on a boundary-dense meeting (one corpus
    recording plans ~600 upserts); `stage.moments.progress` added.
  - `[low]` `[patch]` `test_clearing_replaced_video_evidence_requeues_moments` asserted
    `done` before and after, observing nothing; now asserts state only a real re-run
    produces.

## Design Notes

- **Why boundaries, not "one moment per screenshot".** The obvious reading of the AC — a moment is a
  screenshot plus the discussion over it — cannot survive story 1.12. A transcript-only meeting has
  no screenshots, so its moments must be transcript-derived; when the recording arrives, a
  screenshot-derived layout would produce a different set of moments and every citation minted
  before augmentation would have to be re-keyed. The SPEC forbids exactly that. Cutting the timeline
  at the **union** of the two boundary sets means the transcript boundaries are identical before and
  after augmentation: a pre-existing moment keeps its start and its id, gets shorter, and the tail it
  gave up becomes a new screen-anchored moment — which is precisely what 1.12's acceptance criteria
  describe ("still exists with the same identity, now carrying its screenshot" and "new
  screen-derived moments may be added alongside").
- **Why the gap test uses start-to-start distance.** `align` synthesizes a turn's `end_ms` as the
  next turn's start (capped at `max_segment_ms`), so end-to-start gaps are zero almost everywhere
  and carry no signal. Consecutive **starts** are the only real measure of silence in this corpus.
- **Where the two defaults come from.** Measured over all 28 real transcripts this run.
  `gap_seconds: 20` is the p90 of inter-turn spacing: it yields a median of 30.5 moments on meetings
  whose transcripts span a median of ~50 minutes — roughly one moment per 1.7 minutes, the same
  order as the capture guardrail of under one screenshot per minute, so moments and screenshots stay
  comparable in density rather than one swamping the other. Tightening to 10 s would produce ~80
  blocks per meeting (28 % of all gaps), loosening to 30 s ~16. `max_duration_ms: 180000` is a
  backstop, not a working knob: at a 20 s gap only 4.6 % of blocks run past three minutes (p90 is
  127 s), and without a cap the longest measured block runs 434 s.
- **The deep link is the recap URL verbatim.** UX-DR11 asks for a link "to the original recap", and
  `provenance.url` is a SharePoint Stream page URL present on 28 of 28 drops. No time parameter is
  appended: this project has not verified any deep-link time syntax against SharePoint Stream, and
  the moment's own `start_ms` is carried separately for whoever does. The link is written on every
  moment of a meeting whose drop has no recording and cleared when one arrives, which is how
  UX-DR11's "the deep link is retired" happens with no extra mechanism.
- **Why the stage does not replace wholesale.** Every other meeting-scoped stage deletes its rows
  and rewrites them. `moments` cannot: a moment id is the citation currency (AD-6) and deleting one
  breaks every answer and published artifact that named it. Upsert by identity key is the whole
  idempotence story. The one deletion allowed — screen-anchored moments the current run did not
  recompute — is safe because such a moment exists only as the record of a screenshot that no longer
  does.
- **What this story deliberately leaves paused.** Registering `moments` moves the pipeline's pause
  from `moments` to `extract` (Epic 4). No job reaches `done` until that stage exists, which is the
  design the stage registry already documents. Story 1.7's "at ingest-complete" trigger therefore
  has nothing to fire on yet; that is 1.7's problem to solve, not a reason to fake `extract` here.

```text
transcript starts:   0s      18s        42s ......................... 300s
screenshots:                      [30s -------- 95s] [95s ---- 160s]
boundaries:          0s(t)         30s(s)        95s(s)      120s(t, gap)
moments:             |--0s--|------30s------|----95s----|-----120s-----|
identity keys:  transcript:0   screen:30000  screen:95000  transcript:120000
```

## Verification

**Commands:**
- `uv run --project server pytest server/tests` -- expected: all pass except the two failures
  recorded in story 1.5's Auto Run Result (`test_parse_tsv_without_page_dimensions_is_a_named_error`,
  `test_empty_and_populated_stage_logs_carry_the_same_fields`), which are pre-existing. Start
  Postgres with `make infra-up` first; ffmpeg/OCR/STT-dependent tests skip only with their named
  reason. Story 1.5 recorded that a shared fixed-name `meetingminer_test` database produces spurious
  `AdminShutdown` failures when two suites interleave — run this alone.
- `make migrate && make migrate` -- expected: applies `0006_moments.sql` once; the second run reports
  nothing to apply.
- `make test` -- expected: server suite as above, puller suite unchanged, web build succeeds (no API
  surface change).
- `make up`, POST a transcript-only drop from `/Users/devopsterus/current/meetingminer-drops` to
  `/ingests`, then `GET /jobs/{id}` -- expected: `probe`..`transcribe` `skipped`, `align` and
  `moments` `done`, `extract` `queued`, job `running`. `moment` rows exist with `screenshot_id` NULL,
  a non-null `source_deep_link` equal to the drop's `provenance.url`, and `moment_segment` covering
  each `transcript_segment` at most once. The drop directory's file list, sizes and mtimes are
  unchanged.
- `make up` with a drop that carries `recording.mp4` -- expected: `moment` rows split at screenshot
  starts, `screenshot_id` populated where a screenshot was on display, `source_deep_link` NULL.
- Re-run `moments` over an already-processed meeting (set the checkpoint back to `queued`) --
  expected: identical `moment.id` set, no duplicates, `moment_segment` rebuilt.

## Auto Run Result

Status: done

**Implemented change.** The `moments` stage, which turns the two evidence lanes the earlier stages
produced into the unit everything downstream cites. It cuts the meeting timeline at the union of
transcript-derived and screenshot-derived boundaries — each set computed independently, so a
transcript boundary is identical before and after a recording arrives — and writes one `moment` row
per span carrying video-offset milliseconds, ISO 8601 UTC wall clock with the meeting's precision,
the screenshot on display at its start, provenance, and the transcript segments it covers. On a
meeting with no replay evidence at all, each moment carries the drop's Stream URL as UX-DR11's
transitional deep link, which the same upsert clears when a recording arrives. Idempotence is upsert
by `(meeting_id, identity_key)` rather than the delete-then-insert every other meeting-scoped stage
uses, because a moment id is the citation currency (AD-6) and the SPEC forbids re-keying one.

**Files changed.**
- `server/meetingminer/migrations/0006_moments.sql` — `moment` (no ordinal column, `uuidv7()` id,
  `UNIQUE (meeting_id, identity_key)`, `screenshot_id` FK `ON DELETE SET NULL`) and `moment_segment`
  (`UNIQUE (transcript_segment_id)` enforcing the ERD's one-moment-per-segment relationship).
- `server/meetingminer/pipeline/moments.py` — the pure core: boundary computation, coverage,
  on-display screenshot selection, identity keys.
- `server/meetingminer/pipeline/stages/moments.py` — the stage: two ordered SELECTs, the upsert, the
  one deletion it is allowed, the `moment_segment` rebuild, and the summary event.
- `server/meetingminer/pipeline/stages/__init__.py` — `moments` registered; the documented pause
  moves to `extract`.
- `server/meetingminer/domain/drops.py` — `stream_url`, the one place deciding what counts as a
  usable source link.
- `server/meetingminer/pipeline/runner.py` — `_clear_replaced_video_evidence()` re-queues `moments`;
  the stale pause comment corrected.
- `server/meetingminer/config.py`, `config.yaml` — `MomentsConfig` and the measured defaults.
- `server/tests/` — two new modules (`test_moments_core.py`, `test_worker_moments.py`) plus
  additions to `conftest.py`, `test_config.py`, `test_drops.py`, and `test_worker_runner.py`.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — story marked `done`.

**Review findings.** 19 patched (high 0, medium 7, low 12), 3 deferred, 12 rejected. 0 intent gaps,
0 spec defects. The four that mattered: the on-display scan ignored `end_offset_ms`; `urlsplit`
raised on a malformed URL and would have failed the stage; the delete sweep could re-key a
`screen:X` moment a later transcript boundary took over — the exact failure the identity design
exists to prevent; and retained-stale moments were left unmarked among the live ones.

**Follow-up review recommended: true.** Patched counts: high 0, medium 7, low 12. Score
`3 x 7 + 1 x 12 = 33`, well over the threshold of 5.

**Verification performed.**
- `uv run --project server pytest server/tests` — **537 passed, 2 failed**. Both failures
  (`test_parse_tsv_without_page_dimensions_is_a_named_error`,
  `test_empty_and_populated_stage_logs_carry_the_same_fields`) were reproduced against baseline
  `2d301b6d7db1f48fc5f631707c34ea52dc21db86` in a clean detached worktree and are pre-existing.
- `make migrate && make migrate` — `0006_moments.sql` applied once; both runs afterwards report
  nothing to apply. The applied schema was read back from Postgres and matches the file's DDL
  exactly, including `moment_screenshot_id_fkey` at `ON DELETE SET NULL`.
- `make test` — `check-client` and the puller suite pass; the run stops at the two pre-existing
  pytest failures, so `pnpm --dir web run build` was run separately and succeeds.
- Matrix test audit — all twelve I/O matrix rows covered by tests that ran and passed; 75 passed,
  0 skipped across `test_moments_core.py`, `test_worker_moments.py`, and `test_drops.py`.
- **Real corpus, through the actual worker.** 23 meetings carried moments at the point the worker
  was stopped: 713 transcript-anchored, 965 screen-anchored, 9 `both`. 6463 transcript segments and
  6463 `moment_segment` links, with no segment linked twice. All 567 transcript-only moments carry
  an `https` deep link; no moment on a recording meeting carries one. Every row's `started_at`
  equals its meeting's `started_at` plus `start_ms`; every `segment_count` matches its link count;
  every id is a UUIDv7. `extract` is `queued` on all 30 jobs and no job is `done`.

**Residual risks.**
- The real-corpus figures above were taken mid-run: the worker was stopped deliberately, so seven
  meetings still have `moments` queued and 24 jobs sit `running` pending the requeue a worker
  restart performs.
- Screen–discussion alignment over many screenshots is exercised end-to-end only by the by-hand
  corpus run recorded above; the automated multi-screenshot tests call the stage function directly.
  Deferred.
- A retained-stale moment keeps its old span and screenshot while marked `superseded`. That is the
  deliberate cost of never deleting a citation target, and Epic 2's projection will need to decide
  whether to filter on the marker.
- Moment density inherits screenshot density, which breaches the NFR2 guardrail on eight of the nine
  corpus recordings. Deferred as a `screens` tuning finding.
- One job in the corpus failed at `align` on a transcript matching neither lineage — story 1.5
  behaviour on a corpus file, unrelated to this change.
- Two pre-existing suite failures keep `make test` red independently of this story.
