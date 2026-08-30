---
title: 'Story 4.1: Artifact Extraction Pipeline Stage'
type: 'feature'
created: '2026-08-20'
status: 'done'
baseline_revision: 'eb5d98e615c76a30996bc95451252af564b5e68f'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-4-context.md'
warnings: [oversized]
deferred:
  - summary: >-
      Story 4.3's approval endpoint must consider a concurrently running extract
      stage: the stage snapshots approved moments and deletes drafts at stage
      start inside one long transaction, so an approval committed mid-extract
      can race the draft delete-and-re-propose cycle.
    evidence: |-
      extract.py reads _SELECT_APPROVED_MOMENTS once, then holds the runner's
      transaction across per-moment LLM calls (minutes). An API approval that
      commits during that window targets rows the stage's uncommitted DELETE
      holds locks on, and fresh drafts are inserted beside a just-approved
      artifact. Unreachable until 4.3 exists; single-writer today.
    location: >-
      server/meetingminer/pipeline/stages/extract.py
    severity: medium
  - summary: >-
      Consider retrying the primary extraction model before sticky fallback
      engagement — one transient RateLimitError currently relegates the whole
      meeting to the local fallback model.
    evidence: |-
      FallbackLlm engages on the first LlmError and stays engaged for the
      instance's lifetime (one meeting). litellm's num_retries is not set. The
      matrix pins fallback-for-the-rest-of-the-meeting once engaged; what is
      tunable is how eagerly a transient failure triggers engagement.
    location: >-
      server/meetingminer/adapters/llm/__init__.py
    severity: low
  - summary: >-
      Prompt hardening for extraction: delimit transcript/OCR evidence blocks
      against instruction-shaped content, and pin + record sampling parameters
      (temperature, max_tokens) in artifact provenance.
    evidence: |-
      build_prompt interpolates untrusted transcript and OCR text undelimited
      after the instruction block, and litellm.completion runs on provider
      sampling defaults that provenance does not capture. Consequences are
      bounded by human approval (AD-4), and prompt tuning is 4.2/Epic-5
      territory, so recorded rather than patched.
    location: >-
      server/meetingminer/pipeline/extraction.py
    severity: low
  - summary: >-
      Epics AC "the appropriate artifact set is produced for each archetype"
      (UX-DR6) is measurable only by Epic 5's extraction eval over real models;
      4.1 verifies only that archetype evidence reaches the prompt.
    evidence: |-
      Every 4.1 test scripts FakeLlm replies; no test observes real extraction
      output over a slide-deck versus UI-demo meeting. The eval harness
      snapshots prompt_version/model provenance for exactly this purpose.
    location: >-
      server/meetingminer/pipeline/extraction.py
    severity: low
---

<intent-contract>

## Intent

**Problem:** Every job pauses at the unregistered `extract` stage and no ADRs or action items exist anywhere — meeting outcomes are still mined by hand (FR19, FR20 start; epics.md Story 4.1).

**Approach:** Build the `Llm(extraction)` port (config-bound via LiteLLM, `claude-sonnet-5` primary, `ollama/qwen3:32b` fallback), an `artifact` table, and a checkpointed, idempotent `extract` stage that proposes ADRs and action items per moment and inserts them as `extracted` (unpublished) rows linked to their yielding moment. Jobs start reaching `done`.

## Boundaries & Constraints

**Always:**
- AD-8/AD-10: `litellm` is imported only under `adapters/llm/`; the binding comes from `config.yaml` `llm.roles.extraction` + `providers`; secrets stay in env.
- AD-5 column split: the worker inserts artifact rows and owns extraction-content columns (`kind`, `title`, `body`, `provenance`); the lifecycle column `state` is written by the worker only as the insert default `'extracted'` — no worker code path ever updates it.
- AD-11 idempotence: a rerun deletes and re-proposes only this meeting's `state = 'extracted'` rows; `approved`/`published` rows are never deleted, updated, or re-proposed.
- NFR5: the stage writes only `artifact` rows — never evidence tables, never files.
- NFR7: nothing is projected at extract; the publish gate (`projections/publish_gate.py`) keeps unpublished artifacts out of both stores; `GET /search` never returns artifact content.
- No silent zero (SPEC constraint): model output is parsed strictly — malformed JSON or an unknown `kind` raises, and a meeting-level zero-artifact outcome is logged as its own named event, never passed off silently as success.
- Tests never call a real LLM: an autouse conftest fixture binds the stage to a FakeLlm, mirroring the existing autouse `build_stt` fake.
- `evidence_complete()` and `EVIDENCE_STAGES` stay unchanged; `extract` stays out of `AUGMENTATION_STAGES` and `PARTICIPANT_AUGMENTATION_STAGES`.

