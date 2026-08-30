# Review prompt — Story 2-8 (auto-discovered route registration)

## REQUIRED OUTPUT — read this before anything else

Your review does not exist until its report file is committed. Produce:

**Report path:**
`_bmad-output/implementation-artifacts/review-story-2-8-2026-08-21.md`

**Finding structure** (one block per finding):
- **Location** — file:line
- **Severity** — high / medium / low
- **Finding** — what is wrong
- **Evidence** — why it is real (code you read, command you ran)
- **Suggested direction** — a direction, not a patch

**Report findings; do not fix.** No code edits, no test edits — findings only.

**REPORT-FIRST:** create and commit the report file as a skeleton (scope, review
range, empty findings section) BEFORE reading any code. Then append each finding
as it is confirmed and commit incrementally. Six reviews in this repo produced
their report only as terminal text because the file came last; a crashed session
must lose prose, never the artifact.

**Closeout check:** before reporting completion, run `make check-reviews` — it
fails while any dispatched review (including this one) lacks a committed report
— and state the SHA carrying the report's final version.

## Repo, branch, range

- Repo: `git@github.com:tgoeke/meetingminer.git` — take your own worktree:
  `make worktree STORY=2-8-review`, never the main checkout.
- Branch under review: `story/2-8` (pushed to origin).
- Review range: `527acf00f81834c5eb2385df002b2ce4e2a0ee74..HEAD`, containing:
  - `58c9a5f` docs(2-8): mark spec in-progress at baseline 527acf0
  - `cebdf13` feat(2-8): auto-discover api routers from the package
  - `249a41c` feat(2-8): discovered routes behind a react-router layout shell
  - `f6e1bc3` docs(2-8): retire the two registration chokepoints from the integrate skill
  - `082c43f` test(2-8): pin the unknown-path-renders-home matrix row
  - `a46fc82` fix(2-8): attribute discovery import failures; document scan limits
  - `26c5362` fix(2-8): home fallback for deep-link Back; test the web route registry
  - `09a050c` docs(2-8): close the auto run — triage log, deferred item, done status

All eight commits belong to story 2-8; no foreign-story commits are in the range.
The last four are remediation from the run's internal four-layer review pass —
its triage log is in the spec if you want to see what was already caught.

## Spec and what is frozen

Spec: `_bmad-output/implementation-artifacts/spec-2-8-auto-discovered-route-registration.md`.

- The `<intent-contract>` block (Intent, Boundaries & Constraints, I/O &
  Edge-Case Matrix) is **frozen intent** — judge the code against it; do not
  critique it.
- Everything after `</intent-contract>` — Code Map, Tasks & Acceptance, Design
  Notes, the triage log, Auto Run Result — is **planner work you may attack**.

## Architecture authority

- `AGENTS.md` (repo root) — operating rules; the shared-stores section governs
  which suites you may run.
- The spec's own Boundaries block is the routing authority for this change: the
  config-gate/`# noqa: E402` ordering in `main.py`, `problems.py`'s explicit
  `register_handlers(app)` (never swept into discovery), and `media.py`'s
  internal route order are the standing decisions to check survived.
- `.claude/skills/integrate/conflict-playbook.md` and `dispatch.md` are
  integration-policy artifacts this story edits; the claim they now make (the
  two registration chokepoints are retired) is itself reviewable.

## Scope

**In scope** (the story's file boundary, all in the range):
`server/meetingminer/api/registry.py`, `server/meetingminer/api/events.py`,
`server/meetingminer/api/main.py`, `server/tests/test_api_registry.py`,
`web/package.json`, `web/pnpm-lock.yaml`, `web/src/App.tsx`,
`web/src/App.test.tsx`, `web/src/routes/registry.ts`,
`web/src/routes/registry.test.ts`, `web/src/routes/navigation.ts`,
`web/src/features/moments/MomentView.route.tsx`,
`web/src/features/moments/MeetingMoments.route.tsx`,
`.claude/skills/integrate/conflict-playbook.md`,
`.claude/skills/integrate/dispatch.md`, sprint-status line, the spec itself.

**Out of scope:** any route's path/method/models/status codes (registration
only; `web/src/client` is untouched by design), later stories' functionality
(3-4, 4-2/4-3/4-4 route files), vendored `pull_transcript/`, and the recorded
deferred item (SPA history fallback for production static hosting — already in
the spec frontmatter; do not re-report it).

