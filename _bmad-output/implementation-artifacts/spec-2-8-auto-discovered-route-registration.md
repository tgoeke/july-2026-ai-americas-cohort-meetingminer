---
title: 'Auto-discovered route registration'
type: 'enabler'
created: '2026-08-20'
status: 'done'
baseline_revision: '527acf00f81834c5eb2385df002b2ce4e2a0ee74'
review_loop_iteration: 0
followup_review_recommended: true
context: []
warnings: []
deferred:
  - summary: >-
      Production static hosting for the web app will need an SPA history
      fallback (rewrite non-asset paths to index.html) now that screens have
      real URLs; a direct GET for /meetings/:id 404s on a plain file server.
    evidence: |-
      Story 2.8 moved navigation onto BrowserRouter, so child screens live at
      real paths. The vite dev server handles the fallback natively, but no
      production hosting config exists in this repo to carry the rewrite rule.
    location: >-
      web/src/App.tsx (BrowserRouter)
    severity: low
---

<intent-contract>

## Intent

**Problem:** Two files must be hand-edited to add a surface, and they are the
only two entries in `.claude/skills/integrate/conflict-playbook.md` that
disqualify a pair of stories from parallel work. `server/meetingminer/api/main.py`
carries a nine-name import tuple plus eight `app.include_router(...)` calls
(`:56-65`, `:129-153`); `web/src/App.tsx` carries an `AppView` union, a
hand-rolled navigation stack, and a chain of `view.kind === '...'` render
blocks (`:17-20`, `:112-168`) — its own comment at `:148` says "still no
router — the view union above is the whole navigation." Every API story edits
the first and every screen story edits the second, so `3-4`, `4-2`, `4-3` and
`4-4` are a forced sequence rather than a wave. This is the same class of bet
as story 2.7, which removed the test-harness chokepoint. (Sprint id
`2-8-auto-discovered-route-registration`; minted directly into
`sprint-status.yaml` and `epics.md` like `2-6` and `2-7`, which are also not
in the original epic definition.)

**Approach:** Replace both hand-maintained registries with discovery, and
replace the two implicit ordering contracts with explicit, tested ones.

On the server, a new `meetingminer/api/registry.py` walks the `meetingminer.api`
package and returns every module exposing a module-level `router` that is a
`fastapi.APIRouter`, ordered by a declared `ROUTER_ORDER` with the module name
as tie-break. `main.py` iterates that list. Adding an endpoint becomes adding a
file.

On the web, `App.tsx` becomes a react-router layout route that renders the
shell and the home content and delegates everything else to `<Outlet />`.
Child routes are discovered with `import.meta.glob` over `*.route.tsx` files
beside the components they mount. Adding a screen becomes adding a route file.

**The two constraints that make this harder than it reads**, both currently
encoded only as prose comments, both of which must survive as tests:

1. **Server registration order changes route matching.** `main.py:130-132`
   registers `events` before `jobs` because `/jobs/{job_id}` would otherwise
   swallow `/jobs/events` and reject `events` as a malformed UUID. Alphabetical
   discovery happens to satisfy this today only because `e` sorts before `j`.
2. **The web home view is deliberately never unmounted.** `App.tsx:140-160`
   renders home with `hidden` rather than conditionally, because the
   verify-a-claim loop is search → moment → back → next hit, and unmounting
   would blank the query and results on every Back. A conventional `<Routes>`
   swap unmounts. This is why home stays in the layout route rather than
   becoming a discovered route of its own.

## Boundaries & Constraints

**Always:**
- The registered route table is unchanged in paths, methods, and match order.
  The existing server and web suites are the gate on that — they exercise every
  route and every navigation path.
- Server discovery runs **after** the config gate and the `require_drops_root`
  gate in `main.py`, preserving the deliberate `# noqa: E402` import ordering:
  a broken config must still surface as the config error, not as a schema-path
  or import error.
- `web/src/App.test.tsx` passes with **no changes to its assertions**. Its
  eleven cases already pin the behavior at risk — `keeps the search state alive
  behind a moment opened from a hit` (`:329`), `returns from a moment to the
  meeting list it was opened from` (`:299`), `never stacks a double-clicked
  Open twice` (`:350`). Mechanical edits to imports or to a render wrapper are
  allowed; weakening or deleting a case is not.
