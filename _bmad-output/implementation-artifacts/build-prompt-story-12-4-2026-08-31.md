# Story 12.4 Review Handoff

Repository: MeetingMiner. Review artifact:
`_bmad-output/implementation-artifacts/review-story-12-4-2026-08-31.md`.

The reviewed builder range was exactly `d250cf89..3c75e95d` on
`story/12-4` (eight commits, from `76a6a2dd` through `3c75e95d`). That builder
branch has not moved since review started. The remediated branch is
`story/12-4-review`, rebased onto `origin/main` at `807314e7` and pushed at
`83cc819e`. Do not merge it; the owner runs `integrate`.

## Story verdict

The story does **not** pass review as it stands. Ten patchable findings are
already fixed red-first on `story/12-4-review`; no builder code patch remains.
Two high-severity findings are rooted in the frozen specification/architecture
and require owner decisions. Do not silently code around either one. Amend the
specification, re-derive the affected behavior, and then re-review.

## Spec amendment required before more implementation

### F-03 — Document claims can borrow an unrelated moment citation

Anchor: `server/meetingminer/api/chat.py:1124` (`build_synthesis_prompt`) and
the document placement at `server/meetingminer/api/chat.py:1232`.

What is wrong: a meeting-level extraction document has no claim-to-moment
anchors, but its text is folded beneath whichever retrieved moment from that
meeting happens to be selected first. Document text can therefore supply a
claim while an unrelated retrieved moment supplies a syntactically valid
citation marker.

Concrete failure: given a document-only assertion and any retrieved moment from
the same meeting, the model can repeat the assertion with that moment's marker;
the citation gate accepts the live marker even though the moment never supports
the assertion. Embedded instructions or valid markers in the document have the
same laundering path.

Required decision: the owner must choose either (a) remove extraction-document
text from answer synthesis, or (b) define and persist a deterministic
claim-to-moment relation that the citation gate can verify. Prompt wording or
delimiter escaping is not sufficient enforcement.

### F-11 — Exact unchunked records have a finite store ceiling

Anchor: the one-record writer at
`server/meetingminer/projections/search.py:307` and
`server/meetingminer/projections/search.py:385`; the stack supplies no
Meilisearch payload-limit override in `infra/docker-compose.yml`.

What is wrong: the private stack's actual Meilisearch 1.53.1 binary reports a
default HTTP payload ceiling of 100,000,000 bytes, while the story promises one
exact unchunked record and accepts arbitrary Postgres text. The current long
fixture is only about 79 KB and does not exercise the store boundary.

Concrete failure: a valid extraction document above the request ceiling cannot
be indexed. A delete-then-add projection can also erase an older searchable
record before the oversized replacement fails.

Required decision: establish one explicit policy—retained-source size limit,
configured store ceiling, searchable-text truncation, or revised
chunking/identity—and add boundary tests against the real private store. The
shared live corpus was not queried during its owner rebuild, so no largest-live
measurement is claimed.

Dependency order: decide F-03 before changing prompt/citation behavior; decide
F-11 before changing record identity or projection update order. If either
decision changes the frozen contract, amend the spec first, then regenerate
tests and implementation from that amendment.

## Already fixed — no further action

- F-01 guards the public projection writer against missing AD-18 fields and
  citation-shaped records.
- F-02 isolates the new worker settle point and pins normal, resumed, failure,
  and once-per-pass behavior.
- F-04 requires canonical review/citability fields at write and read boundaries.
- F-05 attaches documents to the first selected prompt block, not the first
  pre-capacity candidate.
- F-06 makes the reusable marking vocabulary/state semantics closed and
  consistent for Story 12.5.
- F-07 rejects stale or cross-scoped index hits by digest and scope.
- F-09 preserves document-index-missing and stale-document UI state.
- F-10 removes the unrelated Neo4j dependency from document-only projection.
- F-12 bounds Postgres document reads before prompt truncation.

F-08 requires no action: inherited `SearchIndexConfig` validation already
requires `meetingId` and `corpus`; the candidate finding was dismissed after
verification. There is no deferred-work entry.

## Required verification after the owner decisions are implemented

Run all commands in this worktree's private stack, in the foreground, and read
their real output:

1. Confirm each new regression test fails against the unfixed behavior before
   applying its implementation.
2. Run focused prompt/citation tests for F-03 and a real-private-Meilisearch
   boundary test for F-11.
3. Run `make lint`.
4. Run `make typecheck`.
5. Run `make test-fast`.
6. Run `make test`.
7. Run `python3 _bmad/scripts/branch_conflicts.py --against story/12-4` and
   inspect the two pairs involving `story/12-4-review`, not only the tool's
   aggregate exit status.

Current verification is green: `make lint`, `make typecheck`,
`make test-fast`, and `make test` all exited 0. The full server gate reported
2979 passed, 3 standing skips, 0 failed; the production web build succeeded.

## Explicitly out of scope

Do not implement Story 12.5 artifacts here, revise the owner-set publish
definition, make extraction documents directly citable, call a paid model,
query or mutate the shared main-checkout corpus during its rebuild, edit
`config.yaml`, restart the shared API/worker, merge into `main`, or run
`make worktree-prune`.
