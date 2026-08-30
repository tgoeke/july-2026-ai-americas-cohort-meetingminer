# Builder handoff — remediate Story 11-1 “Seconds-Fast Default Suite”

Give this file to the Claude `bmad-build-auto` agent. It is a standalone remediation contract; do not rely on the review session's conversation.

## Outcome and source of truth

Story 11-1 **does not pass review as it stands**. Ten findings remain: two specification-rooted contract defects and eight code/test patch actions. Do not merge or mark the story done until they are fixed, verified, and re-reviewed.

- Review report: `/Users/devopsterus/current/cohort/meetingminer/_bmad-output/implementation-artifacts/review-story-11-1-2026-08-29.md`
- Repository: `/Users/devopsterus/current/cohort/meetingminer`
- Remediation worktree: `/Users/devopsterus/current/cohort/meetingminer-wt/11-1-review`
- Remediation branch: `story/11-1-review`
- Published review head: `6424523a973ffa4459c007cca1e6f27eb4fe3028`
- Current base: `main` at `183bdf175288d74350e7147fc7134bcce9fb126e`
- Reviewed submitted range: `e5510c7caf385720851b199382b62aa1221f4051..15fdbe2f430e59054a4e97698cf4641a9ef5cb54`
- Rebased remediation range: `183bdf175288d74350e7147fc7134bcce9fb126e..6424523a973ffa4459c007cca1e6f27eb4fe3028`

The branch moved after code inspection because `main` gained Story 6.1 artifact-tracking commits. Those commits did not overlap Story 11-1's 35 implementation paths. The submitted and twice-rebased unified story diffs have identical SHA-256 `9f0ae72897c3d35cc4f7ab4001c6619a997dcf5c6415ecab76c073594399ce2b`.

Read `AGENTS.md` before touching the tree. Commit coherent units early, stage only named paths, push without asking, never reset/stash/clean the shared tree, do not restart the Docker stack while suites are running, and never run `make evals-run` during this work.

## Action group A — amend and re-derive the specification first

These are specification defects. Do not silently code around them. Record both owner decisions in the spec's change log, re-derive affected acceptance criteria and verification expectations, then make the code/docs conform to the amended contract.

### A1. Permit named new regression tests while preserving existing outcomes

- Anchor: `_bmad-output/implementation-artifacts/spec-11-1-seconds-fast-default-suite.md:45`, also lines 47, 55–56, and 93–95.
- Wrong now: the frozen contract requires exact equality with the 1,683-test baseline while the story plan itself requires permanent regression tests. The submitted story adds 24 tests and collects 1,707; current `main` contributes one unrelated test, so the rebased branch collects 1,708.
- Concrete failure: no implementation can both keep the exact baseline node-id set and add the mandated regression coverage. The empty Spec Change Log leaves the story unable to prove acceptance honestly.
- Owner decision: baseline outcome equality applies to node ids that existed at `e5510c7`; explicitly named new regression tests are allowed. Snapshot totals must name the revision they describe.
- Required result: amend/re-derive the spec and verification language accordingly. Preserve the new tests; do not delete them to recover a stale count.

### A2. Distinguish Postgres skips from twin-bound deselection

- Anchor: `_bmad-output/implementation-artifacts/spec-11-1-seconds-fast-default-suite.md:62`; operator-facing contradictions at `infra/Makefile:94` and `infra/Makefile:286-288` also affect `AGENTS.md`/`project-context.md` wording.
- Wrong now: the contract says a Postgres or test-twin outage under `make test-fast` produces named store-backed skips. Every twin-bound test is deliberately slow-marked or rejected at collection, so the default fast selection deselects it before fixture setup.
- Concrete failure: with both twin endpoints unreachable the submitted run produced `1381 passed, 326 deselected` and zero skips, contradicting the frozen edge-case row and the generic “store-backed tests skip” explanation.
- Owner decision: Postgres-backed fast tests may skip with named reasons; twin-bound slow tests are deselected from `test-fast`; `make test` remains the gate that requires the twins. Do not widen `test-fast` to execute twin-bound tests.
- Required result: amend/re-derive the spec and update all in-scope operational wording to state that distinction precisely.

