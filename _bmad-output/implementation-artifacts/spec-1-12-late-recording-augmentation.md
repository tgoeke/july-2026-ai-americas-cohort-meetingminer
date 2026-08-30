---
title: 'Story 1.12: Late-Recording Augmentation'
type: 'feature'
created: '2026-08-19'
status: 'done'
baseline_revision: '5e1aa35c7d5b13e47af2702732d7ebc5692dbbf0'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md'
warnings: ['oversized']
deferred:
  - summary: >-
      The transcript-preservation guard at intake compares filenames only, never content.
    evidence: |-
      _check_augmenting_drop asserts that every transcript filename in the target's drop also
      exists in the augmenting drop, but not that the bytes match. A hand-authored augmenting
      drop carrying a different transcript.txt under the same name passes, align replaces the
      provided source, and transcript-derived moment identity keys move - the exact outcome the
      guard's own docstring says it exists to prevent. Both drops in every test share
      conftest.DROP_FILE_CONTENT, so the case never arises. Closing it means deciding what a
      later drop is allowed to restate, which is an AD-1 question, not a guard tweak.
    location: >-
      server/meetingminer/api/ingests.py (_check_augmenting_drop)
    severity: medium
  - summary: >-
      The recording-to-transcript-only direction never invalidates the projection state row, so
      the stores keep documents naming deleted screenshots.
    evidence: |-
      _clear_replaced_video_evidence deletes screenshots, frames, meeting_media and the STT
      transcript_source and re-queues align/moments, but leaves meeting_projection current.
      projection_action then answers ACTION_NONE and _maybe_project returns without touching
      Neo4j or Meilisearch. Pre-existing and untouched by story 1.12;
      projections.invalidate_meeting_projection, added by this story, is exactly the helper
      that closes it.
    location: >-
      server/meetingminer/pipeline/runner.py (_clear_replaced_video_evidence)
    severity: medium
  - summary: >-
      No row lock spans the read-then-re-arm sequence at intake, so two concurrent augmenting
      POSTs can both re-arm the same job.
    evidence: |-
      _augment_target, the readiness checks, and _rearm_job run as separate statements with no
      SELECT ... FOR UPDATE on the job row. Two augmenting POSTs for one occurrence can both
      pass evidence_complete() and has_recording is False, and both re-point drop_path; the
      last writer wins and the other recording is silently dropped. AD-9 pins one worker and
      one intake caller and the pre-existing failed-job re-queue path has the same shape, so
      this matches the surrounding code rather than adding a new hazard.
    location: >-
      server/meetingminer/api/ingests.py (_augment_target / _rearm_job)
    severity: medium
  - summary: >-
      Re-arming makes an already-viewable meeting non-viewable for the length of the re-run,
      with no coverage of the meetings-list or SSE view mid-augmentation.
    evidence: |-
      _rearm_job puts align and moments back to queued, so evidence_complete() goes false and
      GET /meetings reports viewable: false until the augmented run settles. The invalidation
      docstring says the meeting stays searchable for the length of the re-run, which holds for
      the stores but not for the API's viewable flag. Whether a mid-augmentation meeting should
      read as viewable is a UX decision Epic 2 owns.
    location: >-
      server/meetingminer/api/meetings.py:91
    severity: medium
  - summary: >-
      Allow a day-to-second startedAtPrecision upgrade on an augmenting drop instead of
      refusing every clock restatement.
    evidence: |-
      Story 1.12 pins startedAt and startedAtPrecision at intake because mint_meeting's ON
      CONFLICT would otherwise silently shift every preserved moment's wall clock. That
      conservative rule also refuses the realistic improvement: a transcript-only drop carries
      day precision, and a recovered recording carries a real timestamp derived from the
      recording filename. Allowing an upgrade whose date agrees would let evidence improve as
      the story intends; it needs a stated rule for what happens to moment started_at values
      that were stamped off midnight.
    location: >-
      server/meetingminer/api/ingests.py (_check_augmenting_drop)
    severity: low
  - summary: >-
      A worker crash between mint_meeting's commit and the projection invalidation leaves the
      augmentation permanently un-projected.
    evidence: |-
      mint_meeting commits has_recording = true, then _invalidate_augmented_projection runs. A
      crash strictly between the two makes the retry read had_recording as true, so the
      invalidation branch never fires, meeting_projection stays current, projection_action
      answers ACTION_NONE, and the augmented bundle never reaches either store. The window is
      narrow and rebuild --meeting is the remedy, but nothing detects it.
    location: >-
      server/meetingminer/pipeline/runner.py (run_job)
    severity: low
  - summary: >-
      The recovered recording's own sourceId is not persisted anywhere in Postgres when it
      differs from the target's.
    evidence: |-
      _rearm_job deliberately leaves job.source_id at the target's value so the meeting's
      identity stays stable, and overwrites drop_path. When the augmenting drop declares its
      own sourceId - the case the schema explicitly permits - that identity survives only
      inside the new drop's metadata.json. Nothing in the database records which physical
      source the meeting's recording actually came from, and the original drop's path is no
      longer recorded either.
    location: >-
      server/meetingminer/api/ingests.py (_rearm_job)
    severity: low
  - summary: >-
      An occurrence whose job failed after minting a meeting cannot be augmented.
    evidence: |-
      _augment_target resolves only non-failed jobs, so augments naming a failed occurrence
      returns 422 unknown-augment-target. The recovered recording is not stranded - the
      pre-existing failed-job re-queue path accepts a recording-bearing drop for that sourceId
      and the runner's had_recording is False branch then invalidates the projection - but
      nothing tells the caller that, and the two routes to the same outcome are undocumented.
    location: >-
      server/meetingminer/api/ingests.py (_augment_target)
    severity: low
  - summary: >-
      The four new problem types are not enumerated in the route's OpenAPI responses.
    evidence: |-
      unknown-augment-target, augment-target-incomplete, augment-target-has-recording and
      invalid-augmenting-drop exist only in ingests.py and its tests. The route still declares
      400/409/422 generically against ProblemDetails, so the generated TypeScript client has no
      way to enumerate or branch on them. Consistent with every other problem type in the
      service, so this is a service-wide gap surfaced here rather than a story defect.
    location: >-
      server/meetingminer/api/ingests.py (create_ingest responses)
    severity: low
