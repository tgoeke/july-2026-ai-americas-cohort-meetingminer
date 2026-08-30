---
id: SPEC-capture-view-classification
companions:
  - failure-evidence.md
  - ../spec-meetingminer/capture-measurements.md
sources: []
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# Capture View Classification Break-fix

## Why

A pain to solve. Eval run `2026-08-21-demo-recorded-3` — the first run with the
scripted demo meetings actually recorded — shows check `2.3 view
classification` failing on demo-002 (q3-architecture-review) at accuracy 0.29:
captures 4–7 hold the right slides (all OCR anchors matched at 1.0) but are
labeled `participant-gallery`, and capture 1's slide is labeled `ui-screen`.
Check `2.2 over-capture guardrail` fails on the same subject (11 captures for a
budget of 7) and is triaged as the same probable root cause. Slides are a top
capture-priority target; a slide labeled as gallery mislabels the moment view
downstream. Failure evidence and the mechanism hypothesis are in
`failure-evidence.md`; triage of record is `sprint-notes.md` (2026-08-21
section, commit `e9479ec`).

## Capabilities

- **CAP-1**
  - **intent:** A slide shared inside a Teams meeting window with live webcam
    tiles visible is classified `slide`, not `participant-gallery` or
    `ui-screen`.
  - **success:** Check 2.3 on demo-002 passes at its blocking threshold, with
    S1–S5's answering captures labeled `slide`.
- **CAP-2**
  - **intent:** Capture cadence on demo-002 returns to budget once webcam-tile
    motion no longer drives change detection.
  - **success:** Check 2.2 on demo-002 passes on a re-run after the CAP-1 fix.
    Re-measure only — no separate fix unless residue remains (triage
    decision of record).
- **CAP-3**
  - **intent:** When the share-region survey does not find the layout it
    expects, the fallback is recorded where an eval reader sees it, instead of
    silently degrading classification and cadence.
  - **success:** The eval run artifacts name the crop `method` and `detected`
    per subject, and demo-002's value explains (or rules out) the fallback
    path.

## Constraints

- **Verify before changing:** the mechanism in `failure-evidence.md` is a
  hypothesis. Task one is reading the recorded crop `method`/`detected` for
  demo-002; the fix targets whatever that verification shows.
- Three view types only. The migration-0003 CHECK and every downstream
  consumer stay valid; new ambiguity is expressed via tags (precedent:
  `avatar-gallery-unresolved`), never a fourth type.
- Story 1-11 retune discipline: threshold or geometry changes are justified
  against the measured baselines in `capture-measurements.md`; no regression
  on the 63 hand-labelled shots or prior corpus baselines; region detection
  stays survey-based — no model, no template match.
- File boundary: `server/meetingminer/pipeline/frameimage.py`,
  `server/meetingminer/pipeline/screens.py`, `ScreensConfig`
  (`config.py`/`config.yaml`), their tests, and demo-002 ground truth under
  `evals/ground-truth/` if the evidence shows a manifest error. Stories 2-5
  and 4-4 are in flight in parallel; none of their files may be touched.
- Iteration is local and free: capture plus `make evals-run`, serial, one run
  at a time. The worker stays stopped — no paid calls. A projection-test run
  owes a `make rebuild` afterward.

## Non-goals

- Check 2.1 on demo-001 (SC2/SC3 dense-screen misses, SC4 at score 0.0) — a
  separate threshold/ground-truth decision, recorded in the triage note, not
  this defect.
- The two expected 2.11 publish-gate failures — story 4-4 retires those.
- Re-capturing or re-tuning the 28-meeting real corpus; this story's subjects
  are the two scripted demos.

## Success signal

`make evals-run` on the scripted demos goes from 19/23 to 21/23 with only the
two expected 2.11 failures remaining, and the prior corpus classification
baselines show no regression.

## Assumptions

- The mechanism is the share-region survey missing demo-002's layout and
  falling back to full-frame pixels, so the camera-first rule fires
  (`classify_view_type`, `screens.py:197`) and webcam motion inflates change
  cues. Held as a hypothesis pending the CAP-3 verification, not asserted.

## Open Questions

- If verification shows the survey *did* detect a region and the crop is
  correct, the failure is in the classification thresholds for this content —
  the 1-11 baseline set then needs demo-002 frames added before retuning.
  Which way it goes is decided by evidence, not in this spec.
