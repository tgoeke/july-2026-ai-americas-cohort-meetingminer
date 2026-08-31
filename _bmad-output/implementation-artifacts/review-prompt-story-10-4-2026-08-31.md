# Reviewer handoff — Story 10.4: Moments Feed Ranking

Branch `story/10-4`, cut from `3211a7f`. Spec:
`_bmad-output/implementation-artifacts/spec-10-4-moments-feed-ranking.md`
(status `review`). Story: `epics.md` line 1757. Build prompt:
`build-prompt-story-10-4-2026-08-31.md`. Wave rules:
`wave-2026-08-30-rules.md`.

**Work in your own worktree**, on `story/10-4-review`, cut from `story/10-4`.
Never work in the main checkout, never commit to `main`, never merge — the
owner runs `integrate`.

## The review lane fixes what it finds

Owner ruling, 2026-08-30:

> Report every finding in the report file first (report-first, committed
> before reading code), then FIX the patchable ones yourself on
> `story/10-4-review` in your own worktree, red-first — the test observed
> failing against the unfixed code, then the fix, then green — committing each
> with its finding number. Leave unfixed, and clearly marked open, only what
> needs an owner decision or is rooted in the frozen spec. Never commit to
> `main`, never work in the main checkout, never merge — the owner runs
> `integrate`.

## What was built

| Path | Change |
|---|---|
| `server/meetingminer/migrations/0018_ranking_signals.sql` | NEW. `ranking_signal` (kind `risk`/`question`, moment-anchored, no `state`), two indexes, `updated_at` trigger, `extraction_source.kind` widened. |
| `server/meetingminer/api/moments_feed.py` | NEW. `GET /moments/feed`, `ROUTER_ORDER = 35`. Wire models, candidate dataclasses, the pure scorer, `validate_reasons`, `rank_and_validate`, the candidate query. |
| `server/meetingminer/pipeline/extraction.py` | The ranking-signals document: kinds, prompt builder, `R`/`Q` prefix map, `_signal_label_and_detail`, `signal_detail`. |
| `server/meetingminer/pipeline/stages/extract.py` | The fourth pass, its rerun delete, its insert, its summary counters. |
| `config.yaml` | The `ranking:` block appended at EOF — nine weights, two windows, four bounds, the prompt, each with rationale. |
| `server/meetingminer/config.py` | `RankingWeights`, `RankingConfig`, `Settings.ranking`. |
| `server/tests/test_ranking_signals.py`, `test_api_moments_feed.py` | NEW. |
| `server/tests/conftest.py`, `test_config.py`, `test_worker_extract.py`, `test_extraction_topics.py`, `test_api_registry.py` | Forced updates — see the spec's change log. |
| `docs/backlog.md` | B-46. |

`server/meetingminer/api/moments.py` is untouched (story 2.2 owns it).

## Where to look hardest

1. **The validate-then-page order.** This is the clause the AC calls out and
   the one a refactor would quietly invert. `rank_and_validate` takes no
   `limit` and no `offset` on purpose. Check that nothing has crept in that
   lets `total` count a row the caller cannot receive — including through the
   `kind` filter, which is applied after validation and before the slice.
   Adversarial angle: is there any input for which
   `offset + len(items) > total`, or for which a row appears on two pages?
2. **`colorOrdinal` is served as `null`** because story 10.3's migration 0017
   adds the column, in parallel. The query reads it as
   `to_jsonb(t) ->> 'color_ordinal'`. I checked `origin/story/10-3` on
   2026-08-31: its 0017 declares `thread.color_ordinal` (a `bigint` from
   `thread_color_ordinal_seq`), which is exactly the key this query reads —
   so the real ordinal should flow the moment 10.3 lands, with no edit here.
   **Verify that end to end once 10.3 is on `main`**, including that the
   value survives the `->>` text extraction and `int(ordinal)` in
   `_thread_of`, and that a `bigint` beyond 32 bits does not surprise
   `FeedThread.color_ordinal`. That is the single highest-value item on this
   list.
3. **The scoring model is a judgement call, and it is the demo's front door.**
   Weights are per kind, once, not per row (a talkative meeting must not hold
   the whole feed). Recency decays exponentially; due urgency falls linearly
   and clamps when overdue. A `recency` reason is emitted only inside one
   half-life while the term always scores. Do the shipped numbers actually
   produce a sensible first screen? Seed something realistic and look at it.
   A finding here is worth more than a finding about a docstring.
