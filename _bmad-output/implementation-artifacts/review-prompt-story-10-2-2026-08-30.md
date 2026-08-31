# Review handoff — Story 10.2: Threads and the Graph Projection

## What you must produce, before anything else

Write your report to
`_bmad-output/implementation-artifacts/review-story-10-2-2026-08-30.md`.

**Report-first.** Create that file as a skeleton — scope, review range, an empty
findings section — and **commit it before you read a single line of code**. Then
append each finding as you confirm it and commit incrementally. Four reviews in
this repository were completed in a session's terminal and never filed, every
one of them written report-last. A crashed or closed session must lose prose,
never the artifact.

Each finding carries: **Location / Severity / Finding / Evidence / Suggested
direction**.

**The review lane applies its own patch findings.** This is the repository's
convention as of 2026-08-30, and it replaces the older "report findings — do
NOT fix them" wording you may see in other prompts in this directory. Those
files are the historical record of what was dispatched, not templates.

So: report every finding in the report file first, then **fix the patchable
ones yourself** on `story/10-2-review` (cut from `story/10-2`, in its own
worktree — `make worktree STORY=10-2-review`), **red-first**: the test observed
failing against the unfixed code, then the fix, then green. Commit each fix
with its finding number. You hand nothing back to a builder.

What you must **not** fix: anything needing an owner decision, and anything
whose root cause is the frozen spec (the `<intent-contract>` block). Report
those, mark them clearly **open**, and leave them for the owner.

Never commit to `main`, never work in the main checkout, never merge — the owner
runs `integrate`.

**Closeout.** Before reporting completion, run `make check-reviews` (it fails
while any dispatched review lacks a committed report, this one included) and
state the SHA carrying the report's final version. A review reported in the
terminal but not filed does not exist.

## Repo, branch, range

- Repo: `/Users/devopsterus/current/cohort/meetingminer`, branch `story/10-2`
  (pushed to `origin`). Work in your own worktree, never the main checkout.
- Review range: **`4a111b8a981f3b5001e81f4bcbca54a2bdf28b42..HEAD`**.
  Use that explicit base, not `main..HEAD`: `main` has advanced 27 commits
  (story 6.3 landed) since this branch was cut, so a two-dot diff against
  `main` shows 6.3's files as spurious deletions.
- Commits in range, oldest first:

  | Revision | Subject |
  |---|---|
  | `69ecc561f27ff6affc73c4b253b9efb970cf3f8a` | docs: spec Story 10.2 — threads and the graph projection |
  | `f27f6658c29348ac79bfa2392eaa66b1fb2fe0b0` | feat(10.2): derive threads from stored topics (migration 0015) |
  | `53796a48acbd62638d18e1c429c9b6cd129e054f` | test(10.2): pin the thread partition with no store and no model |
  | `6b845587d53298c09fb1f2b5805e658f5ba28032` | feat(10.2): project Topic/Thread nodes and register the thread traversal |
  | `34b14615f9a6ae66a1597cea8d9ccba4323d9dc2` | fix(10.2): declare thread-timeline unroutable until story 10.2b |

  Every commit in the range belongs to story 10.2. None belongs to another story.

## The spec, and which half you may attack

`_bmad-output/implementation-artifacts/spec-10-2-threads-and-the-graph-projection.md`.

- **Frozen intent** — the `<intent-contract>` block (Intent, Boundaries &
  Constraints, I/O & Edge-Case Matrix). A finding rooted here is reported and
  left open for the owner, never patched.
- **Planner's work, fair game** — Code Map, Tasks & Acceptance, Spec Change Log,
  Design Notes, Verification. Attack these freely.

## Architecture authority

- **AD-4 (projections have exactly one writer)** — the decision this story
  amends. The amendment is in `docs/architecture.md`: topics and threads are
  navigation metadata outside the publish gate. Check the amendment says what
  the code does, and that `server/tests/test_projections_single_writer.py` still
  passes — nothing outside `projections/` may import `neo4j` or `meilisearch`,
  and `server/meetingminer/domain/threads.py` is new code that must not.
- **AD-5 (table ownership is disjoint)** — `thread` / `topic_thread` are
  worker-owned. Story 10.2a will add api-owned curation on top; check nothing
  here forecloses that.
