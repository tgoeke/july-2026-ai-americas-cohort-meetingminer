# Epic 1 Context: Meeting Ingestion & Evidence Bundle

<!-- Generated from planning artifacts. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Provide one dependable path from a Teams or local evidence source to a fully precomputed, replayable meeting-evidence bundle. The epic accepts recording-only, transcript-only and combined inputs; preserves source evidence, participant identity and provenance; persists authoritative evidence in Postgres; projects it into both retrieval stores; and exposes trustworthy job progress so a meeting is viewable only once its complete evidence exists. It also establishes the scaffold, runtime split and configuration conventions every later epic builds on.

## Stories

- Story 1.1: One-Command Development Environment
- Story 1.2: Source-Drop Intake Endpoint
- Story 1.3: Checkpointed Ingestion Worker (probe + frames)
- Story 1.4: Screen Identification & Screenshots
- Story 1.5: Transcript Verification, Alignment & Participants
- Story 1.6: Moment Identification Completes the Bundle
- Story 1.7: Evidence Projections & Rebuild CLI
- Story 1.8: Teams Puller Emits Source Drops
- Story 1.9: Ingestion Progress in the UI
- Story 1.10: Development Environment Hardening
- Story 1.11: Screen Capture Retune Against Measured Baselines
- Story 1.12: Late-Recording Augmentation
- Story 1.13: Drops Carry the Participant Graph

## Requirements & Constraints

- Evidence enters through exactly one door: an intake endpoint validating the drop against a versioned, camelCase JSON Schema before creating work. A drop carries a stable source id, corpus classification (scripted meetings are the eval subjects, real ones the demo corpus), started-at time plus its precision, embedded provenance, and at least a recording or a transcript; unrecognized files are ignored. Files appearing in the folder never ingest on their own — no folder watcher exists or may be built. A submission whose source id already has a non-failed job is refused as a conflict: re-processing is a rerun of the existing job, never a second meeting.
- Drops are write-once and read-only after intake — staged, finalized atomically, never overwritten or mutated by ingestion. They are the recovery root for evidence; human-curated state (approvals, participant merges, series membership) is not reconstructable from them.
- Transcript-only evidence is first-class, not degraded input. Video-dependent stages record as skipped, moments derive from transcript segmentation with no screenshot, and each carries a transitional deep link to the original recap where a replay link would sit.
- A job reaches done only after the whole bundle is precomputed: screens and screenshots where video exists, provided plus derived transcript rows, participants, moments carrying both video-offset milliseconds and ISO 8601 UTC wall clock, and provenance. Stages are idempotent and restartable; a failure records stage, error and timestamp on the job row and is never swallowed.
- Capture prefers over-capture to loss — 100% recall, bounded only by a guardrail of under one distinct capture per minute of meeting. Capture decisions are made on the detected share region, settle before emitting a frame, reject camera and gallery video before any text rule, and tag rather than drop likely transitions. Every threshold is configuration, never a code constant.
- Speaker attribution never guesses: a label resolving to no participant stays unresolved, one resolving to several stays ambiguous, and neither merges into a resolved person. Externals flagged unresolved in the participant graph are preserved as such.
- Participant identity keys on the directory mail address the puller's participant graph supplies, with normalized display name as the fallback only where mail is absent. The drop must therefore carry that graph — transcript speaker names alone collapse same-named people and split one person across spelling variants.
- A recording recovered after a transcript-only ingest augments that meeting in place: only the previously skipped stages run, screen-derived moments may be added, and screenshots, alignment and replay attach to existing ones — never deleting, renumbering or re-keying a moment that exists, and citations and published artifacts made beforehand must still resolve. More broadly, no later drop may shrink a meeting: a replacement must keep the corpus, wall-clock instant and precision, still carry every transcript the current drop carries, and never return a meeting that has a recording to transcript-only — binding ordinary retry of a failed job as much as declared augmentation.
- Only published artifacts may reach the retrieval stores; the gate is in place from day one even though extraction ships later. Local-first, single-user, no authentication, one machine, and no server component calls Microsoft Graph.

## Technical Decisions

