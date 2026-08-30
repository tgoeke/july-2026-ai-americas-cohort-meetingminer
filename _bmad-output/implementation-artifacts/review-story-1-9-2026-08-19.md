# Follow-up code review — Story 1.9: Ingestion Progress in the UI

## Reviewed range

`d7b742455462a6adf9f14f499778a3604cba03d8..f912e58f9790eefdbade47ce7689545f0a119269`

`git log --oneline d7b7424..f912e58` confirms that the range contains only
`f912e58 fix(web,api): re-seed the meetings list when an event overtakes the first seed`.
The dirty working tree was explicitly excluded because it contains Story 1.7 work.

## Verdict

The seed/SSE race is correctly fixed and its two UI regressions pass. The two cadence findings
below were resolved in post-review remediation `e2dc94c`; their focused API and UI regressions
pass. Story 1.9 passes this follow-up review.

## Findings

### Defects

#### 1. Heartbeat cadence is coupled to the polling interval

- **Severity:** medium
- **Location:** `server/meetingminer/api/events.py:327`, `server/meetingminer/api/events.py:365`
- **What is wrong:** The stream sleeps for `poll_seconds` before it checks whether
  `heartbeat_seconds` has elapsed. The configuration permits the heartbeat to be smaller than the
  poll interval, but in that valid state the loop cannot send its `: heartbeat` comment on the
  configured cadence.
- **Concrete failure:** With `job_events_poll_seconds=2.5` and
  `job_events_heartbeat_seconds=0.2`, an idle stream stays silent for roughly 2.5 seconds before
  its first heartbeat, rather than emitting one after about 0.2 seconds. The default values hide
  this because the normal poll is shorter than the normal heartbeat.
- **Why it matters:** The heartbeat setting is documented as the maximum silent period for an idle
  stream. A valid production retune can silently make liveness reporting materially slower than
  configured.
- **Required outcome:** Schedule reads and heartbeats independently (or constrain validation so
  the documented invariant is always achievable), then prove both cadences at the SSE boundary.

### Verification gap

#### 2. Cadence tests do not pin the configured values or their independence

- **Severity:** low
- **Location:** `server/tests/test_api_events.py:422`, `server/tests/test_api_events.py:455`
- **What is missing:** The fast heartbeat test permits three configured 0.2-second heartbeats to
  take almost two seconds. The slow heartbeat and poll tests assert only lower bounds, and the
  poll test does not observe heartbeats despite setting `poll=2.5` and `heartbeat=0.2`.
- **Mutation that remains green:** Capping settings at the route boundary, such as
  `min(configured_poll, 1.0)` and `min(configured_heartbeat, 1.5)`, keeps all three new tests
  green even though slower configured values no longer control their respective cadence. Likewise,
  the current polling loop leaves the 0.2-second heartbeat untested.
- **Required outcome:** Use bounded timing windows that reject both prematurely and materially
  delayed output, and include a test with a fast heartbeat and slow poll that asserts heartbeat
  timing independently of stage-event polling.

## Verification performed

- `cd web && pnpm test -- MeetingsList.test.tsx` — **38 passed** across 3 files.
- `cd server && uv run pytest tests/test_api_events.py -q` — **21 passed** after Story 1.7 had
  completed and no competing store-backed test process was active.

The review did not inspect uncommitted Story 1.7 files.

## Remediation applied

- `job_event_stream()` schedules the nearer of its next poll and heartbeat deadline, so a fast
  configured heartbeat is no longer held behind a slow read cadence.
- The cadence regressions now use independent poll/heartbeat values and bounded timing windows
  that reject both early and materially delayed output.
- Python compilation and `git diff --check` passed. Ruff is unavailable in this environment.
- Dismissed as duplicates/noise: 10 layer observations, including duplicate timing-bound claims
  and unrelated Story 1.7 sprint-state commentary.
