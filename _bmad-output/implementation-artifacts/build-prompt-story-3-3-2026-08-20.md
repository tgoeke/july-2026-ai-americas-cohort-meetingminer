# Builder handoff — Story 3.3: Cited Q&A with Deterministic Citation Gate

Paste the block below as the `bmad-build-auto` invocation prompt.

Runs independently of story 4-1a — 3.3 is API + retrieval orchestration, 4-1a is
worker-side extraction; no shared files. It is the **only API story in this
wave**, so the `api/main.py` router block is yours alone. Work in a worktree:
`make worktree STORY=3-3`.

---

Implement **Epic 3, Story 3.3 — Cited Q&A with Deterministic Citation Gate**.

The story definition and its acceptance criteria are in
`_bmad-output/planning-artifacts/epics.md` under `### Story 3.3` (line 763). No
story spec file exists yet — planning writes it.

**Canonical contract.** `_bmad-output/specs/spec-meetingminer/SPEC.md` and every
file in its `companions:` frontmatter. Architecture:
`_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md`
— this story is where AD-6, AD-7, AD-8, and AD-15 all converge; read those four
before planning.

## The shape the spine fixes

The chat path is **deterministic router → traversal/search retrieval → LLM
synthesis → deterministic citation validator** (AD-6). *No citation, no answer*
is enforced by the validator in code, never by prompt instructions. Synthesis
emits inline `[[moment:<uuid>]]` markers; the validator resolves every marker
against Postgres and converts to the one structured `citations` array —
`momentId`, `meetingId`, `startMs`, `endMs`, optional `screenshotId`, optional
`sourceDeepLink` for transcript-only meetings (AD-15, quoted in full in the
spine). An answer with any uncited factual claim or unresolvable marker is
rejected — no answer leaves the API. The rejection is a real response shape
(RFC 9457, like the rest of the API): story 3.4 renders it as an explicit
"no citable answer" state, so it must be distinguishable from a transport error.

Validate **before** anything streams. If you expose a streaming surface, the
pinned SSE event names are `chat.token`, `chat.citations`, `chat.done` (story
3.4's AC) and tokens are replayed from the already-validated answer — an
unvalidated draft must never leak token-by-token past the gate. If you instead
deliver a synchronous `POST /chat` and leave the SSE transport to 3.4, record
that boundary in the story spec so 3.4 inherits it explicitly.

## What already exists — consume, don't rebuild

- **Search (3.1, done):** `server/meetingminer/projections/query.py::search_moments`
  — Meilisearch ranks, Postgres cites; every citation field is re-read from the
  database of record; stale hits drop with a `search.stale_hit` log. The
  `api.search.semantic_score_floor` knob (default 0.75) guards the semantic tail.
- **Traversals (3.2, done):** `server/meetingminer/projections/traversals.py` —
  `TRAVERSAL_TEMPLATES` / `run_template` is the registry your router classifies
  onto: `screen-history` and `participant-topic-moments` (the Rowan query).
  3.2 deliberately built **no API surface**; this story is the consumer it was
  built for. Unknown anchor vs. empty result is already structurally distinct
  (anchor `None` vs. empty `rows`) — carry that distinction to the wire, no
  silent zero.
- **LLM port (AD-8):** the `chat` role binding exists in `config.yaml`
  (`llm.roles.chat`: `claude-sonnet-5`, fallback `ollama/qwen3:32b`) typed by
  `LlmConfig` in `server/meetingminer/config.py`, behind
  `server/meetingminer/adapters/llm/`. Model choice stays config-bound, never
  a code constant.
- **Test levers:** `server/tests/projection_seed.py::seed_meeting` already has
  keyword-only `started_at` (3.2 added it anticipating this story) and
  `screen_view_types` (2.3). Fake-LLM fixtures exist in `server/tests/conftest.py`
  (from 4.1) — prefer story-local fixtures over widening the shared block.

## Dispatch note carried from sprint-notes (2026-08-20)

`speakers` is searchable but **not filterable** in the moments index. One line
in the moments index `filterable_attributes` (`config.yaml:298`) plus a
re-projection (`make rebuild`) makes speaker a hard filter. For questions like
"where was Jordan confused", decompose as participant traversal (3.2's registry)
∩ semantic search rather than hoping ranking surfaces the right person.

## Retrieval boundary (NFR7 / SPEC constraint)

Only evidence and `published` artifacts are retrievable; unpublished artifacts
never reach synthesis. Today **zero artifacts are published** (approval is story
4.3, artifact re-indexing is 4.4), so this story's retrieval draws from evidence
moments only — do not wire artifact content into synthesis by any path that
bypasses the published-only rule, and do not build the re-indexing.

## Money and the worker

The Anthropic key is revoked and the standing rule is **no paid model calls
without fresh per-run authorization**. Build and test entirely against fake-LLM
fixtures; the config default binding stays as configured and is exercised live
only when the user says so. The ingestion worker is **stopped by user decision —
do not start it** for any reason; this story needs no worker.

## Verification

- Store-free tests for the router classification, marker parsing, validator
  rejection paths (uncited claim, unresolvable marker, empty retrieval).
- Store-backed tests through the public API proving: a valid answer carries the
  structured citations array with values re-read from Postgres; a poisoned or
  deleted moment id is rejected, not passed through (same discipline as
  3.1's `test_api_search.py`).
- The single-writer property holds: no module under `meetingminer/api/` imports
  `meilisearch` or `neo4j` — extend the existing AST-walk conventions in
  `test_projections_single_writer.py` / the 3.2 boundary tests.
- Full suite green: `uv run --project server pytest server/tests` (1195+ at
  last count). Store-backed suites may overlap other worktrees (2.7 harness).

## Out of scope. Do not widen into any of these

- Story 3.4: `web/src/App.tsx`, the chat UI, citation rendering, replay links.
  Nothing under `web/` changes (client regeneration for the new endpoint is
  fine if the repo convention calls for it — commit what `make client`
  produces, nothing hand-edited).
- Stories 4.2–4.4: prompt visibility, approval/publishing endpoints, artifact
  re-indexing into the retrieval stores.
- Epic 5: the citation-timestamp-window eval check asserts against your
  structured array later; do not build the checker.
- New traversal templates beyond consuming the registry — if a question class
  has no template, that is a router "no template" outcome, not a new Cypher
  statement written mid-story.
- `pull_transcript/` and the extraction pipeline (4-1a is rewriting it
  concurrently — stay out of `pipeline/extraction.py`, `stages/extract.py`,
  and the extraction config block entirely).
