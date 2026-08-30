# Reviewer handoff — Story 1.4: Screen Identification & Screenshots

You are reviewing a completed, pushed change. Report findings; do not apply fixes.

## Repo and range

- Repo: `/Users/devopsterus/current/cohort/meetingminer` (GitHub `tgoeke/meetingminer`)
- Branch: `main`, in sync with `origin/main`
- Review range: `ea33274e1bc3773959c1bcdb7eaf947932ccf963..HEAD`

Commits in the range:

- `8d435e26dc8aab6a0e048deedf351abecccd18cf` — feat(pipeline): story 1.4 — screen identification and screenshots **(this story)**
- `59b950b8e4286977842701fbbf5b454755dd4e6b` — docs: check off the story 1.3 review findings **(different story — bookkeeping only, see below)**
- `99915c38b865c515e45f40512a27d6015a130b4b` — chore: sync sprint status for stories 1.4 and 1.8 **(different story — bookkeeping only)**

The two bookkeeping commits touch no source. `59b950b` ticks ten already-fixed
checkboxes in the story-1.3 spec; each was traced into current code before
ticking, and that tracing is itself worth a skeptical look if you want it, but
the code it refers to landed in `ea33274`, before this range. `99915c3` edits
`sprint-status.yaml` only.

## Specification

`_bmad-output/implementation-artifacts/spec-1-4-screen-identification-screenshots.md`

- The `<intent-contract>` block (Intent, Boundaries & Constraints, I/O & Edge-Case Matrix) is **frozen intent**. If you believe it is wrong, say so as a finding — but it is not planner work.
- Everything below it — Code Map, Tasks & Acceptance, Design Notes, Verification — is **planner work you may attack freely**. The design decisions listed further down were made there.

The human-owned source of the intent is `_bmad-output/planning-artifacts/epics.md`, "Story 1.4: Screen Identification & Screenshots" (four acceptance criteria).

## Architecture authority

`_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md`, read-only. The decision records that govern this change:

- **AD-8** (all model calls go through configured ports) — the `Ocr` port and its two engines. Feature code must never import a provider SDK; swapping engines must be a `config.yaml` edit.
- **AD-10** (one config file drives everything) — every threshold this story introduces belongs in `config.yaml`, not as a code constant.
- **AD-3** (one content root, relative paths only) — screenshots live under `MM_CONTENT_ROOT/meetings/<id>/screenshots/`; the DB stores root-relative POSIX paths.
- **AD-5** (table ownership) — cross-meeting entities (screens) are upserted by identity key and **never** deleted by a stage rerun; per-meeting evidence (screenshots) is replaced.
- **AD-11** (jobs are Postgres rows advanced by the host worker) — every stage idempotent, overwriting only rows keyed to that job's meeting; the api never executes a stage.
- **AD-1 / AD-13** — transcript-only drops skip the video stages; the drop directory is read-only after intake.
- **AD-9** (infra in Docker, code on host) — Apple Vision is a macOS framework, so the worker cannot be containerized.
- ERD, `SCREEN ||--o{ SCREENSHOT` and `MEETING ||--o{ SCREENSHOT` — names and relationships are fixed; attributes belong to the code.

Also relevant: **NFR8** (over-capture preferred to loss) and **NFR2** (distinct captures stay under one per minute of meeting duration) in `epics.md:59,65`. These pull in opposite directions; see the design decisions.

## Scope

**In scope** — the files in `8d435e2`:

- `server/meetingminer/adapters/ocr/{port,apple_vision,tesseract,__init__}.py`
- `server/meetingminer/pipeline/screens.py` (decision core), `stages/ocr.py`, `stages/screens.py`, `stages/__init__.py`
- `server/meetingminer/pipeline/outputs.py` (extracted durability helper) and `stages/frames.py` (rewritten on it, intended to be behavior-preserving)
- `server/meetingminer/pipeline/runner.py` (transcript-only cleanup; commit-hook placement)
- `server/meetingminer/migrations/0003_screens_screenshots.sql`
- `server/meetingminer/config.py`, `config.yaml`, `server/meetingminer/worker/main.py`
- `server/pyproject.toml`, `server/uv.lock`, `infra/Makefile`
- `server/tests/{conftest,test_screens_core,test_ocr_adapter,test_output_dir_swap,test_worker_runner,test_config,test_migrations}.py`

**Out of scope**

- Stories 1.5–1.6 functionality (`transcribe`, `align`, `moments`) and Epic 4's `extract` — a recording job legitimately pauses at `transcribe`.
- Story 1.7 projections (Neo4j, Meilisearch), story 1.9 SSE and any UI.
- `pull_transcript/` — vendored, read-only, never modified by this story.
- Items already recorded in the spec's frontmatter `deferred` list and in `_bmad-output/implementation-artifacts/deferred-work.md`. Re-finding them is fine; treat them as known.

## Design decisions to attack

Each is a choice plus the assumption under it. The planner is not a neutral judge of its own calls.

1. **"Bitrate-delta" is implemented as the relative change in encoded JPEG byte size between consecutive sampled frames.** Assumption: the sampled JPEG's size is a usable proxy for the video's bitrate movement, and it is the only cue that fires where there is no text (video playback, camera gallery). The literal reading — per-packet or GOP bitrate from `ffprobe`, or ffmpeg scene detection against the recording itself — was not implemented, which also means capture instants are confined to story 1.3's 2-second sampling grid.

