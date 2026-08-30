# MeetingMiner — Brainstorm Intent (Capstone Input)

Source: brainstorming session 2026-08-16. Capstone for AI engineering cohort: agentic search indexing, RAG/GraphRAG retrieval, Teams integration. Solo dev; demo next week (~2 weeks total). Strategy: design everything, build the slice.

## Core Concept

- **Moment** is the atomic first-class domain object — attachable to a screenshot, project, product, presentation/slideshow. Every derived artifact welds to a moment.
- **Screen lineage**: the system recognizes the SAME screen across meetings, enabling "show every discussion of this screen over time" and comparison against prior decisions.
- **Screenshots are the trust anchor**: screenshots + transcript segments are what people actually review; video clips are rarely watched but serve as proof that derived artifacts are correct. Decision records link back to their video moment.
- **The domain object graph IS the GraphRAG index**: Moment, Meeting, Screen, Screenshot, Project, Product, Participants, artifacts. Moment + lineage + trust-anchor are one idea — the evidence graph is the retrieval index.
- **"No citation, no answer"**: any factual claim about meeting content must trace to a moment. The user could not imagine an exception. This is the active ingredient.

## Problem Framing

The diseases are retrieval failures; cited retrieval is the cure.

- **Re-deciding**: at corp, people forget decisions and schedule whole meetings just to re-make the same decision. Firm, evidenced decisions are stakes in the sand — architects design with confidence and designs get re-vetted through the same evidence loop (MM output becomes MM input).
- **Re-explaining / rehash**: Scott/Rowan story — "I already explained this to Rowan," but that meeting's knowledge is inaccessible, so it gets re-explained live; meetings rehash prior meetings. The query (participants → meetings → topics → moments) is a canonical graph traversal and the live demo narrative with obvious eval ground truth.
- **Rework from unwitnessed decisions**: 2024 war story — absent stakeholders disagreed with UI demo outcomes months later, forcing a redesign and a 4-month schedule slip.
- **The labor chain MM replaces**: review recording → extract requirements → build action items → summarize → present outcomes in other meetings → build PowerPoints that spawn further meetings.
- **Underlying need**: fewer, calmer meetings; less rework; reduced delivery chaos and organizational stress — efficiency and profitability, but also less exasperation and lower staff churn; reclaiming time for actual work.

## Capstone Scope (MoSCoW)

| Cluster | Decision |
|---|---|
| A. Evidence Core | MUST |
| B. Domain Graph | MUST |
| C. Retrieval | MUST, partial slice (below) |
| D. Extraction | MUST for ADRs + action items; prompt packs COULD; capstone ships baked-in prompts, visible in UI, easily swappable via configuration |
| E. Publishing | Trimmed: publish artifacts to a folder + commit ADRs to a plain local git repo (not GitHub) |
| F. Autonomous | WON'T, except Morning Digest COULD — generate an example email only, no delivery |
| G. Meeting-killers (self-assembling decks, stakeholder agree/disagree) | WON'T this time |
| H. Wild cards | WON'T, except YouTube demo ingestion COULD if time permits |

**Retrieval partial slice**: implement topic/mention search + cited Q&A + GraphRAG over the domain graph; document (not implement) the retrieval eval strategy; produce designs for ALL retrieval items and set expectations with instructors.

## User-Experience Spine

- **Ingestion flow**: Teams recap → browser view → capture URL → paste into puller script → transcript + recording pulled locally → local ingest. Ingestion completes before viewing: video processed, screenshots extracted, moments identified, transcript segmented to match video flow — all precomputed. Participants pulled from Microsoft Graph at ingest to build the participant graph.
- **Moment view anatomy**: still screenshot on top; transcript section below; right rail with extracted analytics (action items, ADRs, decisions, stories, requirements, bug fixes, change requests); full audio+video replay button.
- **Search and locate**: corpus-wide topic search → candidate meetings → drill into transcript with highlighted mentions → small inline video replays. Search by meeting name, topic, mention; ask questions about any decision. Meeting drill-down shows the captured screenshot series (UI screens, slides, or participant headshots when nobody is presenting). Two meeting archetypes: slide-deck presentations vs UI demos — different screenshot types and artifact sets.
- **Human-approved publishing**: extracted artifacts start unpublished; on first visit the user chooses to push stories/tasks/decision docs out. "AI proposes, humans approve" as a UX gesture, per moment.

## Boundary Decisions

- **One-way generation engine**: set-it-and-forget-it outbound; no status sync back from Asana/Linear/GitHub — just outbound links shown in context.
- **Not a tracking system**: lifecycle tracking lives in Asana/Linear/RAID logs; MM may display items it created there but never owns their state. MM's job is the evidence at the origin of the decision workflow.
- **Series membership is human-declared**, not inferred; recurring meetings get per-meeting documents — cross-meeting rollups are the on-demand exception.
- **Extraction prompts baked in** for the capstone, visible in the UI, swappable via configuration.

## Product-Later (Out of Capstone Scope)

- Autonomous ingestion: watch Microsoft Graph / Teams chats for recap-ready events, auto-ingest everything with zero user action; notification subscriptions (processing complete, decision derived).
- Morning digest email delivery: summary of ALL of yesterday's meetings — attended or not — with the user's assigned action items (capstone generates one example email only).
- Per-participant prompt packs (general processing first, then each participant's registered prompts — e.g. architect's pack: executive summary, architectural impact doc, change requests). Resolves the persona assumption (PMs, leadership, process/data architects extract differently) without touching the deterministic core.
- Self-assembling decks: generate the next meeting's presentation from mined artifacts; MM's own well-formatted post-meeting recap for one-look approval; in-flight drafting during meetings.
- Absent-stakeholder agree/disagree registered at the evidence.
- Wild cards: YouTube demo ingestion + reverse-engineering mode (requirements/wireframes from a product demo); Figma reproduction of captured screens for approval; hand-off to agentic engineering workflows.
- Outbound routing to live systems (tasks → Asana, stories → Linear, ADRs → GitHub/SharePoint); Clerk auth + Entra ID enterprise integration; timeline view of a topic's moments across all meetings; custom user-authored extraction prompts in-tool.
