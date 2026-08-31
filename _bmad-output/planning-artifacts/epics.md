---
stepsCompleted: [1, 2, 3, 4]
inputDocuments:
  - _bmad-output/specs/spec-meetingminer/SPEC.md
  - _bmad-output/specs/spec-meetingminer/scope.md
  - _bmad-output/specs/spec-meetingminer/ux-spine.md
  - _bmad-output/specs/spec-meetingminer/eval-strategy.md
  - _bmad-output/specs/spec-meetingminer/eval-design.md
  - _bmad-output/specs/spec-meetingminer/architecture-diagrams.md
  - _bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/solution-design.md
  - _bmad-output/planning-artifacts/sprint-change-proposal-2026-08-29.md
---

# meetingminer - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for meetingminer, decomposing the requirements from the SPEC kernel (serving as PRD), UX spine, and Architecture spine into implementable stories.

## Requirements Inventory

### Functional Requirements

FR1: User can acquire a Microsoft Teams meeting by pasting a recap/Stream URL into the local puller CLI, whose emit-drop step finalizes a write-once source drop — recording and/or speaker-attributed transcript export plus `metadata.json` (embedded provenance, best-effort participants) — atomically into the dedicated drops folder on the dev Mac and calls `POST /ingests` (CAP-1, AD-1)
FR2: User can ingest a local recording — alone or paired with a provided transcript file — through the same source-drop contract; transcript-only drops (no recording) are first-class; a provided transcript is verified and merged, never erased (CAP-1, AD-1, AD-13)
FR3: System validates every source drop against a versioned JSON Schema (`docs/source-drop.schema.json`) at the single intake endpoint `POST /ingests` and inserts a job row; a `POST /ingests` whose `sourceId` already has a non-failed job is rejected with an RFC 9457 conflict — re-processing is a rerun of the existing job, never a second Meeting row — **except an augmenting drop**, which declares the meeting it augments and is accepted rather than rejected (FR32) (AD-1, AD-14)
FR4: Worker claims the job and runs the ingest pipeline stages in order — probe → frames → ocr → screens → transcribe → align → moments → extract — checkpointing each stage in the DB; stages are idempotent and restartable; for transcript-only drops the probe → frames → ocr → screens → transcribe stages skip and `moments` falls back to transcript segmentation; the skip is **reversible** — a recording recovered later re-runs exactly those stages against the existing meeting (FR32) (CAP-1, AD-11)
FR5: Ingestion fully precomputes the evidence bundle before first viewing: every distinct application screen, screenshots, verified speaker-attributed transcript segmented to video flow, identified moments, screen–discussion alignment, timestamps, provenance metadata, and replay links (CAP-1)
FR6: System identifies distinct screens by OCR-text similarity and recognizes the same screen across meetings (screen lineage) (CAP-1, CAP-2)
FR7: When a drop omits participants, the pipeline derives them from transcript speaker attribution; humans can edit participant display names and merge duplicates via the API — a merge writes an alias row the worker resolves before any insert, so merges survive re-ingests and stage reruns (AD-1, AD-5)
FR8: UI shows live ingestion job progress via SSE (`job.stage`, `job.done`, `job.error`) (CAP-1, AD-11)
FR9: System persists all domain objects — Moment, Meeting, Screen, Screenshot, Project, Product, Participant, Series, derived artifacts (including unpublished) — as Postgres rows from the moment of creation, with UUIDv7 IDs minted only there (CAP-2, AD-2)
FR10: Evidence objects are projected into Neo4j (graph) and Meilisearch (full-text) at ingest-complete through the single-writer projections module (CAP-2, CAP-9, AD-4)
FR11: Graph traversal answers "show every discussion of this screen over time" and the participants → meetings → topics → moments query (the "I already explained this to Rowan" demo) via hand-written, parameterized Cypher templates (CAP-2, CAP-3, AD-7)
FR12: User can search the corpus by meeting name, topic, or mention, with results from both retrieval stores (CAP-3, CAP-9)
FR13: User can ask natural-language questions; the chat orchestrator classifies the question to a traversal template, retrieves deterministically from both stores, and an LLM synthesizes the answer with inline `[[moment:<uuid>]]` markers (CAP-3, AD-6, AD-7)
FR14: A deterministic citation validator resolves every marker against Postgres and converts them to a structured citations array; any answer with uncited or unresolvable claims is rejected — no answer leaves the API (CAP-3, AD-6, AD-15)
FR15: Chat streams via SSE (`chat.token`, `chat.citations`, `chat.done`); the web app renders replay links from the structured citations array only (AD-15)
FR16: User can open any moment and see its screenshot on top, transcript section below, a right rail of extracted analytics (action items, ADRs, decisions, stories, requirements, bug fixes, change requests), and a full audio+video replay button; moments from transcript-only meetings render without a screenshot and with a transitional source deep link to the original recap where the replay button sits — transcript and right rail remain (CAP-4)
FR17: Meeting drill-down shows the captured screenshot series (UI screens, slides, or participant headshots) with highlighted mentions and inline replays (CAP-4)
FR18: API streams media (video, screenshots) by resolving paths relative to `MM_CONTENT_ROOT`; replay opens HTML5 video at the cited `startMs` (CAP-4, AD-3)
FR19: System extracts ADRs and action items from moments using baked-in prompts that are visible in the UI and swappable via configuration (CAP-5, AD-8, AD-10)
FR20: Extracted artifacts start unpublished, visible only in their moment's right rail; artifact lifecycle is a one-way Postgres state column `extracted → approved → published`, transitions API-only (CAP-6, AD-4, AD-5)
FR21: Per-moment human approval publishes artifacts to a folder and commits ADRs to a plain local git repository, with outbound links shown in context (CAP-6)
FR22: On publish, artifacts are re-indexed into both retrieval stores and become searchable, citable knowledge; the publish gate inside the projections module refuses any artifact whose state is not `published` (CAP-9, AD-4)
FR23: Unpublished artifacts never appear in any search or chat result (CAP-9, AD-4)
FR24: A `rebuild` CLI regenerates both retrieval stores from Postgres + `config.yaml` alone (AD-4)
FR25: Series membership is human-declared via the API, never inferred (SPEC constraint, AD-5)
FR26: Eval harness runs scripted meetings with machine-readable YAML ground truth (schema per eval-design.md §1) through deterministic-first tiered judging (CAP-7)
FR27: Deterministic eval checks (BUILD): capture recall via OCR-anchor matching (2.1), over-capture guardrail (2.2), view classification accuracy (2.3), dedup quality candidates (2.4), doc-index search recall@5 on planted phrases (2.10), publish-gate projection assert (2.11) (CAP-7)
FR28: Eval harness interacts with the system only as a client — public API for mutations, read-only queries for asserts — and writes immutable run artifacts to `evals/runs/<run-id>/` with the full resolved config snapshot (CAP-7, AD-16, AD-10)
FR29: LLM judge harness (nice-to-have) scores extraction and Q&A per rubric 2.7; judge model selected by a bake-off against human gold verdicts and pinned by exact model id in run metadata (CAP-7, eval-design §7)
FR30: A written eval runbook enables an operator without tribal knowledge to execute a complete eval run — setup, deterministic asserts, LLM-judge review, human judging, verdict recording, triage, and rerun (CAP-8)
FR31: (COULD, time permitting) Morning Digest generator reads published artifacts from Postgres and writes one example email file — no delivery, no scheduler (scope.md Cluster F)
FR33: User can acquire a published YouTube video by URL: the acquisition tool downloads the browser-playable MP4 and the caption track (manual captions preferred, auto-generated as fallback, VTT), finalizes a write-once source drop — `sourceId` `youtube:<videoId>`, `corpus` `real`, `startedAt` from the upload date (day precision) or release time (second precision), provenance carrying the watch URL, channel, duration, yt-dlp version and format — and calls `POST /ingests`; a repeat run on the same video reports `exists` without downloading (CAP-1, AD-1, AD-14, AD-17)
FR34: User can add a meeting from the web app: paste a YouTube URL, or supply a recording and/or transcript files (Teams `.txt`/`.vtt`, Zoom `.vtt`); the api validates the request, launches the acquisition tool as a separate host process, answers 202 with an acquisition id, and the meeting appears with live stage progress once the drop is posted — the api never downloads or converts in-process (AD-11, AD-14)
FR35: A Zoom transcript (`.vtt` with `Name: text` cue payloads) is converted at acquisition into the trusted speaker-attributed `.txt` format plus `.vtt` timing, with `transcriptDialect: zoom` recorded in provenance; the pipeline's transcript contract is unchanged (AD-1, AD-13)
FR36: The `transcribe` stage can bind a real diarizer through the existing `Diarizer` port; turns are stored as recording-local `SPEAKER_NN` tags on STT segments and surfaced per meeting with talk time and sample offsets; no tag is ever resolved to a person by the machine (AD-8, AD-13, never-guess)
FR37: User can assign each speaker tag to an existing participant or a new name, or leave it unresolved; the assignment is an api-owned `participant_alias` row and re-arms `align → moments → extract` for that meeting; moment ids, citations, and approved/published artifacts survive the rerun (AD-5, AD-13, AD-14)
FR38: `config.yaml` declares, per LLM role, a catalog of allowed bindings and a default; the api serves the catalog and persists the user's selection as user-declared data; chat resolves the selection per request, the worker per job; the effective binding is recorded in every eval run snapshot (AD-10 amended, AD-5)
FR39: The status surface reports key validity per configured provider and the active binding per role; a failing selected binding surfaces as a named error where it happens, never a substitute model (no-silent-fallback)
FR40: The home surface is a Moments view that presents the most interesting or pressing moments first — ranked deterministically from signals the database of record holds (decision and ADR artifacts, action items with stated timing, risks and open questions, meeting recency, publication recency, thread membership); every card states why it ranks, cites its moment, and replays in place; no model runs in the ranking loop at request time (CAP-3, CAP-4, AD-6)
FR41: The extract stage produces topics per meeting — name, one-line gist, and the moment anchors where each is discussed — through the same strict-parser path as the other extraction documents; topics are stored in Postgres as evidence-derived navigation anchored to moments, labeled machine-derived in the UI, renameable and mergeable by a human through api-owned curation, and never surfaced in a chat answer as a fact (CAP-5, AD-5, AD-13, no-silent-zero)
FR42: Topics are linked across meetings into threads by normalized name plus embedding similarity, with human merge and split; the graph projection gains Topic and Thread nodes with MENTIONS edges to moments at evidence-complete — navigation metadata, not approvable artifacts, so the publish gate does not apply (AD-4 clarification recorded with the story); a thread traversal template returns its meetings and moments in wall-clock order with per-level aggregates (AD-7)
FR43: The Threads view is a semantic-zoom timeline: zoomed out, threads are bands across the corpus's time span showing mention density; zooming in reveals meetings on the band, then moments with titles and speakers, then the moment's screenshot, transcript excerpt, and artifacts, then inline replay; each level fetches only what it renders and every detail traces to a moment (CAP-2, CAP-4, AD-15)

### NonFunctional Requirements

NFR1: Capture recall is 100% against the script's expected-artifact manifest; any miss fails the eval run (CAP-1, CAP-7)
NFR2: Over-capture guardrail: distinct captures stay under one slide-or-screen per minute of meeting duration (CAP-7)
NFR3: Cited timestamps fall within ±15s of the scripted timestamp (CAP-3)
NFR4: No citation, no answer — every factual claim about meeting content traces to a moment, enforced by deterministic code, not prompt instructions (SPEC core constraint)
NFR5: Deterministic components own evidence capture, transcript alignment, provenance, replay, search, and evaluation; evidence records are never written by a model (SPEC constraint)
NFR6: All model interaction (OCR, STT, diarization, LLM roles, embeddings) sits behind project-owned adapter ports, replaceable via `config.yaml` edits, never code changes (SPEC constraint, AD-8, AD-10)
NFR7: Only published (human-approved) artifacts enter the retrieval stores; unpublished artifacts exist only in the database of record (SPEC constraint)
NFR8: The system is biased toward preserving evidence over minimizing duplicates (over-capture preferred to loss) (SPEC constraint)
NFR9: One-way generation engine: no status sync back from external trackers (SPEC constraint)
NFR10: Local-first, single-user, no authentication; one environment (dev/demo MacBook M4 Max) (SPEC assumption, spine Structural Seed)
NFR11: Ingestion fully precomputes before viewing (SPEC constraint)
NFR12: Sequencing: the eval harness and all its setup complete before demo-script work begins (SPEC constraint)
NFR13: Retrieval stores are derived, rebuildable projections, never the primary copy; source drops are the immutable recovery root for evidence — human-curated state (approvals/publishes, participant merges, series membership) and the publish git repo are not reconstructable from drops, so a `pg_dump` and the publish folder are backed up alongside the drops directory (AD-2, AD-4, conventions)
NFR14: Verifying a claim against its source takes seconds, not a meeting rewatch (CAP-4 success)
NFR15: Cloud judge models receive derived data only (transcript snippets, extracted artifacts), never recordings; system-wide egress is otherwise unrestricted (AD-12)
NFR16: Delivery reality: solo developer, demo in ~1 week (~2 weeks total); design everything, build only the scope.md slice
NFR17: API errors are RFC 9457 `application/problem+json`; pipeline stage failures are recorded on the job row, never swallowed (conventions)
NFR18: Structured JSON logs; every pipeline log line carries `job_id` + `stage` (conventions)
NFR19: A routine test iteration runs in seconds, not minutes: the default server suite excludes process-spawning integration modules (marked `slow`), and no unmarked test may exceed a configured per-test budget; the full run stays under `make test` (owner direction 2026-08-29, backlog B-1)
NFR20: Test runs never contend across builders: every suite run — including the projection suites and `make evals-run` — owns its own store namespace or its own ephemeral store instances, so two worktrees running everything at once wait on nothing and corrupt nothing (owner direction 2026-08-29; extends story 2.7)

### Additional Requirements

**Starter/scaffold (impacts Epic 1 Story 1):** No external starter template. The architecture prescribes a specific monorepo source-tree seed — `server/` (uv Python project: domain, pipeline, adapters, projections, api, worker), `web/` (Vite + React + shadcn/ui), `puller/` (existing JS tool, black box), `evals/` (pytest), `infra/` (docker-compose.yml, Makefile), `docs/` — with `make up` starting infra + processes.

