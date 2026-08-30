# Builder handoff — remediate Story 11-1, round 3

Hand this file to the Claude `bmad-build-auto` agent. It is standalone.

Story 11-1 **does not pass its third review as it stands**. Three medium patch
findings remain. Fix all three, verify, commit, push, and stop. Do not merge or
mark the story done; the next review/integration pass owns that.

## Exact state and reviewed range

- Repository: `/Users/devopsterus/current/cohort/meetingminer`
- Worktree: `/Users/devopsterus/current/cohort/meetingminer-wt/11-1-review`
- Branch: `story/11-1-review`
- Reviewed code head: `02963147d0556f8770b9401eb5db8999f128d73f`
- Current branch head when this handoff was written: `71a4ab3` (the two commits
  after `0296314` contain only the third-review report)
- Full story range reviewed: `28ea43d4fba4510278c524e730d86c944a781181..02963147d0556f8770b9401eb5db8999f128d73f`
- Round-2 range reviewed: `ba1d39efb2ff5182713d0f958b6dab22bae1408d..02963147d0556f8770b9401eb5db8999f128d73f`
- Review report: `_bmad-output/implementation-artifacts/review-story-11-1-third-review-2026-08-29.md`
- Specification: `/Users/devopsterus/current/cohort/meetingminer/_bmad-output/implementation-artifacts/spec-11-1-seconds-fast-default-suite.md`

The older suggested range `183bdf1..0296314` is not the story range after the
rebase: it includes unrelated integrated work. Use `28ea43d..0296314` for the
story or `ba1d39e..0296314` for remediation round 2.

## Fix now

### F1. Enforce the cached-twin structural rule on non-passing/setup paths

- Anchor: `server/tests/fast_budget.py:194-205`.
- Wrong now: `pytest_runtest_makereport` checks `_twins_resolved_for(item)` only
  after `call.when == "call"`, `report.passed`, and no `wasxfail`. When a slow
  test has already cached session-scoped `stores_up`, a later unmarked test can
  resolve it dynamically and then skip or xfail; the fixture-setup hook is not
  called and the report hook returns before the structural check. A cached
  request made during setup has no passing call report either.
- Concrete failure: a throwaway slow seed followed by an unmarked
  `request.getfixturevalue("stores_up"); pytest.skip(...)` returned rc 0 with
  `1 passed, 1 skipped` under `0296314`.
- Required result: any unmarked item that resolved `projection_stores` or
  `stores_up` must surface the twin-rule failure independent of a passed,
  skipped, or xfailed call. Preserve a genuine existing test failure rather
  than obscuring it, but skip/xfail must not make the structural violation
  green. Keep the existing first-time setup guard and diagnostic.
- New regression: add cached-session probes for skip/xfail and a request from
  setup. Confirm them against the unfixed code first; record the observed green
  bypass, then show the fixed behavior.

### F2. Make class-level slow marks representable in the exact pin inventory

- Anchor: `server/tests/test_compose_contract.py:413-465`.
- Wrong now: `_decorated_slow_definitions` records a class mark as
  `module::Class`, while `_pinned` checks collected methods as
  `module::Class::test_method`. No `SLOW_TESTS` tuple can satisfy both the
  syntax exact-set assertion and the collected-node assertion.
- Concrete failure: a throwaway class-body
  `pytestmark = pytest.mark.slow(reason=...)` produced pin
  `test_slow_class_source::TestGroup`; with that exact pin installed,
  `_pinned("test_slow_class_source.py::TestGroup::test_one")` returned `False`.
- Required result: choose one canonical class representation and use it
  consistently in the syntax inventory and runtime node-id mapping. Adding a
  class-level mark plus its documented pin must make both contracts pass;
  omitting the pin must fail and name the class/method clearly.
- New regression: add an AST/runtime probe for a class-level mark, demonstrate
  the current impossible mapping first, then show the fix.

### F3. Pin the direct `test-fast` recipe command list

- Anchor: `server/tests/test_compose_contract.py:263-279`; target at
  `infra/Makefile:295-296`.
- Wrong now: `_dry_run_steps` proves the prerequisite target order and that
  `test-fast` contains a recognized server pytest line, but it does not
  constrain other direct commands owned by the `test-fast` target. Therefore
  the server command need not actually be last and Docker/store work can be
  appended without failing the contract.
- Concrete failure: appending `docker compose up -d` after the pytest recipe
  left both `test-fast` contracts green (`2 passed`).
- Required result: from Make's effective dry run, assert that the direct command
  list owned by `test-fast` contains exactly one whole-server pytest invocation,
  last, and no Docker/store command before or after it. Retain the existing
  exact/transitive prerequisite assertions.
- New regression: repeat the appended-command mutation and require the new
  contract to fail before restoring the Makefile by edit.

## No action in this round

- Do not change the accepted residual risks around pytest private names or a
  later `pytest_collection_modifyitems` hook; they are documented and were not
  promoted to findings.
- Do not widen pins to nested test directories or parameter-instance node ids;
  neither has a current consumer and the existing definition-level convention
  stands.
- Do not rewrite the bodies of `check-client`, `puller-test`, `web-test`, or
  `evals-test`; F3 is about commands directly owned by `test-fast`.
- No specification-rooted finding exists. Do not amend the frozen intent.
- Stay within the Story 11-1 file boundary. Do not touch application code,
  dependencies, README, project-record, or unrelated backlog entries. Do not
  run `make evals-run`.

## Ordering

1. Fetch and confirm branch/upstream/tree state. Rebase only if `main` has moved;
   if it has, rebase before patching and record the new base/head.
2. F1 with its pytester probes.
3. F2 and F3; they may share a contract-test commit if coherent.
4. Update only Story 11-1 documentation whose behavior or revision-pinned
   counts changed. Keep spec status `in-review` and sprint status
   `in-progress`; do not edit `sprint-status.yaml`.
5. Run the complete gate, commit each coherent unit, push, and report the exact
   SHAs. Do not merge and do not write the next review prompt.

## Verification gate

Every new regression must first be demonstrated against the unfixed behavior or
a deliberate mutation, then pass after restoration/fix. Restore mutations by
editing, never by reset/stash/clean.

From the worktree root, stores up, no Docker restart:

```bash
uv run --project server pytest server/tests/test_fast_budget.py server/tests/test_compose_contract.py -m "" -q
uv run --project server pytest server/tests --co -q | tail -1
uv run --project server pytest -m "" server/tests --co -q | tail -1
uv run --project server pytest -m "" server/tests/test_makefile_procs.py -q
make check-test-stores
time make test-fast
time make test
make check-reviews
```

Baseline at reviewed code head `0296314`: contract modules 48 passed; collection
`1389/1715 (326 deselected)`, full collection 1715; `test_makefile_procs` 46;
`make test-fast` server 1389 passed / 326 deselected; coordinator full gate 1715
passed. Compare the full-run junit against the preserved `e5510c7` baseline:
0 changed and 0 missing on the 1683 pre-existing node ids; list new tests
separately and revision-pin every new count. The sole expected warning is the
pre-existing Starlette `httpx` deprecation.

Finish by reporting the final head, upstream equality, clean tree, red evidence,
gate results, and that Story 11-1 awaits another review. Do not merge.
