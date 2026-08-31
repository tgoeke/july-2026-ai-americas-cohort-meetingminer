# Code Review — Story 8.2: Persisted Selection

## Scope

Adversarial review of Story 8.2 implementation and its stated footprint against the frozen intent contract, architecture decisions, acceptance criteria, and regression expectations supplied in the reviewer handoff.

## Review range

- Baseline: `ea0c113`
- Story branch: `story/8-2`
- Review branch: `story/8-2-review`
- Range: `ea0c113..story/8-2`
- Review date: 2026-08-30

## Findings

### Finding 1 — `judge` selections are persisted and reported as effective but never used (open)

- **Location** — `evals/harness/judge.py:499`
- **Severity** — medium
- **Finding** — `GET /settings/models` and `PUT /settings/roles/{role}` include every declared role, including `judge`, and label the stored `judge` choice as `effectiveBinding`. The only production judge call path still binds `config.settings.llm.roles.judge` directly, so a successful `PUT /settings/roles/judge` has no effect on the model that judges a run. The snapshot can therefore call a persisted judge choice “effective” while `llm-judge-report.yaml` and the actual calls use the file binding. This is **open** because the frozen intent contract names call-time adoption only for chat and extraction and the required correction reaches `evals/harness/judge.py`, outside the story footprint; resolving it requires an owner/spec decision.
- **Evidence** — `rg -n "roles\\.judge|build_llm\\(" evals server/meetingminer -g '*.py'` found the judge call at `evals/harness/judge.py:499-500`, which assigns the file role and passes it directly to `build_llm`. `server/meetingminer/api/settings.py:97-104` derives the settings surface from every `LlmRoles.model_fields` entry, and `:123-145` labels any stored choice as the effective binding. `evals/tests/test_run_judge.py` replaces `build_llm` but never asserts which binding was passed, so the non-adoption is not detected.
- **Suggested direction** — Decide whether persisted selection governs the manual eval judge. If it does, amend the frozen contract and footprint so the judge reads the public settings response and applies that returned binding at call time without importing server-owned selection logic. If it does not, stop accepting/reporting a `judge` selection as effective and define clearly what the catalog entry means.

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
