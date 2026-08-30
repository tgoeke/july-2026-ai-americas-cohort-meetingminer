---
title: 'Story 1.1: One-Command Development Environment'
type: 'feature'
created: '2026-08-18'
status: 'done'
review_loop_iteration: 0
baseline_commit: '8be58418e80fa0280af629a98a28c1b3b8c66156'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The repo holds only planning docs and the vendored puller — no runnable system exists, and every later story assumes a running, consistently configured monorepo.

**Approach:** Create the architecture's source-tree seed, docker-compose for the three data stores, a root `config.yaml` driving all adapter bindings with secrets in `.env`, and a Makefile whose `make up` starts infra plus api, worker, and Vite dev server as macOS host processes (AD-9). A minimal FastAPI app serves `/health` and the OpenAPI schema from which the typed TS client generates.

## Boundaries & Constraints

**Always:**
- AD-9 split: compose runs ONLY Postgres 18 (+pgvector), Neo4j Community 2026.07, Meilisearch 1.53.x; api (:8000), worker, Vite (:5173) are host processes.
- All adapter bindings in the single versioned root `config.yaml`; `.env` (gitignored; `.env.example` committed) carries secrets + `MM_CONTENT_ROOT` only (AD-10). One shared config loader used by api and worker; load failure is fatal, never a silent default.
- Versions and tooling per the epic context's pinned stack; Python via `uv`, web via `pnpm` (corepack — pnpm is not yet installed on this machine).
- `puller` is a symlink to `pull_transcript/`; the physical move is story 1.8's.
- All six `server/` packages exist even where empty.

**Ask First:**
- Installing global tooling beyond `corepack enable pnpm`.
- Changing ports if 5432/7687/7474/7700/8000/5173 conflict.

**Never:**
- No DB schema/migrations, job tables, or pipeline logic (stories 1.2+); no folder watcher; no auth; no broker.
- Never modify anything inside `pull_transcript/` (live puller: scheduled jobs, browser session).
- No Ollama in `make up` (first needed in 1.7). No provider SDK imports.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Fresh start | clean clone, Docker up, bootstrap done | `make up` → 3 healthy containers + 3 host processes, logs in `.logs/` | N/A |
| Docker down | daemon not running | `make up` fails fast naming Docker | non-zero exit; host processes not started |
| Missing config | `config.yaml` absent/unparseable | api and worker exit non-zero naming the config problem | fatal at startup, no partial boot |
| Repeat `make up` | already running | idempotent — no duplicate processes | N/A |
| Shutdown | running system | `make down` stops host processes and containers | N/A |

</frozen-after-approval>

## Code Map

- `_bmad-output/planning-artifacts/architecture/.../ARCHITECTURE-SPINE.md` — tree seed, AD-9/AD-10, pinned stack (read-only authority).
- `pull_transcript/` — existing puller; READ-ONLY; untracked meeting archive + `.transcript-profile/`; launchd/cron logs prove it runs in place — hence symlink, not move.
- `.gitignore` — currently only `.DS_Store`.
- No `Makefile`, `server/`, `web/`, `infra/`, `evals/`, `docs/` exist — greenfield, no collisions.
- Host tooling verified: uv 0.12.5, Docker 29.4, Node v22 LTS, make; pnpm absent.

## Tasks & Acceptance

**Execution:**
- [x] `.gitignore` — add node/python/env/log/build ignores.
- [x] `infra/docker-compose.yml` — postgres (18 + pgvector image), neo4j (community 2026.07), meilisearch (1.53.x); named volumes, healthchecks, standard ports.
- [x] `infra/Makefile` + root `Makefile` (thin delegate) — `bootstrap` (check uv/docker/node, corepack pnpm, `uv sync`, `pnpm install`), `up` (compose up -d --wait, then background api/worker/web with pidfiles + logs in `.logs/`), `down`, `api`/`worker`/`web` foreground singles, `client` (regenerate TS client).
- [x] `config.yaml` — versioned skeleton: ocr apple-vision|tesseract, stt mlx-whisper|parakeet-mlx, diarizer noop, llm roles (extraction, chat = claude-sonnet-5, ollama fallback; judge = same default until the Epic 5 bake-off replaces it), embedder qwen3-embedding dim 1024, provider endpoints.
- [x] `.env.example` — provider API keys, `MM_CONTENT_ROOT`, store passwords.
- [x] `server/pyproject.toml` + packages — uv project (fastapi 0.141.x, uvicorn, pyyaml, pydantic) with `domain pipeline adapters projections api worker` packages.
- [x] `server/config.py` — typed loader for `config.yaml` + env secrets; fatal on missing/invalid; shared by api and worker.
- [x] `server/api/main.py` — FastAPI app: `/health` returning config-derived identity; OpenAPI served.
- [x] `server/worker/main.py` — loads config, structured JSON startup log, idle loop (no job tables yet).
- [x] `web/` — Vite 8 + React 19 + TS via pnpm, shadcn/ui initialized, `openapi-ts.config.ts` generating client from `localhost:8000/openapi.json` into `web/src/client/`; placeholder page calling `/health`.
- [x] `evals/README.md` + `docs/README.md` — minimal placeholders completing the seed tree.
- [x] `puller` — symlink → `pull_transcript`.
- [x] `server/tests/test_config.py` — unit-test config-loader edge cases from the I/O matrix (missing file, bad YAML, env secret pickup).

