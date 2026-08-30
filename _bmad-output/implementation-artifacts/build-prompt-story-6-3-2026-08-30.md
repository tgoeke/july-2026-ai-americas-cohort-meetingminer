# Owner/spec handoff — Story 6.3 review decisions

Story 6.3 **does not pass review** and must not merge yet. The review lane fixed
all ten unambiguous code findings itself; two findings are rooted in the frozen
intent and need owner decisions before any further code change.

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

## Specification decisions required

Do not ask a builder to guess either decision. Amend the frozen intent, then
re-derive the implementation task.

### F1 — Choose transcript-only Zoom identity

- **Anchor:** `server/meetingminer/transcripts/dialects.py:220-225` and
  `server/meetingminer/mintdrop.py:652-679` in the reviewed source.
- **Failure:** Two Zoom exports with identical timing/words but different
  speaker labels generate the same speaker-less VTT. Because that VTT is the
  primary converted file, they receive the same `sourceId`; the corrected
  attribution returns `exists` and is silently ignored.
- **Why the spec owns it:** The frozen contract explicitly says identity remains
  the digest of the converted bytes and deliberately declines the available
  `source_id` override.
- **Decision options:**
  1. Use the original operator-file digest as transcript-only source identity.
     This treats the declared export as the stable occurrence source and makes
     speaker-label changes distinct, but an improved converter applied to the
     same original still resolves to the existing drop.
  2. Use a deterministic composite digest covering both generated transcript
     artifacts. This includes attribution in identity, but converter changes can
     mint a new occurrence for the same original export.
- **Required outcome:** Corrected speaker attribution cannot resolve to an
  existing drop that carries different attributed text without a named,
  actionable outcome.

### F6 — Choose behavior for speaker changes inside one second

- **Anchor:** `server/meetingminer/transcripts/dialects.py:434-449` and
  `server/meetingminer/pipeline/alignment.py:153-170` in the reviewed source.
- **Failure:** Starts at 1.100s and 1.900s both render as `00:01`; the first
  turn's matching window ends before its real cue, producing no VTT end and a
  zero-duration fallback boundary.
- **Why the spec owns it:** The frozen contract explicitly requires truncating
  legacy block stamps to whole seconds while also requiring the unchanged
  legacy pipeline format, which has no fractional field.
- **Decision options:**
  1. Fail closed at acquisition when distinct consecutive turns collapse to the
     same legacy stamp. This preserves the unchanged pipeline and never invents
     time, at the cost of refusing those exports.
  2. Amend the pipeline transcript contract to preserve fractional legacy
     starts. This is a wider architecture/story change and violates the current
     unchanged-pipeline acceptance criterion until that criterion is amended.
  3. Define a monotonic whole-second adjustment rule. This stays local but can
     point a turn later than it actually began, so it needs an explicit
     never-guess exception and downstream citation analysis.
- **Required outcome:** Two real speaker turns must not collapse into a
  zero-duration first turn without a named refusal or a representation that
  preserves their order.

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

Every regression was observed failing against the unfixed code before its fix.
The final dialect suite has 46 tests.

## Verification after the owner decisions

After amending the spec and implementing the chosen rules, rerun:

```bash
uv run --project server pytest server/tests/test_transcript_dialects.py -q
make test-fast
make test
python3 _bmad/scripts/branch_conflicts.py --against story/6-3-review
make check-reviews
```

The current review branch already passed all of those test gates except that
`make check-reviews` is reserved for the final committed report closeout. The
full server gate passed 1773 tests and the web production build passed.

## Explicitly out of scope

Do not widen into Stories 6.4/6.4a/6.5/6.5a, Teams content inference,
`pipeline/speakers.py`, unrelated alignment policy, Story 6.2's override
mechanism, shared test fixtures, configuration, root documentation, or the
known deferred `Dr.`-style-name and unbounded same-speaker-gap items. Do not
merge to `main` until a fresh follow-up review sees both decisions resolved and
all gates green.
