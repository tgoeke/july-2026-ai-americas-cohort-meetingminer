# Story 8.1 Review — AD-10 Amendment and Binding Catalog

## Scope

Adversarial review of Story 8.1 on `story/8-1-review`, including the eight changed paths named in the review handoff, the frozen intent contract, planner-owned design decisions, architecture decisions AD-10 and AD-8, and post-review fixes that are patchable without an owner or frozen-spec decision.

## Range

- Original story range: `82f864b51d210920ab07770720c2d81bde200355..story/8-1`
- Final rebased implementation range reviewed: `f92cb9c..8f2c4ff`
- Final integration base: `f92cb9c` (`origin/main`, Story 6.3 landed)
- Review commits begin at: `3ace393`
- Review branch: `story/8-1-review`

## Findings

### Finding 1 — Synthesized prefixed entries discard required provider metadata (patch)

- **Location:** `server/meetingminer/config.py:314-354`; `server/tests/test_config_catalog.py:72-88`
- **Severity:** High
- **Finding:** A legacy role whose `model` has a `<provider>/` prefix is synthesized with `provider: None`. This contradicts the frozen I/O matrix, which requires `model: openai/gpt-5.2` to produce a one-entry catalog whose provider is `openai`.
- **Evidence:** `_catalog_from_model` creates `{"binding": tag, "label": tag}` without deriving the prefix, and `test_legacy_prefixed_model_becomes_a_one_entry_catalog` explicitly asserts `entry.provider is None`. Backward compatibility requires a synthesized entry to bypass the new undeclared-provider refusal; it does not require throwing away derivable provider metadata. The current representation also leaves a legacy prefixed entry without the provider identity later catalog and health consumers need.
- **Suggested direction:** Preserve an explicit internal authored/synthesized distinction. Derive the provider for a synthesized prefixed binding as the frozen matrix requires, but skip the catalog×providers refusal for entries marked synthesized so pre-catalog files with undeclared prefixes still load.

### Finding 2 — The active `model` can sit outside its allowed catalog (patch)

- **Location:** `server/meetingminer/config.py:397-419`
- **Severity:** High
- **Finding:** An authored role can declare `catalog: [a, b]`, `default: a`, and `model: z`; the file loads while `z` remains the binding every current call path uses. The system therefore runs a binding outside the catalog AD-10 calls allowed.
- **Evidence:** `_default_is_a_catalog_binding` validates only `default in catalog` and then leaves `model` untouched. The frozen intent says the catalog contains bindings the role may be served by and simultaneously says `model` remains the active field until Story 8.2. This is not an 8.2 selection question: before 8.2, the active binding must still be inside the boundary the new catalog declares. Legacy roles remain compatible because their synthesized one-entry catalog already contains their model.
- **Suggested direction:** Refuse an authored catalog whose active `model` is absent, with a named error listing the catalog bindings. Keep synthesized legacy roles exempt from any new spelling/normalization rule beyond their existing one-entry projection.

### Finding 3 — The shipped config still makes two stale Anthropic claims (patch)

- **Location:** `config.yaml:195-202`
- **Severity:** High
- **Finding:** AC clause 3 remains unmet: the committed chat comment says the Anthropic key was deliberately invalidated and that `claude-sonnet-5` is AD-10's superseded default, although the key was restored and the catalog amendment replaced that history.
- **Evidence:** Both statements remain verbatim after rebasing onto the main that contains Story 10.1, so the former line-overlap blocker is gone. The surrounding rules are still true: OpenAI remains the owner-selected chat model, chat has no runtime fallback, and `_BARE_OPENAI_PREFIXES` does not include `gpt-5`, so the `openai/` prefix is still required for configured endpoint resolution.
- **Suggested direction:** Delete only the invalidated-key and superseded-default claims. Preserve the current OpenAI choice, no-fallback rule, and `openai/` prefix rationale.

### Finding 4 — A bare binding can declare one provider and route to another (closed — owner ruling implemented)

