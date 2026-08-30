---
title: 'Story 1.10: Development Environment Hardening'
type: 'chore'
created: '2026-08-18'
status: 'done'
review_loop_iteration: 0
baseline_commit: '3f0b52b96268d9c753f076bca02e6e9b1253a456'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/review-story-1-1-2026-08-18.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The story 1.1 review found 27 failure modes in the scaffold; 25 are still live. `make up` reports success on fresh clones that serve a broken page, two `.env` dialects can silently diverge on passwords, stores bind 0.0.0.0 with committed default passwords, and flat top-level packages (`config`, `api`, `db`, …) invite shadowing — a namespace move that gets more expensive with every pipeline story.

**Approach:** Implement epics.md Story 1.10 (lines 408–444) exactly: namespace all server code under `server/meetingminer/`, commit the generated TS client, converge on one `.env` dialect, pin and localhost-bind the stores, replace fixed sleeps with polled readiness, harden the Makefile lifecycle and guards, and add tests for the previously untested orchestration.

## Boundaries & Constraints

**Always:**
- Finding numbers refer to `review-story-1-1-2026-08-18.md`; epics.md Story 1.10 ACs are the acceptance authority. Findings 13 and 26 are already fixed — verify, don't redo.
- Namespace (19): every server module moves under `server/meetingminer/` (`api`, `worker`, `domain`, `pipeline`, `adapters`, `projections`, `config.py`, `db.py`, `migrations/`); wheel `only-include` collapses to `meetingminer`; invocations become `meetingminer.api.main:app`, `-m meetingminer.worker.main`, `-m meetingminer.db migrate` everywhere (Makefile, tests, `db.py` usage/error strings). No compat shims or re-exports of the old names.
- Config anchoring (17): no repo file resolved from `config.py`'s `__file__`. `config.yaml`/`.env` resolve from `MM_CONFIG_PATH`/`MM_ENV_PATH`, else cwd-relative; failure names both attempted locations. `docs/source-drop.schema.json` resolves off the same anchor.
- `.env` dialect (14–16): parse with `python-dotenv` (promoted to explicit dep) so loader and compose `--env-file` agree; never strip comments from quoted values; blank process-env values don't mask `.env` values; `MM_CONTENT_ROOT` is user-expanded, with a startup warning when unset or not a directory (18).
- Makefile lifecycle (2–7): pidfile liveness checks verify the command name (both start and stop sides) and remove stale pidfiles; pidfile creation is noclobber; `up`'s prerequisites are ordered under `make -j`; readiness = polling `/health`, :5173, and the `worker.startup` log event with a timeout — no fixed sleeps; startup failure prints the failing process's last log lines; `make down` warns (via `pgrep`) about matching processes it holds no pidfile for.
- Guards (8–12, 22): `make down` stops containers even when `.env` interpolation fails; `make api` preflights config before the reloader; `stop_proc` patterns anchor to the actual launch commands; `make client` verifies the schema comes from the MeetingMiner api (service name in `/health`); `check-env` uses `-r`; App.tsx aborts the in-flight health check before starting a new one.
- Compose (20–21): all store ports bind `127.0.0.1:` only; images pinned to patch tags or digests; every healthcheck uses a binary guaranteed present in its pinned image.
- Client (1): commit `web/src/client/` (drop the `.gitignore` line); `make client` remains the refresh path; `make up` fails with a named error when the client is absent.
- Tests (23–25, 27): `make test` also builds the web app; new subprocess test runs api fail-fast through the real uvicorn launcher (incl. `--reload`); no-Docker pytest drives `stop_proc` kill/spare/no-duplicate against decoy processes; autouse conftest fixture clears `MM_CONFIG_PATH`/`MM_ENV_PATH` for non-subprocess tests.
- Behavior contracts from stories 1.1/1.2 (named fail-fast errors, problem+json, migration gate) survive unchanged; existing tests keep passing after mechanical rename updates.

**Ask First:**
- Any new config key or env var beyond those documented here.
- Any new dependency beyond `python-dotenv`.
- Any change to `docs/source-drop.schema.json` or existing migration files.

