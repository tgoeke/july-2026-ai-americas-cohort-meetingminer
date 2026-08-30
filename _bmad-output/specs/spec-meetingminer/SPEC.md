---
id: SPEC-meetingminer
companions:
  - glossary.md
  - storage-layout.md
  - scope.md
  - corpus-facts.md
  - capture-measurements.md
  - retrieval-prior-art.md
  - ux-spine.md
  - eval-strategy.md
  - eval-design.md
  - architecture-diagrams.md
sources:
  - ../../../tim.Blake-capstone-product-brief.md
  - ../../brainstorming/brainstorm-meetingminer-agentic-rag-2026-08-16/brainstorm-intent.md
  - ../../brainstorming/brainstorm-meetingminer-eval-strategy-2026-08-16/brainstorm-intent.md
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# MeetingMiner — Evidence Engine for Trustworthy AI Engineering

## Why

A pain to solve and a vision to realize, under a mandate. Lead application architects mine recorded software demonstrations into requirements, architecture decisions, and backlog changes by hand — scrubbing video, screenshotting, aligning transcripts, pasting evidence into an LLM. This takes hours per meeting and fails silently: a missed screen means nobody knows to look for the requirement it contained. Downstream, organizations re-decide decided questions, re-explain in live meetings what a prior meeting already captured, and eat months of rework when absent stakeholders dispute unwitnessed outcomes. MeetingMiner treats meetings as evidence to preserve, not conversations to summarize: every artifact traces to the exact video moment that produced it. The immediate driver is the InfoQ AI Engineering capstone — solo developer, demo in ~1 week (~2 weeks total): design everything, build the slice defined in `scope.md`.

## Capabilities

- **CAP-1 Evidence ingestion**
  - **intent:** User can ingest meetings landing in a local folder as write-once puller drops — a recording and/or its transcript file plus a metadata sidecar with embedded provenance — or a local recording alone; a provided transcript is verified and merged, never erased. Transcript-only meetings are first-class — because some meetings will never have retrievable video, not because most currently lack it: they ingest, search, and cite normally, and their moments carry a source deep link to the original recap in place of a screenshot and video replay. A later drop bringing evidence the meeting lacks — a recovered recording, a participant graph the first drop had not resolved — **augments the meeting in place**: the pipeline runs only the stages that evidence unlocks, so a recovered recording adds screens, screenshots, alignment and true replay and retires the deep link, while a recovered participant graph re-derives participants alone. A drop that brings nothing the meeting lacks is refused. Recordings land in the recorder's personal OneDrive, so late arrival is the expected path, not an edge case (`corpus-facts.md` §1). Ingestion yields a fully precomputed evidence bundle: every distinct application screen, a verified speaker-attributed transcript segmented to video flow, identified moments, screen–discussion alignment, timestamps, provenance metadata, replay links, and participants derived from transcript speakers and the sidecar. The Teams-side pull (recap URL → transcript + recording) happens in the puller script, outside MeetingMiner; the puller notifies MeetingMiner when a drop is ready — files in the folder alone never ingest.
  - **success:** A previously unseen scripted software demonstration processes automatically with 100% capture recall against the script's expected-artifact manifest; ingestion completes before first viewing. Measured properties of the real input — corpus, media, transcript lineages, participant graph — are in `corpus-facts.md`; the measured capture path is in `capture-measurements.md`.

- **CAP-2 Evidence domain graph**
  - **intent:** System persists evidence as a graph of first-class domain objects — Moment (atomic), Meeting, Screen, Screenshot, Project, Product, Participant, derived artifacts — in a database of record from the moment each object is created (artifacts included, while still unpublished). The persisted domain graph is what GraphRAG traverses, and screen lineage recognizes the same screen across meetings.
  - **success:** Graph traversal answers "show every discussion of this screen over time" and the participants → meetings → topics → moments query (the "I already explained this to Rowan" demo) against scripted ground truth.

- **CAP-3 Search and cited Q&A**
  - **intent:** User can search the corpus by meeting name, topic, or mention, and ask natural-language questions answered over the retrieval stores (CAP-9) — GraphRAG over the domain graph plus the full-text document index — with every answer citing the moments it rests on.
  - **success:** Every answer carries citations that replay their evidence; cited timestamps fall within ±15s of the scripted timestamp (human-judged for the capstone; deterministic check documented in `eval-strategy.md`).

- **CAP-4 Moment view and replay**
  - **intent:** User can open any moment and see its screenshot, the transcript section, a right rail of extracted analytics (action items, ADRs, decisions, stories, requirements, bug fixes, change requests), and a full audio+video replay button; meeting drill-down shows the captured screenshot series with highlighted mentions and inline replays. A moment with no local recording renders the same view minus the screenshot, with a **transitional source deep link** to the original recap standing in for the replay button until augmentation supplies real video.
  - **success:** Verifying a claim against its source takes seconds, not a meeting rewatch.

