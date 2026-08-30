# Reviewer handoff — Story 1.11: Screen Capture Retune Against Measured Baselines

You have none of the build run's context. Everything you need is below.

## Repo, branch, and range

- Repo: `/Users/devopsterus/current/cohort/meetingminer`
- Branch: `main`
- Baseline: `a16c19872d4bf72dca393b0ce22dbf17ea160f8b` (`docs: builder handoff prompt for story 1.11`)

The change is committed and pushed. Review range:

```
git diff a16c19872d4bf72dca393b0ce22dbf17ea160f8b..02f1edf
```

Commits in the range that belong to this story:

- `a072cb1` — feat(pipeline): story 1.11 — retune screen capture against measured baselines
- `02f1edf` — docs(story-1.11): spec, review triage, and reviewer handoff

**Two commits in that range are a different story and are not yours to review:** `e693127`
(docs(spec): roll in live corpus, embeddings bake-off, and late-video path) and `85d75ec`
(feat(pipeline): story 1.5 — transcript verification, alignment, participants), plus `cf7a14e`
and `f524f4b`, which are story 1.5's context recompile and its own handoff. Story 1.5 was built
concurrently in the same working tree. To see only this story:

```
git show a072cb1 --stat
git diff a16c1987 02f1edf -- server/meetingminer/pipeline/screens.py \
  server/meetingminer/pipeline/stages/screens.py server/meetingminer/pipeline/frameimage.py \
  server/meetingminer/pipeline/runner.py server/meetingminer/migrations/0004_capture_retune.sql \
  server/meetingminer/config.py config.yaml server/pyproject.toml \
  server/tests/test_screens_core.py server/tests/test_frame_image.py \
  server/tests/test_screens_with_real_pixels.py server/tests/test_worker_runner.py \
  server/tests/test_config.py server/tests/conftest.py
```

Story 1.5 committed only its own hunks, so the six files both stories touched carry only this
story's changes in `a072cb1`. The table below records who owns what in them, in case a hunk still
reads as unrelated.

## Working-tree state — read this before you judge any diff

Six files carry **both** stories' edits and are not separable by file:

| File | This story (1.11) | Story 1.5, not yours to review |
|---|---|---|
| `config.yaml` | the whole `pipeline.screens` block | `stt.model`, the `pipeline.align` block |
| `server/meetingminer/config.py` | `ScreensConfig` fields | `SttConfig.model`, `AlignConfig` |
| `server/pyproject.toml` | `pillow>=11` | `mlx-whisper`, `parakeet-mlx`, the `<3.13` pin |
| `server/tests/conftest.py` | crop table in `EVIDENCE_TABLES`, `FakeOcr.block_x` | STT fixtures, transcript/participant tables |
| `server/tests/test_config.py` | `settle_text_growth_ratio` | `stt.model`, the `align` block |
| `server/tests/test_worker_runner.py` | everything screens-related | stage-pause expectations moved `transcribe` → `moments` |

`server/meetingminer/pipeline/runner.py` interleaves this story's `meeting_crop` delete with story
1.5's `transcript_source` delete in one function. Story 1.5's own files — the stt/diarize adapters,
`transcribe.py`, `align.py`, `alignment.py`, `transcripts.py`, `speakers.py`, `media.py`,
`migrations/0005_*`, `test_worker_transcripts.py` and its siblings — are **out of scope**.

## The spec

`_bmad-output/implementation-artifacts/spec-1-11-screen-capture-retune-against-measured-baselines.md`

- **Frozen intent** — everything inside `<intent-contract>` (Intent, Boundaries & Constraints,
  I/O & Edge-Case Matrix). It came from the story definition; do not treat it as the planner's work.
- **Planner's work, fair game** — Code Map, Tasks & Acceptance, Design Notes, the config defaults
  table, Spec Change Log, Auto Run Result. Attack any of it.

Source documents: `_bmad-output/planning-artifacts/epics.md` (`### Story 1.11` — the acceptance
criteria), and `_bmad-output/specs/spec-meetingminer/capture-measurements.md`, which is the
measured source this story exists to satisfy. `eval-design.md` §2.2 defines the guardrail.

## Architecture authority

`_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md`:

- **AD-10** (one config file) — the story's own acceptance criterion: every threshold from
  `config.yaml`, never a code constant. Check this hard; it is easy to violate quietly.
- **AD-3** (binaries on disk, root-relative paths in the DB) — screenshots and the crop row.
- **AD-5** (disjoint table ownership; `screen` is cross-meeting, upserted by identity key and never
  deleted by a rerun) and **AD-11** (stage idempotence: a rerun replaces only rows keyed to this
  meeting).
- **AD-8** — ffmpeg/Pillow are plain tools, deliberately *not* adapter ports; only OCR/STT/LLM/
  embedder are. Confirm the new imaging code did not become a de facto port, and that no model call
  entered the decision path.
- Spine stage list: screen identity is OCR-text similarity. This story keeps that while removing
  OCR text from *capture* decisions — check the seam.

## Design decisions to attack

Each is stated as the choice plus the assumption under it. The planner is not a neutral judge of
its own calls.

1. **Screenshots stay full-frame; only the change-detection input is cropped.** Rests on reading
   §2's heading ("cropping is an input precondition, not an output concern") as scoping the crop to
   the comparison. The alternative — cropping at the `frames` stage — would also clean the OCR text
   the signature is built from. If that reading is wrong, the fix is a stage earlier.