- **AD-6 (citations are Postgres-minted moment ids)** — every graph node key and
  every id the traversal returns is parsed to `UUID` or refused by name. A topic
  name must never become quotable evidence.
- **AD-7 (deterministic traversal templates)** — the new `thread-timeline`
  entry: hand-written parameterized Cypher, values as `$`-parameters, registered
  in `TRAVERSAL_TEMPLATES` like the other two.
- **AD-8 (model calls go through configured ports)** — the derivation depends on
  the `Embedder` protocol only.
- **AD-10 (one config file drives everything)** — the `threads:` block, its
  recorded rationale, and its lower bound.

Also governing: `AGENTS.md` (worktrees, private stacks, the fast/full split,
lint and typecheck in the loop) and
`_bmad-output/implementation-artifacts/wave-2026-08-30-rules.md` (the footprint
contract).

## Scope

**In scope — the 19 files in the range:**

- `server/meetingminer/migrations/0015_threads.sql` (new)
- `server/meetingminer/domain/threads.py` (new)
- `server/meetingminer/config.py`, `config.yaml`
- `server/meetingminer/projections/`: `evidence.py`, `stores.py`, `graph.py`,
  `traversals.py`
- `server/meetingminer/api/chat_router.py`
- `docs/architecture.md` (AD-4 only)
- tests: `test_threads_derivation.py` (new), `test_threads_record.py` (new),
  `test_projections_threads.py` (new), plus edits to `conftest.py`,
  `test_config.py`, `test_compose_contract.py`, `test_projections_traversals.py`,
  `test_chat_router.py`
- the spec itself

**Explicitly out of scope:**

- Story 10.2a (thread curation: merge/split/rename, api-owned alias rows),
  10.2b (chat routing onto the thread template), 10.3 (thread timeline API),
  10.6 (the Threads view). Absence of any of these is not a finding.
- Anything under `web/`, the artifact lifecycle, and `pipeline/extraction.py` /
  `pipeline/stages/extract.py` (story 10.1 owns topic production; this story
  only consumes stored topics).
- The two recorded deferrals below, and the ruff/mypy baselines.

## Design decisions to attack

The planner is not a neutral judge of its own calls. Each of these is a choice
plus the assumption under it. Please try to break them.

1. **Idempotency is claimed structurally, not by convention.** Four mechanisms:
   order-independent union-find; a cluster seed that is the deterministic
   minimum under `(meeting.started_at, meeting.id, normalized name, topic.id)`;
   `identity_key` = that seed's normalized name, UPSERTed on; and a `WHERE` on
   every conflict clause so an unchanged rerun writes nothing at all.
   *Assumption:* seeds cannot collide across clusters, because every topic
   sharing a normalized name is already unioned into one cluster. Is that
   argument airtight? `_assert_keys_are_unique` is the runtime guard — is it
   reachable, and is it in the right place?
2. **The seed is chronological, not alphabetical.** *Assumption:* new meetings
   almost always arrive later, so a chronological seed survives corpus growth.
   A backfilled older meeting re-seeds the thread and mints a new
   `identity_key`, orphaning the old row (the trigger deletes it) and giving
   the thread a **new id** — which would break 10.2a curation attached to the
   old id. Is that acceptable, or is it a finding for the owner?
3. **`thread-timeline` is registered but deliberately unroutable in chat.**
   `DEFERRED_TEMPLATES` in `chat_router.py`. *Assumption:* letting the
   classifier reach it would be a live `AttributeError` in `_traversal_leg`
   (which reads `result.rows`), and adapting the orchestrator is story 10.2b's
   job. Is the deferral mechanism sound, or does it weaken a tripwire that was
   there for a reason?
4. **`Topic` is meeting-scoped, `Thread` is cross-meeting.** *Assumption:* the
   `Artifact`/`Screen` precedent transfers exactly. A `Thread` whose last topic
   disappears lingers as an edgeless node until `rebuild --all`, like `Screen`.
   Acceptable?
5. **`derive_threads` requires an `Embedder` and rolls back whole when the host
   is unreachable.** *Assumption:* a corpus threaded by name alone is not the
   product, so a name-only pass would be a silent fallback (which the owner has
   rejected). Is the ordering (read → embed → write) actually what guarantees
   nothing partial lands, and does the test prove it or only assert an outcome
   that is true for another reason?
