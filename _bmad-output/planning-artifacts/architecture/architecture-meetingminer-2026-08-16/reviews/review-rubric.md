# Rubric Review — ARCHITECTURE-SPINE.md (meetingminer)

- **Reviewer:** rubric walker (architecture-spine reviewer gate)
- **Date:** 2026-08-17
- **Artifact:** `_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md`
- **Driving spec:** `_bmad-output/specs/spec-meetingminer/SPEC.md` + `scope.md` (checked against `eval-strategy.md`, `eval-design.md` for internal consistency)

## Verdict

**Approve with revisions.** The spine is lean, well-aimed at real divergence points, and covers CAP-1..9 with an explicit capability map. No critical findings. One high finding (the cross-language source-drop contract is the least-specified seam in the system) and three mediums (publish/unpublish inconsistency, embedding-dimension conflict between AD-8 and AD-10, silent write-model recovery) should be fixed before builders fan out. The rest is polish.

## Rubric walk

| # | Checklist item | Result |
|---|---|---|
| 1 | Fixes real divergence points, misses none | Mostly — 13 ADs hit the right seams; the one under-fixed seam is the drop-format contract (F-1); write-model recovery silent (F-4) |
| 2 | Rules enforceable, prevent stated divergence | Yes, with two internal inconsistencies that blunt enforcement (F-2, F-3) |
| 3 | Deferred items can't cause divergence | Yes, with one ownership clarification wanted (F-8) |
| 4 | Named tech internally consistent | Yes; minor pin-style inconsistencies only (F-7) |
| 5 | Covers CAP-1..9 | Yes — capability map is complete; one CAP-1 sub-path undefined (F-5) |
| 6 | Every owned dimension decided/deferred/open | Deployment, infra, config, secrets, observability(logging), failure handling(job rows): decided. Backup/recovery of the write model: **silent** (F-4) |
| 7 | Mermaid valid + conveys structure | All three diagrams syntactically valid; two semantic nits (F-6, F-9) |
| 8 | Solo-dev 1-week fit | Good — three stores are spec-mandated, not spine gold-plating; minor over-provisioning in the stack seed (F-7) |

---

## Findings

### Critical

None.

### High

**F-1 — The source-drop `metadata.json` contract is the system's only no-shared-code seam and it is underspecified.** (AD-1; Conventions table)
AD-1 correctly makes the drop the canonical inbox, and the dependency diagram correctly isolates `puller` ("shares no code with the server — its only contract is the source-drop format"). But that contract is described only as "`metadata.json` (source kind, meeting metadata, participants)". Two units in two languages will write and read this file: the JS puller and the Python pipeline. The Conventions table fixes casing only "at the API boundary" (Python `snake_case` vs TS `camelCase`) — it is silent on which casing `metadata.json` uses, and no schema location, version field, or validation mechanism is named. This is exactly the divergence AD-1 exists to prevent, reproduced one level down. It is also not listed under Deferred, so it is currently an unowned dimension.
**Fix:** Add to AD-1 (or a convention row): the drop format is defined by a versioned schema file (e.g. `docs/source-drop.schema.json` or a shared fixture validated by both a puller test and a pipeline intake test), state its casing convention explicitly, and require intake to reject drops that fail validation. One sentence plus one schema file closes the seam.

### Medium

