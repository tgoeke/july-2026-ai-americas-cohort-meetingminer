---
title: 'Story 3.1 — Corpus Search'
type: 'feature'
created: '2026-08-20'
status: 'done'
baseline_revision: '1ee383dada16ce6e96b6f62a333cf59ac23ed145'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-3-context.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md'
warnings: ['oversized']
deferred:
  - summary: >-
      A search result does not link into meeting drill-down; the meeting title
      renders as plain text because the destination view does not exist yet.
    evidence: |-
      Story 3.1 AC2 requires each result to "link into meeting drill-down with
      the matched terms highlighted", and AC3's path ends in a transcript view.
      That view is story 2.3's named deliverable ("transcript mentions are
      highlighted and each transcript region links to its moment") and story
      2.2 owns the moment view; both are `backlog`. The hit already carries
      `momentId` and `meetingId`, so the link is buildable the moment 2.3
      lands. Closing it here would duplicate 2.3 and collide with its files.
    location: >-
      web/src/features/search/CorpusSearch.tsx
    severity: medium
  - summary: >-
      FR12's "results from both retrieval stores" is unmet — search reads
      Meilisearch only, and the change set does not record the open clause.
    evidence: |-
      `SEARCHABLE_INDEXES = (MOMENTS_INDEX,)`. Neo4j retrieval is story 3.2's
      traversal templates. The diff documents its Epic 2 boundary explicitly
      but says nothing about the Neo4j half of FR12.
    location: >-
      server/meetingminer/projections/query.py
    severity: medium
  - summary: >-
      screenText is indexed for BM25 but never embedded, so a paraphrase of
      on-screen content can never reach the vector lane.
    evidence: |-
      `projections/__init__.py` embeds `[doc["text"] for doc in
      moment_documents]`, so the OCR text added to the document contributes to
      keyword matching only. AC1's OCR requirement passes on the keyword lane
      alone and would keep passing if the semantic half were removed. Changing
      what is embedded forces a full re-projection.
    location: >-
      server/meetingminer/projections/__init__.py
    severity: medium
  - summary: >-
      The semantic floor and the stale-hit drop both run after Meilisearch has
      paged, so a page can come back shorter than `limit` while more
      qualifying matches exist further down the ranking.
    evidence: |-
      Offset-based paging over a floored result set can skip results, and a
      caller cannot distinguish a short page from the last page. Fixing it
      means over-fetching and trimming, which is a retrieval-design change
      rather than a local repair.
    location: >-
      server/meetingminer/projections/query.py
    severity: medium
  - summary: >-
      apply_semantic_floor assumes Meilisearch returns keyword hits first and
      the last `semanticHitCount` entries are the vector lane; that ordering is
      asserted only against a hand-built list, never against the real store.
    evidence: |-
      A Meilisearch version that interleaves the lanes would silently start
      filtering keyword hits — the outcome the design says must never happen.
      The split also has no documented meaning on an `offset > 0` page.
    location: >-
      server/meetingminer/projections/query.py
    severity: medium
  - summary: >-
      api.search.semantic_score_floor is calibrated to one embedding model with
      nothing connecting the two settings.
    evidence: |-
      The 0.75 default was measured with `qwen3-embedding:0.6b` over five
      seeded moments (paraphrase 0.783, unrelated real query 0.734, nonsense
      0.701). Changing `embedder.model` silently invalidates it in either
      direction, and no validator, bind-time warning, or cross-reference from
      the embedder block exists. The measured gap is narrow enough that a
      legitimate paraphrase scoring 0.70-0.75 is dropped today.
    location: >-
      config.yaml
    severity: medium
  - summary: >-
      meetingId and corpus scope filters are enforced only by the Meilisearch
      filter expression, never re-verified against Postgres, though every
      citation field is.
    evidence: |-
      A stale document whose meeting has since changed corpus would leak into
      a `corpus=scripted` result set. `_resolve` re-reads `corpus` from
      Postgres and returns it but never compares it to what the caller asked
      for — the same class of staleness `search.stale_hit` exists to catch.
    location: >-
      server/meetingminer/api/search.py
    severity: medium
  - summary: >-
      Every search writes the user's raw query string to stdout, untruncated,
      on every request.
    evidence: |-
      `search.completed` and `search.index_missing` log `query=q`, and the
      debounced UI turns each typing burst into log lines. No decision about
      logging what people search their meeting corpus for is recorded
      anywhere in the story or the architecture.
    location: >-
      server/meetingminer/api/search.py
    severity: medium
  - summary: >-
      No server-side request budget: the embedder allows 120s and the search
      client 30s while the browser gives up at 8s.
    evidence: |-
      A slow model host occupies a threadpool worker for two minutes per
      abandoned search, one per debounced keystroke burst, with no concurrency
      cap. `meili_client` also adds a `/health` round trip before every query,
      on top of the search and the Postgres re-read.
    location: >-
      server/meetingminer/api/search.py
    severity: medium
  - summary: >-
      offset is unbounded, so a value past Meilisearch's maxTotalHits (default
      1000) returns an empty page indistinguishable from "nothing matched".
    evidence: |-
      `Query(ge=0)` only; there is no `max_offset` beside `max_limit`. This is
      the silent zero the rest of the module works to avoid.
    location: >-
      server/meetingminer/api/search.py
    severity: low
  - summary: >-
      screenText enters the index with no length cap and can become the
      visible snippet as recognition noise.
    evidence: |-
      `moment_documents` writes `screenshot.ocr_text` whole. A dense screen's
      OCR output both bloats the document and can surface through the snippet
      fallback as 40 words of noise.
    location: >-
      server/meetingminer/projections/search.py
    severity: low
  - summary: >-
      Building the embedder at api import means a config with no serving
      provider takes /health, /meetings, /media and the job stream down with
      it — wider than /search needs, given /search degrades when the host is
      merely unreachable.
    evidence: |-
      Kept at import deliberately: it matches the `require_drops_root` house
      pattern, and moving it into `lifespan` would break the `search_client`
      fixture, which reads `app.state.embedder` without running lifespan.
      Recorded rather than traded for an untested gate.
    location: >-
      server/meetingminer/api/main.py
    severity: low
  - summary: >-
      The floor's calibration paragraph is duplicated across six files and
      already disagrees in detail, with no single location named as the one
      Epic 5's retrieval eval should update.
    evidence: |-
      The same measurement appears in config.yaml, config.py, query.py's
      module docstring, apply_semantic_floor, the spec change log and
      sprint-notes; "0.1496" vs "as low as 0.15" and "Meilisearch 1.53" vs
      "1.53.1" already differ between copies.
    severity: low
  - summary: >-
      OCR text is not searchable on already-projected meetings until a
      corpus-wide rebuild runs.
    evidence: |-
      Adding `screenText` changed both the document shape and the index
      settings, so meetings projected before this story carry no OCR text.
      `make rebuild` is a corpus-wide operation on the shared stores and was
      deliberately not run from a story branch.
    severity: medium