## Design decisions to attack

Each is the planner's call plus the assumption it rests on — attack the
assumption:

1. **`ROUTER_ORDER` int + name tie-break, not specificity sorting.** Assumes
   preserving today's route table provably unchanged beats fixing the ordering
   hazard class outright (Design Notes argue specificity sorting is a separate
   story). Check nothing now depends on accidental alphabetical order beyond
   the declared `events` case.
2. **Selection by `isinstance(module.router, APIRouter)`, no explicit
   allow/deny list.** Assumes attribute+type is discriminating enough forever —
   e.g. that `problems.py` will never grow a module-level `router`.
3. **Ordering tests dispatch via `route.matches()` over a flattened table that
   reads FastAPI's private `_IncludedRouter.original_router`** (guarded
   non-empty), not via `TestClient` on the gated production app. Assumes the
   pre-existing suite (which does make real requests) is the true gate and
   these tests only pin relative order.
4. **`main.py` anti-creep test greps source for the literal `include_router`.**
   Assumes a text pin is an acceptable tripwire on top of behavioral coverage,
   and nobody needs to write that word in `main.py` again.
5. **Home stays in the layout route, rendered `hidden`, never a discovered
   route.** Assumes the search-state-survives-Back behavior (pinned at
   `App.test.tsx` "keeps the search state alive…") outweighs route uniformity.
6. **Back = `navigate(-1)` with a fallback to `/` when
   `window.history.state?.idx` is falsy/0.** Assumes react-router 7 keeps its
   history index in `history.state.idx` — a documented but unofficial contract.
7. **Web discovery = `import.meta.glob('../features/**/*.route.tsx')`, eager.**
   Assumes all screens live under `web/src/features/` (documented), and that a
   test-fixture `.route.tsx` must never exist because it would ship (that is
   why `registry.test.ts` tests `routeOf`/`sortRoutes` as functions and asserts
   a two-path floor rather than dropping in a fixture route).
8. **`useOpenPath` dedupe compares `window.location.pathname` directly.**
   Assumes `BrowserRouter` with no basename, and that pathname (no
   query/hash/trailing-slash normalization) is a sufficient identity.
9. **The integrate-skill playbook edits ship in this same branch.** Assumes
   landing them atomically with the code is better than a follow-up; until
   merge, main's playbook still lists the old hazards.

## History a reviewer needs

- Baseline is `527acf0` = main at branch time; the branch is unrebased and main
  has not moved under it as of this writing. `9cbf73b` named in the spec's
  original frontmatter was the spec-freeze baseline; the build re-pinned to
  `527acf0` at start — same tree lineage, no dropped work.
- `App.test.tsx`'s original eleven cases predate the change and their
  assertions are contractually untouched; the three additions (a `beforeEach`
  URL pin, an unknown-path case, a deep-link Back case) came from this story.
  A diff hunk in that file is not license to treat the old cases as new.
- The old `main.py` registration comments were deliberately deleted; their
  content was moved into `registry.py` docstrings and test names. Judge whether
  the move lost anything (one known catch — the `/moments/recent` forward
  hazard — was restored in `a46fc82`).

## Verification baseline

All observed by the orchestrating session at `09a050c` (worktree
`meetingminer-wt/2-8`); a deviation you see is a finding, not noise:

- `cd server && uv run --project . pytest tests/test_api_registry.py -q` → 8 passed.
- `cd server && uv run --project . pytest tests/ -q` → **1505 passed**, 1
  pre-existing Starlette deprecation warning, ~6m30s. Store-backed but
  parallel-safe (per-run database); projection tests queue on a file lock.
- `make web-test` → 11 files, **187 tests passed** (store-free, run freely).
- `pnpm --dir web run build` → succeeded (`tsc -b` + vite).
- `pnpm --dir web run lint` → exit 0; three fast-refresh warnings (one
  pre-existing `button.tsx`, two inherent to `.route.tsx` files).
- Route-table parity: old vs new registration loaded in one process — 12
  path+method pairs identical; `/jobs/events` before `/jobs/{job_id}`; media
  recording route before the `{path:path}` catch-all.