---

<intent-contract>

## Intent

**Problem:** A recording recovered after a meeting was ingested transcript-only cannot reach the system: `POST /ingests` rejects the second drop with a 409 `duplicate-source`, and `docs/source-drop.schema.json` (`schemaVersion: const 1`, `additionalProperties: false`) has no field with which a drop could declare the meeting it augments. Late-arriving video is the expected path for most of the real corpus (`corpus-facts.md` §1), so FR32 is unreachable today.

**Approach:** Add an optional `augments` declaration to the drop schema at `schemaVersion: 2` (version 1 drops stay valid). When intake sees it, resolve the target occurrence and **re-arm that occurrence's existing job in place** — point it at the new drop and put exactly the previously-skipped video stages plus `align` and `moments` back to `queued` — instead of raising the conflict. The worker then re-runs those stages against the same meeting, and the runner invalidates the meeting's recorded projection state so the existing per-meeting delete-and-reinsert re-projects it. Re-using the job row (AD-14: "re-processing an occurrence is a rerun of its existing job, never a second Meeting row") is what keeps `meeting.job_id`/`meeting.source_id` unique, keeps the meeting id stable, and therefore keeps every moment id, citation, and published artifact valid.

## Boundaries & Constraints

**Always:**
- Existing moment ids survive. `moment` upserts on `UNIQUE (meeting_id, identity_key)` (`migrations/0006_moments.sql:54`) and preserves transcript-anchored identities through `identity_key_for()`.
- The already-finalized drop is never modified or deleted. Write-once applies to a drop, not to a meeting (AD-1).
- Provided transcripts survive (AD-13). `stages/align.py:217` drops `transcript_source` rows for provided kinds no longer present, so intake must refuse an augmenting drop that does not carry every transcript file the target's current drop carries.
- All Neo4j/Meilisearch writes stay inside `projections/` (AD-4). The API never touches `meeting_projection`.
- The drop schema stays the one shared artifact across the black-box seam: both `server/tests/test_drop_schema.py` and `pull_transcript/test/emit-drop.test.js` must validate against it independently and both must pass (story 1.8 AC).
- New API errors are RFC 9457 `application/problem+json` with `urn:meetingminer:problem:<slug>` types.

