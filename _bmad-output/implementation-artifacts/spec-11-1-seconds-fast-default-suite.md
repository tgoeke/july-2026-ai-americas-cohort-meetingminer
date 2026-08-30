---
title: 'Seconds-Fast Default Suite'
type: 'chore'
created: '2026-08-29'
status: 'done'
baseline_revision: 'e5510c7caf385720851b199382b62aa1221f4051'
review_loop_iteration: 0
followup_review_recommended: false
context: ['{project-root}/AGENTS.md']
warnings: ['multiple-goals', 'oversized']
deferred:
  - summary: >-
      README.md's make-target table has no `make test-fast` row and its testing section still gives the by-path pytest command without the `-m ""` caveat for `slow` modules.
    evidence: |-
      Blind Hunter finding: README.md make-target table (~line 220) and "Testing and evaluation" (lines 318-346) predate the split; a by-path run of a `slow` module now collects nothing and exits 5. README.md is outside the story's file boundary (build prompt: server/tests/**, server/pyproject.toml, infra/Makefile test targets, AGENTS.md, project-context.md "Running and verifying", docs/backlog.md B-1).
    location: >-
      README.md
    severity: medium
  - summary: >-
      docs/project-record.md carries no entry for story 11.1 although it records earlier test-platform changes (per-run databases, the cross-worktree lock).
    evidence: |-
      Blind Hunter finding; the story's account currently lives only in docs/backlog.md "Removed from this list". project-record.md is outside the story's file boundary; the sprint change proposal says project-record entries land as stories land (integration).
    location: >-
      docs/project-record.md
    severity: low
  - summary: >-
      The residual fast-set cost (about a thousand Postgres-backed api/worker tests at 20-50ms each, ~48s) is described in the B-1 retirement paragraph but not filed as a backlog item with a size.
    evidence: |-
      Blind Hunter and intent-alignment findings; measured 2026-08-29 (fast set 1,358 tests in 47.7s of pytest at d36aaa6). The story's boundary on docs/backlog.md is "B-1 only", so filing a new item is the owner's call.
    location: >-
      docs/backlog.md
    severity: low
---

<intent-contract>

## Intent

**Problem:** The full server run (`pytest server/tests`) is the only run: measured 2026-08-29 at `e5510c7`, 1,683 tests pass in 9m17s wall (554s), so builders run it once per story instead of after every change. Backlog B-1 attributed the cost to seven process-spawning modules; the measurement shows 471 of 527 test-seconds sit in twelve modules bound by the Neo4j/Meilisearch test twins, spawned processes, the projection file lock, or timers, and `test_mint_drop` (which B-1 names) runs in 2.8s. `conftest.py` also exports `REPO_ROOT`, imported by 16 modules through the plugin module, and `test_makefile_procs.py` carries two overlapping `make` runners.

**Approach:** Register a `slow` marker defined by measurement — "duration set by something outside the test process" — put it on those twelve modules (module-level `pytestmark` with a one-line reason each) and on three timing/twin-bound tests in otherwise fast modules, default the runner to `-m "not slow"` through `addopts`, and add a conftest per-test budget (call phase, 2.0s, configured in `pyproject`) that fails any *unmarked* test exceeding it so the fast set cannot regrow silently. `make test` clears the default with `-m ""` and still runs everything; a new `make test-fast` runs the default selection with skip reasons printed plus the three store-free suites (measured 1.7s, 0.7s, 12.7s). Move `REPO_ROOT` into `server/tests/repo_paths.py`, collapse the two runners into one `_make`, state the split in AGENTS.md and `project-context.md`, and retire B-1 with the measured numbers.

## Boundaries & Constraints

