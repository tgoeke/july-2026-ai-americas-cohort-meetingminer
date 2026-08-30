---
title: 'Story 2.1b: Bring Your Own Recording — a Drop From a Local Video'
type: 'feature'
created: '2026-08-19'
status: 'done'
baseline_revision: '182167b1e983139ec3b17a3b16e1cbf189fd14eb'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/specs/spec-meetingminer/storage-layout.md'
  - '{project-root}/docs/source-drop.schema.json'
  - '{project-root}/_bmad-output/specs/spec-meetingminer/glossary.md'
warnings:
  - 'oversized'
deferred:
  - summary: >-
      A transcript-only mint and a later mint of the same meeting's recording produce two
      occurrences, because sourceId is the primary evidence file's hash and the two digests differ.
    evidence: |-
      mint() orders identity on EVIDENCE_FILENAMES, so a transcript-only drop is keyed on the
      transcript and a later video mint is keyed on the video. find_existing_drop cannot see the
      relationship. docs/source-drop.schema.json documents `augments` (schemaVersion 2) as the
      mechanism for exactly this case - "a recording recovered later" - and build_metadata
      hard-codes schemaVersion 1 with no --augments flag. The intent contract has no matrix row
      for it, so it is a shared gap rather than a deviation.
    location: >-
      server/meetingminer/mintdrop.py
    severity: medium
  - summary: >-
      The copy is a full byte copy rather than an APFS clone, so a same-volume mint costs a second
      full copy of a multi-gigabyte recording in permanent storage.
    evidence: |-
      _copy_verified uses shutil.copyfile. The reference producer this tool matches behaviourally,
      pull_transcript/emit-drop.js, passes fs.constants.COPYFILE_FICLONE for the same copy, which
      is a clone on APFS and a real copy elsewhere. On the measured 19.5 GB corpus the difference
      is the size of the corpus.
    location: >-
      server/meetingminer/mintdrop.py
    severity: medium
  - summary: >-
      A run killed by SIGKILL, OOM or power loss leaves a partial multi-gigabyte copy under
      <MM_DROPS_ROOT>/.staging/ with no cleanup path.
    evidence: |-
      _assemble's finally block covers exceptions and Ctrl-C but cannot run on SIGKILL. The drops
      root is permanent, backed-up storage (storage-layout.md section 1), so the orphan is backed
      up too. There is no --gc, no startup sweep of stale .staging entries, and docs/README.md
      does not tell an operator that .staging is safe to delete. The intent's matrix row permits
      the leftover ("staging path is left or cleaned"), so this is an operational gap, not a
      contract deviation.
    location: >-
      server/meetingminer/mintdrop.py
    severity: medium
  - summary: >-
      No free-space preflight before a multi-gigabyte copy into permanent storage.
    evidence: |-
      The disk-full path is handled correctly once it happens - the staging directory is discarded
      and nothing is finalized - but the failure is only discovered after the copy has run. A
      shutil.disk_usage check against the summed byte_size would refuse before reading anything.
    location: >-
      server/meetingminer/mintdrop.py
    severity: low
---

<intent-contract>

## Intent

**Problem:** AD-1 names three sources — "Teams puller, local recording, future YouTube" — and says
every one of them lands as a source drop. Only the Teams puller can actually produce one. There is
no tool that turns a local video file into a drop, and `docs/` holds only the schema, a README, and
the agent kickoff prompt. A user who downloads or records a video today has to hand-author a
schema-valid `metadata.json` — `sourceId`, `corpus`, `startedAt` with its precision, and an embedded
`provenance` block — assemble the directory atomically so intake never sees a partial one, and POST
an absolute path. Nothing documents any of that. The capstone's own eval corpus is scripted
meetings, which are exactly the case this path serves.

**Approach:** A small command that takes a local video (and optionally a transcript file), mints a
conforming drop under the drops root, and reports the path intake wants. One ingestion path, not
two: this tool produces the same artifact the puller produces, and MeetingMiner still only ever
consumes drops.

## Boundaries & Constraints

**Always:**
- The output is a drop that validates against `docs/source-drop.schema.json` — the same door, the
  same validation, no bypass (AD-1, AD-14).
- The drop is assembled in a staging path and moved into place complete, so a directory visible
  under the drops root is always a whole drop.
- `sourceId` is derived from the video's own content — its `sha256` — so re-running the tool on the
  same file resolves to the same occurrence and the write-once rule does the rest, rather than
  minting a duplicate meeting.
