# Story 6.5 Adversarial Review — Add-Meeting UI

Date: 2026-08-31

## Scope

- Review branch: `story/6-5-review`
- Source branch: `story/6-5`
- Original story range: `2d68dcc6dba31007c7d6fd84f0884edbc79508d5..d6216583cf601c925ef4ecdfae594c600be98a52`
- Required scope: the 13 additions listed in the Story 6.5 review contract
- Authority: frozen Story 6.5 intent contract, architecture decisions AD-11/AD-14/AD-18, adopted UX design, and Story 6.5 acceptance criteria

## Findings

### F1 — Probe transport Retry does not issue another probe

- **Location** — `web/src/features/acquisitions/AddMeeting.tsx:323`
- **Severity** — medium
- **Finding** — The Retry control shown after a probe transport failure clears the visible error but never reruns the probe. It assigns the current URL back to itself, so React preserves the state value and the probe effect's dependencies remain unchanged.
- **Evidence** — The handler clears `probeOwner.current.key`, sets `probeState` to `idle`, and calls `setUrl((current) => current)` at lines 323–328. The effect is keyed only by URL classification and normalized URL at line 143. Changing `probeState` therefore rerenders without re-entering the effect. This violates the frozen matrix's probe-transport row, which requires Retry, and leaves Submit disabled at `Waiting for the pre-flight check.` until the user edits the URL manually.
- **Suggested direction** — Give Retry an explicit dependency/generation that reruns the current normalized probe, and add a regression test that observes a second request and a successful answer after the first transport failure.
- **Disposition** — fixed red-first. The new focused test failed against the original handler (`expected probeAcquisition 2 calls, received 1`), then passed after Retry gained an explicit probe-attempt dependency.

### F2 — Probe outage is simultaneously described as a refusal

- **Location** — `web/src/features/acquisitions/AddMeeting.tsx:204`
- **Severity** — medium
- **Finding** — A rejected probe correctly renders `TransportNotice`, but the Submit explanation beside it says `The pre-flight check refused this URL.` The same failure is therefore presented as both an outage and a source refusal.
- **Evidence** — `ProbeState.failed` preserves the discriminated `Failure`, and lines 311–329 render transport and refusal with different components. The `submitReason` branch at lines 204–205 discards that discriminator and labels every failed probe a refusal. This contradicts the frozen constraint that an unreachable api is never dressed as a refusal and the review contract's requirement to verify the distinction on every failure path.
- **Suggested direction** — Derive the disabled-submit explanation from `failure.kind`, retaining refusal language only for an api-issued refusal and giving transport failure a neutral recovery sentence.
- **Disposition** — fixed red-first. The strengthened outage test failed because the neutral retry sentence was absent and the refusal sentence was present; it passed after the explanation began branching on `failure.kind`.

### F3 — Every failed acquisition falsely claims no drop was finalized

- **Location** — `web/src/features/acquisitions/AddMeeting.tsx:400`
- **Severity** — high
- **Finding** — The failed-acquisition surface always states `Nothing was downloaded, nothing minted, no meeting row exists.`, but `intake-failed` is recorded only after download and drop finalization. In that real failure path the screen contradicts both the server state and its own remediation.
- **Evidence** — `server/meetingminer/acquisitions.py:782-802` calls `post_ingest` after `youtube.acquire` returns a finalized drop, then writes `status="failed"` with rule `intake-failed` and remediation beginning `The drop is finalized`. `AddMeeting.tsx` renders the unconditional no-download/no-mint sentence for any served `status.refusal`. The frozen contract requires every rendered claim to be backed by served data and forbids invented state.
- **Suggested direction** — Remove the unconditional lifecycle claim (or make any phase-specific claim derive from an explicit served field). Preserve the api's refusal detail and remediation as the authoritative explanation.
- **Disposition** — fixed red-first. The intake-failure regression failed because the unconditional no-finalization sentence was present; it passed after the UI left lifecycle facts to the served refusal detail/remediation.

### F4 — Offline URL validation rejects a watch URL the server accepts

- **Location** — `web/src/features/acquisitions/youtubeUrl.ts:81`
- **Severity** — medium
- **Finding** — A watch URL with one valid `v` value and an additional blank `v` parameter is accepted by the server but blocked offline by the screen, so the claimed mirror has drifted.
- **Evidence** — Python's `parse_qs` in `server/meetingminer/youtube.py:244` drops blank query values by default; `video_id_from_url('https://youtube.com/watch?v=dQw4w9WgXcQ&v=')` returns the valid id. `URLSearchParams.getAll('v')` preserves the blank value, so the client sees two entries and rejects at lines 81–82. The frozen shape-valid contract requires the client to mirror the server and the review prompt explicitly calls out multiple `v=` keys.
- **Suggested direction** — Match `parse_qs` by discarding empty `v` values before applying the exactly-one rule, while continuing to reject two non-empty candidates.
- **Disposition** — fixed red-first. The server-accepted URL row failed as `invalid` against the original client parser, then passed after blank values were filtered before the exactly-one check.

### F5 — A newly edited URL can be submitted before its probe runs