- Postgres is the sole database of record. Every domain object is minted there with a Postgres-generated UUIDv7, and that id flows unchanged into the graph store, search index, API payloads and citations; projected nodes and documents key on it, never on a sequence number. Media lives on disk under one content root with root-relative paths in the database.
- Runtime splits: containers run only the stateful stores while API, worker, web dev server and local model runtime are host processes, so stages can reach macOS-only frameworks.
- The pipeline is a fixed checkpointed stage order — probe, frames, ocr, screens, transcribe, align, moments, extract — owned entirely by the worker; the API enqueues and reports but never executes a stage. Jobs are rows the worker claims and advances, with no broker or queue framework. Rerunning a stage overwrites only rows keyed to that job's meeting; cross-meeting entities (screens, participants) are upserted by identity key and never deleted by a rerun.
- Every model call (OCR, STT, diarization, LLM roles, embeddings) goes through a project-owned port bound from one versioned config file; environment variables carry secrets only. Model swaps are config edits, except the embedder, whose model and dimension are projection state and force a full rebuild.
- Provided transcripts are immutable inputs: preserved verbatim, with verification and alignment written as new derived rows carrying provenance to both the original and the recognizer output. Where a drop carries several transcript forms they are reconciled by text alignment, never by picking one file wholesale.
- Table ownership is disjoint: the worker owns evidence and job tables, the API owns user-declared data, and artifacts and participants split by column. A participant merge writes an API-owned alias row the worker resolves before any insert, so merges survive re-ingests and stage reruns — including one that moves identity from name-keyed to mail-keyed.
- A single projections module is the only writer to the graph and search stores. It computes embeddings through the port with store-native auto-embedders disabled, records the model that wrote the vectors, treats them as insert-only, carries a meeting id on every meeting-scoped row so re-indexing one occurrence is a delete-and-reinsert, and hosts the publish gate. A rebuild CLI regenerates both stores from the database plus resolved config alone. Full-text search is a first-class half of retrieval, not a fallback behind the vector store.
- Drop schema version 2 adds an optional declaration naming the occurrence a drop augments; carrying it implies version 2, so an older consumer fails loudly instead of ingesting the recording as a second meeting. That declaration, not the drop's own source id, is the link, so the two ids may legitimately differ. Intake accepts such a drop only against an existing, settled, recording-less occurrence at the same corpus, then re-arms that occurrence's existing job in place, preserving the meeting id and every moment id beneath it.
- Conventions: snake_case in database and Python, camelCase in JSON at the API boundary; RFC 9457 problem responses; SSE (never WebSockets) with pinned event names for job progress; structured JSON logs carrying job id and stage.
- The puller is a vendored black box outside the runtime boundary: its own language, no shared server code, authenticated only by its persisted browser session. It owns emit-drop and the one-time backfill of the already-pulled archive, and puller and pipeline tests validate independently against the drop schema.

## UX & Interaction Patterns

- The entry gesture is pasting a recap URL into the puller CLI; the web app makes the current stage, completion and any recorded stage error legible in real time from streamed events, and a meeting is not openable until its job is done.
- Transcript-only moments render the same view minus screenshot and inline replay, with a clearly transitional source deep link where the replay affordance sits; transcript, highlighted mentions and the right rail stay fully functional. When augmentation supplies video, real replay replaces the link.

## Cross-Story Dependencies

- The scaffold and config regime (1.1, hardened by 1.10) precede all pipeline work; the drop schema and intake contract (1.2) gate the worker (1.3), the puller's emit step (1.8, extended by 1.13) and augmentation intake (1.12). Capture retune (1.11) was sequenced before moment identification (1.6), which inherits whatever screenshot noise capture leaves behind.
- Participant identity (1.5) depends on the drop actually carrying the participant graph (1.13); 1.13 also supplies the puller-side re-emit that closes late-recording augmentation (1.12) end-to-end rather than server-side only. Projections and the rebuild path (1.7) must exist before augmentation can re-project a single meeting by id.
- Moment ids and the preservation guarantees established here are the citation and replay identity contract for the exploration, search/Q&A and publishing epics; the publish gate lands here ahead of the extraction epic that fills it.
