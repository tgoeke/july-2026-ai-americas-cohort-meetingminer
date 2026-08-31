# Review handoff — Story 10.3: Thread Timeline API with Level-of-Detail

## What you must produce, before anything else

Write your report to
`_bmad-output/implementation-artifacts/review-story-10-3-2026-08-31.md`.

**Report-first.** Create that file as a skeleton — scope, review range, an empty
findings section — and **commit it before you read a single line of code**. Then
append each finding as you confirm it and commit incrementally. A crashed or
closed session must lose prose, never the artifact.

Each finding carries: **Location / Severity / Finding / Evidence / Suggested
direction**.

**The review lane fixes what it finds.** Report every finding in the report
file first (report-first, committed before reading code), then FIX the
patchable ones yourself on `story/10-3-review` in your own worktree,
red-first — the test observed failing against the unfixed code, then the fix,
then green — committing each with its finding number. Leave unfixed, and
clearly marked open, only what needs an owner decision or is rooted in the
frozen spec. Never commit to `main`, never work in the main checkout, never
merge — the owner runs `integrate`.

This replaces the older "report findings — do NOT fix them" wording in other
prompts in this directory. Those files are the historical record of what was
dispatched, not templates.

**Closeout.** Before reporting completion, run `make check-reviews` and state
the SHA carrying the report's final version. A review reported in the terminal
but not filed does not exist.

## Repo, branch, range

- Repo: `/Users/devopsterus/current/cohort/meetingminer`, branch `story/10-3`
  (pushed to `origin`). Work in your own worktree
  (`make worktree STORY=10-3-review BASE=story/10-3`), never the main checkout.
- Review range: **`3211a7f96b86d7df496cefa451b2cbd431e6d8b4..HEAD`**. Use that
  explicit base rather than `main..HEAD`: `main` has advanced since the branch
  was cut and a two-dot diff against it shows unrelated files.
- Spec (frozen contract):
  `_bmad-output/implementation-artifacts/spec-10-3-thread-timeline-api-with-level-of-detail.md`.
- Build prompt and footprint:
  `_bmad-output/implementation-artifacts/build-prompt-story-10-3-2026-08-31.md`.

## What was built

| Path | What |
|---|---|
| `server/meetingminer/migrations/0017_thread_color_ordinal.sql` | NEW. `thread.color_ordinal` from a sequence, positive, unique, immutable after insert. Closes B-40. |
| `server/meetingminer/domain/thread_timeline.py` | NEW. Pure: `occurred_at`, `format_rfc3339`, `timeline_sort_key`, `plan_buckets`, `bucket_index`, the level vocabulary. |
| `server/meetingminer/api/threads.py` | NEW. `GET /threads`, `GET /threads/{threadId}/timeline?from=&to=&level=`. |
| `server/tests/test_api_threads.py` | NEW. The record's ordinal guarantees, and the list route. |
| `server/tests/test_thread_timeline_levels.py` | NEW. The four tiers, the query shape, the derivation, the refusals. |
| `server/tests/test_api_registry.py` | One line: `"threads"` appended to `BASELINE_ROUTER_ORDER`. Outside the stated footprint — see below. |
| `docs/backlog.md` | B-40 closed; B-42 filed. |

## Where to aim

These are the clauses the story hangs on, and the places a reviewer earns the
most. They are stated as questions, not as claims to confirm.

1. **Does each level really return only its tier?** The four responses are a
   discriminated union on `level`. `test_every_level_returns_exactly_its_own_tier`
   compares whole key sets. Is there a path — a validation error, a union
   coercion, the generated OpenAPI — where a client could see another tier's
   shape?
2. **Is `colorOrdinal` genuinely never recycled?** The argument is: a sequence
   never repeats, a trigger refuses any `UPDATE` that changes the value, and
   `thread` rows are retained rather than deleted (migration 0015). The gap
   deliberately left open: a thread row that *is* deleted frees its ordinal from
   the `UNIQUE` constraint, and an explicit `INSERT` naming that ordinal would
   be accepted. The builder judged a tombstone table out of proportion for the
   deadline and documented the reasoning in the migration header. **Rule on
   whether that is sufficient**, and say so either way.
