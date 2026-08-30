# Adversarial Review — ARCHITECTURE-SPINE.md (meetingminer)

**Lens:** adversary. Method: construct pairs of units one level down that each obey every AD to the letter yet build incompatibly. Every surviving pair is a hole; each gets a minimal AD tightening.

**Assumption held throughout:** each builder (pipeline epic, API epic, web epic, projections epic, evals epic, puller) reads only the spine plus the spec it cites. Nothing is "obvious" across epics.

**Verdict: SOUND CORE, FIVE REAL SEAMS OPEN.** The paradigm (Postgres-of-record, single projection writer, disjoint table ownership) kills most classic incompatibilities, but the spine leaves the *intake handshake*, the *puller↔pipeline drop schema*, the *participant table's writer*, the *eval harness's invocation surface*, and the *embedding ownership chain* unfixed — each one supports two AD-compliant builds that do not compose.

---

## CRITICAL

### C1. Nobody may legally create the Meeting row at intake — so both the API and the worker will

- **Units:** API epic vs worker/pipeline epic (web epic is collateral).
- **The clash.** AD-11: "The API enqueues work by inserting a job row." AD-5: the *worker* writes the meetings table; the API may not. ERD: `JOB ||--|| MEETING : ingests`. Read literally, the API must insert a job row that is 1:1 with a Meeting that does not exist yet and that the API is forbidden to create.
  - *Build A (API epic):* POST `/meetings` mints the Meeting row (natural REST reading of `/meetings/{id}/moments` in the conventions table; also lets the web show the meeting immediately). Violates AD-5 in spirit but the builder will read "meeting metadata is user-facing, so it's user-declared data, which I own."
  - *Build B (worker epic):* worker's first pipeline stage mints the Meeting from `metadata.json` (AD-5-literal). Job row carries only a drop path; no `meeting_id` exists at enqueue time.
  - *Build C (worker epic, equally legal):* worker watches a drop inbox directory and self-enqueues — "the puller emits drops, the pipeline consumes drops" (AD-1) never mentions the API, and the structural diagram's `puller -.-> pipeline` arrow bypasses the API entirely. Now ingestion has two entry points (folder watcher + API enqueue) and drops double-ingest.
  - *Web collateral:* the web epic must decide whether upload returns a `meetingId` or only a `jobId`, and which one the SSE progress stream is keyed by. It will guess.
- **Why it survives code review:** each build is internally complete and AD-cited; the conflict only appears at integration, when the demo path (paste URL → puller → drop → ...UI shows progress) has either zero or two triggers.
- **Minimal tightening (new AD or AD-11 amendment):** *Intake handshake.* (1) Drops land under `MM_CONTENT_ROOT/drops/<drop-id>/`; nothing watches this directory. (2) Ingestion is triggered only by `POST /jobs` with the drop path; the API inserts the job row (`drop_path` set, `meeting_id` NULL) and returns `job_id`. (3) The worker's first stage (`probe`) mints the Meeting row from `metadata.json` and back-fills `job.meeting_id`. (4) The web tracks `job_id` until the job row carries `meeting_id`; the job SSE stream includes `meetingId` once set. ERD edge relaxes to `JOB ||--o| MEETING`.

### C2. The drop contract — the only puller↔pipeline seam — has no schema

- **Units:** puller (black box, own repo conventions, own `.env`) vs pipeline `probe` stage.
- **The clash.** AD-1 makes the source drop "the only contract" between puller and server, then specifies it as "one directory containing the video file, an optional transcript (VTT), and `metadata.json` (source kind, meeting metadata, participants)." That is a description, not a contract. Two compliant builds:
  - *Puller:* writes `{ "source": "teams", "subject": "...", "startDateTime": "...", "attendees": [{"displayName": "...", "upn": "..."}] }`, video as `recording.mp4`, transcript as whatever filename Graph returned.
  - *Pipeline:* expects `{ "sourceKind": "teams|local", "title": ..., "startedAt": <ISO-8601 UTC>, "participants": [{"name": ..., "email": ...}] }`, video as the only `*.mp4` glob, transcript as `transcript.vtt`.
  - Neither builder is wrong; AD-1 explicitly forbids them from sharing code, so there is no common type to converge on. The first real Teams drop fails to parse during demo week.
- **Also unfixed:** which participant identity key Graph resolution yields (UPN? email? AAD object id?) — this feeds C3 directly; file naming inside the drop; whether local-recording drops still require `metadata.json` (AD-1 says participants "may" be omitted — may the whole file be omitted?).
- **Minimal tightening (AD-1 amendment):** pin the drop layout in the spine itself (it is small): `metadata.json` is required for every drop and carries `schemaVersion: 1`, `sourceKind: "teams" | "local"`, `title`, `startedAt` (ISO 8601 UTC), optional `participants: [{name, email}]` (email is the identity key, lowercased); video file is `recording.mp4`; provided transcript, when present, is `transcript.vtt`. Unknown extra keys are ignored (puller may keep richer Graph payloads elsewhere in the drop; server never reads them).

