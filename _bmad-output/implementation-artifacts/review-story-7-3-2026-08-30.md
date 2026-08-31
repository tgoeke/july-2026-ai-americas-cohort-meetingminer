# Code Review — Story 7.3: Speaker Assignment

- Date: 2026-08-30
- Review branch: `story/7-3-review`
- Branch under review: `origin/story/7-3`
- Review status: complete — changes requested; owner decisions remain open

## Scope

Adversarial review of the complete Story 7.3 implementation, its tests,
generated client changes, and closing documentation. Frozen intent-contract
defects will be reported as open and will not be patched. Patchable defects
will be recorded here before red-first remediation on the review branch.

## Review range

`4b7e60174f640f09f6e903255064193018ef223b..5dac13f`

The baseline is the specification commit; the range contains the Story 7.3
implementation through the builder's closing documentation commit.

The review branch was then rebased onto `origin/main` at `be34c6a` as required.
The expected `sprint-notes.md` conflict was resolved by retaining both main's
newer B-36 notes and Story 7.3's closing note. No implementation conflict was
encountered.

## Verdict

Story 7.3 does **not** pass review as done yet. Four patch findings were fixed
and verified on `story/7-3-review`; two medium frozen-spec findings remain open
for the owner. The story and sprint status are therefore `in-progress`, not
`done`. Nothing was merged to `main`.

| Finding | Triage | Result |
| --- | --- | --- |
| F-1 | patch | Fixed in `9d2806d` |
| F-2 | patch | Fixed in `5f40110` |
| F-3 | patch | Fixed in `108c749` |
| F-4 | decision needed | Open — frozen retry contract |
| F-5 | patch | Fixed in `08f3ad9` |
| F-6 | decision needed | Open — frozen key-space row |

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
- Result: Fixed red-first and verified in `9d2806d`.

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
- Result: Fixed red-first and verified in `5f40110`.

### F-3 — Source labels containing `/` cannot be assigned

- Location: `server/meetingminer/api/speakers.py:405-411`
- Severity: Medium
- Finding: The tag is opaque source evidence and the read route returns it
  verbatim, but the PUT route uses FastAPI's default single-segment path
  converter. A source-attributed label containing `/` is therefore visible and
  correctable in `GET /meetings/{id}/speakers` but can never reach the
  assignment handler. Percent-encoding does not help because the ASGI path is
  decoded before route matching.
- Evidence: Added `test_a_source_label_containing_a_slash_is_assignable` with
  the stored label `Platform / Operations` and sent the tag with `/` encoded as
  `%2F`. Against the unfixed route, the red assertion at
  `server/tests/test_api_speaker_assignment.py:377` expected 200 and observed
  the router's 404 before the handler ran.
- Suggested direction: Declare the final tag parameter with Starlette's
  `path` converter so it consumes the remaining decoded path verbatim, retain
  the existing exact database label check, and pin both routing and generated
  OpenAPI/client behavior with the slash regression test.
- Result: Fixed red-first and verified in `108c749`.

### F-4 — A failed speaker rerun has no curator-level retry path — OPEN (frozen spec)

- Location: `_bmad-output/implementation-artifacts/spec-7-3-speaker-assignment.md`
  (`<intent-contract>`, “Evidence not settled” row);
  `server/meetingminer/api/moments.py:451-480`;
  `server/meetingminer/api/ingests.py:890-925`
- Severity: Medium — Open; owner/spec decision required
- Finding: An accepted assignment persists its alias before the worker runs.
  If `align` or `moments` then fails, the failed evidence stage makes
  `_require_viewable` reject every meeting read and every later speaker PUT.
  The curator sees the saved name and the failed stage through job events, but
  cannot retry or correct it from the speaker surface. The meeting is not
  irrecoverable at system level: reposting the original source drop to
  `POST /ingests` requeues a failed job. That recovery deletes and reseeds all
  stage checkpoints, however, rather than retrying the assignment's exact
  `align → moments → extract` scope, and it is an operator ingest action rather
  than the Story 7.4 failure gesture.
- Evidence: `_fail_job` leaves the failed stage non-settled; the shared
  `_require_viewable` gate rejects whenever any evidence stage is not
  `done`/`skipped`. `api/jobs.py` has only `GET /jobs/{id}`. The only failed-job
  requeue found by route/symbol search is `create_ingest`'s retry branch, which
  executes `DELETE FROM job_stage` followed by `_seed_stages`. This is also why
  the assignment response text calling every 409 “transient: retry once the
  job settles” is false for a failed rerun: it will not settle without a new
  write action.
- Suggested direction: Amend the frozen matrix and choose an explicit recovery
  contract before changing code: either allow the same speaker PUT to re-arm a
  failed speaker-owned rerun, or add a job retry gesture that preserves the
  assignment's restricted stage scope. Story 7.4 then needs to expose that
  choice beside the failed-stage state. Do not silently relax the current
  evidence gate in this review lane.

### F-5 — The citation test did not detect assignment-only segment reordering

