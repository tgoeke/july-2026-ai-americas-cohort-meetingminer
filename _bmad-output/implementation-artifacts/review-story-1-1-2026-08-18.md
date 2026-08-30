# Review — Story 1.1: One-Command Development Environment

- date: 2026-08-18
- content reviewed: commit `759c0e3` against `spec-1-1-one-command-development-environment.md`
- lenses: adversarial (17 findings), edge-case-hunter (12), verification-gap (5)
- follow-up story: Story 1.10 (Development Environment Hardening) in `_bmad-output/planning-artifacts/epics.md`

Findings confirmed by more than one independent lens are marked (xN).

## Acceptance-criterion miss

1. **Fresh-clone web client gap (x3 — all lenses).** `web/src/client/` is gitignored (`.gitignore:27`), neither `make bootstrap` nor `make up` generates it, and `web/src/App.tsx:2-4` imports `@/client/*`. On any machine except the authoring one, `make bootstrap && make up` reports success while :5173 serves a Vite import-resolution error. `verify_started` (infra/Makefile:64-73) only checks process liveness after 2s, so the broken dev server passes. Evidence: `git ls-files web/src/client` is empty; it works locally only via untracked generated files.
   Fix: commit the generated client (keep `make client` as refresh), or run client generation inside `up` after start-api and fail `up` loudly when the client is absent.

## Process lifecycle (infra/Makefile)

2. **Start-side PID reuse (x2).** start-api/start-worker/start-web (:78-103) trust bare `kill -0` on a stale pidfile; a reused PID makes `make up` skip the start and exit 0. The stop side already verifies the command name — apply the same check before declaring "already running", removing stale pidfiles.
3. **`make -j` bypasses the healthcheck gate (x2).** `up`'s prerequisites (:59) have no ordering among themselves; parallel make lets start-api race infra-up. Fix: `.NOTPARALLEL:` or chain the prerequisites.
4. **Concurrent `make up` race.** Two invocations both pass the pidfile check before either writes one (:75-103) → duplicate processes, one orphan surviving `make down`. Fix: `noclobber` pidfile creation.
5. **Startup failure names a logfile, not the problem (x2).** verify_started's failure branch (:69-71) prints only the log path; the spec's I/O matrix requires the config error to be named. Fix: `tail` the last log lines on failure.
6. **Fixed `sleep 2` is not readiness.** verify_started passes processes that die at t>2s or never bind their port. Fix: poll `/health` (api), :5173 (web), and the `worker.startup` log event (worker).
7. **Lost pidfile → silent orphans (x2).** `.logs/` deleted while running: `make down` (:136-138, 150-155) exits 0 leaving uvicorn/worker/vite orphaned; next `make up` fails on port binds. Fix: `pgrep -f` safety check with a warning after pidfile-based stops.
8. **`make down` aborts when `.env` interpolation fails.** A blank/removed required var makes compose `${VAR:?}` abort `down` itself; containers keep running. Fix: fallback `docker compose -p meetingminer down` without `--env-file` interpolation.
9. **`make api --reload` survives config failure.** The uvicorn reloader parent (:157-159) outlives the app's SystemExit, violating "no partial boot" in foreground dev mode. Fix: preflight `config.load_config()` in the recipe.
10. **stop_proc patterns are unanchored substrings.** `worker.main`'s `.` matches any character; `vite`/`uvicorn` match any command containing them (:109-148). Fix: anchor to the actual launch commands (`uvicorn api\.main:app`, `python(3)? -m worker\.main`, `node_modules/\.bin/vite`).
11. **`make client` verifies reachability, not identity (:169-171).** A foreign service on :8000 silently regenerates the typed client from the wrong schema. Fix: grep the health response for the MeetingMiner service name.
12. **`check-env` uses `-f` not `-r` (:43-44).** An unreadable `.env` passes the guard built to name exactly that problem.
13. **`make help` omits `test` (:24-32).**

## Configuration (.env / config.py)

14. **Dual .env dialects (x2).** The custom parser (server/config.py:129-159) and docker compose `--env-file` (infra/Makefile:14) disagree on `export` prefixes, quotes, and inline comments; the current ordering both truncates unquoted passwords containing ` #` and leaves literal quotes on `KEY="value" # note`. Container and app passwords can silently diverge. Fix: converge on one dialect (python-dotenv/compose semantics) and never strip comments from secret values.
15. **Empty exported env var masks `.env` value (config.py:166-170).** Fix: skip blank process-env values in the merge.
16. **`MM_CONTENT_ROOT=~/...` never expanded (config.py:172-180).** Later stories would create a literal `./~` directory. Fix: `Path(v).expanduser()`.
17. **`REPO_ROOT` from `__file__` (config.py:20-22).** Breaks under any non-editable install of the wheel (hatch ships config.py). Fix: explicit anchor — `MM_CONFIG_PATH` or cwd-relative `./config.yaml`, error naming both attempted locations.
18. **`mm_content_root=None` is a silent default (config.py:112-122).** The loader contract is "load failure is fatal, never a silent default". Startup warning when unset or not a directory. (Full validation deferred to story 1.3 per deferred-work.md.)
19. **Generic top-level package names (server/pyproject.toml:23-32).** The venv installs importable modules named `config`, `api`, `pipeline`, etc.; a future dependency owning one of these shadows project code. Fix: namespace under `server/meetingminer/` before story 1.3 adds code.

## Infra (docker-compose)

20. **Stores bind 0.0.0.0 with committed default passwords (:15-17, 32-34, 52-53).** From story 1.2 on, real meeting transcripts are reachable from any shared network. Fix: bind `127.0.0.1:` explicitly — AD-9 says nothing off-host needs these ports.
21. **Mutable image tags (:9, 28, 46) + fragile Meilisearch healthcheck (:56-58).** `pg18` / `2026.07-community` / `v1.53` defeat the spec's version pinning; a patch image dropping `curl` makes the healthcheck fail forever. Fix: pin patch tags or digests; use a healthcheck binary guaranteed in the pinned image.

## Web

22. **Re-check race (web/src/App.tsx:22-48).** A click during an in-flight check lets the older response overwrite the newer result. Fix: abort the in-flight request via an AbortController ref before starting a new one.

## Verification gaps

23. **`make test` covers server pytest only (infra/Makefile:53-54).** Nothing automated builds the web app or regenerates the client, so acceptance criterion 4 (typed client generates and type-checks) has no automated proof. Fix: extend `test`/add `verify` with `pnpm --dir web run build` (plus `make client` when the api is reachable).
24. **up/down orchestration has zero automated coverage (x2).** ~100 lines of make-recipe shell; every I/O-matrix row for it is manual-only. Fix: a no-Docker pytest smoke test driving the stop targets against decoy processes (kill-a-match / spare-a-stranger / no-duplicate-start), plus a gated full-stack up→up→down smoke target.
25. **api fail-fast tested via `python -c "import api.main"`, not uvicorn (server/tests/test_failfast.py:49-62).** The supervisor layer between the SystemExit and the exit code the Makefile observes is untested; the `--reload` variant matters most. Fix: one subprocess test running the real uvicorn launcher against missing config.
26. **Worker SIGTERM graceful shutdown untested (server/worker/main.py:54-73).** stop_proc's KILL escalation would mask a regression completely. Fix: subprocess test — start worker with valid config, wait for `worker.startup`, send SIGTERM, assert exit 0 and `worker.shutdown` logged.
27. **Tests honor a developer's exported `MM_CONFIG_PATH`/`MM_ENV_PATH` (server/tests/test_health.py:8-21).** Fix: autouse conftest fixture clearing both for non-subprocess tests.
