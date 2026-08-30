# Spine Review — Update Amendment (path anchors, file provenance, inference scope), 2026-08-19b

**Artifact:** `ARCHITECTURE-SPINE.md` (updated 2026-08-19, commit `01c8dfd`)
**Amendment under review:** AD-3 rewritten for two path anchors (`MM_DROPS_ROOT` / `MM_CONTENT_ROOT`); new AD-17 (per-file provenance row); AD-9 + Structural Seed deployment paragraph rescoped so local-first governs evidence and state but not model inference; ratifications in AD-4, AD-5, AD-13, AD-14 and the Recovery convention row.
**Judged against:** the good-spine checklist, applied to the whole spine, not only the changed lines.
**Cross-checked:** `SPEC.md`, `storage-layout.md`, `scope.md`, `glossary.md`, `ux-spine.md`, `corpus-facts.md`, `epics.md`, `spec-2-1a-evidence-paths-anchored-to-configured-roots.md`, and the shipped tree (`server/`, `web/`, `evals/`, `pull_transcript/`).

**Verdict: REVISE.** The amendment's direction is right and it landed at every touch point it aimed at — AD-3, AD-9, the deployment paragraph, the deployment diagram, the Recovery row and the CAP-1/CAP-4 map rows all carry it, and the prior review's F-2/F-3/F-4 are closed. But two of the three headline changes are not enforceable as written: **AD-17 is contradicted by the very table it names as its reference implementation**, and **AD-9's "never a code change" is false against the shipped adapter layer**. A separate high finding is not amendment-caused but is exposed by it: a cross-unit invariant that is already shipped, already projected into both stores, and already the subject of one shipped bug — the transcript-only **source deep link** — has no representation in the spine at all.

---

## 1. Did the amendment land where it should?

| Touch point | Status | Evidence |
| --- | --- | --- |
| Frontmatter | Landed | `storage-layout.md` added to `sources:`; `updated: 2026-08-19` |
| AD-3 heading + Rule | Landed | Two named roots; anchor-by-provenance rule; the not-copied argument stated with its reason |
| AD-3 Prevents | Landed | Third clause added ("a reader concluding that arriving material must be copied under the content root") — names the divergence that actually occurred |
| AD-17 (new) | Landed as text | Placed after AD-16, bound to CAP-1/CAP-4, carried into the CAP-1 and CAP-4 map rows |
| AD-9 heading + Rule | Landed | "inference wherever it is configured"; local-first scoped to evidence and state; three destination classes |
| Structural Seed deployment paragraph | Landed | Three destination classes; VM 120 `cuda-asr` recorded with its hardware, model, endpoint and scheduling status |
| Deployment diagram | Landed | `lan` node added with an `api & worker -->|HTTP, via AD-8 ports| lan` edge; filesystem box renamed to `MM_DROPS_ROOT` / `MM_CONTENT_ROOT` |
| Component diagram providers node | Landed | "on-prem LAN hosts" inserted between Ollama and the cloud providers |
| AD-4 / AD-5 / AD-13 / AD-14 ratifications | Landed | invalidate-not-unproject trade; mail-else-normalized-name with the AAD non-goal; the `start_ms` invariant; the API-distinguishability rule |
| Recovery convention row | Landed | Human-curated state and the publish repo named as not reconstructable; emit-order replay added |
| Prior review F-2 (AD-12 rationale) | Closed | AD-12's Rule now states the permission directly rather than resting on the sandbox premise |
| Prior review F-3 (Recovery overclaim) | Closed | Recovery row rewritten; `pg_dump` + publish folder named |
| Prior review F-4 (`~25` miscitation) | Closed | Count removed from the CAP-7 row |
| Prior review F-1 (puller intake contract) | Partially closed | See F-14 |

Stale-reference sweep on the amended concepts: no surviving "the content root" singular in the spine; no surviving claim that the recording is copied. Both are still present in `glossary.md` — see F-12.

---

## 2. Findings

### F-1 (High) — AD-17 is contradicted by the table it names as its reference implementation

AD-17's Rule requires each row to carry: the path relative to its root, which root, `sha256`, `byte_size`, and **the stage that wrote or read it**. It then says `transcript_source` (migration `0005`) "is the reference row shape and is matched rather than re-invented."

`server/meetingminer/migrations/0005_transcripts_participants.sql:16-52` does not satisfy the rule it is held up as satisfying:

