---
title: 'Story 10.4: Moments Feed Ranking'
type: 'feature'
created: '2026-08-31'
baseline_revision: '3211a7f96b86d7df496cefa451b2cbd431e6d8b4'
status: 'review'
review_loop_iteration: 1
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-10-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/build-prompt-story-10-4-2026-08-31.md'
  - '{project-root}/_bmad-output/implementation-artifacts/wave-2026-08-30-rules.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-10-1-topic-extraction.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-10-2-threads-and-the-graph-projection.md'
warnings: []
deferred:
  - 'thread.colorOrdinal is served as null until story 10.3 migration 0017 lands'
---

<intent-contract>

## Intent

**Problem:** Opening the app answers nothing. There is no endpoint that says
which moments need attention, so the front door has to be a search box or a
list of everything (FR40). Two of the signals a reader would rank on — risks
and open questions — are not even stored: the extract stage recognizes `R`
and `O` item IDs in the architecture summary and deliberately drops them,
because `artifact.kind` admits only `adr` and `action-item`.

**Approach:** Two halves. The worker gains a fourth whole-transcript
extraction pass that writes `ranking_signal` rows (migration 0018) — kind
`risk | question`, moment-anchored, worker-owned, replaced on rerun, with no
`state` column because they have no lifecycle. The api gains
`GET /moments/feed`, which scores stored rows with a deterministic pure
function whose every weight lives in `config.yaml` with recorded rationale,
attaches an ordered `reasons[]` to each item, drops and logs anything left
without a valid reason, and only then computes `total`, `offset` and the page.

## Boundaries & Constraints

**Always:**
- **No model call at request time.** The feed reads Postgres and nothing else.
  Every signal it ranks on was written by the worker before the request
  arrived. Asserted by a test that makes `build_llm` raise.
- **The score is a pure function over plain facts.** `score_candidate` takes
  a `FeedCandidate` — frozen dataclasses of ints, strings, UUIDs and
  datetimes — the config weights, and one `now`; it takes no connection and
  performs no I/O. That is what makes it unit-testable without a database and
  reproducible from `config.yaml` plus the stored rows.
- **Every weight is in `config.yaml` with recorded rationale.** Nine weights,
  two windows, four bounds. `RankingWeights`/`RankingConfig` make all of them
  required at load: there is no code-level default for a number that decides
  an order (AD-10), and no ranking constant exists in `api/moments_feed.py`.
- **Reason validation happens BEFORE pagination.** `rank_and_validate` scores,
  validates, drops-and-names, and sorts. It knows nothing about `limit` or
  `offset`; the route slices its output. `total` is therefore always the count
  of rows the caller can actually page through.
- **Every item carries a non-empty ordered `reasons[]`** of
  `{kind, label, ref?, at?}`, ordered by the size of the contribution that
  produced them, with ties broken on the vocabulary order and then the label.
  `kind` is an `ArtifactKind` or one of
  `due | risk | question | recency | published | thread`.
- **An item with no valid reason is dropped and logged** — a
  `moments.feed.item_dropped` event naming the moment and the reason. So is an
  item whose moment does not resolve.
- **Ranking signals are not artifacts.** No `state` column exists on
  `ranking_signal`, no api route transitions one, nothing exports one to
  `MM_PUBLISH_ROOT`, and a rerun replaces a meeting's rows wholesale before
  the stage's early exit — the rule story 10.1 set for `topic`.
- **Media stays ID-addressed (AD-17).** The item carries the opaque
  `screenshotId` and no path; `screenshotPath`, which `GET /moments/{id}`
  still serves for 2.2's renderer, is deliberately absent.
- **`/moments/feed` registers ahead of `moments`.** `ROUTER_ORDER = 35`
  against `moments.py`'s 40 — the literal-under-parameterized hazard
  `api/registry.py` documents by name, using `/moments/recent` as its worked
  example. Pinned in `test_api_registry.py`'s baseline and asserted
  behaviourally.
