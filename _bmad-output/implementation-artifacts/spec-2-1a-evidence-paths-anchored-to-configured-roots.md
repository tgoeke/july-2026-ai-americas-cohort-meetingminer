---
title: 'Story 2.1a: Evidence Paths Anchored to Configured Roots'
type: 'bugfix'
created: '2026-08-19'
status: 'done'
baseline_revision: 'fc5c656758f9636446bdb25d8d896d676554bb04'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/specs/spec-meetingminer/storage-layout.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-2-1-media-streaming-replay-foundation.md'
  - '{project-root}/_bmad-output/specs/spec-meetingminer/glossary.md'
warnings:
  - 'SUPERSEDES `spec-2-1-recording-under-the-content-root.md`. That story proposed copying the recording under the content root; the copy is not being done and the copy-versus-hard-link question it escalated no longer arises. Do not build it. The file is absent from `main` and survives only on the stale `story/2-1` branch — delete the branch rather than merging it.'
  - 'UNBLOCKED 2026-08-19: story 2.1 passed review and is merged. `server/meetingminer/api/media.py` and `server/tests/test_api_media.py` are on `main` (commits 18e8ae1, 7bbbd36; merged head eff0a75). Start from `main`, not from a story branch. Do not alter the media HTTP contract while doing this work (build-prompt-story-2-1-2026-08-19.md).'
deferred:
  - summary: >-
      Replay 404s for a meeting between claim and probe, where before 2.1a it streamed.
    evidence: |-
      `mint_meeting` (pipeline/runner.py:104) creates the meeting at claim time on purpose, so
      transcript-only drops still get one. `probe` writes `meeting_media.drop_relative_path`
      later. Between the two, `GET /media/recordings/{id}` finds `has_recording = true` with a
      NULL path and returns 404 `media-not-found`; pre-2.1a it composed `job.drop_path` with
      `RECORDING_FILENAME`, both available at claim time, and streamed. The frozen `Never` list
      says the media route keeps "its problem responses", and the I/O matrix has no row for this
      state. Not patched deliberately: the only way back to the old behaviour is re-composing the
      path from the filename constant, which is the thing this story exists to delete. The guard
      itself is now tested; what needs a human is whether the window is acceptable.
    location: >-
      server/meetingminer/api/media.py (_MEETING_RECORDING) and pipeline/runner.py:104
    severity: medium
  - summary: >-
      The backfill hashes the whole recording corpus inside one long-lived write transaction.
    evidence: |-
      `backfill.main` opens one connection and `backfill_drop_paths` computes `sha256_and_size`
      over every recording inside it, holding row locks on `job`, `transcript_source` and
      `meeting_media` while reading the disk end to end (measured corpus: 19.5 GB across 85 mp4s).
      There is no per-job commit and no progress output, and `--dry-run` pays the same cost before
      rolling back. Correct but operationally unpleasant on a real corpus.
    location: >-
      server/meetingminer/backfill.py
    severity: low
  - summary: >-
      Nothing forbids MM_DROPS_ROOT and MM_CONTENT_ROOT from being equal or nested.
    evidence: |-
      `require_drops_root` checks set/absolute/exists/is-a-directory but never that the two roots
      are distinct and non-nested. Setting them equal puts pipeline-written material inside
      write-once drop storage, which AD-13 forbids, and makes `drop_relative_path` and
      `relative_path` ambiguous for the same file.
    location: >-
      server/meetingminer/config.py
    severity: medium
  - summary: >-
      backfill.py duplicates the CLI bootstrap that projections/cli.py already has.
    evidence: |-
      `_repository_config_path`, `_load_cli_config`, the psycopg connect block and the whole error
      ladder are copied verbatim from projections/cli.py, differing only in `parents[3]` ->
      `parents[2]`. A shared CLI bootstrap is the obvious fix and is out of this story's boundary.
    location: >-
      server/meetingminer/backfill.py
    severity: low
  - summary: >-
      transcribe.py keeps `sha256_of` as a second name for the shared `sha256_and_size`.
    evidence: |-
      The alias was kept so existing callers read unchanged, which leaves two names for the one
      function this story consolidated precisely because a second spelling would be a second
      answer. Renaming the call sites and dropping the alias is trivial but touches a stage this
      story otherwise does not own.
    location: >-
      server/meetingminer/pipeline/stages/transcribe.py
    severity: low
  - summary: >-
      The puller's operator documentation does not mention that drops must live under MM_DROPS_ROOT.
    evidence: |-
      pull_transcript/CLAUDE.md documents `POST /ingests {"dropPath": "<absolute>"}` with no note
      that intake now refuses a path outside the configured drops root. The wire contract is
      genuinely unchanged, so the puller code needs nothing; the operator configuring
      emit-drop.js's output directory is the one who will hit the new 400.
    location: >-
      pull_transcript/CLAUDE.md
    severity: medium
  - summary: >-
      The renamed jobs-API field in the generated TS client was hand-edited and nothing verifies it.
    evidence: |-
      `GET /jobs/{jobId}` returns `dropRelativePath` instead of `dropPath`; web/src/client/types.gen.ts
      was edited by hand because `pnpm run client` needs a live api. `getJob` has no caller in the
      web app, so neither the web suite nor the type checker would catch a wrong edit in either
      direction. Regenerate the client against a running api to confirm.
    location: >-
      web/src/client/types.gen.ts
    severity: medium
