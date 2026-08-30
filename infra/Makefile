# MeetingMiner dev environment (stories 1.1 + 1.10, AD-9).
# Compose runs only the data stores (3 dev + 2 test twins); api, worker, and Vite run as
# macOS host processes, backgrounded with pidfiles + logs under .logs/.

SHELL := /bin/bash

ROOT    := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/..)
INFRA   := $(ROOT)/infra
LOGS    := $(ROOT)/.logs
ENVFILE := $(ROOT)/.env
VENV    := $(ROOT)/server/.venv
WEB     := $(ROOT)/web
# The Teams puller (AD-1 black box). It shares no server code; the only reason
# the Makefile knows about it is that its own test suite validates emitted
# drops against docs/source-drop.schema.json, so both halves of that contract
# have to run under `make test`. Only the tool source is tracked here — the
# working archive it pulls into (occurrence folders, the signed-in browser
# profile, the pull ledger) lives outside this repo.
PULLER  := $(ROOT)/tools/puller
# Where the puller actually RUNS: the working archive outside this repo that
# holds the meeting corpus and the signed-in browser profile. `--all`, `--login`
# and `--replay` resolve against __dirname, so the archive keeps its own copy of
# the source and the two can drift. The path is per-machine and per-operator, so
# it is bound here only as an override rather than a constant.
PULLER_ARCHIVE ?= $(MM_PULLER_ARCHIVE)

COMPOSE := docker compose --env-file $(ENVFILE) -f $(INFRA)/docker-compose.yml

# Host process bind targets, in one place so each launch line, its readiness
# poll, and the messages we print can never drift apart.
API_HOST := 127.0.0.1
API_PORT := 8000
# Vite binds ::1 only when left to its default `localhost`, so a 127.0.0.1
# poll would never succeed: bind and poll the same explicit address.
WEB_HOST := 127.0.0.1
WEB_PORT := 5173

# Anchored launch-command patterns (ERE, finding 10): liveness and stop checks
# match the actual launch commands, never bare substrings like `uvicorn` or
# `vite` that could hit unrelated processes. api and web additionally carry
# this checkout's own paths, so a second clone (or any other project's vite)
# is not mistaken for ours.
API_PATTERN    := $(VENV)/bin/uvicorn meetingminer\.api\.main:app
# The worker cannot be path-scoped: a macOS venv python re-execs the framework
# binary, so ps shows ".../Python.app/Contents/MacOS/Python -m ..." with no
# venv path (hence [Pp]ython). A stable checkout-derived marker in argv keeps
# another clone's worker from matching a stale local pidfile.
WORKER_OWNER   := $(shell printf '%s' "$(ROOT)" | cksum | awk '{print $$1}')
WORKER_PATTERN := [Pp]ython[0-9.]* -m meetingminer\.worker\.main --mm-owner=$(WORKER_OWNER)( |$$)
WEB_PATTERN    := $(WEB)/node_modules/.*vite

# Readiness polling budget: $(READY_TRIES) x $(READY_DELAY)s per process.
READY_TRIES := 60
READY_DELAY := 0.5

# Pidfile claim: how long to wait for another start's in-flight claim to be
# filled in with a real pid, how many times to retry the claim itself, and how
# long an empty pidfile must sit untouched before it counts as abandoned by a
# crashed make rather than in flight.
CLAIM_TRIES    := 20
CLAIM_DELAY    := 0.1
CLAIM_ATTEMPTS := 5
CLAIM_STALE_SECONDS := 60

# Appended to every daemon launch: close stdin plus any inherited make
# jobserver pipe FDs. Without this, `make -j up` never exits — the daemons
# hold the jobserver pipe open and the outer make blocks reading it. The
# launch lines also clear MAKEFLAGS/MFLAGS/MAKELEVEL, which is what carries a
# FIFO-style jobserver (make 4.4+) that no FD range can close.
DETACH_FDS := </dev/null 3<&- 4<&- 5<&- 6<&- 7<&- 8<&- 9<&-
DETACH_ENV := MAKEFLAGS= MFLAGS= MAKELEVEL=

# Let corepack fetch pnpm without an interactive prompt.
export COREPACK_ENABLE_DOWNLOAD_PROMPT := 0

# `up`'s prerequisites must run in listed order (stores -> migrate ->
# processes); .NOTPARALLEL disables parallel execution in this makefile so
# `make -j` cannot start host processes before the store healthcheck gate
# (finding 3).
.NOTPARALLEL:

.PHONY: help bootstrap up down test test-fast puller-test puller-sync puller-archive-check web-test evals-test evals-run migrate api worker web client \
        rebuild purge digest backfill-drop-paths mint-drop test-db-prune check-reviews check-tools check-docker check-env check-client check-stores check-dev-stores check-test-stores check-api \
        infra-up start-api start-worker start-web \
        stop-api stop-worker stop-web \
        worktree worktree-list worktree-remove

