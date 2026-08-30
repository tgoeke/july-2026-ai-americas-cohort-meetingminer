---
title: 'Story 1.6: Moment Review Remediation'
type: 'bugfix'
created: '2026-08-19'
baseline_commit: 'f0d1669c019f42e6ea320656f6e4c673e1656546'
status: 'done'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/spec-1-6-moment-identification-completes-the-bundle.md'
  - '{project-root}/_bmad-output/implementation-artifacts/review-story-1-6-2026-08-18.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Moments can remain marked complete after `screens` or `align` replaces the evidence they depend on. That produces moment rows with cleared screenshot references or cascaded-away segment links, even though the pipeline resumes through them. Several low-risk contract and link-validation defects also remain from the Story 1.6 review.

**Approach:** Make the runner invalidate and recompute moments after successful upstream evidence rewrites, while preserving moment IDs. Restore the frozen stage-event contract and tighten the affected summary and source-link edge cases.

## Boundaries & Constraints

**Always:** Preserve existing moment UUIDs and never delete transcript-anchored moments. Queue `moments` only after a successful `screens` or `align` transaction, so failed upstream work leaves the old checkpoint intact. Continue to mark preserved screen rows superseded, but exclude them from the transcript-retention metric. A usable deep link must be an HTTP(S) URL with an authority; all transcript-only missing-link cases must carry the frozen `moments_without_link` event field. Replay evidence must remove fallback links from both recomputed and preserved rows.

**Ask First:** None.

**Never:** Do not change the moment boundary algorithm, schema identity model, capture density tuning, API/UI, `extract`, or Story 1.12 augmentation intake. Do not delete or re-key a moment to repair its dependent evidence.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|---------------|----------------------------|----------------|
| Screens rerun | A completed recording job queues only `screens` | Old screenshot references are replaced and `moments` reruns in the same claim, retaining the transcript moment ID and attaching current screenshot evidence | The failed screens path must not requeue moments |
| Align rerun | A completed transcript job queues only `align` | Cascaded links are rebuilt by the same runner pass; the retained moment ID has current, exactly-once segment coverage | The failed align path must not requeue moments |
| Missing source URL | Transcript-only meeting lacks a usable URL | Rows are written without a link and the summary includes `moments_without_link` | No error |
| Replay after linked moments | Screenshots/replay arrive while an old transcript moment becomes superseded | Citation row survives but its fallback deep link is NULL | No error |
| Hostless URL | `provenance.url` is `https:`, `https:/path`, or lacks a host | Treat as absent; never persist or render it | No error |

</frozen-after-approval>

## Code Map

- `server/meetingminer/pipeline/runner.py` — `run_job()` caches stage statuses before its loop. After a successful `screens` or `align` implementation, it must queue `moments` in the database and update that cached status before the loop reaches it; placing this before `conn.commit()` preserves rollback safety.
- `server/meetingminer/pipeline/stages/screens.py` — replaces all meeting screenshots at `run():323`; FK `ON DELETE SET NULL` is why a dependent moments rerun is necessary.
- `server/meetingminer/pipeline/stages/align.py` — replaces all transcript segments at `run():598`; the cascade removes `moment_segment` rows which the moments stage owns rebuilding.
- `server/meetingminer/pipeline/stages/moments.py` — stage summary fields and the supersession update. New planned rows already clear links through the upsert; preserved superseded rows need the equivalent replay behavior.
- `server/meetingminer/domain/drops.py` — `DropContents.stream_url` is the sole source-link validation boundary.
- `server/tests/test_worker_moments.py` — runner, direct-stage, log, and moment-row helpers; add regression coverage for both dependent-stage reruns and summary/link cases.
- `server/tests/test_drops.py` — parameterized `stream_url` acceptance/rejection tests.

## Tasks & Acceptance

**Execution:**
- [x] `server/meetingminer/pipeline/runner.py` -- invalidate `moments` after successful `screens` and `align` execution, synchronizing the in-memory stage-status view so it executes in the same claim -- replaces dependent evidence without leaving a false done checkpoint.
- [x] `server/meetingminer/pipeline/stages/moments.py` -- emit the frozen `moments_without_link` summary field, calculate `retained_stale` only from retained transcript-anchored rows, and clear fallback links on retained rows when replay exists -- restores the stage’s observable contract without touching citation identity.
- [x] `server/meetingminer/domain/drops.py` -- require an HTTP(S) authority/host in `stream_url` -- prevents a hostless pseudo-link from reaching storage or rendering.
- [x] `server/tests/test_worker_moments.py` -- add runner-level `screens`/`align` rerun regressions plus assertions for the exact log field, retention metric, and replay-retired stale link -- protect the dependency and contract paths against a superficially green suite.
- [x] `server/tests/test_drops.py` -- add hostless HTTP(S) URL cases -- pin the link-validation boundary.

**Acceptance Criteria:**
- Given a job at `extract` with moments done, when only `screens` or `align` is queued and succeeds, then the same run reaches a newly completed `moments` stage and leaves each retained citation ID backed by current screenshot/segment evidence.
- Given an upstream stage failure, when its transaction rolls back, then it does not invalidate a previously completed moments checkpoint.
- Given transcript-only missing/invalid URL input, when moments completes, then its structured summary has the exact `moments_without_link` field and no persisted source link.
- Given replay arrives while an old moment is retained as superseded, when the moments stage completes, then that row retains its ID but has no fallback link.

## Design Notes

The runner, rather than the upstream stages, owns checkpoint state. It must update its cached `statuses` mapping along with `job_stage`; otherwise it would still resume the old `moments: done` state in the same loop. The invalidation occurs only after the upstream implementation returns successfully and before its transaction commits, so a producer exception rolls both its replacement work and its dependent invalidation back together.

## Verification

**Commands:**
- `uv run --project server pytest server/tests/test_worker_moments.py server/tests/test_drops.py` -- expected: all selected tests pass, including new regressions.
- `uv run --project server pytest server/tests` -- expected: no new failures beyond the two pre-existing baseline failures documented by Story 1.6.
- `make migrate && make migrate` -- expected: both runs report nothing to apply.
- `pnpm --dir web run build` -- expected: production web build succeeds.

## Suggested Review Order

**Pipeline dependency invalidation**

- Queue the dependent stage transactionally and update the cached checkpoint view.
  [runner.py:342](../../server/meetingminer/pipeline/runner.py#L342)

- Prove both upstream reruns rebuild moments without changing citation identity.
  [test_worker_moments.py:435](../../server/tests/test_worker_moments.py#L435)

**Moment contract preservation**

- Retire stale fallbacks and restore the frozen summary field.
  [moments.py:224](../../server/meetingminer/pipeline/stages/moments.py#L224)

- Cover stale-screen accounting and replay retirement of retained citations.
  [test_worker_moments.py:743](../../server/tests/test_worker_moments.py#L743)

**Source-link validation**

- Reject hostless and malformed-port HTTP(S) pseudo-links at the sole boundary.
  [drops.py:118](../../server/meetingminer/domain/drops.py#L118)

- Pin malformed links alongside accepted recap URLs.
  [test_drops.py:65](../../server/tests/test_drops.py#L65)