---

<intent-contract>

## Intent

**Problem:** `job.drop_path` is an absolute filesystem path (`0001_jobs.sql`; intake rejects a
relative one at `api/ingests.py:131`), and it is the anchor for *every* piece of arriving evidence —
not just the recording. Three readers resolve through it long after ingest finishes: provided
transcripts store no segments and are re-parsed from `drop_relative_path` on every stage run
(migration `0005` says so in its own comment); the augmentation door re-reads an ingested
occurrence's `metadata.json` (`_target_drop_has_participant_graph`, `ingests.py:312`); and story
2.1's replay route composes `job.drop_path` with the `RECORDING_FILENAME` constant from
`domain/drops.py`. Moving the drops folder therefore breaks replay, transcript re-parse, and the
augmentation comparison together, while frames and screenshots — anchored to `MM_CONTENT_ROOT` —
keep working. Separately, the recording is the one evidence file with no row of its own: half its
served path is data and half is a Python constant, and it carries no `sha256`, so a substituted
recording is undetectable where a substituted transcript is not.

**Approach:** Give the drops root the same treatment the content root already has. Configure it as
`MM_DROPS_ROOT`, store each job's drop location relative to it, record the recording on
`meeting_media` with its drop-relative path and checksum, and make every reader resolve through the
configured root instead of through a stored absolute path.

## Boundaries & Constraints

**Always:**
- The recording stays in its drop. It is arrived material, the drop is permanent by AD-1, and it is
  not copied or linked anywhere (`storage-layout.md` §4).
- The drop directory stays read-only — nothing is written, renamed, or deleted inside it (AD-13).
- A stored path is relative to exactly one configured root and never absolute
  (`storage-layout.md` §4). No absolute path is written to the database or leaves the server.
- Resolution goes through a containment guard that refuses a path escaping its root by `..` or by a
  symlink, matching the treatment `assert_private_meeting_subdir` already gives the content root.
- `MM_DROPS_ROOT` follows `MM_CONTENT_ROOT`'s existing contract in `config.py`: absolute, `~`
  expanded by the loader only, and a named startup failure rather than a first-use one.
- The recording's row records its drop-relative path and its `sha256`. `meeting_media.size_bytes`
  already holds the byte size from ffprobe — reuse it rather than adding a second size column, and
  fail the stage if the two disagree.

**Block If:**
- The drops root is judged to be a clearable landing zone rather than permanent, backed-up storage.
  The whole design rests on the drop outliving ingest (`storage-layout.md` §1); if drops are
  disposable, the recording has to be copied out and this story is the wrong shape.

**Never:**
- No change to the intake wire contract. `POST /ingests` keeps accepting an absolute `dropPath`, so
  the puller is untouched; only what the server stores changes.
- No change to how media is served over HTTP. `GET /media/recordings/{meetingId}` keeps its URL,
  its range behaviour, and its problem responses; story 2.1's route tests survive apart from how
  their fixture seeds the drop.
