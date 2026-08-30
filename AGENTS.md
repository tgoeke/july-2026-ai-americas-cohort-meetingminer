# Agent operating rules — MeetingMiner

Read this before touching the repository. It governs every agent working here,
whichever tool is driving (Claude Code, Codex, or a BMad skill). It is about
*how* to work in this tree, not what to build — that lives in
[docs/architecture.md](docs/architecture.md), with what was built recorded in
[docs/project-record.md](docs/project-record.md).

## Committing and pushing

**Commit and push without asking.** No agent needs permission to `git commit`
or `git push`. This is a deliberate project rule and it overrides any default
in your harness that says otherwise.

**Commit early and often.** Do not hold a finished unit of work in the working
tree waiting for the end of your run. More than one agent works this repository
at a time, and uncommitted work is the only work that can be destroyed. This has
already happened once: a tree-wide reset by one agent wiped another agent's
finished fix and its tests.

- Commit each coherent unit as it completes, not as one commit at the end.
- Push when the branch is in a state another agent could usefully build on.
- Never commit secrets. `.env` is gitignored; keep it that way.

## Never reset a tree you do not exclusively own

The working tree is shared unless you are in your own worktree (below).

- **Never** run `git checkout -- .`, `git reset --hard`, `git stash` over the
  whole tree, or `git clean` outside your own worktree. Another agent's
  uncommitted work is invisible to you and these commands destroy it silently.
- **Never** `git add -A` / `git add .`. Stage the specific paths you changed.
- Before committing, run `git status --short` and confirm every staged path is
  one you actually touched. Leave everything else alone.
- If you need a clean baseline, get it by creating a worktree — never by
  reverting the shared tree.

## Work in a git worktree

Each concurrent piece of work gets its own worktree, its own branch, and its
own Docker stack, so two agents never share a checkout or a store.

```bash
make worktree STORY=1-12          # ../meetingminer-wt/1-12, branch story/1-12, stack meetingminer-1-12
cd ../meetingminer-wt/1-12
make bootstrap                    # per-worktree venv + node_modules (one-time)
```

`make worktree` also writes the worktree's `.env.worktree` — its compose
project name and the seven host ports allocated for it (a slug matches
`[a-z0-9][a-z0-9_-]*`; compose rejects `.` in a project name) — sweeps a
stale stack of that name left by a hand-deleted worktree, and brings the new
stack up through the *invoking* checkout's Makefile and compose file, so a
worktree checked out from a pre-11.2 ref cannot start the main stack. Docker
down: the worktree and the file stay, store-backed tests there skip with
named reasons until the stack is up, and the error names
`cd <worktree> && make infra-up`. If the file could not be written,
`make worktree-provision` in that worktree writes it and starts the stack.
`BASE=<ref>` branches from something other than `main`. When the work is
done and pushed, remove it:

```bash
make worktree-remove STORY=1-12   # removes the checkout, then its stack and volumes
```

`make worktree-list` shows what exists; `make worktree-prune` removes every
clean worktree already merged into `origin/main`, stack included. Worktrees
live in `../meetingminer-wt/` — a sibling of the main repo, deliberately
outside it, so no `.gitignore` entry is needed and no tooling walks into
them; `make worktree` run from inside a worktree places its siblings there
too.

Notes that matter:

- `config.yaml` is tracked, so it comes with the worktree. `.env` is not — the
  target symlinks the main checkout's `.env` so secrets and both storage roots
  — `MM_CONTENT_ROOT` and `MM_DROPS_ROOT` — are shared rather than re-entered.
- `.env.worktree` is generated, gitignored (the `.env.*` rule), and never
  hand-edited. It carries stack keys only — `MM_STACK_NAME`, the seven
  `MM_*_PORT`s, `MM_TEST_NEO4J_URI`, `MM_TEST_MEILI_URL` — and the loader
  refuses any other key there (a secret cannot be overridden from it) and
  refuses the stack name or a port key in `.env` (the Makefile never reads
  them from there). `infra/Makefile` (`-include`) and `docker compose` (a
  second `--env-file`) read its stack keys; the loader reads it after `.env`
  (`merged_env`: `.env`, then `.env.worktree`, then the process environment,
  a blank process value never masking a file value). A linked worktree
  without the file is refused by name — `make check-env` and the test
  session's import both stop and point at `make worktree-provision` —
  rather than silently running on the main checkout's stack.