- Location: `server/tests/test_api_speaker_assignment.py:646-729`
- Severity: Medium
- Finding: The primary rerun test strongly pins moment ids and artifact
  lifecycle, but it did not snapshot the transcript's immutable structural
  fields. A regression that changes `transcript_segment.ordinal` only when an
  assignment exists can reverse the drilldown and chat transcript while every
  moment id and protected artifact remains unchanged. That violates the
  story's “re-attribute only” design and AD-13 without tripping the claimed
  citation-safety coverage.
- Evidence: Re-ran the builder's 1 ms timing mutation first; it correctly made
  the test fail by replacing `transcript:40000` with `transcript:40001`. Then
  applied an independent mutation at `align.py`'s insert mapping:
  `ordinal = total - index if speaker_assignments else index + 1`. The initial
  ingest remained normal and only the assignment rerun reversed the three
  segment ordinals. The full primary test still passed. `api/moments.py` and
  `api/chat.py` both order transcript output by `ts.ordinal`, so the mutation
  is externally observable despite unchanged citations.
- Suggested direction: In the primary rerun test, snapshot and compare the
  structural segment fields that an assignment must not alter — ordinal,
  start/end timing, text, and speaker label — while separately asserting the
  intended participant/resolution change. Re-run the ordering mutation and
  require that new assertion to fail before accepting the test change.
- Result: Fixed by a mutation-proved regression assertion in `08f3ad9`.

### F-6 — The frozen new-name matrix row should be amended — OPEN (frozen spec)

- Location: `_bmad-output/implementation-artifacts/spec-7-3-speaker-assignment.md`
  (`<intent-contract>`, “Assign a new display name” row)
- Severity: Medium — Open; owner/spec amendment required
- Finding: The row still requires the minted participant's `identity_key` to
  equal the speaker alias key. That is not merely stale implementation detail;
  it specifies the known unmergeable design. `participants.py` determines that
  a participant is merged away when its own identity key appears as an alias
  key. Giving a newly minted participant the key used by its own speaker
  assignment therefore makes it appear merged into itself and permanently
  closes the documented recovery path for cross-meeting splits.
- Evidence: The implementation correctly separates
  `speaker:<meetingId>:<tag>` from `curated:<meetingId>:<tag>`.
  `test_a_minted_participant_can_still_be_merged_away` passes with that split,
  and the builder's red-first result plus the spec Change Log document the
  failure with a shared key. The review also rechecked every
  `participant_alias` reader: `_IS_ALIASED` remains safe only because a
  `speaker:` key is never a participant identity key, while
  `_HAS_ABSORBED_ALIASES` correctly excludes the speaker namespace.
- Suggested direction: The owner should amend and re-freeze the matrix row to
  require `identity_key = curated:<meetingId>:<tag>`, with the assignment alias
  separately keyed as `speaker:<meetingId>:<tag>`, and retain the current
  non-name-shaped `normalized_name`. Do not alter the implementation to match
  the obsolete row.

## Verification

- `uv run --project server pytest -m "" server/tests/test_api_speaker_assignment.py -q`
  — 30 passed after remediation.
- `uv run --project server pytest server/tests/test_api_speakers.py
  server/tests/test_api_registry.py server/tests/test_api_participants.py -q`
  — 44 passed.
- `uv run --project server pytest -m "" server/tests/test_augmentation.py
  server/tests/test_worker_transcripts.py -q` — 39 passed.
- `make test-fast` — lint and mypy green; puller 128 passed; web 294 passed;
  evals 643 passed; server 2,031 passed, 3 named skips, 384 deselected.
- `make test` — puller 128 passed; web 294 passed; evals 643 passed;
  diarization/STT extra 92 passed; test-store reachability passed; full server
  2,415 passed with 3 named environment/network skips; production web build
  succeeded.
- `make check-client` — passed; the `{tag:path}` runtime converter preserves
  the existing `/meetings/{meeting_id}/speakers/{tag}` OpenAPI path, so no
  generated-client delta was required.
- `python3 _bmad/scripts/branch_conflicts.py --against story/7-3` — reported
  only expected overlaps: review fixes against their source Story 7.3 files,
  the known `sprint-notes.md` conflict, and Story 8.2's three generated-client
  files. No unrecorded integration overlap was found.

Mutation checks:

- Assignment-only `start_ms + 1` changed `transcript:40000` to
  `transcript:40001`; the primary citation test failed as claimed.
- Assignment-only reversal of `transcript_segment.ordinal` initially escaped
  the citation test, establishing F-5. After the new structural snapshot, the
  same mutation failed on reversed transcript order.
- Removing the assignment application, `extract` rearm, approved-moment draft
  protection, attendance row, merge hop, or `speaker:` merge-predicate filter
  remains covered by the builder's tests and the full local gate.
- The participant-merged-after-assignment case and the approved-artifact plus
  sibling-draft case both ran green. The latter is protected by `extract`
  itself: its only draft deletion excludes approved/published moments, and its
  proposal loop skips those moments.
- The builder's symmetric moment re-key attempt is correctly classified as a
  non-mutation of this story's invariant: changing the initial ingest and the
  assignment rerun to the same alternate key still gives both passes the same
  identity and therefore does not model an assignment-induced re-key.

## Closeout

- Review branch: `story/7-3-review` (pushed after every coherent unit).
- Story/spec status: `in-progress`; follow-up review recommended.
- Main integration: not performed, per the review-lane instruction and because
  F-4 and F-6 remain open.