## Action group B — fix now after the spec amendment

### B1. Make the documented budget override compatible with the real-session test

- Anchor: `server/tests/test_fast_budget.py:108`.
- Wrong now: the wiring test asserts the effective ini value is exactly `2.0`, although `-o mm_fast_test_budget_seconds=<seconds>` is documented as a supported override.
- Concrete failure: `uv run --project server pytest -q server/tests/test_fast_budget.py::test_the_real_session_loads_fast_budget_from_conftest -o mm_fast_test_budget_seconds=3.0` returns 1 with `assert 3.0 == 2.0`.
- Required result: prove the plugin is loaded and the effective value is valid without defeating command-line overrides. Keep the checked-in literal default pinned separately by the TOML contract.

### B2. Emit the slow-module hint only when marker deselection caused the empty run

- Anchor: `server/tests/fast_budget.py:127`.
- Wrong now: exit 5 plus default mark expression plus any deselection is treated as “all tests were removed by `not slow`.” A `-k` miss on an entirely fast module satisfies those conditions.
- Concrete failure: `uv run --project server pytest -q server/tests/test_config.py -k __meetingminer_no_such_test__` returns 5 after 55 fast tests are deselected and prints the incorrect `-m ""` recovery hint; clearing the marker cannot select a nonexistent `-k` match.
- Required result: track whether marker filtering actually removed every originally collected item. Add executable coverage for a genuine slow-only path and for an unrelated all-deselected `-k` run.

### B3. Verify the full gate's effective marker expression

- Anchor: `server/tests/test_compose_contract.py:85`.
- Wrong now: the contract checks only that the `test` recipe contains the substring `-m ""`.
- Concrete failure/mutation: a recipe containing `pytest -m "" -m "not slow" ...` passes the current assertion, while pytest uses the later expression and removes all slow tests. `pytest --co -q -m "" -m "not slow" server/tests/test_projections_locks.py` collects zero and deselects nine.
- Required result: execute or capture the target's effective pytest argv and prove that no later marker expression replaces the clearing expression; ideally include a slow sentinel proving inclusion.

### B4. Verify that `test-fast` actually runs the complete server fast set

- Anchor: `server/tests/test_compose_contract.py:95`.
- Wrong now: the test requires only `-rs` text and the absence of `MM_REQUIRE_TEST_STORES`; it never asserts that pytest runs or that its path is `server/tests`.
- Concrete failure/mutation: replacing the command with `pytest -q -rs server/tests/test_config.py`, or inert text containing `-rs`, leaves the contract green while almost all server behavior disappears from the loop.
- Required result: use a fake-command/captured-argv Make test, following existing process-target patterns, to assert the pytest project, complete server test root, skip-reporting flag, and effective fast selection.

### B5. Make the canonical slow-module contract exact and syntax-aware

- Anchor: `server/tests/test_compose_contract.py:127`.
- Wrong now: the test iterates only over the expected tuple and searches raw source lines for a prefix. It does not detect extra module-level slow marks, and matching text inside a top-level multiline string satisfies it without applying a mark.
- Concrete failure/mutation: an additional slow-marked module silently shrinks the fast set while every tuple member still passes; alternatively an expected module can replace its actual mark with the same line inside a string and remain green.
- Required result: derive the effective module-level slow set with syntax-aware inspection or collection metadata and compare it exactly with the expected set.

### B6. Cover invalid configured budgets

- Anchor: `server/tests/fast_budget.py:55` and `server/tests/test_fast_budget.py:66`.
- Wrong now: named usage errors for nonnumeric, NaN, infinite, zero, and negative values are implemented and documented but never exercised.
- Concrete failure/mutation: removing finite/positive validation leaves all current tests green; malformed overrides then produce misleading per-test behavior instead of the promised configuration error.
- Required result: parameterize representative invalid overrides and assert `USAGE_ERROR`, the key, and the offending value.

### B7. Cover the non-strict XPASS exemption

