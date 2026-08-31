# Epic 10 Context: Moments & Threads

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Make Moments the product's front door so the most pressing evidence appears first with an explicit reason and immediate replay, while Threads lets a user follow one topic across meetings through a continuously zoomable timeline from corpus-scale bands to moment-backed evidence. The epic makes topics and threads first-class navigation anchored to durable moments: machine-derived and visibly labeled, human-curatable at the thread level, and never presented as facts without moment citations.

## Stories

- Story 10.1: Topic Extraction
- Story 10.2: Threads and the Graph Projection
- Story 10.2a: Thread Curation
- Story 10.2b: Thread Questions in Chat
- Story 10.3: Thread Timeline API with Level-of-Detail
- Story 10.4: Moments Feed Ranking
- Story 10.5: Moments View and Front Door
- Story 10.6: Threads Zoomable Timeline
- Story 10.6a: Evidence Tier and Inline Replay

## Requirements & Constraints

- Extract per-meeting topics through the configured extraction-model port and a strict parser. Each topic has a name, gist, and valid moment anchors; out-of-range anchors fail by name, and a contentful meeting that yields no topics is reported rather than silently accepted.
- Derive threads corpus-wide from stored topics using normalized names and configurable embedding similarity. Derivation is idempotent, while human rename, merge, and split decisions persist across extraction and derivation reruns.
- Rank Moments deterministically from stored signals only. Request-time ranking makes no model call, exposes the ordered reasons that produced the result, and drops and logs invalid or unresolvable items before pagination.
- Risks and open questions are persisted, moment-anchored ranking signals, not publishable artifact kinds. They are replaced on extraction rerun and render as literal reason text rather than artifact chips.
- Timeline APIs return only the requested level of detail: bands, meetings, moments, or evidence. Coarse requests are bounded by the requested time window, and every displayed detail ultimately resolves to a moment.
- Chat may use deterministic thread traversal for “over time” questions, but the existing citation gate remains unchanged: answers cite moments, never topics or threads.
- Failures and degradation are explicit. Clients keep trustworthy stale content where specified, reject invalid wire data as a page-level contract error, and never invent missing counts, reasons, identity, time, or evidence.

## Technical Decisions

- Postgres remains the record of truth; Neo4j and Meilisearch are derived read stores with one projection writer. Topic and Thread graph nodes are navigation metadata outside the artifact publish gate, and rebuilds never mint primary thread rows.
- Topic and thread rows are worker-owned and machine-derived; API-owned curation rows overlay them. Topics are replaced per meeting on extraction rerun. Thread identity is content-derived so unchanged inputs retain the same IDs, and aliases ensure curation survives reruns.
- Thread derivation is a separate corpus-wide operation after ingestion and before projection rebuild. A temporarily unthreaded topic is valid intermediate state.
- Graph retrieval uses registered, parameterized traversal templates. Models may classify a question and synthesize cited prose, but do not build or own graph structure.
- Thread identity color is server-owned: a transactional per-corpus sequence assigns an immutable positive `colorOrdinal`, never recycled. The client maps ordinals to an eight-hue palette and lap treatment; filtering and sorting never recolor a thread.
- Timeline placement uses the server's canonical RFC 3339 UTC `occurredAt`, with source precision preserved and stable ID tie-breaks. `startMs` remains a replay offset and is not used by clients to reconstruct cross-meeting wall-clock time.
- Screenshots and recordings are addressed by opaque media IDs. A client never receives or assembles storage paths.
- Configured inputs include the visible topic-extraction prompt, thread-linking rule and similarity threshold, and every Moments ranking weight, each with recorded rationale.

## UX & Interaction Patterns

- The app is dark-only and data-dense. Moments is `/`, Threads is the second primary destination, and Meetings retains the prior home content. Search, Ask, Add meeting, navigation, and health stay in sticky chrome on every route.
- A Moment card states its API-supplied reasons verbatim, shows its evidence screenshot when present, and offers inline replay plus links to the moment and meeting. At most one card is expanded. Card keyboard order is title, Replay, Open moment, source link, expanded player controls, then kind and thread chips.
- Counts are part of headings and distinguish visible from corpus totals when filtered. Filters precede ranked cards; paging uses a button, moves focus to the first new card, and announces the new visible count. Infinite scroll, autoplay, result toasts, modals, and hover-only actions are prohibited.
- Only the seven artifact kinds use kind chips, always with a glyph. Thread hue comes only from `colorOrdinal`; lap two is hatched and ordinals beyond the palette are grey, with the thread name always carrying identity.
- The Threads surface uses continuous semantic zoom with tier thresholds and hysteresis. Items keep the same horizontal position across tier changes; requests are window-bounded, debounced, cached by window/tier/pinned threads, and guarded against stale responses. Reduced motion removes easing without removing access.
- Accessibility targets WCAG 2.2 AA, 200% text resize, and 320 CSS-pixel reflow. DOM order follows reading and focus order, targets are at least 24×24 CSS pixels, screenshots have factual alt text, replay has client-generated transcript captions, and timeline tiers are exposed as a keyboard-operable DOM grid with concise live announcements.

## Cross-Story Dependencies

- Topic extraction feeds thread derivation and projection. Thread curation and chat traversal depend on stable derived thread identity. The thread-list and timeline APIs supply both curation UI data and every visual timeline tier.
- Moments ranking supplies the front-door feed. Timeline levels supply the zoomable Threads view; its deepest evidence and replay tier extends the same timeline without changing screens.
- The corpus must include recurring meetings so cross-meeting threads have meaningful data. Epic 6 ingestion therefore precedes this epic, and the close-out walkthrough follows it.
- Shell recomposition must keep prior Meetings content and established child routes reachable. Shared replay behavior must remain compatible with existing moment, meeting, and speaker flows.
