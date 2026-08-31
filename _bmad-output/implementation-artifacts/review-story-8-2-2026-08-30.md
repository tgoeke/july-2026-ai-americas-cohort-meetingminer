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
