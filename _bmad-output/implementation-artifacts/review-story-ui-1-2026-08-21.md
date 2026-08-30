# Review — story ui-1 (read-only reveal API)

- Reviewer branch: `story/ui-1-review`
- Reviewed branch: `story/ui-1`
- Commit range: `3ddb2eb..c0b33f6` (merge-base with main: `3ddb2eb`); commits `1fcc917`, `0c2e7a8`, `c0b33f6`
- Contract: `_bmad-output/specs/spec-ui-reimagine/SPEC.md` + companions, stories.yaml entry "1", `_bmad-output/implementation-artifacts/build-prompt-story-ui-1-2026-08-21.md`
- Date: 2026-08-21

## Review priorities

1. Secrets: GET /config must not serialize any secret under any config shape; allowlist is field-by-field; pin tests actually pin it.
2. Read-only claim: no mutation routes in the diff.
3. Correctness of counts (stats + roll-ups) against schema meaning; snapshot consistency.
4. Regenerated client is generator output only; baseUrl overridden in `web/src/lib/api.ts`.
5. Registry baseline and test quality.

## What was run

All from the review worktree `/Users/devopsterus/current/cohort/meetingminer-wt/ui-1-review` with `origin/story/ui-1` merged in, after `make bootstrap`. Neither the worker nor `make evals-run` was touched.

1. `server/.venv/bin/python -m pytest server/tests/test_api_config_view.py server/tests/test_api_stats.py server/tests/test_api_meetings.py server/tests/test_api_registry.py -q` — **33 passed** (3.61s; one pre-existing starlette deprecation warning).
2. Mutation check A (pin adversarial test): temporarily added an `api_key: str | None = None` field to `LlmRoleView` and populated it with None. `test_every_section_is_the_pinned_allowlist` **FAILED** as required (exact-set pin catches the added key even with a null value); reverted.
3. Mutation check B: temporarily concatenated `config.secrets.anthropic_api_key` into the serialized `service` field. `test_no_secret_material_serializes` **FAILED** as required (fake-secret value detected in response text); reverted. Working tree confirmed clean after both reverts.
4. `make web-test` — **13 files, 208 tests passed** (11.2s) against the regenerated client.
5. Static verification: mutation-route grep over the full diff (only two `@router.get` decorators added); schema reads of migrations 0002/0003/0009 for meeting_media cardinality, screenshot.view_type constraints, and artifact state lifecycle.

## Findings

### 1. Secrets — verified, no leak path found

- `server/meetingminer/api/config_view.py` reads only `config.settings`, never `config.secrets`. Structurally, secrets cannot reach the response: `Secrets` (config.py:661) is a sibling of `Settings` on `AppConfig`, holding `anthropic_api_key`, `openai_api_key`, `openrouter_api_key`, `postgres_password`, `neo4j_password`, `meili_master_key` — all sourced from `.env` only. No `Settings` sub-model carries a secret-shaped field: `PostgresStore` is host/port/database/user (no password column even exists in the model), `Neo4jStore` is uri/user, `MeilisearchStore` is url only, `LlmRoleBinding` is model/fallback/base_url/fallback_base_url/timeout_seconds/num_ctx, `ProviderEndpoint` is base_url only.
- The projection is field-by-field: every response model (`LlmRoleView`, `ScreensView`, `PostgresView`, ...) declares its own fields and is populated by naming each source field. No `model_dump`, no `**` splat of a Settings sub-model anywhere in the module.
- Pin quality (`server/tests/test_api_config_view.py`): `test_no_secret_material_serializes` installs a config whose six secrets are known fake strings and asserts neither the value nor its first 12 chars appears in `response.text`. `test_every_section_is_the_pinned_allowlist` asserts **exact set equality** (`set(body) == PINNED`) at every nesting level — response root, each role, embedder/stt/ocr/diarizer, all four pipeline sections, projections, both index views, api knobs, and all three store views. Adversarial check: adding an `api_key` passthrough to `LlmRoleView` (or swapping any section to a wholesale dump) changes the serialized key set and fails the set-equality assertion. A future `Settings` field does NOT appear by default (explicit view models), and if someone made it appear the pin would fail. Verdict: the pin does what the contract demands.
- Residual (non-blocking, inherent to the contract): `base_url` / `providers.*.base_url` / `neo4j.uri` / `meilisearch.url` are config.yaml values and serialize by design; a user who embeds credentials in a URL in config.yaml would expose them. That is a config-authoring hazard, not a `.env`/Secrets leak, and the spec explicitly puts store coordinates on the page (Open Questions acknowledges the trade-off).

