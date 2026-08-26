# Run sheet — demo-002 "Q3 Architecture Review" (slide-deck, 18 min)

Derived from `evals/ground-truth/demo-002-q3-architecture-review.yaml`.
Timestamps are elapsed from **recording start** — start recording AND
transcription at meeting start, keep a visible timer; ±15s tolerance.

**Participants:** Tim Goeke (presenter), Tiffany Goeke (reviewer). A different
reviewer means updating `participants:` in the ground-truth YAML *before*
processing. Note two planted lines belong to the **reviewer** — brief them on
their two lines and rough cue times before the meeting.

**Slides:** open `demo-002-slides.html` in a browser tab; arrow keys advance.
The deck is the full manifest — all five slides must be shown.

| Clock | Action |
|---|---|
| 00:00 | Meeting + recording start. Cameras on, **deck not shared yet** (participant segment 1). Intro chat. |
| 00:00:45 | Share the deck. **S1 title slide** (anchor: *Q3 Architecture Review*). |
| 00:03:10 | **S2** (anchor: *Evidence Pipeline Today*). Walk the pipeline. |
| 00:06:25 | **S3** (anchor: *Retrieval Split Graph and Document Index*). |
| 00:07:15 | Tim states decision D1: **"The document index stays a separate store from the graph."** |
| 00:08:40 | Tiffany states action item AI1: **"I'll write the ADR for the retrieval split before the next review."** |
| 00:10:05 | **S4** (anchor: *Nothing Enters a Store Before Approval*). |
| 00:11:20 | Tim states decision D2: **"No artifact is projected into a retrieval store before it is approved."** |
| 00:12:05 | Tiffany says the planted phrase in a sentence: **"…that's our tangerine scaffolding checkpoint."** (P1) |
| 00:13:30 | **S5** (anchor: *Q4 Proposal and Open Risks*). |
| 00:15:50 | **Close the deck** (participant segment 2). Questions on camera. |
| ~00:18:00 | Wrap, stop recording, end meeting. |

**Expected captures:** 5 slides + 2 participant segments = 7. A slide-deck
manifest is the full deck — skipping a slide is a guaranteed recall miss.

## What actually matters (checked against the harness)

Screens/slides match by **OCR anchor**, participant segments by **count** —
their timestamps never enter the checks; the table above is pacing only.
Say the planted **phrase verbatim**; action items fuzzy-match and decisions
are judged, so natural phrasing around the key nouns is fine. The one exact
dependency is check 2.5's ±15s citation window against each planted item's
`at` — so after the meeting, true-up the `at` values in the ground-truth YAML
from the actual recording (reading the raw VTT/video is legitimate; the
independence rule bars extractor output, not source evidence). True-up the
**speaker names the same way**: whatever label the transcript actually shows
for Tiffany (e.g. "Goeke, Tiffany") is what `participants:` and each planted
item's `speaker:` must carry — attribution never guesses, so a mismatched
name is an unresolved speaker, not a near-match.

## After the meeting

Same four steps as demo-001's sheet: pull the recap → copy the new meeting's
`sourceId` from `GET /meetings` → replace
`placeholder-demo-002-not-yet-recorded` in
`evals/ground-truth/demo-002-q3-architecture-review.yaml` → commit, then
`make evals-run` per `evals/RUNBOOK.md`.