**Block If:**
- The frozen artifact shape in `publish_gate.py` (`kind/state/title/body/moment_ids`, states `extracted→approved→published`) cannot be satisfied by the schema — that would be an architecture change, not a story decision.
- Registering `extract` requires changing any evidence stage's behavior (beyond test assertions about the pause).

**Never:**
- No API routes, no web changes — the right-rail read is Story 2.2; approval/publish endpoints are Story 4.3; prompt visibility/config-swap of prompt text is Story 4.2 (prompts here are baked-in constants).
- No re-arming of `extract` on augmentation; no unpublish path; no new `config.yaml` keys.
- No batching a whole meeting into one model call — the AC is per-moment extraction, linked to the yielding moment.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy path | Job settled through `moments`; eligible moments exist | One LLM call per eligible moment; artifact rows inserted `extracted`, FK to moment; stage `done`; job `done` | No error |
| Zero artifacts | Model returns `{"artifacts": []}` for every moment | No rows; stage/job still `done`; `stage.extract.zero_artifacts` event logged | Signal, not failure |
| Malformed response | Non-JSON, JSON without `artifacts` list, or unknown `kind` | One retry against the same completer; second failure raises | `StageError` naming the moment; job `failed` at `extract` |
| Primary unavailable | Anthropic unreachable / auth fails | Fallback completer used for the rest of the meeting; substitution logged once; `provenance.fallback_engaged = true` | No error if fallback answers |
| Both unavailable | Primary and fallback both fail | Stage fails with both errors named | `StageError`; job `failed`, retryable by re-queue |
| Rerun after partial approval | Meeting has `extracted` + `approved` rows; stage re-queued | `extracted` rows deleted and re-proposed; `approved`/`published` rows untouched and their moments skipped | No error |
| Transcript-only meeting | No recording, video stages `skipped` | Extraction runs normally over transcript-derived moments | No error |
| Nothing to extract from | Moment superseded, or empty transcript text and no OCR text | Moment skipped, counted in summary log | No error |

</intent-contract>

## Code Map

