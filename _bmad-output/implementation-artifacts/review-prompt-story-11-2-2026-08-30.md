# Review handoff — Story 11-2, Per-Run Store Isolation

## REQUIRED OUTPUT — read this before anything else

**Report file (mandatory):**
`_bmad-output/implementation-artifacts/review-story-11-2-2026-08-30.md`

**Finding structure** — one entry per finding:
- **Location** — `path:line`
- **Severity** — high | medium | low
- **Finding** — one sentence stating the defect
- **Evidence** — what you read or ran that proves it
- **Suggested direction** — what a fix would have to achieve (do not implement it)

**Report findings, do not fix.** You review; the builder remediates.

**REPORT-FIRST.** Before reading a single line of code: create the report file as a skeleton (scope, the exact range below, an empty `## Findings` section), `git add` it and commit it. Then append each finding as you confirm it and commit incrementally. Six reviews in this repository were completed as terminal text and never filed because the file was left to the end; a crashed or closed session must lose prose, never the artifact.

**Closeout check.** Before reporting completion, run `make check-reviews` from the repository root — it fails while any dispatched review, including this one, lacks a committed report — and state the SHA carrying the report's final version. A review reported in the terminal but not filed does not exist.

---

## Repository, branch, range

- Repository: `/Users/devopsterus/current/cohort/meetingminer` — **do not review in the main checkout**; make your own: `make worktree STORY=11-2-review BASE=story/11-2` (this provisions a private Docker stack for you, which is the feature under review; bootstrap it with `make bootstrap`).
- Branch: `story/11-2` (pushed; `origin/story/11-2` identical at `fa86b86`).
- Review range: `de0fc08..fa86b86` (`de0fc0816c26a8131fdc153368719e6f3808f40e` is `main`; the branch is based on it, no rebase pending).

Commits in the range, oldest first:

| Revision | Subject |
|---|---|
| `b6fac36` | infra: per-worktree stack allocator, renderer and pruner; compose interpolates project, container names and host ports |
| `104fc2f` | config: merged_env reads .env.worktree after .env; MM_POSTGRES_PORT/MM_NEO4J_BOLT_PORT/MM_MEILI_PORT repoint the stores; MM_PROJECTION_LOCK_KEY (B-14) |
| `056d70b` | make: include .env.worktree, -p the stack, per-checkout store probes, worktree provisions and tears down a private stack, test-db-prune sweeps orphans |
| `69d7edb` | docs: per-worktree stacks replace the shared-store rule; B-14 retired; B-35 files the fixed api/web ports; AD-10 admits the stack to the environment |
| `d70c790` | docs: evals-run comment and the glossary's worktree entry follow the per-stack rule |
| `933ec73` | test: story 11.2 — worktree provision, bad slug and remove rows at the Makefile level |
| `868ff0f` | test: story 11.2 — test_migrations subprocesses target the port their config copy names |
| `c858e66` | docs: story 11.2 — record the per-stack memory of the worktree stacks and the concurrent-run timing |
| `bb3fe58` | story 11.2 review: stack keys only in .env.worktree, pruner safety and --project sweep, strict port parsing, linked-worktree refusal |
| `a352ee0` | story 11.2 review: worktree starts the new stack through the invoking Makefile; explicit stack env for compose; check-env and worktree-provision; stale-stack sweep |
| `fa86b86` | story 11.2 review: docs follow the stack-keys-only rule, the linked-worktree refusal and the per-stack lock; AD-10 in one statement; B-14 closure dated; B-35 in order |

Every commit in the range belongs to this story; none belongs to another story.

## The spec

`_bmad-output/implementation-artifacts/spec-11-2-per-run-store-isolation.md` (local process record, not in git).

- **Frozen intent** (do not critique as a choice; critique the implementation against it): the `<intent-contract>` block — Intent, Boundaries & Constraints, and the I/O & Edge-Case Matrix — and the story's acceptance criteria in `_bmad-output/planning-artifacts/epics.md` (Story 11.2, five Given/When/Then clauses plus the "Not built" paragraph).
- **Planner work you may attack**: Code Map, Tasks & Acceptance, Design Notes, Verification, and the Review Triage Log / Auto Run Result — the plan's choices, not the owner's.

## Architecture authority

