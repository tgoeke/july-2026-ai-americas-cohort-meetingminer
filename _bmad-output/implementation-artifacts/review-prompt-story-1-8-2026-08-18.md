# Reviewer handoff — Story 1.8: Teams Puller Emits Source Drops

You are reviewing a completed, pushed change. You have none of the build's
context; everything you need is below. **Report findings — do not apply fixes.**

## Repository and range

- Repo: `/Users/devopsterus/current/cohort/meetingminer`, branch `main`.
- Review range: `acf5d754212aa5538b0958f603245e0145f53ba4..HEAD`.
- Commits in the range, both belonging to story 1.8:
  - `06a90044678ec9628bd7b5b3895846d82a86428a` — feat(puller): story 1.8 — emit source drops and hand them to /ingests
  - `374867f3037bd921a634dd55d7d4df6e13e67500` — docs: story 1.8 spec, with review triage and deferred findings

No commit in this range belongs to another story. Note that the working tree
also carries uncommitted story-1.3 review artifacts (`review-story-1-3-*.md`,
`build-prompt-story-1-3-*.md`, and edits to the 1.3 spec and `sprint-status.yaml`)
that arrived from a parallel review track. **Those are not part of this range and
are not in scope.**

## Spec

`_bmad-output/implementation-artifacts/spec-1-8-teams-puller-emits-source-drops.md`

- Everything inside `<intent-contract>` (Intent, Boundaries & Constraints, I/O &
  Edge-Case Matrix) is **frozen intent**. It came from the epic's acceptance
  criteria and AD-1. Treat it as the contract, not as a proposal.
- Everything outside it — Code Map, Tasks & Acceptance, Design Notes,
  Verification, Spec Change Log, Review Triage Log, Auto Run Result — is
  **planner work you may critique freely**.

## Architecture authority

`_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md`

- **AD-1 — One canonical inbox: the source drop** (line 174) is the governing
  decision. It fixes: write-once drop directories; canonical filenames with all
  other files ignored; assembly in a staging path with atomic finalize; a re-pull
  never overwriting a finalized drop; `sourceId` as "recording drive-item ID or
  Stream URL"; `startedAt` as full ISO 8601 UTC derived from the recording
  filename timestamp when present, else the meeting date at 00:00 UTC, with
  `startedAtPrecision`; `provenance` as the puller's `_source.json` embedded;
  participants as the source side's best-effort job; and the black-box seam —
  the puller shares no server code and no server component calls Microsoft Graph.
- **AD-14 — One intake door** (lines 248–252): `POST /ingests` is the only intake.
- **Line 124**: the puller's only contracts are the drop format and `POST /ingests`.
- **Line 278**: the puller sits outside the `config.yaml` regime and authenticates
  only through its persisted browser session.
- **Line 308**: the drops folder must be distinct from the puller's own working
  archive, which re-pulls mutate in place.
- `docs/source-drop.schema.json` is the frozen contract from story 1.2. It is
  **not** modified in this range and must not be.

## Scope

In scope — the files in the range:

- `pull_transcript/emit-drop.js` (new, 626 lines) — the mapping, staging/finalize,
  `postIngest`, archive scan, and CLI.
- `pull_transcript/test/emit-drop.test.js` (new, 1169 lines) — 72 `node:test` cases.
- `pull_transcript/grab-teams-transcript.js` — the end-of-pull hook, the extracted
  `parseGrabArgs`, and the new flags.
- `pull_transcript/package.json`, `package-lock.json`, `.gitignore`, `README.md`,
  `CLAUDE.md`.
- `infra/Makefile` — the `puller-test` target and its wiring into `test:`/`bootstrap`.
- `server/tests/test_makefile_procs.py` — one added test, the only server-side change.
- The spec document itself.

Out of scope:

- Everything under `server/meetingminer/`, `web/`, `docs/`, and `config.yaml` —
  untouched by design.
- Later stories' functionality: screen identification (1.4), transcript
  verification (1.5), moments (1.6), projections (1.7), UI progress (1.9).
- The two findings already recorded as deferred in the spec's frontmatter
  `deferred` list. Re-reporting them is noise; challenging the *decision to defer*
  is fair.
- The puller's pre-existing scrape, video-download, and Ollama-summary code, except
  where this change touches it.

## Design decisions to attack

These are the planner's own calls. It is not a neutral judge of them, so they are
handed to you deliberately.

1. **`sourceId` is the Stream URL reduced to its `id` parameter.** AD-1 offers
   "recording drive-item ID or Stream URL". The raw `_source.json` `url` carries
   `referrer`/`referrerScenario` params that vary with how the user copied the
   link. *Assumption:* those params are never identity-bearing, and the `id` path
   is stable across re-pulls and unique per occurrence (verified unique 28/28 on
   this archive). *Attack:* is a third derived form legitimate when AD-1 names two
   specific options? Can the `id` path change upstream for the same meeting?

