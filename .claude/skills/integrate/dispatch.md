# Dispatching the next wave

## The standing rule

**Standing user direction, amended 2026-08-30** (supersedes the 2026-08-19
no-caveat rule): parallel is the default. Merge conflicts between stories are
integrate's routine work — union per `conflict-playbook.md`, then re-run both
stories' suites — not a reason to serialize. Sequence only for:

1. **Disagreement risk** — two stories rewriting the *same statement* (the
   same AD paragraph, the same policy line, the same function's semantics),
   where a union is not a resolution.
2. **Contract dependency** — one story's acceptance criteria reference the
   other's deliverable.
3. **Operational gate** — paid roles, the shared worker, `make evals-run`.

Decide on measured regions, not filenames: `_bmad/scripts/branch_conflicts.py`
prints the pairwise conflict matrix of every `story/*` branch against `main`
(`--hunks <branch>` shows one branch's changed regions in `main` line
numbers). Write each dispatched story's footprint — exact files and anchors,
new tests in new files, never `server/tests/conftest.py` — into its build
prompt; a footprint in the prompt is contract the builder is held to, which is
how proximity conflicts stay rare enough for integrate to absorb.

## How to test a candidate pair

1. **Files.** List what each story touches. Any shared file from
   `conflict-playbook.md` — `conftest.py`, `projection_seed.py` — disqualifies
   the pair from *parallel*. Sequence them. (`api/main.py` and `App.tsx` left
   this list when story 2.8 made registration auto-discovered: an endpoint is
   a file in `meetingminer/api/`, a screen is a `*.route.tsx` file.)
2. **Stores and suites.** Server suites may overlap since story 2.7: each run
   owns a per-run Postgres database, and projection tests queue on a bounded
   cross-worktree file lock. `make evals-run` is still one at a time.
3. **Operational gates.** A story that requires the worker to run is gated by
   the paid-ops hold regardless of how clean its files are.
4. **Contract dependency.** A story whose acceptance criteria reference an
   endpoint another backlog story delivers is blocked, not parallel — for
   example `5-3` needs `4-3`'s per-moment approval endpoint before check 2.11
   can assert publication.

Only a candidate clearing all four is a parallel recommendation.

## Standing structural note — resolved

Both structural chokepoints are gone: story 2.7 removed the test-harness one,
and story 2.8 removed hand-edited registration on both sides
(`server/meetingminer/api/registry.py` discovers routers;
`web/src/routes/registry.ts` discovers `*.route.tsx` screens). Adding an
endpoint or a screen is adding a file, so API stories and screen stories no
longer collide on a shared registration block. Do not re-offer this work.
Stories touching the *same* endpoint file, feature component, or the discovery
mechanism itself still conflict the ordinary way.

## Where the schedule risk is

The live demo is one path only (SPEC: ~3 minutes, CAP-3 → CAP-4): ask the
corpus, get a cited answer, open the moment, replay it. That is Epic 3 plus
story 2.2 and nothing else in Epic 2. Weigh Epic 3 stories accordingly when
recommending what to dispatch — Epic 2's tail is not the risk.
