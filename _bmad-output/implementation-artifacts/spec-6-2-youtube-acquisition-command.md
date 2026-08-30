---
title: 'Story 6.2: YouTube Acquisition Command'
type: 'feature'
created: '2026-08-30'
status: 'review'
baseline_revision: '5cdfce72813d68c2d81f5e02f715b8863f8492af'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/build-prompt-story-6-2-2026-08-30.md'
  - '{project-root}/_bmad-output/implementation-artifacts/wave-2026-08-30-rules.md'
warnings: [oversized]
deferred:
  - summary: >-
      The one network test is env-flag-gated but not `slow`-marked: adding any
      `pytest.mark.slow` requires the matching one-line addition to SLOW_TESTS
      in server/tests/test_compose_contract.py (exact-set AST pin, lines
      471-525), and that file is outside this story's wave footprint. At
      integrate, add `"test_youtube::test_real_youtube_acquisition_end_to_end"`
      to SLOW_TESTS and a `pytest.mark.slow(reason=...)` decorator to the test.
    location: 'server/tests/test_compose_contract.py:471'
    severity: low
---

<intent-contract>

## Intent

**Problem:** Public talks and recorded community meetings on YouTube cannot enter the corpus: there is no acquisition command, and the only producers are the Teams puller and `mint-drop` for local files (FR33).

**Approach:** A new `python -m meetingminer.youtube` command (`make youtube-drop URL=<url>`) that classifies the URL offline, short-circuits on an already-minted `youtube:<videoId>`, refuses by name before writing anything, downloads a browser-playable MP4 plus English captions converted to VTT with `yt-dlp`, and assembles the drop through `mint()`'s existing staging → validate → atomic-rename path via new keyword overrides that default to today's behaviour.

## Boundaries & Constraints

