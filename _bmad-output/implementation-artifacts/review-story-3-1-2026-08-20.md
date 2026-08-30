---
title: 'Story 3.1 — Corpus Search review report'
story: '3-1-corpus-search'
date: '2026-08-20'
reviewed_range: '65f0b1c..7d41adc (rebased and landed through 64d295b)'
status: 'passed'
followup_review_recommended: false
---

# Story 3.1 Review Report

## Scope and disposition

This report records the completed adversarial review of the Story 3.1 server,
web, and documentation/configuration changes. The original story range was
reviewed in separate server and web passes; their fixes landed on `main` in
`79735b1` and `64d295b` respectively. The documentation/configuration slice
was subsequently re-read directly for this report. All must-fix findings below
are resolved. The remaining limits are explicitly deferred story/epic work,
not review blockers.

## Server findings — resolved

### S1 — Semantic floor was applied using an invalid lane boundary

- **Location:** `server/meetingminer/projections/query.py:374` (original design);
  resolved in `search_moments` at `:513-558`.
- **Severity:** high.
- **Finding:** The original implementation treated Meilisearch's
  `semanticHitCount` as a page-local suffix marker and could therefore floor
  keyword hits as though they were semantic hits.
- **Evidence:** Meilisearch documents `semanticHitCount` as exhaustive for the
  request, while paging limits the returned hit list. A later page can contain
  fewer than that count (or a mixed order), so the inferred suffix is not a
  semantic lane. The contract requires typo-tolerant keyword hits to survive.
- **Suggested direction:** Request keyword and pure-semantic lanes separately,
  floor only the semantic lane, and blend their ordered results deterministically.
- **Resolution:** Implemented and covered by `server/tests/test_projections_query.py`.

### S2 — Pure keyword mode still depended on the embedder

- **Location:** `server/meetingminer/api/search.py:182`.
- **Severity:** medium.
- **Finding:** A configured `semantic_ratio: 0.0` should be keyword-only, but
  the initial path still attempted `embed_query`; an unavailable embedder could
  turn a keyword-only request into an unnecessary degraded/failing dependency.
- **Evidence:** The ratio itself declares that the vector lane has zero weight.
- **Suggested direction:** Bypass query embedding when the ratio is exactly zero.
- **Resolution:** The endpoint now takes the keyword-only path directly, with a
  down-embedder regression test.

### S3 — Highlighted fields were not validated as index configuration

- **Location:** `server/meetingminer/config.py:435` and `config.yaml:293`.
- **Severity:** medium.
- **Finding:** Search requested snippets across transcript, OCR, speakers, and
  title, while the loader originally guaranteed only `text`.
- **Evidence:** Removing `screenText`, `speakers`, or `title` would leave a
  valid-looking config that failed search highlighting only after deployment.
- **Suggested direction:** Bind every query-time snippet field to the moments
  index configuration at load time.
- **Resolution:** The `SearchConfig` validator requires all four attributes;
  loader coverage proves each omission is refused.

### S4 — Malformed Meilisearch responses escaped the named refusal path

- **Location:** `server/meetingminer/projections/query.py:337-457`.
- **Severity:** medium.
- **Finding:** Invalid hit arrays, totals, ids, and ranking scores could produce
  incidental exceptions instead of the endpoint's deliberate 503 problem.
- **Evidence:** The store response is external data; the first version assumed
  its shape and numeric fields without validating all of them.
- **Suggested direction:** Validate the response boundary and raise the named
  `ProjectionError` for every malformed shape.
- **Resolution:** Shape, count, id, and score guards now normalize those cases;
  tests assert the RFC 9457 store-unavailable response.

### S5 — Store diagnostic text could expose a raw indexed document

- **Location:** `server/meetingminer/projections/query.py:468` (original path).
- **Severity:** low.
- **Finding:** A malformed/missing id error included the document representation
  in diagnostic detail that could reach the API problem response.
- **Evidence:** Indexed documents contain snippets and metadata not intended as
  error payloads.
- **Suggested direction:** Retain only a bounded structural diagnostic, never
  serialize the source document into a client-facing error.
- **Resolution:** Error text no longer includes raw hit bodies; coverage checks
  the resulting problem detail.