- Feature component prop shapes stay as they are (`onOpen?: (row) => void`,
  `onOpenMoment?: (momentId) => void`). `AppView` and `OpenView` are exported
  from `App.tsx` but imported nowhere else in `web/src`, despite the comment at
  `:11-16` claiming stories 2.3 and 3.4 reuse them — so the web blast radius is
  `App.tsx` and `App.test.tsx`, and no feature test file needs to change.
- Both ordering rules are asserted by a test, not by a comment.

**Block If:** Discovery cannot be made to preserve the existing route-match
order without hand-listing the modules — that would move the chokepoint rather
than remove it, and the story should stop and report instead of shipping a
list under a new name.

**Never:**
- No change to any route's path, method, request model, response model, or
  status codes. This story is registration only; `web/src/client` must not need
  regenerating and `make client` is not part of it.
- No new HTTP surface, no new screen, no UI copy change.
- No change to `media.py`'s internal route order — `/media/recordings/{meeting_id}`
  must stay declared before `/media/{path:path}`, and the router must not be
  split (`main.py:148-152`).
- `problems.py` keeps its explicit `register_handlers(app)` call: it registers
  exception handlers, not a router, and must not be swept into discovery.
- No route-level authentication, versioning, or prefix scheme invented along
  the way.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| Discovery finds every router | The eight modules exposing `router` (`chat`, `events`, `ingests`, `jobs`, `media`, `meetings`, `moments`, `search`) | All eight registered; the app's route table matches the pre-change table in path, method and order | No error expected |
| A module named like a router but exposing none | `chat_router.py` — question-to-template classification, not HTTP routing | Not registered. The name is a trap; selection is by attribute and `isinstance`, never by module name | No error expected |
| Modules with no router | `citations.py`, `problems.py`, `__init__.py` | Not registered. `problems.register_handlers(app)` still called explicitly | No error expected |
| The entry module itself | `main.py` is inside the scanned package | Excluded by name before import, so discovery cannot re-import the module running it | No error expected |
| Ordering hazard, events/jobs | `GET /jobs/events` | Reaches the SSE stream route, not `/jobs/{job_id}` | Never a 422 for a malformed UUID `events` |
| Ordering hazard, media | `GET /media/recordings/{uuid}` | Reaches the recording route, not the `/media/{path:path}` catch-all | Never a filesystem lookup for `recordings/<uuid>` |
| A new endpoint file is added | A module dropped into `meetingminer/api/` exposing `router` | Registered on next start with no edit to `main.py` | No error expected |
| Hand registration creeps back | `main.py` gains an `include_router` call | A test fails naming the file | Fail loud |
| Web: open a moment from a search hit, then Back | Click a hit, click `← Back` | Returns home with the query and results still rendered — home was hidden, never unmounted | No error expected |
| Web: open a moment from inside a meeting, then Back | Meeting → moment → `← Back` | Returns to that meeting, not home | No error expected |
| Web: double-clicked Open | Two rapid clicks on the same row | One history entry; one Back leaves | No error expected |
| Web: a new screen file is added | A `*.route.tsx` beside its component | Mounted on next build with no edit to `App.tsx` | No error expected |
| Web: unknown path | A URL matching no route | Renders home rather than a blank shell | No crash, no error screen |

</intent-contract>

## Code Map

Read on `main` at baseline `9cbf73b`.

- `server/meetingminer/api/main.py:56-65` — the import tuple. Seven of the nine
  names exist only to be passed to `include_router`. Two must stay as named
  imports because they are startup gates, not route registration:
  `ingests` (`:68`, `ingests.load_drop_schema(CONFIG)`) and `problems`
  (`:112`, `problems.register_handlers(app)`). **Be precise about the claim
  this story makes:** `main.py` stops being edited *to add a route*; it is not
  frozen.
- `server/meetingminer/api/main.py:129-153` — the eight `include_router` calls
  and the four comments that encode the ordering contract. The comments are the
  specification for the ordering tests; carry their reasoning into
  `registry.py` docstrings and the test names, then delete them with the block.
- `server/meetingminer/api/main.py:40-50` — the config and drops-root gates,
  and the `# noqa: E402` block comment explaining that imports come after them
  deliberately. Discovery is an import, so it lands after these.
