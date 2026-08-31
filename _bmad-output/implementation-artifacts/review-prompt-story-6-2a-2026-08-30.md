# Review handoff — Story 6.2a: Playlist Acquisition

## What you must produce, before anything else

**Write your report to
`_bmad-output/implementation-artifacts/review-story-6-2a-2026-08-30.md`.**

Create that file and **commit it as a skeleton — scope, review range, an empty
findings section — BEFORE you read a single line of code.** Then append each
finding as you confirm it and commit incrementally. This is not a style
preference: six reviews in this repository produced their report only as
terminal text and were lost when the session closed. A review reported in a
terminal and not filed does not exist.

Each finding takes this structure:

- **Location** — `path:line`
- **Severity** — high / medium / low
- **Finding** — what is wrong
- **Evidence** — how you know; the command you ran, the line you read
- **Suggested direction** — what a fix must achieve

**The review lane fixes what it finds.** Report every finding in the report
file first (report-first, committed before reading code), then FIX the
patchable ones yourself on `story/6-2a-review` in your own worktree
(`make worktree STORY=6-2a-review BASE=story/6-2a` — never the main checkout),
red-first: the test observed failing against the unfixed code, then the fix,
then green — committing each with its finding number. Leave unfixed, and
clearly marked open, only what needs an owner decision or is rooted in the
frozen spec (`<intent-contract>`). Never commit to `main`, never work in the
main checkout, never merge — the owner runs `integrate`.

**Closeout:** before you report completion, run `make check-reviews` (it fails
while any dispatched review lacks a committed report, including this one) and
state the SHA carrying the final version of your report.

## Repo, branch, range

- Repo: `git@github.com:tgoeke/qcon-cohort-meetingminer.git`, branch
  `story/6-2a` (pushed).
- Review range: `4a111b8..HEAD` — `4a111b8` is the `main` commit this branch
  was cut from.
- Commits in range:
  - `8f00de6` docs: plan Story 6.2a — playlist acquisition spec
  - `efbf274` feat: acquire a whole YouTube playlist (story 6.2a)
  - plus the finalization commit carrying the spec's result, the sprint
    artifacts, this prompt, and one documentation patch to `infra/Makefile` and
    `docs/README.md` (the `PLAYLIST=` truthiness note).
- Every commit in the range belongs to story 6.2a. None belongs to another
  story.

## The spec

`_bmad-output/implementation-artifacts/spec-6-2a-playlist-acquisition.md`.

- The `<intent-contract>` block is **frozen intent** — Intent, Boundaries &
  Constraints, and the I/O & Edge-Case Matrix. A finding rooted there is
  reported and left open for the owner, not fixed.
- Everything outside it — Code Map, Tasks & Acceptance, Design Notes,
  Verification, the Auto Run Result — is planner work you may critique and, if
  wrong, correct.

The story itself is "Story 6.2a: Playlist Acquisition" in
`_bmad-output/planning-artifacts/epics.md` (FR33), three Given/When/Then
clauses. The builder's contract was
`_bmad-output/implementation-artifacts/build-prompt-story-6-2a-2026-08-30.md`
with the standing rules in `wave-2026-08-30-rules.md`.

## Architecture authority

- `docs/architecture.md` **AD-1** (three source producers: the Teams puller, a
  local recording, YouTube — this is the third) and **AD-14** (`POST /ingests`
  is the only intake door; a duplicate source identity does not create a
  duplicate meeting). Every playlist entry must go through that one door, once.
- **AD-13** (a finalized drop is never written into) and the write-once drop
  rule: nothing here may modify an existing drop, including on the `exists`
  path.
- **AD-10** (thresholds live in versioned configuration): this story adds no
  configuration; the duration cap it enforces per entry is story 6.2's
  `acquisition.youtube.max_duration_minutes`.
- `docs/source-drop.schema.json` is the acquisition/ingestion boundary. This
  story mints nothing new — it calls story 6.2's `acquire()` — so a schema
  regression here would mean the shared path was disturbed.

## Scope

**In scope (the whole diff):**

- `server/meetingminer/youtube.py` — the only source file changed.
- `infra/Makefile` — the `youtube-drop` recipe only.
- `docs/README.md` — the "Ingesting a YouTube video" section only.
- `server/tests/test_youtube_playlist.py` and
  `server/tests/fixtures/youtube/flat-playlist.json` — both new.
- `_bmad-output/implementation-artifacts/` — the spec, `sprint-status.yaml`
  (`6-2a-playlist-acquisition: review`), `sprint-notes.md`, this prompt.

**Out of scope:**

- `server/meetingminer/mintdrop.py` — story 6.3 owns it in this same wave.
- `server/tests/test_youtube.py` — read-only for this story by contract. It is
  the regression witness: it must still pass untouched, and it does (110
  passed, 1 skipped). If you believe it needs a change, that is a finding to
  report, not an edit to make.
- `config.py`, `config.yaml`, anything under `web/`.
- Story 6.2's own behaviour, story 6.4's launch surface, story 6.6's deep
  links.
