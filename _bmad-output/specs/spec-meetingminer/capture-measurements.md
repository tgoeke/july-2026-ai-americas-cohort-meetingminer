# Capture Measurements

Companion to `SPEC.md` (CAP-1, CAP-7). The measured behaviour of the screen-capture path on real
recordings. Corpus and media properties live in `corpus-facts.md`.

**Measured 2026-08-18** by the parallel spike track on a full 61-minute recording. That track
designs a different system; only its measurements are canonical here. Story 1.4 shipped before
these numbers existed — §5 records the resulting gap.

## 1. The baseline works, and cost is not a constraint

A 61-minute recording yielded ~43 clean settled UI screens plus 10 tagged transitions **with no
model of any kind**, in 28 seconds.

Full decode plus analysis of those 61 minutes ran in 17.0 s — **211× realtime** on a 540 kbps
screen-share stream; demux-only ran ~3000×. Extrapolated to the 117-minute primary demo: well
under a minute. Avoiding full decode is therefore a portability and battery decision, never a
feasibility requirement, and no capture design needs to be shaped around decode cost.

## 2. Cropping is an input precondition, not an output concern

The frame is a stable two-part layout: shared screen on the left, a fixed column of participant
webcam tiles starting at **x ≈ 87.8 %**, and a taskbar in the bottom ~4.5 %. The layout held
across all 24 survey frames spanning the full hour, so the crop is **detect-once geometry**, not
a per-frame vision problem.

Cropping must happen **before** change detection, because uncropped the metric has no usable
dynamic range:

| | Change fraction vs last emitted shot |
|---|---|
| Uncropped | persistent floor ≈ **0.15**; real screen changes reach only ≈ 0.19 |
| Cropped | p50 0.19 · p75 0.23 · p90 0.25 · p95 0.30 · p99 0.41 |

The floor is not constant per-frame motion — it **grows with time since the last emission**,
because webcam content decorrelates over minutes. Any design that compares against the last
*emitted* frame is therefore especially exposed, and any whole-frame proxy for change (encoded
size included) measures the webcam column as much as the shared screen.

## 3. Emit on settle, not on change

*When a change happened* and *which frame to keep* are different questions. Emitting at the
moment of change captures loading spinners and blank pages, because a blank mid-load page is the
single largest possible difference from a populated one. Emitting the first frame at which the
region has stopped changing fixes it, and converges cheaply: median wait 0.0 s, max 2.0 s, **zero
timeouts** across 53 emissions.

This is also why a high change threshold inverts the intended bias. A settled UI state differs
from the previous settled state by 0.20–0.35 (same chrome, same layout, different data), while a
blank page mid-load differs by ~0.80 — so a high gate reliably captures transitions and reliably
misses the populated forms, grids, and modals that carry the requirements.

## 4. View classification without a model

Camera and gallery video separate from screen share on two independent metrics, measured over 63
hand-labelled shots:

| Metric | Camera / gallery video (n=8) | Screen share (n=55) | Margin |
|---|---|---|---|
| Fraction of pixels > 200 ("white") | ≤ **0.046** | ≥ **0.190** | **4.1×** |
| Mean saturation | ≥ **0.292** | ≤ **0.132** | **2.2×** |

Both separate perfectly with thresholds set mid-gap; together they removed every camera frame —
11.9 % of the recording.

**Known gap:** Teams gallery rendered as *initial-avatar tiles* on a light background is bright
and desaturated, so it passes the filter. The signal separates camera **video** from screen
share; it does not separate avatar-tile gallery. That case needs a further signal — likely
absence of window chrome, or a text-density floor.

**Loading pages are not separable.** Mean horizontal gradient ranges overlap (loading 1.37–5.64,
real UI 2.31–6.20), so no single threshold cuts loading frames without cutting real ones. Per the
recall-beats-precision bias these are tagged as likely transitions and never dropped.

## 5. Where the shipped implementation stands against this

Story 1.4 shipped a full-frame path: frames sampled every 2 s with no crop, segmented on OCR-text
similarity plus encoded JPEG byte-size delta.

Its own live-stack verification captured **188 screenshots from a 57-minute meeting = 3.3
captures/min**. `eval-design.md` §2.2 fails a run above 1.0/min, and the measured tuned extractor
above sits at 0.86/min. Over the line by 3.3×, in the direction §2 predicts for an uncropped
whole-frame signal.

The retune is story-level work against §2–§4 and does not change CAP-1's intent: detect the crop
region once per recording, gate on the cropped region, emit on settle, and classify with the
brightness/saturation pair before falling back to text geometry.

## 6. Open gaps in the measurements

Recorded so silence is not read as confirmation.

- **Capture recall has no denominator.** No independent labeling pass has run and the scripted
  mock lab is unbuilt, so CAP-7's 100 % recall requirement is currently unmeasurable. A denominator
  derived from the extractor's own output would report 100 % while measuring nothing — hence the
  independence constraint in `SPEC.md`.
- **Crop auto-detection is not implemented** — the measured crop was hand-set, and the 117-minute
  recording has not been checked for the same geometry.
- **The 8 corpus recordings have not been probed** — durations, resolutions, and whether they
  contain screen shares at all are unknown. Only the two NDA demos were measured.