**Block If:**
- The chosen `augments` shape would require relaxing `job_source_id_live_key` (`migrations/0001_jobs.sql:18-20`), `meeting.job_id UNIQUE`, or `meeting.source_id UNIQUE`. Re-arming in place is chosen precisely to avoid that; if implementation forces a second job row per meeting, HALT — that is an AD-5/AD-14 change, not an implementation detail.

**Never:**
- Do not extend `pull_transcript/emit-drop.js`. Its write-once identity is the drop directory name `<date>-<title-slug>-<sha1(sourceId)[0:8]>` with `existsSync` detection (spec-1-8 deferred item), so a video-bearing re-pull resolves to the same directory and reports `exists`. Teaching it to emit augmenting drops is a separate story; for the capstone, augmenting drops are hand-authored or fixture-built. Record this in `deferred-work.md`.
- Do not add a moment API route or moment UI — Epic 2 owns those. AC "renders a true replay button" is satisfied at the data layer: `moment.source_deep_link` becomes NULL and `moment.screenshot_id` becomes non-NULL.
- Do not add replay-window or alignment columns to `moment`. Replay is `start_ms`/`end_ms` plus `screenshot_id`; alignment lives on `transcript_segment`.
- Do not reclassify the meeting: an augmenting drop whose `corpus` differs from the target's is refused, not applied.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Augmenting drop accepted | Target ingested transcript-only and evidence-complete; new drop has `recording.mp4` + the same transcript files, `schemaVersion: 2`, `augments.sourceId` = target's | 200 `{"jobId": <existing job id>}`; job `queued` with `drop_path` = new drop; the five `VIDEO_ONLY_STAGES` + `align` + `moments` back to `queued`; `extract` untouched | No error expected |
| Plain duplicate | Second drop, no `augments`, sourceId has a live job | 409 `duplicate-source` with `jobId` (unchanged behaviour) | Existing path |
| Unknown target | `augments.sourceId` matches no non-failed job with a meeting row | 422 `unknown-augment-target` | Problem+json |
| Target still ingesting | Target job's evidence stages not all `done`/`skipped` (`evidence_complete()`) | 409 `augment-target-incomplete` | Problem+json |
| Target already has video | Target `meeting.has_recording` is true | 409 `augment-target-has-recording` | Problem+json |
| Augmenting drop has no recording | `augments` present, `recording.mp4` absent | 422 `invalid-augmenting-drop` | Problem+json |
| Augmenting drop drops a transcript | Target's drop has `transcript.txt`; new drop does not (or target's drop dir is unreadable) | 422 `invalid-augmenting-drop` — refusing protects AD-13 | Problem+json |
| Corpus mismatch | `augments` present, `corpus` differs from the target job's | 422 `invalid-augmenting-drop` | Problem+json |
| Drop's own sourceId is a different live occurrence | `sourceId` != `augments.sourceId` and `sourceId` has its own live job | 409 `duplicate-source` | Existing `_conflict` |
| Schema: v1 drop | `schemaVersion: 1`, no `augments` | Validates (all 28 existing drops keep validating) | — |
| Schema: v1 + augments | `schemaVersion: 1` with `augments` | Fails validation | 422 `invalid-drop` with `violations` |
| Schema: unknown top-level key | `groundTruthId` present | Fails validation (`additionalProperties: false` retained) | 422 `invalid-drop` |

</intent-contract>

## Code Map

**Intake**
- `docs/source-drop.schema.json` -- `schemaVersion` is `const: 1`; `additionalProperties: false` on the last line; `$id` ends `/source-drop/1/metadata.json` and is referenced nowhere else in the tree.
- `server/meetingminer/api/ingests.py` -- `_conflict` :162-169; `_select_jobs` :172-178; `_seed_stages` :189-193; `create_ingest` :211-257 with the single conflict raise at **:223-225** and the re-queue-in-place precedent (UPDATE `drop_path`, re-seed stages, return **200**) at :227-244. Schema loaded once at startup (`load_drop_schema` :45-65).
- `server/meetingminer/api/problems.py` -- `problem_response` :66; slugs are free-form, no registry to extend.
- `server/meetingminer/domain/drops.py` -- `EVIDENCE_FILENAMES` :32-36, `RECORDING_FILENAME` :26, `TRANSCRIPT_VTT_FILENAME` :27, `TRANSCRIPT_TEXT_FILENAME` :28; `DropContents.has_recording` :58-65; `stream_url` :99-133 (the UX-DR11 link source).
- `server/meetingminer/domain/jobs.py` -- `STAGE_NAMES` :13-22, `VIDEO_ONLY_STAGES` :27-29 (exactly the replay set), `EVIDENCE_STAGES` :36, `evidence_complete()` :39-47 (**the readiness predicate to reuse — `job.status` never reaches `done` today because `extract` has no implementation**).
- `server/meetingminer/migrations/0001_jobs.sql:18-20` -- `job_source_id_live_key` partial unique index; `0002_meetings_media_frames.sql:28-29` -- `meeting.job_id UNIQUE`, `meeting.source_id UNIQUE`. Read-only evidence: these are why the job row is re-armed rather than a second job created.

