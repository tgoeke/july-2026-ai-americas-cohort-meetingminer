---
title: 'Story 1.13: Drops Carry the Participant Graph'
type: 'feature'
created: '2026-08-19'
status: 'done'
baseline_revision: '11d9cc7b104a3163e9792b3368ed3d4dfcb77d26'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/pull_transcript/CLAUDE.md'
warnings: ['oversized', 'multiple-goals']
deferred: []
---

<intent-contract>

## Intent

**Problem:** `emit-drop.js` omits `metadata.participants`, so the pipeline's mail-keyed
identity path (built and tested in story 1.5) never runs against real data — every person is
keyed on how their name was typed. The bridge cannot be built alone: a drop whose only new
content is the participant graph has **no intake door** (a declared augmentation is refused
without `recording.mp4` and refused when the target already has a recording; the plain
re-queue path only applies when every job for the `sourceId` has failed), and a re-emitted
drop collides with the finalized one on its directory name.

**Approach:** Three coupled changes. (1) `emit-drop.js` maps the occurrence's
`<stem> org chart.json` into `metadata.participants`. (2) Intake widens the `augments` door
from "a recovered recording" to "any evidence this occurrence lacks", keeping one intake door
(AD-14) rather than adding a participant-import bypass. (3) `emit-drop.js` grows an opt-in
re-emit path that writes a `schemaVersion: 2` augmenting drop under a sequence-numbered
sibling directory, so write-once holds and emit order stays recoverable from the drops folder.

## Boundaries & Constraints

**Always:**
- The puller stays a black box: `emit-drop.js` imports no server code, reads no `config.yaml`,
  no `.env`, and never loads the drop JSON Schema at emit time.
- A finalized drop is never overwritten, re-copied into, deleted, or renamed. The 28 existing
  drop directories keep their current names.
