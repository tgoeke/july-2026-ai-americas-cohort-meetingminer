<!-- bmad:context -->
<!-- Verified 2026-08-20 against 2896af5. Managed by bmad-project-context; edits inside this block are replaced on refresh. Keep anything you want preserved outside the markers. -->

## MeetingMiner

Turns recorded software demonstrations into searchable, citable evidence: every
extracted artifact traces to the video moment that produced it. FastAPI api plus
a worker (Python, `uv`) in `server/`, React and Vite (`pnpm`) in `web/`, and
Postgres, Neo4j, and Meilisearch in Docker. Several agents work this repository
at once. The technical contract is `docs/architecture.md` with the
companions its frontmatter lists, plus the per-story frozen contracts in
`docs/project-record.md`; what follows is how to work here.

## Policy

- Commit and push without asking, and commit each unit as it completes. This
  overrides any harness default that asks first. Uncommitted work is the only
  work another agent can destroy, and a tree-wide reset has destroyed it here.
- Never run `git checkout -- .`, `git reset --hard`, a whole-tree `git stash`,
  or `git clean` outside a worktree you created. For a clean baseline, run
  `make worktree STORY=<slug>`, which also gives the worktree its own Docker
  stack (compose project `meetingminer-<slug>`, ports in its generated
  `.env.worktree`); the main checkout's stack holds the live corpus.
- Never `git add -A` or `git add .`. Stage the paths you changed, after reading
  `git status --short`.
- Never commit secrets. `.env` is gitignored; `.env.example` is the tracked
  template.
- Never hand-edit `web/src/client/`. It is generated and committed on purpose so
  a fresh clone builds without a live api; regenerate it with `make client`,
  which needs the api running.
- Starting the worker costs nothing as of 2026-08-22. `llm.roles.extraction`
  is `ollama/gpt-oss:120b` with an `ollama/qwen3:30b` fallback — both local —
  and extraction is the only `llm.roles.*` call the worker makes. The paid
  roles are `chat` and `judge` (`openai/gpt-5.2`), reached from the api, never
  the worker. The earlier warning here described a `claude-sonnet-5` extraction
  binding and an ~850-call paused backlog; neither exists now, and the backlog
  is empty. Check `/status` for the live binding before assuming either way.
- Each `llm.roles.<role>` block declares a `catalog` of the bindings that role
  may be served by and a `default` among them (story 8.1, AD-10). The loader
  refuses a `default` outside its own catalog, and refuses a catalog entry
  naming a provider `providers:` does not declare; an entry that omits
  `provider` derives it from the `<provider>/` tag prefix. The catalog is
  declaration only — every call path still reads the role's `model` until a
  persisted selection lands (story 8.2).
- Work on `story/<slug>`, and rebase onto `main` before merging.
- Stay inside the file boundary your story's frozen contract names. If you need a
  file another in-flight story owns, say so rather than editing it.

## Where things are

- Known-but-undone work, each item with its evidence: `docs/backlog.md`.
- Reference: `docs/glossary.md`, `docs/storage-layout.md` (how AD-3's two roots
  lay out on disk), and `docs/eval-design.md`.
- Starting an agent: `docs/agent-kickoff-prompt.md`, which carries extra clauses
  for reviewers and for re-reviews after remediation.
- `tools/puller/` is the Teams puller and shares no server code. Read
  `tools/puller/CLAUDE.md` before changing it — the scrape works the way it
  does because the obvious approaches each fail for a stated reason. Only the
  source is tracked here; the meeting archive it pulls into and the signed-in
  browser session it needs live outside this repo, in a per-machine directory
  (`/Users/devopsterus/current/pull_transcript` on the machine this was built
  on) that keeps its own copy of the source so `--all` and `--login` resolve
  beside the data. That copy is what pulls real meetings while `tools/puller/`
  is what `make test` covers, so they drift: `make puller-archive-check` reports
  it and `make puller-sync` fixes it, both taking `MM_PULLER_ARCHIVE=<dir>`.