**Worker**
- `server/meetingminer/pipeline/runner.py` -- `mint_meeting` :86-124 (`ON CONFLICT (job_id) DO UPDATE` already flips `meeting.has_recording` to true — no change needed); `_clear_replaced_video_evidence` :140-208 (the *reverse* direction; fires only when `not drop.has_recording`, so augmentation must not trigger it); `_maybe_project` :273-353 (gated on `projection_action`, returns early on `ACTION_NONE`); `run_job` :355-... with the transcript-only cleanup branch at :385-393 (**insert the mirror branch here**) and the settled-stage guard at :401.
- `server/meetingminer/pipeline/stages/moments.py` -- `has_replay = ctx.drop.has_recording or bool(screenshots)` :135, `deep_link = None if has_replay else ctx.drop.stream_url` :136, upsert :66-75/:155-186, superseded-row link retirement :224-232. **Deep-link retirement already works; this story only has to make `moments` re-run.**

**Projections**
- `server/meetingminer/projections/__init__.py` -- `__all__` :74-93; `projection_action` :187-213 (returns `ACTION_NONE` when a current `meeting_projection` row exists — **the reason augmentation would not re-project today**); `project_meeting` :479 (the per-meeting delete-and-reinsert); `unproject_meeting` :541 (deletes store rows *and* the state row — not wanted here: it opens both stores and blanks the meeting from search mid-run).
- `server/meetingminer/projections/graph.py:370` / `search.py:172,207` -- the delete-and-reinsert bodies, both already documented as "story 1.12's path".
- `server/meetingminer/migrations/0007_projection_state.sql:28-42` -- `meeting_projection` PK `meeting_id`.

**Tests (read-only evidence of what already holds)**
- `server/tests/test_worker_moments.py:517` id stability on rerun; `:554` screenshot arriving later keeps the head moment's id and retires its link; `:743` takeover is not a re-key.
- `server/tests/test_projections_graph.py:137` per-meeting re-projection leaves other meetings untouched.
- `server/tests/test_worker_runner.py:307` transcript-only skip; `:476` the reverse (recording → transcript-only) replacement.
- `server/tests/test_drop_schema.py:60-77` parametrizes `schemaVersion: 2` as **invalid** (must be updated); `:93-95` asserts unknown top-level keys fail (must stay).
- `pull_transcript/test/emit-drop.test.js:300-311` asserts the exact emitted key set (stays green — `emit-drop.js` is untouched); `:313-315` validates emitted metadata against the schema (the back-compat proof).
- `server/tests/conftest.py` -- `valid_metadata()` :74-86, `make_drop` :222; `test_pool` :123, `projection_stores` :687, `fake_embedder` :614, autouse `_no_incidental_projection` :620 and its `projection_trigger` escape :647.
- `server/tests/projection_seed.py:75` -- `seed_meeting(..., has_recording=..., turns=..., stage_overrides=...)`.

## Tasks & Acceptance

