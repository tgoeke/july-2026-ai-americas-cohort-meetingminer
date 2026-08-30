# Reviewer Gate — Web-Verification / Reality-Check Lens

- **Target:** `_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md`
- **Lens:** every committed decision must be web-researched or reality-checked, not asserted from training data. Current library/framework versions; each named technology still exists and fits; live defaults of anything the design leans on.
- **Review date:** 2026-08-19 (spine `updated: 2026-08-19`, Stack table stamped "verified current 2026-08-17")
- **Method:** live web fetches against PyPI / npm registry / GitHub releases / Docker Hub / vendor docs, plus direct reads of the working tree at `main` (949c293).

## Verdict

**Accept with fixes.** The Stack table is fully current — all eighteen rows re-verified against upstream today, zero stale entries, and the three container pins in `infra/docker-compose.yml` match it exactly. `nvidia/parakeet-tdt-0.6b-v3` exists and behaves as described, and the ~227× figure is a locally measured number with recorded provenance, not a training-data guess. The failures are not version drift; they are **four spine claims that state as already-true things the tree does not yet do**, and one that the tree contradicts outright. Those are fixable by wording, not by redesign.

---

## Part 1 — Stack table, re-verified 2026-08-19

| Row | Spine claims | Verified upstream today | Verdict |
| --- | --- | --- | --- |
| Python | 3.12+ | 3.14 is current; project pins `requires-python = ">=3.12,<3.13"` (`server/pyproject.toml:10`) because MLX ASR wheels have no 3.14 build | ⚠ row is looser than the code |
| FastAPI | 0.141.x | 0.141.1, released 2026-07-29 | ✅ |
| Postgres | 18 | 18 is the current major; 18.6 released 2026-08-13; supported to 2030-11-14 | ✅ |
| pgvector | 0.8.x | v0.8.6, tagged 2026-07-29 | ✅ |
| Neo4j Community | 2026.07 (arm64 image) | 2026.07.1 released 2026-08-07 — the newest CalVer release; no 2026.08 yet. Official image publishes amd64 + arm64v8; `neo4j:2026.07.1-community` on Docker Hub | ✅ (see note below) |
| neo4j-graphrag | 1.18.x | 1.18.0, released 2026-06-24 | ✅ |
| Meilisearch | 1.53.x (arm64 image) | v1.53.1 released 2026-08-13; `getmeili/meilisearch` is multi-arch amd64 + arm64 | ✅ |
| meilisearch (Python SDK) | 0.43.x | 0.43.0, released 2026-07-22 | ✅ |
| LiteLLM | ≥1.97 | 1.97.0, released 2026-08-16 | ✅ version; ⚠ not yet a dependency (below) |
| Ollama (host) | 0.32.x | v0.32.14 released 2026-08-15 (v0.32.15 pre-release 2026-08-19) | ✅ |
| mlx-whisper | 0.4.x | 0.4.3 — **last released 2025-08-29**, ~12 months dormant | ✅ correct, ⚠ dormant upstream |
| parakeet-mlx | 0.5.x | 0.5.2, released 2026-06-05. Default model is `mlx-community/parakeet-tdt-0.6b-v3` | ✅ |
| pytest | 9.1.x | 9.1.1, released 2026-06-19 | ✅ |
| Vite / React / TypeScript | 8.x / 19.x / current | Vite 8.2.1; React 19.2.8 | ✅ |
| shadcn/ui | CLI v4 (Vite template, Base UI) | CLI v4 shipped March 2026: first-class `init` templates incl. Vite, and a `--base` flag selecting Base UI or Radix primitives | ✅ |
| @hey-api/openapi-ts | 0.99.x | 0.99.0 | ✅ |
| Node (puller) | current LTS | v24 "Krypton" is Active LTS; v26 is Current | ✅ |
| ffmpeg | current brew | not version-pinned; nothing to drift | ✅ |

**Container pins cross-check** — `infra/docker-compose.yml` pins `pgvector/pgvector:pg18`, `neo4j:2026.07-community`, `getmeili/meilisearch:v1.53`, each by digest. All three match the table and all three are the current upstream release today. The Stack table and the deployed infra do not disagree.

