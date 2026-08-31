# Code review handoff — Story 7.2: Speaker Tags on the Wire

You are reviewing a landed-but-unmerged story branch. You have none of the
build session's context; everything you need is below.

## Required output — read this before you read any code

**Write your report to
`_bmad-output/implementation-artifacts/review-story-7-2-2026-08-30.md`.**

Each finding carries: **Location** (path:line) / **Severity** (low, medium,
high) / **Finding** / **Evidence** (what you ran or read that shows it) /
**Suggested direction**.

**Report first, and commit before you read code.** Create that file as a
skeleton — scope, review range, an empty findings section — and commit it
*before* opening a single source file. Then append each finding as you confirm
it and commit incrementally. Six reviews in this repository produced their
report only as terminal text because the file requirement sat at the tail of a
long prompt and was out of context by wrap-up time. A crashed or closed session
must lose prose, never the artifact.

**The review lane fixes what it finds.** This is the repository's convention as
corrected by the owner on 2026-08-30 — do not follow the retired "report
findings, do NOT fix them" wording that appears in older prompts in this
directory. After every finding is in the report file, fix the patchable ones
yourself on branch `story/7-2-review`, cut from `story/7-2` and worked in its
own worktree (`make worktree STORY=7-2-review`), **red-first**: the test
observed failing against the unfixed code, then the fix, then green. Commit each
fix with its finding number in the message. Hand nothing back to a builder.

What you must **not** fix: anything needing an owner decision, and anything
whose root cause is the frozen spec (the `<intent-contract>` block). Report
those, mark them clearly open, and leave them for the owner. Never commit to
`main`, never work in the main checkout, never merge — the owner runs
`integrate`.

**Closeout.** Before reporting completion, run `make check-reviews` (it fails
while any dispatched review lacks a committed report, including this one) and
state the SHA carrying the report's final version. A review reported in the
terminal but not filed does not exist.

## Repository, branch, range

- Repo: `/Users/devopsterus/current/cohort/meetingminer` (main checkout — do not
  work in it). Your worktree: `make worktree STORY=7-2-review`.
- Branch under review: `story/7-2`, rebased onto `main` at `7a1076d` (story
  6.3 landed during this build). Range: `main..HEAD`, four commits:
  - `a784db55f1caf33366b170d956f77418ae0113bc` docs(7-2): frozen spec for Speaker Tags on the Wire
  - `5f5436da3b2920bbff4dd77b81519a3db19068f8` feat(7-2): GET /meetings/{id}/speakers puts the speaker tags on the wire
  - `0c66bbcd340076ae0941d78939fbd45d15d37d6f` chore(7-2): regenerate the typed TS client for listMeetingSpeakers
  - `a6b3be4c3350c6ec7590197c414b527de202f867` docs(7-2): close the build — spec at review, tracking, reviewer handoff
    (this commit also carries the review prompt you are reading; its own SHA
    therefore names the tree as of the final push).
- Every commit in the range belongs to this story. None belongs to another.

## Spec

`_bmad-output/implementation-artifacts/spec-7-2-speaker-tags-on-the-wire.md`.

The `<intent-contract>` block — Intent, Boundaries & Constraints, and the I/O &
Edge-Case Matrix — is **frozen**: a finding rooted there is reported and left
open, not patched. Everything after it (Code Map, Tasks & Acceptance, Design
Notes, Verification) is planner work you may attack freely.

## Architecture authority

- `docs/architecture.md` — **AD-13** (never guess an identity; a speaker label
  resolves to a person only when the source or an alias says so) and **AD-5**
  (table ownership: the worker writes evidence, the API writes curation; the
  API never writes `transcript_segment`, and a participant merge reaches an
  already-ingested meeting only at the next `align` run). **AD-11** for
  cross-meeting participant identity.
- Story 2.8's route auto-discovery contract (`server/meetingminer/api/registry.py`
  docstring): registration is adding a file; a literal path under a
  parameterized sibling must register first.
- `AGENTS.md` — the fast-loop/full-gate split, the fast-set per-test budget, and
  the worktree/private-stack rules.

## Scope

**In scope (the whole change):**
- `server/meetingminer/api/speakers.py` — NEW, the entire feature.
- `server/tests/test_api_speakers.py` — NEW, 16 tests.
- `server/tests/test_api_registry.py` — one baseline-list insertion (see below).
- `web/src/client/{index,sdk,types}.gen.ts` — regenerated, additive only.
- The spec, sprint status and sprint notes.

**Out of scope:**
- Story 7.3 (`PUT /meetings/{id}/speakers/{tag}`, alias writes, job re-arm) and
  story 7.4 (the naming UI). This story only exposes what already exists.
- The tag-producing side — `pipeline/speakers.py`,
  `pipeline/stages/transcribe.py`, `pipeline/stages/align.py`,
  `adapters/diarize/**` — is story 7.1's and is deliberately unchanged.
- `web/src/client/*.gen.ts` content as *style*: it is generated output, never
  hand-edited. Its correctness question is only whether it matches the schema.
- Items already recorded in `_bmad-output/implementation-artifacts/deferred-work.md`.

## Design decisions to attack

Each is a choice the planner made, with the assumption under it. The planner is
not a neutral judge of its own calls.

