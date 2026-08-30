# Third code review — Story 11-1: Seconds-Fast Default Suite

## Review scope

- Review worktree: `/Users/devopsterus/current/cohort/meetingminer-wt/11-1-review`
- Branch: `story/11-1-review`
- Reviewed head: `02963147d0556f8770b9401eb5db8999f128d73f`
- Full story range: `28ea43d4fba4510278c524e730d86c944a781181..02963147d0556f8770b9401eb5db8999f128d73f`
- Remediation round 2 range: `ba1d39efb2ff5182713d0f958b6dab22bae1408d..02963147d0556f8770b9401eb5db8999f128d73f`
- Specification: `_bmad-output/implementation-artifacts/spec-11-1-seconds-fast-default-suite.md`
- Context: `AGENTS.md`, `project-context.md`

The previously suggested `183bdf1..0296314` range is not used as the full-story diff because the branch was rebased onto `main` at `28ea43d`; the older range includes unrelated integrated work.

## Verdict

**Changes requested.** Remediation round 2 closes the three findings from the
previous re-review in their demonstrated cases, but this third review found
three additional medium verification/enforcement gaps. Story 11-1 remains
`in-review`; sprint status remains `in-progress`; do not merge yet.

## Findings

### 1. Cached twin requests that skip or xfail still pass the structural rule

- **Location:** `server/tests/fast_budget.py:194-205`
- **Severity / route:** medium / patch
- **Sources:** blind hunter, edge-case hunter, acceptance auditor
- **Finding:** The cached-session backstop runs only for a passed `call`
  report. Once a slow test has cached session-scoped `stores_up`, a later
  unmarked test can resolve it dynamically and then skip or xfail. The setup
  hook is not called for the cached fixture, and the report hook returns before
  checking `_twins_resolved_for`, so the run remains green even though the test
  is twin-bound and unmarked. A cached request made during setup also has no
  passing call report to inspect.
- **Executable evidence:** A throwaway run with a slow seed followed by an
  unmarked `request.getfixturevalue("stores_up"); pytest.skip(...)` returned
  zero: `1 passed, 1 skipped`. The same plugin correctly fails the ordinary
  passing cached requester, so the gap is the outcome/phase guard, not fixture
  discovery.
- **Required result:** Enforce the twin rule for every unmarked item that
  resolved a twin, independently of whether its call passed, skipped, or
  xfailed. Preserve a test's genuine failure where appropriate, but a skip or
  expected failure must not make the structural violation green. Add cached
  `stores_up` probes for the non-passing/setup paths and show them green against
  the unfixed plugin, then failing under the fix.

### 2. A class-level slow mark has no representable exact pin

- **Location:** `server/tests/test_compose_contract.py:413-465`
- **Severity / route:** medium / patch
- **Sources:** blind hunter, edge-case hunter, acceptance auditor
- **Finding:** `_decorated_slow_definitions` records a class mark as
  `module::Class`, while `_pinned` tests each collected method as
  `module::Class::test_method`. Adding the class entry to `SLOW_TESTS` satisfies
  the syntax inventory but fails the collected-node guard; adding method
  entries satisfies `_pinned` but fails the exact syntax inventory. This
  contradicts the new claim that class `pytestmark` is caught and pin-able.
- **Executable evidence:** A throwaway class with class-body
  `pytestmark = pytest.mark.slow(...)` produced the syntax pin
  `test_slow_class_source::TestGroup`; with that exact pin installed,
  `_pinned("test_slow_class_source.py::TestGroup::test_one")` returned `False`.
- **Required result:** Choose one canonical class representation and make both
  the syntax-derived inventory and collected-node check accept it consistently.
  Add a red/green class-level probe.

### 3. The `test-fast` contract does not prove its own recipe ends with the server command

- **Location:** `server/tests/test_compose_contract.py:263-279`
- **Severity / route:** medium / patch
- **Sources:** blind hunter, verification-gap reviewer
- **Finding:** `_dry_run_steps` proves the prerequisite target order and that
  `test-fast` contains a recognized server pytest line, but it does not
  constrain the other direct commands in the `test-fast` recipe. The server
  pytest command therefore need not actually be last, and Docker/store work or
  another command can be appended without changing the announced target
  sequence or `with_server_pytest == ["test-fast"]`.
- **Executable evidence:** Appending `docker compose up -d` directly after the
  pytest recipe left both Story 11-1 `test-fast` contract tests green (`2
  passed`). The mutation was restored by edit and the worktree diff returned
  empty.
- **Required result:** Derive and assert the direct command list owned by the
  `test-fast` step: exactly one whole-server pytest invocation, last, with no
  Docker/store command before or after it. Keep the existing prerequisite
  graph assertions. Confirm the appended-command mutation fails.

### Layer triage

- Active layers: blind hunter, edge-case hunter, verification-gap reviewer,
  acceptance auditor; none failed.
- Result: 3 patch findings, 0 decision-needed, 0 deferred, 10 normalized claims
  dismissed.
- Dismissed themes: a caught first-time setup-hook failure is still found by
  the report hook (verified by probe); late hook-added marks and the two private
  pytest fields are already recorded residual risks; teardown-only dynamic
  requests are deprecated in pytest 9.1 and outside the pinned pytest range's
  supported direction; parameter pins are deliberately definition-level;
  nested stem collisions and duplicate tuples have no current consumer impact;
  prerequisite target bodies are owned by their own contracts; permissive
  `echo`/`GNUMAKEFLAGS` mutations are harness-hardening concerns rather than
  separate failures.

## Previous findings verification

1. **Previous F1 fixed for its six required mutations.** The effective Make
   sequence is `check-client`, exactly the three store-free targets, then
   `test-fast`; removal/reorder/transitive-prerequisite cases are pinned. New
   finding 3 is the remaining direct-recipe surface.
2. **Previous F2 fixed for module/function marks and unpinned collected items.**
   The exact `SLOW_MODULES`/`SLOW_TESTS` inventories and collection stash are
   present. New finding 2 is the inconsistent class representation.
3. **Previous F3 fixed for first-time dynamic fixture setup and a passing cached
   requester.** The fixture is stopped before running, and the marked-first
   passing probe is caught. New finding 1 is the non-passing/setup report path.

## Verification

- `uv run --project server pytest server/tests/test_fast_budget.py server/tests/test_compose_contract.py -m "" -q`
  — PASS: 48 passed; one pre-existing Starlette deprecation warning.
- Default collection — `1389/1715 tests collected (326 deselected)`; `-m ""`
  collection — `1715 tests collected`.
- `make -n --debug=basic -C infra test-fast` on GNU Make 3.81 — observed the
  documented target order and one normal server command.
- `make test-fast` — PASS: puller 128, web 291, evals 549, server 1389 passed / 326
  deselected in 49.84s; one pre-existing warning.
- Adversarial probes: cached-then-skip run stayed green; appended Docker recipe
  left both `test-fast` contracts green; class syntax pin could not pin its
  collected method. All tracked mutations were restored by edit; tree clean.
- The coordinator's handoff records the full `make test` gate at `4911c21` as
  1715 passed with 0 changed / 0 missing baseline node ids. This reviewer did
  not repeat the nine-minute full gate after the three blocking gaps were
  confirmed.

## Integration

- Review report skeleton committed and pushed as `cdf5faf` before code review.
- No source patch was applied; the user's final-report instruction is treated
  as “leave as action items.”
- No merge: three medium patch findings remain.
- Spec status remains `in-review`; sprint status remains `in-progress` and was
  not edited, matching the story contract.