`docs/architecture.md`:
- **AD-9** (compose runs only the stateful stores; api, worker and dev server on the host) — a per-worktree stack must not move any host process into a container.
- **AD-10** (one config file drives everything) — amended in this range: environment variables carry secrets, the two roots, and a checkout's private-stack name and host ports, applied by the loader to the configured endpoints. Check the amendment is one coherent statement and that the code does no more than it says (ports only; host, scheme and credentials stay in `config.yaml`/`.env`).
- **AD-4** (projections have exactly one writer) and the invariant "single writer per store class, proven not asserted" — the import-inspection and AST tests must still hold; nothing new opens a store client outside `projections/`.
- **AD-2** (Postgres is the sole database of record) — a wiped private stack is recoverable by rebuild; nothing in the range makes a graph or index authoritative.
- Invariants "fail closed, fail named, fail before writing" and "every threshold is configuration; the config model forbids unknown keys".

`AGENTS.md` sections "Work in a git worktree", "Each worktree has its own stores; what is still shared", and "Fast loop and full gate" (the `slow` set, `TEST_FAST_PREREQUISITES` and the one-command `test-fast` recipe are pinned in `server/tests/test_compose_contract.py`; a new store-backed module would have to join `SLOW_MODULES`).

## Scope

In scope (the story's file boundary, all in the range): `infra/docker-compose.yml`, `infra/Makefile`, `infra/worktree_stack.py` (new), `server/meetingminer/config.py`, `server/meetingminer/projections/locks.py`, `server/tests/conftest.py`, `server/tests/test_worktree_stack.py` (new), `server/tests/test_config.py`, `test_compose_contract.py`, `test_makefile_procs.py`, `test_migrations.py`, `test_parallel_store_safety.py`, `test_projections_locks.py`, `test_projections_search.py`, `test_api_search.py` (docstring), `.env.example`, `AGENTS.md`, `CLAUDE.md`, `README.md`, `project-context.md`, `docs/architecture.md` (AD-10 only), `docs/backlog.md`, `docs/glossary.md`, `.claude/skills/integrate/dispatch.md`.

Out of scope — do not file these:
- Per-worktree api/web ports (`API_PORT` 8000 / `WEB_PORT` 5173): filed as backlog B-35 by the story; the intent's ACs cover stores only.
- `make evals-run` staying serial and the evals documentation: story 11.3.
- A per-session ephemeral Neo4j container or a Meilisearch index prefix: excluded by the intent's "Not built" paragraph.
- `docs/project-record.md`: written at integration by repository convention (recorded as deferred in the spec).
- Capping Neo4j/Meilisearch memory in compose: the intent asks to measure and document, which the range does.
- Anything under `web/`, `tools/`, `evals/`, `config.yaml`, migrations.

## Design decisions to attack (choice + the assumption it rests on)

1. **A generated `.env.worktree` beside the symlinked `.env`, read by three readers** (Makefile `-include`, compose second `--env-file`, loader `merged_env`) — assumes the same `KEY=value` lines mean the same to all three, and that "process env > `.env.worktree` > `.env`" is enforced identically (the Makefile snapshots the environment before the include and passes the resolved values to compose explicitly so a blank export cannot make compose fall to a default).
2. **Store overrides are ports only** (`MM_POSTGRES_PORT`, `MM_NEO4J_BOLT_PORT`, `MM_MEILI_PORT`), applied to `config.yaml`'s endpoints by `_apply_stack_overrides` — assumes host, scheme and credentials never need to differ per worktree, and that a `config.yaml` endpoint always has a host (`_with_port` refuses otherwise).
3. **Key rules in `merged_env`**: any key outside the stack set in `.env.worktree` is a `ConfigError`, and a stack key in `.env` is a `ConfigError` — assumes no legitimate `.env` carries `MM_STACK_NAME`/`MM_*_PORT`, and that the set is spelled identically in `infra/worktree_stack.py` (`STACK_KEYS`) and `config.py` (`WORKTREE_ENV_KEYS`), which only the rendered-file round-trip test pins.
4. **Deterministic port allocation** (`crc32(slug) % 400` → base 20000–23990 step 10; seven ports base+1..+7; a bind probe plus every sibling's declared ports count as taken; an `flock` around allocate+write) — assumes 127.0.0.1 binds reflect what compose will publish and that siblings live under one `meetingminer-wt/` root.
5. **Ownership for the orphan sweep is directory existence**: compose's `working_dir` label (containers) or `<WT_ROOT>/<slug>` (volumes only, and only when every volume is one of our seven names), plus any sibling `.env.worktree` naming the project — assumes a hand-deleted directory means "gone" and that no foreign compose project uses our prefix with our volume names. A run killed mid-way inside a still-existing worktree keeps its stack by design.
6. **`make worktree` brings the new stack up through the invoking checkout's Makefile and compose file** (`ENVFILE`/`WT_ENVFILE`/`COMPOSE_PROJECT_DIR` overrides, `--project-directory <wt>/infra`, stack variables unset for the sub-make) — assumes compose's `working_dir` label follows `--project-directory` (verified live) and that the worktree's own Makefile, once on a post-11.2 ref, derives the same `-p` and ports from the same file.
7. **A linked worktree without `.env.worktree` is refused** by `check-env` (keyed on `$(ROOT)/.git` being a file and `$(ROOT)/.env.worktree` absent — deliberately not `$(WT_ENVFILE)`, which tests override) and at conftest import — assumes "silently on the main stack" is worse than a refusal that names `make worktree-provision`, and that no legitimate flow runs store targets in a linked worktree on the main stack.
8. **`MM_PROJECTION_LOCK_KEY`** replaces the URL-derived lock key, validated `[A-Za-z0-9._-]{1,64}`, process-wide — assumes only the B-14 test sets it; an exporting shell re-keys `rebuild` and the worker (documented).
9. **`WT_ROOT` from `git rev-parse --path-format=absolute --git-common-dir`** (lazy, `$(error)` when empty) — assumes git ≥ 2.31 everywhere this Makefile runs; the `$(error)` branch has no test.
10. **Stack pruning as a second line of `test-db-prune`**, not inside the `PRUNE_TEST_DBS` block — assumes the block's exec-with-fakes test (`test_parallel_store_safety.py`) must keep its shape; the stack sweep runs even when the database prune fails and the target exits non-zero if either failed.
11. **Memory is documented, not capped** — the measured figures live only in `AGENTS.md` (other docs point there); assumes the OrbStack VM's allocation (23.5 GiB) is the operator's dial, not compose.

## History a reviewer needs

- The first full run in the worktree (at `d70c790`) failed exactly one test, `test_migrations.py::test_worker_exits_1_on_unreachable_database`: the worktree's `MM_POSTGRES_PORT` overrode the test's deliberately unreachable port, and the success-path copies of `config.yaml` carried the main checkout's port. `868ff0f` makes the config copy carry the checkout's effective port unless a test asks for another and pins `MM_POSTGRES_PORT` in the subprocess env. This is the one place in the range where the new precedence changed an existing test's meaning — look for others (`MM_CONFIG_PATH` users, `evals/conftest.py`'s `load_config()`).
- The probe worktrees used for measurement (`11-2-probe`, `11-2-rm`, `11-2-old`) and their branches were removed after the runs; the main checkout's stack (`meetingminer`, ports 5433/7474/7687/7700/7475/7688/7701) was never touched. `story/11-2`'s own stack is `meetingminer-11-2` on 21761–21767.
- The range includes an in-run review pass (four layers) whose 32 patches landed as `bb3fe58`, `a352ee0`, `fa86b86`; its triage is in the spec's Review Triage Log. Two of them were high severity (a pre-11.2 worktree attaching the main stack; a linked worktree silently on the main stack) — verify the fixes, not just their tests.

## Verification baseline (observed 2026-08-30 in the `11-2` worktree, its stack up)

- `make test` at `fa86b86` → rc 0, **1849 passed** in 578.68s (wall 10m00s), web build green, 0 `ProjectionLockedError`, sole warning the pre-existing Starlette `httpx` deprecation.
- Two worktrees running `make test` at once (`868ff0f`): both rc 0, 1806 passed each, wall 9m27s / 9m31s against 9m49s alone; 0 lock errors in either log.
- `uv run --project server pytest server/tests/test_worktree_stack.py server/tests/test_config.py server/tests/test_compose_contract.py -q` → 181 passed.
- `uv run --project server pytest -m "" server/tests/test_makefile_procs.py -q` → 63 passed (~61s).
- `uv run --project server pytest -m "" server/tests/test_projections_locks.py server/tests/test_parallel_store_safety.py server/tests/test_migrations.py -q` → 32 passed (10 of them `test_migrations`).
- `uv run --project server pytest server/tests --co -q | tail -1` → `1497/1849 tests collected (352 deselected)`.
- `make check-test-stores` → 1 passed (against the worktree's twins).
- Live: `make worktree STORY=<x> BASE=story/11-2` and `BASE=de0fc08` each brought up a private stack; `make worktree-remove` removed checkout, stack and volumes; `make test-db-prune` after `rm -rf` of a worktree removed its stack and skipped the owned one; `.env.worktree` renamed away → `make check-env` exits 1 and pytest refuses at conftest import, both naming `make worktree-provision`.
- `docker stats --no-stream`, idle: main 2.0 GiB, worktree stacks 1.87 / 1.78 GiB; Docker VM 23.5 GiB.

A skip, an error, or a count below these during your review is a finding, not noise. Store-backed suites may run while other agents' suites run (each checkout has its own stack); never run `make evals-run`.
