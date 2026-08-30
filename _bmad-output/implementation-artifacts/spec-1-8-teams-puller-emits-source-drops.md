---
title: 'Story 1.8: Teams Puller Emits Source Drops'
type: 'feature'
created: '2026-08-18'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true
baseline_commit: 'acf5d754212aa5538b0958f603245e0145f53ba4'
baseline_revision: 'acf5d754212aa5538b0958f603245e0145f53ba4'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/kickoff-story-1-8-2026-08-18.md'
warnings: ['oversized']
deferred:
  - summary: >-
      Drop identity is the directory name (date + title slug + sourceId digest), so a re-pull whose
      resolved date or title changes emits a second drop directory for the same sourceId.
    evidence: |-
      dropName() mixes startedAt, slugify(title) and sha1(sourceId)[0:8], and write-once detection is
      an existsSync on that composite path. After a --date correction or an upstream rename the
      existing drop is not recognised, a second directory is finalized, and only the api's
      duplicate-source 409 prevents a second job row. Consequence is an orphan directory rather than a
      duplicate ingest, so it is not blocking; closing it properly means keying detection on the
      digest alone or keeping a sidecar index, which is a design change beyond this story.
    location: >-
      pull_transcript/emit-drop.js (dropName / emitDrop)
    severity: medium
  - summary: >-
      The canonical drop filenames are pinned independently on both sides of the seam with nothing
      linking them, and no test posts an emitDrop-produced directory to the real intake route.
    evidence: |-
      EVIDENCE_MAP in pull_transcript/emit-drop.js and EVIDENCE_FILENAMES in
      server/meetingminer/domain/drops.py both hardcode recording.mp4 / transcript.vtt /
      transcript.txt. The one shared artifact, docs/source-drop.schema.json, names them only in prose
      descriptions, so no validator checks them. server/tests/test_ingests.py builds every drop from
      its own conftest fixture. Renaming one side leaves both suites green while every emitted drop
      starts failing intake. Closing it means either adding machine-checkable filenames to the frozen
      schema or a cross-suite integration test, both outside this story's boundaries.
    location: >-
      pull_transcript/emit-drop.js:45 and server/meetingminer/domain/drops.py:29
    severity: medium
---

<intent-contract>

## Intent

**Problem:** The puller writes its own `<Title>/<M.D.YY>/` archive layout, which the pipeline cannot read: there is no emit-drop step, so no real Teams meeting can enter MeetingMiner, and the 28 already-pulled occurrences sit inert while every pipeline story past 1.3 needs a real corpus to run against.

**Approach:** Add a puller-side emit-drop step that maps one occurrence directory into a schema-valid source drop — assembled in a staging path, finalized by atomic rename into a dedicated drops folder, never overwriting a finalized drop — then POSTs its absolute path to `POST /ingests`. Wire it into the end of a live pull and expose it as a standalone CLI whose `--all` pass backfills the existing archive. Validate the emitted `metadata.json` against `docs/source-drop.schema.json` in the puller's own test suite.

## Boundaries & Constraints

**Always:**
- AD-1 black-box seam: the puller shares no server code, imports nothing from `server/`, and reads no server `config.yaml` or `.env`. Its only contracts are `docs/source-drop.schema.json` and `POST /ingests`. Auth stays the persisted `.transcript-profile/` browser session — no credential files, no Microsoft Graph.
- Drop layout (AD-1): canonical filenames `metadata.json`, `recording.mp4`, `transcript.vtt`, `transcript.txt`; at least one of the latter three. Every other archive file (`.docx`, `.md`, ` action items.md`, `_source.json`, stray transcripts) is **ignored, never mapped**.
- `metadata.json` carries exactly the schema's keys (`additionalProperties: false`): `schemaVersion: 1`, `sourceId`, `corpus`, `startedAt`, `startedAtPrecision`, `provenance`. `provenance` is the occurrence's `_source.json` object embedded verbatim.
- Write-once: assemble under `<dropsRoot>/.staging/<name>.<pid>.<n>/`, finalize with a single `fs.renameSync` into `<dropsRoot>/<name>`. A finalized drop is never overwritten, re-copied into, or deleted; an existing target is reported and skipped. Staging is removed on every exit path.
- The drops folder is distinct from the puller's archive and from the repo. Resolution order: `--drops <dir>` > `MM_DROPS_ROOT` > the built-in default `/Users/devopsterus/current/meetingminer-drops`.
- API base URL resolution order: `--api <url>` > `MM_API_URL` > `http://127.0.0.1:8000`.
- Emit and POST never fail a pull: the live hook is wrapped so a drop or intake failure prints a named diagnostic and leaves the transcript, video, and summaries intact — the same contract `generateDocs` already has.
- The puller stays CommonJS, Node LTS, and must run standing alone outside this repo: the schema file is a **test-time** dependency only, never loaded at emit time.
- `corpus` defaults to `real`; `--corpus scripted` (or `MM_CORPUS`) tags the Epic 5 mock meetings pulled from the same tenant.

