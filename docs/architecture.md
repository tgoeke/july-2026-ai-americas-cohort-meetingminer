# Architecture

MeetingMiner turns recorded software demonstrations into searchable, citable
evidence. Every extracted artifact traces back to the video moment that produced
it.

This document is the technical contract. It supersedes the per-story planning
record: the decisions below are the ones that constrain everything built from
them, and a change to one is a change to the system's shape, not a refactor.

## System shape

```
  acquisition          →  source drop  →  api  →  worker  →  Postgres
  (Teams puller, or                       │                     │
   mint from a local                      │              projections (sole writer)
   recording)                             │                  ↙        ↘
                                     job row              Neo4j    Meilisearch
                                                        (graph)   (text+vector)
```

1. An acquisition tool finalizes a write-once **source drop**: a directory
   holding a recording and/or a transcript, plus `metadata.json` carrying
   `sourceId`, `corpus`, `startedAt` with its precision, provenance, and a
   best-effort participants array.
2. The only entry point is `POST /ingests` with a drop path. The api validates
   the drop against `docs/source-drop.schema.json` and inserts a **job row**.
3. The worker claims the job and runs eight checkpointed stages in order:
   `probe → frames → ocr → screens → transcribe → align → moments → extract`.
   Transcript-only drops skip the five video stages and segment the transcript
   instead.
4. Produced media is written under the content root keyed by meeting id; arrived
   media stays in its drop. Both are recorded as root-relative paths with
   `sha256` and `byte_size`.
5. **Postgres is the sole write model.** UUIDv7 ids are minted on insert and
   carried verbatim into every downstream store.
6. At evidence-complete the worker calls `projections`, the only writer to Neo4j
   and Meilisearch. Artifacts stay out of both until a human approves them.
7. Query path: `POST /chat` classifies the question onto a parameterized Cypher
   template and/or a search query, retrieves moments, synthesizes an answer with
   `[[moment:<uuid>]]` markers, and validates every marker against Postgres
   before anything leaves the api.

### Data model note — topics (story 10.1)

Topics live beside the evidence as `topic` and `topic_mention` rows:
worker-owned, machine-derived navigation metadata, labelled as such in their
provenance, each mention anchored to the moment where the topic was discussed.
They are not artifacts — they never enter the `extracted → approved →
published` lifecycle — and an extraction rerun replaces a meeting's topic rows
wholesale. Nothing projects them yet; story 10.2 gives the graph its `Topic`
nodes and `MENTIONS` edges.

## Decisions

Seventeen decisions constrain the build. Each states what it prevents, because
that is what makes it worth keeping.

**AD-1 — One canonical inbox: the source drop.** Every source lands as one
write-once directory pinned by a versioned JSON Schema. Ingestion consumes only
drops and never knows the source; the acquisition tool emits only drops and
never knows the pipeline. The two share no code — only the schema and one HTTP
call. Intake refuses symlinked canonical files, because a symlink puts bytes
outside the write-once boundary and makes AD-17's checksums describe mutable
data.

**AD-2 — Postgres is the sole database of record.** Every domain object is
minted as a Postgres row and its id created there and nowhere else. No component
may treat the graph store, the search store, or the filesystem as authoritative,
so no entity ever has two owners and projections cannot drift into primary
copies.

**AD-3 — Binaries on disk, paths in the database, relative to one of two roots.**
A drops root and a content root. Every stored path is relative to exactly one,
chosen by *how the file came to exist*: arrived material stays in its drop,
produced material is keyed by meeting id so it survives a re-emit. Neither root's
absolute location is stored or served, so relocation is an environment change
rather than a data migration.

**AD-4 — Projections have exactly one writer.** All graph and search writes go
through `server/projections`. The publish gate lives inside that module and
refuses any artifact whose Postgres state is not `published`, so drafts cannot
leak into retrieval. Embeddings are computed in-module rather than by store-native
auto-embedders, which is what keeps `rebuild` deterministic.