- **Location:** `server/meetingminer/config.py:215-237,356-395`; `server/meetingminer/adapters/llm/litellm.py:54-75`
- **Severity:** High
- **Finding:** An authored prefix-less binding may explicitly declare any configured provider, but the runtime independently routes recognized bare spellings. The catalog can therefore promise one endpoint and call another.
- **Evidence:** Before the fix, a real `Settings` validation of `model: gpt-4o`, catalog entry `{binding: gpt-4o, provider: ollama}`, and `default: gpt-4o` succeeded while `resolve_api_base('gpt-4o', providers)` selected OpenAI. The red regression reproduced that acceptance. `provider_for_model` now lives in `domain/model_providers.py`; `CatalogEntry.provider`, `resolve_api_base`, and `status.provider_of` all consume that function. The same regression now refuses `provider` as extra input, known bare `gpt-4o` and `claude-*` derive OpenAI and Anthropic consistently, and `some-model` refuses as ambiguous.
- **Suggested direction:** Implemented in commit `1271686`: provider identity is derived output from the one shared rule; authored `provider` input and ambiguous bare spellings are named load failures.

### Finding 5 — AD-10 omits the owner-approved selection half of the amendment (patch)

- **Location:** `docs/architecture.md:119-133`
- **Severity:** Medium
- **Finding:** AD-10 records the catalog/default declarations and load-time refusals, but omits the accepted rules that a selection is user-declared Postgres data, is resolved at call time by API and worker, is recorded beside file values in eval snapshots, cannot name anything outside the catalog, and is never a fallback.
- **Evidence:** The owner-approved wording in `_bmad-output/planning-artifacts/sprint-change-proposal-2026-08-29.md` §2 contains all of those clauses, and `epics.md` repeats them as the Epic 8 architecture amendment. The current Design Notes deferred them to 8.2 because code does not implement them yet. AD-10 is the normative decision 8.2 builds from, not an implementation-status report; leaving half out removes the constraints the downstream story is supposed to satisfy.
- **Suggested direction:** Complete AD-10 with the approved selection, resolution, snapshot, catalog-boundary, and no-fallback sentences while preserving Story 11.2's private-stack environment wording verbatim in the same paragraph.

### Finding 6 — Epic 8 context says the new provider validation does not exist (patch)

- **Location:** `_bmad-output/implementation-artifacts/epic-8-context.md:32`
- **Severity:** Medium
- **Finding:** The generated Epic 8 context lists “bindings are not validated against declared providers” as a known gap, contradicting Story 8.1's primary authored-catalog validation and the technical-decision bullets immediately above it.
- **Evidence:** `Settings._catalog_providers_are_declared` refuses every authored catalog entry whose resolved provider is absent from `providers:`, and the story tests cover explicit and derived undeclared providers. Story 8.2 is named as a consumer of this context; stale guidance could make it duplicate or bypass the existing contract. The narrower residual gaps are synthesized legacy entries and the live `fallback`, not authored catalog entries generally.
- **Suggested direction:** Replace the broad false statement with the actual residual boundary: authored catalog entries are checked, while synthesized compatibility entries and `fallback` remain exempt pending later decisions.

### Finding 7 — Story records disagree with the catalog test module (patch)

- **Location:** `_bmad-output/implementation-artifacts/sprint-notes.md:3051`; `_bmad-output/implementation-artifacts/spec-8-1-ad-10-amendment-and-binding-catalog.md:369`
- **Severity:** Low
- **Finding:** The sprint note says the new module has ten tests, while the spec auto-result says twelve; the reviewed module now contains thirteen after the active-model regression was added.
- **Evidence:** `rg '^def test_' server/tests/test_config_catalog.py | wc -l` returns 13. The conflicting prose makes the verification record unreliable and obscures whether the matrix plus review regressions are actually present.
- **Suggested direction:** Update both records to the observed count and describe the module as matrix coverage plus committed-config and review regressions, avoiding a brittle one-per-row claim.

### Finding 8 — The rebased fast gate has two environment-gated skips (defer — current main/environment)

- **Location:** `server/tests/test_diarize_pyannote.py:266`; `server/tests/test_youtube.py:1353`
- **Severity:** Low
- **Finding:** The review handoff's zero-skip baseline no longer reproduces after rebasing onto current main: `make test-fast` skips the optional pyannote import case and the explicitly opt-in real YouTube network acquisition case.
- **Evidence:** The final post-rebase fast server run reported 1,893 passed, 2 skipped, and 378 deselected. The named reasons were `No module named 'pyannote'` and `set MM_YOUTUBE_NETWORK_TEST=1 to run it`. Both tests landed on main after the original Story 8.1 baseline and neither is reached by the catalog change.
- **Suggested direction:** No Story 8.1 patch. Treat the fast result as qualified by these two intentional current-main environment gates; use the dedicated diarize-extra gate when validating pyannote and the explicit environment flag only when a real network acquisition run is intended.