**Block If:**
- The drop schema would need a new field to express something emit-drop must record.
- A dependency beyond `ajv` + `ajv-formats` (dev-only) turns out to be required.

**Never:**
- No changes under `server/`, `web/`, `docs/source-drop.schema.json`, or `config.yaml` — the contract is frozen by story 1.2 and this story consumes it.
- No participant extraction (`participants` is omitted; story 1.5 derives participants from transcript attribution — explicitly sanctioned by the epic AC).
- No mutation of the puller's archive: emit copies, never moves or rewrites occurrence files, and never edits `_source.json`.
- No live Teams pull, login, or tenant traffic during this run (see *Verification split* in Design Notes).
- No re-derivation of wall-clock from media metadata; no timezone guessing for un-suffixed filename stamps.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Transcript-only occurrence | dir with `<stem>.txt` (+`.vtt`), no `.mp4` | drop with `metadata.json` + `transcript.txt` (+`transcript.vtt`); no `recording.mp4` | N/A |
| Occurrence with recording | dir with `<stem>.mp4` | drop additionally carries `recording.mp4` | N/A |
| UTC filename stamp | `recordingName` matches `-YYYYMMDD_HHMMSSUTC-` | `startedAt` = that instant, `startedAtPrecision: "second"` | N/A |
| Un-suffixed stamp / no stamp | `-YYYYMMDD_HHMMSS-` without `UTC`, or none | `startedAt` = `_source.json` `date` at `T00:00:00Z`, precision `"day"` | N/A |
| Generated summaries present | `.docx`, `.md`, ` action items.md` in the occurrence | ignored — absent from the drop | N/A |
| Stray non-stem transcript | `11_59 AM - …_transcript.txt` beside `<stem>.txt` | ignored — only stem-matched files map | N/A |
| Re-emit of a finalized drop | target drop dir already exists | reported `exists`; nothing written, staging removed | no error, exit 0 |
| Concurrent finalize race | rename onto a now-existing dir | `EEXIST`/`ENOTEMPTY` treated as `exists` | staging removed |
| Occurrence missing every evidence file | only `_source.json` | skipped with a named reason; no drop, no POST | counted as skipped |
| Unreadable/invalid `_source.json` | malformed JSON | skipped with a named reason; other occurrences continue | counted as failed |
| POST accepted | fresh `sourceId`, api up | `201` → `jobId` printed | N/A |
| POST duplicate | `sourceId` already has a live job | `409` reported as already-ingested, exit 0 | not an error |
| API unreachable | api down, drop finalized | drop kept; named diagnostic naming the drop path to re-POST | non-zero exit for the CLI, never for a live pull |
| `--dry-run` | any occurrence | prints planned drop name, files, and metadata; writes nothing | N/A |
| `--all` over the archive | 28 occurrences | 28 drops; summary line counts created/exists/skipped/failed | per-occurrence failures do not abort the pass |

</intent-contract>

## Code Map

