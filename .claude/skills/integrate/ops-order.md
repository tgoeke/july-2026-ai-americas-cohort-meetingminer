# Post-merge operations — what is owed, and in what order

Decide by what the merge actually changed. Run what is owed, skip what is not,
and never reorder 1 before 2.

## The ordering that has already cost this project

**`make migrate` runs before the worker sees the new code.** Story 2.1a taught
this: restarting the worker onto post-migration code with the migration
unapplied failed 29 jobs for a missing `drop_relative_path`. It was
recoverable — the backfill re-queued them — but it turned a clean migration
into 29 failures.

Migrations `0009_artifacts.sql` (Epic 4 extraction) and
`0010_extraction_sources.sql` (story 4-1a) are on `main` and **already applied
to the shared dev database** — `0009` by story 2.3's implementing agent and
`0010` on 2026-08-20 at 4-1a's landing. So `make migrate` is not owed on that
environment; the only remaining trigger for the extraction backfill is a
deliberate worker restart. Verify rather than assume: a fresh clone or a
rebuilt store volume owes the migration again, and `make migrate` is
idempotent, so run it when unsure.

Note the trap in `make up`: it is `check-client infra-up migrate` **and then
`start-api start-worker start-web`**. `make up` starts the worker, so it falls
under the gate in `SKILL.md` even though its name sounds like environment
setup. Since 4-1a the extraction backfill it releases is local rather than
paid, but it is still hours of GPU on a queue the user chose to stop — get the
fresh yes.

## The table

| If the merge changed… | Run | Notes |
|---|---|---|
| anything under `server/meetingminer/migrations/` | `make migrate` | Always first. Prereqs `check-env`, `infra-up`. Idempotent — run it when unsure. |
| drop-path storage semantics | `make backfill-drop-paths` | After `migrate`, before any worker start. `BACKFILL_ARGS=--dry-run` reports without writing. Fails closed: an unplaceable row is named and exits non-zero, so a partial backfill cannot look clean. Already run for 2.1a on 2026-08-19 (29 jobs, 51 transcript paths, 8 recordings, 0 unplaceable). |
| a projected field, the Meilisearch index shape, or `config.yaml` embedder/chunking | `make rebuild` | Regenerates Neo4j + Meilisearch from Postgres. **Documents written before the change do not carry the new field** — the code is correct before the rebuild, the corpus simply is not re-indexed. Needs `ollama pull qwen3-embedding:0.6b`; without it use `ARGS='--structural-only'` and the corpus stays searchable. Scope with `ARGS='--meeting <uuid> --embed-only'`. |
| the API surface (a route, a response model) | `make client` | Regenerates the typed TS client from the **live** OpenAPI schema, so the api must be running. It refuses to generate from a foreign schema. Commit the regenerated `web/src/client` — a committed client that matches the api is the point of committing it. Expect it to pick up drift from earlier stories; that is the client catching up, not a bug. |
| nothing above | — | Routine ingestion needs none of this. The worker projects as it goes. |

## Independent of the merge

- `make test-db-prune` — only after a suite was killed with `SIGKILL` and could
  not drop its per-run database. Safe while another suite runs: it takes the
  same advisory lock and refuses any database with a live backend.
- `make worktree-prune` — removes every clean worktree already merged into
  `origin/main`. Phase 4, not here.
- `make check-reviews` — Phase 1 gate, not a post-merge op.

## Outstanding, currently gated

Re-read `sprint-notes.md` before repeating any of this — it is the live record
and this file is a snapshot.

- The worker is **stopped by user decision** (paid-ops rule; the Anthropic key
  was revoked after story 4.1's per-moment design burned 358 paid
  `claude-sonnet-5` calls over 5 meetings). The decision stands and still needs
  a fresh explicit yes — but as of 2026-08-22 neither of its two original
  reasons survives, so do not repeat them as if they did.
- **The queue is empty.** The `corpus-purge-to-samples` purge deleted the 32
  real meetings and, with them, their `job` rows: `select status, count(*) from
  job` returned exactly `done / 2` on 2026-08-22. The **27 jobs at `extract`**
  and the **two queued NDA ingests** this file used to list are gone. A worker
  start now drains nothing. Verify with the query rather than trusting this
  line — the next ingest changes it.
- **Paid calls are not reachable from the worker.** Story `4-1a` (landed
  2026-08-20) moved extraction to whole-transcript, and `config.yaml` binds
  `llm.roles.extraction` to local `ollama/gpt-oss:120b` with an
  `ollama/qwen3:30b` fallback. `chat` and `judge` are `openai/gpt-5.2` and are
  reached from the api, never the worker. Check `/status` for the live binding
  before asserting either way.
- `screenText` (story 3.1) is not re-indexed on already-ingested meetings until
  a `make rebuild` runs. The post-purge rebuild covered the two survivors.

## When a merge adds a `[project.scripts]` entry

Not in the table above because it is not a store operation, and it bit the
`corpus-purge-to-samples` landing. `server/pyproject.toml` registered a new
`prune` script; `make purge` guards on `$(VENV)/bin/prune` existing and failed
in the main clone until `uv sync --project server` reinstalled the package.
Every clone and worktree created before that merge owes the same sync. Check
with `ls server/.venv/bin/` against `[project.scripts]` whenever a merge
touches `server/pyproject.toml`.