- `provenance` records where the file came from: the original absolute path, its size and checksum,
  the wall-clock the tool ran, and who supplied it. This is the only record of the file's origin,
  because the original is not copied back anywhere.
- `startedAt` is taken from an explicit argument when given, else derived from the file's own
  timestamp metadata, and `startedAtPrecision` is set honestly to match. The pipeline never
  re-derives wall clock from media metadata (AD-1), so getting this right here is the only chance.
- `corpus` is a required explicit choice (`scripted` | `real`) — never defaulted, because it is
  carried onto the Meeting row and decides what the eval harness counts.

**Block If:**
- The desired behaviour is for MeetingMiner to watch a folder and ingest whatever appears. That is
  autonomous ingestion, an explicit Non-goal, and it also breaks the rule that files in the folder
  alone never ingest — the producer notifies intake.

**Never:**
- No copying of the source video back to its origin, no modification of the original file, and no
  transcoding. The drop's `recording.mp4` is a byte-identical copy of what the user supplied.
- No new intake endpoint and no new ingestion path. The tool POSTs to the existing door, or prints
  the command that does.
- No hand-authored `metadata.json` in the documentation as the recommended route — the tool is the
  route; the schema stays the contract.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Video only | A local `.mp4`, `corpus` given | Drop with `recording.mp4` and `metadata.json`; path reported | No error expected |
| Video plus transcript | Video and a `.vtt` or speaker-attributed `.txt` | Both copied under their canonical drop filenames | No error expected |
| Transcript only | A transcript file, no video | Valid transcript-only drop — first-class per AD-1 | No error expected |
| Neither | Nothing ingestible supplied | Refused before anything is written | Non-zero exit, named reason |
| Re-run on the same file | Drop for that content hash already finalized | Reported as existing; nothing rewritten, nothing duplicated (AD-1 write-once) | Non-zero exit or explicit `exists` status |
| Explicit start time | `startedAt` supplied | Recorded verbatim with `second` precision | No error expected |
| No derivable start time | File metadata carries none and none supplied | Refused rather than guessed — a wrong wall clock is unrecoverable downstream | Non-zero exit, named reason |
| Unreadable or partial video | Permissions error, or file still being written | Refused; no partial drop is ever finalized | Staging path discarded |
| Interrupted run | Process dies mid-assembly | Staging path is left or cleaned; nothing incomplete appears under the drops root | Atomic finalize |
| Disk full | Copy cannot complete | Refused with a readable error; no drop finalized | Staging path discarded |
| Non-video file passed as video | e.g. a `.docx` renamed | Refused at probe rather than at ingest | Non-zero exit, named reason |

</intent-contract>

## Code Map

Everything below was read on `story/2-1b` at baseline `0df90af` (= `origin/main`,
which already carries story 2.1a merged and remediated).

- `pull_transcript/emit-drop.js` — the reference producer, **read-only for this story**. The
  behaviours to match, not import: the `<YYYY-MM-DD>-<title-slug>-<sha1(sourceId)[0:8]>` directory
  name (`dropName`, `slugify`, lines 216-237); staging under `<dropsRoot>/.staging/<name>.<pid>.<n>`
  then one `rename` to finalize, with `EEXIST`/`ENOTEMPTY` read as `exists` (`emitDrop`,
  lines 553-621); the `created` / `exists` status vocabulary; `postIngest`'s 201→`created`,
  200→`requeued`, 409 `duplicate-source`→`duplicate` mapping (lines 650-684); `--drops` /
  `--api` / `--corpus` flags with `MM_DROPS_ROOT` / `MM_API_URL` / `MM_CORPUS` fallbacks
  (lines 70-83). It is a vendored black box that reads no `.env` and imports no server code
  (its own header, lines 4-23) — so nothing is extracted from it and nothing is edited in it.
- `server/meetingminer/domain/drops.py` — the canonical filenames the new drop must use
  (`METADATA_FILENAME`, `RECORDING_FILENAME`, `TRANSCRIPT_VTT_FILENAME`,
  `TRANSCRIPT_TEXT_FILENAME`, `EVIDENCE_FILENAMES`, lines 34-52) and `sha256_and_size()`
  (lines 193-207), which is the one implementation of "did these bytes change" and therefore the
  one that mints `sourceId`. Import these; do not respell them. Read-only.