help:
	@echo "MeetingMiner targets:"
	@echo "  make bootstrap   - check tools, enable pnpm, create .env, install server + web + puller deps"
	@echo "  make up          - start the data stores (Docker: 3 dev + 2 test twins), apply migrations, then api/worker/web (host, backgrounded)"
	@echo "  make down        - stop host processes and containers"
	@echo "  make test        - run the puller suite, the web suite, the eval suite, the server suite, and build the web app"
	@echo "  make test-fast   - the iteration loop: check-client, the store-free suites, then the server suite's fast set (pytest -m 'not slow'). Needs Postgres only: its Postgres-backed tests skip with a named reason when it is down; twin-bound tests are slow and deselected here — make test is the gate that requires the twins"
	@echo "  make puller-test - run the puller's own suite (emit-drop + drop-schema validation)"
	@echo "  make web-test    - run the web component suite (vitest)"
	@echo "  make evals-test  - run the eval harness suite (schema, loader, subject selection, check algorithms, run artifacts; no stores, no api)"
	@echo "  make evals-run   - one eval run: the store-backed checks (2.1-2.4, 2.10-2.11) against the"
	@echo "                     ingested scripted corpus. Needs the api AND the stores up, and holds"
	@echo "                     them for the duration (AGENTS.md). Writes an immutable run folder"
	@echo "                     under evals/runs/. Options via EVAL_ARGS, e.g."
	@echo "                     make evals-run EVAL_ARGS='--run-label capture'"
	@echo "                     It fails today by design: both ground-truth fixtures still carry"
	@echo "                     placeholder source_ids, so the run has no subjects to measure."
	@echo "  make migrate     - apply pending database migrations (server/meetingminer/migrations/)"
	@echo "  make test-db-prune - drop leaked, unowned idle meetingminer_test_* databases"
	@echo "  make check-reviews - verify every dispatched code review has a committed report"
	@echo "  make purge       - delete every meeting outside a keep-set, with its evidence, produced"
	@echo "                     content and published documents. REPORTS ONLY by default; deleting"
	@echo "                     takes PURGE_ARGS=--delete. The keep-set is always explicit:"
	@echo "                     make purge PURGE_ARGS='--keep-corpus scripted --delete'"
	@echo "                     Source drops are kept unless --drops is passed; rows an earlier"
	@echo "                     merge already orphaned are kept unless --sweep-orphans is."
	@echo "                     Run 'make rebuild' afterwards:"
	@echo "                     the projection stores still describe the old corpus."
	@echo "  make backfill-drop-paths - anchor pre-2.1a drop paths to MM_DROPS_ROOT (run once after migrate; BACKFILL_ARGS='--dry-run')"
	@echo "  make mint-drop   - mint a source drop from a local recording and/or transcript and POST it"
	@echo "                     to the api (AD-1's second source). Needs no store and no migration;"
	@echo "                     a video mint needs ffprobe on PATH (checked by 'make bootstrap')."
	@echo "                     Arguments via MINT_ARGS, e.g."
	@echo "                     make mint-drop MINT_ARGS=\"'~/Downloads/standup.mp4' --corpus scripted --title 'Daily Standup'\""
	@echo "                     Quote each path inside MINT_ARGS: the value is word-split by the shell."
	@echo "  make puller-archive-check - report drift between tools/puller and the working archive"
	@echo "  make puller-sync - copy the tracked puller source into the working archive"
	@echo "                     Both need MM_PULLER_ARCHIVE=<dir> (the archive is per-machine)."
	@echo "  make ingest-drop DROP=<dir> - ingest a drop finalized on another machine and copied into MM_DROPS_ROOT"
	@echo "  make api         - run the FastAPI api in the foreground (:$(API_PORT), --reload)"
	@echo "  make worker      - run the worker in the foreground"
	@echo "  make web         - run the Vite dev server in the foreground (:$(WEB_PORT))"
	@echo "  make client      - regenerate the typed TS client from the live OpenAPI schema"
	@echo "  make worktree STORY=<slug>        - isolated checkout + branch for one piece of work"
	@echo "  make worktree-list                - show every worktree"
	@echo "  make worktree-remove STORY=<slug> - remove one when its work has landed"
	@echo "  make worktree-prune               - remove every clean worktree already merged into origin/main"
	@echo "                     Worktrees isolate CODE, not the Docker stores: server suites use"
	@echo "                     per-run Postgres databases; projection tests queue on a shared lock;"
	@echo "                     make evals-run remains serial (see AGENTS.md)."
	@echo "  make rebuild     - regenerate the Neo4j + Meilisearch projections from Postgres + config.yaml"
	@echo "                     SINGLE-FLIGHT across every worktree sharing the stores: it takes the"
	@echo "                     same cross-worktree file lock as the projection tests before writing,"
	@echo "                     queues on a holder up to MM_PROJECTION_LOCK_TIMEOUT_SECONDS, then"
	@echo "                     refuses by name. Never run two rebuilds at once."
	@echo "                     Run it after an embedder swap or a chunking retune in config.yaml,"
	@echo "                     after wiping a store volume, or whenever a store's content is suspect."
	@echo "                     Routine ingestion needs none of this - the worker projects as it goes."
	@echo "                     Its embedding pass needs the configured model pulled locally:"
	@echo "                     'ollama pull qwen3-embedding:0.6b'. Without it the structural pass"
	@echo "                     still succeeds and the corpus stays searchable (--structural-only)."
	@echo "                     Flags via ARGS, e.g. make rebuild ARGS='--meeting <uuid> --embed-only'"
	@echo "  make digest      - write one example Morning Digest email from every published artifact"
	@echo "                     in Postgres (FR31, story 4.5). Read-only; no delivery mechanism."
	@echo "                     Requires an output path: make digest DIGEST_ARGS='--output /tmp/digest.txt'"

# curl is not decoration: readiness polling and the `make client` identity
# check both depend on it, so its absence must be a named error rather than a
# mysterious "never became ready".
check-tools:
	@command -v uv >/dev/null 2>&1 || { echo "error: 'uv' not found — install it (https://docs.astral.sh/uv/) and retry."; exit 1; }
	@command -v docker >/dev/null 2>&1 || { echo "error: 'docker' not found — install Docker (OrbStack/Docker Desktop) and retry."; exit 1; }
	@command -v node >/dev/null 2>&1 || { echo "error: 'node' not found — install Node LTS and retry."; exit 1; }
	@command -v corepack >/dev/null 2>&1 || { echo "error: 'corepack' not found — it ships with Node LTS; check your Node install."; exit 1; }
	@command -v curl >/dev/null 2>&1 || { echo "error: 'curl' not found — startup readiness checks and 'make client' need it; install curl and retry."; exit 1; }
	@command -v ffmpeg >/dev/null 2>&1 || { echo "error: 'ffmpeg' not found — the worker's frames stage samples video with it; install it ('brew install ffmpeg') and retry."; exit 1; }
	@command -v ffprobe >/dev/null 2>&1 || { echo "error: 'ffprobe' not found — the worker's probe stage reads media metadata with it; it ships with ffmpeg ('brew install ffmpeg'), so check your install."; exit 1; }
	@# tesseract is deliberately NOT checked here: it is the configured fallback
	@# for the Ocr port (config.yaml `ocr.fallback`), engaged only when Apple
	@# Vision is unavailable. The macOS default needs no extra binary, and the
	@# adapter names 'brew install tesseract' itself when the fallback is the
	@# one that cannot run.

check-docker:
	@docker info >/dev/null 2>&1 || { echo "error: the Docker daemon is not running — start Docker (OrbStack/Docker Desktop) and retry."; exit 1; }

# -r, not -f (finding 12): an unreadable .env must fail this guard too.
#
# MM_DROPS_ROOT is checked by name (story 2.1a) because `bootstrap` only copies
# .env.example when .env is absent, so an existing checkout never receives a
# new key. Without this the first signal is a fatal api/worker abort at a
# moment the operator was not thinking about configuration. Presence only —
# whether the path is absolute and exists is the loader's gate, which reports
# it far better than a shell test could.
check-env:
	@[ -r "$(ENVFILE)" ] || { echo "error: $(ENVFILE) missing or unreadable — run 'make bootstrap' (it copies .env.example)."; exit 1; }
	@grep -Eq '^[[:space:]]*(export[[:space:]]+)?MM_DROPS_ROOT[[:space:]]*=[[:space:]]*[^[:space:]#]' "$(ENVFILE)" \
		|| { echo "error: MM_DROPS_ROOT is not set in $(ENVFILE)."; \
		     echo "  Story 2.1a anchors every stored drop path to it, so the api and the worker both refuse to start without it."; \
		     echo "  It is the directory holding your source drops: read-only to MeetingMiner, permanent, and never created for you."; \
		     echo "  Add it with, e.g.:  echo 'MM_DROPS_ROOT=/absolute/path/to/drops' >> $(ENVFILE)"; \
		     exit 1; }
	@! grep -Eq '^[[:space:]]*(export[[:space:]]+)?MM_DROPS_ROOT[[:space:]]*=[[:space:]]*(["'"'"']{2})[[:space:]]*(#.*)?$$' "$(ENVFILE)" \
		|| { echo "error: MM_DROPS_ROOT is empty in $(ENVFILE)."; exit 1; }

