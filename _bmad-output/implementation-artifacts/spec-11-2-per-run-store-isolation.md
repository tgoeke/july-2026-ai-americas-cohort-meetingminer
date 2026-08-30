---
title: 'Per-Run Store Isolation'
type: 'chore'
created: '2026-08-30'
status: 'done'
baseline_commit: '947b9cfcde37b312003a97237658246b50030334'
baseline_revision: 'de0fc0816c26a8131fdc153368719e6f3808f40e'
reviewed_head: 'fa86b864c7101e2a45d2c278a9562669c72d962c'
review_loop_iteration: 0
followup_review_recommended: true
context: ['{project-root}/AGENTS.md']
warnings: ['multiple-goals', 'oversized']
deferred:
  - summary: >-
      docs/project-record.md still describes the cross-worktree lock over shared stores as the platform and lists 11.2 as not started.
    evidence: |-
      Blind Hunter finding (project-record.md:88, :286-292). By the repository's convention the project record is written at integration (story 11.1 deferred the same item); the story's account lives in AGENTS.md, README.md, project-context.md and the backlog.
    location: >-
      docs/project-record.md
    severity: low
  - summary: >-
      evals/README.md and evals/RUNBOOK.md still say an eval run holds "the shared Docker stores" one agent at a time.
    evidence: |-
      Blind Hunter finding (evals/README.md:280; RUNBOOK.md:98-101). The evals-run rule stays serial until story 11.3, which owns the evals documentation; this story does not change what evals/ reads.
    location: >-
      evals/README.md
    severity: low
---

<intent-contract>

## Intent

**Problem:** Every checkout shares one Docker stack on fixed ports with fixed container names, so two worktrees running `make test` queue on the cross-worktree projection lock, and the lock-timeout test (backlog B-14) can observe another worktree's holder. Owner direction 2026-08-29: the machine has 128 GB; use it.

**Approach:** `make worktree STORY=<slug>` provisions a private compose stack per worktree — Postgres, Neo4j, Meilisearch, and both test twins — as compose project `meetingminer-<slug>` on ports allocated for that worktree, and writes them to a generated, gitignored `.env.worktree` that the Makefile, `docker compose --env-file`, and the Python config loader all read. `worktree-remove`/`worktree-prune` tear the stack down; `test-db-prune` also removes orphaned stacks. The projection lock gains an env override for its key (B-14). AGENTS.md is rewritten to the new mechanism.

## Boundaries & Constraints

**Always:**
- With no `.env.worktree` present, every default reproduces today's stack exactly: project `meetingminer`, container names `meetingminer-<service>`, ports 5433/7474/7687/7700/7475/7688/7701, volume names unchanged. The main checkout's live corpus volumes are never renamed, recreated, or removed.
- `.env` stays the symlink to the main checkout's file; it is never rewritten. `.env.worktree` is a second file beside it, generated only by `make worktree`, covered by the existing `.env.*` gitignore rule.
- Precedence for location values remains process environment > `.env.worktree` > `.env` (the existing blank-value rule kept). The ownership identity is the exception: `MM_STACK_NAME` and `MM_STACK_ID` come only from the checkout's validated `.env.worktree` (or the main-checkout defaults) and process values cannot override them. The three readers (Makefile `include`, compose `--env-file`, loader) read the same `KEY=value` lines.
- Store endpoint overrides are ports only (`MM_POSTGRES_PORT`, `MM_NEO4J_BOLT_PORT`, `MM_MEILI_PORT`); host and credentials stay in `config.yaml`/`.env`. An invalid value is a named `ConfigError`, never a fallback.
- `docs/architecture.md` AD-10 gains one sentence admitting a checkout's private stack name, generated incarnation identity, and ports to the environment; nothing else in the spine changes.
- `MM_PROJECTION_LOCK_KEY` is inactive by default; the unset derivation stays byte-identical (`test_lock_paths_stay_byte_compatible_with_the_conftest_scheme` must keep passing unchanged).
- The `define PRUNE_TEST_DBS` block keeps its exact shape (`test_parallel_store_safety.py:187-277` execs it with fakes); stack pruning is a separate recipe line running `infra/worktree_stack.py`.
- Stack pruning removes only projects named `meetingminer-<slug>` (never `meetingminer`, never another project) whose owning checkout directory no longer exists; anything with an existing directory is reported as owned and skipped.
- The frozen contract of `test_compose_contract.py` holds: five services by name, every published port string starts with `127.0.0.1:`, `test-fast` keeps its exact prerequisite set and one-command recipe, `test:` stays one physical rule line naming `infra-up` after `puller-test`.
- Stage only the paths below; commit each unit; push. Never `make evals-run`.

**Block If:**
- Bringing up a second full stack fails for a capacity reason on this machine (OrbStack VM memory cap, port range exhausted) that cannot be fixed inside the story's files.
- A test outside this story's boundary fails only because dev endpoints are now env-overridable, and fixing it needs a file the boundary excludes.