- The `SLOW_TESTS` pin story 6.2 deferred for its network test — already
  recorded, not this story's.

## Design decisions to attack

Each is stated as the choice plus the assumption under it. The builder is not a
neutral judge of its own calls.

1. **`--playlist` is a boolean flag; the URL still arrives as the positional
   `url` (`make youtube-drop URL=<playlist url> PLAYLIST=1`).** The assumption:
   that the story's "`--playlist` with a playlist URL" is satisfied by
   flag-plus-URL rather than requiring `--playlist <url>`. The forcing
   constraint was that `test_youtube.py` (read-only) pins the recipe to a
   `URL is required` guard and to the contiguous string
   `"$${MM_YOUTUBE_URL}" $(YT_ARGS)`. Attack: is the constraint real, and is
   the resulting door the one an operator would guess?

2. **`YoutubeError` gained an optional `rule=`, set at all 27 raise sites.**
   The assumption: that `refused:<rule>` needs a stable token, and that
   touching 27 sites is better than a coarse three-token vocabulary or than
   classifying a refusal by matching its message text. Every message is
   byte-identical — verify that. The vocabulary is closed in `REFUSAL_RULES`
   and pinned by a test that greps the module's own source; attack whether a
   source-grep pin is a real guard or theatre.

3. **A listing row with no usable 11-character video id becomes a per-entry
   `refused:entry-not-a-video`, not a run-level failure.** The assumption: real
   playlists carry deleted and nested rows, and refusing the whole run over one
   is worse than reporting it. Attack the boundary: is
   `_entry_video_id()` too permissive or too strict, and should a nested
   playlist be recursed into instead?

4. **Exit 1 when any entry failed, table printed either way.** The assumption:
   the table is the report and the exit code is what `make` sees, so a run with
   three refusals out of twenty must not look clean to a script. Attack whether
   a partially successful acquisition should really be a non-zero exit.

5. **`main()`'s post-acquire tail was extracted verbatim into `_deliver()` and
   is now shared by both paths.** The assumption: one delivery implementation
   is worth refactoring a landed story's `main()`. Verify the extraction is
   truly verbatim — same prints, same streams, same exit codes — because story
   6.2's output contract rides on it.

6. **`run_playlist` catches `ConfigError`, `MintError` and `YoutubeError` per
   entry, and nothing else.** The assumption: an unexpected exception is not a
   refusal and should end the run. Attack whether "a refused entry does not
   stop the run" is honoured at the boundary an operator would expect.

7. **`ensure_tools()` is called once, before enumeration.** The playlist path
   therefore requires `yt-dlp` even when every entry would have answered
   `exists`, which the single-video path does not. Attack whether that
   divergence matters.

## History you need to tell a regression from a pre-existing condition

- **Story 6.2 landed first and is the foundation.** `server/meetingminer/youtube.py`
  existed before this branch; only the additions above are 6.2a's. Its spec is
  `spec-6-2-youtube-acquisition-command.md` (status `review`) plus
  `spec-6-2-review-remediation.md` (status `done`) — 6.2 is complete per
  `sprint-status.yaml`; the `review` status on the first file is a pre-existing
  bookkeeping artifact, not this story's.
- **Story 11.2 landed in the same wave**: each worktree now owns a private
  Docker stack. Run the gates from your own worktree after
  `make bootstrap`; `make lint` needs `uv sync --project server` first.
- **Story 11.4 landed**: `make test-fast` now runs `make lint` and
  `make typecheck`. The ruff baseline is shrink-only. Three real findings in
  this diff (two ISC004, one FURB105) were fixed rather than baselined; no
  per-file ignore was added, so `test_youtube_playlist.py` satisfies every live
  rule.
- No rebase happened on this branch; no variant was dropped.

## Verification baseline

Run these in your own worktree. A skip or failure that is not listed here is a
finding, not noise.

| Command | Result on `story/6-2a` |
|---|---|
| `uv run --project server pytest server/tests/test_youtube_playlist.py server/tests/test_youtube.py -q` | 155 passed, 1 skipped |
| `uv run --project server pytest server/tests/test_youtube.py -q` | 110 passed, 1 skipped — unchanged from `main` |
| `make lint` | All checks passed |
| `make typecheck` | Success: no issues found in 13 source files |
| `make test-fast` | 1877 passed, 2 skipped |
| `make test` | 2255 passed, 2 skipped, web build green, exit 0 |
| `python3 _bmad/scripts/branch_conflicts.py --against story/6-2a` | clean |

The two skips are named and pre-existing: `pyannote` is not installed, and
story 6.2's `test_real_youtube_acquisition_end_to_end` needs
`MM_YOUTUBE_NETWORK_TEST=1`.

**Never** run `make evals-run` (paid judge role), never start the shared api or
worker, never `git add -A`, and never reset, stash or clean anything outside
your own worktree.

## Known residual risks the builder recorded

Confirm or refute these rather than rediscovering them:

- No live playlist was acquired end to end; enumeration is covered only from a
  recorded listing.
- Per-entry survival is scoped to the three named refusal types.
- The rule vocabulary pin reads this module's source only.
