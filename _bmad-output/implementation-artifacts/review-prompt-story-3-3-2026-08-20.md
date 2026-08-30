# Reviewer handoff — Story 3.3: Cited Q&A with Deterministic Citation Gate

Paste everything below the rule into the Codex `bmad-code-review` agent. You
have none of the build run's context; this file is self-contained.

---

## THE REQUIRED OUTPUT — READ THIS FIRST, ACT ON IT FIRST

**Your review is not done until a report file exists in git.** Six reviews in
this repository produced their findings only as terminal text and were lost.
This section is first so it cannot be compacted out of your context by the time
you finish.

**Report path (exact):**
`_bmad-output/implementation-artifacts/review-story-3-3-2026-08-20.md`

**Finding structure — every finding, no exceptions:**

- **Location** — `path:line`
- **Severity** — high | medium | low
- **Finding** — what is wrong, in one or two sentences
- **Evidence** — why it is real: the code path, the input that reaches it, the
  observable consequence. A finding with no evidence is a guess.
- **Suggested direction** — what a fix would have to achieve. Not a patch.

**Report findings; do not fix them.** No source file changes. The only file you
write is the report.

**REPORT-FIRST — do this before you read a single line of code:**

1. Create the report file as a skeleton: the scope, the review range, and an
   empty findings section.
2. `git add` that one path and commit it.
3. Append each finding to the file **as you confirm it**, and commit
   incrementally.

A crashed or closed session must lose your prose, never the artifact.

**Closeout check, before you report completion:**

- Run `make check-reviews`. It fails while any dispatched review lacks a
  committed report — including this one.
- State the SHA that carries the report's final version.

A review reported in the terminal but not filed does not exist.

---

## Repo, branch, range

- **Repo:** `/Users/devopsterus/current/cohort/meetingminer` (the story branch
  is also checked out at `/Users/devopsterus/current/cohort/meetingminer-wt/3-3`)
- **Branch:** `story/3-3`, pushed to `origin/story/3-3`
- **Review range:** `e94bea85eb165da1c422ae4f1ead66c2d60e3991..HEAD`

Commits in the range, oldest first — **all nine belong to story 3.3**; no
other story's work is mixed in:

| Revision | Subject |
|---|---|
| `f8f220d98ac0091462903d2da88e82598ebfdf67` | docs(3-3): story spec for cited Q&A with the deterministic citation gate |
| `caec004eb51fe785c2bd6bae9969aa5b6c080d96` | docs(3-3): spec status in-progress |
| `88d81f3dd3dd063f3308cbf19b2190375b49b469` | feat(3-3): cited Q&A — POST /chat with the deterministic citation gate |
| `70b3bdbfc7406058179284d810ee9ba1501ca521` | test(3-3): store-backed POST /chat suite, and the search leg queries the classifier's terms |
| `7fb762315a0d0fc3ebcda46eee4c0251244e53c6` | docs(3-3): describe the SSE representation on the /chat 200 response |
| `a88457fefabcd7ac2d367f2ce5bfd511dc0cc3c6` | fix(3-3): anchor resolution, the superseded clause, and truncation on the wire |
| `93c312401444260cacf3928e80376c1a1314528e` | test(3-3): close the gaps that let real defects ship green |
| `0ed257b7652d4b569cf0d3c6a50f7589ad585a47` | docs(3-3): record how the two no-evidence rows of the matrix reconcile |
| `063c73fe8074aad78cd992bc958cf1d9a07705ab` | docs(3-3): review triage, deferred items, and the auto-run result |
| `0098a9691c72f3434e8a582d2ea2b1176c677afe` | docs(3-3): reviewer handoff prompt (this file) |

One commit in the range touches a file that is not story 3.3's product:
`f8f220d` also regenerates
`_bmad-output/implementation-artifacts/epic-3-context.md`. That regeneration is
build-workflow bookkeeping (the cached epic context had gone stale against the
planning tree), not story content. Skim it; do not review it as a deliverable.

## The spec, and which half of it you may attack

`_bmad-output/implementation-artifacts/spec-3-3-cited-qa-citation-gate.md`

- Everything inside the `<intent-contract>` block — **Intent**, **Boundaries &
  Constraints**, **I/O & Edge-Case Matrix** — is **frozen intent**. Judge the
  code against it. Do not treat a constraint there as a planner opinion.
