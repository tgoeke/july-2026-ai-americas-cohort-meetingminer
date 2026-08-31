# Review handoff — Story 6.4: Acquisition Launch Surface

## What you must produce, before anything else

Write your report to
`_bmad-output/implementation-artifacts/review-story-6-4-2026-08-30.md`.

**Create and commit that file as a skeleton — scope, range, an empty findings
section — BEFORE you read a line of code.** Then append each finding as you
confirm it and commit incrementally. Reviews in this repository have repeatedly
produced their report only as terminal text, or finished a session and filed
nothing, because the file requirement sat at the tail of a long prompt. A
crashed or closed session must lose prose, never the artifact.

Each finding carries: **Location / Severity / Finding / Evidence / Suggested
direction.**

**This review lane fixes what it finds** (owner ruling, 2026-08-30). Report
every finding in the report file first — report-first, committed before you
read code. Then FIX the patchable ones yourself on `story/6-4-review`, cut from
`story/6-4`, in its own worktree (`make worktree STORY=6-4-review` — never the
main checkout). Red-first: the test observed failing against the unfixed code,
then the fix, then green, committing each with its finding number. Hand nothing
back to a builder.

Leave unfixed, and clearly marked open, only what needs an owner decision or is
rooted in the frozen spec. Never commit to `main`, never work in the main
checkout, never merge — the owner runs `integrate`.

**Closeout.** Before reporting completion, run `make check-reviews` — it fails
while any dispatched review lacks a committed report, including this one — and
state the SHA carrying the report's final version. A review reported in the
terminal but not filed does not exist.

---

## Repo, branch, range

- Worktree: `/Users/devopsterus/current/cohort/meetingminer-wt/6-4`
  (never edit `/Users/devopsterus/current/cohort/meetingminer`)
- Branch under review: `story/6-4` (pushed to `origin`)
- Review range: `ea0c113e90883ebdb5cc150536b2f260dd6326fb..HEAD`

Every commit in the range belongs to story 6.4. `1c10ecd` is the spec commit
the build started from; everything after it is this story's implementation and
its tracking.

`git log --oneline ea0c113..HEAD` gives the current list.

## Spec

`_bmad-output/implementation-artifacts/spec-6-4-acquisition-launch-surface.md`

- **Frozen intent** — everything inside `<intent-contract>`: Intent, Boundaries
  & Constraints, and the I/O & Edge-Case Matrix. A defect whose root cause is in
  there is reported and left open, never patched.
- **Planner work you may attack** — Code Map, Tasks & Acceptance, Design Notes,
  Verification, Spec Change Log, and the `deferred` frontmatter.

The story's own text (FR34) is in `_bmad-output/planning-artifacts/epics.md`
under "Story 6.4". The build prompt is
`build-prompt-story-6-4-2026-08-30.md`; the wave rules are
`wave-2026-08-30-rules.md`.

## Architecture authority

- **AD-11 — the api accepts work, the worker performs it.** The whole story.
  A request handler that downloads, converts, or runs pipeline work is a
  correctness failure, not a style one.
- **AD-14 — `POST /ingests` is the only intake door.** The detached runner
  reaches intake through `mintdrop.post_ingest` and nowhere else.
- **AD-1 — a drop is write-once evidence**, and its wall clock is never
  guessed. Inherited from 6.2 through `acquire()`, which is called unchanged.
- **Story 2.8's registry contract** (`server/meetingminer/api/registry.py`):
  a literal path under a parameterized sibling registers first, or is
  swallowed. Resolved here *inside* the router by declaration order, the
  `media.py` way.
- **Story 1.10, finding 17**: a repo-relative path anchors on
  `config.config_path.parent`, never on `__file__`.

## Scope

In scope — five changed paths, and no others:

- `server/meetingminer/acquisitions.py` — **new**. Status-file schema and
  atomic writes, the source-id claim lock, `launch()`, the child runner, the
  `REMEDIATIONS` / `PROBLEM_STATUS` tables, `log_tail()`.
- `server/meetingminer/api/acquisitions.py` — **new**. The three routes.
- `server/meetingminer/youtube.py` — one addition (`ProbeReport`,
  `probe_only`). No existing function changed or forked; verify that.
- `server/tests/test_api_acquisitions.py` — **new**. All coverage.
- `server/tests/test_api_registry.py` — one `BASELINE_ROUTER_ORDER` entry plus
  its rationale comment, pre-declared in the Spec Change Log.

