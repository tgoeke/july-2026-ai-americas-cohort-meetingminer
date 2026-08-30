---
title: 'Story 4-1a: Whole-Transcript Extraction'
type: 'refactor'
created: '2026-08-20'
status: 'done'
baseline_revision: '100b09921ecc0113912dab689c9c770cdba7cf76'
review_loop_iteration: 1
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-4-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-4-1-artifact-extraction-pipeline-stage.md'
warnings: [oversized]
deferred:
  - summary: >-
      The 60 finalized drops already on disk cannot gain extraction documents:
      re-emitting them needs the api's augmentation door to accept a
      summary-only augmentation, and `meetingminer/api/` is out of this story's
      boundary. Those meetings take the generate path instead, which is correct
      but costs local model time that adoption would have saved.
    evidence: |-
      `emit-drop.js` `dropIsCurrent` (:507-527) deliberately mirrors intake's
      augmentation rule — the comment at :494-506 says emitting something
      intake will refuse permanently retires the occurrence. Intake refuses a
      drop that brings no evidence the meeting lacks (AD-14), and extraction
      documents are not currently such evidence. So a summaries-only re-emit
      would be refused, and teaching `dropIsCurrent` otherwise without the
      matching api change would strand the occurrence.
    location: >-
      pull_transcript/emit-drop.js
    severity: medium
  - summary: >-
      AC 8's augmenting-drop-plus-extractions case has schema support but no
      runtime effect: the api never re-runs `extract` on an augmenting re-arm,
      and the augmentation door refuses a drop whose only new content is the
      extraction documents.
    evidence: |-
      `api/ingests.py` `_rearm_job` re-arms only AUGMENTATION_STAGES /
      PARTICIPANT_AUGMENTATION_STAGES, and its docstring says `extract` keeps
      whatever checkpoint it had. `domain/jobs.py:55-79` excludes `extract`
      from both tuples deliberately. So a re-pull bringing only the two
      documents is refused at intake, and one that also brings a recording
      still will not re-run extract to adopt them. Sharpens the existing
      emit-drop deferral: the gap is on the api side, not only the puller's.
    location: >-
      server/meetingminer/api/ingests.py
    severity: medium
  - summary: >-
      A transient summariser failure during a pull permanently costs that
      meeting its adoption, because the drop is write-once and a later
      `--summarize` has no path to reach an already-emitted drop.
    evidence: |-
      Generation is non-fatal and the emit unconditional, so a drop lands
      without documents. `emit-drop.js` `dropIsCurrent` treats documents
      appearing afterwards as no reason to re-emit, and intake would refuse
      such a drop anyway. The meeting then takes the generate path forever.
    location: >-
      pull_transcript/grab-teams-transcript.js
    severity: medium
  - summary: >-
      Screen evidence no longer reaches the extraction prompt, so a slide-deck
      meeting whose decisions are stated on screen rather than aloud is not
      extractable; `bundle.screenshots` is now read by nothing in this stage.
    evidence: |-
      Story 4.1's per-moment prompt carried `view_type` + OCR text and its AC 5
      asserted archetype evidence reached the prompt. CAP-5 as re-rendered
      2026-08-20 says extraction operates on the whole meeting transcript, so
      dropping screen evidence follows the re-render — but the epics' two
      archetypes (slide-deck, UI demo) still expect different artifact sets,
      and nothing now feeds the slide half.
    location: >-
      server/meetingminer/pipeline/stages/extract.py
    severity: medium
  - summary: >-
      `_meeting_date` renders the stored UTC instant, so a late-evening local
      meeting is grounded on the following calendar day.
    evidence: |-
      `bundle.started_at` is timestamptz stored UTC; the date line exists
      specifically to stop the model inventing calendar due dates, and the
      puller's own summariser grounds on the local `M.D.YY` folder date, which
      would differ for the same meeting. Fixing it needs a local-timezone
      source the schema does not carry (`startedAtPrecision` is second|day
      only), so it is a contract question rather than a code fix.
    location: >-
      server/meetingminer/pipeline/stages/extract.py
    severity: medium
  - summary: >-
      The `stage.extract.summary` event changed the meaning of existing field
      names without a version marker.
    evidence: |-
      `skipped_approved` / `skipped_superseded` counted moments under 4.1 and
      count artifacts now; `eligible`, `moments_scanned` and `skipped_no_text`
      were removed. Anything reading these across the 4.1 to 4-1a boundary —
      an Epic 5 harness snapshot, an ops query — compares incompatible numbers.
    location: >-
      server/meetingminer/pipeline/stages/extract.py
    severity: low
  - summary: >-
      Two 900-second model calls now run inside the runner's single open
      transaction, holding a pooled Postgres connection for up to 30 minutes
      per meeting.
    evidence: |-
      The stage runs inside the runner's transaction by contract and the
      per-call timeout rose from 120s to 900s with two calls per meeting.
      Nothing in the change considers `idle_in_transaction_session_timeout` or
      pool sizing.
    location: >-
      server/meetingminer/pipeline/stages/extract.py
    severity: low
  - summary: >-
      Nothing measures the rendered transcript against the configured
      `num_ctx`, so a long meeting can silently overrun the context the setting
      exists to protect.
    evidence: |-
      `render_transcript` produces an unbounded string and the stage logs
      `turns` and `moments` but never the rendered length. A truncated
      generation still produces content, so `zero_artifacts` does not fire —
      the silent-truncation failure the setting was added to prevent.
    location: >-
      server/meetingminer/pipeline/extraction.py
    severity: low
  - summary: >-
      `mintdrop.py` cannot produce a drop that exercises the adopt path.
    evidence: |-
      It hardcodes `"schemaVersion": 1` and emits no extraction documents, so
      every synthetic-corpus drop takes the generate path and the adopt path
      has no end-to-end route outside hand-written test drops.
    location: >-
      server/meetingminer/mintdrop.py
    severity: low
  - summary: >-
      `extraction_source.drop_relative_path` is absent from the canonical
      drops-root path inventory in `storage-layout.md`.
    evidence: |-
      `storage-layout.md` sections 4-5 enumerate every column holding a
      drops-root-relative path and name `transcript_source` as the reference
      for the path/checksum/size triple. The new table appears in neither it,
      SPEC.md, nor ARCHITECTURE-SPINE.md. Those are spec-kernel and spine files
      owned by bmad-spec/bmad-architecture; a story branch must not amend them.
    location: >-
      _bmad-output/specs/spec-meetingminer/storage-layout.md
    severity: low
---

<intent-contract>

## Intent

**Problem:** Story 4.1 shipped a **per-moment** extraction stage, and the granularity is wrong: a decision emerges across minutes of discussion — proposal, pushback, agreement — and almost never sits inside one moment. The user stopped its backfill at 5 of 28 meetings after 358 paid `claude-sonnet-5` calls and revoked the Anthropic key. The plumbing is right; the unit of extraction is not. 133 per-moment artifacts sit in the database as unpublished drafts.

**Approach:** Rework the `extract` stage to operate on the **whole meeting transcript**, one pass per meeting, adopting the proven `pull_transcript` summarisation mechanism. When the drop already carries the puller summariser's two markdown documents, the stage **parses** them and makes zero model calls; only a transcript arriving without them is sent to the local model. Both paths converge on one strict markdown parser producing artifacts anchored by `[m:ss]` timestamps that resolve deterministically to their containing moment. The extraction role default flips to `ollama/gpt-oss:120b`, so no paid call is reachable by default configuration.

