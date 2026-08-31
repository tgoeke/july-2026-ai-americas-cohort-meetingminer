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
- **Disposition** — patchable; remediation in progress.

## Disposition

Review in progress. No pass/fail verdict has been assigned.

## Verification

Not run yet.