**Execution:**
- `docs/source-drop.schema.json` -- change `schemaVersion` to `"enum": [1, 2]`; add an optional `augments` object (`required: ["sourceId"]`, `sourceId` string minLength 1, `additionalProperties: false`); add an `allOf` rule that `augments` present implies `schemaVersion` 2; bump `$id` to `/source-drop/2/metadata.json` and update `title`/`description` to say it describes versions 1–2 and what `augments` means. Keep top-level `additionalProperties: false` and the existing `startedAtPrecision` if/then -- the frozen contract needs a declaration field before anything else can use one.
- `server/meetingminer/domain/jobs.py` -- add `AUGMENTATION_STAGES`, the stages an augmenting drop re-runs, derived in `STAGE_NAMES` order from `VIDEO_ONLY_STAGES` plus `align` and `moments`, with a docstring saying why `moments` is included (AC 4) and `extract` is not -- one definition shared by api and worker, per AGENTS.md's shared-predicate rule.
- `server/meetingminer/api/ingests.py` -- add an augmentation branch taken before the `_conflict` raise at :223-225: resolve the target by `augments.sourceId` joined to its `meeting` row, run the refusal checks in the I/O matrix, then re-arm in place (`UPDATE job SET status='queued', error=NULL, drop_path=<new>`; `UPDATE job_stage SET status='queued', error=NULL WHERE name = ANY(AUGMENTATION_STAGES)`), returning 200 with the existing `jobId`. Add 200's description to the route `responses` -- intake is the only door (AD-14), so acceptance has to happen here.
- `server/meetingminer/projections/__init__.py` -- add `invalidate_meeting_projection(conn, meeting_id, *, log=None) -> bool` deleting the `meeting_projection` row and returning whether one existed; export it in `__all__` -- makes the next `projection_action` return `ACTION_FULL` without opening a store or blanking the meeting from search mid-run.
- `server/meetingminer/pipeline/runner.py` -- read the persisted `meeting.has_recording` for the job *before* `mint_meeting` (it overwrites the value); after minting, when the drop now has a recording and the persisted value was false, log `job.augmenting` and call `projections.invalidate_meeting_projection`, logging and continuing on failure (never fail an ingest over projections, per `_maybe_project`) -- without this the terminal `_maybe_project` reads `ACTION_NONE` and the augmented bundle never reaches the stores.
- `server/tests/test_drop_schema.py` -- update the `schemaVersion: 2` case from invalid to valid, and add cases for: v1 + no `augments` valid, v1 + `augments` invalid, v2 + well-formed `augments` valid, `augments` missing `sourceId` invalid, `augments` with an extra key invalid. Keep `test_unknown_top_level_field_fails` -- covers the I/O matrix's schema rows.
- `server/tests/test_ingests.py` -- add the intake matrix rows: acceptance (200, existing jobId, stage statuses, `drop_path`), and each refusal with its exact problem `type` and status. Assert the target's original drop directory is byte-for-byte untouched using the existing `_snapshot` helper -- AC 1's second half.
- `server/tests/test_augmentation.py` (new) -- the end-to-end proof over Postgres: ingest a transcript-only drop, run the worker to evidence-complete, snapshot the moment id set, POST the augmenting drop, run the worker again, then assert (a) exactly `AUGMENTATION_STAGES` re-ran and `extract` stayed `queued`, (b) every pre-augmentation moment id still exists with the same `identity_key`, (c) `meeting.has_recording` is true and moments now carry `screenshot_id` with `source_deep_link` NULL, (d) new `screen:`-keyed moments may appear alongside, (e) `_clear_replaced_video_evidence` did not fire (`meeting_media` and `frame` rows exist). Use `seed_meeting`/`make_drop` fixtures and real pixel fixtures the way `test_worker_runner.py` story-1.11 tests do -- this is the story's acceptance evidence.
- `server/tests/test_projections_rebuild.py` -- add a test that augmenting a projected meeting re-projects it: `invalidate_meeting_projection` makes `projection_action` return `ACTION_FULL`, the re-projection replaces that meeting's documents (added moments present, superseded ones gone, no doubling) and leaves a second meeting's rows untouched. Needs `projection_stores` + `fake_embedder` -- the last AC.
- `pull_transcript/test/emit-drop.test.js` -- add one back-compat test asserting an emitted (`schemaVersion: 1`, no `augments`) metadata object still validates and that a hand-built v2 `augments` object validates, without touching `emit-drop.js` -- keeps story 1.8's independent-validation AC true across the schema change.
- `_bmad-output/implementation-artifacts/deferred-work.md` -- append the puller scope-out: `emit-drop.js` cannot emit an augmenting drop because a video-bearing re-pull resolves to the same `sha1(sourceId)` directory and `existsSync` reports `exists`; augmenting drops are fixture-built for the capstone.
- `_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md` -- amend AD-1 to record `schemaVersion: 2` and the `augments` field, and AD-14 to record that an augmenting drop re-arms the occurrence's existing job rather than being rejected -- the schema is AD-1's decision, so leaving the spine silent makes it wrong.