- **`api/moments.py` is not edited.** Story 2.2 owns it; the feed reads three
  names from it (`PREVIEW_MAX_CHARS`, `ArtifactKind`, `ScreenViewType`) so the
  two routes cannot spell one column two ways.

**Block If:** none — no decision here needed a human.

**Never:**
- No thread curation, no timeline API, no `/media/files/{mediaId}` route
  (story 10.3 territory), no web work (story 10.5), no worker or api start,
  no `make evals-run`, no real model call.
- No `thread.color_ordinal` column. Story 10.3's migration 0017 allocates it
  from a transactional per-corpus sequence and is building in parallel;
  defining it here would put two definitions of one sequence in the tree.
- No `score` field on the wire. The AC enumerates the card's fields and a
  number the client cannot explain is not one of them; the ordered `reasons`
  are the explanation.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Envelope | any corpus | `{items, total, limit, offset}`; each item exactly the AC's fifteen fields | none |
| Ranked order | one moment with an ADR, one merely recent | the ADR moment first, its first reason `kind: adr` | none |
| Soonest first | two action items with stated calendar timing | the nearer date scores strictly higher | none |
| Vague stated timing | `Timing (as stated): after the demo` | earns `action_item_stated_timing`, urgency 0 — never an invented date | none |
| Unstated timing | `Timing (as stated): not stated` | earns nothing; still a reason of kind `action-item` | none |
| Repeated signals | nine risks on one moment | the same score as one risk; at most `max_signal_reasons` reasons | none |
| Recency honesty | meeting 90 days old | no `recency` reason (the term still decays into the score) | none |
| No valid reason | only artifact has a blank title, old meeting | absent from `items`, absent from `total`, `moments.feed.item_dropped` logged | none |
| Unresolved moment | candidate with no moment row joined | dropped, `unresolved-moment` logged | none |
| Paging | 4 scorable + 1 reasonless | `total == 4` on every page; no row served twice or skipped | none |
| Past the end | `offset` beyond `total` | empty `items`, unchanged `total` | none |
| Oversized limit | `limit=100000` | clamped to `ranking.max_limit` | none |
| Filters | `corpus` / `meeting` / `thread` / `kind` | only matching items; `total` matches the filtered set | 422 on a malformed UUID or unknown corpus |
| Unknown kind filter | `kind=astrology` | empty page, `total: 0` | never a 500 |
| Superseded moment | provenance `superseded: true` | never served | none |
| Quiet old moment | old meeting, nothing stored about it | not a candidate at all | none |
| Signals parser | `R1`/`Q1` rows | `risk`/`question` by ID prefix, not by heading | `ArtifactParseError` naming the item |
| Stray commitment | `A9` row in the signals document | structure, never a signal | none |
| Blank label | `R1` with an empty Risk cell | refused by name | `ArtifactParseError` |
| Rerun | extract runs twice | the meeting's signals replaced wholesale | none |
| Superseded anchor | signal anchored to a superseded moment | skipped and named | none |

## Code Map

- `server/meetingminer/api/registry.py` -- READ-ONLY. Its docstring names this
  exact hazard: "a future `/moments/recent` would be swallowed ... give its
  module a `ROUTER_ORDER` below the parameterized module's."
- `server/meetingminer/api/moments.py` -- READ-ONLY (story 2.2). Source of
  `PREVIEW_MAX_CHARS` (300), `ArtifactKind` (the seven-kind forward contract)
  and `ScreenViewType`.
- `server/meetingminer/api/search.py` -- READ-ONLY. `Corpus` literal reused so
  the corpus vocabulary keeps one spelling; `Annotated[..., Query(...)]` is
  the house shape for filters.
- `server/meetingminer/migrations/0014_topics.sql` / `0015_threads.sql` --
  READ-ONLY. The shape 0018 mirrors: worker-owned header, `uuidv7()` PK,
  `set_updated_at` trigger, the composite `(moment_id, meeting_id)` edge.
