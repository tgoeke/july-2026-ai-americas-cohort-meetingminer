# Reviewer handoff — Story 2.7: Parallel-Safe Store-Backed Tests

You are reviewing a completed, pushed story branch. You have none of the build
run's context; everything you need is below. **Report findings — do not apply
fixes.**

## Repo, branch, range

- Repo: `/Users/devopsterus/current/cohort/meetingminer`, branch
  `story/2-7-parallel-safe-store-backed-tests`, pushed to `origin`. A worktree
  exists at `../meetingminer-wt/2-7-parallel-safe-store-backed-tests`; either
  checkout works.
- Review range: **`9452382..HEAD`** (2 commits, 4 files, +153/−34).
- Both commits belong to story 2.7. **No commit in this range belongs to
  another story.**

```
- 6db08958e1b21a5d8a329141cada85057a914233  feat(story 2.7): store-backed tests are safe to run concurrently
- 141dc3934c940e32b5df0a8b8a362a8ea73b8145  docs(story 2.7): correct the identifier-length comment
```

## Read this first: there is no spec file

Every other story in this project has a `spec-<n>-<slug>.md` with a frozen
`<intent-contract>`. **This one does not.** It was registered and built inside a
single session, so the contract lives in two places instead:

- `_bmad-output/implementation-artifacts/deferred-work.md` — the entry whose
  summary begins `FILED as story 2-7-parallel-safe-store-backed-tests`. It
  carries the measured evidence and the tiered plan (Postgres easy, Meilisearch
  moderate, Neo4j not solvable the same way).
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — the DISPATCH RULE
  header block, which states the user direction this story exists to satisfy.

Judge the code against those two. **A finding that the story should have had a
spec is a legitimate finding** — do not suppress it.

## Architecture authority

- `_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md`
- **AD-4** governs the central constraint: Neo4j and Meilisearch are derived,
  disposable projections, and **AD-4 fixes the Meilisearch index names.** That
  is why the projection stores could not be given a per-run namespace the way
  Postgres was. If you think a per-run index prefix is right, that is an AD-4
  amendment, not an implementation choice — report it as such.

## What the change actually does

1. **Postgres, per-run.** `server/tests/conftest.py` gains `RUN_ID`
   (`uuid4().hex[:12]`); `TEST_DATABASE` becomes
   `meetingminer_test_{RUN_ID}`. The session fixture now yields and drops its
   own database on the way out. `test_migrations.py`'s `PENDING_DATABASE` and
   `CLI_DATABASE` get the same treatment **plus teardown** — per-run names make
   teardown mandatory, because fixed names self-overwrote and unique ones would
   accumulate one pair per run.
2. **Projection stores, serialized.** `projection_stores` now wraps its body in
   `_projection_store_lock()`, a blocking `fcntl.flock` on a file in the system
   temp dir keyed by a sha256 of `neo4j.uri|meilisearch.url`.
3. **`make test-db-prune`** drops leaked `meetingminer_test%` databases, skipping
   any with a row in `pg_stat_activity`.
4. **`AGENTS.md`** inverts its "two agents must not run the test suites at the
   same time" rule, and narrows the remaining serial case to `make evals-run`.

## Design decisions to attack

These are the contestable calls. The builder flagged all four; none is settled.

1. **The lock blocks forever with no timeout.** `LOCK_EX` with no `LOCK_NB` and
   no alarm. Rationale in the docstring: "a waiting run is correct, a failing
   one is not." Consequence: one hung suite blocks every other suite
   indefinitely, with no diagnostic. Is silence-then-deadlock better or worse
   than a timeout that fails loudly? **Attack this first.**
2. **`test-db-prune` has a real race.** It refuses databases with a live
   backend, but a run that has just `CREATE`d its database and not yet connected
   has no backend, so a concurrent prune can drop it. Window is small; the
   failure is a confusing mid-suite error. Accept, document, or fix?
3. **The lock file is opened `"w"`.** `flock` binds to the inode, so if anything
   ever deletes and recreates that file, two processes hold "the lock" on
   different inodes and the mutual exclusion silently evaporates. Nothing
   deletes it today. Latent, or worth hardening?
4. **The lock's location is load-bearing and easy to get wrong.** It is in
   `tempfile.gettempdir()`, deliberately NOT the repo: worktrees have different
   roots but share one compose stack, so a repo-relative lock would give each
   worktree its own file and provide no mutual exclusion at all — while looking
   correct. Verify the keying (`stores.neo4j.uri|stores.meilisearch.url`) is the
   right granularity.

## Claims the builder verified — re-verify rather than trust

- **Lock coverage is complete.** Three test files reference `neo4j`/`meili`
  without the locked fixture — `test_compose_contract.py`, `test_config.py`,
  `test_projections_single_writer.py` — and all three were checked to make
  **zero** live store connections (they are static import/config assertions).
  If any of them, or any future test, opens a driver outside
  `projection_stores`, the lock is a fiction. **This is the claim most worth
  re-checking**, and there is no test enforcing it.
- **917 server tests pass**, unchanged from the pre-change count on `main`.
- **Two concurrent runs pass.** `test_migrations.py`, `test_projections_graph.py`,
  `test_projections_search.py`, `test_ingests.py` run simultaneously from two
  pytest processes: 88 passed each, both exit 0.

Note what was **not** demonstrated: no run proves the *old* code fails under the
same concurrency. The mechanism is argued from reading (`DROP DATABASE ... WITH
(FORCE)` on a fixed name), not from an observed red run.

## Known throughput caveat, deliberately accepted

Concurrent suites serialize on the projection tests and run parallel everywhere
else. Nothing fails; it waits. This is documented in `AGENTS.md` rather than
hidden. Judge whether the wording sets the right expectation.

## History you need to tell a regression from a pre-existing condition

- The fixed-name problem was found in the **story 1.2 review** and deferred as
  "matters once more than one contributor or deployment exists." That was
  correct for a solo developer and became wrong once agents ran in parallel.
- `make backfill-drop-paths` was fixed on `main` in `9452382` (the base of this
  range) for an unrelated defect — it inherited `rebuild`'s global
  `ARGS ?= --all`. That commit is **not** part of this story.
- `pull_transcript/package-lock.json` is modified by `make bootstrap` in a fresh
  worktree. It was deliberately reverted and is **not** in this diff.

## Verification baseline

From the worktree, stores up (`make infra-up`):

```
server/.venv/bin/python -m pytest server/tests -q          # expect 917 passed
make test-db-prune                                          # expect a clean sweep
```

Concurrency check (run both at once, expect 88 passed each, both exit 0):

```
server/.venv/bin/python -m pytest server/tests/test_migrations.py \
  server/tests/test_projections_graph.py \
  server/tests/test_projections_search.py server/tests/test_ingests.py -q
```

**Note for zsh users:** do not collect those paths into a variable — zsh does
not word-split unquoted variables, and pytest will receive one long path and
report "no tests ran". This bit the builder.

After any run, confirm no per-run databases leaked:

```
select datname from pg_database where datname like 'meetingminer_test%';
```

## Required output

A findings report: severity, file:line, failure scenario, and whether the
finding is caused by this change or pre-existing. **Report only — apply
nothing.** If you conclude a decision above is defensible as built, say so
explicitly rather than staying silent, so the next reader knows it was examined.