**Never:**
- No pipeline/stage code (1.3), no CI workflows, no auth, no drops-root confinement; never modify `pull_transcript/` or the review file; don't rewrite `verify_started`/`stop_proc` semantics beyond the listed findings.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Fresh clone | `make bootstrap && make up` | :5173 renders, calls `/health`; no manual `make client` | absent client → `up` fails, named error |
| Stale pidfile, PID reused | `make up` | pidfile replaced, process started once | N/A |
| Concurrent `make up` ×2 / `make -j up` | | no duplicate processes; host procs start only after healthy stores + migrate | N/A |
| `.logs/` deleted while running | `make down` | containers stop; warning names still-running matching processes | pgrep sweep, exit 0 |
| Process dies during startup | `make up` | failure names the process and prints its last log lines | exit 1 |
| `KEY="v" # note` in `.env` | loader + compose | both resolve `v` | N/A |
| `export VAR=` (blank) in shell | `make up` / loader | `.env` value wins | N/A |
| `MM_CONTENT_ROOT=~/mm` | loader | expands to `$HOME/mm` | warn if not a directory |
| `.env` breaks compose interpolation | `make down` | containers still stop | fallback compose down |
| Foreign service on :8000 | `make client` | refuses to generate | error names identity mismatch |
| Old flat import | `uv run python -c "import config"` | ImportError | N/A |

</frozen-after-approval>

## Code Map

- `_bmad-output/implementation-artifacts/review-story-1-1-2026-08-18.md` — the 27 findings; authority for each fix's intent. Read-only.
- `server/pyproject.toml` — deps `:6-16`, wheel `only-include` `:28-39` (`db.py`, `migrations` added by 1.2); collapse to `meetingminer`; add `python-dotenv`.
- `server/config.py:20-22` — `REPO_ROOT` from `__file__` (finding 17); parser `:129-159` (quote-strip only when first==last, then `re.split(r"\s#", …)` — the dual-dialect bug); merge `:162-180` (blank env masks; `mm_content_root` `:115,173` — no expanduser, silent None); `MM_CONFIG_PATH`/`MM_ENV_PATH` handling `:192-199`.
- `server/db.py:25` — `MIGRATIONS_DIR` from `__file__` (correct once inside the package — migrations move with it); usage strings `:10,177`, error text `:39` (`make migrate`) asserted by `test_migrations.py:118`.
- `server/api/ingests.py:27,30,46` — `DROP_SCHEMA_PATH = REPO_ROOT/docs/...`, loaded at import; must use the new anchor.
- Flat-name rename sites: imports in `api/main.py:22-24`, `api/jobs.py:12-13`, `worker/main.py:20-21`, `db.py:23`, `tests/conftest.py:20-21,106`, `tests/test_*.py` (incl. `_API_LIFESPAN_SCRIPT` string `test_migrations.py:62-72`, argv lists `test_failfast.py:35-58`, `test_migrations.py:113-207`).
- `infra/Makefile` — `check-env:44-45` (`-f`), `test:54-57`, `migrate:62-66` (`python -m db migrate`), `up:68-69` (unordered prereqs), `verify_started:71-82` (`sleep 2`, log-path-only failure), `start-*:84-112` (bare `kill -0`, non-noclobber pidfiles), `stop_proc:114-148` (unanchored grep `:125`), `stop-*:150-157` (patterns `uvicorn`/`worker.main`/`vite`), `down:159-164` (`--env-file` interpolation), `api:166-168` (no preflight), `client:178-180` (reachability only). Review anchors are +9–11 lines stale.
- `infra/docker-compose.yml` — ports `:15-17,32-34,52-53` (0.0.0.0), images `:9,28,46` (mutable tags), meilisearch healthcheck `:56-61` (curl).
- `.gitignore:27` — `web/src/client/` (finding 1); `git ls-files web/src/client` is empty today.
- `web/src/App.tsx:22-48` — `check` has unmount abort but no ref-held controller for re-click race; button `:72`.
- `server/tests/conftest.py` — fixtures `app_config:58-60`, skip logic `:68-75`, DB lifecycle `:79-96`; no autouse env isolation. `test_failfast.py:14-24` `_run` helper to extend for the uvicorn variant.
- `config.yaml:45-55` + `.env.example` — store settings and env keys; loader anchor change must keep these resolving from repo root cwd.

## Tasks & Acceptance

