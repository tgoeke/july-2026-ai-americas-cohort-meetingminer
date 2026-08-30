---
title: 'Code Review — Story 11-1, Fourth Review'
story: '11-1-seconds-fast-default-suite'
date: '2026-08-29'
reviewer: 'Codex bmad-code-review'
status: 'in-progress'
base_commit: '28ea43d4fba4510278c524e730d86c944a781181'
reviewed_head: '2ce91b3a7834e3572a270f192b2eef892a4f53c9'
reviewed_branch: 'story/11-1-review'
---

# Story 11-1 — Fourth Code Review

## Scope

- Diff: `28ea43d4fba4510278c524e730d86c944a781181...2ce91b3a7834e3572a270f192b2eef892a4f53c9`
- Contract: `/Users/devopsterus/current/cohort/meetingminer/_bmad-output/implementation-artifacts/spec-11-1-seconds-fast-default-suite.md`
- Review state: adversarial layers complete; targeted verification in progress.

## Findings

### 1. `[medium] [patch]` A cached wrapper fixture hides its dynamic twin dependency

`server/tests/fast_budget.py:164-211` checks the current item's resolved fixture definitions, but a session-scoped wrapper fixture can call `request.getfixturevalue("stores_up")` while serving a slow test and then be returned from cache to a later unmarked test. The later item's request resolves only the wrapper, the twin setup hook does not run again, and the report-time check sees no twin. The structural rule is bypassed even though the unmarked test consumes a fixture whose value is bound to the test twin.

Red evidence against reviewed head `2ce91b3`: a throwaway probe with a slow seed, a session-scoped dynamic wrapper, and a later unmarked wrapper requester completed `3 passed`, exit 0. The twin ran once and the unmarked consumer stayed green. The fix must make a dynamically twin-bound fixture remain identifiable when its cached value is served to later requesters, without rejecting wrappers that never resolve a twin.

### 2. `[medium] [patch]` The `test-fast` recipe contract does not pin the actual pytest argv

`server/tests/test_compose_contract.py:129-136,274-339` recognizes a server pytest command when the token list merely contains `uv`, `pytest`, and a path below `server/tests`; the final recipe check asserts only the `cd <root> &&` prefix, a leading `uv`, and a partial chaining denylist. Consequently both `uv run --project <server> echo pytest -q -rs <server/tests>` and a real pytest invocation followed by `& true` satisfy every current assertion. The first never invokes pytest; the second backgrounds it, so make can report success before the suite finishes.

Red evidence against reviewed head `2ce91b3`: evaluating both token lists through the production helpers produced all-true assertion vectors. The first was `['cd', root, '&&', 'uv', 'run', '--project', server, 'echo', 'pytest', '-q', '-rs', tests]`; the second appended `['&', 'true']`. The fix must pin the one allowed post-`cd` argv as an actual `uv run --project <server> pytest -q -rs <server/tests>` invocation and reject added non-execution, selection-narrowing, backgrounding, or second-command tokens.

### 3. `[medium] [patch]` Call-phase-only budgeting is not regression-pinned

`server/tests/fast_budget.py:267-299` correctly exempts setup and teardown reports, as the frozen contract requires, but `server/tests/test_fast_budget.py:291-333` exercises over-budget delays only in test bodies. A change that applied the budget to passed setup or teardown reports would violate the explicit call-phase-only decision while the existing sleeper probes remained green. Add a deterministic pytester probe with over-budget setup and finalizer delays plus an under-budget body, and require the test to pass.

### 4. `[medium] [patch]` Non-empty slow-reason validation is only tested for an absent reason

`server/tests/fast_budget.py:104-106,137-162` correctly rejects absent, empty, whitespace-only, and non-string `reason` values, but `server/tests/test_fast_budget.py:354-361` covers only a bare `@pytest.mark.slow`. A regression from `_has_reason()` to key-presence validation would preserve that test while allowing empty reasons to silently remove tests from the default set. Parameterize the probe over absent, empty, whitespace-only, and non-string values.

## Triage summary

- `patch`: 4 medium
- `decision_needed`: 0
- `defer`: 0
- `dismissed`: 13 normalized layer claims
- failed review layers: 0

## Verdict

Provisional: changes requested; verification and artifact synchronization remain.