- `server/meetingminer/api/` — eight modules define `router = APIRouter()`
  (`chat:76`, `events:42`, `ingests:255`, `jobs:15`, `media:51`, `meetings:25`,
  `moments:54`, `search:52`). `chat_router.py`, `citations.py`, `problems.py`
  and `__init__.py` define none.
- `server/meetingminer/api/events.py:42` — gets `ROUTER_ORDER` so its position
  ahead of `jobs` is declared rather than inherited from the alphabet.
- `web/src/App.tsx:17-23` — `AppView`, `OpenView`. Exported; imported nowhere
  else (verified by grep over `web/src`).
- `web/src/App.tsx:103-110` — `sameView`, the double-click guard. Becomes a
  path comparison against the current location.
- `web/src/App.tsx:112-128` — the stack and `open`/`back`. The stack is a
  hand-rolled history; browser history replaces it, and `back` becomes
  `navigate(-1)`.
- `web/src/App.tsx:130-168` — the shell. `:133` shows Back only off home;
  `:144` is the `hidden` home block that must not become a conditional render;
  `:161-167` are the two `view.kind ===` blocks that become child routes.
- `web/src/App.tsx:37-101` — `HealthPanel`. Part of the home block; it moves
  with home, unchanged.
- `web/src/App.test.tsx:187-360` — eleven cases, already the regression suite
  for everything above. `:14-30` mocks the generated sdk by listing every
  export; no sdk change here, so that block is untouched.
- `web/package.json` — no router dependency today. React 19.2, Vite 8,
  Vitest 4, jsdom 30.
- `.claude/skills/integrate/conflict-playbook.md:57,:68` — the two entries this
  story exists to retire.
- `.claude/skills/integrate/dispatch.md` — the "Standing structural note"
  section names this exact work as the outstanding force multiplier.

## Tasks & Acceptance

**Execution:**

- `server/meetingminer/api/registry.py` — new. `discover_routers() -> list[tuple[str, APIRouter]]`:
  iterate `pkgutil.iter_modules(meetingminer.api.__path__)`, skip `main` and any
  name starting with `_`, `importlib.import_module` each, keep those whose
  module-level `router` attribute passes `isinstance(obj, APIRouter)`, sort by
  `(getattr(mod, "ROUTER_ORDER", 100), name)`. Return module name alongside the
  router so a failure names the file. Docstring carries the events/jobs
  reasoning from the deleted comments. Rationale: selection by attribute and
  type is what makes `chat_router.py` — a question classifier, not an HTTP
  router — a non-event rather than a latent bug.

- `server/meetingminer/api/events.py` — add `ROUTER_ORDER = 10` with a one-line
  comment naming the hazard (`/jobs/events` vs `/jobs/{job_id}`). Rationale:
  alphabetical order satisfies this today by coincidence; a module renamed to
  sort after `jobs` would silently break the SSE stream.

- `server/meetingminer/api/main.py` — reduce the import tuple to `ingests` and
  `problems`; replace the eight `include_router` calls with a loop over
  `discover_routers()`, positioned exactly where the block was (after the CORS
  middleware, before `HealthResponse`). Keep the `# noqa: E402` placement after
  the config gates. Rationale: this is the chokepoint removal itself.

- `server/tests/test_api_registry.py` — new. Assert: every module in
  `meetingminer.api` exposing an `APIRouter` is registered, so a new file cannot
  be silently omitted; `chat_router`, `citations`, `problems`, `main` and
  `__init__` are not registered; `GET /jobs/events` reaches the SSE route and
  never returns a malformed-UUID 422; `/media/recordings/{uuid}` reaches the
  recording route rather than the catch-all; a module injected into the package
  at test time is discovered without editing `main.py`; and `main.py`'s source
  contains no `include_router` call, so hand registration cannot creep back
  unnoticed. Rationale: the four prose comments being deleted become four
  assertions.

- `web/package.json` — add `react-router` (v7) as a dependency. Rationale: the
  user asked for a real router, and its layout-route + `<Outlet />` shape is
  what lets home stay mounted while a child renders — the one property a naive
  `<Routes>` swap destroys.

- `web/src/routes/registry.ts` — new. `import.meta.glob('../features/**/*.route.tsx', { eager: true })`,
  validate each module exports a `RouteModule` (`{ path, element, order? }`),
  sort by `(order ?? 100, path)`, export the child-route array. A module missing
  a required field throws at module load naming the file. Rationale: Vite's glob
  is the web-side equivalent of `pkgutil.iter_modules` and needs no new build
  tooling.