- **No `stage` column.** No table in any of the seven migrations has one. So the fifth element of the rule has no reference implementation, and "matched rather than re-invented" instructs a builder to copy a shape that omits it.
- **The path is not relative to a root.** `drop_relative_path` holds a *bare filename* — `align.py:199` writes `path.name`. It is relative to the drop directory, not to the drops root. AD-3, one AD-file away, specifies the arrived-material path shape as `<drop-dir>/<filename>` against the drops root, and `storage-layout.md` §4 repeats it. The two amended ADs specify different anchor granularities for the same file, and the shipped reference table implements a third.

This is the sharpest amendment-induced contradiction: AD-17 exists to stop two stages inventing different provenance shapes, and as written it hands them two.

**Fix:** decide the anchor granularity for arrived material once (root-relative `<drop-dir>/<filename>` is the one AD-3 and `storage-layout.md` already agree on), state that `transcript_source` is the reference *for the column set* and requires a migration to add `stage` and to widen `drop_relative_path`, or drop the `stage` element from the rule if it is not actually wanted.

### F-2 (High) — AD-17's scope is unbounded, unratified, and already diverging from the story below it

AD-17 says "Every file the system stores or serves." Against the tree:

| Evidence file | Row | path | sha256 | byte_size | stage |
| --- | --- | --- | --- | --- | --- |
| provided transcript / STT audio | `transcript_source` | yes | yes | yes | **no** |
| sampled frame JPEGs | `frame` (`0002:76-84`) | yes | **no** | **no** | **no** |
| screenshots | `screenshot` (`0003:64-87`) | yes | **no** | **no** | **no** |
| `recording.mp4` | **none** | — | — | — | — |
| `metadata.json` | **none** | — | — | — | — |

AD-17 declares four of five non-conforming without saying whether that is a defect to fix, a migration to schedule, or accepted scope — and the spine claims to ratify the brownfield. Three concrete consequences:

- **The recording's carrier table is undecided, and the level below has already picked a different answer.** `spec-2-1a-evidence-paths-anchored-to-configured-roots.md` records the recording on **`meeting_media`** and explicitly reuses **`meeting_media.size_bytes`** "rather than adding a second size column." AD-17 names the column `byte_size` and says match `transcript_source` — which `meeting_media` (ffprobe facts, no path column, meeting-id PK) is not. Spine and frozen story contract disagree today.
- **Screenshots are served** (CAP-4, Epic 2), so AD-17 obliges a `sha256`/`byte_size`/`stage` migration on `screenshot` before Epic 2 — unstated anywhere.
- **Frames are the unbounded case.** Against ~120-minute recordings at the configured sampling interval, "a row per file with a sha256" is a per-frame hashing cost the rule does not scope and no one has priced.

Compounding: **Deferred** still says "Exact Postgres DDL and column sets — the ERD fixes names/relationships; the code owns attributes. Revisit only if a new entity appears." AD-17 is a column-set mandate that Deferred delegates to build. That is a Deferred entry under which two units can now diverge — the checklist item this fails.

**Fix:** scope AD-17 to the file classes it means (served/citable evidence: recording, transcripts, screenshots — with frames explicitly excluded or explicitly included and priced), name the carrier table for the recording, reconcile `byte_size` vs the shipped `size_bytes`, and narrow the Deferred DDL entry to exclude provenance columns.

### F-3 (High) — AD-9's "never a code change" is false against the shipped adapter layer, and AD-8 has no LAN engine to bind

AD-9 now says an engine "may run in-process, as a host process (Ollama), on an **on-prem LAN host** reached over HTTP, or behind a provider API — which one is a `config.yaml` binding (`providers.<name>.base_url`, AD-10) resolved through the AD-8 ports, never a code change and never an architecture change."

For the stage the amendment actually names — speech recognition on VM 120 — none of that holds:

- `server/meetingminer/config.py:133` types the STT engine as `Literal["mlx-whisper", "parakeet-mlx"]`. A LAN engine is **not representable** in the config schema.
- **No STT adapter reads `providers.*.base_url`.** The only adapter that makes an HTTP call at all is `adapters/embed/ollama.py`. `config.yaml`'s `stt:` block has `engine` + `model` and no provider indirection.
- **AD-8's own enumeration lists no such engine:** `Stt` (mlx-whisper | parakeet-mlx) — both local Apple-MLX engines. `parakeet-mlx` (`adapters/stt/parakeet_mlx.py:25`, macOS-only) is a different thing from the `nvidia/parakeet-tdt-0.6b-v3` the Structural Seed records behind FastAPI at `http://10.77.0.120:8000`; the name similarity invites exactly the confusion the spine should prevent.