- `server/meetingminer/domain/jobs.py` -- `STAGE_NAMES` already ends `..., 'moments', 'extract'` (:13); `AUGMENTATION_STAGES` comment (:43-45) claims extract "has no registered implementation" — stale after this story, reword to the surviving rationale (reads transcript, produces artifacts, human approval must not be silently re-proposed). `EVIDENCE_STAGES`/`evidence_complete` (:84,:103) unchanged.
- `server/meetingminer/pipeline/runner.py` -- registry pause at :562-567; job-done block after the loop (:624-628) already exists and becomes reachable; `_maybe_project` (:395) already documents staying correct once extract registers. No changes here.
- `server/meetingminer/pipeline/stages/__init__.py` -- registry; module docstring (:3-11) says "Epic 4 adds its module and one line here". Add `extract` entry + import.
- `server/meetingminer/pipeline/stages/moments.py` -- the stage-shape reference: targeted SQL, `Jsonb` provenance, summary log event with counts (:236-262).
- `server/meetingminer/projections/evidence.py` -- `read_meeting()` (:159) is the reuse point for extraction input: `MomentRow.text` ("Speaker: text" lines), `.speakers`, `.screenshot_id`; `ScreenshotRow.view_type`/`.ocr_text`. Store-free by design. Superseded moments are NOT flagged on `MomentRow` — exclude via `SELECT id FROM moment WHERE meeting_id=%s AND provenance @> '{"superseded": true}'`.
- `server/meetingminer/projections/publish_gate.py` -- frozen artifact vocabulary: `ARTIFACT_STATES` (:28), `Artifact` dataclass (:83-99) with `kind`, `state`, `title`, `body`, `moment_ids`. Schema must map 1:1 (single `moment_id` FK satisfies `moment_ids`; spine ERD is `MOMENT ||--o{ ARTIFACT`).
- `server/meetingminer/adapters/stt/__init__.py` + `adapters/embed/port.py` -- the port/factory pattern to mirror: Protocol + typed errors, `build_*` factory, structural config binding, `*UnavailableError` distinct from misconfiguration.
- `server/meetingminer/config.py` -- `LlmRoles.extraction` (:141-153) and `providers` already exist; no config changes.
- `config.yaml` -- `llm.roles.extraction: claude-sonnet-5 / ollama/qwen3:32b` (:23-27), `providers.*.base_url` (:44-52).
- `server/meetingminer/migrations/` -- next file is `0009`; follow 0006's style (uuidv7 PK, CHECK constraints, `set_updated_at` trigger).
- `server/pyproject.toml` -- add `litellm`; note the embedder deliberately avoided a client dep, but AD-8 names LiteLLM for the `Llm` port specifically.
- `server/tests/conftest.py` -- autouse `build_stt` fake at :633-646 and scriptable `fake_stt` at :650 are the template for `FakeLlm`.
- Tests asserting the extract pause via real worker runs — update to assert completion: `server/tests/test_worker_moments.py` (:253 "never reaches done"), `server/tests/test_augmentation.py` (:172 `statuses["extract"] == "queued"`), and sweep `test_worker_runner.py` for end-state assertions of `running`/`queued` that become `done`. `test_api_meetings.py:131`, `test_projections_rebuild.py:387`, `server/tests/projection_seed.py` construct the paused state directly in SQL — still valid, touch comments only if factually wrong.
- `server/tests/test_ingests.py:50` -- asserts `extract not in AUGMENTATION_STAGES`; stays true, message wording may need the "unbuilt" rationale updated.

## Tasks & Acceptance

