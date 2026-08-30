# Code review — Story 1.7: Evidence Projections & Rebuild CLI

Reviewed range: `4e705e37954b9b43057798727e1f2c59eae03eee..bebbcc7b7dd157407f4d534f8cfb1467ce1742b7` on `main`.

## High

### Scoped `--embed-only` accepts a stale chunk configuration

Location: `server/meetingminer/projections/__init__.py:353`, `:623`.

What is wrong: `rebuild --meeting <id> --embed-only` recalculates chunks using the current configuration but bypasses `projection_action()` and does not verify that the recorded structural state used the same chunk configuration.

Why it matters: after a chunking retune, this command replaces only Meilisearch documents and vectors. Neo4j retains the old Chunk/COVERS/SHOWN_DURING graph while `meeting_projection` still records the old chunk configuration. Search and graph retrieval then disagree for the same meeting.

What the fix must do: refuse an embedding-only pass unless its existing structural state matches the configured model, dimension, and chunking; require a full projection otherwise. Add a regression that proves a scoped embed-only run after a chunking retune writes neither store.

## Medium

### Speaker resolution is absent from the stored chunk representations

Location: `server/meetingminer/projections/search.py:108`, `server/meetingminer/projections/graph.py:215`.

What is wrong: the I/O matrix requires each chunk to carry its raw speaker label and `speakerResolution`, but projections retain only label lists and resolved participant ids.

Why it matters: downstream consumers cannot distinguish unresolved, ambiguous, and placeholder speakers after projection, despite speaker attribution being intentionally non-inferential.

What the fix must do: persist per-turn speaker-resolution information in both chunk representations and add coverage for unresolved/ambiguous/placeholder input.

### A vector-width refusal can mutate Neo4j schema first

Location: `server/meetingminer/projections/__init__.py:160`.

What is wrong: `_open_stores()` calls `ensure_graph_schema()` before `ensure_search_schema()` checks the existing Meilisearch dimension.

Why it matters: a mismatched vector width is required to fail before any write, yet the failed invocation can create Neo4j constraints/indexes.

What the fix must do: run all non-mutating mismatch preflights before modifying either store and test the fresh-Neo4j/mismatched-Meilisearch case.

### The installed rebuild command fails from the server project directory

Location: `server/meetingminer/projections/cli.py:159`.

What is wrong: `load_config()` resolves the default config and environment file relative to cwd; the specified `cd server && uv run rebuild --all` invocation therefore looks for `server/config.yaml` and exits.

Why it matters: the advertised CLI is unusable from its own project directory; only the Makefile wrapper succeeds by changing to the repository root.

What the fix must do: resolve repository configuration reliably while preserving explicit `MM_CONFIG_PATH` behavior, and cover an installed-script `--dry-run` launched from `server/`.

### Embedding tests do not prove vectors belong to their documents

Location: `server/tests/test_projections_search.py:274`.

What is wrong: tests assert only that chunk vectors are non-empty, not that moments and chunks received the vector computed from their own text.

Why it matters: a same-width vector reorder would keep structural checks green while silently corrupting semantic retrieval ranking.

What the fix must do: use the deterministic fake embedder to assert exact text-to-vector correspondence in both indexes.

## Low

### Configured embedding batching is untested

Location: `server/meetingminer/projections/__init__.py:300`.

What is wrong: no test lowers `embed_batch_size` below the document count and verifies the port call sizes.

Why it matters: a future regression that submits a whole large meeting at once can exceed provider request limits while the current suite stays green.

What the fix must do: add a small-batch test that verifies bounded calls and complete assignment.

### Cross-meeting participant survival after unprojection is untested

Location: `server/meetingminer/projections/graph.py:377`.

What is wrong: coverage checks a screen's survival after unprojection but not a shared participant's remaining traversal.

Why it matters: a later broadened delete can silently break person-based navigation for another meeting.

What the fix must do: add a two-meeting shared-participant unprojection regression.

## Triage notes

The review also reconfirmed seven previously recorded deferred items (live-store test isolation, freshness detection, same-width model swaps, artifact index configuration, ingest-versus-rebuild equivalence coverage, read visibility during replace, and graph scaling). Those are not reported as new findings. Sixteen additional layer reports were dismissed as false positives, intended constraints, or duplicate claims.