### S6 — Query-time store loss lacked a direct regression test

- **Location:** `server/tests/test_api_search.py:800-813`.
- **Severity:** medium (verification gap).
- **Finding:** Construction-time store failure was tested, but a store that
  becomes unavailable after construction was not.
- **Evidence:** `meili_client` health-checks before it returns, so a test that
  only fails construction cannot exercise the query call's exception mapping.
- **Suggested direction:** Use a constructed client whose `search` method
  raises, and assert `search-store-unavailable`.
- **Resolution:** Added and passing.

### S7 — The default-limit/max-limit invariant lacked a negative loader test

- **Location:** `server/meetingminer/config.py:520-527`,
  `server/tests/test_config.py`.
- **Severity:** low (verification gap).
- **Finding:** `default_limit > max_limit` means a request that omits `limit`
  is refused by the very constraint intended to protect it; this was guarded in
  code but not proved by a negative configuration test.
- **Evidence:** The invariant is cross-field and cannot be established by
  individual `Field` bounds.
- **Suggested direction:** Add a loader test with the relationship inverted.
- **Resolution:** Added and passing.

## Semantic-score-floor contract deviation — accepted and tracked

- **Location:** `config.yaml:240`, `server/meetingminer/config.py:475-527`, and
  the Story 3.1 spec change log.
- **Severity:** medium.
- **Finding:** The frozen contract named four `api.search` knobs. Implementation
  added `semantic_score_floor` as a fifth knob to make its explicit no-match
  requirement possible under hybrid retrieval.
- **Evidence:** With a caller-supplied vector, the semantic lane returns nearest
  neighbours even for nonsense input. Meilisearch's single
  `rankingScoreThreshold` applies to both keyword and semantic lanes; measured
  keyword typo hits (~0.15) and unrelated semantic hits (~0.65) do not share a
  usable threshold. The configured floor 0.75 was measured over five seeded
  moments: paraphrase 0.783, unrelated real query 0.734, nonsense 0.701.
- **Suggested direction:** Keep it explicit and tune it through Epic 5 retrieval
  evaluation; couple any embedder-model change to re-evaluating the floor.
- **Disposition:** Accepted contract amendment, documented in the spec. Its
  narrow calibration remains a recorded residual risk, not a reason to hide
  semantic noise or violate the no-match acceptance row.

## Web findings — resolved

### W1 — A previous response could win during the next debounce window

- **Location:** `web/src/features/search/CorpusSearch.tsx:149-166`.
- **Severity:** medium.
- **Finding:** Changing a nonblank term originally waited 300 ms before
  cancelling the current request, allowing an old response to overwrite the
  newer intent.
- **Evidence:** Cancellation happened only at the delayed `runSearch` call.
- **Suggested direction:** Abort at the keystroke and mark the live region busy
  for the debounce interval.
- **Resolution:** Implemented with a regression test that resolves the old
  request inside that interval.

### W2 — A client resolving after timeout could overwrite the timeout outcome

- **Location:** `web/src/features/search/CorpusSearch.tsx:89-97`.
- **Severity:** medium.
- **Finding:** The post-await guard checked only supersession, not the expiry
  signal, so a nonconforming/late client response could be accepted after eight
  seconds.
- **Evidence:** Abort signalling does not guarantee every client promise stops
  settling; the test double can demonstrate this case.
- **Suggested direction:** Treat an already-aborted expiry signal as timeout
  regardless of the response body.
- **Resolution:** Added expiry guard and late-response regression test.

### W3 — First-search failure falsely called empty results stale

- **Location:** `web/src/features/search/CorpusSearch.tsx:207-215`.
- **Severity:** low.
- **Finding:** A first failure initializes an empty result array, but the banner
  said results below “may be stale” even when there were none.
- **Evidence:** `rows` was `[]`, not retained nonempty prior data.
- **Suggested direction:** Render the stale qualifier only for retained rows.
- **Resolution:** Implemented with first-failure and retained-result coverage.

### W4 — Error rendering could itself throw on an unknown payload

- **Location:** `web/src/features/search/CorpusSearch.tsx:18-29`.
- **Severity:** low.
- **Finding:** `JSON.stringify` throws on circular data and returns `undefined`
  for some values.
