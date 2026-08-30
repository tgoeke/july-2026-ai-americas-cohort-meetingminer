# Builder handoff — Story 1.11: Screen Capture Retune Against Measured Baselines

Paste the block below as the `bmad-build-auto` invocation prompt.

Runs independently of story 1.5 — different pipeline stages, different config blocks. The two can build concurrently.

---

Implement **Epic 1, Story 1.11 — Screen Capture Retune Against Measured Baselines**.

The story definition and its acceptance criteria are in `_bmad-output/planning-artifacts/epics.md` under `### Story 1.11`. No story spec file exists yet — planning writes it.

**Canonical contract.** `_bmad-output/specs/spec-meetingminer/SPEC.md` and every file in its `companions:` frontmatter. Architecture: `_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md`.

**Read `_bmad-output/specs/spec-meetingminer/capture-measurements.md` in full before planning.** It is the source this story exists to satisfy. Every number in it was measured on a real 61-minute Teams recording; treat them as established, not as things to re-derive.

## Why this story exists

Story 1.4 shipped and is `done`, but it was specified and built before those measurements existed. Its own live-stack verification captured **188 screenshots from a 57-minute meeting = 3.3 captures/min**. `eval-design.md` §2.2 fails a run above 1.0/min, and a tuned extractor measured 0.86/min on comparable content. The shipped path is over the fail line by 3.3×, in exactly the direction an uncropped whole-frame signal predicts.

This is a retune of an existing, working stage — not a rewrite. CAP-1's intent does not change.

## What the shipped implementation does today

- `server/meetingminer/pipeline/media.py:196` samples frames with ffmpeg `-vf fps=1/N`. **No crop anywhere in the pipeline.**
- `server/meetingminer/pipeline/screens.py` holds the segmentation, representative-selection, view-type and identity logic as pure functions over per-frame facts — no Postgres, no ffmpeg, no OCR engine. That design is a gift here: the retune is unit-testable end to end without a live stack.
- `server/meetingminer/pipeline/stages/screens.py` and `stages/frames.py` are the stage wrappers.
- Thresholds live in `config.yaml` under `pipeline.frames` and `pipeline.screens`, typed by `FramesConfig` and `ScreensConfig` in `server/meetingminer/config.py`.
- Capture cues today are OCR-text Jaccard similarity (`similarity_threshold`), encoded JPEG byte-size delta (`size_delta_ratio`), and dwell drift.
- Existing coverage: `server/tests/test_screens_core.py`, `test_pipeline_media.py`, `test_output_dir_swap.py`, `test_ocr_adapter.py`. These must stay green.

## What the measurements establish

**Cropping is an input precondition, not an output concern (§2).** The frame is a stable two-part layout — shared screen left, a fixed participant webcam column starting at x ≈ 87.8 %, a taskbar in the bottom ~4.5 % — holding across all 24 survey frames spanning a full hour. So the crop is detect-once geometry per recording, not a per-frame vision problem. It must happen *before* change detection: uncropped, the persistent noise floor is ≈ 0.15 while real screen changes reach only ≈ 0.19, and that floor **grows with time since the last emission** because webcam content decorrelates. The current `size_delta_ratio` cue on whole-frame JPEG bytes is measuring the webcam column as much as the shared screen.

**Emit on settle, not on change (§3).** *When* a change happened and *which* frame to keep are different questions. Emitting at the cue captures loading spinners and blank pages, because a blank mid-load page is the largest possible difference from a populated one. Emitting the first frame at which the region has stopped changing converged cheaply: median wait 0.0 s, max 2.0 s, zero timeouts across 53 emissions.

**View classification without a model (§4).** Camera and gallery video separate from screen share on two independent metrics — fraction of pixels > 200 (≤ 0.046 camera vs ≥ 0.190 share, 4.1× margin) and mean saturation (≥ 0.292 camera vs ≤ 0.132 share, 2.2× margin). Both separated perfectly over 63 hand-labelled shots with thresholds set mid-gap. Apply this pair *before* text-geometry rules. Known residual: gallery rendered as initial-avatar tiles on a light background is bright and desaturated and passes the filter — record it as a known unresolved case, do not silently classify it as a screen.

**Loading pages are not separable (§4).** Gradient ranges overlap (loading 1.37–5.64, real UI 2.31–6.20). No single threshold cuts them without cutting real UI. Tag as likely transition; never drop. NFR8's bias is over-capture, never loss.

**Decode cost is not a constraint (§1).** Full decode plus analysis of 61 minutes ran in 17.0 s — 211× realtime on a 540 kbps screen-share stream. Do not shape the design around avoiding decode.

## Verification

Re-run the 57-minute meeting that produced 188 captures. The capture count must land under one per minute of meeting duration, and a **human review of the removed captures** must confirm they were transitions, gallery frames, or duplicates rather than settled UI screens.

Capture recall has no independent denominator until story 5.1's scripted fixtures exist (`capture-measurements.md` §6), so that review is the available check — record its result rather than asserting a recall number. **Do not construct a recall denominator from the extractor's own output**; SPEC Constraints forbid it, because a set built from what the extractor emitted cannot contain a screen it missed and would report 100 % while measuring nothing.

Every threshold this story introduces or changes arrives from `config.yaml` and never as a code constant (AD-10) — a later retune against the scripted corpus must be an edit, not a code change.

`epics.md` is newer than the cached `epic-1-context.md`, so epic context will recompile on this run. Do not reuse the stale cache.

## Out of scope. Do not widen into any of these

- Story 1.5 (transcripts, alignment, participants), 1.6 (moments), 1.7 (projections), 1.9 (UI/SSE). Story 1.5 may be building concurrently — stay out of the transcript and participant stages entirely.
- Crop auto-detection beyond what this story needs: the measured crop was hand-set and the 117-minute recording has not been checked for the same geometry. Detect per recording; do not build a general vision system.
- Building the eval harness. Story 5.1 owns ground-truth fixtures and 5.2 owns the deterministic capture checks. This story satisfies the guardrail; it does not implement the checker.
- `pull_transcript/` — the upstream ingest source of record, never modified as a side effect of MeetingMiner work.
- Re-litigating story 1.4's deferred risks already recorded in its spec frontmatter.
