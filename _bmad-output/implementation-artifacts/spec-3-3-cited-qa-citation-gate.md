---
title: 'Story 3.3 — Cited Q&A with Deterministic Citation Gate'
type: 'feature'
created: '2026-08-20'
status: 'done'
baseline_revision: 'e94bea85eb165da1c422ae4f1ead66c2d60e3991'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-3-context.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md'
warnings: ['oversized']
deferred:
  - summary: >-
      The committed TypeScript client carries no `askCorpus` operation, so the
      /chat wire contract is pinned only by hand-written assertions.
    evidence: |-
      `infra/Makefile:check-client` documents that `web/src/client/*.gen.ts` is
      committed, and `test_api_search.py` pins `/search`'s operationId as "the
      published contract" because the client is generated from it. `/chat` has
      no equivalent. Regeneration was not run here: `make client` generates
      from whatever api answers on the fixed port :8000, and its identity check
      cannot distinguish this worktree's api from another agent's, so a
      concurrent run would bake a foreign schema into the committed client.
      Story 3.4 owns `web/` and needs the types.
    location: >-
      web/src/client/sdk.gen.ts
    severity: medium
  - summary: >-
      Person-scoped retrieval unions the traversal and search legs rather than
      intersecting them, so a question about one person can cite moments that
      person was not in.
    evidence: |-
      The dispatch note carried from sprint-notes recommended decomposing
      "where was Jordan confused" as participant traversal INTERSECT semantic
      search rather than hoping ranking surfaces the right person. The search
      leg is called with no filter arguments, so up to `retrieval_limit`
      unfiltered hits are unioned with the traversal rows and every one of them
      is citable. The recorded design note argues the union buys a non-empty
      retrieval when classification is wrong; the note's one-line enabler
      (adding `speakers` to the moments index `filterable_attributes`) also
      requires a full re-projection, which is why it was not taken mid-story.
    location: >-
      server/meetingminer/api/chat.py
    severity: medium
---

<intent-contract>

## Intent

**Problem:** Search (3.1) and traversal templates (3.2) both exist and neither is reachable as an answer: there is no `/chat`, no router classifying a question onto a template, no synthesis, and — the point of the story — no deterministic gate that makes an uncited answer impossible to emit (FR13, FR14, NFR4, AD-6).

**Approach:** Add the chat path the spine fixes: `POST /chat` → router classifies the question onto `TRAVERSAL_TEMPLATES` (3.2) and/or the moments index (3.1) → deterministic retrieval → `Llm(chat)` synthesis emitting `[[moment:<uuid>]]` markers → a deterministic validator that resolves every marker against Postgres and converts them to the one AD-15 `citations` array. An answer that fails the gate is rejected as an RFC 9457 problem — never repaired, never partially emitted. Validation completes **before** anything streams; the SSE surface (`chat.token` / `chat.citations` / `chat.done`) replays an already-validated answer, so no unvalidated draft can leak token by token.

## Boundaries & Constraints