2. **OCR text and encoded byte size stop deciding captures entirely.** Rests on the assumption that
   cropped pixel change sees every screen change that matters. It measurably does not: two similar
   SharePoint listings, or two sheets of one workbook, can share a capture. Re-adding any text cue
   was measured to break the guardrail on the verification recording (Jaccard < 0.4 → 1.09/min;
   a novelty cue at 0.35 → 1.01/min).

   **This one is settled — do not re-litigate it.** The product owner accepted the trade on
   2026-08-19: the priority is UI views and slide-deck slides, and spreadsheets, file listings and
   other dense-information screens are explicitly lower priority for capture. Both classes that
   matter repaint most of the region when they change, so they sit well above `change_threshold`.
   What is still worth your attention is the *mechanism*, not the trade: whether a new slide or a
   new UI view can ever fail to move `change_threshold` of the cropped region. If you can construct
   that case, it is a real finding.
3. **Dwell-drift was deleted rather than re-based.** Rests on: comparing against the last *emitted*
   shot makes drift cross the line by itself. Verify that with `test_drift_that_never_resets_...`.
4. **The settle rule tests text as well as pixels** (`settle_text_growth_ratio`). This was **not**
   in the original plan; it was added after a by-eye review found the first pass storing a skeleton
   loading state and dropping the populated view of the same spreadsheet. Its justification is a
   measurement taken during the build (32 → 82 cropped blocks while pixels moved 0.009) that lives
   only in the spec's change log, not in `capture-measurements.md`. Attack both the threshold and
   the fact that its evidence never made it into the measurements document.
5. **Avatar-tile gallery is `participant-gallery` plus an `avatar-gallery-unresolved` tag, not a
   fourth view type.** Keeps migration 0003's CHECK and every downstream consumer valid; assumes a
   tag is enough for Epic 5 to score it.
6. **Only the webcam column and the taskbar strip are detected.** Everything else is config, on the
   grounds that wider crop auto-detection is out of scope.
7. **`change_threshold: 0.10`**, below §2's cropped p50 of 0.19 for real changes. Justified by
   NFR8's recall bias; no measurement pins 0.10 specifically. Headroom measured: 0.08 → 51
   captures (0.89/min).

## History you need to tell a regression from a pre-existing condition

- **Two tests fail at the baseline commit**, verified in a clean detached worktree with none of
  this story's changes: `test_ocr_adapter.py::test_parse_tsv_without_page_dimensions_is_a_named_error`
  and `test_worker_runner.py::test_empty_and_populated_stage_logs_carry_the_same_fields`. The second
  asserts `stage.screens.captured.directory is None` on the zero-frame path, but commit `a1bd04a`
  deliberately changed that branch to publish and log an empty directory (story 1.4's fix for stale
  screenshot files). The assertion is stale, not the code. Both were left unrepaired on purpose.
  They make `make test` red for reasons that are not this story's.
- **The first implementation pass shipped 47 captures at 0.816/min and looked correct on every
  metric.** The skeleton defect was found only by opening images. If you are tempted to judge this
  change by its numbers, that is the cautionary case.
- **`capture-measurements.md` was measured on a different recording** (the 61-minute secondary
  demo). Two of its three key findings did not transfer to the 57-minute verification meeting: the
  uncropped noise floor (this meeting's webcam column is static avatar tiles, so cropped and
  uncropped change distributions are equal to two decimals) and the settle timings (§3's median
  0.0 s came from finer sampling). §6 already records that the corpus recordings were never probed.
- **Full-suite runs interleaving with the story-1.5 session returned between 1 and 62 spurious
  failures** from the shared fixed-name test database `meetingminer_test`. Run suites in isolation
  before believing a red result.

## Verification baseline — so a skip or failure during review reads as a finding

- `uv run --project server pytest server/tests` → **448 passed, 2 failed** (the two above).
- `make migrate && make migrate` → `0004_capture_retune.sql` applied once; second run reports
  nothing to apply.
- `pnpm --dir web run build` → succeeds unchanged. (`make test` never reaches it, because the two
  pre-existing failures stop the server suite first.)
- Live re-run of `screens` for meeting `01a0170c-bb04-78c2-832a-4fc2bc555551` (57.56 min, 1727
  frames) → `capture_count=46`, `captures_per_minute=0.799`, `crop=[0.0, 0.0, 0.871875, 0.9389]`,
  `crop_detected=true`, `method="webcam-column+bottom-strip"`, tags
  `{"likely-transition": 2, "avatar-gallery-unresolved": 0}`, `screens_created=0, screens_reused=46`.
  To reproduce: reset that job's `screens` stage to `queued`, set the job to `queued`, and run
  `runner.run_once`.
- The four mutations that the review layers proved the suite could not catch — replacing the pixel
  pair with always-screen-share constants, replacing the detected region with the full frame,
  collapsing the analysis downscale to one pixel tall, and disabling the settle text test — each now
  fail at least one test. Re-run them if you want to check the new tests are not decorative.

## Required output

Write your findings to
`_bmad-output/implementation-artifacts/review-story-1-11-2026-08-19.md`.

Structure: one section per finding, each with location (`file:line`), what is wrong, why it
matters, and the concrete failure it produces. Group by severity. Close with a short verdict.

**Report findings; do not apply fixes.** Ten items are already recorded in the spec's frontmatter
`deferred` list — read it first and do not re-file them; tell us if you think any is misfiled or
under-rated.
