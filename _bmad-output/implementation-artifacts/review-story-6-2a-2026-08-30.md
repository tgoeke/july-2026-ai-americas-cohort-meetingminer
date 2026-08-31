# Code Review — Story 6.2a: Playlist Acquisition

## Scope

Adversarial review of Story 6.2a across the implementation, tests, operator documentation, Make recipe, and story artifacts named in the review handoff. Frozen intent in the spec is reviewable but will not be patched; out-of-scope files remain read-only.

## Review range

- Source range before the mandatory rebase: `4a111b8..596a709` (`story/6-2a`)
- Review branch: `story/6-2a-review`
- Final rebased story range: `f92cb9c..9d35982` (`origin/main` through the rebased Story 6.2a finalization commit).
- Review-lane commits begin at `098f22d`; the skeleton was intentionally committed before implementation inspection.

## Findings

### F1 — Resolved: eager media-tool gate defeats the per-entry `exists` short-circuit

- **Location** — `server/meetingminer/youtube.py:1114`
- **Severity** — medium
- **Finding** — `run_playlist()` calls the single-video `ensure_tools()` gate before enumeration. That gate requires `yt-dlp`, `ffmpeg`, and `ffprobe`, so a playlist whose entries already exist is refused before `acquire()` can apply Story 6.2's deliberate read-only `exists` short-circuit. The playlist path therefore requires media tooling for work that performs no probe, download, or mint, unlike the unchanged single-video path and the frozen per-entry `exists` contract.
- **Evidence** — `run_playlist()` calls `ensure_tools()` at line 1114, while `acquire()` checks `_find_existing_youtube_drop()` and returns `MintResult(status="exists", ...)` at lines 866–883 before its own `ensure_tools()` at line 884. A focused `uv run --project server python` probe with `yt-dlp` present and `ffmpeg`/`ffprobe` absent printed `tool-missing: ffmpeg is not on PATH`; its instrumented result was `enumeration_called=False; acquire_called=False`.
- **Suggested direction** — Require only the listing executable before the one playlist-enumeration subprocess, and leave the full media-tool gate inside `acquire()` after its existing-drop lookup. Add a regression test proving an all-existing playlist still enumerates, POSTs each existing drop, and reaches neither the media probe/download path nor a requirement for `ffmpeg`/`ffprobe`.
- **Resolution** — Added a listing-only `ensure_playlist_tool()` gate and kept the full media-tool `ensure_tools()` call inside `acquire()`. The existing-drop regression test was observed failing first with `YoutubeError: ffmpeg is not on PATH`, then passed after the fix; the complete playlist module passed (45 tests).

### F2 — Resolved: the refusal-vocabulary test does not enforce explicit or declared rules

- **Location** — `server/tests/test_youtube_playlist.py:283`
- **Severity** — low
- **Finding** — `test_every_rule_the_source_raises_is_declared()` regexes only literal `rule="..."` text and checks that the literals it happens to find are a subset of `REFUSAL_RULES`. A new `raise YoutubeError("...")` with no rule is invisible, and a dynamic or directly constructed undeclared rule is also invisible. The test therefore does not close the vocabulary or guarantee the spec's “set at each raise site” property despite its name and docstring.
- **Evidence** — A focused `uv run --project server python` mutation removed the first explicit `rule="not-a-video-url"` from an in-memory copy of the module and re-ran the test's exact regex predicate; it printed `current_guard_accepts_missing_rule=True`. The same probe constructed `YoutubeError("x", rule="invented-token")`, and `refusal_rule()` returned `invented-token`. A separate AST inventory confirmed today's implementation has 37 `raise YoutubeError(...)` sites and zero missing explicit rules, so this is a guard gap rather than a current-site misclassification.
- **Suggested direction** — Replace the regex subset check with an AST assertion over every `raise YoutubeError(...)`: each site must have exactly one literal `rule=` keyword and that value must belong to `REFUSAL_RULES`. Also reject undeclared explicit tokens at construction or directly test the mapping invariant so a future non-literal token cannot leak into the stable table vocabulary.
- **Resolution** — Replaced the regex with an AST walk that checks every raised `YoutubeError` for exactly one literal declared rule, and made `YoutubeError` reject undeclared tokens at construction. The new constructor test failed first with `DID NOT RAISE ValueError`, then the three focused vocabulary/message tests and all 46 playlist tests passed.

### F3 — Resolved: per-entry `ConfigError` survival is implemented but unverified

- **Location** — `server/tests/test_youtube_playlist.py:294`
- **Severity** — low
- **Finding** — The frozen contract names `ConfigError` as one of three per-entry refusals that must be recorded and survived, but the playlist suite only checks its token mapping. It exercises loop survival for `YoutubeError` and `MintError`, not `ConfigError`; deleting `ConfigError` from `run_playlist()`'s catch tuple would therefore escape the loop and leave all current playlist tests green.
- **Evidence** — `rg -n 'ConfigError|run_playlist' server/tests --glob '*.py'` found the playlist module's only `ConfigError` use at line 300 inside `test_refusal_rule_names_the_source_of_every_refusal_kind()`, which never invokes `run_playlist()`. A focused two-entry `uv run --project server python` probe made the first acquisition raise `ConfigError("configuration changed")`; current code correctly printed `refused:config`, attempted the second entry, and reported `code=1; entries_attempted=2`, demonstrating the behavior that lacks a test.
- **Suggested direction** — Add a loop-level regression case in `test_youtube_playlist.py` that raises `ConfigError` for one entry and asserts `refused:config`, exit 1, and acquisition of the later entry. Keep the existing mapping assertion as the unit check for the token itself.
- **Resolution** — Added the loop-level regression case. For the red phase, the catch tuple was temporarily mutated to omit `ConfigError`; the new test failed as the exception escaped from entry 1. The production tuple was immediately restored, after which the focused test and all 47 playlist tests passed. The mutant was never committed.