---

<intent-contract>

## Intent

**Problem:** The evidence bundle is projected into Meilisearch but nothing can query it — `server/meetingminer/projections/search.py` has write functions only, there is no `/search` route, and the web app has no search surface. A user cannot locate the meetings and moments where something was discussed (FR12, UX-DR3, UX-DR4), and Epic 5's check 2.10 (planted-phrase recall@5 through the public API) has nothing to call.

**Approach:** Add a query side to the projection module, expose it as `GET /search`, and give the web app a corpus-search view. Meilisearch ranks; Postgres cites — the index returns ordered moment ids plus highlighted snippets, and every returned citation field is re-read from the database of record so a hit is authoritative rather than as-indexed (AD-2, AD-6). Ranking is hybrid keyword+vector via the `Embedder` port's `embed_query`, degrading to keyword-only, announced in the response, when the model host is down.

## Boundaries & Constraints

**Always:**
- No `meilisearch`/`neo4j` import outside `server/meetingminer/projections/` — `tests/test_projections_single_writer.py::test_the_api_package_never_reaches_a_store` asserts it by AST walk. The route calls a function in `projections/`, never a client directly.
- Every hit exposes a `momentId` that resolves in Postgres (AD-6, AD-15). A hit whose moment row is gone is dropped and logged as a named event — never silently returned and never silently swallowed ("no silent zero", SPEC Constraints).
- Search reads an explicit index allow-list containing `MOMENTS_INDEX` only. `publish_gate.ARTIFACTS_INDEX` is never queried, so no unpublished artifact can surface (NFR7, AD-4).
- Every retrieval knob is `config.yaml`, never a Python constant (AD-10). Query-time knobs go in a new `api.search` block; they are not index settings and must not enter `SearchIndexConfig`.
- Vectors come from the `Embedder` port (AD-8). The Meilisearch embedder is `userProvided`, so the store cannot embed the query — the caller must pass the vector.
- API errors are RFC 9457 via `api/problems.Problem`; response models use `alias_generator=to_camel` (spine Consistency Conventions).
- The web app renders highlights from structured data, never from markup on the wire — no `dangerouslySetInnerHTML` (the AD-15 principle: consumers render from the array, they do not parse).

**Block If:**
- Meilisearch 1.53's hybrid search rejects a `userProvided` embedder with a caller-supplied `vector`, making hybrid ranking unreachable without a store-native embedder (which AD-4 forbids).
- Adding `screenText` to `moments.searchable_attributes` is refused by `SearchIndexConfig`'s validator or by the store.

