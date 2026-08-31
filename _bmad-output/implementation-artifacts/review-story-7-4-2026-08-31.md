# Code Review — Story 7.4: Speaker Naming UI

Date: 2026-08-31

## Scope

Adversarial review of the Story 7.4 web implementation, with emphasis on unsettled-evidence state retention, AD-13 identity handling, all three speaker-assignment paths, rerun event folding, combobox accessibility, replay behavior, and the meeting-view insertion. Server code and generated clients are out of scope; owner-decision or frozen-spec issues remain open.

## Review range

- Source branch: `story/7-4`
- Review branch: `story/7-4-review`
- Implementation-only range: `4e35269..6cdd1d2`
- Review base supplied by the handoff: `4e35269`
- Source head at review start: `6cdd1d2`

## Findings

### F1 — Cold recovery still cannot read speaker tags

- **Location:** `server/meetingminer/api/speakers.py:211`; `server/tests/test_api_speaker_assignment.py:581`
- **Severity:** High
- **Status:** Fixed on `story/7-4-review`
- **Finding:** `GET /meetings/{id}/speakers` still calls `_require_viewable` unconditionally, so a curator cold-loading a meeting whose speaker rerun failed cannot obtain the tag needed by the route-local recovery `PUT`. This contradicts the owner ruling in `docs/backlog.md` B-41.
- **Evidence:** Commit `7d8d93e` rules that the read must receive the same narrow, route-local recovery exception while drilldown and unrelated operations remain gated. The route still returns `meeting-not-viewable`, and `test_only_speaker_put_bypasses_the_failed_evidence_gate` currently asserts that obsolete 409 for the speakers read.
- **Suggested direction:** Red-first, change the failed-rerun boundary test to require a successful speakers response with the meeting's tags while retaining 409 for drilldown/moments and unrelated writes; implement the exception locally in the speakers read without changing `_require_viewable`.
- **Red/green evidence:** The revised boundary test first failed with `409 meeting-not-viewable`; after the route-local exception it passed. The adjacent fast API suites passed: 45 passed, 6 slow tests deselected.

### F2 — `job.done` cannot prove that extraction landed

- **Location:** `web/src/features/speakers/speakers.ts:342`; `server/meetingminer/api/events.py:235`; `server/meetingminer/domain/jobs.py:120`; `_bmad-output/implementation-artifacts/spec-7-4-speaker-naming-ui.md:74`
- **Severity:** High
- **Status:** Open — frozen-spec/owner decision required; not patched
- **Finding:** `applyJobEvent()` treats `job.done` as completion of every re-armed stage, including `extract`, and `landedSentence()` then states that extractions now carry the name. The wire deliberately emits `job.done` when evidence through `moments` becomes complete; `extract` is explicitly outside `EVIDENCE_STAGES` and may still be queued or running.
- **Evidence:** `_done_event()` contains no stage completion data and fires from `snapshot.complete`; `EVIDENCE_STAGES` ends at `moments`. The event stream also regards evidence-complete jobs as settled and may close after that transition. The frozen Story 7.4 matrix nevertheless defines `job.done` as the rerun-landed trigger and requires a sentence claiming extraction completed, so the implementation follows an internally incompatible contract.
- **Suggested direction:** Owner must amend one side of the contract: either provide a wire signal/status read that proves all `rearmedStages` (including `extract`) settled and make the UI wait for it, or narrow the landed claim to what `job.done` actually proves. Do not silently reinterpret `job.done` in the client.

### F3 — A route-parameter change leaves the old meeting actionable

- **Location:** `web/src/features/speakers/SpeakerNaming.tsx:116`; `web/src/features/speakers/SpeakerNaming.route.tsx:10`
- **Severity:** High
- **Status:** Fixed on `story/7-4-review`
- **Finding:** Changing `/meetings/:meetingId/speakers` can reuse the mounted component. Its effect starts new reads but does not invalidate old speakers, selection, draft, clip, transcript, failures, or rerun state. Until the new reads settle, an old row remains usable while `save()` already builds the request path from the new `meetingId`, allowing an old meeting's selected tag to be assigned on the new meeting.
- **Evidence:** `load` closes over the new ID, but `selected` continues to resolve from the prior `speakers` array and `selectedTag`; the save path uses the new prop. `SPEAKER_00`-style tags commonly exist in more than one meeting, so this is reachable without any malformed data.
- **Suggested direction:** Key the stateful screen by meeting identity so a parameter change synchronously remounts and clears all meeting-owned state before the new load. Preserve stale rows only across rereads of the same meeting.
- **Red/green evidence:** The regression first retained the old `SPEAKER_00` row after rerendering with `meeting-2`; the keyed state boundary removes it synchronously and the targeted test passes.

### F4 — Harmless edits discard a picked participant's identity

