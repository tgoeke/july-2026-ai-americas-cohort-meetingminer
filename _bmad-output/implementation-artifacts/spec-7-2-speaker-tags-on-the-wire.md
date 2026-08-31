---
title: 'Story 7.2: Speaker Tags on the Wire'
type: 'feature'
created: '2026-08-30'
baseline_revision: '8073a756589abeecf2981e0a5897ad7a2f0041f1'
status: 'done'
review_loop_iteration: 1
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

### Review Findings

- [x] [Review][Patch] F-1: nullable attribution fields were optional in the
  published schema [`server/meetingminer/api/speakers.py:129`]

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

- 2026-08-30 (build, row order): the Design Notes name three ordering keys
  (`talkTimeMs` DESC, `speakerLabel`, `participantId` NULLS LAST). Those three do
  not totally order the result, because the grouping key has a fourth component:
  two rows sharing a label with `participantId` NULL on both and differing only in
  `speaker_resolution` would tie on all three and come back in planner order.
  `ts.speaker_resolution` is appended as a final key, so the "fully deterministic"
  constraint in Boundaries holds for every input the grouping key admits. The
  three declared keys are unchanged and still decide every ordinary case.
- 2026-08-30 (build, SQL): `MAX_SAMPLE_OFFSETS` is interpolated into the
  `array_agg` slice bound at import time rather than bound as a parameter — an
  array subscript is not a value position Postgres infers a parameter type for
  the way a comparison is. The interpolated text is a module-level `int`;
  `meeting_id` remains a bound parameter.
- 2026-08-30 (build, client): regenerated from an in-process `app.openapi()` dump
  with a `servers: [{url: 'http://localhost:8000'}]` entry injected (the 2.2
  pattern), then `pnpm --dir web run client -i <dump>`. `client.gen.ts` came back
  byte-identical; the diff is additive only — `listMeetingSpeakers`,
  `MeetingSpeakersResponse`, `SpeakerTag` and the `ListMeetingSpeakers*` types.

- 2026-08-30 (rebase onto `main` at `7a1076d`): story 6.3 landed mid-build, so the
  "Zoom transcript converted by story 6.3" half of the second acceptance clause is
  no longer forward-looking. 6.3 converts a Zoom `.vtt` at acquisition into a
  legacy-lineage `transcript.txt` and leaves `pipeline/transcripts.py` and
  `pipeline/stages/align.py` unchanged, so a Zoom name resolves through the
  roster by the same path a Teams label takes and reaches
  `transcript_segment.speaker_label`/`participant_id` identically. This route
  reads those columns and never the source lineage, so the named-source tests
  cover both origins by construction; no lineage-specific test was added, and no
  drop fixture is needed to prove it. The rebase also unioned `sprint-notes.md`
  (both entries appended at EOF, both kept whole) and re-ran the full gate.

## Review Triage Log

### 2026-08-30 — Independent review

The coordinator required all layers to run locally and sequentially, so no
subagents were launched. Blind, edge-case, verification-gap, and acceptance
passes converged on one patch finding: the runtime always emitted the two
nullable attribution keys, but the OpenAPI schema and generated TypeScript
client allowed consumers to omit them. The regression test was observed red
against the original model, the model and generated client were fixed, and the
full gate passed. Triage: decision 0; patch 1 (medium, resolved); defer 0; open
0. Full evidence is in `review-story-7-2-2026-08-30.md`.

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

## Auto Run Result

**Status:** review (per the wave contract this story terminates at review; it is
not merged and not marked done by the builder).

**Summary.** `GET /meetings/{meetingId}/speakers` aggregates a meeting's
existing `transcript_segment` rows into one row per voice — talk time, segment
count, and the `startMs` of the tag's three longest segments, never padded —
with `participantId`/`displayName` carrying only what `align` already stored.
No migration, no change to story 7.1's tag-producing side, no write path.
Registration is the file (story 2.8): `api/main.py` is untouched.

**Files changed.**
- `server/meetingminer/api/speakers.py` — NEW, the whole feature.
- `server/tests/test_api_speakers.py` — NEW, 16 tests, one per matrix row.
- `server/tests/test_api_registry.py` — `"speakers"` added to
  `BASELINE_ROUTER_ORDER` (footprint departure, recorded in the Change Log).