**Acceptance Criteria:**
- Given a fresh clone with Docker running, when I run `make bootstrap && make up`, then the three stores report healthy and api (:8000), worker, and Vite (:5173) run as host processes.
- Given the repository, when inspected, then the tree matches the seed: `server/{domain,pipeline,adapters,projections,api,worker}`, `web/`, `puller`, `evals/`, `infra/`, `docs/`.
- Given api or worker boots, when configuration loads, then every adapter binding comes from `config.yaml` and secrets only from `.env`.
- Given the api is running, when `make client` executes, then the typed TS client generates from the live OpenAPI schema without errors.

### Review Findings

- [x] [Review][Patch] Roll back processes started by a failed `make up` so the command cannot leave a partial environment running [infra/Makefile:59]
- [x] [Review][Patch] Quote repository-derived paths so clones beneath directories containing spaces remain operable [infra/Makefile:14]
- [x] [Review][Patch] Mark the root delegate's `FORCE` sentinel phony so a file named `FORCE` cannot suppress target forwarding [Makefile:11]
- [x] [Review][Patch] Reject blank service/store identifiers and ports outside the valid TCP range during configuration validation [server/config.py:72]
- [x] [Review][Patch] Exercise the browser-to-API CORS contract in the health endpoint tests [server/tests/test_health.py:8]
- [x] [Review][Patch] Test the unsupported-config-version fail-fast guard with a structurally valid future version [server/tests/test_config.py:94]
- [x] [Review][Patch] Pin the pnpm version used by Corepack through the package manifest [web/package.json:1]

## Spec Change Log

## Design Notes

`make up` backgrounds host processes with pidfiles under `.logs/` — zero new dependencies; `make down` kills by pidfile. Compose `--wait` + healthchecks gate host-process start so the api never races the stores.

## Verification

**Commands:**
- `make bootstrap && make up` — expected: exit 0; `docker compose -f infra/docker-compose.yml ps` shows 3 healthy services.
- `curl -s localhost:8000/health` — expected: 200 JSON naming the service.
- `make client && pnpm --dir web run build` — expected: client regenerates; type-checks clean.
- `uv run --project server pytest server/tests` — expected: config-loader tests pass.
- `make down && make up && make down` — expected: idempotent; `pgrep -f uvicorn` empty after down.

## Suggested Review Order

**Orchestration — the one command**

- Entry point: `up` composes infra-up then gated host-process starts — the story's whole promise in one target.
  [`infra/Makefile:59`](../../infra/Makefile#L59)

- stop_proc verifies the pidfile's command and kills the process group — PID reuse can never kill a stranger.
  [`infra/Makefile:105`](../../infra/Makefile#L105)

- `test` target wires pytest into the build entry point.
  [`infra/Makefile:53`](../../infra/Makefile#L53)

- Root Makefile is a catch-all delegate — no target list to drift.
  [`Makefile:1`](../../Makefile#L1)

**Infra — AD-9 runtime split**

- Compose runs only the three stores; postgres host-mapped to 5433 (5432 held by another project).
  [`docker-compose.yml:7`](../../infra/docker-compose.yml#L7)

**Config — AD-10 single source**

- The versioned skeleton every adapter binding comes from.
  [`config.yaml:5`](../../config.yaml#L5)

- Shared typed loader; any failure is a named ConfigError, never a silent default.
  [`config.py:183`](../../server/config.py#L183)

- Hardened .env parsing: export prefix, inline comments, empty keys.
  [`config.py:129`](../../server/config.py#L129)

**API ↔ web contract**

- Fatal-or-boot: the api refuses to start on bad config.
  [`main.py:19`](../../server/api/main.py#L19)

- Typed HealthResponse (camelCase) makes the generated TS client a real contract.
  [`main.py:40`](../../server/api/main.py#L40)

- Web consumes the generated SDK — no hand-written duplicate types, abortable fetch.
  [`App.tsx:27`](../../web/src/App.tsx#L27)

- Client generation config: live OpenAPI schema → web/src/client.
  [`openapi-ts.config.ts:6`](../../web/openapi-ts.config.ts#L6)

**Worker process boundary**

- Structured-log startup + idle loop proves the api/worker split before any pipeline exists.
  [`main.py:37`](../../server/worker/main.py#L37)

**Peripherals**

- Fail-fast contract pinned by subprocess tests (exit 1, named error, no traceback).
  [`test_failfast.py:34`](../../server/tests/test_failfast.py#L34)

- Loader edge cases + committed config.yaml validity (10 tests).
  [`test_config.py:1`](../../server/tests/test_config.py#L1)

- /health exact-JSON and OpenAPI-shape assertions.
  [`test_health.py:1`](../../server/tests/test_health.py#L1)