- The re-emit discriminator must keep **emit order recoverable from the drops folder alone**
  (reconstruction replays a meeting's drops in emit order). A sequence number or timestamp
  qualifies; a content hash or random suffix does not.
- Default `emit-drop` behaviour is unchanged: without the new flag an existing target is still
  reported `exists` and nothing is written.
- Widening the augmentation door must not weaken the Meeting-preservation checks already in
  `_check_meeting_replacement`: corpus, `startedAt`, `startedAtPrecision` and every transcript
  the target's drop carries are still pinned, and a recorded meeting may still not be
  downgraded to transcript-only.
- Both suites keep validating emitted metadata against `docs/source-drop.schema.json`
  independently (AD-1).

**Block If:**
- Satisfying the story would require renaming, rewriting or deleting an already-finalized drop.
- Satisfying the story would require a second intake path beside `POST /ingests` (AD-14).

**Never:**
- No Microsoft Graph call, on either side. `mail` comes from the chart the puller already wrote.
- No change to `align`'s participant derivation, `speakers.identity_key_for`, migration 0005,
  or the `participant` / `meeting_participant` schema — that half is already built.
- No change to the SPEC kernel; this is an AD-14 amendment.
- Do not union the drop graph with transcript labels — the graph-as-roster-authority reading is
  story 1.5's shipped behaviour and re-deciding it is out of scope.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Chart present | `<stem> org chart.json` with `people[]` | `metadata.participants` = one object per person, `name` renamed to `displayName`, every other field verbatim (`mail`, `title`, `department`, `deptCode`, `lineOfBusiness`, `office`, `org`, `guest`, `unresolved`, `managerChain`, `foundIn`, `invite`, `response`, `spokeTurns`, `spokeWords`) | No error expected |
| No chart | no `org chart.json` beside the occurrence | `participants` key omitted; drop is byte-identical to today's | No error expected |
| Unusable chart | unreadable / not JSON / `people` absent or not an array / zero usable rows | `participants` key omitted, named warning on stderr | Never a `SkipError` — the transcript is the occurrence's evidence, the chart is auxiliary |
| Nameless row | one `people[]` entry with blank/absent `name` | that row is dropped, named warning on stderr, the rest map | One bad row must not retire an occurrence |
| Re-emit, first drop absent | `--re-emit`, no existing target | plain version-1 drop at the base name, no `augments` | You cannot augment an occurrence never ingested |
| Re-emit, drop brings something new | `--re-emit`, base target exists, this pass would bring the newest drop a non-empty participant graph or a recording it lacks | new drop at `<base>-002` (then `-003`, …), `schemaVersion: 2`, `augments.sourceId` = own `sourceId` | Sequence exhausted at `-999` → named error, nothing written; a VTT/TXT-only change is `current` |
| Re-emit, nothing new | `--re-emit`, newest drop already carries a participant graph and every evidence file this pass has — including when the chart was re-resolved and its rows now differ | status `current`, nothing written | No error expected |
| Empty participants array | a drop or a target drop carrying `participants: []` | `[]` is never emitted, and counts as no graph on both sides of the intake comparison | No error expected |
| Intake, participants-only augmenting drop | target ingested, evidence stages settled, target's drop carries no `participants` | 200, existing job re-armed, only `align` + `moments` re-queued | — |
| Intake, augmenting drop adds nothing | target already has a recording and its drop already carries participants | 409 `augment-adds-nothing` naming both halves, with `jobId` | — |
| Intake, recording-recovery augmenting drop | target transcript-only, drop carries `recording.mp4` | 200, video stages + `align` + `moments` re-queued (story 1.12, unchanged) | — |

</intent-contract>

## Code Map

- `pull_transcript/emit-drop.js` -- the whole puller change. `planDrop()` (metadata assembly,
  the `participants`-omitted comment at the `metadata` literal), `emitDrop()` (write-once
  target/staging/rename), `dropName()`, `parseArgs()`/`USAGE`/`VALUE_FLAGS`, `main()`
  (per-occurrence loop, `counts`, summary line). Occurrence files are matched on the stem
  `"<M.D.YY> <Title>"` via `EVIDENCE_MAP`; the chart is the same stem plus `" org chart.json"`.
- `pull_transcript/test/emit-drop.test.js` -- `node --test` suite; `makeOccurrence()` builds
  fixture occurrences, `assertValid()` checks metadata against `docs/source-drop.schema.json`
  under `SCHEMA_TEST` (skipped only when the schema file is absent).
- `server/meetingminer/api/ingests.py` -- `_check_target_is_augmentable` (:258, the
  `augment-target-has-recording` 409 to remove), `_check_augmenting_drop` (:287, the
  "must carry recording.mp4" refusal to replace), `_check_meeting_replacement` (:317, keep,
  now receiving the target's real `has_recording`), `_rearm_job` (:425), `_accept_augmenting_drop`
  (:447), module docstring (:1-19).
- `server/meetingminer/domain/jobs.py` -- `AUGMENTATION_STAGES` (:53), `evidence_complete()` (:67).
  Add the narrower participants-only stage set beside them.
- `server/meetingminer/pipeline/runner.py` -- `_invalidate_augmented_projection` (:220) and its
  only call site (:436, gated on `drop.has_recording and had_recording is False`). Without
  invalidation `projection_action` answers `ACTION_NONE` and the meeting never re-projects.
- `server/meetingminer/domain/drops.py` -- `read_metadata()`, `RECORDING_FILENAME`; reuse for
  reading the target drop's metadata. **Read-only.**
- `server/meetingminer/pipeline/stages/align.py` -- `_graph_roster()` (:274) reads
  `metadata.participants`, keys identity via `speakers.identity_key_for(display, mail)` (:313),
  `_resolve_participants()` (:371) resolves through `participant_alias` first (AD-5 — this is
  what makes AC "merges survive" already true), `_meeting_participant_rows()` (:423) stores the
  graph entry whole in `meeting_participant.source`. **Read-only — already built, story 1.5.**
- `server/tests/test_augmentation.py` -- `_augmenting_metadata()` (:49) and the augmentation
  tests to extend; `server/tests/test_ingests.py` -- intake refusal cases.
- `docs/source-drop.schema.json` -- `augments` description narrates "a recovered recording";
  `participants` items are `additionalProperties: true`, so the mapped fields need no schema
  change.
- **Evidence, read-only:** real charts live at
  `/Volumes/nvmepool/mm_current/pull_transcript/<Title>/<M.D.YY>/<stem> org chart.json`
  (28 files, 225 person-rows, 222 with `mail`, 208 with `managerChain`, 3 `unresolved: true`
  with `org: "Unknown"`, `guest` false on all 225). Verified shape: top-level `generatedAt`,
  `meeting`, `attendeeSources`, `orgSource`, `people[]`, `notes[]`.

## Tasks & Acceptance

**Execution:**
- [x] `pull_transcript/emit-drop.js` -- add `ORG_CHART_SUFFIX = ' org chart.json'`, a pure
  `mapParticipants(chart)` and a `readParticipantGraph(dir, stem)` that returns `null` on any
  unusable chart; set `metadata.participants` from it in `planDrop()` and delete the stale
  "no participants key" comment -- AC1.
- [x] `pull_transcript/emit-drop.js` -- add `--re-emit` (`opts.reEmit`): `nextDropName()` scans the
  drops root for `^<base>(-(\d{3}))?$`, `emitDrop()` returns `current` when the newest existing
  drop already carries the same participant graph and recording presence, otherwise
  emits at the next sequence with `schemaVersion: 2` and `augments: { sourceId }`; wire it
  through `parseArgs`, `USAGE`, `main()`'s counts and summary -- AC3, AC4.
- [x] `server/meetingminer/domain/jobs.py` -- add `PARTICIPANT_AUGMENTATION_STAGES = ('align',
  'moments')` beside `AUGMENTATION_STAGES`, documented as the stage set a drop that adds no
  recording needs -- avoids re-running frames/ocr/screens over an unchanged recording.
- [x] `server/meetingminer/api/ingests.py` -- replace the recording-specific augmentation gate with
  "brings evidence this occurrence lacks" (a recording the target has not got, or a
  `participants` array its drop has not got), remove the unconditional
  `augment-target-has-recording` 409, pass the target's real `has_recording` into
  `_check_meeting_replacement`, and re-arm the narrower stage set when no recording is added;
  update the module docstring -- AC-prerequisite.
- [x] `server/meetingminer/pipeline/runner.py` -- invalidate the meeting projection for **any**
  augmenting drop, not only one that first supplies a recording -- otherwise
  `projection_action` answers `ACTION_NONE` and the new participants never reach the stores.
- [x] `docs/source-drop.schema.json` -- widen the `augments` description from "a recovered
  recording" to "evidence the occurrence lacks"; note that `participants` is what the puller
  maps from its per-occurrence participant graph.
- [x] `pull_transcript/test/emit-drop.test.js` -- cover every row of the I/O matrix's puller half:
  chart mapped, chart absent, chart unusable, nameless row, re-emit sequencing and its
  `schemaVersion: 2` + `augments` shape, `current`, default-unchanged behaviour, and schema
  validation of every emitted metadata.
- [x] `server/tests/test_augmentation.py` -- cover the intake half: a participants-only augmenting
  drop is accepted and re-arms only `align`/`moments`; an augmenting drop that adds nothing is
  refused; the recording-recovery path still behaves as story 1.12 specified.
- [x] `pull_transcript/emit-drop.js` -- after a `--re-emit` pass, report how many occurrence
  prefixes in the drops root have a newest drop carrying **no** `participants` key, so a
  half-migrated corpus is visible rather than silent. Recoverable from the drops folder alone,
  the same property the sequence discriminator preserves.
- [x] `pull_transcript/CLAUDE.md` -- correct the "participants is deliberately omitted" and "this
  tool never emits `augments`" paragraphs; document `--re-emit` and the sequence discriminator.
- [x] `_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md`
  -- amend AD-14's augmentation clause and AD-1's closing "the puller does not emit augmenting
  drops" sentence.
- [x] `_bmad-output/implementation-artifacts/deferred-work.md` -- close the story-1.12 deferral this
  story implements.
- [x] `_bmad-output/implementation-artifacts/sprint-status.yaml` -- record story 1.13.

**Acceptance Criteria:**
- Given an occurrence with a resolved `org chart.json`, when `emit-drop` runs, then
  `metadata.json` carries a `participants` array whose entries carry `displayName` plus `mail`,
  title, department and reporting chain where the chart row has them, and the emitted metadata
  validates against `docs/source-drop.schema.json`.
- Given a drop carrying participants, when it ingests, then participants dedupe across meetings
  by `mail`, fall back to normalized display name only where the graph supplies none, and an
  `unresolved: true` / `org: "Unknown"` row is stored as external without consulting `guest`.
- Given a drop that brings evidence the meeting lacks but carries no recording, when it is
  POSTed to `/ingests`, then intake accepts it and re-arms the occurrence's existing job.
- Given the 28 already-finalized drops, when the puller is asked to bring them up to contract,
  then it emits a *new* sibling drop per occurrence — the finalized one untouched — under a
  name from which emit order is recoverable by lexical sort within the occurrence's prefix.
- Given a `--re-emit` pass that leaves some occurrences un-re-emitted, when the pass finishes,
  then it names the count of drop prefixes whose newest drop still carries no `participants`
  key, so a partial migration is reported rather than silent.
- Given a participant merged through the API before this change, when re-ingest runs, then
  `participant_alias` still resolves the identity, so the merge survives the move to mail-keyed
  identity.

## Spec Change Log

- **2026-08-19, planner review of the implementation.** Two intent-contract corrections, both
  found by reading the delivered code rather than from new information:
  - *The adds-nothing refusal is `409 augment-adds-nothing`, not `400 invalid-augmenting-drop`.*
    The matrix's 400 would have put one RFC 9457 problem type under two statuses. Nothing about
    such a drop is invalid — the identical drop is accepted against an occurrence that still
    lacks the evidence — so what refuses it is the target's current state, which is what 409
    says, and it is the status of the `augment-target-has-recording` refusal it supersedes.
    Known-bad state avoided: a client switching on `type` seeing two meanings for one slug.
  - *`--re-emit` emits only what intake will accept, not on any difference.* A re-resolved chart
    is a difference but not evidence the occurrence lacks, so intake refuses it — and the puller
    would already have finalized that drop write-once and POSTed it, read the 409 as "already
    ingested", and on the next pass compared against that never-ingested drop and reported the
    occurrence migrated. Known-bad state avoided: the silent name-keyed/mail-keyed split this
    spec's Design Notes exist to prevent, reached by a second route. Also pinned: `[]` counts as
    no graph on both sides, so it neither adds participants nor blocks the drop that finally
    supplies them.
  - **KEEP:** the sequence discriminator and its `current` short-circuit; the narrower
    `PARTICIPANT_AUGMENTATION_STAGES` re-arm; the omit-rather-than-emit-`[]` rule in the puller;
    the migration-progress report on every `--re-emit` pass.

## Design Notes

- **Why a sequence number and not a timestamp.** Both keep emit order recoverable. A timestamp
  makes every `--re-emit` pass write 28 new drops; a sequence plus the `current` short-circuit
  makes a repeat pass a no-op, which is the property the existing `--all` idempotence test
  asserts. Zero-padded to three digits so lexical order is emit order.
- **Why the base name keeps no suffix.** The 28 finalized drops must not be renamed, so
  sequence 1 *is* the existing unsuffixed name and the discriminator starts at `-002`.
- **Why the re-emitted drop always declares `augments`.** A re-emit exists only because the
  occurrence was already emitted, and therefore probably already ingested; without the
  declaration intake would answer 409 on the live job. Declaring it with the drop's own
  `sourceId` is legal (the schema allows the two ids to differ but does not require it) and
  routes to the re-arm path that preserves the meeting id.
- **An unusable chart omits the key rather than emitting `[]`.** `align` reads an empty array as
  "the source looked and found nobody" and does *not* fall back to transcript labels, so
  emitting `[]` for a broken chart would silently strip a meeting of its participants.
- **A transcript speaker absent from the chart becomes `unresolved`.** `align` treats the graph
  as the roster authority rather than unioning it with transcript labels (story 1.5's shipped
  reading). The charts record `transcript speakers (N)` in `attendeeSources`, so the graph
  covers them in this corpus — but this is the behaviour change most worth a reviewer's eye.
- **Partial re-emit splits one human across two identity keys.** `--re-emit` is opt-in per
  occurrence, so the same person can be `mail:avery.reed@corp.com` in a re-emitted meeting
  and `name:avery reed` in one left alone. `_resolve_participants` reads `participant_alias`
  by `alias_key` and nothing writes an alias automatically, so those are two unrelated
  `participant` rows and the participants -> meetings -> topics -> moments traversal returns
  half that person's meetings. The mitigation here is operational, not structural: the migration
  is one `--all --re-emit` pass over 28 occurrences, and the pass reports how many prefixes are
  still on the old contract so a half-migrated corpus is visible. Rows whose chart carries no
  `mail` stay name-keyed everywhere, which is consistent. The structural fix — `align` writing a
  `name:` -> mail-keyed-participant alias when the graph first supplies a mail for a name it has
  already seen — is deliberately NOT taken: AD-5 gives `participant_alias` to the API, and a
  worker that writes aliases is an AD-5 amendment rather than an implementation choice. Recorded
  in `deferred-work.md` as the real fix if identity ever has to migrate incrementally.
- **Field rename.** The chart writes `name`; the drop schema requires `displayName`. Everything
  else passes through verbatim, which is what puts `managerChain` into
  `meeting_participant.source` without a new column.

## Verification

**Commands:**
- `make puller-test` -- expected: the full `node --test` suite green, no skipped schema cases
  (the schema file is present in this checkout).
- `pytest server/tests/test_augmentation.py server/tests/test_ingests.py server/tests/test_drop_schema.py`
  -- expected: green. **Store-backed — hold the Docker stores one agent at a time (AGENTS.md).**
- `node pull_transcript/emit-drop.js --dry-run "<a real occurrence dir under /Volumes/nvmepool/mm_current/pull_transcript>"`
  -- expected: the plan prints a participant count matching that chart's `people[]` length.

**Results, 2026-08-19:**
- `make test` — 742 passed, 0 failed, 1 warning (pre-existing starlette/httpx deprecation),
  248s, followed by a clean web build. `make test` also runs `puller-test` and `web-test`.
- `make puller-test` — 98 pass, 0 fail, 0 skipped (the schema cases ran, not skipped).
- `make web-test` — 38 pass across 3 files.
- Corpus sweep through `planDrop` + ajv over the live archive at
  `/Volumes/nvmepool/mm_current/pull_transcript`: **29** occurrences (the corpus gained one
  since the 2026-08-18 measurement of 28), 29 valid against the schema, 0 invalid, 29 carrying
  participants, 233 person rows, 230 with `mail`, 216 with `managerChain`, 3 `unresolved: true`,
  0 `guest: true`. Rates match `corpus-facts.md` §4.
- `--dry-run` on a real occurrence: `people 7`, matching that chart's `people[]` length.
- `--dry-run --re-emit` against the live drops root: targets `…-002`, `schemaVersion 2` with
  `augments`, and `participants: 28 of 28 drop prefixes still carry no participants key`. The
  drops root still holds 28 directories; nothing was written.

**Manual checks (if no CLI):**
- The 28 finalized drop directories under the drops root are unchanged in name and mtime after
  any `--re-emit` pass.

### Review Findings

- [x] [Review][Patch] Restrict re-emit to recording and a non-empty participant graph [pull_transcript/emit-drop.js:503] — **Decision, 2026-08-19:** a newly recovered provided transcript is not independently augmentable evidence. VTT/TXT-only changes remain `current`; tests cover the no-write path.

- [x] [Review][Patch] Reject a re-emit plan that would shed a target transcript before finalizing it [pull_transcript/emit-drop.js:503] — Candidate evidence is now checked against the newest target before write; regression coverage proves no sibling is created.

- [x] [Review][Patch] Make failed or refused re-emit POSTs recoverable rather than silently current [pull_transcript/emit-drop.js:665] — Only duplicate-source is benign; other 409 responses fail visibly and name the exact finalized sibling for direct re-POST.

- [x] [Review][Patch] Preserve an existing participant graph during a recording-recovery augmentation [server/meetingminer/api/ingests.py:467] — Intake now refuses a recovery that sheds a target graph; focused contract coverage passes.

- [x] [Review][Patch] Do not accept a different recording as a participants-only augmentation [server/meetingminer/api/ingests.py:358] — Intake compares byte digests when the target already has video and refuses a changed recording on the narrow path.

- [x] [Review][Patch] Serialize augmenting re-arms for an occurrence [server/meetingminer/api/ingests.py:257] — The target job is row-locked before the evidence-complete check and re-arm.

- [x] [Review][Patch] Count `participants: []` as still unmigrated in the re-emit summary [pull_transcript/emit-drop.js:543] — The summary uses the same non-empty graph predicate; regression coverage pins the count.

- [x] [Review][Patch] Cover the chart read-error degradation path [pull_transcript/test/emit-drop.test.js:1348] — A directory-at-chart-path fixture confirms warning plus graph-less emission.

## Suggested Review Order

**Re-emit safety**

- Plan only augmentations the intake door can accept.
  [emit-drop.js:507](../../../pull_transcript/emit-drop.js#L507)

- Surface a refused handoff and name its exact retry target.
  [emit-drop.js:663](../../../pull_transcript/emit-drop.js#L663)

**Intake preservation and concurrency**

- Lock the target before checking and re-arming its evidence.
  [ingests.py:258](../../../server/meetingminer/api/ingests.py#L258)

- Preserve graph, transcripts, and video bytes across replacement drops.
  [ingests.py:475](../../../server/meetingminer/api/ingests.py#L475)

**Regression coverage**

- Exercise failure, no-op, and evidence-preservation boundary cases.
  [emit-drop.test.js:663](../../../pull_transcript/test/emit-drop.test.js#L663)

- Pin the API preservation guard against graph and recording loss.
  [test_ingests.py:945](../../../server/tests/test_ingests.py#L945)