- No transcoding, re-encoding, or modification of any evidence bytes.
- No change to frame or screenshot paths, which already conform.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Intake of a drop under the root | Absolute `dropPath` inside `MM_DROPS_ROOT` | Job stores the drop-relative path; behaviour otherwise unchanged | No error expected |
| Intake of a drop outside the root | Absolute `dropPath` not under `MM_DROPS_ROOT` | Refused before a job row exists, naming both the path and the configured root | 400 `invalid-drop-path`, RFC 9457 |
| `MM_DROPS_ROOT` unset | API or worker starts | Named startup failure, the way `require_content_root` fails | `ConfigError` at startup |
| First ingest with video | Drop holds `recording.mp4` | `meeting_media` records the drop-relative path, `sha256` and `byte_size`; `byte_size` matches the file | No error expected |
| Transcript-only ingest | No recording in the drop | No path, no checksum recorded; existing transcript-only behaviour unchanged | No error expected |
| Late-arriving video | Meeting ingested transcript-only, recovered recording augments it | Recorded exactly as a first-pass one; existing moments and citations unchanged | No error expected |
| Stage rerun, unchanged file | Recording present, checksum matches | Row stands, no rewrite | No error expected |
| Stage rerun, changed file | Recording present at the same recorded path, checksum differs | Existing provenance remains intact | Stage failure: write-once arrived evidence was substituted |
| Drops root relocated | Both roots moved, `MM_DROPS_ROOT` updated | Replay, transcript re-parse, and the augmentation door all keep working — this is the regression the story exists to prevent | No error expected |
| Legacy rows | Existing jobs hold absolute `drop_path` | Backfilled to relative when under the configured root; any row that is not is reported by path, never silently dropped | Backfill exits non-zero |
| Path escaping the root | Stored path containing `..`, or a symlinked drop directory | Refused at resolution | Stage/route failure, not traversal |
| Symlinked evidence inside a valid drop | `recording.mp4`, `transcript.vtt`, `transcript.txt` or `metadata.json` is a symlink | Refused at intake before a job row exists — today it passes (`is_file()` follows links), reports `has_recording=true`, then 404s at replay (spine AD-1) | 400 `symlinked-evidence`, RFC 9457 |
| Replay, no recording | Transcript-only meeting | The existing `media-no-recording` 404 is unchanged | RFC 9457 |

</intent-contract>

## Code Map

- `server/meetingminer/config.py:504-640` — `mm_content_root` and `require_content_root` are the
  shape to copy for `MM_DROPS_ROOT`: absolute check, `~` expansion, resolve, and a named
  `ConfigError`. Add the drops root beside it rather than inventing a second config mechanism.
- `server/meetingminer/migrations/0008_*.sql` — **new** (0007 is the highest applied): add `drop_relative_path` to `job`, and
  `drop_relative_path` plus `sha256` to `meeting_media`. Follow the commentary style of
  `0005_transcripts_participants.sql:18-40`, which already explains the two anchors; this migration
  makes that rule uniform instead of transcript-only.
- `server/meetingminer/migrations/0002_meetings_media_frames.sql:48-71` — `meeting_media` today:
  ffprobe facts, one row per meeting keyed by `meeting_id`, upserted on rerun. Right cardinality
  already; `size_bytes` is the existing byte size.
- `server/meetingminer/api/ingests.py:131` `_validate_drop_path` — keeps requiring an absolute path
  on the wire, and gains the containment check against `MM_DROPS_ROOT` plus the conversion to
  relative. This is the single place the conversion should happen.
- `server/meetingminer/api/ingests.py:259,312,537,560` — the augmentation door and the re-queue
  path read and write `j.drop_path`. Each becomes a resolve-from-root call.
- `server/meetingminer/pipeline/runner.py:52,80,315,418` — `ClaimedJob.drop_path` and
  `read_drop(Path(job.drop_path))`. The claim returns the relative path; the runner resolves it once
  against the configured root and the stages below are unaffected.
- `server/meetingminer/pipeline/stages/probe.py` — already opens the recording for ffprobe; the
  natural place to compute `sha256` and write the row. Confirm rather than assume: if `frames` is
  the first true read, record it where the file is first opened.
- `server/meetingminer/pipeline/outputs.py:32-56` `assert_private_meeting_subdir` — the containment
  and symlink guard to mirror for drops-root resolution. A drop path needs the equivalent, not a
  bypass.
- `server/meetingminer/api/media.py:335-372` (on `main`) — `_MEETING_RECORDING` and
  `get_recording` compose `job.drop_path` with the filename constant. They read the recorded
  `meeting_media` path and resolve it against the drops root instead.