### Stack-table findings

**S-1 (low) — the Neo4j row goes stale monthly by construction.** Neo4j moved to CalVer at 2025.01 and ships a feature release every month; 2026.07.1 is only current because 2026.08 has not landed yet. Pinning `2026.07` in a document stamped with a verification date means this row is wrong roughly thirty days from now, every month, forever. Either say "current CalVer release, pinned by digest in `infra/docker-compose.yml` — that file is authoritative", or pin to an LTS line. The digest pin in compose is the real contract; the spine row should defer to it rather than duplicate a number that rots.

**S-2 (low) — "Python 3.12+" contradicts the project's own pin.** `server/pyproject.toml:10` is `>=3.12,<3.13`, and its comment gives the reason: mlx-whisper and parakeet-mlx publish no wheel for 3.13/3.14. A builder reading "3.12+" may reasonably provision 3.13 and hit an unresolvable lock. Write `3.12 only (MLX ASR wheels)`.

**S-3 (low) — mlx-whisper is dormant, and nothing in the spine acknowledges the risk.** 0.4.3 is the correct current version, but it was published 2025-08-29 — twelve months without a release, against a Python-version pin that exists *because of* that package. This is the STT default engine in `config.yaml`. Not a version error; a supply-risk the spine should name once, since `parakeet-mlx` (released 2026-06-05, actively maintained, and defaulting to the same parakeet-tdt-0.6b-v3 the LAN host serves) is already the configured alternative.

**S-4 (low) — two direct dependencies are missing from the table.** `server/pyproject.toml` pins `neo4j>=6.0,<7` (the Bolt driver; 6.2 is current) and `psycopg[binary]>=3.2`. The table lists `neo4j-graphrag`, an *optional* helper per AD-7, but not the driver the code actually connects with. If the table's job is to freeze versions for build, the driver belongs in it more than the optional helper does.

**S-5 (informational) — `claude-sonnet-5` is a valid, current model ID.** AD-10's default binding and `config.yaml`'s three role bindings all name `claude-sonnet-5`. Verified current: Claude Sonnet 5, 1M context, $3/$15 per MTok — with introductory pricing of $2/$10 **expiring 2026-08-31**. Any eval cost estimate in `eval-design.md` computed at the intro rate is about to be 50% low. Flagging so the number is re-checked, not because the binding is wrong.

**S-6 (informational) — the Deferred section's Neo4j vector note is correct.** "Neo4j Community indexes `LIST<FLOAT>` embeddings; the native `VECTOR` property type is Enterprise-only" — confirmed. The native VECTOR type requires server ≥ 2025.10 **Enterprise**; Community continues to index `LIST<INTEGER | FLOAT>` properties, and vector indexes accept both forms. This claim was reality-checked correctly.

---

## Part 2 — Priority claims

### P-1 — `nvidia/parakeet-tdt-0.6b-v3` and the VM 120 description

**Model exists and the core description is accurate.** Verified on Hugging Face: released 2025-08-14, FastConformer-TDT architecture, 600M parameters, 25 European languages, runtime NeMo 2.4. It emits **char-, word-, and segment-level timestamps natively** — the spine's "native NeMo timestamps" is correct and is not a training-data assumption. The model card describes no speaker diarization. Published RTFx on the Open ASR Leaderboard is 3,332.74 (datacenter GPUs, batched), so the spine's ~227× end-to-end on one RTX 4080 with upload, resampling and chunking overhead is not implausible.

**The ~227× figure has provenance.** `_bmad-output/specs/spec-meetingminer/corpus-facts.md:206` records it as measured on the host's own 600-second benchmark (~2.4 s model time per 10 minutes of audio), with health verified live from the dev machine on 2026-08-19. This is reality-checked, not asserted. Good.