So the amendment admits a destination class that the untouched AD-8 cannot express, and asserts config-only swapping for a path that requires a new adapter implementation *and* a config-schema widening. `10.77.0.120`, `cuda-asr` and `parakeet-tdt` appear nowhere in tracked code or config — only in planning docs.

**Fix:** amend AD-8's `Stt` enumeration to include the remote-HTTP engine class and state the rule honestly — a *destination* within an existing engine class is config; a *new engine class* is an adapter implementation, and that is the only code change the ports regime permits. Then AD-9's "never an architecture change" stands and "never a code change" becomes accurate.

### F-4 (High) — The transcript-only source deep link has no spine representation

`moment.source_deep_link` is shipped (`0006_moments.sql:46`), written and retired by the `moments` stage (`pipeline/stages/moments.py:136, 165, 228`), validated for scheme in `domain/drops.py`, and **projected into both stores** as `sourceDeepLink` (`projections/graph.py:285`, `projections/search.py:88`). It is required by `SPEC.md` CAP-1 and CAP-4, by `epics.md` UX-DR11 and stories 1.6 / 1.12 / 2.2 / 2.3, and by `ux-spine.md` — a document the spine lists in its own `sources:`.

The spine mentions it nowhere. Consequences at exactly the seams the spine exists to fix:

- **AD-15's citation wire format enumerates `momentId`, `meetingId`, `startMs`, `endMs`, optional `screenshotId`** and says the web app "renders replay links from that array and never parses markers." For a transcript-only moment there is no replay to render and no deep link in the array. Epic 3's chat surface and Epic 2's moment view will each have to invent the field.
- **The retire condition is a cross-unit invariant with a shipped bug already against it** — `review-story-1-6-2026-08-18.md`: "Replay does not retire deep links on newly superseded moments." That is precisely the divergence class an AD prevents.
- The *Ingest pipeline stages* paragraph on transcript-only drops says moments "carry no screenshot ... and video replay is unavailable" and stops there, where `glossary.md:142` defines `moments` as "the stage that attaches the screenshot and clears the transitional deep link."

**Fix:** either extend AD-15's array with the deep link and state the retire rule (the link is present iff the moment has no replay; the `moments` stage is its sole writer and clearer), or add a short AD for it. This is the last unclaimed piece of the augmentation-safety story that AD-13/AD-14 otherwise cover well.

### F-5 (Medium) — AD-3's env-var roots contradict AD-10 and the Config convention row

AD-3 now names `MM_DROPS_ROOT` and `MM_CONTENT_ROOT` as the configuration mechanism. AD-10's untouched Rule: "A single versioned `config.yaml` declares every adapter binding ...; **environment variables carry secrets only**." The Conventions table repeats it: "`config.yaml` (AD-10); secrets via `.env`, never committed."

A filesystem root is not a secret. The shipped code already made the carve-out and wrote it down — `.env.example:2-3`: ".env is gitignored; it carries secrets **and MM_CONTENT_ROOT only**" — but the carve-out lives in a code comment, and the amendment doubled the number of non-secret env vars without touching the AD that forbids them.

Second-order, and worse: **`MM_DROPS_ROOT` is today the puller's own knob**, not the server's. It exists only at `pull_transcript/emit-drop.js:72`, and `pull_transcript/test/emit-drop.test.js:697` asserts the puller **must not** read the server config regime. The Config convention row says "The puller is outside this regime." The drops root is therefore the one configuration value the black-box seam does *not* isolate — two independently built components must agree on one env var — and no AD says so.

**Fix:** amend AD-10 to "environment variables carry secrets and the two storage roots, nothing else" (the rationale is already in AD-3: relocating a root is an environment change), and add one clause to AD-1 or the Config row naming `MM_DROPS_ROOT` as a value the puller and the server share by name across the seam.

### F-6 (Medium) — AD-3 reads as ratified but is aspirational at its newest point

The spine's job here includes ratifying the brownfield. AD-3 states, present tense: "Neither root's absolute location is stored in a database." Shipped:

- `job.drop_path` is absolute (`0001_jobs.sql:7`), and intake **rejects a relative one**: `api/ingests.py:132-136` raises `400 invalid-drop-path`.
- The prohibited composition in AD-17 is the live code path: `domain/drops.py:26` `RECORDING_FILENAME = "recording.mp4"` joined to the stored `job.drop_path` (`runner.py:315`, and `ingests.py:360, 436, 512`).

Story 2.1a is the fix and is still `status: draft`. Nothing in AD-3 or AD-17 marks the gap, so a builder cannot tell which sentences describe the system and which describe the target. Every other AD in this spine is either true today or explicitly forward-looking about an unbuilt epic; these two are silently neither.

**Fix:** one clause in AD-3 and AD-17 naming story 2.1a as the conforming change and the current state as non-conforming. This costs two sentences and stops the next reader re-deriving the divergence the amendment was written to end.

### F-7 (Medium) — AD-3 made the API a drops-root reader; neither diagram nor the responsibilities table followed

AD-3 now requires replay to serve the recording out of the drop (`storage-layout.md` §1 states it outright). The API already reads the drop directory today (`ingests.py:360, 436, 512`, and story 2.1's replay route). But:

- The **component diagram** has `api -->|"streams media"| content` and no `api → drops` edge.
- The **deployment diagram** has `worker --> drops` and `api --> content` — again no `api → drops`.
- The **responsibilities table** gives `pipeline` "Consumes: adapters, domain, content root" and `api/routes` no filesystem consumer at all.

A builder reading the views rather than the AD prose concludes the API never touches the drops root — which is the pre-amendment answer.

**Fix:** add the `api → drops` edge to both diagrams and name the drops root in the `pipeline` and `api/routes` Consumes cells.

### F-8 (Medium) — A third path anchor is undecided, and `storage-layout.md` contradicts the spine on it

AD-3: "every recorded path is relative to exactly one of them." Two filesystem locations in the spine's own diagrams are neither: the **publish folder + local git repo** (component diagram `pubout`, deployment diagram `publish`, AD-4/CAP-6, and AD-5's "publish metadata" which the API owns and therefore records), and `evals/runs/<run-id>/`.

`storage-layout.md` §1 lists "published artifacts" under the **content root**; its own §3 content-root tree lists only `frames/`, `screenshots/`, `audio/`; the spine's diagrams draw the publish folder as a third location outside both roots. Three statements, three answers, and Epic 4 has to pick one.

**Fix:** decide whether the publish folder is a third configured root or a subtree of the content root, say it in AD-3, and correct `storage-layout.md` §1 to match. Then AD-17 can say whether a published ADR file gets a row.

### F-9 (Medium) — The ERD and the Deferred DDL entry are stale against entities the amended ADs now name

Deferred: "Exact Postgres DDL and column sets — the ERD fixes names/relationships ... **Revisit only if a new entity appears.**" Three have appeared and are named in AD prose but absent from the ERD:

- **`projection_state`** — migration `0007` exists; the AD-4 amendment names "the projection state row" in its documented-cost sentence.
- **`transcript_source`** — migration `0005`; AD-17 names it as its reference implementation.
- **`participant_alias`** — migration `0005:104-108`; AD-5 names "an API-owned alias row."

Also absent: `frame`, `meeting_media`. The ERD is the artifact Deferred points at for entity names, so its staleness is what makes the Deferred entry unsafe (F-2).

**Fix:** add the three named entities to the ERD; they are cited by ADs and therefore no longer attribute-level detail.

### F-10 (Medium) — Adapter unavailability and fallback: a silent dimension in the operational envelope

`config.yaml` ships a fallback mechanism today: `ocr.fallback` ("engaged only when `engine` is unavailable on this host; the substitution is logged once per stage run") and `llm.roles.<role>.fallback` for all three roles. **AD-8, AD-9 and AD-10 mention fallbacks nowhere.** So: does the fallback mechanism apply to `Stt` and `Embedder`? Who decides "unavailable"? Is a silent substitution permitted in an eval run whose config snapshot (AD-10) then does not describe what actually ran?

The AD-9 amendment makes this sharper rather than softer. It admits an operator-scheduled network dependency into a pipeline stage, records that "VM 120 and VM 116 pass through the same GPU and must not run at once," and then explicitly declines to require a local fallback. Declining the fallback is a legitimate decision; leaving undefined what the `transcribe` stage *does* on connection-refused is not. The Errors convention covers a stage failure recorded on the job row, and AD-11 gives idempotent restartable stages — that may well be the intended answer, but the amendment does not say it, and the shipped `fallback` keys say something different.