**Execution:**
- `server/meetingminer/migrations/0009_artifacts.sql` -- create `artifact`: `id uuid PK uuidv7()`, `moment_id uuid NOT NULL REFERENCES moment(id)` (deliberately NO cascade: deleting a moment that yielded artifacts must fail loudly, protecting "published artifacts stay valid across augmentation"), `meeting_id uuid NOT NULL REFERENCES meeting(id)`, `kind text CHECK IN ('adr','action-item')`, `state text NOT NULL DEFAULT 'extracted' CHECK IN ('extracted','approved','published')`, `title text NOT NULL`, `body text NOT NULL`, `provenance jsonb NOT NULL DEFAULT '{}'`, timestamps + `set_updated_at` trigger; indexes on `(moment_id)` and `(meeting_id, state)`.
- `server/meetingminer/adapters/llm/port.py` -- `Llm` Protocol: `complete(prompt: str) -> LlmReply` where `LlmReply` carries `text`, `model` (the model that actually answered), `fallback_engaged: bool`; `LlmError` + `LlmUnavailableError` (mirroring embed/port.py's two-error contract).
- `server/meetingminer/adapters/llm/litellm.py` -- LiteLLM-backed completer: model string passed through; `api_base` resolved from `providers.<prefix>.base_url` when the model string carries a known provider prefix (e.g. `ollama/...`), Anthropic base_url for bare `claude-*`; sane timeout; maps litellm exceptions to the two port errors.
- `server/meetingminer/adapters/llm/__init__.py` -- `build_llm(role_binding, providers, log)` factory returning a fallback-composing `Llm`: primary first; on any `LlmError` from the primary, log the substitution once and use the configured fallback for subsequent calls; both failing raises with both errors named.
- `server/meetingminer/pipeline/extraction.py` -- engine-free decision core: baked-in prompt constant(s) with a `PROMPT_VERSION`, instructions covering both meeting archetypes (slide-deck vs UI demo) and both kinds; `MomentInput` value type; `build_prompt(...)` embedding meeting title, moment span, speakers, transcript lines, and — when present — screen `view_type` + OCR text; `parse_artifacts(text)` strict: accepts a JSON object `{"artifacts": [{"kind","title","body"}]}` (tolerating a fenced code block), rejects unknown kinds/missing fields with a named error.
- `server/meetingminer/pipeline/stages/extract.py` -- stage: build the completer via `build_llm`; read the bundle via `projections.evidence.read_meeting`; exclude superseded moments (provenance query), moments with neither transcript text nor OCR text, and moments already carrying an `approved`/`published` artifact; `DELETE FROM artifact WHERE meeting_id = %s AND state = 'extracted'`; per eligible moment call `complete` (one retry on parse failure), insert rows with `provenance = {"role":"extraction","model":reply.model,"fallback_engaged":...,"prompt_version":...}`; emit `stage.extract.summary` (moments scanned/skipped-by-reason, artifacts per kind, model used) and `stage.extract.zero_artifacts` when eligible moments > 0 and artifacts == 0.
- `server/meetingminer/pipeline/stages/__init__.py` -- import + register `"extract": extract_stage.run`; update the docstring that says no job reaches `done`.
- `server/meetingminer/domain/jobs.py` -- comment-only: reword the two stale "no registered implementation" rationales (AUGMENTATION_STAGES, EVIDENCE_STAGES blocks).
- `server/pyproject.toml` -- add `litellm` dependency (then `uv lock` in `server/`).
- `server/tests/conftest.py` -- `FakeLlm` (scriptable per-call replies/errors) + autouse fixture binding `extract_stage.build_llm` to a default zero-artifact fake + scriptable `fake_llm` fixture, exactly the `build_stt` pattern.
- `server/tests/test_extraction_core.py` -- unit tests: prompt embeds transcript, speakers, and screen evidence (view_type + OCR) when present and omits the screen block when absent; parse accepts plain and fenced JSON and empty lists; parse rejects non-JSON, missing fields, unknown kind; AST-walk test asserting `litellm` is imported only under `adapters/llm/` (pattern: `test_projections_single_writer.py`).
- `server/tests/test_worker_extract.py` -- store-backed stage tests via `runner.run_once`: rows land `extracted` linked to yielding moments and job reaches `done`; transcript-only meeting extracts; idempotent rerun (re-queue extract → `extracted` rows replaced, `approved` row and its moment untouched/skipped); parse-failure retry then job `failed` naming `extract`; primary-unavailable engages fallback with `fallback_engaged` provenance; both-unavailable fails the job; superseded and empty moments skipped per summary counts.
- `server/tests/test_worker_moments.py`, `server/tests/test_augmentation.py`, `server/tests/test_worker_runner.py` -- update pause-at-extract assertions to the new completion behavior (jobs reach `done` with the autouse fake).

**Acceptance Criteria:**
- Given a queued job for a drop with a recording, when the worker runs with the extraction port answering, then every stage including `extract` checkpoints `done`, the job reaches `done`, and each proposed artifact is a row in `extracted` state FK-linked to the moment that yielded it (AD-11, AD-5).
- Given a transcript-only drop, when the worker runs, then `extract` runs over its transcript-derived moments and behaves identically (AD-1).
- Given a meeting whose evidence projected at ingest-complete, when `extract` settles and `GET /search` is queried for an extracted artifact's title text, then no artifact content appears in any hit — the stores were not written by extract (NFR7, AD-4).
- Given an extraction rerun over a meeting with an `approved` artifact, when the stage completes, then that row and its moment's artifact set are unchanged and only `extracted` drafts were replaced (SPEC "augmentation adds, never destroys").
- Given both archetypes, when prompts are built, then a moment with slide/UI screen evidence carries that evidence (view_type + OCR text) into the prompt, and a transcript-only moment's prompt omits the screen block cleanly (UX archetypes, epics AC 3).
- Given `config.yaml` with a different `llm.roles.extraction.model`, when the stage binds, then the new model string is what the adapter is constructed with — no code change (AD-8, AD-10).

## Spec Change Log

## Review Triage Log

### 2026-08-20 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 11: (high 0, medium 5, low 6)
- defer: 4: (high 0, medium 1, low 3)
- reject: 10
- addressed_findings:
  - `[medium]` `[patch]` `artifact.meeting_id` unconstrained against its moment's meeting — composite FK `(moment_id, meeting_id) → moment (id, meeting_id)` plus `UNIQUE (id, meeting_id)` on moment added inside migration 0009.
  - `[medium]` `[patch]` Draft sibling on an approved moment was deleted and never re-proposed — `_DELETE_DRAFTS` now excludes approved/published moments entirely; skip counting reordered so approved precedes no-text; mixed-state rerun test added.
  - `[medium]` `[patch]` `LiteLlmCompleter.complete` had zero execution coverage — stubbed-`litellm` tests added for passthrough (model/api_base/timeout/messages), all mapped exceptions, unmapped exceptions, degenerate responses, and `response.model` provenance.
  - `[medium]` `[patch]` Response handling could leak unmapped `TypeError`/`KeyError` and non-string content — except tuple broadened, `isinstance(str)` check added, lazy `import litellm` wrapped to `LlmError`.
  - `[medium]` `[patch]` Spec AC 3 (search-negative) and NFR5 evidence invariance were asserted only structurally — store-backed extract→project→`GET /search` negative test and evidence-table row-count invariance added.
  - `[low]` `[patch]` Fallback engagement on base `LlmError` untested — engagement test with a plain `LlmError` primary added.
  - `[low]` `[patch]` `_span` rendered 90 minutes as `90:12` — `h:mm:ss` from one hour up, with test.
  - `[low]` `[patch]` `_strip_fences` dropped payload sharing the opening fence line — unfence keeps non-language-tag content, with test.
  - `[low]` `[patch]` `_propose` typed `Any` — now `Llm`/`LlmReply` port types.
  - `[low]` `[patch]` `_no_real_llm` docstring overclaimed its guard — reworded to exactly what is patched.
  - `[low]` `[patch]` Rerun-test comment slip ("approved moment's moment", ambiguous "Moment 1") — reworded.

### Review Findings

- [x] [Review][Patch] Reject non-string artifact kinds as parse errors [server/meetingminer/pipeline/extraction.py:211] — fixed with a type guard plus core and stage-retry regressions.
- [x] [Review][Patch] Bind bare OpenAI model names to the configured endpoint [server/meetingminer/adapters/llm/litellm.py:49] — fixed for common bare OpenAI model IDs, with an endpoint-resolution regression.
- [x] [Review][Patch] Correct the LiteLLM import-boundary verification glob [_bmad-output/implementation-artifacts/spec-4-1-artifact-extraction-pipeline-stage.md:189] — fixed to exclude the adapter path from the repository root.

## Design Notes

- **Per-moment calls, per-meeting transaction.** The whole stage runs inside the runner's open transaction (stage.py contract) — a mid-meeting failure rolls back every draft, so a retry never sees half a meeting's proposals. Precedent for long-running work inside the stage transaction: `transcribe`.
- **Reuse `read_meeting` rather than re-deriving moment text.** The extraction input text is exactly the projection's moment document text; a third SQL assembly of "what a moment says" is the divergence AD-4 warns about. Attack point: this couples pipeline→projections; the defense is that `evidence.py` is deliberately store-free and read-only.
- **`moment_id` FK without cascade** makes the moments stage's stale-screen-moment DELETE fail loudly if it ever hits a moment that yielded artifacts. Analysis says no realistic path reaches it (recovered-recording augmentation starts from transcript-only meetings with no screen moments; participant augmentation recomputes an identical screen-moment set; a failed job never reached extract) — and if one appears, a named FK failure beats silently destroying approved artifacts.
- **Fallback at call time, not bind time** (unlike OCR): LLM unavailability is a network fact discovered on first call. Once engaged, the fallback serves the rest of the meeting — flip-flopping mid-meeting would mix two models' judgments in one artifact set with no record of which produced what beyond provenance.
- **Extract stays out of the augmentation sets**, so an augmenting drop re-runs `align`/`moments` but not `extract` — the meeting's approved/published artifacts and existing drafts survive augmentation untouched. Re-extraction after augmentation is a deliberate manual re-queue, not an intake behavior.
- **Operational note for the dispatcher:** the 28 real-corpus jobs are all paused at `extract`. The next worker restart on a deployment with this story advances all of them through per-moment `claude-sonnet-5` calls (~850 moments) — real API spend, expected, but worth knowing before `make worker` on the dev machine.

## Verification

**Commands:**
- `cd server && uv run pytest tests/test_extraction_core.py -q` -- expected: all pass, store-free.
- `cd server && uv run pytest tests/ -q` -- expected: all pass (store-backed suites use the per-run database; projection tests queue on the cross-worktree lock). No test hits a real LLM.
- `make web-test` -- expected: unaffected, all pass (no web changes).
- `rg -n 'import litellm|from litellm' server/meetingminer --glob '!server/meetingminer/adapters/llm/**'` -- expected: no matches (AD-8 boundary).

## Auto Run Result

**Status:** done (review passed; 11 patches applied, 4 findings deferred, followup review recommended by score).

**Implemented change:** The `extract` pipeline stage is registered and jobs reach `done` for the first time. Extraction runs per moment through the new `Llm(extraction)` port (LiteLLM adapter, `claude-sonnet-5` primary with call-time sticky fallback to `ollama/qwen3:32b`), proposing ADRs and action items parsed strictly from pinned-shape JSON, inserted as `artifact` rows in `extracted` state FK-linked to the yielding moment (migration 0009, composite FK to `moment (id, meeting_id)`). Idempotent rerun replaces only drafts and leaves approved/published moments — drafts included — untouched. Nothing is projected at extract; unpublished artifacts stay out of both stores.

**Files changed:**
- `server/meetingminer/migrations/0009_artifacts.sql` — `artifact` table, lifecycle CHECK, composite moment FK, trigger, indexes.
- `server/meetingminer/adapters/llm/{port,litellm,__init__}.py` — `Llm` port, LiteLLM completer, fallback composer.
- `server/meetingminer/pipeline/extraction.py` — baked-in prompt (`PROMPT_VERSION` 1), `build_prompt`, strict `parse_artifacts`.
- `server/meetingminer/pipeline/stages/extract.py` + `stages/__init__.py` — the stage and its registration.
- `server/meetingminer/domain/jobs.py`, `server/meetingminer/projections/evidence.py` — comment-only staleness fixes.
- `server/pyproject.toml` + `server/uv.lock` — `litellm` dependency.
- `server/tests/` — `FakeLlm` + autouse guard (conftest), `test_extraction_core.py` (46), `test_worker_extract.py` (9), pause-at-extract assertion updates across worker/augmentation/ingest/rebuild tests, `projection_seed.py` comments.

**Review findings breakdown:** 11 patched (5 medium, 6 low — all applied in `de22eff` and re-verified), 4 deferred to frontmatter `deferred` (4.3 approval concurrency; primary retry before fallback; prompt hardening/sampling provenance; archetype-quality measurement belongs to Epic 5 evals), 10 rejected as noise or mistaken premise.

**Follow-up review recommendation:** true — patched counts high 0, medium 5, low 6; score 3×5 + 1×6 = 21 ≥ 5.

**Verification performed (run by the coordinator, post-patch):**
- `cd server && uv run pytest tests/ -q` → 1141 passed (0:05:54).
- `cd server && uv run pytest tests/test_extraction_core.py -q` → passed within the above (46 tests).
- `make web-test` → 90 passed.
- `rg 'import litellm|from litellm' server/meetingminer` outside `adapters/llm/` → no matches (also pinned by an AST test).

**Residual risks:**
- The 28 real-corpus jobs are all paused at `extract`; the next worker restart on this code advances them through ~850 per-moment `claude-sonnet-5` calls — real API spend, expected but deliberate. Run `make migrate` before restarting the worker (migration 0009).
- Archetype-appropriate extraction quality is unverified until Epic 5's extraction evals (deferred item).
- The right-rail read path does not exist yet (Story 2.2); until then extracted artifacts are visible only via SQL.
