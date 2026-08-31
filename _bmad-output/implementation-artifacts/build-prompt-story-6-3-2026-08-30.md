# Owner/spec handoff — Story 6.3 review decisions

Story 6.3 **passes review and is ready to land**. The review lane fixed every
patchable finding. The owner deferred F1 and F6 on 2026-08-30 with their exact
reproductions and revisit triggers preserved. No finding remains open for
remediation; integration remains owner-operated.

- Repository: `/Users/devopsterus/current/cohort/meetingminer`
- Source branch: `story/6-3`
- Exact reviewed range: `d72c658..4877cf2`
- Source movement: none observed; `story/6-3` still resolved to `4877cf2` at
  closeout.
- Review/remediation branch: `story/6-3-review`
- Review report:
  `_bmad-output/implementation-artifacts/review-story-6-3-2026-08-30.md`
- Frozen spec:
  `_bmad-output/implementation-artifacts/spec-6-3-local-files-acquisition-with-transcript-dialect-conversion.md`

Read the report first. Its Location / Severity / Finding / Evidence / Suggested
direction entries are authoritative.

## F1 owner ruling — deferred 2026-08-30

- **Anchor:** `server/meetingminer/transcripts/dialects.py:220-225` and
  `server/meetingminer/mintdrop.py:652-679` in the reviewed source.
- **Failure:** Two Zoom exports with identical timing/words but different
  speaker labels generate the same speaker-less VTT. Because that VTT is the
  primary converted file, they receive the same `sourceId`; the corrected
  attribution returns `exists` and is silently ignored.
- **Ruling:** Defer. Do not amend the identity contract and do not change code
  unless the observed trigger occurs.
- **Revisit trigger:** An operator re-mints a corrected Zoom export and the
  system reports `exists` while keeping the old attribution.
- **Candidate fixes preserved for that future decision:**
  1. Use the original operator-file digest as transcript-only source identity.
     This treats the declared export as the stable occurrence source and makes
     speaker-label changes distinct, but an improved converter applied to the
     same original still resolves to the existing drop.
  2. Use a deterministic composite digest covering both generated transcript
     artifacts. This includes attribution in identity, but converter changes can
     mint a new occurrence for the same original export.
- **Action now:** None. The reproduction is retained in `deferred-work.md`.

## F6 owner ruling — deferred 2026-08-30

- **Anchor:** `server/meetingminer/transcripts/dialects.py:434-449` and
  `server/meetingminer/pipeline/alignment.py:153-170` in the reviewed source.
- **Failure:** Starts at 1.100s and 1.900s both render as `00:01`; the first
  turn's matching window ends before its real cue, producing no VTT end and a
  zero-duration fallback boundary.
- **Ruling:** Defer. Do not amend the truncation contract and do not change the
  converter while the frequency in genuine Zoom exports remains unmeasured.
- **Evidence retained:** Exact input: cues at 1.100s and 1.900s. Observed:
  `merge_vtt_end_timings() -> (None, 2200)`, producing a zero-duration first
  boundary. `_bmad-output/implementation-artifacts/deferred-work.md` carries
  the full reproduction.
- **Revisit trigger:** Real Zoom exports in the new corpus showing sub-second
  speaker changes.
- **Observability added:** `stage.align.zero-duration-fallback` names the
  meeting, affected turn, and both colliding stamps without changing timing,
  retry, conversion, or acceptance behavior.

## Already fixed on the review branch

No builder action is requested for these findings:

- `77c805c` — F2, F4, F8, F9, F10: malformed delimiters, reverse timings,
  missing separators, out-of-order cues, invalid headers/stamps.
- `895af76` — F3, F11: first-payload-line speaker semantics and no-space colon
  prefixes.
- `a435a82` — F5: unknown cues stay distinct and placeholders stay out of
  `speakerLabels`.
- `df5b7d9` — F7, F12: provenance hashes the converted byte snapshot and
  workspace write failures are named.
- `da69b58` — F6: records the deferral and emits the owner-authorized named
  zero-duration warning without changing timing behavior.
- `be7ba80` — F13: extends that warning to descending-start fallbacks, also
  warning-only and red-first.

Every regression was observed failing against the unfixed code before its fix.
The final dialect suite has 46 tests.

## Closeout verification

Before landing, run:

```bash
uv run --project server pytest server/tests/test_transcript_dialects.py -q
make test-fast
make test
python3 _bmad/scripts/branch_conflicts.py --against story/6-3-review
make check-reviews
```

The current review branch passed the post-F6 gates: the combined transcript
surface passed 78 tests, `make test-fast` passed 1449 server tests with 326 slow
tests deselected, and the full server gate passed 1775 tests plus the web
production build. F1 changes documentation only, so no code or test rerun is
required; `make check-reviews` closes the committed report. The owner's
`integrate` run owns rebase/conflict resolution and its post-resolution gates.

## Explicitly out of scope

Do not widen into Stories 6.4/6.4a/6.5/6.5a, Teams content inference,
`pipeline/speakers.py`, unrelated alignment policy, Story 6.2's override
mechanism, shared test fixtures, configuration, root documentation, or the
known deferred `Dr.`-style-name and unbounded same-speaker-gap items. The story
is ready to land, but this review branch must not merge to `main`; the owner is
running `integrate`.
