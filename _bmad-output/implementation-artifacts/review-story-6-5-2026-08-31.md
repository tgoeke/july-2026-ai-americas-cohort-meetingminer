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

### F9 — Enter in the URL field does not submit

- **Location** — `web/src/features/acquisitions/AddMeeting.tsx:268`
- **Severity** — medium
- **Finding** — After a successful probe, pressing Enter in the focused URL field does nothing; only pointer activation of Submit starts the acquisition.
- **Evidence** — The URL control and click-handled button are not inside a form and the input has no key handler. The adopted UX Flow 1 explicitly specifies `Enter. POST /acquisitions answers 202` (`EXPERIENCE.md:371`), and the field is the initial focus target, so this is the documented keyboard path rather than an optional shortcut.
- **Suggested direction** — Give the YouTube panel native form submission semantics, keep non-submit actions as buttons, and test Enter after the current probe has answered.
- **Disposition** — fixed red-first. The keyboard regression observed zero `startAcquisition` calls against the original click-only controls; it passed after the panel gained native form submission with Submit as its submit button.

### F10 — Posted job label truncates to four characters instead of eight

- **Location** — `web/src/features/acquisitions/acquisitions.ts:178`
- **Severity** — low
- **Finding** — The posted step shows only four job-id characters, while the frozen posted-state matrix requires the first eight before the ellipsis.
- **Evidence** — `postedWordFor` uses `jobId.slice(0, 4)` and its unit test pins `8f3c…`; the contract requires `posted — job <8 chars>…`. Four characters are materially less useful when correlating the visible acquisition with logs or status output.
- **Suggested direction** — Render the first eight characters and update the unit and component assertions to pin the contract.
- **Disposition** — fixed red-first. The strengthened unit assertion received `posted — job 8f3c…` from the original helper, then passed after the prefix changed to eight characters; the component assertion pins the same output.

### F11 — Acquisition and ingestion transitions are not announced

- **Location** — `web/src/features/acquisitions/AcquisitionStepper.tsx:59`
- **Severity** — medium
- **Finding** — Visible progress bars update, but neither acquisition transitions nor the handed-off job-stage transitions write to a polite live region. Screen-reader users receive the initial labels only when navigating back to them and miss the live flow.
- **Evidence** — `AcquisitionStepper` has no live announcer; its only `aria-live` is deliberately `off` on the diagnostic log. `IngestingMeetingCard` patches `StageProgress` without an announcement. The adopted Accessibility Floor requires acquisition and ingestion progress to announce politely once per transition through one region per stepper/list (`EXPERIENCE.md:215`).
- **Suggested direction** — Add a single atomic polite region for the acquisition stepper's current transition and one for this card's stage list, leaving the noisy log `off`; pin posted and streamed-stage announcements in tests.
- **Disposition** — fixed red-first. The posted-state test could not find an acquisition announcer against the original stepper; after adding the polite regions, posted announces its served job prefix and a streamed `frames done` event updates the ingestion announcement.

### F12 — Auto-caption probes hide the speaker-label consequence

- **Location** — `web/src/features/acquisitions/AddMeeting.tsx:310`
- **Severity** — medium
- **Finding** — When the probe reports `captions.kind: "auto"`, the screen prints only `captions: auto en`. It never tells the user that YouTube auto-generated captions carry no speaker attribution, so the most common corpus outcome—segments arriving as `Unknown`—is hidden until after the acquisition is committed.
- **Evidence** — `ProbeResult.captions.kind` is a served field and the owner's live probe returned `auto`; the owner also confirmed those captions carry no speaker labels. `EXPERIENCE.md:305` makes the probe's captions answer part of the pre-submit contract, and Flow 1's eventual `Name speakers` action is specifically for captions that carried no speakers (`EXPERIENCE.md:374`). The current answered branch renders only `probeSummary(...)` plus `Nothing has been written.` even though it has enough data to state the limitation without guessing.
- **Suggested direction** — When and only when the served probe kind is `auto`, put a concise pre-submit warning next to the probe answer that speaker labels are absent and segments will initially appear as `Unknown`; pin both its presence for auto captions and its absence for manual captions.
- **Disposition** — fixed red-first. The auto-caption probe regression could not find any speaker-label guidance against the original screen; after remediation, an `auto` answer names the absent labels and initial `Unknown` segments, while the existing manual-caption path pins that no warning is invented.

