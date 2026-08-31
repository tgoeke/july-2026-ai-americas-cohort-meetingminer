---
title: 'Story 10.2a: Thread Curation'
type: 'feature'
created: '2026-08-31'
baseline_revision: '2d68dcc6'
status: 'review'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/spec-10-2-threads-and-the-graph-projection.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-10-3-thread-timeline-api-with-level-of-detail.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-meetingminer-2026-08-29/DESIGN.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-meetingminer-2026-08-29/EXPERIENCE.md'
deferred:
  - 'Duplicate curated names are not refused — filed as B-53 with the reasoning'
  - 'No unmerge / unsplit control — filed as B-54; the record was built to make it cheap'
---

<intent-contract>

## Intent

**Problem:** Story 10.2 derives threads from topics and **re-derives every one
of them on every pass**. Nothing lets a human correct the grouping, and the
naive way to add it — let the user edit `thread.name`, move `topic_thread`
rows — produces something worse than no curation at all: the next derivation
rewrites `thread.name` from the cluster's seed topic and moves the membership
back, and the user watches their own correction disappear with no record that
it was ever made. FR42 asks for merge, split and rename **"without being
overwritten on the next rerun"**, and that clause is the story.

**Approach:** Curation is an **input to the derivation, never an edit of its
output**. Migration 0021 adds three api-owned tables; `derive_threads` reads
them before it writes; the api's read path and the graph projection resolve the
same rows live. That is the shape `participant_alias` already has (AD-5,
migration 0005): the api writes the alias, `align` resolves it before every
insert, and a merge survives every re-ingest.

| Operation | Stored as | Why the rerun cannot undo it |
|---|---|---|
| Rename | `thread_curation(thread_id, name)` | The derivation writes `thread.name`; readers display `COALESCE(curated, derived)`. Two different columns — they cannot collide. |
| Merge | `thread_alias(thread_id, merged_into_id)` | The derivation resolves a cluster's thread through it *before* writing memberships, so the absorbed cluster re-derives **into** the survivor every pass. |
| Split | `thread_topic_pin(meeting_id, normalized_name, thread_id, topic_id)` | The pin is applied before the membership UPSERT. Keyed on durable normalized content, so story 10.1 replacing a meeting's topics wholesale does not take the split with it. |

## Boundaries & Constraints

**Always:**

- **`thread.color_ordinal` is never written by curation.** A merge writes an
  alias row and moves memberships — two operations that do not name the column
  — so the survivor keeps its ordinal and the absorbed row keeps its. A split
  *inserts*, so it takes a new ordinal by the ordinary path, which is what
  0017's own comment anticipated. Migration 0017's immutability trigger would
  raise on anything else.
- **The derivation's idempotency is preserved intact.** Curation is resolved
  as each membership is written, not corrected afterwards, so every topic is
  still written by exactly one statement and property 4 of
  `domain/threads.py`'s argument — an unchanged rerun writes nothing at all,
  not even `updated_at` — still holds with curation on record. Pinned by test.
- **A split's thread cannot be reclaimed by a later pass.** Its `identity_key`
  is namespaced `curated-split:`, disjoint from every key the derivation can
  mint (a normalized name reduces to alphanumerics and single spaces; the only
  other form is the literal `topic-name-sha256:`). Reservation by content key
  therefore cannot reach it, and `_attached_thread_to_reuse` refuses it
  explicitly — the subtle hazard, since a curated thread is attached to exactly
  the topics split onto it and attachment is otherwise the mechanism that
  *preserves* identity.
- **Nothing is discarded quietly (AD-18).** A pin whose durable key matches no
  topic in this corpus is kept, counted in `ThreadDerivation.unmatched_pins`,
  and named — meeting id and normalized name — in a `threads.curation_unmatched`
  log event. A recorded correction that did not apply and a corpus with no
  corrections are otherwise the same observation.
- **The alias map is flat, never a chain.** Every resolver follows exactly one
  hop, so A→B→C would strand A on a thread that is itself merged away.
  Enforced in `api/thread_curation.py` *and* by 0021's `thread_alias_flat`
  trigger, because thread curation has two independent resolvers and a rule
  held in only one of them is not a guarantee for the other.
- **A reader can always tell a curated name from a derived one.** `GET
  /threads` serves `nameIsCurated` on every row; the write routes serve `name`,
  `derivedName` and `nameIsCurated` together; the row prints `curated` or
  `machine-derived`.

