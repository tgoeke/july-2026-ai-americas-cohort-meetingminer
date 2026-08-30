---
title: 'Story 4-2: Visible, Swappable Extraction Prompts'
type: 'feature'
created: '2026-08-21'
status: 'done'
baseline_revision: '64363f7527f613c3b3ebcfeb3d245c7c621be1d5'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-4-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-4-1a-whole-transcript-extraction.md'
warnings: [oversized]
deferred:
  - summary: >-
      A historical `prompt_hash` cannot be resolved back to its exact prompt
      text once `config.yaml` is edited again; only the current binding is
      queryable.
    evidence: |-
      `extraction_source.prompt_hash` and `artifact.provenance.prompt_hash`
      store only the hash, not the template text itself. Recovering the exact
      text behind an older hash requires correlating it against `config.yaml`'s
      git history by hand — no code path automates that lookup. AC3 ("records
      which prompt/model configuration produced it") is satisfied literally
      (a durable, config-edit-sensitive identifier exists), but exact-text
      reproducibility for an eval rerun is a manual git-archaeology exercise,
      not a queryable one.
    location: >-
      server/meetingminer/pipeline/stages/extract.py
    severity: low
  - summary: >-
      `MomentView` refetches `GET /extraction/prompts` on every mount, even
      though the two prompts are global config, not per-moment data.
    evidence: |-
      The new `useEffect` in `web/src/features/moments/MomentView.tsx` has an
      empty dependency array, so it only refires on remount, not on `momentId`
      changes within one mount — but if the app ever mounts a fresh
      `MomentView` per moment navigation (e.g. via a React `key`), each
      navigation re-fetches identical data with no cache.
    location: >-
      web/src/features/moments/MomentView.tsx
    severity: low
  - summary: >-
      A failed or slow "Active extraction prompts" fetch is swallowed with no
      logging, so a persistent backend regression on `GET /extraction/prompts`
      would silently and permanently hide the section with no operator signal.
    evidence: |-
      The `catch` block in `MomentView.tsx`'s prompts effect is empty by
      design (tolerant-of-failure is the intended UX), but nothing logs the
      failure anywhere, so the only symptom is an absent UI section that looks
      identical to "the fetch just hasn't answered yet."
    location: >-
      web/src/features/moments/MomentView.tsx
    severity: low
---

<intent-contract>

## Intent

**Problem:** Story 4.1a's two extraction prompts are Python string constants (`server/meetingminer/pipeline/extraction.py`). Nobody can see what produced an artifact without reading code, and changing a prompt means shipping code — both violate AD-8/AD-10 ("swapping is a config edit, never a code change") and FR19/UX-DR9.

**Approach:** Move both whole-transcript prompt templates into `config.yaml` as the two documents' active, editable text (their current content, `_GROUNDING_RULES` folded in, becomes the committed default). The stage reads them from config at call time; nothing in code hard-codes prompt text anymore. Add a read endpoint so the UI can show the full active text per artifact type, and record a hash of the resolved template on every generated artifact so provenance can tell two prompt-config edits apart even though `PROMPT_VERSION` (the parser-contract version) does not change.

## Boundaries & Constraints

**Always:**
- Prompt text lives only in `config.yaml`, under `llm.roles.extraction`, as two required, non-empty strings (`arch_summary_prompt` for the ADR document, `action_items_prompt` for the action-item document) — mirrors how `base_url`/`num_ctx`/`timeout_seconds` were added to the role binding in 4-1a.
- The generate path always uses whatever config currently holds; there is no code-level default it falls back to at runtime (AD-10).
- `parse_extraction_document`'s layout expectations (table header, `D#`/`A#` IDs, `[m:ss]` anchors) are load-bearing for whatever text ships in config's default — the committed default must keep producing parseable output, since a broken swap is the user's problem but a broken *default* is this story's.
- Every artifact's `provenance` and every `extraction_source` row for a *generated* document records a hash of the exact template text used (`prompt_hash`), alongside the unchanged `model`/`prompt_version`. `NULL` for an adopted document, matching `model`/`prompt_version`'s existing rule.
- New endpoint and new fields are additive: no change to `MomentArtifact`'s existing fields, `approve`/`publish` behavior, or the parser.

**Block If:** none identified — no decision here needs a human.

**Never:**
- No new artifact kinds, no touching 4.3's approve/publish routes or git-commit path.
- No restarting the worker; no paid model calls. Verify against fixtures/fake LLM only.
- No editing migrations 0009/0010/0011 — a new one only.
- No `{rules}` templating indirection: each config prompt is the complete text sent (plus the code-owned meeting header + transcript), so "the full active prompt text is visible" is literally true of what the UI shows.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Config prompt edited | `config.yaml`'s `action_items_prompt` changed, worker not restarted mid-run | Next `extract` run (fresh process) sends the new text; `prompt_hash` on new artifacts changes | No error |
| Missing prompt key | `config.yaml` omits `arch_summary_prompt` | App fails to start — `_StrictModel`/pydantic required-field error naming the missing key | Startup error, not a runtime default |
| UI reads active prompts | `GET /extraction/prompts` | Both kinds' full text returned, sourced from the same config the stage reads | No error |
| Adopted document | Drop carries the document, no model call | `extraction_source.prompt_hash` stays `NULL`, exactly like `model`/`prompt_version` | No error |
| Generated document | Drop lacks the document | `extraction_source.prompt_hash` and `artifact.provenance.prompt_hash` both set to the resolved template's hash | No error |

</intent-contract>

## Code Map

- `server/meetingminer/config.py:141-179` -- `LlmRoleBinding` (141), `LlmRoles` (176, `extraction: LlmRoleBinding`). Add `ExtractionRoleBinding(LlmRoleBinding)` with the two `NonEmptyText` (103) prompt fields; retype `LlmRoles.extraction`.
- `server/meetingminer/config.py:666` -- `AppConfig(settings, secrets, config_path)`; runtime access is always `request.app.state.config.settings...` (`api/main.py:130`), never a FastAPI `Depends`.
- `config.yaml:22-70` -- `llm.roles.extraction` block; add the two prompt keys as `|`-block scalars, comments explaining they are the literal, complete generate-path prompt (grounding rules folded in) and that editing either is a live behavior change.
- `server/meetingminer/pipeline/extraction.py:166-325` -- `_GROUNDING_RULES` (166), `_SUMMARY_PROMPT`/`_ACTIONS_PROMPT` (184/217, delete both plus `_GROUNDING_RULES`), `build_summary_prompt`/`build_actions_prompt`/`build_prompt` (273/289/305) — add a required keyword-only `template: str`, drop the `.format(rules=...)` call, join `template` + `_document_header(...)` + transcript exactly as before.
- `server/meetingminer/pipeline/stages/extract.py:144-147,273-353` -- `_DECLARATION` dict (144, the pattern to copy) for a new `_PROMPT_FIELD = {DOC_ARCH_SUMMARY: "arch_summary_prompt", DOC_ACTION_ITEMS: "action_items_prompt"}`; in `run()` (273), read `binding = ctx.config.settings.llm.roles.extraction` (274, unchanged) and pass `template=getattr(binding, _PROMPT_FIELD[document_kind])` into `core.build_prompt` (338-343); compute `prompt_hash = hashlib.sha256(template.encode()).hexdigest()[:16]` only on the generate branch (344-352), else `None`; add to the `provenance` dict (390-402) and to the `_UPSERT_EXTRACTION_SOURCE` params (408-423).
- `server/meetingminer/migrations/0011_artifact_publish_metadata.sql` -- read-only reference for the next migration number; create `0012_extraction_prompt_hash.sql` adding `prompt_hash text` to `extraction_source` (nullable, no CHECK — same shape as `model`).
- `server/meetingminer/api/registry.py` -- auto-discovery; a new `api/extraction.py` module with a top-level `router = APIRouter()` needs no `main.py` edit. No literal/parameterized prefix collision (`/extraction/prompts` shares no prefix with any existing router).
- `server/meetingminer/api/moments.py:221-229,241-264` -- `ArtifactKind`/`ArtifactState` Literal pattern to copy for a narrower `Literal["adr", "action-item"]`; `MomentArtifact` `ConfigDict(alias_generator=to_camel, ...)` pattern to copy for the new response models.
- `server/meetingminer/api/main.py:130` -- confirms `request.app.state.config` is the only DI path; new route follows the same convention (see `api/search.py:164`, `api/ingests.py:286` for examples).
- `web/src/client/sdk.gen.ts` (generated) -- regenerate via `make client` after the new route ships; do not hand-edit. `getMoment` (~line 56) is the shape a new `getExtractionPrompts` will take.
- `web/src/features/moments/moments.ts:21-29` -- `ARTIFACT_CATEGORIES` already carries the `adr`/`action-item` labels to reuse for the new section's headings.
- `web/src/features/moments/MomentView.tsx:39-119,344-413` -- `load()`'s abort/timeout pattern (61-119) to mirror at smaller scale for a mount-once prompts fetch; right rail `<aside>` (344-413) is where the new "Active extraction prompts" section renders, above the existing `<h3>Extracted artifacts</h3>` (350).
- `server/tests/conftest.py:195-199` -- `app_config` fixture (real, committed `config.yaml`) — source of the default prompt text for `test_extraction_core.py`'s rewritten prompt-shape tests, keeping that suite store-free.
- `server/tests/test_extraction_core.py:115-158` -- prompt tests to rework (they currently call `build_summary_prompt`/`build_actions_prompt` with no `template`).
- `server/tests/test_worker_extract.py:29,391,401` -- existing `prompt_version` assertions to extend with `prompt_hash`.
- `server/tests/test_api_moments.py` -- field-set-literal pinning style to copy for a new `server/tests/test_api_prompts.py`.

## Tasks & Acceptance

**Execution:**
- `server/meetingminer/config.py` -- add `ExtractionRoleBinding(LlmRoleBinding)` with `arch_summary_prompt: NonEmptyText` and `action_items_prompt: NonEmptyText`; retype `LlmRoles.extraction`. Rationale: prompts become a config-owned binding, extraction-only, without touching `chat`/`judge`.
- `config.yaml` -- add both prompt keys under `llm.roles.extraction` as block scalars; content is the current `_SUMMARY_PROMPT`/`_ACTIONS_PROMPT` text with `_GROUNDING_RULES` concatenated in verbatim (delete the `{rules}` placeholder). Comment that this is the literal, complete generate-path text and that editing it is a live behavior change with no code change (AD-10), and that the table header / ID prefixes / `[m:ss]` requirement are load-bearing for the parser.
- `server/meetingminer/pipeline/extraction.py` -- delete `_GROUNDING_RULES`, `_SUMMARY_PROMPT`, `_ACTIONS_PROMPT`; add required keyword-only `template: str` to `build_summary_prompt`, `build_actions_prompt`, `build_prompt`, composing it with `_document_header` + transcript exactly as the deleted constants were. Rationale: the engine-free core stays engine-free — it composes whatever text it is handed.
- `server/meetingminer/pipeline/stages/extract.py` -- select the right config field per `document_kind`, pass it as `template=`, compute `prompt_hash` only on the generate branch, thread it into both the artifact `provenance` dict and the `extraction_source` upsert. Rationale: epics AC3 — an artifact must record which prompt config produced it, and a config-only edit does not bump `PROMPT_VERSION`.
- `server/meetingminer/migrations/0012_extraction_prompt_hash.sql` -- new migration, `ALTER TABLE extraction_source ADD COLUMN prompt_hash text`. Rationale: AD-17-adjacent — the same "record what actually produced this" discipline `model`/`prompt_version` already follow.
- `server/meetingminer/api/extraction.py` (new) -- `router = APIRouter()`; `GET /extraction/prompts` returns `ExtractionPromptsResponse{prompts: list[ExtractionPrompt{kind: Literal["adr","action-item"], promptText: str}]}`, sourced from `request.app.state.config.settings.llm.roles.extraction`, `arch-summary → adr`, `action-items → action-item` (the same D/A-prefix mapping the parser already uses). Rationale: epics AC1 — a wire source for "the extraction area."
- `web/src/features/moments/MomentView.tsx` -- fetch `getExtractionPrompts()` once on mount (own `AbortController`, own small timeout, tolerant of failure — omits the section rather than blocking the moment view); render a collapsible "Active extraction prompts" section (`<details>` per kind, `<pre>` for text) in the right rail above "Extracted artifacts." Rationale: epics AC1, decoupled from any one moment's load state since the prompts are global config, not per-moment data.
- `server/tests/test_extraction_core.py` -- rework the prompt-shape tests (115-158) to source `template` from the `app_config` fixture; add a test proving `template` is used verbatim (a distinct sentinel string round-trips into the output) — the unit-level proof of "no code change needed."
- `server/tests/test_worker_extract.py` -- extend the `prompt_version` assertions (391, 401) with `prompt_hash` (set for generated, `None` for adopted); add a test that a different `ExtractionRoleBinding` prompt text changes `prompt_hash` without changing `PROMPT_VERSION`.
- `server/tests/test_api_prompts.py` (new) -- contract test for `GET /extraction/prompts`: both kinds present, `promptText` equal to the committed `config.yaml` value, field-set pinned per `test_api_moments.py`'s style.
- `web/src/features/moments/MomentView.test.tsx` -- new cases: both kinds' prompt text renders; a failed prompt fetch degrades silently (moment view still renders).

**Acceptance Criteria:**
- Given the committed `config.yaml`, when `GET /extraction/prompts` is called, then it returns the full, current text of both `arch_summary_prompt` and `action_items_prompt`, keyed `adr`/`action-item`.
- Given `config.yaml`'s `action_items_prompt` changed and the app restarted, when `extract` runs a generate-path meeting, then the model receives the new text with no code change, and the resulting artifacts' `provenance.prompt_hash` differs from a run against the old text.
- Given an adopted document, when `extract` completes, then its `extraction_source.prompt_hash` is `NULL`, matching `model`/`prompt_version`.
- Given the moment view, when it renders, then an "Active extraction prompts" section shows both kinds' full text, and a failed fetch of it never blocks or errors the rest of the moment view.

### Review Findings

- [x] [Review][Patch] Ignore prompt responses that arrive after their request has been aborted [`web/src/features/moments/MomentView.tsx:138`](../../web/src/features/moments/MomentView.tsx) — fixed in the independent review: the effect now returns when its controller is aborted, and `MomentView.test.tsx` proves a late post-timeout resolution cannot restore the section.

## Design Notes

- **AD-10 tension, resolved as an extension, not a violation.** AD-10's "nothing else lives there" targets adapter-binding sprawl (env vars, code defaults, CLI flags), not a prohibition on what a binding may contain. 4-1a already widened `LlmRoleBinding` past a bare model string (`base_url`, `num_ctx`, `timeout_seconds`) precisely because the role needed more than a model name to be fully config-driven; the two prompts are the same kind of addition, and the epics AC is explicit that `config.yaml` is where a prompt edit must land. Treated as a judgment call, not an intent gap.
- **`prompt_hash`, not a config-file-wide hash.** Hashing just the resolved template (not the whole `config.yaml`) means an unrelated config edit (e.g. `frames.jpeg_quality`) never perturbs extraction provenance, and the eval harness's own full-config snapshot (AD-10) already covers cross-run config diffing at the run level — this hash is the per-artifact-row answer to "which prompt text, specifically."
- **No `{rules}` placeholder.** Keeping a shared grounding-rules fragment that both prompts formatted in would mean the config value a user edits is not actually what gets sent — undermining "the full active prompt text is visible." Folding it into both defaults duplicates ~10 lines of YAML; that cost is worth the honesty of what's shown.

## Spec Change Log

## Review Triage Log

### 2026-08-21 — Review pass

Four layers over `64363f7527f613c3b3ebcfeb3d245c7c621be1d5..HEAD`: blind
hunter, edge-case hunter, verification-gap, intent-alignment.

- intent_gap: 0
- bad_spec: 0
- patch: 2: (high 0, medium 0, low 2)
- defer: 3: (high 0, medium 0, low 3)
- reject: 14
- addressed_findings:
  - `[low]` `[patch]` The new migration's comment claimed `prompt_hash` is
    "the sha256 of the resolved template text," but the code truncates it to
    `hexdigest()[:16]` (64 bits) — reworded to say "truncated sha256 (first
    16 hex characters)."
  - `[low]` `[patch]` `test_a_different_configured_prompt_changes_the_hash_not_the_prompt_version`
    only proved the mechanism for `arch_summary_prompt`; extended with a
    symmetric case for `action_items_prompt` so the story's central AC2/AC3
    mechanism is proven for both documents, not one.