**F-2 — "publish/unpublish" (AD-4) contradicts the one-way lifecycle everywhere else.** (AD-4 vs AD-5, Conventions "State mutation")
AD-4 says projections are "invoked … by the API at publish/unpublish." AD-5 and the Conventions table define the lifecycle as `extracted → approved → published` with no reverse transition, and eval check 2.11 (`eval-design.md`) only tests the forward direction. If unpublish exists, the lifecycle needs a `published → approved` transition and the projections module needs delete/de-index behavior (and the publish folder / git repo need a story for retraction — a committed ADR can't be un-committed). If it doesn't, the word invites a builder to invent it.
**Fix:** Decide one way: either strike "unpublish" from AD-4, or add the reverse transition to the lifecycle, note that git publishes are append-only (retraction = superseding commit), and extend the state-mutation convention accordingly.

**F-3 — AD-8 fixes a 1024-dim vector space; AD-10 makes "embedding model + dimension" a config knob.** (AD-8 vs AD-10; Deferred "pgvector usage")
These pull in opposite directions: if dimension is config-declared, a config edit ("swapping a model is a config edit, never a code change", AD-8) can silently break the Meilisearch hybrid index and any pgvector column, and existing projected vectors become garbage. The spine also never states the obvious consequence that changing the embedder mandates a projection rebuild.
**Fix:** State in AD-8 that the 1024-dim space is a spine invariant; AD-10's config picks only among models emitting that dimension; any embedder change requires the AD-4 `rebuild` CLI to be run before the stores are trusted. (Or, if dimension is genuinely meant to be swappable, say the dimension lives in one place and rebuild is mandatory on change — but pick one.)

**F-4 — Backup/recovery of the write model is a silent dimension.** (Structural Seed; AD-2/AD-4)
The spine answers projection recovery thoroughly (rebuild from Postgres, "never hand-edit a store") but says nothing about how Postgres itself or `MM_CONTENT_ROOT` survive a bad migration, a destructive bug, or a disk mishap the night before the demo. For a one-environment capstone this needs only one line, but the rubric is right that a whole dimension left silent is a finding — and AD-13 already does 80% of the work (drops are immutable after intake).
**Fix:** Add one line to the Structural Seed: source drops are retained immutably under the content root, so full recovery = re-ingest from drops + rebuild projections; optionally a `pg_dump` before the demo/eval run. No new machinery.

### Low

**F-5 — Speaker attribution is undefined for the (local video, no transcript, noop diarizer) path.** (AD-8; CAP-1)
CAP-1 promises a "verified speaker-attributed transcript." Teams drops carry VTT speaker labels and pyannote is an optional adapter, but the default config (diarizer = noop) on a local drop with no provided transcript yields no speakers at all. Fine for the scripted single-presenter capstone corpus, but the spine should say what the degraded output is.
**Fix:** One clause in AD-8 or AD-1: with noop diarization and no provided transcript, segments carry a single "unattributed" speaker; attribution quality is an adapter concern, not a pipeline invariant.

**F-6 — ERD cardinalities overconstrain two human-declared/derived relationships.** (Structural Seed ERD)
`PROJECT ||--o{ MEETING` requires every meeting to have exactly one project, yet project assignment is an API-written human declaration (AD-5) that will be absent at ingest. `MOMENT ||--o{ TRANSCRIPT_SEGMENT` forbids transcript segments that fall outside any moment. Both should be optional on the child side (`|o--o{`). Mermaid syntax itself is valid in all three diagrams.
**Fix:** Loosen the two cardinalities; leave the rest.

**F-7 — Stack seed pin-style inconsistencies / mild over-provisioning.** (Stack)
LiteLLM is the only floating lower bound ("≥1.97") in an otherwise minor-pinned table — inconsistent with the eval reproducibility posture (config snapshot per run, rerun-on-change rule). Both STT engines (mlx-whisper and parakeet-mlx) are seeded, which invites building two adapters in week one when the port plus one engine suffices. Not re-researching currency; no internally contradictory versions found.
**Fix:** Pin LiteLLM to a minor like the rest; mark one STT engine primary and the other "optional, port-proven-by-existence-of-second only if time permits."

**F-8 — Cypher traversal-template ownership is implied but never stated.** (AD-7; Capability map)
AD-7 hands graph-shape ownership to `server/projections` (via AD-4) but doesn't say where the hand-written Cypher templates live. The capability map ("CAP-3 … api (router, validator) + projections queries") implies projections — good, because then node naming (deferred, "owned entirely by projections") and the queries over it are one unit. If a builder instead puts templates in `api`, the deferred naming decision becomes a two-unit divergence.
**Fix:** Add one sentence to AD-7: traversal templates live in `server/projections` alongside the writers; `api` calls them by name.

**F-9 — Deployment-diagram edge label reads backwards.** (Structural Seed, first diagram)
`worker -.->|pytest eval harness drives| evals` draws worker → evals, but the label says the harness drives — the actual flow is pytest driving ingestion/queries and writing `evals/runs/`. Cosmetic; the diagram is otherwise a faithful picture of the single-environment envelope.
**Fix:** Redirect or relabel, e.g. `evals -.->|pytest drives pipeline, writes runs| worker` or split into two edges.

---

## Coverage check (CAP-1..9)

All nine capabilities appear in the Capability → Architecture Map with governing ADs; spot-checks against SPEC intents hold (drop-based ingestion for CAP-1 incl. provided-transcript merge via AD-13; publish gate inside projections for CAP-6/CAP-9 matching eval check 2.11; sequencing constraint for CAP-7 carried into the map; egress terminology conflict between spine and `eval-design.md` §7 explicitly resolved by AD-12). Only gap of note is the CAP-1 speaker-attribution sub-path (F-5).

## Over-engineering check (greenfield, solo, ~1 week)

The spine is appropriately lean: three stores, CQRS-lite, and the rebuild CLI are spec-mandated (CAP-2/CAP-9, rebuildable-projection constraint), not spine embellishment; UUIDv7/RFC 9457/SSE conventions cost nothing; the noop diarizer default and deferred Morning Digest show correct restraint. The only over-provisioning signals are in F-7 (dual STT engines seeded) — nothing structural.
