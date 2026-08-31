# Code Review — Story 6.2a: Playlist Acquisition

## Scope

Adversarial review of Story 6.2a across the implementation, tests, operator documentation, Make recipe, and story artifacts named in the review handoff. Frozen intent in the spec is reviewable but will not be patched; out-of-scope files remain read-only.

## Review range

- Source range before the mandatory rebase: `4a111b8..596a709` (`story/6-2a`)
- Review branch: `story/6-2a-review`
- Final rebased story range: `f92cb9c..9d35982` (`origin/main` through the rebased Story 6.2a finalization commit).
- Review-lane commits begin at `098f22d`; the skeleton was intentionally committed before implementation inspection.

## Findings

### F1 — Open: eager media-tool gate defeats the per-entry `exists` short-circuit

- **Location** — `server/meetingminer/youtube.py:1114`
- **Severity** — medium
- **Finding** — `run_playlist()` calls the single-video `ensure_tools()` gate before enumeration. That gate requires `yt-dlp`, `ffmpeg`, and `ffprobe`, so a playlist whose entries already exist is refused before `acquire()` can apply Story 6.2's deliberate read-only `exists` short-circuit. The playlist path therefore requires media tooling for work that performs no probe, download, or mint, unlike the unchanged single-video path and the frozen per-entry `exists` contract.
- **Evidence** — `run_playlist()` calls `ensure_tools()` at line 1114, while `acquire()` checks `_find_existing_youtube_drop()` and returns `MintResult(status="exists", ...)` at lines 866–883 before its own `ensure_tools()` at line 884. A focused `uv run --project server python` probe with `yt-dlp` present and `ffmpeg`/`ffprobe` absent printed `tool-missing: ffmpeg is not on PATH`; its instrumented result was `enumeration_called=False; acquire_called=False`.
- **Suggested direction** — Require only the listing executable before the one playlist-enumeration subprocess, and leave the full media-tool gate inside `acquire()` after its existing-drop lookup. Add a regression test proving an all-existing playlist still enumerates, POSTs each existing drop, and reaches neither the media probe/download path nor a requirement for `ffmpeg`/`ffprobe`.

### F2 — Open: the refusal-vocabulary test does not enforce explicit or declared rules

- **Location** — `server/tests/test_youtube_playlist.py:283`
- **Severity** — low
- **Finding** — `test_every_rule_the_source_raises_is_declared()` regexes only literal `rule="..."` text and checks that the literals it happens to find are a subset of `REFUSAL_RULES`. A new `raise YoutubeError("...")` with no rule is invisible, and a dynamic or directly constructed undeclared rule is also invisible. The test therefore does not close the vocabulary or guarantee the spec's “set at each raise site” property despite its name and docstring.
- **Evidence** — A focused `uv run --project server python` mutation removed the first explicit `rule="not-a-video-url"` from an in-memory copy of the module and re-ran the test's exact regex predicate; it printed `current_guard_accepts_missing_rule=True`. The same probe constructed `YoutubeError("x", rule="invented-token")`, and `refusal_rule()` returned `invented-token`. A separate AST inventory confirmed today's implementation has 37 `raise YoutubeError(...)` sites and zero missing explicit rules, so this is a guard gap rather than a current-site misclassification.
- **Suggested direction** — Replace the regex subset check with an AST assertion over every `raise YoutubeError(...)`: each site must have exactly one literal `rule=` keyword and that value must belong to `REFUSAL_RULES`. Also reject undeclared explicit tokens at construction or directly test the mapping invariant so a future non-literal token cannot leak into the stable table vocabulary.