## Verification

**Commands:**
- `cd server && uv run pytest tests/test_extraction_core.py -q` -- expected: all pass, store-free.
- `cd server && uv run pytest tests/ -q` -- expected: all pass; store-backed suites use the per-run database. Announce before running (shared Docker stores).
- `make web-test` -- expected: all pass, including the new `MomentView` prompt-section cases.
- `make client` -- expected: regenerates `web/src/client/` with the new `getExtractionPrompts` function; requires the api reachable (announce before running).
- `rg -n 'import litellm|from litellm' server/meetingminer --glob '!**/adapters/llm/**'` -- expected: no matches (AD-8 boundary, unaffected by this story).

## Auto Run Result

**Status:** implemented; review round 1 applied — both patch findings fixed.

**Summary of implemented change:** the two whole-transcript extraction
prompts moved from Python string constants into `config.yaml`
(`llm.roles.extraction.arch_summary_prompt` / `.action_items_prompt`), so a
prompt swap is a config edit with no code change. `GET /extraction/prompts`
serves both active prompt texts, and the moment view's right rail gained an
"Active extraction prompts" section (fetched once on mount, tolerant of
failure). Every generated document's artifacts and `extraction_source` row
now carry a `prompt_hash` (truncated sha256 of the resolved template),
letting provenance distinguish two prompt-config edits even though
`PROMPT_VERSION` — the parser-contract version — does not change on a
config-only edit.