# The generated TS client is committed (finding 1); a checkout without it is
# broken and must fail loudly, not serve a Vite import-resolution error.
# App.tsx imports all three of these, so a partial checkout is caught too.
check-client:
	@for f in client.gen.ts sdk.gen.ts types.gen.ts; do \
		[ -f "$(WEB)/src/client/$$f" ] || { echo "error: generated TS client incomplete — $(WEB)/src/client/$$f is missing; it is committed to git, so restore the checkout or regenerate it with 'make client' (needs the api running)."; exit 1; }; \
	done

# --- worktrees (AGENTS.md) --------------------------------------------------
# Isolated checkouts so two agents never share a working tree. Placed beside
# the repo rather than inside it: no .gitignore entry to maintain, and no
# tooling walks into them. `.env` is symlinked rather than copied so secrets
# and MM_CONTENT_ROOT have one source of truth.
WT_ROOT := $(abspath $(ROOT)/../meetingminer-wt)

worktree:
	@[ -n "$(STORY)" ] || { echo "error: STORY is required, e.g. 'make worktree STORY=1-12'"; exit 1; }
	@[ ! -e "$(WT_ROOT)/$(STORY)" ] || { echo "error: $(WT_ROOT)/$(STORY) already exists — 'make worktree-list', or pick another STORY."; exit 1; }
	@mkdir -p "$(WT_ROOT)"
	@git -C $(ROOT) show-ref --verify --quiet refs/heads/story/$(STORY) 		&& git -C $(ROOT) worktree add "$(WT_ROOT)/$(STORY)" story/$(STORY) 		|| git -C $(ROOT) worktree add -b story/$(STORY) "$(WT_ROOT)/$(STORY)" main
	@[ -r "$(ENVFILE)" ] && ln -sfn "$(ENVFILE)" "$(WT_ROOT)/$(STORY)/.env" 		|| echo "note: no readable $(ENVFILE) to link — run 'make bootstrap' in the worktree."
	@echo ""
	@echo "worktree ready: $(WT_ROOT)/$(STORY)  (branch story/$(STORY))"
	@echo "  cd $(WT_ROOT)/$(STORY) && make bootstrap"
	@echo "  .env is symlinked from the main checkout; config.yaml came with the branch."
	@echo "  The Docker stores are SHARED — hold them one agent at a time (AGENTS.md)."

worktree-list:
	@git -C $(ROOT) worktree list

worktree-remove:
	@[ -n "$(STORY)" ] || { echo "error: STORY is required, e.g. 'make worktree-remove STORY=1-12'"; exit 1; }
	@git -C $(ROOT) worktree remove "$(WT_ROOT)/$(STORY)" || { echo "note: uncommitted changes present — commit them, or re-run with 'git worktree remove --force'."; exit 1; }
	@echo "removed $(WT_ROOT)/$(STORY) — branch story/$(STORY) is kept; delete it once merged."