**P-1a (medium) — "no diarization" contradicts this project's own verified record.** The spine's Structural Seed says of VM 120: "native NeMo timestamps, no diarization." But `corpus-facts.md` §5 states the opposite about the *host*, under a heading that calls it out explicitly: "**Diarization is available on that host, contrary to the handoff's silence on it.** Verified by inspection 2026-08-19: the installed NeMo carries `clustering_diarizer.py`, `msdd_models.py`, `online_diarizer.py`, `sortformer_diar_models.py` and TitaNet speaker-embedding `label_models.py`. What is missing is not capability but deployment — no diarization weights are in the caches and the running service exposes only `/health` and `/transcribe`." The correct statement is that *the deployed `/transcribe` endpoint does not diarize, and the parakeet model itself does not*, while *the host can, given a model pull and an endpoint*. As written, the spine forecloses the one deployment path AD-8's `Diarizer` port (`noop | pyannote`) most plausibly grows into, and a builder reading only the spine would never look. Fix the sentence to distinguish model, service, and host.

**P-1b (low) — RTX 4080 is not on the model card's tested architecture list.** The card names Ampere, Blackwell, Hopper and Volta as supported, and lists A10/A100/A30/H100/L4/L40/T4/V100 as tested. The RTX 4080 is Quinn Harper — absent from both lists. It plainly works (the 227× benchmark ran on it), so this is not a blocker; but the spine's framing — "available infrastructure rather than a best-effort dependency, and no rule here requires a local fallback for a stage that names it" — is a strong commitment resting on an arch the vendor does not list. One clause acknowledging that the deployment is validated locally rather than vendor-tested would make the commitment honest.

**P-1c (informational) — CUDA 12.9 and Ubuntu 24.04 were dropped between memlog and spine.** Both `_bmad-output/specs/spec-meetingminer/.memlog.md:195` and the architecture memlog record `RTX 4080, CUDA 12.9`, and corpus-facts adds Ubuntu 24.04. The spine keeps neither. Given the model card names Linux as the preferred/supported OS and NeMo 2.4 as the runtime, the OS/CUDA pair is the load-bearing part of "this host can serve this model". Not wrong to omit from a spine, but if the host is named at all, its runtime should be too — otherwise the one fact a reader needs to reproduce it lives only in a memlog.

### P-2 — AD-3's two-root claim vs the real schema

**The schema half is confirmed.** `server/meetingminer/migrations/0005_transcripts_participants.sql` carries exactly the two-anchor shape AD-3 and AD-17 describe: `drop_relative_path text` ("Path inside the source drop… the drop itself is never written (AD-13). NULL for the STT lane"), `content_path text` ("Path relative to MM_CONTENT_ROOT (AD-3)… NULL for a provided source"), plus `sha256 text NOT NULL` and `byte_size bigint NOT NULL CHECK (byte_size >= 0)`. AD-17's designation of `transcript_source` as the reference row shape is accurate. `server/meetingminer/domain/drops.py` is consistent: it reads a drop and never writes, renames or deletes inside one.

**P-2a (high) — the drops-root half of AD-3 is not implemented server-side, and the spine states it as an invariant in force.** Three concrete contradictions in the tree:

1. **`MM_DROPS_ROOT` does not exist in the server.** `server/meetingminer/config.py`'s own module docstring says environment variables carry "secrets and `MM_CONTENT_ROOT` **only**", and `Secrets` (`config.py:504`) declares `mm_content_root` and nothing else. There is `require_content_root`; there is no `require_drops_root`. The variable exists only in the JS puller (`pull_transcript/emit-drop.js`, story 1.8), on the emitting side.
2. **An absolute drop path is stored in the database and does leave the server.** `migrations/0001_jobs.sql:7` declares `drop_path text NOT NULL`; `api/ingests.py:131` `_validate_drop_path` *requires* the path to be absolute (`400 invalid-drop-path` otherwise); and `api/jobs.py:36,95` selects `j.drop_path` and returns it on the job resource. AD-3 says flatly "Neither root's absolute location is stored in a database or leaves the server." Today it is both.
3. **`drop_relative_path` is not anchored where AD-3 says.** AD-3: arriving material "is recorded as `<drop-dir>/<filename>` against the drops root." Actual: `pipeline/stages/align.py:201` writes `"drop_relative_path": path.name` — the bare filename, relative to the drop directory, which is itself located only by the absolute `job.drop_path`. The migration comment agrees ("relative to the drop directory"), so the schema and the spine describe two different anchors.