- Everything outside it — **Code Map**, **Tasks & Acceptance**, **Design
  Notes**, **Verification**, **Auto Run Result** — is planner work and is fair
  game. The Design Notes in particular are where the planner argued for calls
  it is not a neutral judge of; several are listed below for you to attack.

## Architecture authority

`_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md`

Four decision records govern this change specifically. Read these four, not the
whole spine:

- **AD-6 — Citations are Postgres-minted moment IDs, gated in code.** The chat
  path is router → retrieval → synthesis → deterministic validator. "No
  citation, no answer" is enforced by the validator, *not* by prompt text. This
  is the story's reason to exist; a finding that the gate can be bypassed is
  the highest-value finding you can produce.
- **AD-7 — GraphRAG is deterministic traversal templates.** Hand-written
  parameterized Cypher only; the model's only two jobs are classifying onto a
  template and synthesizing. No library may build or own graph structure.
- **AD-8 / AD-10 — All model calls go through configured ports.** The chat
  model comes from `llm.roles.chat` in `config.yaml` via `build_llm`. A model
  id as a code constant is a violation.
- **AD-15 — One citation wire format.** Synthesis emits `[[moment:<uuid>]]`;
  the API returns a structured `citations` array (`momentId`, `meetingId`,
  `startMs`, `endMs`, optional `screenshotId`, optional `sourceDeepLink`). The
  web app renders from the array and never parses markers.

Also binding, from `AGENTS.md` and AD-4: **no module under
`server/meetingminer/api/` may import `meilisearch` or `neo4j`.**
`server/tests/test_projections_single_writer.py` asserts it by AST walk.

## Scope

**In scope — the files this story owns:**

- `server/meetingminer/api/citations.py` (new) — the gate
- `server/meetingminer/api/chat_router.py` (new) — classification parsing
- `server/meetingminer/api/chat.py` (new) — the orchestrator and the route
- `server/meetingminer/api/main.py` — router registration
- `server/meetingminer/config.py`, `config.yaml` — the `api.chat` block
- `server/tests/test_chat_citations.py`, `test_chat_router.py`,
  `test_api_chat.py` (all new)
- `server/tests/conftest.py` — the widened no-real-model guard
- `server/tests/test_config.py` — bounds cover for the two new knobs

**Explicitly out of scope — do not report as missing:**

- Story 3.4: the chat UI, citation rendering, replay links, anything under
  `web/` that is hand-written.
- Stories 4.2–4.4: prompt visibility, approval/publishing endpoints, artifact
  re-indexing.
- Epic 5: the citation-timestamp-window eval check.
- New traversal templates or new Cypher. A question class with no template is a
  router "no template" outcome by design.
- `pull_transcript/`, `pipeline/extraction.py`, `pipeline/stages/extract.py`
  and the extraction config block — story 4-1a is rewriting them concurrently.
- The two items already recorded in the spec's frontmatter `deferred` list:
  the unsynchronized TypeScript client, and union-rather-than-intersection
  retrieval for person-scoped questions. Both are known; re-reporting them
  costs a triage pass. **New** consequences of either are worth reporting.

## Design decisions to attack

These are the planner's calls. Each is stated as the choice plus the assumption
it rests on. The planner is not a neutral judge of them.

1. **The gate is a sentence rule, deliberately blunt.** Every sentence unit
   containing an alphanumeric character must carry at least one marker, or the
   entire answer is rejected. *Assumption:* that over-approximating is correct
   because the alternative — classifying which sentences are factual claims —
   puts a model back inside the gate, which AD-6 forbids. *Attack:* can a
   compliant model produce prose this rejects? Can a non-compliant model
   produce prose this *accepts* that still contains an uncited claim — a
   sentence carrying a marker for a moment that does not support it? The gate
   proves a citation is *present and resolvable*, never that it is *apposite*.
   That limit is real; decide whether it is stated honestly.

2. **Validate first, stream second, one endpoint, content-negotiated.**
   `POST /chat` returns JSON, or SSE when `Accept: text/event-stream`. Tokens
   are chunks of the already-validated answer. *Assumption:* that this keeps
   one orchestration path for both the eval harness (AD-16 asserts against the
   structured array) and the browser, and that the `Llm` port needs no
   streaming method. *Attack:* whether the negotiation is honest under a
   compound or wildcard `Accept` header; whether a POST-based SSE surface is
   actually usable by story 3.4 (`EventSource` cannot POST, so 3.4 needs a
   fetch-based reader) and whether that is recorded anywhere 3.4 will look.