6. **`0.82` is unmeasured.** Recorded as such in `config.yaml`. *Assumption:*
   an honest, conservative starting value beats a fabricated measurement. The
   `ge=0.5` floor is the fail-closed guard. Is 0.5 the right floor?
7. **O(n²) pair generation.** *Assumption:* a few hundred meetings × a handful
   of topics is a few hundred thousand short dot products, cheaper than the
   read. An approximate index was rejected because it would make the partition
   depend on the index's recall. Does the arithmetic hold at the corpus size
   this project actually targets?
8. **`linked_by` is derived from the finished cluster, not from the union
   order** ("does it share a name with any other member"), so a stored column
   cannot depend on iteration order. Is the `EMBEDDING_LINK` similarity — the
   max to any other member — the right number to store?

## Footprint deviations — please check these specifically

The build prompt's footprint table did not cover four files the acceptance
criteria turned out to require. All four are additive, all four are recorded in
the spec's Spec Change Log, and none is touched by any branch in flight
(`story/6-2a`, `story/7-2`, `story/8-1`, `story/8-1-review`), verified with
`git diff --name-only` per branch. Judge whether each was actually necessary:

1. `server/meetingminer/projections/evidence.py` — `graph.project_meeting`
   takes a driver and a `MeetingEvidence`, never a Postgres connection, and
   `evidence.py` is by design "the projection module's whole input surface".
   AC2 is not deliverable without it. Note `projections/__init__.py` is
   **not** touched: routing topics through `MeetingEvidence` is what kept the
   orchestration unchanged.
2. `server/meetingminer/projections/stores.py` — `Topic`'s per-meeting deletion,
   its `meetingId` index and both unique-id constraints key off tuples there.
3. `server/tests/conftest.py` (`EVIDENCE_TABLES`) — `topic_thread` references
   `topic`, so `TRUNCATE` is refused outright without it and **every**
   DB-backed test in the suite fails. Not optional.
4. `server/meetingminer/api/chat_router.py` + `test_chat_router.py` — see
   design decision 3.

Plus three forced one-liners in shared test modules: `test_config.py`'s
`VALID_CONFIG` (a required config field, exactly as story 10.1 did for
`topics_prompt`), `test_compose_contract.py`'s `SLOW_MODULES` (a store-backed
module must be `slow`-marked and the mark is pinned in both places by design),
and `test_projections_traversals.py`'s registry assertion (it pins the
registry's exact membership).

## Recorded deferrals — not findings

- **B-38: nothing calls `derive_threads` in production yet.** Wiring it into the
  worker's settle point is an edit to `pipeline/stages/extract.py` and/or
  `domain/jobs.py`, which story 10.1 owns and the footprint marks "not yours".
  The function, its configuration and its record are complete and tested; the
  trigger is the named gap. **B-38 and B-39 are ids this lane took** (highest
  previously used was B-37); they are recorded in the spec, not in
  `docs/backlog.md`, which the wave rules put off limits.
- **B-39: `thread.color_ordinal`.** The epic requires a server-owned,
  never-recycled, **per-corpus** colour ordinal. `thread` has no corpus column
  and a thread may span corpora; scoping that is a 10.3/10.6 decision, so no
  half-right column was added.
- **`domain/threads.py` is not in `[tool.mypy] files`.** Its pure clustering half
  is a decision core and arguably belongs there, but widening the scope is an
  edit of `server/pyproject.toml` **and** `test_lint_contract.py`'s
  `DECISION_CORE_FILES`, both outside the footprint. A one-line follow-up at
  integrate.

## History you need to tell a regression from a pre-existing condition

- The branch was cut from `4a111b8`, **before** story 6.3 landed on `main`. It
  has **not** been rebased. Anything you see attributed to 6.3 in a
  `main..HEAD` diff is an artifact of the wrong base — use the explicit base
  above.
- Migration `0014` is story 10.1's (`topic` / `topic_mention`, landed). `0015`
  is this story's and is uncontested: no other branch, and not `main`, holds a
  `0015`.