- `server/meetingminer/domain/drops.py:26` `RECORDING_FILENAME` — stays the canonical name a drop's
  *producer* writes and a reader looks for; it stops being half of a served path.
- `server/tests/test_api_media.py` (on `main`, 72 tests passing) — the `recorded_meeting` fixture seeds a
  drop; it seeds the recorded path instead. Keep every status-code, range, and header assertion.
- `server/tests/conftest.py:269` `content_root`, `:277` `synthetic_recording` — existing fixtures; a
  `drops_root` fixture joins them.

## Tasks & Acceptance

**Execution:**
- `server/meetingminer/config.py` — add `MM_DROPS_ROOT` with `require_drops_root`, mirroring the
  content-root contract — one config mechanism, two roots.
- `server/meetingminer/migrations/0008_*.sql` — add `job.drop_relative_path`, and
  `meeting_media.drop_relative_path` and `.sha256`, nullable, with commentary naming which root each
  is anchored to — transcript-only meetings legitimately have no recording path. No `.byte_size`
  column: the frozen `Always` constraint says to reuse the existing `meeting_media.size_bytes` and
  fail the stage when it and the file disagree, so this bullet's earlier mention of `.byte_size` was
  planner error and is corrected here rather than built.
- `server/meetingminer/api/ingests.py` — validate the posted absolute path is under the drops root
  and store the relative form; resolve on every read — the wire contract does not change.
- `server/meetingminer/domain/drops.py` — refuse a canonical file that is a symlink, and a drop
  directory that is one. `present()` uses `is_file()`, which follows links, so a symlinked recording
  is admitted today and only fails at replay. The bytes must live in the write-once drop or its
  checksum describes something that can change without the row changing. A hard link is not a
  symlink and stays permitted.
- `server/meetingminer/pipeline/runner.py` — resolve the claimed job's relative path once against
  the configured root, before `read_drop`.
- `server/meetingminer/pipeline/stages/probe.py` — record the recording's drop-relative path and
  `sha256`, and fail if the ffprobe size and the file size disagree.
- `server/meetingminer/api/media.py` — serve from the recorded row resolved against the drops root;
  drop the constant-composed path.
- A backfill command for the existing jobs' absolute `drop_path` values — reports every row it
  cannot place under the configured root and exits non-zero, so a partial backfill cannot look
  clean (the `--all` precedent in `pull_transcript/emit-drop.js`).
- `server/tests/` — cover every row of the I/O matrix, including a test that relocates the drops
  root and asserts replay, transcript re-parse, and the augmentation door all still work.

**Acceptance Criteria:**
- Given a drop under the configured drops root, when it is ingested, then the database stores its
  path relative to that root and no absolute path is written anywhere.
- Given a drop outside the configured root, when it is posted to intake, then it is refused with a
  message naming the path and the root, and no job row is created.
- Given a completed ingestion, when both roots are relocated and the environment updated, then
  replay serves the recording, a stage rerun re-parses the transcript, and the augmentation door
  reads the target's metadata — all without a data migration.
- Given a meeting with a recording, when it is ingested, then `meeting_media` holds the recording's
  drop-relative path and `sha256`, and a later substitution of that file is detected on rerun.
- Given a transcript-only meeting, when it is ingested, then no recording path or checksum is
  recorded and replay's existing 404 is unchanged.
- Given the existing jobs with absolute paths, when the backfill runs, then every row under the
  configured root is converted and every row that is not is named in the output with a non-zero
  exit.
- Given story 2.1's media route tests, when this story is complete, then they pass unmodified apart
  from how the fixture seeds the drop.

## Design Notes

**Why the recording is not copied.** The story this one replaces proposed copying the recording
under `MM_CONTENT_ROOT` for literal AD-3 compliance. That fixes replay and nothing else: transcript
re-parse and the augmentation door would still resolve through an absolute `job.drop_path`, so it
buys a third of the relocation guarantee at the cost of a multi-gigabyte duplicate per meeting
(measured corpus: 19.5 GB across 85 `.mp4`), a new worker stage, and its own crash-safety and
disk-full handling. AD-1 already makes the drop permanent — never renamed, rewritten, or deleted —
so the copy would be a second permanent copy of a permanent file. Anchoring the root instead fixes
all three readers and copies nothing. The copy-versus-hard-link trade that story escalated to a
human decision does not arise.

