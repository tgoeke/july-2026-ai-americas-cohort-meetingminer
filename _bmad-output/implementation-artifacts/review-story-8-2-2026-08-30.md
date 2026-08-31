# Code Review — Story 8.2: Persisted Selection

## Scope

Adversarial review of Story 8.2 implementation and its stated footprint against the frozen intent contract, architecture decisions, acceptance criteria, and regression expectations supplied in the reviewer handoff.

## Review range

- Baseline: `ea0c113`
- Story branch: `story/8-2` at `2e5ba83`
- Review branch: `story/8-2-review`
- Range: `ea0c113..story/8-2`
- Review date: 2026-08-30

## Findings

### Finding 1 — `judge` selections are persisted and reported as effective but never used (resolved by owner ruling)

- **Location** — `evals/harness/judge.py:499`
- **Severity** — medium
- **Finding** — `GET /settings/models` and `PUT /settings/roles/{role}` include every declared role, including `judge`, and label the stored `judge` choice as `effectiveBinding`. The only production judge call path still binds `config.settings.llm.roles.judge` directly, so a successful `PUT /settings/roles/judge` has no effect on the model that judges a run. The snapshot can therefore call a persisted judge choice “effective” while `llm-judge-report.yaml` and the actual calls use the file binding. This is **open** because the frozen intent contract names call-time adoption only for chat and extraction and the required correction reaches `evals/harness/judge.py`, outside the story footprint; resolving it requires an owner/spec decision.
- **Evidence** — `rg -n "roles\\.judge|build_llm\\(" evals server/meetingminer -g '*.py'` found the judge call at `evals/harness/judge.py:499-500`, which assigns the file role and passes it directly to `build_llm`. `server/meetingminer/api/settings.py:97-104` derives the settings surface from every `LlmRoles.model_fields` entry, and `:123-145` labels any stored choice as the effective binding. `evals/tests/test_run_judge.py` replaces `build_llm` but never asserts which binding was passed, so the non-adoption is not detected.
- **Suggested direction** — Decide whether persisted selection governs the manual eval judge. If it does, amend the frozen contract and footprint so the judge reads the public settings response and applies that returned binding at call time without importing server-owned selection logic. If it does not, stop accepting/reporting a `judge` selection as effective and define clearly what the catalog entry means.
- **Owner ruling and resolution (2026-08-30)** — Judge is file-only today. The settings surface now derives its roles through an exhaustive policy that excludes judge, `PUT /settings/roles/judge` returns the named `role-file-only` refusal, and no settings payload can report a judge `effectiveBinding`. A paired eval regression asserts that `run_judge` still passes the file role to `build_llm`. Follow-up B-41 owns adopting persisted selection in the harness. Implemented in `30266a6` after rebase.

### Finding 2 — the model-not-served error still trusts LiteLLM's provider spelling

- **Location** — `server/meetingminer/adapters/llm/litellm.py:163`
- **Severity** — medium
- **Finding** — the new mapping falls back to `NotFoundError.llm_provider` when `provider_for_model()` returns `None`. That contradicts the frozen one-rule invariant that provider identity comes from `domain.model_providers.provider_for_model` “and nothing else,” and it makes an SDK guess authoritative precisely on the ambiguous spelling the shared rule refuses to guess.
- **Evidence** — reading `LiteLlmCompleter.complete` shows `provider_for_model(self.model) or getattr(exc, "llm_provider", None) or "unknown"`. `test_the_refusal_names_the_provider_the_shared_spelling_rule_derives` proves a recognized binding wins over a conflicting SDK value, but no test covers the `None` branch; constructing a LiteLLM `NotFoundError` confirms `llm_provider` is populated and therefore would be used.
- **Suggested direction** — derive the provider only through `provider_for_model`; if that rule cannot identify it, report a non-authoritative sentinel such as `unknown` rather than promoting SDK metadata. Add a regression where an ambiguous model and an SDK-supplied provider disagree.

### Finding 3 — the new chat 502 is absent from the API contract

