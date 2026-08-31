---
title: 'Story 7.2: Speaker Tags on the Wire'
type: 'feature'
created: '2026-08-30'
status: 'ready-for-dev'
review_loop_iteration: 0
followup_review_recommended: false
context: []
warnings: ['oversized']
deferred: []
---

<intent-contract>

## Intent

**Problem:** Story 7.1 stamps `SPEAKER_NN` tags onto transcript segments and `align`
resolves source-supplied names to participants, but nothing lists a meeting's speakers:
a user cannot tell who is who — or how much each voice spoke — before naming anyone
(FR36).

**Approach:** Add one read-only route, `GET /meetings/{meetingId}/speakers`, that
aggregates the meeting's existing `transcript_segment` rows into one row per speaker
label — talk time, segment count, three sample offsets taken from that label's longest
segments — with nullable `participantId`/`displayName` carrying whatever attribution
`align` already stored. A diarized meeting and a meeting whose transcript arrived with
real names produce the same response shape; only the nullable fields differ.

## Boundaries & Constraints

**Always:** Read-only — no INSERT, UPDATE or DELETE, and no store client in `api/`.
Registered by auto-discovery (story 2.8): adding the file is the registration.
camelCase wire fields via `alias_generator=to_camel`, the house convention.
Never guess an identity (AD-13/AD-5): `participantId` and `displayName` come from
`transcript_segment.participant_id` — set by `align` only when the source or an alias
resolved the label — and are `null` for every `placeholder`, `unresolved` and
`ambiguous` tag. Same 404/409/422 problem+json contract as the sibling meeting reads.
Row order and sample-offset selection are fully deterministic.

**Block If:** the response would have to name a person the store does not name.

**Never:** no change to the tag-producing side (`pipeline/speakers.py`,
`pipeline/stages/transcribe.py`, `pipeline/stages/align.py`, `adapters/diarize/**`) —
story 7.1 owns it; no migration (every column already exists); no assignment or write
path (story 7.3); no UI (story 7.4); no hand-edit of `api/main.py`, a registry, or
`web/src/client/*.gen.ts`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Diarized meeting | segments tagged `SPEAKER_00`/`SPEAKER_01`, `speaker_resolution` `placeholder`, `participant_id` NULL | 200; one row per tag, `participantId`/`displayName` null, talk time = summed segment durations | No error expected |
| Named source (Teams / 6.3-converted Zoom) | segments labelled `Goeke, Timothy`, resolution `resolved`, `participant_id` set | 200; same field set, `participantId` + curated `displayName` populated | No error expected |
| One shape, two sources | the two meetings above seeded with identical timings | identical `talkTimeMs`, `segmentCount`, `sampleOffsetsMs` and identical field sets; only label/attribution fields differ | No error expected |
| Longest-segment samples | a tag with five segments of differing durations | exactly three offsets, the `startMs` of the three longest, longest first; ties broken by earlier start then ordinal | No error expected |
| Fewer than three segments | a tag with one or two segments | that many offsets, never padded or fabricated | No error expected |
| Ambiguous or unresolved label | `speaker_resolution` `ambiguous`/`unresolved`, `participant_id` NULL | row listed with its verbatim label and resolution, attribution fields null | No error expected |
| Renamed participant | curator renamed the participant row after ingest | `displayName` is `participant.display_name`; `speakerLabel` stays the transcript's verbatim label | No error expected |
| Meeting with no segments | meeting exists, transcript lane empty | 200 with an empty `speakers` list | No error expected |
| Unknown meeting | a UUID no meeting carries | 404 `not-found` | problem+json |
| Evidence not settled | an ingest or augmentation stage still running | 409 `meeting-not-viewable`, same extensions as the sibling reads | problem+json |
| Malformed id | `/meetings/not-a-uuid/speakers` | 422 `invalid-request` | problem+json |

</intent-contract>

## Code Map

- `server/meetingminer/api/speakers.py` — NEW; the whole story. Model it on
  `api/participants.py` (module SQL constants, `BaseModel` + `to_camel`, `logs.log_event`)
  and `api/moments.py:483-534` (header → gate → evidence under REPEATABLE READ).
- `server/meetingminer/api/moments.py:451-480` — `_require_viewable`, the 409 gate with
  its `meetingId`/`augmenting`/`jobStatus` extensions; imported and reused so the two
  meeting reads cannot drift apart. `:196-204` `_TRANSCRIPT_WITH_MOMENTS` is the column
  vocabulary this route aggregates; `:379-397` `DrilldownSegment` already puts
  `speakerLabel`/`speakerResolution`/`participantId` on the wire per segment — the AC's
  "transcript segments carry their tag" half, pinned by a test here rather than re-built.
- `server/meetingminer/api/problems.py` — `Problem(status, slug, detail, **extensions)`.
- `server/meetingminer/migrations/0005_transcripts_participants.sql` — `transcript_segment`
  (`speaker_label` NOT NULL verbatim, `participant_id` NULL unless `resolution='resolved'`,
  `start_ms`/`end_ms`, `UNIQUE (meeting_id, ordinal)`) and `participant.display_name`.
  Index `transcript_segment_meeting_start_idx` serves the meeting-scoped scan. No migration.
- `server/meetingminer/pipeline/speakers.py:RESOLUTIONS` — the four resolution values, the
  vocabulary the response reuses; `_PLACEHOLDER_LABEL` is why a `SPEAKER_NN` tag never
  becomes a participant. Read-only evidence.
