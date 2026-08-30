---
title: 'Story 1.11: Preserve Full Frame When Webcam Detection Is Inconclusive'
type: 'bugfix'
created: '2026-08-18'
status: 'done'
route: 'one-shot'
baseline_commit: 'bcb34e1d92c07d710d329436215d2f6d4afaf2c6'
---

# Story 1.11: Preserve Full Frame When Webcam Detection Is Inconclusive

## Intent

**Problem:** The screen-capture survey could strip a static bottom band from a recording even when it did not detect the webcam column that defines the measured two-part layout.

**Approach:** Treat an inconclusive webcam-column survey as a full-frame fallback and prove the behavior with changing content above a static bottom band.

## Suggested Review Order

- The early fallback preserves all evidence when the layout is inconclusive.
  [frameimage.py:288](../../../server/meetingminer/pipeline/frameimage.py#L288)

- The regression fixture proves a static bottom band remains part of measurement.
  [test_frame_image.py:203](../../../server/tests/test_frame_image.py#L203)

- Review artifacts record the acceptance regression and its resolution.
  [review-story-1-11-2026-08-19.md:8](review-story-1-11-2026-08-19.md#L8)