**Fix:** one clause in AD-8 — fallback is a per-port config key, substitution is logged and recorded in the eval config snapshot, and a remote host being down is a stage failure (AD-11 retry), not a silent engine swap.

### F-11 (Medium) — Post-augmentation drop identity is ambiguous, and the ambiguity arises every time

AD-14 speaks of "the occurrence's **current** drop" (singular pointer, re-armed in place). The Recovery convention row speaks of "a meeting's **drops** ... in emit order" (a set). AD-14 also requires an augmenting drop to carry *every transcript the occurrence's current drop carries*. So after every augmentation the same transcript bytes exist in two finalized drops at two different `<drop-dir>/<filename>` anchors, with identical `sha256`.

The spine does not say whether arrived-material rows are re-pointed to the new drop or retained against the old, nor which drop `align` re-parses on the next stage run. `transcript_source` has `UNIQUE (meeting_id, kind)` (`0005:52`), so one of the two paths silently wins — a mechanism, not a decision.

**Fix:** state in AD-3 or AD-14 that arrived-material rows re-point to the re-armed job's drop (and that the superseded drop stays on disk for emit-order replay), or that they do not. Either answer is fine; the silence is not, because AD-17 makes each of those paths a stored row.

### F-12 (Low) — `glossary.md` still gives the pre-amendment answer

`glossary.md:171-173`: "**Content root** (`MM_CONTENT_ROOT`) — the one directory under which **video**, extracted frames and screenshots live." There is no **Drops root** entry. The glossary is a `SPEC.md` companion and the doc most likely to be consulted for a term, and it now states exactly the belief the amendment was written to correct: one root, video under it.

Related, and worth a line: the spine's `sources:` lists SPEC, scope, storage-layout, eval-strategy, eval-design and ux-spine — **not** `glossary.md`, although AD-13 and AD-14 use terms (`transcript:<start_ms>` identity key, `viewable` / `evidence_complete`) that are defined only there.

**Fix:** update the glossary's Content root entry, add a Drops root entry, and add `glossary.md` to the spine's `sources:`.

### F-13 (Low) — Only one of the two LAN hosts is recorded

`corpus-facts.md` §5 and `glossary.md:301-302` name **two** LAN model hosts: an Ollama host serving embeddings (in production use) and VM 120 `cuda-asr`. The amendment records VM 120 in detail and leaves Ollama drawn as a Mac host process at `:11434` inside the MacBook box — which matches `config.yaml`'s `providers.ollama.base_url: http://localhost:11434` today, but means the one adapter that already makes a LAN HTTP call (`adapters/embed/ollama.py`) is depicted as local. Since the Structural Seed asserts "MeetingMiner leaves the Mac in exactly two directions and no others," the omission weakens the sentence it sits next to.

**Fix:** name the Ollama embeddings host in the `lan` node alongside VM 120, or state that Ollama is bound to localhost today and the LAN host is the alternative binding.

### F-14 (Low) — Residual AD-1 contradiction from the prior review's F-1

The prior review offered two fixes for the three-way puller-intake disagreement. Option (b) was taken in the module-structure caption — "its only contracts are the source-drop format (AD-1) and the public `POST /ingests` call (AD-14)" — and the deployment diagram gained the `pullercli -->|POST /ingests| api` edge. But **AD-1's Rule still ends "the puller emits only drops and never knows the pipeline."** The half-applied fix leaves the contradiction inside the AD rather than between two diagrams.

**Fix:** amend that clause in AD-1 to match the caption.

### F-15 (Low) — Source-tree seed drift

- `adapters/llm/` is named in the seed and does not exist (`adapters/` has `ocr/ stt/ embed/ diarize/`).
- `evals/runs/` is named in the seed and in the deployment diagram; it does not exist yet.
- `puller/` is a **git symlink** to the real `pull_transcript/` directory.
- The seed omits `server/meetingminer/migrations/` and `server/tests/`.

Harmless individually; collectively the seed no longer reads as ratified. One pass to reconcile.

### F-16 (Low) — "No silent zero" has no home in the spine

