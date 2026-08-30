---
title: 'Story 1.12 Remediation: Failed-Job Retry Preservation'
type: 'bugfix'
created: '2026-08-19'
status: 'done'
baseline_commit: '985cc6a812dd92c9f10d185c8f6640d5eada7250'
review_loop_iteration: 1
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-1-12-late-recording-augmentation.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** A late-recording augmentation can fail after the worker has minted or refreshed its Meeting. A subsequent ordinary retry enters the pre-existing failed-job requeue path, which replaces the source drop and metadata without the augmentation guard. A recording-only retry can then cause alignment to remove an immutable provided transcript; changed identity metadata can rewrite the existing meeting and shift preserved moments.

**Approach:** Before re-queuing any failed job that already owns a Meeting, validate the incoming replacement against that Meeting and its current drop. Reuse the existing augmentation-preservation rules while keeping failed-before-mint retries unchanged.

## Boundaries & Constraints

**Always:** Preserve every provided transcript form carried by the failed job's current drop; refuse corpus, `startedAt`, and `startedAtPrecision` drift for a job with a Meeting; return RFC 9457 `invalid-augmenting-drop` before mutating job or stage rows; retain the existing failed-job response shape and same job id. A declared augmentation still requires its additional readiness and recording checks. The target drop remains read-only.

**Ask First:** No product choice is open: the frozen Story 1.12 contract already makes provided transcripts and moment timing immutable.

**Never:** Do not alter the no-Meeting failed-job retry path, introduce a second job or Meeting, change moment identity logic, loosen the recorded augmentation checks, or modify a source drop.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Failed before mint | Failed job has no Meeting; replacement drop is valid | Existing retry requeues the same job and reseeds all stages | Existing 200 response |
| Failed after mint, compatible retry | Failed job owns a Meeting; replacement retains the provided transcripts and matching identity fields | Same job requeues in place | Existing 200 response |
| Failed after mint, transcript lost | Replacement recording omits a provided transcript from the current drop | No job or stage mutation | 422 `invalid-augmenting-drop` |
| Failed after mint, identity drift | Replacement changes corpus, `startedAt`, or precision | No job or stage mutation | 422 `invalid-augmenting-drop` |

</frozen-after-approval>

## Code Map

- `server/meetingminer/api/ingests.py` -- `_check_augmenting_drop()` already compares corpus, wall-clock fields, and transcript filenames; `_accept_augmenting_drop()` supplies its declared-augmentation-specific recording check; the plain failed-job branch in `create_ingest()` currently bypasses both at :489–506.
- `server/meetingminer/pipeline/runner.py` -- `mint_meeting()` runs before stages; `_fail_job()` can therefore leave a failed job with durable Meeting/evidence rows.
- `server/meetingminer/pipeline/stages/align.py` -- provided transcript kinds absent from a replacement are deleted, then segments are replaced; this is the concrete AD-13 loss the intake check prevents.
- `server/tests/test_ingests.py` -- owns the failed-job requeue contract and augmentation refusal matrix; add the lifecycle regression here using its existing fixtures and snapshots.
- `server/meetingminer/migrations/0002_meetings_media_frames.sql` -- `meeting.job_id` is unique, so detecting a Meeting by job is unambiguous.

## Tasks & Acceptance

**Execution:**
- [x] `server/meetingminer/api/ingests.py` -- factor or extend the existing preservation validator so the failed-job requeue branch validates a replacement when its job already owns a Meeting, before changing `job`, `job_stage`, or `drop_path`; preserve the no-Meeting retry behavior exactly and refuse a recording-to-transcript-only downgrade.
- [x] `server/tests/test_ingests.py` -- add failed-after-mint retry regressions proving a recording-only replacement cannot shed a provided transcript or an already-recovered recording, without mutating the existing job/stages/drop reference; cover identity drift through the same validator where compactly practical.

**Acceptance Criteria:**
- Given an augmentation fails after a Meeting exists, when an ordinary recording-only retry is posted, then intake returns 422 `invalid-augmenting-drop` and the original provided transcript remains the active input.
- Given a failed job has no Meeting, when its valid replacement is posted, then the existing same-job requeue behavior remains unchanged.
- Given a failed job owns a Meeting, when a replacement restates corpus, `startedAt`, or `startedAtPrecision`, then no job or stage mutation occurs.

## Spec Change Log

### 2026-08-19 — review loop 1

- **Trigger:** The initial remediation deliberately made the generic existing-Meeting validator recording-agnostic. A failed augmentation whose Meeting already had `has_recording = true` could consequently be retried with a transcript-only drop, causing the worker to clear the recovered video evidence.
- **Amendment:** Require a replacement for an existing recorded Meeting to carry a recording; retain the recording-agnostic path only for an existing transcript-only Meeting and for failed-before-mint retries.
- **Avoids:** A failed late-recording augmentation becoming an unguarded recording-to-transcript-only downgrade that violates “augmentation adds, never destroys.”
- **KEEP:** Preserve the shared corpus/wall-clock/provided-transcript validator; preserve failure-before-mint requeue semantics, declared-augmentation requirements, and rejection-before-mutation assertions.

## Design Notes

The validator must distinguish “a replacement that repairs a failed initial ingest” from “a replacement that can overwrite an existing occurrence.” The presence of the Meeting row is that distinction. The generic existing-meeting validator should not require an `augments` declaration; it requires a recording only when the persisted Meeting already has one. This leaves an existing transcript-only Meeting and a failed-before-mint job retryable without video, but makes a failed late-recording augmentation preserve the recovered evidence.

## Verification

**Commands:**
- `cd server && uv run pytest tests/test_ingests.py -q` -- expected: the requeue and augmentation matrices pass, including the new failed-after-mint refusal.
- `cd server && uv run pytest tests/test_augmentation.py tests/test_worker_runner.py tests/test_worker_moments.py -q` -- expected: augmentation and pipeline identity behavior remain green. Needs the shared Postgres store; hold it exclusively.

## Suggested Review Order

**Existing-meeting retry boundary**

- Reuse one validator so failure recovery cannot mutate durable meeting identity.
  [`ingests.py:319`](../../server/meetingminer/api/ingests.py#L319)

- Gate failed-job requeue on the durable Meeting before replacing its source drop.
  [`ingests.py:532`](../../server/meetingminer/api/ingests.py#L532)

**Regression evidence**

- Prove compatible transcript-only recovery still requeues the same job.
  [`test_ingests.py:234`](../../server/tests/test_ingests.py#L234)

- Cover transcript loss and corpus or wall-clock drift without any mutation.
  [`test_ingests.py:262`](../../server/tests/test_ingests.py#L262)

- Prevent a failed recording augmentation from becoming a transcript-only downgrade.
  [`test_ingests.py:336`](../../server/tests/test_ingests.py#L336)