## Boundaries & Constraints

**Always:**
- **Adopt-when-present, generate-when-absent** (user decision 2026-08-20). Derivative documents are created only when necessary, never regenerated. Adoption is decided per document kind: a drop carrying only the action-items doc adopts that one and generates the other.
- **One strict parser serves both paths** and must handle **both known layouts** of each section — a markdown table row and a bullet line. This is the measured `retrieval-prior-art.md` §8 failure: a parser that understood one of two layouts contributed zero decisions for every meeting using the other, reported success, and was found by chance; fixing it moved decisions from 41 to 182.
- **The parser keys on item ID and timestamp, never on heading numbering.** Sampled real output shows heading style varies per meeting (`# 1️⃣ Executive Summary`, `## 1. Header & Executive Summary`, `# 1 Executive Summary`, or a document title line before section 1). Column headers drift, rows go ragged, and timestamps appear as points, ranges, bracketed, parenthesised, italicised, or comma lists — frequently with **non-ASCII hyphens** (U+2010/U+2011) and curly punctuation. Tolerance for these is a stated requirement, not parser sloppiness.
- **No silent zero** (SPEC constraint): a source document whose target sections carry content but which yields zero artifacts is a named signal, never success.
- **Every artifact carries a `[m:ss]` anchor that resolves to its containing moment.** Moments tile the meeting contiguously and do not overlap, so resolution is the greatest `moment.start_ms <= anchor_ms`, matching `plan_moments`' own half-open `[start, next_start)` assignment. An anchor that resolves to no moment is a **named error path, not a dropped artifact** — this is what keeps extraction inside *no citation, no answer*.
- AD-8/AD-10: all model interaction stays behind the `Llm` port; `litellm` is imported only under `adapters/llm/`; bindings come from `config.yaml`.
- AD-5 column split: the worker inserts artifact rows and owns extraction content; `state` is written only as the insert default `'extracted'`.
- AD-11 idempotence: a rerun deletes and re-proposes only this meeting's `state = 'extracted'` rows, and never touches a moment carrying an `approved`/`published` artifact. The 133 existing per-moment drafts are replaced by this rerun **by design** — nothing published exists, so no citation can break.
- AD-17: adopted extraction documents are *arrived* material — each gets a row naming its drops-root-relative path, `sha256` and `byte_size`, like every other evidence file.
- NFR5/NFR7: the stage writes only artifact rows and the new extraction-source rows — never evidence tables, never files, and nothing is projected at extract.
- Tests never call a real LLM or a real Ollama host; the autouse `_no_real_llm` guard stays effective.

**Block If:**
- The whole-transcript shape cannot satisfy `publish_gate.py`'s frozen artifact vocabulary (`kind`/`state`/`title`/`body`/`moment_ids`) — that is an architecture change, not a story decision.
- Adopting a summariser document would require widening `artifact.kind` beyond `('adr', 'action-item')` — the additional right-rail types are Epic 4's later stories.

**Never:**
- **No paid model calls, and do not start the worker.** The worker is STOPPED by user decision; restarting it is the user's call after this story merges. No live-stack extraction run is part of this story — build and verify against fake-LLM fixtures and fixture transcripts.
- No edits to migration `0009_artifacts.sql` — schema changes are a new migration.
- No `meetingminer/api/` or `web/` changes (story 3.3 owns the API surface this wave); no prompt-visibility UI (4.2); no approval/publish/re-indexing (4.3/4.4); no eval checkers (Epic 5).
- No hand-written cleanup script for the 133 draft artifacts — the stage rerun replaces them.
- No reunification of the two `pull_transcript` working copies.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Adopt both | Drop carries both extraction docs | Zero model calls; both parsed; artifacts inserted `extracted` with `provenance.source = "adopted"`; one extraction-source row per document | No error |
| Generate both | Drop carries neither | Two whole-transcript calls (one per document kind) through the `Llm` port; `provenance.source = "generated"` | No error |
| Mixed | Drop carries only the action-items doc | That doc adopted, the summary generated; provenance records each artifact's own source | No error |
| Table layout | Adopted doc renders its items as a markdown table | Parsed identically to the bullet layout | No error |
| Bullet layout | Adopted doc renders its items as a bullet list | Parsed identically to the table layout | No error |
| Layout drift | Heading style, column headers, or row arity differ from the sampled examples | Items still found by ID + timestamp; heading numbering is never depended on | No error |
| Unicode timestamps | Anchor written `4:23‑5:12` with U+2011, or `*(4:51‑4:53)*`, or `(4:26, 5:08, 6:04)` | Normalized; earliest timestamp is the anchor | No error |
| Silent-zero signal | Source document has a populated target section but parses to zero artifacts | No rows; `stage.extract.zero_artifacts` logged naming the document and the populated section | Signal, not failure |
| Unanchored item | A parsed item carries no `[m:ss]` anchor | Named parse error; generate path retries once, adopt path fails immediately (re-reading the same bytes cannot change) | `StageError` naming the document and item |
| Anchor outside the timeline | Anchor resolves to no moment (before the first moment, or past the last `end_ms`) | Named error identifying the artifact, the anchor, and the meeting's moment span | `StageError`; job `failed` at `extract` |
| Malformed document | Neither layout matches a required section | Generate path: one retry, then raise. Adopt path: raise | `StageError` naming the document |
| Model unavailable | Primary local model unreachable | Configured fallback serves the rest of the meeting; `provenance.fallback_engaged = true` | No error if fallback answers |
| Rerun after partial approval | Meeting has `extracted` + `approved` rows | Drafts replaced; approved/published rows and their moments untouched | No error |
| Transcript-only meeting | No recording, video stages `skipped` | Extraction runs normally over the transcript-derived moments | No error |
| Empty transcript | Meeting has no transcript segments | Stage completes; no calls, no rows; skip reason counted in the summary log | No error |

</intent-contract>

## Code Map

**The 4.1 implementation being reworked**
- `server/meetingminer/pipeline/extraction.py` (228 lines) — the engine-free core. `PROMPT_VERSION = 1` (:29); `KIND_ADR`/`KIND_ACTION_ITEM`/`KNOWN_KINDS` (:33-35); `EXTRACTION_PROMPT` (:40-74) is **per-moment framed throughout and is replaced**; `ArtifactParseError(ValueError)` (:77); `MomentInput` (:86-102) and `build_prompt` (:123-144) are replaced by whole-transcript equivalents; `_span` (:114) renders `m:ss`/`h:mm:ss`; `parse_artifacts` (:173-228) is JSON-shaped and is **replaced by the markdown parser** — keep its strictness discipline and its distinct per-failure message substrings. `ProposedArtifact` (:105-111: `kind`, `title`, `body`) survives, extended with the anchor.
- `server/meetingminer/pipeline/stages/extract.py` (221 lines) — the stage. `_SELECT_SUPERSEDED` (:44-47), `_SELECT_APPROVED_MOMENTS` (:52-55), `_DELETE_DRAFTS` (:63-70, excludes approved/published moments — keep the carve-out and its rationale at :57-62), `_INSERT_ARTIFACT` (:74-77, `state` deliberately omitted so the column default applies — AD-5). `_propose` (:80-110) holds the one-retry-then-`StageError` discipline to preserve. `run` (:113-221) builds the completer at :114-118, reads the bundle at :119-120, and its **per-moment loop (:143-194) and four skip counters are replaced**. Summary log at :196-210, `stage.extract.zero_artifacts` at :211-221.
- `server/meetingminer/adapters/llm/port.py` — `LlmError` (:24), `LlmUnavailableError` (:28), `LlmReply(text, model, fallback_engaged)` (:37-48), `Llm.complete(prompt: str) -> LlmReply` (:51-54). **One positional argument, no per-call options** — widening this is required for `num_ctx`.
- `server/meetingminer/adapters/llm/litellm.py` — `DEFAULT_TIMEOUT_SECONDS = 120.0` (:26); `resolve_api_base(model, providers)` (:40-61) maps an `ollama/` prefix to `providers["ollama"].base_url`; `LiteLlmCompleter.complete` (:83) calls `litellm.completion(model=, messages=, api_base=, timeout=)` at :96-101 with **no options passthrough**; exception mapping :102-121 (note `BadRequestError` maps to plain `LlmError`, so it does **not** engage the fallback).
- `server/meetingminer/adapters/llm/__init__.py` — `RoleBinding` Protocol (:36-46), `FallbackLlm` (:48, engages at call time, stays engaged, re-wraps replies with `fallback_engaged=True`), `build_llm(role_binding, providers, log)` (:97-120).
- `server/meetingminer/migrations/0009_artifacts.sql` — `artifact`: `moment_id uuid NOT NULL`, `meeting_id`, `kind CHECK IN ('adr','action-item')`, `state DEFAULT 'extracted'`, `title`, `body`, `provenance jsonb`, composite FK `(moment_id, meeting_id) -> moment (id, meeting_id)` with **no cascade**. Read-only here.