This is **tracked**: `_bmad-output/implementation-artifacts/spec-2-1a-evidence-paths-anchored-to-configured-roots.md` is a registered story that adds `MM_DROPS_ROOT` with `require_drops_root`, converts `job.drop_path` to a drop-relative path, adds a containment check at intake, and backfills existing absolute rows. So the design is agreed and the gap is scheduled. The defect is that the spine gives no signal that AD-3 describes a target state — a builder auditing today's code against AD-3 finds three violations and no way to tell them from bugs. Mark the drops-root anchor as pending story 2-1a, the way a spine normally marks an ADOPTED-vs-proposed decision.

### P-3 — AD-5's dedup key vs `pipeline/speakers.py`

**Confirmed exactly, clause by clause.** `identity_key_for(label, mail)` (`server/meetingminer/pipeline/speakers.py`) returns `f"{MAIL_NAMESPACE}{address.casefold()}"` when `mail` contains `@`, else `f"{NAME_NAMESPACE}{normalized}"`, with `MAIL_NAMESPACE = "mail:"` and `NAME_NAMESPACE = "name:"` declared as module constants. `normalize_display_name` does precisely what AD-5 says: NFKC normalize, strip parenthetical/bracketed qualifiers via `_QUALIFIER` (the docstring cites `(CNTR)` and `(Foster, Logan)` — the same two examples AD-5 uses), reorder two-part `Last, First` to `First Last`, collapse whitespace, casefold. `migrations/0005` backs it: `participant.identity_key text NOT NULL UNIQUE`, and `participant_alias(alias_key PRIMARY KEY → participant_id)` as the API-owned merge table the worker resolves through before insert. No Microsoft Graph or AAD object ID appears anywhere in the key path — the SPEC non-goal holds, and both the module docstring and the migration comment state that mail comes from the SharePoint user-profile service. This claim needed no correction.

**P-3a (low) — one unstated edge.** `identity_key_for` returns the **empty string** when there is no mail and the label normalizes to nothing. AD-5's phrasing ("deduplicating by the mail address … else by normalized display name") admits no third outcome. The empty key would violate `identity_key NOT NULL UNIQUE` semantics if it ever reached an insert; callers appear to filter placeholders upstream, but the spine's absolute phrasing does not cover the case. One clause, or a note that placeholder-only labels never become participants (which `roster_from_labels` and `is_placeholder_label` enforce).

**P-3b (low) — the spine understates the corpus caveat that the code documents.** `speakers.py` and `migrations/0005` both warn that a name-only key holds "only while no two people share a name — true of the 50 distinct people here and false of the 150-person store upstream", and that the failure mode is a **silent** merge of two humans. AD-5 presents the name fallback with no such caveat. Given `corpus-facts.md` §6 records a 269-row upstream library, this is a known scaling limit of a committed invariant and belongs in the invariant, not only in the code comment.

### P-4 — AD-13's `start_ms` claim vs migration 0005 and `align.py`

**Schema confirmed.** `transcript_segment` has `start_ms bigint NOT NULL CHECK (start_ms >= 0)` alongside nullable `stt_start_ms`, `alignment_delta_ms`, and `match_score`, under an all-or-none CHECK that also covers `stt_source_id`. The separation AD-13 requires is structurally enforced.

**P-4a (medium-high) — "always" is false on the no-provided-transcript path.** AD-13 states: "`transcript_segment.start_ms` **always** carries the provided transcript's cue timing, and the STT lane writes its matched start and signed offset into the separate nullable `stt_start_ms` / `alignment_delta_ms` columns — never over `start_ms`." In `server/meetingminer/pipeline/stages/align.py`, `run()` selects its base segments in three branches. When a provided transcript exists, the claim holds — `base = label_source.segments` and the STT match only ever populates the anchor columns. But when no transcript is provided:

```python
elif stt is not None:
    # No provided transcript at all: the derived segments *are* the STT
    # segments, every speaker label the `Unknown` placeholder (AD-13).
    label_source_id = stt.id
    base = stt.segments
```