- `web/src/client/{index,sdk,types}.gen.ts` — regenerated, additive only.
- Sprint status (`7-2-speaker-tags-on-the-wire: review`) and sprint notes.

**Verification (all run in this worktree against its private stack
`meetingminer-7-2`, on the rebased tree, base `origin/main` at `7a1076d`).**
- `uv run --project server pytest server/tests/test_api_speakers.py -q` — 16
  passed, 1.28s.
- `uv run --project server pytest server/tests/test_api_speakers.py
  server/tests/test_api_registry.py server/tests/test_api_moments.py -q` — 62
  passed.
- `make test-fast` — 1896 passed, 2 skipped, 378 deselected, 57.75s; lint,
  typecheck, puller, web and eval suites all inside the target.
- `uv run --project server pytest -m "slow" server/tests -q -rs` — 378 passed,
  1898 deselected, 844.88s (the twin-bound half, run separately because the
  whole gate exceeds one foreground call).
- `make test` — **exit 0**: 2274 passed, 2 skipped in 930.78s, puller suite
  `# fail 0`, diarize-extra lane 92 passed, web build succeeded. 1896 + 378 =
  2274, so the fast and slow halves account for the gate exactly.
- The two skips are pre-existing environment skips named in the output: no
  `pyannote` module in the default venv, and the network-gated yt-dlp test.
- `python3 _bmad/scripts/branch_conflicts.py --against story/7-2` —
  **`main × story/7-2` clean**, and clean against `story/10-2-review`,
  `story/6-2a-review`, `story/8-1-review`. Every remaining pair involving this
  branch conflicts only on `sprint-notes.md`, the file the wave rules say has no
  merge driver and that integrate unions — `main × story/10-2`,
  `main × story/6-2a` and `main × story/8-1` each conflict on it independently.
  The `docs/architecture.md` half of the `story/8-1` pair is that branch's own
  conflict with `main`: this branch never touches the file
  (`git diff --name-only main...HEAD`).

**Two observations that are not defects in this branch.**
- `test_youtube.py::test_makefile_passes_a_hostile_url_as_one_data_argument[shell]`
  tripped the 2.0s fast-set budget once at 2.92s during a run concurrent with a
  sibling worktree's suite, and passed at 0.24s re-run alone. Contention, which
  the budget plugin's own message says is not a reason to mark a test slow. It
  is a story 6.2 test, untouched here.
- One gate run failed at `puller-test` with `listen EPERM: operation not
  permitted 127.0.0.1`. That was a harness error, not a code failure: the puller
  tests bind a local HTTP socket and that run was launched inside the tool
  sandbox. Re-run unsandboxed, the puller suite reports `# fail 0`.

**Coverage was demonstrated, not asserted.** Each behavioral claim was proved by
mutating the implementation, observing the named tests fail, and reverting:
removing the route module (collection error, whole file); dropping the `[1:3]`
slice (three-longest test red); reversing the sample ordering to shortest-first
(3 red); reversing row order to quietest-first (2 red); falling `displayName`
back to the raw label, i.e. a guessed identity (3 red, including the
one-shape-two-sources criterion); removing the viewability gate (both 409 tests
red); removing the existence check (404 test red). The registry departure was
proved the same way: reverting the `BASELINE_ROUTER_ORDER` line fails
`test_existing_routers_keep_the_baseline_registration_order`.

**Residual risks.**
- `talkTimeMs` is summed wall-clock segment duration, so overlapping segments
  from two labels would double-count against a meeting's real length. No caller
  divides by meeting length today; story 7.4's talk share sums the rows.
- A participant merged away after the last `align` run is still named here until
  the rerun — the deliberate AD-5 lag, chosen so `/speakers` and `/drilldown`
  cannot disagree about one segment's `participantId`.
- `moments._require_viewable` is imported across a module boundary rather than
  extracted to a shared home, because extracting it would edit `moments.py`,
  outside this story's footprint.
- Not filed as backlog ids: no id was taken this run (highest used remains
  B-37).