**Execution:**
- [x] `server/meetingminer/` — `git mv` all packages + `config.py`, `db.py`, `migrations/` under it; add package `__init__.py`; update every first-party import; `uv sync` to refresh the editable install.
- [x] `server/pyproject.toml` — `only-include = ["meetingminer"]`; add `python-dotenv`.
- [x] `server/meetingminer/config.py` — anchor resolution (17), dotenv parser (14), merge skip-blank (15), `expanduser` + content-root warning (16, 18).
- [x] `server/meetingminer/api/ingests.py` — schema path via anchor (17).
- [x] `server/meetingminer/db.py` — `-m meetingminer.db` strings; `MIGRATIONS_DIR` relative to package.
- [x] `infra/docker-compose.yml` — `127.0.0.1:` binds, pinned images, healthcheck binaries (20–21).
- [x] `infra/Makefile` — module-path updates; lifecycle fixes (2–7); guard fixes (8–12); `test` builds web (23).
- [x] `.gitignore` + `web/src/client/` — un-ignore and commit generated client; `up` presence check (1).
- [x] `web/src/App.tsx` — AbortController ref for re-check race (22).
- [x] `.env.example` — document the single dialect (quoting, comments, `export`).
- [x] `server/tests/` — rename updates; autouse env-isolation fixture (27); uvicorn fail-fast test (25); `test_makefile_procs.py` decoy-process stop_proc suite (24); `.env`-dialect parity tests incl. matrix rows (14–16).

### Review Findings

- [x] [Review][Patch] Bound the Uvicorn reload test's stderr read [server/tests/test_failfast.py:106] — `readline()` blocks when Uvicorn emits no newline, so the monotonic 30-second loop cannot enforce its deadline and can leave the suite hanging. Use non-blocking/select-based output collection or `communicate(timeout=...)` while retaining the cleanup path.
- [x] [Review][Defer] Validate the source-drop schema against its metaschema at API startup [server/meetingminer/api/ingests.py:61] — deferred, pre-existing. A syntactically valid but structurally invalid JSON Schema can bypass the startup error path and fail during the first intake instead.
- [x] [Review][Patch] Scope worker process ownership across checkouts [infra/Makefile:31] — add a checkout-derived, command-line ownership marker to the background worker launch and require it in `WORKER_PATTERN`, so a stale PID file cannot identify another checkout's worker.
- [x] [Review][Patch] Preserve an already-running worker during a repeated start [infra/Makefile:241] — `start-worker` captures the current end of `worker.log` even when `start_guard` set `ALREADY=1`; its readiness probe then waits for a startup event that can never be new, times out, and stops the healthy worker. Use a liveness readiness probe for the already-running path.
- [x] [Review][Patch] Do not report a fresh, unfilled pidfile claim as a successful start [infra/Makefile:175] — after the short claim wait, `start_guard` exits 0 without running readiness verification. A concurrent `make up` can therefore succeed while the claiming invocation later fails. Return a named in-progress failure or keep waiting until the claim has a PID and can be verified.

**Acceptance Criteria:**
- Given epics.md Story 1.10's seven AC blocks, when each is exercised, then it passes as written.
- Given the moved layout, when `uv run --project server pytest server/tests` runs with stores up, then all existing 1.1/1.2 tests pass unmodified in behavior.
- Given a fresh database, when `make migrate` runs twice via the new module path, then the second run is a no-op.
- Given `make test`, when it runs, then server pytest and the web build both execute and pass.

## Design Notes

- Commit the client (not generate-in-`up`): `make test`'s web build must succeed without a live api, which generation-at-startup can't provide. `make client` stays the refresh path.
- Anchor choice (17): `MM_CONFIG_PATH` wins, else `./config.yaml` from cwd; `ConfigError` names both. Derive the schema/docs root from the resolved config file's parent — one anchor, no second mechanism.
- `MIGRATIONS_DIR` stays `Path(__file__).parent / "migrations"` — inside the package it ships with the wheel, which fixes the non-editable-install gap the review flagged.
- Decoy tests (24): invoke `make stop-api` etc. against fake processes matching/near-missing the anchored patterns; no Docker, no real services.

## Verification

**Commands:**
- `uv run --project server pytest server/tests` — expected: all pass (DB tests need `make infra-up`).
- `make test` — expected: pytest + web build both pass.
- `make down && make up` — expected: polled readiness, no sleeps; then `make up` again → "already running", no duplicates.
- `make migrate && make migrate` — expected: second run reports nothing to apply.
- `uv run --project server python -c "import config"` — expected: ImportError (flat names gone).
- `docker inspect` port bindings — expected: all `127.0.0.1` only.