**Never:**
- Do not build the meeting drill-down transcript page or the moment view — stories 2.3 and 2.2 own those (see Design Notes).
- Do not touch `pull_transcript/` or `docs/` — story 2.1b is in flight there.
- Do not introduce a web router or a new npm dependency; compose into `App.tsx` as the codebase does today.
- Do not query the `chunks` index from `/search`; chunk-granularity retrieval is story 3.3's synthesis leg.
- Do not run `make evals-run` (still serial, AGENTS.md).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| Keyword hit | `GET /search?q=purchase order`, meeting projected, embedder up | 200; hits ordered by Meilisearch; each carries `momentId`/`meetingId`/`startMs`/`endMs`/`meetingTitle` from Postgres and `snippet` as `[{text, highlighted}]` runs; `ranking: "hybrid"` | No error expected |
| Typo tolerance | `q=purchse order` | Same moment still returned (`typo` ranking rule) | No error expected |
| Embedder host down | `EmbedderUnavailableError` from `embed_query` | 200, keyword-only results, `ranking: "keyword"`, `search.degraded` logged | Degrade, never fail — BM25 carries the dominant query shape (`retrieval-prior-art.md` §7 finding 1) |
| Embedder misconfigured | `EmbedderError` (wrong width / unparseable) | 503 problem `embedder-unusable` naming model and dimension | No silent fallback: a config error must not masquerade as a degraded search |
| Meilisearch down | `StoreUnavailableError` | 503 problem `search-store-unavailable` | Named refusal, no partial result |
| Blank / whitespace query | `q=` or `q=%20` | 422 problem `invalid-request` | FastAPI validation → existing handler |
| `limit` above `max_limit` | `limit=5000` | 422 problem `invalid-request` | Bounded by config, not clamped silently |
| Meeting scope | `meetingId=<uuid>` | Only that meeting's moments | Unknown id → 200 with zero hits (a filter, not a lookup) |
| Corpus scope | `corpus=scripted` | Only scripted-corpus moments; `real` excluded | Value outside `scripted`/`real` → 422 |
| Stale index document | Index holds a moment Postgres no longer has | That hit is omitted; `search.stale_hit` logged with the id | Remaining hits still return |
| Unpublished artifact in store | An `artifacts` index document with `state: extracted` exists | Never appears — `/search` reads the moments index only | No error expected |
| No matches | `q=zzzzzzzz` | 200, `hits: []`, `estimatedTotal: 0` | Empty is a valid answer, distinct from an error |

</intent-contract>

## Code Map

- `server/meetingminer/projections/search.py:57` `moment_documents` -- the citation-shaped document builder; add `screenText`. Only write functions exist today; no query function.
- `server/meetingminer/projections/stores.py:30` `MOMENTS_INDEX`/`CHUNKS_INDEX`, `:41` `EMBEDDER_NAME = "default"` (`userProvided`), `:96` `meili_client(config)` (health-checks, raises `StoreUnavailableError`).
- `server/meetingminer/projections/publish_gate.py:36` `ARTIFACTS_INDEX` -- the index the allow-list must exclude.
- `server/meetingminer/projections/evidence.py:38` `ScreenshotRow`, `:238` the screenshot SELECT -- add `representative_frame_id → frame_ocr.text` join. `frame_ocr.text` is defined at `server/meetingminer/migrations/0003_screens_screenshots.sql:17`; `screenshot.representative_frame_id` at `:75`.
- `server/meetingminer/adapters/embed/port.py` `Embedder.embed_query`, `EmbedderError`, `EmbedderUnavailableError` -- the seam this story is the first caller of.
- `server/meetingminer/adapters/embed/__init__.py` `build_embedder(config, log)` -- constructing it contacts no host, so it is safe at API startup; only the first call can fail.
- `server/meetingminer/config.py:360` `SearchIndexConfig` (+`:379` validator: `meetingId`/`corpus` filterable, `text` searchable), `:417` `SearchConfig`, `:458` `ApiConfig` -- add `SearchQueryConfig` here. `_StrictModel` rejects unknown keys, so config.yaml and the model must move together.
- `config.yaml:232` `projections.search.moments` -- `searchable_attributes` order **is** the field boost.
- `server/meetingminer/api/jobs.py:67` -- the read-only route template (`operation_id`, `responses={404: ProblemDetails}`, sync `def`, `request.app.state.pool`).
- `server/meetingminer/api/meetings.py:95` `listMeetings` + `MeetingsResponse` -- the list-shaped precedent for `SearchResponse`.
- `server/meetingminer/api/problems.py:52` `Problem(status, slug, detail, title=None, **extensions)`; `:32` `ProblemDetails`.
- `server/meetingminer/api/main.py:107-118` -- router registration order is load-bearing; `app.state.config` set at `:97`.
- `server/tests/conftest.py:243` `client` (TestClient, pool injected, lifespan **not** run), `:912` `projection_stores` (the only fixture taking the cross-process lock; yields `(driver, meili_client)`), `:748` `fake_embedder`, `:789` `stores_reachable`. Store-backed tests declare `projection_stores`; there is no marker.
- `server/tests/projection_seed.py:75` `seed_meeting(conn, *, source_id, has_recording, title, corpus, turns, ...)`; `:33` `SeededTurn`; `:42` `DEFAULT_TURNS` (known text incl. "SFTP", "purchase order").
- `server/tests/test_projections_search.py:53` `project()` helper, `:62` `settings_of`, `:178` the settings-match-config assertion that will pick up `screenText` automatically.
- `web/src/features/meetings/MeetingsList.tsx` -- component house style: generated SDK only, `AbortController` ref + `setTimeout` expiry + `AbortSignal.any`, post-await `if (controller.signal.aborted) return`, `rows: T[] | null` (null=loading, []=empty), error as a non-blocking `role="alert"` banner naming `API_BASE`, `data-testid` on everything asserted.
- `web/src/features/meetings/rows.ts` -- precedent for pure display helpers unit-tested separately.
- `web/src/features/replay/ReplayPlayer.tsx:4` `ReplayPlayerProps { meetingId, startMs, label?, className? }` -- reuse verbatim for inline replay; re-seek by re-rendering with a new `startMs`, never remounting.
- `web/src/App.tsx:86` -- single `<main>`, **no router**; `web/src/App.test.tsx` asserts the composition and mocks `@/client/sdk.gen` with a factory listing every export.
- `web/openapi-ts.config.ts` -- client generated from a live api; `web/src/client/*.gen.ts` are committed on purpose. Store-free regeneration is verified working: dump `app.openapi()` to a file, then `pnpm --dir web run client -i <file>`.
- Read-only evidence: `server/tests/test_projections_single_writer.py:101` forbids store clients in `meetingminer/api/**`. `server/tests/conftest.py:754` `_no_incidental_projection` is autouse — `/search` tests must not rely on the projection trigger.