**Files changed:**
- `server/meetingminer/config.py` — `ExtractionRoleBinding(LlmRoleBinding)`
  adds `arch_summary_prompt`/`action_items_prompt` (required, non-empty);
  `LlmRoles.extraction` retyped.
- `config.yaml` — the two prompt templates as the committed default, grounding
  rules folded in verbatim (no more `{rules}` indirection).
- `server/meetingminer/pipeline/extraction.py` — `build_summary_prompt` /
  `build_actions_prompt` / `build_prompt` take a required `template=`;
  `_GROUNDING_RULES`/`_SUMMARY_PROMPT`/`_ACTIONS_PROMPT` constants deleted.
- `server/meetingminer/pipeline/stages/extract.py` — selects the per-document
  config field, computes `prompt_hash` on the generate branch only, threads
  it into `provenance` and `extraction_source`.
- `server/meetingminer/migrations/0012_extraction_prompt_hash.sql` — new
  nullable `extraction_source.prompt_hash` column.
- `server/meetingminer/api/extraction.py` (new) — `GET /extraction/prompts`,
  auto-discovered per story 2.8.
- `web/src/features/moments/MomentView.tsx`, `moments.ts` — the "Active
  extraction prompts" right-rail section and its label/timeout helpers.
- `web/src/client/*.gen.ts` — regenerated via `make client`.
- Tests: `server/tests/test_config.py`, `test_extraction_core.py`,
  `test_worker_extract.py`, `test_api_registry.py`, new
  `test_api_prompts.py`; `web/src/features/moments/MomentView.test.tsx`.