- `_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md` — **AD-1** (line 174: emit-drop mapping, staging + atomic finalize, write-once, `sourceId` = "recording drive-item ID or Stream URL", `startedAt` from filename stamp else day precision, provenance = `_source.json` embedded, unknown files ignored), **AD-14** (lines 248–252, intake), line 124 (puller shares no server code), line 278 (puller outside the config regime), line 308 (drops folder distinct from the puller archive). Read-only authority.
- `docs/source-drop.schema.json` — the frozen contract. `additionalProperties: false` at top level; `startedAt` pattern requires `Z`/`+00:00`; the `if/then` block pins `day` precision to `T00:00:00`. Read-only.
- `server/meetingminer/api/ingests.py:196` — `POST /ingests` accepts `{"dropPath": "<absolute>"}`; `201 {jobId}` fresh, `200 {jobId}` failed-job re-queue, `409` duplicate with `jobId` in the problem body, `400` bad path, `422` invalid drop. Read-only.
- `server/meetingminer/domain/drops.py:22-32` — canonical filenames and the at-least-one-evidence rule the emitter must satisfy. Read-only.
- `server/tests/test_drop_schema.py` — the pipeline half of the "both suites validate" AC; already green, unchanged.
- `pull_transcript/grab-teams-transcript.js:1237` — `writeSource(dir, {...})` inside `if (!outFile)`, after the `.txt`/`.vtt`/`.docx` writes and after the video fallback chain. **The live hook point**: every drop input exists on disk here, and summaries (which the drop ignores) have not run yet.
- `pull_transcript/grab-teams-transcript.js:97` — `recordingNameFromUrl()` shows the `id`-param decode this story's `sourceId` canonicalization reuses.
- `pull_transcript/grab-teams-transcript.js:315` — `stampDate()`: existing `-(20\d{2})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})(UTC)?` parse; group 7 (`UTC`) is the discriminator emit-drop needs and `stampDate` currently discards.
- `pull_transcript/grab-teams-transcript.js:107` — `heldRecordingNames()`: the existing recursive `_source.json` scan the `--all` backfill mirrors (skip dotfiles and `node_modules`).
- `pull_transcript/grab-teams-transcript.js:940-960` — arg parsing (`args.filter(a => a.startsWith('--'))` style) and the `generateDocs` try/catch that models "a late step never fails the pull".
- `pull_transcript/.gitignore` — deny-all allowlist (`*` then `!name`); every new tracked file must be listed, and a new directory needs both `!test/` and `!test/*.js`.
- `pull_transcript/package.json` — `commonjs`, only `playwright`; no `test` script yet.
- `infra/Makefile:124` — `test: check-client infra-up` runs pytest then the web build; the new puller suite hangs off here. `Makefile:113` `bootstrap` is where `npm install` for the puller belongs.
- **Measured archive facts** (28 occurrences under `pull_transcript/`, verified this run): every occurrence's files are named `<date> <title>.<ext>` with `date`/`title` exactly matching its `_source.json` — 28/28, one stray non-stem `.txt` in `vendor Contract Data Template Mapping Review- NA/7.14.26/`. 28 `.txt`, 20 `.vtt`, 8 `.mp4`. Canonicalized Stream URLs are unique 28/28. Filename stamps: 9 `UTC`-suffixed, 17 un-suffixed, 2 absent → 9 `second` / 19 `day`. `_source.json` `dateSource` values: 21 `migrate-layout.js (from pulls.jsonl)`, 6 `the recording's createdDateTime`, 1 `the date in the recording's name`. `Recordings and Transcripts/` holds batch-mirror subfolders with no `_source.json` — the scan must key on the sidecar, not on an `M.D.YY` name pattern.

## Tasks & Acceptance

**Execution:**
- `pull_transcript/emit-drop.js` -- new module + CLI. Pure mapping helpers (`canonicalSourceId`, `startedAtFrom`, `dropName`, `planDrop`) plus `emitDrop` (staging → atomic rename → status) and `postIngest`. CLI flags: occurrence dirs positionally, `--all`, `--dry-run`, `--drops`, `--api`, `--no-post`, `--corpus`. Exports the helpers for the test suite. -- Keeps the mapping testable without a browser and gives the backfill and the live hook one implementation.
- `pull_transcript/grab-teams-transcript.js` -- require `emit-drop.js`; after `writeSource`/`logPull` in the `if (!outFile)` branch, emit the drop and POST it inside a try/catch that only warns; add `--no-emit`, `--drops`, `--api`, `--corpus` to arg parsing and the usage text. -- Closes the live "pull → emit → POST" leg without changing the pull itself.
- `pull_transcript/test/emit-drop.test.js` -- new `node:test` suite: build fixture occurrence dirs in a temp tree, run `emitDrop`, validate every emitted `metadata.json` against `docs/source-drop.schema.json` with ajv 2020-12 + `ajv-formats`, and cover each I/O Matrix row that does not need a live api (both precision paths, ignored files, stray transcript, transcript-only, recording, re-emit, missing evidence, malformed sidecar, dry-run). Skip with a named reason when the schema file is absent (standalone checkout). -- The puller half of the "both suites validate against the schema" AC.
- `pull_transcript/package.json` -- add `ajv` + `ajv-formats` as `devDependencies`, a `test` script (`node --test test/`), and an `emit-drop` bin entry; `pull_transcript/package-lock.json` updated by the install. -- Node has no built-in JSON-Schema validator; independent validation needs one.
- `pull_transcript/.gitignore` -- allowlist `emit-drop.js`, `test/`, `test/*.js`. -- The deny-all allowlist would otherwise leave the new files untracked and silently absent from the commit.
- `pull_transcript/README.md`, `pull_transcript/CLAUDE.md` -- document the emit-drop step, the drops folder and its overrides, `--all` backfill, `--no-emit`, and the UTC-stamp precision rule. -- CLAUDE.md is the puller's own handoff doc; an undocumented emit step is invisible to the next agent.
- `infra/Makefile` -- add `puller-test` (runs `npm test` in `pull_transcript/`, with a named skip when `node_modules` is absent), make `test` depend on it, and install the puller's dev deps in `bootstrap`. -- Otherwise the puller suite never runs and the AC's "both suites" is untrue in practice.