- `web/src/features/moments/MomentView.route.tsx`, `web/src/features/moments/MeetingMoments.route.tsx`
  — new. Declare `/moments/:momentId` and `/meetings/:meetingId`, read the param
  with `useParams`, and render the existing component with the existing props.
  Rationale: these two files are the proof of the AC — a screen is now a file.

- `web/src/App.tsx` — becomes the layout route: shell, `← Back` (shown when a
  child route matches, calling `navigate(-1)`), the home block still rendered
  with `hidden` and never conditionally, `<Outlet />` where the two `view.kind`
  blocks were. Delete `AppView`, `OpenView`, `sameView`, and the stack. The
  double-click guard becomes: build the target path, compare to
  `location.pathname`, skip navigation when equal. Keep `HealthPanel` and the
  home layout byte-for-byte where possible. Wire a catch-all route to home.
  Rationale: `hidden`-not-unmounted plus one-Back-per-Open are the two
  behaviors under threat; both are pinned by existing tests.

- `web/src/App.test.tsx` — assertions unchanged. Only the mechanical changes a
  router forces (a wrapper, or letting `App` own its own browser router in
  jsdom) are permitted. If a case cannot pass without weakening it, stop and
  report rather than editing the assertion. Rationale: this suite is the whole
  safety net for the web half.

- `.claude/skills/integrate/conflict-playbook.md` — rewrite the `main.py` and
  `App.tsx` entries: they are no longer merge hazards, and the note should say
  what replaced them so a future conflict on `registry.py` is recognized for
  what it is.

- `.claude/skills/integrate/dispatch.md` — retire the "Standing structural note"
  and record the outcome, so the next dispatch does not re-offer work already done.

- `_bmad-output/planning-artifacts/epics.md` — add Story 2.8 under Epic 2, in
  the Given/When/Then form stories 2.6 and 2.7 use.

- `_bmad-output/implementation-artifacts/sprint-status.yaml` — add
  `2-8-auto-discovered-route-registration`. `story-id: status` line only.

**Acceptance Criteria:**
- Given the api as built, when it starts, then every module in
  `meetingminer.api` exposing an `APIRouter` is registered and the route table
  matches the pre-change table in path, method and match order.
- Given a new endpoint module dropped into `meetingminer/api/`, when the api
  starts, then its routes serve without any edit to `main.py`.
- Given `GET /jobs/events`, when it is requested, then it reaches the SSE
  stream and never returns a malformed-UUID 422 — asserted by a test, not by a
  comment.
- Given `chat_router.py`, which is a question-to-template classifier rather
  than an HTTP router, when discovery runs, then it is not registered.
- Given a new screen shipped as a `*.route.tsx` file, when the web app builds,
  then the screen mounts at its path without any edit to `App.tsx`.
- Given a moment opened from a search hit, when `← Back` is pressed, then the
  query and its results are still rendered — home was hidden, never unmounted.
- Given a moment opened from inside a meeting, when `← Back` is pressed, then
  the meeting is shown rather than home.
- Given two rapid clicks on the same Open control, when Back is pressed once,
  then the reader has left that view.
- Given the full suites, when they run, then `make web-test` and the server
  suite pass with `App.test.tsx`'s assertions unmodified.
- Given the merged story, when `conflict-playbook.md` is read, then neither
  `api/main.py` nor `App.tsx` is listed as a parallel-work disqualifier.

## Design Notes

**Why the web half is not a plain `<Routes>` swap.** The obvious shape —
`<Routes><Route path="/" element={<Home/>}/>…</Routes>` — unmounts home when a
child matches, which blanks the search query and results on every Back and
forces a re-search plus a re-seeded meetings stream. `App.tsx:140-143` says so
explicitly and `App.test.tsx:329` tests it. The layout-route shape keeps home
in the parent and puts children in `<Outlet />`, so `hidden` still works and
the behavior is preserved rather than reconstructed.

**URLs are a side effect, not a requirement.** No acceptance criterion in
`epics.md` and nothing in `ux-spine.md` asks for addressable or shareable
screens. Real URLs fall out of using a router and are welcome — a moment
becomes linkable, which helps the demo — but no sharing affordance, no
copy-link control, and no deep-link entry state is in scope. If shareable
citations are wanted, that is a separate story with its own AC.