**Acceptance Criteria:**
- Given a meeting ingested transcript-only and evidence-complete, when an augmenting drop carrying a recording and declaring `augments.sourceId` is posted, then intake returns 200 rather than a `duplicate-source` conflict, and the earlier drop directory is unchanged in name, size, and mtime.
- Given that accepted drop, when the worker runs, then exactly `probe`, `frames`, `ocr`, `screens`, `transcribe`, `align`, and `moments` execute, `extract` stays `queued`, and no stage outside that set re-runs.
- Given augmentation completes, when moments are read, then every moment id present beforehand is still present with its original `identity_key`, and none was deleted, renumbered, or re-keyed.
- Given screens found in the recovered recording that no transcript-derived moment covers, when `moments` runs, then additional `screen:`-keyed moments exist alongside the pre-existing ones.
- Given a moment that carried `source_deep_link` before augmentation, when augmentation completes, then that moment's `source_deep_link` is NULL and it names a `screenshot_id`.
- Given the meeting was already projected, when augmentation completes, then the recorded `meeting_projection` row is replaced and the meeting's graph nodes and search documents are deleted and reinserted for that meeting id only, with every other meeting's rows unchanged.
- Given `pull_transcript` is unmodified, when `make puller-test` runs, then the emit-drop suite passes against the updated schema, proving version 1 drops still validate.

### Review Findings


## Review Triage Log

### 2026-08-19 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 9: (high 1, medium 2, low 6)
- defer: 9: (high 0, medium 4, low 5)
- reject: 11: (high 0, medium 0, low 11)
- addressed_findings:
  - `[high]` `[patch]` The re-projection AC had no end-to-end witness: test_augmentation.py did not take the projection_trigger fixture, so conftest's autouse _no_incidental_projection stubbed _maybe_project for the whole test and its only evidence was that meeting_projection was empty. Added test_augmentation_replaces_the_meetings_documents_in_both_stores, which runs the real trigger against live Neo4j and Meilisearch; confirmed by mutation (disabling the runner's invalidation call makes it fail).
  - `[medium]` `[patch]` AUGMENTATION_STAGES was only ever asserted against itself, so dropping align or transcribe from the comprehension would have shrunk both sides together and shipped green. Pinned the literal tuple and its order, and added an outcome witness that transcript_source now holds both a provided-text and an stt row.
  - `[medium]` `[patch]` mint_meeting's ON CONFLICT rewrote started_at, started_at_precision, title and provenance from the augmenting drop while intake guarded only corpus, so a restated startedAt silently shifted the wall clock of every moment whose id the feature preserves. Intake now refuses a startedAt or startedAtPrecision mismatch; title and provenance stay restatable, and a test pins that.
  - `[low]` `[patch]` invalidate_meeting_projection's docstring claimed the worst a racing rebuild could do was project twice; a rebuild re-inserting the state row mid-run actually restores ACTION_NONE and the augmented bundle never projects. Docstring corrected to state the window and name rebuild --meeting as the remedy.
  - `[low]` `[patch]` AUGMENTATION_STAGES' docstring claimed the api and the worker both consult it; only api/ingests.py imports it. Reworded to what is true.
  - `[low]` `[patch]` A test comment claiming extract keeps its checkpoint sat on a uniform stage-map assertion that could not establish it. Made the map explicit and moved the claim onto the updated_at assertion that proves it.
  - `[low]` `[patch]` pull_transcript/CLAUDE.md still described metadata.json as carrying exactly the schema's keys at schemaVersion 1. Reworded to say what the puller emits without claiming it is the schema's complete key list.
  - `[low]` `[patch]` A third-party import sat in the first-party group in test_projections_rebuild.py. Moved.
  - `[low]` `[patch]` _invalid_augmenting_drop's docstring said "the three refusals" while covering four, one of them about the target rather than the new drop. Corrected.