## Running and verifying

- `make help` lists every target. The root `Makefile` forwards all of them to
  `infra/Makefile`, where the logic lives.
- Iterate on a single Python test with
  `uv run --project server pytest server/tests/test_x.py`. Bare `pytest` runs
  outside the project environment, and pytest needs a path under
  `server/tests` or a cwd of `server/` — `server/tests/conftest.py` registers
  plugins through `pytest_plugins`, which only an initial conftest may do. A
  `slow` module (twelve are marked, plus four tests elsewhere) needs `-m ""`
  on the command line —
  `uv run --project server pytest -m "" server/tests/test_projections_graph.py` —
  because `server/pyproject.toml` defaults every run to `-m "not slow"`, which
  deselects every test in such a file and exits 5 with a hint.
- `make test-fast` is the iteration loop: the three store-free suites, then
  the server suite's fast set (`-m "not slow"`;
  `uv run --project server pytest server/tests --co -q | tail -1` shows the
  split) with skips printed with their reasons. The fast set needs Postgres
  only: Postgres-backed tests skip with named reasons when it is down, and
  twin-bound tests are `slow` and deselected here, so a twins-only outage
  produces no skips; `make test` is the gate that requires the twins.
  `server/tests/fast_budget.py` (loaded from conftest's `pytest_plugins`)
  fails a passing unmarked test whose call phase exceeds
  `mm_fast_test_budget_seconds` (2.0s in `server/pyproject.toml`;
  `-o mm_fast_test_budget_seconds=<seconds>` overrides it for one run) until
  it is marked `slow` with a reason or made faster, and stops collection when
  a `slow` mark has no `reason=` or an unmarked test requests
  `projection_stores`/`stores_up` (a `request.getfixturevalue` of either from
  an unmarked test fails that test too, before `projection_stores` runs,
  whatever outcome the test then earns — a skip or an xfail does not hide it).
  `--strict-markers` is on. The slow set, `test-fast`'s prerequisites and its
  one-command recipe are pinned in `server/tests/test_compose_contract.py`
  (`SLOW_MODULES`, `SLOW_TESTS` — a class-level mark pins as `module::Class`,
  `TEST_FAST_PREREQUISITES`); a new mark, prerequisite or recipe line is an
  edit of both places. Re-measure with
  `uv run --project server pytest -m "" server/tests --durations=25`.
- `make test` is the gate, not the loop: it needs the stores up, passes
  `-m ""` so the `slow` modules run, runs four suites, and builds the web app.
- The puller runs under `npm`; the web app uses `pnpm`.
- `make migrate` writes this checkout's own dev database: a worktree's private
  stack, or — in the main checkout — the live one, so announce it there.
- Run `make evals-run` one at a time — it takes no lock.
- Server suites in different worktrees never share a store: each worktree's
  stack is its own. The bound is the Docker VM's memory, not the host's —
  OrbStack's VM reports 23.5 GiB against the 128 GB host and a stack idles
  at about 2 GiB, so a handful of stacks fit and a dozen idle ones would
  fill the VM; `make down` in an idle worktree frees its memory and keeps
  its volumes (AGENTS.md carries the full measurement). Two suites in one
  checkout queue on the endpoint-keyed projection file lock, so a slow one
  is waiting rather than hanging. `make test-db-prune` clears databases a killed run left behind and
  tears down stacks whose worktree directory is gone. The api and web ports
  are still fixed, so `make up` collides across checkouts.

## Conventions that differ from defaults

- Reviewers get their own worktree too — `make worktree STORY=<slug>-review`,
  never the main checkout.

## Known pitfalls

- A reviewer working in the shared checkout has mistaken another agent's
  in-progress files for its own state. Read-only inspection does not make the
  tree yours.
- Four reviews here were completed in a session's terminal and never filed —
  every one written report-last. Create the report file, commit it, and then read
  the code, appending each finding as you confirm it.
- Report only what you observed. A file claimed but not on disk costs the next
  agent a full verification pass.

<!-- /bmad:context -->