**Acceptance Criteria:**
- Given the 28-occurrence archive and an empty drops folder, when `node emit-drop.js --all --no-post` runs, then 28 drops are finalized, each containing `metadata.json` plus only the canonical evidence files present for that occurrence, with 8 carrying `recording.mp4`, 20 carrying `transcript.vtt`, and 28 carrying `transcript.txt`.
- Given those 28 emitted drops, when each `metadata.json` is validated against `docs/source-drop.schema.json`, then all pass, `corpus` is `real` throughout, and precision splits 9 `second` / 19 `day`.
- Given a drops folder already holding the 28 finalized drops, when the same `--all` pass runs again, then all 28 report `exists`, no file inside any drop changes (mtimes and contents identical), and no staging directory remains.
- Given the api is running with migrations applied, when `node emit-drop.js --all` runs, then each drop is POSTed to `/ingests`, fresh drops return `201` with a `jobId`, and a repeat run reports every one as an already-ingested `409` without erroring.
- Given `npm test` in `pull_transcript/`, when it runs, then the puller suite passes and independently validates emitted metadata against the shared schema.
- Given the black-box seam, when the change is reviewed, then `emit-drop.js` and `grab-teams-transcript.js` import nothing from `server/`, read no `config.yaml` or `.env`, load the schema only in tests, and add no credential file.
- Given `make test`, when it runs, then the server suite, the puller suite, and the web build all pass.

## Spec Change Log

- 2026-08-18 — `package.json`'s `test` script is `node --test test/*.test.js`, not the spec's
  `node --test test/`. Node 22 resolves a bare directory argument as a module path and dies with
  `Cannot find module .../test`; the glob is the working form of the same thing.
- 2026-08-18 — `startedAtFrom` adds one fallback the I/O matrix leaves undefined: when `_source.json`
  has no parseable `date` **and** the recording name carries a non-UTC stamp, the stamp's calendar
  day is used at `T00:00:00Z`, `day` precision. The organizer-timezone stamp still names the right
  day, which is exactly the resolution `day` claims. All 28 archive occurrences have a usable
  `date`, so this path is fixture-only today; with neither signal the occurrence is skipped.
- 2026-08-18 — `--replay` forwards `--no-emit` / `--drops` / `--api` / `--corpus` to the pulls it
  spawns. Not in the task list, but without it `--replay --no-emit` would silently emit drops.
- 2026-08-18 — the `--all` backfill was run into the real default drops folder
  (`/Users/devopsterus/current/meetingminer-drops`), not a temp dir as the Verification block wrote:
  a temp drops root would leave 28 job rows pointing at paths that vanish, and the permanent folder
  is the corpus later pipeline stories need.

## Review Triage Log