**Why AD-3 was not actually violated.** The architecture has always had two anchors; it just never
said so outside the comments in migration `0005` — `drop_relative_path` for material that arrived,
`content_path` for material the pipeline produced, each beside a checksum and a size. AD-3's single
sentence names only the content root, so a reviewer comparing the recording against it correctly
reports a violation that is really an undocumented rule. `storage-layout.md` is now that rule
written down; AD-3 needs the one-sentence amendment tracked separately.

**Why the checksum comes along now.** `transcript_source` stores `sha256` and `byte_size` beside its
path so a re-ingest can prove the input did not change. The recording is the larger and more
consequential input and has no such protection. The stage already opens the file, so the checksum is
nearly free at that moment and expensive to retrofit later.

## Verification

**Commands:**
- `cd server && .venv/bin/python -m pytest tests/ -q` — expected: no regressions, and story 2.1's
  media tests still pass. **Store-backed — safe to run concurrently since story 2.7; only `make evals-run` is one at a time (AGENTS.md).**
- `make web-test` — expected: unchanged and passing; the web side is not touched.

**Manual checks:**
- Ingest a meeting, then move both roots and update `.env`. Confirm replay still serves, a stage
  rerun still re-parses the transcript, and re-posting an augmenting drop still gets the right
  answer from the door.
- Confirm no absolute path appears in `job` or `meeting_media` after ingestion.

## Review Triage Log

### 2026-08-19 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 12: (high 2, medium 8, low 2)
- defer: 7: (high 0, medium 4, low 3)
- reject: 4: (high 0, medium 1, low 3)
- addressed_findings:
  - `[high]` `[patch]` A worker started before the backfill permanently marked every pre-2.1a
    queued job `failed`, and the backfill converted the path without re-queueing — operator-order
    job loss. Fixed: the error text is one shared constant, and the backfill re-queues only jobs
    whose status is `failed` AND whose error is exactly that string, carried in the UPDATE's own
    predicate. Both directions tested.
  - `[high]` `[patch]` `_backfill_media`'s inner JOIN silently skipped a `has_recording` meeting
    with no `meeting_media` row, leaving replay permanently broken while the report said clean —
    contradicting the module's fail-closed contract and matrix row 10. Fixed with a LEFT JOIN that
    distinguishes the three states and reports the third by meeting id.
  - `[medium]` `[patch]` `get_recording` read the drops root before the `has_recording` branch, so
    a transcript-only meeting on a server with a bad drops root returned 500 instead of the
    `media-no-recording` 404 the frozen matrix pins as unchanged. Root read moved below both branches.
  - `[medium]` `[patch]` `_backfill_transcripts` widened a bare filename and counted it converted
    without checking it pointed at anything. Now resolved and required to be a file first.
  - `[medium]` `[patch]` `media-root-unconfigured` was raised for both roots, so an operator could
    not tell which was broken. The drops root got its own slug in api/problems.py.
  - `[medium]` `[patch]` The new symlink test in test_api_media.py had a `.parent.mkdir` typo and
    left a dangling symlink inside the session-shared drops root for every later test.
  - `[medium]` `[patch]` Migration 0008 asserted "no absolute path is written from here on" and
    enforced nothing. Added CHECK constraints on all three `drop_relative_path` columns (leading
    `/`, `..` segment, empty string) plus `(drop_relative_path IS NULL) = (sha256 IS NULL)`.
  - `[medium]` `[patch]` SPEC.md:73 still stated this story's three defects as open. Corrected to
    the implemented state.
  - `[medium]` `[patch]` No upgrade path for existing checkouts: the first signal of a missing
    MM_DROPS_ROOT was a fatal api/worker abort. `check-env` now fails early and by name.
  - `[medium]` `[patch]` Seven guards could be deleted or inverted with the suite still green —
    the ffprobe size-disagreement StageError, the `recording_changed` detection log, both
    per-request root guards, the backfill's exit code and `--dry-run`, the already-anchored
    conversion branch, `read_drop`'s symlink re-check, and the `relative is None` 404. All pinned.
  - `[low]` `[patch]` Log fields were camelCase among snake_case siblings.
  - `[low]` `[patch]` Migration 0008 added a catalog comment only for the column it did not create.
  - `[medium]` `[patch]` Fallout, found by running rather than by inspection: the new `check-env`
    gate fired before three tests reached their own subject (one in test_failfast.py, two in
    test_makefile_procs.py). Their temp `.env` files got a drops root. The two neighbouring sites
    writing the identical `.env` string were deliberately left alone — they exercise `.env`
    failure modes, where stopping early is the point.

