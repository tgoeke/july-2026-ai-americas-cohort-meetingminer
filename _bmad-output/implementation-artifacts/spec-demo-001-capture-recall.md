---
title: 'Demo-001 capture recall — dense UI screens missed by the emit gate'
type: 'bugfix'
created: '2026-08-21'
status: 'done'
review_loop_iteration: 0
baseline_commit: '413a3122bc9aca3219c86e2617da60cc95ccafb0'
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Meeting `01a02545-fbdb-7baa-b895-20791a06299a` (demo-001, orders UI demo) is missing 3 of its 4 critical UI screenshots: SC2/SC3/SC4 got no capture (eval 2.1 recall 0.5). One capture spans 44s–220s — ~88 consecutive frames scored below `change_threshold: 0.10` against the shot emitted at 44s while the presenter paged through three more same-chrome dense screens. UI views are top capture-priority targets; the prior "acceptable dense-screen miss" triage is overridden.

**Approach:** Verify first by replaying the emit decision offline over the 124 persisted frames (crop was detected correctly — this is not the demo-002 fallback defect). Then fix the emit gate so settled same-chrome screen changes capture — threshold retune at analysis width and/or emit-gate reference semantics, whichever the measured numbers justify — and resolve the eval's structural contradiction (6 expected captures vs over-capture budget ceil(4.117)=5).

## Boundaries & Constraints

**Always:**
- Verify before changing: measure per-frame `change_fraction` vs the emitted shots using the recorded crop `[0, 0, 0.871875, 0.938888…]` over `/Users/devopsterus/current/meetingminer-content/meetings/01a02545-…/frames/`; the fix targets what those numbers show. Record the measurements in this spec's Design Notes.
- Ordering renegotiated by the human 2026-08-21: this story goes FIRST — `story/capture-view-classification` (demo-002, same files: `screens.py`, `frameimage.py`, `ScreensConfig`) has not started and kicks off only after this branch lands. Work in the worktree `make worktree STORY=demo-001-capture-recall` creates; never a second concurrent writer on those files.
- Region detection stays survey-based; three view types only; retunes justified against `capture-measurements.md`; no regression on the 63 hand-labelled shots or prior corpus classification baselines.
- `test_the_shipped_defaults_hold_the_over_capture_guardrail` keeps passing; the skeleton-regression behavior (`test_the_skeleton_is_not_the_stored_screen`) is improved, not reverted.
- Worker stays stopped (no paid calls); `make evals-run` serial, one at a time; a projection-test run owes `make rebuild`.

**Ask First:**
- Re-recording demo-001 (human work) if replay shows the frames genuinely cannot separate at any defensible threshold.
- Any change that alters capture counts on the 28-meeting real corpus beyond a stated, measured delta.

**Never:**
- Demo-002 checks 2.2/2.3 (owned by `story/capture-view-classification`); the 2.11 publish-gate expected failures (story 4-4); relaxing ground truth to bless the misses; a model or template-match for region/change detection; files owned by in-flight stories 2-5 and 4-4.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Screen page-through | Settled dense UI screen replaced by another same-chrome screen (~20s+ on screen) | New capture per screen, `viewType: ui-screen` | N/A |
| Static screen | One screen held for minutes | Exactly 1 capture (no over-capture regression) | N/A |
| Skeleton → populated | Mid-load frame emitted, page then fills in | Populated view eventually captured | N/A |
| Budget vs manifest | Scripted take shorter than planned: expected captures > ceil(duration) | Check 2.2 budget = max(ceil(duration_minutes), manifest expected count) | N/A |

</frozen-after-approval>

## Code Map

