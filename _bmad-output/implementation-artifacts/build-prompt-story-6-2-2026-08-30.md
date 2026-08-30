# Builder handoff — Story 6.2: YouTube Acquisition Command

Agent: `bmad-build-auto`. Read `wave-2026-08-30-rules.md` in this directory
first; it carries the wave-wide rules and the conflict check you must pass.

- Repository: `/Users/devopsterus/current/cohort/meetingminer`
- Worktree: `/Users/devopsterus/current/cohort/meetingminer-wt/6-2`, branch `story/6-2`
- Story: `_bmad-output/planning-artifacts/epics.md` → "Story 6.2: YouTube
  Acquisition Command" (FR33). Six Given/When/Then clauses; derive the spec
  from them. Story 6.2a (playlists) is NOT in scope.
- Context: `_bmad-output/implementation-artifacts/epic-6-context.md`, the 6-1
  design set under `_bmad-output/planning-artifacts/ux-designs/`, story 6.6
  (`spec-6-6-youtube-deep-links.md`) for how `youtube:<videoId>` source ids
  are already consumed downstream.
- Owner decision superseding Addendum 2 of the 2026-08-29 sprint change
  proposal: 6.2 no longer waits for 11.2. It runs now, inside the footprint
  below.

## Footprint — the only files and regions you may change

| Path | Allowed edit |
|---|---|
| `server/meetingminer/youtube.py` | NEW. URL classification, `yt-dlp`/`ffmpeg` presence and refusal matrix, download (the exact format selector in the AC), caption selection → VTT, `info.json` → metadata mapping, the `exists` short-circuit via `find_existing_drop`, and a `__main__` entry so `python -m meetingminer.youtube` is the command. No `[project.scripts]` entry — `server/pyproject.toml` is not yours. |
| `server/meetingminer/mintdrop.py` | Keyword overrides on `mint()` (main lines 615–630) and `build_metadata()` (541–556) that default to today's behaviour: `source_id`, `started_at` + precision/source, `provenance` extras, `participants` omission. Nothing else in the file — story 6.3 edits its CLI and file classification next and must find them untouched. |
| `server/meetingminer/config.py` | NEW class `AcquisitionConfig` (`youtube.max_duration_minutes: int = 180` and whatever else the refusal matrix needs) inserted immediately BEFORE `class Settings` (main line 689); field `acquisition: AcquisitionConfig` added as the LAST field of `Settings`. No other line. |
| `config.yaml` | `acquisition:` block appended at the END of the file. |
| `infra/Makefile` | `youtube-drop:` target inserted immediately AFTER the `mint-drop` recipe (main lines 544–553), before `puller-archive-check`. `URL=` required; `--no-post`/`--drops`/`--api` pass through as `mint-drop`'s do. No other Makefile line. |
| `docs/README.md` | "Ingesting a YouTube video" section directly after "Bringing your own recording". |
| `server/tests/test_youtube.py`, `server/tests/fixtures/youtube/` | NEW. Offline coverage of URL classification, `info.json` mapping, the refusal matrix and the `exists` short-circuit; the single network test behind an env flag, `slow`-marked. |
| `_bmad-output/implementation-artifacts/` | Your spec, `sprint-status.yaml`, `sprint-notes.md`, `review-prompt-story-6-2-<date>.md`. |

Not yours: `server/tests/test_mint_drop.py` (add your mint-override tests to
`test_youtube.py`), `server/tests/conftest.py`, root `README.md`, `AGENTS.md`,
`docs/backlog.md`, `project-context.md`, `server/pyproject.toml`, anything under
`web/`. `yt-dlp`/`ffmpeg` are checked at run time by name (AC 1), not added to
`check-tools`.

## Design constraints

- Refuse before writing anything; every refusal is named (AC 1). Duration cap
  from `acquisition.youtube.max_duration_minutes`.
- `find_existing_drop(drops_root, "youtube:<videoId>")` answers before any
  media download (AC 2); prove "no network traffic for media" in a test by
  asserting the downloader is never invoked.
- Assembly goes through `mint()`'s staging → validate → atomic-rename path via
  the new keyword overrides (AC 4). No second finalize implementation.
- `metadata.json` field list exactly as the AC: `sourceId`, `corpus: real`,
  `startedAt` from `release_timestamp` (second) else `upload_date` (day) with
  the matching precision, `provenance` {tool, url, channel, durationSeconds,
  ytDlpVersion, formatId} plus the per-file sha256/byteSize block `mint-drop`
  already writes; `participants` omitted.
- Fail closed, fail named, fail before writing — the repository invariant.

## Verification

- `uv run --project server pytest server/tests/test_youtube.py -q`
- `make test-fast`; `make test` once before `review`.
- `python3 _bmad/scripts/branch_conflicts.py --against story/6-2` → clean.
- One real run with a short public video is allowed (it is free): `make
  youtube-drop URL=<url> --no-post` equivalent, then inspect the drop. Do not
  POST to the shared api from a test.

## Completion

Spec `status: review`, `6-2-youtube-acquisition-command: review` in
`sprint-status.yaml`, review prompt written, all pushed, SHAs reported.