### 2. Read-only — verified

The diff adds exactly two route decorators, both `@router.get` (`/config` in config_view.py, `/corpus/stats` in stats.py); meetings.py extends the existing GET `/meetings` payload. No POST/PUT/PATCH/DELETE anywhere in the range; nothing writes `config.yaml`; stats.py and meetings.py execute only SELECTs.

### 3. Counts — correct against the schema

- `publishedDocuments` = `count(*) FROM artifact WHERE state = 'published'` — matches migration 0009's one-way lifecycle where `published` is the publish-gate terminal state, i.e. exactly the rows that read as knowledge. Matches CAP-1's "published documents".
- Duration: `COALESCE(mm.duration_ms, ts.max_end_ms, 0)` summed per meeting. `meeting_media` is PRIMARY KEY (meeting_id) — at most one row per meeting, so no join fan-out and no double count. Transcript-only meetings count their last segment end rather than a fabricated zero; same rule in both /corpus/stats and the per-meeting roll-up.
- Poster: `ORDER BY (ps.view_type = 'participant-gallery') ASC, ps.ordinal ASC LIMIT 1`. `screenshot.view_type` is NOT NULL with CHECK in ('slide','ui-screen','participant-gallery') (migration 0003), so the boolean sort has no NULL hazard; non-gallery captures win, gallery only as fallback — as the contract asks.
- Per-meeting roll-ups ride the same statement as the stage rows (scalar subqueries + one LATERAL), so a card's counts share the stage snapshot. `meeting_participant` for per-meeting count vs. `participant` for the corpus count is the right pair (cross-meeting identity).
- Minor (non-blocking): stats.py's comment says "One statement, therefore one snapshot", which is true for the eight headline counts, but `by_kind`/`by_state` are two further statements on the same connection. psycopg's default is one transaction per `connection()` block but READ COMMITTED, so each statement takes its own snapshot: `artifacts.total` could in principle disagree with `sum(byKind)` if an extract commit lands between them. Vanishingly unlikely to matter for a dashboard; noted for accuracy of the comment, not as a defect to fix tonight.

### 4. Regenerated client — generator output, baseUrl overridden

- All changes under `web/src/client/` are consistent with `@hey-api/openapi-ts` output: the auto-generated headers stand, additions are the new `getConfiguration`/`getCorpusStats` operations plus `getSystemStatus` and status types (the system-status story had not regenerated the client, so they legitimately ride this one regen), and every added type line is generator-shaped. No hand-edit indicators found.
- `client.gen.ts` now bakes `baseUrl: 'http://localhost:8000'` into `createConfig` (generator behavior for the live-URL input in `web/openapi-ts.config.ts`). `web/src/lib/api.ts:12` runs `client.setConfig({ baseUrl: API_BASE })` at module load with `API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'` — the override the builder noted is real, so the baked default is inert whenever `VITE_API_BASE` is set.

### 5. Registry baseline and test quality

- `test_api_registry.py`: baseline gains `config_view` (before `extraction`, name-sorted among default-order modules) and `stats` (between `participants` and `status`), each with the required no-parameterized-sibling justification comment. `/config` and `/corpus/stats` indeed have no parameterized siblings; ordering carries no matching hazard.
- Test quality: stats tests pin the empty-corpus zero shape exactly, then assert every count against self-seeded rows including the shared-participant identity case (2 people across 2 meetings, not 4) and the duration COALESCE both ways. Meetings roll-up tests cover the no-evidence card (nulls not fabricated zeros), seeded counts, probed-duration preference, and gallery-vs-slide poster preference. Field-set pins on the meetings item were extended to the seven new camelCase fields.

## Verdict

**pass-with-findings** (both findings non-blocking; no remediation required before integration)

1. (informational) stats.py's "one snapshot" comment overstates slightly: `byKind`/`byState` are separate statements under READ COMMITTED, so `artifacts.total` vs `sum(byKind)` is not strictly one snapshot. Harmless for a dashboard; fix the comment or fold the GROUP BYs into the single statement whenever the file is next touched.
2. (informational, inherent to spec) config.yaml-authored URLs (`base_url`, provider endpoints, `neo4j.uri`, `meilisearch.url`) serialize by design; credentials embedded in such a URL by a config author would appear. Not a `.env`/Secrets leak — nothing reads `config.secrets` — and the spec's Open Questions already owns the store-coordinates trade-off.

Do-not-merge note honored: merging is the integrator's step; this review only reports.