- **CAP-5 Artifact extraction**
  - **intent:** System extracts ADRs and action items from the **whole meeting transcript** in one pass per meeting — a decision emerges across minutes of discussion and almost never sits inside a single moment. Derivative documents are created only when necessary, never regenerated: when a drop arrives already carrying the puller summariser's extraction documents, the stage **parses** them and makes no model call; only a transcript arriving without them is sent to a model, using prompts that are visible in the UI and swappable via configuration, adapted from the proven `pull_transcript` summarization pair. Both paths converge on one strict parser that reads both known summariser layouts. Every extracted artifact carries the transcript timestamp(s) that ground it, resolved deterministically to its containing moment; the artifact-to-moment anchor is what keeps extraction inside *no citation, no answer*, and a timestamp that resolves to no moment is a named error rather than a dropped artifact.
  - **success:** Fuzzy set-match against scripted action items reports found/missing/extra; ADR and decision extraction passes LLM-judge plus human-judge review.

- **CAP-6 Human-approved publishing**
  - **intent:** Extracted artifacts start unpublished; the user approves per moment to publish artifacts to a folder and commit ADRs to a plain local git repository.
  - **success:** Nothing publishes without an explicit approval gesture; approved ADRs land as commits in the local repo with outbound links shown in context.

- **CAP-7 Eval harness**
  - **intent:** System is evaluated against scripted Teams meetings with machine-readable YAML ground truth through a deterministic-first tiered judging pyramid: deterministic asserts, then LLM judge, then human judge via runbook.
  - **success:** One full eval run completes before the demo; capture recall is 100% and the over-capture guardrail (under one slide-or-screen per minute of meeting) holds. Full metric set and build plan in `eval-strategy.md`; check algorithms and ground-truth schema in `eval-design.md`.

- **CAP-8 Eval runbook**
  - **intent:** An operator can execute a complete eval run — setup, deterministic asserts, LLM-judge review, human judging, verdict recording, failure triage, and rerun — by following a written runbook alone.
  - **success:** A full eval run is completed end-to-end using only the runbook (no tribal knowledge), with verdicts and run artifacts recorded as specified in `eval-design.md`.

- **CAP-9 Multi-store retrieval with artifact re-indexing**
  - **intent:** The retrieval layer spans multiple stores — an indexed full-text search engine over evidence documents alongside the GraphRAG domain graph — both derived projections of the database of record. Published derived artifacts (ADRs, action items, other architectural documents) are re-indexed into the retrieval stores, becoming searchable, citable knowledge themselves.
  - **success:** A single corpus query returns hits from both stores — an evidence moment via the document index and a published ADR via re-indexing — each with citations that replay evidence; unpublished artifacts never appear in any result. Schema shape and store constraints already proven on this corpus are in `retrieval-prior-art.md`.

## Constraints

