# Capstone Scope (MoSCoW)

Companion to `SPEC.md`. Decides what the ~2-week solo capstone builds vs designs vs defers. Strategy: design everything, build the slice.

## Cluster decisions

| Cluster | Decision |
|---|---|
| A. Evidence Core | MUST |
| B. Domain Graph | MUST |
| C. Retrieval | MUST, partial slice (below) |
| D. Extraction | MUST for ADRs + action items; prompt packs COULD; capstone ships baked-in prompts, visible in UI, swappable via configuration |
| E. Publishing | Trimmed: publish artifacts to a folder + commit ADRs to a plain local git repo (not GitHub) |
| F. Autonomous | WON'T, except Morning Digest COULD — generate an example email only, no delivery |
| G. Meeting-killers (self-assembling decks, stakeholder agree/disagree) | WON'T this time |
| H. Wild cards | WON'T, except YouTube demo ingestion COULD if time permits |

## Corpus

- **Scripted mock meetings** — hosted and recorded on the corp Teams tenant, pulled with `pull_transcript`, dropped on the dev Mac. Sole basis for eval: ground-truth manifests, 100% capture recall, and all `eval-design.md` checks apply only to these.
- **Real pulled meetings** — the existing `pull_transcript/` archive (vendor, project, Boomi, corp internal). Part of the demo corpus: ingested, searchable, and visible in the live demo. Measured 2026-08-18: 28 occurrences, only 8 with a recording — 20 ingest transcript-only, searchable and citable, without screenshots, carrying a source deep link instead of video replay. That split is actively closing: recordings sit in each recorder's personal OneDrive and are being recovered, so treat the ratio as a dated snapshot. No ground truth exists for them, so they are never eval subjects. Re-measured 2026-08-19: recovery is well underway — 77 of the 103 indexed archive recordings are now on disk (19.5 GB local across 85 `.mp4`, against an indexed 24.7 GB) and archive transcripts grew from 141 to 193. Teams retention still expires recordings, so pulling stays time-sensitive; inventory and the recovery path are in `corpus-facts.md`.

## Retrieval partial slice (Cluster C)

- Implement: topic/mention search + cited Q&A + GraphRAG over the domain graph.
- Implement: indexed full-text search engine over evidence documents (second retrieval store alongside the graph, per CAP-9).
- Implement: re-indexing of published artifacts (ADRs, action items, architectural docs) into the retrieval stores on approval — unpublished artifacts never enter a store.
- Document (not implement): the retrieval eval strategy.
- Produce designs for ALL retrieval items and set expectations with instructors.

## Product-later (out of capstone scope)

- Autonomous ingestion: watch Microsoft Graph / Teams chats for recap-ready events, auto-ingest with zero user action; notification subscriptions (processing complete, decision derived).
- Morning digest email delivery: summary of ALL of yesterday's meetings — attended or not — with the user's assigned action items (capstone generates one example email only).
- Per-participant prompt packs: general processing first, then each participant's registered prompts (e.g. architect's pack: executive summary, architectural impact doc, change requests). Resolves the persona assumption — PMs, leadership, process/data architects extract differently — without touching the deterministic core.
- Self-assembling decks: generate the next meeting's presentation from mined artifacts; MeetingMiner's own well-formatted post-meeting recap for one-look approval; in-flight drafting during meetings.
- Absent-stakeholder agree/disagree registered at the evidence.
- Wild cards: YouTube demo ingestion + reverse-engineering mode (requirements/wireframes from a product demo); Figma reproduction of captured screens for approval; hand-off to agentic engineering workflows.
- Outbound routing to live systems: tasks → Asana, stories → Linear, ADRs → GitHub/SharePoint.
- Clerk auth + Entra ID enterprise integration.
- Microsoft Graph participant pull (capstone derives participants from transcript speakers + `_source.json` sidecar).
- Timeline view of a topic's moments across all meetings.
- Custom user-authored extraction prompts in-tool.

## Future meeting types (same evidence-first platform)

Capstone starts with recorded software demonstrations because they provide measurable ground truth. The architecture extends to: architecture reviews, discovery workshops, sprint reviews, customer interviews, incident postmortems, design sessions — and to future capabilities (requirements extraction, ADR generation, business rule discovery, API change detection, implementation planning, GraphRAG expansion, engineering agent workflows).