- **Location:** `web/src/features/speakers/SpeakerNaming.tsx:675`; `web/src/features/speakers/speakers.ts:217`
- **Severity:** Medium
- **Status:** Fixed on `story/7-4-review`
- **Finding:** Every input change unconditionally clears `picked`, even though `choiceOf()` is designed to keep the participant choice while the trimmed field still equals that participant's display name. Adding whitespace, or editing and restoring the original text, therefore changes the body from `{participantId}` to `{displayName}`. With two participants sharing a display name, the field text cannot recover which person the curator selected.
- **Evidence:** The suggestion click stores the exact `ParticipantRow`; the next `onChange` drops it before `choiceOf()` can apply its equality boundary. The API's exactly-one-field contract is still met, but the wrong assignment path is chosen and may mint or reuse a different participant.
- **Suggested direction:** Retain the picked row as selection provenance while the field is edited and let `choiceOf()` decide whether the current text still represents it. Verify whitespace, edit-away-and-restore, and duplicate-display-name selections.
- **Red/green evidence:** All three new boundary cases first sent `{displayName}`; after retaining selection provenance, whitespace, restored text, and a duplicate-name second-row pick all send the exact selected `participantId`. Four targeted assignment tests pass, including the existing type-over case.

### F5 — A successful assignment has no authoritative visible identity

- **Location:** `web/src/features/speakers/SpeakerNaming.tsx:282`; `web/src/features/speakers/SpeakerNaming.tsx:523`; `web/src/features/speakers/SpeakerNaming.tsx:769`
- **Severity:** High
- **Status:** Fixed on `story/7-4-review`
- **Finding:** After a successful assignment, the screen clears the field and creates a global rerun strip but does not show the saved choice or `rerun · queued` on its row. It also records `choice.displayName` rather than the authoritative `SpeakerAssignmentResponse.displayName`, so a participant renamed since roster load produces a stale landed sentence. After the landed reread, the transcript column still renders only tag, offsets, and text, making the assigned identity visually absent there.
- **Evidence:** Row rendering is exclusively from the pre-PUT `speakers` array until a later read; the success response's participant/name fields are ignored. The landed effect rereads both sources, but the transcript header/body never calls `resolvedName()`. This violates the matrix requirements that the row show the choice immediately and the change be visible in the transcript when the rerun lands.
- **Suggested direction:** Store the response-confirmed pending choice per tag and label it as awaiting rerun without claiming resolution; derive rerun copy from the response. On a successful settled reread, clear pending choices and render only `resolvedName(selected)` in the transcript heading, preserving AD-13.
- **Red/green evidence:** The row test first stayed a nameless placeholder after a response carrying a renamed participant, and the landed transcript remained tag-only. The row now shows the response-confirmed choice as `rerun · queued`; after the settled reread, pending state clears and the transcript displays only the name accepted by `resolvedName()`. Both targeted tests pass.

### F6 — Clip controls do not play or restart the sample

- **Location:** `web/src/features/speakers/SpeakerNaming.tsx:315`; `web/src/features/replay/ReplayPlayer.tsx:48`
- **Severity:** High
- **Status:** Fixed on `story/7-4-review`
- **Finding:** Pressing a clip control only mounts `ReplayPlayer` and seeks it; neither the control nor player calls `play()`. Pressing the already-selected clip again creates a new state object with identical `startMs`/`endMs`, so the player effects do not rerun and the stopped sample cannot restart from its beginning.
- **Evidence:** The player has controls but no `autoPlay` behavior; its seek effect depends only on `src` and `startMs`, and its latch effect depends on the same offsets. The existing caller test asserts only that the element appears, not that the user gesture starts or restarts media.
- **Suggested direction:** Add opt-in autoplay behavior to the shared player so existing open-ended callers remain unchanged, and give each speaker clip activation a fresh playback identity that remounts/reseeks/re-arms even for the same offset.
- **Red/green evidence:** The caller regression first observed zero `play()` calls after activation. Speaker clips now opt into playback and each press gets a fresh player identity; the same clip calls `play()` twice across two presses and remounts, while other callers retain the default non-autoplay behavior.

### F7 — Rerun terminal events have no resync or assignment ownership

