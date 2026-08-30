# Epic 2 Context: Evidence Exploration & Replay

<!-- Generated from planning artifacts. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Let a user open any moment and see its full evidence context — still screenshot on top, covering transcript section below, right rail of extracted analytics, full audio+video replay — drill into a meeting's screenshot series with highlighted mentions and inline replays, and curate the human-owned data the system never infers (participant name edits and merges, series/project/product assignment). The epic delivers the core product promise that verifying a claim against its source takes seconds, not a meeting rewatch, and it builds the media-streaming foundation every later citation replay depends on.

## Stories

- Story 2.1: Media Streaming & Replay Foundation
- Story 2.2: Moment View
- Story 2.3: Meeting Drill-Down with Screenshot Series
- Story 2.4: Participant Curation
- Story 2.5: Series, Project & Product Assignment

## Requirements & Constraints

- Media (video, screenshots) streams from the API by resolving DB-stored relative paths against configured roots; replay opens HTML5 video positioned at the cited `startMs`. Range requests must return partial content so video can seek.
- Moment view anatomy is fixed: screenshot top, transcript section below, right rail of extracted analytics (action items, ADRs, decisions, stories, requirements, bug fixes, change requests), replay button. The right rail reads artifacts of any lifecycle state from Postgres via the API — the only place unpublished artifacts may appear — and must show an explicit empty state before Epic 4 delivers extraction.
- Meeting drill-down shows the captured screenshot series in timeline order (UI screens, slides, or participant headshots when nobody presents), each labeled with view classification and timestamp; transcript mentions highlighted, each transcript region linked to its moment; inline video replays play from an offset without leaving the page.
- Transcript-only meetings render in degraded mode: no screenshot, no inline replays; a transitional source deep link to the original recap stands in for the replay affordance; transcript, highlighted mentions, moment links, and right rail stay fully functional. The link retires when a recovered recording later augments the meeting.
- Series membership, and project/product assignment, are human-declared via the API only — never inferred.
- Participant display-name edits and duplicate merges (the human half of participant management) go through the API and must survive re-ingests and stage reruns.
- API errors are RFC 9457 `application/problem+json`. Path traversal outside the storage roots must be impossible; a media path that fails to resolve returns an RFC 9457 error.

## Technical Decisions

- **Two storage roots, relative paths only.** Arrived material (recording, transcripts, metadata) lives in its write-once drop under `MM_DROPS_ROOT`; produced material (frames, screenshots, audio) lives under `MM_CONTENT_ROOT` at `meetings/<meeting_id>/<subdir>/`. No absolute path is stored in the DB or leaves the server; the recording is served out of its drop, never copied under the content root. Known gap the architecture assigns to this epic (story 2.1a): `MM_DROPS_ROOT` doesn't exist in code yet, `job.drop_path` is stored absolute and returned by `GET /jobs`, and `transcript_source.drop_relative_path` holds a bare filename instead of `<drop-dir>/<filename>` — widen and backfill.
- **Serve files by row, never by client path.** Every evidence file has a Postgres row (root-relative path, anchor, `sha256`, `byte_size`, producing stage). The API resolves a media request by looking up the row from an id and joining its recorded path to the configured root — never by joining a client-supplied path onto a root, and never by composing a stored value with a hardcoded filename constant.
- **Table ownership is disjoint.** The API writes user-declared data (series membership, project/product assignment) and the human-curated participant columns; worker-owned evidence and intake columns are untouched. A participant merge writes an API-owned alias row (`alias_key → surviving participant id`); the worker resolves identity keys through the alias table before any insert, which is what makes merges survive reruns. Participant identity keys are namespaced: case-folded mail address when the drop supplied one, else normalized display name (case-folded, parenthetical qualifiers stripped, `Last, First` reordered).
- **Postgres is the sole database of record**; the PRODUCT → PROJECT → MEETING hierarchy and series membership persist there per the ERD and appear in the Neo4j graph projection at next projection or `rebuild`. All store writes go through the single-writer projections module — never edit a retrieval store directly.
- **Time and naming conventions**: video offsets are integer milliseconds from recording start; wall-clock is ISO 8601 UTC; a moment carries both. JSON payloads are camelCase (snake_case in Python/Postgres, converted at the API boundary); REST paths are plural nouns. The web app consumes the API only through the generated TypeScript client driven by the OpenAPI schema.
- **Citation wire format**: structured citations carry `momentId`, `meetingId`, `startMs`, `endMs`, optional `screenshotId`, optional `sourceDeepLink`; consumers replay from `startMs`/`screenshotId` when evidence exists and fall back to `sourceDeepLink` when it does not. Moment payloads follow the same transitional-affordance pattern, and moment IDs (UUIDv7, Postgres-minted) are never re-keyed by augmentation.
- Stack for this epic's surface: FastAPI 0.141.x API, React 19 + Vite + shadcn/ui SPA, @hey-api/openapi-ts generated client; API and worker run as separate macOS host processes, stores in Docker.

## UX & Interaction Patterns

- Screenshots plus transcript segments are what people actually review; video clips are rarely watched but prove derived artifacts correct — design views around scan-then-verify, with replay as proof at the relevant offset.
- Search-to-verify flow: candidate meetings → drill into transcript with highlighted mentions → small inline replays; drill-down and moment view are the landing points for that flow and for later chat citations.
- Two meeting archetypes (slide-deck presentations, UI demos) drive different screenshot types — views must handle both, plus participant-headshot captures.
- Meetings whose evidence stages have not settled must be refused server-side at the detail route, not merely gated by a disabled button in the UI (`evidence_complete` is computed and returned as `viewable`, but no route enforced it when the progress UI shipped).
- A meeting mid-augmentation must be distinguishable from a never-ingested meeting: `viewable` legitimately goes false during an augmenting run (transcript segments are deleted and rebuilt) while the meeting keeps its identity, citations, and projections. Derive the distinction from `job.status` plus stage rows — no schema change — and never key an empty state on `viewable` alone.

## Cross-Story Dependencies

- Story 2.1 (media streaming, Range support, `startMs` positioning) is the foundation; 2.2's replay button and 2.3's inline replays both use its player and endpoints, and Epic 3's chat citations render replay links onto the same mechanism.
- Story 2.2's right rail is the display surface Epic 4's extraction fills; it must work (with empty state) before Epic 4 exists, and unpublished artifacts appear there and nowhere else.
- Story 2.4 completes the human half of participant handling whose intake half shipped in Epic 1; correctness depends on the worker's alias-resolution behavior already in place.
- Story 2.5's series/project/product assignments feed the Neo4j projection that Epic 3's graph traversals (including the "I already explained this to Rowan" query) traverse.
- Degraded transcript-only rendering (2.2, 2.3) pairs with Epic 1's augmentation path: when a recovered recording augments a meeting in place, real screenshots and replay must replace the transitional deep link on existing moments without re-keying them.