**Review findings breakdown:** 2 patched (high 0, medium 0, low 2 — both
applied and re-verified), 3 deferred to frontmatter `deferred`, 14 rejected
as noise, established codebase convention, or already resolved by the epic
context / spec's own design notes (see the Review Triage Log entry above for
the full breakdown).

**Follow-up review recommendation:** `false`. Counting only this pass's
`patch` findings: high 0, medium 0, low 2; score = 3×0 + 1×2 = 2, below the
threshold of 5.

**Verification performed (post-patch, re-run independently):**
- `cd server && uv run pytest tests/test_worker_extract.py tests/test_extraction_core.py tests/test_config.py tests/test_api_prompts.py tests/test_api_registry.py -q` -> 192 passed.
- `cd server && uv run pytest tests/ -q` -> 1511 passed, 0 failed (0:06:51).
- `make web-test` -> 189 passed (11 files).
- `rg -n 'import litellm|from litellm' server/meetingminer --glob '!**/adapters/llm/**'` -> no matches (exit 1).
- `make client` (during implementation) -> api started transiently, `/openapi.json` served, `getExtractionPrompts` generated; api shut down cleanly afterward.
- No model call of any kind was made: the worker was not started and
  `make evals-run` was not run.

**Matrix Test Audit:** every I/O & Edge-Case Matrix row is covered by a test
that ran and passed above — config prompt edited
(`test_a_different_configured_prompt_changes_the_hash_not_the_prompt_version`,
now symmetric across both documents), missing prompt key
(`test_missing_extraction_prompt_key_is_fatal`), UI reads active prompts
(`test_extraction_prompts_returns_both_kinds_verbatim`), adopted document
(`test_adopting_both_documents_makes_no_model_call_and_records_both_sources`),
generated document
(`test_generating_both_documents_makes_one_call_per_document_kind`).

**Residual risks and follow-ups:** the three deferred items above (historical
`prompt_hash` text is not automatically recoverable from git history;
`MomentView` refetches prompts on every mount with no cache; a persistent
prompts-fetch failure is silent with no operator-facing signal). None block
this story's acceptance criteria.
