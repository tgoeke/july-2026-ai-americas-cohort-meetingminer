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