and the INSERT then writes `"start_ms": segment.start_ms` from those STT segments. So for a recording-only drop, `start_ms` **is** STT timing. AD-13's own next-but-one sentence half-admits this ("When no transcript is provided … STT segments carry an `Unknown` speaker placeholder"), which makes the "always" an internal contradiction as well as a tree contradiction.

Why it matters rather than being pedantry: AD-13 rests moment identity on this rule and warns that "a capture or segmentation retune that writes STT timing into `start_ms` breaks every pre-existing citation, silently." For every recording-only meeting, that is already the standing condition — the `transcript:<start_ms>` identity key is STT-derived, so a recognizer swap (`mlx-whisper` → `parakeet-mlx`, both bindable per AD-8) or an `align` retune re-keys those moments and invalidates their citations. The invariant should say so, and the risk should be named, e.g.: *"carries the provided transcript's cue timing whenever the drop provides one. When no transcript is provided, the STT segments are the derived segments and their timing is the identity anchor — so a recognizer or segmentation change re-keys that meeting's moments, and those meetings must be re-projected."* Note AD-14 currently shields this in practice, since an augmenting drop may not shed a transcript the occurrence already has — but the shield is incidental, and the spine does not say it is the shield.

**P-4b (low) — the anchor column set is named incompletely.** AD-13 names `stt_start_ms` and `alignment_delta_ms`. The schema's all-or-none CHECK binds four columns: `stt_source_id`, `stt_start_ms`, `alignment_delta_ms`, **`match_score`**. `match_score` is the token-overlap score that justified the anchor and is the only column that lets a reviewer judge an alignment. A builder matching AD-13 literally would omit it.

### P-5 — AD-9's "inference location is purely a `config.yaml` binding"

**P-5a (high) — false for the `Stt` port as built; unbuilt for the `Llm` port.** AD-9 asserts that whether an engine runs in-process, on a LAN host over HTTP, or behind a provider API "is a `config.yaml` binding (`providers.<name>.base_url`, AD-10) resolved through the AD-8 ports, **never a code change and never an architecture change**." Against the tree:

- **`SttConfig.engine` is a closed enum.** `server/meetingminer/config.py:123` declares `engine: Literal["mlx-whisper", "parakeet-mlx"]` and `model: NonEmptyText`. There is no `provider`, `base_url`, or endpoint field on the STT binding.
- **The adapter registry says so in its own words.** `server/meetingminer/adapters/stt/__init__.py`: "Engine name in config.yaml -> implementation. **Adding an engine is one entry here plus the Literal in `meetingminer.config`**; no stage changes." That is a two-file code change, not a config edit.
- **Both implementations are in-process Apple-Silicon MLX.** `adapters/stt/` contains only `mlx_whisper.py` and `parakeet_mlx.py`. No HTTP client, no remote engine, nothing that could target `http://10.77.0.120:8000`.
- **`config.yaml`'s `providers:` block lists only `anthropic`, `openai`, `openrouter`, `ollama`** — no LAN host entry, and nothing wires any `providers.*.base_url` to the `Stt` port. `AppConfig.providers` is typed `dict[str, ProviderEndpoint]`, so the *config schema* would accept a `cuda_asr` entry today; the *port* has no way to consume it.
- **The `Llm` half is entirely unbuilt.** There is no `server/meetingminer/adapters/llm/`, and `litellm` is not among `server/pyproject.toml`'s dependencies. AD-8's "`Llm` (per role: extraction, chat, judge — via LiteLLM)" and AD-9's provider-API path are design intent with no implementation to check against.

So the Structural Seed's statement that MeetingMiner reaches VM 120 for ASR "via AD-8 ports" over HTTP is, today, unimplementable without new code. The open `providers` dict makes the *destination* configurable; the closed engine enum makes the *engine* a code change. Either AD-9 should say that placing an engine remotely is a config edit **once an adapter for that transport exists**, or a `remote-http` STT engine plus an endpoint field on `SttConfig` should be a named story. As written, AD-9 promises a swap that would fail on a Pydantic `Literal` validation error.

