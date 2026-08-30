# Glossary

Terms as this project uses them. Where a term has a precise form in code or in the architecture
spine, the definition gives that form rather than a paraphrase — a glossary that rounds off the
mechanism is how two components end up meaning different things by one word.

Entries marked **⚠ collision** are words this project uses for two different things. Those are the
ones worth reading even if you know the domain.

---

## Evidence and domain objects

**Moment** — the atomic unit of evidence: a span of a meeting that can be cited and replayed.
Carries `start_ms`/`end_ms`, an optional `screenshot_id`, and an `identity_key` unique within its
meeting. Everything the system asserts about meeting content traces to one.

**Moment identity key** — `transcript:<start_ms>` or `screen:<start_ms>`, the key
`(meeting_id, identity_key)` that moment upserts are idempotent on. A span the transcript anchors
takes the transcript key *even when a screenshot coincides*, because the transcript anchor is what
survives a recording arriving later. Only a span that exists solely because a screenshot did takes
a `screen:` key — and that is the one kind of moment a rerun may delete.

**Meeting** — one occurrence of a meeting, minted in Postgres at the worker's first stage and
identified thereafter by its meeting id. Not a meeting *series*: two instances of a recurring
standup are two meetings.

**Occurrence** — a meeting instance as the source side sees it, before ingestion: one dated folder
in the puller's output, one `sourceId`. "Occurrence" is source-side vocabulary, "meeting" is
system-side; they name the same event on opposite sides of the drop contract.

**Screen** — a distinct application screen recognized across meetings. Screen lineage is what lets
"show every discussion of this screen over time" work; screens are cross-meeting entities, upserted
by identity key and never deleted by a rerun.

**Screenshot** — one captured still image, stored on disk under the content root with its path
recorded relative to that root.

**Participant** — a person, deduplicated *across* meetings by `identity_key`. Distinct from a
speaker label, which is what a transcript line is tagged with inside one meeting.

**Participant identity key** — `mail:<address>` when the participant graph supplies a directory
address, otherwise `name:<normalized display name>`. Mail is the primary key and name normalization
the fallback, not the reverse. Resolved through the alias table before any insert, so a human merge
survives re-ingest.

**Match key** — the normalized display name used to match a *transcript label* to a roster entry
within one meeting. Not the same as the identity key, which is what the person is upserted by across
meetings. Conflating them is what makes two same-named humans collapse into one row.

**Normalized display name** — case-folded, parenthetical qualifiers stripped (`(CNTR)` and similar),
`Last, First` reordered to `First Last`, NFKC-normalized.

**Unresolved / ambiguous** — a speaker label that resolves to no participant, or to more than one.
Both states are recorded as such and never merged into a resolved person. In the participant graph,
an external who is not in the directory is marked `unresolved: true` with `org: "Unknown"` — **not**
by the `guest` field, which is `false` on all 225 person-rows corpus-wide.

**Series** — a human-declared grouping of recurring meetings. Never inferred.

**Citation** — a reference from a claim to the moment that supports it. LLM synthesis emits the
inline marker `[[moment:<uuid>]]`; the API's validator resolves each marker and returns a structured
`citations` array (`momentId`, `meetingId`, `startMs`, `endMs`, optional `screenshotId`). The web app
renders from the array and never parses markers.

---

## Ingestion and the drop contract

**Source drop** (or just **drop**) — one write-once directory, the only way evidence enters the
system. Canonical filenames: `metadata.json` (required), `recording.mp4`, `transcript.vtt`,
`transcript.txt`; at least one of the latter three must be present. Every other file in the
directory is ignored at intake. Contents are read-only after intake.

**Drop identity** — the drop directory's name, `<date>-<title-slug>-<sha1(sourceId)[0:8]>`, checked
with a plain filesystem existence test. Two drops for one occurrence therefore need a discriminator
in the name, and that discriminator must keep emit order recoverable from the drops folder alone.

**`sourceId`** — the occurrence's stable identity from the source side (a recording drive-item id or
a Stream URL). One live, non-failed ingestion job may exist per `sourceId`.

**`augments`** — the optional `metadata.json` object (`{ "sourceId": ... }`) by which a drop declares
the already-ingested occurrence it augments rather than opening a new one. Its presence requires
`schemaVersion: 2`, so a consumer pinned to version 1 fails closed instead of ignoring the field and
ingesting the content as a second meeting. The declaration — not the drop's own `sourceId` — is the
link, so the two ids may legitimately differ.