- **Location** — `server/meetingminer/api/chat.py:1343`
- **Severity** — medium
- **Finding** — chat now emits `502 urn:meetingminer:problem:binding-failed`, but the route's declared OpenAPI responses still contain only 200, 422, and 503. The regenerated client therefore has no 502 member in `AskCorpusErrors`, so the story's new failure contract is invisible to generated consumers even though it exists at runtime.
- **Evidence** — `app.openapi()["paths"]["/chat"]["post"]["responses"]` returned only `200`, `422`, and `503`; `web/src/client/types.gen.ts:2332-2341` likewise defines only 422 and 503 errors. The on-wire test checks the problem type and fields but does not assert `response.status_code == 502` or inspect OpenAPI.
- **Suggested direction** — declare the 502 `ProblemDetails` response with `application/problem+json`, pin both the runtime status and schema entry in tests, then regenerate the committed client from the schema.

### Finding 4 — the selection route's named refusals are absent or mis-typed in OpenAPI

- **Location** — `server/meetingminer/api/settings.py:168`
- **Severity** — medium
- **Finding** — `PUT /settings/roles/{role}` emits a named 404 `unknown-role` and a named 422 `binding-not-in-catalog`, both as `ProblemDetails`, but the route declares neither. FastAPI consequently documents no 404 and documents 422 only as its default `HTTPValidationError`; the regenerated client's `SelectRoleBindingErrors` omits the unknown-role case and gives the catalog refusal the wrong body type.
- **Evidence** — `app.openapi()["paths"]["/settings/roles/{role}"]["put"]["responses"]` returned only 200 and the default validation 422. `web/src/client/types.gen.ts:2608-2613` contains only `422: HttpValidationError`, while `server/tests/test_api_settings.py:174-201` proves the actual responses are RFC 9457 problem documents with story-specific slugs.
- **Suggested direction** — explicitly declare 404 and 422 problem responses on the route, preserve the custom validation handler's same `ProblemDetails` wire shape, add schema assertions, and regenerate the client.

### Finding 5 — the API-level non-mutation assertion is tautological

- **Location** — `server/tests/test_api_settings.py:323`
- **Severity** — low
- **Finding** — `test_a_selection_never_mutates_the_configured_role` compares `_roles(app_config).chat.model` to itself, so the assertion passes even if selection resolution mutates the process-wide configured model. The identity assertion beside it only proves the object handed to `build_llm` is distinct; it does not prove the configured object's value stayed unchanged.
- **Evidence** — the test line is `assert _roles(app_config).chat.model == _roles(app_config).chat.model`. A repository-wide symbol/import search found the pure-domain test does correctly pin non-mutation, but this API-level test's stated per-request invariant is not independently observed at its boundary.
- **Suggested direction** — capture the configured model before the `PUT`/chat request and compare that saved value with the configured model afterward; mutation-test the assertion against a deliberately mutating resolver before restoring the production code.

### Finding 6 — settings reads do not emit the required stale-selection event

- **Location** — `server/meetingminer/api/settings.py:123`
- **Severity** — medium
- **Finding** — `_view()` resolves a stale stored choice with `model_selection.resolve()` and serializes `staleSelection`/`staleReason`, but it never logs `llm.selection_stale`. The frozen contract and Design Notes require the discard both in `GET /settings/models` and in a log event, with the latter emitted on every resolution. Chat and extraction use `resolve_role(..., log=...)`; the settings surface bypasses that logging path. A stale `judge` selection is especially silent because no judge call path resolves it.
- **Evidence** — tracing `GET /settings/models` shows `read_selections()` followed by `_view()` and `model_selection.resolve()`; no `logs.log_event` call occurs. `rg -n "llm.selection_stale" server/meetingminer server/tests` found the only production emission inside `model_selection.resolve_role`, plus a worker/chat-oriented test, while `test_a_stored_selection_the_catalog_dropped_is_reported_not_applied` asserts only the payload.
- **Suggested direction** — make the API view path emit the same structured event when its `EffectiveBinding` is stale, using one shared logging helper or an optional log callback so the event shape does not fork. Add a GET-level regression that captures the event.

### Finding 7 — catalog membership is implemented twice instead of by one shared decision

