# Failure Evidence — eval run 2026-08-21-demo-recorded-3, demo-002

Report: `evals/runs/2026-08-21-demo-recorded-3/deterministic-report.yaml`.
First run with the scripted demos recorded, so these are first measurements,
not regressions.

## Check 2.3 — view classification, accuracy 0.29 (2/7)

Every slide anchor OCR-matched at score 1.0; only the label is wrong:

| entry | anchor | expected | capture | got |
|---|---|---|---|---|
| S1 | q3 architecture review | slide | 1 | ui-screen |
| S2 | evidence pipeline today | slide | 4 | participant-gallery |
| S3 | retrieval split graph and document index | slide | 5 | participant-gallery |
| S4 | nothing enters a store before approval | slide | 6 | participant-gallery |
| S5 | q4 proposal and open risks | slide | 7 | participant-gallery |

The two correct labels are the participant-gallery segments themselves.

## Check 2.2 — over-capture, 11 captures / 7.0 min (budget 7, 1.571/min)

Same subject, same run. Triage decision of record: treat as the same root
cause, re-measure after the 2.3 fix, only then consider it separately.

## Mechanism hypothesis (unverified — verify first)

`classify_view_type` (`server/meetingminer/pipeline/screens.py:197`) tests the
camera pixel pair first: `white_fraction <= camera_max_white_fraction AND
mean_saturation >= camera_min_saturation` → `participant-gallery`, before any
text geometry. That ordering is deliberate (the 1-11 retune, perfect
separation over 63 hand-labelled shots on the measured corpus).

The pixel facts are measured on the cropped share region, and
`detect_share_region` (`server/meetingminer/pipeline/frameimage.py:231`)
surveys once per recording for the measured-corpus layout: share area left,
webcam column starting near x = 87.8%. If demo-002's Teams layout differs
(e.g. gallery strip elsewhere), the survey returns the full-frame fallback
with `detected=False` — recorded, not hidden. Full-frame pixels over live
webcam tiles are dark and saturated → the camera rule fires for every shared
slide. The same uncropped pixels feed `change_fraction`, so webcam motion
keeps crossing `change_threshold` → 11 captures for 7 minutes. One mechanism,
both failures.

S1's `ui-screen` label (capture 1, the title slide) says the camera rule did
not fire there — consistent with a title-card frame bright enough to escape
the pixel pair, then failing the slide geometry gate
(`slide_min_block_height`/`slide_max_blocks`). Whether that is the same fix
or a threshold case falls out of the verification step.

## Suggested verification order

1. Read the recorded crop `method`/`detected` for demo-002's ingest (the
   survey records them) — this decides fallback-vs-threshold before any code
   changes.
2. If fallback: make the survey handle demo-002's layout (survey-based, no
   model), re-run capture + `make evals-run`, check 2.3 then 2.2.
3. If crop was correct: add demo-002 frames to the 1-11 hand-labelled
   baseline set, retune thresholds against the union, prove no regression.