**Augmentation** — a later drop bringing evidence the meeting lacks (a recovered recording, or a
participant graph the first drop had not resolved). Intake re-arms the occurrence's *existing* job
against the new drop rather than opening a second one, so the meeting id — and every moment id,
citation and published artifact naming it — survives. A drop bringing nothing the meeting lacks is
refused.

**Write-once** — applies to a *drop*, not to a meeting. A finalized drop is never overwritten, but
one meeting may accumulate several drops over time.

**Participants array** — the optional `metadata.json` list carrying the source side's resolved
people. An omitted array and an empty one are different statements: **omitted** means the source did
not look, and transcript speaker attribution fills in; **`[]`** means the source looked and found
nobody, and no fallback runs.

**Participant graph** / **`org chart.json`** — the puller's per-occurrence roster, resolved upstream
against the SharePoint user-profile service over the existing browser session, carrying `mail`,
title, department and a reporting chain. Not Microsoft Graph — the name is coincidental and the
confusion is expensive.

**Provenance** — the puller's `_source.json` content, embedded verbatim in `metadata.json`.

**Puller** — `pull_transcript`, the existing local script that drives a logged-in browser to fetch a
Teams recap's transcript and recording. It sits outside MeetingMiner's runtime boundary: it emits
drops and never knows the pipeline.

**emit-drop** — the puller step that maps its native `<Title>/<M.D.YY>/` output into a schema-valid
drop, assembles it in a staging path, finalizes it atomically, and POSTs it to `/ingests`.

**`corpus`** — a required tag on every drop, `"scripted"` or `"real"`, carried onto the meeting row.
Scripted meetings are eval subjects; real meetings are demo corpus and never eval subjects.

**Intake door** — `POST /ingests`, the single entry point. Files appearing in the drops folder never
ingest by themselves; there is no folder watcher.

---

## Pipeline and jobs

**Job** — a Postgres row the API inserts and the worker claims. Pipeline work never runs in the API
process.

**Stage** — one named step of the ingest pipeline, checkpointed in the database. In execution order:
`probe → frames → ocr → screens → transcribe → align → moments → extract`.

**Video-only stages** — `probe`, `frames`, `ocr`, `screens`, `transcribe`. A transcript-only drop
records exactly these as `skipped` and proceeds to `align`; `moments` then falls back to transcript
segmentation.

**Evidence stages** — everything up to and including `moments`: the stages whose completion means
the evidence bundle is built. `extract` sits outside, so `job.status == 'done'` is *not* the
safe-to-open gate.

**Augmentation stages** — the set intake puts back to `queued` when it re-arms a job: the video-only
stages plus `align` (the merged transcript must be re-derived against the new STT lane) and
`moments` (the stage that attaches the screenshot and clears the transitional deep link). `extract`
is deliberately excluded.

**Idempotent stage** — a stage whose rerun deterministically overwrites its own outputs, where "its
own" means rows keyed to that job's meeting. Cross-meeting entities (screens, participants) are
upserted by identity key and never deleted by a rerun.

**`evidence_complete` / `viewable`** — the predicate that every evidence stage has settled (`done`
or `skipped`), and the field the API returns from it. It legitimately goes false *during* an
augmentation, because `align` deletes the meeting's transcript segments before `moments` re-runs.

**Transcript source** — a raw transcript as received or produced, stored whole: the provided Teams
export, the provided VTT, or the STT lane's output (`kind='stt'`). Raw sources are never merged into
each other and never erased.

**Transcript segment** — a derived row produced by `align`, carrying the reconciled text and timing.
`start_ms` holds the *provided* transcript's cue timing; the STT lane's timings live in separate
`stt_start_ms` / `alignment_delta_ms` columns and never overwrite it. That separation is what keeps
moment identity — and therefore every existing citation — stable when a recording arrives later.

**STT lane** — the speech-recognition pass run over the recording's extracted audio, used to
*verify* a provided transcript rather than replace it. Behind the `Stt` adapter port.

**Diarization** — segmenting audio into speaker turns. It produces anonymous clusters
("speaker 1", "speaker 2"); it does not name them. Behind the `Diarizer` port, `noop` by default.