- **Evidence:** Error payloads are external diagnostic data and must not crash
  the failure UI.
- **Suggested direction:** Guard serialization and use a stable fallback.
- **Resolution:** Implemented with a circular-payload regression test.

### W5 — The search-level replay test did not prove the actual seek

- **Location:** `web/src/features/search/CorpusSearch.test.tsx:347-387`.
- **Severity:** low (verification gap).
- **Finding:** The test asserted the media source and separately rendered
  `0:44`, but not that replay applied the hit's `startMs` after metadata loaded.
- **Evidence:** `ReplayPlayer` seeks on `loadedmetadata`; a source assertion
  cannot prove the event-driven seek.
- **Suggested direction:** Dispatch `loadedmetadata` and assert
  `currentTime === 44` in the integration-level test.
- **Resolution:** Added and passing.

### W6 — RFC 9457 banners omitted the configured API address

- **Location:** `web/src/features/search/CorpusSearch.tsx:213-214`.
- **Severity:** low.
- **Finding:** Transport errors named `API_BASE`, but problem-response errors
  did not, contrary to the established component error-banner convention.
- **Evidence:** Both states direct the user to the same configured service;
  omitting its address makes diagnosis less actionable.
- **Suggested direction:** Include `API_BASE` in both banner variants.
- **Resolution:** Implemented and asserted.

## Deep-link trust-boundary decision — resolved by product direction

- **Location:** `web/src/features/search/hits.ts:33-50`.
- **Severity:** medium (security/product decision).
- **Finding:** Scheme-only validation allows an arbitrary HTTPS origin from a
  source drop to be labelled “Open in Stream”; it prevents executable URLs but
  does not establish an origin allow-list.
- **Evidence:** `sourceDeepLink` originates outside the web application. An
  `https:` URL can be safe to navigate yet still be a misleading destination.
- **Suggested direction:** Either specify trusted origins or explicitly declare
  source-drop provenance trusted.
- **Disposition:** The user selected the latter. The code and comments now
  state that trusted source drops may provide any absolute HTTP(S) URL, while
  `javascript:`, `data:`, `file:`, relative, and malformed values stay inert.

## Documentation and configuration review — clean

This final slice was re-run directly by this reviewer; it does not rely on the
other session's reconstruction draft.

- **Location:** `config.yaml:218-240` and
  `server/meetingminer/config.py:475-548`.
- **Severity:** none.
- **Finding:** The new query-time settings are correctly separated from
  projection/index settings, use bounded types, and are required by the strict
  loader. The cross-field default/max relationship is validated. The moments
  search configuration preserves ordered field boosting and declares
  `text`, `screenText`, `speakers`, and `title`.
- **Evidence:** The config model's validators match the declared runtime query
  surface; `server/tests/test_config.py` covers a complete load, reordered
  searchable fields, a missing snippet field, and inverted limits. The explicit
  comments correctly state that `screenText` needs a rebuild for existing
  documents and that query knobs do not themselves re-project data.
- **Suggested direction:** No patch. Keep the documented Epic 5 evaluation as
  the owner of semantic-score calibration and continue treating corpus rebuild
  as a shared-store operation.

The Epic 3 context, sprint notes, frozen contract, and deferred frontmatter
also agree on the two intentional Story 3.1 boundaries: drill-down stays with
Story 2.3, and Neo4j retrieval stays with Story 3.2. No documentation/config
contradiction or unrecorded configuration key was found.

## Verification recorded by this review

- Server remediation tests: `98 passed` for query/config and `35 passed` for
  API search; the original full server run exposed the unrelated projection-lock
  timing flake, which was later fixed on `main` in `e567d1e`.
- Web remediation: `pnpm --dir web run test` — `90 passed`; production build
  passed; lint had only the pre-existing `button.tsx` fast-refresh warning.
- Documentation/configuration re-check: `git diff --check` for the scoped
  configuration and implementation-artifact changes; config-model/test coverage
  inspected as described above.

## Final verdict

Story 3.1 passes review. `followup_review_recommended` is false because all
review patches and the one decision were resolved; the documented deferred
work remains assigned to its owning stories or Epic 5 evaluation.
