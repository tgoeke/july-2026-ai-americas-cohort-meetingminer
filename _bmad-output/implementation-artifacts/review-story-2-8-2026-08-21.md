---
title: 'Code Review: Story 2-8 — Auto-discovered Route Registration'
story: '2-8-auto-discovered-route-registration'
reviewed_range: '527acf00f81834c5eb2385df002b2ce4e2a0ee74..f837f4306e3e914906b96c4392a494886f1c6e5b'
status: 'passed'
date: '2026-08-21'
---

# Code Review — Story 2-8

Independent full-spec review of `story/2-8` at
`527acf00f81834c5eb2385df002b2ce4e2a0ee74..f837f4306e3e914906b96c4392a494886f1c6e5b`.

## Review outcome

Both corrective patches are resolved. The implementation now preserves the
frozen contract's complete route-table match order and its new import
diagnostic has a regression test.

### Registration order no longer matches the baseline route table

- **Location:** `server/meetingminer/api/registry.py:77-80`; `server/tests/test_api_registry.py:102-113`
- **Severity:** medium
- **Finding:** Discovery now registers the existing routers as `events, chat,
  ingests, jobs, media, meetings, moments, search`, while the baseline order
  was `ingests, events, jobs, meetings, moments, search, chat, media`. The
  frozen contract requires the registered route table's match order to remain
  unchanged, not just preservation of the two currently known collisions.
- **Evidence:** `discover_routers()` sorts the sole explicit `ROUTER_ORDER =
  10` router followed by module name. I ran
  `cd server && uv run python -c "from meetingminer.api.registry import
  discover_routers; print([name for name, _ in discover_routers()])"` and
  observed that order; the baseline's eight `main.py` calls establish the
  prior sequence. The current route-table test converts routes to a set, so it
  cannot detect any sequence change.
- **Suggested direction:** Preserve the baseline order declaratively in the
  discovered modules (without recreating a list in `main.py`) and add an
  ordered route-table regression assertion covering the complete baseline
  sequence as well as the existing dispatch hazards.

**Resolution (2026-08-21):** Each shipped router now declares its existing
position, and a regression test pins the complete baseline sequence.

### Attributed discovery-import failure has no regression test

- **Location:** `server/meetingminer/api/registry.py:66-73`; `server/tests/test_api_registry.py:159-192`
- **Severity:** low
- **Finding:** The remediation that wraps a discovered module's import failure
  in an `ImportError` naming the module is never exercised. Its only injected
  module imports successfully.
- **Evidence:** I searched the registry suite and package for both `router
  discovery failed importing` and `pytest.raises(ImportError)`; neither has a
  test occurrence. `test_a_dropped_in_module_is_discovered_without_editing_main`
  creates only a successful endpoint module, and the eight-test suite still
  passes if the diagnostic wrapper is removed.
- **Suggested direction:** Inject a temporary discovered module whose import
  raises, then assert the raised `ImportError` identifies its fully qualified
  module name and preserves the original exception as its cause.

**Resolution (2026-08-21):** A temporary broken module now verifies both the
attributed import error and exception chaining.

## Triage notes

Twelve other hypotheses were dismissed: invalid future ordering metadata,
duplicate or reserved future web paths, repeat registration, non-recursive
scanning, and direct-hosting history fallback either are outside the frozen
contract, already deferred, or are documented design choices. The full route
order and the untested import diagnostic are both concrete current-story
requirements.

## Verification

- `cd server && uv run pytest tests/test_api_registry.py -q` — 10 passed.
- `cd server && uv run pytest tests/ -q` — 1,507 passed; one pre-existing
  Starlette deprecation warning.
- `make web-test` — 11 files, 187 tests passed.
- `pnpm --dir web run build` — passed.
- `pnpm --dir web run lint` — exit 0; three pre-existing/inherent fast-refresh
  warnings.

**Review verdict:** passed. No must-fix Story 2-8 findings remain.