### 2026-08-18 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 21: (high 1, medium 4, low 16)
- defer: 2: (high 0, medium 2, low 0)
- reject: 11: (high 0, medium 0, low 11)
- addressed_findings:
  - `[high]` `[patch]` `parseStamp`/`parseOccurrenceDate` accepted impossible clock fields and non-existent calendar days, so a malformed recording name emitted a write-once drop the api rejects with 422 forever — fixed to raise `SkipError` before anything is written.
  - `[medium]` `[patch]` `make test` was green with the whole puller suite skipped on any checkout that had not run `make bootstrap` — the guard now fails when this repo's puller is present with dev deps missing, and checks `ajv-formats` as well as `ajv`.
  - `[medium]` `[patch]` A corrupt schema or missing validator downgraded AD-1's contract check to a skip — schema-absent now skips with a named reason, schema-present-but-unusable fails loudly, and the behavioral metadata assertions moved out from behind that gate.
  - `[medium]` `[patch]` `postIngest` had no timeout, so an api that accepted the connection and hung blocked the pull indefinitely — added `AbortSignal.timeout`.
  - `[medium]` `[patch]` The rewritten flag/positional parsing in `grab-teams-transcript.js` — the code that decides whether the hand-off runs at all — had no test loading it; lifted into an exported pure `parseGrabArgs` and covered.
  - `[low]` `[patch]` `emit-drop.js`'s `parseArgs`/`main` were unexported and untested, so `--dry-run` and `--no-post` could break in the wiring while function-level tests passed — both exported and driven in-process against a stub api.
  - `[low]` `[patch]` `MM_DROPS_ROOT` / `MM_API_URL` / `MM_CORPUS` resolution was untested — added precedence and trailing-slash tests.
  - `[low]` `[patch]` A value flag followed by another option, a repeated value flag, `--all` plus listed directories, and single-dash unknown options were all silently mis-parsed — each is now a named error in both parsers.
  - `[low]` `[patch]` `canonicalSourceId` built a `null`-origin id from a non-http(s) URL — now a `SkipError`.
  - `[low]` `[patch]` An existing non-directory at the drop path was reported as `exists`, permanently hiding the occurrence — now a named error.
  - `[low]` `[patch]` The puller's undated layout produced a leading-space stem matching nothing — stem falls back to the bare title when `date` is empty.
  - `[low]` `[patch]` A backfill that skipped every occurrence exited 0 — now non-zero when nothing was emitted and something was skipped.
  - `[low]` `[patch]` An unreadable subtree vanished silently from `--all` — now named on stderr.
  - `[low]` `[patch]` The intake-failure retry hint printed a cwd-relative path — now absolute.
  - `[low]` `[patch]` `MM_CORPUS` was validated in `emit-drop.js` but not in `grab-teams-transcript.js`, surfacing only after a completed pull — validated before the browser launches.
  - `[low]` `[patch]` `.gitignore` allowlisted only `test/*.js`, which would silently drop future fixtures — widened to the directory's contents.
  - `[low]` `[patch]` No `engines` field though `fetch` and `node --test` need Node 18+ — added.
  - `[low]` `[patch]` The store-free puller suite ran after `infra-up` — reordered so it fails before Docker starts.
  - `[low]` `[patch]` `server/tests/test_makefile_procs.py` gained a backstop asserting `test:` still lists `puller-test` before `infra-up` and that the recipe fails rather than skips.
  - `[low]` `[patch]` Makefile help line was misaligned — fixed.
  - `[low]` `[patch]` Suite grew 29 -> 72 tests as a result of the coverage findings above.

Supporting detail for the pass:

- **Correctness (1–5).** Impossible clock fields and non-existent calendar days now raise
  `SkipError` in `parseStamp`/`parseOccurrenceDate` before anything is written (a finalized
  write-once drop the api 422s could never be ingested and may never be deleted); `postIngest`
  carries `AbortSignal.timeout` (30s default, `opts.timeoutMs`); `canonicalSourceId` rejects
  non-http(s) URLs whose origin stringifies as `null`; an existing non-directory at the drop path
  is a named error rather than `exists`; the puller's undated layout (`<title>.<ext>`, empty
  `date`) maps instead of building a leading-space stem that matches nothing.
- **Verification holes (6–11).** `make puller-test` now FAILS when this repo's puller is present
  with dev deps missing (skip only when the directory is absent) and checks `ajv-formats` as well
  as `ajv`; the test file distinguishes schema-absent (named skip) from schema-present-but-unusable
  (loud failure at load) and the behavioral assertions moved out from behind that gate;
  `server/tests/test_makefile_procs.py` gained a backstop that `test:` still lists `puller-test`
  before `infra-up`; `grab-teams-transcript.js`'s flag parsing was lifted into an exported pure
  `parseGrabArgs` (the CLI now runs only under `require.main === module`) and covered;
  `emit-drop.js` exports `parseArgs`/`main`, both tested including in-process runs against a stub
  api; the three `MM_*` env vars are tested for precedence and the trailing-slash strip.