## Auto Run Result

Status: done

### Summary

The drops root becomes a configured anchor, `MM_DROPS_ROOT`, the twin of the existing
`MM_CONTENT_ROOT`. Every job stores its drop location relative to that root instead of as an
absolute path, the recording finally gets a row of its own on `meeting_media` carrying its
drop-relative path and `sha256`, and every reader — replay, transcript re-parse, and the
augmentation door — resolves through the configured root. Relocating either root is now an
environment change rather than a data migration, which is the regression this story existed to
prevent. The intake wire contract is unchanged: `POST /ingests` still accepts an absolute
`dropPath`, and only what the server stores changed.

### Files changed

- `server/meetingminer/config.py` — `MM_DROPS_ROOT` and `require_drops_root`, mirroring the
  content-root contract; deliberately does not create or write-probe the directory.
- `server/meetingminer/migrations/0008_drop_root_anchored_paths.sql` — new columns plus the CHECK
  constraints that make the anchor rule the database's rather than a convention.
- `server/meetingminer/domain/drops.py` — `drop_relative_path` in, `resolve_drop_path` out,
  `assert_unlinked_evidence`, and one shared `sha256_and_size`.
- `server/meetingminer/domain/jobs.py` — the shared un-backfilled-job error constant.
- `server/meetingminer/api/ingests.py` — converts the posted absolute path once at intake.
- `server/meetingminer/api/media.py` — serves from the recorded row, not the filename constant.
- `server/meetingminer/api/jobs.py` — stops returning an absolute path off the server.
- `server/meetingminer/api/problems.py` — a distinct slug per misconfigured root.
- `server/meetingminer/api/main.py`, `worker/main.py` — startup gates.
- `server/meetingminer/pipeline/{runner,stage}.py`, `stages/{probe,align,transcribe}.py` — resolve
  once, record path and checksum, widen the transcript anchor.
- `server/meetingminer/backfill.py` — the fail-closed backfill, including convert-then-requeue.
- `infra/Makefile`, `.env.example` — the make target and the early env gate.
- `AGENTS.md`, `_bmad-output/specs/spec-meetingminer/SPEC.md` — corrected to the implemented state.
- `server/tests/` — 74 new tests across test_drops_root.py and the existing modules.
- `web/src/client/types.gen.ts` — the renamed jobs field, hand-edited (see deferred).

### Review findings

Four review layers ran in parallel: blind hunter, edge-case hunter, verification gap, and intent
alignment. 12 patches applied, 7 items deferred, 4 rejected. No intent_gap and no bad_spec, so no
spec loopback was triggered; `review_loop_iteration` stays 0.

Rejected: the `size_bytes` provenance change (the guard raises on disagreement, so the two numbers
can only differ on a failing path); the augmenting-drop media path (the recording legitimately
lives in its own permanent drop); a zero-component stored path (speculative); and the three-things-
named-`drop_relative_path` naming objection.

Follow-up review recommended: **true** — 2 of the 12 patched findings were high severity, which
triggers the rule on its own.

### Verification

- `cd server && .venv/bin/python -m pytest tests/ -q` → **886 passed, 0 failed**, 238s. Run while
  holding the shared Docker stores, handed over explicitly by the story 5.2 builder and released
  after. An earlier run at 861 passed; the +25 are the guard tests this review added.
- `make web-test` → **52 passed**, 5 files. Store-free.
- Matrix test audit: all 13 rows of the I/O & Edge-Case Matrix covered by tests that ran and
  passed, asserting the exact RFC 9457 slugs the matrix names. No skips.
- Manual checks from the spec were NOT performed: relocating both roots and re-posting an
  augmenting drop by hand requires a live api, a worker, and a real `.env`. The relocation
  guarantee is covered mechanically by `test_relocating_both_roots_breaks_nothing`, which moves
  both roots and asserts replay, transcript re-parse, and the augmentation door all still work —
  but it substitutes a relocated config object rather than re-reading the environment and
  restarting the processes, so the env-var-to-running-process leg is unexercised.

