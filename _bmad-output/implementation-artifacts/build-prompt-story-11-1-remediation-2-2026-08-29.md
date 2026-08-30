# Builder handoff — remediate Story 11-1 "Seconds-Fast Default Suite", round 2

Give this file to the Claude `bmad-build-auto` agent. It is a standalone remediation contract; do not rely on any review session's conversation.

## Outcome and source of truth

Story 11-1 **does not pass re-review as it stands**. The ten first-round findings are verified fixed. Three new medium findings remain, all verification/enforcement gaps: a contract that does not pin what it promises, an inventory that misses one class of mark, and an invariant with a dynamic bypass. Fix all three, verify, push, and stop. Do not merge or mark the story done.

- Re-review report: `/Users/devopsterus/current/cohort/meetingminer/_bmad-output/implementation-artifacts/review-story-11-1-rereview-2026-08-29.md`
- First review (context only, all fixed): `.../review-story-11-1-2026-08-29.md`
- Spec: `/Users/devopsterus/current/cohort/meetingminer/_bmad-output/implementation-artifacts/spec-11-1-seconds-fast-default-suite.md` — the frozen `<intent-contract>` as amended 2026-08-29 stands; nothing here amends it
- Repository: `/Users/devopsterus/current/cohort/meetingminer` (main checkout — other agents work in it; do not edit code there)
- Worktree: `/Users/devopsterus/current/cohort/meetingminer-wt/11-1-review`, branch `story/11-1-review` at `31ff5392dc6d28d4b9e116efc6b759d37d2b8521`, pushed, clean
- Re-reviewed range: `183bdf175288d74350e7147fc7134bcce9fb126e..31ff5392dc6d28d4b9e116efc6b759d37d2b8521`
- `main` is now `a22d67c` (three commits past the branch base: integrate-skill restore, sprint-status sync, `_bmad-output` untracked)

`_bmad-output/` is gitignored and **never pushed**. Every path under it above is under the main checkout; edit the spec there. Never `git add -f` under `_bmad-output/`.

Read `AGENTS.md` first. Commit each coherent unit, stage only named paths, push without asking, never reset/stash/clean the shared tree, do not restart the Docker stack while any suite is running, never run `make evals-run`.

Harness note carried over from round 1: the Bash sandbox denies writes under the worktree and reads of `.env`; edit files with the Edit/Write tools and run `git`, `pytest`, `uv`, `make` inside the worktree with the sandbox disabled. Run pytest from the worktree root with a path under `server/tests` (`pytest_plugins` needs the initial conftest). Server suites may run concurrently with other worktrees' suites.

## Step 0 — rebase onto current main first

```bash
git -C /Users/devopsterus/current/cohort/meetingminer-wt/11-1-review fetch origin
git -C /Users/devopsterus/current/cohort/meetingminer-wt/11-1-review rebase origin/main
```

Known conflict, `infra/Makefile`, by proximity only: both sides add to `.PHONY` and to `help` (`test-fast` on this branch, `check-reviews` on main). Resolve by **union** — keep both entries in both places. No other overlap exists.

After the rebase the worktree's real `_bmad-output/` directory loses the files `a22d67c` untracked; that is expected. Nothing under it in the worktree is needed — the spec and reports live under the main checkout.

Push with `git push --force-with-lease origin story/11-1-review`. Record the post-rebase head; every SHA you cite from here on is post-rebase.

## Findings to fix

### F1. Pin `test-fast`'s prerequisite suites

- Anchor: `server/tests/test_compose_contract.py:200` (`test_make_test_fast_runs_the_whole_server_fast_set`); `infra/Makefile:294`.
- Wrong now: the `test-fast` contract proves only the server pytest argv. Nothing pins the target's promised prerequisites `check-client`, `puller-test`, `web-test`, `evals-test`. The only prerequisite-composition test in the tree, `test_makefile_procs.py::test_test_target_runs_the_puller_suite`, covers `test:` and only `puller-test`.
- Concrete failure: delete `web-test` from the `test-fast:` prerequisite line — every current 11-1 contract stays green while `make test-fast` stops running the web suite.
- Required result: a contract deriving `test-fast`'s effective prerequisite/command sequence (the `make -n` argv oracle already in `test_compose_contract.py` is the natural source; `_the_command_for` and `_recipe` exist) that requires all four store-free prerequisites to run before the whole-server fast pytest command, and requires `check-client` first (it is there so a missing client fails with its named message rather than as a Vite import error inside `web-test`). Red evidence: removing any one of the four from the prerequisite line must fail the new contract.

### F2. Inventory the function-level `slow` marks exactly