- `server/meetingminer/pipeline/screens.py` — `segment_captures` (:265–395); emit gate at :352 (`change_since_emitted < change_threshold` → absorb) is the defect site; settle rule :305–333; timeout force-emit :168/:348. No budget or min-spacing exists here.
- `server/meetingminer/pipeline/stages/screens.py` — `_RegionChange.__call__` (:151, frame vs last **emitted** shot = the cue); `_measure_frames` (:203, consecutive deltas, settle-only); `_captures_per_minute` (:287, reporting only); crop persistence :364–375.
- `server/meetingminer/pipeline/frameimage.py` — `measure_frame` :142, `change_fraction` :156 (cropped grayscale pixels, delta ≥ `pixel_diff_threshold: 16`), `detect_share_region` :231. Crop worked here (`crop_detected: true`, worker.log:5473) — leave detection alone.
- `server/meetingminer/config.py:244` `ScreensConfig`; `config.yaml:195–225` — `analysis_width: 320`, `change_threshold: 0.10`. §2's p50 0.19 for real changes was measured at 1920px; nothing constrains 320px same-chrome browser pages — the gap this bug lives in.
- `server/tests/test_screens_with_real_pixels.py` — :166 skeleton regression (documents this miss mode); :229 over-capture guardrail (10 screens × 60s → exactly 10 captures).
- `server/tests/test_worker_runner.py:1275` — asserts `change_threshold == 0.10`; update deliberately with any retune.
- `evals/harness/checks.py:480` — `over_capture`, `budget = ceil(duration)`; `evals/ground-truth/demo-001-orders-ui-demo.yaml` — `duration_minutes: 4` (actual take 247s), 6 expected captures.
- Evidence: `/Users/devopsterus/current/meetingminer-content/meetings/01a02545-…/frames/` (124 JPEGs, 2s apart); `evals/runs/2026-08-21-demo-recorded-3/deterministic-report.yaml:31–113`. Per-probe change fractions are persisted nowhere — replay is the only verification path.

## Tasks & Acceptance

**Execution:**
- [x] Replay script (scratchpad, not committed) — compute `change_fraction` for each of the 124 frames vs each emitted shot under the recorded crop at `analysis_width: 320` — decides threshold-vs-semantics; append the measured numbers to Design Notes.
- [x] `server/meetingminer/pipeline/screens.py` (+ `frameimage.py`/`ScreensConfig`/`config.yaml` as evidence dictates) — make settled same-chrome screen changes cross the emit gate; update config comments with the new measured justification.
- [x] `server/tests/test_screens_with_real_pixels.py` — add a demo-001-shaped regression test (real pixels, N same-chrome dense pages each ~20s → N captures) alongside the kept guardrail test.
- [x] `server/tests/test_worker_runner.py` — update the shipped-default assertion if the threshold changes.
- [x] `evals/harness/checks.py` — budget = `max(ceil(duration_minutes), manifest expected captures)`; `evals/ground-truth/demo-001-orders-ui-demo.yaml` — true-up `duration_minutes` to the actual take (5).
- [x] Re-capture demo-001 + `make evals-run` (serial); record the run under `evals/runs/` — recorded as `2026-08-21-demo-recorded-4` (2.1/2.2/2.3/2.4 demo-001 all pass; see Design Notes for the environmental 2.10 failure).

**Acceptance Criteria:**
- Given the recorded demo-001 drop re-ingested, when `make evals-run` runs, then check 2.1 on demo-001 passes (SC1–SC4 anchor-matched, recall 1.0) and check 2.2 on demo-001 still passes under the amended budget.
- Given the fix, when the server screen suites run, then all pass including the unmodified over-capture guardrail test.
- Given prior corpus baselines, when compared post-fix, then classification baselines show no regression and any corpus capture-count delta is measured and stated.

## Spec Change Log

## Design Notes

Replay evidence lands here (ground truth: SC2 at 90s, SC3 at 160s, SC4 at 196s; sharing stops ~216s). Two mechanisms the numbers must separate: (a) genuine sub-0.10 deltas at 320px between same-chrome pages → threshold retune with a new measured floor; (b) the 44s emitted shot is a transition/skeleton frame later screens hover near → emit-gate reference semantics (e.g. additional cue on sustained change vs previous settled frame). Also: 2 of 4 captures carry `likely-transition` (settle timeouts) against §3's measured zero — check during replay.

### Replay measurements (2026-08-21, offline over the 124 frames, crop `[0, 0, 0.871875, 0.938888…]`, 320px, pixel_diff 16)