- `server/meetingminer/config.py` — `load_config()`, `ConfigError`, and `validate_drops_root()`
  (lines 667-696), the read-only root check the api reruns per request. The tool calls it for the
  root and then makes its own writability decision, because `validate_drops_root` deliberately
  never write-probes. Read-only.
- `server/meetingminer/api/ingests.py` — the door, **unchanged by this story**. Constrains what the
  tool may produce: `_validate_drop_path` (lines 180-226) demands an absolute `dropPath` that is a
  real directory under `MM_DROPS_ROOT`, refuses a symlinked drop directory or canonical file, and
  is the only place the absolute path becomes the stored relative one; `_load_metadata`
  (lines 244-277) validates against the schema and answers 422; `drop_schema_path` (lines 86-97)
  anchors the schema next to the loaded `config.yaml` — the tool resolves the schema the same way,
  so both sides validate against one file.
- `server/meetingminer/pipeline/media.py` — `probe_media()` (lines 114-171) and `MediaToolError`
  (line 39): the existing ffprobe wrapper, and the "is this actually a video" gate. `MediaFacts`
  carries no container `creation_time`, so this story adds one small public function beside it
  (below). It already states it never writes inside a drop (lines 10-11).
- `server/meetingminer/backfill.py` — the shape to copy for an operator CLI: module docstring
  stating when to run it, `argparse` in `main()`, fail-closed non-zero exit, `load_config` with
  `MM_CONFIG_PATH` / `MM_ENV_PATH` support. Read-only.
- `server/pyproject.toml` — `[project.scripts]` already carries `rebuild` and `backfill`; the new
  command joins them.
- `infra/Makefile` — `backfill-drop-paths` (lines 403-406) is the target shape to copy, including
  its `BACKFILL_ARGS ?=` variable (line 258) and the explicit reason it is not the global `ARGS`.
  `.PHONY` (lines 74-78) and the `help` block (lines 82-116) both need the new target.
- `server/tests/conftest.py` — `RUN_ID`/`TEST_DATABASE` (lines 62-67) make the suite parallel-safe
  (story 2.7); the Postgres fixtures are opt-in, not autouse, so the new test module is store-free.
  `valid_metadata()` (line 92) and the drop fixtures are the existing vocabulary for drop tests.
- `server/tests/test_drop_schema.py` — how the server side already validates a drop against
  `docs/source-drop.schema.json`; the new tests validate every produced drop the same way.