- **CLI robustness (12–19).** A value flag followed by another option, a repeated value flag,
  `--all` plus listed directories, and single-dash unknown options are all named errors; a pass
  that emitted nothing while skipping something exits non-zero (mixed runs stay 0); an unreadable
  subtree is named on stderr; `grab-teams-transcript.js` validates the resolved corpus (including
  `MM_CORPUS`) before the browser launches and prints an absolute path in its retry hint.
- **Packaging (20–21).** `.gitignore` allowlists `test/**` rather than `test/*.js`; `engines.node
  >= 18`; `puller-test` runs before `infra-up`; help column realigned.

Suite grew 29 → 72 tests.

## Design Notes

**`sourceId` — canonicalized Stream URL.** AD-1 offers "recording drive-item ID or Stream URL". The raw `_source.json` `url` carries `referrer`/`referrerScenario` params that vary with how the user copied the link, so using it verbatim risks two job rows for one occurrence. Emit-drop keeps only the identifying `id` param:
`https://<host><path>?id=<percent-encoded server-relative recording path>` — still a valid Stream URL, stable across re-pulls, and unique across all 28 occurrences. The drive-item id is not used: it is only available from live player traffic, so the backfill could not produce it.

**`startedAt` precision — the `UTC` suffix is the discriminator.** Teams stamps recordings `-YYYYMMDD_HHMMSS[UTC]-`. Only the `UTC`-suffixed form names an instant; the puller's own CLAUDE.md records that un-suffixed stamps use the *organizer's* timezone, which the puller does not know. Converting one anyway would write a wrong UTC instant under `startedAtPrecision: "second"`, which the schema defines as "a real time of day". So: `UTC` stamp → that instant, `second`; anything else → the occurrence date at `T00:00:00Z`, `day`. Nothing is lost — the un-suffixed stamp survives verbatim inside `provenance.recordingName` for a later, better-informed pass. This also makes all three `dateSource` variants fall out of one rule rather than three branches.

**Drop directory name.** `<YYYY-MM-DD>-<title-slug>-<sha1(sourceId)[0:8]>` — human-scannable, and deterministic from `sourceId` so write-once detection is a plain `existsSync` on a stable path.

**Verification split (state this plainly; do not imply otherwise).** This checkout is a fork of the puller, not the user's working copy, and live pulls run against the corp production tenant on another machine. Verified here: the emit-drop mapping, the backfill over all 28 occurrences, write-once on re-emit, POST `/ingests` against the local api, and the puller schema suite. **Not verified here:** the live "paste a recap URL → pull → emit → POST" leg, which needs a live Teams session and must not run unattended. It is implemented and its two halves are exercised separately; the end-to-end leg is for the user to run on their working copy.

**Copy, don't clone semantics.** Files are copied with `fs.copyFileSync(..., fs.constants.COPYFILE_FICLONE)` — an APFS clone when possible, a real copy otherwise — so the 8 recordings cost no extra disk while the drop stays independent of the archive that re-pulls mutate.

## Verification

**Commands:**
- `cd pull_transcript && npm install` -- expected: adds `ajv` + `ajv-formats`, lockfile updated.
- `cd pull_transcript && npm test` -- expected: all puller tests pass, including schema validation of emitted metadata.
- `node pull_transcript/emit-drop.js --all --dry-run` -- expected: 28 occurrences planned, 0 written.
- `MM_DROPS_ROOT=<tmp> node pull_transcript/emit-drop.js --all --no-post` -- expected: `created 28`; file counts 28 `transcript.txt`, 20 `transcript.vtt`, 8 `recording.mp4`, 0 `.docx`/`.md`; precision split 9 `second` / 19 `day`; no `.staging` residue.
- re-run the same command -- expected: `exists 28`, `created 0`, drop contents byte-identical.
- `make up` then `MM_DROPS_ROOT=<tmp> node pull_transcript/emit-drop.js --all` -- expected: 28 × `201` with jobIds; a second run reports 28 × `409` already ingested, exit 0.
- `make test` -- expected: server suite passes (205+ tests), puller suite passes, web build clean.
- `git status --porcelain` inside `pull_transcript/` -- expected: only the intended tracked files appear; no archive content, `node_modules`, or drops enter git.

**Manual checks (if no CLI):**
- The live leg (recap URL → pull → emit → POST) is **not** run here; the spec's Design Notes record why and hand it to the user's working copy.

## Auto Run Result

Status: done

