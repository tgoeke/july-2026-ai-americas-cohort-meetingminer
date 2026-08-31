---
title: 'Story 6.2a: Playlist Acquisition'
type: 'feature'
created: '2026-08-30'
status: 'review'
baseline_revision: '8f00de6f2a825bd0fc99fac4da5bda620bff5161'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/build-prompt-story-6-2a-2026-08-30.md'
  - '{project-root}/_bmad-output/implementation-artifacts/wave-2026-08-30-rules.md'
warnings: [oversized]
deferred: []
---

<intent-contract>

## Intent

**Problem:** `youtube-drop` acquires exactly one video per invocation (story 6.2). A recurring series — a community's weekly meeting — is a YouTube playlist, and bringing twenty of them in one at a time is twenty commands, so the corpus never gets more than one meeting per topic (FR33).

**Approach:** Add `--playlist` to the existing command. It enumerates the playlist's entries with `yt-dlp --flat-playlist`, then mints and posts each entry **through story 6.2's own single-video path, unchanged**, one after another, and prints a summary table naming every entry's outcome as `minted | exists | refused:<rule>`. A refused entry is recorded and the run continues.

## Boundaries & Constraints

**Always:**
- Story 6.2's single-video path is byte-identical in effect when `--playlist` is absent: same argument handling, same ordering of refusals, same `_report`/POST output, same exit codes. The playlist path calls `acquire()` and the extracted delivery helper; it does not fork them.
- Entries are enumerated with one `yt-dlp -J --flat-playlist <canonical playlist url>` invocation. No media bytes are downloaded during enumeration.
- Each entry is acquired by its canonical watch URL and delivered **sequentially** — one drop and one `POST /ingests` per entry, in playlist order. Never concurrent: one identity lock, one intake door, one ordered table.
- Story 6.2's `exists` short-circuit applies per entry: an already-minted `youtube:<videoId>` is answered from the drops root with no probe, no download, and no media network traffic, and is still POSTed.
- **A refused entry does not stop the run.** Every `YoutubeError`/`MintError`/`ConfigError` raised while acquiring or delivering one entry is caught, printed in full, recorded as `refused:<rule>`, and the loop advances to the next entry.
- Every refusal carries a short, stable rule token. `YoutubeError` gains an optional `rule` keyword set at each raise site; the message text of every existing 6.2 refusal is unchanged, so 6.2's tests and the operator-facing wording are untouched.
- The run's exit code is 0 only when every entry ended `minted` or `exists` and every POST succeeded; otherwise 1. The summary table is printed either way.
- A run-level refusal — the URL is not a playlist URL, `yt-dlp` is missing, enumeration fails or yields no entries — refuses by name before any entry is acquired, exactly as 6.2 refuses before permanent writes.
- Tests are offline: `_run` and `acquire` stubbed, a recorded flat-playlist listing as the fixture, `tmp_path` drops roots, no store fixtures, no conftest edits, no POST to a real api.

**Block If:**
- The story cannot land without editing a file outside the footprint below.
- `story/6-2a` diverges from an upstream mid-run.

**Never:** appending to `server/tests/test_youtube.py` or editing it at all (its Makefile and README pins must keep passing as written); `server/meetingminer/mintdrop.py` (story 6.3 owns it); `server/meetingminer/config.py`, `config.yaml`; `server/tests/conftest.py`, `test_compose_contract.py`, `test_config.py`; root `README.md`, `AGENTS.md`, `docs/backlog.md`, `project-context.md`; anything under `web/`; parallel or threaded entry acquisition; resuming a partially finished playlist from state on disk (re-running is the resume, via `exists`).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Playlist URL | `--playlist` + `youtube.com/playlist?list=<id>` | one `-J --flat-playlist` call; each entry minted+POSTed in order; table of outcomes | No error expected |
| Watch URL carrying a list | `--playlist` + `watch?v=<vid>&list=<id>` | the `list=` id is enumerated (the `v=` is ignored) | No error expected |
| `--playlist` absent | any watch/shorts/youtu.be URL | story 6.2 unchanged, including `&list=` ignored | unchanged |
| `--playlist` on a video URL | `--playlist` + `watch?v=<id>` with no `list=` | named refusal `not a YouTube playlist URL`, exit 1 | before any subprocess |
| Entry already minted | playlist containing a minted `youtube:<id>` | that row is `exists`; no probe, no download; still POSTed | downloader/probe never invoked |
| Entry refused | an entry over the duration cap, private, or removed | full refusal printed; row `refused:<rule>`; **run continues**; exit 1 at the end | remaining entries still acquired |
| Entry is not a video | flat entry with no usable 11-char id (nested playlist, malformed row) | row `refused:entry-not-a-video`; run continues | no subprocess for that row |
| Enumeration fails | yt-dlp exits non-zero | named refusal carrying yt-dlp's own message, exit 1 | no entry acquired |
| Enumeration unreadable | stdout is not JSON, not an object, or has no `entries` list | named refusal `playlist-unreadable`, exit 1 | no entry acquired |
| Empty playlist | `entries: []` | named refusal `playlist-empty`, exit 1 | nothing acquired |
| Intake fails on one entry | POST raises `IntakeError` | 6.2's re-POST guidance for that drop; row keeps its mint outcome, marked `intake FAILED`; run continues; exit 1 | drop stays finalized |