Rejected as factually wrong, verified rather than assumed: the claim that STAGES is unimported in test_ingests.py (it is defined at tests/test_ingests.py:14 and the suite passes), and the claim that _invalidate_augmented_projection's rollback could discard the freshly minted meeting (mint_meeting commits at runner.py:123 before it is called).

## Design Notes

**Why the job row is re-armed instead of a second job created.** `meeting.job_id` and `meeting.source_id` are both UNIQUE (`0002:28-29`) and `job_source_id_live_key` (`0001:18-20`) forbids a second live job per sourceId. A second job could therefore never own the meeting, and giving it one would mean relaxing three constraints that AD-5 and AD-14 rest on. AD-14 already states the intended shape — "re-processing an occurrence is a rerun of its existing job, never a second Meeting row" — and the failed-job re-queue branch at `ingests.py:227-244` is the existing precedent for exactly this move. Re-using the job keeps the meeting id, which is what keeps moment ids, citations, and published artifacts valid.

**Why `augments` is an object keyed by `sourceId`, not a boolean.** The SPEC says a later drop "declares which meeting it augments *rather than colliding on `sourceId`*", so the declaration — not the drop's own identity — is the link. A recording recovered from the recorder's personal OneDrive legitimately carries its own drive-item id (AD-1 admits both forms), so `sourceId` and `augments.sourceId` are allowed to differ; a video-bearing re-pull of the same recap sets them equal. An object leaves room for a future second locator without another version bump.

**Why `schemaVersion` becomes `enum: [1, 2]` rather than staying 1.** All 28 existing drops carry version 1 and must keep validating, but a consumer pinned to version 1 must not silently accept a drop whose `augments` field it will ignore — ignoring it would ingest the recovered recording as a brand-new meeting and orphan every existing citation. `enum: [1, 2]` plus "`augments` implies version 2" gives back-compat in one direction and fail-closed behaviour in the other.

**Why the readiness gate is `evidence_complete()` and not `job.status = 'done'`.** `extract` has no implementation, so `run_job` pauses there with the job still `running` (`runner.py:417-421`) and no job ever reaches `done`. Gating on `done` would make augmentation permanently unreachable. `evidence_complete()` is the same predicate the meetings list already uses for `viewable`.

**Why the puller is out of scope.** `emit-drop.js` names a drop `<date>-<title-slug>-<sha1(sourceId)[0:8]>` and detects write-once with `existsSync` on that path. A video-bearing re-pull has the same sourceId, the same date and the same title, so it resolves to the same directory and returns `{status: 'exists'}` — nothing is emitted and nothing is POSTed. Changing that means changing drop identity itself, which spec-1-8 already carries as a deferred design item. The capstone needs the server-side path working and provable; extending the puller is a second story.

