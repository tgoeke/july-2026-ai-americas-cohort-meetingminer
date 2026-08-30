# Epic 10 Context: Moments & Threads

<!-- Generated from planning artifacts. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Give the product its front door: a Moments view that opens the app on the most pressing evidence first, each item stating why it ranks, citing its moment, and replaying in place; and a Threads view that follows a topic across meetings on a timeline zoomed like Google Earth — thread bands, then meetings, then moments, then evidence, then inline replay. To support both, topics become first-class, moment-anchored navigation in the database of record and the graph: machine-derived and labeled as such, human-curatable at the thread level, and never surfaced in a chat answer as a fact. Sequenced after Epic 6 so the new corpus lands on the new front door.

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

(Story 10.7 is a retired id, merged into 10.5; ids are stable and never reused.)

## Requirements & Constraints

- The home surface presents moments ranked by a deterministic score over stored signals (decision/ADR artifacts, action items with stated timing, risks and open questions, meeting recency, publication recency, thread membership). No model call happens at request time; the score is a pure, unit-testable function; every card carries a non-empty ordered list of reasons rendered verbatim.
- Topics are extracted per meeting (name, one-line gist, moment anchors) through the same LLM extraction port and strict parser as the existing extraction documents. An anchor outside the timeline fails by name; a contentful meeting yielding zero topics is reported as a signal, never silent success.
- Threads link topics across meetings by normalized name plus embedding similarity above a configured threshold; derivation is idempotent — a rerun over unchanged topics yields the same threads. Human merge, split, and rename survive every rerun; the machine never renames or merges on its own.
- The Threads timeline serves exactly one tier per level (bands, meetings, moments, evidence); each level returns only what it renders, and every detail traces to a moment — nothing invented at any level. Coarse levels are cheap window-bounded aggregates, never a full scan of moments on a corpus of hundreds of meetings.
- Risks and open questions exist as persisted, moment-anchored ranking-signal rows produced through the extraction port; they are not publishable artifacts, never enter the approval lifecycle, and are replaced on rerun.
- Failures surface visibly: a feed item with no valid reason or an unresolvable moment is dropped and logged before pagination; totals count only serializable rows. No silent fallback anywhere.

## Technical Decisions

- Topics and threads are navigation metadata outside the publish gate — an AD-4 clarification recorded in docs/architecture.md as part of story 10.2. The projections module remains the sole graph/search writer and writes Topic and Thread nodes plus MENTIONS edges to moments at evidence-complete.
- Table ownership stays disjoint: the worker owns topic and topic-mention rows (machine-derived, replaced on rerun); the api owns thread curation as alias rows, projected on the next pass. Topics never enter the extracted → approved → published lifecycle.
- Thread traversal is a registered deterministic query template like the existing ones, returning a thread's meetings and moments in wall-clock order with per-level aggregates. The chat classifier may route over-time questions to it; answers still cite moments only and pass the existing citation gate unchanged.
- Thread color identity is server-owned: a transactional per-corpus sequence allocates a unique positive colorOrdinal once, never recycled; a merge survivor keeps its ordinal, a split product gets a new one. The client maps ordinal to hue and lap and never invents or recomputes color.
- Cross-meeting time is server-canonical: RFC 3339 UTC occurredAt derived from meeting start plus the meeting-relative offset; day-precision meetings anchor at midnight UTC with precision preserved and stable id tie-breaks. Clients position by the served value and never reconstruct wall-clock time.
- Media is ID-addressed only — screenshots and recordings resolve through opaque ids on the media routes, never a storage path.
- Configuration carries the knobs with recorded rationale: the topics prompt (served by the extraction-prompts endpoint and visible in the UI), the thread-linking rule and similarity threshold, and every ranking weight.
- Existing conventions apply: RFC 9457 problem responses, camelCase payloads, Postgres-minted ids carried verbatim everywhere, list endpoints returning items/total/limit/offset.

## UX & Interaction Patterns

- The story 6.1 design spines are the design companion; deviations from them are recorded, not silent.
- Story 10.5 recomposes the shell: Moments is the default route, Threads the second primary view; Meetings/Participants/Status/Settings stay reachable; search, ask, and Add-meeting stay persistent chrome. It applies the dark theme class (today the dark tokens exist but are inert), the per-route shell widths (wide for the grid/timeline routes, the existing 1024px for child screens, 720px for the form route), the strengthened focus ring and control-border tokens, and pins child-screen placement and route widths by test (closing B-13). The api health panel leaves the front door for the Meetings view — an existing home test may pin it.
- The timeline is continuous zoom about the pointer or focused item, with ms-per-pixel tier thresholds, hysteresis so a single wheel notch does not flap tiers, short ease-out zoom and cross-fade transitions, and a tested no-layout-jump rule: an item keeps its x across a tier change. Keyboard access is a roving-tabindex grid with tier-local keys; reduced motion swaps instantly; a polite live region announces tier changes once.
- Fetch discipline: fetch the visible window padded 50 percent, debounced, cached by pinned threads + level + bucketed window; stale responses are discarded by generation; a finer tier is never drawn from coarser data; on failure the outgoing tier stays drawn with a refusal box naming the problem.
- Thread bands use eight fixed hues by ordinal (lap 2 hatched, beyond 16 grey); mention density is alpha steps, not hue. Risk/question reasons render as muted text, never kind chips — only real artifact kinds get chips, always with their glyph.
- Screenshots carry the alt pattern "viewType at offset, meetingTitle" (the feed serves viewType for it); the shared replay player gains an optional client-generated captions track from transcript segments, landing with whichever of 10.5, 10.6a, or 7.4 touches it first.
- Banned: toasts for results, infinite scroll (paged "Show 24 more"), autoplay, modal dialogs, hover-only affordances, disabled buttons without a stated reason. Global single-key shortcuts belong to 10.5's chrome; timeline keys to 10.6/10.6a.
- Narrow reflow is in scope: 200 percent text resize and 320px reflow with two-row chrome and one-column layouts; only the labeled timeline scrollport scrolls horizontally.

## Cross-Story Dependencies

- Data flows forward: 10.1 topics feed 10.2 derivation/projection; 10.2a (curation) and 10.2b (chat routing) build on 10.2; 10.3 serves the levels 10.6 renders, and 10.6a adds the evidence tier and inline replay on top of 10.6; 10.4 serves the feed 10.5 renders. 10.2a's merge/split/rename UI lives in 10.6's Threads view; its split panel lists topic membership served by 10.3's meetings level.
- Epic order is 11 → 6 → 10 → 7 → 8 → 9: the test-suite epic and Epic 6 land first, and corpus selection for the close-out should include recurring meeting series so threads have something to show.
- 10.5 must keep the existing corpus counts and meeting cards reachable and the current demo path and web tests green while replacing the home route.
- The replay player changes (optional end offset, captions track) are shared with the speaker-naming work in Epic 7; whichever story touches the player first lands them without breaking existing callers.