**Why `ROUTER_ORDER` rather than sorting routes by specificity.** Sorting
literal path segments ahead of parameterized ones would remove the ordering
hazard class outright instead of preserving it. It is the better long-term
answer and it is deliberately not taken here: it changes matching for every
route at once, and this story's whole value depends on the route table being
provably unchanged. `ROUTER_ORDER` keeps the change to registration alone.
Specificity sorting is worth its own story once this one has landed — filed as
a design note rather than a deferred item, because nothing is broken today.

**What this does not buy.** Two stories touching the *same* new route file, or
the same feature component, still conflict. What is removed is the conflict
that has nothing to do with the work: two unrelated stories colliding purely
because both had to add a line to the same registration block.

**Sequencing.** This pays only if it lands before `4-2`, `4-3` and `4-4`.
Story `3-4` does not need it and should not wait for it, but `3-4` is a web
story that will edit `App.tsx` — so whichever of the two lands second resolves
a conflict there. Landing `2-8` first makes `3-4` add a route file instead,
which is the cheaper order.

## Review Triage Log

### 2026-08-21 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 10: (high 0, medium 2, low 8)
- defer: 1: (high 0, medium 0, low 1)
- reject: 13
- addressed_findings:
  - `medium` `patch` Web discovery mechanism had no direct tests while its server twin had a full suite — added `web/src/routes/registry.test.ts` (10 tests: shipped-paths floor, all `routeOf` validation errors naming the file, the `(order ?? 100, path)` sort).
  - `medium` `patch` Back on a deep-linked child route called `navigate(-1)` with no in-app history, doing nothing or leaving the site — Back now falls back to `navigate('/', { replace: true })` when react-router's history index is 0, pinned by a new deep-link test case.
  - `low` `patch` The forward-looking moments ordering hazard (`/moments/recent` vs `/moments/{moment_id}`) dropped with the old `main.py` comments — carried into `registry.py`'s docstring.
  - `low` `patch` A failed import during discovery gave no module context — re-raised naming `meetingminer.api.<module>`.
  - `low` `patch` Non-recursive scan limit (subpackage routers not discovered) was undocumented — stated in `registry.py`'s docstring.
  - `low` `patch` `registry.py` docstring claimed duplicate-path detection that does not exist — claim removed.
  - `low` `patch` `_flat_routes` depended on FastAPI's private `original_router` with no loud-failure guard — call sites now assert non-empty flattening; dependency named in the docstring.
  - `low` `patch` The `features/`-only glob constraint was undocumented — a `*.route.tsx` elsewhere is silently undiscovered; stated in the `RouteModule` doc.
  - `low` `patch` Web `order` doc implied FastAPI-style match-order semantics; react-router ranks by specificity — doc corrected to what `order` actually controls.
  - `low` `patch` `useOpenPath`'s `window.location.pathname` comparison assumes `BrowserRouter` with no basename — assumption documented.

## Verification

- `cd server && uv run pytest tests/test_api_registry.py -q` — the new suite.
- `cd server && uv run pytest tests/ -q` — the route-table regression: the api
  suites exercise every route, so an accidental path, method or ordering change
  surfaces here rather than in a snapshot list that would become a second
  hand-maintained registry.
- `make web-test` — `App.test.tsx` assertions unmodified.
- `pnpm --dir web run build` — `tsc -b` proves the discovered route array is
  typed, since `import.meta.glob` returns `unknown` values by default.
- `pnpm --dir web run lint`.
- Manual: start the api, confirm `GET /jobs/events` streams and
  `GET /openapi.json` lists the same paths as before the change.

## Auto Run Result

Status: done (2026-08-21 unattended build-auto run, branch `story/2-8`, baseline `527acf00f81834c5eb2385df002b2ce4e2a0ee74`)