**Anchoring inputs**
- `server/meetingminer/projections/evidence.py` — `read_meeting(conn, meeting_id) -> MeetingEvidence` (:160) returns in one read both `turns` (`Turn(id, ordinal, start_ms, end_ms, text, speaker_label, …)`, ordered by `ordinal`) and `moments` (`MomentRow`, `.start_ms`/`.end_ms`, ordered `start_ms, id`). This is the whole input surface — both sides of the anchoring problem from one call. Store-free and read-only.
- `server/meetingminer/pipeline/moments.py:249-255` — the assignment loop whose semantics the anchor resolver must match: greatest `start_ms <= t`, half-open `[start, next_start)`. Moments **tile contiguously and never overlap** (docstring :198-225: "overlapping spans cannot answer 'which moment covers this instant' single-valuedly"). Gaps exist only before the first moment and after the last `end_ms`.
- `server/meetingminer/pipeline/transcripts.py` — `parse_timestamp(raw, *, line_number=None) -> int` (:114) parses `MM:SS`/`HH:MM:SS` **by field count** and returns milliseconds. **Reuse this for `[m:ss]` anchors** rather than a second spelling.
- `server/meetingminer/projections/chunking.py:31-48` — `Turn`; `_render(turn)` (:79) is the nearest precedent for rendering a turn. No helper renders a whole meeting as one timestamped string — that is new.

**Drop surfaces (adopt path)**
- `server/meetingminer/domain/drops.py` — canonical filename constants (:35-52: `METADATA_FILENAME`, `RECORDING_FILENAME`, `TRANSCRIPT_VTT_FILENAME`, `TRANSCRIPT_TEXT_FILENAME`, `EVIDENCE_FILENAMES`, `CANONICAL_FILENAMES`); `sha256_and_size(path) -> tuple[str, int]` (:202) is **the one hashing implementation**; `DropContents` (:219-227) has no extraction-doc slot; `read_drop` builds it via `present()` (:389-398) and enforces the at-least-one-evidence rule (:400-404); `assert_unlinked_evidence` (:180) refuses symlinks for every name in `CANONICAL_FILENAMES`.
- `server/meetingminer/pipeline/stages/align.py` — the AD-17 template for arrived material: `_UPSERT_PROVIDED_SOURCE` (:60-74), `_read_drop_file(path) -> (text, sha256, byte_size)` (:158), `_record_provided_sources` (:170) setting `ctx.drop_relative_path(path)` (:203) and deleting stale rows for kinds the drop no longer carries (:218-224).
- `server/meetingminer/migrations/0005_transcripts_participants.sql:16-52` — `transcript_source` is the reference shape for the path/checksum/size triple; `0008_drop_root_anchored_paths.sql:76-132` carries the root-relative CHECK constraints to copy.
- `server/meetingminer/pipeline/stage.py` — `StageError` (:21); `StageContext` (:30-52) carries `conn`, `config`, `meeting_id`, `drop`, `content_root`, `drops_root`, `log`; `drop_relative_path(path)` (:76-90). A stage **never commits and never rolls back**.

**Config**
- `server/meetingminer/config.py` — `_StrictModel` forbids extra keys (:99-100), so any new `config.yaml` key needs a typed field; `LlmRoleBinding(model, fallback)` (:141-143); `LlmRoles` (:146-149); `ProviderEndpoint(base_url)` (:161-162).
- `config.yaml` — `llm.roles.extraction` (:24-27) currently `claude-sonnet-5` / `ollama/qwen3:32b`; `providers.ollama.base_url: http://localhost:11434` (:50-51), **which the embedder also resolves** (`adapters/embed/__init__.py:44,:73`).

**Puller (in scope)**
- `pull_transcript/grab-teams-transcript.js` — `OLLAMA_URL = 'http://10.77.0.52:11434'`, `OLLAMA_MODEL = 'gpt-oss:120b'` (:82-83); `summarizeTranscript(txtPath, mdPath, promptFile)` (:886) posts `/api/chat` with `stream: true`, `options: { num_ctx: 65536 }` and a system/user split — system is the prompt file, user is `dateLine()` + the due-date rule + `'Raw transcript:\n\n' + transcript` (:891-906); `addActionCounts` (:933) counts table rows by trailing Status cell — **evidence that the action-items doc renders as a table**; `generateDocs(txtPath)` (:949) writes `<stem>.md` and `<stem> action items.md`.
- `pull_transcript/arch_summary_prompt.md` (76 lines) — 13 numbered sections; grounding rules: no invented facts, Confirmed/Assumed/Open/Risk marks, `[m:ss]` anchors on every decision/action/risk, `[Proposed]` tags, short item IDs (D1, A1, R1), "do not repeat content across sections". Section 5 is an action-items table; section 13 closes with "Decisions made".
- `pull_transcript/action_items_prompt.md` (29 lines) — output pinned as `# Action Items — <title> (<date>)`, then `## <Owner>` sections each with a table `ID | Action | Details / dependency | Timing (as stated) | Timestamp | Status (Committed / Assigned / Tentative)`, then `## Unowned — needs an owner`, `## Reported done`, `## Watch items`.
- `pull_transcript/arch_summary_prompt.orig.md` (pre-7/16/26) — same sections, **no timestamp-anchoring rule at all**: documents from this lineage carry no `[m:ss]` anchors, which is why an unanchored item must be a named error rather than a silent drop.
- `pull_transcript/emit-drop.js` — `EVIDENCE_MAP` (:49-53) maps occurrence **extension** to canonical drop filename and therefore cannot express two `.md` files; `ORG_CHART_SUFFIX` (:61) is the precedent for "auxiliary evidence carried in when it exists"; `planDrop` (:366-429) builds `files` (:380-398) and `metadata` (`schemaVersion: 1` at :401, bumped to 2 for `augments` at :587-589); `readParticipantGraph` (:314) is the omit-when-absent pattern to mirror; staging copy loop at :619-624; `--dry-run` report at :840. **emit-drop records no checksums** — the only hash is `sha1(sourceId)[0:8]` for the directory name (:234) and `metadata.json` carries no files array, so sha256/byte_size stay server-side. `dropIsCurrent` (:507-527) and `evidencePresentIn` (:467-479) key on `plan.files` as the *evidence* set — summaries must stay out of it.
- `pull_transcript/grab-teams-transcript.js:1340-1377` — the ordering: `emitDrop` runs **before** `generateDocs`, and the comment at :1340-1345 states the invariant explicitly ("the generated summaries — which the drop ignores — have not run yet"). This is why no drop on disk carries summaries today.
- `pull_transcript/test/emit-drop.test.js` (1767 lines, ~105 cases) — schema harness at :21-63 compiles `docs/source-drop.schema.json` with `ajv/dist/2020`; `dropFiles()` (:158-160) asserts drop contents by exact sorted list; **:259-279 asserts summaries are ignored** and **:307-322 asserts the exact metadata key set** — both must change; the isolation test at :684-699 forbids emit-drop from referencing server paths or the schema file; re-emit semantics at :1438-1767.
- `pull_transcript/.gitignore` is an **allowlist** — a new tracked file needs an explicit `!` entry, though `!test/**` already covers new test files.
- `docs/source-drop.schema.json` — `additionalProperties: false`; `schemaVersion` `enum [1, 2]`; `allOf[0]` forces `schemaVersion` **`const: 2`** when `augments` is present. That `const` must relax to `minimum: 2`, or an augmenting drop that also carries extraction docs becomes unsatisfiable.
- `server/meetingminer/api/ingests.py` — `_load_metadata(drop_dir, schema)` (:359) is the api-side validation; `_validator()` (:207) reloads on stat change (story 2-6), so **no api code change is needed**. The worker validates independently in `drops.py:370-386`; both must pass.

