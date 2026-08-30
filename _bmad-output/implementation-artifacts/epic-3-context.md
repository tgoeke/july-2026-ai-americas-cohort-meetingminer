# Epic 3 Context: Search & Cited Q&A

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Make the evidence corpus both discoverable and trustworthy to interrogate. Users can find a meeting, topic, or mention through full-text search and ask natural-language questions across the graph and text retrieval stores, including the participant-and-topic traversal behind “I already explained this to Rowan.” Every answer must trace claims to replayable moments through a deterministic validation gate, so the system never presents an uncited factual answer.

## Stories

- Story 3.1: Corpus Search
- Story 3.2: Graph Traversal Templates
- Story 3.3: Cited Q&A with Deterministic Citation Gate
- Story 3.4: Chat UI with Streaming & Replay Citations

## Requirements & Constraints

- Search must support meeting-name, topic, and mention queries. It is typo-tolerant and returns highlighted results from a hybrid keyword-plus-vector full-text index over transcript and OCR text.
- Every search result must expose at least one resolvable `momentId`. Following it takes the user from search results to candidate meetings and a transcript with the matched mentions highlighted and inline replay available where evidence permits.
- Structural questions are deterministic graph queries. The required templates cover screen history across meetings in time order and participant → meetings → topics → moments, returning the moments in which a named participant was present for a topic discussion.
- Template results retain the Postgres-minted moment UUID unchanged, and each traversal template must be unit-tested against known fixture data.
- `/chat` classifies a question to a traversal template, retrieves deterministically from Neo4j and Meilisearch, and passes retrieved moments to the configured chat LLM for answer synthesis. The draft uses `[[moment:<uuid>]]` citation markers.
- Before any answer leaves the API, every marker must resolve against Postgres and become a structured citation. Answers with an unresolvable marker or an uncited factual claim are rejected; prompt instructions are not an acceptable substitute for this gate.
- Search and chat can retrieve evidence and published artifacts only. Unpublished artifacts must neither appear in results nor reach chat synthesis.
- A valid chat response streams the pinned SSE events `chat.token`, `chat.citations`, and `chat.done`. When no citable answer can be returned, the UI explicitly communicates that state instead of rendering an uncited reply.

## Technical Decisions

- Postgres is authoritative. A moment ID is minted there once and carried verbatim into Neo4j, Meilisearch, search results, and chat citations; the stores are rebuildable read projections rather than alternate sources of truth.
- Graph retrieval uses hand-written, parameterized Cypher templates against Neo4j. No library may auto-extract or own graph structure. The LLM may classify a question to a template and synthesize prose, but it does not determine graph traversal.
- Meilisearch provides typo-tolerant, highlighted, hybrid keyword-plus-vector full-text retrieval. The projections module computes embeddings through the configured embedder port; store-native auto-embedders remain disabled so rebuilding stays deterministic.
- All writes to Neo4j and Meilisearch go through the projections module. Evidence projects at ingest completion; artifacts project only after their Postgres lifecycle reaches `published`. This publication gate is the structural safeguard against draft leakage.
- The chat LLM is the project-owned `Llm(chat)` port, configured in `config.yaml`; its documented default is `claude-sonnet-5` with an Ollama fallback. Model bindings must remain replaceable without feature-code changes.
- The API citation validator is the single citation conversion point. It resolves markers to `momentId`, `meetingId`, `startMs`, `endMs`, and optional `screenshotId` and `sourceDeepLink`; the validator, web app, and evals share this wire contract rather than separately parsing markers.
- API payloads use camelCase, while server-side Python and Postgres names use snake_case. Video offsets are integer milliseconds from recording start.

## UX & Interaction Patterns

- Search follows: query → candidate meetings → transcript with highlighted mentions → inline replay.
- Chat citations render from the structured citation array only; the web app must never parse the inline LLM marker syntax.
- A citation opens replay at its `startMs` when video exists. For transcript-only meetings, it links to the relevant moment/transcript position; the optional source deep link supports the transitional original-recap affordance when there is no replay evidence.
- Citation links lead to the established moment view, where replay is available when the meeting has recording evidence.

## Cross-Story Dependencies

- Corpus search and graph templates require ingest-complete evidence projections from earlier work, plus stable Postgres moment IDs for cross-store resolution.
- Cited Q&A consumes the deterministic Meilisearch and Cypher retrieval established by Stories 3.1 and 3.2, then depends on Postgres moment rows for citation validation.
- The chat UI consumes Story 3.3’s structured citations and SSE event names, and reuses Epic 2’s moment view as the citation destination.
- Published artifact retrieval depends on Epic 4’s approval and projection path; drafts remain excluded until that lifecycle transition.
