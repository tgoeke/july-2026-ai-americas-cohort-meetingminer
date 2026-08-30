# Review handoff — Story 2.1a: Evidence Paths Anchored to Configured Roots

You are reviewing a completed, verified story branch. You have none of the build
run's context; everything you need is below. **Report findings — do not apply
fixes.**

## Where the code is

- **Repo:** `/Users/devopsterus/current/cohort/meetingminer`
- **Worktree:** `/Users/devopsterus/current/cohort/meetingminer-wt/2-1a`
- **Branch:** `story/2-1a`, pushed to `origin/story/2-1a`, in sync (`0 0`)
- **Review range:** `fc5c656..HEAD` (HEAD = `ee26915a69ac5fbabd925c87e053cc1f15d79365`)

`fc5c656` is the tip of `main` this branch forked from. Every commit in the
range belongs to story 2.1a — there is no foreign commit to skip.

| Revision | Subject |
|---|---|
| `8394da287986f52bfe74760ee5d68cbbff91e3ad` | docs(spec): mark story 2.1a in-progress with baseline revision |
| `3216ccc5e6a8f39c047ad83c00339c32e924f6d9` | feat(2.1a): anchor drop paths to a configured MM_DROPS_ROOT at intake |
| `acda3123f1bc13da1efdca3fdb0897e99ee72471` | feat(2.1a): resolve drops through the configured root in worker and api |
| `8a8eb6e9c6168f9f05b6e95dc2cec3e806425205` | feat(2.1a): add the fail-closed drop-path backfill command |
| `141be66cbcb4cd86503d53d8894abb0df889eca0` | test(2.1a): build every fixture drop under a session MM_DROPS_ROOT |
| `629b3de30e965a2e712063b663c04994d41f1c8a` | test(2.1a): cover the drops-root anchor, provenance row and backfill |
| `7f03b44bf4ad48819c54cb3052c2f38ae959df2b` | fix(2.1a): stop GET /jobs from returning an absolute drop path |
| `d57e489f02a1fab6a8b4990bb9863b1b7b0a3ebe` | chore(2.1a): expose the backfill as a make target |
| `ab2f60e29f60739aa618618a31e995d77b29c938` | test(2.1a): pin the startup gate through the real entry points |
| `e5ec5ccce576e09cd2395cdfdcae12d4f8255285` | docs(2.1a): record the three deferrals this story leaves behind |
| `4efbc797ad53bf5269115e136cc85b86e8eaff0a` | fix(2.1a): assert the relative drop path in the three missed re-arm tests |
| `966e4a30912545c48ad77901e66f60c18ef1cbba` | fix(2.1a): stop a too-early worker costing an operator its jobs |
| `3d521975a4ec6d975cec69d70b858db797567f4c` | fix(2.1a): keep transcript-only replay a 404, and name each root's fault |
| `ae3b88cb0eaddcedc4c7a8fddeb3e384e58c7dc2` | fix(2.1a): make the anchor rule the database's, not a convention |
| `1c95f8af3b3661a4998bf09dcff8805c7e580ab1` | chore(2.1a): fail early on a .env with no drops root; correct SPEC.md |
| `a151092f13c28d2ac4a75c48c7a8e1ec9f275231` | test(2.1a): pin every guard the review found deletable |
| `33cfc0aad08cf35ce43f3975d7cca04131ce67dd` | test(2.1a): keep the api config preflight test testing the preflight |
| `9863d1adb13eee65c18f12d59d18bdeaf24a508b` | docs(2.1a): note the second storage root in the worktree .env rule |
| `45ea1f7fedfcc100735b4f87ff45ed4b135dfc34` | fix(2.1a): keep the make-up ordering tests testing ordering |
| `ee26915a69ac5fbabd925c87e053cc1f15d79365` | docs(2.1a): record the review triage, deferrals and run result |

Commits `966e4a3` onward are the response to an automated review that already
ran. Treat them as part of the change under review, not as settled.

## The spec, and which half you may attack

`_bmad-output/implementation-artifacts/spec-2-1a-evidence-paths-anchored-to-configured-roots.md`