- **No citation, no answer.** Every factual claim about meeting content must trace to a moment. No exceptions.
- **Augmentation adds, never destroys.** A later drop may attach a screenshot, replay window and alignment to an existing moment, may add new screen-derived moments, and may replace a meeting's participants with better-identified ones, but never deletes, renumbers or re-keys a moment that already exists. Existing citations and published artifacts stay valid across augmentation — a citation that breaks when better evidence arrives violates *no citation, no answer* at exactly the moment the evidence improved.
- Write-once applies to a drop, not to a meeting. A finalized drop is still never overwritten, but one meeting may accumulate more than one drop over time, so a later drop declares which meeting it augments (`augments.sourceId`, which requires drop schema version 2) rather than colliding on `sourceId`. The declaration, not the drop's own `sourceId`, is the link, so a recording recovered from a different location keeps its own id (spine AD-1, AD-14).
- Once a meeting exists, no later drop may rewrite or shrink it. This binds the ordinary retry of a failed job as well as a declared augmentation: a replacement drop must keep the meeting's corpus, wall-clock instant and precision, must still carry every provided transcript the current drop carries, and may not return a meeting that already has a recording to transcript-only. A failed ingest that never minted a meeting keeps its unrestricted re-queue path. The retry route is otherwise the one path that could destroy a cited meeting without ever declaring an augmentation.
- Deterministic components own evidence capture, transcript alignment, provenance, replay, search, and evaluation. AI contributes evidence; AI never owns truth.
- **Two storage roots, both configured, both permanent.** Material that *arrived* — the recording, provided transcripts, the metadata sidecar — stays in its write-once drop under the drops root; material this pipeline *produced* — frames, screenshots, extracted audio, published artifacts — is written under the content root. Recorded paths are relative to one of those two roots and nothing else: neither root's absolute location is stored in a database or leaves the server, so relocating either is an environment change rather than a data migration. The drops root is not a clearable landing zone — ingested drops are re-read for transcript re-parse, for replay, and for the augmentation comparison long after ingest, so both roots are backed up together. Full layout, per-file anchors and the bring-your-own-recording path in `storage-layout.md`. Story 2.1a implemented this: `MM_DROPS_ROOT` is a configured root gated at api and worker startup, `job.drop_relative_path` and `meeting_media.drop_relative_path` are anchored to it, `transcript_source.drop_relative_path` was widened from a bare filename to the same `<drop-dir>/<filename>` form, and migration 0008 CHECKs that no stored path is absolute or carries a `..` segment. The pre-2.1a absolute `job.drop_path` survives as a nullable column only until `make backfill-drop-paths` has run everywhere (spine AD-3).
- **Every evidence file has a row, and no path is half data and half code.** Each file the system stores or serves carries a database row naming its path relative to its root, its `sha256`, its byte size, and the stage that produced or read it — so a substituted file is detectable and every served byte has provenance. Composing a path at serve time from a stored value plus a hardcoded filename constant is what this rules out: it is how the recording came to be the one piece of evidence with no checksum and no row of its own.
- All model interaction (speech recognition, embeddings, transcript refinement, future LLMs) sits behind adapter interfaces, replaceable via configuration, not code changes.
- **Extraction defaults to a local model** — `ollama/gpt-oss:120b`, the `pull_transcript` bake-off winner (7/16/26) — not a paid API. Any operation that spends money on model calls requires fresh, explicit per-run authorization; a prior general go-ahead does not carry (user decision 2026-08-20, after stopping the paid per-moment backfill at 5 of 28 meetings).
- The system is biased toward preserving evidence over minimizing duplicates: required capture recall is 100%, bounded only by the over-capture guardrail.
- Capture-recall ground truth is produced independently of the extractor, never derived from its own output: a set built from what the extractor emitted cannot reveal what it missed, so a self-derived denominator reports 100% while measuring nothing.
- **No silent zero.** A stage that parses model or tool output into artifacts must report a zero result from input that plainly contains extractable content as a signal, not as success. Measured upstream on this corpus: a summary parser that understood one of two document layouts contributed zero decisions for every meeting using the other, reported success, and was found by chance — the fix moved decisions from 41 to 182 (`retrieval-prior-art.md` §8). Applies to extraction (CAP-5) and to every eval check that counts what a stage produced (CAP-7).
- Evidence capture is designed against ~120-minute recordings (the primary real sample is 117.6 minutes, 16 fps, mono), not a 60-90 minute bar.
- Teams transcripts are the sole go-forward transcript source; third-party transcripts already in the corpus are read-only legacy support, and no two raw sources are ever merged. Legacy-format parsing stays required regardless: the two NDA demo recordings are the primary capture-eval assets and carry it.
- Speaker attribution never guesses. A label that cannot be resolved to a participant stays unresolved and an ambiguous one stays ambiguous, because a wrong attribution is worse than an absent one - who said it is half of no citation, no answer.
- Participants key on the directory `mail` address the participant graph supplies — measured on 98.7% of rows — with the normalized display name as the fallback, not the default. That means the drop must carry the participant graph the puller already resolved: a name-keyed roster collapses two same-named humans and splits one human across spelling variants, and it is the reporting chain and mail that make the participants → meetings → topics → moments traversal answer *who*.
- One-way generation engine: no status sync back from external trackers. MeetingMiner may display items it created elsewhere but never owns their lifecycle state.
- Series membership is human-declared, never inferred; recurring meetings get per-meeting documents, with cross-meeting rollups as the on-demand exception.
- AI proposes, humans approve: publishing is a per-moment user gesture; artifacts start unpublished.
- Full-text search is a first-class half of retrieval, not a fallback behind the vector store. Measured on this corpus, no embedding model beat BM25 alone when a query reuses the transcript's wording, and that is the dominant query shape; embeddings win decisively only on paraphrased questions. CAP-9 funds both halves, and the embedding model is a recorded, re-indexable property of the store rather than a config toggle. Measurements in `retrieval-prior-art.md` §7.
- Only published (human-approved) artifacts enter the retrieval stores; search and Q&A never surface unapproved AI output.
- Domain objects and artifacts persist in a database of record from creation; retrieval stores are derived, rebuildable projections of it, never the primary copy. Unpublished artifacts exist only in the database of record.
- No dedicated Teams test environment (the M365 developer sandbox is discontinued): scripted mock meetings are hosted and recorded on the corp production Teams tenant and retrieved by the puller script logged in as the user. This rules out tenant-side automation, Graph app registration, and any MeetingMiner-to-Teams integration.
- **The live demo runs about three minutes.** That budget fits one path end to end — ask the corpus a question, get a cited answer, open a cited moment, replay its original evidence (CAP-3 → CAP-4). Everything else the capstone builds is evidenced by artifacts and the eval run rather than shown: ingestion, augmentation, extraction, publishing and the harness must be complete and demonstrable on request, but the script spends no seconds on them. Anything that cannot be precomputed before the clock starts is not in the demo.
- Sequencing: the eval harness and all its setup are completed before demo-script work begins. Hidden prerequisite the backlog order does not show: check 2.11 approves an artifact through the public per-moment approval endpoint (CAP-6, story 4.3), so the harness cannot finish before that endpoint exists; the capture checks (story 5.2) are the early-closable part of the eval track, needing only the NDA demo recordings minted as drops (story 2-1b).
- Ingestion fully precomputes (video, screenshots, moments, transcript segmentation) before viewing.
- Delivery reality: solo developer, demo in ~1 week (~2 weeks total). Design everything; build only the slice in `scope.md`.

