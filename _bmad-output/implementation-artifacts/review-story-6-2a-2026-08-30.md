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

## Verdict

**Pass after remediation.** All three findings are resolved on `story/6-2a-review`; there are no open high, medium, or low findings, no owner decisions, and no deferred work. The frozen intent contract was not edited. The story spec and sprint tracking are `done`, pending the owner's integration of this review branch.

## Compatibility and design-decision audit

- **Story 6.3 rebase/API compatibility** — verified after rebasing onto `origin/main`: `mint()` retains every keyword used by `youtube.acquire()`, `MintResult` only adds the defaulted `ignored` field, and `MintError`, `IntakeError`, `_report`, `post_ingest`, `ingest_command`, and `resolve_api_url` imported by `youtube.py` are the landed `mintdrop.py` symbols. The focused and full suites exercise the rebased composition.
- **Existing refusal text** — an AST comparison against `origin/main` found all 27 pre-existing `raise YoutubeError(...)` first-argument expressions identical. The `_yt_dlp_detail()` extraction preserves `classify_probe_failure()` output, and Story 6.2's 110 tests remain untouched and green inside the 157-test focused run.
- **Single-video delivery** — `_deliver()` retains the original report, `--no-post`, successful intake, duplicate intake, and `IntakeError` print/exit paths; the unchanged Story 6.2 tests observe those outputs and exit codes.
- **Per-entry failure boundary** — a named mid-playlist `YoutubeError` probe attempted all later entries and printed the table with exit 1. A probed unexpected `RuntimeError` escaped after its entry and printed no table, matching the frozen contract's explicit `YoutubeError`/`MintError`/`ConfigError` scope rather than being mislabeled as a refusal.
- **Architecture** — every usable entry still reaches Story 6.2's `acquire()` and exactly one `_deliver()` call sequentially; `_deliver()` uses only `POST /ingests`; the existing-drop path reads and POSTs without modifying the finalized drop; the configured duration cap is reused unchanged; no schema or configuration file changed.

## Verification

- `uv run --project server pytest server/tests/test_youtube_playlist.py server/tests/test_youtube.py -q` — 157 passed, 1 skipped (the named network test).
- `make lint` — all checks passed.
- `make typecheck` — success, no issues in 13 source files.
- `make test-fast` — 1927 passed, 2 skipped, 378 deselected; the skips are the named `pyannote` and YouTube network cases.
- `make test` — 2305 server tests passed, 2 named skips; puller, web tests, 643 eval-harness tests, isolated diarization tests, store checks, and the web production build all passed.
- `python3 _bmad/scripts/branch_conflicts.py --against story/6-2a-review` — `main × story/6-2a-review` is clean. The command exits 1 overall because the matrix also includes expected `sprint-notes.md` append conflicts with other in-flight branches and the intentional overlap with its source branch; the owner must union the notes during integration as already directed.
- `make check-reviews` — passed: `every dispatched review has a committed report`.

## Remediation commits

- `848c8c0` — F1: preserve the playlist `exists` short-circuit without media tools.
- `c38bb4d` — F2: enforce the refusal-rule vocabulary and replace the regex guard.
- `3bc6795` — F3: cover per-entry `ConfigError` survival.

## Residual risks

- No live playlist was acquired end to end. Enumeration remains deliberately verified against the recorded offline fixture; a future `yt-dlp --flat-playlist` payload change needs a real operator run to expose it.
- Unexpected exceptions outside the three named per-entry refusal types still abort the run without a summary table. This was probed and matches the frozen boundary; it is not an open review finding.
- The review branch intentionally overlaps `story/6-2a` and appends to `sprint-notes.md`; the owner must integrate this branch, not merge the unrebased source branch beside it.