- **Location** — `server/meetingminer/domain/model_selection.py:149`
- **Severity** — medium
- **Finding** — `check_selectable()` implements write-time membership with `if binding not in offered`, while `resolve()` independently implements read-time membership with `if selected not in offered` at line 177. They share `catalog_bindings()`, but the membership decision itself is duplicated. This violates the frozen “one function used by both the write path and the read path” rule and leaves the two refusal boundaries free to drift when membership semantics change.
- **Evidence** — direct branch tracing of both functions shows separate membership conditionals and no shared predicate/call. Existing tests exercise the two outcomes independently, so both remain green if one side later adds normalization or another membership rule without the other.
- **Suggested direction** — introduce one dependency-free membership predicate (or make both paths call the same checker) and pin that both write-time refusal and read-time stale detection route through it.

### Finding 8 — a valid catalog binding can be too long for the selection API

- **Location** — `server/meetingminer/api/settings.py:42`
- **Severity** — medium
- **Finding** — the request-only `SelectedBinding` type caps a model tag at 200 characters, while `config.CatalogEntry.binding` uses `NonEmptyText` with no maximum. The API can therefore serve a valid catalog entry from `GET /settings/models` and then reject that exact entry as an invalid request before the shared catalog membership rule runs, violating the promise that any catalog binding can be persisted.
- **Evidence** — `server/meetingminer/config.py:169` defines `NonEmptyText` with only stripping and `min_length=1`; `CatalogEntry.binding` uses it at line 238. The PUT body independently adds `max_length=200`, and existing tests cover blank and out-of-catalog values but no catalog entry beyond that boundary.
- **Suggested direction** — make the writable value domain identical to the catalog value domain (preferably by removing the independent request cap and letting catalog membership bound accepted values), then add a route-level regression using a valid catalog entry longer than 200 characters.

### Finding 9 — the settings wire uses `fileModel` instead of the frozen `fileBinding`

- **Location** — `server/meetingminer/api/settings.py:71`
- **Severity** — medium
- **Finding** — the frozen I/O matrix requires each settings role to expose `fileBinding`, but `RoleSelectionView` defines `file_model`, serialized as `fileModel`. The eval adapter and generated client have adopted the same non-contract name, so the implementation is internally consistent but externally inconsistent with the preservation-locked wire.
- **Evidence** — `_bmad-output/implementation-artifacts/spec-8-2-persisted-selection.md:119` names `fileBinding`. `app.openapi()` and `web/src/client/types.gen.ts` expose `fileModel`; `evals/harness/run.py:280` reads `row.get("fileModel")`; the API and eval tests assert that spelling rather than the frozen one.
- **Suggested direction** — rename the response field to `fileBinding`, update the eval snapshot adapter and fixtures to consume it, add a negative/positive wire assertion, and regenerate the client.

### Finding 10 — the new problem extensions leak snake_case onto a camelCase API

- **Location** — `server/meetingminer/api/chat.py:1082`
- **Severity** — medium
- **Finding** — `binding-failed` passes `config_path` and `upstream_status` into `Problem`. Problem extensions are copied verbatim; unlike Pydantic response models, no alias generator converts them. The runtime body therefore exposes snake_case keys, contradicting the API's established camelCase extension convention and the story's Design Note promising `configPath`.
- **Evidence** — `api/problems.py:83-90` updates the JSON body directly from `extensions`. The new chat branch supplies snake_case names. Existing problem code explicitly documents camelCase extensions, while `test_a_binding_the_provider_does_not_serve_surfaces_as_binding_failed` asserts provider/binding/role and status text but never inspects either extension key.
- **Suggested direction** — emit `configPath` and `upstreamStatus` explicitly, assert the camelCase keys and absence of their snake_case variants on the real response, and keep the upstream status in `detail` as the frozen matrix requires.

### Finding 11 — B-38 still cannot name the endpoint for a valid legacy binding (resolved by owner ruling)