- `server/meetingminer/pipeline/stages/extract.py` -- the topics pass (~line
  510) is the model the ranking-signals pass follows exactly: always
  generated, never adopted, same port, same `_generate` one-retry discipline,
  same `_UPSERT_EXTRACTION_SOURCE` row.
- `server/meetingminer/pipeline/extraction.py` -- `_kind_for` decides an item
  ID's kind per document; `_topic_title_and_body` is the precedent for a
  required-fields reader rather than a title heuristic.
- `server/tests/projection_seed.py` -- READ-ONLY. `seed_meeting` and
  `insert_artifact` are the seeding entry points the feed tests use.

## Tasks & Acceptance

**Execution:**
- `server/meetingminer/migrations/0018_ranking_signals.sql` -- NEW: the
  `ranking_signal` table, its two indexes, its `updated_at` trigger, and the
  `extraction_source.kind` CHECK widened for the fourth document.
- `server/meetingminer/config.py` -- ADD `RankingWeights` and `RankingConfig`
  immediately before `class Settings`, and `ranking: RankingConfig` as the
  last field of `Settings`.
- `config.yaml` -- APPEND the `ranking:` block at EOF: nine weights, two
  windows, four bounds, the signals prompt, each with recorded rationale and
  an explicit statement that none of the values are measured.
- `server/meetingminer/pipeline/extraction.py` -- ADD `KIND_RISK`,
  `KIND_QUESTION`, `RANKING_SIGNAL_KINDS`, `DOC_RANKING_SIGNALS`,
  `build_signals_prompt`, `_SIGNAL_PREFIX_KINDS`, `_signal_label_and_detail`,
  `signal_detail`, and the three dispatch arms.
- `server/meetingminer/pipeline/stages/extract.py` -- ADD the delete, the
  insert, the pass itself, and the two summary counters.
- `server/meetingminer/api/moments_feed.py` -- NEW: the wire models, the
  candidate dataclasses, the pure scorer, `validate_reasons`,
  `rank_and_validate`, the candidate query and the route.
- `server/tests/test_ranking_signals.py` -- NEW: the parser and the pure
  ranker, store-free.
- `server/tests/test_api_moments_feed.py` -- NEW: the wire contract and the
  validate-then-page order, Postgres-backed.
- `docs/backlog.md` -- ADD B-46.

**Acceptance Criteria:**
- Given a corpus with artifacts, ranking signals, threads and recent
  meetings, when `GET /moments/feed` is called, then it returns
  `{items, total, limit, offset}` with each item carrying exactly the AC's
  fifteen fields and a non-empty ordered `reasons[]`.
- Given a moment whose only signal produces no renderable reason, when the
  feed is served, then it is absent from `items`, not counted in `total`, and
  named in a `moments.feed.item_dropped` log line — demonstrated red against a
  build that counted `total` from the candidate scan.
- Given five candidates of which one is reasonless, when the feed is paged two
  at a time, then every page reports `total: 4` and the union of the pages is
  four distinct moments with none repeated and none skipped.
- Given two action items with stated calendar timing, when they are scored,
  then the nearer date scores strictly higher, and an item whose timing the
  transcript never stated scores zero for timing.
- Given the extract stage runs, then `ranking_signal` rows appear for `R`/`Q`
  items, a rerun replaces them, and no `artifact` row and no publish path is
  involved.
- Given `make test-fast`, then `make lint` and `make typecheck` pass with no
  new ruff baseline entry.

## Spec Change Log

- **2026-08-31, implementation — `server/meetingminer/config.py` edited,
  outside the footprint table, deliberately and on the record.** The AC
  requires every weight to live in `config.yaml` with recorded rationale, and
  `Settings` is a `_StrictModel` with `extra="forbid"`: a new top-level YAML
  block that no field declares is refused at load. Delivering the AC without
  touching `config.py` is therefore not possible. The edit is additive — two
  classes immediately before `class Settings`, one field appended to its list
  — and is the same edit story 10.2 made for `threads:`. Story 11-2, whose
  footprint claimed `config.py` lines 750–1010, has landed on `main`;
  `branch_conflicts.py` reports clean against every branch in flight.