- `docs/README.md` — three stale lines today ("`source-drop.schema.json` ... lands here with story
  1.2"). This story replaces it with the user-facing procedure.
- `_bmad-output/specs/spec-meetingminer/storage-layout.md` §6 "Bringing your own recording" — the
  frozen description of this tool; §1 names it as a legitimate writer of the drops root, alongside
  the puller's `emit-drop`.

## Tasks & Acceptance

**Execution:**

1. `server/meetingminer/pipeline/media.py` — add one public function
   `probe_creation_time(path: Path) -> str | None`, returning `format.tags.creation_time` from a
   single `ffprobe` call (reusing `_run` and `FFPROBE_TIMEOUT_SECONDS`) or `None` when the
   container carries none. Raises `MediaToolError` on a missing or failing ffprobe, like its
   neighbours. Rationale: ffprobe knowledge stays in the one module that owns it, and this is the
   only honest source for a recording's wall clock.
2. `server/meetingminer/mintdrop.py` — the new command. In order: resolve config and drops root;
   refuse when nothing ingestible was supplied; probe the video and refuse a non-video; compute
   `sha256` per supplied file; mint `sourceId` as `sha256:<hex>` of the primary evidence file;
   resolve `startedAt`/`startedAtPrecision`; detect an already-minted drop for that `sourceId` and
   report `exists`; otherwise assemble under `<drops-root>/.staging/`, validate the assembled
   `metadata.json` against `docs/source-drop.schema.json`, finalize with one `rename`, and POST to
   `/ingests` unless `--no-post`. Every failure path removes the staging directory.
3. `server/tests/test_mint_drop.py` — one test per I/O-matrix row plus the acceptance criteria
   below. Store-free: `tmp_path` drops root, no Postgres fixture. Every produced `metadata.json`
   is validated against `docs/source-drop.schema.json` with the same
   `jsonschema.Draft202012Validator` + `FormatChecker` the api uses.
4. `server/pyproject.toml` — register `mint-drop = "meetingminer.mintdrop:main"` under
   `[project.scripts]`, beside `rebuild` and `backfill`.
5. `infra/Makefile` — add a `mint-drop` target taking `MINT_ARGS`, plus its `.PHONY` and `help`
   entries. It depends on `check-env` only: minting needs no store and no migration.
6. `docs/README.md` — replace the stale stub with the procedure: what a drop is, where the drops
   root comes from, the one command, and what to do with the path it prints.

**Acceptance Criteria:**

- Given a local video and `--corpus scripted`, when `mint-drop` runs, then a directory named
  `<YYYY-MM-DD>-<slug>-<sha1(sourceId)[0:8]>` exists under `MM_DROPS_ROOT` holding exactly
  `metadata.json` and `recording.mp4`, its `metadata.json` validates against
  `docs/source-drop.schema.json`, and `recording.mp4` is byte-identical to the input.
- Given a drop already minted for that content, when `mint-drop` runs again with a different
  `--title` and a different `--started-at`, then it reports `exists` with the existing path and
  writes nothing — the `sourceId` match decides, not the directory name.
- Given `--no-post`, when the command finishes, then it prints the absolute drop path and the exact
  `POST /ingests` request that ingests it, and makes no HTTP call.
- Given a failure at any point after staging began, when the drops root is listed, then no
  directory for that drop is visible there and the staging directory is gone.
- Given the api answers 409 `duplicate-source`, when the command reports, then it says
  `already ingested` and exits 0 — a drop that is already in the system is not a tool failure.

### Review Findings

- [x] [Review][Patch] Preserve audio-less video-only support through a viewable pipeline outcome [server/meetingminer/mintdrop.py:316] — decision 2026-08-20: retain the frozen video-only contract; do not reject a recording solely because it lacks audio or a supplied transcript.
- [x] [Review][Patch] Refuse an explicit drops root that intake cannot resolve [server/meetingminer/mintdrop.py:375]
- [x] [Review][Patch] Serialize minting by content-derived `sourceId` across the existence check and finalize [server/meetingminer/mintdrop.py:590]
- [x] [Review][Patch] Revalidate the staged recording as video immediately before finalize [server/meetingminer/mintdrop.py:724]
- [x] [Review][Patch] Validate that `--api` is an origin-only HTTP(S) base before minting [server/meetingminer/mintdrop.py:770]
- [x] [Review][Patch] Exercise a minted drop through a real HTTP intake fixture, including the endpoint URL [server/tests/test_mint_drop.py:718]

## Spec Change Log

## Review Triage Log

### 2026-08-20 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 14: (high 1, medium 8, low 5)
- defer: 4: (high 0, medium 3, low 1)
- reject: 5: (high 0, medium 0, low 5)
- addressed_findings:
  - `[high]` `[patch]` `--drops` outside the configured `MM_DROPS_ROOT` finalized a write-once drop
    intake answers 400 for, forever — the intent's "never writes a drop the door would refuse".
    Now warns, naming both roots; a test asserts the path is one `drop_relative_path` rejects.
  - `[medium]` `[patch]` `mint()` resolved the wall clock before `find_existing_drop`, so a
    transcript-only re-run without `--started-at` refused instead of reporting `exists`,
    contradicting the re-run matrix row. Existence scan moved above the clock; reproduced by hand
    before and after.
  - `[medium]` `[patch]` `exists` silently discarded evidence a re-run supplied that the existing
    drop lacks. `MintResult.ignored` now names those files. Report-only; augmentation stays intake's.
  - `[medium]` `[patch]` Mutation-proven: deleting the two-files-map-to-one-canonical-name guard
    left the suite green, so a two-`.mp4` run could finalize a drop holding only the second. Tested.
  - `[medium]` `[patch]` Mutation-proven: deleting the zero-byte refusal left the suite green;
    transcript-only drops skip the ffprobe gate, so it is the only size check there. Tested.
  - `[medium]` `[patch]` Mutation-proven: removing the 1904 epoch sentinel left the suite green,
    and 1904 is the origin an mp4 container actually carries. Parametrize row added.
  - `[medium]` `[patch]` Mutation-proven: replacing the default-`--title` expression left the suite
    green, so every untitled meeting could silently become "untitled". Asserted on title and name.
  - `[medium]` `[patch]` No test asserted a minted drop satisfies the door's own containment rule.
    Added one that mints into the configured root and calls `drop_relative_path`.
  - `[medium]` `[patch]` `docs/README.md` omitted `--drops`/`--api`, misstated the `--title` and
    `--supplied-by` defaults, listed three of nine refusals, showed sample output the tool never
    prints, and claimed re-running would not retry the POST when it does. All corrected.
  - `[low]` `[patch]` `metadata.json` escaped non-ASCII while the puller writes raw UTF-8 into the
    same drops root; `ensure_ascii=False`.
  - `[low]` `[patch]` Dead `title == "duplicate-source"` branch in `post_ingest` removed; matches
    the full problem type rather than an `endswith` on a bare suffix.
  - `[low]` `[patch]` POSIX `rename()` succeeds onto an empty directory, contradicting the stated
    "a finalized drop is never overwritten"; explicit guard added.
  - `[low]` `[patch]` `test_an_unreadable_file_is_refused` was a no-op under root; `skipif` added.
  - `[low]` `[patch]` `--api` had no test and accepted a schemeless value, printing an unusable
    re-POST command; scheme validated up front, tests added.

Rejected as not reproducing: a claimed traceback from a schemeless `--api` (`urlopen` raises
`URLError`, which `main` catches and reports), and a claimed `find_existing_drop` blind spot on
`-NNN` sequence drops (this tool mints no siblings, and puller drops carry unrelated digests).
Rejected as contrary to the intent: a plausibility window on `--started-at`, which the matrix
requires to be "recorded verbatim". Rejected as scope additions: copy progress output, and a
distinct exit code for the finalized-but-unposted case.

## Design Notes

**Story 2.1a has landed.** The frontmatter warning that gated this story ("best built after 2.1a")
is resolved: `origin/main` at `0df90af` carries 2.1a merged and remediated, so `MM_DROPS_ROOT` is a
real, validated configuration value and the tool writes under it. No explicit-destination fallback
is needed and none is built.

**Why Python in the server package rather than beside `emit-drop.js`.** The acceptance criterion is
that someone follows the documented procedure and reaches an ingested meeting without hand-writing
JSON. That requires the tool to know `MM_DROPS_ROOT` without the user restating it, and the only
component that reads this project's `.env` in this project's dialect is `meetingminer.config`. The
puller states in its own header that it reads no `.env` and imports no server code (AD-1's black
box); teaching it to would destabilise exactly the property the Code Map's "extract if it does not
destabilise the puller" clause protects. So `emit-drop.js`'s *behaviour* is matched and its *code*
is left alone. The cost is one duplicated staging-and-finalize implementation, which is the
deliberate price of AD-1's two-black-boxes rule.

**This does not breach AD-13.** AD-13 makes drop contents read-only *after intake*, and
`storage-layout.md` §1 names "the bring-your-own-recording tool" as a writer of the drops root
beside the puller's `emit-drop`. The tool only ever creates a new directory: it never opens, edits,
renames or deletes anything in a finalized drop, and an existing target is reported, never written
into.

**`sourceId` is `sha256:<hex>` of the primary evidence file.** Prefixed so it can never be confused
with the puller's Stream-URL ids. Primary means the first present of `recording.mp4`,
`transcript.vtt`, `transcript.txt` — `EVIDENCE_FILENAMES` order — so a transcript-only mint and a
later video-plus-transcript mint of the same video do not collide on identity by accident, and
re-running with the video present always resolves to the same id.

**Re-run detection is by `sourceId`, not by directory name.** The directory name embeds the date and
the title slug, both of which the user can change between runs; only the trailing
`sha1(sourceId)[0:8]` is fixed. The tool therefore scans the drops root for a directory ending in
that digest and confirms the candidate's `metadata.json` carries the same `sourceId` before
reporting `exists`. Without this, `mint-drop video.mp4 --title A` followed by `--title B` finalizes
a second write-once drop that intake then refuses with 409 — a drop that can never be ingested and
can never be deleted.

**`startedAt` comes from the argument or from container metadata, never from the filesystem.** A
file's mtime is reset by copying and downloading, so deriving a meeting's wall clock from it is the
guess the intent contract forbids. `format.tags.creation_time` is written by the recorder and is
the only honest fallback; when it is absent and `--started-at` was not given, the command refuses.
`--started-at 2026-08-05T12:00:19Z` records `second` precision; `--started-at 2026-08-05` records
`2026-08-05T00:00:00Z` with `day` precision, which is what the schema's `day` means.

**`provenance` carries no `url`.** `DropContents.stream_url` turns `provenance.url` into UX-DR11's
transitional "watch the original recap" deep link. A local file has no such page, so the key is
omitted and the UI correctly offers no link. `provenance.title` *is* set, because
`DropContents.title` reads it as the meeting's human label.

## Verification

**Commands:**
- `cd server && .venv/bin/python -m pytest tests/test_mint_drop.py -q` — expected: green; every
  produced drop schema-validated inside the tests. Store-free.
- `make puller-test` — expected: unchanged and passing. Nothing in `pull_transcript/` is edited, so
  this is a regression check, not a change check.
- `cd server && .venv/bin/python -m pytest tests/ -q` — expected: no regressions.
  **Store-backed — safe to run concurrently since story 2.7; only `make evals-run` is one at a time (AGENTS.md).**
- `make mint-drop MINT_ARGS='--help'` — expected: usage text, exit 0.

**Manual checks:**
- Mint a drop from a non-Teams video, POST it, and confirm the meeting is viewable with replay
  working — the end-to-end proof that AD-1's third source is real. Requires the full stack up.

## Auto Run Result

Status: done
Blocking condition: none

**What was built.** `mint-drop`, a producer that turns a local recording and/or transcript into a
schema-valid source drop under `MM_DROPS_ROOT` and hands it to `POST /ingests`. AD-1's third source
is now real: a hand-brought video reaches a meeting through the same door, the same validation and
the same write-once rules as a pulled one, with no second ingestion path.

**Files changed**

- `server/meetingminer/mintdrop.py` (new) — the command: classify supplied files, ffprobe-gate the
  video, digest each file, mint `sourceId` as `sha256:<hex>` of the primary evidence file, find any
  drop already minted for that id, resolve the wall clock, assemble under `<root>/.staging/`,
  validate against `docs/source-drop.schema.json`, finalize with one `rename`, POST.
- `server/meetingminer/pipeline/media.py` — one additive public `probe_creation_time()`, so ffprobe
  knowledge stays in the module that owns it.
- `server/tests/test_mint_drop.py` (new) — 53 store-free tests covering every I/O-matrix row, the
  acceptance criteria, and each guard the review found unpinned.
- `server/pyproject.toml` — `mint-drop` console script beside `rebuild` and `backfill`.
- `infra/Makefile` — `mint-drop` target with `MINT_ARGS`, `.PHONY` and `help` entries.
- `docs/README.md` — the user-facing procedure, replacing a three-line story-1.2 stub.

**Review findings.** 14 patched (1 high, 8 medium, 5 low), 4 deferred (see frontmatter), 5 rejected.
No intent gaps and no spec defects, so no re-derivation loopback. Follow-up review recommended:
true — a high-severity finding was patched (score 3x8 + 1x5 = 29, threshold 5).

**Verification** (every command run by the workflow owner, not reported second-hand)

- `cd server && .venv/bin/python -m pytest tests/test_mint_drop.py -q` — 53 passed.
- `cd server && .venv/bin/python -m pytest tests/ -q` — 982 passed, 0 failed, 0 skipped, 3m59s.
  Run concurrently with story 3.1 per AGENTS.md; no contention observed.
- `make puller-test` — 102 pass, 0 fail. `pull_transcript/` is untouched by this story.
- `make mint-drop MINT_ARGS='--help'` — usage, exit 0.
- End-to-end against a scratch drops root, through the documented `make mint-drop` line: minted from
  an ffmpeg-built mp4, confirmed `recording.mp4` byte-identical by sha256, `startedAt` taken from
  the container's `creation_time`, and a re-run with a different `--title` and `--started-at`
  reporting `exists` against the original directory with nothing rewritten.

**Residual risks**

- The manual end-to-end in `## Verification` — mint, POST, then confirm the meeting is viewable with
  replay — was not performed. It needs the full stack up, and no run has yet proved the produced
  drop ingests against a live api. This is the single largest untested claim in the story.
- Every test drives the process surface (argv in, exit code out, `tmp_path` root, stubbed
  `urlopen`). The door's own containment rule is asserted through `drop_relative_path`, but no test
  posts a minted drop to a running api.
- `--drops` outside the configured root now warns rather than refuses, because the suite depends on
  the flag. An operator who ignores the warning still finalizes an unusable write-once drop.