- Anchor: `server/tests/test_compose_contract.py:280–318` (`_is_slow_mark`, `_has_module_level_slow_mark`, `test_the_module_level_slow_set_is_exactly_the_measured_twelve`).
- Wrong now: the `ast`-derived exact-set guard inventories only module-level `pytestmark` assignments. The four production function-level marks — `test_api_events.py:434`, `test_api_events.py:455`, `test_artifact_publish.py:414`, `test_worker_extract.py:1164` — are outside every exact inventory. The collection rule accepts any additional function-level mark with a non-empty reason and the budget exempts it, so a fifth `@pytest.mark.slow(reason=...)` on a fast test silently removes it from the default suite with every contract green.
- Required result: a second syntax-derived inventory — decorated `def`/`async def` at module level and inside classes, walked with `ast`, so marks inside pytester probe strings (`test_fast_budget.py`, `test_compose_contract.py`) are not counted — of the function-level slow node ids, compared both ways against an expected tuple of exactly those four (module stem + function name is enough; keep the same "edit both places" comment as `SLOW_MODULES`). Reuse `_is_slow_mark`. Red evidence: a deliberate extra decorator on a fast test must fail the contract; removing one of the four must fail it the other way.

### F3. Close the dynamic twin-fixture bypass

- Anchor: `server/tests/fast_budget.py:86–90` (`pytest_collection_modifyitems`, the `_TWIN_FIXTURES & set(item.fixturenames)` check).
- Wrong now: `item.fixturenames` is the static fixture closure. A test that calls `request.getfixturevalue("projection_stores")` or `request.getfixturevalue("stores_up")` is not in it, so an unmarked test enters the default fast set and acquires and wipes the twins. No production test does this today; it is a reachable regression, and the stated invariant ("every twin-bound test is slow") has a hole.
- Required result: enforce the same rule at fixture setup time for the two named fixtures — a `pytest_fixture_setup` hook (or equivalent) that, when `fixturedef.argname in _TWIN_FIXTURES` and the requesting item carries no `slow` mark, fails with the same diagnostic text naming the node id. Keep the collection-time check: it reports every offender at once before anything runs; the setup-time check is the backstop for the dynamic path. Do not widen `_TWIN_FIXTURES`. Red evidence: a pytester probe whose unmarked test calls `request.getfixturevalue("projection_stores")` (with a fake `projection_stores` fixture in the probe that records it ran) must reach the fixture under the unfixed plugin and must be stopped, with the fixture never running, under the fixed one. Add the mirror probe for `stores_up`, or parametrize.

## Ordering

1. Step 0 rebase, push.
2. F3 (plugin + pytester probes) as one unit.
3. F1 and F2 in `test_compose_contract.py`; they may share a commit.
4. Docs: if the new hook changes the behaviour AGENTS.md `## Fast loop and full gate` or `project-context.md` describe (the twin rule is stated there), update the sentence; otherwise leave the docs alone. Re-pin the count comment in `infra/Makefile` and the `docs/backlog.md` B-1 paragraph to the final commit if the collected total changes.
5. Verification gate below. Push. Append a "Remediation round 2" paragraph to the spec's `## Auto Run Result` (main checkout) with the final head, the counts, and the gate results. Leave `status: 'in-review'` in the spec frontmatter and `11-1-seconds-fast-default-suite: in-progress` in `sprint-status.yaml`; do not edit `sprint-status.yaml` at all.

## Verification required before reporting complete

Every new regression must be shown failing against the unfixed code or a deliberate mutation, then passing after restore. Mutate inside the worktree you own and restore by editing, never by resetting.

Then, from the worktree root, stores up, no Docker restarts during any suite:

```bash
uv run --project server pytest server/tests/test_fast_budget.py server/tests/test_compose_contract.py -m "" -q
uv run --project server pytest server/tests --co -q | tail -1
uv run --project server pytest -m "" server/tests --co -q | tail -1
uv run --project server pytest -m "" server/tests/test_makefile_procs.py -q
make check-test-stores
time make test-fast
time make test
```

Baseline at `31ff539`: the two contract modules → 41 passed; collection `1382/1708 (326 deselected)`, `-m ""` → 1708; `test_makefile_procs` → 46; `make test-fast` rc 0 (~65s; server step 1382 passed / 326 deselected); `make test` rc 0 (~9 min; 1708 passed). Report the new totals tied to the final commit. Compare the full run's outcomes for every node id that existed at `e5510c7` against the preserved baseline junit: 0 changed, 0 missing; list the added tests separately. The one warning in every run is the pre-existing Starlette `httpx` deprecation.

Finish by stating: final head, `origin/story/11-1-review` identical, tree clean, the counts, and that the story awaits re-review. Do not write the re-review prompt; do not merge.

## Explicitly out of scope

- Story 11.2; anything under `server/meetingminer/**`, `web/`, `evals/`, `tools/`, `config.yaml`, migrations, dependencies.
- The three deferred owner items (README, project-record entry, filing the fixture-cost residue).
- The nine layer claims the re-review dismissed as by-design (call-phase budgeting, Postgres-down skips, module-level marking, `PYTEST_ADDOPTS` as an operator override, the `--deselect` hint edge, the 49-second fixture residue). No action.
- Any change to the frozen `<intent-contract>`.