### F13 — The finished flow omits a supported Name speakers action

- **Location** — `web/src/features/acquisitions/IngestingMeetingCard.tsx:213`
- **Severity** — medium
- **Finding** — A newly acquired auto-captioned meeting never offers `Name speakers`, even after its served `transcribe` stage reaches `done`. The builder's stated reason—that `MeetingListItem` has no speaker-attribution field—is true of that row but not of this flow as a whole: the parent still owns the probe's served `captions.kind`.
- **Evidence** — The probe answer is retained in `AddMeeting`'s `ProbeState.answered`; `auto` is the source's explicit absence of speaker-attributed captions, not an inference from meeting content. The finished card already receives `stages[]`, whose `transcribe: done` value is the backing field named at `EXPERIENCE.md:316`. The adopted state and focus-order contracts require the action in this condition (`EXPERIENCE.md:144,212,374`), and `/meetings/:meetingId/speakers` is a registered route. No current prop carries the probe fact or the navigation callback to the card.
- **Suggested direction** — For a newly created acquisition whose served probe kind was `auto`, carry that fact into the finished card and render `Name speakers` only after `transcribe` is `done` and a real meeting id exists; navigate to the existing speakers route. Do not infer the same for `result: exists`, where names may already have been assigned.
- **Disposition** — fixed red-first. The focused auto-caption completion test could not find the action against the original card; it passed after the parent carried the served probe fact into the card and the route wired the existing speakers destination. The manual-caption handoff pins that the action is not guessed, and `result: exists` is deliberately excluded because a prior naming state is not served here.

### F14 — An unrecognised acquisition status silently unlocks the form

- **Location** — `web/src/features/acquisitions/AddMeeting.tsx:187`
- **Severity** — medium
- **Finding** — If the api returns any status outside this client's four known values, polling stops, the running step is drawn as queued, and the URL field unlocks with no explanation. A state the client cannot interpret is therefore presented as if the acquisition were no longer active.
- **Evidence** — The generated `AcquisitionStatus.status` is an open `string`. `useAcquisitionStatus` intentionally stops when `isLive` is false, including an unknown value; `locked` uses the same live-only predicate, and `stepperSteps` falls through to queued bars. This conflicts with AD-18's named-failure rule and with the existing ingestion-stage convention in `stageStyles.ts`, where unknown served values render loudly as `unknown` instead of being disguised. It also violates the frozen lock boundary: the form unlocks before a served `posted | failed` terminal state.
- **Suggested direction** — Keep the form locked unless the served value is exactly `posted` or `failed`, render the raw unknown value with the existing visual `unknown` state and a named compatibility notice, and offer an explicit poll Retry rather than inferring a terminal outcome.
- **Disposition** — fixed red-first. The regressions observed both an unlocked field and a queued-looking bar against the original handling. After remediation, only explicit `posted | failed` unlocks the form; an open-string status outside the known vocabulary renders fuchsia `unknown`, preserves its raw value in a compatibility alert, and offers Retry to read the acquisition again.

### F15 — A populated meeting card hides that its progress is stale

- **Location** — `web/src/features/acquisitions/IngestingMeetingCard.tsx:177`
- **Severity** — medium
- **Finding** — Seed and stream failures are rendered only while `row === null`. Once a row has loaded, losing `/jobs/events` or failing a reseed leaves the old card and stage bars looking current with no stale label.
- **Evidence** — Both `seedError` and `connection.kind === 'lost'` alerts live exclusively in the pending return at lines 177–190; the populated-card return never reads either value. `EXPERIENCE.md:158` requires every unreachable-api surface to keep stale content *and label it*, while AD-18 forbids silent fallback. This path is especially consequential here because the card is the handoff from acquisition polling to the job stream: after `posted`, no acquisition polling remains to expose the outage.
- **Suggested direction** — Keep the last served card, but render the same named seed/stream alerts alongside it whenever either source is unavailable; add a regression with an existing row and a lost stream.
- **Disposition** — fixed red-first. With a served meeting row and a mocked lost stream, the original card kept its bars but contained no outage text. The same regression passed after the populated branch retained the card and rendered both stream-loss and reseed-failure alerts beside it.

## Disposition

Review in progress. No pass/fail verdict has been assigned.

## Verification

Not run yet.