- `AGENTS.md` was rewritten on 2026-08-30 (story 11.2): each worktree now owns a
  private Docker stack. `make bootstrap` then `make infra-up` in your worktree.
- Two skips in the suite are pre-existing and named: `pyannote.audio` is not
  installed, and the real-network yt-dlp test needs `MM_YOUTUBE_NETWORK_TEST=1`.

## Verification baseline

Run these in your own worktree with its stack up. A skip or failure that is not
listed here is a finding, not noise.

| Command | Result at `34b1461` |
|---|---|
| `make test-fast` (includes `make lint` + `make typecheck`) | **1883 passed, 2 skipped, 404 deselected** in 56s |
| `uv run --project server pytest server/tests/test_threads_derivation.py -q` | **30 passed** |
| `uv run --project server pytest server/tests/test_threads_record.py -q` | **20 passed** |
| `uv run --project server pytest -m "" server/tests/test_projections_threads.py -q` | **26 passed** in 46s |
| `uv run --project server pytest -m "" server/tests/test_projections_traversals.py server/tests/test_projections_graph.py server/tests/test_projections_single_writer.py server/tests/test_compose_contract.py server/tests/test_lint_contract.py -q` | **125 passed** in 107s |
| `make test` (the full gate, private stack up) | **2287 passed, 2 skipped**, exit 0, web build succeeded, in 643s (10m43s) |
| `python3 _bmad/scripts/branch_conflicts.py --against story/10-2` | every **code** pair clean; `sprint-notes.md` conflicts — see below |

**On the conflict report, stated precisely rather than as "clean".** Measured
twice. Before this story's `sprint-notes.md` entry existed, `main × story/10-2`
was **`clean`** — that is the meaningful result, and it is the state of every
source, test, config, migration and doc file in the range.

After the entry, `main × story/10-2` reports `CONFLICT:
_bmad-output/implementation-artifacts/sprint-notes.md`, and nothing else. That
file has **no merge driver**; `main` gained story 6.3's entry after this branch
was cut, so any append lands at the same base position as 6.3's. The wave rules
anticipate exactly this — "keep your entry short and at the end; expect
integrate to union it" — and `main × story/6-2a` conflicts on the same file for
the same reason. Rebuilding the entry on top of main's current content was
tried and does **not** help (git still sees an add/add at one base position,
and it risks duplicating 6.3's entry at integrate), so that attempt was dropped
rather than left in the history.

The remaining pairs: `story/10-2 × story/8-1` also lists
`docs/architecture.md`. `story/8-1` already conflicts with **`main` itself** on
that file, so it is stale against main and must rebase regardless — this branch
adds no file to that pair. After 8-1 rebases, its hunk is in AD-10 and this
story's is in AD-4, ~36 lines apart.

**So: if you see a conflict on anything other than `sprint-notes.md`, that is a
finding.**

**Never** run `make evals-run` (paid judge role), `make up`, or the shared
worker/api, and never call the `chat` or `judge` roles.

### The tests were mutation-checked, so please attack them too

Rather than assume the new tests can fail, each key clause was checked by
breaking the implementation and confirming a red. Caught: `>=` → `>` on the
threshold (1 failure); an inverted cluster seed (5); dropping the name-leg
union (3); letting empty normalized names union (1); forcing the thread upsert
to always write (the idempotency test, 1); removing the `_write_topics` call
(9); disabling the `MENTIONS` edge-count check (1); stamping `Thread` with a
`meetingId` (1); reversing the traversal `ORDER BY` (1); reading the span off
the last row instead of the widest end (1).

**Two mutants were equivalent and are reported as such rather than inflated:**
`min(members, key=order_key)` → `members[0]`, and dropping the internal
`sorted(topics, ...)`. Both pass, because the partition is order-independent
through *both* the union-find and the explicit `min`. The consequence worth
your attention: `test_the_partition_does_not_depend_on_the_order_topics_arrive_in`
is weaker than its name suggests — it cannot fail against the current
implementation, and earns its place only as protection against a future greedy
refactor. Decide whether that is acceptable or whether it should test the
partition through a seam that can actually vary.

---

When you are done: state the report path, the SHA carrying its final version,
and the `make check-reviews` result.