3. **The model classifies; code dispatches.** `parse_route` never raises;
   anything unregistered degrades to search-only. Anchors arrive as natural
   language and are resolved to Postgres UUIDs by SQL in `chat.py`. *Assumption:*
   that this satisfies both AD-6's "deterministic router" and AD-7's "the LLM
   classifies". *Attack:* the anchor-resolution SQL is the seam where
   model-supplied text meets the database — it was already found once to
   interpolate unescaped LIKE metacharacters. Look again, hard.

4. **The orchestrator lives in `api/`, not a new top-level package.** The
   spine's component diagram names a "chat orchestrator" but its module
   structure lists no such package, and `api/search.py` already reaches a store
   through `projections` without importing a store client. *Assumption:* that
   following the `search.py` precedent beats adding a package the spine does
   not name. *Attack:* whether `chat.py` at its current size is one module's
   worth of responsibility.

5. **Rejection carries a closed-set `reason`.** 422 problem+json, slug
   `no-citable-answer`, plus a camelCase `reason` and the route object.
   *Assumption:* that 3.4 renders one state while an operator can still tell
   "the corpus had nothing" from "the model cited a moment that does not
   exist". *Attack:* whether 422 is the right status for "the system could not
   produce a citable answer", and whether the route object on an error body
   leaks anything it should not.

6. **The search leg queries the classifier's `searchTerms`, not the raw
   question.** Measured during the build: Meilisearch's `last` matching
   strategy drops trailing query words first, and an English question puts its
   subject last — "what happened with the purchase order?" returned 0 hits
   against the moments index while "purchase order" returned 1. *Attack:*
   whether making retrieval depend on a model-produced query string is
   acceptable given AD-6's "deterministic" framing, and what happens when the
   classifier returns poor terms.

## History you need to tell a regression from a pre-existing condition

- **This branch has been through one adversarial review pass already.** Four
  review layers ran against the range and produced 27 findings; 23 were applied
  as patches (commits `a88457f`, `93c3124`, `0ed257b`), 2 deferred, 2 rejected.
  The full triage, with each finding and the action taken, is in the spec's
  `## Review Triage Log`. **Read it before you start** — a finding already
  listed there as fixed is either genuinely fixed or a regression in the fix,
  and those are very different reports.
- **Two findings were rejected, with reasons.** (a) The sentence splitter and
  decimals/abbreviations — the terminator-followed-by-whitespace guard already
  covers it. (b) `ProjectionError` from `run_template` surfacing under a store
  503 slug — unreachable, because `parse_route` only ever emits registered
  template names with exact parameter sets. If you think either rejection was
  wrong, say so with the input that reaches the path.
- **No rebase, no dropped variant, no superseded baseline.** The range is
  linear from `e94bea8`, which is `main` at dispatch time.
- The `_no_real_llm` autouse guard in `conftest.py` was widened from a single
  hard-coded call site to a `LLM_CALL_SITES` list. That is a deliberate
  widening of a shared fixture: the guard's purpose is that no test reaches a
  paid provider, and `/chat` added a second production `build_llm` call site.

## Verification baseline

These are the current results, observed on this branch. A skip or a failure you
see during review is a **finding**, not noise.

| Command | Current result |
|---|---|
| `uv run --project server pytest server/tests/test_chat_citations.py server/tests/test_chat_router.py` | 58 passed |
| `uv run --project server pytest server/tests/test_api_chat.py` | 40 passed |
| `uv run --project server pytest server/tests/test_projections_single_writer.py server/tests/test_config.py server/tests/test_api_search.py` | 93 passed |
| `uv run --project server pytest server/tests` | **1338 passed**, 0 failed |
| `make web-test` | 157 passed, 9 files |

Notes on running them:

- The store-backed suites need the Docker stores up (`make infra-up`). Since
  story 2.7 they are safe to run while another agent's suite runs; the handful
  of projection tests queue on a cross-worktree file lock rather than
  interleaving. `test_parallel_store_safety.py::test_projection_lock_times_out_with_holder_details_then_releases`
  is the one test that can fail when another agent holds that lock — it asserts
  the holder file names its own subprocess. It passes in isolation.
- **`make evals-run` is still serial. Do not run it.**
- **The ingestion worker is stopped by user decision. Do not start it.**
- **No paid model call.** The Anthropic key is revoked and the standing rule is
  no paid calls without fresh per-run authorization. Every test binds a fake
  `Llm`; if you find a path that could reach a real provider from a test, that
  is a high-severity finding.