**Always:**
- The gate is code, not prompt text. `[[moment:<uuid>]]` markers are parsed deterministically; every marker must (a) name a moment that was actually retrieved for this question and (b) re-resolve against Postgres in the same request. Every citation field on the wire (`momentId`, `meetingId`, `startMs`, `endMs`, `screenshotId?`, `sourceDeepLink?`) is read from Postgres, never from Neo4j, Meilisearch, or the model's text (AD-6, AD-15, mirroring `api/search.py::_resolve`).
- **"Every claim cited" is enforced as "every sentence cited."** The answer is split into sentence units (terminator or newline); any unit containing an alphanumeric character must carry ≥1 marker, or the whole answer is rejected. This deliberately over-approximates — a non-factual sentence is rejected too — because the property that must hold is that no uncited claim leaves the API.
- Rejection is a first-class response: `422` `application/problem+json`, slug `no-citable-answer`, with a camelCase `reason` extension (`no-evidence` | `no-citations` | `uncited-claim` | `unresolvable-marker` | `empty-answer`) so 3.4 can render one explicit state and still tell it from a transport error.
- No `meilisearch` and no `neo4j` import anywhere under `server/meetingminer/api/` (AD-4; asserted by `tests/test_projections_single_writer.py::test_the_api_package_never_reaches_a_store`). Stores are reached only through `projections.query.search_moments`, `projections.traversals.run_template`, and `projections.stores.meili_client` / `neo4j_driver` — the exact pattern `api/search.py` already uses.
- The model is bound only through `llm.roles.chat` in `config.yaml` via `adapters.llm.build_llm` (AD-8, AD-10). No model id appears as a code constant.
- Retrieval draws from evidence moments only. Nothing reads `publish_gate.ARTIFACTS_INDEX`; no artifact text reaches the synthesis prompt by any path (NFR7).
- No silent zero: empty retrieval is rejected with `reason: no-evidence` **before** any model call; an unresolved traversal anchor (`anchor is None`, 3.2's distinction) is carried to the wire as its own outcome and logged, never collapsed into "nothing found".
- No test may reach a real model provider or spend money (AGENTS.md; the Anthropic key is revoked). Everything is exercised against fake `Llm` instances.
- Store-free tests for router parsing, marker parsing, and every validator rejection path; store-backed tests through the public API for the end-to-end citation contract.

**Block If:**
- The gate cannot be satisfied without changing 3.2's traversal signatures or 3.1's `search_moments` contract — both are `done` and their modules are outside this story's boundary.
- The `Llm` port turns out to need a streaming method to satisfy the SSE names: adding one changes an ADOPTED port shared with `extract` and 4-1a's concurrent rewrite. (Not expected — tokens are replayed from the validated answer, so `complete()` suffices.)

**Never:**
- Nothing under `web/src/features/`, `web/src/App.tsx`, or any hand-edited web file — the chat UI, citation rendering, and replay links are story 3.4. Regenerating the committed TS client (`make client`) is permitted; hand-editing it is not.
- No new traversal templates and no new Cypher. A question class with no template is a "no template" outcome, not a new statement.
- No approval/publishing endpoints, no prompt-visibility UI, no artifact re-indexing (4.2–4.4). No eval checker (Epic 5).
- Do not touch `pipeline/extraction.py`, `pipeline/stages/extract.py`, or the `pipeline.extraction` config block — 4-1a owns them concurrently.
- Do not start the ingestion worker. Do not run `make evals-run`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Cited answer, search leg | Projected corpus; question matching seeded moments; fake `Llm` returning one sentence per retrieved moment, each with its `[[moment:<uuid>]]` | `200` with `answer` (markers stripped), `citations` in first-appearance order, every field equal to that moment's Postgres row; `route.template` reported | No error expected |
| Cited answer, traversal leg | Two meetings a seeded participant attended; question naming that participant and a topic term; fake `Llm` classifier returning `participant-topic-moments` | Retrieval runs the 3.2 template, citations carry its moment ids re-read from Postgres | No error expected |
| Poisoned marker | Fake `Llm` cites a random UUID never retrieved | `422` problem+json, `reason: unresolvable-marker`; no `answer` field | Rejected whole; nothing partial emitted |
| Deleted moment | Marker names a retrieved moment whose row is deleted before validation | `422` `reason: unresolvable-marker`; logged | Rejected whole |
| Uncited claim | Fake `Llm` returns two sentences, only the first carrying a marker | `422` `reason: uncited-claim` | Rejected whole |
| No markers at all | Fake `Llm` returns plain prose | `422` `reason: no-citations` | Rejected whole |
| Empty retrieval | Question matching nothing; index empty or all hits floored | `422` `reason: no-evidence`, no model call made (assert the fake recorded zero calls) | Refused before synthesis |
| Unknown traversal anchor | Classifier names `participant-topic-moments` for a person not in the corpus | Traversal reports anchor unresolved; search leg still runs; if it also yields nothing → `no-evidence` with the unresolved anchor logged | No silent zero |
| Unregistered template | Classifier returns a template name not in `TRAVERSAL_TEMPLATES`, or malformed JSON | Deterministic fallback to search-only; logged; never dispatched | Never raises to the caller |
| SSE happy path | `Accept: text/event-stream`, answer passes the gate | Events in order: `chat.token`+ (replayed from the validated answer), `chat.citations` (the same array), `chat.done` | No error expected |
| SSE rejection | `Accept: text/event-stream`, answer fails the gate | `422` problem+json — the stream never opens, so no token is emitted | Distinguishable from transport error |
| Bad request | `question` blank/whitespace, or over the length bound | `422` `invalid-request` | Refused at the door |
| Store down | Meilisearch or Neo4j unreachable | `503` problem+json, slug naming which store | Named, not a 500 |

</intent-contract>

## Code Map

- `server/meetingminer/api/search.py` -- **the template to follow.** `_RESOLVE_MOMENTS` (one statement per page), `_resolve()` (stale hits dropped + `search.stale_hit` log), `_embed()` (degrade vs. refuse), `SEARCH_TERM_MAX_LENGTH`, `_limit_of()` config bound, camelCase models via `alias_generator=to_camel`. Reuse the shape; do not import from it beyond `SEARCH_TERM_MAX_LENGTH` if useful.
- `server/meetingminer/projections/query.py:468` -- `search_moments(client, config, *, query, limit, offset, meeting_id, corpus, query_vector)` → `MomentSearchResult(hits: tuple[MomentHit], estimated_total, limit, offset, index_missing, below_floor)`. `MomentHit` is `moment_id`/`snippet`/`score` only — no citation fields.
- `server/meetingminer/projections/traversals.py` -- `TRAVERSAL_TEMPLATES` (`screen-history` params `("screen_id",)`; `participant-topic-moments` params `("participant_id","topic")`), `run_template(driver, name, **params)`, `TraversalMoment`, `ScreenHistoryResult.screen is None` / `ParticipantTopicMomentsResult.participant is None` = unknown anchor. Raises `ValueError` on malformed input, `ProjectionError` on an unregistered name or wrong params.
- `server/meetingminer/projections/stores.py:91,116` -- `neo4j_driver(config)` (context manager) and `meili_client(config)` (health-checks; raises `ProjectionError`/`StoreUnavailableError`). Also `MOMENTS_INDEX`; `publish_gate.ARTIFACTS_INDEX` must stay unread.
- `server/meetingminer/adapters/llm/__init__.py` -- `build_llm(role_binding, providers, log)` → `FallbackLlm`; `port.py` -- `Llm.complete(prompt) -> LlmReply(text, model, fallback_engaged)`, `LlmError` / `LlmUnavailableError`. `pipeline/stages/extract.py:114` shows the one existing call site's shape.
- `server/meetingminer/config.py:141-154` -- `LlmRoleBinding` / `LlmRoles.chat`; `:475` `SearchQueryConfig`, `:531` `ApiConfig` — where an `api.chat` block is added. `config.yaml:23-34` (`llm.roles.chat`) and `config.yaml:193-240` (the `api:` block).
- `server/meetingminer/api/problems.py` -- `Problem(status, slug, detail, title=None, **extensions)`, `ProblemDetails`, `problem_response`. Extensions are camelCase by convention (`maxLimit`, `jobId`).
- `server/meetingminer/api/main.py:130-150` -- router registration block; note the registration-order comments. `/chat` has no literal sibling, so append after `search`.
- `server/meetingminer/api/events.py` -- the existing SSE precedent in this codebase (named events, heartbeats); read it before writing the chat stream.
- `server/tests/conftest.py:671-742` -- `FakeLlm` (scripted replies, `calls` list), autouse `_no_real_llm` (currently patches `extract_stage.build_llm` only — **widen it** to also patch the chat call site), `fake_llm` fixture, `truncate_evidence`, `projection_stores` / `stores_up`.
- `server/tests/projection_seed.py:75` -- `seed_meeting(conn, *, source_id, has_recording, title, corpus, turns, participants, screen_identity_keys, screen_view_types, with_moments, started_at, stage_overrides)`; `DEFAULT_TURNS`, `DEEP_LINK`, `SeededMeeting.moment_ids`.
- `server/tests/test_api_search.py` -- the store-backed API test pattern to mirror (`projection_stores`, `meili` naming, `await_task`, Postgres-vs-index assertions).
- `server/meetingminer/projections/evidence.py:180-245` -- how moment text is assembled (`moment_segment` → `transcript_segment`, `"<speaker>: <text>"` joined by newline). The chat context read must produce the same shape from Postgres.
- Read-only evidence: `moment` has **no** `text` column (`migrations/0006_moments.sql`); text comes from the segment join. `participant.normalized_name` and `participant.identity_key` are the name-resolution keys (`migrations/0005`). `screen.label` / `screen.identity_key` are the screen keys (`migrations/0003`).

## Tasks & Acceptance

**Execution:**
- `server/meetingminer/api/citations.py` -- new: `MARKER_PATTERN`, `parse_markers(text)`, `strip_markers(text)`, `split_claims(text)`, and `validate(draft, retrieved, resolve) -> ValidatedAnswer | Rejection` -- pure, store-free, no FastAPI import, so the gate is unit-testable in isolation and reviewable in one file.
- `server/meetingminer/api/chat_router.py` -- new: the classification prompt plus `parse_route(raw) -> RouteDecision` validating the model's JSON against `TRAVERSAL_TEMPLATES` -- keeps "the model classifies, code dispatches" (AD-7) in one pure module; anything unrecognized becomes `template=None` (search-only), never an exception.
- `server/meetingminer/api/chat.py` -- new: the `POST /chat` route, anchor resolution against Postgres, both retrieval legs, the synthesis prompt, the gate call, the JSON and SSE responses, and the `chat.*` log events -- the orchestrator the spine's sequence diagram names.
- `server/meetingminer/api/main.py` -- register the chat router after `search` -- one line, with the registration-order comment convention respected.
- `server/meetingminer/config.py` -- add `ChatQueryConfig` (`retrieval_limit`, `traversal_row_limit`) to `ApiConfig` -- retrieval breadth is a tuning knob and belongs in the one config file (AD-10), not in a code constant.
- `config.yaml` -- add the `api.chat` block with commented defaults -- same house style as `api.search`.
- `server/tests/test_chat_citations.py` -- new: store-free unit tests for every marker/claim/validator row of the I/O matrix, including malformed markers, duplicate markers, uppercase UUIDs, and a marker adjacent to punctuation.
- `server/tests/test_chat_router.py` -- new: store-free unit tests for classification parsing — valid decision, unregistered template, wrong parameter set, fenced/`prose-wrapped` JSON, junk output — asserting fallback rather than raising.
- `server/tests/test_api_chat.py` -- new: store-backed tests through `POST /chat` for the cited answer (both legs), each rejection reason, the no-model-call-on-empty-retrieval assertion, the SSE event sequence, and the SSE rejection shape.
- `server/tests/conftest.py` -- widen autouse `_no_real_llm` to bind the chat call site too, and add a `fake_chat_llm` fixture -- the money guard must cover every production `build_llm` call site, or a `/chat` test spends real API budget.

### Review Findings

- [x] [Review][Patch] Nested malformed citation syntax can pass the gate and leak a marker prefix [server/meetingminer/api/citations.py:57]
- [x] [Review][Patch] Non-LF line separators let one marker cover multiple claims [server/meetingminer/api/citations.py:239]
- [x] [Review][Patch] `Accept` negotiation ignores a `text/event-stream;q=0` exclusion [server/meetingminer/api/chat.py:392]
- [x] [Review][Patch] Classifier-provided search terms and traversal anchors have no size bound [server/meetingminer/api/chat_router.py:190]
- [x] [Review][Patch] Prose-wrapped classifier replies with more than one JSON object are needlessly discarded [server/meetingminer/api/chat_router.py:168]
- [x] [Review][Patch] Citation eligibility and route metadata include prompt-dropped moments [server/meetingminer/api/chat.py:787]
- [x] [Review][Patch] Traversal-limit documentation states the reverse of the implemented ordering [config.yaml:261]
- [x] [Review][Patch] The API suite does not prove the search leg uses classifier terms rather than the raw question [server/tests/test_api_chat.py:1055]
- [x] [Review][Patch] The API suite lacks a transcript-only citation deep-link assertion [server/tests/test_api_chat.py:231]
- [x] [Review][Patch] The API suite does not cover base `ProjectionError` translation for either store [server/tests/test_api_chat.py:652]

**Acceptance Criteria:**
- Given a question POSTed to `/chat` and a projected corpus, when the orchestrator handles it, then it classifies onto a registered traversal template (or records "no template"), retrieves deterministically from Neo4j and/or Meilisearch, and synthesizes through the config-bound `Llm(chat)` port emitting `[[moment:<uuid>]]` markers.
- Given a draft answer whose every marker names a retrieved, Postgres-resident moment, when the validator runs, then the response carries a `citations` array whose `momentId`, `meetingId`, `startMs`, `endMs`, `screenshotId` and `sourceDeepLink` each equal that moment's Postgres row, and the `answer` string contains no `[[moment:` marker.
- Given an answer with any uncited sentence or any unresolvable marker, when validated, then the API emits `422` `application/problem+json` with slug `no-citable-answer` and a `reason`, and no answer text or citation is returned by any surface.
- Given `Accept: text/event-stream` and an answer that passes the gate, when the response is produced, then events arrive named `chat.token`, `chat.citations`, `chat.done`, every token drawn from the already-validated answer.
- Given `Accept: text/event-stream` and an answer that fails the gate, when the response is produced, then the client receives the problem+json rejection and zero `chat.token` events.
- Given the whole server package, when `test_projections_single_writer.py` walks it, then no module under `meetingminer/api/` imports `meilisearch` or `neo4j`.
- Given the full suite `uv run --project server pytest server/tests`, when run with the stores up, then it is green with no regressions against the 1195+ baseline.

## Spec Change Log

## Review Triage Log

### 2026-08-20 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 23: (high 0, medium 12, low 11)
- defer: 2: (high 0, medium 2, low 0)
- reject: 2: (high 0, medium 0, low 2)
- addressed_findings:
  - `[medium]` `[patch]` LIKE metacharacters in model-supplied anchor text were interpolated unescaped — `%` matched every participant and dispatched the traversal onto an arbitrary row. Added `like_contains()` escaping `\ % _` plus `ESCAPE` on both statements.
  - `[medium]` `[patch]` An anchor normalizing to an empty needle became `LIKE '%%'`. Refused as unresolved before querying (`chat.anchor_empty`).
  - `[medium]` `[patch]` The ambiguity guard missed two *equally* exact matches, silently resolving to the first row. Guard is now `rows[0][2] == rows[1][2]`, with an id tiebreak making the two-row window deterministic.
  - `[medium]` `[patch]` A superseded moment was citable: the gate-side `_RESOLVE_MOMENTS` lacked the filter `_read_context` had. Shared `_LIVE_MOMENT` clause now on all three statements.
  - `[medium]` `[patch]` Both `_read_context` drop paths (`chat.stale_hit`, `chat.superseded_moment`) were untested. Tests added, including a mid-flight supersede refused by the gate.
  - `[medium]` `[patch]` `traversal_row_limit` silently kept the OLDEST rows, dropping exactly the recent appearances the classifier prompt advertises `screen-history` for. Now keeps the recent rows and reports `traversalTruncated` on the wire.
  - `[medium]` `[patch]` The 422 body carried no route information, collapsing "unknown anchor" into "nothing found" — the distinction the intent requires on the wire. `_reject` now carries the route object; tests assert `anchorResolved is False` and the null branch.
  - `[medium]` `[patch]` `screen-history` was never dispatched end to end — half the AD-7 surface could be non-functional with a green suite. Mirror test added over two meetings sharing a screen.
  - `[medium]` `[patch]` Nothing asserted moment text reached the synthesis prompt; breaking the transcript join left every test green. Seeded phrase, speaker label and meeting date now asserted.
  - `[medium]` `[patch]` Neither retrieval knob was exercised — deleting the slice kept the suite green. Both now shown to bound.
  - `[medium]` `[patch]` Chat's `_embed` degrade/refuse split was untested; `EmbedderUnavailableError` subclasses `EmbedderError`, so a clause reorder would 503 every question while `/search` kept degrading. Pair added.
  - `[medium]` `[patch]` `LLM_CALL_SITES` states its own failure mode and nothing enforced it — the money guard. AST walk added asserting every production `build_llm` caller is listed.
  - `[low]` `[patch]` Exact and contains legs covered different columns asymmetrically. Contains legs widened to match.
  - `[low]` `[patch]` A superseded-only corpus still billed a classifier call. `_ANY_MOMENT` now ignores superseded rows.
  - `[low]` `[patch]` A refused traversal input reported as an unknown anchor. Now `traversalOutcome: "input-refused"` with `anchorResolved: null`.
  - `[low]` `[patch]` The chat model 503 taxonomy was documented and asserted nowhere. Parameterized over both exception classes and both call sites.
  - `[low]` `[patch]` The synthesis prompt was unbounded. `MOMENT_TEXT_MAX_CHARS` / `PROMPT_MOMENTS_MAX_CHARS` with a `chat.prompt_cropped` log.
  - `[low]` `[patch]` The prompt gave the model no way to tell two same-titled recurring meetings apart. Block headers now carry the meeting date, using the previously dead `started_at` column.
  - `[low]` `[patch]` Logging: `below_floor` was discarded, `chat.index_missing` mislabelled the classifier terms as `question`, and `chat.completed` recorded no elapsed time (NFR4 unobservable). All three fixed.
  - `[low]` `[patch]` `test_every_rejection_reason_is_camel_free_and_closed` did not test kebab-case. Renamed and now checks it by regex.
  - `[low]` `[patch]` `strip_markers` collapsed all interior horizontal whitespace, not just the gap a marker left. Narrowed to the removed marker's position.
  - `[low]` `[patch]` Neither config surface recorded that `api.search`'s knobs also govern what the chat model sees. Documented in both.
  - `[low]` `[patch]` The reconciliation between the matrix's two `no-evidence` rows was unrecorded. Added to Design Notes.

Patched severity counts: high 0, medium 12, low 11. Score = 3x12 + 1x11 = 47, which is 5 or more, so `followup_review_recommended` is true.

Rejected (dropped): the sentence splitter's handling of decimals and abbreviations (the terminator-followed-by-whitespace guard already covers it); `ProjectionError` out of `run_template` reported under a store 503 slug (unreachable — `parse_route` only ever emits registered names with exact parameter sets).

## Design Notes

**The gate is a sentence rule, and it is deliberately blunt.** Deciding "is this sentence a factual claim" is a model judgment, and a model judgment cannot be the enforcement mechanism for "no citation, no answer" (AD-6 says the validator, not the prompt, enforces it). So the rule is mechanical: every sentence unit with alphanumeric content needs a marker. The synthesis prompt is written to that rule, so a compliant model produces compliant prose. *Assumption to attack: a well-formed answer may legitimately want an uncited connective sentence ("Here is what the corpus shows:"), and this rejects it; the alternative — a claim classifier — puts a model back inside the gate, which is the thing AD-6 forbids.*

**Validate first, stream second.** The SSE surface exists here rather than in 3.4 because 3.4's boundary is `web/` and this wave's API story is this one. Tokens are chunks of the validated answer, replayed — so the port needs no streaming method and no unvalidated draft can reach the wire. Content negotiation on `Accept` keeps one endpoint: JSON for the eval harness (AD-16 asserts against the structured array) and SSE for the browser. *Assumption to attack: content negotiation on one route versus two routes; two would duplicate the whole orchestration path or force one to proxy the other.*

**The router is a model classifying and code dispatching.** The model returns JSON naming a template and its anchors *in natural language* ("Rowan", "the vendor portal screen"); deterministic code resolves those to Postgres-minted UUIDs and calls `run_template`. 3.2 recorded exactly this split (`_input_uuid`: "name-to-id resolution is the router's job"). Anything the registry does not recognize degrades to search-only rather than raising. *Assumption to attack: the search leg runs on every question, including ones a traversal answered completely — that costs one Meilisearch round trip and buys a non-empty retrieval when classification is wrong.*

**The orchestrator lives in `api/`, not in a new top-level package.** The spine's component diagram names a "chat orchestrator", but its module structure permits `api → projections` and `api → adapters` and lists no such package. `api/search.py` already reaches a store through `projections` without importing a store client; chat follows it. *Assumption to attack: a reviewer may prefer `meetingminer/chat/`; the AST single-writer test passes either way, and this keeps the wire shape and its orchestration adjacent.*

**Rejection carries a reason, and the reason is a closed set.** 3.4 renders one "no citable answer" state, but an operator needs to tell "the corpus had nothing" from "the model cited a moment that does not exist". A camelCase `reason` extension on the problem body says which, matching the `maxLimit`/`jobId` precedent.

**"No model call" on an empty retrieval means one call, not zero, once the corpus is populated — recorded here because the matrix and the unknown-anchor row pull in opposite directions.** The matrix's *Empty retrieval* row asks for `no-evidence` with no model call made; its *Unknown traversal anchor* row asks for the unresolved anchor to be reported, and the anchor is only known because the classifier — itself a model call — ran. Both cannot hold for the same request. The implementation splits them at the point where the difference is provable without a model: a `SELECT EXISTS` over live (non-superseded) `moment` rows. A corpus that can cite nothing is refused with **zero** model calls, which is the *Empty retrieval* row's substance — no money is spent on a question nothing could answer. A populated corpus whose retrieval comes back empty pays for **one** call, the classification, and none for synthesis, which is what the *Unknown traversal anchor* row requires and what that row's "Refused before synthesis" column already says. The route information — `traversalOutcome`, `anchorResolved` — is carried on the 422 body in both cases, so the two refusals are distinguishable on the wire rather than only in the log.

## Verification

**Commands:**
- `cd <worktree> && uv run --project server pytest server/tests/test_chat_citations.py server/tests/test_chat_router.py` -- expected: green, store-free, no model call.
- `cd <worktree> && uv run --project server pytest server/tests/test_api_chat.py` -- expected: green with the Docker stores up; named skips when down.
- `cd <worktree> && uv run --project server pytest server/tests/test_projections_single_writer.py server/tests/test_config.py server/tests/test_api_search.py` -- expected: green — the new api modules and the config knob regress neither.
- `cd <worktree> && uv run --project server pytest server/tests` -- expected: full server suite green (1195+ baseline), no regressions.
- `cd <worktree> && make web-test` -- expected: green; only relevant if the generated TS client is regenerated.

**Manual checks (if no CLI):**
- `POST /chat` against a projected corpus returns citations whose `momentId`s also resolve through `GET /moments/{id}`.

## Auto Run Result

Status: done
Blocking condition: none

### What was implemented

The chat path the spine fixes, as `POST /chat`: a model classifies the question
onto 3.2's `TRAVERSAL_TEMPLATES` while deterministic code resolves the anchors
against Postgres and dispatches (nothing unregistered ever reaches Neo4j);
retrieval runs the traversal leg and 3.1's `search_moments` and unions them;
`Llm(chat)` synthesizes over the retrieved moments emitting `[[moment:<uuid>]]`
markers; and a store-free validator rejects the whole answer unless every
sentence carries a marker and every marker names a retrieved moment that still
resolves in Postgres. Citations are re-read from the database of record and
carry exactly AD-15's six camelCase fields. The response is `ChatResponse` JSON
or, on `Accept: text/event-stream`, `chat.token` / `chat.citations` /
`chat.done` replayed from the already-validated answer — the gate runs before
the representation is chosen, so a rejection is the same RFC 9457 422 on both
paths and the stream never opens.

### Files changed

- `server/meetingminer/api/citations.py` — the gate: marker parsing, sentence
  splitting, and `validate()`; standard library only, no FastAPI import.
- `server/meetingminer/api/chat_router.py` — the classifier prompt and
  `parse_route`, which never raises: every unusable reply degrades to
  search-only with a declared fallback reason.
- `server/meetingminer/api/chat.py` — the orchestrator: anchor resolution, both
  retrieval legs, synthesis, the gate call, and both response representations.
- `server/meetingminer/api/main.py` — registers the chat router after `search`.
- `server/meetingminer/config.py`, `config.yaml` — `api.chat.retrieval_limit`
  and `api.chat.traversal_row_limit`, with the inherited `api.search` knobs
  documented on both surfaces.
- `server/tests/test_chat_citations.py`, `test_chat_router.py` — store-free
  cover for every marker, claim, validator and classification-parsing path.
- `server/tests/test_api_chat.py` — the store-backed suite through the public
  API: both retrieval legs, every rejection reason, the SSE contract, the
  embedder and model failure taxonomies, and the knobs' bounding effect.
- `server/tests/conftest.py` — the autouse money guard now iterates a named
  `LLM_CALL_SITES` list covering both production `build_llm` call sites, with
  an AST walk asserting the list stays complete.
- `server/tests/test_config.py` — bounds cover for the two new knobs.

### Review findings breakdown

23 patches applied (medium 12, low 11); 2 deferred (both medium, in frontmatter
`deferred`); 2 rejected. No intent gaps, no spec-level defects, no loopback.

### Follow-up review recommendation

`true`. Patched counts high 0, medium 12, low 11; score = 3x12 + 1x11 = 47.

### Verification performed

Every command below was run in this worktree and its result observed:

- `uv run --project server pytest server/tests/test_chat_citations.py server/tests/test_chat_router.py` — 58 passed.
- `uv run --project server pytest server/tests/test_api_chat.py` — 40 passed.
- `uv run --project server pytest server/tests/test_projections_single_writer.py server/tests/test_config.py server/tests/test_api_search.py` — 93 passed.
- `uv run --project server pytest server/tests` — 1338 passed (baseline 1195).
- `make web-test` — 157 passed across 9 files.

Matrix test audit: all 13 I/O rows are covered by tests that ran and passed; no
covering test was skipped or filtered out.

### Residual risks

- **The gate's sentence rule over-approximates.** A legitimate uncited
  connective sentence is rejected along with an uncited claim. That is the
  deliberate trade: a claim classifier would put a model back inside the gate,
  which AD-6 forbids.
- **Classification itself is untested end to end.** Because the router is a
  model call, no store-free test can assert that a given question routes to a
  given template without spending money; the tests prove dispatch *given* a
  classification. The Rowan query is exercised only as a hand-written
  classifier reply.
- **NFR7's retrieval-store half is asserted by absence.** No artifact is
  indexed yet, so the published-only rule is proven today only on the Postgres
  context read. It has to be re-proven when 4.4 indexes artifacts.
- **The two deferred items** — the unsynchronized TS client and the union (vs.
  intersection) retrieval for person-scoped questions — are recorded in
  frontmatter `deferred`.