- **Frozen — do not treat as negotiable.** Everything inside `<intent-contract>`:
  the Intent, Boundaries & Constraints, and the I/O & Edge-Case Matrix. If the
  code contradicts this, that is a finding.
- **Planner work — fair game.** Code Map, Tasks & Acceptance, Design Notes,
  Verification, and the Review Triage Log. These were written by the build run
  and can be wrong. One is already known wrong and was corrected during the run:
  the Execution list named a `meeting_media.byte_size` column that the frozen
  `Always` constraint forbids.

## Architecture authority

- `_bmad-output/specs/spec-meetingminer/storage-layout.md` — the governing
  companion. §1 (two roots, both permanent, why the drops root is not a landing
  zone), §4 (the anchor rule: every recorded path relative to exactly one root),
  §5 (checksum handling by anchor). Cited by the spec's `context:`.
- `_bmad-output/specs/spec-meetingminer/SPEC.md` — spine decision records
  **AD-1** (drops are write-once and permanent), **AD-3** (the content root; its
  single sentence names only that root, which is why a reviewer comparing the
  recording against it reports a violation that is really an undocumented rule),
  **AD-11** (stage-then-replace), **AD-13** (nothing writes inside a drop),
  **AD-14**. This story edited SPEC.md:73, which previously stated 2.1a's three
  defects as still open.
- `_bmad-output/implementation-artifacts/spec-2-1-media-streaming-replay-foundation.md`
  — story 2.1, merged, which built the replay route this story re-points.

## Scope

**In scope** — `server/meetingminer/{config,backfill}.py`,
`domain/{drops,jobs}.py`, `api/{ingests,media,jobs,problems,main}.py`,
`worker/main.py`, `pipeline/{runner,stage}.py`,
`pipeline/stages/{probe,align,transcribe}.py`,
`migrations/0008_drop_root_anchored_paths.sql`, `server/tests/**`,
`infra/Makefile`, `.env.example`, `AGENTS.md`, `SPEC.md`, the story spec, and
`web/src/client/types.gen.ts`.

**Out of scope**

- Story 2.1's media HTTP contract itself (URL, range behaviour, problem
  responses) — merged and deliberately untouched, except as noted below.
- Story 5.2, running in parallel on `story/5-2`. Zero file overlap: that branch
  touches `evals/` and one AGENTS.md hunk far from this one. Neither branch
  contains the other.
- The seven items already recorded in the spec's `deferred` frontmatter and the
  three in `deferred-work.md`. Re-reporting them is noise; finding one is
  *worse* than recorded is a finding.

## Design decisions to attack

These are the build run's own calls. The planner is not a neutral judge of them,
which is why they are handed over rather than left to be rediscovered.

1. **The recording is not copied.** The superseded story proposed copying it
   under `MM_CONTENT_ROOT` for literal AD-3 compliance. **Assumption:** AD-1
   makes the drop permanent, so a copy would be a second permanent copy of a
   permanent file (19.5 GB across 85 mp4s), and it would fix replay while
   leaving transcript re-parse and the augmentation door still resolving through
   an absolute path. Attack the premise that the drops root is truly permanent —
   `storage-layout.md` §1 asserts it, and the whole design collapses if it is
   wrong.

2. **Replay now 404s during the ingest window.** `mint_meeting`
   (`pipeline/runner.py:104`) creates the meeting at claim time; `probe` writes
   `meeting_media.drop_relative_path` later. In between, `GET
   /media/recordings/{id}` sees `has_recording = true` with a NULL path and
   returns 404 `media-not-found`. **Pre-2.1a it streamed**, because
   `job.drop_path` and `RECORDING_FILENAME` were both available at claim time.
   **Assumption:** a recording mid-ingest is not meaningfully servable, so a 404
   is honest. The frozen `Never` list says the media route keeps "its problem
   responses" and the matrix has no row for this state. This is the single most
   important item in this handoff. It was deliberately not patched: the only
   route back to the old behaviour is re-composing the path from the filename
   constant, which is what the story exists to delete.