### Finding 9 — A missing model loses its endpoint identity and may engage fallback (defer — filed as B-38)

- **Location:** `server/meetingminer/adapters/llm/litellm.py:155-179`; `server/meetingminer/adapters/llm/__init__.py:66-91`
- **Severity:** High
- **Finding:** A provider response saying the configured model does not exist falls through the adapter's generic SDK-error mapping. The resulting `LlmError` names the model but not the endpoint or provider actually called, and `FallbackLlm` catches every `LlmError`, so the configuration mistake can silently answer from a different model.
- **Evidence:** `LiteLlmCompleter.complete` maps connection, timeout, service, rate-limit, authentication, and permission errors to `LlmUnavailableError` with `model` and `api_base`. Every other SDK exception, including LiteLLM's installed `NotFoundError`/`BadRequestError` missing-model shapes, becomes `LlmError("model ... failed")` without `api_base`. `FallbackLlm.complete` catches the base `LlmError` and engages its configured fallback; the existing test `test_a_plain_llm_error_from_the_primary_also_engages_the_fallback` pins that broad behavior. This confirms the owner-provided operating risk.
- **Suggested direction:** This changes call-time adapter and fallback semantics, while Story 8.1's frozen boundary says it changes no call path and names `litellm.py` read-only. File B-38 with the exact required failure template `provider {provider!r} at {api_base!r} does not serve model {model!r}`; map model-not-found to its own configuration-shaped port error; exclude that error from fallback; and retain `LlmUnavailableError` fallback for genuine outages.

### Finding 10 — Legacy synthesis normalizes the catalog but not the active model (closed — patch)

- **Location:** `server/meetingminer/config.py:327-350`; `server/meetingminer/domain/model_providers.py:17-27`
- **Severity:** High
- **Finding:** For a legacy role with outer whitespace around `model`, catalog synthesis strips the spelling before deriving provider metadata, but `LlmRoleBinding.model` retains the original string that runtime routing consumes. The catalog/status identity can therefore disagree with the actual call despite using the same resolver function.
- **Evidence:** Before the fix, `_catalog_from_model` computed `tag = model.strip()` for `CatalogEntry` while the validated `model: str` field retained whitespace. The red regression failed with `'  gpt-4o  ' != 'gpt-4o'`. `LlmRoleBinding.model` now uses `NonEmptyText`; the stored model, synthesized binding, derived provider, and `resolve_api_base` endpoint all agree.
- **Suggested direction:** Implemented in commit `af1672b`; the focused regression and full catalog/config set pass.

### Finding 11 — Known-bare agreement is not observed at the status consumer (patch — verification gap)

- **Location:** `server/meetingminer/api/status.py:128-134`; `server/tests/test_config_catalog.py:150-167`; `server/tests/test_api_status.py`
- **Severity:** Medium
- **Finding:** The owner contract requires config, runtime, and displayed status to use one provider rule. The regression asserts config metadata against `resolve_api_base`, but no normal test observes the status consumer for bare OpenAI/Anthropic spellings.
- **Evidence:** Repository-wide symbol tracing shows `status.provider_of` aliases `provider_for_model`, and `/config` imports that alias, so adoption is correct today. `test_known_bare_catalog_provider_matches_runtime_routing` checks catalog and adapter only; searches for `gpt-4o` and `claude-sonnet-5` in `test_api_status.py` return no cases. Replacing the status alias with a divergent bare-name rule could therefore leave the owner regression green.
- **Suggested direction:** Extend the existing known-bare parametrized regression to assert `status.provider_of(model) == provider`, pinning config, runtime, and display in one case matrix.

### Finding 12 — Eval bake-off fixtures use newly ambiguous bare bindings (patch)