- **Location** — `server/meetingminer/adapters/llm/litellm.py:170`
- **Severity** — medium
- **Finding** — when no configured provider or role endpoint resolves, the model-not-served error says only `"the provider's default endpoint"` and carries `api_base=None`. That is readable but it is not the endpoint URL the B-38 contract says must be named. This path is reachable for a valid legacy role: story 8.1 deliberately lets a synthesized prefixed catalog load without a matching `providers:` entry. The story therefore closes silent substitution but does not fully close B-38's actionable-endpoint requirement. This is **open** because obtaining an authoritative URL would require changing the frozen legacy-config rule or defining a new source of provider endpoint truth; guessing from LiteLLM would conflict with AD-10.
- **Evidence** — `config.py:323-335` explicitly exempts synthesized legacy entries and says an unmatched prefix gets no configured `api_base`. `LiteLlmCompleter` substitutes the prose label at line 170 and sets the exception field from `self.api_base` (still `None`) at line 180. `test_the_refusal_is_still_readable_with_no_configured_endpoint` asserts only that the message omits the word `None`, not that it contains a URL.
- **Suggested direction** — owner must choose between requiring an explicit endpoint for every callable binding (including legacy projections), weakening B-38's URL requirement for SDK-default routing, or introducing an architecture-approved provider-default endpoint source. Do not infer the URL from the SDK's provider label ad hoc.
- **Owner ruling and resolution (2026-08-30)** — Config now refuses every catalog binding whose derived provider prefix lacks a `providers:` endpoint, including synthesized legacy entries. The named load error gives the binding, provider prefix, missing endpoint, and exact `providers.<prefix>.base_url` remedy. The former legacy exemption is intentionally compatibility-breaking and is recorded in the spec change log. Implemented in `f4108e1` after rebase.

## Remediation

The review lane applied every unambiguous patch red-first and committed each with its finding number:

| Finding | Result | Commit |
|---|---|---|
| 1 | Fixed by owner ruling — judge is explicitly file-only and absent from the selection surface | `30266a6` |
| 2 | Fixed — SDK provider metadata is no longer authoritative | `9d53b39` |
| 3 | Fixed — chat 502 is declared, tested, and present in the regenerated client | `37470e1` |
| 4 | Fixed — selection 404/422 problems are declared and typed in the regenerated client | `5b7c97d` |
| 5 | Fixed — the API-level immutability assertion now compares against the pre-request value | `c351669` |
| 6 | Fixed — settings reads emit the shared stale-selection event shape | `35f7426` |
| 7 | Fixed — write and read call one catalog-membership predicate | `4a6be32` |
| 8 | Fixed — PUT accepts the same non-empty binding domain the catalog permits | `331340a` |
| 9 | Fixed — the frozen `fileBinding` wire name is restored end-to-end | `3986e02` |
| 10 | Fixed — problem extensions emit `configPath` and `upstreamStatus` | `2d1756e` |
| 11 | Fixed by owner ruling — endpoint-less catalog bindings fail at config load | `f4108e1` |

Red evidence was observed for every patch. Finding 5 is a verification-only defect, so its corrected assertion was mutation-tested against a temporary resolver that mutated the process-wide role: the corrected test failed, the temporary mutation was restored, and the test passed against production code. No temporary mutation was committed.

## Design-decision rulings

- **Stale selection → file default:** accepted for this story. The operator's catalog edit withdraws the stored choice before call time, the frozen contract explicitly selects the declared default, and the effective/stale split is visible. Finding 6 repaired the missing settings-read event, so the discard is now reported on the API read as well as chat/worker resolution. This is distinct from answering a call-time model-not-found with a substitute.
- **502 for `binding-failed`:** accepted. The host answered and retrying the same binding cannot repair it. The web chat path treats any non-422 problem as the server's named problem, and eval HTTP clients already treat any non-2xx as a failure. Finding 3 repaired the missing OpenAPI declaration.
- **`binding` means model tag:** accepted as problem-type-specific vocabulary because `configPath` separately anchors the configuration location. Finding 10 repaired that companion field's actual wire spelling. The two existing 503 slugs keep their established `binding="llm.roles.chat"` contract.
- **Role `base_url` carries into a selected model:** accepted within the frozen role semantics. It preserves the role endpoint rather than silently rerouting through the provider map; an endpoint that does not serve the selected tag now refuses by name. The Finding 11 owner ruling closes the legacy gap by refusing a binding whose provider endpoint is not explicitly configured.
- **Fallback remains outside the catalog:** no new finding; it is explicitly deferred in the spec and out of this review's patch scope.
- **Generic `app_setting` table:** accepted. API writes are catalog-validated, every read revalidates against the current catalog, scalar/nonblank checks protect the stored shape, and production search confirmed only `api/settings.py` writes it.
- **Eval reads effective bindings over HTTP and continues when unavailable:** accepted as the frozen AD-16/client behavior. The snapshot records an explicit problem and never guesses the file binding; changing verdict validity belongs to an owner/spec decision beyond this story.
- **Chat reuses its no-evidence connection:** accepted. The added indexed lookup occurs inside the existing short connection context, which closes before either model call or retrieval, so it adds no long-lived pool hold and resolves once per request.