**AD-5 — Table ownership is disjoint.** The worker writes evidence and job
tables; the api writes user-declared data. Two processes never mutate the same
rows, so no locking machinery is needed. Two tables split by column rather than
by table: artifacts (worker owns content, api owns lifecycle) and participants
(worker inserts on intake, api owns curated columns). A merge writes an
api-owned alias row that the worker resolves before every insert, so merges
survive re-ingests.

**AD-6 — Citations are Postgres-minted moment ids, gated in code.** A moment id
is minted once and carried verbatim into graph nodes, search documents, and
every answer. The chat path ends in a deterministic validator that rejects any
answer whose claims lack resolvable moment ids. "No citation, no answer" is
enforced by that gate, not by prompt instructions.

**AD-7 — Graph retrieval is deterministic traversal templates.** Hand-written
parameterized Cypher against the graph projection. No framework builds, extracts,
or owns graph structure; the model only classifies the question to a template and
synthesizes the cited answer, which keeps retrieval testable.

**AD-8 — All model calls go through configured ports.** Feature code calls
project-owned interfaces — `Ocr`, `Stt`, `Diarizer`, `Llm` per role, `Embedder` —
with every binding from config. Provider SDKs never appear in feature code, so
swapping a model is a config edit. The embedder is the exception: its model and
dimension are part of projection state, so changing it forces a full rebuild.

**AD-9 — Infrastructure in Docker, code on the host, inference wherever
configured.** Compose runs only the stateful stores; api, worker, and the dev
server run as host processes. No pipeline stage may assume a container and no
container may require platform frameworks, which keeps OCR and speech engines
that need host frameworks or GPU access reachable. Local-first governs evidence
and state, not inference: a remote engine is a new adapter behind an existing
port, not an architecture change.

**AD-10 — One config file drives everything.** A single versioned `config.yaml`
declares every adapter binding, model, threshold, and endpoint, and — for each
LLM role — the catalog of bindings that role may be served by plus the default
among them; environment variables carry only secrets, the two root locations, a
checkout's private-stack name and generated incarnation identity, and the host
ports its stores publish. The name and id are infrastructure ownership metadata;
the ports are infrastructure location, applied by the loader to the configured
endpoints rather than written into a second config file. A default outside its
own catalog, an active `model` outside an authored catalog, and a catalog entry
whose derived provider `providers:` does not declare are refused when the file
loads. Provider identity is never declared beside a binding: one
dependency-neutral model-spelling rule drives catalog metadata, call-time
endpoint resolution, and status display; authored provider labels and
ambiguous bare spellings are refused rather than guessed.
A user's selection is user-declared data (AD-5): persisted in Postgres by the
api, resolved at call time by api and worker, and recorded in every eval run's
config snapshot beside the file values. Nothing outside the catalog can be
selected, and no selection is a fallback: a failing binding surfaces as an
error. Bindings cannot scatter across env vars, code defaults, and flags, and
the eval harness snapshots the resolved config into every run so any run is
reproducible.

**AD-11 — Jobs are Postgres rows advanced by the host worker.** The api enqueues
by inserting a row; the worker claims it and advances named stages, checkpointing
each. No broker, and no pipeline work in the api process. Every stage is
idempotent: a rerun deterministically overwrites *its own* outputs — rows keyed
to that job's meeting — while cross-meeting entities are upserted by identity key
and never deleted by a rerun.

**AD-12 — Egress is unrestricted system-wide.** Any configured provider may
receive any content; no system-wide egress filter exists or may be built. The
narrower "judges receive derived data only" rule belongs to the eval design and
stays there.

**AD-13 — Provided transcripts are immutable inputs; merge, never erase.** Drop
contents are read-only after intake. A provided transcript is preserved verbatim
and verification writes *new* derived rows carrying provenance to both the
original and the speech-recognition output. The load-bearing mechanism: where a
transcript was provided, its cue timing owns `start_ms` while the recognition
lane writes to separate nullable columns. That is what pins a moment's identity
when a recording arrives later, and therefore what keeps citations minted before
an augmentation resolving after it.