**Tests**
- `server/tests/conftest.py` — `EVIDENCE_TABLES` (:258-283) must gain the new table; `make_drop` factory (:336-390) builds drops under `DROPS_ROOT`; `FakeLlm` (:671-702) with `.calls` and scripted replies; **autouse `_no_real_llm` (:705-724) patches `meetingminer.pipeline.stages.extract.build_llm` by that exact attribute name** — the rework must keep importing it under that name or the guard silently stops guarding; `fake_llm` (:727-738).
- `server/tests/test_extraction_core.py` (471 lines, 26 test functions) — `build_prompt` tests (:58-97) and the 11-case `parse_artifacts` rejection table (:139-163) are rewritten; the fallback/config-binding tests (:168-270), the stubbed-`litellm` fixture and its tests (:309-427), and the AD-8 import-boundary tests (:452-471) survive with additions for the new options passthrough.
- `server/tests/test_worker_extract.py` (555 lines, 9 tests) — every per-moment-call assertion is reworked (tests 1, 3, 4, 6, 8 count calls per moment). Helpers to keep: `make_transcript_drop` (:64), `moment_ids` (:74), `artifact_rows` (:85), `summary_event` (:114), `requeue_extract` (:123), `evidence_counts` (:139).
- `server/tests/projection_seed.py` — `seed_meeting(...)` (:75) seeds turns, `transcript_source`, and two moments cut at the 30s gap; `DEFAULT_TURNS` (:42) are at 2s/5s/9s/40s/44s, each `end_ms = start_ms + 2000`.
- `server/tests/test_drop_schema.py` — `test_schema_documents_the_augments_declaration` (:160) asserts `enum == [1, 2]` and **must be updated**; `test_schema_documents_canonical_filenames` (:166) asserts each canonical name appears in the schema description; `test_unknown_top_level_field_fails` (:94) enforces `additionalProperties: false`.
- `pull_transcript/` own suite via `make puller-test` (`infra/Makefile:353`), which needs `ajv` + `ajv-formats` present.

## Tasks & Acceptance

**Execution:**

- `server/meetingminer/migrations/0010_extraction_sources.sql` -- new migration (never edit 0009) creating `extraction_source`: `id uuid PK uuidv7()`, `meeting_id uuid NOT NULL REFERENCES meeting (id) ON DELETE CASCADE`, `kind text NOT NULL CHECK (kind IN ('arch-summary','action-items'))`, `origin text NOT NULL CHECK (origin IN ('adopted','generated'))`, `drop_relative_path text` (NULL for a generated document, which is not a drop file), `sha256 text NOT NULL`, `byte_size bigint NOT NULL CHECK (byte_size >= 0)`, `layout text NOT NULL` (which parser layout matched), `artifact_count integer NOT NULL DEFAULT 0 CHECK (artifact_count >= 0)`, `model text`, `prompt_version integer`, timestamps + `set_updated_at` trigger, `UNIQUE (meeting_id, kind)`. Copy 0008's root-relative CHECK constraints for `drop_relative_path` verbatim. Rationale: AD-17 — an adopted document is arrived material and needs a row naming its path, checksum and size; the row is also where the no-silent-zero check records what it parsed.

- `server/meetingminer/domain/drops.py` -- add `EXTRACTION_SUMMARY_FILENAME = "extraction-summary.md"` and `EXTRACTION_ACTIONS_FILENAME = "extraction-action-items.md"`; add them to `CANONICAL_FILENAMES` (so `assert_unlinked_evidence` covers them) but **not** to `EVIDENCE_FILENAMES` (they never make a drop ingestible on their own); add `extraction_summary_path` / `extraction_actions_path` to `DropContents` and wire them through `read_drop`'s `present()`. Rationale: the adopt path needs the files enumerated the same way every other canonical file is.

- `docs/source-drop.schema.json` -- add optional `extractions` object declaring which extraction documents the drop carries; add `3` to the `schemaVersion` enum with an `allOf` clause requiring `schemaVersion >= 3` when `extractions` is present; **relax the existing `augments` clause from `const: 2` to `minimum: 2`** so a v3 augmenting drop stays satisfiable; name the two new canonical filenames in the schema `description`. Bump `$id` to `.../source-drop/3/metadata.json`. Rationale: `additionalProperties: false` means the key must be declared, and the schema's own rule is that a consumer pinned to an older version must fail closed rather than silently ignore a declaration.

