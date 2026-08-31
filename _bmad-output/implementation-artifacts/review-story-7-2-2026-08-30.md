# Code Review — Story 7.2: Speaker Tags on the Wire

Date: 2026-08-30  
Reviewer branch: `story/7-2-review`  
Review base: `origin/main` at `d1abe8a1c3ab1a7b7be7f63cde7d870737245147`  
Rebased story tip: `66ee0261e427726ac2b420f1587a5c074d200c50`  
Review range: `origin/main..66ee0261e427726ac2b420f1587a5c074d200c50`

## Scope

Adversarial review of the complete landed-but-unmerged Story 7.2 range, with
primary attention to the new speakers API route, its tests, route registration,
the regenerated TypeScript client, and the frozen intent contract. The review
also verifies the coordinator's five named claims and attacks the seven design
decisions in the handoff.

## Findings

### F-1 — Nullable attribution fields are optional in the published schema

- **Location:** `server/meetingminer/api/speakers.py:129`
- **Severity:** medium
- **Finding:** `participant_id` and `display_name` have `None` defaults, so
  Pydantic omits them from `SpeakerTag.required`. The runtime route currently
  supplies both keys, but the generated TypeScript contract exposes
  `participantId?` and `displayName?`. That breaks the story's one-shape
  contract at the consumer boundary: a conforming server or mock may omit the
  fields entirely instead of carrying explicit nullable attribution.
- **Evidence:** `SpeakerTag.model_json_schema()` lists only `speakerLabel`,
  `speakerResolution`, `talkTimeMs`, `segmentCount`, and `sampleOffsetsMs` in
  `required`; `web/src/client/types.gen.ts` consequently declares
  `participantId?: string | null` and `displayName?: string | null`. The
  runtime field-set tests do not inspect the OpenAPI required set.
- **Suggested direction:** Declare both fields as required nullable Pydantic
  fields (no default), add an OpenAPI contract assertion that they are required
  and nullable, then regenerate the TypeScript client so both properties lose
  the optional marker while retaining `| null`.
- **Disposition:** Fixed in the review lane. The new schema assertion was
  observed failing against the unfixed model, then passed after the fields were
  made required nullable; all 17 speaker-route tests and the web production
  build passed after client regeneration.

## Verdict

**Pass after remediation.** One medium finding was confirmed and fixed
red-first on `story/7-2-review`. No owner decision, deferred item, or open
finding remains. The frozen intent contract was not changed.

The Blind Hunter, Edge Case Hunter, Verification Gap, and Acceptance Auditor
layers were run locally and sequentially, as required by the coordinator. Their
duplicate schema-contract concern was normalized into F-1; the remaining
candidates were rejected after tracing the database constraints, the complete
`align` replacement transaction, sibling route behavior, and the tests.

## Coordinator-claim audit

- **Forced registry footprint:** confirmed by removing the `speakers` baseline
  entry and running
  `test_existing_routers_keep_the_baseline_registration_order`; it failed at
  index 11 because discovery still returned `speakers`. The mutation was
  restored. The branch-conflict matrix shows no in-flight lane sharing
  `test_api_registry.py`.
- **Generated client:** regenerated from an in-process `app.openapi()` dump
  with the localhost server entry and no api process. `client.gen.ts`,
  `index.ts`, and `sdk.gen.ts` reproduced byte-for-byte. Only `types.gen.ts`
  changed after F-1, exactly where the two optional markers became required
  nullable properties.
- **One shape by construction:** confirmed. Both fixtures consume `_TIMINGS`,
  and `test_the_two_sources_produce_one_shape` compares the two live payloads'
  field sets, talk times, counts, and sample offsets row by row.
- **Sampling boundaries:** one segment and two segments are covered by
  `test_fewer_than_three_segments_are_never_padded`; exactly three by the
  shared-timing fixtures; ties and a single-speaker meeting by
  `test_the_samples_are_the_three_longest_segments_longest_first`. All passed
  in the 17-test route suite.
- **Never guess identity:** confirmed by temporarily changing `display_name` to
  fall back to `speaker_label`. The diarized, one-shape, and
  ambiguous/unresolved tests all failed on non-null guessed names. The mutation
  was restored before the gates.

## Design-decision audit

- Reading `transcript_segment.participant_id` without following aliases is the
  correct AD-5 lag: `align` replaces the meeting's segment rows wholesale after
  resolving aliases, and `/drilldown` reads the same stored id. Read-time alias
  following would create a temporary disagreement between the two endpoints.
- The three-column grouping extension can yield duplicate labels only for a
  store that disagrees with itself. Normal writes cannot produce it: one
  `align` run computes resolution from one roster and replaces all meeting rows
  in one transaction. Returning two honest rows is safer than selecting an
  identity from corrupt evidence; this remains a residual presentation risk,
  not a reachable application defect.
- Importing `moments._require_viewable` creates private-name coupling but keeps
  the 409 calculation and extensions identical. There is no cycle and the
  sibling-route suite passed; extracting it would be a footprint-expanding
  refactor with no behavior gain for this story.
- The interpolated sample limit is safe because the only interpolated value is
  the module's integer constant. A live PostgreSQL `PREPARE` probe also showed
  that an untyped array-slice parameter is inferred successfully, so binding
  was possible; the comment is conservative rather than evidence of an
  injection surface.
- The fourth row-order key closes the only tie left by the grouping key. The
  offset ordinal tie-break is intentionally unobservable when duration and
  start are equal, because either segment emits the same offset.
- Summing segment wall-clock durations can count simultaneous voices twice
  against meeting duration, but the contract defines talk time as that sum and
  Story 7.4's share denominator is the sum of speaker rows. It is safe unless a
  future consumer instead treats the value as exclusive meeting occupancy.
- `totalTalkTimeMs` and `mergedIntoParticipantId` are not required for this
  read: the client can sum rows, and exposing merge-forward state here would
  undermine the deliberate segment-id lag above.

## Verification

- `uv sync --project server` — completed before lint.
- `uv run --project server pytest server/tests/test_api_speakers.py -q` — 17
  passed.
- `uv run --project server pytest server/tests/test_api_registry.py
  server/tests/test_api_moments.py -q` — 46 passed.
- `make web-test` — 16 files / 294 tests passed.
- `make test-fast` — lint and typecheck clean; 1,944 passed, 2 named environment
  skips, 378 deselected.
- `make test` — exit 0; 2,322 server tests passed, 2 named environment skips in
  649.61s; puller 128 passed, eval harness 643 passed, diarization-extra 92
  passed, web tests and production build passed.
- `python3 _bmad/scripts/branch_conflicts.py --against story/7-2-review` —
  `main × story/7-2-review` clean. Other reported overlaps are the expected
  source-branch overlap and sprint-notes/docs conflicts already assigned to
  integration.
- `make check-reviews` — pending final report commit.

## Remediation commits

- `e9cfe71` — F-1: make nullable attribution fields required in OpenAPI and the
  generated TypeScript contract.

## Residual risks

- A manually corrupted store can produce two rows sharing one label because the
  database does not enforce meeting-label attribution consistency; the normal
  writer path does enforce it by construction.
- Overlapping diarizer turns make summed speaking activity exceed elapsed
  meeting time. Current and planned consumers sum speaker rows rather than
  dividing by meeting duration.
- Story 7.4 is the first UI consumer; this review verifies the wire contract and
  generated client, not an as-yet-unbuilt presentation.