**Implemented change.** The puller gained an emit-drop step: `emit-drop.js` maps one
`<Title>/<M.D.YY>/` occurrence into a schema-valid source drop — assembled under
`<dropsRoot>/.staging/`, finalized by a single atomic rename, never overwritten — and POSTs its
absolute path to `POST /ingests`. It is both a module and a CLI, so the same implementation serves
the end-of-pull hook in `grab-teams-transcript.js` and the `--all` backfill over the existing
archive. The black-box seam holds: nothing under `server/` is imported, no `config.yaml` or `.env`
is read, and `docs/source-drop.schema.json` is loaded only by the test suite.

**Files changed.**
- `pull_transcript/emit-drop.js` — new. Mapping helpers, `emitDrop` (staging → rename →
  created/exists), `postIngest`, `findOccurrences`, and the CLI.
- `pull_transcript/test/emit-drop.test.js` — new. 72 `node:test` cases; validates emitted
  `metadata.json` against the shared schema with ajv 2020-12 + ajv-formats.
- `pull_transcript/grab-teams-transcript.js` — requires `emit-drop.js`; emits and POSTs after
  `writeSource` in the `if (!outFile)` branch, wrapped so the hand-off can never fail a pull; flag
  parsing lifted into the exported pure `parseGrabArgs`; `--no-emit`/`--drops`/`--api`/`--corpus`
  added and forwarded by `--replay`.
- `pull_transcript/package.json`, `package-lock.json` — ajv + ajv-formats dev deps, `test` script,
  `emit-drop` bin, `engines.node >= 18`.
- `pull_transcript/.gitignore` — allowlists `emit-drop.js` and `test/**`.
- `pull_transcript/README.md`, `CLAUDE.md` — drop layout, overrides, UTC-stamp precision rule,
  write-once, backfill, seam.
- `infra/Makefile` — `puller-test` target (fails rather than skips when this repo's puller lacks
  dev deps), wired into `test:` ahead of `infra-up`; `bootstrap` installs the puller's deps.
- `server/tests/test_makefile_procs.py` — the single server-side change: a backstop asserting
  `test:` still runs `puller-test`.

**Review findings.** 21 patches applied (1 high, 4 medium, 16 low); 2 deferred (both medium, in
frontmatter); 11 rejected. No intent gaps and no spec defects, so no code was reverted.

**Follow-up review recommended: true** — one patched finding was `high` severity (patched counts:
high 1, medium 4, low 16; the high alone sets the flag).

**Verification performed** (every command re-run after the patches):
- `cd pull_transcript && npm test` — 72 tests, 72 pass, 0 fail, **0 skipped**.
- `node pull_transcript/emit-drop.js --all --dry-run` — planned 28, skipped 0, failed 0, nothing written.
- `MM_DROPS_ROOT=<tmp> … --all --no-post` — created 28. 28 `metadata.json`, 28 `transcript.txt`,
  20 `transcript.vtt`, 8 `recording.mp4`, 0 `.docx`/`.md`, 0 staging residue.
- Schema validation of those 28 with the server's `jsonschema` + `FormatChecker`: 0 invalid,
  precision 9 `second` / 19 `day`, `corpus: real` ×28, 28 unique `sourceId`s.
- Re-run of the same command — created 0, exists 28; all 84 files byte-identical by sha1.
- `node pull_transcript/emit-drop.js --all` against the live api — 28 already ingested (409), exit 0.
  Postgres holds 28 job rows at the drops root with 28 distinct `source_id`; `probe`/`frames` are
  `done` on exactly the 8 drops with recordings and `skipped` on the 20 transcript-only ones.
- Guard behaviour: `make puller-test` exits 0 with deps present, exits non-zero when this repo's
  puller lacks `ajv-formats`, and skips with a named reason only when the puller directory is absent.
- `make test` — exit 0: puller 72/72 (0 skipped), pytest 206 passed, web build clean.
- I/O matrix audit: all 15 rows covered by tests that ran and passed.

**Residual risks.**
- The live "recap URL → pull → emit → POST" leg was not exercised. This checkout is a fork of the
  puller, and a live pull needs a Teams session against the corp production tenant, which must not run
  unattended. Both halves are verified separately; the end-to-end leg is for the user's working copy.
- The backfill was emitted into the real default drops folder rather than a temp root (recorded in
  the Spec Change Log): a temp root would leave 28 job rows pointing at paths that vanish.
- Two deferred findings remain open — see frontmatter `deferred`.