# Sweep worktrees whose work has landed. Builder and reviewer sessions end
# without cleaning up (their context is spent by then), so leftover worktrees
# accumulate under $(WT_ROOT). This removes only what is provably finished:
# working tree clean AND HEAD already landed in origin/main — as an ancestor,
# or with every commit patch-equivalent (`git cherry`), because a reviewer who
# rebases the story onto main lands the content without the ref. Anything
# dirty, unpushed, or unmerged is kept and named. The landed branch is deleted
# with the worktree — its content is fully contained in main. Safe to run any
# time.
worktree-prune:
	@git -C $(ROOT) fetch --prune --quiet origin
	@for wt in $(WT_ROOT)/*/; do \
		[ -e "$$wt.git" ] || continue; \
		if [ -n "$$(git -C "$$wt" status --porcelain 2>/dev/null | head -1)" ]; then \
			echo "keep $$wt — uncommitted changes"; continue; \
		fi; \
		head=$$(git -C "$$wt" rev-parse HEAD 2>/dev/null) || continue; \
		if git -C $(ROOT) merge-base --is-ancestor "$$head" origin/main \
			|| ! git -C $(ROOT) cherry origin/main "$$head" | grep -q '^+'; then \
			branch=$$(git -C "$$wt" rev-parse --abbrev-ref HEAD); \
			git -C $(ROOT) worktree remove "$$wt" && echo "pruned $$wt (merged into origin/main)"; \
			if [ "$$branch" != "HEAD" ]; then git -C $(ROOT) branch -D "$$branch" >/dev/null 2>&1 && echo "deleted branch $$branch" || true; fi; \
		else \
			echo "keep $$wt — not merged into origin/main"; \
		fi; \
	done

bootstrap: check-tools
	@command -v pnpm >/dev/null 2>&1 || corepack enable pnpm
	@[ -f $(ENVFILE) ] || { cp $(ROOT)/.env.example $(ENVFILE); echo "created .env from .env.example — fill in provider API keys, MM_CONTENT_ROOT and MM_DROPS_ROOT"; }
	uv sync --project $(ROOT)/server
	pnpm --dir $(WEB) install
	@# The puller keeps its own npm project (CommonJS, its own lockfile) — it is
	@# its own black box, not part of the pnpm workspace.
	npm --prefix $(PULLER) install
	@echo "bootstrap complete."

# Brings the stores up first so DB-backed tests cannot pass vacuously by
# skipping; running pytest directly still skips them with a named reason.
# puller-test and web-test both come before infra-up: neither needs a store,
# so a failure in either shows up in seconds rather than after Docker has spun
# up three containers.
# `make test` is this project's only gate — there is no CI — so the vitest
# suite has to run here or it never runs at all. The web build follows the
# server suite (finding 23): the committed client must type-check and bundle
# without a live api.
# The server step passes `-m ""`: server/pyproject.toml's addopts selects
# `-m "not slow"` (the fast set, story 11.1), and an empty expression on the
# command line replaces it and clears the filter, so the gate runs the `slow`
# modules too. `make test-fast` is the iteration loop.
test: check-client puller-test web-test evals-test infra-up check-dev-stores check-test-stores
	cd $(ROOT) && MM_REQUIRE_TEST_STORES=1 uv run --project $(ROOT)/server pytest -m "" $(ROOT)/server/tests
	pnpm --dir $(WEB) run build

# The iteration loop (story 11.1): check-client first, so a missing client
# fails with its named message rather than as a Vite import error inside
# web-test; then the three store-free suites; then the server suite under
# pyproject's default `-m "not slow"` — the tests whose duration the test
# process controls (1,393 of 1,719 at bd5fecb; `pytest server/tests --co -q`
# shows the current split). The fast set needs Postgres only: when Postgres
# is down its Postgres-backed tests skip with a named reason, and `-rs`
# prints every skip with its reason, so an unrun suite is visible rather
# than silent. Twin-bound tests are `slow` — or a collection error if
# unmarked — so the default selection deselects them here and a twins-only
# outage produces no skips; `make test` is the gate that requires the twins
# (check-test-stores). Skips never set the exit code; failures and collection
# errors do.
test-fast: check-client puller-test web-test evals-test
	cd $(ROOT) && uv run --project $(ROOT)/server pytest -q -rs $(ROOT)/server/tests

# The eval harness half of `make test` (story 5.1). Joins puller-test and
# web-test in the store-free group ahead of infra-up: ground-truth validation,
# the loader rules and subject selection are file and pure-function work, so a
# broken manifest reports in under a second rather than after three containers
# have started.
#
# Runs from $(ROOT) with an absolute test path: `evals/` and `evals/tests/`
# both carry an __init__.py, so pytest's prepend import mode puts the repo
# root on sys.path and `from evals.harness...` resolves with no path hack.
evals-test:
	cd $(ROOT) && uv run --project $(ROOT)/server pytest $(ROOT)/evals/tests

# One eval run (story 5.2): the tier-1 capture checks against the ingested
# scripted corpus. Deliberately NOT part of `make test` and deliberately not in
# the store-free group — it reads Postgres and lists the corpus through the
# api, so it holds the shared stores for its duration (AGENTS.md) and needs a
# live api the way `make client` does.
#
# It also writes: each run creates an immutable folder under `evals/runs/`
# holding the deterministic report and the resolved configuration it was
# measured against. That is why it is a separate target rather than a phase of
# `make test` — a test run that leaves a committed audit artifact behind should
# be asked for on purpose.
#
# It fails today, by design: both shipped ground-truth fixtures still carry
# placeholder `source_id` values, so nothing ingested answers to them and the
# run fails on `test_subjects_exist` naming each one. A green run here before
# the scripted meetings are recorded and pulled would mean the subject selector
# or the zero-subject failure was weakened.
#
# EVAL_ARGS rather than ARGS: ARGS defaults to `--all` for `make rebuild`,
# which pytest would reject.
EVAL_ARGS ?=

# Deliberately NOT $(ARGS): that carries a global `?= --all` default for
# `rebuild`, and `backfill drop-paths` accepts only `--dry-run`, so sharing
# the variable made the no-argument `make backfill-drop-paths` fail every
# time while an explicit `ARGS='--dry-run'` worked — the default path was the broken one.
BACKFILL_ARGS ?=

# Same reasoning as BACKFILL_ARGS: not $(ARGS), whose `?= --all` default is for
# `rebuild` and which mint-drop would reject. Deliberately unquoted below so an
# operator can pass several flags; a path containing spaces needs its own quotes
# inside the value.
MINT_ARGS ?=

# Same reasoning as BACKFILL_ARGS/MINT_ARGS: not $(ARGS), whose `?= --all`
# default is for `rebuild` and which `digest` would reject (`--output PATH`
# is required, and `--all` is not a flag it knows). No default value: an
# operator must always name an output path explicitly.
DIGEST_ARGS ?=

# Prerequisite order matters: the stores come up BEFORE the api is probed. The
# api cannot answer without them, so probing first would report "api not
# reachable" on a stack that `infra-up` was about to fix, and the `infra-up`
# prerequisite could never help.
#
# `--api-base-url $(CLIENT_URL)` rather than the harness default: `check-api`
# validates $(CLIENT_URL), and a run that read a different address would have
# been guarded on one service and measured another the moment anyone overrides
# API_PORT. $(EVAL_ARGS) comes after, so an operator can still point a run
# somewhere else on purpose.
evals-run: check-env infra-up check-dev-stores check-api
	cd $(ROOT) && uv run --project $(ROOT)/server pytest $(ROOT)/evals/checks --api-base-url $(CLIENT_URL) $(EVAL_ARGS)

# The eval harness lists the corpus through the public api (AD-16), so a run
# without one answering would fail on a connection error rather than on what it
# measured. Same identity check `make client` uses: a foreign service holding
# the port must be a named error, not a mysterious empty corpus.
check-api:
	@HEALTH=$$(curl -sf --max-time 3 $(CLIENT_URL)/health) || { echo "error: api not reachable on :$(API_PORT) — an eval run reads the corpus through it; run 'make up' (or 'make api') first."; exit 1; }; \
	echo "$$HEALTH" | grep -Eq '"service"[[:space:]]*:[[:space:]]*"meetingminer-api"' || { echo "error: the service on :$(API_PORT) did not identify as the MeetingMiner api — refusing to run an eval against a foreign service (health response: $$HEALTH)"; exit 1; }

# The web half of `make test`, split out so it can also be run on its own.
# Needs no store and no api: it runs the component suite over the committed
# client's types.
web-test:
	@[ -d "$(WEB)/node_modules" ] || { echo "error: web deps missing — run 'make bootstrap' first."; exit 1; }
	pnpm --dir $(WEB) run test

# Story 1.7's projection suites are store-backed and skip themselves with a
# named reason when Neo4j or Meilisearch is unreachable. `infra-up --wait`
# proves the *containers* are healthy; this proves the ports actually answer
# from the host, so a whole suite cannot go quietly unrun under `make test`.
# Running pytest directly still skips rather than fails, which is the
# established DB-test convention.
check-stores: check-dev-stores check-test-stores

check-dev-stores:
	@curl -sf -o /dev/null --max-time 5 http://localhost:7700/health || { echo "error: Meilisearch is not answering on :7700 — the api and worker need it; run 'make infra-up' and retry."; exit 1; }
	@# Bolt (7687), not the HTTP browser (7474): Bolt is the protocol the
	@# projection module connects over, and the two can disagree. SHELL is
	@# bash here, so /dev/tcp is a dependency-free TCP probe; a real Bolt
	@# handshake would need a driver, and the container healthcheck already
	@# covers "the process is up".
	@exec 3<>/dev/tcp/localhost/7687 2>/dev/null || { echo "error: Neo4j Bolt is not answering on :7687 — the api and worker need it; run 'make infra-up' and retry."; exit 1; }

# Exercise the same validated AppConfig and authenticated clients pytest uses,
# including MM_TEST_NEO4J_URI / MM_TEST_MEILI_URL overrides. Direct pytest
# keeps its named-skip convention; this Make gate promotes that state to a
# failure so the repository's full test command cannot pass vacuously.
# `-m ""` clears pyproject's default `-m "not slow"`: test_projections_search
# is a `slow` module, and a node id inside a deselected module collects
# nothing and exits 5 (story 11.1).
check-test-stores:
	cd $(ROOT) && MM_REQUIRE_TEST_STORES=1 uv run --project $(ROOT)/server pytest -q -m "" $(ROOT)/server/tests/test_projections_search.py::test_configured_projection_stores_are_reachable

# The puller half of AD-1's "puller and pipeline both validate against the drop
# schema in their tests". Needs no stores and no api — it runs the emit-drop
# mapping over temp fixtures.
#
# Missing deps must FAIL here, not skip: this repo always contains the puller,
# so on a fresh clone that has not run `make bootstrap` a skip would make
# `make test` green with all of the puller's tests unrun. ajv-formats is checked
# too — without it every `format: date-time` assertion silently degrades to a
# no-op.
#
# A missing $(PULLER) is the same hazard one level up, and it is the one a
# relocation actually trips: the binding goes stale, the rule skips, and every
# puller test leaves `make test` without anyone noticing. So the skip is allowed
# only where the puller genuinely may be absent — a standalone checkout of the
# tool on its own. Inside a MeetingMiner checkout, which docs/source-drop.schema.json
# identifies, an unresolvable binding is an error.
puller-test:
	@if [ ! -d "$(PULLER)" ]; then \
		if [ -f "$(ROOT)/docs/source-drop.schema.json" ]; then \
			echo "error: PULLER ($(PULLER)) is not a directory, but this is a MeetingMiner"; \
			echo "       checkout — the binding is stale. Skipping here would drop every"; \
			echo "       puller test, including AD-1's only source-side check of the drop"; \
			echo "       schema, out of a green 'make test'."; \
			exit 1; \
		fi; \
		echo "skip: puller test suite — $(PULLER) is not present in this checkout."; \
	elif [ -d "$(PULLER)/node_modules/ajv" ] && [ -d "$(PULLER)/node_modules/ajv-formats" ]; then \
		MM_REQUIRE_DROP_SCHEMA=1 npm --prefix $(PULLER) test; \
	else \
		echo "error: puller dev deps missing — $(PULLER)/node_modules needs both ajv and ajv-formats; run 'make bootstrap' (or 'npm --prefix $(PULLER) install')."; \
		exit 1; \
	fi

infra-up: check-docker check-env
	$(COMPOSE) up -d --wait

# Order-only prerequisite: migrations must never run before Postgres is
# healthy (matters under `make -j up`).
migrate: check-env | infra-up
	@[ -x "$(VENV)/bin/python" ] || { echo "error: server venv missing — run 'make bootstrap' first."; exit 1; }
	cd $(ROOT) && $(VENV)/bin/python -m meetingminer.db migrate

# One-shot after migration 0008 (story 2.1a): convert every pre-2.1a absolute
# drop path to one anchored to MM_DROPS_ROOT. Fails closed — any row it cannot
# place under the configured root is named and the exit code is non-zero, so a
# partial backfill cannot look clean. `ARGS=--dry-run` reports and writes
# nothing.
#
# Order is forgiving on purpose: a worker started before this command fails
# every un-backfilled job it claims, and this command puts exactly those jobs
# back to `queued` as it converts them. Running it late costs a second
# invocation, not the jobs.
test-db-prune: check-env | infra-up
	@echo "pruning leaked, unowned idle meetingminer_test_* databases..."
	@cd $(ROOT) && $(VENV)/bin/python -c "$$PRUNE_TEST_DBS"

# Four reviews were completed in a session's terminal and never filed; naming
# the required file in the review prompt did not prevent the fourth. This
# checks the requirement mechanically: every review-prompt-story-* artifact
# must have a committed review-story-* report. Reviewers run it before
# reporting completion; anyone can run it to catch a loss immediately.
# Needs no store, no env, no venv.
check-reviews:
	@python3 $(ROOT)/_bmad/scripts/check_review_reports.py

# Per-run test databases (story 2.7) are dropped by their own fixtures; a run
# killed with SIGKILL cannot, so this sweeps what is left. Before every
# destructive action it obtains the same session advisory lock a suite holds
# from CREATE through teardown. That closes the no-target-backend startup race
# which a pg_stat_activity snapshot cannot see.
define PRUNE_TEST_DBS
import psycopg
from psycopg import sql
from meetingminer import db
from meetingminer.config import load_config

OWNER_LOCK_PREFIX = "meetingminer-test-owner:"
cfg = load_config()
pruned = skipped_owned = skipped_active = failed = 0
with psycopg.connect(db.conninfo(cfg), autocommit=True) as conn:
    rows = conn.execute(
        "SELECT datname FROM pg_database"
        " WHERE datname ~ '^meetingminer_test(_(pending|cli))?_[0-9a-f]{12}$$'"
    ).fetchall()
    for (name,) in rows:
        locked = conn.execute(
            "SELECT pg_try_advisory_lock(hashtextextended(%s, 0))",
            (OWNER_LOCK_PREFIX + name,),
        ).fetchone()[0]
        if not locked:
            skipped_owned += 1
            print(f"skipped owned {name}")
            continue
        try:
            active = conn.execute(
                "SELECT 1 FROM pg_stat_activity WHERE datname = %s LIMIT 1", (name,)
            ).fetchone()
            if active is not None:
                skipped_active += 1
                print(f"skipped active {name}")
                continue
            conn.execute(
                sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name))
            )
            pruned += 1
            print(f"dropped {name}")
        except psycopg.Error as exc:
            failed += 1
            print(f"failed {name}: {exc}")
        finally:
            conn.execute(
                "SELECT pg_advisory_unlock(hashtextextended(%s, 0))",
                (OWNER_LOCK_PREFIX + name,),
            )
    print(
        f"pruned {pruned} database(s); skipped owned {skipped_owned};"
        f" skipped active {skipped_active}; failed {failed}"
    )
if failed:
    raise SystemExit(1)
endef
export PRUNE_TEST_DBS

backfill-drop-paths: check-env | infra-up migrate
	@[ -x "$(VENV)/bin/python" ] || { echo "error: server venv missing — run 'make bootstrap' first."; exit 1; }
	@echo "backfill: converting pre-2.1a drop paths; any job a worker already failed for a missing drop path is re-queued as it is converted."
	cd $(ROOT) && $(VENV)/bin/python -m meetingminer.backfill drop-paths $(BACKFILL_ARGS)

# Bring your own recording (story 2.1b): a local file -> a source drop -> the
# intake door. `check-env` and nothing else — minting reads MM_DROPS_ROOT from
# .env, writes one drop directory, and touches no store, so neither `infra-up`
# nor `migrate` is a prerequisite. The POST at the end needs the api, but an api
# that is down is not a reason to refuse to mint: the drop is finalized either
# way and the command prints the request that ingests it.
#
# `check-tools` is deliberately not a prerequisite either, even though minting a
# video needs ffprobe: it also demands docker, node, corepack and uv, none of
# which minting touches. The command checks for ffprobe itself and refuses with
# a named error, which is the narrower gate.
mint-drop: check-env
	@[ -x "$(VENV)/bin/python" ] || { echo "error: server venv missing — run 'make bootstrap' first."; exit 1; }
	cd $(ROOT) && $(VENV)/bin/python -m meetingminer.mintdrop $(MINT_ARGS)

# Ingest a published YouTube video (story 6.2): URL -> drop -> the same intake
# door. `check-env` only, for mint-drop's reasons: the command writes one drop
# and touches no store. `yt-dlp` and `ffmpeg` are deliberately NOT added to
# `check-tools`: the command checks for them itself at run time and refuses
# with a named error, which is the narrower gate. `--no-post`/`--drops`/`--api`
# pass through YT_ARGS the way MINT_ARGS does.
youtube-drop: export MM_YOUTUBE_URL := $(value URL)
youtube-drop: check-env
	@[ -x "$(VENV)/bin/python" ] || { echo "error: server venv missing — run 'make bootstrap' first."; exit 1; }
	@[ -n "$${MM_YOUTUBE_URL}" ] || { echo "error: URL is required — run 'make youtube-drop URL=https://www.youtube.com/watch?v=...' (options go in YT_ARGS='--no-post ...')."; exit 1; }
	cd $(ROOT) && $(VENV)/bin/python -m meetingminer.youtube "$${MM_YOUTUBE_URL}" $(YT_ARGS)


# The puller is tested here and runs there, so "there" can silently fall behind
# a fix that passed the gate. Neither target joins `make test`: the archive is
# per-machine and is legitimately absent on most checkouts. The tracked file set
# comes from git rather than a hand-kept list, so a file added to the package is
# covered without anyone remembering to update this.
puller-archive-check: _puller-archive-guard
	@drift=0; \
	for f in $$(git -C $(ROOT) ls-files tools/puller | sed 's|^tools/puller/||'); do \
	  if [ ! -e "$(PULLER_ARCHIVE)/$$f" ]; then echo "missing:  $$f"; drift=1; \
	  elif ! cmp -s "$(PULLER)/$$f" "$(PULLER_ARCHIVE)/$$f"; then echo "differs:  $$f"; drift=1; fi; \
	done; \
	if [ $$drift -eq 0 ]; then echo "in sync: $(PULLER_ARCHIVE) matches tools/puller"; \
	else echo ""; echo "The archive copy is what pulls real meetings. Run 'make puller-sync' to update it."; exit 1; fi

puller-sync: _puller-archive-guard
	@for f in $$(git -C $(ROOT) ls-files tools/puller | sed 's|^tools/puller/||'); do \
	  mkdir -p "$$(dirname "$(PULLER_ARCHIVE)/$$f")"; \
	  cp "$(PULLER)/$$f" "$(PULLER_ARCHIVE)/$$f"; \
	done
	@echo "synced $$(git -C $(ROOT) ls-files tools/puller | wc -l | tr -d ' ') tracked files -> $(PULLER_ARCHIVE)"
	@echo "note: node_modules there is the archive's own; run 'npm --prefix $(PULLER_ARCHIVE) install' if deps changed."

_puller-archive-guard:
	@[ -n "$(PULLER_ARCHIVE)" ] || { \
	  echo "error: the puller archive path is unset. It is per-machine, so name it:"; \
	  echo "         make $(MAKECMDGOALS) MM_PULLER_ARCHIVE=/path/to/pull_transcript"; \
	  echo "       It is the directory holding the occurrence folders and .transcript-profile/."; \
	  exit 1; }
	@[ -d "$(PULLER_ARCHIVE)" ] || { echo "error: $(PULLER_ARCHIVE) is not a directory."; exit 1; }

# The other half of the work-laptop path: ingest a drop that was finalized on
# another machine (`emit-drop --no-post`) and copied into this laptop's drops
# root. The puller normally POSTs its own drop; it cannot when it runs with no
# route to this api. This is not a second ingestion door — it is the same
# POST /ingests the puller makes, with the path resolved on this side.
ingest-drop: check-env check-api
	@[ -n "$(DROP)" ] || { echo "error: DROP is unset — name the drop directory, e.g."; 	    echo "  make ingest-drop DROP=/absolute/path/to/drops/2026-08-21-scripted-ui-demo-orders-module-1a2b3c4d"; exit 1; }
	@[ -d "$(DROP)" ] || { echo "error: $(DROP) is not a directory."; exit 1; }
	@[ -f "$(DROP)/metadata.json" ] || { echo "error: $(DROP) has no metadata.json — that is not a drop."; exit 1; }
	@ROOTDIR=$$(grep -E '^[[:space:]]*(export[[:space:]]+)?MM_DROPS_ROOT[[:space:]]*=' "$(ENVFILE)" \
	    | tail -1 | sed -E 's/^[^=]*=[[:space:]]*//; s/^["'"'"']//; s/["'"'"'][[:space:]]*$$//'); 	ABS=$$(cd "$(DROP)" && pwd); 	case "$$ABS/" in "$$ROOTDIR"/*) : ;; 	  *) echo "error: $$ABS is not under MM_DROPS_ROOT ($$ROOTDIR)."; 	     echo "       Paths are stored relative to that root (spine AD-3), so a drop outside it"; 	     echo "       cannot be recorded. Move the drop directory there and re-run."; exit 1 ;; 	esac; 	echo "ingesting $$ABS"; 	curl -sS -X POST $(CLIENT_URL)/ingests -H 'content-type: application/json' \
	  -d "$$(printf '{"dropPath":"%s"}' "$$ABS")" -w '\nHTTP %{http_code}\n'