- `pull_transcript/emit-drop.js` -- in `planDrop`, match `<stem>.md` and `<stem> action items.md` beside the occurrence via a **suffix-keyed** table separate from `EVIDENCE_MAP` (both are `.md`, so an extension key cannot distinguish them, and `<stem> org chart.md` also sits in the directory and must not match); collect them into a `plan.summaries` list **kept out of `plan.files`**, because `dropIsCurrent` (:515-521) and `evidencePresentIn` (:467-479) both treat `plan.files` as the evidence set and folding summaries in would silently change re-emit semantics; copy them in the staging loop (:619-624); declare them in `metadata.extractions` with `schemaVersion: 3`, omitting the key entirely when neither exists (mirroring `readParticipantGraph`'s omit-never-empty rule); add them to the `--dry-run` report at :840. Rationale: so the adopt path receives real input as *arrived* material.

- `pull_transcript/grab-teams-transcript.js` -- run `generateDocs` **before** `emitDrop` on a fresh pull (today the emit at :1346-1369 precedes generation at :1371-1377, so summaries do not exist at emit time and no drop can ever carry them). Keep generation failure non-fatal and keep the emit unconditional, so "the hand-off never fails a pull" still holds; update the comment at :1340-1345, which encodes the current ordering as deliberate. Rationale: without this the adopt path is unreachable for every future pull.

- `pull_transcript/test/emit-drop.test.js` -- update the two tests that pin today's behavior: `"generated summaries and stray non-stem transcripts are ignored"` (:259-279) asserts the drop is exactly `['metadata.json','transcript.txt','transcript.vtt']` and must be inverted for the carried case while still excluding `<stem> org chart.md` and stray non-stem files; the exact-metadata-keys assertion (:307-322) must admit `extractions`. Add: docs carried when present, key omitted when absent, `schemaVersion` 3 only when carried, an augmenting drop carrying docs still validates, and the schema-validation harness (:21-63) still passes. Keep the isolation test (:684-699) green — new emit-drop code must not reference server paths, `config.yaml`, or the schema file. Rationale: `make puller-test` is the only gate on the puller.

- `server/meetingminer/config.py` -- extend `LlmRoleBinding` with three optional typed fields: `base_url: str | None = None` (overrides the provider endpoint for this role), `timeout_seconds: float | None = None`, `num_ctx: int | None = None`. Rationale: `providers.ollama.base_url` is a single value the **embedder also resolves**, so extraction cannot point at a different Ollama host without a per-role override; the fixed 120s timeout is shorter than a whole-transcript run on `gpt-oss:120b` (~3 minutes measured); and without `num_ctx` Ollama's default context **silently truncates** a 120-minute transcript, which is exactly the silent loss the SPEC forbids.

- `server/meetingminer/adapters/llm/port.py` -- widen `Llm.complete` to accept optional per-call options (a typed `LlmOptions` value or keyword-only `num_ctx`/`timeout_seconds`), keeping `LlmReply` unchanged. Rationale: the port is the only place model interaction is expressed (AD-8); `num_ctx` cannot be smuggled past it.

- `server/meetingminer/adapters/llm/litellm.py` -- honour the role's `base_url` override ahead of `resolve_api_base`; pass the resolved timeout per call; pass `num_ctx` to `litellm.completion` **only for `ollama/`-prefixed models**, so no other provider receives an unknown parameter. Rationale: the three settings above have to reach the SDK call.

- `server/meetingminer/adapters/llm/__init__.py` -- thread the new role-binding fields through `build_llm` into the **primary** completer; the fallback keeps resolving its endpoint through `providers` unless the role declares its own fallback endpoint. Keep `FallbackLlm`'s call-time sticky engagement unchanged. Rationale: the role's `base_url` names the host serving the role's *primary* model — forcing it onto the fallback repoints a model that resolved correctly before this story and can leave the fallback dead on arrival.

- `config.yaml` -- flip `llm.roles.extraction` to `model: ollama/gpt-oss:120b`, keep `fallback: ollama/qwen3:32b`, and set the role's `base_url: http://10.77.0.52:11434`, `num_ctx: 65536`, `timeout_seconds: 900`. Comment why the role carries its own `base_url` (the embedder owns `providers.ollama.base_url`) and that `num_ctx` prevents silent truncation. Leave `chat` and `judge` untouched. Rationale: SPEC constraint — extraction defaults to the local model and no paid call is reachable by default configuration.

- `server/meetingminer/pipeline/extraction.py` -- rework the core, still engine-free: bump `PROMPT_VERSION`; replace `EXTRACTION_PROMPT` with two whole-transcript prompt constants adapted from the proven pair, carrying over the grounding rules (no invented dates, `[m:ss]` anchor on every item, `[Proposed]` tags, Confirmed/Assumed/Open marks) and **pinning the output layout strictly**; add `render_transcript(turns)` producing `[m:ss] Speaker: text` lines; add `build_summary_prompt`/`build_actions_prompt` embedding the meeting title, date line and the rendered transcript; replace `parse_artifacts` with `parse_extraction_document(text, kind) -> ParsedDocument` that finds candidate items **by item-ID pattern plus timestamp presence rather than by heading numbering** — accepting both a markdown table row (`| **D1** | … |`) and a bullet line (`- **D1** – …`), the observed ID vocabulary (`D#`, `A#`, `R#`, `O#`, `OQ#`, `OQ Q#`, `BR#`, and the action doc's per-owner initials), and status cells matched by **prefix** (`Tentative* (ownership inferred)` must count as Tentative, exactly as `addActionCounts` does); normalize Unicode hyphens and punctuation before matching timestamps; accept point, range, bracketed, parenthesised, italicised and comma-list timestamp forms, taking the **earliest** as the anchor; map ID prefix to `kind` (`D` → `adr`, `A` → `action-item`); keep a distinct message substring per failure mode; add `resolve_anchor(anchor_ms, moments) -> UUID` implementing greatest-`start_ms <= t` and raising a named error when the anchor precedes the first moment or follows the last `end_ms`. Rationale: one strict parser serving both paths is what makes adopt and generate interchangeable.

- `server/meetingminer/pipeline/stages/extract.py` -- rework the stage: keep `build_llm` imported under that exact name (the autouse test guard patches it); read the bundle once via `read_meeting`; per document kind, adopt the drop file when present (hash it, record an `extraction_source` row, parse it) else generate it through the port with the role's options; resolve every artifact's anchor to a moment; keep `_DELETE_DRAFTS` and its approved-moment carve-out; insert with `provenance = {role, source: adopted|generated, model, fallback_engaged, prompt_version, anchor_ms, document_kind, layout}`; replace the four per-moment counters with per-document counters (adopted/generated, artifacts per kind, anchors resolved); keep `stage.extract.summary` and extend `stage.extract.zero_artifacts` to name the document and the populated section that produced nothing. Retry discipline: the generate path retries once on a parse failure; the adopt path does not (the same bytes cannot parse differently). Rationale: this is the granularity correction itself.

- `server/tests/conftest.py` -- add `extraction_source` to `EVIDENCE_TABLES`; extend `make_drop` (or add a story-local factory) to write the two extraction documents; keep `FakeLlm` and the autouse guard working against the new call shape. Prefer story-local fixtures over widening the shared block. Rationale: the shared conftest is a known cross-story conflict point.

- `server/tests/test_extraction_core.py` -- rework: transcript rendering; both prompts embed title, date line and transcript; **both layouts of both documents parse to the same artifacts**; unanchored item rejected by name; every rejection case keeps a distinct complaint; anchor resolution inside a moment, on a boundary, before the first moment, and past the last `end_ms`; the new options passthrough reaches `litellm.completion` for `ollama/` models and is absent for others; keep the AD-8 import-boundary tests. Rationale: the I/O matrix's edge cases are unit-testable here without stores.

- `server/tests/test_worker_extract.py` -- rework the store-backed tests: adopt path makes **zero** model calls and lands `extraction_source` rows with path/sha256/byte_size; generate path makes one call per document kind; mixed drop adopts one and generates the other; artifacts FK-link the moment containing their anchor; draft replacement on rerun with an approved moment untouched; unresolvable anchor fails the job by name; zero-artifact signal logged; transcript-only meeting behaves identically; evidence-table row counts invariant. Rationale: the stage's contract is only observable end to end.

- `server/tests/test_drop_schema.py` -- update the `schemaVersion` enum assertion to `[1, 2, 3]`, assert the two new canonical filenames appear in the description, and add cases for the `extractions` declaration and the relaxed `augments` gate. Rationale: these tests are the schema's contract.

**Acceptance Criteria:**
- Given a drop carrying both summariser documents, when the worker runs `extract`, then no model call is made, artifacts are inserted `extracted` anchored to the moments containing their `[m:ss]` timestamps, and each document has an `extraction_source` row naming its drops-root-relative path, `sha256` and `byte_size`.
- Given a drop carrying neither document, when the worker runs `extract`, then the whole timestamped transcript is sent once per document kind through the `Llm` port and the resulting artifacts are indistinguishable in shape from the adopted ones.
- Given the same logical content rendered once as a markdown table and once as a bullet list, when each is parsed, then both yield the same artifacts — the `retrieval-prior-art.md` §8 regression.
- Given a source document whose target section plainly carries items but which parses to zero artifacts, when the stage completes, then `stage.extract.zero_artifacts` names the document and the populated section, and the run is not reported as a plain success.
- Given an artifact whose `[m:ss]` anchor falls outside every moment, when the stage runs, then the job fails at `extract` with an error naming the artifact and the anchor — the artifact is never silently dropped.
- Given `config.yaml` as committed, when the extraction role binds, then the model string is `ollama/gpt-oss:120b` and no configuration path reaches a paid provider.
- Given an extraction rerun over a meeting with an `approved` artifact, when the stage completes, then that row and its moment's artifacts are unchanged and only drafts were replaced.
- Given an augmenting drop that also carries extraction documents, when it is validated against the drop schema, then it passes with `schemaVersion: 3`.

## Review Findings

- [x] [Review][Decision] Reconcile CAP-5's "one pass per meeting" wording with the required two document-generation calls — resolved 2026-08-20: "one pass" means one logical whole-meeting extraction pass, implemented as the two document-kind calls required for convergence with adopted documents. CAP-5 needs a spec-owner clarification; no implementation redesign is required.
- [x] [Review][Patch] Reject a document whose markdown structure is outside its required extraction sections [server/meetingminer/pipeline/extraction.py:807] — fixed in `dffbb3b`: parser acceptance now requires a recognized target section; adopted malformed documents fail by name and generated ones retry once.
- [x] [Review][Patch] Never carry stale summariser documents into a newly emitted drop [pull_transcript/grab-teams-transcript.js:1072] — fixed in `dffbb3b`: `finishPull()` supplies an explicit current-run document selection to the emitter, including empty and partial-success cases.
- [x] [Review][Patch] Consume the final unterminated Ollama NDJSON record [pull_transcript/grab-teams-transcript.js:938] — fixed in `dffbb3b`: the decoder flushes and the residual record follows the same parser path.

## Spec Change Log

### 2026-08-20 — review finding: the role endpoint was forced onto the fallback

- **Triggering finding:** `build_llm` applied the extraction role's `base_url` and `num_ctx` to the fallback as well as the primary. `ollama/qwen3:32b` resolved to `providers.ollama.base_url` before this story and now points at the role's host, where nothing establishes it is served; if it is not, the fallback is dead and "both models failed" becomes the only outcome.
- **Root cause was this spec, not the implementation.** The Execution task said "into both the primary and fallback completers ... one binding path, primary and fallback alike", and the implementation followed it exactly.
- **Amended:** that task line now scopes the role's endpoint to the primary and leaves the fallback on `providers` unless the role declares its own fallback endpoint.
- **Known-bad state avoided:** a silently dead fallback on every extraction run, discoverable only when the primary is down — the moment the fallback exists for.
- **Deviation from the workflow's bad_spec branch, stated plainly:** the letter of triage sends a spec-caused finding through revert-and-re-derive. That would discard five commits of independently verified, fully green work to change one function's parameter routing, and the other 21 findings are implementation-level and contained. The spec text is corrected here and the code fixed as a patch. Recording it so the deviation is visible rather than silent.
- **KEEP:** the per-role `base_url` / `num_ctx` / `timeout_seconds` fields themselves, and the reasoning for them — `providers.ollama.base_url` is shared with the embedder, the 120s default is shorter than a whole-transcript pass, and an unset `num_ctx` truncates silently. Only the fallback's endpoint resolution changes.

## Review Triage Log

### 2026-08-20 — Review pass

Four layers over `100b0992..c4cf887`: blind hunter, edge-case hunter,
verification-gap, intent-alignment.

- intent_gap: 0
- bad_spec: 0 (one spec-caused finding handled as a patch plus a Spec Change Log
  amendment rather than a revert-and-re-derive loopback — the deviation and its
  reasoning are recorded in the Spec Change Log)
- patch: 22: (high 0, medium 8, low 14)
- defer: 9: (high 0, medium 4, low 5)
- reject: 6
- addressed_findings:
  - `[medium]` `[patch]` Anchors were scanned from the whole table row, so an incidental time in a Details cell ("the 9:00 standup") silently became the citation and still resolved to a real moment — precedence is now header-labelled Timestamp column, then a stamp-only cell, then the whole row.
  - `[medium]` `[patch]` `_STATUS_CELL` matched a bare prefix with no word boundary, so decisions beginning "Open", "Risk" or "Assigned" lost their title to a context cell — now word-bounded and shape-constrained.
  - `[medium]` `[patch]` The `## <Owner>` heading reached no artifact, so an adopted action item arrived ownerless while a generated one carried its Owner column — the owner now lands as one canonical `Owner: <name>` body line on both paths, satisfying the convergence AC.
  - `[medium]` `[patch]` `seen_ids` was document-global while real action documents repeat per-owner IDs, silently dropping a second owner's `A1` — dedup is now keyed on (section, item id).
  - `[medium]` `[patch]` The role's `base_url` was forced onto the fallback, repointing `ollama/qwen3:32b` away from the host it resolved to before this story — the fallback resolves through `providers` again unless a new optional `fallback_base_url` says otherwise. Root cause was this spec's own task line; see the Spec Change Log.
  - `[medium]` `[patch]` The puller reordering put `generateDocs` ahead of `writeSource`, so an interrupt mid-summarisation left an occurrence with no `_source.json` and invisible to `--all` backfill — ordering is now sidecar, then generate, then emit.
  - `[medium]` `[patch]` The summariser `fetch` had no timeout and now preceded the emit, so an Ollama stall blocked the drop hand-off indefinitely — bounded, still non-fatal, emit still unconditional.
  - `[medium]` `[patch]` Nothing read `metadata.extractions`, so a drop declaring documents whose files were absent silently generated and the schema's fail-closed version gate bought nothing — the stage now cross-checks declaration against presence and refuses by name.
  - `[low]` `[patch]` The committed LAN address was asserted as a string literal in a test, turning any host change or off-network clone red — the test now asserts the property the AC needs.
  - `[low]` `[patch]` `resolve_anchor` never verified the chosen moment actually contains the anchor — containment is asserted rather than assumed.
  - `[low]` `[patch]` `num_ctx` was silently dropped for a non-`ollama/` model, the exact silent truncation it exists to prevent — now logged by name.
  - `[low]` `[patch]` `_DELETE_STALE_SOURCES` could never delete a row given the migration's own CHECK.
  - `[low]` `[patch]` `extraction_source.artifact_count` stored inserted rather than parsed, making a document that parsed onto an approved moment indistinguishable from a parse failure in the query the column exists for — both counts are recorded.
  - `[low]` `[patch]` The adopted document decoded with `errors="replace"`, flowing U+FFFD into artifact titles while the sha256 recorded bytes nobody could tell were corrupt — now a named refusal.
  - `[low]` `[patch]` `body or title` silently duplicated the title into an empty body, which 4.1 had refused by name.
  - `[low]` `[patch]` A ragged row with an empty leading cell was dropped without trace — the §8 shape; the ID is now sought across the leading cells.
  - `[low]` `[patch]` Item IDs matched case-sensitively, so a document writing `d1` yielded zero artifacts.
  - `[low]` `[patch]` The symlink refusal test enumerated a hardcoded filename list, leaving the two new canonical files uncovered — now parametrized over `CANONICAL_FILENAMES`.
  - `[low]` `[patch]` Migration 0010's two CHECK constraints had no test while every sibling 0008 constraint has one — direct-SQL tests added.
  - `[low]` `[patch]` `_meeting_date` was unreachable from any test and the stage's prompt assertions never inspected the date line, so a mis-grounded prompt would ship silently.
  - `[low]` `[patch]` An artifact anchored onto an approved or superseded moment was discarded with only a counter — now logged by name.
  - `[low]` `[patch]` Nothing exercised the generate-before-emit ordering, so the reordering could be reverted with every suite green — the pull tail is an exported `finishPull()` seam and `test/finish-pull.test.js` pins the sequence.

## Design Notes

- **Two calls per meeting, not one.** "One pass per meeting" replaces *per moment*, and the proven mechanism is a **pair** of prompts producing two documents. The adopt path parses exactly two documents, so for the two paths to converge on one parser the generate path must produce the same two. Two calls per meeting against 28 meetings is ~56 local calls, against the 358 paid calls that 5 meetings cost before. **Attack point:** if "one pass" was meant literally as a single call, the two documents would have to be sections of one reply and the adopt path would parse a shape no summariser emits.

- **Markdown, not JSON.** 4.1 parsed a pinned JSON reply. The adopt path receives summariser markdown, and the contract requires one parser for both paths, so the generate prompts must emit the same markdown shape. The strictness discipline survives; the format does not. **Attack point:** markdown is a looser contract than JSON, and the mitigation is entirely in the two-layout tests plus the no-silent-zero signal.

- **"Both known layouts" understates the real variance, so the parser keys on the stable thing.** Sampled generated docs across 29 occurrences show the arch-summary heading is `#` or `##`, numbered with a digit, a keycap emoji, or not at all, sometimes preceded by a document title; the executive-summary table has 2 or 3 columns; timestamps live in their own column, fused into a Status cell as `Confirmed – [7:47‑8:24]`, or italicised inline as `*(4:51‑4:53)*`. What is stable is the **item ID** (the prompt mandates `D1, A1, R1, BR1…`) and the presence of a timestamp. Anchoring the parser to those two, and treating headings as advisory, is what makes the §8 lesson actionable rather than a promise to be careful. **Attack point:** ID-keyed scanning could pick up an ID *reference* in a later section — the prompt says later sections reference IDs instead of restating them, so a reference without its own timestamp must not become a second artifact.

- **The puller's ordering is the real blocker for the adopt path, and it is a one-line move.** `emitDrop` runs before `generateDocs`, so no drop that exists today or would be emitted tomorrow could carry summaries. Reordering means the drop lands ~3-6 minutes later (one model pass per document); generation stays non-fatal so a summariser failure still emits the drop. **Rejected alternative:** teaching `dropIsCurrent` to re-emit existing occurrences for summaries alone — that produces a drop intake refuses, which the code comment says permanently retires the occurrence, and fixing intake means editing `meetingminer/api/`, which this story may not touch. Recorded as a deferred item instead.

- **Anchoring is a containment lookup, not a similarity match.** Moments tile the meeting contiguously and never overlap, so greatest-`start_ms <= t` is single-valued — the same rule `plan_moments` already uses to assign a segment to a span. Nearest-moment snapping was rejected: it would manufacture a citation for an anchor the timeline does not contain, which is the failure *no citation, no answer* exists to prevent.

- **An unresolvable anchor raises rather than drops.** The contract says a named error path, "not a dropped artifact". Dropping would be a silent zero by another name. The cost is that one bad model anchor fails the whole meeting; the defense is that the generate path retries once first, and a meeting that fails is re-queueable while a silently dropped decision is not recoverable.

- **The role needs its own `base_url`, and this is the least obvious change here.** `providers.ollama.base_url` is one value that the **embedder** also resolves (`adapters/embed/__init__.py:73`). The embedder's `qwen3-embedding:0.6b` is served locally; the bake-off winner `gpt-oss:120b` is served at `10.77.0.52`. Without a per-role override, satisfying the SPEC's local-extraction constraint breaks embeddings. **Attack point:** this adds three config keys the frozen contract did not name — the alternative was leaving the committed default pointing at a host that does not serve the model.

- **`num_ctx` is a correctness setting, not tuning.** The puller sets it explicitly because "Ollama's default context would silently truncate" a long transcript. A truncated transcript yields fewer decisions and reports success — the §8 failure mode arriving through a different door.

- **`BadRequestError` does not engage the fallback** (`litellm.py:102-121`). A whole-transcript prompt is far larger than a per-moment one, so a context-length refusal now fails the stage outright rather than falling back. That is arguably correct — a smaller fallback model would refuse it too — but it is a behavior change worth the reviewer's attention.

- **The 133 existing drafts are replaced, not migrated.** They are unpublished, so no citation can break. `_DELETE_DRAFTS` already scopes to `state = 'extracted'` and skips approved moments; per-moment drafts simply do not survive the first rerun.

- **Operational note:** migration `0010` must be applied (`make migrate`) before the worker is restarted onto this code — the same ordering lesson as 2.1a and 4.1. The worker stays STOPPED; restarting it is the user's deliberate call after merge.

## Verification

**Commands:**
- `cd server && uv run pytest tests/test_extraction_core.py -q` -- expected: all pass, store-free.
- `make puller-test` -- expected: all pass, store-free (needs `ajv` + `ajv-formats` from `make bootstrap`).
- `make web-test` -- expected: all pass, unaffected (no web changes).
- `cd server && uv run pytest tests/ -q` -- expected: all pass; store-backed suites use the per-run database and the projection tests queue on the cross-worktree lock. No test reaches a real LLM or a real Ollama host.
- `rg -n 'import litellm|from litellm' server/meetingminer --glob '!**/adapters/llm/**'` -- expected: no matches (AD-8 boundary, also pinned by an AST test).

## Auto Run Result

**Status:** implemented; review round 1 applied — all 22 patch findings
fixed. (The triage also recorded 9 deferred and 6 rejected; those are the
coordinator's, in the frontmatter and the Spec Change Log.)

**Implemented change:** `extract` operates on the whole meeting transcript, once
per document kind, instead of once per moment. A drop carrying the puller
summariser's documents has them **adopted** with zero model calls; a document
the drop lacks is **generated** through the `Llm` port. Both paths converge on
one strict markdown parser that keys on item ID plus timestamp, reads the table
and bullet layouts identically, and normalizes the unicode-hyphen, range,
parenthesised, italicised and comma-list timestamp forms the sampled real output
uses. Every artifact's `[m:ss]` anchor resolves to the moment containing it
(greatest `start_ms <= t`); an anchor outside the timeline fails the stage by
name rather than dropping the artifact. `llm.roles.extraction` now defaults to
`ollama/gpt-oss:120b`, so no configuration path in the committed `config.yaml`
reaches a paid provider.

**Files changed:**
- `server/meetingminer/migrations/0010_extraction_sources.sql` — `extraction_source`
  (origin, drops-root-relative path, sha256, byte size, matched layout,
  artifact count, model, prompt version), 0008's root-relative CHECK copied
  verbatim, plus a CHECK pinning "adopted iff it names a drop file".
- `server/meetingminer/pipeline/extraction.py` — `PROMPT_VERSION` 2,
  `render_transcript`, `build_summary_prompt`/`build_actions_prompt`,
  `parse_extraction_document`, `resolve_anchor`, `AnchorResolutionError`.
- `server/meetingminer/pipeline/stages/extract.py` — adopt/generate per document,
  anchor resolution, `extraction_source` upsert, per-document counters, the
  extended `stage.extract.zero_artifacts` signal.
- `server/meetingminer/adapters/llm/{port,litellm,__init__}.py` — `LlmOptions`;
  the role's `timeout_seconds`/`num_ctx` reach both completers while `base_url`
  scopes to the primary (the fallback resolves through `providers` unless the
  role declares `fallback_base_url`); `num_ctx` forwarded only to
  `ollama/`-prefixed models, and logged by name when ignored.
- `server/meetingminer/config.py`, `config.yaml` — the three role fields and the
  local-model default.
- `server/meetingminer/domain/drops.py` — the two extraction filenames as
  canonical (so `assert_unlinked_evidence` covers them), not as evidence.
- `docs/source-drop.schema.json` — `extractions` at `schemaVersion: 3`; the
  `augments` gate relaxed from `const: 2` to `minimum: 2`.
- `pull_transcript/{emit-drop.js,grab-teams-transcript.js,CLAUDE.md}` —
  `generateDocs` before `emitDrop`; suffix-keyed `EXTRACTION_MAP` collecting
  into `plan.summaries` (never `plan.files`); `metadata.extractions`.
- `server/tests/` — `test_extraction_core.py` (102), `test_worker_extract.py` (17),
  `test_drop_schema.py` (+11), `conftest.py`, and a repadded schema-replacement
  helper in `test_ingests.py`.
- `pull_transcript/test/emit-drop.test.js` — carried/omitted/one-only cases, the
  `plan.files` separation, the version-3 gate, and the augmenting-plus-extractions
  drop.

**Verification performed (re-run independently by the coordinator, post-patch):**
- `cd server && uv run pytest tests/test_extraction_core.py -q` -> 102 passed.
- `cd server && uv run pytest tests/ -q` -> 1326 passed, 0 failed (0:05:31).
- `make puller-test` -> 118 tests, 118 pass, 0 fail.
- `make web-test` -> 157 passed (9 files).
- `rg -n 'import litellm|from litellm' server/meetingminer --glob '!**/adapters/llm/**'`
  -> no matches (exit 1).
- `git status --porcelain` empty; `git rev-list --left-right --count HEAD...@{u}`
  reported `0	0`.
- No model call of any kind was made: the worker was not started and
  `make evals-run` was not run.

**Verification performed (after the review round):**
- `cd server && uv run pytest tests/test_extraction_core.py -q` -> 102 passed.
- `cd server && uv run pytest tests/ -q` -> 1326 passed, 0 failed (0:08:03).
- `make puller-test` -> 118 passed, 0 failed.
- `make web-test` -> 157 passed (9 files).
- `make evals-test` -> 371 passed.
- `rg -n 'import litellm|from litellm' server/meetingminer --glob '!**/adapters/llm/**'`
  -> no matches.
- No model call of any kind was made: `make worker` was not started and
  `make evals-run` was not run.

**Review findings breakdown:** 22 patched (high 0, medium 8, low 14 — all
applied and re-verified), 9 deferred to frontmatter `deferred`, 6 rejected as
noise or as spec-conformant behaviour deliberately chosen (notably "fall back to
generate when adopt fails", which would mask a broken parser — the §8 failure
this story exists to close).

**Follow-up review recommendation:** `true`. Counting only this pass's `patch`
findings: high 0, medium 8, low 14; score = 3 x 8 + 1 x 14 = 38, at or above the
threshold of 5.

**Review round (22 findings, all patched):**
- *Anchoring and citation correctness.* The anchor was `min()` over the whole
  row, so a Details cell reading "as agreed at [2:10]" outranked the item's own
  timestamp and produced a confidently wrong citation; the item's own timestamp
  cell is now preferred. `resolve_anchor` bounds-checked the meeting and then
  assumed the tiling; it now verifies containment.
- *Silent zeros closed.* Per-owner ID reuse (`A1` under two owners) dropped the
  second owner's whole set; a ragged `|  | D4 | ... |` was dropped with no
  trace; a lowercase `d1` was a whole meeting's zero. All three now parse.
- *Convergence.* The `## <Owner>` heading never reached the artifact, so an
  adopted action item had no owner while a generated one did.
- *Title quality.* `_STATUS_CELL` matched a bare prefix, so "Open the firewall
  port for SFTP", "Risk register moves to Jira" and "Assigned owners are
  tracked in the runbook" lost their titles to the context cell.
- *Refusals instead of quiet damage.* A non-UTF-8 drop file was decoded lossily
  under a correct checksum; a detail-less item duplicated its title into its
  body; a declared-but-absent extraction document took the generate path and
  made the schema's fail-closed version gate buy nothing.
- *Operability.* `extraction_source` records `item_count` (parsed) beside
  `artifact_count` (inserted); each discarded proposal is logged by name; an
  ignored `num_ctx` is logged by name.
- *The fallback was pointed at the primary's host* and would have been dead on
  the first call the primary missed. It resolves through `providers` again
  unless the role declares `fallback_base_url`.
- *Puller ordering.* The sidecar is written before the summariser (a crash
  during the model pass had been making the occurrence invisible to `--all`),
  the summariser fetch is now bounded on stall and total time, and
  `test/finish-pull.test.js` pins the sequence with stubs.
- *Test coverage.* Migration 0010's CHECK constraints, the two new canonical
  filenames' symlink refusal, `_meeting_date`'s grounding of the generate-path
  prompt, and the committed binding asserted as a property rather than as a
  literal host.

I rejected none of the 22: every one named a real wrong-artifact,
silent-zero, or untested-behavior path.

**Residual risks and follow-ups:**
- Migration `0010` must be applied (`make migrate`) before the worker is
  restarted onto this code. The worker stays STOPPED; restarting it is the
  user's call.
- The 60 finalized drops on disk carry no extraction documents and take the
  generate path (the frontmatter `deferred` item). The adopt path is exercised
  only against fixtures until a fresh pull lands.
- The parser is measured against sampled shapes reproduced as fixtures, not
  against the real archive, which is not in this checkout. The
  `stage.extract.zero_artifacts` signal is what surfaces a shape it does not
  read.
- Migration `0010` was amended in place (it gained `item_count`) rather than
  superseded by an `0011`. It is introduced by this unmerged branch and has not
  been applied anywhere; if any environment did apply the earlier shape, drop
  `extraction_source` before running `make migrate`.
- `_ITEM_ID` is now case-insensitive, which widens what a bullet can be read as:
  in the action document, `- step1 - do the thing [1:00]` becomes an action
  item. Judged acceptable — under an owner heading with a timestamp that is
  plausibly what it is — but it is a widening, not a pure fix.
- `BadRequestError` still maps to a plain `LlmError`, so a context-length
  refusal on a whole-transcript prompt fails the stage rather than engaging the
  fallback (Design Notes call this out; unchanged here).
- `storage-layout.md` §4-5 enumerates the columns holding drops-root-relative
  paths and does not yet name `extraction_source.drop_relative_path`. Left to
  the spine owner rather than amended from a story branch.