</intent-contract>

## Code Map

- `server/meetingminer/youtube.py` — the whole story, and the only source file touched.
  - `YoutubeError` `:118` — gains `__init__(message, *, rule=...)` storing `self.rule`. Additive: `RuntimeError`'s message behaviour and every existing `str(exc)` are unchanged.
  - 27 `raise YoutubeError(...)` sites — each gains `rule="<token>"`. Message text unchanged, so `test_youtube.py`'s `match=` assertions all still hold.
  - `video_id_from_url()` `:134` — read-only except its refusal tail ("Playlists are not supported." → point at `--playlist`); its accept/refuse *behaviour* is pinned by `test_everything_else_is_refused_by_name` (which lists `/playlist?list=…` as refused) and must not change.
  - `watch_url()` `:125`, `ensure_tools()` `:177`, `_run()` `:197`, `classify_probe_failure()` `:212`, `acquire()` `:681` — reused verbatim by the playlist loop.
  - `main()` `:812` — its post-acquire tail (lines 851-876: `_report`, `--no-post` recovery print, `post_ingest`, `IntakeError` guidance, intake label) is extracted verbatim into `_deliver()` and called from both paths.
  - `_parser()` `:776` — `--playlist` added as `action="store_true"`; the positional `url` stays required and unchanged.
- `server/meetingminer/mintdrop.py` — READ-ONLY. `MintResult` `:551` (`status` is `created`/`exists` — the table maps `created` → `minted`), `_report` `:1065`, `post_ingest` `:957`, `ingest_command` `:932`, `resolve_api_url` `:891`, `IntakeError`, `MintError`. Story 6.3 owns this file in the same wave.
- `server/tests/test_youtube.py` — READ-ONLY, and it pins my two shared surfaces:
  - `test_makefile_has_the_youtube_drop_target_with_a_url_guard` `:1286` asserts the recipe still contains `error: URL is required` and the contiguous string `"$${MM_YOUTUBE_URL}" $(YT_ARGS)`, and that `$(URL)` never appears in the recipe. The Makefile edit must satisfy all three — hence `--playlist` is appended *after* `$(YT_ARGS)` and `URL=` keeps carrying the URL.
  - `test_readme_distinguishes_temporary_downloads_from_permanent_writes` `:1094` asserts three strings inside the "## Ingesting a YouTube video" section; the section is extended, never restructured.
  - `test_everything_else_is_refused_by_name` `:232` and `test_download_command_and_outputs_are_covered_without_network` `:643` pin the single-video argv and refusals.
- `infra/Makefile` — `youtube-drop` recipe `:817-822` (`unexport URL`, `export MM_YOUTUBE_URL := $(value URL)`, venv guard, URL guard, command line). Only this recipe.
- `docs/README.md` — "## Ingesting a YouTube video" `:166-204`. Extend: the playlist command, the outcome table, the refusal-does-not-stop-the-run rule, and correcting the two "playlists are not supported" statements at `:174` and `:188`.
- `server/tests/fixtures/youtube/` — five recorded `info.json` fixtures exist (`full`, `auto-captions`, `no-english`, `audio-only`, `upload-date-only`); add `flat-playlist.json`, a pruned `-J --flat-playlist` listing.
- `server/pyproject.toml` — READ-ONLY. `[tool.ruff.lint.per-file-ignores]` does not list `tests/test_youtube.py`, so a new test module gets every live rule; `[tool.mypy] files` does not include `youtube.py`. `mm_fast_test_budget_seconds = 2.0` bounds each new test's call phase.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` `:101` (`6-2a-playlist-acquisition: backlog`) and `sprint-notes.md` (append at EOF; no merge driver).

## Tasks & Acceptance