### Residual risks

1. **`MM_DROPS_ROOT` is not in the shared `.env`.** Until someone adds it, `make test`, `make up`,
   `make api` and `make worker` all stop at `check-env`. This is the new gate working as designed,
   not a defect. Direct `pytest` runs are unaffected — conftest exports its own session root. The
   correct absolute path is the operator's to choose, so no agent set it.
2. **The pre-probe replay window** (first deferred item) is the one behavioural regression this
   story knowingly ships.
3. **Neither this branch nor story/5-2 contains the other.** Each was verified green in isolation;
   whichever merges second must re-run its suite.
4. The relocation test's env-var leg, and the hand-edited TS client, as described above.

### Review Findings

- [x] [Review][Decision] Arrived-recording checksum policy is contradictory — resolved 2026-08-19: `storage-layout.md` §5 is authoritative. A changed arrived recording is a hard stage failure; amend the conflicting matrix wording and patch `probe` plus its regression tests. `[high]`
- [x] [Review][Decision] Preserve or intentionally break the existing job-response field — resolved 2026-08-19: retain the existing `dropPath` wire field, but make its value the root-relative path so no absolute filesystem path leaves the server. Update the generated client type and contract tests. `[high]`
- [ ] [Review][Patch] Backfill can overwrite a concurrent re-arm with a stale legacy path [server/meetingminer/backfill.py:268] — it snapshots all jobs without locking and later updates only by `id`. A retry or augmentation can first set a new `drop_relative_path`, after which the backfill clears it and writes the old `drop_path` selected at the beginning of the run. Lock or condition the update so it cannot overwrite a newer path. `[high]`
- [ ] [Review][Patch] Backfill launders invalid legacy drops [server/meetingminer/backfill.py:282] — `drop_relative_path()` resolves a symlink and does not require the legacy target to be a real directory. A symlinked drop or a regular file beneath the root is reported converted, then the worker fails after the command claimed success. Require a real non-symlinked drop and canonical evidence checks before conversion; report failures as unplaceable. `[high]`
- [ ] [Review][Patch] Backfill widens a transcript without validating its recorded provenance [server/meetingminer/backfill.py:156] — it checks only that the candidate path is a file. If bytes changed after the original `sha256` and `byte_size` were stored, the command re-anchors tampered evidence as a success. Compare the file's digest and size with the row before writing, and report a mismatch. `[high]`
- [ ] [Review][Patch] Already-anchored recording rows are not actually checked [server/meetingminer/backfill.py:235] — the command claims that rows hanging from an already-relative job are still checked, but returns as soon as `meeting_media.drop_relative_path` is non-null. A bad/missing/tampered existing recording can therefore leave the command clean. Validate the path, checksum, and size on that branch as well. `[medium]`
- [ ] [Review][Patch] Database constraints still permit impossible anchor shapes [server/meetingminer/migrations/0008_drop_root_anchored_paths.sql:41] — `job_has_a_drop` permits both paths, and the root-relative checks permit `.`/`./` plus bare recording and transcript filenames. Direct SQL can thus write ambiguous or unresolvable evidence paths despite the migration claiming database enforcement. Require exactly one job path, reject root aliases, and require recording/transcript paths to include their drop-directory component. `[medium]`
- [ ] [Review][Patch] Drops-root startup gate accepts an unusable mount [server/meetingminer/config.py:667] — `require_drops_root()` checks only existence and directory type. A non-traversable/readable drops root passes startup and fails only at intake, replay, or a worker claim, contrary to the named startup-failure contract. Add a read-only usability check that does not create or mutate the root. `[medium]`
- [ ] [Review][Patch] The early Makefile root gate accepts a quoted empty value [infra/Makefile:140] — `MM_DROPS_ROOT=""` satisfies the grep but python-dotenv later treats it as unset, moving the failure from `make check-env` back to process startup. Tighten the guard and add a readable-env-without-root regression test. `[medium]`
- [ ] [Review][Patch] Root-path and legacy response guards lack direct regression tests [server/tests/test_drops_root.py:779] — no test asserts the `transcript_source` CHECK rejects absolute/escaping values, and no API test seeds a pre-backfill row to prove `GET /jobs/{id}` returns `dropRelativePath: null` without leaking its legacy absolute path. Add both mutation-resistant tests. `[low]`