4. **`stated_timing` parses free text written by a model.** It reads only the
   labelled line matching `timing|due|deadline|when|by`. Hunt for real
   summariser output shapes it misses, and for a body where it reads the wrong
   line. Note that `_title_and_body` renders `<header>: <cell>`, so a header
   containing a colon would already have split.
5. **The candidate scan is the query that runs on a corpus of hundreds of
   meetings.** Four `EXISTS` subqueries plus four `LATERAL` joins. Is it
   bounded? Is there an index it wants that does not exist? The AC for story
   10.3 demanded a query-shape test for the same reason; this story has none.
6. **The fourth extraction pass costs a model call per meeting.** Confirm it
   is genuinely free (local Ollama, `llm.roles.extraction`) and that the
   one-retry discipline and the superseded-moment skip match the topics pass
   exactly.

## Known open items — do not re-report as discoveries

- **`ranking.signals_prompt` is not under `llm.roles.extraction`.** Filed as
  B-46 with the reason (footprint discipline in a parallel wave). This is a
  **first-class candidate for you to fix**: the wave's footprint no longer
  binds once these branches are landing, and moving it is a small, mechanical
  change with an obvious test. If you fix it, close B-46 in the same commit.
- **The backlog counter is over-subscribed across this wave.** The wave
  prompts told every lane "highest in use is B-40", but `main` already had a
  B-41 (an eval-harness item). Measured on 2026-08-31, the in-flight branches
  claim: `story/7-4` B-41 **and** B-42, `story/8-3` B-42 and B-43,
  `story/10-3` B-42, `story/10-6` B-44 and B-45. I moved this story's entry
  to **B-46** to sit clear of all of them, but three separate B-42s and a
  duplicate B-41 still have to be reconciled at integrate — that is an owner
  or coordinator job, not this review's.
- **`make client` is owed at integrate, and story 10.5 is blocked on it.**
  The target requires a live api on `:8000` (`infra/Makefile:1139`), which
  this lane is forbidden to start — the shared api/worker must stay down
  during the corpus ingest, and a worktree's `make up` collides on that port
  anyway (B-35). Story 6.4 left the same obligation to integration for the
  same reason. **What I did instead:** built the app in-process and dumped
  `app.openapi()`. `getMomentsFeed` takes `corpus`, `thread`, `meeting`,
  `kind`, `limit`, `offset` (all optional), and the schemas are
  `MomentsFeedResponse{items,total,limit,offset}`,
  `FeedItem{momentId, meetingId, meetingTitle, startedAt,
  startedAtPrecision, startMs, endMs, corpus, hasRecording, sourceDeepLink,
  screenshotId, viewType, preview, threads, reasons}`,
  `FeedReason{kind,label,ref,at}`, `FeedThread{threadId,name,colorOrdinal}`
  — the AC's names exactly, which is what story 10.5 is coding against. The
  generated TS client still has to be produced once an api is running.
- **No query-shape test on the candidate scan** (item 5 above). Named, not
  written.
- **No `score` on the wire.** Deliberate: the AC enumerates the card's fields.
  If you think a debug-only score is worth it, that is an owner decision.
- **`/media/files/{mediaId}` does not exist yet.** This story serves the
  opaque `screenshotId` and no path, which is its half of AD-17; building the
  route is not in this footprint. Story 10.3 reached the same conclusion
  independently and filed it (its B-42, "AD-17's id-addressed media route does
  not exist"), so the gap is on the record — do not file it a third time.

## Verification to reproduce

Your worktree owns a private Docker stack. `make bootstrap` first, then
`uv sync --project server` before `make lint`.

```bash
make test-fast                       # includes make lint + make typecheck
uv run --project server pytest server/tests/test_ranking_signals.py \
    server/tests/test_api_moments_feed.py -q
make test                            # the full gate, private stack up
python3 _bmad/scripts/branch_conflicts.py --against story/10-4-review
```

Never run `make evals-run`, never start the shared api or worker, never
`git add -A`, never reset/stash/clean outside your worktree.

## Finish

Report file committed first. Fixes red-first, each commit naming its finding
number. Spec's Review Triage Log updated. Push `story/10-4-review`. Do not
merge; do not mark the story done.
