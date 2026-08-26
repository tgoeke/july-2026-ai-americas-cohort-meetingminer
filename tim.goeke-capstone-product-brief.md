# MeetingMiner
## An Evidence Engine for Trustworthy AI Engineering

**Tagline:** *Transform meetings into durable engineering knowledge.*

**InfoQ Certified AI Engineering Program — Capstone Project**  
**Author:** Tim Goeke

---

# Executive Summary

Large language models have become remarkably good at generating engineering artifacts. What they still cannot do is prove where those artifacts came from.

Today's AI meeting assistants generate summaries, action items, and decisions that users are expected to trust without evidence. While useful for personal productivity, they are difficult to rely upon for engineering work, where requirements, architectural decisions, implementation plans, and backlog changes must remain traceable to their original source.

**MeetingMiner** treats meetings as evidence to preserve, not conversations to summarize.

Every distinct application screen, every spoken discussion, every participant, and every engineering decision is captured, aligned, indexed, and linked back to the original recording. AI is then used to mine that evidence into engineering artifacts—but every artifact remains traceable to the exact video moment that produced it.

The result is not another meeting summarizer.

It is a trustworthy engineering memory.

---

# Problem Statement

Engineering knowledge is created continuously during meetings.

Software demonstrations, architecture reviews, sprint planning sessions, customer interviews, design reviews, and incident postmortems all produce valuable knowledge:

- requirements
- architectural decisions
- implementation constraints
- business rules
- risks
- rationale
- action items

Unfortunately, that knowledge is largely ephemeral.

As a lead application architect, one of my recurring responsibilities is reviewing recorded software demonstrations and translating them into architecture decisions, requirements, and backlog changes. Today that process is largely manual:

- scrub through recordings
- capture screenshots
- align them with transcripts
- copy evidence into an LLM
- generate engineering artifacts

This process routinely takes hours per meeting.

More importantly, it fails silently.

If a critical application screen is missed during review, nobody knows to go looking for the requirement it contained.

The fundamental problem is preserving trustworthy engineering evidence, not summarization.

---

# Vision

MeetingMiner transforms ephemeral conversations into durable engineering knowledge.

Rather than generating summaries that must be trusted, MeetingMiner creates an evidence-first representation of every meeting that becomes the foundation for future engineering work.

Every processed meeting becomes part of a searchable engineering memory where every claim can be traced back to its original source.

This evidence foundation enables AI systems to generate trustworthy engineering artifacts because every conclusion remains verifiable.

---

# Solution

MeetingMiner accepts either:

- a Microsoft Teams meeting recap URL
- or a local meeting recording

It automatically produces an evidence bundle containing:

- every distinct application screen
- a verified speaker-attributed transcript
- alignment between screens and discussion
- timestamps
- provenance metadata
- replay links to the original recording

Every processed meeting is then indexed into a searchable knowledge base.

Users can:

- search across meetings
- ask questions in natural language
- replay supporting evidence instantly

Every answer must include citations.

Every citation must replay the original evidence.

**No citation. No answer.**

---

# Core Design Principles

## Evidence First

Evidence is the primary artifact.

Summaries, requirements, decisions, and future engineering artifacts are derived from evidence—not the other way around.

---

## Provenance Everywhere

Every generated artifact remains linked to:

- meeting
- speaker
- timestamp
- application screen
- original recording

Verification should take seconds rather than requiring someone to rewatch an entire meeting.

---

## Deterministic Core

The system separates deterministic processing from probabilistic AI.

Deterministic components are responsible for:

- evidence capture
- transcript alignment
- provenance
- replay
- search
- evaluation

AI contributes evidence.

AI never owns truth.

---

## AI Behind Stable Interfaces

All model interaction occurs behind adapter interfaces.

Speech recognition, embeddings, transcript refinement, and future language models are replaceable through configuration rather than code changes.

The architecture evolves independently of model vendors.

---

## Evaluation First

Evaluation is treated as a first-class architectural concern.

MeetingMiner will use scripted Microsoft Teams meetings with known ground truth.

Because every meeting follows a script, the system knows before processing:

- which screens should be captured
- what was said
- who said it
- what questions should be answerable

Every pipeline change is evaluated against known answers before deployment.

---

# High-Level Architecture

```
Meeting Sources
        │
        ▼
Source Adapters
        │
        ▼
Pipeline Orchestrator
        │
 ┌──────┼──────────┐
 ▼      ▼          ▼
Video   Audio   Metadata
Lane    Lane    Extraction
 └──────┼──────────┘
        ▼
Evidence Builder
        │
        ▼
Evidence Bundle
        │
 ┌──────┴──────────┐
 ▼                 ▼
Viewer      Knowledge Base
                    │
                    ▼
          Search + RAG + Chat
```

---

# What Makes MeetingMiner Different

Existing AI meeting assistants optimize for summaries.

MeetingMiner optimizes for evidence.

Instead of asking users to trust generated prose, it preserves the original engineering conversation and allows every generated artifact to be verified against its source.

The innovation is not a better language model but an architecture that makes probabilistic AI trustworthy through deterministic evidence capture, provenance, replay, and evaluation.

---

# Success Criteria

The capstone is successful when a previously unseen software demonstration can be processed automatically and produces:

- complete application screen capture
- verified transcript alignment
- searchable engineering knowledge
- replayable provenance
- cited chat responses

The primary evaluation metric is **capture recall**, and the required score against the scripted ground truth is 100%.

Missing a screen means missing potential requirements.

Therefore, the system is intentionally biased toward preserving evidence rather than minimizing duplicates.

---

# Future Vision

MeetingMiner begins with recorded software demonstrations because they provide measurable ground truth.

The architecture is intentionally broader.

The same evidence-first platform naturally extends to:

- architecture reviews
- discovery workshops
- sprint reviews
- customer interviews
- incident postmortems
- design sessions

Once trustworthy evidence exists, additional AI capabilities become possible:

- requirements extraction
- ADR generation
- business rule discovery
- API change detection
- implementation planning
- GraphRAG
- engineering agent workflows

Every future capability inherits the same principle:

**Engineering decisions are only as trustworthy as the evidence they preserve.**

---

# Design Philosophy

> **AI proposes.  
> Provenance verifies.  
> Humans approve.**
