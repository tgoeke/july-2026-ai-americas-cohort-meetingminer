# Reviewer handoff — Story 1.6: Moment Identification Completes the Bundle

You are reviewing a change you have no prior context on. Everything you need is below.

## Repository and range

- Repo: `/Users/devopsterus/current/cohort/meetingminer`
- Branch: `main` (pushed; `origin/main` is at the same revision)
- Review range: `2d301b6d7db1f48fc5f631707c34ea52dc21db86..HEAD`

Commits in the range:

| Revision | Subject |
|---|---|
| `ec4cf460ff1a487841e9ee25aa91e6c495423afb` | `docs(epic-1): regenerate epic context from current epics.md` |
| `1789adc51e68d11f3eba9db29d6f7523b30a7340` | `feat(pipeline): identify moments and complete the evidence bundle (story 1.6)` |

`ec4cf46` belongs to a **different concern** — it regenerates a planning-context
document that was stale (it omitted story 1.12 entirely). It is not story 1.6 code.
Review it only for whether the regenerated context misstates anything; the story
itself is `1789adc`.

## The spec

`_bmad-output/implementation-artifacts/spec-1-6-moment-identification-completes-the-bundle.md`

- Everything inside the `<intent-contract>` element — Intent, Boundaries & Constraints,
  I/O & Edge-Case Matrix — is **frozen intent**. Treat it as the requirement.
- Everything outside it — Code Map, Tasks & Acceptance, Design Notes, Verification,
  Review Triage Log, Auto Run Result — is **planner work you may attack**. The design
  decisions listed below all live there.

## Architecture authority

Read `_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md`.
The decision records that actually govern this change:

- **AD-2** — every domain object is a Postgres row from creation with a Postgres-minted UUIDv7.
- **AD-5** — table ownership: the worker writes evidence tables, the API writes user-declared data.
- **AD-6** — a moment's id is minted once and is the citation currency carried verbatim into Neo4j,
  Meilisearch and every answer. This is the record the whole idempotence design turns on.
- **AD-10** — every adapter binding and threshold comes from `config.yaml`, never a code constant.
- **AD-11** — meeting-scoped idempotence; a stage rerun overwrites only its own outputs for that meeting.
- **AD-13** — evidence is written by deterministic code, never by a model.
- The stage list at `:132` and the transcript-only fallback at `:137`.
- The ERD at `:355-368`, specifically `MOMENT }o--o| SCREENSHOT : evidences` and
  `MOMENT ||--o{ TRANSCRIPT_SEGMENT : covers`.

Also governing, and more important than any of the above for this story:

- `_bmad-output/specs/spec-meetingminer/SPEC.md:67` — **"Augmentation adds, never destroys."** A
  later drop may attach a screenshot, replay window and alignment to an existing moment and may add
  new screen-derived moments, but never deletes, renumbers or re-keys a moment that already exists.
- `_bmad-output/planning-artifacts/epics.md:113` (UX-DR11) and `:317` (story 1.6) and `:505`
  (story 1.12, whose acceptance criteria this table design must not foreclose).

## Scope

**In scope** — the files in `1789adc`:

- `server/meetingminer/migrations/0006_moments.sql`
- `server/meetingminer/pipeline/moments.py` (pure core)
- `server/meetingminer/pipeline/stages/moments.py` (the stage)
- `server/meetingminer/pipeline/stages/__init__.py` (registration + docstring)
- `server/meetingminer/pipeline/runner.py` (re-queue `moments` on video-evidence clear)
- `server/meetingminer/domain/drops.py` (`stream_url`)
- `server/meetingminer/config.py`, `config.yaml` (`MomentsConfig` and its two thresholds)
- `server/tests/test_moments_core.py`, `server/tests/test_worker_moments.py`, and edits to
  `conftest.py`, `test_config.py`, `test_drops.py`, `test_worker_runner.py`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`, and the spec itself

**Out of scope:**

- The `extract` stage — Epic 4. It is deliberately unregistered and jobs pause there.
- Any `/moments` API route, projection, or UI — Epic 2 and story 1.7.
- Story 1.12's augmentation flow — intake does not yet accept an augmenting drop.
- `pull_transcript/` — vendored, read-only, untouched.
- The three items already recorded in the spec's frontmatter `deferred` list, and everything in
  `_bmad-output/implementation-artifacts/deferred-work.md`.

## Design decisions to attack

Each of these is a planner choice plus the assumption holding it up. The planner is not a neutral
judge of its own calls, so these are handed over rather than left to be rediscovered.

1. **Moments are cut at the union of transcript-derived and screenshot-derived boundaries, not one
   per screenshot.** *Assumption:* the more literal reading of AC1 — a moment is a screenshot plus
   the discussion over it — cannot satisfy SPEC:67, because a transcript-only meeting's moments
   would be re-keyed the moment a recording arrived. If that assumption is wrong, the whole shape
   is wrong.
2. **A moment's `identity_key` is `transcript:<start_ms>` or `screen:<start_ms>`, and a coincident
   span keys on the transcript anchor.** *Assumption:* a turn's `start_ms` comes from the provided
   transcript and does not move when a recording arrives, because `align` records the STT offset in
   `alignment_delta_ms` rather than snapping `start_ms`. Verify that assumption against
   `pipeline/stages/align.py` — if a matched row's start can move, every identity key can move.
3. **The `moment` table has no ordinal column; order is `start_ms`.** *Assumption:* an ordinal
   cannot survive story 1.12 inserting a moment between two existing ones.
4. **Idempotence is upsert, and the stage never deletes a transcript-anchored moment even when the
   current transcript no longer produces it.** Such a row is kept, its `segment_count` zeroed, and
   `provenance.superseded` set. *Assumption:* a stale citation target that resolves to an old span
   is less harmful than a broken citation. Epic 2's projection will have to decide whether to filter
   on that marker — check whether the marker is sufficient for it to do so.
5. **The one deletion allowed is a screen-anchored moment the run did not recompute and whose
   `start_ms` no recomputed moment took over.** The second clause was added during review because
   without it a `screen:X` row was deleted and re-minted as `transcript:X` with a new UUID.
   *Assumption:* no other path can delete or re-key a moment. Try to find one.
6. **The screenshot named is the latest capture starting at or before the span's start, bounded at
   the last capture's end.** *Assumption:* capture spans are disjoint and ordered, so the gaps
   between consecutive captures are sampling artifacts across which the screen genuinely was still
   up, while past the final capture nothing is on display. Verify the disjointness claim against
   `pipeline/screens.py::segment_captures`.
7. **A covered segment may end after the moment covering it**, because segments are assigned by
   `start_ms` while spans close at the next boundary and `align` synthesizes ends up to
   `max_segment_ms` (60 s). Documented and pinned by a test rather than fixed. *Assumption:* keeping
   spans contiguous matters more than making every citation window contain all of its own words.
   This is the decision most likely to be wrong.
8. **The deep link is the recap URL verbatim, with no time parameter**, and it is written per
   meeting (`has_recording or any screenshots`) rather than per moment. *Assumptions:* UX-DR11's
   "link to the original recap" means the page, not a point; and a moment in a recording meeting has
   video replay even where it has no screenshot, so it needs no standby link. Story 1.12's AC says
   the link retires when video arrives "**for it**" — check whether the per-meeting predicate is
   really equivalent.
9. **`gap_seconds: 20` and `max_duration_ms: 180000`.** Measured this run over all 28 real
   transcripts: 7,983 turns, inter-turn start-to-start spacing p50 5 s / p90 20 s / p95 32 s; at a
   20 s gap, 823 blocks, median 30.5 per meeting, block span p90 127 s with 4.6% past 180 s. The
   measurement is recorded in the spec and `config.yaml`, not in `corpus-facts.md` — the same
   convention story 1.11 used. *Assumption:* moment density should sit in the same order as capture
   density.
10. **`moment_segment` carries `UNIQUE (transcript_segment_id)`**, enforcing the ERD's one-moment-
    per-segment relationship in the schema. *Assumption:* no future story needs a segment covered by
    two moments.

## History a reviewer needs

- The `moments` stage was **designed to be paused at** by stories 1.3-1.5; the stage registry's
  docstring named story 1.6 as the one that would register it. The pause moving to `extract` is
  therefore the pre-existing design, not a regression introduced here.
- `0006_moments.sql` was edited **after** it had been applied to the developer database, to correct
  one comment. The migration runner tracks filenames only, with no checksum (a known gap already
  recorded in `deferred-work.md`), so the applied schema was read back from Postgres and confirmed
  to match the file's DDL exactly. No structural drift.
- The change was reviewed once already by four parallel layers; 19 findings were patched and are
  listed in the spec's `## Review Triage Log`. Anything you find that duplicates one of those is
  either a regression or a patch that did not land.
- The worker was run over the real corpus during verification and then **stopped mid-run**. Seven
  meetings still have `moments` queued and 24 jobs sit `running` pending the requeue a worker
  restart performs. That is an environment state, not a defect.

## Verification baseline

Run these; a skip or a failure beyond the two named below is a finding, not noise.

- `make infra-up` first, then `uv run --project server pytest server/tests`
  — current result: **537 passed, 2 failed**. The two failures are
  `test_parse_tsv_without_page_dimensions_is_a_named_error` and
  `test_empty_and_populated_stage_logs_carry_the_same_fields`; both were reproduced at
  `2d301b6` in a clean detached worktree and are pre-existing.
  Run the suite alone — it uses a fixed-name `meetingminer_test` database, and two interleaved
  runs produce spurious `AdminShutdown` failures.
- `make migrate && make migrate` — applies nothing (already applied) and reports
  "nothing to apply" both times.
- `make test` — `check-client` and the puller suite pass, then the run stops at the two
  pre-existing pytest failures. `pnpm --dir web run build` succeeds when run separately.

## Required output

Write your findings to
`_bmad-output/implementation-artifacts/review-story-1-6-2026-08-18.md`.

**Report findings; do not apply fixes.** For each finding give: the file and line, what is wrong,
the concrete failure scenario (inputs or state, and the wrong result), your severity
(low / medium / high), and whether you believe it is caused by this change or pre-existing. Group
by severity, most severe first. If you find nothing at a given severity, say so explicitly rather
than omitting the heading.