- **2026-08-31, implementation — `server/tests/conftest.py` edited, one
  line, forced by the gate rather than by planning.** `EVIDENCE_TABLES` gains
  `ranking_signal`. `TRUNCATE` refuses to empty a table another one
  references however that reference cascades on DELETE, so without the name
  the `moment` truncation is refused and **every** store-backed test in the
  suite fails. Not optional and not avoidable in a private module — story
  10.2 hit the identical wall with `thread`/`topic_thread` and recorded it
  the same way.
- **2026-08-31, implementation — three shared test modules edited, each
  because my change makes a fact they assert untrue.** `test_config.py`'s
  `VALID_CONFIG` gains the `ranking:` block (a required config section);
  `test_worker_extract.py` and `test_extraction_topics.py` count one more
  model call and one more `extraction_source` kind now that a fourth document
  is generated; `test_api_registry.py`'s `BASELINE_ROUTER_ORDER` gains
  `moments_feed` ahead of `moments`. No new test was appended to any of them.
- **2026-08-31, planning — `ranking.signals_prompt` is not under
  `llm.roles.extraction`.** The other three extraction prompts are fields on
  `ExtractionRoleBinding`, and this one architecturally belongs beside them.
  It is not there because the frozen footprint gives story 10.4 the END of
  `config.yaml` and gives the `llm:` block to nobody, and editing a block
  another lane may hold is the widening the wave rules forbid. The port is
  unchanged — the stage still calls `Llm(extraction)` — and the value is
  still versioned configuration with recorded rationale, so no AC is
  weakened. Filed as **B-46**, and named in the review prompt as a
  first-class candidate for the review lane to relocate.
