# Builder handoff — Story 10.1: Topic Extraction

Agent: `bmad-build-auto`. Read `wave-2026-08-30-rules.md` in this directory
first; it carries the wave-wide rules and the conflict check you must pass.

- Repository: `/Users/devopsterus/current/cohort/meetingminer`
- Worktree: `/Users/devopsterus/current/cohort/meetingminer-wt/10-1`, branch `story/10-1`
- Story: `_bmad-output/planning-artifacts/epics.md` → "Story 10.1: Topic
  Extraction" (FR41). Three Given/When/Then clauses; derive the spec from
  them. Threads (10.2), curation (10.2a) and the UI stories are NOT in scope.
- Context: the Epic 10 addendum in
  `_bmad-output/planning-artifacts/sprint-change-proposal-2026-08-29.md`;
  story 4.1a / 4.2 specs for the whole-transcript extraction pattern and the
  visible-prompt contract this story extends; `docs/architecture.md` AD-8 (one
  `Llm(extraction)` port), AD-2 (Postgres is the record), AD-4 (one writer).
- Why now: 10.1 is the root of an eight-story chain and touches nothing the
  other lanes touch.

## Footprint — the only files and regions you may change

| Path | Allowed edit |
|---|---|
| `server/meetingminer/config.py` | `topics_prompt: NonEmptyText` added directly after `action_items_prompt` inside `ExtractionRoleBinding` (main line 189). No other line. |
| `config.yaml` | `topics_prompt:` added directly after `action_items_prompt` inside `llm.roles.extraction`. Wording covers meetings and recorded sessions alike (story 6.7's generalisation). Nothing else. |
| `server/meetingminer/pipeline/extraction.py` | The topics document kind and its strict parser: name, one-line gist, `[m:ss]` anchors → containing moment; an anchor outside the timeline fails by name; zero topics on a meeting with content is a signal, not success. |
| `server/meetingminer/pipeline/stages/extract.py` | The third pass through the same port and parser; rerun replaces rows. |
| `server/meetingminer/api/extraction.py` | Serve the third prompt (`kind="topic"`) beside the two existing ones. |
| `server/meetingminer/migrations/0014_topics.sql` | NEW. `topic` and `topic_mention` anchored to moments; worker-owned, machine-derived, labelled as such; not artifacts, never in the `extracted → approved → published` lifecycle. |
| `server/meetingminer/domain/` or `projections/` | Only NEW modules if the record needs a reader; nothing projects to Neo4j/Meilisearch in this story (10.2 does). |
| `web/src/features/<extraction-prompts feature>/` | Only if the prompts screen enumerates kinds by hand: make it render whatever the endpoint returns, with its test. If the OpenAPI schema changes, regenerate `web/src/client/` from the in-process schema (as story 2.2 did) — never point `make client` at :8000. |
| `docs/architecture.md` | A data-model note for the two tables in the data section only. Do not touch the AD-8…AD-11 paragraphs (11-2 edits AD-10). |
| `server/tests/test_extraction_topics.py`, `server/tests/test_api_extraction_prompts_topics.py`, `server/tests/test_migrations_topics.py` | NEW. All coverage for this story lives here. |
| `_bmad-output/implementation-artifacts/` | Your spec, `sprint-status.yaml`, `sprint-notes.md`, `review-prompt-story-10-1-<date>.md`. |

Not yours: `test_extraction_core.py`, `test_worker_extract.py`,
`test_migrations.py`, `test_config.py`, `server/tests/conftest.py`,
`AGENTS.md`, `infra/Makefile`, `docs/backlog.md`, `project-context.md`, root
`README.md`. The worker is not started for this story — verify with fakes; the
owner runs a real extraction after integration.

## Verification

- `uv run --project server pytest server/tests/test_extraction_topics.py server/tests/test_api_extraction_prompts_topics.py server/tests/test_migrations_topics.py -q`
- `make test-fast`; `make test` once before `review` (migration applies to a
  per-run database).
- `python3 _bmad/scripts/branch_conflicts.py --against story/10-1` → clean.

## Completion

Spec `status: review`, `10-1-topic-extraction: review` in `sprint-status.yaml`
(and `epic-10: in-progress`), review prompt written, all pushed, SHAs reported.
