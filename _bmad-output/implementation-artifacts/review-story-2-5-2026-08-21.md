---
title: 'Code Review: Story 2.5 — Series, Project & Product Assignment'
story: '2-5-series-project-product-assignment'
reviewed_range: 'e9479ec938c2f3f98e71608a38f8e83a68dcc953..3147042'
status: 'passed'
date: '2026-08-21'
---

# Code Review — Story 2.5

Independent full-spec review of `story/2-5` at
`e9479ec938c2f3f98e71608a38f8e83a68dcc953..3147042`.

## Review outcome

✅ Clean review — all layers passed.

No must-fix findings remain. The independent layers raised fifteen distinct
hypotheses, all dismissed after checking the frozen intent, the adjacent
call-sites, and the current tests.

## Findings

No findings confirmed.

## Triage notes

- The projection's read of API-owned structure is required by the frozen
  contract's explicit `read_meeting` join. AD-5 reserves writes to their
  owner; it permits read-only shared access.
- Projection lag is intentional: assignments appear on the next projection or
  `rebuild`; the API is neither a store writer nor a projection scheduler.
- The API-to-projection integration seam and unbounded list routes are already
  recorded as deferred in the frozen story contract. They are not new review
  findings.
- The null-clear race hypothesis has no reachable production deleter for a
  meeting; current retirement code unprojects but does not delete the meeting
  row. The remaining test-gap and case-normalization hypotheses are outside
  the frozen requirements or already covered by schema/graph behavior.

## Verification

Independent review layers completed: Blind Hunter, Edge Case Hunter,
Verification Gap Reviewer, and Acceptance Auditor. The acceptance audit found
no acceptance-criteria or spec-constraint violations.

Targeted and full verification results:

- `uv run --project server pytest server/tests/test_api_structure.py -q` —
  22 passed.
- `uv run --project server pytest server/tests/test_migrations.py
  server/tests/test_api_registry.py server/tests/test_projections_single_writer.py
  -q` — 26 passed.
- `make web-test` — 202 passed; `pnpm --dir web run build` — passed.
- `uv run --project server pytest server/tests/ -q` — 1,566 passed, 0 failed
  (15:34).

The focused graph/rebuild command also completed under the shared projection
lock before the full run; the full server run independently includes and
passes those same store-backed tests.

**Review verdict:** passed. No must-fix Story 2.5 findings remain.