1. **`participantId` is read from `transcript_segment.participant_id` and the
   route does not follow `participant_alias` forward at read time.** Assumption:
   a participant merge performed after the last `align` run should reach this
   route at the next rerun (the documented AD-5 lag), because resolving the
   alias here would make `/speakers` and `/drilldown` report different
   `participantId`s for the same segment. The cost is that a merged-away
   participant can still be named here until the rerun. Is the trade right?
2. **Grouping key `(speaker_label, participant_id, speaker_resolution)`, not the
   label alone.** Assumption: `align` resolves a label deterministically once
   per meeting, so this is one row per label in practice, and a store that
   disagrees with itself should produce two honest rows rather than one row
   whose attribution the query picked. Is the split ever reachable, and would a
   caller handle two rows sharing a label?
3. **`moments._require_viewable` is imported across module boundaries** — a
   private name from a sibling router. Assumption: one definition of the
   viewability gate beats two that can drift, and the alternative (copying the
   409 body and its `augmenting`/`jobStatus` extensions) is worse. The
   alternative not taken was extracting the gate to a shared module, which would
   have required editing `moments.py` — outside this story's footprint.
4. **The `array_agg(...)[1:N]` slice bound is interpolated into the SQL string**
   rather than bound as a parameter, because an array subscript is not a value
   position Postgres infers a parameter type for. The interpolated text is a
   module-level `int`. `meeting_id` remains a bound parameter. Judge whether the
   comment justifying this is adequate for the next reader.
5. **Row ordering adds a fourth key** (`speaker_resolution`) beyond the three the
   Design Notes name, so the order is total rather than usually-total. Sample
   offsets order by duration DESC, then `start_ms`, then `ordinal` — the last
   key is deliberately unobservable in the payload (two segments tying on
   duration and start emit the same `startMs`).
6. **`talkTimeMs` is summed wall-clock `end_ms - start_ms`.** Overlapping
   segments from two labels would double-count against a meeting's real
   duration. No caller divides by meeting length today; story 7.4's "talk share"
   will sum the rows. Is that safe to leave?
7. **No `totalTalkTimeMs` on the envelope and no `mergedIntoParticipantId` on
   the row.** Both were considered and left out to keep one minimal shape; the
   client sums. Recorded in the spec rather than filed.

## History you need to tell a regression from a pre-existing condition

- **Story 7.1 landed on `main` before this branch was cut** (`bb50c7b`), but
  `spec-7-1-diarizer-engine-behind-the-port.md` still reads `status: in-review`
  because a builder in this wave terminates at review and never marks a story
  done. The sprint key `7-1-diarizer-engine-behind-the-port: done` is the
  accurate one. Not a regression.
- **`server/tests/test_api_registry.py` is outside this story's stated
  footprint.** Its `BASELINE_ROUTER_ORDER` is a hard-coded list of every
  discovered router module asserted with `==`, so a new router file cannot be
  added without extending it. This was demonstrated, not assumed: reverting the
  inserted line makes
  `test_existing_routers_keep_the_baseline_registration_order` fail. The
  departure is recorded in the spec's Change Log. No other in-flight branch
  (`story/6-2a`, `story/6-3`, `story/8-1`, `story/10-2`) touches that file,
  `web/src/client`, or `api/main.py`.
- **The generated client was regenerated from an in-process `app.openapi()` dump
  with an injected `servers: [{url: 'http://localhost:8000'}]` entry** (the story
  2.2 pattern), never from a running api — this wave must not start one, and the
  api port is shared across checkouts. The injection is what keeps
  `client.gen.ts` byte-identical; it came back unchanged. Regenerating a second
  time reproduced `types.gen.ts` and `sdk.gen.ts` byte-for-byte.
- **`test_youtube.py::test_makefile_passes_a_hostile_url_as_one_data_argument[shell]`
  tripped the 2.0s fast-set budget once at 2.92s** during a run concurrent with
  another worktree's suite, and passed at 0.24s when re-run alone. It is a story
  6.2 test, untouched here. Contention, not a finding against this branch — but
  if you see it again, that is what it is.

## Verification baseline

Run these; a skip or failure that is not listed here is a finding, not noise.

- `uv run --project server pytest server/tests/test_api_speakers.py -q`
  — 16 passed, ~1.3s.
- `uv run --project server pytest server/tests/test_api_registry.py server/tests/test_api_moments.py -q`
  — 46 passed, unchanged by this branch.
- `make test-fast` — green: 1848 passed, 2 skipped, 378 deselected, ~56s. Both
  skips are pre-existing environment skips and are named in the output: no
  `pyannote` module in the default venv, and the network-gated yt-dlp test.
  Lint and typecheck run inside this target and both pass.
- `make test` — the full gate, result recorded in the spec's Auto Run Result.
- `python3 _bmad/scripts/branch_conflicts.py --against story/7-2` — result
  recorded in the spec's Auto Run Result.

**Coverage was demonstrated, not asserted.** Every behavioral claim was proved
by mutating the implementation and watching the right tests go red, each
mutation reverted afterwards: removing the route module (whole file errors on
collection); dropping the `[1:3]` slice; reversing the sample ordering to
shortest-first; reversing row order to quietest-first; falling `displayName`
back to the raw label (a guessed identity); removing the viewability gate;
removing the 404 existence check. If you add a test, hold it to the same
standard — observe it red against the unfixed code first.
