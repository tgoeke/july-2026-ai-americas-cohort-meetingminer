# MeetingMiner — 3-Minute Cohort Demo Script

Saturday, August 22, 2026 · 3:00 total · slides 2:00 + live demo 1:00
Deck: `meetingminer-cohort-demo.pptx` (12 slides; presenter notes carry the same timings)

## Before you present (do this Friday, then again 30 min before)

1. `make up` — three Docker stores, migrate, then api + worker + web as host processes.
2. Confirm Ollama is running and `qwen3-embedding:0.6b` is pulled (search dies without it).
3. Confirm the demo corpus is ingested: open http://127.0.0.1:5173 — the meetings list
   should show your real meetings with completed stage bars.
4. **Pick and rehearse the search query.** It must return a hit **with a screenshot**
   (those are the hits that replay video). Type it, click the hit, confirm the video
   seeks to the moment and plays *with audio audible on the demo machine*.
   Write the winning query here: `____________________`
5. Load the browser at http://127.0.0.1:5173, zoomed so the back row can read it
   (⌘+ twice). Close every other tab. Do Not Disturb on.
6. Fallback: screen-record the rehearsed demo (⌘⇧5) and keep the recording on the
   desktop. If anything is down on Saturday, play the recording instead — same 60s.

## Run of show — slides (0:00–2:00)

| Slide | Time | Say (compressed — notes in the deck carry the full lines) |
| --- | --- | --- |
| 1 Title | 0:00 | "MeetingMiner turns Teams meetings into searchable, replayable evidence. Three minutes: architecture, decisions, then it live." |
| 2 What it does | 0:05 | "Ingest once; then everything is search and replay. The rule that shapes the whole design: **no citation, no answer**." |
| 3 Finding the screenshots | 0:15 | "Before any AI answers anything, we find what was on screen: a frame every two seconds, crop the webcam column, OCR each frame — then screen identity comes from the **text**, not the pixels. Same slide next week resolves to the same screen, and every citation gets its screenshot." |
| 4 Architecture | 0:30 | "One sentence: deterministic evidence pipeline, ports-and-adapters at every model boundary, CQRS-lite storage. Puller acquires, worker derives evidence into Postgres, projects into a graph store and a search store. Models never write evidence." |
| 5 Stack & why | 0:45 | "Boring, current tech on purpose. The one unusual call: Docker runs only the stores — the pipeline runs on the Mac host for Apple Vision and MLX. Every model is a config binding, never code." |
| 6 Storage & RAG | 1:00 | "Five decisions: one database of record; projections with exactly one writer, rebuildable from the record; GraphRAG as deterministic Cypher — the LLM never owns retrieval; the citation gate is code, not a prompt; drafts never reach retrieval." |
| 7 Encodings | 1:15 | "Measured, not guessed: 1024-dim embeddings, 1,400-char chunks, keyword-heavy hybrid ratio, 20-second moment gap — the p90 measured over 28 real meetings. Provided transcripts are immutable; STT verifies alongside." |
| 8 Ingestion | 1:25 | "One door in: a write-once drop plus one POST. Eight checkpointed, idempotent stages. Out come the derived objects: aligned segments, screens, screenshots, moments, and LLM-extracted ADRs and action items — human-approved before publish." |
| 9 Data model | 1:37 | "The moment is the atom — the citation currency, minted once, never renumbered. Screens and participants persist across meetings. Citations survive re-ingestion." |
| 10 Query path | 1:45 | "A question classifies to a traversal template; retrieval is deterministic from both stores; the LLM synthesizes; the validator resolves every marker or the answer dies. Search and replay run on this path today — cited chat is the current epic." |

## Live demo (2:00–3:00) — slide 11 up, then switch to the browser

**Beat 1 — the corpus (10s).** Meetings list at http://127.0.0.1:5173.
> "These are real Teams meetings, each ingested through that pipeline — here's the
> stage-by-stage progress, streamed live."
(Point at one completed stage bar. Do not click into anything.)

**Beat 2 — search (20s).** Type the rehearsed query. Hits appear with highlighted
snippets.
> "One query across every meeting. Hybrid keyword-plus-semantic — and every hit
> isn't a document, it's a *moment*: a span of a specific meeting with millisecond
> timing."

**Beat 3 — replay (25s).** Click the rehearsed hit (the one with a screenshot).
The player opens seeked to the moment; press play, let ~8 seconds run.
> "Click it and the recording plays from that exact moment. This is what a citation
> resolves to — not a page number, the actual conversation."
Pause. Let the room hear the meeting audio for a beat before you speak again.

**Beat 4 — the point (5s).** Back to slide 12.
> "Not a chatbot over notes — an evidence system. Every answer is a moment you can
> watch."

## Timing discipline

- Hard checkpoint: **be switching to the browser at 2:00**. If you're behind, slides
  7 (encodings) and 9 (data model) are the sacrifice — say their bold line and advance.
- The demo has ~15s slack built in. If search is slow, narrate beat 3's line while
  it loads.
- If the video won't play: the screenshot on the hit *is* the evidence — show it,
  say the replay line over it, move on. If the whole app is down: play the ⌘⇧5
  recording from the desktop.

## What NOT to claim (honesty guardrails)

- Don't demo or promise **chat/Q&A** — cited chat (Epic 3) isn't built yet; the
  query-path slide already frames it as "the current epic."
- Don't call the extraction stage live — `extract` is in review; the deck's
  "human-approved artifacts" line describes the design, and slide 7 is the design
  slide, so that's fine — just don't offer to show it.