`SPEC.md` carries it as a Constraint binding CAP-5 extraction and every CAP-7 check that counts what a stage produced, with a measured incident behind it (`retrieval-prior-art.md` §8, decisions 41 → 182). It is a cross-unit rule: the `extract` stage and each eval counting check must treat an empty parse identically. The spine's Errors convention covers a stage *failure*; a zero result is not a failure, which is the entire point of the constraint. Nothing in the spine carries it.

**Fix:** one clause in the Errors convention row, or in AD-8 alongside the port contract.

## 3. Checklist verdicts

**Fixes the real divergence points for the level below; misses none.** Mostly yes — the drop schema (AD-1), single database of record (AD-2), single projection writer (AD-4), disjoint table ownership (AD-5), citation wire format (AD-15), the intake door (AD-14) and the `start_ms` identity invariant (AD-13) are exactly the seams where Epic 1–5 stories would otherwise diverge, and the AD-13/AD-14 pair is the strongest work in the document: it makes augmentation citation-safe by construction. **One miss:** the transcript-only source deep link (F-4), which spans pipeline, projections, api and web and has already gone wrong once.

**Every Rule enforceable and actually prevents its stated divergence.** No for two. **AD-17** cannot be enforced as written (F-1: its own reference table fails it; F-2: its scope is unbounded and the story below already deviates). **AD-9** states a rule — destination is config, never code — that the shipped adapter layer cannot honour for the stage it names (F-3). The remaining fifteen ADs name mechanical checks rather than aspirations.

**Nothing under Deferred could let two units diverge.** No. "Exact Postgres DDL and column sets" now sits under AD-17's column mandate and above an ERD missing three AD-named entities (F-2, F-9); the recording's carrier table and column names are live disagreements between the spine and story 2.1a. Every other Deferred entry remains safe — single-writer-owned, companion-owned, or genuinely product-later.

**Ratifies rather than contradicts the brownfield.** Mixed. The AD-5 dedup ratification is verified exactly right (`pipeline/speakers.py:133-165`, mail-else-normalized-name, no AAD id anywhere, `participant_alias` at `0005:104-108`), as is the AD-13 `start_ms` / `stt_start_ms` / `alignment_delta_ms` invariant (`0005:167, 197-198`). Against that, AD-3 and AD-17 assert as current a state the tree does not have (F-6), AD-9 asserts a swap mechanism the adapters do not have (F-3), and `MM_DROPS_ROOT` does not exist in the server at all (F-5).

**Covers the driving spec's capabilities, especially `storage-layout.md`.** Substantially — AD-3 carries §1, §2 and §4 faithfully, and AD-17 carries §5. Two gaps: the publish folder's anchor, where the spine and `storage-layout.md` §1/§3 disagree three ways (F-8), and §6 (bring-your-own-recording), which AD-1's "future YouTube, local recording" clause covers only glancingly while story 2.1b is already frozen against it. CAP-1's and CAP-4's deep-link requirement is uncovered (F-4).

**Every dimension the altitude owns is decided, deferred, or an open question.** One silent dimension in the operational envelope: adapter unavailability and the fallback mechanism that is already shipped in `config.yaml` but appears in no AD (F-10) — made load-bearing by the amendment's admission of an operator-scheduled remote host. Backup, secrets, logging, error surface, recovery and the deployment envelope are all now decided; the Recovery row in particular is materially better than it was on 2026-08-18.

**Amendments vs untouched parts.** Four contradictions with untouched text, all listed above: AD-3's env vars vs AD-10 and the Config row (F-5); AD-17's path shape vs AD-3's (F-1); AD-9's config-only claim vs AD-8's port enumeration (F-3); AD-3's API-reads-the-drop consequence vs both diagrams and the responsibilities table (F-7).

---

## 4. Recommended order of fixes

1. **F-1 + F-2** — make AD-17 enforceable: decide anchor granularity, scope the file classes, name the recording's carrier table and column names, narrow the Deferred DDL entry. Blocks story 2.1a and Epic 2.
2. **F-3** — amend AD-8's `Stt` enumeration and restate AD-9's swap rule accurately. Blocks any use of VM 120.
3. **F-4** — give the source deep link an invariant. Blocks Epic 2 story 2.2 and Epic 3 story 3.4.
4. **F-8** — decide the publish-folder anchor and correct `storage-layout.md` §1. Blocks Epic 4.
5. **F-5, F-6, F-7, F-9, F-10, F-11** — one editing pass; none blocks work in flight.
6. **F-12 … F-17** — housekeeping, best done in the same pass.