2. **Dwell is a *gated* re-capture, not a periodic one.** A capture re-fires only when it has run `dwell_seconds` (20) **and** its text has drifted below `dwell_drift_threshold` (0.9) against the capture anchor. Assumption: NFR8's over-capture bias does not require re-capturing an unchanged static screen every 20 seconds. The opposite reading — unconditional periodic re-capture — is defensible from NFR8 alone.

3. **Screen identity is `sha256(normalized OCR text)` with a similarity fallback.** Exact key hit reuses the row; otherwise the best existing screen scoring `>= lineage_threshold` (0.8) is reused. Assumption: normalized text is stable enough across renderings and engines to be an identity. Note the identity carries no engine or recognizer-revision component (recorded as deferred).

4. **A textless signature is scoped to its meeting** (`meeting:<id>:<ordinal>`) rather than hashed, below `min_signature_tokens` (1). Assumption: collapsing every textless screen in the corpus onto one row is worse than minting per-meeting rows that never gain lineage.

5. **View type is a first-match-wins rule over block geometry** (`block_count`, `text_density`, `mean_block_height`) with four config thresholds. Assumption: a deterministic, tunable rule is the right shape because Epic 5 scores it, so it must never become a model call. The thresholds have no derivation from real imagery — they were chosen by the planner.

6. **`ocr.fallback` was added to the config binding.** Assumption: one `engine:` key cannot express "Apple Vision primary, Tesseract swappable fallback", so the binding mirrors `llm.roles.*.fallback`. The fallback engages on host unavailability only, never on a recognition failure.

7. **The `frames` durability logic was extracted into `OutputDirSwap` and shared.** Assumption: duplicating logic the story-1.3 review had already hardened would duplicate its bugs. This rewrites story-1.3 code; it is intended to be behavior-preserving and is worth checking as a regression surface.

8. **A screenshot is a byte copy of the most text-rich sampled frame**, not a fresh extraction from the video at full resolution, and not a hardlink.

9. **Ten new numbers ship in `config.yaml`** with no derivation from the eval design and no test asserting the shipped values produce the NFR8 bias or stay inside NFR2.

## History you need to tell a regression from a pre-existing condition

- `stages/frames.py` is a **rewrite on top of the new shared helper**, not new logic. Its previous form is at `ea33274:server/meetingminer/pipeline/stages/frames.py`. Behavior differences there are regressions; the guards and the staging/backup dance themselves came from the story-1.3 review.
- `runner.py`'s advisory lock, claim-time schema revalidation, source-PTS frame offsets and requeue-on-DB-error all landed in `ea33274` (story 1.3) and are **not** this story's work.
- The four review layers that ran before this handoff already patched 17 findings. The spec's `## Review Triage Log` lists every one. Two of those patches were proved necessary by mutation testing — killing the `size-delta` cue and deleting the lineage branch both passed the whole suite beforehand.
- Migration `0003` is already applied to the development database. Editing it in place would drift from that database silently (the project has no migration checksums — a known deferred item), which is why one low-severity finding about a missing `capture_cues` CHECK was deferred rather than patched.

## Verification baseline

Current results, so a skip or failure during review reads as a finding rather than noise:

- `uv run --project server pytest server/tests` — **294 passed, 0 skipped** (needs the compose Postgres: `make infra-up`).
- `make test` — 294 passed, web build succeeds unchanged (no API surface change, so the committed TS client stays valid).
- `make migrate && make migrate` — nothing to apply twice; `schema_migrations` holds `0003_screens_screenshots.sql` applied once.
- `uv run --project server python -c "from meetingminer.config import load_config; from meetingminer.adapters.ocr import build_ocr; print(build_ocr(load_config().settings.ocr))"` — `AppleVisionOcr`.
- Live stack: a real 57-minute meeting reached `probe/frames/ocr/screens` `done` with `transcribe` `queued` — 1727 frames, 1727 OCR rows, 188 screenshots, every stored path relative and present on disk; every pipeline log record since the current worker start carries `job_id` and `stage`.
- `ffmpeg`, `ffprobe`, `tesseract` and PyObjC/Vision are all present on this machine, which is why nothing skips. Tesseract is deliberately **not** in `make check-tools`; its tests skip with a named reason where it is absent.

Known measurement, already deferred, stated so you do not re-derive it: across all nine real meetings processed, captures per minute are 1.23, 2.19, 3.00, 3.27, 4.36, 6.42, 6.61, 7.63 and 16.99 — every one above NFR2's cap of one per minute.

## Required output

Write your findings to `_bmad-output/implementation-artifacts/review-story-1-4-2026-08-18.md`, matching the structure of the existing `review-story-1-3-2026-08-18.md`:

- A header block: date, content reviewed (range and branch), specification, lenses used with signal counts, exclusions, and how verification actually went for you.
- Findings grouped by theme, numbered, each naming the file and line, the concrete trigger, the consequence, and a suggested fix. Mark findings confirmed by more than one independent lens with `(xN)`.

Report findings. Do not apply fixes.
