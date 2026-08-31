# Code Review — Story 7.3: Speaker Assignment

- Date: 2026-08-30
- Review branch: `story/7-3-review`
- Branch under review: `origin/story/7-3`
- Review status: in progress

## Scope

Adversarial review of the complete Story 7.3 implementation, its tests,
generated client changes, and closing documentation. Frozen intent-contract
defects will be reported as open and will not be patched. Patchable defects
will be recorded here before red-first remediation on the review branch.

## Review range

`4b7e60174f640f09f6e903255064193018ef223b..5dac13f`

The baseline is the specification commit; the range contains the Story 7.3
implementation through the builder's closing documentation commit.

## Findings

### F-1 — A corrected source attribution remains credited to the old participant

- Location: `server/meetingminer/pipeline/stages/align.py:724-730`
- Severity: Medium
- Finding: `align` marks the roster match as having spoken before it loads and
  applies a human speaker assignment. When a curator corrects an already
  resolved source label from participant A to participant B, the segments and
  `SPOKE_IN` attribution move to B, but A's `meeting_participant.derived_from`
  remains `both` instead of returning to `drop-graph`. If B was already in the
  source roster, the inverse is also possible: B remains `drop-graph` even
  though the corrected transcript now names B.
- Evidence: Added
  `TestRerun::test_correcting_a_source_named_tag_moves_transcript_provenance`
  and ran it against the unfixed implementation. It failed at
  `server/tests/test_api_speaker_assignment.py:787`: expected the old source
  participant's provenance to be `drop-graph`, observed `both`. The segment
  attribution itself had moved to the newly assigned participant, isolating
  the defect to attendance provenance.
- Suggested direction: Apply the assignment before setting roster `spoke`
  flags. Credit a source resolution only when no human assignment overrides
  that label; when an assignment targets a participant already in the roster,
  mark that target as having spoken. Keep the source participant as an
  attendee, but do not claim the transcript corroborates the superseded
  attribution.

### F-2 — The running-job refusal has a check-to-rearm race

- Location: `server/meetingminer/api/speakers.py:235-238,438-486`
- Severity: High
- Finding: `_JOB_FOR_MEETING` reads the job status without locking the job row.
  READ COMMITTED refreshes the status at that statement, but it does not keep
  the status current through the later alias and rearm writes. A competing
  request can queue the job and the worker can claim it after this route reads
  `done`; this route then writes the assignment and changes the worker's
  `running` job back to `queued`. The worker's eventual unconditional `done`
  write can erase the queued signal, so the accepted assignment is not
  guaranteed to receive a rerun.
- Evidence: Added
  `test_a_worker_cannot_claim_between_the_status_check_and_rearm` with a gated
  route connection and a real second Postgres connection. Against the unfixed
  code, the competing rearm plus `runner.claim_job` completed while the route
  was paused after its status read; the red assertion at
  `server/tests/test_api_speaker_assignment.py:524` observed
  `claimed_before_assignment_committed is True`. The route then returned 200
  and overwrote the job state.
- Suggested direction: Select the joined job row `FOR UPDATE OF j` before
  checking `job_status`, and hold that lock through the alias and stage rearm
  writes. This makes a claimant wait when the route saw a settled job and makes
  the route wait and observe `running` when a claimant won first. Keep READ
  COMMITTED so a lock wait sees the claimant's committed status.