**What is already built.** Moment identity preservation (`ON CONFLICT (meeting_id, identity_key)`), supersede-not-delete, deep-link retirement (`moments.py:136,228`), `meeting.has_recording` refresh (`mint_meeting`'s `ON CONFLICT`), and per-meeting delete-and-reinsert (`projections.project_meeting`) all exist and are tested. This story supplies the missing entry path and the projection invalidation, then proves the whole chain end to end.

## Verification

**Commands:**
- `cd server && uv run pytest tests/test_drop_schema.py tests/test_moments_core.py tests/test_projections_single_writer.py -q` -- expected: all pass; no Docker stores needed.
- `make puller-test` -- expected: the emit-drop suite passes with `emit-drop.js` unmodified, proving version 1 drops still validate against the updated schema.
- `cd server && uv run pytest tests/test_ingests.py tests/test_augmentation.py tests/test_worker_runner.py tests/test_worker_moments.py -q` -- expected: all pass. **Needs the shared Docker Postgres — announce and hold the stores first (AGENTS.md).**
- `cd server && uv run pytest tests/test_projections_rebuild.py tests/test_projections_graph.py tests/test_projections_search.py -q` -- expected: all pass. **Needs Postgres, Neo4j and Meilisearch — same hold.**
- `make test` -- expected: the full server suite passes, with skips only for genuinely unreachable services.

## Auto Run Result

Status: done
Blocking condition: none

**Implemented change.** A recording recovered after an occurrence was ingested transcript-only
now reaches the system. The drop schema gains an optional `augments` declaration at
`schemaVersion: 2` (version 1 drops keep validating; `augments` implies version 2 so a pinned
version-1 consumer fails closed). Intake resolves the declared occurrence and re-arms its
existing job in place rather than raising the sourceId conflict, putting exactly
`AUGMENTATION_STAGES` back to `queued`. The runner detects that the drop now carries a recording
for a meeting recorded as having none, and invalidates the meeting's projection state so the
existing per-meeting delete-and-reinsert re-projects it. Moment identity, screenshot attachment
and deep-link retirement were already built and tested; this story supplied the missing entry
path and the projection invalidation, then proved the chain end to end.

**Files changed.**
- `docs/source-drop.schema.json` -- `schemaVersion` enum [1, 2], optional closed `augments` object, `allOf` rule making `augments` imply version 2, `$id`/title/description updated.
- `server/meetingminer/domain/jobs.py` -- `AUGMENTATION_STAGES`, the stages an augmenting drop re-runs, in `STAGE_NAMES` order.
- `server/meetingminer/api/ingests.py` -- the augmentation branch, its five refusal paths, and the in-place re-arm returning 200.
- `server/meetingminer/domain/drops.py` -- `_parse_started_at` promoted to `parse_started_at` so intake parses the declared instant exactly as the pipeline does.
- `server/meetingminer/projections/__init__.py` -- `invalidate_meeting_projection`, exported.
- `server/meetingminer/pipeline/runner.py` -- reads the persisted `has_recording` before `mint_meeting` overwrites it; invalidates the projection on the augmenting transition.
- `server/tests/test_drop_schema.py`, `test_ingests.py`, `test_augmentation.py` (new), `test_projections_rebuild.py` -- the schema cases, the intake matrix, the end-to-end acceptance evidence, and the scoped re-projection proof.
- `pull_transcript/test/emit-drop.test.js` -- back-compat across the black-box seam, with `emit-drop.js` unmodified.
- `pull_transcript/CLAUDE.md`, `ARCHITECTURE-SPINE.md` (AD-1, AD-14), `deferred-work.md` -- documentation.

**Review findings.** 9 patched (1 high, 2 medium, 6 low), 9 deferred (4 medium, 5 low), 11
rejected. Follow-up review recommended: **true** (a high-severity finding was patched).
Patched counts by severity: high 1, medium 2, low 6; score 3x2 + 1x6 = 12, and the high alone
already sets the flag.

**Verification performed.** All commands run in the worktree after the patch pass:
- `pytest tests/test_drop_schema.py tests/test_moments_core.py tests/test_projections_single_writer.py -q` -- 66 passed.
- `make puller-test` -- 74 pass, 0 fail, with `pull_transcript/emit-drop.js` byte-identical to baseline (verified by empty diff). This is the back-compat proof: version 1 drops still validate.
- `pytest tests/test_ingests.py tests/test_augmentation.py tests/test_worker_runner.py tests/test_worker_moments.py tests/test_drop_schema.py tests/test_projections_rebuild.py tests/test_projections_graph.py tests/test_projections_search.py -q` -- 202 passed, 1 failed (the pre-existing failure below).
- `make test` -- 727 passed, 2 failed.
- Mutation check on the new end-to-end test: disabling the runner's `invalidate_meeting_projection` call makes `test_augmentation_replaces_the_meetings_documents_in_both_stores` fail, so it witnesses the chain rather than restating it. The runner was restored immediately afterwards.

**Two failures are pre-existing and inherited from `main`**, not caused by this story. Verified by
checking out `6ff87a4` over `server/` and `docs/` -- none of this story's code present -- and
re-running: both still fail.
- `tests/test_ocr_adapter.py::test_parse_tsv_without_page_dimensions_is_a_named_error`
- `tests/test_worker_runner.py::test_empty_and_populated_stage_logs_carry_the_same_fields` -- asserts `stage.screens.captured.directory is None` on a zero-capture run; the stage now reports the directory.

**Residual risks.** The nine deferred items above, of which four are medium: the
filename-only transcript guard, the un-invalidated projection on the reverse
(recording-to-transcript-only) path, the unlocked read-then-re-arm sequence, and a meeting
reading as non-viewable for the length of its augmented run. Separately, the puller cannot emit
an augmenting drop at all, so this path is exercised only by hand-authored or fixture-built
drops -- a deliberate scope-out recorded in `deferred-work.md`.