### C3. PARTICIPANT has two owners — or, read literally, none

- **Units:** worker/pipeline epic vs API epic.
- **The clash.** AD-5 enumerates the worker's evidence tables: "meetings, screens, screenshots, moments, transcripts" — **participants is absent**. The API owns "participant edits." AD-1 says Teams drops arrive with resolved participants that ingestion persists. So:
  - *Literal build (worker):* worker may not write the participants table ("outside that split, neither process writes the other's tables"), so Teams-resolved participants are... dropped? No compliant path exists.
  - *Pragmatic build (worker):* worker treats participants as evidence and inserts rows + attendance edges at intake. Simultaneously the API epic, reading "the API writes user-declared data (… participant edits)," builds full CRUD on the same table with its own dedup convention. Two writers of one entity — exactly what AD-5 exists to prevent — with divergent identity keys (worker dedupes on UPN from Graph, API dedupes on display name typed by the user). The Rowan demo (participants → meetings → topics → moments) then splits one human across two rows and the traversal silently returns half the meetings.
- **Minimal tightening (AD-5 amendment):** add participants to the split table list with a column/row split: the worker **upserts** participant rows keyed by normalized email (from `metadata.json`) and owns the meeting↔participant attendance edges for drop-borne data; the API inserts human-declared participants (local drops) and edits display fields, and may attach/detach attendance for local meetings only. One identity rule for both: a participant is unique by lowercased email; email-less human-declared participants are unique by name within the instance and get merged by an API-side merge action, never automatically.

---

## HIGH

### H1. The eval harness has no legal way to run — so it will pick an illegal one that breaks the publish gate

- **Units:** evals epic vs API epic + projections epic.
- **The clash.** `evals/` appears in the source tree and the structural diagram ("worker -.-> pytest eval harness drives evals") but **not in the dependency graph**, whose rule is "anything not drawn is forbidden." Two compliant-looking escapes:
  - *Build A (evals):* pytest imports `server/pipeline` and drives stages directly per meeting — fast, hermetic, and it satisfies "worker … drives evals" as drawn. But it bypasses AD-11 job checkpointing and AD-5 ownership; worse, for check 2.11 (publish-gate projection) it flips the artifact lifecycle column in Postgres directly — evals is not a party to AD-5, so the builder reads the split as not applying to them. The projections publish gate (which lives inside the module, AD-4) never fires, so "approve it; assert it appears in BOTH" fails — or the evals builder "fixes" it by calling `server/projections` directly, minting a second publish path.
  - *Build B (API):* meanwhile the API epic builds approval assuming it is the *only* publish trigger (AD-4: "invoked … by the API at publish/unpublish").
  - Also unfixed: AD-10 says "the eval harness snapshots the full resolved config" — from where? Reading `config.yaml` off disk races against the API's resolved view (defaults, per-role fallbacks).
- **Minimal tightening (new AD):** *The eval harness is a client, not a component.* Evals drives the system only through public surfaces: it places drops and calls the HTTP API (enqueue, poll job SSE, search, chat, approve/publish); it never imports `server/*` and never writes any store. Its only privileged access is read-only Postgres/Meili/Neo4j queries for asserts. Config snapshot comes from a `GET /config` (secrets redacted) so the snapshot is the resolved view the run actually used. Add `evals → api (HTTP)` to the dependency diagram as a dashed client edge.

### H2. Embeddings: the only module allowed to write Meilisearch is forbidden to compute them

- **Units:** projections epic vs pipeline epic (API epic for artifacts).
- **The clash.** AD-8 defines an `Embedder` port; the Deferred note says "embeddings currently serve Meilisearch hybrid." But the dependency graph draws no `projections → adapters` edge — so projections, the sole Meili writer, **cannot call the Embedder**. Three compliant divergent builds:
  - *Projections A:* configures Meilisearch's built-in embedder (REST source → provider endpoint) so Meili embeds at index time. Obeys AD-4 to the letter; silently violates AD-8/AD-10 (a model call outside the ports, bound outside `config.yaml`) and breaks the rebuild guarantee's determinism.
  - *Pipeline B:* computes evidence embeddings via the Embedder port and stores them in pgvector, expecting projections to copy vectors into Meili as user-provided vectors. Compatible with rebuild-from-Postgres-alone; incompatible with Projections A (double embedding, two vector spaces).
  - *Artifacts:* published-artifact re-indexing (CAP-9) needs artifact embeddings; who computes them — API at publish (api → adapters is drawn) or nobody? Unstated.