**Execution:**
- `server/meetingminer/youtube.py` — give `YoutubeError` an optional `rule` keyword (default `"unclassified"`) and set an explicit token at all 27 raise sites; add `refusal_rule(exc)` mapping `MintError`→`mint-refused`, `ConfigError`→`config`, `YoutubeError`→`exc.rule` — the outcome table's `refused:<rule>` needs a short stable token, and the raise site is the only place that knows which rule fired.
- `server/meetingminer/youtube.py` — factor `_yt_dlp_detail(stderr)` out of `classify_probe_failure` and add `classify_playlist_failure(stderr)` on top of it — a playlist that cannot be listed must not be reported as "the video cannot be acquired", and the extracted half keeps one line-parsing implementation.
- `server/meetingminer/youtube.py` — add `PLAYLIST_ID_PATTERN`, `playlist_url(id)`, `playlist_id_from_url(url)` (http(s) only; `youtube.com`/`*.youtube.com`; `/playlist?list=<id>` or `/watch?v=…&list=<id>`; exactly one `list` value; `[A-Za-z0-9_-]{2,128}`) — classification is offline and refuses before any subprocess, the rule 6.2 set for video URLs.
- `server/meetingminer/youtube.py` — add `PlaylistEntry` (position, video_id, title) and `enumerate_playlist(url)` running `[YT_DLP, "-J", "--flat-playlist", url]` through `_run` with `PROBE_TIMEOUT_SECONDS`; refuse on non-zero exit, unreadable JSON, a non-object, a missing/non-list `entries`, or an empty list; a row whose `id` is not an 11-character video id becomes an entry with `video_id=None` rather than a run-level failure — deleted/nested rows are the playlist's problem, not the run's.
- `server/meetingminer/youtube.py` — extract `main()`'s post-acquire tail verbatim into `_deliver(result, *, api_url, no_post) -> tuple[int, str]` (exit code, short intake note) and call it from the single-video path — one delivery implementation, and 6.2's output stays character-for-character what it was.
- `server/meetingminer/youtube.py` — add `EntryOutcome` and `run_playlist(url, *, api_url, no_post, acquire_kwargs)`: classify, `ensure_tools()`, enumerate, then per entry in order — `video_id is None` → `refused:entry-not-a-video`; else `acquire(watch_url(id), **acquire_kwargs)` inside `try/except (YoutubeError, MintError, ConfigError)` printing the full refusal to stderr and recording `refused:<rule>`; on success `_deliver(...)` and record `minted`/`exists` plus any intake note. Print the table and return 0 only if nothing failed — the AC's "a refused entry does not stop the run" is exactly this `except`-and-continue.
- `server/meetingminer/youtube.py` — add `format_outcome_table(rows)` returning the printed lines (`<n>. <video id> <outcome> <title>` plus a counted summary line) and wire `--playlist` into `_parser()`/`main()`; `main()` routes to `run_playlist` only when `args.playlist` is set, after the same api-url and drops-root resolution the single path does — a table is data the tests can assert on without capturing stdout formatting twice.
- `infra/Makefile` — in the `youtube-drop` recipe only: append `$(if $(PLAYLIST),--playlist)` after `$(YT_ARGS)` and extend the URL-guard message to name `PLAYLIST=1` — `make youtube-drop URL=<playlist url> PLAYLIST=1`; appending after `$(YT_ARGS)` keeps `test_youtube.py`'s contiguous-string pin true and leaves `URL=` as the one place a URL is passed.
- `docs/README.md` — extend "Ingesting a YouTube video": the playlist command, sequential one-drop-one-POST behaviour, the outcome table, the per-entry `exists` short-circuit, refusals not stopping the run, the exit code, and correcting the two statements that say playlists are unsupported — docs land with the code.
- `server/tests/fixtures/youtube/flat-playlist.json` — a recorded `-J --flat-playlist` listing pruned to the fields read (`_type`, `id`, `title`, `entries[].{_type,id,title,url,duration}`), including one row that is not a video — offline truth for enumeration.
- `server/tests/test_youtube_playlist.py` — NEW module covering every row of the I/O matrix: playlist-URL classification (accepted shapes and each refusal), the exact `-J --flat-playlist` argv, enumeration from the fixture, the four enumeration refusals, the per-entry loop over a stubbed `acquire` (minted / exists / refused / not-a-video, asserting order, the table text, and that later entries still ran), the `exists` short-circuit with `probe`/`download` stubs that fail the test if invoked, an intake failure on one entry not stopping the rest, the exit codes, `--playlist` absent leaving the single-video path untouched (`enumerate_playlist` fails the test if called), the Makefile pass-through, and the README statements.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` + `sprint-notes.md` — set `6-2a-playlist-acquisition: review` and append a dated 6-2a narrative at EOF — wave tracking rule.

**Acceptance Criteria:**
- Given the three Given/When/Then clauses of "Story 6.2a: Playlist Acquisition" in `_bmad-output/planning-artifacts/epics.md`, when the suite is inspected, then each clause holds as written (the I/O matrix operationalizes them).
- Given `uv run --project server pytest server/tests/test_youtube.py server/tests/test_youtube_playlist.py -q`, when it runs offline, then every test passes and the 6.2 module is unchanged and green — the proof that the single-video path did not move.
- Given `make test-fast` (lint and typecheck included) and, once before review, `make test`, when they run, then both pass.
- Given `python3 _bmad/scripts/branch_conflicts.py --against story/6-2a`, when run before the final push, then it prints `clean` against `main` and every other `story/*`.

## Spec Change Log

## Review Triage Log

### 2026-08-30 — Builder self-review pass

No in-session reviewer subagents were run. Two reasons, both recorded rather
than assumed: this wave's contract routes adversarial review to an external
lane carried by `review-prompt-story-6-2a-2026-08-30.md` (story 6.2 recorded
the same decision), and this run's dispatch requires strictly synchronous work
while this harness's subagents execute detached. The diff was instead read
end to end by the builder.

- intent_gap: 0
- bad_spec: 0
- patch: 1: (high 0, medium 0, low 1)
- defer: 0
- reject: 0
- addressed_findings:
  - `[low]` `[patch]` `infra/Makefile` used `$(if $(PLAYLIST),--playlist)`,
    which Make evaluates on emptiness, so `PLAYLIST=0` would have silently
    enabled the flag. Documented in the recipe comment and in
    `docs/README.md` that any non-empty value enables it and that the variable
    is omitted to acquire a single video — chosen over a `filter-out` guard,
    which would have invented a truthiness convention this Makefile has
    nowhere else.

## Design Notes

- **`--playlist` is a flag, not an option taking a URL.** `test_youtube.py:1286` pins the Makefile recipe to the contiguous string `"$${MM_YOUTUBE_URL}" $(YT_ARGS)` and to a `URL is required` guard, and that file is read-only for this story. A `PLAYLIST=<url>` variable would need a second URL-carrying env export and would leave the positional `url` empty; a flag keeps one URL entry point (`URL=`), keeps every existing pin true, and reads the same on the command line: `youtube-drop '<playlist url>' --playlist`. The assumption a reviewer should attack: that the AC's "`--playlist` with a playlist URL" is satisfied by flag-plus-URL rather than requiring `--playlist <url>`.
- **`rule` on `YoutubeError` rather than message matching.** The AC wants `refused:<rule>`. The alternative — classifying a refusal by matching its prose in the table renderer — would silently mislabel a row the day a message is reworded. Setting the token where the refusal is raised costs 27 one-word edits, changes no message, and is greppable. Assumption to attack: that touching all 27 sites is worth it versus a coarser three-token vocabulary (`youtube` / `mint` / `config`).
- **An unusable entry row is a per-entry refusal, not a run-level one.** Real playlists carry deleted and private rows; `--flat-playlist` still lists them. Refusing the whole run because row 7 is a nested playlist would defeat the story. Assumption to attack: that `entry-not-a-video` belongs in the table rather than being skipped silently.
- **Exit 1 when any entry failed.** The table is the report; the exit code is what `make` sees. A run where three of twenty entries were refused is not a success, and a silent 0 would let a broken playlist look clean in a script. The refusals are still printed in full as they happen, so the code is a summary, never the only signal.
- The cached `epic-6-context.md` was used rather than recompiled: its `-newer` test fails only because a fresh worktree checkout stamps every file with one mtime. Checked in git instead — the context was committed at `00f4dfc` (2026-08-30 15:29), after `epics.md` at `5cdfce7` (13:05), so it is current.

## Verification

**Commands:**
- `uv run --project server pytest server/tests/test_youtube_playlist.py -q` -- expected: all pass.
- `uv run --project server pytest server/tests/test_youtube.py -q` -- expected: unchanged from main (43 passed, 1 skipped) — the single-video path did not move.
- `make lint` and `make typecheck` -- expected: clean; the new test module carries no per-file ignore entry, so it must satisfy every live rule.
- `make test-fast` -- expected: green.
- `make test` -- expected: green once before the status flips to review (needs the worktree's own stack up).
- `python3 _bmad/scripts/branch_conflicts.py --against story/6-2a` -- expected: `clean`.

## Auto Run Result

Status: review. Per the wave contract this run never marks the story done:
adversarial review is external and is carried by
`review-prompt-story-6-2a-2026-08-30.md`, whose lane fixes what it finds.

**Summary.** `youtube-drop --playlist` (`make youtube-drop URL=<playlist url>
PLAYLIST=1`) enumerates a playlist with one `yt-dlp -J --flat-playlist` call
and then mints and posts each entry sequentially through story 6.2's own
`acquire()` — one drop and one `POST /ingests` per entry, in listing order,
with the `exists` short-circuit answering per entry before any probe or
download. Each refusal is printed in full and recorded as `refused:<rule>`; the
run continues, ends with a summary table naming every entry
`minted | exists | refused:<rule>`, and exits non-zero if anything failed.

**Files changed.**
- `server/meetingminer/youtube.py` — `rule=` on all 27 `YoutubeError` raise
  sites plus the closed `REFUSAL_RULES` vocabulary and `refusal_rule()`;
  `_yt_dlp_detail()` split out of `classify_probe_failure()` with
  `classify_playlist_failure()` beside it; `playlist_id_from_url()`,
  `playlist_url()`, `PlaylistEntry`, `enumerate_playlist()`, `EntryOutcome`,
  `format_outcome_table()`, `run_playlist()`; `main()`'s post-acquire tail
  extracted verbatim into `_deliver()` and shared by both paths; `--playlist`
  on the parser and the routing in `main()`.
- `infra/Makefile` — the `youtube-drop` recipe only: `$(if $(PLAYLIST),--playlist)`
  after `$(YT_ARGS)`, and the URL guard now names `PLAYLIST=1`.
- `docs/README.md` — "Ingesting a YouTube video" extended with an "A whole
  playlist" subsection; the two statements saying playlists are unsupported
  corrected.
- `server/tests/test_youtube_playlist.py` + `server/tests/fixtures/youtube/flat-playlist.json`
  (both new) — 45 offline tests over a recorded flat listing.
- Sprint artifacts: `sprint-status.yaml` (`6-2a-playlist-acquisition: review`),
  `sprint-notes.md`, this spec.

**Review findings breakdown.** Builder self-review only (see the triage log):
patched 1 (low), deferred 0, rejected 0. Follow-up review recommendation:
false — patched counts high 0, medium 0, low 1, score `3x0 + 1x1 = 1`, under 5.

**Verification performed** (every command run in this worktree, against its own
`meetingminer-6-2a` stack):
- `uv run --project server pytest server/tests/test_youtube_playlist.py server/tests/test_youtube.py -q`
  — 155 passed, 1 skipped (story 6.2's env-flagged network test).
- `uv run --project server pytest server/tests/test_youtube.py -q` — 110 passed,
  1 skipped, unchanged from `main`: the single-video path did not move.
- The same new module against unfixed code first — 45 failed — so every test
  here was observed red before it was claimed as coverage.
- `make lint` — All checks passed (the new test module carries no per-file
  ignore, so it satisfies every live rule; three real findings, two ISC004 and
  one FURB105, were fixed rather than baselined).
- `make typecheck` — Success: no issues found in 13 source files.
- `make test-fast` — 1877 passed, 2 skipped (pyannote absent; the network test).
- `make test` — 2255 passed, 2 skipped, web build green, exit 0.
- Real CLI smoke, no network: `--help` shows `--playlist`, and
  `youtube.py '<watch url>' --playlist` refuses by name with exit 1.
- `python3 _bmad/scripts/branch_conflicts.py --against story/6-2a` — run before
  the final push; result reported with the run.

**Residual risks.**
- No live playlist was acquired end to end. Enumeration argv, entry mapping and
  the whole outcome table are covered offline from a recorded listing, but a
  real `--flat-playlist` payload shape change would be caught only by story
  6.2's single-video network test, which does not enumerate.
- `run_playlist` catches `ConfigError`, `MintError` and `YoutubeError` per
  entry. Anything else — an `OSError` from the filesystem, say — still ends the
  run. That is deliberate (an unexpected failure is not a refusal), but it
  means "a refused entry does not stop the run" is scoped to named refusals.
- The rule vocabulary is pinned by a test that greps this module's source for
  `rule="..."`. A rule raised from a *different* module would not be caught by
  that pin; today none is.