## Non-goals

- Autonomous ingestion, notification subscriptions, and digest delivery. (Morning Digest is a COULD: generate one example email, deliver nothing.)
- Self-assembling decks and absent-stakeholder agree/disagree registration.
- Task/story lifecycle tracking — Asana, Linear, and RAID logs own state; MeetingMiner is the evidence at the origin of the decision workflow.
- Outbound routing to live systems (GitHub, Asana, Linear, SharePoint): capstone publishes to a local folder and a plain local git repo only.
- Retrieval eval implementation — designed and documented only, with expectations set with instructors.
- Image-similarity dedup scan (OCR text compare covers dedup this week).
- Auth and enterprise integration (Clerk, Entra ID).
- Microsoft Graph integration. Participants derive from the puller's per-occurrence participant graph — resolved against the SharePoint user-profile service over the existing session, carrying a real directory mail address and a reporting chain — plus recording permissions and transcript speakers. Enabling Graph would add only calendar accept/decline status, so the non-goal costs nothing structural; Graph is product-later.

## Success signal

A previously unseen scripted software demonstration is processed automatically into complete screen capture (100% capture recall against ground truth), verified transcript alignment, a searchable knowledge base, replayable provenance, and cited chat responses — demonstrated live by answering the "I already explained this to Rowan" query through the participants → meetings → topics → moments traversal, with every cited moment replaying its original evidence.

## Assumptions

- The capstone runs local-first and single-user with no authentication (Clerk/Entra ID are explicitly product-later). Local-first governs evidence and state — content root, database of record, retrieval stores — not model inference: on-prem LAN model hosts are already in use for embeddings and available for speech recognition (`corpus-facts.md` §5), which is what the adapter constraint exists to allow. These hosts are operator-scheduled and available on request, demo included, and further VMs can be provisioned on the same workstation.
- The Teams recap puller is the existing `pull_transcript` tool — a manual paste-the-URL local script driving a logged-in browser, not a Teams integration.
- The ingestion input contract is a puller-emitted write-once drop directory, pinned by `docs/source-drop.schema.json` (spine AD-1): recording and/or speaker-attributed transcript export, plus a `metadata.json` sidecar carrying the source id, corpus, meeting wall clock with its precision, embedded provenance, and the participants array. The puller's emit-drop step maps its per-occurrence participant graph (`org chart.json`, measured in `corpus-facts.md` §4) into that array, carrying each person's `mail`, title, department and reporting chain; the array is omitted only when the puller resolved no graph, and the pipeline then derives participants from transcript speaker attribution alone. An omitted array and an empty one are not the same statement: omitted means the source did not look, and transcript attribution fills in; `[]` means the source looked and found nobody, and no fallback runs. The drop also carries the summariser's extraction documents when the puller produced them — optional files added to the schema alongside the evidence files — so an adopted extraction arrives as *arrived* material with the same provenance as every other file in the drop (per-file row, `sha256`, drops root) instead of through a side channel; their absence is what sends the transcript to a model (CAP-5).

## Open Questions

- None open. Resolved and closed: participant identity input path (2026-08-19 — the spec's claim stands and the puller closes the gap by carrying the graph it already resolves; server side needs no change); PNG-to-slide matching, OCR engine, LLM judge model, CAP-9 eval coverage (2026-08-17, see `eval-design.md` §6–§7 and checks 2.10–2.11); transcript-only replay affordance and the late-arriving-video path (2026-08-18, now rendered into CAP-1, CAP-4 and Constraints); the two ARCHITECTURE-SPINE amendments this spec had queued — the deployment paragraph's on-prem LAN model hosts and AD-3's single-content-root wording — both applied and committed 2026-08-19; the two-lineage question of which SPEC and spine are canonical (this repo's CAP-1–9 and AD-1–16 are; the spike cluster is a parallel track); and the participants-backfill intake door, closed by the AD-14 widening that admits any drop bringing evidence the meeting lacks.
