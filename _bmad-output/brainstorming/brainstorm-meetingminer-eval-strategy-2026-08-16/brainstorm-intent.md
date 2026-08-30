# MeetingMiner Eval Strategy — Intent

Eval design for the MeetingMiner capstone (evidence-first meeting mining). Scripted
Microsoft Teams meetings serve as ground truth; capture recall is the primary metric.
Scope is eval design only — not the demo script.

## Architecture: Deterministic-First Tiered Judging Pyramid

- Ground truth = machine-readable YAML meeting scripts (action items, planted phrases,
  timestamps, slide manifest).
- Judging tiers, in order:
  1. Deterministic asserts — script diff, OCR text compare, timestamp-window assert,
     fuzzy set-match — always run first.
  2. LLM judge — for extraction and answer-quality scoring.
  3. Human judge — final arbiter, operated via a simple runbook, kept in the loop
     over deterministic/LLM results.
- Thesis parallel: the eval strategy mirrors the product itself — deterministic core,
  probabilistic contributors, humans approve.

## Ground-Truth Design

- Scripted test decks display ALL slides, keeping ground truth clean and processing easy.
- Expected screenshot count: at least the slide count PLUS participant-screen segments
  (meeting start, and whenever sharing stops).
- Scripts plant action items and phrases with known timestamps; every expected artifact
  per meeting is known up front and checked against what was detected.

## Metrics and Checks

Recall metrics are paired with anti-spam guardrails.

- Capture recall — screenshots vs the script's expected-artifact manifest (script diff
  + OCR compare + human judge).
- Over-capture guardrail — distinct captures must stay under one slide OR screen per
  minute of meeting duration (deterministic only).
- View classification — slide view vs participant/gallery view; classification accuracy
  is itself evaluated.
- Dedup quality — OCR text comparison on sequential captures; human judge over results.
- Citation timestamp-window check — |cited timestamp − scripted timestamp| ≤ 15s.
- Action-item extraction — fuzzy set-match against scripted items: found / missing /
  extra; LLM + human judge.
- ADR/decision extraction and cited Q&A answer quality — LLM judge + human judge.
- Retrieval right-moment-cited — human judge for the capstone; the deterministic
  timestamp-window check above is the documented replacement.

## Design Notes (capture pipeline)

- Dwell threshold: a screen held ~20–30s triggers a snapshot.
- Bitrate-delta detection: large video-stream playback changes mark candidate capture
  moments.

## Eval Cadence

- ONE full eval run before demo (honest capstone scope).
- Documented (not implemented): change-triggered runs on prompt or screenshot-algorithm
  changes, plus a pre-delivery go-to-production run.

## Sequencing Rule

The eval harness and all setup are completed BEFORE demo-script work begins.

## Build Plan (as decided)

**BUILD this week**
- YAML meeting scripts (ground truth as data)
- Capture recall check via script diff
- Over-capture guardrail (one slide OR screen per minute)
- OCR text compare (dedup + capture-to-script matching; PNG-to-slide matching TBD)
- View classification eval (first pass)
- Human judging protocol as a simple runbook

**BUILD nice-to-have**
- LLM judge harness

**DOCUMENT only**
- Citation timestamp-window check
- Fuzzy set-match for action items
- Eval cadence document (change-triggered runs, go-to-prod gate)
- Full retrieval eval design docs

**SKIP this week**
- Image-similarity dedup scan