**P-5b (informational) — the OCR fallback shape is real and the STT one is deliberately absent.** `config.yaml`'s `ocr.fallback` and `OcrConfig.fallback` exist; `SttConfig` documents having no fallback key on purpose ("two recognizers silently producing one corpus's verification lane would make `alignment_delta_ms` incomparable across meetings"). This is consistent with the spine's "no rule here requires a local fallback for a stage that names it." No finding — noting it because it is the one place where the absence of a config key is a decision rather than an omission.

---

## Part 3 — Other reality checks performed

- **AD-1's schema claims verified in-tree.** `docs/source-drop.schema.json` declares `schemaVersion` with `enum: [1, 2]` and the documented description ("2 adds the optional `augments` declaration and is required whenever `augments` is present"), and an `augments` property is present. AD-1's version-2 paragraph matches the artifact.
- **AD-14's uniqueness argument verified.** `meeting.job_id` / `meeting.source_id` UNIQUE and `job_source_id_live_key` are cited in `spec-1-12-late-recording-augmentation.md` against `0002:28-29` and `0001:18-20`. The "a second job could never own the meeting" argument rests on constraints that exist.
- **AD-17's reference-row claim is right about the columns, wrong about one.** `transcript_source` carries path, `sha256`, `byte_size` — but **no stage column**. AD-17 requires every evidence row to name "the stage that wrote or read it" and then designates `transcript_source` as the shape to match "rather than re-invent". A builder matching 0005 will not produce a stage column; `kind`/`format`/`engine`/`model` are what 0005 actually carries. **(medium-low)** — either name the substitute (`kind` identifies the lane) or stop calling 0005 the complete reference shape.
- **`config.yaml` ↔ spine consistency.** Embedder `qwen3-embedding:0.6b` at dimension 1024 matches AD-8's "fixed 1024-dim vector space"; the three LLM roles match AD-10's stated defaults including the `judge` placeholder pending the Epic 5 bake-off; Meilisearch settings are declared in config rather than left to store defaults, as AD-4's rebuild-determinism argument requires. No drift found.

---

## Fix list, in priority order

1. **P-5a (high)** — AD-9: qualify "never a code change". Placing an engine on a LAN host is config-only *for ports that have a remote adapter*; the `Stt` port has none, and its engine enum is closed. Add a story for a remote-HTTP STT engine, or restate the invariant.
2. **P-2a (high)** — AD-3: mark the drops-root anchor as pending story 2-1a. Today `MM_DROPS_ROOT` is absent from `config.py`, `job.drop_path` holds an absolute path, and `GET /jobs` returns it — three literal contradictions of the rule as written.
3. **P-4a (medium-high)** — AD-13: drop "always". State that `start_ms` carries STT timing when no transcript is provided, and name the citation-re-keying consequence for recording-only meetings.
4. **P-1a (medium)** — Structural Seed: "no diarization" is true of the model and the deployed endpoint, false of the host. `corpus-facts.md` §5 verified diarization capability on VM 120; say which of the three the sentence is about.
5. **AD-17 (medium-low)** — either add a stage column to the reference shape or stop describing 0005 as complete for AD-17's purposes.
6. **S-1, S-2 (low)** — Neo4j row defers to the compose digest pin; Python row says 3.12 only.
7. **P-1b, P-3a, P-3b, P-4b, S-3, S-4, S-5 (low / informational)** — as detailed above.

## What this lens found no fault with

Every version in the Stack table; the three container image pins; the existence, timestamp behaviour, and diarization-absence of `nvidia/parakeet-tdt-0.6b-v3` itself; the provenance of the ~227× benchmark; the `claude-sonnet-5` model ID; the Neo4j Community `LIST<FLOAT>` vs Enterprise `VECTOR` note; AD-5's dedup key in full; the AD-1 drop-schema version claims; and the two-column anchor shape in migration 0005. On the specific question this gate exists to answer — *was this researched or asserted?* — the Stack table and the model choice were researched, and the four flagged invariants were reasoned from intent rather than checked against the tree.