Plus tracking: the spec, `sprint-status.yaml`, `sprint-notes.md`.

Out of scope:

- Stories 6.4a (upload sessions), 6.5 / 6.5a (the Add-meeting UI), playlists
  through the api, and cancelling, deleting or listing an acquisition. All are
  in the spec's Never list.
- `docs/project-record.md`, written at integration.
- `docs/backlog.md`, `AGENTS.md`, `README.md`, `infra/Makefile`,
  `server/tests/conftest.py`, `server/meetingminer/mintdrop.py`,
  `server/meetingminer/config.py`, anything under `web/` — off limits to this
  lane by the build prompt and the wave rules.
- The five items in the spec's `deferred` frontmatter are already recorded.
  Confirm or challenge the triage; do not re-report them as new.

## Design decisions to attack

Each is a choice plus the assumption under it. The builder is not a neutral
judge of its own calls.

1. **Liveness is a directory scan, not a registry.** "Is a second acquisition
   running for this source id?" is answered by globbing `*.json` under one
   `fcntl.flock` and checking `os.kill(pid, 0)`. Assumption: pid reuse is rare
   enough that one spurious 409 (which a rerun clears) is cheaper than a launch
   that races a live download. Attack it two ways: is pid reuse actually the
   only false positive, and does the scan cost matter as the directory grows
   unreaped? (The growth is deferred item 5.)

2. **The api holds the claim lock across the `Popen`.** The lock is taken,
   the directory scanned, the record written, the child started, and the pid
   recorded, all before release — so a `Popen` that hangs holds a lock every
   other launch waits on for up to `CLAIM_LOCK_TIMEOUT_SECONDS` (10). The
   alternative — release before `Popen` — reopens the race the lock exists to
   close. Attack the trade, and attack the timeout value.

3. **`meetingId` is deliberately not in the status file.** The api resolves it
   per read from `meeting.job_id`, so a later poll shows it appear. Assumption:
   a per-poll single-row query on a `NOT NULL UNIQUE` column is cheaper than
   the coordination a written-back id would need between the runner and the
   worker. Consequence: every status poll of a `posted` acquisition takes a
   pool connection. Is that acceptable for a UI that polls?

4. **The runner re-loads its own config through
   `mintdrop._load_cli_config()`.** An `AppConfig` cannot cross a process
   boundary, so the child reads `config.yaml` and `.env` from disk and inherits
   `MM_CONFIG_PATH` from the api's environment. Consequence, and the single
   exception to "the log tail is never the source for why": a `ConfigError` at
   child start has no status directory to write into, so it prints to stderr
   and exits, leaving the record `queued` with a dead pid. Deferred item 3
   names two possible remedies. **Press on whether one of them should have
   been built here.**

5. **`PROBLEM_STATUS`'s three buckets.** `not-a-video-url` is 400; the
   host-side rules (`tool-missing`, `tool-unrunnable`, `tool-timeout`,
   `version-failed`, `version-empty`, `config`) are 503; everything else is
   422. Attack the membership rule by rule — `probe-failed` on a private video
   is arguably the client's problem and is 422; `drops-root-changed` is
   arguably the host's and is 422 too.

6. **Both tables are literal dicts, not comprehensions over `REFUSAL_RULES`.**
   Deliberate: a comprehension would give a rule added later a silent default
   and make the completeness test vacuous. Cost: thirty hand-written entries
   that a careless edit can desynchronize. Is the test enough of a guard?

7. **An intake failure keeps `rule: "unclassified"`.** `refusal_rule()`
   classifies an `IntakeError` that way and the builder kept it, on the
   grounds that the *tool* refused nothing — the api did not answer — and gave
   the row its own remediation (the exact `curl` re-POST for the finalized
   drop) rather than the table's generic one. The competing reading is that a
   distinguishable failure deserves a distinguishable token, which would mean
   extending `REFUSAL_RULES` — a `youtube.py` change beyond the one addition
   the footprint allows. **This is the most likely candidate for "right
   finding, wrongly deferred".**

8. **`probe_only` reuses `validate_info`, so a probe also refuses
   `channel-missing` and `started-at-unknown`.** The build prompt names "URL,
   availability, stream, tool and duration checks"; `validate_info` is a
   superset. Assumption: a pre-submit check that accepts what the acquisition
   would then refuse is worse than one that is slightly stricter than
   advertised. Attack the reading.

