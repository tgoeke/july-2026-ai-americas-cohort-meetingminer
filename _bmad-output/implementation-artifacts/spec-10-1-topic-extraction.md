---
title: 'Story 10.1: Topic Extraction'
type: 'feature'
created: '2026-08-30'
baseline_revision: '5cdfce72813d68c2d81f5e02f715b8863f8492af'
status: 'review'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-10-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/build-prompt-story-10-1-2026-08-30.md'
  - '{project-root}/_bmad-output/implementation-artifacts/wave-2026-08-30-rules.md'
warnings: [oversized]
deferred: []
---

<intent-contract>

## Intent

**Problem:** The graph has no topic data — "what did we discuss about X" is a text `CONTAINS` over moment text. Threads (10.2) need per-meeting topics anchored to moments, and none exist (FR41).

**Approach:** Add a third whole-transcript extraction document — topics — through the same `Llm(extraction)` port and strict parser as the summary and action items: one row per topic with name, one-line gist, and `[m:ss]` anchors, each anchor resolved to its containing moment. Store in new worker-owned `topic` / `topic_mention` tables (migration 0014); rerun replaces. The prompt lives in `config.yaml` beside the other two and is served by `GET /extraction/prompts` as `kind="topic"`.

## Boundaries & Constraints

**Always:**
- The topics document is always *generated* — no drop declaration, no adoption path, no `domain/drops.py` change.
- Every anchor resolves through `resolve_anchor`; an anchor outside the timeline fails the stage by name (`StageError` wrapping `AnchorResolutionError` naming the topic item id). No snapping, no dropping.
- Zero topics on a meeting that has transcript text and moments is logged as a named signal (`stage.extract.zero_topics`), keyed on *meeting content*, not on parser section names — an empty topics table from the model is a signal, never quiet success.
- Topics are not artifacts: never in `extracted → approved → published`, no `artifact` row, no approved-moment skip (mentions attach regardless of artifact state). Superseded moments: mention skipped with a named discard log; a topic left with zero mentions is skipped with a named log.
- Rerun replaces: `DELETE FROM topic WHERE meeting_id = %s` (mentions cascade) before the pass, including on the no-transcript/no-moments early exit.
- `extraction_source` gains a `kind='topics'` row per run (0014 widens the CHECK — 0010's comment says widening is a story; this is it). `PROMPT_VERSION` stays 2 (it tracks code constants; `prompt_hash` identifies the config template).
- Prompt wording covers meetings and recorded sessions alike (story 6.7's generalisation; never "Microsoft Teams").
- Footprint per build-prompt table. New tests only in the three named new files.

**Block If:** none — no decision here needs a human.

**Never:**
- No projection to Neo4j/Meilisearch (10.2 does that). No thread derivation, no curation, no UI views.
- No worker start, no real model call — fakes only.
- No edit to migrations 0006/0009/0010/0012, `test_extraction_core.py`, `test_worker_extract.py`, `test_migrations.py`, `test_config.py`, `AGENTS.md`, `infra/Makefile`.
- No `make client` against :8000 — regenerate from the in-process `app.openapi()` dump (story 2.2 pattern), preserving the committed `baseUrl: 'http://localhost:8000'` literal form.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy path | Meeting with transcript+moments; model returns `## Topics` table, T1/T2 rows, multi-stamps | One `topic` row per T-id; one `topic_mention` per (topic, containing moment), `anchor_ms` = earliest stamp in that moment | No error |
| Anchor outside timeline | A stamp before first moment / past last `end_ms` | Stage fails naming the topic item id and the span | `StageError` |
| Zero topics, contentful meeting | Model returns a header-only or topic-free document | Parse succeeds empty; `stage.extract.zero_topics` logged with meeting id | Signal, not error |
| Unparseable reply | Prose, no table/bullet anywhere | One retry, then stage failure naming the document | `StageError` |
| Rerun | Same meeting extracted again | Old `topic`/`topic_mention` rows gone, new set inserted; `extraction_source(kind='topics')` upserted | No error |
| Superseded moment | Anchor lands in a `superseded` moment | Mention skipped + discard log; topic dropped (logged) only if no mention survives | No error |
| Missing config key | `config.yaml` lacks `topics_prompt` | Startup fails naming the key (pydantic required field) | Fail-fast |
| Prompts endpoint | `GET /extraction/prompts` | Three entries; `kind="topic"` carries `topics_prompt` verbatim | No error |

</intent-contract>

## Code Map

- `server/meetingminer/config.py:189` — `ExtractionRoleBinding`: add `topics_prompt: NonEmptyText` directly after `action_items_prompt`. No other line (footprint).
- `config.yaml` — after `action_items_prompt` block (ends ~line 145, before the chat-role comment): `topics_prompt: |` block. Pinned parseable shape: `## Topics` heading; table `| ID | Topic | Gist | Timestamps |` with example row; IDs `T1, T2, T3...`; every row carries `[m:ss]` timestamps of *every* place the topic is discussed; ground rules mirroring the existing two (verbatim transcript form, no invention, STT noise, one row per topic, "no timestamp → must not be written"); generalized preamble ("one meeting or recorded session transcript").
- `server/meetingminer/pipeline/extraction.py` — `KIND_TOPIC = "topic"` (NOT added to `KNOWN_KINDS` — that set feeds the artifact counters); `DOC_TOPICS = "topics"` (NOT added to `DOCUMENT_KINDS` — the stage's artifact loop iterates it); `_TOPIC_PREFIX_KINDS = {"T": KIND_TOPIC}`. `ProposedArtifact` gains `anchors_ms: tuple[int, ...] = ()` (all parsed stamps, written order, after `owner`) — topics need every anchor; artifact kinds keep using `anchor_ms`. `parse_extraction_document` and `build_prompt` accept `DOC_TOPICS` (`build_topics_prompt` mirrors the other two builders). Every non-empty heading remains recognizable structure so conftest's shared header-only `EMPTY_EXTRACTION_DOCUMENT` parses to an honest zero, but a T-row becomes a topic only when its heading has topic/discussion/theme semantics or its table has both Topic and Gist columns; contentful foreign Decisions/Notes/task shapes fail by item id and retry. Non-T ids under topics parse remain structure, not topics. Dedup key: document-global (topics numbered once).
- `server/meetingminer/pipeline/stages/extract.py` — `_PROMPT_FIELD["topics"] = "topics_prompt"`; `_DELETE_TOPICS` before the document loop and on the early exit; third pass after the artifact loop: generate (never adopt) via the same `_generate` (one retry), resolve every `anchors_ms` entry, collapse to one mention per containing moment (earliest stamp wins), skip superseded with `_log_discard`-style log, insert `topic` + `topic_mention`, upsert `extraction_source` `kind='topics'` (origin `generated`, `item_count`=parsed topics, `artifact_count`=inserted topics, model/prompt_version/prompt_hash as the generate branch does); update the `_DELETE_ALL_SOURCES` comment (three kinds now, still all-or-nothing); summary log gains topics/mention counts; `stage.extract.zero_topics` when the meeting had content and zero topic rows landed.
- `server/meetingminer/migrations/0014_topics.sql` — NEW. `topic` (id uuidv7 PK, meeting_id FK CASCADE, name/gist NOT NULL, provenance jsonb, timestamps + `set_updated_at` trigger, index on meeting_id) and `topic_mention` (PK (topic_id, moment_id); topic_id FK CASCADE; composite FK `(moment_id, meeting_id) REFERENCES moment (id, meeting_id)` ON DELETE CASCADE — same-meeting integrity via 0009's composite key; navigation metadata, so cascade unlike `artifact`; `anchor_ms` bigint ≥ 0; index on moment_id). Comments: worker-owned, machine-derived, labelled as such; not artifacts; never in the lifecycle; replaced on rerun. Plus: widen `extraction_source_kind_check` to `('arch-summary','action-items','topics')` (drop + re-add named constraint).
- `server/meetingminer/api/extraction.py` — `ExtractionPromptKind = Literal["adr", "action-item", "topic"]`; third entry `kind="topic"`, `prompt_text=binding.topics_prompt`; docstring "two" → "three".
- `web/src/features/moments/moments.ts:44-51` — `extractionPromptLabel` enumerates kinds by hand; make it render whatever the endpoint returns: accept the generated union, `ARTIFACT_CATEGORIES` label ?? `{topic: 'Topics'}` ?? the kind itself. Test in `moments.test.ts`; MomentView already maps `prompts` generically — add a `topic`-kind rendering case in `MomentView.test.tsx`.
- `web/src/client/` — regenerate: dump `app.openapi()` via `uv run --project server python` (env: `MM_DROPS_ROOT`/`MM_CONTENT_ROOT` set), inject `servers: [{url: 'http://localhost:8000'}]` to keep `client.gen.ts`/`baseUrl` byte-stable (2.2 precedent), `pnpm --dir web run client -i <dump>`.
- `docs/architecture.md` — one short data-model note after the System-shape numbered list (before `## Decisions`): `topic`/`topic_mention` as worker-owned, machine-derived, moment-anchored navigation metadata outside the publish lifecycle, replaced on rerun, projected by 10.2. AD-8…AD-11 untouched (11-2 owns AD-10).
- `server/tests/conftest.py:409-417` — **pinned shared addition, outside the frozen footprint, mechanically forced**: append `"topic", "topic_mention"` to `EVIDENCE_TABLES` (with a story-10.1 comment). Postgres refuses `TRUNCATE meeting/moment` once any table references them without being named — without this every DB-backed test in every lane fails the moment 0014 applies. story/11-2's conftest hunks end ~line 250; verified clean via `branch_conflicts.py`. Exact definition pinned here so no second spelling can appear.
- Read-only patterns: `server/tests/test_worker_extract.py` (runner+FakeLlm store-backed pattern), `test_api_prompts.py` (field-set pinning), `conftest.py` `FakeLlm`/`make_drop`/`valid_metadata`/`test_pool`, `projection_seed.seed_meeting`, `test_worker_runner` helpers.

## Tasks & Acceptance

**Execution (dependency order):**
1. `server/tests/test_extraction_topics.py` — NEW, red first: parser (table+bullet layouts, T-ids, all-anchors capture, range/comma stamps, missing-anchor error, no-structure error, dedup, EMPTY_EXTRACTION_DOCUMENT parses to zero topics), prompt build (template composed verbatim + header + transcript), config binding (`topics_prompt` loads from committed config; wording generalized, no "Microsoft Teams"), then store-backed stage tests (rows land, mention-per-moment collapse, rerun replaces, superseded skip, zero-topics signal, anchor-outside StageError, `extraction_source` topics row).
2. `server/tests/test_migrations_topics.py` — NEW, red first: tables exist with expected columns; composite-FK rejects a mention naming another meeting's moment; topic delete cascades mentions; meeting delete cascades topics; moment delete cascades mentions; `extraction_source` accepts `'topics'`, rejects a fourth kind.
3. `server/tests/test_api_extraction_prompts_topics.py` — NEW, red first: three prompts, field sets, `topic` text verbatim `== binding.topics_prompt`, `## Topics` present.
4. `server/meetingminer/config.py` + `config.yaml` — the binding field and the committed prompt.
5. `server/meetingminer/migrations/0014_topics.sql` + conftest `EVIDENCE_TABLES` append (one commit, pinned together — the migration is unlandable without the append).
6. `server/meetingminer/pipeline/extraction.py` — parser + prompt builder extensions.
7. `server/meetingminer/pipeline/stages/extract.py` — the third pass.
8. `server/meetingminer/api/extraction.py` — serve `kind="topic"`.
9. `web/src/client/` regeneration + `web/src/features/moments/moments.ts` label + web tests.
10. `docs/architecture.md` data-model note; sprint-status/notes; review prompt.

**Acceptance Criteria:**
- Given the extract stage and a fake LLM scripted with a topics document, when a meeting is extracted, then `topic` rows carry name+gist and `topic_mention` rows link each anchor's containing moment — through the same port and parser machinery as the other two documents.
- Given an anchor outside the timeline, when the topics pass runs, then the stage fails naming the topic item id.
- Given a contentful meeting whose topics document yields nothing, when the pass completes, then a named zero-topics signal is logged and the run is not an error.
- Given a rerun, when extract runs again, then the previous topic rows are replaced, and no `artifact` row or lifecycle state is touched.
- Given the committed `config.yaml`, when `GET /extraction/prompts` is called, then three kinds return, `topic` verbatim from config, and the UI section renders it with a "Topics" label.

## Spec Change Log

- 2026-08-30 (owner decision, review finding #5): **fairly strict parser boundary.** Heading drift remains supported (`Topics`, `Discussion themes`, and equivalent topic/discussion/theme wording), while an otherwise drifted table is also accepted when it has both Topic and Gist columns. A contentful foreign Decisions/Notes/task shape with a T-row is a named parse error and therefore earns the generated-document retry. The shared foreign header-only default remains a successful zero-topic document. Added accepted-drift, rejected Decisions/task, and generate-retry regressions; all were observed red before the parser guard and green afterward.
- 2026-08-30 (build): three more consequential test edits outside the frozen footprint, each mechanically forced by the story's own AC (a third always-generated document changes counts existing tests pin) and each minimal:
  - `server/tests/test_config.py` — one line: `topics_prompt` added to the `VALID_CONFIG` fixture (a required binding field fails all 35 minimal-config tests without it). 11-2's edits are EOF-appended; this is mid-file.
  - `server/tests/test_worker_extract.py` — expectation updates only: call counts +1 for the topics pass, `extraction_source` set/count 2 → 3, `generated` 0 → 1, adoption's zero-call asserts now name the one topics call. No test logic changed.
  - `server/tests/test_api_prompts.py` — `len == 2` → `3`, kind set gains `topic` (verbatim pin lives in the new 10.1 file).
  All verified clean against every in-flight `story/*` branch with `branch_conflicts.py` before the final push.
- 2026-08-30 (planning): `server/tests/conftest.py` `EVIDENCE_TABLES` append recorded as a deliberate, named footprint deviation — mechanical necessity (Postgres TRUNCATE FK rule), pinned in Code Map, conflict-checked against every in-flight branch. Wave rule "do not widen quietly" satisfied by this entry + review-prompt callout.

## Review Triage Log

### 2026-08-30 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 1: (high 0, medium 0, low 1)
- defer: 0
- reject: 2
- addressed_findings:
  - `low` `patch` The new API test file's docstring claimed `test_api_prompts.py` "stays frozen at two entries", made false by the consequential count update there — rewritten to describe the actual split. Rejected as noise: duplicate topic names per meeting are permitted by design (10.2 normalizes); the code-owned "Meeting:" prompt header residue is story 6.7's already-filed deferred item.

## Design Notes

- Fairly strict topic acceptance (owner decision, review finding #5): heading drift is tolerated when the heading still carries topic/discussion/theme semantics, and canonical Topic/Gist columns can establish semantics under a neutral heading. A T-row with neither signal is refused and retried. Header-only foreign tables still parse to zero so the shared worker default remains valid.
- One mention per (topic, containing moment): the moment is the citation unit; two stamps inside one moment are one discussion. PK `(topic_id, moment_id)` makes the collapse a constraint, not a convention.
- `anchors_ms` added to `ProposedArtifact` rather than a parallel topic dataclass: one parser, one row shape, additive field, artifact paths untouched.

## Verification

**Commands:**
- `uv run --project server pytest server/tests/test_extraction_topics.py server/tests/test_api_extraction_prompts_topics.py server/tests/test_migrations_topics.py -q` — expected: all pass (DB-backed parts skip by name only if Postgres is down).
- `make test-fast` — expected: green, no new skips, fast-budget respected.
- `make test` — once before `review`: green (migration applies to the per-run database; twins required).
- `make web-test` — expected: green including the new label/render tests.
- `python3 _bmad/scripts/branch_conflicts.py --against story/10-1` — expected: `clean` for every pair not involving `story/11-2-review`.

## Auto Run Result

Status: review — implementation complete, internal review pass done, awaiting
the external `bmad-code-review` pass
(`review-prompt-story-10-1-2026-08-30.md`). Not merged, not done.

**Implemented:** the topics document as the third whole-transcript extraction
pass — same `Llm(extraction)` port, same parser machinery, one-retry
discipline; `topic`/`topic_mention` rows (migration 0014) anchored to moments,
worker-owned, machine-derived, replaced on rerun, outside the artifact
lifecycle; `topics_prompt` in `config.yaml` served as `kind="topic"`; prompts
UI renders whatever the endpoint returns; client regenerated in-process.

**Files:** `config.py` (+1 field), `config.yaml` (+prompt block),
`pipeline/extraction.py` (DOC_TOPICS, anchors_ms, topic_gist),
`stages/extract.py` (third pass), `api/extraction.py` (+topic kind),
`migrations/0014_topics.sql` (new), `docs/architecture.md` (data note),
`web/src/features/moments/*` (+label, tests), `web/src/client/types.gen.ts`
(regenerated), three new test files; consequential: `conftest.py`
EVIDENCE_TABLES, `test_worker_extract.py` counts, `test_config.py` fixture
key, `test_api_prompts.py` counts (all in the change log).

**Review findings:** patch 1 (low — stale docstring, fixed), defer 0,
reject 2. Followup score: 1 low = 1 < 5 → `followup_review_recommended:
false` (0 high, 0 medium, 1 low patched).

**Verification:** story files 31 passed ~9s; `make test-fast` 1432 passed /
326 deselected / 0 skips, 50s; `make web-test` 294 passed; `make test` full
gate exit 0 — 1758 passed, 13m17s, web build ok; `branch_conflicts.py`: all
`story/10-1` pairs clean except the exempt `× story/11-2-review`.

**Residual risks:** the real extraction model's topics output is unproven
against the committed prompt (owner runs a real extraction after
integration); `main × story/11-2` spec-file conflict pre-exists this story.