**Alignment** — reconciling the provided transcript, its VTT cue timing, and the STT lane by text
alignment, never by picking one file wholesale.

**Content root** (`MM_CONTENT_ROOT`) — the directory under which material this pipeline *produced*
lives: extracted frames, screenshots, and the STT lane's extracted audio, under
`meetings/<meeting_id>/`. It does **not** hold the recording — see *Drops root*.

**Drops root** (`MM_DROPS_ROOT`) — the directory holding the write-once source drops, and so the
anchor for material that *arrived*: the recording, provided transcripts, and `metadata.json`. It is
permanent, backed-up storage rather than a landing zone, because ingested drops are re-read for
transcript re-parse, for replay, and for the augmentation comparison long after ingest.

Which of the two roots a recorded path is relative to is a property of how the file came to exist —
arrived versus produced — not of its type. Databases store paths *relative* to one root or the
other and never an absolute path; the API and the worker resolve them at use time, so no absolute
path leaves the server. Full layout in `storage-layout.md`; the rule is spine AD-3, and the
per-file provenance row it resolves through is AD-17.

---

## Storage and retrieval

**Database of record** — Postgres, the sole authoritative store. Every domain object and artifact is
minted there first and its id is created nowhere else.

**Projection** — a derived, rebuildable copy of database-of-record state written into a retrieval
store. Projections are never the primary copy, and all writes go through one module.

**Retrieval stores** — Neo4j (the domain graph) and Meilisearch (full-text over evidence documents).
Both are projections.

**`rebuild`** — the CLI that regenerates both retrieval stores from Postgres and `config.yaml` alone.
The answer to a corrupt or migrated store, in place of hand-editing one.

**Publish gate** — the rule, enforced inside the projections module, that refuses to project any
artifact whose Postgres state is not `published`. Unpublished artifacts exist only in the database of
record and surface only in the moment view's right rail.

**GraphRAG** — retrieval that traverses the domain graph rather than only ranking documents; here,
the Neo4j half of the retrieval layer.

**BM25** — the ranking function behind full-text search. Measured on this corpus, it beat every one
of nine embedding models whenever a query reused the transcript's wording — which is the dominant
query shape — so it is funded as a first-class half of retrieval, not a fallback.

**Hybrid retrieval** — combining full-text and vector search. Justified here by traffic mix
(embeddings win decisively only on paraphrased questions), not by vectors being better in general.

**Chunk** — a passage indexed for retrieval: whole speaker turns packed to ~1,400 characters with one
turn of overlap, keyed `meetingId#seq`. Turn boundaries are preserved because speaker attribution and
timestamp citations both hang off them.

**MRR / recall@k** — mean reciprocal rank and recall at *k*, the retrieval metrics used in the
embedding bake-off.

---

## Extraction, artifacts and publishing

**Artifact** — an ADR, action item, decision, requirement or similar, extracted by the pipeline
from a moment and subject to the publish gate. (This term once also named the planning documents
under a separate process tree; that tree is gone and the collision with it no longer exists.)

**Artifact lifecycle** — `extracted → approved → published`, one-way; no unpublish exists in the
capstone. The worker owns extraction content, the API owns the lifecycle column.

**ADR** — Architecture Decision Record, one of the artifact types extracted from moments and
committed to a plain local git repository on approval.

**Publishing** — the per-moment human gesture that moves artifacts to `published`, writes them to a
folder, and commits ADRs. Nothing publishes without it.

---

## Evaluation

**Ground truth** — machine-readable YAML declaring everything a scripted meeting should produce,
authored *before* ingestion and independently of the extractor. A denominator derived from what the
extractor emitted cannot reveal what it missed.

**Manifest** — a ground-truth file for one scripted meeting, matched to its ingested meeting by
`sourceId`.

**`ocr_anchor`** — a unique, distinctive string on each expected slide or screen, used to identify it
deterministically in captured output. Missing or duplicate anchors fail validation.

**Archetype** — the shape of a scripted fixture: `slide-deck` or `ui-demo`.

**Capture recall** — the fraction of expected screens/slides actually captured. Required to be 100%.

**Over-capture guardrail** — the counterweight to a 100% recall target: fewer than one captured
slide-or-screen per minute of meeting. Without it, capturing everything trivially satisfies recall.