9. **`duration_ms` rather than `durationSeconds`.** The probe answers in
   milliseconds because every other duration on the api's wire is in
   milliseconds, while the drop's own provenance records `durationSeconds`.
   Two units for one fact, in two places. Check the rounding at the boundary.

10. **The test suite starts a real `/bin/sleep` child.** The launch path is
    exercised for real — the same `Popen`, the same detached session, the same
    log file — with only the program swapped, so a status record's pid is
    genuinely alive. Assumption: that is safer than stubbing `Popen`, because
    stubbing it would stop testing the thing the story is about. Attack the
    portability and the reaping.

## Verify these clauses directly, they are what the story is

- **The request handler does no acquisition work.** `no_acquisition_work` is an
  autouse fixture making `youtube._run`, `youtube.download` and `mint()`
  must-not-run. Confirm nothing bypasses it.
- **`failed` explains itself with no log.** Two tests assert
  `refusal.{rule,detail,remediation}` with the log file empty and with no log
  file at all. This is the clause most likely to rot; confirm the api never
  reads `logTail` to build `refusal`.
- **The `exists` short-circuit makes no yt-dlp call.**
  `test_an_already_minted_drop_reaches_posted_exists_with_no_yt_dlp_call` runs
  the real `acquire()` against a real existing drop with `shutil.which`
  returning `None` and every yt-dlp invocation an error. Reaching `posted`
  proves neither ran.
- **`/acquisitions/probe` is not swallowed.** Asserted twice: as a declaration
  order inside the router, and as a live 200 on the discovery-registered app.
- **No request can name a file.** Every path segment is a typed `UUID`.

## Verification baseline

Current results on `story/6-4` — a skip or failure during review is a finding,
not noise:

- `uv run --project server pytest server/tests/test_api_acquisitions.py -q`
  → **34 passed**
- `uv run --project server pytest server/tests/test_api_registry.py
  server/tests/test_youtube.py server/tests/test_youtube_playlist.py -q`
  → **201 passed, 1 skipped** (the network test, env-flagged as 6.2 left it)
- `make test-fast` → lint **clean**, mypy **clean (13 files)**, server
  **1996 passed, 2 skipped, 378 deselected**
- `make test` → **2374 passed, 2 skipped** in 10m18s, web build clean. The two
  skips are the pre-existing env-flagged ones `make test-fast -rs` names by
  reason: 6.2's real-network yt-dlp test (`MM_YOUTUBE_NETWORK_TEST=1`) and
  `test_diarize_pyannote.py`, whose extra `diarize-extra-test` runs in its own
  isolated lane.
- `python3 _bmad/scripts/branch_conflicts.py --against story/6-4` → clean
  against `main` and against `story/10-2-review`, `story/7-3`, `story/8-2`.
  `story/10-2` conflicts on `sprint-notes.md` only — that branch already
  conflicts with `main` on the same file, so it is pre-existing and integrate
  unions it.

**Red-first evidence.** The tests were written after the code, so their
coverage was proved by mutation instead: fourteen single-edit mutations across
the three source files and the registry baseline — liveness removed, a
remediation key renamed, a status entry deleted, the pre-`Popen` write removed,
`refusal_for` dropped from the failure path, the re-POST command dropped from
the intake remediation, the partial-line trim disabled, offline URL
classification bypassed, `source` suppressed, the meeting query stubbed,
`ensure_tools` dropped from `probe_only`, the ms conversion dropped, the blank-
title fallback weakened, and the registry entry removed. **All fourteen turned
a test red**; none passed silently. The harness is
`scratchpad/mutate.py` (not committed — reproduce it or trust the list).

## History you need to tell a regression from a pre-existing condition

- The branch was cut from `main` at `ea0c113` and has **not** been rebased.
  Story 11-2 had already landed, so this worktree runs a private Docker stack.
- `sprint-notes.md` conflicts with `story/10-2`. That branch already conflicts
  with `main` on the same file. Pre-existing; integrate absorbs it.
- `make client` was **not** run — `web/` is outside the footprint and the
  command needs a running api, which this wave forbids starting. This is the
  epic's last acceptance clause and is deliberately unmet. It is deferred item
  1, severity high, and **story 6.5 is blocked on it**. Report it if you like,
  but do not fix it here: `web/` is out of scope for this lane too.