- **Location** — `web/src/features/acquisitions/AddMeeting.tsx:110`
- **Severity** — high
- **Finding** — After one URL has an answered probe, editing the field to a different shape-valid video leaves the old `answered` state visible and Submit enabled until the new 600 ms debounce elapses. Clicking during that window starts the new URL without a successful preflight.
- **Evidence** — The effect changes ownership immediately but does not change `probeState` until the timer sets `probing` at lines 114–115. `submitDisabled` at line 192 depends only on `probeState.kind`, while the click handler submits the current `shape.normalized` at line 339. This violates the frozen requirement that Submit remain disabled until the current normalized URL's probe answers and defeats the probe's refusal-before-write purpose.
- **Suggested direction** — Clear the previous answer synchronously when a different normalized URL schedules a probe, then enable Submit only after that generation answers. Add a regression test covering the debounce window after editing an answered URL.
- **Disposition** — fixed red-first. The debounce-window regression observed an enabled Submit against the original effect; it passed after a new probe generation synchronously cleared the prior answer before scheduling its timer.

### F6 — The handoff fixture hides the real pre-mint meeting row

- **Location** — `web/src/features/acquisitions/IngestingMeetingCard.tsx:78`
- **Severity** — high
- **Finding** — Before the worker mints a meeting, the real `/meetings` endpoint already returns the queued job with `meetingId: null`. The card accepts that row and renders a partial meeting card, instead of the required pending sentence. The suite models this state as an empty meetings array, so it passes against a response shape the live api does not use.
- **Evidence** — `server/meetingminer/api/meetings.py:58-63` selects from `job` and left-joins `meeting`; `MeetingListItem.meeting_id` is explicitly nullable until worker claim at lines 79–81, and every job becomes an item at lines 151–170. `IngestingMeetingCard.seed` matches only `jobId` and commits the row. The frozen matrix requires `meetingId: null` to show that the row has not been minted and forbids a half-row; `AddMeeting.test.tsx:528-536` instead returns `meetings: []`.
- **Suggested direction** — Treat a matched item with no `meetingId` as pending, seed the test with the actual null-ID job row, and only render the finished-card structure once the served meeting identity exists.
- **Disposition** — fixed red-first. The real null-ID job fixture rendered `acquired-meeting` and failed to find `meeting-pending` against the original seed; it passed after seed required a served meeting id before committing the card row.

### F7 — Seed/SSE baseline race can leave the finished card stale forever

- **Location** — `web/src/features/acquisitions/IngestingMeetingCard.tsx:68`
- **Severity** — high
- **Finding** — The initial `/meetings` seed can read before a job transition while `/jobs/events` takes its silent baseline after the transition. No event is then emitted. The stream's connected-frame `onAlive` either gets discarded while seed is in flight or declines to reseed once a stale row is held, so the card can remain permanently behind reality.
- **Evidence** — `server/meetingminer/api/events.py:322-328` explicitly makes the opening snapshot a silent baseline and then emits a connected comment. `seed()` at lines 68–90 returns immediately when `seedingRef` is true without remembering the request; `onAlive` at lines 119–121 requests only while `rowRef` is null. Unlike `MeetingsList.requestSeed` (`web/src/features/meetings/MeetingsList.tsx:90-106`), this consumer has no pending/coalesced follow-up. The acquisition suite's hook mock captures only `onEvent`, so the critical `onAlive` ordering is untested.
- **Suggested direction** — Coalesce a seed requested during an in-flight seed into one follow-up read, and bracket the stream's first live frame with a seed even when the first response has already produced a row. Extend the hook mock to drive `onAlive` and reproduce a transition between the first seed snapshot and silent stream baseline.
- **Disposition** — fixed red-first. The deferred-seed test observed only one `/meetings` call against the original consumer; it passed after seed requests became coalesced and the stream's first alive frame always bracketed the initial snapshot with a follow-up read.

### F8 — A non-2xx acquisition poll cannot be retried

- **Location** — `web/src/features/acquisitions/AddMeeting.tsx:396`
- **Severity** — medium
- **Finding** — When `GET /acquisitions/{id}` answers with Problem Details, polling stops and the problem renders without Retry. Only thrown transport errors receive the recovery control, even though both paths leave a nonterminal acquisition with no scheduled next poll.
- **Evidence** — `useAcquisitionStatus.ts:69-71` sets `failure` and returns for every generated-client error, scheduling no timer. `AddMeeting.tsx:389-398` gives `retry` only to `TransportNotice`; the RFC problem branch is a bare `RefusalBox`. The frozen poll-failure requirement says the last stepper state stays visible and Retry resumes polling; it does not permit an HTTP failure to strand the flow.
- **Suggested direction** — Preserve the parsed problem fields, but offer the same explicit retry action and verify that it starts a new poll without clearing the last known acquisition state.
- **Disposition** — fixed red-first. The HTTP-poll regression found no accessible Retry control against the original branch; it passed after the parsed problem box gained an explicit retry action wired to the polling hook.

## Disposition

Review in progress. No pass/fail verdict has been assigned.

## Verification

Not run yet.
