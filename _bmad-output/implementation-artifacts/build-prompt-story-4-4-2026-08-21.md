# Builder Handoff: Story 4-4 Review Complete

Carry this prompt to the Claude `bmad-build-auto` agent by hand.

## State and reviewed range

- Repository: `meetingminer`
- Verified branch: `story/4-4-review`
- Review report: `_bmad-output/implementation-artifacts/review-story-4-4-2026-08-21.md`
- Frozen story: `_bmad-output/implementation-artifacts/spec-4-4-published-artifacts-become-citable-knowledge.md`
- Remediation spec: `_bmad-output/implementation-artifacts/spec-4-4-citable-knowledge-review-remediation.md`
- Original reviewed range: `2d9705fb286098f9af08e2724d0106052244bc0f..bb813821356dd295240dd5bee6e36271bd1ce58d`
- Remediated branch head: `e991669ac1cd9d0a81dc497b665074d60fc09e96`

The branch moved after the original range because the review itself added its
report, the approved remediation, regressions, final verdict, and status sync.
It is committed, pushed, and clean at the head above.

## Review outcome

**Story 4-4 passes review as it stands. There are no fix-now findings.** The
builder must not search for or invent more work. The story and remediation
spec are already `done`, sprint tracking is `done`, and the branch is pushed.
If this handoff is run, confirm that state and do not change code merely to
produce another commit.

The original nine findings were fixed:

1. Augmentation remaps published artifacts to one unique live evidence moment.
2. Artifact-first search paging exposes every artifact and moment exactly once.
3. Artifact-only projection is isolated from vector schema and removes embedders.
4. Embed-only rebuilding leaves the artifacts index untouched.
5. Artifact-backed chat evidence retains prompt capacity.
6. Postgres readback preserves artifact relevance order.
7. Config requires the artifact query's `state` and `title` surfaces.
8. The unlocked legacy artifact writer was removed.
9. Artifact-backed route telemetry counts distinct searchable source moments.

Remediation re-review added and closed 13 more patch findings covering exact
Meilisearch artifact counts, stale-slot paging, approval/remap serialization,
original evidence-instant preservation, malformed provenance refusal,
post-lock projection reads, embedder-inspection failures, exact Artifact-only
Neo4j schema, absent-index and stale-embedder separation, search-rank readback,
traversal-first prompt presentation, and two stale contract descriptions.
Their anchors, concrete failure modes, and final requirements are recorded in
the review report's `Remediation re-review` section and the remediation spec's
Suggested Review Order.

## Deferred — record only, no action in this story

- `server/meetingminer/projections/__init__.py:572` — embed-only projection
  still opens and health-checks Neo4j even though it writes only Meilisearch
  vectors. A Neo4j outage can therefore block vector repair. This predates the
  Story 4-4 remediation and is already appended to
  `_bmad-output/implementation-artifacts/deferred-work.md` with the remediation
  spec as its source. Do not widen this story to add a search-only store context.

## No-action candidates

- Moment totals remain explicitly estimated after semantic-floor filtering;
  the wire field promises an estimate, not an exhaustive count.
- The hard 32,000-character chat cap may drop lower-ranked evidence blocks;
  artifact capacity is reserved, but the safety cap remains deliberate.
- Intermediate workflow status mismatches were transient and are now resolved.

There was no specification-root finding and no frozen intent amendment is
needed. The user decision remains: remap by the unique live moment containing
the original source instant, retain source identity and transition evidence,
and fail by name before commit when replacement is not unique.

## Verification already observed

Run these only to confirm the pushed head, not to derive new work:

```bash
cd server && uv run pytest tests/test_worker_moments.py tests/test_projections_search.py tests/test_projections_rebuild.py tests/test_projections_locks.py tests/test_config.py tests/test_api_search.py tests/test_api_chat.py -q
cd server && uv run pytest tests/ -q
make evals-test
make web-test
rg -n "import neo4j|import meilisearch|from neo4j|from meilisearch" server/meetingminer/api
```

Observed at the pushed head: 254 targeted server tests, 1,587 full server
tests, 548 eval tests, and 207 web tests passed; the API store-import scan was
empty. Regeneration from this worktree's own OpenAPI schema left
`web/src/client/` unchanged. `make evals-run` is explicitly out of scope.

The original focused regression set was exercised against unfixed
`bb813821356dd295240dd5bee6e36271bd1ce58d`: 13 of 14 selected cases failed;
the one passing mixed-lane de-duplication case is paired with an artifact-only
telemetry case that failed, so the finding remained non-vacuous. Any future
test introduced for a new change must likewise be demonstrated against the
unfixed code rather than assumed non-vacuous.

## Integration note

The review agent did not merge to `main`. Current `origin/main` advanced by
117 commits since the Story 4-4 merge base, and the required rebase stopped on
content conflicts in `server/meetingminer/projections/graph.py` and
`server/meetingminer/projections/stores.py`. The rebase was aborted; no conflict
resolution was guessed and the verified review branch remains unchanged.
Integration requires an explicit reconciliation pass against current `main`.