The verdict is mechanism **(a)** — genuine sub-0.10 deltas between settled same-chrome pages — with a shape discriminator, not a plain threshold cut:

- The 48s emitted shot (capture 3's representative, frame-000025) is **not** a skeleton: it is the settled SC1 (identical to its neighbours, `vs_prev` 0.0000; its OCR carries the SC1 anchor). Mechanism (b) is ruled out.
- Change vs the emitted SC1 shot, sustained and pixel-quiet: **SC2 0.0683–0.0701** (frames 46–79), **SC3 0.0772–0.0807** (frames 80–99), **SC4 0.0469–0.0471** (frames 100–111). All below the 0.10 gate — hence one 44s–220s capture.
- Same-screen quiet noise vs the emitted shot: ≤ **0.003** (occasional 0.005–0.008 wiggles). One transient at 76s spiked to **0.0401** vs the emitted shot but was **never pixel-quiet** (`vs_prev` 0.0399/0.0398) and returned to 0.0002 one sample later.
- Page-flip steps vs the previous frame: 0.0690 (88s), 0.0855 (156s), 0.0689 (198s) — each a single-step arrival followed by a long quiet plateau at the new distance. **A real page change arrives and stays; a transient spikes and returns.**
- The two `likely-transition` captures are the two gallery segments (live webcam motion keeps `vs_prev` at 0.03–0.09, above `settle_threshold` 0.02, so they settle-timeout). Expected for galleries; not a defect of this story.
- Capture 1 was the **Teams title slate** (frame-000001, dark 0.010 white / 0.139 saturation, on screen < one 2s sample): the 7th row that would have blown the amended budget of 6.

**Fix shipped:** (1) `settled-change` cue — a frame pixel-quiet (`vs_prev ≤ settle_threshold`) at `settled_change_threshold: 0.03`+ from the emitted shot, sustained for `settled_change_frames: 3` consecutive samples, opens a capture. 0.03 sits ~4× above the measured noise ceiling (0.008) and 36% below the weakest measured real crossing (0.047). The non-quiet / sub-floor reset is what rejects the 0.0401 transient. (2) The opening title slate (single first frame, emitted at anchor, replaced by the very next sample, dark **and** desaturated — failing both §4 classes) is discarded and its first-frame cue carried onto the replacing capture; a bright or saturated one-sample opening frame keeps its capture (NFR8).

**Side effect (pinned by the updated drift tests):** quiet drift now cues via `settled-change` every 4 steps (the first 0.02 step is under the floor, then 0.04→0.06→0.08 completes the run) instead of `region-change` every 5.

**Accepted limitation:** a real change accompanied by continuous motion — never 3 consecutive pixel-quiet samples — does not fire the settled cue; that is the same pixel-quiet conjunct that keeps live galleries from flooding captures every `settled_change_frames` samples (such a change still cues at 0.10 via `region-change`, or is caught by the settle timeout).

**Measured corpus delta (13 stored meetings replayed offline, old algorithm's stored rows vs new segmentation):** 829 → 1076 captures (**+247, +30%**) at floor 0.03; +179 (+22%) at 0.04; +116 (+14%) at 0.05. 0.05 was rejected: it sits above the weakest measured real crossing (0.047). The delta is concentrated in real-world (non-scripted) meetings that were already above 1/min under the old gate; the scripted eval meetings stay inside budget. Demo-002 goes 11 → 10 (its opening slate folds) — a stated side effect; its checks 2.2/2.3 remain `story/capture-view-classification`'s.

**Offline result on demo-001:** exactly **6 captures** — gallery 2–42s, SC1 44–92s (rep 48s), SC2 94–160s (rep 94s, `settled-change`), SC3 162–202s (rep 162s), SC4 204–220s (rep 204s), gallery 222–246s. All four anchors present verbatim in the representatives' OCR. Budget = max(ceil(5), 6) = 6 → 2.2 passes.

### Recorded run `2026-08-21-demo-recorded-4` (vs baseline `…-3`)

- demo-001: **2.1 PASS (recall 1.0, 6/6 matched, 6 captures)**, 2.2 PASS (budget 6), 2.3 PASS, 2.4 PASS. The live DB rows match the offline replay exactly (ordinals 1–6, cues `first-frame+region-change`, `region-change`, 3× `settled-change`, `region-change`). Re-capture note: the first requeue at 21:10 was consumed by a still-running main-checkout worker on the pre-fix code (produced 4 captures again); that worker was stopped per this spec's "worker stays stopped", the job requeued, and the worktree worker ran the fixed screens stage once (capture_count 6, no extract call — its checkpoint stayed done) and was stopped again.
- Still failing, unchanged in ownership: 2.11 ×2 (publish-gate, story 4-4's expected failures) and demo-002's 2.2/2.3 (`story/capture-view-classification`).

## Verification

**Commands:**
- `uv run --project server pytest server/tests/test_screens_with_real_pixels.py server/tests/test_screens_core.py server/tests/test_worker_runner.py server/tests/test_frame_image.py` — expected: all pass.
- `make evals-run` — expected: 2.1 demo-001 passes; no new failures vs run `2026-08-21-demo-recorded-3` beyond those owned by other stories.

## Suggested Review Order

**The settled-change emit gate**

- Entry point: two frame-in-hand comparisons now decide an emit — the shipped `change_threshold` cue and the new sustained, pixel-quiet `settled-change` cue for same-chrome pages too close for the first.
  [`screens.py:266`](../../server/meetingminer/pipeline/screens.py#L266)

- The sustained-run accumulator: counts consecutive quiet frames over the settled floor, reset by a cue, an unsettled frame, or a fall back under the floor — the reset is what tells a real change from a transient.
  [`screens.py:417`](../../server/meetingminer/pipeline/screens.py#L417)

- New config knobs with the measured justification (0.03 floor, 3 sustained samples) inline as comments.
  [`config.py:283`](../../server/meetingminer/config.py#L283)
  [`config.yaml:221`](../../config.yaml#L221)

**The opening title-slate fold**

- A first-sample-only capture that is dark *and* desaturated is folded into the capture that replaces it, rather than stored as a screen the meeting never showed; a bright or saturated one-sample opener keeps its own capture (NFR8).
  [`screens.py:370`](../../server/meetingminer/pipeline/screens.py#L370)

**The eval-harness budget fix for a shorter-than-planned take**

- Budget is now `max(ceil(duration_minutes), expected_screenshot_count)` so a scripted take that ran short doesn't fail 2.2 for satisfying 2.1's own denominator.
  [`checks.py:480`](../../evals/harness/checks.py#L480)

- Ground truth trued to the actual 247s take.
  [`demo-001-orders-ui-demo.yaml:21`](../../evals/ground-truth/demo-001-orders-ui-demo.yaml#L21)

**Tests — cue and fold boundaries**

- The demo-001 reproduction at the real comparator: four same-chrome pages, each held ~20s, each its own capture.
  [`test_screens_with_real_pixels.py:230`](../../server/tests/test_screens_with_real_pixels.py#L230)

- Settled-change fires under the region threshold; a transient blip and persistent sub-floor noise do not.
  [`test_screens_core.py:231`](../../server/tests/test_screens_core.py#L231)
  [`test_screens_core.py:261`](../../server/tests/test_screens_core.py#L261)
  [`test_screens_core.py:285`](../../server/tests/test_screens_core.py#L285)

- Slate fold boundaries: dark+desaturated folds; held, bright, or saturated openers each keep their own capture.
  [`test_screens_core.py:297`](../../server/tests/test_screens_core.py#L297)
  [`test_screens_core.py:329`](../../server/tests/test_screens_core.py#L329)
  [`test_screens_core.py:343`](../../server/tests/test_screens_core.py#L343)
  [`test_screens_core.py:358`](../../server/tests/test_screens_core.py#L358)

- Shipped defaults pinned against the loaded `config.yaml`, matching the existing `change_threshold` pin.
  [`test_worker_runner.py:1301`](../../server/tests/test_worker_runner.py#L1301)

- Budget fix covered on both arms (short take floored at the manifest's expected count; long take still governed by ceil).
  [`test_checks.py:313`](../../evals/tests/test_checks.py#L313)