**Implemented change.** Both hand-maintained registration blocks replaced with
discovery. Server: `api/registry.py` walks `meetingminer.api` with
`pkgutil.iter_modules`, selects modules by `isinstance(module.router, APIRouter)`,
orders by `(ROUTER_ORDER, name)` (`events.py` declares `ROUTER_ORDER = 10` for
the `/jobs/events` vs `/jobs/{job_id}` hazard); `main.py` keeps only the
`ingests`/`problems` gate imports and calls `register_routers(app)` after the
config gates. Web: `App.tsx` is a react-router 7 layout route — home rendered
`hidden`, never unmounted; `<Outlet />` for children; Back = `navigate(-1)` with
a home fallback when there is no in-app history; catch-all renders home. Child
routes discovered by `routes/registry.ts` (`import.meta.glob` over
`features/**/*.route.tsx`); `MomentView.route.tsx` and `MeetingMoments.route.tsx`
are the first two discovered screens. Route table proven unchanged: 12
path+method pairs identical pre/post, both ordering hazards asserted by tests.

**Files changed.**
- `server/meetingminer/api/registry.py` — new; discovery, ordering, attributed import errors, hazard docstrings.
- `server/meetingminer/api/events.py` — `ROUTER_ORDER = 10` with the hazard named.
- `server/meetingminer/api/main.py` — registration block replaced by `register_routers(app)`; gates untouched.
- `server/tests/test_api_registry.py` — new; 8 tests (discovery floor, exclusions, both dispatch hazards, drop-in module, no-`include_router` source pin).
- `web/package.json`, `web/pnpm-lock.yaml` — `react-router ^7.18.2`.
- `web/src/App.tsx` — layout route; stack/`AppView`/`OpenView`/`sameView` deleted; deep-link Back fallback.
- `web/src/App.test.tsx` — assertions unchanged; `beforeEach` URL pin plus two new cases (unknown path, deep-link Back).
- `web/src/routes/registry.ts`, `registry.test.ts` — glob discovery with validation; 10 tests.
- `web/src/routes/navigation.ts` — `useOpenPath` double-click guard as path comparison.
- `web/src/features/moments/MomentView.route.tsx`, `MeetingMoments.route.tsx` — new route files.
- `.claude/skills/integrate/conflict-playbook.md`, `dispatch.md` — the two chokepoint entries retired.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — `2-8` line added.

**Review findings breakdown.** 4 review layers (blind hunter, edge-case hunter,
verification-gap, intent-alignment). Patches applied: 10 (2 medium — missing web
discovery tests, deep-link Back defect; 8 low — doc/attribution/guard fixes).
Deferred: 1 (SPA history fallback for future production hosting; see frontmatter).
Rejected: 13 (hypothetical future-module scenarios, test-style nits where the
existing suites are the intent-named gate, playbook-tense complaint).

**Follow-up review recommendation:** true — patched counts high 0, medium 2,
low 8; score 3×2 + 8 = 14 ≥ 5.

**Verification performed** (all observed directly by the orchestrating session
after the patch commits):
- `server: uv run --project . pytest tests/test_api_registry.py -q` — 8 passed.
- `server: uv run --project . pytest tests/ -q` — 1505 passed, 1 pre-existing deprecation warning (6m26s).
- `make web-test` — 11 files, 187 tests passed.
- `pnpm --dir web run build` — `tsc -b` + vite build succeeded.
- `pnpm --dir web run lint` — exit 0; three fast-refresh warnings (one pre-existing, two inherent to the `.route.tsx` pattern).
- Manual-check substitute: old and new registration loaded in one process; route tables compared — 12 path+method pairs identical, `/jobs/events` before `/jobs/{job_id}`, media recording route before the catch-all.

**Residual risks.**
- `_flat_routes` in the registry tests reads FastAPI's private `_IncludedRouter.original_router` (0.141); a FastAPI upgrade dropping it now fails loudly rather than vacuously, but the helper will need rewriting then.
- The deep-link Back fallback reads react-router's history index from `window.history.state.idx` — documented in code and pinned by a test.
- Deployed static hosting will need an SPA history fallback (deferred item).
- Registration order changed from the old hand order to discovery order; match semantics proven equivalent, but `openapi.json` path listing order could differ in principle (observed identical).

### Review Findings

- [x] [Review][Patch] Preserve the complete baseline API registration order [server/meetingminer/api/registry.py:77] — the eight shipped routers now declare their baseline positions, and a regression test pins their complete sequence.
- [x] [Review][Patch] Cover attributed discovery-import failures [server/meetingminer/api/registry.py:66] — a temporary broken discovered module now proves the wrapper names its fully qualified module and retains its original cause.
