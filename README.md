# MeetingMiner

**Turns recorded software demonstrations into searchable, citable evidence.
Every extracted artifact traces back to the video moment that produced it.**

Lead application architects mine recorded demos into requirements, architecture
decisions, and backlog changes by hand — scrubbing video, screenshotting,
aligning transcripts, pasting evidence into an LLM. It takes hours per meeting
and fails silently: a missed screen means nobody knows to look for the
requirement it contained.

MeetingMiner treats a meeting as evidence to preserve rather than a conversation
to summarize. It ingests a recording and/or its transcript, captures every
distinct application screen, aligns speaker-attributed transcript to video flow,
identifies moments, extracts artifacts (ADRs, action items, decisions), and
answers natural-language questions over the corpus — with citations that replay
the original audio and video at the timestamp they came from.

The governing rule is **no citation, no answer**: every factual claim about
meeting content must resolve to a moment, or it is not returned.

---

## Contents

- [What it does](#what-it-does)
- [How it works](#how-it-works)
- [Quick start](#quick-start)
- [Everyday commands](#everyday-commands)
- [Repository layout](#repository-layout)
- [Configuration](#configuration)
- [Models and cost](#models-and-cost)
- [Testing and evaluation](#testing-and-evaluation)
- [Troubleshooting](#troubleshooting)
- [Documentation map](#documentation-map)
- [Project status](#project-status)

---

## What it does

| Capability | What you get |
|---|---|
| **Evidence ingestion** | A write-once *source drop* (recording and/or transcript plus a `metadata.json` sidecar) becomes a fully precomputed evidence bundle: screens, screenshots, verified speaker-attributed transcript, identified moments, screen–discussion alignment, provenance, replay links, participants. |
| **Late augmentation** | A second drop that brings evidence a meeting lacks — a recovered recording, a participant graph — re-runs only the stages that evidence unlocks. Existing moments are never renumbered, re-keyed, or deleted, so citations published earlier stay valid. |
| **Evidence domain graph** | Moments, Meetings, Screens, Screenshots, Projects, Products, Participants and derived artifacts persist as first-class rows in Postgres from the instant they are created. Screen lineage recognizes the same application screen across meetings. |
| **Search and cited Q&A** | Meilisearch ranks full-text and vector matches together (`semantic_ratio`, default `0.3`) and Neo4j answers graph traversals; every answer carries citations, and every citation replays its evidence. |
| **Moment view and replay** | Open any moment: screenshot, transcript section, right rail of extracted artifacts, and an audio+video replay seeked to the moment. Transcript-only meetings render the same view with a source deep link where the replay button would be. |
| **Artifact extraction** | Two whole-transcript passes per meeting — one for the architecture summary, one for action items — rather than one call per moment. Drops that already carry the puller's extraction documents are parsed instead, with no model call. Every artifact carries the transcript timestamp that grounds it. |
| **Human-approved publishing** | Artifacts start unpublished. A per-moment approval gesture writes a markdown export to the publish root and commits ADRs to a git repository rooted there. Only published artifacts are re-indexed into the retrieval stores. |
| **Eval harness** | Scripted meetings with machine-readable YAML ground truth, judged through a deterministic-first pyramid: deterministic asserts, then LLM judge, then human judge via a written runbook. |

## How it works

```
 Teams recap                                        ┌──────────────┐
     │  tools/puller/ (Teams puller, npm)           │  React + Vite│
     ▼                                              │   web/ :5173 │
 source drop  ──POST /ingests──►  FastAPI api  ◄────┴──────────────┘
 (write-once)                      server/ :8000
     │                                 │
     │                            job queue
     ▼                                 ▼
 MM_DROPS_ROOT                      worker  ──►  MM_CONTENT_ROOT
 (material that arrived)               │         (material this pipeline produced)
                                       │
        probe → frames → ocr → screens → transcribe → align → moments → extract
                                       │
                                       ▼
                            ┌────────  Postgres  ────────┐   the only primary copy
                            │                            │
                            ▼                            ▼
                    Neo4j (graph)            Meilisearch (text + vectors)
                    ── rebuildable projections, `make rebuild` ──
```

Four properties are worth knowing before you read any code:

1. **Two storage roots, both permanent.** `MM_DROPS_ROOT` holds material that
   arrived; `MM_CONTENT_ROOT` holds material this pipeline produced. Every path
   stored in the database is relative to exactly one of them and never
   absolute, so relocating either root is an environment change rather than a
   data migration. Neither is a landing zone — drops are re-read for transcript
   re-parse, for replay, and for the augmentation comparison long after ingest,
   so both roots are backed up together.
2. **Postgres holds the only primary copy.** Neo4j and Meilisearch are derived
   projections and can be regenerated from Postgres plus `config.yaml` at any
   time. Unpublished artifacts exist only in Postgres. Embedding vectors are
   written into Meilisearch, not Postgres — the schema declares no vector
   column and enables no `vector` extension.
3. **`POST /ingests` is the only ingestion entry point.** Copying a directory
   into the drops root ingests nothing; nothing watches the folder. A producer
   has to notify the api.
4. **Every model sits behind an adapter port.** Speech recognition, OCR,
   embeddings, and LLM calls are swapped by editing `config.yaml`, never by
   changing code.

## Quick start

### Prerequisites

`make bootstrap` runs `make check-tools`, which names whichever of these is
missing:

| Tool | Why |
|---|---|
| [`uv`](https://docs.astral.sh/uv/) | server dependency and virtualenv management (Python 3.12) |
| `docker` | the three data stores plus two disposable test twins |
| `node` LTS + `corepack` | the web app (`pnpm`) and the puller (`npm`) |
| `curl` | startup readiness checks and `make client` |
| `ffmpeg` / `ffprobe` | the worker's `frames` and `probe` stages; `brew install ffmpeg` |

Two runtime dependencies `check-tools` does **not** verify, so nothing will warn
you before the relevant stage fails:

- **An [Ollama](https://ollama.com) host** for the embedder
  (`qwen3-embedding:0.6b`) and for extraction (`gpt-oss:120b`, falling back to
  `qwen3:30b`). `make rebuild`'s embedding pass needs
  `ollama pull qwen3-embedding:0.6b`; without it the structural pass still
  succeeds and the corpus stays searchable.
- **An `OPENAI_API_KEY`** for cited Q&A and the LLM judge — see
  [Models and cost](#models-and-cost).

**Platform.** The stack is developed and run on a single Apple-silicon Mac.
Speech recognition ships only MLX engines and OCR defaults to Apple Vision, all
macOS-only and all imported lazily: on Linux or Windows the adapters report
unavailability rather than failing at import, so the api, the worker's
non-transcribing stages, and the web app run, but no bundled engine will
transcribe audio. Python is pinned to `>=3.12,<3.13` because the MLX wheels
publish no build for newer interpreters.

### Set it up

```bash
git clone git@github.com:tgoeke/meetingminer.git
cd meetingminer
make bootstrap
```

`make bootstrap` checks the tools above, enables `pnpm` through `corepack`,
copies `.env.example` to `.env` if you have no `.env` yet, installs the server,
web, and puller dependency sets.

Then open `.env` and fill in all three roots. Every one of them is checked at
startup:

```bash
MM_CONTENT_ROOT=/absolute/path/to/meetingminer-content   # created if missing
MM_DROPS_ROOT=/absolute/path/to/meetingminer-drops       # must already exist
MM_PUBLISH_ROOT=/absolute/path/to/meetingminer-publish   # created if missing
```

- The **api** refuses to start when the drops root is missing or when the
  publish root is unset, uncreatable, or read-only.
- The **worker** refuses to start without both a writable content root and an
  existing drops root.

The drops root is the one MeetingMiner never creates for you, because nothing it
runs ever writes inside it. The publish root does not need to be a git
repository beforehand — the first ADR publish runs `git init` there itself.
These are fatal-at-startup checks on purpose: a wrong root is not recoverable
once ingest has written paths against it.

### Run it

```bash
make up               # stores (Docker) + migrations, then api/worker/web on the host
```

| Service | Address |
|---|---|
| api (FastAPI, uvicorn) | http://127.0.0.1:8000 — OpenAPI at `/docs` |
| web (Vite dev server) | http://127.0.0.1:5173 |
| Postgres | `127.0.0.1:5433` (5432 is taken by another project on the dev machine) |
| Neo4j | `127.0.0.1:7474` browser, `7687` Bolt |
| Meilisearch | `127.0.0.1:7700` |

Those are the main checkout's addresses. A git worktree (`make worktree`) runs
its own stack — compose project `meetingminer-<slug>` — on ports written to the
worktree's generated `.env.worktree` (read it there for the numbers); the api
and web ports are the same in every checkout.

`make up` backgrounds all three host processes with pidfiles and logs under
`.logs/`; it does **not** enable uvicorn's `--reload`, so code edits need a
restart. Run `make api`, `make worker`, or `make web` to hold a single process
in the foreground instead — `make api` is the target that adds `--reload`.
`make down` stops the host processes and the containers.

### Ingest your first meeting

Point MeetingMiner at a video or transcript you already have:

```bash
make mint-drop MINT_ARGS="'~/Downloads/standup.mp4' --corpus scripted --title 'Daily Standup'"
```

That mints a conforming write-once drop under `MM_DROPS_ROOT` and POSTs it to
the api; the worker picks the job up and the meeting appears in the app as it
processes. Full argument reference, refusal conditions, and the
transcript-only path: [`docs/README.md`](docs/README.md).

Do not hand-author a drop. The schema
([`docs/source-drop.schema.json`](docs/source-drop.schema.json)) is the
contract, not the procedure — a drop that gets the content-derived `sourceId`,
the `startedAt` precision pair, or the atomic finalize wrong is write-once and
unusable.

## Everyday commands

`make help` lists every target with its full notes. The root `Makefile` forwards
every target to [`infra/Makefile`](infra/Makefile), where the logic lives.

| Command | What it does |
|---|---|
| `make bootstrap` | check tools, create `.env`, install all three dependency sets, register the merge driver |
| `make up` / `make down` | start / stop the whole stack |
| `make api` / `make worker` / `make web` | run one process in the foreground |
| `make migrate` | apply pending migrations from `server/meetingminer/migrations/` — writes this checkout's dev database; in the main checkout that is the live one, so announce it |
| `make mint-drop MINT_ARGS='...'` | mint a drop from a local recording and/or transcript and POST it |
| `make ingest-drop DROP=<dir>` | ingest a drop finalized elsewhere and already copied under `MM_DROPS_ROOT` |
| `make rebuild` | regenerate the Neo4j + Meilisearch projections from Postgres + `config.yaml` |
| `make client` | regenerate `web/src/client/` from the live OpenAPI schema (needs the api up) |
| `make digest DIGEST_ARGS='--output /tmp/digest.txt'` | write one example Morning Digest email from every published artifact; the output path is required |
| `make backfill-drop-paths` | anchor pre-2.1a drop paths to `MM_DROPS_ROOT`; run once after `make migrate` |
| `make test` | the full gate — see [Testing and evaluation](#testing-and-evaluation) |
| `make evals-run` | one eval run against the ingested scripted corpus |
| `make test-db-prune` | drop leaked, unowned `meetingminer_test_*` databases, and tear down worktree stacks whose checkout is gone |
| `make worktree STORY=<slug>` | an isolated checkout, branch and private Docker stack for one piece of work (`worktree-list`; `worktree-remove` and `worktree-prune` tear the stack down with the checkout; `worktree-start STORY=<slug>` retries a start that failed, from the main checkout) |

Two targets still need care. `make rebuild` is single-flight per stack: it
takes the same endpoint-keyed file lock the projection tests take, queues on
whoever holds it, and then refuses by name — never run two rebuilds against one
stack at once. `make evals-run` takes **no** lock at all and holds the stores
and the api for its whole duration, so serialize it yourself.

## Repository layout

```
server/                  FastAPI api + worker (Python 3.12, uv)
  meetingminer/api/      route modules, auto-discovered by registry.py
  meetingminer/worker/   the job runner
  meetingminer/pipeline/ the eight ingestion stages and their pure cores
  meetingminer/domain/   the shared domain vocabulary, including STAGE_NAMES
  meetingminer/adapters/ ocr | stt | diarize | embed | llm ports and engines
  meetingminer/projections/  the only modules that write Neo4j and Meilisearch
  meetingminer/publish/  the per-moment approval and publish path
  meetingminer/digest/   the Morning Digest renderer behind `make digest`
  meetingminer/migrations/   numbered SQL migrations
  tests/                 the server suite
web/                     React 19 + TypeScript + Vite (pnpm)
  src/features/          home, search, chat, meetings, moments, participants,
                         replay, settings, status
  src/client/            generated from OpenAPI and committed on purpose, so a
                         fresh clone builds without a live api — never hand-edit
infra/                   docker-compose.yml and the Makefile every target reaches
evals/                   ground-truth manifests, checks, harness, designs, RUNBOOK
tools/puller/            Teams recap puller (npm, its own lockfile); source only,
                         its meeting archive lives outside this repo
docs/                    source-drop schema, bring-your-own-recording guide
_bmad/                   the scripts bootstrap executes
docs/                    architecture, project record, backlog, and reference
```

Regenerate `web/src/client/` with `make client` (which needs the api running),
never by hand. `tools/puller/` shares no server code and keeps its own npm
project and lockfile; read [`tools/puller/CLAUDE.md`](tools/puller/CLAUDE.md)
before changing it, because the scrape works the way it does for reasons that
file states. Only the tool source is tracked here — the archive it pulls into,
and the signed-in browser profile it needs, live outside this repo.

## Configuration

Two files, split by whether the value is a secret:

- **[`config.yaml`](config.yaml)** — every adapter binding. OCR engine
  (`apple-vision` | `tesseract`), speech recognition (`mlx-whisper` |
  `parakeet-mlx`) and its model id, diarizer, embedder model and dimension,
  per-role LLM models with their endpoints, fallbacks and timeouts, the two
  extraction prompt templates, ingestion sampling rates, and search tuning.
  Swapping an engine or a model is an edit to this file, never a code change.
- **`.env`** (gitignored; template in [`.env.example`](.env.example)) — the
  three storage roots, store passwords, and provider API keys. Read by both the
  Python loader and `docker compose --env-file`, so `.env.example` documents
  exactly which constructs mean the same thing to both.

Those two files are not the whole surface. Store host ports default in
[`infra/docker-compose.yml`](infra/docker-compose.yml) and are set per worktree
by its generated `.env.worktree` (`MM_STACK_NAME`, `MM_POSTGRES_PORT`,
`MM_NEO4J_HTTP_PORT`, `MM_NEO4J_BOLT_PORT`, `MM_MEILI_PORT` and the three
test-twin ports), which the Makefile, compose and the loader all read after
`.env` — the loader applies the three store ports to `config.yaml`'s endpoints,
so ports never live in the tracked file. The api and web ports are fixed in
`infra/Makefile`, and a few runtime and test overrides
(`MM_PROJECTION_LOCK_TIMEOUT_SECONDS`, `MM_PROJECTION_LOCK_KEY`,
`MM_REQUIRE_TEST_STORES`, `MM_TEST_NEO4J_URI`, `MM_TEST_MEILI_URL`, and
`MM_REQUIRE_DROP_SCHEMA` — which only the exact value `1` arms) are read from
the environment without appearing in `.env.example`. `MM_PULLER_ARCHIVE` names the puller's working archive for
`make puller-sync` and `make puller-archive-check`; it has no default because
the archive is per-machine.

Some committed defaults are specific to the machine this was built on. The
extraction role's `base_url` points at an Ollama host on the author's LAN
(`http://10.77.0.52:11434`) while the embedder resolves the shared
`providers.ollama` entry (`http://localhost:11434`); they are deliberately
separate, because the two models are served from different boxes. Point both at
whatever serves them for you before the first ingest.

## Models and cost

Extraction runs locally by default. Cited Q&A does not:

| Role | Model as committed | Cost | Fallback |
|---|---|---|---|
| `extraction` | `ollama/gpt-oss:120b` | local | `ollama/qwen3:30b` |
| `embedder` | `qwen3-embedding:0.6b` via Ollama | local | none — search degrades to `ranking: "keyword"` and says so |
| `chat` | `openai/gpt-5.2` | **paid** | none, by owner decision |
| `judge` | `openai/gpt-5.2` | **paid** | none |

Every chat turn and every LLM-judge eval run is a billed OpenAI call, so
`OPENAI_API_KEY` in `.env` is a prerequisite for asking the corpus anything.
`chat` has no fallback deliberately: a failing primary must surface as an error
the user sees rather than engage a substitute model silently.

**Restarting the worker can cost money.** A job paused at the `extract` stage
resumes on restart and issues real model calls for the whole backlog. Restart it
only when you intend that spend.

## Testing and evaluation

```bash
make test          # the full gate
make web-test      # vitest, no stores needed
make evals-test    # the harness's own suite, no stores and no api
make puller-test   # the puller's suite
```

There is no CI, so `make test` is the gate. It runs the three store-free suites
first — puller, web, evals — so a failure there shows up in seconds rather than
after Docker has started three containers, then brings the stores up before the
server suite so store-backed tests cannot pass vacuously by skipping, and
finishes by building the web app against the committed client.

To iterate on one Python test, stay inside the project environment:

```bash
uv run --project server pytest server/tests/test_x.py
```

Bare `pytest` runs outside it and will not resolve the dependencies.

Each git worktree has its own stores: `make worktree` provisions a private
compose stack (`meetingminer-<slug>`, its ports and its incarnation id
`MM_STACK_ID` in the worktree's generated `.env.worktree` — a validated
ownership record every reader refuses when it is incomplete, hand-edited or
copied from another worktree). Its `MM_STACK_NAME` and `MM_STACK_ID` cannot be
overridden from the process environment; a conflicting value is refused before
the stack starts, while port and endpoint overrides keep their normal
precedence. Suites in two worktrees therefore never contend.
Memory is the Docker VM's, not the host's: OrbStack's VM reports 23.5 GiB
against the 128 GB host, a stack idles at about 2 GiB, so a handful of
stacks fit and a dozen idle ones would fill the VM — `make down` in an idle
worktree frees its memory and keeps its volumes (AGENTS.md carries the full
measurement). Server suites take a per-run Postgres
database; two suites in one checkout queue on a bounded endpoint-keyed file
lock (a slow one is waiting, not hanging); `make test-db-prune` clears
databases a killed run left behind and tears down stacks whose worktree is
gone. Neo4j and Meilisearch have disposable test twins (`7475`/`7688` and
`7701` in the main checkout) so a suite's `drop_all` can never empty the corpus
you are demoing.

Beyond unit tests, [`evals/README.md`](evals/README.md) documents the harness
that measures the system against scripted meetings with YAML ground truth —
capture recall, doc-index recall@5, and the publish gate. It reaches the system
only through the public API and read-only store queries, a boundary enforced by
an AST walk rather than by convention. The operator procedure is
[`evals/RUNBOOK.md`](evals/RUNBOOK.md), and `make evals-run` writes an immutable
run folder under `evals/runs/`.

`make evals-run` fails today by design: both shipped ground-truth fixtures still
carry placeholder `source_id` values, so a run selects no subjects to measure.
Authoring a real manifest is what turns it green.

## Troubleshooting

**Something did not start.** `make up` verifies each process came up and prints
where it looked. Logs and pidfiles live in `.logs/` at the repo root:

```bash
tail -f .logs/api.log .logs/worker.log .logs/web.log
```

**The stores are not healthy.** `make up` refuses when the Docker daemon is
down (`make check-docker`) or `.env` is incomplete (`make check-env`). Start
Docker, then re-run `make up` — it is idempotent and skips processes already
running.

**Ingest is stuck at a stage.** Every job carries per-stage state, and the home
dashboard shows the pipeline per meeting with the failure detail for whichever
stage refused. Stage failures are named rather than silent: an `align` refusal
says what it could not align.

**Search returns nothing, or `ranking: "keyword"`.** The embedding host is
unreachable. Keyword-only results are still good results here — measured on this
corpus, BM25 alone was unbeaten on transcript-worded queries — but paraphrased
questions will do worse until Ollama is back.

**A store's contents look wrong.** `make rebuild` regenerates Neo4j and
Meilisearch from Postgres. Run it after an embedder swap, a chunking retune, a
wiped volume, or whenever a store's content is suspect. Routine ingestion needs
none of it — the worker projects as it goes.

## Documentation map

| Document | What it is |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | The technical contract: system shape, the seventeen architecture decisions stated by what each prevents, and the cross-cutting invariants. |
| [`docs/project-record.md`](docs/project-record.md) | What each epic delivered, what to know before changing it, and what was deliberately left undone. |
| [`docs/backlog.md`](docs/backlog.md) | Known, evidenced, undone work — every item found by a review, an incident, or a measurement. |
| [`AGENTS.md`](AGENTS.md) | Operating rules for every AI agent working this repository, regardless of tool. Read it before touching the tree. |
| [`project-context.md`](project-context.md) | The condensed version of those rules: policy, where things are, how to run and verify. |
| [`docs/README.md`](docs/README.md) | Bringing your own recording — the `mint-drop` procedure end to end. |
| [`docs/agent-kickoff-prompt.md`](docs/agent-kickoff-prompt.md) | The prompt used to start an agent on this repository, with its reviewer clauses. |
| [`evals/README.md`](evals/README.md) / [`evals/RUNBOOK.md`](evals/RUNBOOK.md) | The eval harness reference and the operator runbook; documented-only check designs live in [`evals/designs/`](evals/designs/). |

## Project status

MeetingMiner is a solo-developer capstone for the InfoQ AI Engineering program,
built against a real corpus of recorded meetings. All five epics — evidence
ingestion, the evidence UI, search and cited Q&A, extraction and publishing, and
the eval harness — are complete; per-story status lives in

It runs local-first and single-user with **no authentication**. Auth, enterprise
integration, Microsoft Graph, and outbound routing to live systems (GitHub,
Asana, Linear, SharePoint) are explicit non-goals for this build — publishing
targets a local folder and a local git repository.

The repository carries no `LICENSE` file, so no license is granted.