**Never:**

- **The api never writes `topic_thread`**, and never writes any column of
  `thread` other than on the one insert a split needs.
- **The machine never renames, merges or splits on its own.** Every curation
  row is written by a route a person called.
- **No store client in the api** (AD-4). Curation reaches Neo4j at the next
  projection pass, which reads the same resolved membership.

**The one named exception to AD-5:** a split mints one `thread` row from the
api. Its product needs a `thread.id` for story 10.3's timeline to address and a
`color_ordinal` for the view to colour, and neither can come from a curation
table. This is the same exception `api/speakers.py` already holds against
worker-owned `participant`. Both `docs/architecture.md` and
`ARCHITECTURE-SPINE.md` state it under AD-5; no AD was added, so the AD-1…AD-18
count is unchanged.

## I/O & Edge-Case Matrix

| Input | Answer |
|---|---|
| `PATCH /threads/{id}` `{name}` | 200 the curated thread. `null` clears, restoring the machine's *current* name — not a copy taken when the rename happened. |
| `PATCH` a merged-away thread | 409 `already-merged`. Curating something nobody can see is a correction with no visible effect. |
| `PATCH` blank / whitespace name | 422; also refused by a CHECK, so a direct writer cannot produce an unnamed band. |
| `POST /threads/{id}/merge` `{intoThreadId}` | 200 the survivor. Same id both sides → 422. Either side already in the map → 409 (`already-merged` / `merge-target-not-canonical`). Concurrent duplicate → 409, never a 500. |
| `POST /threads/{id}/split` `{topicIds, name}` | 201 the new thread with a fresh `colorOrdinal`. |
| Split naming no topics, or topics the thread does not hold | 422. Membership is checked against the **effective** grouping, so a stale client offering yesterday's list is refused rather than silently re-pinning. |
| Split naming *every* topic | 422 — that empties the original and is a rename. Refused by the api and disabled in the UI. |
| Split naming a punctuation-only topic name | 422: it normalizes to the empty string and has no durable identity to pin to. |
| Re-derivation after any curation | The correction holds; `ThreadDerivation` reports `curated_links`, `merged_clusters` and `unmatched_pins`. |
| Re-extraction replacing every topic row | The split still holds — the pin's key is content, not a UUID. |

</intent-contract>

## Code Map

| Path | What |
|---|---|
| `server/meetingminer/migrations/0021_thread_curation.sql` | NEW. `thread_curation`, `thread_alias` (+ flatness trigger), `thread_topic_pin`. |
| `server/meetingminer/domain/thread_curation.py` | NEW. The resolution rule in Python and in SQL (`EFFECTIVE_MEMBERSHIP`), the curated key space, `pin_content_key`, the AD-18 reporting helpers. |
| `server/meetingminer/domain/threads.py` | `derive_threads` resolves curation before writing; `_attached_thread_to_reuse` refuses a curated row; `ThreadDerivation` gains three counts. |
| `server/meetingminer/api/thread_curation.py` | NEW. `PATCH /threads/{id}`, `POST /threads/{id}/merge`, `POST /threads/{id}/split`. |
| `server/meetingminer/api/threads.py` | Reads `EFFECTIVE_MEMBERSHIP` at all six sites; serves the curated name and `nameIsCurated`. |
| `server/meetingminer/projections/evidence.py` | Same fragment, so the graph's `Thread` node matches what the user sees. |
| `server/tests/test_thread_curation.py` | NEW. 22 tests, weighted at survival across reruns and re-extraction. |
| `server/tests/conftest.py` | The three tables added to `EVIDENCE_TABLES`. |
| `server/tests/test_api_registry.py`, `test_api_threads.py` | Two pinned baselines a new module and a new field legitimately move. |
| `web/src/features/threads/ThreadCuration.tsx` | NEW. Rename · Merge into… · Split…, per `DESIGN.md`'s split-panel spec. |
| `web/src/features/threads/threadsApi.ts` | The three writes, the split panel's topic read, `nameIsCurated`. |
| `web/src/features/threads/ThreadCuration.test.tsx` | NEW. 14 tests. |
| `docs/architecture.md`, `ARCHITECTURE-SPINE.md` | AD-5 amended with the split's named exception. |
| `docs/backlog.md` | B-53, B-54 filed. |

## Spec Change Log

- 2026-08-31 — written at implementation, status `review`.
