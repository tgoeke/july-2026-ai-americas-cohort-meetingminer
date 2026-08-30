---
title: 'Story 1.11: Screen Capture Retune Against Measured Baselines'
type: 'feature'
created: '2026-08-18'
baseline_revision: 'a16c19872d4bf72dca393b0ce22dbf17ea160f8b'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
  - '{project-root}/_bmad-output/specs/spec-meetingminer/capture-measurements.md'
warnings: ['oversized']
deferred:
  - summary: >-
      Screen identity and cross-meeting lineage still run on whole-frame OCR text, including the
      webcam column this story proved is noise.
    evidence: |-
      `FrameFacts.normalized_text` is deliberately left uncropped and `signature_for` returns it
      verbatim, so it feeds `identity_key_for`, `min_signature_tokens` and `best_lineage_match`
      (AD-5 lineage). The docstring's claim that the column "contributes no text worth excluding"
      is unmeasured, and §2's layout has participant name labels that change as speakers change.
      `crop_blocks` already filters block geometry the same way and could filter the text. Left
      alone because changing what a screen is identified by is beyond this story's ACs and would
      re-key existing `screen` rows.
    location: >-
      server/meetingminer/pipeline/screens.py (signature_for)
    severity: medium
  - summary: >-
      Story 1.4's four view-type geometry thresholds were not re-measured after cropping changed
      the coordinate space they are compared in.
    evidence: |-
      `crop_blocks` renormalizes each box to the region, so on §2's layout every normalized width
      grows about 1.14x and every height about 1.05x, while `gallery_max_blocks`,
      `gallery_max_text_density`, `slide_min_block_height` and `slide_max_blocks` keep their
      story-1.4 values. Renormalizing is a rescale, not an identity. No test covers a frame near a
      geometry boundary before and after cropping, and slide-vs-ui-screen accuracy has no
      denominator until story 5.1's fixtures exist.
    location: >-
      config.yaml (pipeline.screens geometry thresholds)
    severity: medium
  - summary: >-
      The detect-once crop has no guard for a recording whose layout changes part way through.
    evidence: |-
      The survey runs once and its region is used for every frame. A meeting where sharing stops
      and the gallery goes full width keeps the surveyed crop for the rest of the run, with no
      re-detection, no tag, and no fallback - while every other unresolvable case in this story
      gets a tag per NFR8. capture-measurements.md §6 already records that the 117-minute
      recording was never checked for the same geometry and that crop auto-detection is
      unimplemented, so this is that gap arriving in code.
    location: >-
      server/meetingminer/pipeline/frameimage.py (detect_share_region)
    severity: medium
  - summary: >-
      Continuously moving content (a video played inside the meeting) can produce one capture per
      settle timeout, roughly six per minute.
    evidence: |-
      If every frame differs from the emitted shot by more than `change_threshold`, each capture
      opens, never settles, force-emits at `settle_timeout_seconds`, and the next frame cues
      again. Nothing bounds the minimum interval between captures. Not observed on the 57-minute
      meeting, which contains no played video, and adding a minimum-interval knob is a design
      change rather than tuning.
    location: >-
      server/meetingminer/pipeline/screens.py (segment_captures)
    severity: medium
  - summary: >-
      Two test failures reproduce at the baseline commit and leave `make test` red for every story.
    evidence: |-
      Verified at a16c19872d4bf72dca393b0ce22dbf17ea160f8b in a clean detached worktree:
      `test_ocr_adapter.py::test_parse_tsv_without_page_dimensions_is_a_named_error`, and
      `test_worker_runner.py::test_empty_and_populated_stage_logs_carry_the_same_fields`, which
      asserts `stage.screens.captured.directory is None` on the zero-frame path although commit
      a1bd04a deliberately changed that branch to publish and log an empty directory (story 1.4's
      fix for stale screenshot files). The assertion is stale, not the code. Correcting an
      expectation to match code is the one repair this workflow forbids doing unattended.
    location: >-
      server/tests/test_worker_runner.py:1474
    severity: medium
  - summary: >-
      Every frame is decoded twice by the `screens` stage.
    evidence: |-
      `_measure_frames` decodes and measures all N frames, then `_RegionChange.__call__` decodes
      each frame again per comparison plus one re-decode per reference change. The measurements
      the second pass recomputes were already produced one function earlier and discarded.
      Harmless today - the stage runs in about ten seconds over 1727 frames - so caching them is
      an optimisation, not a fix.
    location: >-
      server/meetingminer/pipeline/stages/screens.py (_RegionChange)
    severity: low
  - summary: >-
      `meeting_crop.updated_at` and its `set_updated_at` trigger are unreachable.
    evidence: |-
      The stage only ever DELETEs then INSERTs the row, in `run()` and in
      `_clear_replaced_video_evidence`; nothing UPDATEs the table, so `updated_at` never diverges
      from `created_at`. Fixing it means either an upsert or editing migration 0004, which is
      already applied to the development database - and migration drift detection is itself
      already deferred from story 1.2.
    location: >-
      server/meetingminer/migrations/0004_capture_retune.sql
    severity: low
  - summary: >-
      Migration 0003 still documents the three capture cues this story removed, and historical
      screenshot rows still carry them.
    evidence: |-
      `0003_screens_screenshots.sql` describes `capture_cues` as "text-change, size-delta,
      dwell-drift, first-frame" and omits `region-change`. Story-1.4 rows in the development
      database still hold the old values until their meeting's `screens` stage is re-run. A
      `COMMENT ON COLUMN` belongs in a later migration rather than an edit to either applied file.
    location: >-
      server/meetingminer/migrations/0003_screens_screenshots.sql:80
    severity: low
  - summary: >-
      `meeting_crop.detected` can be false for a meeting that was in fact cropped.
    evidence: |-
      `detected` means only "a webcam column was found", but the bottom-strip scan can still
      remove up to `crop_max_bottom_strip` of the frame with `detected = false` and
      `method = "bottom-strip"`. The stored fractions and the method make the real crop
      recoverable, so nothing is lost, but the boolean reads narrower than its name suggests.
    location: >-
      server/meetingminer/pipeline/frameimage.py (CropRegion.detected)
    severity: low
  - summary: >-
      The spec's I/O matrix and the implemented timeout fallback disagree about which frame is
      emitted when a region never settles.
    evidence: |-
      The matrix row says "the last frame in the window is emitted"; `force_emit` emits
      `choose_representative` - the most text-rich frame of the window - because a transition
      frame is never the richest. The epics acceptance criterion is silent, and the implemented
      behaviour is the better of the two, so the code was left alone; the matrix sits inside the
      read-only intent contract and was not edited.
    location: >-
      server/meetingminer/pipeline/screens.py (_OpenCapture.force_emit)
    severity: low