## Tasks & Acceptance

**Execution:**
- `server/meetingminer/config.py` -- add `SearchQueryConfig` (`default_limit`, `max_limit`, `semantic_ratio` 0.0–1.0, `crop_length`, all bounded) and a `search: SearchQueryConfig` field on `ApiConfig` -- query knobs are configuration, not code constants (AD-10), and they are not index settings.
- `config.yaml` -- add the `api.search` block; append `screenText` to `projections.search.moments.searchable_attributes` after `text` -- AC1 requires the full-text index to span OCR text, and list order is the field boost.
- `server/meetingminer/projections/evidence.py` -- add `ocr_text: str | None` to `ScreenshotRow` and LEFT JOIN `frame_ocr` on `screenshot.representative_frame_id` -- OCR text has to reach the projection before it can be indexed.
- `server/meetingminer/projections/search.py` -- write `screenText` into each moment document from the moment's screenshot -- transcript-only moments carry `None`, which is not an error.
- `server/meetingminer/projections/query.py` (new) -- `SEARCHABLE_INDEXES = (MOMENTS_INDEX,)`, a `search_moments(client, config, *, query, limit, offset, meeting_id, corpus, query_vector)` returning ordered `(moment_id, snippet_runs, score)` plus `estimated_total`, the hybrid/highlight/crop parameter construction, and the `_formatted` → runs parser using U+E000/U+E001 sentinels -- keeps every store call inside `projections/` (AD-4) and makes the wire format structured rather than markup.
- `server/meetingminer/api/search.py` (new) -- `GET /search` (`operation_id="searchCorpus"`): validate params, embed the query through the port with the degrade/refuse split, call `search_moments`, resolve the returned ids against Postgres for `meetingId`/`meetingTitle`/`startMs`/`endMs`/`screenshotId`/`sourceDeepLink`, drop and log unresolvable hits, return camelCase `SearchResponse` -- Meilisearch ranks, Postgres cites (AD-2, AD-6).
- `server/meetingminer/api/main.py` -- build the embedder once at startup onto `app.state` and include the search router before `media` -- fail fast on a config error; the media catch-all must stay last.
- `server/tests/test_projections_query.py` (new) -- store-free unit tests for the highlight parser (adjacent runs, unmatched sentinel treated as literal text, sentinel already present in source text, empty `_formatted`) and for the built query parameters (hybrid present with a vector, absent without one; allow-list excludes `ARTIFACTS_INDEX`) -- this is the I/O-matrix edge-case task.
- `server/tests/test_api_search.py` (new) -- store-backed tests over `client` + `projection_stores` + `fake_embedder` + `projection_seed`: keyword hit, typo tolerance, meeting and corpus scoping, degraded ranking when the embedder raises `EmbedderUnavailableError`, 503 on `EmbedderError`, 422 cases, stale-hit omission, an `artifacts`-index document never surfacing, and the `/search` operationId in the OpenAPI schema -- name the Meilisearch client `meili`, never `client` (the TestClient fixture owns that name).
- `web/src/features/search/hits.ts` (new) + `web/src/features/search/CorpusSearch.tsx` (new) -- the search view: debounced query input, `rows: Hit[] | null` loading/empty/error states, snippet runs rendered as `<mark>` from data, per-hit meeting title and timestamp, an inline replay toggle mounting `ReplayPlayer` for hits with a recording and a `sourceDeepLink` anchor for those without.
- `web/src/features/search/CorpusSearch.test.tsx` (new) -- loading → results → empty → error-banner states, highlight rendering, degraded-ranking notice, inline replay toggle.
- `web/src/App.tsx` + `web/src/App.test.tsx` -- mount `CorpusSearch` above `MeetingsList`; extend the sdk mock factory with `searchCorpus`.
- `web/src/client/*.gen.ts` -- regenerate and commit -- a committed client is what lets a fresh clone build without a live api.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` + `sprint-notes.md` -- move `3-1-corpus-search` to `review` and record what landed.

**Acceptance Criteria:**
- Given a projected meeting whose moments carry transcript text and whose screenshots carry OCR text, when `GET /search?q=<term>` is called for a term appearing only in the OCR text, then the containing moment is returned — proving the index spans transcripts *and* OCR text (AC1).
- Given the embedder is reachable, when a search runs, then the Meilisearch request carries both a `hybrid` block naming the `default` embedder and a caller-supplied `vector`, and the response reports `ranking: "hybrid"` (AC1).
- Given any returned hit, when the response is built, then its `momentId` was read back from Postgres in the same request and its `startMs`/`endMs`/`meetingId` come from that row rather than from the index document (AC2, AD-6/AD-15).
- Given a hit on a meeting with a recording, when the web view renders it, then an inline replay opens at that hit's `startMs`; given a transcript-only meeting, then the `sourceDeepLink` is offered in its place (AC3 as far as story 3.1 owns it — UX-DR3's transcript drill-down leg is story 2.3).
- Given a document in an `artifacts` index in any state, when any search runs, then it never appears, because the searched-index allow-list contains the moments index alone (AC4 / NFR7).
- Given `make web-test` and the server suite, when run on this branch, then every new test passes and no existing test regresses — including `test_projections_single_writer.py` and `test_index_settings_match_config_and_no_auto_embedder_is_registered`.

### Review Findings

- [x] [Review][Patch] Re-derive the semantic-score floor [server/meetingminer/projections/query.py:376] — resolved by independently retrieving and deterministically blending keyword and semantic lanes; the floor now sees semantic-only results.

- [x] [Review][Patch] Skip embedding for pure keyword configuration [server/meetingminer/api/search.py:180] — resolved and covered with a down embedder at `semantic_ratio: 0.0`.
- [x] [Review][Patch] Bind snippet attributes to the moments index configuration [server/meetingminer/config.py:417] — resolved with a moments-only configuration invariant and loader coverage.
- [x] [Review][Patch] Normalize malformed query responses to the named 503 [server/meetingminer/projections/query.py:330] — resolved with shape/count/score validation that raises `ProjectionError`.
- [x] [Review][Patch] Do not expose raw indexed documents in problem details [server/meetingminer/projections/query.py:468] — resolved; missing-id messages no longer include the document representation.
- [x] [Review][Patch] Cover query-time store loss [server/tests/test_api_search.py:734] — resolved with a client whose query fails after construction.
- [x] [Review][Patch] Cover the default-limit configuration invariant [server/tests/test_config.py:75] — resolved with an inverted configuration loader test.

- [x] [Review][Decision] Define trusted source-deep-link origins — resolved: source-drop provenance is trusted; any absolute `http:` or `https:` URL may be rendered as “Open in Stream”. Scheme filtering remains mandatory to prevent executable and local URL schemes.
- [x] [Review][Patch] Abort and announce a superseded debounced search [web/src/features/search/CorpusSearch.tsx:143] — resolved with immediate cancellation and `aria-busy` before the next debounce interval; regression coverage resolves the old request inside that interval.
- [x] [Review][Patch] Reject a response that arrives after the client timeout [web/src/features/search/CorpusSearch.tsx:89] — resolved with an expiry-signal guard after the await; a late successful response now preserves the timeout diagnosis.
- [x] [Review][Patch] Mark stale results only when results are retained [web/src/features/search/CorpusSearch.tsx:207] — resolved; the stale-results sentence renders only with nonempty retained rows.
- [x] [Review][Patch] Make unknown error descriptions total [web/src/features/search/CorpusSearch.tsx:18] — resolved with a guarded serialization fallback and circular-payload coverage.
- [x] [Review][Patch] Verify replay seeks to the cited start offset [web/src/features/search/CorpusSearch.test.tsx:347] — resolved by dispatching `loadedmetadata` and asserting `currentTime === 44` in the search-level replay test.
- [x] [Review][Patch] Name the configured API in problem-response banners [web/src/features/search/CorpusSearch.tsx:207] — resolved; RFC 9457 banners now identify `API_BASE` as well.

## Spec Change Log

### 2026-08-20 — a fifth query knob: `api.search.semantic_score_floor`

**What the contract said.** The I/O matrix requires `q=zzzzzzzz` to answer 200
with `hits: []` and `estimatedTotal: 0` ("Empty is a valid answer, distinct
from an error"), *and* requires typo tolerance. `SearchQueryConfig` was
specified with four knobs: `default_limit`, `max_limit`, `semantic_ratio`,
`crop_length`.

**What the store does.** Measured against Meilisearch 1.53.1 during
implementation: with any `semanticRatio > 0` and a caller-supplied vector, the
vector lane ranks by similarity and has no notion of "no match" — a nonsense
query comes back with the k nearest moments. Both matrix rows cannot hold at
once without intervention.

**Why Meilisearch's own threshold does not serve.** `rankingScoreThreshold`
applies to both lanes, and the two do not share a scale. Measured on this
index: a typo-tolerant keyword hit scored 0.1496, a semantic hit on unrelated
text scored ~0.65. One number either keeps the noise or deletes the typo
tolerance the AC requires.

**Resolution.** A fifth knob, `api.search.semantic_score_floor`, applied to the
semantic lane alone by `projections.query.apply_semantic_floor`. The endpoint
retrieves keyword and pure-semantic lanes separately, floors only the latter,
then deterministically blends the ordered lanes by `semantic_ratio`; an id that
also appears in the keyword lane remains keyword evidence. This avoids treating
Meilisearch's exhaustive `semanticHitCount` as a page-local lane marker.
Default 0.75, measured on the seeded corpus with
`qwen3-embedding:0.6b` — a paraphrase query scored 0.783 against the moment
that answers it, nonsense queries topped out at 0.701, an unrelated real query
0.734. *Assumption to attack: that gap is narrow and was measured over five
moments; like `semantic_ratio`, this is a config knob precisely so Epic 5's
retrieval eval can settle it.*

### 2026-08-20 — Block If conditions, both cleared

Probed against the live stores before implementation:

- **Hybrid with a `userProvided` embedder.** Meilisearch 1.53.1 accepts a
  `hybrid` block naming a `userProvided` embedder together with a
  caller-supplied `vector`, and blends the lanes. Hybrid ranking is reachable
  without a store-native embedder.
- **`screenText` in `moments.searchable_attributes`.** Accepted by
  `SearchIndexConfig`'s validator (which requires `text` and constrains
  nothing else) and by the store. Documents that omit the field index and
  return normally.

### 2026-08-20 — files touched beyond the Execution list

- `server/tests/test_config.py` — `VALID_CONFIG` had to gain the `api.search`
  block, because `_StrictModel` makes the model and the file move together.
- `web/src/client/{index,sdk,types}.gen.ts` — regenerating for `searchCorpus`
  also added `getRecording` and `getMediaFile`, which the committed client had
  been missing since story 2.1. Regeneration produces the whole sdk.
- `_bmad-output/implementation-artifacts/sprint-notes.md` gained an Epic 3
  section; it had none.

### 2026-08-20 — `test_api_search.py` embeds with a local `SpreadEmbedder`

The Execution list names `conftest.fake_embedder` as the embedder the
store-backed search tests use. They use a `SpreadEmbedder` defined in
`test_api_search.py` instead. `conftest.FakeEmbedder` derives every component
of a vector from one hash seed plus the component index, which makes any two
of its vectors nearly parallel — adequate for "did this document get *its*
vector", which is what the projection tests ask, and useless here. The
semantic floor is only meaningful if two unrelated passages score *apart*, so
`SpreadEmbedder` sets a small hash-chosen set of components to 1 and the rest
to 0: two different texts share a component only by coincidence, and the
cosine between them is near zero, which is what a real embedding model does to
unrelated passages, exaggerated for determinism.

`conftest.fake_embedder` is still used by the projection tests it was written
for; nothing was changed there.

## Review Triage Log

### 2026-08-20 — Server review remediation
- decision: re-derived the semantic floor after verifying that Meilisearch's
  `semanticHitCount` is exhaustive, not page-local.
- patch: keyword and pure-semantic lanes are retrieved separately and blended
  deterministically; the floor no longer has a path to discard a keyword hit.
- patch: pure keyword mode skips the embedder; moments configuration must carry
  every highlighted attribute; malformed query responses are named, safe 503s.
- verification: `test_projections_query.py`, `test_config.py`, and the full
  `test_api_search.py` pass. The full server suite had one unrelated failure in
  `test_projection_lock_times_out_with_holder_details_then_releases`: its
  waiter acquired the lock after the holder's one-second delay while importing
  test infrastructure. Re-running that test alone reproduced the same timing
  failure; no file in that test or its lock implementation changed here.

### 2026-08-20 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 23: (high 0, medium 13, low 10)
- defer: 14: (high 0, medium 9, low 5)
- reject: 5: (high 0, medium 0, low 5)
- addressed_findings:
  - `[medium]` `[patch]` `ProjectionError` escaped the route as an opaque 500 (unset `MEILI_MASTER_KEY`, a refused query, a hit with no id) — now a named 503 `search-store-unusable`, ordered after the `StoreUnavailableError` subclass clause, with both slugs declared in `responses`.
  - `[medium]` `[patch]` `MomentSearchResult.index_missing` never reached the wire, so a never-projected corpus rendered "No moments match" — the silent zero the module exists to prevent. Added `indexMissing` to the response, a distinct web message, and a store-backed test that deletes the index.
  - `[medium]` `[patch]` `SNIPPET_ATTRIBUTES` omitted `speakers` and `title`, so two of AC1's three named input kinds returned unhighlighted results. Added both; `_formatted_strings` reaches inside the `speakers` array.
  - `[medium]` `[patch]` No test queried by meeting name or speaker — AC1's first and third input kinds. Added both, each asserting a highlighted run.
  - `[medium]` `[patch]` Ranking order was unasserted: every hit assertion compared sets, so database order would have kept the suite green. Added an ordered assertion contrasting index order with Postgres `ORDER BY start_ms`.
  - `[medium]` `[patch]` `limit`/`offset` were accepted and echoed but never exercised end to end. Added an explicit `limit=1`/`offset=1` paging case.
  - `[medium]` `[patch]` `q` was unbounded while `limit` was config-bounded. Added `max_length` 512, covered in the 422 block.
  - `[medium]` `[patch]` `SearchHit.started_at` was `str` with a hand-called `.isoformat()`, so `/search` lost `format: date-time` and diverged from `MeetingListItem`. Aligned to `datetime | None`; client regenerated.
  - `[medium]` `[patch]` The web panel wedged on "Searching…" after a failed first search, showing the banner and a permanent spinner. Rows now fall back to empty, and the "no matches" sentence is suppressed while a failure stands.
  - `[medium]` `[patch]` Every failure was headlined "Cannot reach the api", discarding the 503/422 distinction the server built. Transport failures and problem responses are now told apart, surfacing `title`/`detail`; both `error !== undefined` branches are tested for the first time.
  - `[medium]` `[patch]` `sourceDeepLink` was rendered as an `href` with no scheme check. Now `http:`/`https:` only, anything else rendered as inert text.
  - `[medium]` `[patch]` Truncation was invisible: results stopped at the configured limit with no indication more existed. Added "showing N of about M".
  - `[medium]` `[patch]` The timeout path and the superseded-response race had no tests, though the house style pins both elsewhere. Added both.
  - `[low]` `[patch]` `search.degraded` was a contracted log line with no assertion; added a `capsys` check including `reason="embedder_unavailable"`.
  - `[low]` `[patch]` The api's `build_embedder` startup gate was unreachable by `test_failfast.py` (every case aborted earlier at `load_config`). Added a case whose config has no serving provider.
  - `[low]` `[patch]` `estimatedTotal` told two stories — the docstring claimed one thing, the arithmetic another. Docstring corrected; an entirely-floored first page with zero keyword hits now reports 0, guarded to `offset == 0`.
  - `[low]` `[patch]` A non-UUID hit id raised a bare `ValueError` into the 500 handler; now the same named `ProjectionError` as the missing-id branch.
  - `[low]` `[patch]` Three docstrings claimed the route holds no store client, which is false — narrowed to the property the AST-walk test actually enforces.
  - `[low]` `[patch]` The debounce test asserted `< 14` calls for 14 keystrokes, passing at 13. Now asserts exactly one.
  - `[low]` `[patch]` `AbortSignal.any` sat outside the `try`, leaking the timer on throw; moved inside.
  - `[low]` `[patch]` An empty-string `meetingTitle` produced a blank header, and an empty snippet array an empty paragraph; both now fall back visibly.
  - `[low]` `[patch]` `aria-label` overrode the visible label text (WCAG 2.5.3); removed, and the results region gained `aria-live`/`aria-busy`.
  - `[low]` `[patch]` `epic-3` stayed `backlog` while a story left it, and the new sprint-notes section ran together with Epic 2; both corrected, plus a change-log entry recording the `SpreadEmbedder` substitution.

## Design Notes

**Why the `moments` index and not `chunks`.** A corpus-search result must be citable, and `moments` is the citation-shaped index — one document per Postgres-minted moment id, carrying `screenshotId`/`sourceDeepLink` (AD-6, AD-15). Eval check 2.10 is phrased as "a moment from the containing meeting appears in the top k", which the moments index answers directly. Moments are also comparable in size to chunks (median ~1.7 min of talk vs `chunk_max_chars: 1400`), so the granularity cost is small. `chunks` stays the retrieval unit for story 3.3's synthesis leg. *Assumption to attack: that moment-granularity recall is close enough to chunk-granularity recall for user-facing search; the bake-off measured chunks, not moments, and nothing here re-measures it.*

**Why `semantic_ratio` defaults keyword-heavy (0.3).** `retrieval-prior-art.md` §7 finding 1: on transcript-worded queries — the dominant shape — 0 of 9 embedding models beat BM25 alone, and six of nine hybrid configurations scored *below* the keyword baseline. Finding 2 says vectors earn their place on paraphrase only. *Assumption to attack: 0.3 is reasoned from those findings but is itself unmeasured on this corpus; it is a config knob precisely so Epic 5's retrieval eval can settle it.*

**Highlight runs, not markup.** Meilisearch returns `_formatted` with configurable pre/post tags. Using U+E000/U+E001 (Unicode private use area) as those tags and parsing them server-side into `[{text, highlighted}]` keeps HTML off the wire and out of React — the same reasoning AD-15 applies to citations. *Assumption to attack: that PUA code points never occur in transcript or OCR text; the parser must treat an unmatched sentinel as literal text rather than crashing, and a test covers exactly that.*

**Meilisearch ranks, Postgres cites.** The index decides ordering and produces the snippet; every citation field on the wire is re-read from the database of record. This costs one extra query per request and makes a stale index document a dropped-and-logged hit instead of a citation that resolves nowhere. *Assumption to attack: that the extra round trip is acceptable at demo scale.*

**Scope boundary against Epic 2.** Stories 2.2 (moment view) and 2.3 (meeting drill-down with the highlighted transcript) are both `backlog`. UX-DR3's full path therefore cannot terminate inside this story. 3.1 delivers search → candidate meetings/moments → highlighted snippet → inline replay using the existing `ReplayPlayer` from story 2.1; the transcript drill-down page is 2.3's named deliverable and building it here would duplicate that story and collide with its file boundary.

**Adding `screenText` requires a re-projection.** Existing Meilisearch documents predate the field. After this lands, `rebuild` must run for OCR text to be searchable on already-ingested meetings; the code is correct before that happens, the corpus simply is not re-indexed yet.

## Verification

**Commands:**
- `cd <repo> && uv run --project server pytest server/tests/test_projections_query.py` -- expected: all pass, no stores needed.
- `cd <repo> && uv run --project server pytest server/tests/test_api_search.py` -- expected: all pass with the Docker stores up (skips by name if they are down).
- `cd <repo> && uv run --project server pytest server/tests` -- expected: full server suite green, no regressions.
- `make web-test` -- expected: vitest green including the new `CorpusSearch` tests.
- `pnpm --dir web run build` -- expected: `tsc -b` clean against the regenerated client.
- `pnpm --dir web lint` -- expected: oxlint clean.
- `server/.venv/bin/python -c "import json,pathlib;from meetingminer.api.main import app;pathlib.Path('openapi.json').write_text(json.dumps(app.openapi()))" && pnpm --dir web run client -i openapi.json` -- expected: `web/src/client/{sdk,types}.gen.ts` gain `searchCorpus`. Run from the repo root so config.yaml resolves. Write the dump from inside Python rather than redirecting stdout: importing the app emits the `embedder.bound` startup log line, which a `>` redirect would fold into the file and break the parse. `client.gen.ts` will lose its `baseUrl: 'http://localhost:8000'` literal — that comes from the `servers` block only live-api generation supplies, so restore that one line (`lib/api.ts` overrides it at runtime either way).

**Manual checks (if no CLI):**
- `GET /search?q=<term>` against a running api returns hits whose `momentId` values also resolve through the existing evidence reads — confirming the index and the database of record agree.

## Auto Run Result

Status: done
Blocking condition: none

### What was implemented

`GET /search` over the Meilisearch `moments` projection, plus a corpus-search
view in the web app. The index ranks (typo-tolerant BM25 blended with a vector
lane through the `Embedder` port); Postgres supplies every citation field, so a
hit's `momentId`, `meetingId`, `startMs`, `endMs`, `screenshotId` and
`sourceDeepLink` come from the database of record rather than from the index,
and a document the database no longer backs is dropped and logged instead of
returned. Highlights travel as structured `{text, highlighted}` runs, never
markup. OCR text reaches the index for the first time via a new `screenText`
attribute. Search reads an explicit one-entry index allow-list, so no artifact
index is reachable regardless of what is written to one.

### Files changed

- `server/meetingminer/projections/query.py` (new) — the query side: index
  allow-list, hybrid/highlight/crop parameters, the `_formatted` → runs parser,
  the semantic floor, and the store-error taxonomy.
- `server/meetingminer/api/search.py` (new) — the route: validation, the
  embedder degrade/refuse split, Postgres citation resolution, three named 503s.
- `server/meetingminer/api/main.py` — embedder bound at startup; search router
  registered before the media catch-all.
- `server/meetingminer/config.py`, `config.yaml` — `api.search` query knobs
  (`default_limit`, `max_limit`, `semantic_ratio`, `crop_length`,
  `semantic_score_floor`); `screenText` added to the moments searchable list.
- `server/meetingminer/projections/evidence.py` — `ScreenshotRow.ocr_text` via
  `screenshot.representative_frame_id → frame_ocr.text`.
- `server/meetingminer/projections/search.py` — writes `screenText` into the
  moment document.
- `server/tests/test_projections_query.py`, `server/tests/test_api_search.py`
  (new), `server/tests/test_failfast.py`, `server/tests/test_config.py`.
- `web/src/features/search/{hits.ts,CorpusSearch.tsx,CorpusSearch.test.tsx}`
  (new), `web/src/App.tsx`, `web/src/App.test.tsx`, `web/src/client/*.gen.ts`.
- `_bmad-output/implementation-artifacts/{sprint-status.yaml,sprint-notes.md}`.

### Review findings breakdown

Four review layers (blind hunter, edge-case hunter, verification-gap,
intent-alignment). 23 patches applied, 14 items deferred, 5 rejected as noise.
No intent gap and no spec repair loopback: AC2's drill-down destination is
resolved by the intent corpus itself (story 2.3 owns that view), and every
remaining finding was localized rather than structural.

### Follow-up review recommendation

`true`. Patched this pass: high 0, medium 13, low 10. Score = 3 x 13 + 1 x 10 =
49, which is at or above the threshold of 5.

### Verification performed

Run in the story worktree after the patch pass, results observed directly:

- `uv run --project server pytest server/tests` — **1009 passed**, 0 skipped, 0
  failed, 1 pre-existing `StarletteDeprecationWarning` (277.53s).
- `pnpm --dir web run test` — **86 passed**, 6 files.
- `pnpm --dir web run build` — clean (`tsc -b` + vite).
- `pnpm --dir web lint` — clean except a pre-existing fast-refresh warning in
  `web/src/components/ui/button.tsx`, a file this story never touched.
- OpenAPI dump confirms `/search` with `operationId: searchCorpus`; regenerating
  the client from that dump produced byte-identical `sdk.gen.ts` and
  `types.gen.ts`, so the committed client matches the app.
- Matrix audit: all 12 I/O rows are covered by tests that ran and passed. The
  "Meilisearch down → 503" row had code but no test at first audit and was
  filled before review.

### Residual risks

- **`semantic_score_floor` is the least-evidenced number in the change.** 0.75,
  measured over five seeded moments with `qwen3-embedding:0.6b`: nonsense
  topped out at 0.701, an unrelated real query hit 0.734, a paraphrase scored
  0.783. A legitimate paraphrase landing between 0.70 and 0.75 is dropped
  today, and changing `embedder.model` invalidates the number silently.
- **Hybrid retrieval quality is unproven.** The store-backed suite uses a
  deliberately near-orthogonal stand-in embedder, so no test shows the vector
  lane retrieving anything BM25 misses. What is tested is that the hybrid
  request is well-formed and the ranking mode is announced.
- **OCR text is indexed but not embedded**, so on-screen content is reachable
  by keyword only.
- **Existing corpora need `make rebuild`** before `screenText` is searchable;
  that is a corpus-wide operation on the shared stores and was not run from a
  story branch.
