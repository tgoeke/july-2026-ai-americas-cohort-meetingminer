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