# The starts run through a sub-make (command-line variables propagate) so that
# a failure part-way through can stop exactly the processes this invocation
# launched — a failed `up` must not leave a half-started environment behind.
# Each start records itself in $(LOGS)/.started only when it actually launches,
# so a process that was already running is never rolled back.
up: check-client infra-up migrate
	@mkdir -p $(LOGS); rm -f "$(LOGS)/.started"
	@if $(MAKE) --no-print-directory -C $(INFRA) start-api start-worker start-web; then \
		rm -f "$(LOGS)/.started"; \
		echo "up: stores healthy; api (:$(API_PORT)), worker, web (:$(WEB_PORT)) running — logs in $(LOGS)/"; \
	else \
		STARTED=$$(tail -r "$(LOGS)/.started" 2>/dev/null || tac "$(LOGS)/.started" 2>/dev/null || true); \
		if [ -n "$$STARTED" ]; then \
			echo "up: startup failed — stopping the processes this invocation started"; \
			for name in $$STARTED; do $(MAKE) --no-print-directory -C $(INFRA) stop-$$name; done; \
		fi; \
		rm -f "$(LOGS)/.started"; \
		echo "up: failed — environment left stopped; fix the error above and run 'make up' again"; \
		exit 1; \
	fi

# start_guard(name, pattern): decide whether this start owns the launch.
# Sets ALREADY=1 when a matching process is already running (the caller skips
# the launch but still verifies readiness — "already running" must never mean
# "assumed healthy"), otherwise claims the pidfile with noclobber so that of
# two concurrent starts exactly one launches.
#
# Pidfile states, in the order they are handled:
#  - absent            -> claim it and launch.
#  - exists but empty  -> another start claimed it microseconds ago and has
#                         not written its pid yet. Wait for the pid. If none
#                         arrives and the file is still fresh, that start is
#                         simply slow: skip rather than steal its claim. Only
#                         an empty pidfile older than CLAIM_STALE_SECONDS is
#                         treated as abandoned by a crashed make.
#  - live + matching   -> ALREADY=1.
#  - anything else     -> stale pidfile: remove it and retry the claim.
# A claim that fails while the pidfile does NOT exist is a real error (the
# logs directory is unwritable, the disk is full): fail loudly instead of
# silently reporting a duplicate start that never launched anything.
define start_guard
	ALREADY=0; CLAIMED=0; \
	for attempt in $$(seq 1 $(CLAIM_ATTEMPTS)); do \
		if ( set -o noclobber; : > $(LOGS)/$(1).pid ) 2>/dev/null; then CLAIMED=1; break; fi; \
		if [ ! -e $(LOGS)/$(1).pid ]; then \
			echo "$(1): cannot create $(LOGS)/$(1).pid — check that $(LOGS) exists, is writable, and the disk is not full"; \
			exit 1; \
		fi; \
		PID=$$(cat $(LOGS)/$(1).pid 2>/dev/null); \
		if [ -z "$$PID" ]; then \
			for i in $$(seq 1 $(CLAIM_TRIES)); do \
				sleep $(CLAIM_DELAY); \
				PID=$$(cat $(LOGS)/$(1).pid 2>/dev/null); \
				[ -n "$$PID" ] && break; \
			done; \
		fi; \
		if [ -z "$$PID" ]; then \
			NOW=$$(date +%s); \
			MTIME=$$(stat -f %m $(LOGS)/$(1).pid 2>/dev/null || stat -c %Y $(LOGS)/$(1).pid 2>/dev/null || echo $$NOW); \
			AGE=$$((NOW - MTIME)); \
			if [ "$$AGE" -lt $(CLAIM_STALE_SECONDS) ]; then \
				echo "$(1): another start claimed the pidfile but did not publish a pid within $(CLAIM_TRIES) checks — retry after it starts or fails"; \
				exit 1; \
			fi; \
			echo "$(1): removing abandoned pidfile claim (empty for $${AGE}s)"; \
			rm -f $(LOGS)/$(1).pid; \
			continue; \
		fi; \
		CMD=$$(ps -p $$PID -o command= 2>/dev/null || true); \
		if echo "$$CMD" | grep -Eq -- '$(2)'; then \
			echo "$(1): already running (pid $$PID)"; \
			ALREADY=1; \
			break; \
		fi; \
		echo "$(1): removing stale pidfile (pid $$PID is $${CMD:-gone}, not a $(1) process)"; \
		rm -f $(LOGS)/$(1).pid; \
	done; \
	if [ "$$ALREADY" = "0" ] && [ "$$CLAIMED" = "0" ]; then \
		echo "$(1): could not claim $(LOGS)/$(1).pid after $(CLAIM_ATTEMPTS) attempts"; \
		exit 1; \
	fi