3. **`meeting_media.size_bytes` changed provenance.** It now holds the size read
   while checksumming rather than ffprobe's number, and `probe` raises
   `StageError` when the two disagree. **Assumption:** since disagreement fails
   the stage, the stored number is identical to ffprobe's on every surviving
   path, so one number that cannot drift beats two that can. An automated
   reviewer flagged this and it was rejected on that reasoning — re-test it.

4. **`GET /jobs/{jobId}` changed shape**, `dropPath` → `dropRelativePath`
   (nullable). **Assumption:** the frozen `Always` rule that no absolute path
   leaves the server outranks an unversioned read field with no caller. This is
   a breaking API change the spec did not authorise in so many words.

5. **`job.drop_path` is retained**, nullable, behind a `job_has_a_drop` CHECK,
   rather than dropped. **Assumption:** the backfill must read it, and a
   deployment may still hold un-backfilled rows.

6. **The backfill re-queues jobs it converts.** It matches `status = 'failed'`
   AND `error` equal to one exact shared constant, in the UPDATE's own
   predicate. **Assumption:** that string is precise enough that no unrelated
   failure is ever resurrected. Attack the matching.

7. **Intake's 400 deliberately names the server's absolute drops root**, while
   the media route refuses to leak any absolute path. Two rules on two routes;
   the matrix row licenses the second. **Assumption:** a caller posting a bad
   path needs to see the root to fix it, and intake is operator-facing.

8. **Migration 0008 was edited in place** rather than superseded by an 0009,
   on the grounds that it is unreleased.

## History you need to tell a regression from a pre-existing condition

- This branch **supersedes** `spec-2-1-recording-under-the-content-root.md`,
  which proposed the copy. That file is absent from `main` and survives only on
  the stale `story/2-1` branch, which should be deleted, not merged. A worktree
  for it still exists at `../meetingminer-wt/2-1`.
- Three `test_ingests.py` assertions failed on the first full run because
  `_job_row` had moved to `drop_relative_path` while they still compared against
  the absolute posted path. Stale expectations, not a code defect; fixed in
  `4efbc79`. The `dropPath` POST bodies correctly remain absolute.
- Three more tests failed later — one in `test_failfast.py`, two in
  `test_makefile_procs.py` — because the new `check-env` gate fires before they
  reach their own subject. Their temp `.env` files were given a drops root. **Two
  neighbouring sites in `test_makefile_procs.py` write the identical `.env`
  string and were deliberately left alone**, because they exercise `.env`
  failure modes where stopping early is the point. If you see an inconsistency
  there, it is intentional.
- An automated review already ran four layers and produced 12 patches, 7
  deferrals, 4 rejections. The full triage is in the spec's Review Triage Log.

## Verification baseline

Re-run these. A skip or failure is a finding, not noise.

- `cd server && .venv/bin/python -m pytest tests/ -q` → **886 passed, 0 failed**,
  ~240s. **Store-backed.** The three Docker stores are one shared stack and the
  fixture drops `meetingminer_test` `WITH (FORCE)`; hold them one agent at a time
  (AGENTS.md). Run directly as shown — going through `make test` reaches
  `check-env`, which fails until `MM_DROPS_ROOT` is in `.env`.
- `make web-test` → **52 passed**, 5 files. Store-free.

**`MM_DROPS_ROOT` is not in the shared `.env`.** Until an operator adds it,
`make test`, `make up`, `make api` and `make worker` stop at `check-env`. That is
the new gate working, not a defect. Direct `pytest` runs are unaffected because
conftest exports its own session root.

The spec's manual checks were **not** performed: relocating both roots by hand
needs a live api, a worker and a real `.env`. `test_relocating_both_roots_breaks_nothing`
covers the guarantee mechanically, but it substitutes a relocated config object
instead of re-reading the environment and restarting the processes — the
env-var-to-running-process leg is unexercised. Worth your attention.

## Required output

Write your findings to
`_bmad-output/implementation-artifacts/review-story-2-1a-2026-08-19.md`.

Structure each finding as: location (`file:line`), what is wrong, the concrete
failure scenario (inputs or state → wrong behaviour), and severity. Separate
confirmed defects from suspicions, and say which you actually executed versus
read. Close with an overall verdict: pass, pass-with-findings, or fail.

**Report findings. Do not apply fixes.**