**Always:**
- Refuse before writing anything; every refusal is a named error with non-zero exit stating the rule and remediation: non-YouTube URL, private/removed video, no video stream, `yt-dlp` or `ffmpeg` missing from PATH (checked at run time by name, never added to `check-tools`), duration over `acquisition.youtube.max_duration_minutes` (committed default 180).
- The video id is parsed from the URL offline; `find_existing_drop(drops_root, "youtube:<videoId>")` answers before any `yt-dlp` invocation; on `exists` the downloader is never invoked and no network traffic for media occurs.
- Assembly goes only through `mint()`; no second staging/finalize implementation. The new keyword overrides (`source_id`, started-at value+precision+source, `provenance_extra`) default to today's behaviour so every existing call site is byte-identical in effect.
- `metadata.json` carries exactly: `sourceId` `youtube:<videoId>`, `corpus` `real`, `startedAt` from `release_timestamp` (precision `second`) else `upload_date` (precision `day`, T00:00:00Z), `provenance` with `tool`, `url` (canonical watch URL — this is what `DropContents.stream_url` and story 6.6's deep links read), `channel`, `durationSeconds`, `ytDlpVersion`, `formatId`, plus the per-file sha256/byteSize `files` block `mint()` already writes; `participants` omitted (omitted means "source did not look").
- `info.json` is read for metadata and never copied into the drop; the recording is `bv*[ext=mp4][vcodec^=avc1]+ba[ext=m4a]/b[ext=mp4]` merged to MP4; captions are English manual when present else auto-generated, converted to VTT.
- `--no-post`, `--drops`, `--api` behave exactly as `mint-drop`'s (reuse `resolve_api_url`, `resolve_drops_root`, `post_ingest`, `ingest_command`).
- Footprint is the wave contract: only `server/meetingminer/youtube.py` (new), the two mintdrop keyword-override regions, `config.py` insert before `Settings` + last `Settings` field, `config.yaml` EOF append, `infra/Makefile` target after `mint-drop`, `docs/README.md` section, `server/tests/test_youtube.py` + `server/tests/fixtures/youtube/` (new), and this story's `_bmad-output` artifacts.
- Tests are offline (subprocess/`shutil.which` stubbed, recorded `info.json` fixtures, `tmp_path` drops roots — no store fixtures, no conftest edits); the single network test runs only behind `MM_YOUTUBE_NETWORK_TEST=1` with a named skip otherwise.
- No paid model calls; never POST to the shared api from a test; never start the shared api/worker.

**Block If:**
- The story cannot land without editing a file outside the footprint beyond the recorded SLOW_TESTS deferred gap.
- `story/6-2` diverges from its upstream mid-run.

**Never:** playlists (`--playlist` is story 6.2a); `server/pyproject.toml` (no `[project.scripts]`, no yt-dlp dependency — subprocess by name); `server/tests/test_mint_drop.py`, `server/tests/conftest.py`, `test_compose_contract.py`; root `README.md`, `AGENTS.md`, `docs/backlog.md`, `project-context.md`; anything under `web/`; `mintdrop.py` beyond the two named regions (story 6.3 edits its CLI and classification next).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| New watch video | `youtube.com/watch?v=<11-char id>` | probe → download MP4+captions → `mint()` → `created`, POST unless `--no-post` | No error expected |
| Already minted | id whose `youtube:<id>` drop exists | `exists` before any yt-dlp call; still POSTs (mirrors `mint-drop`) | downloader/probe never invoked |
| youtu.be / shorts URL | `youtu.be/<id>`, `youtube.com/shorts/<id>` | same id extracted; watch URL canonicalized for provenance | No error expected |
| watch URL with `&list=` | video id present | single video acquired (`--no-playlist`); list ignored | No error expected |
| Non-YouTube / playlist-only URL | other host; `/playlist?list=…`; no `v=`; bad id shape; non-http scheme | named refusal `not a YouTube video URL` | before any subprocess |
| Tool missing | `yt-dlp` or `ffmpeg` not on PATH | named refusal naming the tool and `brew install` remediation | before any network |
| Private/removed | probe exits non-zero | named refusal carrying yt-dlp's own message | nothing written |
| No video stream | probe info has no format with a video codec | named refusal | nothing written |
| Over duration cap | `duration` > cap minutes | named refusal stating duration, cap, and the config key | before download |
| `release_timestamp` present | e.g. `1755088630` | `startedAt` second-precision ISO, `startedAtSource: release_timestamp` | — |
| Only `upload_date` | e.g. `20260812` | `startedAt` `T00:00:00Z`, precision `day`, source `upload_date` | — |
| Neither timestamp | pathological info.json | named refusal (never guessed from mtime) | nothing written |
| Manual `en`/`en-*` captions | `subtitles` carries them | that track, converted VTT → `transcript.vtt` | — |
| Auto captions only | `automatic_captions` only | auto track VTT; no refusal | — |
| No English captions | neither dict has `en*` | recording-only drop; still valid | — |

</intent-contract>

## Code Map

- `server/meetingminer/mintdrop.py` — `build_metadata()` def at `:541`, `mint()` def at `:615`. Reuse unchanged: `resolve_api_url`, `resolve_drops_root`, `find_existing_drop`, `post_ingest`, `ingest_command`, `_report`, `MintResult`, `read_metadata` (via domain), `_load_cli_config`, `slugify`/`drop_name` (used by `mint()`), `_iso_second_utc`. `mint()` already: digests files → derives `sha256:` source id → identity lock → `find_existing_drop` → started-at → `build_metadata` → `_assemble`. Overrides slot in where the sha-id and started-at are derived.
- `server/meetingminer/config.py` — `_StrictModel` (`extra="forbid"`) `:99`; `ApiConfig` ends `:687`; `class Settings` `:689` with fields ending `api: ApiConfig`. Insert both new classes immediately before `:689`; `acquisition` becomes the last `Settings` field with `default_factory` so every fixture config.yaml that predates the block still validates (the committed `config.yaml` carries it explicitly per AD-10).
- `config.yaml` — currently ends with the `stores:` block; append `acquisition:` at EOF.
- `infra/Makefile` — `check-env` `:182`; `mint-drop` recipe `:544-553`; insert `youtube-drop:` directly after it, before the `puller-archive-check` comment block. `URL=` guarded with a named error; `YT_ARGS` passes `--no-post`/`--drops`/`--api` through like `MINT_ARGS`.
- `server/meetingminer/domain/drops.py` — `DropContents.stream_url` `:302` returns `provenance.url` when http(s)+host (story 6.6's deep-link source); `title` `:357` reads `provenance.title` (already written by `build_metadata`). Read-only.
- `server/meetingminer/pipeline/media.py` — `FFPROBE`/`FFMPEG` name constants `:22-23`; the tool-by-name subprocess pattern to mirror. `mint()`'s `_assert_is_a_video` still needs `ffprobe`, which ships with `ffmpeg`.
- `docs/source-drop.schema.json` — `sourceId` any non-empty string (`youtube:` prefix legal); `provenance` open object; `participants` optional; `day` precision forces `T00:00:00(Z|+00:00)`. Read-only; validate fixtures against it as `test_mint_drop.py` does.
- `server/tests/test_compose_contract.py` — READ-ONLY: exact-set AST pins `SLOW_MODULES` `:396`, `SLOW_TESTS` `:471` over every `server/tests/test_*.py`; any new `slow` mark fails the fast suite. Drives the deferred item above.
- `server/tests/test_mint_drop.py` — style donor (schema validation helpers, ffprobe stubbing); do not edit.
- `_bmad-output/implementation-artifacts/spec-6-6-youtube-deep-links.md` — downstream consumer contract; its deferred note (moments stage nulls `source_deep_link` when replay exists, filed B-34) is pre-existing and out of scope here.

## Tasks & Acceptance

**Execution:**
- `server/meetingminer/config.py` -- insert `YoutubeAcquisitionConfig` (`max_duration_minutes: int = Field(default=180, gt=0)`) and `AcquisitionConfig` (`youtube: YoutubeAcquisitionConfig = Field(default_factory=…)`) immediately before `class Settings`; add `acquisition: AcquisitionConfig = Field(default_factory=AcquisitionConfig)` as the LAST `Settings` field -- the refusal cap is configuration (AD-10), defaults keep pre-existing config fixtures valid.
- `config.yaml` -- append the commented `acquisition:` block (`youtube.max_duration_minutes: 180`) at EOF -- the committed value is explicit even though the model defaults.
- `server/meetingminer/mintdrop.py` -- `build_metadata()`: add `provenance_extra: dict[str, Any] | None = None`, merged into the provenance dict AFTER the defaults so a caller may deliberately override `tool`; `mint()`: add `source_id: str | None = None` (None → today's `sha256:` derivation; set → used verbatim for identity, lock, and lookup), `started_at_override: tuple[str, str, str] | None = None` (`(startedAt, precision, source)`; None → today's `--started-at`/container path), `provenance_extra` passthrough. No other line -- one finalize implementation, defaults preserve today's behaviour bit-for-bit.
- `server/meetingminer/youtube.py` -- NEW: `YoutubeError`; `video_id_from_url()` (hosts `youtube.com`/`*.youtube.com`/`youtu.be`, http(s) only, paths `/watch?v=`, `/shorts/<id>`, `youtu.be/<id>`, 11-char `[A-Za-z0-9_-]` id, everything else refused); `ensure_tools()`; `probe()` (`yt-dlp -J --no-playlist`); refusal matrix (`classify_probe_failure`, video-stream check over `formats`, duration cap from `AppConfig.settings.acquisition`); `select_captions()` (manual `en`/`en-*` first, else auto, else none); `download()` (format selector from the AC, `--merge-output-format mp4`, `--write-info-json`, caption flags + `--convert-subs vtt`, private temp dir); `metadata_overrides_from_info()` (startedAt triple + provenance extras incl. `ytDlpVersion` from `yt-dlp --version`); `acquire()` orchestrating exists-short-circuit → probe → download → `mint()`; `main()` with `URL`, `--no-post`, `--drops`, `--api` reusing mintdrop's report/POST flow; `__main__` guard -- the command is `python -m meetingminer.youtube`.
- `infra/Makefile` -- `youtube-drop: check-env` after the `mint-drop` recipe: venv guard, `URL=` guard with a named error, `cd $(ROOT) && $(VENV)/bin/python -m meetingminer.youtube "$(URL)" $(YT_ARGS)` -- same door, same pass-through convention.
- `docs/README.md` -- "Ingesting a YouTube video" section directly after the "Bringing your own recording" section: command, refusal list, exists behaviour, caption rule, `--no-post`/`--drops`/`--api` pointer -- docs land with the code.
- `server/tests/fixtures/youtube/` -- recorded `info.json` fixtures (full: release_timestamp + manual subs; auto-only; no-english; audio-only formats; upload_date-only), pruned to the fields read -- offline truth for the mapping tests.
- `server/tests/test_youtube.py` -- NEW, offline: URL classification table (valid and refused); info.json → overrides mapping incl. both startedAt paths and caption selection; the refusal matrix (which-stubs, probe-failure stub, duration cap via injected config, no-video-stream fixture) asserting drops root untouched; exists short-circuit (pre-minted `youtube:<id>` drop in `tmp_path` root, downloader/probe stubs that fail the test if invoked); mint-override coverage: with overrides → AC metadata shape (schema-validated), without → today's `sha256:`/`tool: mint-drop` behaviour unchanged; Makefile target presence + URL guard by parsing `infra/Makefile`; env-flag network test (`MM_YOUTUBE_NETWORK_TEST=1`, named skipif otherwise, docstring naming the `-o mm_fast_test_budget_seconds=600` run instruction) -- the AC's test clause without network.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` + `sprint-notes.md` -- flip `6-2-youtube-acquisition-command` and record the narrative under a dated 6-2 heading -- wave tracking rule.

**Acceptance Criteria:**
- Given the six Given/When/Then clauses of "Story 6.2: YouTube Acquisition Command" in `_bmad-output/planning-artifacts/epics.md`, when the suite and a manual `--no-post` run are inspected, then each clause holds as written (the I/O matrix above operationalizes them).
- Given `uv run --project server pytest server/tests/test_youtube.py -q` offline, when it runs, then every test passes with the network test skipped by name.
- Given `make test-fast` and (once, before review) `make test`, when they run, then they pass — in particular `test_mint_drop.py` and `test_config.py` unchanged and green, proving the overrides default to today's behaviour.
- Given `python3 _bmad/scripts/branch_conflicts.py --against story/6-2`, when run before the final push, then every pair not involving `story/11-2-review` is clean.

## Spec Change Log

- 2026-08-30 (planning): The build prompt asks for the network test to be `slow`-marked; `server/tests/test_compose_contract.py` pins the slow set as an exact AST-derived set (`SLOW_TESTS` `:471`), so the mark REQUIRES an off-footprint edit there. Resolution: env-flag skipif without the mark (legal — the test touches no store fixture, and a skipped test never trips the fast budget), plus the frontmatter deferred item handing the integrator the exact one-line pin addition. KEEP: never edit `test_compose_contract.py` from this branch.

## Review Triage Log

## Design Notes

- `yt-dlp` is a subprocess by name, mirroring `pipeline/media.py`'s ffmpeg pattern: `server/pyproject.toml` is off-footprint, and a CLI tool checked at run time (AC 1) needs no import. Probe (`-J --no-playlist`) carries the whole refusal matrix before a byte is downloaded; the download phase writes `info.json` beside the media in a private temp dir and THAT file is the metadata source (`format_id` of the actually-selected format lives only there), satisfying "read for metadata but not copied into the drop".
- `provenance_extra` merges after the defaults so `tool: youtube-drop` replaces `mint-drop` without a second `tool` parameter; the per-file `files` block stays exactly what `build_metadata` writes today (its `sourcePath` names the temp download path — provenance of the copy, harmless and honest).
- The exists path still POSTs (as `mint-drop`'s exists does) so a dropped hand-off is recoverable by re-running the same command; `--no-post` prints the same `curl` line via `ingest_command`.

## Verification

**Commands:**
- `uv run --project server pytest server/tests/test_youtube.py -q` -- expected: all pass, network test skipped with its named reason.
- `make test-fast` -- expected: green (Postgres up; store-free suites + fast set).
- `make test` -- expected: green once before status flips to review (twins up; runs `test_compose_contract` slow-pin checks against this branch).
- `python3 _bmad/scripts/branch_conflicts.py --against story/6-2` -- expected: `clean` against `main` and every `story/*` except pairs involving `story/11-2-review`.
- One real run (free, allowed): `make youtube-drop URL=<short public video> YT_ARGS='--no-post --drops <scratch child of MM_DROPS_ROOT>'` -- expected: `created`, schema-valid metadata with the AC field list; do NOT POST to the shared api.

## Auto Run Result

Status: review (per the wave contract this run never marks the story done;
adversarial review is external, carried by
`review-prompt-story-6-2-2026-08-30.md` — the in-session reviewer layers were
not run as subagents, matching the repo's established external-review path).

**Summary.** `make youtube-drop URL=<url>` acquires a published YouTube video
as a source drop through the one intake door: offline URL classification,
`exists` on `youtube:<videoId>` before any yt-dlp invocation, the named
refusal matrix at probe time, MP4+captions download into a private temp dir,
and assembly through `mint()` via three new default-preserving keyword
overrides.

**Files changed.**
- `server/meetingminer/youtube.py` (new) — the acquisition command and `__main__` entry.
- `server/meetingminer/mintdrop.py` — `source_id`, `started_at_override`, `provenance_extra` keyword overrides on `mint()`/`build_metadata()`, defaulting to today's behaviour.
- `server/meetingminer/config.py` — `YoutubeAcquisitionConfig`/`AcquisitionConfig` before `Settings`; `acquisition` as last, defaulted `Settings` field.
- `config.yaml` — `acquisition:` block appended at EOF (cap 180).
- `infra/Makefile` — `youtube-drop:` target after `mint-drop`, `URL=` guarded, `YT_ARGS` pass-through.
- `docs/README.md` — "Ingesting a YouTube video" section after "Bringing your own recording".
- `server/tests/test_youtube.py` + `server/tests/fixtures/youtube/` (new) — 43 offline tests + env-flagged network test.
- Sprint artifacts: `sprint-status.yaml` (`6-2-youtube-acquisition-command: review`), `sprint-notes.md` entry, this spec.

**Review findings breakdown.** No in-session review pass ran (external review
pending via the reviewer prompt); patched 0, deferred 1 (the SLOW_TESTS pin,
recorded in frontmatter at planning time), rejected 0. Follow-up review
recommendation: false (score 0).

**Verification performed.**
- `uv run --project server pytest server/tests/test_youtube.py -q` — 43 passed, 1 skipped (network test, named reason).
- `make test-fast` — 1444 passed, 1 skipped.
- `make test` — 1770 passed, 1 skipped (the env-flagged network test), web build green, exit 0.
- `MM_YOUTUBE_NETWORK_TEST=1 … test_real_youtube_acquisition_end_to_end -o mm_fast_test_budget_seconds=600` — passed against a real 19s public video (created + exists, schema-valid, no POST) after upgrading the machine's stale Homebrew yt-dlp 2026.07.04 → 2026.08.19.
- Manual CLI: `--no-post` run minted a schema-valid drop into a scratch child root; re-run reported `exists`; refusals verified by name.
- `python3 _bmad/scripts/branch_conflicts.py --against story/6-2` — clean except pairs involving `story/11-2-review` (expected per wave rules); re-run before the final push.

**Residual risks.**
- The network test is env-flagged but not `slow`-marked until the deferred `SLOW_TESTS` pin lands at integrate.
- `provenance.files[].sourcePath` for a YouTube drop names the transient download directory — honest provenance of the copy, but a path that no longer exists after the run.
- Extractor drift: a stale yt-dlp fails the real download (HTTP 403 seen with 2026.07.04); the refusal carries yt-dlp's own message, and `ytDlpVersion` in provenance records what ran.