**Tiered judging pyramid** — deterministic asserts first, then an LLM judge, then a human judge.
Deterministic-first by design; the human verdict wins any disagreement.

**Run artifacts** — the immutable output of one eval run, including the config snapshot that says
which models and prompts produced it.

**`verdict.md` / `human-verdicts.yaml`** — the recorded outcome of a run, and the per-item human
judgements with one-line reasons.

**No silent zero** — the rule that a stage parsing model or tool output must report a zero result
from input that plainly contains extractable content as a signal, not as success. Named after a
measured upstream failure: a parser that understood one of two document layouts contributed zero
decisions for every meeting using the other and reported success; the fix moved decisions from 41
to 182.

---

## Corpus and sources

**Occurrence folder** — one `<Meeting Title>/<M.D.YY>/` directory in the puller's own library.

**Archive mirror** — `Recordings and Transcripts/`, the fetched copy of the wider SharePoint library.
Distinct from the occurrence folders and much larger.

**Transcript lineages** — three forms in this corpus: the Teams speaker-attributed export
(`[m:ss] Lastname, Firstname: text`), a `.vtt` subtitle track (often speaker-less, and never a
substitute for the text transcript), and a legacy `<Name> | MM:SS` format carried by the two NDA
demo recordings.

**Transcript-only meeting** — a meeting ingested with no recording. First-class: it ingests, searches
and cites normally, its moments carry a source deep link in place of a replay button, and it is
first-class because some meetings will *never* have retrievable video — not because most currently
lack it.

**Source deep link** — the transitional link to the original Teams recap that stands in for the
replay button on a transcript-only moment. Explicitly temporary: augmentation retires it.

---

## Infrastructure

**Store-backed suites** — the test suites requiring Postgres, Neo4j or Meilisearch. They run against
the checkout's own compose stack, so suites in two worktrees never contend; two in one checkout queue
on the endpoint-keyed projection lock.

**Worktree** — a separate checkout for one work item (`make worktree STORY=<slug>`) with its own branch
and its own Docker stack: compose project `meetingminer-<slug>` on ports written to the worktree's
generated `.env.worktree`, together with the stack's incarnation id (`MM_STACK_ID`, stamped on its
containers and volumes so a stale same-named stack is torn down rather than attached to). The bound is
the Docker VM's memory: OrbStack's VM reports 23.5 GiB against the 128 GB host and a stack idles at
about 2 GiB, so a handful fit and a dozen idle ones would fill the VM — `make down` in an idle worktree
frees its memory and keeps its volumes (AGENTS.md carries the full measurement). The api and web ports
are still the same in every checkout.

**LAN model hosts** — on-prem inference machines: an Ollama host (embeddings) and VM 120 `cuda-asr`
(an RTX 4080 serving `nvidia/parakeet-tdt-0.6b-v3` for speech recognition). Operator-scheduled and
available on request. Reached through adapter ports, so swapping one is a configuration change.

---

## Project and process vocabulary

**Spec** — the technical contract for what to build. Now `docs/architecture.md`, with
`docs/project-record.md` recording what was actually delivered against it.

**Companion** — a reference document that must be read alongside the architecture: `glossary.md`,
`storage-layout.md`, `eval-design.md`. Distinct from inputs fully absorbed into it, which
downstream does *not* read.

**`.memlog.md`** — the append-only record of every decision, constraint and open question, in the
order it happened. `SPEC.md` and its companions are re-derived from it; it is never edited or
reordered, and a later entry supersedes an earlier one without deleting it.

**Capability (`CAP-n`)** — a numbered capability in the spec kernel, carrying an `intent` (what) and
a `success` (how you know). Ids are stable and never reused.

**FR / AD / UX-DR** — a functional requirement in `epics.md`; an architecture decision in
`ARCHITECTURE-SPINE.md`; a UX design rule. Cross-references between documents use these ids.

**Spine** — `ARCHITECTURE-SPINE.md`, the set of architecture decisions. Note that it is amended on
story branches while work is in flight, so `main`'s copy can lag.

**Deferred work** — `deferred-work.md`, findings deliberately not fixed in the story that found
them, each recorded with its evidence. A deferral is a decision; an unrecorded omission is not.