- Runtime split: docker-compose runs only Postgres 18 (+pgvector), Neo4j Community 2026.07, Meilisearch 1.53.x; API, worker, Vite dev server, and Ollama run as macOS host processes (AD-9)
- Pinned stack: Python 3.12+, FastAPI 0.141.x, LiteLLM ≥1.97, mlx-whisper 0.4.x, parakeet-mlx 0.5.x, pytest 9.1.x, React 19.x, @hey-api/openapi-ts 0.99.x (generated TS client), Node LTS for puller
- Single versioned `config.yaml` declares every adapter binding (OCR/STT/diarizer engines, LLM per role, embedding model + dimension, provider endpoints); env vars carry secrets only; defaults: extraction + chat = `claude-sonnet-5`, Ollama fallback (AD-10)
- Adapter ports to implement: `Ocr` (Apple Vision primary | Tesseract fallback), `Stt` (mlx-whisper | parakeet-mlx), `Diarizer` (noop default | pyannote documented), `Llm` per role (extraction, chat, judge — via LiteLLM), `Embedder` (fixed 1024-dim; local qwen3-embedding via Ollama default) (AD-8)
- Embedder change forces full projection rebuild and triggers the eval rerun rule (AD-8)
- Source-drop contract pinned by versioned JSON Schema at `docs/source-drop.schema.json` (camelCase, explicit `schemaVersion`); drops are write-once, assembled in a staging path and finalized atomically — a re-pull never overwrites a finalized drop; at least one of recording or transcript must be present; `metadata.json` requires `sourceId` (recording drive-item ID or Stream URL), `corpus` (`"scripted"` | `"real"`, carried onto the Meeting row), `startedAt` (ISO 8601 UTC) with `startedAtPrecision` (`"second"` | `"day"`), and embedded `provenance` (the puller's `_source.json` content); puller and pipeline both validate against the schema in their tests; unknown files in a drop are ignored (AD-1)
- Existing puller stays a black box in its own language, vendored in the monorepo but outside the runtime boundary; it authenticates via its persisted browser session (`.transcript-profile/`) — no credential files; it gains an emit-drop step plus a one-time backfill pass converting the already-pulled archive into schema-valid drops; no server component calls Microsoft Graph — Graph participant lookup is product-later (AD-1)
- Meeting environment: Microsoft's M365 sandbox program is discontinued; scripted mock meetings are hosted on the corp production Teams tenant and acquired with the existing puller logged in as the user. Participants come best-effort from the puller's sidecar, with transcript-attribution derivation as the fallback per AD-1 (the SPEC was updated accordingly 2026-08-18 — the Graph-access assumption is gone)
- Ingestion trigger stays `POST /ingests` per drop (AD-14) — dropping files into the folder does not auto-ingest; no folder watcher exists or may be built; duplicate `sourceId` submissions are rejected as RFC 9457 conflicts (rerun, never a second Meeting)
- Disjoint table ownership: worker writes evidence + job tables; API writes user-declared data; artifacts and participants tables split by column between worker and API (AD-5)
- Participant dedup at intake: by AAD object ID when present, else by normalized display name — case-folded, parenthetical qualifiers stripped, `Last, First` reordered to `First Last`; merges write API-owned alias rows the worker resolves before any insert (AD-5)
- REST surface: `/ingests` `/jobs` `/meetings` `/moments` `/search` `/chat` `/artifacts` `/participants` `/media`; OpenAPI schema drives the generated TypeScript client; snake_case Python / camelCase JSON conversion at the API boundary (spine components, conventions)
- Time conventions: video offsets as integer milliseconds from recording start; wall-clock as ISO 8601 UTC; a moment carries both
- No broker/queue framework: jobs are Postgres rows claimed and advanced by the host worker (AD-11)
- Store-native auto-embedders stay disabled; the projections module computes embeddings via the `Embedder` port so `rebuild` is deterministic (AD-4)
- Eval ground-truth authoring rule: every slide/screen entry carries a unique distinctive `ocr_anchor`; thresholds provisional (anchor ≥ 0.8, dedup ≥ 0.9, fuzzy ≥ 0.75, recall@5) (eval-design §1, §6)
- A ready-made development corpus of ~25 real pulled meetings exists in `pull_transcript/` (vendor, project, Boomi, and related recordings + transcripts), usable for pipeline development before the scripted corp-tenant mock meetings are recorded; the puller's one-time backfill pass converts this archive into schema-valid drops, most of them transcript-only (view-only recordings with no downloadable video) (solution-design §4, AD-1)
- Eval subject selection: eval subjects are meetings with `corpus: scripted`, matched to their ground-truth manifests by `sourceId`; real pulled meetings carry `corpus: real` — ingested demo corpus, never eval subjects (AD-1, scope.md Corpus)
- Documented-only items (design docs, no implementation): citation timestamp-window check, action-item fuzzy set-match, eval cadence, full retrieval eval design (eval-strategy build plan)

### UX Design Requirements

UX-DR1: Ingestion flow UI: user pastes a Teams recap URL into the puller script; the web app shows ingestion progress and only exposes meeting viewing after the bundle is fully precomputed
UX-DR2: Moment view anatomy: still screenshot on top; transcript section below; right rail of extracted analytics (action items, ADRs, decisions, stories, requirements, bug fixes, change requests); full audio+video replay button
UX-DR3: Corpus-wide topic search flow: search → candidate meetings → drill into transcript with highlighted mentions → small inline video replays
UX-DR4: Search inputs: meeting name, topic, mention; plus free-form question asking (chat) about any decision
UX-DR5: Meeting drill-down displays the captured screenshot series: UI screens, slides, or participant headshots when nobody is presenting
UX-DR6: Two meeting archetypes drive different screenshot types and artifact sets: slide-deck presentations and UI demos
UX-DR7: Publishing gesture: on first visit to a moment the user chooses to push stories/tasks/decision docs out — per-moment approval, "AI proposes, humans approve"
UX-DR8: Outbound links to anything created are shown in context; MeetingMiner never shows or owns downstream status
UX-DR9: Extraction prompts are visible in the UI (with config-swap as the change mechanism)
UX-DR10: Decision records link back to their video moment; replay opens HTML5 video at the cited `startMs`; citations in chat render as replay links
UX-DR11: Transcript-only meetings render moment view and drill-down in a degraded mode — no screenshot and no inline replays, with a **transitional source deep link** to the original recap standing in for the replay affordance; transcript, highlighted mentions, and the right rail remain fully functional, and search/chat citations into these moments link to the transcript position. The deep link is transitional by design: when a recovered recording augments the meeting (FR32), real replay replaces it
UX-DR12: A moment from a YouTube meeting offers "Open on YouTube at this moment" (`sourceDeepLink` plus the moment offset) beside replay; replay stays the primary affordance
UX-DR13: Add-meeting is one flow with source tabs (YouTube URL, local files, Zoom export, Teams export), validation before any write, progress from launch through ingestion, and honest failure states naming the refusing rule
UX-DR14: Speaker naming shows each tag's talk share, three playable sample clips, and the tag-filtered transcript; names are assigned inline with existing-participant suggestions that are never auto-applied; unresolved is a first-class choice
UX-DR15: Model selection is available where it matters — the ask box and the settings page — and shows provider health beside each choice
UX-DR16: The front door is two views: Moments first (the most pressing items, ranked and explained), Threads second (a topic followed across meetings on a timeline); search, ask, and Add-meeting stay persistent chrome on both
UX-DR17: A moment card states its reason for ranking ("decision at 12:40 · 2 action items due next week · thread: retrieval split"), shows its screenshot, and replays in place; nothing decorative
UX-DR18: Threads zoom like Google Earth — continuous zoom and pan, level-of-detail thresholds with smooth transitions, detail revealed per level (thread bands → meetings → moments → evidence → replay), and nothing invented at any level

### FR Coverage Map

FR1: Epic 1 - Teams acquisition via puller CLI → source drop → POST /ingests
FR2: Epic 1 - Local recording ingestion through the same source-drop contract
FR3: Epic 1 - Drop validation against versioned JSON Schema at the single intake endpoint
FR4: Epic 1 - Worker pipeline stages probe→moments, checkpointed and idempotent (extract stage added in Epic 4)
FR5: Epic 1 - Full evidence bundle precomputed before first viewing
FR6: Epic 1 - Screen identity via OCR-text similarity; screen lineage across meetings
FR7: Epic 1 - Participant derivation from transcript attribution (human editing half delivered in Epic 2)
FR8: Epic 1 - Live ingestion job progress via SSE
FR9: Epic 1 - All domain objects persisted as Postgres rows with UUIDv7 from creation
FR10: Epic 1 - Evidence projected into Neo4j + Meilisearch at ingest-complete
FR11: Epic 3 - Graph traversal queries via parameterized Cypher templates (Rowan demo)
FR12: Epic 3 - Corpus search by meeting name, topic, mention across both stores
FR13: Epic 3 - NL questions: classify → deterministic retrieval → LLM synthesis with moment markers
FR14: Epic 3 - Deterministic citation validator; no answer leaves the API uncited
FR15: Epic 3 - Chat SSE streaming; replay links rendered from structured citations array
FR16: Epic 2 - Moment view: screenshot, transcript, right rail, replay button
FR17: Epic 2 - Meeting drill-down: screenshot series, highlighted mentions, inline replays
FR18: Epic 2 - Media streaming relative to MM_CONTENT_ROOT; HTML5 replay at startMs
FR19: Epic 4 - ADR + action-item extraction with visible, config-swappable prompts
FR20: Epic 4 - Artifacts start unpublished; one-way lifecycle column, API-only transitions
FR21: Epic 4 - Per-moment approval publishes to folder + local git with outbound links
FR22: Epic 4 - Published artifacts re-indexed into both stores; publish gate in projections
FR23: Epic 4 - Unpublished artifacts never appear in search or chat results
FR24: Epic 1 - rebuild CLI regenerates both stores from Postgres + config.yaml
FR25: Epic 2 - Series membership human-declared via API
FR26: Epic 5 - Eval harness over scripted YAML ground truth, tiered judging
FR27: Epic 5 - Deterministic BUILD checks 2.1–2.4, 2.10, 2.11
FR28: Epic 5 - Harness as API client; immutable run artifacts with config snapshot
FR29: Epic 5 - LLM judge harness (nice-to-have) + judge bake-off, pinned model id
FR30: Epic 5 - Written eval runbook executable without tribal knowledge
FR31: Epic 4 - (COULD) Morning Digest example email generator
FR32: A recording recovered after a meeting was ingested transcript-only **augments that meeting in place** — the drop declares which meeting it augments, the worker runs only the previously-skipped stages, and existing moments, citations, and published artifacts are preserved: augmentation attaches screenshots, alignment and replay to existing moments and may add new screen-derived moments, but never deletes, renumbers or re-keys one that already exists (CAP-1, CAP-4, AD-1)
FR33: Epic 6 - YouTube acquisition command: yt-dlp → write-once drop → POST /ingests, idempotent by video id
FR34: Epic 6 - Add-meeting from the web app; api launches the acquisition tool as a separate host process
FR35: Epic 6 - Zoom transcript dialect converted at acquisition into the trusted speaker-attributed format
FR36: Epic 7 - Real diarizer behind the Diarizer port; SPEAKER_NN tags on STT segments, surfaced per meeting
FR37: Epic 7 - Human speaker assignment as alias rows; align → moments → extract re-run with ids preserved
FR38: Epic 8 - Per-role binding catalog in config.yaml; persisted user selection resolved per request/job (AD-10 amended)
FR39: Epic 8 - Status reports provider key validity and active bindings; failing selection is a named error
FR40: Epic 10 - Moments view: deterministic, explained ranking of pressing moments
FR41: Epic 10 - Topic extraction anchored to moments, machine-derived; curation at thread level (FR42, story 10.2a); never a chat fact
FR42: Epic 10 - Threads across meetings; Topic/Thread graph nodes; thread traversal with level aggregates
FR43: Epic 10 - Semantic-zoom thread timeline, level-of-detail fetching

## Epic List

### Epic 1: Meeting Ingestion & Evidence Bundle
A user can ingest a Teams meeting (via the puller CLI — recording and/or transcript, transcript-only first-class) or a local recording and receive a fully precomputed evidence bundle — screens, screenshots, verified speaker-attributed transcript, moments, provenance — persisted in the database of record and projected into both retrieval stores, with live progress in the UI. Includes the puller's one-time backfill pass converting the ~25 already-pulled real meetings into drops. Story 1.1 establishes the monorepo scaffold per the architecture's source-tree seed (docker-compose infra, `make up`, uv/pnpm projects, `config.yaml` skeleton); no external starter template.
**FRs covered:** FR1, FR2, FR3, FR4 (stages probe→moments), FR5, FR6, FR7 (derivation), FR8, FR9, FR10, FR24, FR32

### Epic 2: Evidence Exploration & Replay
A user can open any moment (screenshot, transcript section, right rail, replay button), drill into a meeting's screenshot series with highlighted mentions and inline replays, and curate human-owned data (participant edits/merges, series membership). Verifying a claim takes seconds, not a meeting rewatch.
**FRs covered:** FR16, FR17, FR18, FR25 (+ human-editing half of FR7)

### Epic 3: Search & Cited Q&A
A user can search the corpus by meeting name, topic, or mention, and ask natural-language questions answered over both retrieval stores — every answer passing the deterministic citation validator, streaming via SSE, with citations rendering as replay links. Includes the "I already explained this to Rowan" traversal.
**FRs covered:** FR11, FR12, FR13, FR14, FR15

### Epic 4: Artifact Extraction & Human-Approved Publishing
The system extracts ADRs and action items (visible, config-swappable prompts) into the moment's right rail as unpublished drafts; the user approves per moment, publishing to a folder + local git, and published artifacts are re-indexed into both stores as searchable, citable knowledge. The publish gate guarantees unpublished AI output never surfaces in retrieval.
**FRs covered:** FR19, FR20, FR21, FR22, FR23, FR31 (COULD — last story, droppable)

### Epic 5: Eval Harness & Runbook
An operator can execute a complete eval run against scripted YAML ground truth using only the written runbook: deterministic checks (capture recall, over-capture guardrail, view classification, dedup quality, doc-index recall@5, publish-gate assert), optional LLM judge with bake-off, and immutable run artifacts. Sequencing note (NFR12): this epic completes before any demo-script work begins.
**FRs covered:** FR26, FR27, FR28, FR29, FR30

### Epic 6: Bring Any Meeting In
A user can add a meeting from a YouTube URL, a Zoom export, a Teams export, or loose files — from the web app — and watch it become evidence with live progress. Every source enters through the same write-once drop and the single intake door; the api launches acquisition as a separate process and never runs it in-process. Designed before it is built: story 6.1 is the UX design spec the UI stories of epics 6–8 and 10 consume.
**FRs covered:** FR33, FR34, FR35, UX-DR12, UX-DR13

### Epic 7: Know Who Spoke
A user can see who spoke when in any recording and put names to the voices without the system ever guessing: a real diarizer segments turns into anonymous tags, a human assigns names, and the assignment re-attributes the transcript, graph, and extractions while every moment id and citation survives.
**FRs covered:** FR36, FR37, UX-DR14

### Epic 8: Choose the Model
A user can pick which model answers and which extracts, from the catalog `config.yaml` allows, and see the provider's health beside the choice. Amends AD-10: the file declares the catalog and defaults; a persisted user selection picks among them; no selection is a fallback.
**FRs covered:** FR38, FR39, UX-DR15

### Epic 9: Cohort Close-out
The corpus holds the owner's chosen meetings, speakers are named on the featured ones, artifacts are published, and the five-minute walkthrough is recorded against real, unencumbered data.
**FRs covered:** none new — exercises FR33–FR39 end to end

### Epic 10: Moments & Threads
The front door: a Moments view that puts the most pressing evidence first with its reason stated, and a Threads view that follows a topic across meetings on a timeline you zoom into like Google Earth — bands, then meetings, then moments, then evidence, then replay. Needs topics as first-class, moment-anchored navigation in the database of record and the graph. Sequenced right after Epic 6 so the new corpus lands on the new front door.
**FRs covered:** FR40, FR41, FR42, FR43, UX-DR16, UX-DR17, UX-DR18

### Epic 11: Fast, Conflict-Free Test Suite
The operator's first priority: a routine test run takes seconds, the full run stays available under `make test`, and two builders in two worktrees can run every suite at once without waiting on a lock or breaking each other's stores. Lint and type tooling join the fast loop. Built before any other new work.
**FRs covered:** NFR19, NFR20; closes backlog B-1, B-4, B-14 and the `evals-run` isolation item

## Epic 1: Meeting Ingestion & Evidence Bundle

A user can ingest a Teams meeting (via the puller CLI — recording and/or transcript, transcript-only first-class) or a local recording and receive a fully precomputed evidence bundle — screens, screenshots, verified speaker-attributed transcript, moments, provenance — persisted in the database of record and projected into both retrieval stores, with live progress in the UI. Includes the puller's one-time backfill pass converting the already-pulled real archive into drops.

### Story 1.1: One-Command Development Environment

As a solo developer,
I want the monorepo scaffold and all infrastructure to start with one command,
So that every subsequent story builds on a running, consistently configured system.

**Acceptance Criteria:**

**Given** a fresh clone on the dev MacBook,
**When** I run `make up`,
**Then** docker-compose starts Postgres 18 (+pgvector), Neo4j Community 2026.07, and Meilisearch 1.53.x,
**And** the FastAPI api (:8000), worker, and Vite dev server (:5173) start as macOS host processes (AD-9).

**Given** the repository,
**When** inspected,
**Then** the source tree matches the architecture seed: `server/{domain,pipeline,adapters,projections,api,worker}`, `web/`, `puller/`, `evals/`, `infra/`, `docs/`.

**Given** the api or worker boots,
**When** configuration loads,
**Then** every adapter binding comes from the single versioned `config.yaml` and secrets come only from `.env` (AD-10).

**Given** the api is running,
**When** the OpenAPI schema is fetched,
**Then** the typed TypeScript client generates from it via @hey-api/openapi-ts.

### Story 1.2: Source-Drop Intake Endpoint

As a user with a local recording,
I want to submit a source-drop directory through a single validated intake endpoint,
So that any evidence source — local file today, Teams tomorrow — enters through one door. (FR2, FR3)

**Acceptance Criteria:**

**Given** `docs/source-drop.schema.json` exists (versioned, camelCase, explicit `schemaVersion`),
**When** a drop (recording and/or transcript — at least one — plus `metadata.json` with `sourceId`, `corpus`, `startedAt` + `startedAtPrecision`, and embedded `provenance`) is POSTed to `/ingests`,
**Then** the API validates it against the schema and inserts a job row, returning the job id (AD-1, AD-14).

**Given** an invalid or incomplete drop (including one with neither recording nor transcript),
**When** POSTed,
**Then** an RFC 9457 `problem+json` error is returned and no job row is created.

**Given** a `POST /ingests` whose `sourceId` already has a non-failed job,
**When** submitted,
**Then** it is rejected with an RFC 9457 conflict — re-processing an occurrence is a rerun of its existing job, never a second Meeting row (AD-14).

**Given** a drop containing files not named by the schema,
**When** validated,
**Then** those files are ignored at intake.

**Given** a queued job,
**When** I GET `/jobs/{id}`,
**Then** status and per-stage checkpoints are returned.

**Given** any accepted drop,
**When** ingestion later runs,
**Then** drop contents are read-only — never modified or deleted (AD-13).

### Story 1.3: Checkpointed Ingestion Worker (probe + frames)

As a user,
I want ingestion to run as restartable, checkpointed stages,
So that a failed ingest resumes rather than restarting from zero. (FR4 start, FR9 start)

**Acceptance Criteria:**

**Given** a queued job row,
**When** the worker claims it,
**Then** the first stage mints the Meeting row (UUIDv7, worker-owned tables per AD-5) linked to the job, and the API process never executes pipeline stages (AD-11).

**Given** the claimed job,
**When** `probe` and `frames` run,
**Then** media metadata is recorded and ffmpeg-sampled frames are written under `MM_CONTENT_ROOT` with only relative paths stored in the DB (AD-3).

**Given** a transcript-only drop (no recording),
**When** the worker advances the job,
**Then** the `probe → frames → ocr → screens → transcribe` stages record as skipped and the job proceeds to `align` (AD-1).

**Given** any completed stage,
**When** the job is re-run,
**Then** the stage idempotently overwrites only its own derived outputs for that meeting.

**Given** a stage failure,
**When** it occurs,
**Then** stage, error, and timestamp are recorded on the job row — never swallowed — and structured logs carry `job_id` + `stage` (NFR17, NFR18).

### Story 1.4: Screen Identification & Screenshots

As a user,
I want every distinct application screen or slide captured as a screenshot,
So that no shown screen is lost. (FR6)

**Acceptance Criteria:**

**Given** the `Ocr` port,
**When** bound in `config.yaml`,
**Then** Apple Vision runs as primary and Tesseract as swappable fallback with no feature-code change (AD-8).

**Given** sampled frames,
**When** the `ocr` and `screens` stages run,
**Then** OCR text is stored per frame and frames group into distinct screens by OCR-text similarity, biased to over-capture rather than loss (NFR8), using dwell (~20–30s) and bitrate-delta capture cues.

**Given** a screen already seen in a previous meeting,
**When** it appears again,
**Then** the Screen entity is upserted by identity key (lineage across meetings) and never deleted by a stage rerun.

**Given** each capture,
**When** classified,
**Then** its view type (slide | ui-screen | participant/gallery) is recorded — the eval harness later scores this accuracy.

### Story 1.5: Transcript Verification, Alignment & Participants

As a user,
I want a verified, speaker-attributed transcript segmented to video flow,
So that transcript evidence is trustworthy and attributable. (FR7 derivation, AD-13)

**Acceptance Criteria:**

**Given** the `Stt` and `Diarizer` ports,
**When** bound in config,
**Then** mlx-whisper is the STT default (parakeet-mlx swappable) and the diarizer defaults to noop (pyannote documented).

**Given** a provided transcript (Teams VTT or user file),
**When** the `transcribe` and `align` stages run,
**Then** the provided transcript is preserved verbatim and alignment writes new derived transcript rows with provenance to both the original and the STT output.

**Given** no provided transcript and the noop diarizer,
**When** alignment completes,
**Then** STT segments carry an `Unknown` speaker placeholder.

**Given** a drop that carries a participant graph, and separately one that omits it,
**When** intake completes,
**Then** participants are derived from transcript speaker attribution joined to the drop's participant graph when it carries one, and from speaker attribution alone when it does not (the original wording named only the omitting case while requiring `mail`-keyed identity, which only the carrying case can supply — story 1.13 closes the gap that conflation hid), deduplicated by normalized display name — case-folded, parenthetical qualifiers stripped, `Last, First` reordered to `First Last`, bare first names resolved only against that meeting's roster — with the identity key resolved through the alias table before any insert (AD-5). Identity keys on the participant graph's `mail` field, which is a real directory address present on 222 of 225 person-rows (98.7%) and resolved from the SharePoint user-profile service over the puller's existing session — **not** from Microsoft Graph, which remains a SPEC non-goal. Name normalization is the fallback for the rows that lack `mail`, not the primary key. Note that the tenant *login* is a separate field holding an employee number (`10001@corp.com`); it is not the same value as `mail` and joining the two silently misses. See `corpus-facts.md` §4.

**Given** a speaker label that resolves to no participant, or to more than one,
**When** participants are derived,
**Then** it is recorded as unresolved or ambiguous respectively and never merged into a resolved person — a wrong attribution is worse than an absent one, since who said it is half of no citation, no answer (SPEC Constraints). Externals marked unresolved in the participant graph are preserved as such, never dropped and never merged. Detect them by `unresolved: true` (with `org: "Unknown"`) — **not** by the `guest` field, which is `false` on all 225 rows corpus-wide, so code keying on `guest` finds nothing (`corpus-facts.md` §4).

**Given** a provided transcript,
**When** it is parsed,
**Then** both corpus lineages are handled: the Teams `[m:ss] Lastname, Firstname: text` source of record, and the legacy `<Name> | MM:SS` format that the primary capture-eval recordings carry. Timestamps are second-precision in both, so alignment anchors within ~±2s rather than a minute floor, and a transcript that switches from `MM:SS` to `HH:MM:SS` past the hour is parsed by field count. A `.vtt` export may be a speaker-less subtitle track and is not a substitute for the text transcript. See `_bmad-output/specs/spec-meetingminer/corpus-facts.md` §3-§4.

### Story 1.6: Moment Identification Completes the Bundle

As a user,
I want the system to identify moments aligning screens with discussion,
So that every piece of evidence anchors to a replayable point. (FR5, FR9)

**Acceptance Criteria:**

**Given** screenshots and derived transcript segments,
**When** the `moments` stage runs,
**Then** Moment rows are created linking evidencing screenshot and covered transcript segments, each carrying video-offset milliseconds and ISO 8601 UTC wall-clock time plus provenance.

**Given** a transcript-only meeting,
**When** the `moments` stage runs,
**Then** moments derive from transcript segmentation alone — `screenshotId` stays null (it is optional in the model) and, in place of a video replay link, the moment carries a transitional source deep link built from the drop's Stream URL, which is present on 100% of measured occurrences (UX-DR11, `corpus-facts.md` §4). The link is retired when a recovered recording augments the meeting (FR32) (AD-1).

**Given** all stages complete,
**When** the job finishes,
**Then** the job reaches `done` only after the full bundle (screens, screenshots, transcript, moments, timestamps, provenance) is precomputed (NFR11).

**Given** every domain object created during ingestion,
**When** written,
**Then** it exists as a Postgres row from creation with a Postgres-minted UUIDv7 (AD-2).

### Story 1.7: Evidence Projections & Rebuild CLI

As a user,
I want ingested evidence automatically projected into the graph and search stores,
So that retrieval sees every meeting — and the stores can always be regenerated. (FR10, FR24)

**Acceptance Criteria:**

**Given** ingest-complete,
**When** the worker triggers projection,
**Then** all Neo4j and Meilisearch writes execute inside `server/projections` — no other module writes to either store (AD-4).

**Given** Meilisearch documents,
**When** projected,
**Then** embeddings are computed via the `Embedder` port (1024-dim, local qwen3-embedding default) with store-native auto-embedders disabled.

**Given** a moment,
**When** projected,
**Then** its Postgres-minted UUID is carried verbatim into Neo4j nodes and Meilisearch documents (AD-6).

**Given** wiped or corrupted stores,
**When** the `rebuild` CLI runs,
**Then** both stores regenerate from Postgres + `config.yaml` alone, equivalent to the originals.

**Given** an artifact row not in `published` state,
**When** projection runs,
**Then** it is never projected (gate present from day one).

**Given** the projection stores,
**When** they are written,
**Then** the constraints already established against this corpus hold (`_bmad-output/specs/spec-meetingminer/retrieval-prior-art.md` §3): a single writer owns each store; embedding vectors are insert-only and never updated in place; the embedding model that wrote them is recorded so a model swap of a different width is caught rather than silently producing wrong neighbours; structural indexing succeeds with the model host unreachable, with embedding and answering resumable; and every meeting-scoped row carries its meeting id so re-indexing one occurrence is a delete-and-reinsert rather than a full rebuild.

**Given** a projected node or document,
**When** its identity is assigned,
**Then** it is keyed on the Postgres-minted UUID and never on a sequence number, which renumbers on re-index and orphans every edge pointing at it.

**Given** the full-text store,
**When** it is configured,
**Then** it is funded as a first-class half of retrieval rather than a fallback behind the vector store — searchable attributes and ranking rules are set deliberately, and domain synonyms (SFTP/FTP, PO/purchase order) and field boosts are configured. Measured on this corpus, **no embedding model beat BM25 alone when a query reuses the transcript's wording**, which is the dominant query shape, and embeddings win decisively only on paraphrased questions (`retrieval-prior-art.md` §7, SPEC Constraints).

**Given** transcript chunking for the projections,
**When** chunk size and overlap are chosen,
**Then** they are treated as a tuning lever with a recorded rationale, not an incidental constant: upstream measurement found passage boundaries a larger lever on retrieval quality than model choice, and a chunk boundary also bounds how precisely a screen can be tied to what was said (`retrieval-prior-art.md` §6-§7).

### Story 1.8: Teams Puller Emits Source Drops

As a lead architect,
I want to paste a Teams recap URL into the puller and have the meeting ingested end-to-end,
So that real Teams meetings flow into MeetingMiner without manual assembly. (FR1)

**Acceptance Criteria:**

**Given** the existing puller CLI running against the corp production Teams tenant (logged in as the user via its persisted browser session),
**When** it completes a pull,
**Then** its emit-drop step maps the native `<Title>/<M.D.YY>/` output into a schema-valid drop — recording and/or speaker-attributed transcript export, plus `metadata.json` with `sourceId`, `corpus`, `startedAt` (from the recording-filename timestamp when present, else meeting date at day precision), embedded provenance, and best-effort participants (omitted participants derive from transcript attribution downstream per Story 1.5) — assembled in a staging path, finalized atomically into the dedicated drops folder, and POSTed to `/ingests` (AD-1).

**Given** an occurrence whose drop was already finalized,
**When** a re-pull runs,
**Then** the finalized write-once drop is never overwritten (AD-1).

**Given** the already-pulled archive (~25 real meetings),
**When** the one-time backfill pass runs,
**Then** each occurrence converts into a schema-valid drop with `corpus: "real"` — most transcript-only — ready for demo-corpus ingestion (AD-1).

**Given** the puller and pipeline test suites,
**When** they run,
**Then** both independently validate against `docs/source-drop.schema.json`.

**Given** the black-box seam,
**When** reviewed,
**Then** the puller shares no server code, authenticates only via its persisted browser session (`.transcript-profile/`, no credential files), and no server component calls Microsoft Graph (AD-1).

### Story 1.9: Ingestion Progress in the UI

As a user,
I want to watch ingestion progress live and know when a meeting is ready,
So that I never open a half-processed meeting. (FR8, UX-DR1)

**Acceptance Criteria:**

**Given** an in-flight job,
**When** I view the web app,
**Then** meetings list with ingestion status and live per-stage progress rendered from SSE events `job.stage`, `job.done`, `job.error`.

**Given** a meeting whose job has not reached `done`,
**When** I try to open it,
**Then** it is not viewable — viewing is exposed only after full precompute.

**Given** a failed stage,
**When** I view the job,
**Then** the recorded stage error is displayed.

### Story 1.10: Development Environment Hardening

As a solo developer,
I want the story 1.1 scaffold hardened against the failure modes found in its review,
So that `make up`'s success output is accurate on any machine and later stories inherit a trustworthy environment.

Source: `_bmad-output/implementation-artifacts/review-story-1-1-2026-08-18.md` (finding numbers below refer to it). Schedule before story 1.3 — the package-namespace change (finding 19) becomes expensive once pipeline code accumulates.

**Acceptance Criteria:**

**Given** a fresh clone with Docker running,
**When** I run `make bootstrap && make up`,
**Then** the page at :5173 renders and calls `/health` with no manual `make client` step — the generated TS client is either committed or generated inside `up`, and `up` fails with a named error when the client is absent. (finding 1)

**Given** a stale pidfile whose PID was reused, a deleted `.logs/` while processes run, two concurrent `make up` invocations, or `make -j up`,
**When** `make up` and `make down` run,
**Then** no start is skipped or duplicated, host processes never start before the compose healthcheck gate, `make down` warns about running processes it holds no pidfile for, and startup readiness is verified by polling `/health`, :5173, and the `worker.startup` log event rather than a fixed sleep; a startup failure prints the failing process's last log lines. (findings 2–7)

**Given** a `.env` value containing quotes, an inline comment, an `export` prefix, or a leading `~`,
**When** read by the Python loader and by docker compose `--env-file`,
**Then** both resolve the identical value under one documented dialect, an empty exported process-env variable does not mask a `.env` value, and `MM_CONTENT_ROOT` is user-expanded. (findings 14–16)

**Given** the compose file,
**When** stores start,
**Then** all store ports bind `127.0.0.1` only, images are pinned to patch tags or digests, and every healthcheck uses a binary present in the pinned image. (findings 20–21)

**Given** the remaining guard fixes,
**When** applied,
**Then** `check-env` verifies readability, `make client` verifies the schema comes from the MeetingMiner api, `make api` preflights config before the reloader starts, `make down` still stops containers when `.env` interpolation fails, stop_proc patterns anchor to the actual launch commands, `make help` lists `test`, the config default path no longer derives from `__file__`, a missing `mm_content_root` produces a startup warning, and the web page aborts an in-flight health check before starting a new one. (findings 8–13, 17–18, 22)

**Given** the server packages,
**When** story 1.3 begins,
**Then** they are namespaced under `server/meetingminer/` so no top-level module named `config`, `api`, `pipeline`, etc. is installed. (finding 19)

**Given** `make test`,
**When** it runs,
**Then** it also builds the web app, and new tests cover: api fail-fast through the real uvicorn launcher, worker SIGTERM graceful shutdown, stop_proc kill/spare/no-duplicate behavior via decoy processes without Docker, and a conftest fixture isolating tests from exported `MM_CONFIG_PATH`/`MM_ENV_PATH`. (findings 23–27)

### Story 1.11: Screen Capture Retune Against Measured Baselines

As a user,
I want screen capture tuned against measured recordings rather than assumed thresholds,
So that what gets captured is the settled screens that carry requirements, and the over-capture guardrail holds. (FR6, NFR8)

Source: `_bmad-output/specs/spec-meetingminer/capture-measurements.md` (section numbers below refer to it). Story 1.4 shipped before these measurements existed. Schedule before story 1.6 — moment identification consumes these screenshots and inherits their noise.

**Acceptance Criteria:**

**Given** a recording whose frame composites a shared screen with a participant webcam column,
**When** the `screens` stage runs,
**Then** the share region is detected once per recording and every change comparison is made on the cropped region — no whole-frame proxy, encoded byte size included, decides a capture. Uncropped, the change signal has no usable dynamic range, and its noise floor grows with time since the last capture rather than staying constant. (§2)

**Given** a capture cue has fired,
**When** the stage selects which frame to keep,
**Then** it emits the first subsequent frame at which the region has stopped changing, subject to a configured timeout — the cue decides *when* a change happened, the settle rule decides *which* frame to keep. Emitting at the cue captures loading spinners and blank pages, because a blank mid-load page is the largest possible difference from a populated one. (§3)

**Given** a captured frame,
**When** its view type is classified,
**Then** camera and gallery video are rejected on the brightness and saturation pair before any text-geometry rule is applied, and gallery rendered as initial-avatar tiles is recorded as a known unresolved case rather than silently classified as a screen. (§4)

**Given** a frame that may be a loading or transition state,
**When** it is classified,
**Then** it is tagged as a likely transition and never dropped — loading pages are not separable from real UI by any single threshold, and NFR8's bias is over-capture, never loss. (§4)

**Given** the 57-minute meeting that produced 188 captures under story 1.4 (3.3/min, failing `eval-design.md` §2.2 by 3.3x),
**When** it is re-run after the retune,
**Then** the capture count is under one per minute of meeting duration, and a human review of the removed captures confirms they were transitions, gallery frames, or duplicates rather than settled UI screens. Capture recall has no independent denominator until the scripted fixtures of story 5.1 exist (§6), so this review is the available check and its result is recorded.

**Given** every threshold this story introduces or changes,
**When** capture density is retuned,
**Then** it arrives from `config.yaml` and never as a code constant (AD-10), so a later retune against the scripted corpus is an edit, not a code change.

### Story 1.12: Late-Recording Augmentation

As a user,
I want a recording recovered after the fact to enrich the meeting I already ingested,
So that evidence improves over time without invalidating anything already cited or published. (FR32)

**Context:** Teams recordings land in the personal OneDrive of whoever hit record, and recovering them across the organisation is active work in progress. Late-arriving video is therefore the expected path for most of the transcript-only corpus, not an edge case (`corpus-facts.md` §1).

**Acceptance Criteria:**

**Given** a meeting already ingested transcript-only,
**When** a drop arrives carrying a recording and declaring the meeting it augments,
**Then** intake accepts it rather than returning the `sourceId` conflict (FR3), and the finalized earlier drop is left untouched — write-once applies to a drop, not to a meeting (AD-1).

**Given** an accepted augmenting drop,
**When** the worker runs,
**Then** it executes only the stages that were skipped — probe → frames → ocr → screens → transcribe — plus `align`, and does not re-run stages whose outputs already exist.

**Given** augmentation completes,
**When** existing moments are examined,
**Then** every moment that existed beforehand still exists with the same identity, now carrying its screenshot, replay window and alignment where the video supports it; no pre-existing moment is deleted, renumbered or re-keyed (SPEC Constraints).

**Given** screens found in the recovered recording that no transcript-derived moment covers,
**When** `moments` runs,
**Then** new screen-derived moments may be added alongside the existing ones.

**Given** citations and published artifacts created before augmentation,
**When** augmentation completes,
**Then** every one still resolves to a valid moment — a citation must not break at the moment its evidence improves.

**Given** a transcript-only moment carrying a source deep link,
**When** augmentation supplies real video for it,
**Then** the moment renders a true replay button and the deep link is retired (UX-DR11).

**Given** augmentation completes,
**When** projections run,
**Then** the affected meeting is re-projected by meeting id as a delete-and-reinsert rather than a full store rebuild (Story 1.7).

### Story 1.13: Drops Carry the Participant Graph

As a lead architect,
I want the puller's resolved participant graph to reach the drop,
So that people are identified by their directory address instead of by how their name was typed. (FR1, FR7, FR32)

**Context:** Story 1.8's AC already requires emit-drop to write best-effort participants into `metadata.json`; `emit-drop.js` omits the key on the reasoning that transcript speaker attribution is "better than anything the puller holds". The 2026-08-18 measurement falsifies that: `org chart.json` carries `mail` on 222/225 rows and a reporting chain on 208, while transcript attribution carries display names only. The server half is already built and unused — `align` reads `metadata.participants`, keys identity on `mail`, and stores title, department and reporting chain (`corpus-facts.md` §4, SPEC Constraints).

**Acceptance Criteria:**

**Given** an occurrence whose `org chart.json` the puller resolved,
**When** emit-drop runs,
**Then** `metadata.json` carries a `participants` array mapped from that graph — `displayName` plus `mail`, title, department and reporting chain where the row has them — and the key is omitted only when no graph was resolved (Story 1.8 AC, AD-1).

**Given** a drop carrying participants,
**When** it ingests,
**Then** participants dedupe across meetings by `mail` and fall back to normalized display name only where the graph supplies none; an unresolved external is detected by `unresolved: true` with `org: "Unknown"`, never by the `guest` field, which is `false` corpus-wide (Story 1.5).

**Given** a drop that brings evidence the meeting lacks but carries no recording,
**When** it is POSTed to `/ingests`,
**Then** intake accepts it. **This does not work today and is a prerequisite, not a detail:** a declared augmentation is refused unless the drop carries `recording.mp4` (`api/ingests.py:303`) and unless the target has no recording yet, while the plain re-queue path applies only when every job for that `sourceId` has failed (`ingests.py:532`). A participants-only drop is therefore refused for an already-ingested transcript-only meeting *and* for one that already has its recording. Story 1.12 built the door for recovered video specifically; this widens it to any evidence the meeting lacks, keeping one intake door rather than adding a participant-import bypass (AD-14).

**Given** the 28 occurrences whose drops were already finalized without participants,
**When** the puller is asked to bring them up to contract,
**Then** it emits a new drop for an occurrence it has already emitted rather than reporting `exists` — a finalized drop is still never overwritten (AD-1) — and the re-ingested meetings acquire mail-keyed identity. The discriminator added to the drop directory name `<date>-<title-slug>-<sha1(sourceId)[0:8]>` must keep **emit order recoverable from the drops folder alone**, because reconstruction replays a meeting's drops in emit order: a content hash or random suffix satisfies write-once and still breaks recovery.

**Given** that same re-emit path,
**When** a recovered recording is available for a meeting ingested transcript-only,
**Then** the puller can emit the `schemaVersion: 2` augmenting drop story 1.12's intake already accepts, closing FR32 end-to-end rather than server-side only (`deferred-work.md`).

**Given** participants already merged through the API before this change,
**When** re-ingest runs,
**Then** the alias table still resolves them, so a merge performed against name-keyed rows survives the move to mail-keyed identity (AD-5).


## Epic 2: Evidence Exploration & Replay

A user can open any moment (screenshot, transcript section, right rail, replay button), drill into a meeting's screenshot series with highlighted mentions and inline replays, and curate human-owned data (participant edits/merges, series membership). Verifying a claim takes seconds, not a meeting rewatch.

### Story 2.1: Media Streaming & Replay Foundation

As a user,
I want video and screenshots served by the API with seekable replay,
So that any piece of evidence can be viewed and replayed in the browser. (FR18)

**Acceptance Criteria:**

**Given** media files under `MM_CONTENT_ROOT`,
**When** the web app requests `/media` paths,
**Then** the API streams them by resolving the DB's relative paths against the configured root — absolute paths never leave the server (AD-3).

**Given** a video stream request with an HTTP Range header,
**When** served,
**Then** partial content is returned so HTML5 video can seek directly to any `startMs`.

**Given** a moment's timestamps,
**When** replay is invoked with its `startMs`,
**Then** the HTML5 player opens positioned at that offset (UX-DR10).

**Given** a media path that doesn't resolve under the content root,
**When** requested,
**Then** an RFC 9457 error is returned and path traversal outside the root is impossible.

### Story 2.1a: Evidence Paths Anchored to Configured Roots

As a maintainer,
I want every stored evidence path recorded relative to one of the two configured roots,
So that relocating the drops or content folder is an environment change, not a data migration. (AD-3, storage-layout.md)

**Acceptance Criteria:**

**Given** a drop arriving at intake,
**When** the api and worker start,
**Then** `MM_DROPS_ROOT` is a gated configured root and a drop outside it is refused at the door with a problem naming both paths.

**Given** an ingested job, transcript source, or recording,
**When** its path is persisted,
**Then** `job.drop_relative_path`, `transcript_source.drop_relative_path` (widened to `<drop-dir>/<filename>`), and `meeting_media.drop_relative_path` hold root-relative values, and migration 0008 CHECKs that no stored path is absolute or carries a `..` segment.

**Given** the recording — the one arriving artifact with no row of its own,
**When** it is served,
**Then** its path comes from a database row carrying `sha256` and byte size, never from a stored value plus a hardcoded filename constant.

**Given** rows written before this story,
**When** `make backfill-drop-paths` runs,
**Then** absolute paths convert to root-relative ones, and the nullable `job.drop_path` column survives only until every deployment has run it.

### Story 2.1b: Bring-Your-Own-Recording Drops

As a user,
I want to mint a source drop from a loose local video file,
So that recordings the puller never produced — recovered recordings and the NDA demo assets — can enter the corpus through the same write-once door. (CAP-1)

**Acceptance Criteria:**

**Given** a local video file,
**When** I mint a drop from it,
**Then** a write-once drop directory is produced with a `metadata.json` sidecar carrying source id, corpus, meeting wall clock and precision — the same contract `docs/source-drop.schema.json` pins for puller-emitted drops.

**Given** a minted drop,
**When** it is copied into place,
**Then** the copy is verified by digest before the drop is finalized, and an existing drop is never overwritten.

**Given** a minted drop,
**When** it is posted to intake,
**Then** it ingests through the unchanged intake path with no tool-specific branch.

### Story 2.2: Moment View

As a lead architect,
I want to open any moment and see its full evidence context in one view,
So that I can verify a claim against its source in seconds, not a meeting rewatch. (FR16, NFR14, UX-DR2)

**Acceptance Criteria:**

**Given** an ingested meeting,
**When** I open one of its moments,
**Then** the view shows the still screenshot on top, the covering transcript section below, and a right rail of extracted analytics (action items, ADRs, decisions, stories, requirements, bug fixes, change requests).

**Given** the right rail,
**When** artifacts exist for the moment (any lifecycle state),
**Then** they are read from Postgres via the API — unpublished artifacts appear here and only here;
**And** when none exist yet, the rail shows an explicit empty state (functional before Epic 4 delivers extraction).

**Given** the moment view,
**When** I press the replay button,
**Then** full audio+video replay opens at the moment's `startMs` (Story 2.1 player).

**Given** a moment from a transcript-only meeting,
**When** I open it,
**Then** the view renders in degraded mode — no screenshot, and a transitional source deep link to the original recap in place of the replay button — with transcript and right rail fully functional (UX-DR11).

**Given** the API,
**When** `/meetings/{id}/moments` and `/moments/{id}` are fetched,
**Then** payloads are camelCase and served through the generated TypeScript client.

### Story 2.3: Meeting Drill-Down with Screenshot Series

As a lead architect,
I want a meeting's captured screenshot series with mentions highlighted and inline replays,
So that I can scan a whole meeting's visual flow and jump to any point. (FR17, UX-DR5)

**Acceptance Criteria:**

**Given** an ingested meeting,
**When** I open its drill-down view,
**Then** the captured screenshot series displays in timeline order — UI screens, slides, or participant headshots when nobody was presenting — each labeled with its view classification and timestamp.

**Given** the meeting transcript,
**When** displayed in drill-down,
**Then** search-term or topic mentions are highlighted and each transcript region links to its moment.

**Given** any screenshot or transcript region,
**When** I click its replay affordance,
**Then** a small inline video replay plays from that offset without leaving the page (UX-DR3 inline-replay pattern).

**Given** a transcript-only meeting,
**When** I open its drill-down,
**Then** the view renders without a screenshot series or inline replays — transcript with highlighted mentions and moment links remain, and a single source deep link to the original recap is offered at meeting level (UX-DR11).

**Given** a meeting whose evidence stages have not settled,
**When** its detail route is requested,
**Then** the API refuses it server-side rather than leaving the disabled Open button as the only gate — `evidence_complete` is computed and returned as `viewable` today, but no route existed to enforce it when story 1.9 shipped (`deferred-work.md`).

**Given** a meeting being augmented by a recovered recording,
**When** the same route is requested,
**Then** the empty state distinguishes an augmenting run from a never-ingested meeting. `viewable` legitimately goes false mid-augmentation — `align` deletes the meeting's transcript segments before `moments` re-runs, so its moments briefly exist over zero transcript coverage — while the meeting keeps its identity, citations and projections throughout. Derivable from `job.status` plus `job_stage` with no schema change; do not key the empty state on `viewable` alone (architecture memlog, post-merge gap 2).

### Story 2.4: Participant Curation

As a user,
I want to correct participant names and merge duplicate participants,
So that speaker attribution and the participant graph stay accurate. (FR7 human half)

**Acceptance Criteria:**

**Given** participants created at intake,
**When** I edit a display name via `/participants`,
**Then** the change persists in the API-owned human-curated columns — worker-owned intake columns are untouched (AD-5).

**Given** two participant records that are the same person,
**When** I merge them via the API,
**Then** transcript segments, meeting attendance, and graph edges resolve to the surviving participant, and an API-owned alias row (`alias_key → surviving participant id`) is written (AD-5).

**Given** a completed merge,
**When** a meeting is re-ingested or a stage reruns,
**Then** the worker resolves identity keys through the alias table before any insert, so the merge survives — no duplicate participant reappears (AD-5).

**Given** an `Unknown` speaker placeholder from a transcript-less ingest,
**When** I rename it,
**Then** its transcript segments show the corrected attribution everywhere the participant appears.

### Story 2.5: Series, Project & Product Assignment

As a user,
I want to declare series membership and assign meetings to projects and products,
So that the domain graph reflects human-known structure that is never guessed. (FR25)

**Acceptance Criteria:**

**Given** an ingested meeting,
**When** I assign it to a Series via the API,
**Then** membership is stored as human-declared — the system never infers series membership.

**Given** projects and products,
**When** I create them and assign meetings to a project (and projects to a product),
**Then** the PRODUCT → PROJECT → MEETING hierarchy persists per the ERD, written only by the API (AD-5 user-declared data).

**Given** these assignments,
**When** evidence is next projected (or `rebuild` runs),
**Then** series/project/product relationships appear in the graph projection for later traversal.

### Story 2.6: Source-Drop Schema Reloaded on Change

As an operator,
I want the api to notice when `docs/source-drop.schema.json` changes,
So that a schema update reaches a running api instead of presenting as bad drops. (defect found in operation 2026-08-19)

**Acceptance Criteria:**

**Given** a running api,
**When** `POST /ingests` is called,
**Then** the schema file's identity (path, mtime, size) is re-stat'ed and the validator swapped on change — a `stat()` per request, never a re-parse of an unchanged file.

**Given** a schema file that has become unreadable or invalid,
**When** a drop is posted,
**Then** the request fails closed as a 500 problem with slug `drop-schema-unreadable` naming the schema file — never as `422 invalid-drop`, because the drop is not the fault — and recovery needs no restart.

**Given** any load or reload of the schema,
**When** it completes,
**Then** one structured stdout event names the loaded path, `$id`, mtime, and size, so which copy got loaded is observable (NFR17).

**Given** startup,
**When** the schema is missing or invalid,
**Then** the existing fail-fast behavior is unchanged: a named error, no traceback, exit 1.

### Story 2.7: Parallel-Safe Store-Backed Tests

As an agent working this repository alongside others,
I want store-backed server suites to run concurrently without corrupting each other,
So that two worktrees can advance two stories at once. (dispatch rule, 2026-08-19)

**Acceptance Criteria:**

**Given** two pytest runs starting at once,
**When** each needs Postgres,
**Then** each owns a per-run database from creation through teardown, and `make test-db-prune` takes the same candidate lock so it never drops a database another run owns.

**Given** Neo4j Community serving one database and AD-4 fixing the Meilisearch index names,
**When** projection tests run concurrently,
**Then** they queue on a bounded cross-worktree file lock that reports the lock path and holder metadata, rather than pretending to be isolated.

**Given** the lock,
**When** a holder dies or a wait exceeds its bound,
**Then** the wait ends with a named failure rather than hanging, and the lock file is never truncated by a competing open.

**Given** `make evals-run`,
**When** it is invoked,
**Then** it remains serial — it reads the shared corpus and writes an immutable run folder.

### Story 2.8: Auto-Discovered Route Registration

As an agent working this repository alongside others,
I want adding an endpoint or a screen to require no edit to a shared registration file,
So that unrelated stories stop conflicting over the one line each had to add. (dispatch rule, 2026-08-19; the last two entries in the integrate skill's conflict playbook)

**Acceptance Criteria:**

**Given** the eight api modules that expose a router,
**When** the api starts,
**Then** each is registered by package discovery, and the route table matches the pre-change table in path, method and match order.

**Given** a new endpoint module dropped into `meetingminer/api/`,
**When** the api starts,
**Then** its routes serve without any edit to `api/main.py`.

**Given** `GET /jobs/events`,
**When** it is requested,
**Then** it reaches the SSE stream rather than `/jobs/{job_id}` — the registration-order contract asserted by a test rather than by a comment.

**Given** a new screen shipped as a route file beside its component,
**When** the web app builds,
**Then** the screen mounts at its path without any edit to `App.tsx`.

**Given** a moment opened from a search hit,
**When** Back is pressed,
**Then** the query and its results are still rendered — the home view is hidden while a child route is open, never unmounted.

## Epic 3: Search & Cited Q&A

A user can search the corpus by meeting name, topic, or mention, and ask natural-language questions answered over both retrieval stores — every answer passing the deterministic citation validator, streaming via SSE, with citations rendering as replay links. Includes the "I already explained this to Rowan" traversal.

### Story 3.1: Corpus Search

As a lead architect,
I want to search the corpus by meeting name, topic, or mention,
So that I can locate the meetings and moments where something was discussed. (FR12, UX-DR3, UX-DR4)

**Acceptance Criteria:**

**Given** ingested meetings projected into Meilisearch,
**When** I query `/search` by meeting name, topic, or mention,
**Then** typo-tolerant, highlighted results return from the full-text index over transcripts and OCR text, using hybrid keyword+vector ranking.

**Given** any search result,
**When** returned,
**Then** it exposes at least one resolvable `momentId` (AD-15) and links into meeting drill-down with the matched terms highlighted.

**Given** the search flow,
**When** I follow a result,
**Then** the path is search → candidate meetings → transcript with highlighted mentions → inline replay (UX-DR3).

**Given** artifacts in any non-`published` state,
**When** any search runs,
**Then** they never appear in results (NFR7).

### Story 3.2: Graph Traversal Templates

As a lead architect,
I want structural questions answered by deterministic graph traversals,
So that queries like "show every discussion of this screen over time" are exact, testable, and citable. (FR11)

**Acceptance Criteria:**

**Given** the Neo4j evidence projection,
**When** the screen-history template runs for a screen,
**Then** it returns every meeting and moment where that screen appeared, in time order, via a hand-written parameterized Cypher template (AD-7).

**Given** the participants → meetings → topics → moments template,
**When** run for a participant and topic (the "I already explained this to Rowan" query),
**Then** it returns the moments where that participant was present when the topic was discussed.

**Given** every traversal template,
**When** executed,
**Then** results carry Postgres-minted moment UUIDs verbatim, and each template has unit tests against known fixture data.

**Given** the template registry,
**When** reviewed,
**Then** no library auto-extracts or owns graph structure — templates are the only graph retrieval path.

### Story 3.3: Cited Q&A with Deterministic Citation Gate

As a lead architect,
I want to ask natural-language questions and get answers that cannot exist without citations,
So that every claim traces to replayable evidence — enforced in code, not prompts. (FR13, FR14, NFR4)

**Acceptance Criteria:**

**Given** a question POSTed to `/chat`,
**When** the orchestrator handles it,
**Then** it classifies the question to a traversal template, retrieves deterministically from Neo4j and Meilisearch, and synthesizes the answer via the `Llm(chat)` port (config-bound, `claude-sonnet-5` default with Ollama fallback) emitting inline `[[moment:<uuid>]]` markers.

**Given** a draft answer,
**When** the citation validator runs,
**Then** every marker resolves against Postgres and converts to a structured citations array (`momentId`, `meetingId`, `startMs`, `endMs`, optional `screenshotId`) (AD-15).

**Given** an answer with any uncited factual claim or unresolvable marker,
**When** validated,
**Then** it is rejected — no answer leaves the API (AD-6).

**Given** retrieval inputs,
**When** assembled,
**Then** only evidence and `published` artifacts are retrievable; unpublished artifacts never reach synthesis (NFR7).

### Story 3.4: Chat UI with Streaming & Replay Citations

As a lead architect,
I want a chat interface that streams answers and renders citations as replay links,
So that I can interrogate the corpus and jump straight to the evidence. (FR15, UX-DR10)

**Acceptance Criteria:**

**Given** a validated answer,
**When** streamed to the web app,
**Then** it arrives as SSE events `chat.token`, `chat.citations`, `chat.done` (pinned names).

**Given** the citations array,
**When** rendered,
**Then** each citation displays as a replay link opening the video at its `startMs` — or, for a moment from a transcript-only meeting, as a link to its moment view at the transcript position (UX-DR11) — the web app never parses inline markers (AD-15).

**Given** a rejected answer,
**When** the API declines to respond,
**Then** the UI shows an explicit "no citable answer" state rather than an uncited reply.

**Given** a citation link,
**When** followed,
**Then** it navigates to the moment view (Story 2.2) with replay available.

## Epic 4: Artifact Extraction & Human-Approved Publishing

The system extracts ADRs and action items (visible, config-swappable prompts) into the moment's right rail as unpublished drafts; the user approves per moment, publishing to a folder + local git, and published artifacts are re-indexed into both stores as searchable, citable knowledge. The publish gate guarantees unpublished AI output never surfaces in retrieval.

### Story 4.1: Artifact Extraction Pipeline Stage

As a lead architect,
I want ADRs and action items extracted automatically from each moment,
So that meeting outcomes are proposed for me instead of mined by hand. (FR19, FR20 start)

**Acceptance Criteria:**

**Given** the ingest pipeline,
**When** the `extract` stage is added after `moments`,
**Then** it runs through the `Llm(extraction)` port (config-bound, `claude-sonnet-5` default, Ollama fallback) using baked-in prompts, and remains checkpointed and idempotent like every stage (AD-11).

**Given** extraction output for a moment,
**When** persisted,
**Then** artifact rows are inserted by the worker in `extracted` (unpublished) state, linked to their yielding moment — the worker owns extraction-content columns, the API owns the lifecycle column (AD-5).

**Given** both meeting archetypes (slide-deck and UI demo),
**When** extraction runs,
**Then** the appropriate artifact set is produced for each (UX-DR6).

**Given** newly extracted artifacts,
**When** I open their moment,
**Then** they appear in the right rail (Story 2.2) — and nowhere else: not in search, not in chat (NFR7).

**Given** any extraction output,
**When** written,
**Then** it touches only artifact rows — never evidence records (NFR5).

### Story 4.1a: Whole-Transcript Extraction

As a lead architect,
I want extraction to run over the whole meeting transcript rather than per moment,
So that decisions emerging across minutes of discussion are extracted at the granularity they exist at. (CAP-5, user decision 2026-08-20)

**Acceptance Criteria:**

**Given** a drop that already carries the puller summariser's extraction documents,
**When** the extract stage runs,
**Then** the documents are parsed and no model call is made, and the adopted files carry the same provenance as every other arrived file — per-file row, `sha256`, drops root.

**Given** a transcript arriving without extraction documents,
**When** the extract stage runs,
**Then** the whole timestamped transcript goes to the configured local model with prompts adapted from the proven `pull_transcript` pair, and the output is read by the same strict parser that reads both known summariser layouts.

**Given** an extracted artifact,
**When** it is persisted,
**Then** its transcript timestamp anchor resolves deterministically to its containing moment, and a timestamp resolving to no moment is a named error rather than a dropped artifact.

**Given** input that plainly contains extractable content,
**When** the parser returns zero artifacts,
**Then** that is reported as a failure signal, not as success (no silent zero).

**Given** configuration,
**When** the extraction role is resolved,
**Then** it defaults to a local model; a paid model requires fresh, explicit per-run authorization.

### Story 4.2: Visible, Swappable Extraction Prompts

As a user,
I want to see exactly which prompts produced the extractions and swap them via configuration,
So that the AI's contribution is transparent and tunable without code changes. (FR19, UX-DR9)

**Acceptance Criteria:**

**Given** the baked-in extraction prompts,
**When** I view the extraction area in the UI,
**Then** the full active prompt text for each artifact type is visible.

**Given** `config.yaml`,
**When** a prompt (or the extraction model binding) is changed there,
**Then** subsequent extractions use the new value with no code change (AD-8, AD-10).

**Given** an extracted artifact,
**When** inspected,
**Then** it records which prompt/model configuration produced it (provenance for the eval config snapshot).

### Story 4.3: Per-Moment Approval & Publishing

As a lead architect,
I want to approve artifacts per moment and have them published to a folder and local git,
So that nothing leaves the system without my explicit gesture — AI proposes, I approve. (FR20, FR21, UX-DR7, UX-DR8)

**Acceptance Criteria:**

**Given** unpublished artifacts in a moment's right rail,
**When** I visit the moment,
**Then** I'm offered the per-moment approval gesture to publish its artifacts.

**Given** an approval,
**When** processed via the API,
**Then** the lifecycle column advances one-way `extracted → approved → published` — transitions are API-only, and no unpublish path exists (AD-4, AD-5).

**Given** a published artifact,
**When** publishing completes,
**Then** it is exported to the publish folder, and ADRs are additionally committed to the plain local git repository.

**Given** published items,
**When** I view the moment,
**Then** outbound links to what was created are shown in context — and MeetingMiner never shows or owns downstream status (NFR9, UX-DR8).

**Given** an artifact I do not approve,
**When** left alone,
**Then** it remains in `extracted` state indefinitely, visible only in its moment's right rail.

### Story 4.4: Published Artifacts Become Citable Knowledge

As a lead architect,
I want published artifacts re-indexed into both retrieval stores,
So that yesterday's approved ADR is tomorrow's search hit — with its own evidence trail. (FR22, FR23)

**Acceptance Criteria:**

**Given** an artifact transitioning to `published`,
**When** the API triggers projection,
**Then** it is indexed into both Neo4j and Meilisearch through the projections module, carrying citations back to its source moment (AD-4).

**Given** the publish gate inside the projections module,
**When** any artifact projection is attempted,
**Then** it refuses any artifact whose Postgres state is not `published` — regardless of caller.

**Given** a published ADR,
**When** I search or ask a question that it answers,
**Then** it appears as a result/citation whose evidence trail replays the original moment (CAP-9 success signal).

**Given** the `rebuild` CLI,
**When** run after publishing,
**Then** published artifacts are re-projected and unpublished ones remain excluded.

### Story 4.5: Morning Digest Example Email (COULD — droppable)

As a stakeholder,
I want one example Morning Digest email generated from published artifacts,
So that the digest concept is demonstrated without building delivery. (FR31)

**Acceptance Criteria:**

**Given** published artifacts in Postgres,
**When** the digest generator runs,
**Then** it writes a single example email file summarizing meetings and assigned action items — reading Postgres only.

**Given** the capstone scope,
**When** reviewed,
**Then** there is no delivery mechanism, no scheduler, and no architectural footprint beyond the generator (scope.md Cluster F).

## Epic 5: Eval Harness & Runbook

An operator can execute a complete eval run against scripted YAML ground truth using only the written runbook: deterministic checks (capture recall, over-capture guardrail, view classification, dedup quality, doc-index recall@5, publish-gate assert), optional LLM judge with bake-off, and immutable run artifacts. Sequencing note (NFR12): this epic completes before any demo-script work begins.

### Story 5.1: Ground-Truth Schema & Scripted Fixtures

As an eval operator,
I want machine-readable YAML meeting scripts that declare everything the pipeline should detect,
So that every expected artifact is known before ingestion runs. (FR26)

**Acceptance Criteria:**

**Given** the ground-truth schema (eval-design §1),
**When** YAML files are placed under `evals/ground-truth/`,
**Then** they validate against the schema — meeting metadata, archetype, slides/screens with `ocr_anchor`, participant segments, planted action items/decisions/phrases with timestamps, and `qa` entries.

**Given** the authoring rule,
**When** a fixture is validated,
**Then** every slide/screen entry carries a unique, distinctive `ocr_anchor` — validation fails on missing or duplicate anchors.

**Given** a fixture,
**When** the expected screenshot count is computed,
**Then** it equals slides (or screens) + participant segments — the recall denominator.

**Given** at least one fixture per archetype (slide-deck, ui-demo),
**When** the suite loads,
**Then** both parse and validate, ready for check execution.

**Given** the ingested corpus,
**When** the suite selects eval subjects,
**Then** only meetings with `corpus: "scripted"` are matched to ground-truth manifests — by `sourceId` — and `corpus: "real"` meetings are never eval subjects (AD-1, scope.md Corpus).

### Story 5.2: Deterministic Capture Checks with Immutable Run Artifacts

As an eval operator,
I want the tier-1 capture checks to run as plain pytest tests writing immutable run reports,
So that the primary quality claims are machine-verified and auditable. (FR27 checks 2.1–2.4, FR28)

**Acceptance Criteria:**

**Given** an ingested scripted meeting,
**When** capture recall (2.1) runs,
**Then** each captured PNG's OCR text is matched against manifest `ocr_anchor`s (normalized, fuzzy token-set ≥ 0.8) and the run fails on any recall below 100% (NFR1).

**Given** the same meeting,
**When** the over-capture guardrail (2.2), view classification (2.3), and dedup quality candidates (2.4) run,
**Then** captures failing count > ceil(duration_minutes) fail the run (NFR2), classification accuracy is reported against manifest-implied labels, and sequential-capture OCR similarity > 0.9 pairs are listed for human judging.

**Given** any check execution,
**When** it interacts with the system,
**Then** it mutates only through the public API (`POST /ingests`) and asserts through API reads and read-only store queries (AD-16).

**Given** a run,
**When** it starts,
**Then** a run folder `evals/runs/<run-id>/` is created containing `deterministic-report.yaml` and the full resolved `config.yaml` snapshot; the folder is immutable after verdict.

### Story 5.3: Retrieval & Publish-Gate Checks

As an eval operator,
I want deterministic checks defending the retrieval index and the publish gate,
So that the system's two hardest promises are machine-verified. (FR27 checks 2.10–2.11)

**Acceptance Criteria:**

**Given** planted phrases in a scripted meeting,
**When** doc-index search recall (2.10) runs,
**Then** each phrase queried against Meilisearch must return a moment from the containing meeting in the top 5 — recall@5 = 1.0 or the run fails.

**Given** a scripted artifact,
**When** the publish-gate projection check (2.11) runs,
**Then** it asserts the artifact appears in NEITHER store before approval, approves it via the public API, and asserts it appears in BOTH stores with citations resolving to its source moment — any violation fails the run.

**Given** both checks,
**When** executed,
**Then** results append to the run's `deterministic-report.yaml` under the same immutability rule.

### Story 5.4: LLM Judge Harness & Bake-Off (nice-to-have)

As an eval operator,
I want an LLM judge scored against human gold verdicts and pinned by exact model id,
So that tier-2 judging is empirically selected, not chosen by fiat. (FR29)

**Acceptance Criteria:**

**Given** the judge bake-off (eval-design §7),
**When** run before the first full eval run,
**Then** candidates from all three pools (frontier APIs, local Ollama, hosted open-weight) judge the same sample blind via the `Llm(judge)` port, graded on agreement with prior human gold verdicts, and the winner is pinned by exact model id in `evals/runs/bakeoff-<date>/`.

**Given** cloud judge candidates,
**When** they receive content,
**Then** it is derived data only (transcript snippets, extracted artifacts) — never recordings (NFR15).

**Given** the pinned judge,
**When** it scores extraction and Q&A per rubric 2.7,
**Then** results land in `llm-judge-report.yaml` with the judge model id and version in run metadata, scores advisory to the human judge.

**Given** a later judge-model change,
**When** it occurs,
**Then** prior verdicts are invalidated per the rerun rule.

### Story 5.5: Eval Runbook & Documented-Only Designs

As an eval operator without tribal knowledge,
I want a written runbook covering the complete eval procedure,
So that anyone can execute a full run and record a defensible verdict. (FR30)

**Acceptance Criteria:**

**Given** the runbook,
**When** an operator follows it alone,
**Then** they complete: preconditions, deterministic suite, failure triage (pipeline bug | script error | genuine miss), optional LLM judging, human judging worksheets, final verdict (`verdict.md` — PASS only if recall = 100%, guardrail holds, no human fail), archive, and the rerun rule.

**Given** human judging,
**When** performed,
**Then** verdicts + one-line reasons are recorded per item in `human-verdicts.yaml`, human verdict winning any disagreement.

**Given** the DOCUMENT-only commitments,
**When** the epic completes,
**Then** design docs exist for: the citation timestamp-window check (±15s), action-item fuzzy set-match, eval cadence (change-triggered + go-to-prod gate), and the full retrieval eval design (recall@k, exact-set graph traversal comparison) — implementation explicitly deferred per scope.md.

**Given** the sequencing rule (NFR12),
**When** this epic is declared done,
**Then** it is complete before any demo-script work begins.

## Epic 6: Bring Any Meeting In

A user can add a meeting from a YouTube URL, a Zoom export, a Teams export, or loose files — from the web app — and watch it become evidence with live progress. Every source enters through the same write-once drop and the single intake door (AD-1, AD-14); the api launches acquisition as a separate host process and never runs it in-process (AD-11). Sprint Change Proposal 2026-08-29, approved.

### Story 6.1: UX Design Spec for the New Flows

As the product owner,
I want a design specification for the three new flows before any of them is built,
So that the front door, acquisition, speaker-naming, and model-selection experiences are designed as one product rather than bolted on screen by screen. (UX-DR12–UX-DR18)

**Acceptance Criteria:**

**Given** the reimagined UI's dark, data-dense idiom (spec-ui-reimagine) as the base,
**When** the design spec is produced with `bmad-ux`,
**Then** it covers Add-meeting (source tabs, pre-flight validation, launch-to-ingestion progress, failure states naming the refusing rule), Speaker naming (talk share, three sample clips per tag, tag-filtered transcript, inline naming, unresolved as a first-class choice), Model selection (selector in the ask box and on the settings page, provider health inline), and the two front-door views — Moments (ranked, explained cards) and Threads (semantic-zoom timeline with level-of-detail tiers, transitions, and what each tier reveals). It defines a color system on the dark, data-dense base where color carries meaning — thread identity, moment kind, ingestion state, provider health — with an accessible palette and stated contrast ratios, not decoration (owner: "make sure there's a bit of color").

**Given** the design spec,
**When** a UI story in epics 6–8 or 10 is built,
**Then** it cites the spec as its adopted design companion and deviates only with a recorded reason.

**Given** every element the design shows,
**When** it is checked against the server surface,
**Then** each is backed by data that exists or by an endpoint a story in this plan creates — nothing decorative.

### Story 6.2: YouTube Acquisition Command

As a user,
I want `make youtube-drop URL=<url>` to turn a published YouTube video into an ingested meeting,
So that public talks and recorded community meetings build the corpus through the same write-once door as every other source. (FR33)

**Acceptance Criteria:**

**Given** a YouTube watch or short URL,
**When** the command runs,
**Then** it refuses before writing anything for: a URL that is not a YouTube video, a private or removed video, no video stream, `yt-dlp` or `ffmpeg` missing, or a duration over a configurable cap (default 180 minutes) — each refusal named.

**Given** a video already minted,
**When** the command runs again on it,
**Then** `find_existing_drop` on `youtube:<videoId>` answers before any download, the result is `exists`, and no network traffic for media occurs.

**Given** a new video,
**When** it is downloaded,
**Then** the recording is a browser-playable MP4 (`bv*[ext=mp4][vcodec^=avc1]+ba[ext=m4a]/b[ext=mp4]`, merged), the caption track is English manual captions when present, otherwise auto-generated, converted to VTT, and `info.json` is read for metadata but not copied into the drop.

**Given** the downloaded files,
**When** the drop is minted,
**Then** `metadata.json` carries `sourceId` `youtube:<videoId>`, `corpus` `real`, `startedAt` from `release_timestamp` (second) or `upload_date` (day), `provenance` with `tool`, `url`, `channel`, `durationSeconds`, `ytDlpVersion`, `formatId`, and the per-file sha256/byteSize block `mint-drop` writes; `participants` is omitted; assembly goes through `mintdrop`'s existing staging → validate → atomic-rename path via keyword overrides on `mint()` that default to today's behaviour — no second finalize implementation.

**Given** `--no-post`, `--drops`, or `--api`,
**When** supplied,
**Then** they behave as in `mint-drop`.

**Given** the test suite,
**When** it runs,
**Then** URL classification, metadata mapping from a recorded `info.json`, the refusal matrix, and the `exists` short-circuit are covered without network; one network test runs only behind an env flag; `docs/README.md` gains an "Ingesting a YouTube video" section beside "Bringing your own recording".

### Story 6.2a: Playlist Acquisition

As a user,
I want `make youtube-drop` to accept a playlist URL and mint one meeting per entry,
So that a recurring series (a community's weekly meeting) enters the corpus in one command and threads have more than one meeting per topic. (FR33)

**Acceptance Criteria:**

**Given** `--playlist` with a playlist URL,
**When** the command runs,
**Then** entries are enumerated with `--flat-playlist` and each is minted and posted exactly as story 6.2 mints one video — one drop and one `POST /ingests` per entry, sequentially — with a summary table naming each entry's outcome (`minted | exists | refused:<rule>`); a refused entry does not stop the run.

**Given** a playlist containing an already-minted video,
**When** the run reaches it,
**Then** story 6.2's `exists` short-circuit applies per entry with no media download.

**Given** the test suite,
**When** it runs,
**Then** enumeration and the per-entry outcome table are covered offline from a recorded flat-playlist listing.

### Story 6.3: Local-Files Acquisition with Transcript Dialect Conversion

As a user,
I want to mint a drop from a recording and a transcript exported by Zoom or Teams,
So that past meetings with their own transcripts enter the corpus with their speakers intact. (FR35)

**Acceptance Criteria:**

**Given** `mint-drop` with `--transcript-dialect zoom`,
**When** a Zoom `.vtt` whose cue payloads read `Name: text` is supplied,
**Then** it is converted into the trusted speaker-attributed `.txt` format (`<Name> | MM:SS` blocks) plus a `.vtt` carrying timing, both written into the drop, and `provenance.transcriptDialect` records `zoom` and the conversion.

**Given** `--transcript-dialect teams-vtt` or `plain`,
**When** files are supplied,
**Then** Teams exports pass through unchanged (a `.txt` with speakers, a speaker-less `.vtt`), and `plain` is the existing behaviour; a dialect is never inferred from content.

**Given** a converted Zoom transcript,
**When** the meeting ingests,
**Then** `align` resolves the Zoom names through the roster exactly as Teams labels resolve, and the pipeline's transcript contract (`pipeline/transcripts.py`) is unchanged.

### Story 6.4: Acquisition Launch Surface

As a user,
I want the api to accept an acquisition request and report its progress,
So that the web app can start an acquisition without the api doing the work itself. (FR34)

**Acceptance Criteria:**

**Given** `POST /acquisitions` with a YouTube URL,
**When** the request is valid,
**Then** the api launches the acquisition tool as a detached host process with a per-acquisition status file and log under `.logs/`, answers 202 with an acquisition id, and refuses a second running acquisition for the same source id with a conflict.

**Given** `POST /acquisitions/probe` with `{url}`,
**When** the URL is checked before submit,
**Then** it performs story 6.2's URL, availability, stream, tool, and duration checks without downloading media, minting a drop, starting a process, or writing acquisition state; success returns `{title, durationMs, captions: {kind, language}, sourceId}`, and refusal is RFC 9457 Problem Details carrying stable `rule`, `detail`, and `remediation` fields.

**Given** `GET /acquisitions/{id}`,
**When** polled,
**Then** it reports `queued | running | posted | failed` from the status file with the log tail; `posted` carries `result: created | exists`, the job id and meeting id returned by or resolved around `POST /ingests`, and `source: {sourceId, tool, toolVersion}` from acquisition provenance; story 6.2's `exists` short-circuit maps to `posted` with `result: exists` and the existing ids, and no media network traffic occurs.

**Given** an acquisition that ends in `failed`,
**When** status is read,
**Then** it carries `refusal: {rule, detail, remediation}` from the tool or upload-session refusal, never requiring the web client to parse the log tail.

**Given** any acquisition,
**When** it runs,
**Then** the api performs no download, conversion, or pipeline work in-process (AD-11) and opens no second intake door (AD-14).

**Given** route registration,
**When** the routes are added,
**Then** they register through the auto-discovered registry (story 2.8) and `make client` regeneration happens in this story and 6.4a only.

### Story 6.4a: Upload Sessions

As a user,
I want to hand the api a recording and transcript files for a meeting I already have,
So that a Zoom or Teams export can enter through the web app without the api touching the pipeline. (FR34)

**Acceptance Criteria:**

**Given** an upload-session endpoint receiving a recording and/or transcript files with a declared transcript dialect,
**When** the files are received,
**Then** the multipart session requires `title`, RFC 3339 `startedAt` including a numeric UTC offset, `corpus: real`, and an explicit `transcriptDialect` whenever a VTT is present; the UI collects the timestamp and never infers one from a date; files stream to a staging directory under the drops root, never into a finalized drop; the session is refused by name for missing metadata, an undeclared dialect, an unsupported file type, or a size over a configured cap.

**Given** a completed upload session,
**When** `POST /acquisitions` names it,
**Then** the api launches `mint-drop` with `--transcript-dialect` against the staging directory exactly as story 6.4 launches the YouTube tool — same status file, same `GET /acquisitions/{id}` states — and the staging directory is removed once the drop is finalized or the acquisition fails.

**Given** route registration,
**When** the routes are added,
**Then** they register through the auto-discovered registry and `make client` is regenerated.

### Story 6.5: Add-Meeting UI

As a user,
I want one Add-meeting flow in the web app,
So that bringing in a meeting from any source is a first-class experience with live progress. (FR34, UX-DR13)

**Acceptance Criteria:**

**Given** the story 6.1 design,
**When** Add-meeting opens,
**Then** it presents the YouTube URL tab with pre-flight validation (a URL probe naming the refusing rule before submit) inside the tab chrome the story 6.1 design defines for all four sources; the file tabs are story 6.5a.

**Given** a submitted acquisition,
**When** it progresses,
**Then** the UI shows launch → running → posted, then the meeting card with the existing SSE stage progress, without a reload.

**Given** a refusal at any step,
**When** it is shown,
**Then** the message names the refusing rule and the remediation, and nothing is invented; the web test suite covers the URL tab and each of its failure states.

### Story 6.5a: Add-Meeting File Tabs

As a user,
I want the local-files, Zoom-export, and Teams-export tabs of Add-meeting,
So that a meeting I already have enters through the same flow as a YouTube URL. (FR34, FR35, UX-DR13)

**Acceptance Criteria:**

**Given** the story 6.1 design and story 6.4a's upload session,
**When** a file tab is used,
**Then** dropped or chosen files are classified client-side (recording, speaker-bearing `.txt`, `.vtt`) and the transcript dialect is an explicit choice on the Zoom and Teams tabs, never inferred, before submit.

**Given** a submitted upload,
**When** it progresses,
**Then** upload → launch → running → posted → meeting card follows the same progress surface as the URL tab, without a reload.

**Given** a refusal at any step,
**When** it is shown,
**Then** the message names the refusing rule and the remediation; web tests cover each file tab and each failure state.

### Story 6.6: YouTube Deep Links

As a user,
I want a moment from a YouTube meeting to open the original video at that moment,
So that the source is one click away even though replay is local. (UX-DR12)

**Acceptance Criteria:**

**Given** a moment whose `sourceDeepLink` host is YouTube,
**When** moment view, drill-down, or a chat citation renders it,
**Then** it offers "Open on YouTube at HH:MM:SS" secondary to local replay, built with the browser URL API by replacing or inserting the provider's time parameter from the moment start offset; it works for watch and `youtu.be` URLs with or without an existing query and never concatenates a second time parameter.

**Given** a non-YouTube deep link or a meeting without local replay,
**When** rendered,
**Then** the existing behaviour holds ("Open in Stream"; deep link as the sole affordance only when no replay exists); web tests cover both hosts and both replay states.

### Story 6.7: Extraction Prompt Wording Generalized

As an operator,
I want the extraction prompts to describe the input as a meeting or recorded session transcript,
So that talks and Zoom calls are not framed as Microsoft Teams meetings. (FR19)

**Acceptance Criteria:**

**Given** `config.yaml`'s two extraction prompts,
**When** their preambles are reworded,
**Then** the table headers, item-id prefixes, and timestamp rules the parser keys on are untouched and every parser test passes.

## Epic 7: Know Who Spoke

A user can see who spoke when in any recording and put names to the voices without the system ever guessing: a real diarizer segments turns into anonymous tags (worker-owned evidence, AD-5), a human assigns names as api-owned alias rows, and the assignment re-attributes the transcript, graph, and extractions while every moment id and citation survives (AD-13).

### Story 7.1: Diarizer Engine Behind the Port

As an operator,
I want a real diarization engine bound through the existing `Diarizer` port,
So that recordings without a speaker-attributed transcript get who-spoke-when turns. (FR36)

**Acceptance Criteria:**

**Given** the `Diarizer` port and `config.yaml`,
**When** `diarizer.engine` names the new engine,
**Then** `build_diarizer` returns it, an unavailable engine still raises the named `DiarizerError`, and `noop` remains the default.

**Given** a 60-minute recording,
**When** diarization runs,
**Then** wall-clock time and turn quality are measured and recorded in the story report for the chosen engine — `pyannote.audio` in-process on this machine first, with the NeMo endpoint on the LAN GPU host as the config-swappable alternative if it is too slow.

**Given** the turns,
**When** `transcribe` stores the STT lane,
**Then** each segment carries its `SPEAKER_NN` tag exactly as `speaker_at` assigns today, and no tag resolves to a participant.

### Story 7.2: Speaker Tags on the Wire

As a user,
I want to see each speaker tag with its talk time and sample offsets,
So that I can tell who is who before naming anyone. (FR36)

**Acceptance Criteria:**

**Given** `GET /meetings/{id}/speakers`,
**When** called,
**Then** it lists each tag with talk time, segment count, and three sample offsets chosen from its longest segments; every row carries nullable `participantId` and `displayName`, populated when the source or an alias resolves the label; transcript segments carry their tag; the route is read-only and registered through the registry.

**Given** a meeting whose transcript already carried speaker names (a Teams archive drop, or a Zoom transcript converted by story 6.3),
**When** the endpoint is called,
**Then** each label is listed as a resolved participant with the same talk time and sample offsets, so named and unnamed sources share one shape (absorbed from story 7.5).

### Story 7.3: Speaker Assignment

As a user,
I want to assign a speaker tag to a participant or a new name,
So that the transcript, graph, and extractions reflect who spoke without breaking a citation. (FR37)

**Acceptance Criteria:**

**Given** `PUT /meetings/{id}/speakers/{tag}` with a participant id, a new display name, or `unresolved`,
**When** it is accepted,
**Then** an api-owned `participant_alias` row is written in a `speaker:<meetingId>:<tag>` namespace (AD-5) and the meeting's job is re-armed for `align → moments → extract` only.

**Given** the rerun,
**When** it completes,
**Then** every pre-existing moment id, citation, and approved/published artifact still resolves — pinned by a test — and extraction replaces drafts only.

**Given** `unresolved`,
**When** chosen,
**Then** segments keep the tag with `speaker_resolution` `placeholder`, and no name is guessed.

### Story 7.4: Speaker Naming UI

As a user,
I want to name speakers by listening to short clips,
So that attribution is a two-minute task rather than a rewatch. (UX-DR14)

**Acceptance Criteria:**

**Given** the story 6.1 design,
**When** the meeting's speakers panel opens,
**Then** each tag shows its talk share and three clips that play through the existing Range-correct media route at the sample offsets, plus the tag-filtered transcript; `ReplayPlayer` accepts an optional `endMs`, and each sample clip sets it to `startMs + 8000` so playback pauses after eight seconds while existing callers retain open-ended playback.

**Given** a tag,
**When** I name it,
**Then** I can pick an existing participant from suggestions that are never auto-applied, type a new name, or mark it unresolved; the change is visible in the transcript when the rerun lands; web tests cover all three choices.

**Given** a label already resolved from the transcript,
**When** I correct it,
**Then** the correction writes the same alias row and triggers the same rerun as story 7.3 (absorbed from story 7.5).

**Story 7.5 (retired id): Zoom-Supplied Speakers Through the Same Path** — merged 2026-08-29 into stories 7.2 (resolved-label shape on the wire) and 7.4 (correcting a resolved label). Id retired; not reused. Not a heading, so sprint tracking does not re-create it.

## Epic 8: Choose the Model

A user can pick which model answers and which extracts, from the catalog `config.yaml` allows, and see the provider's health beside the choice. Amends AD-10: the file declares every binding plus, for the LLM roles, the catalog a user may choose between and the default; a user's selection is user-declared data persisted by the api (AD-5), resolved at call time by api and worker, recorded in every eval snapshot; nothing outside the catalog can be selected and no selection is a fallback.

### Story 8.1: AD-10 Amendment and Binding Catalog

As an operator,
I want `config.yaml` to declare the models a user may choose per role,
So that choice happens inside a boundary the file still owns. (FR38)

**Acceptance Criteria:**

**Given** `llm.roles.<role>`,
**When** the config schema gains `catalog[]` (`binding`, `label`, `provider`) and `default`,
**Then** the loader fails closed if the default is not in the catalog or a catalog binding names an undeclared provider, and existing single-`model` files still load with a one-entry catalog.

**Given** the amendment,
**When** it lands,
**Then** `docs/architecture.md` AD-10 carries the new wording, `project-context.md`'s policy line about bindings is updated, and the stale chat comment about the revoked key is removed.

### Story 8.2: Persisted Selection

As a user,
I want my model choice to persist and to be what the system actually uses,
So that the selector is real, not decorative. (FR38, FR39)

**Acceptance Criteria:**

**Given** an api-owned `app_setting` table (migration),
**When** `PUT /settings/roles/{role}` names a catalog binding,
**Then** it persists; `GET /settings/models` serves the catalog with the active selection; a binding outside the catalog is refused.

**Given** a chat request and an extraction job,
**When** they resolve their role,
**Then** chat reads the selection per request and the worker per job; the eval snapshot records the effective binding beside the file value.

**Given** a selected binding that fails at call time,
**When** the failure is raised,
**Then** it surfaces at the point of use as RFC 9457 type `urn:meetingminer:problem:binding-failed` with `provider`, `binding`, and the upstream status represented in `detail`; no other model is substituted.

### Story 8.2a: Provider Health on the Status Surface

As a user,
I want the status surface to show whether each configured provider's key is valid and which binding each role is using,
So that a bad key or a wrong selection is visible before I ask anything. (FR39)

**Acceptance Criteria:**

**Given** `GET /status`,
**When** it reports,
**Then** it shows key validity per configured provider as `providers[]{provider, keyState, detail, remediation}`, probed through free endpoints only (a model list, never a completion) and cached between polls, and the active binding per role as resolved from story 8.2's persisted selection beside the file default.

**Given** the status page and chrome indicator (spec-system-status),
**When** a provider's key is missing or invalid, or a role's selection resolves to a failing binding,
**Then** the surface names the provider or role and the remediation, and no fragment of any key serializes.

**Given** AD-10 as amended 2026-08-31 — the model *catalog* is a snapshot each process takes at startup, while a *selection* is a per-request `app_setting` read,
**When** this surface reports a provider's health or a role's binding,
**Then** it says **whose view it is**. A binding indicator describes the process that answered the request, never "the system": the api and the worker hold independent snapshots, so a role can read as locally served here while the worker is genuinely calling a paid provider on a different snapshot. This is not hypothetical — it happened on 2026-08-31, when a config edit was followed by a worker restart and no api restart, and `GET /status` advertised free local extraction while OpenAI was being billed. Reporting a state the system is not in is an AD-18 violation, so the surface must attribute its reading rather than leave it ambiguous, and the wording must not imply that a single answer covers both processes.

### Story 8.3: Model Picker UI

As a user,
I want to choose the model where I ask and on the settings page,
So that the choice is one click away and its health is visible. (UX-DR15)

**Acceptance Criteria:**

**Given** the story 6.1 design,
**When** the ask box and the settings page render,
**Then** each offers the catalog with provider health inline and the active choice marked; a failing binding shows the named error where it happens.

**Given** the Anthropic entries,
**When** the builder pins model ids and parameters,
**Then** they are taken from the `claude-api` reference, not from memory; web tests cover selection and the failure state.

## Epic 9: Cohort Close-out

The corpus holds the owner's chosen meetings, speakers are named on the featured ones, artifacts are published, and the five-minute walkthrough is recorded against real, unencumbered data. Preceded by the ops checklist in the Sprint Change Proposal (OrbStack, `make up`, `/status` green, both provider keys verified).

### Story 9.1: Demo Corpus

As the product owner,
I want the corpus built from my chosen videos and past meetings with speakers named and artifacts published,
So that every screen in the walkthrough runs on real data. (FR33–FR39)

**Acceptance Criteria:**

**Given** the owner's list of videos and exports,
**When** they are acquired through Add-meeting (or the command while the UI is in flight),
**Then** every meeting ingests to evidence-complete, featured meetings have their speakers named, and several moments carry approved, published artifacts.

**Given** the demo path,
**When** it is rehearsed end to end,
**Then** chat re-submit (B-12) and an idle job-event stream (B-11) are exercised and fixed only if they reproduce; paid chat calls run under the 2026-08-29 authorization.

### Story 9.2: Five-Minute Walkthrough

As the product owner,
I want a scripted, rehearsed, recorded five-minute walkthrough,
So that the cohort close-out shows the system as built. (all)

**Acceptance Criteria:**

**Given** the 3-minute capstone script as the base,
**When** the new script is written,
**Then** it covers: add a YouTube meeting and watch it ingest → dense meeting view → name a speaker → replay a moment → search → pick a model → ask → cited answer → open the cited moment → YouTube deep link → status/config; one rehearsal precedes the recording; the script is committed under `docs/` and the recording is stored outside git.

## Epic 10: Moments & Threads

The front door: a Moments view that puts the most pressing evidence first with its reason stated, and a Threads view that follows a topic across meetings on a timeline you zoom into like Google Earth. Topics become first-class, moment-anchored navigation in the database of record and the graph — machine-derived and labeled as such, human-curatable, never a chat fact. Owner direction 2026-08-29; designed in story 6.1; sequenced right after Epic 6.

### Story 10.1: Topic Extraction

As a user,
I want each meeting's topics extracted with the moments where they are discussed,
So that a topic can be followed instead of searched for. (FR41)

**Acceptance Criteria:**

**Given** the extract stage,
**When** a meeting is extracted,
**Then** a third document — topics — is produced through the same `Llm(extraction)` port and strict parser as the summary and action items: one row per topic with name, one-line gist, and `[m:ss]` anchors, each anchor resolved to its containing moment; an anchor outside the timeline fails by name; a meeting that plainly has content and yields zero topics is reported as a signal, not success.

**Given** the database of record,
**When** topics are stored,
**Then** they live in new `topic` and `topic_mention` tables anchored to moments (worker-owned, machine-derived rows, labeled as such), are not artifacts and never enter the `extracted → approved → published` lifecycle, and a rerun replaces them; topic-level human curation is not in this story — curation happens at thread level in story 10.2a.

**Given** the prompt,
**When** it is added to `config.yaml`,
**Then** it is served by the extraction-prompts endpoint and visible in the UI like the other two (FR19), and its wording covers meetings and recorded sessions alike.

### Story 10.2: Threads and the Graph Projection

As a user,
I want topics linked across meetings into threads,
So that one thread shows every discussion of a subject over time. (FR42)

**Acceptance Criteria:**

**Given** topics from more than one meeting,
**When** threads are derived,
**Then** topics link by normalized name and by embedding similarity above a configured threshold into one thread, and the rule and threshold are configuration with recorded rationale; derivation is idempotent, so a rerun over unchanged topics yields the same threads.

**Given** the projection pass,
**When** a meeting reaches evidence-complete,
**Then** `projections` — still the sole writer (AD-4) — writes `Topic` and `Thread` nodes and `MENTIONS` edges to moments; the AD-4 clarification that topics are navigation metadata outside the publish gate is recorded in `docs/architecture.md` with `bmad-architecture` as part of this story.

**Given** a thread,
**When** the thread traversal template runs,
**Then** it returns the thread's meetings and moments in wall-clock order with per-level aggregates (mentions per meeting, span, participants where known), registered like the existing templates (AD-7).

### Story 10.2a: Thread Curation

As a user,
I want to merge, split, and rename threads,
So that the machine's grouping can be corrected without being overwritten on the next rerun. (FR42)

**Acceptance Criteria:**

**Given** api-owned curation endpoints for threads,
**When** I merge two threads, split one, or rename one,
**Then** the change is stored as api-owned curation (alias rows, AD-5), survives every rerun and re-derivation of story 10.2, and is projected into the graph by `projections` (AD-4) on the next pass; the machine never renames or merges on its own.

**Given** the Threads view (story 10.6),
**When** curation is available,
**Then** merge, split, and rename are reachable from a band or its header per the story 6.1 design where it covers them (otherwise with a recorded deviation), and web tests cover each.

### Story 10.2b: Thread Questions in Chat

As a user,
I want to ask "what have we said about X over time" and get an answer that walks the thread,
So that a thread is reachable from the ask box as well as the timeline. (FR42, FR13)

**Acceptance Criteria:**

**Given** the chat classifier,
**When** a question asks about a subject over time,
**Then** it may route to story 10.2's thread traversal template; the answer still cites moments only and passes the existing citation gate unchanged, pinned by tests in the chat suite.

### Story 10.3: Thread Timeline API with Level-of-Detail

As a user,
I want the thread timeline served at the detail level I am looking at,
So that zooming is fast and each level shows only what it renders. (FR43)

**Acceptance Criteria:**

**Given** `GET /threads` and `GET /threads/{id}/timeline?from=&to=&level=`,
**When** called at levels `bands | meetings | moments | evidence`,
**Then** `GET /threads` returns `threadId`, `name`, `mentionCount`, `meetingCount`, `firstMentionAt`, `lastMentionAt`, and immutable `colorOrdinal`; each level returns exactly its tier: thread bands with mention density per time bucket; meetings on the band with counts and topic membership for Story 10.2a's split panel; moments with `momentId`, `meetingId`, `title`, `startMs`, `occurredAt`, `occurredAtPrecision`, speakers-where-known, and opaque `screenshotId`; evidence adds transcript excerpt, artifact anchors, `hasRecording`, and opaque media ids needed for ID-addressed replay through `GET /media/files/{mediaId}` — never a storage path.

**Given** a thread is created, merged, or split,
**When** its identity is stored,
**Then** the database allocates a unique positive `colorOrdinal` from a transactional per-corpus sequence, assigns it once, and never recycles it within the corpus; a merge survivor retains its ordinal and a newly split thread receives a new ordinal, so concurrent creates, filtering, sorting, imports, and reruns never duplicate or recolor an existing thread.

**Given** a timeline item anchored by a meeting-relative `startMs`,
**When** the api serializes it,
**Then** the server derives canonical RFC 3339 UTC `occurredAt` from the meeting start plus `startMs`; when the source supplied only a date it anchors at `00:00:00Z + startMs`, preserves `occurredAtPrecision: day`, and breaks equal-anchor ties by `meetingId`, then `momentId`; clients use the served value rather than reconstructing wall-clock time.

**Given** a corpus of hundreds of meetings,
**When** the coarse levels are requested,
**Then** they are cheap aggregates over the database of record, bounded by the time window, and never a full scan of moments.

### Story 10.4: Moments Feed Ranking

As a user,
I want the most pressing moments first,
So that opening the app answers "what needs my attention" without a search. (FR40)

**Acceptance Criteria:**

**Given** `GET /moments/feed`,
**When** called with optional filters (corpus, thread, meeting, kind),
**Then** it returns `{items, total, limit, offset}` with moments ranked by a deterministic score over stored signals — decision and ADR artifacts, action items with stated timing (soonest first), risks and open questions, meeting recency, publication recency, thread membership — with every weight in `config.yaml` with recorded rationale. Each item carries `momentId`, `meetingId`, `meetingTitle`, `startedAt`, `startedAtPrecision`, `startMs`, `endMs`, `corpus`, `hasRecording`, `sourceDeepLink`, opaque `screenshotId`, `viewType`, `preview`, `threads[]{threadId,name,colorOrdinal}`, and a non-empty ordered `reasons[]` of `{kind, label, ref?, at?}` where `kind` is an artifact kind or `due | risk | question | recency | published | thread`; `screenshotId` resolves only through ID-addressed `GET /media/files/{mediaId}` (AD-17). Reason validation happens before pagination: an item with no valid reason is dropped and logged, and `items`, `total`, and offsets are computed only from remaining serializable rows.

**Given** risks and open questions are ranking signals but not publishable artifacts,
**When** Story 10.4 extends the extract stage,
**Then** it produces strict-parser, moment-anchored persisted ranking-signal rows of kind `risk | question` through the existing `Llm(extraction)` port; they are worker-owned and replaced on rerun, do not enter the artifact approval lifecycle, and the request-time ranker reads only those stored rows.

**Given** the ranking,
**When** it runs,
**Then** no model call happens at request time, the score is unit-testable as a pure function over plain facts, and an item whose moment no longer resolves is dropped and logged, never returned.

### Story 10.5: Moments View and Front Door

As a user,
I want the home screen to be the Moments view,
So that the most pressing evidence is the first thing I see. (UX-DR16, UX-DR17)

**Acceptance Criteria:**

**Given** the story 6.1 design,
**When** the app opens,
**Then** it shows ranked moment cards — screenshot, meeting and offset, the stated reason, thread chips — each replaying in place and linking to its moment and meeting, with filters for corpus, thread, and kind; search, ask, and Add-meeting stay persistent chrome.

**Given** the corpus counts and meeting cards of the reimagined home,
**When** the Moments view lands,
**Then** they remain reachable (a Meetings view or panel) and the existing demo path and web tests stay green.

**Given** the shell,
**When** the front door is recomposed,
**Then** Moments is the default route and Threads the second primary view, Meetings/Participants/Status/Settings remain reachable from the chrome, search and ask stay persistent, the shell applies the dark theme class the story 6.1 design specifies, and the shell's child-screen placement is pinned by a test (backlog B-13 closed here; absorbed from story 10.7).

### Story 10.6: Threads Zoomable Timeline

As a user,
I want to zoom into a thread's timeline like Google Earth,
So that I go from the shape of a subject across months to one replayed sentence without changing screens. (FR43, UX-DR18)

**Acceptance Criteria:**

**Given** the Threads view,
**When** it opens,
**Then** it starts zoomed out: every thread as a band across the corpus's time span with mention density, sortable by activity and recency, searchable by name.

**Given** continuous zoom and pan on a band,
**When** level-of-detail thresholds are crossed,
**Then** the view reveals meetings, then moments with titles and speakers — each tier fetched from story 10.3 at that level, with smooth transitions and no layout jump; nothing is shown that a moment does not back. The evidence tier and inline replay are story 10.6a.

**Given** a moment at the moments tier,
**When** it is opened,
**Then** it links to moment view; web tests cover the bands → meetings → moments transitions with fixture data at each level.

### Story 10.6a: Evidence Tier and Inline Replay

As a user,
I want the deepest zoom to show the moment's evidence and play it in place,
So that the path from a subject across months ends at one replayed sentence without changing screens. (FR43, UX-DR18)

**Acceptance Criteria:**

**Given** the moments tier of story 10.6,
**When** the level-of-detail threshold into `evidence` is crossed,
**Then** the moment's screenshot, transcript excerpt, and artifact anchors render from story 10.3's evidence level, with the same transition discipline and no layout jump.

**Given** a moment at the evidence tier,
**When** it is opened,
**Then** it replays in place through the existing replay player and links to moment view; web tests cover the moments → evidence transition and the replay affordance with fixture data.

**Story 10.7 (retired id): Front-Door Composition** — merged 2026-08-29 into story 10.5 (Moments View and Front Door). Id retired; not reused. Not a heading, so sprint tracking does not re-create it.

## Epic 11: Fast, Conflict-Free Test Suite

The operator's first priority (2026-08-29): "tests cause conflicts between builders and tests take forever to run." Measured baseline (backlog B-1): `pytest server/tests` runs 1,684 tests in ~33 minutes; collection takes 1.0s and a pure decision-core module runs 34 tests in 0.04s, but 215 tests (16%) in seven modules spawn real processes — `make` targets with readiness polls, ffprobe/ffmpeg, `CREATE DATABASE`, a 300s file-lock wait — with a combined timeout budget of ~1,500s, unmarked, in the same directory. Story 2.7 made Postgres per-run; the projection suites still share two test-twin containers behind a cross-worktree file lock, and `make evals-run` is serial by rule. Built before Epic 6.

### Story 11.1: Seconds-Fast Default Suite

As a builder,
I want the routine server test run to finish in seconds,
So that I run it after every change instead of once per story. (NFR19)

**Acceptance Criteria:**

**Given** the seven process-spawning modules named in backlog B-1,
**When** they are marked `slow`,
**Then** the default runner (`uv run --project server pytest`, and a new `make test-fast`) selects `-m "not slow"`, runs the remaining ~1,169 tests in a few seconds, and `make test` still runs everything.

**Given** a per-test time budget in `pyproject`/conftest (configured, with rationale),
**When** an unmarked test exceeds it,
**Then** the run fails naming the test, so the fast suite cannot silently regrow.

**Given** `conftest.py`,
**When** the story lands,
**Then** `REPO_ROOT` lives in a normal module the five importing modules use, the duplicate `_make`/`_run_make` helpers are collapsed, no test changes behaviour, and AGENTS.md and `project-context.md` state the fast/full split.

### Story 11.2: Per-Run Store Isolation

As a builder,
I want every worktree to own its stores,
So that two worktrees can run everything at once without waiting or interfering. (NFR20)

**Acceptance Criteria:**

**Given** `make worktree STORY=<slug>`,
**When** a worktree is created,
**Then** it provisions a full private stack — its own Postgres, Neo4j, and Meilisearch, dev instances and test twins alike, as a compose project named for the worktree on dynamic ports — and writes the worktree's environment to point at them, so dev stores and test twins are both per-worktree; `make worktree-remove` tears the stack down; the per-stack memory cost is measured and documented (this machine has 128 GB — owner direction 2026-08-29: make the most of it).

**Given** the projection suites,
**When** a session starts in a worktree,
**Then** they target that worktree's test twins; the cross-worktree file lock — keyed by store URL — therefore never has a holder from another worktree, and it remains for dev-store writers (`rebuild`, the worker) inside one worktree.

**Given** `test_projection_lock_times_out_with_holder_details_then_releases` (B-14),
**When** it runs,
**Then** it targets its own lock key through an env override and cannot observe another worktree's holder.

**Given** a run or worktree killed mid-way,
**When** `make test-db-prune` runs,
**Then** it also removes orphaned per-worktree stacks, refusing anything with a live owner.

**Given** two worktrees,
**When** both run `make test` simultaneously,
**Then** neither waits on the other, both pass, the measurement (wall-clock per run, alone and concurrent) is recorded in the story report, and AGENTS.md's "worktrees do not isolate the stores" section is rewritten to the new truth.

**Not built in this story (2026-08-29 simplification):** the per-session ephemeral Neo4j container and the `stores.meilisearch.index_prefix` setting the earlier draft named — a private stack per worktree makes both redundant. Revisit only if a measured case (two concurrent suite runs inside one worktree) needs them.

### Story 11.3: Eval Runs Own Their Namespace

As an operator,
I want `make evals-run` to be safe to run while a builder's suite is running,
So that the one remaining serial rule goes away. (NFR20)

**Acceptance Criteria:**

**Given** an eval run,
**When** it starts,
**Then** it reads the shared dev stores read-only as today, its run folder is owned by its run id (never reused, never overwritten), and any store it must write through the public api (the publish-gate check) targets a namespace the run owns and cleans up; AGENTS.md's "one at a time" rule is replaced with the measured truth.

### Story 11.4: Lint and Type Tooling in the Fast Loop

As a builder,
I want `ruff` (and `mypy` where the code is typed enough) on the server,
So that the fast loop catches the errors a test never would. (backlog B-4)

**Acceptance Criteria:**

**Given** `make lint` and `make typecheck`,
**When** they run,
**Then** `ruff` passes on `server/` with a committed configuration, `mypy` runs on the decision-core modules with a committed baseline, both are part of `make test-fast`, and the `.gitignore` entries that anticipated them are now real.

## Epic 12: Meeting-Level Analysis

Extraction already runs whole-transcript — story 4.1's per-moment granularity was
replaced precisely because a decision emerges across minutes of discussion. But
everything it produces is then stored and shown per moment, and the document it
produced is discarded. Measured on the live corpus 2026-08-31: 15 meetings, 45
extraction runs, 193 artifacts, and **zero retained documents**; the moment view
of a meeting holding 16 artifacts reports "Nothing extracted yet" because that
moment carries none of them. This epic keeps what the model wrote, gives a
meeting its summary, and shows a meeting's analysis at the meeting.

Owner direction 2026-08-31: "The generated markdown isn't retained — this is a
huge miss. Artifacts must be visible and at the meeting level."

### Story 12.1: Retain the Extraction Documents

As an owner,
I want the document each extraction run produced kept and readable,
So that what the model actually wrote is evidence rather than a discarded intermediate.

**Acceptance Criteria:**

**Given** the extract stage,
**When** an extraction document is produced or parsed,
**Then** its full text is persisted with the `extraction_source` row that already records the run's kind, model, prompt hash, sha256 and byte size, and the stored bytes are the exact bytes the parser read, so the `sha256` already recorded verifies against them. A **generated** document — produced through the `Llm(extraction)` port — is primary data with no other home and is stored in Postgres, the precedent being `artifact.body`; AD-3's content root is for binaries (frames, screenshots, audio) and does not apply.

**Given** a document a drop already carried,
**When** it is adopted rather than generated,
**Then** its text is stored too, exactly as a generated one is, so both kinds are read back through one path. **The reason is AD-4, not economy.** Every extraction document must be searchable, and `projections/` never opens an evidence file — it reads Postgres values only, and `rebuild` regenerates both stores from Postgres plus `config.yaml` alone. Text living only in a drop could not be indexed without turning the projection module into a filesystem reader, and it would fall out of search on every rebuild. AD-3's anti-copy rule governs material the system *serves but does not retrieve over* (a recording is never indexed; everything searchable derived from it is already rows), so it does not reach here — see AD-3 as amended 2026-08-31.

**Given** a rerun,
**When** a meeting is extracted again,
**Then** the document is replaced wholesale alongside the artifacts derived from it, so a stored document is never a stale record of a run whose artifacts have since changed.

**Given** the api,
**When** a meeting's extraction runs are requested,
**Then** an endpoint serves each run's document text with its kind, model, prompt hash and item count; the document is served as the markdown it is, not re-rendered, so the reader sees what the model emitted including anything the parser ignored.

**Given** a document that parsed to zero items while plainly carrying content,
**When** it is stored,
**Then** the existing named signal still fires and the document is retained regardless — a run that yielded nothing is exactly the run whose text someone needs to read.

### Story 12.2: The Meeting Summary

As a user,
I want each meeting's summary kept as a first-class artifact,
So that the whole-meeting analysis the extraction already performs is not thrown away.

**Acceptance Criteria:**

**Given** the architecture-summary document,
**When** it is parsed,
**Then** its executive-summary prose is captured as an artifact of a new `summary` kind, scoped to the meeting rather than to a moment; only the decision rows continue to become `adr` artifacts, and no summary is fabricated for a document that carries none.

**Given** the artifact schema,
**When** a meeting-scoped artifact is stored,
**Then** `artifact.moment_id` is nullable and a constraint requires it null for meeting-scoped kinds and present for moment-anchored kinds, so the two scopes cannot be confused by a reader or a query; `meeting_id` stays required for both. **Which kinds are meeting-scoped is declared in exactly one place — that constraint** — so no reader carries its own copy of the list and none can drift from it. **Widening the scope must not weaken the anchor:** where `moment_id` is present, migration 0009's composite `(moment_id, meeting_id)` edge still holds, so no artifact can name a moment belonging to another meeting.

**Given** the approval lifecycle,
**When** a summary is created,
**Then** it enters the same `extracted → approved → published` lifecycle as every other artifact and is published by the same gesture — a meeting-level artifact is not an exception to human-approved publishing (AD-6), and the per-moment approval path keeps working unchanged for moment-anchored kinds.

**Given** "no citation, no answer",
**When** a summary is read in the meeting panel,
**Then** it renders freely — that is a read of stored artifact state, not an answer, and it needs no citation to be shown.

**Given** "no citation, no answer",
**When** a summary's content enters an answer,
**Then** it is citable only through the moments its individual claims anchor to, exactly as every other claim already is; a claim the document does not anchor is not citable at all. **`meeting_id` is scope and provenance, never a citation** — AD-15's citation carries a `momentId` with `startMs`/`endMs` because the product promise is that a citation opens the recording at the second, and a meeting-only citation hands the replay links, the eval checks and search something that cannot replay. That is the silent degradation AD-18 forbids, so the summary is not an exception to the citation rule and does not widen it.

### Story 12.3: The Meeting Analysis Panel

As a user,
I want a meeting's analysis visible when I open the meeting,
So that I read what the meeting produced without hunting through moments that mostly hold nothing.

**Acceptance Criteria:**

**Given** the api,
**When** a meeting's artifacts are requested,
**Then** one endpoint returns every artifact for that meeting — summary, ADRs and action items — with each one's moment anchor where it has one; the meeting view no longer assembles its rail by fanning out one `getMoment` call per moment.

**Given** the meeting view,
**When** a meeting is opened,
**Then** the summary is shown first, then ADRs and action items grouped by kind, each item stating its timestamp and linking to the moment it anchors to; a meeting with artifacts never reports "Nothing extracted yet".

**Given** the artifact kind list,
**When** the rail renders,
**Then** only kinds the pipeline can actually produce are listed — the five kinds that render a permanent `0` today are removed, so a zero means "none found in this meeting" rather than "this kind is never produced".

**Given** story 12.1's retained documents,
**When** a meeting's analysis is shown,
**Then** each extraction run is reachable from the meeting as its source document, labelled with the model and prompt that produced it, so a reader can compare an artifact against the text it came from.

**Given** the moment view,
**When** a moment is opened,
**Then** its existing per-moment rail is unchanged for the artifacts anchored to that moment — this story adds the meeting scope rather than moving the moment one.

### Story 12.4: Extraction Documents Are Searchable

As a user,
I want to search and ask questions about the extraction documents themselves,
So that the analysis a run produced is findable, including the run that produced nothing worth approving.

Owner ruling 2026-08-31, recorded in AD-4: extraction documents are indexed
**immediately and ungated** — search and chat retrieve over evidence, published
artifacts, and every extraction document regardless of approval state. This is
the **first deliberate exception to the publish gate** in this build. The
reasoning is story 12.1's own motivation turned around: the run whose text
somebody needs to read is exactly the run that yielded nothing worth approving,
so gating documents behind approval withholds them in precisely the case they
exist for.

**Acceptance Criteria:**

**Given** `projections` as the sole writer of both stores (AD-4),
**When** an extraction document is stored,
**Then** it is indexed as soon as it is stored, without passing the publish
gate, and it is re-indexed by `rebuild` from its Postgres row alone — the
projection module still opens no evidence file, so its filesystem access is
unchanged by this story.

**Given** AD-18, which forbids unreviewed output that reads the same as
reviewed output,
**When** a document is indexed or rendered,
**Then** it carries its unreviewed, machine-written status **in the indexed
record itself**, and every surface that renders one labels it as such — the
same requirement topics and threads already carry. **The exception is to reach,
never to legibility.** Indexing a document without that label is an AD-18
violation, not a missing polish item, and a test pins the label's presence in
the indexed record rather than only in the UI.

**Given** "no citation, no answer" and AD-6,
**When** a document's content appears in an answer,
**Then** the document is **never a citation target**. It is a claim *about*
evidence, not evidence: citing it would establish that the model said
something, not that the meeting did — the circularity the publish gate exists
to prevent. Content reaches an answer only through the moments its individual
claims anchor to; unanchored prose stays readable and findable without becoming
citable, and a test asserts no citation can resolve to a document.

**Given** `chunking.py` keys a chunk on its first transcript segment's UUID,
**When** a document is chunked for indexing,
**Then** it takes **no** chunk identity from a transcript segment, having none;
its indexed identity derives from its `extraction_source` row. Because a
document is not citable, that identity is a build decision rather than an
invariant — choose one, state it, and pin it with a test so a later reader does
not have to infer it.

**Given** `publish/publish_gate.py`,
**When** this story lands,
**Then** its module docstring no longer describes a rule that holds only in
part: it names the extraction-document exception and points at AD-4, so the
gate's own account of itself stays true.

### Story 10.7: Threads Is a Query, Not a Catalogue

As a user,
I want to open Threads empty, name a subject, and fly along a timeline of every meeting where it was discussed,
So that a thread is a route into the corpus rather than a list of everything the machine derived. (FR42, FR43, UX-DR18)

**Why this story exists.** Story 10.6 built a zoom and the zoom works, but both
ends of it are wrong. The view opens on a catalogue — every derived thread as a
band, 1,090 of them on the corpus of 2026-08-31, of which **976 involve exactly
one meeting** — so the reader arrives at a wall of rows that are not subjects
followed across meetings at all. And the deepest zoom ends at a moment, when the
thing the reader wants is the meeting.

Owner direction 2026-08-31: *"I go to the threads view and I type in a thread
topic. Then I get an overview of all the meetings where that thread runs through
those meetings … you're going to see a timeline across all your meetings where
that gets surfaced … and then I can click into a meeting like I can do in the
meeting view."*

**This design is taken from a working prototype** the owner pointed at, which
solves it well. Where an acceptance criterion below states a mechanism, that
mechanism is the prototype's and is deliberate — read
`web/src/ZoomTimeline.tsx`, `web/src/Thread.tsx` and `api/thread.js` in that
tree before designing an alternative.

**Acceptance Criteria:**

**Given** the Threads view,
**When** it opens,
**Then** it is **empty** — no thread list, no bands, no derived catalogue — and
offers a place to name a subject, beside a handful of **suggested subjects
drawn from the corpus**.

**Given** those suggestions,
**When** they are chosen,
**Then** they are **not the most-mentioned subjects**. The most-mentioned ones
are generic, appear in nearly every meeting, and their thread is the whole
corpus and no story at all. Choose subjects appearing in a **middling** number
of meetings and rank them by **how much calendar time they span**, because a
subject worth tracing is specific enough to be one concern and recurrent enough
to have a history. Drop near-duplicates so one concern does not consume two
slots. Each suggestion shows its reach — how many meetings, over how many days.

**Given** a subject typed into the box,
**When** it resolves,
**Then** there are **two ways in and the view says which one it took**. A typed
phrase that unambiguously names a known subject walks the stored mentions and
is **exhaustive within the corpus**; anything else is a **top-k retrieval
sample**, ordered by relevance and then re-sorted by time. A sample presented as
a full history is the same unverified-absence failure as claiming no recording
exists, so the completeness of what is on screen is stated in words, always.

**Given** a subject that resolves to more than one candidate,
**When** the reader has not yet chosen,
**Then** the adjacent candidates are offered to pick from rather than one being
guessed — "trail closures" surfaces both "Cedar Lake Trail closure" and "Trail
reopening outlook".

**Given** a chosen subject,
**When** the timeline builds,
**Then** it runs **left to right in time** across **every** meeting where that
subject surfaced, **on one timeline** — meetings from different recurring series
interleaved by date, not separated into lanes. The same subject discussed in two
different community meeting settings is two points on one schedule, which is the
comparison the reader came for.

**Given** a subject with more mentions than can be drawn,
**When** the result is capped,
**Then** the cap is applied **per meeting, never overall**. An overall limit
cuts the tail off a long-running subject and shows the first months as though
they were the whole history. Every meeting that mentions the subject stays a
stop on the timeline; only the number of moments quoted at each stop is limited,
and both figures are reported. **A shorter timeline is comprehensible; a
timeline with holes in it is not.**

**Given** the built timeline,
**When** the reader zooms and pans,
**Then** the zoom is **semantic, not magnification**. Layout is computed in
world coordinates — **pixels per day** — and every label is drawn at a constant
readable size, the way a map keeps its place names legible at any altitude.
Scaling a container with a CSS transform is explicitly wrong here: it is
unreadable at the top of the zoom and merely bigger at the bottom, and never
reveals anything new.

**Given** the altitude,
**When** it changes,
**Then** **what a meeting is** changes with it, over one payload already in
hand rather than by refetching a tier:

| pixels per day | a meeting is |
|---|---|
| under 20 | a bar — height is moment count, marked when it carries screens |
| 20 to 60 | the bar, with its date |
| 60 to 160 | a card — title, who spoke, a strip of its screens |
| over 160 | its moments — timecode, speaker, quote, screen, clickable |

So zooming out answers "what shape did this concern have over four months" and
zooming in answers "what exactly was said, and what was on screen when" —
without changing view. Zoom is about the cursor, so what is under the pointer
stays under it, and the view opens at the altitude where the whole span fits.

**Given** two meetings close together in time,
**When** the view is zoomed,
**Then** lanes are packed against each card's **actual pixel footprint at that
altitude**, not against the calendar date. Two meetings a day apart do not
overlap at 8 pixels per day and do overlap at 210, so a lane assignment fixed at
load time is wrong at every zoom but one.

**Given** a meeting on the timeline,
**When** it is clicked,
**Then** it opens the **meeting view** — that meeting's moments, artifacts,
screenshots and everything else already held for it. The meeting is the
destination; the thread was the route.

**Given** a meeting that carries no date,
**When** the timeline is drawn,
**Then** it is placed at one end and **named as unplaceable**, never
interleaved into the sequence. Guessing a position would fabricate exactly the
chronology this view exists to show.

**Given** a meeting with no screens,
**When** it appears as a stop,
**Then** it is a legitimate stop with its reason stated, never a blank that
reads as a rendering failure, and never "no recording" unless that has actually
been established (AD-18).

**Given** a built thread,
**When** it is displayed,
**Then** the subjects that co-occur with its moments are offered beneath it, so
a thread leads somewhere rather than dead-ending.

**Given** a subject that matches nothing,
**When** it is submitted,
**Then** the view says so plainly and offers nothing it cannot back.

**Partial delivery is acceptable** by owner decision: the query entry, the
suggestions and the left-to-right timeline with its semantic zoom are the spine.
Shipping those without the deepest altitude is better than shipping nothing.

### Story 10.7a: Retire the Thread Catalogue

As a maintainer,
I want `GET /threads` to stop serving a catalogue nobody navigates,
So that the endpoint matches how threads are actually entered. (FR42)

**Acceptance Criteria:**

**Given** story 10.7's query entry,
**When** it lands,
**Then** the unfiltered thread list is no longer the view's front door, and the
endpoint either serves the suggestion query or is scoped to subjects that
actually span meetings — a one-meeting, one-mention row is not a thread by
`domain/threads.py`'s own definition and must not be offered as one.

**Given** the derivation,
**When** it mints identity rows for single-topic clusters,
**Then** those rows keep existing — they are reuse targets that make a rerun
idempotent — but existing is not the same as being served.

### Story 12.5: Artifacts Are Indexed When They Are Made, Not When They Are Published

As a user,
I want to find an artifact as soon as it exists,
So that extraction produces something I can search for rather than something I have to publish before I can locate it. (FR13, FR24)

**The correction this story exists for.** Publishing and indexing are different
concerns and the build has them coupled. Owner, 2026-08-31:

> *"Artifacts need to be indexed before they're published, obviously … otherwise
> how can you find any of those artifacts."*

> *"Publishing them puts them in GitHub or in SharePoint or in some other system
> like Obsidian. So that's the definition of publish."*

**Publish means export to an external system** — a git repository, SharePoint,
Obsidian — and it is a deliberate human act with an audience outside
MeetingMiner. It has never meant "make this findable in MeetingMiner", and
using it as the gate for indexing was a category error.

Measured on the corpus 2026-08-31: **941 artifacts, 0 approved, 0 published,
and the `artifacts` search index holds 0 documents** while `moments` holds 4,940
and `chunks` holds 6,570. Every ADR and action item the extraction has ever
produced is unfindable, not because anything failed but because the gate for
sending them *out* is also the gate for finding them *in*.

**Acceptance Criteria:**

**Given** an artifact,
**When** it is created by the extract stage,
**Then** it is indexed and findable **immediately**, in whatever state it holds.
Its lifecycle state is not a condition of being indexed.

**Given** the publish gate,
**When** it runs,
**Then** it governs **export only** — writing the markdown to the publish root
and committing an ADR to the git repository rooted there. Publishing remains a
human act on human judgement (AD-6) and nothing here weakens it; what changes is
that it stops standing between an artifact and the search box.

**Given** AD-18,
**When** an artifact is indexed or rendered,
**Then** it carries **its lifecycle state in the indexed record itself** —
`extracted`, `approved` or `published` — and every surface that shows one says
which. Unreviewed machine output must never read the same as reviewed output,
and a reader must be able to tell a draft from a decision a human has stood
behind. A test pins the state's presence in the record, not only in the UI.

**Given** story 12.4's ungated indexing of extraction documents,
**When** this story lands,
**Then** it **reuses that mechanism rather than carving a second bypass** —
"this row type is indexed ungated" is a declaration, and artifacts are the
second row type to make it.

**Given** an unapproved artifact appearing in a cited answer,
**When** the citation is followed,
**Then** it resolves to its moment and replays, exactly as any other citation
does — an artifact is moment-anchored and genuinely citable, which is the
difference between it and an extraction document. **Whether an `extracted`
artifact may ground an answer at all, or only be found by search, is an owner
decision this story must surface rather than assume**; the honest default is
that it is findable and clearly labelled, and that an answer says what state
the thing it cites is in.

**Given** the projections module,
**When** artifacts are indexed on creation,
**Then** `projections` remains the sole writer of both stores (AD-4), `rebuild`
still regenerates them from Postgres and `config.yaml` alone, and no evidence
file is opened.

**Given** `docs/architecture.md` and the architecture spine,
**When** this story lands,
**Then** both record that publish means export to an external system, because
AD-4 currently describes the gate as governing what search and chat operate
over, and that is the sentence this story overturns.