- Anchor: `server/tests/fast_budget.py:105`.
- Wrong now: the nuanced `wasxfail` exemption is implemented and documented without a probe.
- Concrete failure/mutation: removing or breaking the guard leaves current tests green and converts an over-budget non-strict XPASS into a budget failure.
- Required result: add an over-budget non-strict xfail probe that unexpectedly passes and prove its native XPASS outcome is preserved.

### B8. Exercise reason validation with default slow deselection active

- Anchor: `server/tests/test_fast_budget.py:147`.
- Wrong now: the reasonless-slow probe runs with no `-m` expression, even though `tryfirst=True` exists specifically so validation precedes default deselection.
- Concrete failure/mutation: changing the collection hook to run after marker deselection keeps the current probe green but lets a reasonless slow item disappear silently in the normal default path.
- Required result: run the reasonless-slow probe under `-m "not slow"` and require the same usage error and node id.

## Ordering and dependencies

1. Amend and re-derive A1 and A2 before source changes; record both owner decisions.
2. Fix B1 and B2, then add B6–B8 in the same focused plugin-test unit.
3. Replace the weak Make/slow-set contracts for B3–B5. B3 and B4 may share one captured-command harness; B5 is independent.
4. Update the A2 operational docs after behavior/test naming is final.
5. Run targeted regressions, then the complete verification gate. Commit each coherent unit and push `story/11-1-review`.
6. Leave story/sprint status `in-progress` and request a follow-up `bmad-code-review`; do not mark done or merge yourself.

## Verification required before reporting remediation complete

For every new regression, demonstrate that it detects the unfixed defect rather than merely passing on the repaired code. Use an isolated scratch copy or a deliberate mutation inside a test fixture; never reset, stash, or destructively rewrite the shared tree.

Targeted requirements:

- B1 red evidence is the `3.0` override command above; after the fix it must pass.
- B2 must prove both cases: genuine slow-only path prints the hint, `-k` miss on a fast module does not.
- B3 mutation with a later `-m "not slow"` must fail the new contract.
- B4 mutation narrowing the server path to one module must fail the new contract.
- B5 both an extra module mark and a string-only fake mark must fail the new contract.
- B6 representative invalid values must return usage errors; a valid non-2.0 override must remain accepted.
- B7 the XPASS probe must retain XPASS over budget.
- B8 the reasonless mark must remain a usage error under `-m "not slow"`.

Then run from the worktree root, with stores up for the full gate and without restarting Docker during any suite:

```bash
uv run --project server pytest server/tests/test_fast_budget.py server/tests/test_compose_contract.py -m "" -q
uv run --project server pytest server/tests --co -q | tail -1
uv run --project server pytest -m "" server/tests --co -q | tail -1
uv run --project server pytest -m "" server/tests/test_makefile_procs.py -q
make check-test-stores
time make test-fast
time make test
```

Expected collection at the published remediation base, before any additional parametrized cases alter the total: default `1382/1708 collected (326 deselected)` and full `1708 collected`. If the fixes add cases, report the new totals and tie them to the final commit. For the full run, compare outcomes for every pre-`e5510c7` node id against the preserved baseline and separately list new tests; no pre-existing outcome may change.

Repeat the real throwaway 2.5-second budget probe from the spec: unmarked pass becomes a named budget failure; an ordinary assertion remains its own failure; a slow-marked sleeper is exempt under `-m ""`. Delete the throwaway file afterward using a precise, safe operation.

## Explicitly out of scope

- Story 11.2 store namespacing, containers, or lock behavior.
- Speeding tests by changing what they exercise.
- `server/meetingminer/**`, `web/`, `evals/`, `tools/`, `config.yaml`, migrations, or dependencies.
- The three already deferred owner items: README updates, a project-record entry, and filing the Postgres fixture-cost residue as a new backlog item.
- The pre-existing Starlette/httpx deprecation warning.
- `make evals-run`.

No deferred-work entry is requested by this review. The 12 dismissed review-layer claims require no builder action; their rationale remains in the review report's surviving-finding boundary.