---

<intent-contract>

## Intent

**Problem:** The shipped `screens` stage decides captures from whole-frame signals — OCR-text Jaccard over the entire 1920×1080 frame, encoded JPEG byte size, and a text-drift dwell rule — and emits at the moment of change. On the 57-minute meeting it produced 188 captures (3.27/min), failing `eval-design.md` §2.2's one-per-minute guardrail by 3.3×, while `capture-measurements.md` records a tuned extractor at 0.86/min on comparable content.

**Approach:** Retune the existing stage against `capture-measurements.md` §2–§4: detect the share region once per recording, compare frames on the cropped region only, fire one cue on change **against the last emitted shot**, emit the first frame at which the region has settled, and classify view type on the measured brightness/saturation pair before any text-geometry rule. Segmentation stays a pure function over per-frame facts; every threshold stays in `config.yaml`.

## Boundaries & Constraints

**Always:**
- AD-10: every threshold introduced or changed arrives from `config.yaml` via `ScreensConfig`/`FramesConfig` — never a code constant. `_StrictModel` is `extra="forbid"`, so removed keys must leave `config.yaml` and every test config fixture together.
- The decision core in `server/meetingminer/pipeline/screens.py` stays pure: no Postgres, no ffmpeg, no OCR engine, no model call. Per-frame pixel facts are measured in the I/O layer and passed in as plain numbers.
- Crop is a precondition on the **change-detection input**, not on the output: the stored screenshot stays the full representative frame (`capture-measurements.md` §2 title, and NFR8's bias to preserving evidence).
- Emit on settle, never at the cue (§3). The cue decides *when*, the settle rule decides *which frame*.
- Loading/transition frames are tagged, never dropped (§4, NFR8).
- AD-5/AD-11 idempotence is unchanged: a `screens` rerun replaces only this meeting's `screenshot` rows, its `screenshots/` subtree, and its crop row; `screen` rows are still upserted by identity key and never deleted.
- AD-3: images stay under `MM_CONTENT_ROOT`; only root-relative paths are stored.
- SPEC Constraints: no recall denominator may be constructed from the extractor's own output. The human review of removed captures is recorded as prose, not converted into a recall number.

**Block If:**
- The re-run cannot reach under one capture per minute of meeting duration without raising the change threshold above the p50 of real screen changes (§2: cropped p50 0.19) — that would invert NFR8's bias and needs a human call on which guardrail yields.
- Crop detection would need a model, a template match, or per-frame vision rather than a detect-once survey (§2 fixes it as detect-once geometry).

**Never:**
- No re-OCR, no `ocr`-stage change, no `frames`-stage output change: sampled frames stay full-frame, so the retune is verifiable by re-running `screens` alone.
- No transcript, participant, align, moments, extract, or projection work (stories 1.5–1.7, Epic 4) — story 1.5 may be building concurrently.
- No eval harness, no ground-truth fixtures, no capture-recall check (stories 5.1/5.2 own those).
- No crop auto-detection beyond the share-region survey this story needs; no per-frame crop.
- No image-similarity dedup, no perceptual hashing, no model-based classification.
- Never modify `pull_transcript/`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Two-part layout | frames with a webcam column and a taskbar | one crop row for the meeting; every change comparison uses that region | N/A |
| No webcam column | frames whose right edge is as bright as the share area | crop falls back to the configured full-frame region and records that detection was inconclusive | N/A |
| Cue then settle | a burst of transition frames after a screen change | one capture, whose representative is the first settled frame, not the cue frame | N/A |
| Region never settles | change persists past the settle timeout | the last frame in the window is emitted and tagged `likely-transition` | N/A |
| Camera video | cropped frame with low white fraction and high saturation | `participant-gallery`, decided before any text-geometry rule | N/A |
| Avatar-tile gallery | bright, desaturated frame with almost no text | `participant-gallery` plus tag `avatar-gallery-unresolved` — never `ui-screen`/`slide` | N/A |
| Static screen | a slide held for 30 minutes | one capture; cumulative change against the emitted shot never reaches the threshold | N/A |
| Unreadable frame image | a sampled JPEG missing or corrupt | `StageError` naming the file and telling the operator to rerun `frames` | stage + job recorded `failed` |
| Zero frames | `frames` done with nothing sampled | zero captures, no crop row, the existing empty-swap path unchanged | N/A |
| `screens` rerun | prior screenshots and crop row present | both replaced for this meeting only; `screen` rows survive | previous output intact on failure |

</intent-contract>

## Code Map

- `server/meetingminer/pipeline/screens.py` — the pure core to retune. `FrameFacts` (`:79`) gains cropped pixel facts and loses `size_bytes`; `segment_captures` (`:186`) becomes cue-vs-last-emitted plus settle; `classify_view_type` (`:146`) gains the pixel pair ahead of the geometry rules; `_size_delta` (`:127`) and `CUE_SIZE_DELTA`/`CUE_TEXT_CHANGE`/`CUE_DWELL_DRIFT` (`:35`–`:38`) go. `choose_representative` (`:120`) survives as the settle-timeout fallback. `normalize_text`/`tokens`/`jaccard`/`signature_for`/`identity_key_for`/`best_lineage_match` are untouched — screen identity stays OCR-text similarity (spine `:135`).
- `server/meetingminer/pipeline/stages/screens.py` — the I/O around the core. `_SELECT_FRAMES` (`:36`) must also select `o.blocks`; `_load_frames` (`:56`) stops stat-ing files for `size_bytes` and instead measures each frame image; `run` (`:236`) gains the crop survey and the crop-row write. `_ScreenUpserter` (`:96`) and `_captures_per_minute` (`:221`) are unchanged.
- `server/meetingminer/pipeline/frameimage.py` — **new**: the only module that opens a frame image. Pillow `draft()`-downscaled decode, cropped white fraction / mean saturation / change fraction, and the column+row survey that detects the share region. Keeps `screens.py` engine-free.
- `server/meetingminer/config.py` — `ScreensConfig` (`:181`): drop `similarity_threshold`, `size_delta_ratio`, `dwell_seconds`, `dwell_drift_threshold`; add the crop, change/settle, and view-classification fields. `_StrictModel` (`:92`) forbids extras.
- `config.yaml` — `pipeline.screens` (`:62`–`:87`) is the only place the numbers live.
- `server/meetingminer/adapters/ocr/port.py` — `OcrBlock.as_json` (`:44`) fixes the `frame_ocr.blocks` shape (`x`,`y`,`width`,`height` normalized, origin top-left) the cropped geometry recompute reads.
- `server/meetingminer/migrations/0003_screens_screenshots.sql` — `screenshot` (`:63`) has no CHECK on `capture_cues`, so new cue names need no migration; `view_type` (`:81`) does have one, so the three view types stay as they are. Next migration file is `0004_`.
- `server/meetingminer/pipeline/outputs.py` — `OutputDirSwap` unchanged; the screenshots swap protocol is reused verbatim.
- `server/meetingminer/pipeline/runner.py` — `_clear_replaced_video_evidence()` (`:136`) already clears screenshots; it must also clear the new crop row.
- `server/tests/test_screens_core.py` — `DEFAULTS` (`:21`) and `frame()` (`:38`) are the fixtures to extend; `test_encoded_size_delta_splits_textless_frames` (`:136`), `test_both_cues_are_recorded_when_both_fire` (`:149`), `test_a_zero_byte_predecessor_never_fires_the_size_cue` (`:158`), `test_dissimilar_text_splits_with_a_text_change_cue` (`:112`), `test_long_dwell_with_drifted_text_re_captures` (`:166`), `test_dwell_alone_does_not_re_capture_before_the_threshold` (`:186`) encode the removed cues and are replaced by their region-change equivalents.
- `server/tests/test_config.py` — the inline config fixture (`:50`) carries `size_delta_ratio` and must match the new schema.
- `server/tests/test_worker_runner.py` — `NO_SIZE_CUE` (`:185`) and `test_encoded_size_delta_captures_a_screen_ocr_cannot_see` (`:1002`) are size-delta-specific and must be reworked onto the region-change cue.
- `server/tests/conftest.py` — `EVIDENCE_TABLES` (`:140`) must name the new crop table.
- `server/pyproject.toml` — dependency list (`:6`); Pillow is added here and `server/uv.lock` refreshed.
- `_bmad-output/specs/spec-meetingminer/capture-measurements.md` — read-only source of every number below.
- `pull_transcript/`, `_bmad-output/planning-artifacts/` — read-only.

## Tasks & Acceptance

**Execution:**
- `server/pyproject.toml`, `server/uv.lock` — add `pillow>=11`; refresh the lock.
- `server/meetingminer/config.py` — `ScreensConfig`: remove the four dead thresholds; add `analysis_width`, `pixel_diff_threshold`, `change_threshold`, `settle_threshold`, `settle_timeout_seconds`, `crop_survey_frames`, `crop_column_white_max`, `crop_min_region_width`, `crop_row_static_range_max`, `crop_max_bottom_strip`, `camera_max_white_fraction`, `camera_min_saturation` — each with a bounded `Field` and a comment naming the measurement it comes from.
- `config.yaml` — replace the `pipeline.screens` block with the new thresholds and the defaults from Design Notes.
- `server/meetingminer/migrations/0004_capture_retune.sql` — `meeting_crop` (meeting FK PK, `left/top/right/bottom` fractions, `detected` boolean, `method` text, timestamps + trigger) and `screenshot.classification_tags text[] NOT NULL DEFAULT '{}'`.
- `server/meetingminer/pipeline/frameimage.py` — new module: `FrameImage` (decoded, downscaled, cropped grayscale + HSV-saturation facts), `white_fraction`, `mean_saturation`, `change_fraction(a, b, pixel_diff_threshold)`, and `detect_share_region(paths, config) -> CropRegion` running the column/row survey. Pillow is imported here and nowhere else. Raise a named error the stage turns into `StageError` when an image will not decode.
- `server/meetingminer/pipeline/screens.py` — replace the cue set with `CUE_FIRST_FRAME` + `CUE_REGION_CHANGE`; add `TAG_LIKELY_TRANSITION` and `TAG_AVATAR_GALLERY_UNRESOLVED`; put `change_fraction_vs_previous`, `white_fraction`, `mean_saturation` and the cropped `block_count`/`text_density`/`mean_block_height` on `FrameFacts` and drop `size_bytes`; rewrite `segment_captures` as cue-against-last-emitted plus settle-with-timeout; put the brightness/saturation test ahead of the geometry rules in `classify_view_type` and emit tags; carry `tags` on `Capture`.
- `server/meetingminer/pipeline/stages/screens.py` — survey the meeting's frames once for the share region, persist it, measure every frame through `frameimage`, recompute cropped OCR geometry from `frame_ocr.blocks`, run the core, and log the crop plus the tag counts alongside `captures_per_minute`.
- `server/meetingminer/pipeline/runner.py` — clear `meeting_crop` alongside screenshots in `_clear_replaced_video_evidence()`.
- `server/tests/test_frame_image.py` — new: synthesized images assert white fraction, mean saturation, change fraction, and that `detect_share_region` finds a planted webcam column and taskbar, refuses a too-narrow band, and reports inconclusive on a uniform frame.
- `server/tests/test_screens_core.py` — cover the retuned core: cue fires against the last emitted shot and not against the previous frame; settle emits the first quiet frame; settle timeout emits the last frame and tags it; a long static screen captures once; camera pixels beat text geometry; bright desaturated textless frames tag as unresolved avatar gallery; representative falls back to the most text-rich frame on timeout.
- `server/tests/test_config.py`, `server/tests/test_worker_runner.py`, `server/tests/conftest.py` — update the config fixtures to the new schema, rework the size-delta worker test onto the region-change cue, add the crop table to `EVIDENCE_TABLES`, and assert the crop row and tags survive a rerun.

**Acceptance Criteria:**
- Given the epics.md Story 1.11 acceptance criteria, when each is exercised against the retuned stage, then it passes as written.
- Given the 57-minute meeting `01a0170c-bb04-78c2-832a-4fc2bc555551`, when `screens` is re-run at the shipped defaults, then it records fewer than 57 captures (under one per minute) and one `meeting_crop` row.
- Given the captures removed relative to the shipped 188, when a sample is reviewed by eye against the frames they came from, then the review's finding is recorded verbatim in `## Auto Run Result

**Status:** implemented and verified against the measured baseline. The first pass met the
guardrail but failed the removed-capture review; the settle rule was amended (Spec Change Log,
2026-08-19) and re-verified.

### The re-run

`screens` re-run for meeting `01a0170c-bb04-78c2-832a-4fc2bc555551` (57.56 min, 1727 frames) at
the shipped `config.yaml` defaults:

```
capture_count=46  captures_per_minute=0.799
crop=[0.0, 0.0, 0.871875, 0.9388888888888889]  crop_detected=true
crop_method="webcam-column+bottom-strip"
tags={"likely-transition": 2, "avatar-gallery-unresolved": 0}
```

- 46 < 57 and 0.799 < 1.0 — `eval-design.md` §2.2's guardrail holds, against the shipped run's
  188 = 3.27/min. It sits beside the §5 tuned baseline of 0.86/min.
- One `meeting_crop` row. The detected right boundary is **0.871875** against §2's measured
  87.8 %, from the survey alone — no model, no template match, no per-frame vision.
- Cues: 1 `first-frame`, 45 `region-change`. 46 rows, 46 files on disk, every stored path
  relative and present.
- Idempotent: `screens_created=0, screens_reused=46` on the re-run — the cross-meeting `screen`
  rows survived (AD-5).
- Why the retune works here is not what §2 predicts. Cropping is *not* what removed the
  captures on this recording: measured over frames 300-900, the cropped and uncropped change
  distributions are the same to two decimals (p50 0.027 vs 0.029 at a 60 s gap), because this
  meeting's webcam column is mostly static avatar tiles rather than live video. What removed
  them is the rule change — 91 of the old 188 were `dwell-drift` and 96 `text-change`, both
  OCR-text rules, and both are gone. The crop still earns its place (§2's floor is real on
  recordings with live webcams, and the story's AC requires it) but on *this* recording it is
  not the lever.

### Review of the removed captures, by eye

142 captures present in the reconstructed 188-capture run and absent from the 46. The old
algorithm was re-simulated from the stored `frame_ocr` rows and reproduced **188 exactly**, so
the diff is against a faithful reconstruction, not an estimate.

Measured, for every removed capture, against **all 46** kept captures (not just the one covering
that moment — a screen counts as recalled if any capture holds it, which is how
`eval-design.md` §2.1 matches `ocr_anchor`s):

| best cropped-token Jaccard vs any kept capture | removed captures |
|---|---|
| ≥ 0.9 — plain duplicate | 13 |
| 0.8-0.9 | 23 |
| 0.6-0.8 | 66 |
| < 0.6 | 51 |

Six of the < 0.6 group were opened and read, since that is the group where a real loss would
hide:

- **1874 s** — a **blank loading page**: an empty Safari window, tab still spinning. Correctly
  dropped. (2 of the 51 are blank-shaped like this; the other 49 carry normal text volume.)
- **1740 s and 1790 s** — `vendor_template_field_matrix.xlsx` scrolled to rows 40-94 and 52-105.
  Kept capture #13 holds the same document at rows 1-56. Same screen, different scroll offset.
- **1710 s** — a SharePoint `iContract Templates` listing. That listing is held by 11 kept
  captures (#2-#15).
- **1052 s** — the Excel `MainStructure` sheet. Held by kept capture #2.
- **1856 s** — same pattern: a scrolled position of a document held elsewhere.

**Finding.** No case was found where an application screen shown in this meeting is absent from
all 46 captures. The removals are loading states, near-duplicates, and *different scroll
positions of a document that is itself captured*. Calling a scrolled view a duplicate is a
judgement, and it is recorded as one rather than hidden: under `eval-design.md` §2.1's anchor
matching the screen is recalled, but **content below the captured viewport is not represented** —
rows 57-105 of the field matrix appear in no screenshot. That is a real coverage limit of
one-capture-per-screen and it is the thing to check first when story 5.1's fixtures make recall
measurable.

Per the SPEC independence constraint and `capture-measurements.md` §6, none of this is converted
into a recall figure: the denominator here is the extractor's own earlier output, which cannot
contain a screen both runs missed.

**The counter-example that was fixed rather than recorded.** The first pass shipped 47 captures
at 0.816/min and looked correct on every number. Opening the images showed capture #14 was a
**skeleton loading state** of the field matrix — placeholder bars, empty grid — while the
populated view of the same spreadsheet was among the removals. The settle rule was pixel-only, a
skeleton is pixel-quiet between two-second samples, and a skeleton grid and a populated grid are
both mostly white, so the emitted skeleton then blinded every later comparison. The rule now
requires the text to have stopped painting as well (Spec Change Log). Capture #13 is now the
populated matrix. Density barely moved — 47 → 46 — which is the point worth keeping: **no metric
in this story would have caught it.**

### Residual risks

- **A screen whose text changes without moving ~10 % of the region's pixels can share a capture
  with the screen before it.** Two similar SharePoint listings, or two sheets of one workbook,
  are the measured instance. Adding any cropped-text cue back breaks the guardrail on this
  recording (measured: Jaccard < 0.4 → 1.09/min; a novelty cue at 0.35 → 1.01/min), so the
  guardrail and this kind of recall are in direct tension on this content.

  **Accepted, 2026-08-19.** The product priority is UI views and slide-deck slides; spreadsheets,
  file listings, and other dense-information screens are explicitly lower priority for capture,
  being hard to parse usefully in any case. That resolves the tension in the guardrail's favour as
  a decision rather than as a silent trade, and it is why no text cue was reinstated. Both classes
  that matter move a large fraction of the region when they change — a new slide or a new UI view
  repaints most of it — so they sit well above `change_threshold`, while the dense-information
  cases that do not are the ones being conceded. Threshold headroom if that ever changes:
  0.08 → 51 captures (0.89/min).

  Consequence to carry into Epic 5: capture recall should be scored against slide and UI-view
  fixtures. A ground-truth manifest that plants `ocr_anchor`s on spreadsheet scroll positions
  would fail this extractor by design, not by defect.
- **`capture-measurements.md`'s numbers came from a different recording.** §2's noise floor, §3's
  settle timings, and §4's camera thresholds were measured on the 61-minute secondary demo. Two
  of the three did not transfer to this 57-minute meeting (the crop floor and the settle timing).
  §6 already records that the 8 corpus recordings were never probed; this is the first evidence
  of what that costs.
- **Scroll positions beyond the captured viewport are not represented** (above).

### Verification commands, as run

- `uv run --project server pytest server/tests` — **429 passed, 2 failed** (both pre-existing,
  see below).
- `make migrate && make migrate` — `0004_capture_retune.sql` recorded once in
  `schema_migrations`; both runs report "nothing to apply — database is up to date".
  `meeting_crop` and `screenshot.classification_tags` exist.
- `make test` — fails on the two pre-existing failures below, so the web half never ran; run
  separately, `pnpm --dir web run build` succeeds unchanged (no API surface change).
- `screens` re-run for `01a0170c-bb04-78c2-832a-4fc2bc555551` — the numbers above, taken from the
  `stage.screens.captured` event of the run itself.
- `grep -rn "0\.[0-9]" server/meetingminer/pipeline/screens.py server/meetingminer/pipeline/frameimage.py`
  — only `0.0`/`1.0` identity values and docstrings; no capture threshold outside `config.yaml`.
- I/O matrix audit: all 10 rows covered by tests that ran and passed. One gap was found and
  closed — the zero-frames row asserted no screenshots but not "no crop row"; the assertion was
  added to `test_zero_frames_completes_ocr_and_screens_with_no_outputs`.

### Pre-existing failures, not from this story

Both reproduce at `a16c19872d4bf72dca393b0ce22dbf17ea160f8b` in a clean detached worktree with
none of this story's changes present:

- `test_ocr_adapter.py::test_parse_tsv_without_page_dimensions_is_a_named_error` — out of scope;
  this story changes nothing under `adapters/ocr/`.
- `test_worker_runner.py::test_empty_and_populated_stage_logs_carry_the_same_fields` — asserts
  `stage.screens.captured.directory is None` on the zero-frame path. The stage does publish an
  empty directory there and log it, which is story 1.4's reviewed fix for stale screenshot files.
  The assertion is stale, not the code. Left alone deliberately: correcting an expectation to
  match code is the one repair this workflow forbids doing unattended, and "fixing" the code
  would revert a reviewed patch.

### Concurrency note

Story 1.5 was building in this same working tree throughout. Full-suite runs interleaved with it
returned between 1 and 62 spurious failures from the shared fixed-name test database
(`meetingminer_test`, already a recorded deferred item); the 429/2 result above is from a run
with no interference, and every scoped suite was confirmed in isolation. Files touched by both
stories (`config.py`, `config.yaml`, `pyproject.toml`, `conftest.py`, `test_config.py`,
`test_worker_runner.py`) contain both stories' edits.

### Files changed

- `server/meetingminer/pipeline/frameimage.py` (new) — the only module that opens an image. Downscaled decode, cropped white fraction / mean saturation / change fraction, the detect-once column-and-row share-region survey, and `crop_blocks`.
- `server/meetingminer/pipeline/screens.py` — cues reduced to `first-frame` + `region-change`; cue measured against the last emitted shot; settle requires pixel quiet *and* text no longer painting; §4's pixel pair tested ahead of the geometry rules; `likely-transition` and `avatar-gallery-unresolved` tags.
- `server/meetingminer/pipeline/stages/screens.py` — the crop survey, per-frame measurement, the crop row, tag persistence, and crop plus tag counts on the stage log.
- `server/meetingminer/pipeline/runner.py` — clears `meeting_crop` with the rest of a meeting's video evidence.
- `server/meetingminer/migrations/0004_capture_retune.sql` (new) — `meeting_crop`, and `screenshot.classification_tags`.
- `server/meetingminer/config.py`, `config.yaml` — four dead thresholds removed, fourteen added, each with its provenance.
- `server/pyproject.toml`, `server/uv.lock` — `pillow>=11`.
- `server/tests/test_screens_with_real_pixels.py` (new), `test_frame_image.py` (new), `test_screens_core.py`, `test_worker_runner.py`, `test_config.py`, `conftest.py`.

### Review findings

Four layers (blind hunter, edge-case hunter, verification-gap with mutation testing, intent
alignment). **18 patched** (0 high, 8 medium, 10 low), **10 deferred**, 5 rejected. No intent gaps
and no spec-level defects.

Four of the patches close gaps the verification-gap layer *proved* with mutations that the suite
did not catch: the pixel pair never reached the classifier through the stage, the detected crop
never reached the OCR geometry, the analysis-scale downscale was never executed by any test, and
segmentation was never driven by its production comparator. Each fix was re-checked by re-running
the same mutation and confirming it now fails.

**Follow-up review recommended: true.** Patched by severity: high 0, medium 8, low 10.
Score = 3x8 + 1x10 = 34, at or above the threshold of 5.

### Final verification

- `uv run --project server pytest server/tests` — **448 passed, 2 failed**, both reproduced at the
  baseline commit in a clean worktree and recorded in `deferred`.
- `screens` re-run for `01a0170c-bb04-78c2-832a-4fc2bc555551` after every patch — 46 captures,
  0.799/min, crop `[0.0, 0.0, 0.871875, 0.9389]`, `detected=true`, unchanged from before the patch
  round (this recording's webcam column is static, so the row-survey fix does not move it).
- `pnpm --dir web run build` — succeeds unchanged.

### Review Findings — Follow-up (2026-08-18)

- [x] [Review][Patch] No-webcam fallback can crop static content [server/meetingminer/pipeline/frameimage.py:288] — Fixed: an inconclusive webcam-column survey now returns the full-frame region before the bottom-strip survey. A regression test covers a bright right edge, changing content, and a static bottom band.
