# Adversarial review prompt — story/6-2 (YouTube Acquisition Command)

Generated 2026-08-30 for external review (Codex `bmad-code-review` or another
LLM), because the bmad-build step-04 review layers were not run as subagents
in-session — the repo's established external-review path.

## REQUIRED OUTPUT — read this before any code

- Write the report to
  `_bmad-output/implementation-artifacts/review-story-6-2-2026-08-30.md`.
- Finding structure: **Location / Severity (high|medium|low) / Finding /
  Evidence / Suggested direction**. Report findings — do NOT fix them.
- **REPORT-FIRST:** create and COMMIT the report file as a skeleton (scope,
  review range, empty findings section) BEFORE reading any code, then append
  each finding as it is confirmed and commit incrementally. A crashed or
  closed session must lose prose, never the artifact. Six reviews in this
  repo produced their report only as terminal text; do not be the seventh.
- **Closeout:** before reporting completion, run `make check-reviews` (it
  fails while any dispatched review lacks a committed report — including this
  one) and state the SHA carrying the report's final version. A review
  reported in the terminal but not filed does not exist.

## The change under review

- Repo: `/Users/devopsterus/current/cohort/meetingminer` — review in your OWN
  worktree (`make worktree STORY=6-2-review`), never the main checkout.
- Branch: `story/6-2`. Review range: `5cdfce7..HEAD` on that branch.
- Commits in range:
  - `4c0ad9d` docs: add Story 6.2 spec (YouTube acquisition command)
  - `7625b79` feat: mint() keyword overrides and acquisition config (story 6.2 groundwork)
  - `aa7d316` feat: YouTube acquisition command (story 6.2, FR33)
  - `5b93fc2` test: offline coverage for the YouTube acquisition command (story 6.2)
  - one artifacts commit after this file (spec status/sprint tracking; docs only)
- Spec (context): `_bmad-output/implementation-artifacts/spec-6-2-youtube-acquisition-command.md`.
  The `<intent-contract>` block is FROZEN intent derived from the six
  Given/When/Then clauses of "Story 6.2: YouTube Acquisition Command" in
  `_bmad-output/planning-artifacts/epics.md` — judge the code against it.
  Everything outside that block (Code Map, Tasks, Design Notes, Auto Run
  Result) is planner work you may critique.

## Architecture authorities

- `docs/architecture.md` — AD-1 (every source enters as a write-once source
  drop; wall clock is never re-derived from media), AD-13 (drop contents are
  read-only after intake; a finalized drop is never written into), AD-14 (one
  intake door, `POST /ingests`), AD-10 (thresholds are configuration —
  the duration cap must live in config.yaml, not code).
- `docs/source-drop.schema.json` — the metadata contract both the tool and
  intake validate against.
- Repository invariant: fail closed, fail named, fail before writing; no
  silent fallbacks.

## Scope

In scope: `server/meetingminer/youtube.py` (new),
`server/meetingminer/mintdrop.py` (ONLY the keyword-override edits),
`server/meetingminer/config.py` (ONLY the two classes + last Settings field),
`config.yaml` (EOF block), `infra/Makefile` (`youtube-drop` target),
`docs/README.md` (new section), `server/tests/test_youtube.py` +
`server/tests/fixtures/youtube/`.

Out of scope: playlists (story 6.2a); `mint-drop`'s CLI and file
classification (story 6.3 owns them next); `server/tests/conftest.py`,
`test_mint_drop.py`, `test_compose_contract.py`, `server/pyproject.toml`,
root `README.md`, `AGENTS.md`, anything under `web/`; the pre-existing B-34
deep-link retention issue (moments stage nulls `source_deep_link` once replay
exists — filed, not this story's); the already-recorded deferred item (the
network test's missing `slow` mark + `SLOW_TESTS` pin, deliberately deferred
to integrate because that file is outside this story's wave footprint).

## Design decisions to attack (the planner is not a neutral judge of its own calls)

1. **yt-dlp as a subprocess by name, no dependency entry** — rests on the
   assumption that `pipeline/media.py`'s ffmpeg pattern extends to a tool
   whose extractor breaks with site changes, and that a run-time named
   refusal is a better gate than `check-tools`.
2. **`provenance_extra` merges AFTER the defaults and may override `tool`** —
   rests on the assumption that a deliberate collision is a feature, not a
   foot-gun for future producers.
3. **The probe (`yt-dlp -J --no-playlist`) carries the whole refusal matrix;
   the downloaded `info.json` is the metadata source** — rests on the
   assumption that probe info and downloaded info agree on the refusal fields
   (duration, timestamps), and that only the downloaded file's `format_id` is
   trustworthy.
4. **The exists short-circuit still POSTs** (mirrors `mint-drop`) — rests on
   the assumption that re-POST idempotency is the right recovery for a
   dropped hand-off.
5. **Caption rule: `en` exactly, else first `en-*` sorted, manual over auto**
   — rests on the assumption that lexicographic choice among en-variants is
   acceptable and that non-tag keys (`english`, `enm`) must not count.
6. **`--no-post`/`--drops`/`--api` verified by reuse of mintdrop's resolvers
   plus manual runs, with no automated CLI-level test of `main()`** — attack
   whether that indirect coverage satisfies the AC's "behave as in
   mint-drop".
7. **`startedAt` refusal when neither `release_timestamp` nor `upload_date`
   exists** — an interpretation of the AC (which names only the two sources);
   the frozen intent's "each refusal named" is read as covering it.
8. **Settings gains a DEFAULTED `acquisition` field** — rests on the
   assumption that a defaulted block does not violate the project's
   no-silent-fallback posture because config.yaml carries it explicitly.

## History a reviewer needs

- Baseline `5cdfce7` is the wave dispatch commit; the branch was cut from it
  and never rebased. Five other lanes build beside this one; the wave
  footprint (`build-prompt-story-6-2-2026-08-30.md` table) is a contract —
  an edit outside it is a finding even if technically sound.
- The owner superseded Addendum 2 of the 2026-08-29 sprint change proposal:
  6.2 no longer waits for 11.2.
- The machine's Homebrew yt-dlp was upgraded 2026.07.04 → 2026.08.19 during
  the build (stale extractor gave HTTP 403 on media).

## Verification baseline (a deviation during review is a finding, not noise)

- `uv run --project server pytest server/tests/test_youtube.py -q` — 43
  passed, 1 skipped (network test, named reason).
- `make test-fast` — 1444 passed, 1 skipped.
- `make test` — 1770 passed, 1 skipped, web build green, exit 0.
- `MM_YOUTUBE_NETWORK_TEST=1 uv run --project server pytest server/tests/test_youtube.py::test_real_youtube_acquisition_end_to_end -o mm_fast_test_budget_seconds=600 -q`
  — passed for real (19s public video; free; no POST).
- `python3 _bmad/scripts/branch_conflicts.py --against story/6-2` — clean
  except pairs involving `story/11-2-review` (expected per wave rules).
