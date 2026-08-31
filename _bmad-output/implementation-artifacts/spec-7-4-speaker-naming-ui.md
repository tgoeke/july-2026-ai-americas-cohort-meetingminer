---
title: 'Story 7.4: Speaker Naming UI'
type: 'feature'
created: '2026-08-31'
status: 'draft'
baseline_commit: '3211a7f96b86d7df496cefa451b2cbd431e6d8b4'
review_loop_iteration: 0
followup_review_recommended: false
context: []
warnings: []
deferred: []
---

<intent-contract>

## Intent

**Problem:** Stories 7.1, 7.2 and 7.3 built the whole speaker chain — diarization
produces `SPEAKER_NN` tags, `GET /meetings/{id}/speakers` serves each tag with talk
time, segment count and three sample offsets, and `PUT /meetings/{id}/speakers/{tag}`
records a participant id, a new display name, or `unresolved` and re-arms
`align → moments → extract`. None of it is reachable. There is no screen, so the
corpus still describes anonymous voices and the only evidence the chain works is a
pytest run (UX-DR14, FR37).

**Approach:** One new screen at `/meetings/:meetingId/speakers`, built from the
existing generated client — no endpoint, no client regeneration. Three columns at
full density (speakers rail · clips and naming · tag-filtered transcript), the
`speaker-naming.html` mockup's composition under the DESIGN.md/EXPERIENCE.md spines.
`ReplayPlayer` gains an optional `endMs` so a sample clip stops after eight seconds;
every existing caller keeps open-ended playback. The meeting view gains one control
that reaches the screen and nothing else.

## Boundaries & Constraints

**Always:** The three assignment paths — an existing participant picked from
suggestions, a typed new display name, `unresolved` — each send the request shape
`AssignSpeakerRequest` names, and each is covered by a web test. Suggestions are
shown, never applied (`Suggestions are shown, never applied — pick one or type a
name.`); nothing pre-fills the field. An unresolved tag renders as its
`SPEAKER_NN` label with its `speakerResolution` word and no name — AD-13, the UI
never presents a guessed identity. A successful `PUT` states that the meeting is
reprocessing (the `rearmedStages` the api returned, live from `GET /jobs/events`),
never a spinner that looks like a hang.

**The unsettled-evidence clause.** Story 7.3 deliberately admits the `PUT` while a
meeting's evidence is unsettled so a curator can correct a failed rerun, while its
sibling `GET /meetings/{id}/speakers` and `GET /meetings/{id}/drilldown` both still
refuse with 409 `meeting-not-viewable`. A rename therefore makes the screen's own
two reads start refusing seconds after it succeeds. The screen must survive that:
last-known speaker rows and transcript segments stay on screen, labelled as
reprocessing rather than blanked, and every naming control stays live, because that
route-local exception exists precisely so this screen keeps working.

**Never:** no new api route, no edit to `server/**`, no regeneration of
`web/src/client/*.gen.ts`. No restructuring of the meeting view (story 2.2 owns it
and its tests) — one control, added to the existing rail. No touch to the app shell
(story 10.5) or the ask box (story 8.3). No new test appended to an existing test
module. No behaviour change for a `ReplayPlayer` caller that passes no `endMs`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| Tags listed | `GET …/speakers` → rows, talk time descending | one row per tag: label, share bar, `41%`, `23m 51s · 112 segments` | — |
| Talk share | client-side `talkTimeMs / Σ talkTimeMs` | integer percent; `0%` when the sum is 0 | never NaN |
| Unresolved tag | `speakerResolution` ≠ `resolved` | the tag, the resolution word, **no name** (AD-13) | — |
| Resolved tag | `resolved` + `displayName` | the name beside the tag, `from transcript`, `Correct` instead of `Name` | — |
| Pick a participant | a suggestion chosen, then Save | `PUT` body `{participantId}` | 404 `unknown-participant` → refusal box under the field |
| Type a new name | text typed, no suggestion chosen | `PUT` body `{displayName}` | 422 → refusal box |
| Unresolved | the third button | `PUT` body `{unresolved: true}` | refusal box |
| Save succeeds | 200 `SpeakerAssignmentResponse` | rerun strip from `rearmedStages`, each `queued`, live from `/jobs/events`; the row shows the choice | — |
| Rerun lands | `job.done` for that `jobId` | `Rerun landed <ts> — transcript, graph, and extractions now name <tag> as <name>. Moment ids and citations unchanged.`; both reads re-run | — |
| Rerun fails | `job.error`, or a stage `failed` | `Rerun failed at <stage> — <error>. Names are saved; the transcript still shows tags.` | naming stays usable |
| Reads refuse mid-rerun | 409 `meeting-not-viewable` after a save | last-known rows and segments kept, labelled reprocessing; controls live | never blanked |
| Cold load into an unsettled meeting | 409 on first read, nothing cached | the api's own sentence + Retry | filed as B-41 |
| No diarization | `speakers: []` | `No speaker tags for this meeting — the transcript arrived speaker-attributed, or the diarizer is noop (config.yaml: diarizer.engine).` | — |
| Clip | a sample offset pressed | the one player opens at `startMs`, pauses at `startMs + 8000` | a caller with no `endMs` plays open-ended |
| Job busy | 409 `assignment-target-busy` | the api's sentence in a refusal box | retryable |
| Api unreachable | fetch rejects | `Cannot reach the api at {API_BASE}: {message}.` + Retry | — |

## Verification

- `web/src/features/speakers/speakers.test.ts` — the pure helpers: share, labels,
  request bodies for all three choices, suggestion filtering, the resolution rule
  that never names an unresolved tag, the rerun sentences.
- `web/src/features/speakers/SpeakerNaming.test.tsx` — the screen: all three
  assignment paths end-to-end against a mocked sdk; suggestions never auto-applied;
  the rerun strip and the landed sentence; the 409-after-save case keeping rows and
  controls; the no-tags sentence.
- `web/src/features/replay/ReplayPlayerClip.test.tsx` — `endMs` pauses at the
  boundary and only once; no `endMs` never pauses.
- `web/src/features/moments/MeetingSpeakersLink.test.tsx` — the meeting view's one
  new control.
- `make web-test`, `make lint`, `make typecheck`.

</intent-contract>

## Change log

- 2026-08-31 — spec written against `3211a7f`.