- **Location:** `evals/tests/test_bakeoff.py:459,524`
- **Severity:** Medium
- **Finding:** Two store-free eval tests construct `LlmRoleBinding` with fake bare model names whose provider cannot be determined under the owner-amended contract, so `make test-fast` fails before exercising the behavior those tests target.
- **Evidence:** The first foreground `make test-fast` run passed lint, typecheck, puller, and web, then failed `test_run_bakeoff_excludes_a_candidate_that_fails_after_its_probe` on `model="x"` and `test_run_bakeoff_breaks_an_agreement_tie_by_consistency_end_to_end` on `model="flaky-model"`; both raise the new named ambiguous-routing validation error. The remaining eval suite reported 641 passed.
- **Suggested direction:** Give the synthetic bindings an explicit `test/` provider prefix so the fixtures remain unmistakably fake and unambiguous without changing the bake-off behavior under test. Rerun the eval suite, then restart `make test-fast` from the beginning.

## Review-layer and triage summary

All four configured layers ran locally and sequentially: Blind Hunter, Edge
Case Hunter, Verification Gap Reviewer, and Acceptance Auditor. The original
eight findings plus owner follow-ups 9 and 10 are now triaged: eight patch
findings are fixed, one low-severity current-main/environment
qualification is deferred, and the out-of-scope call-time defect is filed as
B-38. No review layer failed.

The original deferred inventory was reassessed rather than duplicated:

- The stale chat comment and active-model boundary were wrongly deferred; they
  became Findings 3 and 2 and are fixed.
- Provider-rule drift was more serious than recorded; the concrete bare-tag
  mismatch became open Finding 4.
- The live `fallback` exemption remains a medium owner/Story 8.2 boundary.
- API visibility remains correctly owned by Story 8.2.
- Resolved-config dump round-tripping remains a low, currently unconsumed gap.
- Duplicate bindings, first-error-only reporting, `catalog: null`, and the
  blank-model diagnostic remain low and outside the frozen acceptance surface.

## Red-first remediation evidence

- Finding 1: the legacy-prefixed regression failed with `None == 'openai'` on
  the unfixed loader, then passed with derived provider metadata and an explicit
  synthesized marker; legacy undeclared-prefix and bare-tag cases also passed.
- Finding 2: the active-model regression failed because no `ConfigError` was
  raised, then passed after the authored-catalog membership check was added.
- Finding 3: a source assertion failed while both stale Anthropic claims were
  present, then passed after their removal and preservation of the three live
  chat rules.
- Finding 5: an AD-10 contract assertion failed on the missing selection,
  resolution, and no-fallback clauses, then passed after the accepted wording
  was united with Story 11.2's infrastructure sentence.
- Findings 6 and 7: source assertions failed on the stale provider-validation
  claim and mismatched test counts, then passed after their records were
  corrected.
- Finding 4 owner remediation: six focused cases failed on the unfixed branch —
  the misleading authored provider was accepted, ambiguous legacy bare input
  was accepted, authored known-bare inputs were refused, and synthesized
  known-bare entries carried no provider. All six passed after the shared
  resolver and computed provider landed; the full catalog/adapter/status set
  then passed 136 tests.
- Finding 10: a spaced legacy model regression failed because catalog synthesis
  normalized `gpt-4o` while the active model retained whitespace; it passed
  after `model` adopted `NonEmptyText`, and the catalog/config set passed 139.

## Final verification

All final gates ran after rebasing onto `origin/main` at `f92cb9c`:

- `uv sync --project server` — clean.
- `make lint` — clean.
- `make typecheck` — no issues in 13 source files.
- `make test-fast` — puller 128 passed; web 294 passed; evals 643 passed;
  server 1,893 passed, 2 skipped, 378 deselected. Both skips are Finding 8.
- `make test` — puller 128 passed; web 294 passed; evals 643 passed; isolated
  diarize-extra gate 92 passed; test-store reachability 1 passed; server 2,271
  passed and the same 2 tests skipped; production web build clean.
- Targeted pre-rebase remediation suites also passed: config/catalog 134 and
  fail-fast 12. The final fast and full gates reran those modules after rebase.

## Verdict

**Pending final gates.** Finding 4 is closed under the owner's frozen-spec
amendment. Finding 9 is verified but intentionally outside Story 8.1's
no-call-path boundary and is filed as B-38. The final verdict will be recorded
after lint, typecheck, fast/full tests, and `make check-reviews`. This review
does not merge or commit to `main`.
