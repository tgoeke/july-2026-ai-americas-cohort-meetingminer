# Code Review — Story 3.3: Cited Q&A with Deterministic Citation Gate

**Review date:** 2026-08-20  
**Reviewer branch:** `story/3-3-review`  
**Reviewed branch:** `story/3-3`  
**Review range:** `e94bea85eb165da1c422ae4f1ead66c2d60e3991..501bad3bc86a494182685fd631974cfbb2ef9faa`

## Scope

Independent full-spec review of Story 3.3, including the deterministic citation
gate, `/chat` orchestration, routing, configuration, and its tests.

## Findings

### 1. Nested malformed citation syntax passes the gate and leaks marker syntax

- **Location:** `server/meetingminer/api/citations.py:57,190,293-347`
- **Severity:** medium
- **Finding:** The marker regex recognizes an inner valid marker but ignores an
  unmatched outer `[[moment:` prefix. The gate accepts the draft and returns
  prose that still contains a marker prefix, violating AC2 and AD-15's
  marker-free answer contract.
- **Evidence:** I ran `validate()` with `The feed moved
  [[moment:not-a-uuid [[moment:<retrieved-id>]]`; it returned
  `ValidatedAnswer` with `[[moment:not-a-uuid` still in `answer`.
- **Suggested direction:** Reject malformed or nested marker syntax before a
  validated answer is constructed; pin the nested case in the store-free gate
  tests.

### 2. Non-LF line separators allow an uncited claim through the sentence gate

- **Location:** `server/meetingminer/api/citations.py:239-242`
- **Severity:** medium
- **Finding:** `split_claims()` treats only `\\n` as a newline. A carriage-return
  or Unicode line separator leaves two claims in one unit, allowing the last
  claim's marker to satisfy both.
- **Evidence:** `First claim is uncited\\rSecond claim is cited
  [[moment:<retrieved-id>]]` returns `ValidatedAnswer` rather than
  `uncited-claim`.
- **Suggested direction:** Normalize or split on the complete set of line-break
  characters before evaluating the per-sentence citation rule, with regression
  tests for CRLF/CR and Unicode separators as applicable.

### 3. SSE negotiation disregards an explicit `q=0` exclusion

- **Location:** `server/meetingminer/api/chat.py:385-392`
- **Severity:** low
- **Finding:** `_wants_stream()` is a substring check, so `Accept:
  application/json, text/event-stream;q=0` receives an SSE response even though
  the client declared that representation unacceptable.
- **Evidence:** The function returns true whenever the token appears; it does
  not parse quality values. The story expressly chose a content-negotiated
  endpoint.
- **Suggested direction:** Perform minimal standards-compliant negotiation for
  the two supported representations and add compound-header coverage.

### 4. Classifier-derived query strings and anchors have no length bound

- **Location:** `server/meetingminer/api/chat_router.py:190-247`
- **Severity:** medium
- **Finding:** Any nonblank `searchTerms`, participant, screen, or topic value
  from the classifier is accepted. It can be passed into embedding,
  Meilisearch, Postgres `LIKE`, and structured logs far beyond the 1,000-char
  user-question bound.
- **Evidence:** `_text()` only trims and checks truthiness; `_answer()` forwards
  `decision.search_terms` to `_embed()` and `_search_leg()`, while anchors reach
  `_resolve_anchor()` and log fields.
- **Suggested direction:** Bound classifier-supplied strings at the router
  boundary and degrade safely to search-only/raw-question behavior when a route
  cannot be used; add boundary tests.

### 5. Parser drops a usable first JSON object when a reply contains another object

- **Location:** `server/meetingminer/api/chat_router.py:160-172`
- **Severity:** low
- **Finding:** The fallback candidate spans from the first `{` to the final `}`.
  A prose-wrapped valid decision followed by another brace-delimited object is
  concatenated into invalid JSON, so the router loses its usable route and
  search terms.
- **Evidence:** `_json_candidates()` uses `find("{")` with `rfind("}")`; no
  balanced-object extraction exists despite the comment promising candidates
  worth parsing.
- **Suggested direction:** Decode the first complete JSON object deterministically
  (while respecting quoted braces) and test the multi-object wrapper case.