endef

# verify_started(name, pattern, ready-check): poll the readiness command until
# it passes, the process dies, or the budget runs out (finding 6 — never a
# fixed sleep). This runs for an already-running process too: a live but hung
# process must not be reported as a successful `up`.
# Failure stops the process through stop_proc (process-group TERM with KILL
# escalation — a never-ready vite or `uvicorn --reload` has children), then
# names the process and prints its last log lines (finding 5).
define verify_started
	READY=0; \
	for i in $$(seq 1 $(READY_TRIES)); do \
		PID=$$(cat $(LOGS)/$(1).pid 2>/dev/null); \
		if [ -z "$$PID" ] || ! kill -0 $$PID 2>/dev/null; then break; fi; \
		if $(3) >/dev/null 2>&1; then READY=1; break; fi; \
		sleep $(READY_DELAY); \
	done; \
	if [ "$$READY" = "1" ]; then \
		echo "$(1): ready (pid $$(cat $(LOGS)/$(1).pid)) -> $(LOGS)/$(1).log"; \
	else \
		if [ -s $(LOGS)/$(1).pid ] && kill -0 $$(cat $(LOGS)/$(1).pid) 2>/dev/null; then \
			echo "$(1): never became ready — stopping it"; \
			$(call stop_proc,$(1),$(2)); \
		fi; \
		rm -f $(LOGS)/$(1).pid; \
		echo "$(1): failed to start — last log lines from $(LOGS)/$(1).log:"; \
		tail -n 25 $(LOGS)/$(1).log 2>/dev/null || true; \
		exit 1; \
	fi