**Always:** Work only in the remediation worktree `/Users/devopsterus/current/cohort/meetingminer-wt/11-1-review` on branch `story/11-1-review` (the submitted `story/11-1` rebased onto `main`; the spec and the review report live in the main checkout's `_bmad-output/implementation-artifacts/`, read them by absolute path; never edit the main checkout). Run pytest from the repo root (`./config.yaml` resolves relative to the cwd). Stay inside: `server/tests/**`, `server/pyproject.toml`, `infra/Makefile` (test targets only), `AGENTS.md`, `project-context.md` ("Running and verifying" only), `docs/backlog.md` (B-1 only). No test changes behaviour: every node id that existed at `e5510c7` keeps its baseline outcome in the full run (junit before vs after, compared on pre-existing node ids); the named new regression tests (`server/tests/test_fast_budget.py` and the additions to `server/tests/test_compose_contract.py`) are allowed and listed separately; any snapshot total names the revision it describes. Every child `pytest` a test spawns keeps its selection (`-m ""`). Every marker is registered. The budget is a configured value with a written rationale, applies to the `call` phase only, and never to `slow`-marked tests. Skips are printed, never silent. Report measured numbers only. Commit each unit as it lands.

**Block If:** A node id that existed at `e5510c7` changes outcome in the after-run for any reason other than the budget hook naming that test.

**Never:** Add `pytest-timeout` or any dependency. Touch `server/meetingminer/`, `web/`, `evals/`, `tools/`, `config.yaml`, migrations. Start 11.2 (store namespacing, containers, the lock's behaviour). Run `make evals-run`. Speed a test up by changing what it does. `git add -A`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Default run | `uv run --project server pytest server/tests` from the root | `addopts` selects `-m "not slow"`; the collect summary reports the split (`1381/1707 (326 deselected)` at `15fdbe2`; re-measure at the final commit); wall-clock reported | No error expected |
| Full gate | `make test` | `pytest -m ""` runs every collected test with `MM_REQUIRE_TEST_STORES=1`; every pre-`e5510c7` node id keeps its baseline outcome; the new regression tests are listed separately | Twins down → `check-test-stores` fails first (unchanged) |
| Node-id run of a `slow` module | `check-test-stores`, or a builder running `pytest server/tests/test_projections_graph.py` | The Makefile passes `-m ""`; a bare path run deselects everything and exits 5 — documented, not hidden | — |
| Child pytest spawned by a test | `test_parallel_store_safety` targets a `slow` module | The child passes `-m ""`, so its target is still collected | — |
| Unmarked test over budget | call phase > 2.0s, test passed | Reported FAILED, naming the test, its duration, the budget key, and the two remedies | — |
| `slow`-marked test over budget | any duration | Passes | — |
| Failing test over budget | assertion failed and slow | The assertion failure is reported, not the budget | — |
| `make test-fast`, Postgres down | Postgres unreachable | Postgres-backed fast tests skip with named reasons listed (`-rs`); store-free suites still run; exit reflects failures only | — |
| `make test-fast`, twins down | Neo4j/Meilisearch test twins unreachable, Postgres up | No skips: every twin-bound test is `slow` (or a collection error if unmarked), so the default selection deselects it before fixture setup; the fast set needs Postgres only. `make test` remains the gate that requires the twins (`check-test-stores`) | — |

</intent-contract>

## Code Map

- Baseline (before): `/private/tmp/claude-501/-Users-devopsterus-current-cohort-meetingminer/68d22a64-4e5e-45dd-be14-5c0cc96a7004/scratchpad/baseline/full.log` (`--durations=0`), `/private/tmp/claude-501/-Users-devopsterus-current-cohort-meetingminer/68d22a64-4e5e-45dd-be14-5c0cc96a7004/scratchpad/baseline/junit.xml` — 1,683 passed, 0 failed/skipped, 554s; per-module: `test_api_chat` 54/96.6s, `test_projections_rebuild` 39/81.9s, `test_projections_graph` 26/64.3s, `test_api_search` 41/60.5s, `test_makefile_procs` 46/51.0s, `test_projections_search` 34/46.1s, `test_projections_traversals` 32/28.5s, `test_migrations` 10/16.9s, `test_parallel_store_safety` 12/8.6s, `test_failfast` 12/6.8s, `test_augmentation` 7/6.0s, `test_projections_locks` 9/3.7s (= 322 tests, 471s). Timing tests elsewhere: `test_api_events::test_a_slow_configured_heartbeat_is_not_overridden_by_a_faster_default` 3.0s, `::test_configured_poll_cadence_is_honored` 2.5s, `test_artifact_publish::test_approve_projects_into_both_stores` 1.6s (the one `real_projection` test). Slowest remaining call: 1.3s (`test_frame_image`).
- `server/pyproject.toml:99-103` -- `[tool.pytest.ini_options]`: add `addopts = "-m 'not slow'"`, the `slow` marker, `mm_fast_test_budget_seconds = "2.0"` with rationale.
- `server/tests/conftest.py:49-51` -- `REPO_ROOT` (used at `:158`, `:298`); no `pytest_*` hooks exist. Add `pytest_addoption` (registers the ini key) and a `pytest_runtest_makereport` wrapper after the `RUN_ID` block.
- `server/tests/repo_paths.py` -- NEW: `REPO_ROOT = Path(__file__).resolve().parents[2]`; conftest imports it from here.
- `REPO_ROOT` importers (16) rewritten by `python3 /private/tmp/claude-501/-Users-devopsterus-current-cohort-meetingminer/68d22a64-4e5e-45dd-be14-5c0cc96a7004/scratchpad/rewrite_repo_root_imports.py <tests dir> --write` (dry-run verified): one-line at `test_compose_contract:15`, `test_config:22`, `test_content_root:24`, `test_drop_schema:11`, `test_failfast:18`, `test_publish_root:20`, `test_makefile_procs:27`; mixed lists at `test_ingests:23`, `test_mint_drop:42`, `test_ocr_adapter:22`, `test_parallel_store_safety:18,309,353` (309/353 are inside child-process scripts that also run with `server/tests` on `sys.path`); function-level at `test_embed_adapter:294,308`; multi-line blocks at `test_migrations:27`, `test_projections_search:48`, `test_drops_root:51`, `test_worker_runner:40`.
- `server/tests/test_makefile_procs.py:72-101` -- `_make(target, logs, tmp_path=None)` (4 sites: 295, 314, 331, 615; timeout 60) wraps `_run_make(targets, variables, env=None, timeout=180)` (25 sites). One `_make(targets, variables=None, *, logs=None, tmp_path=None, env=None, timeout=180)`; the four old sites pass `timeout=60`.
- `server/tests/test_parallel_store_safety.py:77` -- child `[sys.executable, "-m", "pytest", "-p", "cleanup_plugin", target, "-q"]` with `target` = `test_migrations.py::…` (`:104`); add `"-m", ""`.
- `infra/Makefile:82-86` `.PHONY`; `:88-96` `help`; `:272-274` `test:` (`test_compose_contract.py:61-67` parses this recipe to the first blank line and requires `check-test-stores` and `MM_REQUIRE_TEST_STORES=1`); `:285-286` `evals-test`; `:352-354` `web-test`; `:377-378` `check-test-stores` (node id in a `slow` module → `-m ""`); `:396-411` `puller-test`.
- `AGENTS.md:132-136` -- store-free suites paragraph; the fast/full paragraph follows it.
- `project-context.md` "Running and verifying" -- replace the `make test is not an iteration loop` bullet; extend the single-test bullet.
- `docs/backlog.md:14-37` -- B-1; `:311` "Removed from this list" (prose summaries of retired items).

## Tasks & Acceptance

**Execution:**
- `server/tests/repo_paths.py`, `server/tests/conftest.py`, 16 importers -- create the module; conftest and every importer take `REPO_ROOT` from it (run the rewrite script with `--write`) -- import-time only.
- `server/tests/test_makefile_procs.py` -- one `_make`; `_run_make(` sites renamed, the four `_make(x, logs, tmp_path)` sites become keyword calls with `timeout=60` -- same commands, same bounds.
- `server/pyproject.toml` -- `addopts`, `slow` marker, `mm_fast_test_budget_seconds` with rationale -- selection and budget are configuration.
- `server/tests/conftest.py` -- budget hooks: after a passed `call`, if `call.duration` > budget and no `slow` marker, set the report failed with a message naming test, duration, key, remedies -- no plugin.
- The twelve modules -- `pytestmark = pytest.mark.slow` with a one-line reason and the measured cost; `test_api_events` (2) and `test_artifact_publish` (1) -- `@pytest.mark.slow` per test with a reason.
- `server/tests/test_parallel_store_safety.py` -- child pytest gets `-m ""` -- keeps its target selected under the new default.
- `infra/Makefile` -- `test:` and `check-test-stores` pass `-m ""` (comment says why); new `test-fast` (prereqs `puller-test web-test evals-test`; recipe `pytest -q -rs`); `.PHONY`; `help` line.
- `AGENTS.md`, `project-context.md`, `docs/backlog.md` -- fast/full split, budget, the `-m ""` rule for `slow` modules; B-1 moved to "Removed from this list" with the measured numbers.
- Verification -- `--co` counts, `make test-fast` timing, `make test` once with junit, outcome diff against the baseline, budget probe.

**Acceptance Criteria:**
- Given the marks are in place, when `uv run --project server pytest server/tests --co -q` runs from the root, then the deselected count equals the number of `slow`-marked tests and the reported split is recorded against the commit it was measured at.
- Given `make test`, when it runs, then every node id that existed at `e5510c7` keeps its baseline outcome, the new regression tests are listed separately, and the `test:` contract test still passes.
- Given a throwaway unmarked test that sleeps 2.5s, when the default run executes it, then the run fails naming that test and `mm_fast_test_budget_seconds`; deleting the file restores green.
- Given `make test-fast` with the stores reachable, when it runs, then it exits 0 and its wall-clock is recorded; the `slow`-deselected count is printed by pytest.
- Given AGENTS.md and `project-context.md`, when a builder reads "Running and verifying" and the store section, then both state the fast/full split, the budget, and how to run a `slow` module by path; `docs/backlog.md` no longer lists B-1 as open.

### Review Findings — Fourth Review (2026-08-29)

- [x] [Review][Patch] Cached wrapper fixtures can hide a dynamically resolved twin from later unmarked requesters [`server/tests/fast_budget.py:164`] — fixed in `b66636a`
- [x] [Review][Patch] The `test-fast` recipe contract recognizes token-containing impostors and omits `&`, rather than pinning the one allowed pytest argv [`server/tests/test_compose_contract.py:129`] — fixed in `484f886`
- [x] [Review][Patch] Call-phase-only budgeting lacks a setup/teardown exemption regression probe [`server/tests/test_fast_budget.py:291`] — fixed in `7228d70`
- [x] [Review][Patch] Non-empty slow reasons are tested only when `reason` is absent, not empty, whitespace-only, or non-string [`server/tests/test_fast_budget.py:354`] — fixed in `7228d70`

## Spec Change Log

### 2026-08-29 — Review findings 9 and 10 (Codex `bmad-code-review`; owner decisions recorded in the report)
- **Triggering findings.** (9) The frozen contract required the after-run's outcome set and totals to equal the 1,683-test baseline while the story itself mandates permanent regression tests (24 added; one more existing test slow-marked). (10) The stores-down row promised named skips for a twin outage under `make test-fast`, but every twin-bound test is `slow` or a collection error, so the default selection deselects it before fixture setup; a twins-only outage yields zero skips.
- **Amended (owner decisions, 2026-08-29).** Always / Block If / Default and Full gate rows / ACs / Verification: outcome equality applies to node ids that existed at `e5510c7`; the named new regression tests are allowed and listed separately; snapshot totals name their revision. The stores-down row is split: Postgres-backed fast tests may skip with named reasons; twin-bound tests are deselected from `test-fast` (never widened to run them); `make test` remains the gate that requires the twins. Work moves to the rebased branch `story/11-1-review` in its worktree.
- **Known-bad state avoided.** Deleting useful regression tests to recover a stale count; documenting a skip behaviour the fast selection cannot produce.
- **KEEP.** The measured `slow` set and its reasons; the call-phase budget with configure-time validation; the two collection rules; `-m ""` at every node-id site; `test-fast` as Postgres-only; the pre-existing-node-id outcome comparison against the preserved `e5510c7` junit.

## Review Triage Log

### 2026-08-29 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 21: (high 0, medium 3, low 18)
- defer: 3: (high 0, medium 1, low 2)
- reject: 7: (high 0, medium 0, low 7)
- addressed_findings:
  - `[medium]` `[patch]` The live session never observed the `fast_budget` wiring (intent-alignment 3.5, verification-gap A) — `test_fast_budget.py` now asserts `pluginmanager.hasplugin("fast_budget")` and the ini value 2.0 in the real session (`0ecef76`).
  - `[medium]` `[patch]` The budget could not see function-scoped `projection_stores` setup, and a module dropping its `pytestmark` re-entered the fast set silently (blind #6, verification-gap B) — collection rule: an unmarked test requesting `projection_stores`/`stores_up` is a usage error listing every node id; the one such fast-set test (`test_worker_extract`) is now `slow`; a contract test pins the twelve module-level marks (`0ecef76`, `eb31e47`).
  - `[medium]` `[patch]` Budget value unvalidated: non-numeric raised per test, `0`/negative failed every test, `inf` passed the contract (blind #10, edge #1/#2/#12) — parsed once in `pytest_configure` into the config stash, finite and > 0 or a usage error; contract asserts finite > 0; `-o` override documented (`0ecef76`, `eb31e47`, `15fdbe2`).
  - `[low]` `[patch]` `--strict-markers` off, and the addopts contract compared bytes (blind #7/#8) — `--strict-markers` added; contract parses addopts with `shlex` (`0ecef76`, `eb31e47`).
  - `[low]` `[patch]` `reason=` documented but unenforced (blind #9) — collection rule with a pytester case (`0ecef76`).
  - `[low]` `[patch]` Budget message wrong under concurrent load (blind #11, verification-gap C, edge #4) — message tells the builder to re-run alone first (`0ecef76`).
  - `[low]` `[patch]` XPASS over budget would be flipped (edge #3) — `wasxfail` guard (`0ecef76`).
  - `[low]` `[patch]` Whitespace regressions at two `pytestmark` insertions (intent 3.9, blind #14, verification-gap D) — restored (`0ecef76`).
  - `[low]` `[patch]` Stale/self-contradicting counts in four documents (blind #1) — counts appear only where pinned to a commit (`15fdbe2`, `eb8bab4`).
  - `[low]` `[patch]` Docs placed the hook in conftest.py (blind #2) — corrected to `fast_budget.py` (`15fdbe2`).
  - `[low]` `[patch]` Garbled conftest comment (blind #19) — rewritten (`0ecef76`).
  - `[low]` `[patch]` `_make` collapse left 14 hand-built `LOGS`/`_tree_vars` sites and a str-target trap (blind #15, edge #9) — keyword form everywhere, precedence documented, `str` asserted (`eb31e47`).
  - `[low]` `[patch]` Contract module: inline recipe split duplicated, docstring stale (blind #16) — `_recipe` reused, docstring updated (`eb31e47`).
  - `[low]` `[patch]` No re-measurement command (blind #17) — `--durations=25` line in both docs (`15fdbe2`).
  - `[low]` `[patch]` pytester tests: `next()` without default, 0.01s probe budget, inner rootdir could climb (blind #18, edge #6/#7/#8) — named assertion, 0.05s/0.2s margins, `makeini` (`0ecef76`).
  - `[low]` `[patch]` `test-fast` without `check-client` (edge #10) — prerequisite added (`eb8bab4`).
  - `[low]` `[patch]` AGENTS.md paragraph broke the isolation narrative (blind #12) — own `## Fast loop and full gate` section (`15fdbe2`).
  - `[low]` `[patch]` Two sources for the budget default (blind #13) — docstring states the fallback's only use (`0ecef76`).
  - `[low]` `[patch]` `pytest_plugins` needs an initial conftest; bare `pytest` from the repo root errors (verification-gap E, edge #5) — invocation constraint documented (`15fdbe2`).
  - `[low]` `[patch]` Exit 5 with no clue on a by-path slow run (edge #11) — `pytest_sessionfinish` hint (`0ecef76`).
  - `[low]` `[patch]` Budget default duplicated in prose and the Makefile count unpinned (blind #1/#13) — Makefile comment pinned to a commit (`eb8bab4`).
- deferred (outside the intent's file boundary): README.md make-target table and testing section (medium); docs/project-record.md entry (low); filing the fixture-cost residue as a backlog item (low) — see frontmatter `deferred`.
- rejected: store-free suites unconditional in `test-fast` (measured 1.7s/0.7s/12.7s, documented); `REPO_ROOT` still reached via `sys.path` (the AC asked for a normal module, delivered); hook in a local plugin module vs "no plugin" (no dependency added); AGENTS.md "testing section" placement (superseded by the new section); pytester inner run executed per test (0.65s each, within budget); env-var budget override (the `-o` override is documented); apply the budget only under the fast selection (kept in the gate, message fixed).

### 2026-08-29 — External review pass (Codex `bmad-code-review`, report `review-story-11-1-2026-08-29.md`)
- intent_gap: 0
- bad_spec: 2: (high 0, medium 2, low 0) — findings 9 and 10, resolved by owner decision as spec amendments (see Spec Change Log) rather than a code re-derivation
- patch: 8: (high 0, medium 5, low 3)
- defer: 0
- reject: 0 (the reviewer dismissed 12 layer claims itself)
- addressed_findings:
  - `[medium]` `[bad_spec]` (9) Frozen totals contradicted the mandated regression tests — spec amended: outcome equality on pre-`e5510c7` node ids, named new tests allowed, totals revision-pinned.
  - `[medium]` `[bad_spec]` (10) Stores-down row promised twin skips the fast selection cannot produce — spec row split (Postgres skips vs twin deselection); Makefile help/comment, AGENTS.md, project-context.md reworded (`270b0bc`, `31ff539`).
  - `[medium]` `[patch]` (1) Wiring test pinned 2.0, defeating the documented `-o` override — asserts plugin loaded and a finite positive stash value equal to `getini` (`6451453`).
  - `[medium]` `[patch]` (2) `-k` miss printed the slow-module hint — collection hook records "every collected item was slow"; hint requires that flag, the default expression, and no `-k`; pytester cases for both paths (`6451453`).
  - `[medium]` `[patch]` (3) `test:` contract checked a substring — `make -n` argv captured and `shlex`-parsed; last `-m` must be `""`; pytester slow sentinel (`722e521`).
  - `[medium]` `[patch]` (4) `test-fast` contract could stay green with the server path narrowed — argv contract: project, exact `server/tests` path, `-rs`, no `-m` (`722e521`).
  - `[medium]` `[patch]` (5) Slow-module pin was a spoofable prefix search — `ast`-derived module-level set compared exactly both ways (`722e521`).
  - `[low]` `[patch]` (6) Invalid budgets uncovered — parametrized usage-error probes plus an accepted `3.5` (`6451453`).
  - `[low]` `[patch]` (7) XPASS exemption untested — over-budget non-strict xfail keeps XPASS (`6451453`).
  - `[low]` `[patch]` (8) Reason rule untested under default deselection — probe under `-m "not slow"` by CLI and by `addopts` (`6451453`).
- red evidence: each new regression was shown failing against the unfixed code or a deliberate mutation (Makefile `-m "" -m "not slow"`, narrowed `test-fast` path, extra/string-only module marks, validation removed, `wasxfail` guard removed, `tryfirst`→`trylast`), then restored and shown passing.

### 2026-08-29 — Re-review pass (Codex `bmad-code-review`, report `review-story-11-1-rereview-2026-08-29.md`)
- Original findings 1–10: all verified fixed (commands in the report).
- intent_gap: 0
- bad_spec: 0
- patch: 3: (high 0, medium 3, low 0) — **open**, remediation round 2 (`build-prompt-story-11-1-remediation-2-2026-08-29.md`)
- defer: 0
- reject: 0 (the reviewer dismissed 9 layer claims itself: call-phase budgeting, Postgres-down skips, module-level marking, `PYTEST_ADDOPTS` override, the `--deselect` hint edge, the fixture-cost residue)
- open_findings:
  - `[medium]` `[patch]` (1) `test-fast` prerequisites unpinned (`test_compose_contract.py:200`, `infra/Makefile:294`) — the contract proves only the server argv; deleting `web-test` (or any of `check-client`, `puller-test`, `evals-test`) from the target line leaves every contract green.
  - `[medium]` `[patch]` (2) Function-level `slow` marks outside every exact inventory (`test_compose_contract.py:280–318`) — the `ast` guard sees module-level `pytestmark` only; a fifth `@pytest.mark.slow(reason=...)` on a fast test shrinks the default set silently. Four production marks exist: `test_api_events.py:434,455`, `test_artifact_publish.py:414`, `test_worker_extract.py:1164`.
  - `[medium]` `[patch]` (3) Dynamic twin-fixture requests bypass the collection rule (`fast_budget.py:86–90`) — `item.fixturenames` is the static closure; `request.getfixturevalue("projection_stores"|"stores_up")` from an unmarked test reaches the twins. No production use today; a reachable regression.
- verdict: changes requested; no merge; status stays `in-review` / sprint `in-progress`.
- remediation round 2 (2026-08-29): all three fixed on `story/11-1-review` — (1) `ff0d536`→`7268956`, (2) `7268956`, (3) `ff0d536` + `4911c21`; see the next entry and Auto Run Result.

### 2026-08-29 — Review pass (remediation round 2, internal layers over `ba1d39e..83a2419`)
- intent_gap: 0
- bad_spec: 0
- patch: 16: (high 0, medium 5, low 11) — the three external findings plus 13 from the four internal layers
- defer: 0
- reject: 4: (high 0, medium 0, low 4)
- addressed_findings:
  - `[medium]` `[patch]` Re-review (1) `test-fast` prerequisites unpinned — `_dry_run_steps` takes the remake sequence from `make -n --debug=basic` (both GNU quote styles); `test_make_test_fast_runs_check_client_then_every_store_free_suite_before_the_fast_set` requires `check-client` first, exactly the three store-free suites (transitively — an `infra-up` would fail it), and the one whole-server pytest command last under `test-fast`; `TEST_FAST_PREREQUISITES` is the pinned tuple (`7268956`). Red: each of the four removed, a reorder, an added `infra-up` — six mutations, all failed.
  - `[medium]` `[patch]` Re-review (2) per-test `slow` marks uninventoried — `SLOW_TESTS` (four `module::test` ids) and `_decorated_slow_definitions` (an `ast` walk over decorated `def`/`async def`/`class` at module level, inside classes, and under module-level `if`/`try`/`with`; a mark anywhere in a decorator expression, so `pytest.param(marks=...)` counts; class-body `pytestmark` counts for the class; strings never do), compared both ways (`7268956`, `4911c21`). Red: an extra decorator on a fast test and the `test_api_events.py:434` decorator removed — both failed; a `pytest.param(marks=pytest.mark.slow(...))` mutation failed it too.
  - `[medium]` `[patch]` Re-review (3) dynamic twin requests bypass the collection rule — `pytest_fixture_setup` (tryfirst) fails an unmarked requester of `projection_stores`/`stores_up` before the fixture function runs, caching the failure the way pytest's own implementation does (`FixtureDef.execute` registers the post-finalizer before the hook and `finish` returns early on an empty cache, so a bare raise left a finalizer behind for the next requester to trip `assert not self._finalizers`) and tearing it down with the offending item so a later `slow` test sets a session-scoped `stores_up` up afresh (`ff0d536`). Red: under the unfixed plugin the unmarked test PASSED and the fake fixture ran (`RAN == ['stores_up']`); real-session throwaway probe: both unmarked dynamic requesters failed with the diagnostic in 0.04s, no store touched.
  - `[medium]` `[patch]` (intent-alignment, edge-case, verification-gap, blind hunter — all four) a session-scoped `stores_up` a `slow` test already set up is served from the cache with no setup for the hook to see, so under `make test` a later unmarked `request.getfixturevalue("stores_up")` passed silently — `pytest_runtest_makereport` now fails a passing unmarked test whose request resolved either twin (`Function._request._fixture_defs`), same diagnostic; probe: a slow module first, then the unmarked requester, for both fixtures at their real scopes (`4911c21`).
  - `[medium]` `[patch]` (blind hunter, edge-case) marks pytest applies at collection (`pytest.param(marks=...)`, class `pytestmark`) were outside every syntax inventory — the plugin records every collected slow-marked node id before deselection (`_SLOW_NODEIDS`); `test_every_slow_marked_item_this_session_collected_is_pinned` requires each to be in `SLOW_MODULES` or `SLOW_TESTS` (`4911c21`). Red: the `pytest.param` mutation on `test_config.py` failed it alone (`-k pinned`), naming `test_config.py::test_missing_config_file_is_fatal[1]`.
  - `[low]` `[patch]` (edge-case, blind hunter) the setup-hook diagnostic named `stores_up` for a test that asked for `projection_stores` (its dependency is resolved first) — the diagnostic names the test only, suffix `(requested at run time)`; the probe conftest now has conftest's dependency shape (`4911c21`).
  - `[low]` `[patch]` (blind hunter) `assert fixture in body` was vacuous (`_twin_rule` always prints both names) — asserts the suffix and the node id (`4911c21`).
  - `[low]` `[patch]` (blind hunter) `_requesting_item` fell back to `request.node` and disabled itself silently for session scope — raises naming the pytest version when `_pyfuncitem` is missing; the pyproject pin is what makes the private name safe (`4911c21`).
  - `[low]` `[patch]` (blind hunter) module docstring said nothing is cached while the hook docstring explained the cached failure — module docstring rewritten (`4911c21`).
  - `[low]` `[patch]` (blind hunter) a dynamic request from one of the test's own fixtures is an ERROR at setup, not FAILED — probed (`test_unmarked_via_its_own_fixture`), docs say "an error at setup, when one of its own fixtures asked" (`4911c21`).
  - `[low]` `[patch]` (blind hunter) `TWIN_SCOPES` hand-copied from conftest — `test_the_real_session_loads_fast_budget_from_conftest` asserts each twin's real scope via the session's fixture manager (`4911c21`).
  - `[low]` `[patch]` (blind hunter, verification-gap) a module-level `pytestmark` requester was exercised only by `make test` — the marked-first probe module uses `pytestmark` (`4911c21`).
  - `[low]` `[patch]` (blind hunter) nothing told an agent where the sets are pinned — contract messages name the tuple and file; AGENTS.md and project-context.md name `SLOW_MODULES`/`SLOW_TESTS`/`TEST_FAST_PREREQUISITES` (`4911c21`).
  - `[low]` `[patch]` (edge-case, blind hunter) `_dry_run_steps` returning nothing raised a bare `IndexError` — asserts with `make --version` and the first output lines (`4911c21`).
  - `[low]` `[patch]` (blind hunter) `set(targets[1:-1])` discards order without saying so; `_dry_run` docstring stale — comment states the order among the three is unconstrained and the set is exact transitively; docstring covers the `--debug=basic` case (`4911c21`).
  - `[low]` `[patch]` (blind hunter) project-context "a few tests elsewhere" — "four tests elsewhere"; AGENTS.md sentence reworded (`4911c21`).
- rejected: a make-derived sequence contract for `test:` (outside F1's scope; `test:` keeps its `_recipe` and puller-suite contracts); `from pytest import mark` / alias forms (the round-1-accepted `_is_slow_mark` convention); `rglob` for subdirectory modules (none exist; consistent with `SLOW_MODULES`); the backlog's "three timing tests … a fourth per-test mark" narrative (accurate as history; counts re-pinned instead).
- followup review: patched high 0 / medium 5 / low 11 → 3×5 + 11 = 26 ≥ 5 → `followup_review_recommended: true` (unchanged; the third external review is the contract's next step).

### 2026-08-29 — Third review pass (Codex `bmad-code-review`, report `review-story-11-1-third-review-2026-08-29.md`)
- Previous re-review findings 1–3: verified fixed for their required red cases; three narrower gaps remain.
- intent_gap: 0
- bad_spec: 0
- patch: 3: (high 0, medium 3, low 0) — **open**
- defer: 0
- reject: 10 normalized layer claims dismissed (accepted private/late-hook residual risks; caught setup exception disproved by probe; deprecated teardown path; definition-level parameter pins; no-current-impact nested/duplicate cases; prerequisite-body/Make-parser hardening outside the three actionable claims)
- open_findings:
  - `[medium]` `[patch]` (1) cached `stores_up` requester skips/xfails or has no passing call report (`fast_budget.py:194–205`) — the report hook returns before `_twins_resolved_for`, so the structural violation remains green. Red: slow seed + unmarked cached request + `pytest.skip` → `1 passed, 1 skipped`, rc 0.
  - `[medium]` `[patch]` (2) class-level slow pin is internally inconsistent (`test_compose_contract.py:413–465`) — syntax records `module::Class`, collection checks `module::Class::test`; no `SLOW_TESTS` representation satisfies both. Red helper: exact syntax pin installed, `_pinned(...::TestGroup::test_one)` → `False`.
  - `[medium]` `[patch]` (3) `test-fast` direct recipe commands are unconstrained (`test_compose_contract.py:263–279`) — appending `docker compose up -d` after pytest leaves both sequence/argv contracts green (`2 passed`), so the promised server-command-last/Docker-free property is not proved.
- verdict: changes requested; user requested a final report, so findings are left as action items; no source patch, no merge; status stays `in-review` / sprint `in-progress`.
- remediation round 3 (2026-08-29): all three fixed on `story/11-1-review` — (1) `31dec15`, (2) and (3) `4a66d2a`; see the next entry and Auto Run Result.

### 2026-08-29 — Review pass (remediation round 3, internal layers over `0296314..4a66d2a`)
- intent_gap: 0
- bad_spec: 0
- patch: 18: (high 0, medium 4, low 14) — the three external findings plus 15 from the four internal layers
- defer: 0
- reject: 6: (high 0, medium 0, low 6)
- addressed_findings:
  - `[medium]` `[patch]` Third review (1) cached twin request then skip/xfail/xpass, or from a fixture of the test's own, stayed green — the report-time check now runs on the setup and call reports of every unmarked test whose request resolved a twin, whatever outcome it earned: passed/skipped/xfailed/xpassed becomes the diagnostic naming the outcome it replaces (an error at setup when the test's own fixture asked), a failure of the test's own is kept with the diagnostic beside it. The setup hook's refusal is stashed on the item and counts as a resolved twin — the probe found a fourth bypass: an `xfail`-marked unmarked test requesting the function-scoped `projection_stores` had the hook's refusal absorbed into a green XFAIL (`31dec15`). Red under the unfixed plugin, `stores_up` cached by a slow module: SKIPPED / XFAIL / XPASS, rc 0; `projection_stores`: XFAIL.
  - `[medium]` `[patch]` Third review (2) class-level slow pin unrepresentable — `module::Class` is the one representation: the syntax inventory already produced it for a class decorator and a class-body `pytestmark`; `_pinned` now accepts the `module::Class` of any enclosing class, so one pin covers every test collected under it (parametrized, nested). `_pinned` takes the inventories as parameters; the probe collects a class-marked module in-process with `fast_budget` loaded and checks the plugin's `_SLOW_NODEIDS` against the syntax pins both ways (`4a66d2a`). Red under the old mapping: five class-marked node ids unpinned with the exact syntax pins installed.
  - `[medium]` `[patch]` Third review (3) `test-fast` direct commands unconstrained — `_direct_commands` keeps the lines make printed under the target's own remake announcement that a plain `make -n` prints too (the recipe without make's trace); `test_make_test_fast_recipe_is_the_one_whole_server_pytest_command` requires that list to be exactly the one whole-server pytest command (`4a66d2a`). Red: `docker compose up -d` appended after the pytest line → the new contract failed naming it while the two older contracts stayed green; Makefile restored by edit, diff empty.
  - `[medium]` `[patch]` (verification-gap) a Docker step chained onto the one recipe line — `cd $(ROOT) && docker compose up -d && uv run … pytest …` — passed all three `test-fast` contracts — the recipe contract also pins the command's shape: `cd <root> &&` then the pytest invocation with no `&&`, `||`, `;`, `|`, `$(` or backtick in it (`bd5fecb`). Red: the chained mutation → 1 failed, 2 passed; restored by edit, diff empty.
  - `[low]` `[patch]` (edge-case, blind hunter) refusal recognised by a substring of the longrepr — the setup hook stashes the failure object; the report check compares `call.excinfo.value` by identity (`bd5fecb`).
  - `[low]` `[patch]` (edge-case) `report.sections` is what `--show-capture` filters by name, so the diagnostic beside a self-earned failure vanished under anything but the default — it goes on the exception repr (`addsection`), which the terminal prints with the traceback (`bd5fecb`).
  - `[low]` `[patch]` (blind hunter, edge-case) `_TWIN_REPORTED` guarded an unreachable path (a failed setup report stops the call phase) and, with `_TWIN_REFUSED`, persisted across a rerun plugin's re-execution — guard removed; the refusal is cleared at teardown (`bd5fecb`).
  - `[low]` `[patch]` (blind hunter) "this replaces the test's own call outcome (xfailed)" misdescribed an absorbed refusal — "the refusal was absorbed into …" when the hook refused (`bd5fecb`).
  - `[low]` `[patch]` (blind hunter) the skip/xfail reason was dropped from the replaced report — the outcome carries its reason (`bd5fecb`).
  - `[low]` `[patch]` (blind hunter) the probe was named "cached" though half its parametrization is the refused path — renamed; the docstring says which twin covers which (`bd5fecb`).
  - `[low]` `[patch]` (blind hunter, edge-case, verification-gap — all three) the no-duplicate branch was unobserved: an unconditional section left the suite green while printing the diagnostic twice — the probe asserts the diagnostic exactly once and no section on the refusal path, and the section present beside the self-earned assertion (`bd5fecb`).
  - `[low]` `[patch]` (blind hunter) no probe for a skip raised at setup by the test's own fixture after a cached request — added, "setup outcome (skipped: …)" (`bd5fecb`).
  - `[low]` `[patch]` (blind hunter) the section title was a literal in the test — `_TWIN_SECTION` imported (`bd5fecb`).
  - `[low]` `[patch]` (edge-case) a recipe line that expands differently between the two dry runs (`$(shell date)`) dropped out of the intersection silently — a line under the target that is neither in the plain run nor make's trace fails `_direct_commands` (`bd5fecb`).
  - `[low]` `[patch]` (blind hunter) "GNU make 4.x turns `-w` on with `-C`" — `-C` turns it on; the version attribution is gone (`bd5fecb`).
  - `[low]` `[patch]` (blind hunter) "the contract after the next" — the contract is named (`bd5fecb`).
  - `[low]` `[patch]` (blind hunter) the class probe's docstring did not say the inventory already named both class forms, nor that neither is a module-level mark — it does, and asserts `_has_module_level_slow_mark` is false for the probe module (`bd5fecb`).
  - `[low]` `[patch]` (blind hunter) `_direct_commands` said "remade 0 times" for a target make never announced — its own message; docstring says why the plain run's whole output is a safe reference (`bd5fecb`).
- rejected: a run-time `add_marker("slow")` exempting a test at report time (the handoff's accepted residual risk — late marks — no action this round); `_failure_section` on an `ERROR at setup` header (the passing test proves it); a `shlex` error on an unparseable recipe line (still red, names the line); wrapping single-line docstrings (the file's convention); "docs lag" (AGENTS.md and project-context.md are edited in this round's docs commit; project-record is a recorded deferral); the intent's "three timing tests" against four `SLOW_TESTS` entries (pre-existing, told in the backlog narrative).
- intent alignment (descriptive): F1 implements the wider reading — a refused request counts as a resolved twin — because the narrow one left the `xfail`-absorbed refusal green; F3 the strict one — the recipe is exactly one command — because "no Docker/store command" by name is a denylist. Both are recorded in Design Notes. The contract's "Block If" surface (pre-`e5510c7` node ids keep their outcome) is the full gate's junit comparison.
- followup review: patched high 0 / medium 4 / low 14 → 3×4 + 14 = 26 ≥ 5 → `followup_review_recommended: true` (unchanged; the fourth external review is the contract's next step).

### 2026-08-30 — Fourth review pass and inline remediation (Codex `bmad-code-review`, report `review-story-11-1-fourth-review-2026-08-29.md`)
- intent_gap: 0
- bad_spec: 0
- patch: 4: (high 0, medium 4, low 0) — all fixed during the review (`b66636a`, `484f886`, `7228d70`)
- defer: 0
- dismiss: 13 normalized layer claims
- addressed_findings:
  - `[medium]` cached wrapper fixtures hid a dynamic twin from later unmarked cache consumers — the plugin records every active wrapper fixture definition as twin-bound for the lifetime of its cached value and clears it at post-finalization; the previously green probe now reports the unmarked consumer as an error (`b66636a`).
  - `[medium]` the `test-fast` recipe contract accepted `uv … echo pytest …` and a real pytest command followed by `& true` — the post-`cd` argv is now compared exactly with `uv run --project <server> pytest -q -rs <server/tests>`; both mutations failed before restoration (`484f886`).
  - `[medium]` call-phase-only budgeting had no setup/teardown regression probe — a pytester fixture spends 0.2s in both setup and teardown against a 0.05s budget while its fast body remains green; removing the call-phase guard made the probe fail (`7228d70`).
  - `[medium]` reason validation was tested only for an absent value — the probe now covers absent, empty, whitespace-only and non-string reasons under CLI and addopts selection; a key-presence mutation failed six cases (`7228d70`).
- verdict: **pass**. Focused contracts 60 passed; collection `1401/1727 (326 deselected)`; `make test-fast` rc 0; `make test` rc 0 with all 1727 server tests and the web production build green. No unresolved high or medium finding remains; `followup_review_recommended: false`.

## Design Notes

- Harness note: the Bash sandbox denies writes under the worktree and reads of `.env`; edit files with the Edit/Write tools, and run `git`, `pytest`, `uv` and `make` inside the worktree with the sandbox disabled (the `.env` read and `uv` cache errors are that sandbox, not the repo). Store-backed suites may run concurrently (AGENTS.md); never `make evals-run`.
- The `slow` set is defined by measurement, not by B-1's list: the story says to identify the set "from the measurement, not from memory", and NFR19 asks for seconds. B-1's seven-module premise would leave a ~7-minute default run; the store-twin suites are the cost. `test_mint_drop` stays in the fast set (2.8s / 68 tests, max 1.2s). Deviation recorded here and in the report.
- Expected fast set: 1,358 tests, ~55s of test time against live stores — Postgres-backed API/worker tests at 20–50ms each, spread across ~1,000 tests. Not "a few seconds"; the residue is fixture cost, and making fixtures cheaper changes what tests do, which this story forbids. Named as a follow-up in the report.
- Budget on the `call` phase only: per-run database creation, migrations and store wipes are fixtures and amortise; the budget guards test bodies. 2.0s sits above the fast set's slowest measured call (1.3s) and below any readiness poll or store task wait.
- `-m ""` on the CLI overrides `addopts` and an empty expression disables marker filtering — verified on pytest 9.1.1 (`-o addopts="-m 'not real_projection'"` → 1664/1 deselected; with `-m ""` → 1665).
- Round 3 decisions the next reviewer should attack: (a) the twin rule's report-time check treats the setup hook's refusal as a resolved twin, so an `xfail` mark cannot absorb it — the assumption is that a refusal a test never sees reported is the same green bypass as a cached request; (b) any non-failing report of an unmarked twin-bound test is rewritten to a failure (skip, xfail, xpass, at setup or call), and a self-earned failure is kept with the diagnostic on its exception repr — the assumption is that the structural violation outranks the outcome the test earned, and that a failure already red need not be rewritten; (c) one report per run of the item carries the diagnostic because a failed setup report stops the call phase — no guard, so a rerun plugin starts clean (the refusal is cleared at teardown); (d) a class-level mark pins as `module::Class` and covers every test collected under the class, including tests added later without a `SLOW_TESTS` edit — the same looseness a module in `SLOW_MODULES` already has; (e) `test-fast`'s recipe is exactly one command, `cd <root> && uv run … pytest …` with nothing chained — stricter than "no Docker/store command", because a denylist by name is the weaker contract; an `@echo` would fail it too, by design; (f) `_direct_commands` tells recipe lines from make's trace by intersecting the `--debug=basic` step with a plain `-n` run, with a trace regex only as the guard against a line that expands differently between the two — the `--debug=basic` announcement remains an undocumented interface (residual risk from round 2). Not verified here: GNU make 4.x (`--no-print-directory` was added for its `-C`-implied `-w`; only 3.81 is on this machine).

## Verification

**Commands:**
- `cd <worktree> && uv run --project server pytest server/tests --co -q | tail -1` -- expected: `N/M tests collected (K deselected)` with K = the `slow`-marked count; record N/M/K against the final commit.
- `cd <worktree> && time make test-fast` -- expected: exit 0; wall-clock recorded.
- `cd <worktree> && time make test` (with `--junitxml` on the server step for the diff) -- expected: green; every node id that existed at `e5510c7` keeps its baseline outcome (compare against the preserved `e5510c7` junit on pre-existing node ids); new tests listed separately.
- Throwaway `server/tests/test_zz_budget_probe.py` with `time.sleep(2.5)` -- expected: FAILED naming the test and `mm_fast_test_budget_seconds`; file deleted afterwards, run green.
- `uv run --project server pytest server/tests/test_makefile_procs.py -m ""` -- expected: 46 passed after the runner collapse.

## Auto Run Result

**Status:** done (2026-08-29). Branch `story/11-1` at `15fdbe2f430e59054a4e97698cf4641a9ef5cb54`, pushed, `origin/story/11-1` identical, working tree clean; 13 commits `95ff6ee`..`15fdbe2` on base `e5510c7`.

**Implemented.** The server suite defaults to the fast set: `server/pyproject.toml` `addopts = "-m 'not slow' --strict-markers"`, a registered `slow` marker, and `mm_fast_test_budget_seconds = "2.0"`. Twelve modules bound by the store twins, spawned processes, the projection lock or timers carry a module-level `slow` mark with a `reason=` and their measured cost; four twin- or timer-bound tests elsewhere carry per-test marks. `server/tests/fast_budget.py` (registered from conftest's `pytest_plugins`) validates the budget once, reports a passing unmarked test failed when its call phase exceeds it, enforces two collection rules (every `slow` mark has a reason; an unmarked test may not request `projection_stores`/`stores_up`), and prints a hint when the default selection deselects everything. `make test-fast` runs `check-client`, the three store-free suites and the fast set with skip reasons; `make test` and `check-test-stores` pass `-m ""`, as does the child pytest in `test_parallel_store_safety`. `REPO_ROOT` moved to `server/tests/repo_paths.py` (17 importers); `test_makefile_procs.py` has one `_make`. AGENTS.md (new `## Fast loop and full gate`), `project-context.md` and `docs/backlog.md` (B-1 retired with measured numbers) state the split.

**Files changed (35).** `server/pyproject.toml` addopts/marker/budget; `server/tests/fast_budget.py` new plugin; `server/tests/repo_paths.py` new; `server/tests/conftest.py` imports `REPO_ROOT`, registers `pytester`+`fast_budget`; `server/tests/test_fast_budget.py` new (6 tests); `server/tests/test_compose_contract.py` +18 contract tests; `server/tests/test_makefile_procs.py` runner collapse + mark; 11 other modules module-level `slow`; `test_api_events.py`, `test_artifact_publish.py`, `test_worker_extract.py` per-test marks; `test_parallel_store_safety.py` child `-m ""`; 13 modules importer rewrite only; `infra/Makefile` `test-fast`, `-m ""` in `test`/`check-test-stores`, `.PHONY`, help; `AGENTS.md`, `project-context.md`, `docs/backlog.md`.

**Review findings.** 21 patched (3 medium, 18 low), 3 deferred (README, project-record, filing the residue — outside the intent's file boundary), 7 rejected. Follow-up review: patched counts high 0 / medium 3 / low 18 → score 3×3 + 18 = 27 ≥ 5 → `followup_review_recommended: true`.

**Verification (all observed by the coordinator, worktree root, stores up).**
- Baseline at `e5510c7`: `make test`-equivalent server run 1,683 passed in 554s (9m14s), junit kept.
- `uv run --project server pytest server/tests --co -q` → `1381/1707 tests collected (326 deselected)`; with `-m ""` → `1707 tests collected`.
- `make test-fast` → rc 0, 66s wall; server step `1381 passed, 326 deselected in 48.91s`; puller 128, web 257, evals 549.
- Fast set with the twins unreachable (`MM_TEST_NEO4J_URI`/`MM_TEST_MEILI_URL` → port 1) → `1381 passed, 326 deselected`, 0 skips: the fast set needs Postgres only.
- `make test` at `15fdbe2` → rc 0, 561s wall; `1707 passed`; junit diff vs baseline: 0 outcome changes, 0 missing, 24 added (the new tests). An earlier gate run at `d36aaa6` was interrupted by another agent recreating the Docker stack mid-run (`AdminShutdown`, all containers `Up 5 minutes`); re-run clean.
- Budget probe through the real conftest (throwaway, deleted): unmarked 2.5s sleeper FAILED naming `mm_fast_test_budget_seconds`; failing sleeper kept its assertion; `slow`-marked sleeper passed under `-m ""` and was deselected by default.
- `make check-test-stores` → 1 passed; by-path `test_projections_locks.py` → `9 deselected`, rc 5, hint printed; `-m ""` `test_makefile_procs.py` → 46 passed.
- The one pytest warning in every run is the pre-existing Starlette `httpx` deprecation.

**Residual risks.** (1) The fast set is ~49s of pytest / ~66s `make test-fast`, not "a few seconds": the residue is ~1,000 Postgres-backed api/worker tests at 20–50ms each — fixture cost this story may not change; deferred for the owner to file. (2) The budget also runs under `make test`; a concurrent suite that slows a 1.3s call past 2.0s fails the gate with a message that now says to re-run alone. (3) `pytest_plugins` in `server/tests/conftest.py` means pytest must be given a path under `server/tests` or run from `server/`; a bare `pytest` from the repo root errors (documented). (4) `main` is three commits ahead of the base (story 6.7, owner runbook) with no path overlap; rebase before merge per AGENTS.md.

### Remediation after the external review (2026-08-29)

Branch `story/11-1-review` (the submitted `story/11-1` rebased onto `main` `183bdf1` by the reviewer) at `31ff5392dc6d28d4b9e116efc6b759d37d2b8521`, pushed, `origin/story/11-1-review` identical, tree clean. Four remediation commits `6451453`, `722e521`, `270b0bc`, `31ff539`.

Verification observed by the coordinator in `meetingminer-wt/11-1-review`: `test_fast_budget.py` + `test_compose_contract.py` → 41 passed; collect `1382/1708 (326 deselected)`, `-m ""` → 1708; the wiring test passes with `-o mm_fast_test_budget_seconds=3.0`; by-path slow module → hint, rc 5; `-k` miss on `test_config.py` → no hint, rc 5; `make check-test-stores` 1 passed; `make test-fast` rc 0, 65s (`1382 passed, 326 deselected in 48.85s`); twins-down server step `1382 passed`, 0 skips; `make test` rc 0, 549s, `1708 passed`; junit vs the `e5510c7` baseline on pre-existing node ids: 0 changed, 0 missing; 25 new — 16 `test_fast_budget`, 8 `test_compose_contract` (this story), 1 `test_extraction_core` (story 6.7 on `main`).

Known for the integrator: `main` is now `a22d67c`; a trial merge conflicts on `infra/Makefile` by proximity only (both branches add to `.PHONY` and `help`: `test-fast` here, `check-reviews` on main) — resolve by union. Status: awaiting re-review (`review-prompt-story-11-1-rereview-2026-08-29.md`); sprint status stays `in-progress`.

### Re-review result (2026-08-29)

`review-story-11-1-rereview-2026-08-29.md`: **changes requested** — all ten first-round findings verified fixed; three new medium patch findings (see Review Triage Log, re-review pass). Reviewer's gate at `31ff539`: 41 contract tests; `make test-fast` 1382/326 deselected in 1m04; `make test` 1708 passed in 9m17; e5510c7 baseline 0 missing / 0 changed / 25 added. Next: remediation round 2 on `story/11-1-review` per `build-prompt-story-11-1-remediation-2-2026-08-29.md` (rebase onto `a22d67c` first; Makefile `.PHONY`/`help` union), then a third review. Status: `in-review`; sprint `in-progress`; round 2 dispatched by the owner 2026-08-29 ~22:00.

### Remediation round 2 (2026-08-29)

Branch `story/11-1-review` rebased onto `main` `28ea43d` (6.6 had landed; the handoff's `a22d67c` was stale by three commits) — `infra/Makefile` `.PHONY` union resolved by hand, no other overlap, rebased head `ba1d39e` force-pushed with lease; 41 contract tests and `1382/1708` unchanged there. Final head **`02963147d0556f8770b9401eb5db8999f128d73f`**, pushed, `origin/story/11-1-review` identical (`0	0`), tree clean. Five commits `ba1d39e..0296314`: `ff0d536` F3 hook + probes; `7268956` F1 + F2 contracts; `83a2419` docs; `4911c21` internal-review patches (report-time twin check, pinned-set guard, probes, diagnostics); `0296314` count re-pin.

Files changed this round: `server/tests/fast_budget.py` (`pytest_fixture_setup` backstop; report-time twin check in the makereport wrapper; `_SLOW_NODEIDS`; `_twin_rule`/`_requesting_item`; docstring), `server/tests/test_fast_budget.py` (+4 tests: unmarked-first and marked-first dynamic-request probes × both twins; real scopes pinned), `server/tests/test_compose_contract.py` (+3 tests: `test-fast` prerequisite sequence, per-test slow inventory, every slow-marked item pinned; `_dry_run`/`_server_pytest_words`/`_dry_run_steps`, `_slow_pytestmark_in`, `_both_ways`), `AGENTS.md` and `project-context.md` (run-time twin check; where the sets are pinned), `infra/Makefile` and `docs/backlog.md` (counts re-pinned to `4911c21`; B-1 paragraph names the run-time check).

Verification, all observed by the coordinator in `meetingminer-wt/11-1-review`, stores up, no Docker restart:
- `uv run --project server pytest server/tests/test_fast_budget.py server/tests/test_compose_contract.py -m "" -q` → **48 passed** (was 41), 1 warning; re-run after the pin commit: 48 passed.
- `pytest server/tests --co -q` → **`1389/1715 tests collected (326 deselected)`**; `-m ""` → **1715**. The seven new tests are all in fast modules; the deselected count is unchanged.
- `pytest -m "" server/tests/test_makefile_procs.py -q` → 46 passed. `make check-test-stores` → 1 passed.
- `time make test-fast` at `4911c21` → **rc 0, 68s wall**: puller 128 subtests ok, web 291 passed (16 files; 6.6's additions), evals 549, server **`1389 passed, 326 deselected in 49.42s`**.
- `time make test` at `4911c21` (`PYTEST_ADDOPTS=--junitxml=…`) → **rc 0, 562s wall**: puller 128, web 291, evals 549, check-test-stores 1, server **`1715 passed, 1 warning in 540.34s`**, web production build ok. Junit vs the preserved `e5510c7` baseline (1683 nodes): shared 1683, **0 changed, 0 missing, 32 added** — 20 `test_fast_budget`, 11 `test_compose_contract`, 1 `test_extraction_core` (6.7 on `main`). An earlier `make test` at `83a2419` (rc 0, 556s) is superseded: its files were patched mid-run.
- Twins unreachable (`MM_TEST_NEO4J_URI`/`MM_TEST_MEILI_URL` → port 1): `1389 passed, 326 deselected`, 0 skips, 50s.
- Red evidence: every new regression shown failing first — F3 against the unfixed plugin (unmarked test PASSED, fake fixture ran) and in a real-session throwaway probe; F1 six Makefile mutations; F2 an extra decorator, a removed decorator, a `pytest.param(marks=…)`; the pinned-set guard alone on the `pytest.param` mutation. Each mutation restored from saved bytes, `git diff` empty, module green again.
- The one warning in every run is the pre-existing Starlette `httpx` deprecation. `make check-reviews` from the main checkout passes.

Residual risks: (1) `_requesting_item` and `_twins_resolved_for` read `request._pyfuncitem` and `Function._request._fixture_defs` — private, stable across pytest 8–9, pinned in `server/pyproject.toml`; both raise or fail rather than fall back. (2) The `--debug=basic` remake announcement is not a documented interface; the pattern covers the 3.81 and 4.x quote styles, and no match fails with `make --version` and the output's first lines. (3) A `slow` mark added by a `pytest_collection_modifyitems` hook that runs after the plugin's tryfirst hook is outside `_SLOW_NODEIDS` (no such hook exists). (4) The exact prerequisite set is transitive: a prerequisite of a prerequisite would fail the `test-fast` contract, by design.

Not done, per the contract: no merge, no status flip (`status: in-review`, sprint `in-progress`), `sprint-status.yaml` untouched, no re-review prompt written. **Awaiting the third review.**

### Third review result (2026-08-29)

`review-story-11-1-third-review-2026-08-29.md`: **changes requested** — remediation round 2 passes its normal gate and fixes the three prior findings in their demonstrated cases, but three new medium patch findings remain (see Review Triage Log): cached twin requests on non-passing/setup paths remain green, class-level slow marks have no consistent exact pin, and direct commands appended to `test-fast` are not constrained by its sequence contract. Reviewer evidence at reviewed head `0296314`: 48 contract tests passed; collection `1389/1715 (326 deselected)`; `make test-fast` passed (server 1389/326 in 49.84s); three adversarial probes reproduced the gaps. The coordinator's 1715-test full gate was accepted as handoff evidence and not repeated after blocking findings were confirmed. Status remains `in-review`; sprint remains `in-progress`; no merge.

### Remediation round 3 (2026-08-29)

Branch `story/11-1-review`, base unchanged (`main` still `28ea43d`, no rebase). Final head **`2ce91b3`**, pushed, `origin/story/11-1-review` identical (`0	0`), worktree and main checkout clean. Four commits `79fcb61..2ce91b3`: `31dec15` F1 plugin + probes; `4a66d2a` F2 + F3 contracts; `bd5fecb` internal-review patches (chained-command shape, refusal by identity, diagnostic on the exception repr, teardown clearing, reasons, probe coverage, contract-file docstrings); `2ce91b3` docs and count re-pin to `bd5fecb`.

Files changed this round: `server/tests/fast_budget.py` (report-time twin check at setup and call whatever outcome the test earned; `_TWIN_REFUSED` stash of the setup hook's failure; `_twin_bound`/`_earned_outcome`/`_add_section`/`_twin_failure`; docstring), `server/tests/test_fast_budget.py` (+2 tests: `test_an_unmarked_twin_request_is_failed_whatever_outcome_the_test_earned` × both twins over a seven-test probe), `server/tests/test_compose_contract.py` (+2 tests: the class-level pin probe, the one-command recipe contract; `_direct_commands`, `_MAKE_TRACE`, `_SHELL_CHAINING`; `_pinned` accepts an enclosing class's pin and takes the inventories as parameters; `_dry_run` passes `--no-print-directory`), `AGENTS.md`, `project-context.md`, `infra/Makefile` (comment count only), `docs/backlog.md` (B-1 counts and measurement re-pinned).

Verification, all observed by the coordinator in `meetingminer-wt/11-1-review`, stores up, no Docker restart:
- `uv run --project server pytest server/tests/test_fast_budget.py server/tests/test_compose_contract.py -m "" -q` → **52 passed** (was 48), 1 warning.
- `pytest server/tests --co -q` → **`1393/1719 tests collected (326 deselected)`**; `-m ""` → **1719**. The four new tests are in fast modules; the deselected count is unchanged.
- `pytest -m "" server/tests/test_makefile_procs.py -q` → 46 passed. `make check-test-stores` → 1 passed.
- `time make test-fast` at `bd5fecb` → **rc 0, 1:06 wall**: puller 128, web 291, evals 549, server **`1393 passed, 326 deselected in 48.57s`** (at `4a66d2a`: 1:07, 49.16s).
- Twins unreachable (`MM_TEST_NEO4J_URI`/`MM_TEST_MEILI_URL` → port 1) at `bd5fecb`: `1393 passed, 326 deselected`, 0 skips, 48.7s.
- `time make test` at `2ce91b3` (`PYTEST_ADDOPTS=--junitxml=…`) → **rc 0, 9:13 wall**: puller 128, web 291, evals 549, check-test-stores 1, server **`1719 passed, 1 warning in 532.08s`**, web production build ok. Junit vs the preserved `e5510c7` baseline (1683 nodes): shared 1683, **0 changed, 0 missing, 36 added** — 22 `test_fast_budget`, 13 `test_compose_contract`, 1 `test_extraction_core` (6.7 on `main`).
- Red evidence, each new regression first shown against the unfixed behaviour or a mutation: F1 under the unfixed plugin with `stores_up` cached by a slow module → SKIPPED / XFAIL / XPASS, rc 0, and with `projection_stores` → XFAIL (the fourth bypass); F2 under the old `_pinned` with the exact syntax pins → five class-marked node ids unpinned; F3 `docker compose up -d` appended → new contract failed, two older contracts green; the chained `cd … && docker compose up -d && uv run … pytest …` → 1 failed, 2 passed. Both Makefile mutations restored by edit, `git diff` empty.
- The one warning in every run is the pre-existing Starlette `httpx` deprecation. `make check-reviews` from the main checkout passes.

Residual risks: (1) unchanged from round 2 — `_pyfuncitem`, `Function._request._fixture_defs` and the `--debug=basic` announcement are private or undocumented, pinned by `server/pyproject.toml` and the trace regex; a `slow` mark added after collection (a later `pytest_collection_modifyitems` hook, `add_marker` at run time) is outside `_SLOW_NODEIDS` and the report-time exemption reads `get_closest_marker` — accepted, no such code exists. (2) GNU make 4.x not exercised (`--no-print-directory` is for its `-C`-implied `-w`; only 3.81 here). (3) `_direct_commands` runs `make -n` twice per call; a recipe line that expands differently between them fails the contract by design. (4) The one-command recipe contract fails on any second line, `@echo` included, by design.

Not done, per the handoff: no merge, no status flip (`status: in-review`, sprint `in-progress`), `sprint-status.yaml` untouched, no re-review prompt written. **Story 11-1 awaits its fourth review.**

### Fourth review and inline remediation (2026-08-30)

Review branch `story/11-1-fourth-review` was cut from submitted head `2ce91b3` against `main` `28ea43d`. The report skeleton and findings were landed first (`cea3bcb`, `23d401c`), then all four accepted patches landed as `b66636a` (cached wrapper twin propagation), `484f886` (exact `test-fast` argv), and `7228d70` (phase and reason regression probes), each pushed before the final gate.

Verification observed in `meetingminer-wt/11-1-fourth-review` at `7228d70`, stores healthy:
- `test_fast_budget.py` + `test_compose_contract.py` → **60 passed**; `test_makefile_procs.py` → **46 passed**.
- Collection → **`1401/1727 tests collected (326 deselected)`**; `-m ""` → **1727**.
- `make check-test-stores` → **1 passed**; `make check-reviews` → pass.
- `time make test-fast` → **rc 0, 70.66s wall**: puller 128, web 291, evals 549, server **`1401 passed, 326 deselected in 51.17s`**.
- `time make test` → **rc 0, 568.70s wall**: puller 128, web 291, evals 549, check-test-stores 1, server **`1727 passed, 1 warning in 546.51s`**, web production build green. Docker reported all five existing containers healthy and did not recreate them.
- Mutation evidence: the exact-argv contract rejected both `uv … echo pytest …` and trailing `& true`; removing the call-phase guard failed the setup/teardown probe; weakening `_has_reason` to key presence failed six invalid-reason cases. The original cached-wrapper probe was green at `2ce91b3` (`3 passed`) and stopped the unmarked consumer after `b66636a` (`2 passed, 1 error`).
- Sole warning: the pre-existing Starlette `httpx` deprecation.

**Verdict:** passed. Story status `done`, sprint story status `done`, no re-review required.