**AD-14 — One intake door.** The only way evidence enters is `POST /ingests`.
A duplicate `sourceId` with a live job is refused with a conflict — re-processing
is a rerun of the existing job, never a second meeting row. The single exception
is a drop declaring `augments`, which re-arms the existing job in place and
requeues only the stages the new evidence unlocks, so the meeting id and every
moment id, citation, and published artifact naming it survive. No folder
watchers, no worker-side discovery, no direct database seeding.

**AD-15 — One citation wire format.** Synthesis emits inline `[[moment:<uuid>]]`
markers; the api validator resolves each and returns a structured citations
array. The web app renders replay links from that array and never parses markers,
so validator, UI, and eval checks cannot each parse citations differently.

**AD-16 — The eval harness is a client, not a housemate.** It mutates only
through the public api and asserts through read-only access. Eval code never
imports server modules to change state, so it cannot route around the publish
gate it exists to test.

**AD-17 — Every evidence file has a row.** Every file stored or served carries a
Postgres row naming its root-relative path, anchor root, `sha256`, `byte_size`,
and the stage that wrote it. The row is also *how* the file is served: the api
resolves a media request by looking the row up from an id, never by joining a
client-supplied path onto a root. Checksum mismatch is read by anchor — a hard
failure for arrived material, provenance-only for produced material, because
reruns are not bit-reproducible.

## Invariants

These span stories and are the most expensive things to rediscover.

- **Write-once arrived evidence.** A finalized drop is never overwritten,
  renamed, or deleted. Producers assemble in staging and finalize with a single
  atomic rename; an existing target is reported, never written into. Detection of
  "already produced" is by source id, not directory name, because the name embeds
  a mutable date and title.
- **One live job per source id, one meeting per job.** Enforced by a partial
  unique index plus unique constraints. A second job row for the same occurrence
  is a halt condition, not an implementation choice — three constraints rest on
  it.
- **Settlement order is the augmentation signal.** Stages run in one canonical
  order shared by api and worker. A first ingest settles them strictly in that
  order; out-of-order settlement is the mechanical signal that an augmentation is
  in flight. Nothing may be marked done or skipped for an unimplemented stage.
- **Identity is minted once and carried verbatim.** The database UUID is the row
  id, the graph node key, and the search document id. Never a sequence, never an
  ordinal. Moments have deliberately no ordinal column — order is `start_ms` —
  because augmentation inserts moments between existing ones.
- **Fail closed, fail named, fail before writing.** Invalid config, pending
  migrations, an unusable root, an unreadable schema, a vector-dimension
  mismatch: each is a named error with no traceback and a non-zero exit, refused
  before any partial boot or partial store mutation. Every api error body is
  `application/problem+json`.
- **Single writer per store class, proven not asserted.** An import-inspection
  test proves only `projections` writes the stores; an AST walk proves the api
  package opens no store client. Corruption is repaired by rebuild, never by
  hand-editing a store.
- **Never guess.** Speaker labels that do not resolve stay unresolved rather than
  being merged into a resolved person. Wall-clock time is never re-derived from
  media metadata; a drop with no derivable start time is refused. A video-only
  meeting settles with zero transcript rows rather than a synthesized placeholder.
- **Structural before semantic.** Full-text retrieval is a first-class half, not
  a fallback. The structural projection pass never calls the embedder, so a
  meeting indexed with no vectors is fully functional on the dominant query
  shape and the embedding pass resumes independently.
- **Every threshold is configuration.** Sampling intervals, similarity and
  lineage thresholds, dwell rules, chunk size and overlap, moment gap and
  duration caps — all in the versioned config with recorded rationale, never as
  code constants. The config model forbids unknown keys, so a removed key must
  leave the file and every fixture together.
- **Decision cores are pure.** Segmentation, classification, identity, chunking,
  and highlighting are database-free, model-free functions over plain per-item
  facts, unit-testable without any store. The I/O layer measures; the core
  decides.
