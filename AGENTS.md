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

Each concurrent piece of work gets its own worktree and its own branch, so two
agents can never share a checkout.

```bash
make worktree STORY=1-12          # ../meetingminer-wt/1-12 on branch story/1-12
cd ../meetingminer-wt/1-12
make bootstrap                    # per-worktree venv + node_modules (one-time)
```

When the work is done and pushed, remove it:

```bash
make worktree-remove STORY=1-12
```

`make worktree-list` shows what exists. Worktrees live in
`../meetingminer-wt/` — a sibling of the repo, deliberately outside it, so no
`.gitignore` entry is needed and no tooling walks into them.

Notes that matter:

- `config.yaml` is tracked, so it comes with the worktree. `.env` is not — the
  target symlinks the main checkout's `.env` so secrets and both storage roots
  — `MM_CONTENT_ROOT` and `MM_DROPS_ROOT` — are shared rather than re-entered.
- `server/.venv` and `web/node_modules` are gitignored, so each worktree needs
  its own `make bootstrap`. That is the price of isolation; pay it once.
- The worker's pidfile is already keyed on the checkout path, so a worker
  started in a worktree does not collide with one started in the main checkout.

## What worktrees do NOT isolate: the data stores

This is the sharp edge. A worktree isolates *code*. It does not isolate the
Docker stores, which are a single shared stack on fixed ports with fixed
container names: the three dev stores (Postgres 5433, Neo4j 7687,
Meilisearch 7700) plus two disposable **test-store twins** (neo4j-test on
7475/7688, meilisearch-test on 7701) that exist so the projection test
suites can wipe stores without emptying the developer's live corpus.

**Consequence: the server suite is now safe to run concurrently; one eval run
at a time.** Story 2.7 fixed the suite; the remaining limit is `make evals-run`.

- `server/tests/conftest.py` names its database per run (`RUN_ID`), so two
  suites own different databases and each drops only its own on the way out.
  `test_migrations.py`'s two extra databases follow the same rule. A run killed
  with `SIGKILL` cannot clean up after itself — `make test-db-prune` sweeps
  what is left, and refuses any database with a live backend, so it is safe to
  run while another suite is going.
- The projection suites cannot be namespaced the same way: Neo4j Community
  serves exactly one database, and AD-4 fixes the Meilisearch index names, so
  `projection_stores` wipes whatever is there. They therefore run against the
  **dedicated test containers** — the session `app_config` in
  `server/tests/conftest.py` repoints the Neo4j and Meilisearch endpoints at
  `bolt://localhost:7688` / `http://localhost:7701` (env-overridable via
  `MM_TEST_NEO4J_URI` / `MM_TEST_MEILI_URL`) — so a suite run never touches
  the dev stores' content. When the test twins are down the store-backed
  tests skip with a named reason; they never fall back to the dev endpoints.
  Concurrent suites still share the two test twins, so those tests take a
  **cross-process file lock** and queue instead of interleaving. The lock
  lives in the system temp dir keyed by the store URLs, not in the repo —
  worktrees have different roots but share one compose stack, so a
  repo-relative lock would give each worktree its own file and no mutual
  exclusion at all. The URL keying also means test suites and dev-store
  writers (rebuild, the worker) hold *different* lock files now: the lock
  only serializes writers of the same endpoints, which is exactly the
  contention that remains. Waiting is bounded (configurable through
  `MM_PROJECTION_LOCK_TIMEOUT_SECONDS`) and a timeout names the path and
  current holder metadata.
- **`make rebuild` is single-flight across every worktree sharing the stores.**
  The same file lock is not test-only: every server entrypoint that writes
  Neo4j or Meilisearch — `rebuild`, the worker's per-meeting projection, the
  embeddings-only pass, and meeting retirement
  (`server/meetingminer/projections/locks.py`) — takes it first, then the
  Postgres advisory lock. Two rebuilds, or two projection-test suites in
  different worktrees, therefore queue on the same file instead of racing.
  (A rebuild and a test suite no longer contend at all: the suite's lock is
  keyed by the test-twin URLs, the rebuild's by the dev-store URLs, and each
  writes only the stores its lock covers.) The loser of a timed-out wait
  gets a named `ProjectionLockedError`,
  never a torn store. For the worker this means a projection that lands while
  a rebuild or another dev-store writer holds the lock queues for up to
  `MM_PROJECTION_LOCK_TIMEOUT_SECONDS` (default 300s), then fails that
  meeting with the named refusal rather than writing anyway. Do not start a
  rebuild expecting it to interleave with anything that writes the stores.
- **`make evals-run` is still one at a time.** It reads Postgres directly, lists
  the corpus through the api, and writes an immutable run folder under
  `evals/runs/`; it takes no lock. Announce it, run it, release it.

Note what the projection lock means in practice: concurrent server suites will
serialize on the handful of projection tests and run in parallel everywhere
else. That is a throughput property, not a correctness one — nothing fails, it
waits.

Store-free suites are always safe to run concurrently — `make web-test`
(vitest, no stores), `make puller-test`, and `make evals-test` (the eval
harness: ground-truth validation, subject selection, the check algorithms over
synthetic captures, and the run-artifact rules; no stores, no api, and no run
folder created).

The remaining isolation work is for `make evals-run`: per-run eval namespaces
and run-artifact ownership would be needed before those runs can overlap. It
is recorded in `docs/backlog.md` and
does not limit concurrent server suites.

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