- `server/meetingminer/pipeline/stages/align.py:600-705` — where `participant_id` and
  `speaker_resolution` are written (alias-resolved before insert). Read-only.
- `server/tests/projection_seed.py:seed_meeting` — seeds job/meeting/participants/source;
  its turns hard-code `end_ms = start_ms + 2000`, so this story seeds its own segments
  (with `turns=()`) to get differing durations. Read-only.
- `server/tests/conftest.py:434` — `client` fixture (TestClient, pool injected, evidence
  truncated). Read-only.
- `server/tests/test_api_registry.py:29-59` — `BASELINE_ROUTER_ORDER`, a hard-coded list
  a new router module mechanically extends (`speakers` sorts between `participants` and
  `stats` at `DEFAULT_ROUTER_ORDER`). Outside the footprint; see the Spec Change Log.
- `web/src/client/*.gen.ts` — generated, committed; regenerated from this branch's
  in-process `app.openapi()` dump (the story 2.2 pattern), never from a running api.

## Tasks & Acceptance

**Execution:**
- `server/meetingminer/api/speakers.py` — NEW. One `GET /meetings/{meeting_id}/speakers`
  returning `MeetingSpeakersResponse{meetingId, speakers[]}` of
  `SpeakerTag{speakerLabel, speakerResolution, participantId, displayName, talkTimeMs,
  segmentCount, sampleOffsetsMs}`; one GROUP BY statement over `transcript_segment` LEFT
  JOIN `participant`, header → `_require_viewable` → aggregate on one REPEATABLE READ
  connection; `logs.log_event("speakers.listed", …)`.
- `server/tests/test_api_speakers.py` — NEW. One test per matrix row plus a field-set
  literal for the payload shape (the `test_api_moments.py` pinning style), a test that the
  route is discovered by the registry, and one asserting the drilldown segments carry the
  `SPEAKER_NN` tag.
- `server/tests/test_api_registry.py` — add `"speakers"` to `BASELINE_ROUTER_ORDER`
  (mechanically forced by the new module; recorded in the Spec Change Log).
- `web/src/client/` — regenerate from this branch's schema dump; commit the diff.

**Acceptance Criteria:**
- Given a diarized meeting and a name-carrying meeting seeded with identical timings, when
  both are fetched, then the two payloads have identical field sets and identical
  `talkTimeMs`/`segmentCount`/`sampleOffsetsMs`, and only the named one carries
  `participantId`/`displayName`.
- Given the route is added as a file only, when the app starts, then the registry
  discovers and registers it with no edit to `api/main.py`.
- Given any tag, when the response is built, then no `participantId` appears that
  `transcript_segment.participant_id` does not already carry.
- Given `make test-fast`, when it runs, then lint, typecheck and the fast set are green.

## Spec Change Log

- 2026-08-30 (planning): story 7.1's spec frontmatter still reads `status: in-review`
  because the wave contract terminates a builder at review, while the story itself landed
  on `main` (`bb50c7b`, sprint key `7-1-…: done`, `adapters/diarize/pyannote.py` present in
  this branch's tree). Step-01's previous-story continuity check is satisfied by that
  landing rather than by the frontmatter; recorded instead of halting.
- 2026-08-30 (planning, footprint): `server/tests/test_api_registry.py` is outside the
  build prompt's footprint but its `BASELINE_ROUTER_ORDER` is a hard-coded list of every
  discovered router module, asserted with `==`. A new router file cannot be added without
  extending it, so the one-line insertion is made and recorded here rather than widened
  quietly. No other in-flight branch touches that file (`git diff --name-only main...` over
  every `story/*` branch), and `branch_conflicts.py` is re-run before the final push.

## Review Triage Log

## Design Notes

- **Grouping key is `(speaker_label, participant_id, speaker_resolution)`, not the label
  alone.** `align` resolves a label deterministically once per meeting, so in practice this
  is one row per label; keying on all three means a store that somehow disagrees with
  itself produces two honest rows instead of one row whose attribution was picked.
- **Attribution is read, never re-derived.** The route does not re-run `resolve_label`, and
  does not follow `participant_alias` forward at read time: a merge performed after the last
  `align` run reaches the transcript at the next rerun (the documented AD-5 lag,
  `api/participants.py`), and following it here would make `speakers` and `drilldown`
  disagree about the same segment's `participantId`. `displayName` is read live from
  `participant.display_name`, so a rename — which keeps the id — shows immediately.
- **Determinism.** Rows: `talkTimeMs` DESC (the epic's "sort by talk time descending"),
  then `speakerLabel`, then `participantId` NULLS LAST. Offsets: the `startMs` of the three
  longest segments, ordered duration DESC, `startMs`, `ordinal` — so a tie between equal
  durations resolves to the earlier moment rather than to whatever the planner returned.
- **`sampleOffsetsMs` is a list of at most three**, never padded: story 7.4 plays clip *n*
  of what is there, and a fabricated offset would play silence.

## Verification

**Commands:**
- `uv run --project server pytest server/tests/test_api_speakers.py -q` — expected: all pass.
- `uv run --project server pytest server/tests/test_api_registry.py server/tests/test_api_moments.py -q` — expected: unchanged, all pass.
- `make web-test` — expected: green after the client regeneration.
- `make test-fast` — expected: green, lint and typecheck included.
- `make test` — expected: green, once, before `review`.
- `python3 _bmad/scripts/branch_conflicts.py --against story/7-2` — expected: clean.