- **Minimal tightening (AD-8/AD-4 amendment):** embeddings are domain data: computed only through the Embedder port by the pipeline (evidence, at ingest) and by the API at publish (artifacts), and persisted in Postgres (pgvector). Projections copies stored vectors into Meilisearch as user-provided vectors; Meilisearch's own embedding integrations are forbidden. This also makes `rebuild` truly Postgres-only (no model calls during rebuild).

### H3. Citation wire format: validator, web renderer, and eval check each need a shape nobody fixed

- **Units:** API epic (chat + citation validator) vs web epic; evals epic collateral (check 2.5's "cited timestamp").
- **The clash.** AD-6 fixes citation *identity* (Postgres moment ID, verbatim everywhere) but not citation *encoding*. The chat answer is an SSE token stream; the validator must parse claims↔citations out of it; the web must render replay links; eval 2.5 needs a cited timestamp.
  - *Build A (API):* LLM emits inline markers `[moment:<uuid>]`; validator regex-scans the final text; SSE is pure `token` events; web is expected to parse markers out of prose.
  - *Build B (web):* renders a citations footer from a structured terminal SSE event `citations: [{momentId, meetingId, startMs}]` and treats answer text as plain prose. Against Build A it renders raw `[moment:…]` goo and no replay links; against a validator that only checks "at least one ID somewhere," per-claim traceability (the "no citation, no answer" constraint) is unenforceable.
- **Minimal tightening (AD-6 amendment + conventions row):** fix the chat wire contract: the synthesis LLM must emit inline markers in the fixed form `[m:<moment-uuid>]` after each factual claim; the validator strips and verifies them (every claim-bearing sentence carries ≥1 resolvable marker, else the whole answer is rejected and replaced by the refusal shape); the API then emits a terminal SSE `citations` event `[{momentId, meetingId, startMs, endMs}]` resolved from Postgres. Web renders from the terminal event only; eval 2.5 reads `startMs` from it.

---

## MEDIUM

### M1. Meilisearch "document" granularity vs the eval's and CAP-9's hit contract

- **Units:** projections epic vs evals epic + API epic (search endpoint).
- **The clash.** Deferred: "Meilisearch index settings … owned entirely by projections … decided at build." But eval 2.10 asserts "a **moment** from the containing meeting appears in the top 5," and CAP-9's success needs every hit citable/replayable. AD-4 lists four evidence types projected (meetings, moments, screens, transcripts) — projections may legally build four indexes with meeting-level transcript documents; the API's search endpoint builder may legally query one "corpus" index; eval 2.10 then fails structurally (planted phrase hits a transcript doc, not a moment) with no bug anywhere.
- **Minimal tightening (AD-4 or conventions):** index internals stay deferred, but fix the *result contract*: every Meilisearch hit returned by the search API resolves to at least one moment ID (a hit either is a moment document or carries `momentIds`), and the search API returns one merged hit list in that shape. Planted-phrase text must be searchable at moment granularity.

### M2. Artifact lifecycle has an `unpublish` invocation but no unpublish state

- **Units:** API epic vs projections epic vs web epic.
- **The clash.** AD-4 says projections is invoked "by the API at publish/**unpublish**"; the state machine everywhere else is strictly forward: `extracted → approved → published`. The API builder must invent the reverse transition (to `approved`? `extracted`? a new `retracted`?); the projections builder must invent deletion semantics (remove from both stores? tombstone?); the web builder decides whether an unpublish button exists; and nobody knows what happens to the already-made git commit (CAP-6). Three private inventions, one entity.
- **Minimal tightening (conventions row):** either delete "unpublish" from AD-4 (capstone is forward-only; corrections go through re-extraction) — cheapest — or fix it: `published → approved` is the only reverse transition, API-only; on it, projections deletes the artifact from both stores; the git history is append-only (a retraction commit, never a rewrite).

### M3. Cross-meeting SCREEN rows vs AD-11 "rerunning a stage overwrites its own outputs"

- **Units:** pipeline `screens` stage vs everything referencing SCREEN (projections, web screen-lineage view, other meetings' screenshots).
- **The clash.** CAP-2 makes SCREEN a cross-meeting entity ("recognizes the same screen across meetings"); AD-11 makes stage reruns overwrite their own outputs. A rerun of meeting A's `screens` stage that re-clusters may delete/replace SCREEN rows that meeting B's screenshots FK to — legal under AD-11 ("its own outputs"), corrupting under CAP-2. Conversely a builder who treats SCREEN as immutable-global can't honor "deterministically overwrites its own outputs" for that stage and will invent a third semantics.
- **Minimal tightening (AD-11 or AD-13-style note):** SCREEN rows are append-only global entities; a stage rerun re-links its meeting's screenshot→screen edges (its own outputs) but never deletes or mutates a SCREEN row referenced by another meeting; orphaned SCREEN rows are garbage, cleaned only by `rebuild`-adjacent maintenance, never by stage reruns.

### M4. Job-progress SSE vocabulary is uninvented on both sides

- **Units:** API epic vs web epic.
- **The clash.** The conventions table mandates SSE for job progress but not the event names or payload shapes, and SSE payloads are invisible to the `@hey-api/openapi-ts` generated client (OpenAPI covers REST, not event bodies) — so the usual type-sharing safety net is absent exactly here. Likely divergence: API streams raw job_stage rows in snake_case (the "conversion at the API boundary" rule is easy to drop on a hand-rolled SSE path); web expects camelCase `progress` events with a percentage. Both compile; the progress bar shows nothing during the live demo's ingest.
- **Minimal tightening (conventions row):** job stream events mirror job/job_stage rows one-to-one: event `stage` with camelCase data `{jobId, meetingId?, stage, status: queued|running|done|failed, error?}` plus terminal event `done`/`failed`; chat stream events are `token`, `citations` (per H3), `done`, `error`. camelCase applies to SSE data exactly as to REST bodies.

---

## LOW

### L1. Read-path ambiguity: API direct store reads vs "projections queries"

The dependency graph gives `api → projections` and the capability map says CAP-3 uses "projections queries," but the structural diagram draws `api → neo & meili` directly. An API builder may hand-roll Cypher in `server/api`, scattering AD-7's traversal templates across two modules. One sentence fixes it: all Neo4j/Meilisearch access (read and write) goes through `server/projections`; AD-7's Cypher templates live there; `api` calls its query functions. (The structural diagram's arrows then describe process-level connectivity only.)

### L2. Moment temporal shape

Conventions fix ms offsets and "a moment carries both" (offset + wall-clock) but not whether a moment is a point or an interval. Pipeline (mints), web (replay clip), citation validator (2.5 window), and projections all touch it. One conventions cell: a moment carries `startMs` and `endMs` (`endMs ≥ startMs`) plus wall-clock start; citations and eval 2.5 use `startMs`.

---

## Attacks that failed (the spine holds)

For completeness — pairs constructed and defeated by existing ADs:

- **Two owners of an artifact row** (worker extraction vs API lifecycle): defeated by AD-5's explicit column split.
- **Neo4j/Meili shape drift between two writers:** defeated by AD-4 single-writer + Deferred note; granularity contract aside (M1), shape divergence is structurally impossible.
- **Draft artifacts leaking into retrieval:** gate lives inside the sole writer (AD-4); eval 2.11 defends it — provided H1's tightening makes evals go through the API.
- **ID/citation mismatch across stores:** AD-2 + AD-6 + the UUIDv7 convention close every variant tried.
- **Provided-transcript clobbering on stage rerun:** AD-13 exists precisely for this and is airtight.
- **Config/env divergence between worker and API:** AD-10 single file; the puller exemption is explicit.
- **Container/host capability mismatch:** AD-9 is unambiguous.

## Disposition summary

| ID | Severity | Seam | Fix locus |
|---|---|---|---|
| C1 | Critical | API vs worker vs web — intake trigger + Meeting minting | New AD / AD-11 |
| C2 | Critical | puller vs pipeline — drop schema | AD-1 |
| C3 | Critical | worker vs API — participants ownership + identity key | AD-5 |
| H1 | High | evals vs API/projections — invocation surface, publish path | New AD + dep graph |
| H2 | High | projections vs pipeline/API — embedding ownership | AD-8/AD-4 |
| H3 | High | API vs web vs evals — citation wire format | AD-6 + conventions |
| M1 | Medium | projections vs evals/API — search-hit granularity contract | AD-4/conventions |
| M2 | Medium | API vs projections vs web — unpublish state | Conventions |
| M3 | Medium | pipeline rerun vs cross-meeting SCREEN | AD-11 note |
| M4 | Medium | API vs web — SSE event vocabulary | Conventions |
| L1 | Low | api vs projections — read path | One sentence |
| L2 | Low | all — moment interval shape | One conventions cell |

All fixes are tightenings of existing ADs or one-row conventions additions except C1 and H1, which each warrant a short new AD. Nothing found contradicts the paradigm; every hole is an unpinned seam between epics, which is exactly what a build-substrate spine must pin.