**Never:**
- Per-session ephemeral Neo4j containers or a Meilisearch index prefix (owner simplification 2026-08-29).
- Per-worktree api/web ports (`API_PORT` 8000, `WEB_PORT` 5173) — record as a backlog item, do not build.
- Writing ports into the tracked `config.yaml`, or a generated second `config.yaml` via `MM_CONFIG_PATH`.
- Changing what `evals/` reads, or the `evals-run` serial rule (story 11.3).
- Editing `web/`, `tools/`, `docs/project-record.md` (recorded at integration), `server/meetingminer/` beyond `config.py` and `projections/locks.py`.
- Capping Neo4j/Meilisearch memory in compose; measure and document instead.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Provision | `make worktree STORY=11-2-probe` (Docker up) | worktree on `story/11-2-probe` from `BASE` (default `main`); `.env` symlinked; `.env.worktree` written with `MM_STACK_NAME=meetingminer-11-2-probe` + 7 ports + `MM_TEST_NEO4J_URI`/`MM_TEST_MEILI_URL`; `make -C <wt>/infra infra-up` brings project `meetingminer-11-2-probe` up healthy; banner names the ports | Docker down: worktree and env file stay, named error says `cd <wt> && make infra-up` |
| Port choice | slug hashes to a base whose ports are taken (bound, or declared in a sibling's `.env.worktree`) | next base (+10, wrapping inside 20000–23999) with all 7 free | 400 bases exhausted → named error, no file written |
| Bad slug | `STORY=Foo_Bar!` | refused before any git action: slug must match `[a-z0-9][a-z0-9._-]*` | exit 1 with the rule |
| Main checkout | `make infra-up`/`make test` with no `.env.worktree` | today's project, names, ports; `check-dev-stores` probes 7700/7687 | unchanged |
| Worktree checkout | `uv run --project server pytest server/tests` directly (no make) | loader reads `.env.worktree`; `app_config` dev endpoints on the private ports, twins from `MM_TEST_*` in the file; per-run databases on the private Postgres | twins down → existing named skip / `MM_REQUIRE_TEST_STORES=1` failure, naming the private URLs |
| Override value | `MM_POSTGRES_PORT=abc` or `70000` | `ConfigError` naming the variable and the rule | fail before any connection |
| URI without port | `stores.neo4j.uri: bolt://host` + `MM_NEO4J_BOLT_PORT=1` | `bolt://host:1` | — |
| Lock key | `MM_PROJECTION_LOCK_KEY=b14-<run>` | lock at `<tmp>/meetingminer-projections-b14-<run>.lock`; unset → sha256 derivation as today | value outside `[A-Za-z0-9._-]{1,64}` → `ConfigError` naming the variable |
| Remove | `make worktree-remove STORY=x` | reads stack name from `<wt>/.env.worktree` (fallback `meetingminer-x`) first, runs `git worktree remove`, and only after that succeeds runs `docker compose -p <name> down -v --remove-orphans` | dirty tree → git refuses as today and the stack is left intact; stack already gone → note, exit 0 |
| Prune orphans | `make test-db-prune`; project `meetingminer-gone` has containers/volumes whose `working_dir` label parent no longer exists | `down -v` for it; prints `removed stack meetingminer-gone`; owned stacks print `skipped owned <name> (<dir>)`; `meetingminer` never listed | docker unavailable → named error, non-zero |
| Prune volumes-only | project `meetingminer-x` has volumes but no containers, `<WT_ROOT>/x` absent | volumes removed; present → skipped owned | — |
| `down` fallback | `.env` unreadable in a worktree | `docker compose -p $(MM_STACK_NAME) down` | as today |

</intent-contract>

## Code Map

- `infra/docker-compose.yml:6` `name: meetingminer` → `${MM_STACK_NAME:-meetingminer}`; `:13,34,52,83,101` `container_name:` → `${MM_STACK_NAME:-meetingminer}-<service>`; ports `:22` `"127.0.0.1:${MM_POSTGRES_PORT:-5433}:5432"`, `:38-39` `MM_NEO4J_HTTP_PORT:-7474` / `MM_NEO4J_BOLT_PORT:-7687`, `:58` `MM_MEILI_PORT:-7700`, `:87-88` `MM_NEO4J_TEST_HTTP_PORT:-7475` / `MM_NEO4J_TEST_BOLT_PORT:-7688`, `:107` `MM_MEILI_TEST_PORT:-7701`. Volumes `:117-124` untouched (compose prefixes them with the project name). Verified 2026-08-30 with compose v5.1.2: interpolation works in `name`, `container_name`, ports; a second `--env-file` wins; `-p` wins over `name`.
- `infra/Makefile:10` `ENVFILE`; add `WT_ENVFILE := $(ROOT)/.env.worktree`, `-include $(WT_ENVFILE)`, `?=` defaults for the eight `MM_*` names; `:27` `COMPOSE` → add `$(if $(wildcard $(WT_ENVFILE)),--env-file $(WT_ENVFILE),) -p $(MM_STACK_NAME)`; `:82-86` `.PHONY`; `:131-141` help (worktree rows, the "Worktrees isolate CODE, not the Docker stores" lines); `:206-218` `WT_ROOT`/`worktree` (`WT_ROOT` must become lazy `=` from `git rev-parse --path-format=absolute --git-common-dir` so a worktree's Makefile places siblings beside the main repo; add `BASE ?= main`; slug check; env file via `python3 $(INFRA)/worktree_stack.py provision`; `$(MAKE) --no-print-directory -C $(WT_ROOT)/$(STORY)/infra infra-up`); `:223-226` `worktree-remove`; `:237-253` `worktree-prune` loop (tear down per pruned worktree); `:386-393` `check-dev-stores` literals → `$(MM_MEILI_PORT)` / `$(MM_NEO4J_BOLT_PORT)`; `:457-459` `test-db-prune` (+ line: `python3 $(INFRA)/worktree_stack.py prune --worktree-root $(WT_ROOT)`); `:795` `docker compose -p meetingminer down` → `-p $(MM_STACK_NAME)`. GNU Make 3.81 on this machine: no `$(file)`, `-include` and `$(wildcard)` fine; keep recipes free of anything that expands differently between `-n` and `--debug=basic` (`test_compose_contract.py:186-204`).
- `infra/worktree_stack.py` -- NEW, stdlib only (`python3` 3.14 here): `SERVICES` port table with defaults; `allocate_ports(slug, taken, probe)` deterministic base `20000 + (zlib.crc32(slug) % 400) * 10`, 7 ports base+1..+7, skip on any taken; `taken_ports(worktree_root)` from sibling `*/.env.worktree`; `render_env(slug, ports)`; `provision` subcommand (`--slug --worktree --worktree-root`); `prune` subcommand using `docker ps -a --filter label=com.docker.compose.project --format '{{.Label "com.docker.compose.project"}}\t{{.Label "com.docker.compose.project.working_dir"}}'` and `docker volume ls --filter label=com.docker.compose.project --format '{{.Name}}\t{{.Label "com.docker.compose.project"}}'`; owner = parent of `working_dir` (containers) or `<worktree_root>/<slug>` (volumes only); `docker compose -p <name> down -v --remove-orphans`; docker calls through one injectable `run` callable for tests.
- `server/meetingminer/config.py:41` filenames (+ `WORKTREE_ENV_FILENAME = ".env.worktree"`); `:1-20` docstring ("carry secrets and MM_CONTENT_ROOT only" → amend); `:737-762` `_read_env_file` / `_load_secrets` merge → extract public `merged_env(env_path) -> dict[str, str]` (`.env`, then `env_path.parent / ".env.worktree"` overriding, then process env with the blank rule at `:759-762`); `:211-230` store models (frozen-by-`extra=forbid`, rebuild via `model_validate`); `:968-1012` `load_config` → after `Settings.model_validate`, apply `_apply_stack_overrides(settings, env)` for the three port names (int 1..65535 else `ConfigError` naming the variable; URI port replaced via `urlsplit`, host required). `Secrets`/`AppConfig` untouched.
- `server/meetingminer/projections/locks.py:53` `TIMEOUT_ENV`; `:56-63` `store_lock_paths` → honour `MM_PROJECTION_LOCK_KEY` (`KEY_ENV`), validated `^[A-Za-z0-9._-]{1,64}$`, else the sha256 key; module docstring `:18-21` rewrite ("worktrees share one compose stack" is no longer the rule).
- `server/tests/conftest.py:197-201` twin URLs → `_STACK_ENV = merged_env(REPO_ROOT / ".env")`, `TEST_NEO4J_URI = _STACK_ENV.get("MM_TEST_NEO4J_URI") or "bolt://localhost:7688"` (same for Meili); `:295-303` `app_config` unchanged (explicit `REPO_ROOT` paths already give each worktree its own files); `:1091-1109` `stores_up` message names the resolved URLs already.
- `server/tests/test_parallel_store_safety.py:311-321` `_lock_process_script` and `:324-398` the B-14 test → pass `MM_PROJECTION_LOCK_KEY=f"b14-{RUN_ID}"` to holder and waiter; assert the lock path in the diagnostic carries that key; `:35-65` runs the real `make test-db-prune` (now also the stack sweep — owned stacks are skipped, so it stays safe).
- `server/tests/test_projections_locks.py:51-62` byte-compat test stays; add `test_lock_key_env_override_names_its_own_file` and `test_lock_key_env_override_rejects_bad_values`.
- `server/tests/test_projections_search.py:603-624` guard unchanged; `:626-644` alias pairs → derive from the dev config's actual endpoints (swap `localhost`↔`127.0.0.1` on the dev host, keep its port) so the guard is exercised on whatever ports this checkout uses.
- `server/tests/test_config.py:232-266,362-394` env precedence tests (pattern: `tmp_path` config + `.env`, `monkeypatch`); add: worktree file overrides `.env`; process env overrides worktree; blank process value does not mask; the three port overrides (valid, invalid, out of range, URI without port); `/config`-visible effect via `load_config(...).settings.stores`.
- `server/tests/test_makefile_procs.py:54-60` `_tree_vars` → add `WT_ENVFILE=<tmp>/.env.worktree` (absent) so `:752` `compose -p meetingminer down` keeps holding; add one test writing that file and asserting the decoy sees `--env-file <tmp>/.env --env-file <tmp>/.env.worktree` and `-p meetingminer-probe` on `down`.
- `server/tests/test_compose_contract.py:37-76` compose tests → add: `name`/`container_name` interpolate `MM_STACK_NAME` with default `meetingminer`; each published host port is `${MM_<X>_PORT:-<default>}` and the defaults equal `worktree_stack.DEFAULT_PORTS`; `TEST_FAST_PREREQUISITES:294`, `SLOW_MODULES:396` unchanged (new test module is fast).
- `server/tests/test_worktree_stack.py` -- NEW fast module (load `infra/worktree_stack.py` via `importlib` from `REPO_ROOT`): determinism, collision skip, sibling-declared ports count as taken, wrap and exhaustion, rendered file round-trips through `dotenv_values`, prune classification (owned / orphan containers / orphan volumes / foreign project / main project) with a recording fake `run`.
- `.env.example:1-3` header → mention `.env.worktree`; `AGENTS.md:69-141` section rewrite (+ fix the dangling "recorded in docs/backlog.md" to story 11.3) and `:44-67` worktree section (stack provisioned; `make up` in a worktree still collides on api/web ports); `project-context.md` policy + "Running and verifying" bullets on shared stores / `make migrate`; `README.md:170-176` address table (defaults; worktrees differ), `:214` migrate row, `:223` worktree row, `:225-229`, `:280-284`, `:342-346`; `docs/glossary.md:302-306` two entries; `docs/backlog.md:137-145` B-14 → "Removed from this list" in the B-1 form with the count at `:309`, plus a new item for per-worktree api/web ports; `docs/architecture.md:109-113` AD-10 sentence.
- Measured 2026-08-30 before the change (`docker stats`, shared stack idle after a full run): neo4j-test 1.21 GiB, neo4j 578 MiB, meilisearch-test 111 MiB, postgres 89 MiB, meilisearch 43 MiB — ≈2.0 GiB per stack; Docker (OrbStack) VM reports 23.5 GiB total against the host's 128 GB, so the VM allocation, not the host, bounds the stack count.

## Tasks & Acceptance

**Execution:**
- `infra/worktree_stack.py` + `server/tests/test_worktree_stack.py` -- write the allocator, renderer, and pruner with their fast tests first -- the Makefile and the docs both cite its names and defaults.
- `infra/docker-compose.yml` -- interpolate project name, container names, and host ports with today's values as defaults -- one file serves every stack.
- `server/meetingminer/config.py` + `server/tests/test_config.py` -- `merged_env`, `.env.worktree` precedence, the three port overrides -- every server entrypoint and the eval harness resolve the private stack through the one loader.
- `server/meetingminer/projections/locks.py` + `server/tests/test_projections_locks.py` -- `MM_PROJECTION_LOCK_KEY` -- B-14.
- `server/tests/conftest.py`, `test_parallel_store_safety.py`, `test_projections_search.py` -- twin URLs from the merged env; B-14 test on its own key; alias guard derived from the live dev endpoints.
- `infra/Makefile` + `test_makefile_procs.py` + `test_compose_contract.py` -- include, defaults, `COMPOSE`, `check-dev-stores`, `down`, `worktree`/`-remove`/`-prune`, `test-db-prune`, help -- the mechanism, pinned.
- `.env.example`, `AGENTS.md`, `project-context.md`, `README.md`, `docs/glossary.md`, `docs/backlog.md`, `docs/architecture.md` -- the documented truth follows the code; B-14 retired on evidence; api/web ports filed.
- Verification -- provision a probe worktree from this branch, run `make test` alone and concurrently, `docker stats` both stacks, prune an orphan, record numbers in the report.

**Acceptance Criteria:**
- Given this branch's Makefile, when `make worktree STORY=11-2-probe BASE=story/11-2` runs, then `../meetingminer-wt/11-2-probe/.env.worktree` exists, `docker compose ls` shows `meetingminer-11-2-probe` running(5) beside `meetingminer` running(5), and `docker ps` shows both sets of container names on different ports.
- Given a worktree with a stack, when `uv run --project server pytest -m "" server/tests/test_projections_search.py::test_configured_projection_stores_are_reachable` runs there with `MM_REQUIRE_TEST_STORES=1`, then it passes against that worktree's twin ports (visible in `app_config`), and the same node id in the main checkout still passes against 7688/7701.
- Given two worktrees each with a stack, when `time make test` runs in both at once, then both exit 0, neither run's projection tests wait on the other's lock (`ProjectionLockedError` never appears; the lock paths differ), and the wall-clock alone and concurrent is recorded in the report.
- Given `MM_PROJECTION_LOCK_KEY` set for the B-14 test's subprocesses, when a second process holds the URL-derived lock for the same stack, then the test still passes.
- Given a worktree directory deleted by hand while its stack runs, when `make test-db-prune` runs, then the stack and its volumes are removed and every stack whose directory exists is reported skipped owned; `meetingminer` is never touched.
- Given `make worktree-remove STORY=11-2-probe`, when it runs, then project `meetingminer-11-2-probe` is gone from `docker compose ls -a` and `docker volume ls` shows no `meetingminer-11-2-probe_*` volume.
- Given AGENTS.md, README.md, project-context.md, and the glossary, when a builder reads them, then none says the stores are shared across worktrees; each states the per-worktree stack, the measured memory per stack, the OrbStack VM bound, and that api/web ports are still fixed.

## Remediation Plan — follow-up review 2026-08-30

The follow-up review (`review-story-11-2-2026-08-30.md`, reviewed head `fa86b86`, base `de0fc08`) returned 7 blocking findings (4 high, 3 medium) and 3 low ones; its handoff is `build-prompt-story-11-2-2026-08-30.md`. Both files sit beside this spec. The `### Review Findings` checklist at the end of this file is the list to close; this section is how. The intent-contract above is unchanged: no finding has a specification root cause.

### Harness (unchanged from the first round, restated because it is binding)

- Work only in `/Users/devopsterus/current/cohort/meetingminer-wt/11-2` on branch `story/11-2` (HEAD `fa86b86`, clean, pushed; its private stack `meetingminer-11-2` is up on 21761–21767). `_bmad-output` there is a symlink to the main checkout's. Never edit the main checkout; never touch the reviewer's worktree `../meetingminer-wt/11-2-review` or its stack `meetingminer-11-2-review`; never touch the `meetingminer` project or its volumes. The Bash sandbox denies writes outside the main checkout, so run every command in the worktree with `dangerouslyDisableSandbox: true`. Bare `ls` is broken here — use `find`/`git ls-files`.
- Commit each coherent unit as it completes and push `story/11-2` — no permission needed; stage only the paths you changed; never `git add -A`, never reset/stash/clean. Never `make evals-run`.
- `pytest` needs a path under `server/tests`; a `slow` module by path needs `-m ""`; the fast set is budgeted at 2.0s per test (`server/tests/fast_budget.py`) and a new `slow` mark is also an edit of `SLOW_MODULES`/`SLOW_TESTS` in `server/tests/test_compose_contract.py`.
- **Red first.** For every defect below, write the regression, run it against the unfixed tree and record the observed failure (test id + the assertion that failed) in `## Auto Run Result` before changing production code. A test never seen red does not count. Run the red tests with `git stash` NOT allowed — instead commit the tests first (they fail), then the fix (they pass); or run them from a scratch copy of the pre-fix module. The commit sequence "tests red → fix green" is the evidence.

### Harness addendum 2026-08-30 (~14:00) — the wave context

Binding, from `build-prompt-story-11-2-remediation-2026-08-30.md` and `wave-2026-08-30-rules.md` beside this spec (read both). Where this conflicts with the Harness bullets above, this wins:

- `_bmad-output/` is now **tracked on main** (owner decision; main moved `de0fc08` -> `211857c`). Before anything else in the worktree: `rm _bmad-output` (it is a hand-made symlink; this removes the link only), then `git fetch origin && git rebase origin/main` on `story/11-2`. Expect a conflict on `.claude/skills/integrate/dispatch.md` (both sides edited it): keep main's new dispatch-doctrine text and re-apply the story's stack note within it. After the rebase the directory — this spec included — comes from git; commit spec/status/notes edits on `story/11-2` like any other path; never `git add -f`. Record the old->new SHA mapping of the rebased commits (old head `fa86b86`) in the report — the follow-up reviewer needs it to tell a rebase from a regression.
- The Harness bullets saying `_bmad-output` is a symlink and that the sandbox denies writes outside the main checkout are stale after that rebase; everything else above stands.
- Five lanes build in parallel beside this one (`story/6-2`, `story/10-1`, `story/7-1`, `story/11-3`, `story/11-4`) with footprints disjoint from this story's. Before **every** push: `python3 _bmad/scripts/branch_conflicts.py --against story/11-2` — `story/11-2-review` conflicting on this spec file is expected and resolved at integrate; every other pair must be clean. A fix that needs a region another lane owns is stopped, recorded in the Spec Change Log, and the rest continues.
- Finding 10's doc rewrites must also correct any sentence in README, `project-context.md`, `docs/glossary.md` or `AGENTS.md` still saying `_bmad-output/` is local-only or never pushed — the owner reversed that rule.

### The one missing concept: a stack's incarnation identity

Every high finding is a symptom of ownership being inferred from things two incarnations of the same slug share: the directory (`<WT_ROOT>/<slug>`), the compose project name, and — because the allocator is deterministic — usually the ports. A worktree hand-deleted and re-created under the same slug is indistinguishable from the original by any of them, which is why the Docker-down retry can attach to abandoned volumes (finding 5) and why the pruner's ownership tests are unverifiable. The fix is one new fact:

- `provision` writes **`MM_STACK_ID=<12 lowercase hex, secrets.token_hex(6)>`** into `.env.worktree` as a tenth stack key (`STACK_KEYS` order: `MM_STACK_NAME`, the seven ports, `MM_STACK_ID`, `MM_TEST_NEO4J_URI`, `MM_TEST_MEILI_URL`).
- `infra/docker-compose.yml` stamps it on the stack: every one of the five services gets `labels: { "com.meetingminer.stack-id": "${MM_STACK_ID:-}" }` and every one of the seven volumes gets the same `labels:` entry. The main stack renders the label empty. **Before touching the real compose file, prove on a throwaway compose project (a busybox service with one named volume, project name `mm-label-probe`) that adding a `labels:` entry to an already-created volume's definition neither fails `up` nor recreates the volume (write a file into the volume, add the label, `up` again, the file is still there); record the compose version and the observation in the Auto Run Result, then `down -v` the probe.** The main checkout's corpus volumes are never recreated; its containers may be recreated once by the label change, which is acceptable and must be stated in the report.
- Ownership is then two-layered, and the layers are named in the module docstring:
  - **Directory ownership** (the frozen general-prune rule, `make test-db-prune`): a `meetingminer-<slug>` project whose checkout directory exists is `skipped owned`; one whose directory is gone and whose volumes are all recognised is removed; anything else is `skipped unknown`. Unchanged in outcome, hardened below.
  - **Incarnation ownership** (creation and every start): a project is *this worktree's* only when every one of its containers and volumes carries the `MM_STACK_ID` of the worktree's validated `.env.worktree`. Anything else under that name — no id, another id, a mix — is a stale incarnation and is torn down before compose starts, never attached to.

### Theme 1 — `.env.worktree` is one validated ownership record (finding 1)

`infra/worktree_stack.py`:
- Replace `check_env_file` with **`validate_env_file(env_file: Path, slug: str) -> dict[str, str]`**, the single schema. It refuses, by name and with the offending key, any file where: the key set is not exactly `STACK_KEYS` (missing, blank, or foreign keys — `POSTGRES_PASSWORD=x` is foreign); `MM_STACK_NAME != stack_name(slug)`; any port is not ASCII digits in 1..65535 (`abc`, `0`, `70000`, `+5`, `1_000`); the seven ports are not distinct; any port equals a main-checkout default (`DEFAULT_PORTS.values()` — a worktree that names 7688 would wipe the main twins); `MM_STACK_ID` is not `^[0-9a-f]{12}$`; `MM_TEST_NEO4J_URI != f"bolt://localhost:{MM_NEO4J_TEST_BOLT_PORT}"` or `MM_TEST_MEILI_URL != f"http://localhost:{MM_MEILI_TEST_PORT}"` (exactly what `render_env` writes). The message ends with the remedy: `delete <file> and run 'make worktree-start STORY=<slug>' from the main checkout (or 'make worktree-provision' inside a post-11.2 worktree); the stack is recreated and its volumes discarded`.
- `provision()` calls `validate_env_file(env_file, slug)` for an existing file (so a file naming another slug is refused, not kept). **Atomic publication:** render to `<worktree>/.env.worktree.tmp-<pid>` and `os.replace` it into place under the lock; any failure removes the temp file and nothing named `.env.worktree` ever holds a partial write. Red tests: `os.replace` patched to raise → `StackError` `cannot write`, no `.env.worktree`, no temp file left; the existing directory-in-the-way test keeps passing.
- New subcommand **`check --worktree <dir>`**: `validate_env_file(<dir>/.env.worktree, slug=<dir>.name)`; exit 0 silently, else the named error, exit 1. The slug is the directory name because `make worktree` always creates `<WT_ROOT>/<slug>` and `worktree-provision` already keys on `$(notdir $(ROOT))`; a renamed directory is refused by name (state this in the docstring and AGENTS.md — `git worktree move` is not supported for a worktree with a stack).
- `declared_owners` and `taken_ports` keep reading sibling files leniently (a sibling's broken file must not break allocation), but `declared_owners` counts only files whose `MM_STACK_NAME` is a valid `meetingminer-<slug>` name.

`infra/Makefile`:
- **Parse-time foreign-key guard, before `-include`:** if `$(WT_ENVFILE)` exists, extract its keys with one `sed` in `$(shell …)` (`^[[:space:]]*(export[[:space:]]+)?KEY[[:space:]]*=`), `$(filter-out $(STACK_VARS) MM_TEST_NEO4J_URI MM_TEST_MEILI_URL, …)`, and `$(error …)` naming the foreign keys — a file that assigns `ROOT` or `INFRA` must never be included. `MM_STACK_ID` joins `STACK_VARS` (default empty) so it reaches compose through `STACK_ENV` and is unset by `UNSET_STACK_ENV`.
- `check-env`: for a linked worktree (`.git` is a file) require the file **and** `python3 $(INFRA)/worktree_stack.py check --worktree "$(ROOT)"`; for the main checkout (`.git` is a directory) refuse an existing `.env.worktree` by name (`the main checkout runs the main stack; remove $(ROOT)/.env.worktree`). Both messages name the remedy.

`server/meetingminer/config.py`:
- `WORKTREE_ENV_KEYS` gains `MM_STACK_ID`. `merged_env` validates the whole file when it exists — the same rules as `validate_env_file` minus the slug/directory check (the loader does not know the checkout): exact key set, `meetingminer-<valid slug>` name, seven valid distinct non-default ports, id format, twin URLs derived from the declared test ports — each a `ConfigError` naming the file and key. `test_config.py` pins the two implementations equal with one parametrized table of good/bad files run through both `validate_env_file` and `merged_env` (the loader's message must name the same key). The docstring says why the rule is spelled twice (stdlib-only script before the venv exists vs the server package).

`server/tests/conftest.py`:
- Replace `linked_worktree_without_stack` with **`linked_worktree_refusal(root: Path) -> str | None`**: a linked worktree needs the file (message names `make worktree-provision`); its `merged_env(root / ".env")` must load (a `ConfigError` becomes the refusal text, naming the key); and `MM_STACK_NAME` must equal `meetingminer-<root.name>`; a main checkout (`.git` directory) with a `.env.worktree` is refused too. `twin_endpoints` stays (the defaults are right only when no file exists, which the refusal now guarantees for linked worktrees). Update `test_worktree_stack.py::test_linked_worktree_without_stack_file_is_refused_by_name` — a name-only file is now refused, a rendered file for `linked` passes, a rendered file for another slug is refused.

Red regressions (fast module `test_worktree_stack.py` unless stated): parametrized bad files — truncated before `MM_STACK_ID`, before each twin URL, name-only, another slug's name, `meetingminer` as name, each invalid port form, two equal ports, a main default port, each incoherent twin URL, a foreign key, a blank value — refused by `validate_env_file`, by `provision` (file kept byte-identical), by `merged_env`, by `linked_worktree_refusal`, and at Make level (`test_makefile_procs.py`: write the bad file into a linked worktree from `_throwaway_repo`, `make check-env` exits 1 naming the key; `make check-env` in the main checkout with a copied file exits 1; a file assigning `ROOT=/elsewhere` fails at parse time for any target).

### Theme 2 — the pruner proves ownership for names and volumes (findings 2, 3)

`infra/worktree_stack.py`:
- `_is_worktree_project(project)`: the suffix after `meetingminer-` must match `_SLUG_RE` (so `meetingminer-`, `meetingminer-Foo`, `meetingminer-.backup` are out). Report such prefix-only names as `skipped foreign <name> (not a meetingminer-<slug> name)` — once, in the sweep — and never let them near `down`. Projects without the prefix are never listed (that is the existing contract).
- `worktree_stacks()` computes `unknown` for **every** candidate from its volumes (`all(volume in ours)`), containers or not; `Stack` gains `ids: set[str]` (container labels) and `volume_ids: set[str]` (volume labels, empty string for unlabeled). `PS_ARGV`/`VOLUME_ARGV` add a third `\t{{.Label "com.meetingminer.stack-id"}}` column; `_tab_rows` returns three columns. In `prune`, a present owner is still `skipped owned` first; then `unknown` is `skipped unknown` (or the error in `--project` mode); only a recognised, unowned stack reaches `down -v`.
- Red regressions: `meetingminer-Foo` with a missing working dir is never removed and is reported foreign; a valid-prefix project with a missing owner path and a `meetingminer-probe_foreign-data` volume is `unknown` and never removed (both general and `--project` mode, where it is the error); the existing volumes-only cases keep passing.

### Theme 3 — one start path, safe for old refs and for the Docker-down retry (findings 4, 5)

`infra/worktree_stack.py` — new subcommand **`claim --worktree <dir> --worktree-root <root>`** (`claim(worktree, root, run, out)`): validate the file (slug = directory name); inventory docker; if no project of that name exists → `no stale stack <name>`; a present owner other than `<dir>` → error (`belongs to the existing checkout <other>`); an unknown layout → error (inspect and remove by hand); every container id and every volume id equal to the file's `MM_STACK_ID` → `kept stack <name> (this worktree's)`; anything else (no resources with our id, an id-less pre-fix stack, another id, a mix) → `docker compose -p <name> down -v --remove-orphans` and `removed stale stack <name> (not started from <file>)`. `claim` and `prune` both hold `<root>/.provision.lock` (finding 7 below).

`infra/Makefile`:
- New **`check-stack`** prerequisite of `infra-up` (`infra-up: check-docker check-env check-stack`): when `$(WT_ENVFILE)` exists, `python3 $(INFRA)/worktree_stack.py claim --worktree "$(dir $(WT_ENVFILE))" --worktree-root "$(WT_ROOT)"`; when it does not, nothing. Because `worktree` and `worktree-start` call `infra-up` with `WT_ENVFILE=<wt>/.env.worktree`, the claim runs for the new worktree through the invoking checkout's script, and `cd <wt> && make infra-up` in a post-11.2 worktree runs the same claim through its own copy. This is the one place a stack is ever started, so the Docker-down retry, the compose-failure retry, an old-ref worktree's start and a plain restart are all the same path.
- New target **`worktree-start STORY=<slug>`**: the worktree `$(WT_ROOT)/$(STORY)` must exist and be a linked worktree (`.git` file), else a named error; `check-docker`; `provision` (keeps a valid file, refuses a bad one, writes one if absent); then exactly the `$(UNSET_STACK_ENV) $(MAKE) --no-print-directory -C $(INFRA) infra-up ENVFILE=… WT_ENVFILE=… COMPOSE_PROJECT_DIR=…` line `worktree` uses today — move that line into `worktree-start` and have `worktree` call `$(MAKE) --no-print-directory worktree-start STORY=$(STORY)` after `git worktree add` and the `.env` link. `worktree-provision` (inside a linked worktree) becomes `$(MAKE) --no-print-directory worktree-start STORY=$(notdir $(ROOT))` after refusing the main checkout and a checkout not at `$(WT_ROOT)/$(notdir $(ROOT))`.
- Retry messages, all executable for an old ref: provision failure → `make worktree-start STORY=<slug>` run from this checkout (`$(ROOT)`); compose/Docker failure → if `<wt>/infra/Makefile` contains a `worktree-start:` rule, `cd <wt> && make infra-up` (the matrix row; safe now because `infra-up` claims first), else the same `make worktree-start STORY=<slug>` from this checkout plus one line saying the worktree's own Makefile predates story 11.2 and its store targets would use the main stack. Never print a command that runs an old `infra/Makefile`'s stack logic.
- Docker down at creation: the worktree and its file stay (matrix row) and the sweep is deferred to the retry, where `claim` performs it: a same-named project left by a hand-deleted worktree cannot carry the new file's id, so it is torn down before the first `up`.

Red regressions (`test_makefile_procs.py`, throwaway repo + decoy `docker`; add a decoy `python3` on the PATH that execs the real interpreter — bake in `shutil.which("python3")` resolved before the decoy dir is prepended — except that it exits 1 for a `provision` call while a flag file exists, and add `__UP_EXIT__`/`__PS_Q_EXIT__`/`__DOWN_EXIT__`-style knobs or an env-driven `DECOY_FAIL` list to the docker decoy):
- old ref + provision failure: output names `make worktree-start STORY=probe`, not `cd … worktree-provision`; running that command then drives compose with the invoker's compose file, the worktree's two env files, `-p meetingminer-probe`, `--project-directory <wt>/infra`, and no argv line ever carries `-p meetingminer ` (the main project);
- old ref + compose failure: same, and the output never contains `cd <wt> && make infra-up`;
- post-11.2 worktree + compose failure: output contains `cd <wt> && make infra-up` (existing assertion) and running `make -C <wt>/infra infra-up` with the decoy claims first (`ps -a` with the label format appears before ` up -d --wait`);
- Docker down at creation with `ps_rows`/volume rows describing a stale `meetingminer-probe` (id-less, or another id): worktree and file stay (existing test), and the retry (`make worktree-start STORY=probe`, decoy now up) issues `compose -p meetingminer-probe down -v --remove-orphans` before ` up -d --wait` and prints `removed stale stack`; with rows carrying the file's own id the retry prints `kept stack` and issues no `down`;
- `claim` unit tests in `test_worktree_stack.py`: kept / stale id-less / stale other id / mixed / foreign owner error / unknown layout error / absent project.

### Finding 6 — cleanup never reports success after inventory or teardown failure

Move the teardown out of shell: new subcommand **`down --project <name>`** (`down(project, run, out)`): refuse anything but a valid `meetingminer-<slug>` name; `docker info` failing → note `Docker daemon not running — stack <name> left in place; 'make test-db-prune' sweeps it once its worktree is gone`, exit 0 (the matrix keeps this a note); `docker ps -aq --filter label=com.docker.compose.project=<name>` or `docker volume ls -q --filter …` failing → named `StackError`, exit 1 (never "already gone"); resources present → `docker compose -p <name> down -v --remove-orphans`, failure named, exit 1; nothing present → `note: stack <name> was already gone`, exit 0. `stack_down` in the Makefile becomes one line calling it. `worktree-remove` ends with it (status propagates). `worktree-prune` tracks `rc=1` when `down` fails, still deletes the branch (the checkout is already gone), and exits `$$rc` after the loop — the branch-delete's `|| true` no longer masks it. Red tests: decoy where `ps -aq` fails after `info` succeeds → `worktree-remove` exits 1 naming the inventory failure and the stack is not reported gone; decoy where `compose … down` fails → `worktree-remove` and `worktree-prune` exit 1, the worktree is gone, the failure is named; `down()` unit tests for each branch.

### Finding 7 — no teardown on a stale snapshot

`prune()` and `claim()` acquire `<worktree_root>/.provision.lock` (`fcntl.flock`, exclusive) around inventory **and** teardown, the same file `provision()` holds across allocation and publication, so a sweep never interleaves with a provision or a claim. Immediately before every `down -v` in `prune`, re-resolve `present_owner` (the directory may have appeared after the inventory); if it now exists, print `skipped owned` instead. Red tests: a fake `run` that creates the owner directory during the inventory call → no `down`, `skipped owned`; a subprocess holding the lock for 0.5s while `prune()` runs with a fake → the `down` call happens only after the release (assert by timestamps); mutation check: with `flock` monkeypatched to a no-op the timing test fails.

### Finding 8 — the provisioning lock is proven to exclude

`test_worktree_stack.py`: two `python3` subprocesses (each loads the module by path) provision two slugs with the same base index (`_slug_with_base_index`) into two worktrees under one root, each with `port_is_free` replaced by a probe that sleeps 0.3s on its first call so the allocation windows overlap; assert the two files declare disjoint port sets and the second one landed on the next base. Then the mutation: the same run with `fcntl.flock` replaced by a no-op in both processes yields identical ports — assert that too, so the test fails if the lock is ever removed. Keep the call phase under the 2.0s fast budget or mark it `slow` with a reason and pin it in `SLOW_TESTS`.

### Finding 9 — strict lock-key validation

`locks.py`: `_KEY_RE.fullmatch(override)`; add `"b14-key\n"`, `"\n"`, `"key\r"` to the invalid table in `test_projections_locks.py`; confirm the byte-compat test is untouched.

### Finding 10 — the concrete VM bound in every document the AC names

`README.md` (the worktree paragraph), `project-context.md` (the "Server suites in different worktrees" bullet), `docs/glossary.md` (the Worktree entry): each states, in its own words, that OrbStack's VM reports **23.5 GiB against the 128 GB host**, that a stack is about 2 GiB idle, that a handful of stacks fit and a dozen idle ones would fill the VM, and that `make down` in an idle worktree frees its memory and keeps its volumes. AGENTS.md keeps the full measurement.

### Documentation the remediation itself requires

`AGENTS.md` (worktree section and the store section: the file is the ownership record, `MM_STACK_ID`, `worktree-start`, the old-ref retry, `git worktree move` unsupported, what `claim` removes and why), `README.md` (same, briefly), `docs/glossary.md` (Worktree entry mentions the stack id), `.env.example` header, the Makefile `help` rows (`worktree-start`), and `docs/backlog.md` only if the builder defers something. The module docstring of `infra/worktree_stack.py` documents the two ownership layers and every subcommand (`provision`, `check`, `claim`, `down`, `prune`).

### Migrating this worktree's own stack

The 11-2 worktree's `.env.worktree` predates `MM_STACK_ID`, so after Theme 1 lands its `check-env` refuses it. Migrate in this order, once the code is green: `make down` in the worktree (frees 21761–21767 so the deterministic base is reused), delete `.env.worktree`, `make worktree-provision` — `claim` finds the id-less volumes-only project, removes it, and the stack comes back fresh on the same ports. Do not touch `../meetingminer-wt/11-2-review`; say in the report that it needs the same migration when its owner next starts it.

### Order of work

1. Red regressions for Theme 1, committed failing; then `validate_env_file`, atomic publication, `check`, the Makefile parse-time guard and `check-env`, `merged_env`, `linked_worktree_refusal`; green; commit; push.
2. The compose label probe on a throwaway project (record it); `MM_STACK_ID` in the file, the compose labels, `STACK_VARS`; commit.
3. Red tests for Theme 2; `_is_worktree_project`, universal volume recognition, the id columns; green; commit.
4. Red tests for Theme 3; `claim`, `check-stack`, `worktree-start`, the retry messages, `worktree-provision`; green; commit.
5. Red tests for finding 6; `down` subcommand and the Makefile propagation; commit.
6. Finding 7 lock + recheck, finding 8 contention test, finding 9, finding 10 and the other docs; commit.
7. Migrate this worktree's stack; run the full verification below; update this file (check the findings, fill `## Auto Run Result`), push.

### Decisions for the reviewer to attack

- (e) Incarnation identity as a compose label on containers and volumes, generated per `provision` — assumes compose reuses an existing labeled-differently volume without recreating it (proven on a throwaway project before use) and that a main-stack container recreation at the next `up` is acceptable.
- (f) The stack name must equal `meetingminer-<directory name>` at every guard — assumes nobody moves a worktree with `git worktree move`; the refusal says so.
- (g) `claim` runs before every `infra-up` that has a stack file, and tears down a same-named project that does not carry the file's id — assumes a worktree's stores are disposable (the story already tears them down on `worktree-remove`) and that a fail-closed teardown beats a refusal the operator would resolve with the same `down -v` by hand.
- (h) The Makefile refuses foreign keys in `.env.worktree` at parse time with `$(shell sed …)` — assumes one `sed` per make invocation is acceptable.
- (i) Existing worktree stacks (id-less) are treated as stale by `claim` the first time they start after this lands — a one-time migration, stated in the report.

## Spec Change Log

- 2026-08-30 (final adversarial validation): three additional patch findings closed red-first. `infra-up` now checks the parsed identity before destructive claim as well as immediately before Compose; the ownership-record path is derived from the checkout working directory and cannot be replaced with `WT_ENVFILE`; the identity CLI enforces linked/main checkout topology without blocking `worktree-provision`. Generated-file and operator documentation now state the identity exception precisely.

- 2026-08-30 (owner rulings on follow-up Findings 10–11): `MM_STACK_NAME` and `MM_STACK_ID` are non-overridable ownership identity read only from the checkout's `.env.worktree`; process precedence remains unchanged for ports and endpoints. Compose must also refuse immediately before execution if its effective name or id differs from the file. Story 11-2 owns the matching AD-10 amendment naming the generated incarnation identity; the owner will union Story 8-1's separate model-binding sentence during integration.

- 2026-08-30 (remediation build): all ten follow-up findings closed red-then-green; `## Auto Run Result` carries the remediation record. Branch rebased onto main `a011695` mid-run (main gained the harness addendum and the duplicate-lane halt note in this file; the Auto Run Result conflict was resolved by keeping both paragraphs). One deferred non-edit: the `story/7-1` × `main` conflict on `sprint-notes.md` predates this lane and is 7-1's rebase debt — not touched from here (wave rule: never edit another lane's file to make room).

- 2026-08-30 ~14:30: `### Harness addendum 2026-08-30` added under the Remediation Plan — `_bmad-output` tracked on main, rebase-first, wave conflict checks, finding-10 wording; from the coordinator's addendum, intent unchanged.
- 2026-08-30 (follow-up review): `## Remediation Plan — follow-up review 2026-08-30` added; frontmatter `reviewed_head` records the head the review read (`fa86b86`); intent-contract unchanged.

## Review Triage Log

### 2026-08-30 — Follow-up review remediation round
- intent_gap: 0
- bad_spec: 0
- patch: 10: (high 4, medium 3, low 3)
- defer: 0
- reject: 0
- Every finding of the follow-up review (`review-story-11-2-2026-08-30.md`) was
  triaged `patch`: none had a specification root cause, so the intent-contract
  is unchanged. All ten are closed red-then-green in
  `ebbcd6c..e331fb6` and checked off under `### Review Findings`; the per-finding
  red evidence is in `## Auto Run Result`. A second follow-up review is dispatched
  by `review-prompt-story-11-2-followup-2026-08-30.md`.

### 2026-08-30 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 32: (high 2, medium 6, low 24)
- defer: 2: (high 0, medium 0, low 2)
- reject: 9
- addressed_findings:
  - `[high]` `[patch]` A worktree cut from a pre-11.2 ref ran the old Makefile's `infra-up` and attached the main stack under a private-stack banner — the stack now comes up through the invoking checkout's Makefile and compose file with `--project-directory <wt>/infra`, stack variables unset for the sub-make.
  - `[high]` `[patch]` A linked worktree without a usable `.env.worktree` silently used the main stack — `provision` refuses an incomplete file; `check-env` and the test conftest refuse a linked worktree without the file, naming `make worktree-provision` (new target).
  - `[medium]` `[patch]` Slug rule admitted `.`, which compose rejects in project names — rule is `[a-z0-9][a-z0-9_-]*` in both places.
  - `[medium]` `[patch]` `.env.worktree` could override secrets and `.env` could carry stack keys the Makefile ignores — the loader refuses keys outside the stack set in `.env.worktree` and stack keys in `.env`.
  - `[medium]` `[patch]` A blank exported `MM_*` made compose fall to the default while the loader used the file — compose receives the resolved values explicitly.
  - `[medium]` `[patch]` Pruner could `down -v` a foreign volumes-only `meetingminer-*` project or a moved worktree's stack, and an empty `WT_ROOT` made every stack look orphaned — volume-name check, sibling `MM_STACK_NAME` ownership, missing-root handling, `$(error)` on an empty common dir.
  - `[medium]` `[patch]` Re-provisioning a slug revived its stale volumes on new ports — `make worktree` sweeps a stale project of that name first (`prune --project`).
  - `[low]` `[patch]` Port parsing accepted `+5`/`1_000`; `_with_port` lowercased the host; docker calls had no timeout; one failed `down` stopped the sweep; the DB prune's failure skipped the stack sweep; no provisioning lock — all fixed with tests.
  - `[low]` `[patch]` Missing tests added: `worktree-prune` teardown, the `test-db-prune` sweep line, `check-dev-stores` ports, `make worktree` from inside a worktree, the real `.gitignore`, the conftest twin binding, make-level env precedence.
  - `[low]` `[patch]` Docs and hygiene: CLAUDE.md, the integrate skill's dispatch note, two stale test docstrings, AD-10 restated as one sentence, measured numbers kept in AGENTS.md only, the full-VM remedy, the `worktree` failure message, the `pytestmark` count, backlog ordering and B-14's own dated paragraph, `worktree-list` showing stacks, a test rename.

## Design Notes

- Harness note (from 11.1): all work happens in the worktree `/Users/devopsterus/current/cohort/meetingminer-wt/11-2` on branch `story/11-2` (venv and node_modules already bootstrapped; `_bmad-output` there is a symlink to the main checkout's). Never edit the main checkout `/Users/devopsterus/current/cohort/meetingminer` — other agents are in it. The Bash sandbox denies writes outside the main checkout and reads of `.env`, so run every command in the worktree with the sandbox disabled (`dangerouslyDisableSandbox: true`); bare `ls <path>` is aliased to a tool that mishandles arguments — use `find`/`git ls-files`. Commit each coherent unit as it completes and push `story/11-2` (`git push -u origin story/11-2` the first time) — no permission needed, never `git add -A`, stage only the paths you changed, never reset or stash. Store-backed suites may run concurrently with other agents' suites (AGENTS.md: per-run Postgres databases, twins behind the file lock); never `make evals-run`. Order of operations: write `infra/worktree_stack.py`, the compose interpolation, and the Makefile changes first, then provision this worktree's own stack (`python3 infra/worktree_stack.py provision --slug 11-2 --worktree <wt> --worktree-root <wt>/..` then `make infra-up`) so every store-backed run after that hits the private stack, not the shared one. `pytest` must be given a path under `server/tests`; a `slow` module by path needs `-m ""`.
- Why a second env file and not `config.yaml`: the intent says "writes the worktree's environment"; `config.yaml` is tracked and branch-carried, so per-worktree values there would be a permanent diff and a merge conflict on every story. AD-10 is amended by one sentence because the intent chose this reading; the ports are infrastructure location (the same class as `MM_CONTENT_ROOT`), not adapter bindings.
- Why ports, not URLs, in the override: compose needs the numbers; the loader keeps host and scheme from `config.yaml`, so a checkout that points at a remote stack keeps working, and a `.env.worktree` cannot redirect the api to a foreign host.
- Why the twin URLs are still written as `MM_TEST_NEO4J_URI`/`MM_TEST_MEILI_URL`: those names already exist as the seam (conftest, README, AGENTS.md); the file supplies them, the process env still wins.
- Why the allocator is deterministic per slug with a collision step: re-provisioning the same slug lands on the same ports unless something else took them; a bind probe alone cannot see a sibling whose stack is currently down, so declared ports in sibling files count as taken.
- Why orphan detection uses compose's own `working_dir` label: compose stamps it on every container from the `-f` directory the stack was started from, which is the worktree's `infra/`; no new label or registry is needed. Volumes carry only the project label, so the volumes-only case falls back to `<worktree_root>/<slug>`, exact because the slug rule forbids characters compose would rewrite.
- Decisions for the reviewer to attack: (a) `WT_ROOT` derived from the git common dir so a worktree can create siblings — assumes `git rev-parse --path-format=absolute` (git ≥ 2.31); (b) the stack sweep inside `test-db-prune` runs for real during `test_prune_preserves_owned_database_and_removes_abandoned` — assumes "directory exists" is a sufficient ownership signal; (c) `make worktree` requires Docker for the stack but leaves the worktree usable if compose fails — assumes a named retry instruction beats an all-or-nothing rollback; (d) the lock-key override is process-wide, so a shell that exports it would also re-key `rebuild` and the worker — accepted as a test-only knob, documented.

## Verification

**Commands:**
- Remediation gate (run in `<wt>` with its private stack; every command below is part of it):
  - `uv run --project server pytest server/tests/test_worktree_stack.py server/tests/test_config.py server/tests/test_compose_contract.py -q` -- expected: all pass, including every new red-then-green regression.
  - `uv run --project server pytest -m "" server/tests/test_makefile_procs.py server/tests/test_projections_locks.py server/tests/test_parallel_store_safety.py -q` -- expected: all pass.
  - `make check-env` in `<wt>` -- expected: exit 0 after the migration; with `.env.worktree` renamed away, exit 1 naming `make worktree-provision`; with a foreign key appended, exit 1 at parse time naming the key; restored → exit 0.
  - `make worktree STORY=11-2-probe BASE=story/11-2` from `<wt>`, then `docker compose ls` and `docker ps` -- expected: `meetingminer-11-2-probe` running(5) beside `meetingminer` and `meetingminer-11-2`, all on different ports; `docker inspect` of one probe container and one probe volume shows `com.meetingminer.stack-id` equal to the probe file's `MM_STACK_ID`.
  - `MM_REQUIRE_TEST_STORES=1 uv run --project server pytest -m "" server/tests/test_projections_search.py::test_configured_projection_stores_are_reachable` in `<wt>` and in the main checkout -- expected: each passes against its own twin ports.
  - `time make test` alone in `<wt>`, then concurrently in `<wt>` and the probe -- expected: rc 0 in all three, no `ProjectionLockedError`, different lock paths, wall times recorded.
  - `docker stats --no-stream` -- expected: per-stack memory recorded plus the OrbStack VM figure.
  - Orphan case: `rm -rf <probe>` (deliberately without `git worktree remove`), `make test-db-prune` from `<wt>` -- expected: `removed stack meetingminer-11-2-probe`, `skipped owned meetingminer-11-2`, `skipped owned meetingminer-11-2-review`, no probe volumes left, `meetingminer` untouched; then `git -C <main> worktree prune`.
  - Stale-incarnation case: `make worktree STORY=11-2-probe BASE=story/11-2` again, `make down` in the probe, then delete the probe's `.env.worktree` and run `make worktree-provision` there -- expected: `removed stale stack meetingminer-11-2-probe`, a fresh stack with a new `MM_STACK_ID`, then `make worktree-remove STORY=11-2-probe` leaves no project and no `meetingminer-11-2-probe_*` volume.
  - `uv run --project server pytest server/tests --co -q | tail -1`, `make check-test-stores`, `make check-reviews` -- expected: the fast set collects, 1 passed against the worktree's twins, every dispatched review has a committed report.
- `cd <wt> && uv run --project server pytest server/tests/test_worktree_stack.py server/tests/test_config.py server/tests/test_compose_contract.py -q` -- expected: all pass (fast set).
- `cd <wt> && uv run --project server pytest -m "" server/tests/test_makefile_procs.py server/tests/test_projections_locks.py server/tests/test_parallel_store_safety.py -q` -- expected: all pass.
- `cd <wt> && make worktree STORY=11-2-probe BASE=story/11-2` then `docker compose ls` -- expected: two `meetingminer*` projects running(5).
- `cd <wt> && time make test` (alone) and then `cd <wt> && time make test & cd <probe> && time make test` -- expected: both rc 0, wall-clock recorded, no `ProjectionLockedError` in either log.
- `docker stats --no-stream` -- expected: per-stack resident memory recorded for both stacks.
- `rm -rf <probe>` (after `git worktree remove --force` is deliberately skipped) then `cd <wt> && make test-db-prune` -- expected: `removed stack meetingminer-11-2-probe`, `skipped owned meetingminer-11-2`; `git -C <main> worktree prune` afterwards.
- `cd <wt> && uv run --project server pytest server/tests --co -q | tail -1` -- expected: the new module collected in the fast set; `make check-test-stores` -- expected: 1 passed against the worktree's twins.

## Auto Run Result

**Duplicate-lane halt (2026-08-30 ~15:00, session e8e75846).** A second `bmad-build-auto` run, launched by the owner with the `013e0ff` review handoff, halted `blocked` with condition `duplicate lane — story/11-2 remediation owned by another session's agent`. Before halting it wrote the Remediation Plan section above and launched a builder into `../meetingminer-wt/11-2`; on the other lane's cross-session challenge the builder was stopped having committed nothing (branch clean at `d5e7a90`, no stray processes or probe stacks). The `status` field is left `in-progress` on purpose: it describes the story, which the surviving lane owns. Anything below this paragraph is the surviving lane's record.

**Remediation label probe (2026-08-30, step 2 of the order of work).** Docker
Compose v5.1.2, throwaway project `mm-label-probe` (busybox + one named
volume): a file written into the volume before the label existed; a
`labels: {com.meetingminer.stack-id: ...}` entry then added to the service
and the volume definition; `up -d` succeeded, the container was recreated
once carrying the label, the volume was **not** recreated (same `CreatedAt`,
the file still present) and kept its old label-less metadata — which is
exactly how `claim` recognises a stale incarnation. Probe removed with
`down -v`; no `mm-label-probe` volumes remain.

**Remediation status: done (2026-08-30, follow-up round).** All ten `### Review Findings` closed, each as a red-tests-then-fix commit pair on `story/11-2`, worktree `../meetingminer-wt/11-2`; branch rebased onto main `a011695` and pushed. Rebase mapping for the reviewer: the reviewed head `fa86b86` is the pre-rebase name of `d5e7a90`, which after the mid-run rebase onto main is `ebbcd6c` (content unchanged); the remediation commits are `04822cd`→`e3aae50` (finding 1 red/fix), `32ceb3f` (MM_STACK_ID labels + probe), `a508c2a`→`6b7b82f` (findings 2-3), `523c788`→`f972c70` (findings 4-5), `72cd10b`→`29c7762` (finding 6), `37a3bf7`→`ef0565e` (findings 7-9), `24176c8` (finding 10 + docs), then this spec update.

**Red evidence (observed against the unfixed tree, per commit message).** Finding 1: 43+19+3 failures (no `validate_env_file`, no `ws.os`, no `linked_worktree_refusal`; `check-env` exited 0 on a wrong-name file, on a main-checkout file, and a file assigning `ROOT` was included at parse time). Findings 2-3: 7 failures (`_is_worktree_project` accepted any prefix; the pruner removed `meetingminer-Foo` and a foreign-volume project; no id columns). Findings 4-5: 9+4 failures (no `claim`, no `worktree-start`; old-ref retries pointed at `worktree-provision` / `cd <wt>`; no claim before `up`). Finding 6: 13+3 failures (no `down` subcommand; inventory failure read as absence; `worktree-prune` masked a failed teardown). Finding 7: prune tore down 0.45s before a held provisioning lock was released (timing test red); the recheck-before-down half had no observable red — `present_owner` was already evaluated lazily per loop iteration — so that test pins behavior and the lock is the fix with teeth. Finding 8 (verification gap): against a scratch flock-no-op mutant, two concurrent provisions of two slugs hashing to one base both published the identical seven ports (21271-21277 twice, observed); the committed test's no-op phase demands that collision, so removing the lock cannot pass silently. Finding 9: `'b14-key\n'` was accepted by the old `re.match` (observed red).

**Remediation verification (2026-08-30, this worktree and its private stack).**
- Migration: this worktree's pre-remediation stack (id-less containers and volumes) was torn down by `claim` on the first `infra-up` after the labels landed and came back fresh on the same ports 21761-21767 with `MM_STACK_ID=35b12b56fba0` stamped on every container and volume.
- Fast trio (`test_worktree_stack` + `test_config` + `test_compose_contract`): 279 passed. `-m ""` trio (`test_makefile_procs` + `test_projections_locks` + `test_parallel_store_safety`): 106 passed in 84s. Collection split: 1595/1961 (366 deselected).
- `make check-env`: 0 with the valid file; renamed away → refused naming `make worktree-provision`; a foreign key appended → refused at parse time naming the key; restored → 0. `make check-test-stores`: 1 passed against 21766/21767. `make check-reviews`: every dispatched review filed.
- `make worktree STORY=11-2-probe BASE=story/11-2` → `meetingminer-11-2-probe` running(5) on 23861-23867 beside `meetingminer`, `meetingminer-11-2` and `meetingminer-11-2-review`, all on distinct ports; `docker inspect` of a probe container and a probe volume both showed `com.meetingminer.stack-id` equal to the probe file's `MM_STACK_ID`.
- Reachability: `MM_REQUIRE_TEST_STORES=1 …test_configured_projection_stores_are_reachable` passed in the worktree (21766/21767) and in the main checkout (7688/7701); the worktree loader resolves 21761 / `bolt://localhost:21763` / `http://localhost:21764`.
- `time make test` alone in the worktree: rc 0, **1961 passed** in 566.5s, wall 9m49s. Concurrent pair (11-2 + probe): rc 0 both, 1961 passed each, pytest 556.2s / 595.5s, wall 9m39s / 10m27s; 0 `ProjectionLockedError` in any log; the two lock paths differ (`…-73c387370d8a3719.lock` vs `…-5d43a2b4292e0f9d.lock`).
- Memory under the two concurrent runs (`docker stats --no-stream`): 11-2 ≈1.85 GiB, probe ≈1.47 GiB, review (idle) ≈1.30 GiB, main (idle) ≈2.06 GiB; Docker (OrbStack) VM 23.5 GiB total.
- Orphan case: probe hand-deleted (`rm -rf`, no `git worktree remove`), `make test-db-prune` → `removed stack meetingminer-11-2-probe`, `skipped owned meetingminer-11-2`, `skipped owned meetingminer-11-2-review`, no probe volumes or project left, `meetingminer` untouched; `git worktree prune` run in the main checkout afterwards.
- Stale-incarnation case: probe recreated, `make down` there, `.env.worktree` deleted, `make worktree-provision` → `removed stale stack meetingminer-11-2-probe (not started from …/.env.worktree)`, fresh stack on the same ports with a new `MM_STACK_ID` (`037893164369` → `f7eb8b89cf46`); `make worktree-remove STORY=11-2-probe` left no project and no `meetingminer-11-2-probe_*` volume.

**Remediation notes.** (1) `../meetingminer-wt/11-2-review`'s stack is still an id-less incarnation; its owner's next `make infra-up` there will run `claim`, tear it down and recreate it fresh — the same one-time migration every pre-remediation worktree stack gets (decision (i)). (2) The main checkout's containers will be recreated once by the new label at its next `up`; its corpus volumes are never touched (proven on the throwaway label probe above). (3) The main checkout keeps running label-less containers until then — `claim` never runs there (no stack file), so nothing tears it down. (4) `git worktree move` is now refused by every guard (stack name must equal `meetingminer-<directory name>`); documented in AGENTS.md. (5) `worktree-start STORY=<slug>` is the retry for every start failure and the only start path; no failure message names a command that would run a pre-11.2 `infra/Makefile`'s stack logic.

**Round-one record (superseded by the remediation record above; kept for history).** **Status:** done (2026-08-30). Branch `story/11-2` at `fa86b86` in worktree `../meetingminer-wt/11-2`, pushed, `origin/story/11-2` identical (`git rev-list --left-right --count HEAD...@{u}` → `0	0`), `git status --porcelain` empty; 11 commits `b6fac36`..`fa86b86` on base `de0fc08` (= `main`).

**Implemented.** Every worktree owns a private compose stack. `infra/docker-compose.yml` interpolates the project name, the five container names and the seven host ports from `MM_STACK_NAME` / `MM_*_PORT` with today's values as defaults, so the main checkout's stack, names and corpus volumes are unchanged. `make worktree STORY=<slug> [BASE=main]` validates the slug (`[a-z0-9][a-z0-9_-]*`), adds the checkout beside the main repo (`WT_ROOT` from the git common dir, so a worktree can create siblings), links `.env` to the main file, sweeps a stale project of the same name, writes `.env.worktree` (`infra/worktree_stack.py provision`: base `crc32(slug) % 400` in 20000–23999, stepping past bound or sibling-declared ports) and brings the stack up through the invoking checkout's Makefile and compose file with `--project-directory <wt>/infra` — so a worktree cut from a pre-11.2 ref still gets its own stack. `worktree-remove` / `worktree-prune` tear the stack and volumes down after git removes the checkout; `test-db-prune` adds a second sweep (`worktree_stack.py prune`) that removes `meetingminer-<slug>` projects whose checkout directory is gone and reports every owned one; `worktree-list` shows each stack's name and ports; `worktree-provision` writes the file for an existing linked worktree. Three readers take the file: the Makefile (`-include`, location precedence env > file > default, values passed to compose explicitly), compose (second `--env-file`, `-p`), and the loader (`merged_env`: `.env`, then `.env.worktree`, then the process env for location/endpoint values with the blank rule; `MM_POSTGRES_PORT` / `MM_NEO4J_BOLT_PORT` / `MM_MEILI_PORT` replace only the port of the configured endpoints). `MM_STACK_NAME` and `MM_STACK_ID` are non-overridable ownership identity from `.env.worktree` (main defaults without it); conflicting process values are refused before claim and the live record is checked again immediately before Compose. Stack keys are allowed only in `.env.worktree`, never in `.env`. The test session reads its twin URLs through the same merged env; a linked worktree without the file is refused by `check-env` and at conftest import. `MM_PROJECTION_LOCK_KEY` names the projection lock file (B-14); unset, the derivation is byte-identical. AD-10 admits the private name, ports, and generated incarnation identity; AGENTS.md's store section is rewritten with the mechanism and measurements; README, glossary, project-context, `.env.example`, the integrate skill's dispatch note and the backlog (B-14 closed, B-35 filed) follow.

**Files changed (24).** `infra/docker-compose.yml` interpolation; `infra/Makefile` include/precedence, `COMPOSE`, `check-env` guard, `check-dev-stores` ports, `worktree`/`-list`/`-remove`/`-prune`/`-provision`, `test-db-prune` sweep, `down` fallback, help; `infra/worktree_stack.py` new (allocator, renderer, pruner, CLI); `server/meetingminer/config.py` `merged_env`, key rules, port overrides; `server/meetingminer/projections/locks.py` `MM_PROJECTION_LOCK_KEY`; `server/tests/conftest.py` twin binding via `twin_endpoints`, linked-worktree refusal; `server/tests/test_worktree_stack.py` new; `test_config.py`, `test_compose_contract.py`, `test_makefile_procs.py` (+17 tests: worktree provision/old-ref/Docker-down/bad slug/remove/prune/check-env/check-dev-stores/precedence), `test_projections_locks.py`, `test_parallel_store_safety.py` (B-14 test on its own key), `test_projections_search.py` (alias guard from live endpoints), `test_migrations.py` (subprocess port pinned), `test_api_search.py` docstring; docs: `AGENTS.md`, `CLAUDE.md`, `README.md`, `project-context.md`, `.env.example`, `docs/architecture.md` (AD-10), `docs/backlog.md`, `docs/glossary.md`, `.claude/skills/integrate/dispatch.md`.

**Review findings.** Four layers (blind hunter, edge-case hunter, verification-gap, intent alignment). Patched 32 (high 2, medium 6, low 24), deferred 2 (project-record entry — written at integration; evals docs — story 11.3), rejected 9. Follow-up review: high patched > 0 → `followup_review_recommended: true` (score 3×6 + 24 = 42).

**Verification (observed by the coordinator in the worktree, all stacks up).**
- Alone `make test` at `d70c790` (pre-fix): 1 failed / 1799 passed in 567s, wall 9m49s, 0 `ProjectionLockedError`; the failure was `test_migrations::test_worker_exits_1_on_unreachable_database` — the worktree's `MM_POSTGRES_PORT` overrode the test's unreachable port; fixed in `868ff0f`.
- Concurrent pair at `868ff0f` (worktrees `11-2` and `11-2-probe`, stacks on 21761–21767 and 23861–23867): **both rc 0, 1806 passed each**, 542.7s / 547.0s of pytest, wall 9m27s / 9m31s; 0 `ProjectionLockedError` in either log. A pre-fix pair gave 8m45s / 9m20s pytest, same single failure, 0 lock errors.
- Gate after the review patches at `fa86b86`: `make test` → rc 0, **1849 passed** in 578.68s (wall 10m00s, 11:28:10–11:38:10), web build green, 0 lock errors, sole warning the pre-existing Starlette `httpx` deprecation.
- Fast trio (`test_worktree_stack`, `test_config`, `test_compose_contract`) → 181 passed; `--co` → 1497/1849 (352 deselected); `make check-test-stores` in the worktree → 1 passed against 21766/21767; loader in the worktree resolves 21761 / `bolt://localhost:21763` / `http://localhost:21764`; `-m ""` `test_makefile_procs` → 63 passed (builder-observed), `test_projections_locks` + `test_parallel_store_safety` + `test_migrations` + the two search guards → 43 passed (builder-observed); `test_migrations` alone → 10 passed (coordinator).
- Live: `make worktree STORY=11-2-rm BASE=story/11-2` from the worktree's Makefile → sibling under `meetingminer-wt/`, `.env` → main file, stack on 22691–22697; `make worktree-remove STORY=11-2-rm` → checkout, stack and volumes gone. `make worktree STORY=11-2-old BASE=de0fc08` (pre-11.2 Makefile in the new tree) → stack `meetingminer-11-2-old` on 22141–22147 via the invoker's compose file, `working_dir` label = the old worktree's `infra/`, main stack untouched; removed cleanly. `rm -rf` of the probe worktree then `make test-db-prune` → `skipped owned meetingminer-11-2`, `removed stack meetingminer-11-2-probe`, no probe volumes left, `meetingminer` untouched. `.env.worktree` renamed away → `make check-env` exits 1 and pytest refuses at conftest import, both naming `make worktree-provision`; restored → green.
- Memory (`docker stats --no-stream`, idle after full runs): main 2.0 GiB, worktree stacks 1.87 GiB and 1.78 GiB (Neo4j ≈ 90 %); under two concurrent runs within 100 MiB of idle. Docker (OrbStack) VM 23.5 GiB against the 128 GB host.

**Residual risks.** (1) The `.env.worktree` key set is spelled in both `infra/worktree_stack.py` and `config.py`, pinned equal only by the rendered-file round-trip test. (2) `$(error)` for an empty git common dir and the `worktree` target's provision-failure branch have no test (no git < 2.31 here; nothing in the throwaway repo makes `provision` fail after a fresh `git worktree add`). (3) Stack ownership is directory existence (plus sibling `MM_STACK_NAME`); a foreign compose project named `meetingminer-<x>` whose volumes are named exactly like ours and whose containers are gone would still be swept. (4) `MM_PROJECTION_LOCK_KEY` is process-wide; a shell exporting it re-keys `rebuild` and the worker (documented). (5) Api/web ports stay fixed — `make up` collides across checkouts (B-35). (6) Worktrees created before this lands have no `.env.worktree`; after landing, their store targets and test sessions are refused until `make worktree-provision` runs there. (7) The Docker VM's 23.5 GiB, not the host, bounds the stack count; `make down` in an idle worktree keeps its volumes.

### Review Findings

- [x] [Review][Patch] Incomplete or incoherent worktree metadata can silently target another stack [infra/Makefile:224]
- [x] [Review][Patch] The orphan pruner accepts invalid `meetingminer-*` project names as owned worktree stacks [infra/worktree_stack.py:359]
- [x] [Review][Patch] A container label bypasses the pruner's foreign-volume safety check [infra/worktree_stack.py:379]
- [x] [Review][Patch] Failure recovery for a pre-11.2 worktree either cannot run or starts the main stack [infra/Makefile:298]
- [x] [Review][Patch] Docker-down creation can revive stale volumes when the documented retry runs [infra/Makefile:289]
- [x] [Review][Patch] Worktree cleanup can return success after stack discovery or teardown failed [infra/Makefile:272]
- [x] [Review][Patch] Pruning races worktree creation after taking its ownership snapshot [infra/worktree_stack.py:424]
- [x] [Review][Patch] The provisioning lock's exclusion behavior is unverified [server/tests/test_worktree_stack.py:116]
- [x] [Review][Patch] The projection lock-key validator accepts a trailing newline [server/meetingminer/projections/locks.py:58]
- [x] [Review][Patch] Three required documents omit the concrete Docker VM bound [README.md:351]

### Remediation Follow-up Review Findings — 2026-08-30

- [x] [Review][Patch] Make stack name/id non-overridable and assert effective identity immediately before Compose [infra/Makefile:626] — owner decision 2026-08-30; closed red/green on the follow-up review branch.
- [x] [Review][Patch] Add the generated stack incarnation identity to AD-10 [docs/architecture.md:109] — owner decision 2026-08-30; Story 11-2 owns this sentence.
- [x] [Review][Patch] Worktree removal could tear down a copied record's foreign stack [infra/Makefile:382]
- [x] [Review][Patch] A process name override could hide a copied record from the test-session guard [server/tests/conftest.py:237]
- [x] [Review][Patch] Make directives and duplicate assignments bypassed the ownership-record grammar [infra/Makefile:25]
- [x] [Review][Patch] Same-target provisioners could publish two incarnation ids [infra/worktree_stack.py:483]
- [x] [Review][Patch] `worktree-remove` accepted a traversal instead of a slug [infra/Makefile:394]
- [x] [Review][Patch] `make down` in an unprovisioned worktree targeted the main project [infra/Makefile:987]
- [x] [Review][Patch] The application loader accepted another worktree's copied record [server/meetingminer/config.py:899]
- [x] [Review][Patch] `worktree-prune` masked Git worktree removal failure [infra/Makefile:428]
- [x] [Review][Patch] The ownership-recheck regression did not exercise the final recheck [server/tests/test_worktree_stack.py:1079]
- [x] [Review][Patch] Stack slug/project/id regexes accepted a trailing newline [infra/worktree_stack.py:166]
- [x] [Review][Patch] The final start check ran after destructive claim [infra/Makefile:654]
- [x] [Review][Patch] `WT_ENVFILE` could redirect every ownership guard [infra/Makefile:17]
- [x] [Review][Patch] Identity helpers misclassified missing and main-checkout records [infra/worktree_stack.py:910]

Full evidence, red/green commit history, and resolutions are in `review-story-11-2-followup-2026-08-30.md`.

## Suggested Review Order

**Ownership entry point**

- Derive identity from the active checkout and reject process conflicts before any target runs.
  [`Makefile:7`](../../infra/Makefile#L7)

- Check parsed identity before destructive claim, then recheck immediately before Compose.
  [`Makefile:654`](../../infra/Makefile#L654)

**Identity validation**

- Enforce linked/main topology and compare process, parsed, and live identities centrally.
  [`worktree_stack.py:911`](../../infra/worktree_stack.py#L911)

- Keep loader identity file-owned while preserving process precedence for locations and endpoints.
  [`config.py:938`](../../server/meetingminer/config.py#L938)

**Architecture and operator contract**

- Distinguish generated ownership metadata from endpoint-location overrides in AD-10.
  [`architecture.md:109`](../../docs/architecture.md#L109)

- Document the non-overridable identity and final Compose recheck for every agent.
  [`AGENTS.md:88`](../../AGENTS.md#L88)

**Regression evidence**

- Exercise hostile identity, pre-claim mutation, path redirection, and recovery with fake Docker.
  [`test_makefile_procs.py:2123`](../../server/tests/test_makefile_procs.py#L2123)

- Pin loader identity precedence and reject identity keys in the shared secrets file.
  [`test_config.py:838`](../../server/tests/test_config.py#L838)
