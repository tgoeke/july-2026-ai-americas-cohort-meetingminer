# Review handoff — Story 10.2a: Thread Curation

## What you must produce, before anything else

Write your report to
`_bmad-output/implementation-artifacts/review-story-10-2a-2026-08-31.md`.

**Report-first.** Create that file as a skeleton — scope, review range, an empty
findings section — and **commit it before you read a single line of code**. Then
append each finding as you confirm it and commit incrementally. A crashed or
closed session must lose prose, never the artifact.

Each finding carries: **Location / Severity / Finding / Evidence / Suggested
direction**.

**The review lane fixes what it finds.** Report every finding in the report
file first (report-first, committed before reading code), then FIX the
patchable ones yourself on `story/10-2a-review` in your own worktree,
red-first — the test observed failing against the unfixed code, then the fix,
then green — committing each with its finding number. Leave unfixed, and
clearly marked open, only what needs an owner decision or is rooted in the
frozen spec. Never commit to `main`, never work in the main checkout, never
merge — the owner runs `integrate`.

**Closeout.** Before reporting completion, run `make check-reviews` and state
the SHA carrying the report's final version. A review reported in the terminal
but not filed does not exist.

## Repo, branch, range

- Repo: `/Users/devopsterus/current/cohort/meetingminer`, branch `story/10-2a`
  (pushed to `origin`). Work in your own worktree
  (`make worktree STORY=10-2a-review BASE=story/10-2a`), never the main
  checkout. Run `make bootstrap` there before `make lint`.
- Review range: **`2d68dcc6..HEAD`**. Use that explicit base rather than
  `main..HEAD`: `main` has advanced since the branch was cut and a two-dot diff
  against it shows unrelated files.
- Spec (frozen contract):
  `_bmad-output/implementation-artifacts/spec-10-2a-thread-curation.md`.
- Acceptance criteria: `_bmad-output/planning-artifacts/epics.md`,
  "### Story 10.2a: Thread Curation".

## What was built

| Path | What |
|---|---|
| `server/meetingminer/migrations/0021_thread_curation.sql` | NEW. `thread_curation`, `thread_alias` (+ a flatness trigger), `thread_topic_pin`. |
| `server/meetingminer/domain/thread_curation.py` | NEW. The one resolution rule, spelled twice — Python for the derivation, `EFFECTIVE_MEMBERSHIP` for the SQL readers. |
| `server/meetingminer/domain/threads.py` | `derive_threads` resolves curation before writing; `_attached_thread_to_reuse` refuses a curated row; `ThreadDerivation` gains `curated_links`, `merged_clusters`, `unmatched_pins`. |
| `server/meetingminer/api/thread_curation.py` | NEW. `PATCH /threads/{id}`, `POST /threads/{id}/merge`, `POST /threads/{id}/split`. |
| `server/meetingminer/api/threads.py` | Six SQL sites now read `EFFECTIVE_MEMBERSHIP` instead of `topic_thread`; curated name and `nameIsCurated` served. |
| `server/meetingminer/projections/evidence.py` | Same fragment, so the graph's `Thread` node is the thread the user sees. |
| `server/tests/test_thread_curation.py` | NEW, 22 tests. |
| `server/tests/conftest.py` | Three tables added to `EVIDENCE_TABLES`. |
| `server/tests/test_api_registry.py`, `test_api_threads.py` | Two pinned baselines a new router module and a new field legitimately move. |
| `web/src/features/threads/*` | `ThreadCuration.tsx` + test (14), the three writes and the split panel's read in `threadsApi.ts`, the row wiring, fixture updates. |
| `docs/architecture.md`, `ARCHITECTURE-SPINE.md` | AD-5 amended: the split's one named `thread` insert. No AD added; the AD-1…AD-18 count is unchanged. |
| `docs/backlog.md` | B-53, B-54 filed. |

## Where to aim

The story is not "add three endpoints". It is "a correction the machine cannot
silently reverse". Aim there.