endef

start-api:
	@mkdir -p $(LOGS)
	@[ -x "$(VENV)/bin/uvicorn" ] || { echo "error: server venv missing — run 'make bootstrap' first."; exit 1; }
	@$(call start_guard,api,$(API_PATTERN)); \
	if [ "$$ALREADY" = "0" ]; then \
		cd $(ROOT); set -m; $(DETACH_ENV) nohup $(VENV)/bin/uvicorn meetingminer.api.main:app --host $(API_HOST) --port $(API_PORT) >> $(LOGS)/api.log 2>&1 $(DETACH_FDS) & echo $$! > $(LOGS)/api.pid; echo api >> "$(LOGS)/.started"; \
	fi; \
	$(call verify_started,api,$(API_PATTERN),curl -sf -o /dev/null --max-time 2 http://$(API_HOST):$(API_PORT)/health)

# The readiness grep starts past the bytes worker.log already held, so a
# startup line from a previous run can never pass a hung worker.
start-worker:
	@mkdir -p $(LOGS)
	@[ -x "$(VENV)/bin/python" ] || { echo "error: server venv missing — run 'make bootstrap' first."; exit 1; }
	@$(call start_guard,worker,$(WORKER_PATTERN)); \
	if [ "$$ALREADY" = "0" ]; then \
		OFFSET=$$(wc -c < $(LOGS)/worker.log 2>/dev/null | tr -d ' ' || echo 0); \
		cd $(ROOT); set -m; $(DETACH_ENV) nohup $(VENV)/bin/python -m meetingminer.worker.main --mm-owner=$(WORKER_OWNER) >> $(LOGS)/worker.log 2>&1 $(DETACH_FDS) & echo $$! > $(LOGS)/worker.pid; echo worker >> "$(LOGS)/.started"; \
		$(call verify_started,worker,$(WORKER_PATTERN),tail -c +$$(($${OFFSET:-0}+1)) $(LOGS)/worker.log | grep -Eq '"event"[[:space:]]*:[[:space:]]*"worker\.startup"'); \
	else \
		$(call verify_started,worker,$(WORKER_PATTERN),true); \
	fi; \
	:

start-web: check-client
	@mkdir -p $(LOGS)
	@[ -x "$(WEB)/node_modules/.bin/vite" ] || { echo "error: web deps missing — run 'make bootstrap' first."; exit 1; }
	@$(call start_guard,web,$(WEB_PATTERN)); \
	if [ "$$ALREADY" = "0" ]; then \
		cd $(WEB); set -m; $(DETACH_ENV) nohup $(WEB)/node_modules/.bin/vite --host $(WEB_HOST) --port $(WEB_PORT) --strictPort >> $(LOGS)/web.log 2>&1 $(DETACH_FDS) & echo $$! > $(LOGS)/web.pid; echo web >> "$(LOGS)/.started"; \
	fi; \
	$(call verify_started,web,$(WEB_PATTERN),curl -sf -o /dev/null --max-time 2 http://$(WEB_HOST):$(WEB_PORT)/)

# stop_proc(name, command-pattern): kills only a process whose command matches
# the anchored pattern (PID reuse must never kill an unrelated process),
# taking its whole process group (started with set -m, so the group is its
# own) unless that group is somehow our own.
define stop_proc
	if [ -f $(LOGS)/$(1).pid ]; then \
		PID=$$(cat $(LOGS)/$(1).pid); \
		CMD=$$(ps -p $$PID -o command= 2>/dev/null || true); \
		if [ -z "$$CMD" ]; then \
			echo "$(1): not running"; \
			rm -f $(LOGS)/$(1).pid; \
		elif ! echo "$$CMD" | grep -Eq -- '$(2)'; then \
			echo "$(1): pid $$PID is now '$$CMD', not a $(1) process — removing stale pidfile without killing"; \
			rm -f $(LOGS)/$(1).pid; \
		else \
			PGID=$$(ps -p $$PID -o pgid= 2>/dev/null | tr -d ' '); \
			MYPGID=$$(ps -p $$$$ -o pgid= 2>/dev/null | tr -d ' '); \
			echo "$(1): stopping (pid $$PID)"; \
			if [ -n "$$PGID" ] && [ "$$PGID" != "$$MYPGID" ]; then \
				kill -TERM -- -$$PGID 2>/dev/null || kill -TERM $$PID 2>/dev/null || true; \
			else \
				kill -TERM $$PID 2>/dev/null || true; \
			fi; \
			for i in $$(seq 1 20); do kill -0 $$PID 2>/dev/null || break; sleep 0.5; done; \
			if kill -0 $$PID 2>/dev/null; then \
				echo "$(1): forcing kill"; \
				if [ -n "$$PGID" ] && [ "$$PGID" != "$$MYPGID" ]; then kill -KILL -- -$$PGID 2>/dev/null || true; fi; \
				kill -KILL $$PID 2>/dev/null || true; \
			fi; \
			rm -f $(LOGS)/$(1).pid; \
		fi; \
	else \
		echo "$(1): no pidfile"; \
	fi
endef

stop-api:
	@$(call stop_proc,api,$(API_PATTERN))

stop-worker:
	@$(call stop_proc,worker,$(WORKER_PATTERN))

stop-web:
	@$(call stop_proc,web,$(WEB_PATTERN))

# After the pidfile-based stops: warn about matching processes we hold no
# pidfile for (finding 7 — a deleted .logs/ must not orphan silently), then
# stop the containers even when .env interpolation is broken (finding 8).
down: stop-web stop-worker stop-api
	@STRAY=$$( { pgrep -f '$(API_PATTERN)'; pgrep -f '$(WORKER_PATTERN)'; pgrep -f '$(WEB_PATTERN)'; } 2>/dev/null | sort -un | tr '\n' ' ' ); \
	if [ -n "$$STRAY" ]; then \
		echo "down: warning — processes launched from this checkout are still running without pidfiles (pids: $$STRAY) — stop them manually"; \
	fi; \
	if docker info >/dev/null 2>&1; then \
		if [ -r $(ENVFILE) ] && $(COMPOSE) down; then \
			:; \
		else \
			echo "down: compose down via --env-file failed or .env unreadable — falling back to project-name teardown"; \
			docker compose -p meetingminer down; \
		fi; \
	else \
		echo "down: Docker daemon not running — skipped compose down"; \
	fi

# Preflight (finding 9): importing meetingminer.api.main runs the config +
# schema fail-fast gates in this shell, so a broken config exits non-zero
# here instead of leaving the uvicorn reloader parent idling over a dead app.
api: check-env
	@[ -x "$(VENV)/bin/uvicorn" ] || { echo "error: server venv missing — run 'make bootstrap' first."; exit 1; }
	@cd $(ROOT) && $(VENV)/bin/python -c "import meetingminer.api.main"
	cd $(ROOT) && $(VENV)/bin/uvicorn meetingminer.api.main:app --reload --host $(API_HOST) --port $(API_PORT)

worker: check-env
	@[ -x "$(VENV)/bin/python" ] || { echo "error: server venv missing — run 'make bootstrap' first."; exit 1; }
	cd $(ROOT) && $(VENV)/bin/python -m meetingminer.worker.main --mm-owner=$(WORKER_OWNER)

# check-client for the same reason start-web has it: the foreground dev server
# would otherwise serve the broken fresh-clone page.
web: check-client
	@[ -x "$(WEB)/node_modules/.bin/vite" ] || { echo "error: web deps missing — run 'make bootstrap' first."; exit 1; }
	cd $(WEB) && $(WEB)/node_modules/.bin/vite --host $(WEB_HOST) --port $(WEB_PORT) --strictPort

# Identity check (finding 11): only regenerate the client from a service that
# answers /health as the MeetingMiner api — never from a foreign service that
# happens to hold the port. The generator is pointed at the very same URL that
# was validated (-i overrides the input in web/openapi-ts.config.ts), so an
# API_PORT override can never validate one service and generate from another.
# CLIENT_URL is deliberately `localhost` rather than $(API_HOST): the
# generator bakes this origin into the committed client as its default
# baseUrl, so it has to stay stable no matter which address the api was
# bound to. Identity check and generation use the identical URL.
CLIENT_URL := http://localhost:$(API_PORT)

# AD-4's answer to a corrupt, stale, or wiped projection store: regenerate it
# from Postgres + config.yaml, never by hand-editing an index. Also how an
# embedder swap (AD-8) and a chunking retune land, since both invalidate every
# projected document. Order-only prerequisites for the same reason `migrate`
# has them: a rebuild started before the stores are up reports an outage
# instead of doing the work.
# `rebuild` itself refuses to pick a scope for you (an unscoped run drops
# both stores), so the bare `make rebuild` supplies the corpus-wide one the
# help text promises; ARGS replaces it entirely.
ARGS ?= --all

rebuild: check-env | infra-up migrate
	@[ -x "$(VENV)/bin/rebuild" ] || { echo "error: the 'rebuild' console script is missing from the server venv — run 'make bootstrap' first."; exit 1; }
	cd $(ROOT) && $(VENV)/bin/rebuild $(ARGS)

# The keep-set has no default: `prune` itself refuses an unscoped run, and
# supplying one here would defeat that. `make purge` with no PURGE_ARGS is
# therefore a usage error from the command, which is the intended landing.
PURGE_ARGS ?=

purge: check-env | infra-up migrate
	@[ -x "$(VENV)/bin/prune" ] || { echo "error: the 'prune' console script is missing from the server venv — run 'make bootstrap' first."; exit 1; }
	cd $(ROOT) && $(VENV)/bin/prune $(PURGE_ARGS)

digest: check-env | infra-up migrate
	@[ -x "$(VENV)/bin/digest" ] || { echo "error: the 'digest' console script is missing from the server venv — run 'make bootstrap' first."; exit 1; }
	cd $(ROOT) && $(VENV)/bin/digest $(DIGEST_ARGS)

client:
	@HEALTH=$$(curl -sf --max-time 3 $(CLIENT_URL)/health) || { echo "error: api not reachable on :$(API_PORT) — run 'make up' (or 'make api') first."; exit 1; }; \
	echo "$$HEALTH" | grep -Eq '"service"[[:space:]]*:[[:space:]]*"meetingminer-api"' || { echo "error: the service on :$(API_PORT) did not identify as the MeetingMiner api — refusing to generate the client from a foreign schema (health response: $$HEALTH)"; exit 1; }
	pnpm --dir $(WEB) run client -i $(CLIENT_URL)/openapi.json