- **Location:** `web/src/features/speakers/SpeakerNaming.tsx:197`; `web/src/features/meetings/useJobEvents.ts:48`; `server/meetingminer/api/events.py:322`
- **Severity:** High
- **Status:** Fixed on `story/7-4-review`
- **Finding:** The screen passes a no-op `onResync`, although the stream's silent baseline means completion or failure during a disconnect is never replayed. It also folds `job.done`/`job.error` by `jobId` alone even though consecutive assignments reuse the meeting's job ID. A delayed terminal frame from the first assignment can therefore land a newly installed queued rerun for the second.
- **Evidence:** `useJobEvents` documents that missed frames are gone and calls `onResync` only so the consumer can reseed. The speakers screen neither reseeds nor checks current job state. `applyJobEvent` has no generation or stage-snapshot input beyond the reused ID, and the assignment response supplies no distinct rerun ID.
- **Suggested direction:** Reconcile terminal frames, the immediate post-PUT state, and reconnects through the existing authoritative `GET /jobs/{jobId}` response. Apply the snapshot only if the same rerun object still owns the screen; this rejects delayed frames for a newer re-arm and recovers missed terminal transitions. Surface a lost connection while reconciliation is unavailable.
- **Red/green evidence:** Three regressions first showed that a reconnect left a completed rerun queued, a delayed terminal frame landed a newer assignment, and a lost stream remained invisible. Terminal frames and resync now reconcile through `GET /jobs/{jobId}` behind an object-identity generation guard, the post-PUT snapshot closes the no-frame gap, and a lost connection is named beside active progress. All 72 speaker tests pass.

### F8 — The `u` shortcut can submit a second assignment while Save is pending

- **Location:** `web/src/features/speakers/SpeakerNaming.tsx:295`; `web/src/features/speakers/SpeakerNaming.tsx:399`; `web/src/features/speakers/SpeakerNaming.tsx:800`
- **Severity:** High
- **Status:** Fixed on `story/7-4-review`
- **Finding:** `saving` disables the visible buttons, but `save()` itself has no in-flight guard and the panel's `u` shortcut calls it directly. Pressing `u` while a name assignment is pending aborts that request and immediately submits `{unresolved: true}`. The first request may already have committed server-side, so the screen can create two re-arms while displaying only the second result.
- **Evidence:** Every call to `save()` aborts `saveControllerRef.current` before installing a new controller. React state does not protect imperative callers, and `onPanelKeyDown` does not inspect `saving`; focus on any non-input control inside the naming panel makes the shortcut reachable while both assignment buttons are disabled.
- **Suggested direction:** Put a synchronous single-flight guard inside `save()` itself, release it only for the request that owns it, and leave disabled controls as presentation rather than the concurrency boundary. Verify that a pending Save followed by `u` issues exactly one PUT.
- **Red/green evidence:** A deferred PUT followed by the scoped `u` shortcut first produced two assignment calls, with the second carrying `{unresolved: true}`. A synchronous in-function guard now rejects every second entry path until the owning request releases it; the regression passes with exactly one PUT.

### F9 — A settled reread can strand selection on a removed tag

- **Location:** `web/src/features/speakers/SpeakerNaming.tsx:274`; `web/src/features/speakers/SpeakerNaming.tsx:281`
- **Severity:** High
- **Status:** Fixed on `story/7-4-review`
- **Finding:** Selection reconciliation only chooses the first row when `selectedTag` is `null`. If a successful settled reread returns honest rows that no longer contain the selected tag, `selectedTag` remains stale, `selected` becomes `null`, and the screen hides the naming controls and transcript even though other speaker rows are present.
- **Evidence:** `selected` is derived with `find(...) ?? null`, while the effect returns every non-null current tag without checking membership in the new `rows`. A rerun can legitimately change diarization output or concurrent recovery work can replace the tag set; this is exactly the state-retention boundary where stale evidence must remain usable without preserving an invalid pointer.
- **Suggested direction:** Preserve selection only while the refreshed rows still contain it; otherwise select the first available row, and retain `null` only for an empty result. Verify a landed reread that removes the active tag moves selection to a remaining tag.
- **Red/green evidence:** A landed reread returning only `SPEAKER_03` first left that row unselected and removed the naming region because selection still pointed to absent `SPEAKER_00`. Reconciliation now preserves a tag only while it exists in the refreshed rows and otherwise selects the first remaining row; the regression restores the `SPEAKER_03` naming region.

### F10 — Rerun changes are silent and the naming controls tab in the wrong order

- **Location:** `web/src/features/speakers/SpeakerNaming.tsx:500`; `web/src/features/speakers/SpeakerNaming.tsx:808`; `_bmad-output/planning-artifacts/ux-designs/ux-meetingminer-2026-08-29/EXPERIENCE.md:213`
- **Severity:** Medium
- **Status:** Confirmed — patch required
- **Finding:** The rerun strip changes stage words, failure, and landed content without a live region, so a screen-reader user who remains in the naming controls receives no progress transition. In the same keyboard path, DOM order places Save before Unresolved even though the accessibility floor specifies name field → Unresolved → Save.
- **Evidence:** The strip is a static `role="group"`; only the connection-lost paragraph has `role="status"`. Stage frames mutate descendant text without an announcement primitive. The JSX renders the primary Save button before Unresolved, reversing the spine's explicit tab order.
- **Suggested direction:** Add one atomic polite status summary for the rerun (not one live region per stage), and render Unresolved before Save while retaining Save as the single filled primary action. Verify both the stage announcement and the tab sequence.