- `server/.venv` and `web/node_modules` are gitignored, so each worktree needs
  its own `make bootstrap`. That is the price of isolation; pay it once.
- The worker's pidfile is already keyed on the checkout path, so a worker
  started in a worktree does not collide with one started in the main checkout.
  The api (`:8000`) and web (`:5173`) ports are still fixed in `infra/Makefile`,
  so `make up` in a worktree collides with another checkout's api and web
  (backlog B-35). Stores are private; the host processes are not yet.

## Each worktree has its own stores; what is still shared

Every checkout has its own compose stack: the three dev stores (Postgres,
Neo4j, Meilisearch) plus the two disposable **test-store twins** (neo4j-test,
meilisearch-test) that exist so the projection test suites can wipe stores
without emptying the developer's live corpus. The main checkout's stack is
compose project `meetingminer` on the fixed ports (5433, 7474/7687, 7700;
twins on 7475/7688 and 7701) with container names `meetingminer-<service>` —
unchanged, and its corpus volumes are never renamed, recreated or removed. A
worktree's stack is project `meetingminer-<slug>`: containers
`meetingminer-<slug>-<service>`, volumes `meetingminer-<slug>_<volume>`, on
seven ports allocated from 20000–23999 (`infra/worktree_stack.py`: a base
hashed from the slug, stepping to the next base when a port is bound or
declared by a sibling's `.env.worktree`). One compose file serves every
stack: its project name, container names and host ports interpolate
`MM_STACK_NAME` and the `MM_*_PORT` variables with today's values as the
defaults.

**Consequence: server suites, rebuilds and workers in different worktrees
never contend; one eval run at a time.**

- A store-backed suite runs against its own checkout's stack. The loader
  applies the private Postgres port; the session `app_config` in
  `server/tests/conftest.py` repoints Neo4j and Meilisearch at the twins
  named by `MM_TEST_NEO4J_URI` / `MM_TEST_MEILI_URL` from `.env.worktree`
  (the process environment still wins; the main checkout defaults to
  `bolt://localhost:7688` / `http://localhost:7701`); Postgres tests keep
  their per-run database (`RUN_ID`). When the twins are down the store-backed
  tests skip with a named reason that includes the resolved URLs; they never
  fall back to the dev endpoints.
- The projection file lock (`server/meetingminer/projections/locks.py`) lives
  in the system temp dir keyed by the store URLs, so two checkouts on
  different ports hold different locks and never wait on each other. Two
  writers of the same endpoints — two sessions in one checkout, or a rebuild
  and the worker — still queue on one file, bounded by
  `MM_PROJECTION_LOCK_TIMEOUT_SECONDS` (default 300s); the loser of a
  timed-out wait gets a named `ProjectionLockedError`, never a torn store.
  `MM_PROJECTION_LOCK_KEY` replaces the derived key with a named one
  (`[A-Za-z0-9._-]{1,64}`, else a `ConfigError`). It is process-wide — a
  shell that exports it re-keys `rebuild` and the worker too — and exists
  only for `test_parallel_store_safety`'s lock-timeout test, which must own
  a lock nobody else can hold (B-14, closed).
- **`make rebuild` is single-flight per stack.** It takes the same file lock
  first, then the Postgres advisory lock. Never start two rebuilds against
  one stack expecting them to interleave.
- `make test-db-prune` sweeps what a `SIGKILL`ed run or a hand-deleted
  worktree left: per-run databases with no live owner (it refuses any with a
  live backend), then worktree stacks — `meetingminer-<slug>` projects whose
  checkout directory no longer exists get `down -v`, volumes included. A
  stack whose directory exists is reported `skipped owned`; `meetingminer`
  is never a candidate. Safe to run while another suite is going.
- `make migrate`, `make rebuild`, `make purge` and the worker write the
  checkout's own stores. In the main checkout that is the live corpus, so
- **`make evals-run` is still one at a time.** Story 11.3 gives every run an
  immutable folder and a run-owned check-2.11 probe, coordinates probes that
  share a subject moment, waits for raced projection, and erases under the
  projection-writer lock. The owner's 2026-08-30 live two-run measurement was
  **safe for the corpus** but **unsafe for the verdict**: all four probes were
  erased, no subject artifact changed, and the concurrent `make test` was
  unaffected, but one run judged a sibling's in-flight probe as subject state
  and false-reported a projection regression. The current branch excludes
  probe-marked rows from that subject half; until a new owner remeasurement
  passes, announce an eval run, run it alone, and release it. It may overlap
  test suites, but not another eval run or a dev-store writer.

Memory is the bound, and it is the Docker VM's, not the host's. Measured
2026-08-30 with `docker stats`, each stack idle after a full `make test`: the
main stack 2.0 GiB (neo4j-test 1.20 GiB, neo4j 578 MiB, meilisearch-test
99 MiB, postgres 88 MiB, meilisearch 39 MiB); two worktree stacks 1.87 GiB and
1.78 GiB, with the same shape — Neo4j is nine tenths of it. Under two
concurrent full runs the figures were the same within 100 MiB. OrbStack's VM
reports 23.5 GiB against the host's 128 GB, and every other project's
containers share it, so a handful of stacks fit and a dozen idle ones would
fill it; nothing in compose caps Neo4j or Meilisearch. `docker stats
--no-stream` shows the current figure. The port range (400 bases) is not the
limit. When the VM is full, `make down` in an idle worktree stops its stack
and keeps its volumes; `make infra-up` there brings it back. Two full `make test` runs in two worktrees at once took 9m27s and
9m31s wall-clock against 9m49s for one alone (2026-08-30, `868ff0f`): neither
waited on the other.

Store-free suites are always safe to run concurrently — `make web-test`
(vitest, no stores), `make puller-test`, and `make evals-test` (the eval
harness: ground-truth validation, subject selection, the check algorithms over
synthetic captures, and the run-artifact rules; no stores, no api, and no run
folder created).

The remaining eval-run work is a passing live remeasurement, not another
namespace design: Story 11.3 built per-run folder/probe ownership and the first
measurement confirmed corpus safety, but verdict isolation failed. The
single-flight rule above remains until the owner-gated concurrent Verification
passes. It does not limit concurrent server suites.

## Fast loop and full gate

`server/pyproject.toml` sets `addopts = "-m 'not slow' --strict-markers"`, so
every `pytest` run selects the fast set unless the command line says
otherwise: the tests whose duration the test process controls. `slow` marks
the rest — twelve modules bound by the test twins, spawned processes, the
projection lock, or timers, plus a few timer- and twin-bound tests in
otherwise fast modules — each with a `reason=` naming what sets its duration
and its measured cost. The measurement behind the split (2026-08-29 at
`e5510c7`) put 471 of the full run's 527 test-seconds in those twelve modules
and the whole run at 9m17s.
`uv run --project server pytest server/tests --co -q | tail -1` shows the
current split; `uv run --project server pytest -m "" server/tests --durations=25`
re-measures it.

- **`make test-fast` is the loop.** `check-client`, the three store-free
  suites, then the fast set with every skip printed with its reason (`-rs`).
  The fast set needs Postgres only: with Postgres down, its Postgres-backed
  tests skip with named reasons; the twin-bound tests are `slow` (or a
  collection error if unmarked) and deselected here, so a twins-only outage
  produces no skips at all.
- **`make test` is the gate.** It passes `-m ""`, runs everything, and
  requires the twins — `check-test-stores` fails first when they are down.
- **A `slow` module run by path needs `-m ""`.**
  `pytest server/tests/test_projections_graph.py` deselects every test in the
  file and exits 5 with a one-line hint; run
  `uv run --project server pytest -m "" server/tests/test_projections_graph.py`.
  An empty expression on the command line replaces the `addopts` one and
  clears the filter. The Makefile's `test:` and `check-test-stores` pass it,
  and so does the child pytest `test_parallel_store_safety` spawns.
- **Give pytest a path under `server/tests`, or run it from `server/`.**
  `server/tests/conftest.py` registers the plugins below through
  `pytest_plugins`, which pytest accepts only from a conftest it loads at
  startup for the arguments given. A bare `pytest` from the repo root is
  unsupported.
- **The fast set is budgeted.** `server/tests/fast_budget.py` (registered from
  conftest's `pytest_plugins`) reports a passing test failed when it carries
  no `slow` mark and its call phase exceeds `mm_fast_test_budget_seconds`
  (2.0s, set with its rationale in `server/pyproject.toml`;
  `-o mm_fast_test_budget_seconds=<seconds>` overrides it for one run),
  naming the test, its duration, the key, and the remedies: mark it `slow`
  with a reason, or make it faster — and if it is only slow while another
  suite, a rebuild, or the worker is running, re-run it alone first;
  contention is not a reason to mark. Fixture time does not count, a failing
  test keeps its own failure, and `slow`-marked tests are exempt under either
  selection.
- **Two rules are checked at collection**, and a violation stops the run
  naming every offending node id: a `slow` mark must carry a non-empty
  `reason=`, and a test with no `slow` mark may not request
  `projection_stores` or `stores_up` — a twin-bound test belongs in the slow
  set. The second rule is also applied when either fixture is set up and
  when an unmarked test's setup or call is reported, which catches a
  `request.getfixturevalue(...)` the static closure cannot show: the
  unmarked test fails (an error at setup, when one of its own fixtures
  asked) and `projection_stores` never runs for it — whatever outcome the
  test earned on its own, so a skip, an xfail or an xpass after the request
  does not hide it, and a failure of its own is kept with the diagnostic
  added. With `--strict-markers`, an unregistered mark stops collection too.
  The slow set is pinned in `server/tests/test_compose_contract.py`
  (`SLOW_MODULES`, `SLOW_TESTS` — a class-level mark pins as
  `module::Class`), as are `test-fast`'s prerequisites
  (`TEST_FAST_PREREQUISITES`) and its recipe, which is the one fast-set
  command: adding a mark, a prerequisite or a recipe line is an edit of both
  places.
- **Lint and typecheck are in the loop** (story 11.4, backlog B-4).
  `make lint` runs ruff over the whole server tree — sources and tests —
  and `make typecheck` runs mypy over the decision-core modules named by
  `[tool.mypy] files`; both read only committed configuration in
  `server/pyproject.toml`. The rule set is ruff's default at the pinned
  minor, kept green on main by a dated baseline (2026-08-30: a seven-code
  global ignore plus per-file entries), never a source sweep — violations
  live at measurement are filed for per-module retirement in
  `_bmad-output/implementation-artifacts/deferred-work.md`; a new file gets
  every rule outside the seven globally ignored codes, which stay exempt
  tree-wide until retired. `make test-fast` runs both directly after
  `check-client`, so an unused import or a type error in a decision core
  fails the loop before any pytest starts. The targets, the loop membership,
  the baseline and the mypy scope are pinned by
  `server/tests/test_lint_contract.py` alongside `TEST_FAST_PREREQUISITES`:
  dropping either target from the rule line is an edit of both places.

## Branch and merge

- Branch names: `story/<slug>`, e.g. `story/1-12`, `story/1-7-remediation`.
- `main` is the integration branch every agent baselines against. Merge back to
  `main` (fast-forward or a normal merge) as soon as the work is reviewed —
  long-lived branches defeat the point, because the next agent baselines on
  something that no longer resembles the tree.
- Rebase onto `main` before merging, so the reviewed range is the range that
  lands.

## Staying out of each other's way

- The per-story frozen contract names the files that story owns. Treat that as
  the boundary; if you need a file another in-flight story owns, say so rather
  than editing it.
- A shared low-level addition (a predicate in `domain/`, a fixture in
  `conftest.py`) is fine, but pin its exact definition in both story specs so
  two agents cannot write it two ways. This has worked in practice:
  `evidence_complete()` in `domain/jobs.py` was specified identically in the
  1.7 and 1.9 contracts, and whichever landed first was consumed unchanged.
- Report accurately. If you did not write a file, do not report that you did —
  a claimed artifact that is not on disk costs the next agent a verification
  pass. State what you actually verified, and how.

## Kicking off an agent

A copy-pasteable prompt that front-loads these rules — for Codex, Claude Code,
or a BMad skill run — is in `docs/agent-kickoff-prompt.md`, with extra clauses
for reviewer agents and for re-reviews after remediation.
