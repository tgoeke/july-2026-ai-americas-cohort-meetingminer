# Conflict playbook

Every conflict listed here is **proximity, not disagreement** — two stories
adding two unrelated things near each other. The resolution is almost always
*union both sides*, never *pick one*. Picking one is how a passing suite starts
failing on a file nobody edited.

After resolving any shared file, **re-run the suites of both stories**, not
just the one you are landing.

## `_bmad-output/implementation-artifacts/sprint-status.yaml`

Merged by a custom driver (`_bmad/scripts/merge_sprint_status.py`) registered
through `.gitattributes`. It merges **by key**, not by line: for each
`story-id: status` it keeps unchanged keys, takes the single changed side, and
on a two-sided disagreement takes the furthest-along status
(`backlog` → `ready-for-dev` → `in-progress` → `review` → `done`), reporting it
on stderr. What it cannot decide it leaves as a normal conflict, by design.

Two things follow:

- **Install the driver once per clone** — `.gitattributes` selects a driver but
  cannot define one:
  ```bash
  _bmad/scripts/install_merge_drivers.sh
  ```
  Worktrees share the clone's config, so this is per-clone, not per-worktree.
  If you see line-proximity conflicts in this file, the driver is not installed.
- **The driver takes surrounding text from `ours`**, so a comment or note added
  on the other branch is *silently dropped*. Narrative goes in
  `sprint-notes.md`. Keep this file to `story-id: status` lines.

## `server/tests/projection_seed.py` — `seed_meeting()`

The worked example, and the pattern to copy. `story/3-2` added a `started_at`
keyword parameter (cross-meeting time-order assertions need distinct
`startedAt` values); `story/2-3` added `screen_view_types`. Both were correct
and both were needed. **On `main` today the signature carries both** — that
union is the resolution, already landed.

Expect the same shape again: this file is seeded by every store-backed story.
**Union the parameters.** Then run both suites:

```bash
server/tests/test_projections_traversals.py    # 3-2
server/tests/test_api_moments.py               # 2-3
```

An auto-merge that drops either parameter breaks the other story's tests, and
does so silently until that suite runs.

This is the sanctioned shape for shared low-level additions per `AGENTS.md`: a
fixture or predicate added by two stories is fine as long as its exact
definition is pinned in both story contracts. `evidence_complete()` in
`domain/jobs.py` went through this cleanly across stories 1.7 and 1.9.

## `server/meetingminer/api/main.py` — no longer a merge hazard

Story 2.8 removed the hand-edited router block: routers are discovered by
`server/meetingminer/api/registry.py` (any module in `meetingminer.api`
exposing a module-level `fastapi.APIRouter` named `router`), so an API story
adds a *file*, not a line here. `main.py` contains no `include_router` call at
all — `tests/test_api_registry.py` fails if one creeps back — so do not
resolve a conflict by re-adding one.

What can still conflict, and what it means:

- **`registry.py` itself**: two stories editing discovery or its ordering
  rules genuinely disagree about registration policy. That is a contract
  problem, not a union — stop and surface it.
- **`ROUTER_ORDER` in a module**: a declared registration-order contract
  (`events.py` carries `ROUTER_ORDER = 10` so `/jobs/events` beats
  `/jobs/{job_id}`). Two stories setting orders on colliding prefixes need the
  ordering tests in `test_api_registry.py` run, not a blind union.
- **`main.py`** still holds the startup gates (config, drops root, publish
  root, drop schema, embedder, `problems.register_handlers`). Stories editing
  *those* can conflict here the ordinary way; union as usual.

## `web/src/App.tsx` — no longer a merge hazard

Same story, same fix: `App.tsx` is a react-router layout route (shell + home)
and screens are `*.route.tsx` files beside their components, discovered by
`web/src/routes/registry.ts` via `import.meta.glob`. A story adding a screen
adds a route file; two such stories touch disjoint files. `App.tsx` is only
edited to change the shell or the home block itself — a conflict there is a
real disagreement about the shell, not registration proximity. The home block
must stay rendered `hidden`, never conditionally — `App.test.tsx` pins it.

## `server/tests/conftest.py`

Story 4.1 adds fake-LLM fixtures near the fixture block that API-test stories
also extend. Union the fixtures. The suites themselves are concurrency-safe
(story 2.7) — this is a text conflict only.

## `web/src/client/`

Generated, not hand-written. Never hand-resolve it. Take either side, then
regenerate against a running api:

```bash
make client
```

Commit the result.

## Anything not listed

If two branches genuinely disagree about behavior, that is not a merge
resolution — it is a contract problem. Stop, and say so. Per `AGENTS.md`: the
per-story frozen contract names the files that story owns; if a story edited a
file another in-flight story owns, surface it rather than quietly picking a
winner.