2. **Only a `UTC`-suffixed filename stamp yields `second` precision.** AD-1 says
   `startedAt` comes "from the recording-filename timestamp when present". A
   literal reading gives 26 of 28 occurrences `second` precision; this
   implementation gives 9, because an un-suffixed stamp is in the organizer's
   timezone (per the puller's own CLAUDE.md) and converting it would write a wrong
   UTC instant. *Assumption:* the schema's definition of `second` ("a real time of
   day", full ISO 8601 UTC) overrides the AC's looser wording. *Attack:* this is a
   17-occurrence behavioral difference on the real corpus. Is discarding a known
   local time in favour of midnight-UTC day precision the right trade, given the
   raw stamp is preserved only inside `provenance`?

3. **`participants` is omitted entirely, and a test asserts its absence.** The AC
   lists "best-effort participants" but parenthetically sanctions omission. The
   puller does hold speaker names (the media-API JSON and the `[m:ss] Speaker:`
   export). *Assumption:* story 1.5's derivation — dedup by AAD id or normalized
   display name, alias-resolved — is strictly better than a raw speaker list.
   *Attack:* the assertion makes the omission test-locked rather than merely
   current behavior, closing a decision rather than deferring it.

4. **Drop directory name is `<YYYY-MM-DD>-<title-slug>-<sha1(sourceId)[0:8]>`, and
   write-once detection is `existsSync` on that path.** *Assumption:* the name is
   stable for a given occurrence. *Attack:* it is not stable if a re-pull resolves
   a different date or title — this is one of the two deferred findings; judge
   whether deferring it was right. Also note the date component comes from the UTC
   `startedAt` while the archive folder uses organizer-local `M.D.YY`, so the two
   can disagree by a day.

5. **The drop is finalized before the POST.** *Assumption:* a finalized drop the
   api rejects is recoverable by fixing the input and re-emitting. *Attack:* with
   write-once and no `--force`, the documented recovery is manually deleting a
   directory the tool promises never to delete. Range validation now prevents the
   known trigger, but the shape of the guarantee is worth challenging.

6. **The hand-off can never fail a pull.** Emit and intake failures print a named
   diagnostic and continue, mirroring `generateDocs`. *Attack:* a silently
   un-ingested meeting is now a warning line in a long pull's stderr.

7. **The emit hook fires only for single-recording pulls with no explicit output
   path.** Batch/folder mirroring, `--index`, stdout output, and explicit-`outFile`
   pulls emit nothing. *Attack:* the AC says "when it completes a pull", which
   reads broader than what the hook covers.

8. **`DEFAULT_DROPS_ROOT` is a hardcoded absolute path in one developer's home
   directory**, overridable by `--drops`/`MM_DROPS_ROOT`. This was an explicit user
   decision, not an oversight — but say so if you think it is wrong for a tracked
   file.

## History you need

- The spec was written and the code built in one unattended run from baseline
  `acf5d754212aa5538b0958f603245e0145f53ba4`. There was no rebase, no dropped
  variant, and no superseded baseline.
- One internal review round already ran (four parallel layers). **21 findings were
  patched, 2 deferred, 11 rejected; no code was reverted.** The patches are folded
  into commit `06a9004` — they are not separate commits, so the diff you see is
  post-patch. The full list is in the spec's `## Review Triage Log`. A finding
  already patched there should not resurface; a finding rejected there may, if you
  think the rejection was wrong.
- The test suite grew from 29 to 72 cases during that round, mostly to close
  coverage holes rather than to fix behavior.
- `pull_transcript/` was listed under "Never" in the story 1.2 and 1.3 specs. That
  constraint was scoped to those stories. For 1.8 the puller is explicitly in
  scope: it is a separate fork, freely modifiable, and AD-1 says it "gains
  emit-drop + one-time backfill steps".

## Verification baseline

These all pass as of `374867f`. A skip or failure during your review is a finding,
not noise.

- `cd pull_transcript && npm test` — 72 tests, 72 pass, 0 fail, **0 skipped**.
- `make test` — exit 0: puller 72/72, pytest **206 passed**, web build clean.
- `node pull_transcript/emit-drop.js --all --dry-run` — planned 28, skipped 0, failed 0.
- `MM_DROPS_ROOT=<tmp> node pull_transcript/emit-drop.js --all --no-post` — created 28;
  28 `metadata.json`, 28 `transcript.txt`, 20 `transcript.vtt`, 8 `recording.mp4`,
  0 `.docx`/`.md`, no staging residue.
- Re-running that command — created 0, exists 28, all 84 files byte-identical by sha1.
- Schema validation of the 28 emitted `metadata.json` with `jsonschema` +
  `FormatChecker`: 0 invalid; precision 9 `second` / 19 `day`; `corpus: real` ×28;
  28 unique `sourceId`s.
- `node pull_transcript/emit-drop.js --all` against a running api — 28 already
  ingested (409), exit 0. Postgres holds 28 jobs at the drops root, `probe`/`frames`
  `done` on the 8 with recordings and `skipped` on the 20 transcript-only.
- `make puller-test` — exits 0 with deps present; non-zero when this repo's puller
  lacks `ajv`/`ajv-formats`; skips with a named reason only when the puller
  directory is absent.

**Not verified, by design:** the live "paste a recap URL → pull → emit → POST" leg.
This checkout is a fork of the puller; a live pull needs a Teams session against the
corp production tenant and must not run unattended. Both halves are exercised
separately. Do not report the absence of that run as a finding — but do report any
defect you can see in the hook's code path by reading it.

## Required output

Write your findings to:

`_bmad-output/implementation-artifacts/review-story-1-8-2026-08-18.md`

Structure it as:

1. **Verdict** — does story 1.8 pass? One paragraph.
2. **Findings**, each numbered, with: file and line, what is wrong, the concrete
   scenario that triggers it, and what a fix must achieve. Group by theme.
3. **Specification defects** — anything requiring an amendment inside the spec's
   `<intent-contract>`, called out separately from code findings.
4. **Deferred** — findings you judge real but out of scope for this story.
5. **Verification you ran** — commands and their real results.

Report findings; do not apply fixes.
