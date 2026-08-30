# Epic 11 Context: Fast, Conflict-Free Test Suite

<!-- Generated from planning artifacts. Regenerate with compile-epic-context if planning docs change. -->

## Goal

A routine server test run finishes in seconds, the full run stays available under `make test`, and two builders in two worktrees can run every suite — projection suites and eval runs included — at the same time without queueing on a lock or writing into each other's stores. Lint and type checking join the fast loop so it catches what tests never would. This is the operator's stated first priority (2026-08-29) and is built before any other new work; epic order is 11 → 6 → 10 → 7 → 8 → 9.

## Stories

- Story 11.1: Seconds-Fast Default Suite
- Story 11.2: Per-Run Store Isolation
- Story 11.3: Eval Runs Own Their Namespace
- Story 11.4: Lint and Type Tooling in the Fast Loop

## Requirements & Constraints

- **Fast by default, full on demand.** The default pytest invocation and `make test-fast` select only tests whose duration the test process controls; process-spawning, twin-bound, lock-bound, and timer-bound tests carry a `slow` mark with a stated reason. `make test` runs everything and requires the test twins.
- **No silent regrowth.** A configured per-test time budget (with recorded rationale) fails the run naming any unmarked test that exceeds it; contention with another suite, a rebuild, or the worker is not a reason to mark a test slow — re-run it alone first.
- **No contention across builders.** Every suite run owns its own store namespace or its own store instances. Two worktrees running `make test` simultaneously must both pass with neither waiting on the other; wall-clock alone versus concurrent is measured and recorded in the story report.
- **Eval runs are safe alongside a suite.** An eval run reads the shared dev stores read-only, its run folder is owned by its run id (never reused or overwritten), and any store write it must make goes through the public api into a namespace the run owns and cleans up. The current "one eval run at a time" rule is replaced with the measured result.
- **Orphan cleanup is safe while others run.** `make test-db-prune` also removes orphaned per-worktree stacks left by a killed run or worktree, and refuses anything with a live owner.
- **Lint and types.** `ruff` passes on `server/` with a committed configuration; `mypy` runs on the decision-core modules with a committed baseline; both run inside `make test-fast`; the existing `.gitignore` entries for their caches become real.
- **Docs follow the code.** AGENTS.md's "worktrees do not isolate the stores" section and `project-context.md` are rewritten to the mechanism actually built; any per-stack memory cost is measured and documented (the host has 128 GB and the owner wants it used).
- **No silent fallbacks.** A store that is down produces a named skip or a named error; tests never fall back to the dev endpoints.

## Technical Decisions

- **Isolation is one private compose stack per worktree.** `make worktree STORY=<slug>` provisions Postgres, Neo4j, and Meilisearch — dev instances and test twins alike — as a compose project named for the worktree on dynamic ports, and writes the worktree's environment to point at them; `make worktree-remove` tears it down. Neo4j Community serves exactly one database and the Meilisearch index names are fixed by the architecture, so isolation is by instance, not by namespace. The earlier draft's per-session ephemeral Neo4j container and Meilisearch index-prefix setting are not built; revisit only if a measured case (two concurrent suite runs inside one worktree) needs them.
- **The projection file lock stays, keyed by store URL.** It lives in the system temp dir (not the repo, because repo-relative paths would give each worktree its own file). With per-worktree store URLs it never has a holder from another worktree; inside one worktree it still serializes every dev-store writer — rebuild, the worker's per-meeting projection, the embeddings-only pass, meeting retirement — ahead of the Postgres advisory lock, with a bounded wait and a named timeout error. The lock-timeout test targets its own lock key through an env override.
- **Postgres is already per-run.** The session conftest names the database by run id and each run drops only its own; the migrations module's extra databases follow the same rule. Extend this pattern rather than replacing it.
- **Worktree conventions to preserve.** Worktrees live in a sibling directory outside the repo; `.env` is symlinked from the main checkout so secrets and both storage roots are shared; the worker pidfile is keyed on the checkout path. A per-worktree environment must not overwrite the shared `.env`.
- **Compose runs only the stateful stores.** Api, worker, and dev server stay host processes; no pipeline stage may assume a container.
- **Invariants that must survive the plumbing.** Only the `projections` package writes Neo4j or Meilisearch (proven by an import-inspection test and an AST walk); the api package opens no store client; decision cores stay database-free and model-free (they are the natural `mypy` targets); every threshold is configuration with recorded rationale, and the config model forbids unknown keys, so a removed key leaves the file and every fixture together.
- **Store-free suites are unchanged.** The web, puller, and eval-harness unit suites open no stores and are already safe to run concurrently.

## Cross-Story Dependencies

- 11.1 has landed: the `slow`/fast split, the per-test budget, and the collection-time rules are in place and pinned by a compose-contract test, so a new mark, prerequisite, or `test-fast` recipe line is an edit in both places. Measured at landing: `make test-fast` ran in about 66s wall with Postgres only, and the full run in about 9m17s — the fast set is fixture-bound, not process-bound, and further speedup is a separate item.
- 11.4 adds `ruff`/`mypy` to the `make test-fast` target 11.1 created.
- 11.3's owned write-through namespace presupposes the per-worktree stacks of 11.2.
- 11.2 and 11.3 each rewrite part of the same AGENTS.md store-isolation section; land them in order, not in parallel.
- Story 6.1 (UX design spec, no code) runs in parallel with this epic; Story 6.2 waits for 11.1 and 11.2 because all three change `server/tests`.
