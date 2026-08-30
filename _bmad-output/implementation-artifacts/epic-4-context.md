# Epic 4 Context: Artifact Extraction & Human-Approved Publishing

<!-- Generated from planning artifacts. Regenerate with compile-epic-context if planning docs change. -->

## Goal

The system extracts ADRs and action items over the whole meeting transcript using visible, config-swappable prompts, landing them as unpublished drafts in the moment's right rail. A per-moment human approval publishes artifacts to a folder and commits ADRs to a plain local git repository; published artifacts are then re-indexed into both retrieval stores as searchable, citable knowledge with their own evidence trail back to the yielding moment. The publish gate guarantees unpublished AI output never surfaces in search or chat — “AI proposes, humans approve” is enforced by code, not convention.

## Stories

- Story 4.1: Artifact Extraction Pipeline Stage
- Story 4.1a: Whole-Transcript Extraction
- Story 4.2: Visible, Swappable Extraction Prompts
- Story 4.3: Per-Moment Approval & Publishing
- Story 4.4: Published Artifacts Become Citable Knowledge
- Story 4.5: Morning Digest Example Email (COULD — droppable)

## Requirements & Constraints

- `extract` is the final ingest stage, after `moments`; it is checkpointed, idempotent, and runs for transcript-only meetings.
- Extraction is whole-transcript, not per-moment. Each extracted timestamp anchor must resolve deterministically to its containing moment; an unresolvable anchor is a named error, never a dropped artifact.
- When a drop includes the source tool’s extraction documents, parse them without a model call and retain the normal arrived-file provenance. Otherwise, pass the timestamped transcript to the configured local extraction model and parse every supported source through one strict parser.
- A plainly extractable input producing zero parsed artifacts is a failure signal, not successful emptiness. Cloud/paid extraction requires fresh explicit per-run authorization.
- Extraction touches only artifact rows. Extracted artifacts begin in `extracted` and remain visible only in their moment right rail until published; no unapproved artifact may appear in search or chat.
- Artifact lifecycle is API-only and one-way: `extracted → approved → published`; there is no unpublish route. A single approval gesture covers a moment’s artifacts and unapproved artifacts remain `extracted` indefinitely.
- Publishing writes artifacts to the configured folder and additionally commits ADRs to the local repository. The moment view shows outbound links, but MeetingMiner neither owns nor displays downstream status.
- Publishing re-indexes artifacts into Neo4j and Meilisearch with source-moment citations. `rebuild` must re-project published artifacts while excluding drafts.
- Artifact types cover action items, ADRs, decisions, stories, requirements, bug fixes, and change requests, with appropriate sets for slide-deck and UI-demo meetings.
- Active prompts must be visible per artifact type and config-swappable; each artifact records its prompt/model configuration for provenance and eval snapshots.
- Story 4.5 is COULD scope: a single example digest reads published artifacts from Postgres and writes one file, with no delivery, scheduler, or additional architecture.

## Technical Decisions

- Extraction uses the config-bound `Llm(extraction)` port. Prompts and model bindings live in the versioned `config.yaml`; secrets stay in `.env`.
- `artifacts` has disjoint column ownership: the worker inserts and owns extraction-content fields; the API owns lifecycle and publish metadata. Postgres is authoritative; Neo4j and Meilisearch are derived projections.
- All retrieval-store writes pass through `server/projections`: the worker projects evidence at ingest completion and the API projects artifacts on publish. The publish gate is in that module and rejects artifacts not in `published` state, regardless of caller.
- The projections module owns embeddings through the configured `Embedder` port; store-native auto-embedders stay disabled so rebuild is deterministic from Postgres and config.
- The publish folder and plain git repository are a third configured export location, not an evidence storage root. The API writes exports once; no publish-relative path is used to serve requests.
- Approval/publish state and the publish repository are not recoverable from source drops. They require backup with the Postgres dump and storage roots.
- Augmenting re-ingests preserve existing moment IDs, so published artifact links and citations remain stable across later evidence recovery.
- ADR file format and commit conventions are intentionally build-time choices because the API is their single writer.

## UX & Interaction Patterns

- The Epic 2 moment-view right rail is the sole surface for unpublished artifacts.
- Per-moment approval is the explicit publication gesture; generated links appear in context after publishing, without downstream-status synchronization.
- The extraction area exposes the complete active prompt text and explains that prompt/model changes are configuration changes.
- Published ADRs discovered via search or chat retain citations that replay their source moments.

## Cross-Story Dependencies

- Story 4.1 relies on Epic 1’s pipeline and Epic 2’s right rail; 4.1a extends the same extract stage with whole-transcript inputs.
- Story 4.2 supplies the visible prompt and provenance contract consumed by extraction and eval snapshots.
- Story 4.3 depends on extracted artifacts from 4.1/4.1a. Story 4.4 depends on its publish transition and the existing projections/rebuild infrastructure.
- Epic 3 retrieval correctness depends on the Epic 4 publish gate; Epic 5’s public endpoint check exercises approval, publishing, and projection end to end.
- Story 4.5 depends only on published Postgres artifacts and may be dropped without downstream impact.