The three footprint extensions were forced: router order is pinned by `BASELINE_ROUTER_ORDER`; the LiteLLM stub must expose every lazily referenced exception class; and the harness network-import guard must list `run.py` once it calls the public settings endpoint. The LiteLLM `.env` containment also passed with the real SDK import executed before the two named config-precedence tests; the deferred item accurately records that the repository-wide guard still belongs in `server/tests/conftest.py`.

B-38's primary ordering is correct after remediation: `NotFoundError` maps before the outage/generic clauses, `FallbackLlm` re-raises `LlmModelNotServedError` before its substituting `except LlmError`, and the provider now comes only from `provider_for_model`. No selected-primary model-not-served path reached the fallback in the inspected callers or tests. AD-4, AD-6, and AD-15 remain intact: the chat edit occurs before retrieval/synthesis and does not change projection writers, citation minting, marker parsing, or the final citation gate.

## Verification

- `uv run --project server pytest server/tests/test_settings_resolution.py server/tests/test_api_settings.py -q` — **33 passed**.
- `uv run --project server pytest server/tests/test_worker_extract.py server/tests/test_api_chat.py -q` — **23 passed, 55 deselected**.
- Real LiteLLM import followed by the two named config-precedence tests — **3 passed**; the SDK did not leak `.env` state across the fixture boundary.
- `uv run --project server pytest evals/tests -q` — **655 passed**.
- `make lint` — **All checks passed**.
- `make typecheck` — **Success: no issues found in 13 source files**.
- `make web-test` — **294 passed in 16 files**.
- `make test-fast` — **1995 passed, 2 expected skips, 378 deselected**.
- `make test` — optional diarizer lane **92 passed**; full server gate **2373 passed, 2 expected skips** in 609.66s; production web build passed. The two skips are the named pyannote/default-environment case and opt-in YouTube network case.
- `python3 _bmad/scripts/branch_conflicts.py --against story/8-2` — `story/8-2 × story/8-2-review` is **clean**. The command also reproduced only the already-characterized `sprint-notes.md` conflicts and the `story/7-3` generated-client conflict.
- `make check-reviews` — **every dispatched review has a committed report**.

## Owner-ruling closeout

- Both owner regressions were red against the unfixed code: the settings API
  returned `judge`, and a synthesized `moonshot/kimi-k2` binding loaded with no
  `providers.moonshot` endpoint. The paired judge-harness assertion passed and
  pins that `run_judge` still calls `build_llm` with the file role.
- Focused post-fix verification passed: **52 server tests** across catalog,
  selection, settings, and fail-fast behavior; **20 eval tests** across judge
  and effective-binding snapshots; lint, typecheck, and client drift checks.
- The branch rebased successfully onto `origin/main` at `c678837`. The sole
  conflict was the characterized `sprint-notes.md` append and was resolved as
  a union; migration `0015_threads.sql` and `0016_app_setting.sql` coexist and
  passed the migration suite.
- The first post-rebase full gate exposed one test-fixture regression after
  **2,509 passed / 3 skipped**: the embedder fail-fast fixture no longer made
  only the embedder unroutable under the new catalog invariant. The corrected
  fixture explicitly rebinds all LLM catalogs to declared OpenAI before
  removing `providers.ollama`; its slow test passed with `-m ""` and the fix is
  committed as `0da468a`.
- The complete gate was then rerun from the beginning and passed: puller
  **128**, web **294**, evals **655**, isolated diarization/STT **92**, server
  **2,510 passed / 3 expected skips** in 662.17 seconds, followed by a clean
  production web build. The three skips are the named pyannote dependency,
  opt-in remote diarizer network, and opt-in YouTube network cases.
- B-41 is filed with the exact judge call and missing-assertion evidence. No
  merge to `main` was attempted.

## Verdict

**Clean pass.** All eleven findings are closed, including the two owner-ruling
items. The rebased branch passes the full gate and is ready for owner
integration from `story/8-2-review`. The review branch was not merged.