1. **Try to make a rerun eat a curation.** This is the review's main job.
   Construct corpora the tests do not: a topic renamed so its cluster's
   `identity_key` moves; two meetings whose subjects converge into one cluster
   after a split has separated them; a merge whose survivor is later emptied by
   re-extraction; a split product that later becomes a content-key match for a
   derived cluster. In each case run `derive_threads` twice and ask whether the
   human's decision is still on screen. Anything that reverses it silently is a
   Major finding regardless of what the tests say.
2. **`_attached_thread_to_reuse`'s exclusion.** The filter is a string prefix
   test in SQL (`NOT starts_with(th.identity_key, 'curated-split:')`). Is the
   key-space disjointness argument in `domain/thread_curation.py` actually
   airtight — can `normalized_topic_name` ever emit a `:` or `-`? Can the
   `topic-name-sha256:` fallback? If a collision is reachable, the split's
   thread is stealable and the whole story fails at that one line.
3. **The read/write split of the pin's `topic_id` hint.** It carries no foreign
   key, deliberately. The argument (module docstring) is that the SQL join only
   has to cover the window between a split and the next derivation, because
   after a pass `topic_thread` itself carries the answer. Test that argument
   rather than accepting it: is there a state where the read path and the
   derivation disagree about where a topic lives, and does anything surface the
   disagreement?
4. **Idempotency.** `test_curation_leaves_an_unchanged_rerun_writing_nothing`
   asserts it for one shape. Does it hold with a merge *and* a split *and* a
   rename on the same threads, and after a re-extraction?
5. **The six converted SQL sites in `api/threads.py`.** Each one was a
   mechanical substitution of a subquery for a table name. Check the query
   plans and the semantics: `_THREAD_LIST`'s `GROUP BY` now repeats two
   expressions, `_MOMENTS_LEVEL` nests the fragment inside an `IN (SELECT …)`,
   and `_MEETING_TOPICS` reports `linked_by` as `curated` where a pin fired.
   Is any of them now wrong at a window boundary, or quadratic?
6. **Concurrency.** `merge` locks both `thread` rows in sorted order and runs
   at READ COMMITTED with the checks after the lock. The flatness trigger is
   the backstop. Is there an interleaving that produces a chain, or a deadlock
   between merge and split on the same thread?
7. **AD-18 honesty.** `unmatched_pins` is reported. Is anything *else* lost
   without a word? Specifically: a pin whose thread row is deleted (cascade), a
   curated thread whose every pin goes unmatched, a merge whose survivor no
   longer exists.
8. **The UI's two rules.** `canSplit` refuses all-topics and the api refuses it
   too. Confirm the api's rule and the button's rule cannot disagree — and that
   a refusal genuinely leaves the panel's state intact rather than appearing to.

## Known deviations, already recorded

Do not re-file these; do challenge the reasoning if you disagree.

- **Duplicate curated names are not refused** (B-53). `EXPERIENCE.md · Flow 8`
  names a `threads: name in use` refusal. Deliberately not built: a uniqueness
  rule over a *display* name would refuse a legitimate correction, and the cure
  for two threads that are one subject is Merge. The softer half — an advisory
  beside Save — is the filed follow-up.
- **No unmerge / unsplit** (B-54). Outside the acceptance criteria. The record
  was built to make it cheap: a merge is one deletable row and the absorbed
  thread keeps its identity and its colour.
- **Curation controls sit on the list row, not additionally on the focused
  band's header.** `EXPERIENCE.md · Thread list` asks for both; the AC asks for
  "a band or its header". The row is what `EXPERIENCE.md`'s own keyboard order
  (line 211) describes, and the header would duplicate the same component.
  Worth a finding if you judge the header genuinely load-bearing.

## Gates

`make test-fast` for the loop; `make test` is the gate and needs the twins.
`make bootstrap` and `uv sync --project server` first in a fresh worktree. Do
not run `make evals-run`; do not start the shared worker or api.