- **2026-08-31, planning — deferred: `thread.colorOrdinal` is served as
  `null`.** The AC requires `threads[]{threadId,name,colorOrdinal}` and the
  column lands with story 10.3's migration 0017, in parallel. The field is on
  the wire with the right name and type today; the query reads it as
  `to_jsonb(t) ->> 'color_ordinal'`, which yields no key when the column does
  not exist, so the real ordinal appears the moment 0017 is applied with no
  edit to this story's code. Naming the column directly would make the query
  a syntax error on this branch; adding the column here would put two
  definitions of one per-corpus sequence in the tree (B-40 is 10.3's).
- **2026-08-31, planning — scoring is per kind, not per row.** The `risk` and
  `question` weights are earned once however many rows there are, and the
  `adr`/`decision` weights once per kind. A count-multiplied term would let
  one talkative meeting hold the whole front door;
  `max_signal_reasons` bounds the reasons shown, not the score. The
  `config.yaml` comment says so, and a test pins it.

## Review Triage Log

### Review Findings — 2026-08-31

- [ ] [Review][Decision] F9 — Offset pages have no stable ranking snapshot
  across requests. Each request chooses a new `now`; fixing multi-request
  duplicate/skip behavior requires an `asOf`, cursor, or an explicit contract
  relaxation, all of which are frozen-wire decisions.
- [x] [Review][Patch] F1 — Recency contributions disappear after one half-life
  instead of decaying. [`server/meetingminer/api/moments_feed.py:472`]
- [x] [Review][Patch] F2 — Multiple timed action rows multiply a categorical
  weight. [`server/meetingminer/api/moments_feed.py:408`]
- [x] [Review][Patch] F3 — Thread count, invalid names, and uncapped wire chips
  violate the thread contract. [`server/meetingminer/api/moments_feed.py:517`]
- [x] [Review][Patch] F4 — Timed action items disappear from the
  `kind=action-item` feed. [`server/meetingminer/api/moments_feed.py:408`]
- [x] [Review][Patch] F5 — Free-text timing parsing both misses and invents
  urgency. [`server/meetingminer/api/moments_feed.py:247`]
- [x] [Review][Patch] F6 — The production extraction-to-feed handoff and
  replacement rules are unverified.
  [`server/meetingminer/pipeline/stages/extract.py:653`]
- [x] [Review][Patch] F7 — Ranking configuration accepts infinity.
  [`server/meetingminer/config.py:933`]
- [x] [Review][Patch] F8 — Conflicting duplicate signal IDs are silently
  discarded. [`server/meetingminer/pipeline/extraction.py:1112`]

### Remediation result — 2026-08-31

- intent_gap: 1 (F9, open owner decision)
- bad_spec: 0
- patch: 8 (high 2, medium 6), all resolved red-first or as explicitly named
  coverage-only work
- defer: 0
- reject: 12 deduplicated/already-known candidates
- addressed_findings:
  - F1-F8 are fixed on `story/10-4-review`; exact commits and red/green evidence
    are recorded in the review report.
  - B-46 is closed: `ranking_signals_prompt` now lives on
    `llm.roles.extraction`, the stage reads it through `_PROMPT_FIELD`, and the
    backlog entry was removed.
  - A thread-bearing feed item is the normal API test case. The bigint text
    conversion is pinned beyond 32 bits; true migration 0017 integration still
    waits for Story 10.3 to land on `main`.

Status remains `review`, not `done`: F9 is an unresolved frozen-wire decision,
`make client` remains integration-owned, and this lane is forbidden to merge.

## Design Notes

**Why validation and pagination are two functions, not two statements.**
Getting the order backwards is the failure the AC calls out, and a comment
saying "validate first" is not a mechanism. `rank_and_validate` takes no
`limit` and no `offset`, so the wrong order is not expressible inside it; the
route can only slice what it returns. The proof this is load-bearing is
recorded: a deliberately wrong build that computed `total` from the candidate
scan failed four tests, including both `kind`-filter tests, which is the same
bug seen from another angle.

**Why a candidate scan rather than every moment.** A moment nothing is stored
about has nothing to put on a card, so the query only scans moments carrying
an artifact, a ranking signal, or a thread membership, or belonging to a
meeting inside one recency half-life. That is also what bounds the query on a
corpus of hundreds of meetings, and it is what makes the drop-and-log path
real rather than theoretical: without it every moment would earn a `recency`
reason and nothing could ever be dropped.

**Why a `recency` reason is emitted only inside one half-life.** The term
always decays into the score, but claiming "recent" on a card for a
two-month-old meeting would be saying something untrue to the reader. The
threshold is the config's own half-life rather than a new constant.

**Why "soonest first" is linear and clamped.** A deadline does not decay, it
arrives — so urgency falls linearly to zero at `due_horizon_days` rather than
exponentially. Overdue clamps to 1.0 rather than growing without bound:
something three months late is not thirty times more urgent than something
due tomorrow, and letting it grow would park one forgotten row at the top of
the feed forever.

**Why the timing text is read from a labelled line only.** The action-items
prompt is explicitly forbidden from converting "next week" into a calendar
date, so a date appearing anywhere in the body is as likely to be a
dependency's date as the item's own. `stated_timing` reads only the line
whose label matches `timing|due|deadline|when|by`, which is what
`_title_and_body` writes.

## Verification

**Commands:**
- `make test-fast` -- `check-client`, `make lint`, `make typecheck`, the three
  store-free suites and the server fast set.
- `uv run --project server pytest server/tests/test_ranking_signals.py server/tests/test_api_moments_feed.py -q`
- `make test` -- the full gate with the private stack up.
- `python3 _bmad/scripts/branch_conflicts.py --against story/10-4`

## Auto Run Result

_(filled in below at completion.)_

</intent-contract>