3. **Do the two anchors matter?** The coarse levels bucket by
   `topic_mention.anchor_ms`; the fine levels serve and derive from
   `moment.start_ms`. The module docstring argues they differ by at most one
   moment's duration and coincide at every ladder step above a minute. Is there
   a window or bucket width where a client would see a mention counted in one
   bucket and its moment rendered in a neighbouring one? Is that acceptable, or
   should both anchors be `anchor_ms`?
4. **Are the coarse levels actually cheap?** Two proofs are in place: a static
   assertion that no coarse statement names `moment` as a relation, and an
   `EXPLAIN` assertion (with the fine level as a control, so the assertion
   cannot be vacuous). The `EXPLAIN` runs against a nearly-empty table, where
   the planner may choose a sequential scan for reasons that would not hold at
   scale. **Is the query shape right for a corpus of hundreds of meetings**, and
   is there an index this should have added?
5. **The fine-level cap.** `MOMENT_LEVEL_LIMIT = 500` with a reported
   `truncated` flag is the builder's addition, not the acceptance criteria's. It
   exists so a `moments` request over a whole corpus span cannot grow without
   bound, and it is reported rather than silent. Is a cap right here at all, and
   is 500 the right number?
6. **`GET /threads` omits a thread with no membership.** Migration 0015 retains
   such rows as reuse targets. The builder judged them not navigable. Does 10.6
   need them?

## Known gaps, stated rather than implied

- **`GET /media/files/{mediaId}` does not exist.** AD-17 and both this story's
  and 10.4's acceptance criteria name it; `api/media.py` was outside both
  footprints and no story built it. This story serves the opaque ids that route
  will take and never a path, which is the half of AD-17 the footprint allowed.
  Filed as **B-42**. A client holding a `screenshotId` today still needs the
  path-addressed route for the bytes.
- **One file was edited outside the stated footprint**, recorded in the spec's
  change log: `server/tests/test_api_registry.py`, one line appended to
  `BASELINE_ROUTER_ORDER`. That list is an exact-equality assertion, so *any*
  new router module must edit it; `threads.py` was deliberately left at default
  `ROUTER_ORDER` so the addition lands at the end of the list rather than
  mid-list, keeping it away from where story 10.4's `moments_feed` will land.
- **The generated TS client does not carry these routes.** `make client`
  regenerates `web/src/client/` from a running api, and both `web/` and
  starting the api were outside this footprint, so it was not run. `make
  check-client` only asserts the three generated files exist, not that they
  are current, which is why the gate is green regardless. Story 10.6 was told
  to build against fixtures, so this blocks nothing today, but it is owed at
  integration — the same debt story 6.4 left and integration paid.
- **Story 10.2a's merge and split are not implemented**, so the ordinal
  behaviour a merge and a split depend on is proven at the record (an `UPDATE`
  refused, a second row taking a new value) rather than through curation
  endpoints that do not exist yet.
- **Nothing calls `derive_threads` in production** (B-39, still open), so on a
  live corpus these endpoints answer over whatever thread rows a developer has
  derived by hand.

## Verification the builder ran

Stated so you can re-run it rather than take it on trust; the SHAs and full
output are in `sprint-notes.md` under the story's heading.

- The two new suites plus `test_api_registry.py`.
- A mutation sweep: twelve deliberate breakages of the clauses above, each
  requiring the named test to fail. Results are in the sprint notes.
- `make test-fast` (lint, typecheck, the store-free suites, the fast set).
- `python3 _bmad/scripts/branch_conflicts.py --against story/10-3`.

## Standing rules

`AGENTS.md` first. Commit each unit; stage only paths you changed; never
`git add -A`; never reset, stash or clean outside your worktree. Your worktree
owns a private Docker stack — `make bootstrap`, then `uv sync --project server`
before `make lint`. Never `make evals-run`, never start the shared api or
worker (a corpus ingest may be running on the main stack). New tests in NEW
files.