### 6. Prompt-dropped moments remain citable and are reported as prompt-visible

- **Location:** `server/meetingminer/api/chat.py:787-839,964-991`
- **Severity:** medium
- **Finding:** `build_synthesis_prompt()` drops whole moments at the prompt cap,
  but validation receives all Postgres context IDs and `route.retrieved` claims
  all of them reached synthesis. A model can cite a retrieved-but-unshown ID,
  and the wire metadata misstates the prompt evidence set.
- **Evidence:** The prompt loop increments `dropped_moments` and omits the
  block, while `_answer()` calls `validate()` with every item in `retrieved`.
  `RouteModel.retrieved` is documented as moments that reached the prompt.
- **Suggested direction:** Return or preserve the included moment IDs from prompt
  construction, use that set for the validator and route count, and test a
  deliberately oversized retrieval.

### 7. Traversal-limit documentation reverses actual behavior

- **Location:** `config.yaml:258-263`, `server/meetingminer/config.py:558-563`
- **Severity:** low
- **Finding:** Both configuration descriptions say the cap retains earliest
  rows/drops newest rows, while `_traversal_leg()` deliberately keeps the most
  recent `rows[-limit:]`.
- **Evidence:** `server/meetingminer/api/chat.py:646-653` and its integration
  test implement the latter behavior.
- **Suggested direction:** Correct the user-facing comments/docstring to say
  the newest rows are retained, consistent with the code and test.

### 8. No end-to-end proof that search uses classifier-normalized terms

- **Location:** `server/tests/test_api_chat.py:231-275,1055-1083`
- **Severity:** low
- **Finding:** Search tests use questions whose typed text already includes the
  classifier term. Replacing `decision.search_terms or question` with `question`
  would keep them green, despite a measured reason this path must use normalized
  classifier terms.
- **Evidence:** The `ledger` test asks “what happened with the ledger?” and the
  common search case asks about “purchase order”; each contains its `searchTerms`.
- **Suggested direction:** Add a projected-evidence case where only the
  classifier-provided phrase matches and assert the cited response.

### 9. Transcript-only source deep links lack a positive API assertion

- **Location:** `server/tests/test_api_chat.py:231-262`
- **Severity:** low
- **Finding:** The API test compares `sourceDeepLink` against Postgres only for
  the default recording-backed seed, and no successful transcript-only `/chat`
  response proves the fallback navigation field is serialized.
- **Evidence:** `seed_meeting()` defaults to `has_recording=True`; store-free
  tests cover a resolver field but not public JSON serialization for the
  transcript-only path.
- **Suggested direction:** Seed a transcript-only meeting and assert a successful
  response has `screenshotId: null` and the Postgres `sourceDeepLink`.

### 10. Base unusable-store mappings are untested

- **Location:** `server/tests/test_api_chat.py:652-704`
- **Severity:** low
- **Finding:** The suite covers `StoreUnavailableError` but not base
  `ProjectionError` from either retrieval leg. Those are distinct handlers and
  slugs (`*-store-unusable`) intended for callers and operators.
- **Evidence:** `StoreUnavailableError` is caught before `ProjectionError` in
  `chat.py`; the tests monkeypatch only the former exception class.
- **Suggested direction:** Force a base `ProjectionError` from each leg and
  assert its named 503 problem type and store extension.

## Dismissed after verification

- The person-scoped union finding is already a documented Story 3.3 deferred
  item; this review does not duplicate it.
- A populated corpus with no matching retrieval correctly spends one
  classification call but no synthesis call; the story’s Design Notes reconcile
  that necessary distinction with the no-evidence matrix row.
- No actionable defect was established for the deferred generated TypeScript
  client, generic OpenAPI problem extensions, or provider-level response-size
  limits.

## Remediation

All ten patch findings were applied on `story/3-3-review`. The gate now rejects
nested/malformed marker prefixes and recognizes common non-LF line separators;
the router bounds model-derived values and extracts the first complete JSON
object; the endpoint respects an SSE `q=0` exclusion; and citation eligibility
is now the subset actually placed in the synthesis prompt. The remaining fixes
correct the traversal-cap documentation and add regression coverage for all
identified API seams.
