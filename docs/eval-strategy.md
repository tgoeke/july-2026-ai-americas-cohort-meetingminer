# Eval Strategy

Companion to `SPEC.md` (CAP-7, CAP-8). Strategy level — check algorithms, ground-truth schema, and the runbook live in `eval-design.md`. Not the demo script. Thesis parallel: the eval strategy mirrors the product — deterministic core, probabilistic contributors, humans approve.

## Architecture: deterministic-first tiered judging pyramid

Ground truth = machine-readable YAML meeting scripts (action items, planted phrases, timestamps, slide manifest). Judging tiers, in order:

1. **Deterministic asserts** — script diff, OCR text compare, timestamp-window assert, fuzzy set-match. Always run first.
2. **LLM judge** — extraction and answer-quality scoring.
3. **Human judge** — final arbiter, operated via a simple runbook, kept in the loop over deterministic/LLM results.

## Ground-truth design

- Scripted test decks display ALL slides, keeping ground truth clean and processing easy.
- Expected screenshot count: at least the slide count PLUS participant-screen segments (meeting start, and whenever sharing stops).
- Scripts plant action items and phrases with known timestamps; every expected artifact per meeting is known up front and checked against what was detected.

## Metrics and checks

Recall metrics are paired with anti-spam guardrails.

| Check | Method |
|---|---|
| Capture recall (primary; required 100%) | Screenshots vs the script's expected-artifact manifest: script diff + OCR compare + human judge. The manifest is authored independently of the extractor — never derived from its output |
| Over-capture guardrail | Distinct captures stay under one slide OR screen per minute of meeting duration (deterministic only). Measured headroom is thin: a tuned extractor sits at 0.86/min and the shipped story 1.4 path at 3.3/min — see `capture-measurements.md` |
| View classification | Slide view vs participant/gallery view; classification accuracy is itself evaluated |
| Dedup quality | OCR text comparison on sequential captures; human judge over results |
| Citation timestamp window | \|cited timestamp − scripted timestamp\| ≤ 15s |
| Action-item extraction | Fuzzy set-match against scripted items: found / missing / extra; LLM + human judge |
| ADR/decision extraction, cited Q&A answer quality | LLM judge + human judge |
| Retrieval right-moment-cited | Human judge for the capstone; the deterministic timestamp-window check is the documented replacement |

## Capture pipeline design notes

Measured behaviour and thresholds live in `capture-measurements.md`; the load-bearing points:

- Dwell threshold: a screen held ~20–30s triggers a snapshot.
- Bitrate-delta detection marks candidate capture moments — but any whole-frame proxy measures the
  participant webcam column too, so the share region is cropped **before** change detection, not after.
- The signal decides *when* a change happened; a settle rule decides *which* frame to keep. Emitting
  at the moment of change captures loading spinners and blank pages.
- View classification starts from brightness and saturation, which separate camera video from screen
  share with 4.1x and 2.2x margins and no model. Avatar-tile gallery is a known residual case.
- Loading pages are not separable from real UI by any single threshold: tag them, never drop them.

## Cadence

- ONE full eval run before demo (honest capstone scope).
- Documented, not implemented: change-triggered runs on prompt or screenshot-algorithm changes, plus a pre-delivery go-to-production run.

## Sequencing rule

The eval harness and all setup are completed BEFORE demo-script work begins.

## Build plan

**BUILD this week**
- YAML meeting scripts (ground truth as data)
- Capture recall check via script diff
- Over-capture guardrail (one slide OR screen per minute)
- OCR text compare (dedup + capture-to-script matching; unique-anchor authoring rule per `eval-design.md` §1, Apple Vision primary / Tesseract fallback)
- View classification eval (first pass)
- Eval runbook (CAP-8) — operator procedure for the full eval run, human judging included; procedure lives in `eval-design.md`

**BUILD nice-to-have**
- LLM judge harness

**DOCUMENT only**
- Citation timestamp-window check
- Fuzzy set-match for action items
- Eval cadence document (change-triggered runs, go-to-prod gate)
- Full retrieval eval design docs

**SKIP this week**
- Image-similarity dedup scan
