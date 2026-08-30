# Adversarial review prompt — story/6-3 (Local-Files Acquisition with Transcript Dialect Conversion)

Generated 2026-08-30 for external review (Codex `bmad-code-review` or another
LLM), because the bmad-build step-04 review layers were not run as subagents
in-session — the repo's established external-review path.

## REQUIRED OUTPUT — read this before any code

- Write the report to
  `_bmad-output/implementation-artifacts/review-story-6-3-2026-08-30.md`.
- Finding structure: **Location / Severity (high|medium|low) / Finding /
  Evidence / Suggested direction**. Report findings — do NOT fix them.
- **REPORT-FIRST:** create and COMMIT the report file as a skeleton (scope,
  review range, empty findings section) BEFORE reading any code, then append
  each finding as it is confirmed and commit incrementally. A crashed or
  closed session must lose prose, never the artifact. Several reviews in this
  repo produced their report only as terminal text; do not join them.
- **Closeout:** before reporting completion, run `make check-reviews` (it
  fails while any dispatched review lacks a committed report — including this
  one) and state the SHA carrying the report's final version. A review
  reported in the terminal but not filed does not exist.

## The change under review

- Repo: `/Users/devopsterus/current/cohort/meetingminer` — review in your OWN
  worktree (`make worktree STORY=6-3-review`), never the main checkout.
- Branch: `story/6-3`. Review range: `d72c658..HEAD` on that branch.
- Commits in range:
  - `f145c1e` docs+chore: story 6.3 spec, and the story 6.2 mint() override hunk verbatim
  - `bb5d031` feat: transcript dialect conversion at acquisition (story 6.3, FR35)
  - `05315d6` docs: transcript dialects section for mint-drop (story 6.3)
  - one artifacts commit after this file (spec result/status, sprint tracking; docs only)
- Spec (context):
  `_bmad-output/implementation-artifacts/spec-6-3-local-files-acquisition-with-transcript-dialect-conversion.md`.
  The `<intent-contract>` block is FROZEN intent derived from the three
  Given/When/Then clauses of "Story 6.3: Local-Files Acquisition with
  Transcript Dialect Conversion" in `_bmad-output/planning-artifacts/epics.md`
  (FR35) — judge the code against it. Everything outside that block (the
  pinned coupling, Code Map, Result) is planner/builder work you may critique.

## Architecture authorities

- `docs/architecture.md` — AD-1 (every source enters as a write-once source
  drop), AD-13 (drop contents are read-only after intake; **evidence is never
  model-written**, and speaker labels belong with the speaker-attributed
  export, never with a VTT), AD-5 (identity and the never-guess constraint on
  attribution), AD-14 (one intake door).
- `docs/source-drop.schema.json` — `provenance` is an open object; the new
  `transcriptDialect` key rides in it.
- Repository invariant: fail closed, fail named, fail before writing; no
  silent fallbacks.

## Scope

In scope: `server/meetingminer/transcripts/` (new package: `__init__.py`,
`dialects.py`), `server/meetingminer/mintdrop.py` (ONLY the new import,
`--transcript-dialect` in `_parser()`, and the workspace/convert wiring in
`main()` — plus the 6.2 hunk, see below), `docs/README.md` (the "Transcript
dialects" subsection and one argument-table row),
`server/tests/test_transcript_dialects.py` (new, 35 tests).

Out of scope: stories 6.4 / 6.4a / 6.5 / 6.5a; `server/meetingminer/youtube.py`
and everything else story 6.2 owns; `pipeline/transcripts.py`,
`pipeline/stages/align.py`, `pipeline/speakers.py` (all deliberately
unchanged — an edit to any of them would itself be a finding);
`server/tests/conftest.py`, `test_mint_drop.py`, `infra/Makefile`,
`config.py`, `config.yaml`, root `README.md`, `AGENTS.md`, `docs/backlog.md`.

**The 6.2 hunk in `mintdrop.py` is context, not this story's work.** The
`build_metadata()`/`mint()` keyword overrides were taken **verbatim** from
`story/6-2` commit `7625b79` so the two branches carry one identical change
rather than two parallel ones (the `seed_meeting()` precedent in
`.claude/skills/integrate/conflict-playbook.md`). Review this story's *use* of
`provenance_extra`; review the mechanism itself under 6-2.

## Design decisions to attack (the builder is not a neutral judge of its own calls)

1. **The converter self-verifies with `pipeline.transcripts.
   parse_text_transcript` and refuses on any mismatch** — rests on the
   assumption that borrowing the pipeline's parser as a gate is better than a
   render-side escape rule, and that refusing a mint over an utterance
   containing ` | ` is proportionate. Attack the coupling this creates: a
   future change to the pipeline parser now changes which files `mint-drop`
   accepts.
2. **A cue prefix is a speaker only if 1–6 tokens, has a letter, and has none
   of `.?!`; otherwise the turn is `Unknown`** — rests on the assumption that
   losing `Dr. Alice Chen` to a placeholder is cheaper than reading
   `Right. So:` as a person. Attack the constant choices (why 6 tokens? why
   60 characters in `_PREFIXED`?) and whether the `Unknown` fallback can
   *silently* produce a mostly-placeholder transcript that still mints — note
   the only guard is "at least one cue somewhere carried a speaker".
3. **Consecutive same-speaker cues merge into one turn, with no gap bound** —
   attack whether a long silence inside one speaker's cues should break a
   turn, and what that does to `moments` boundaries downstream.
4. **The block stamp truncates to the second and switches to `HH:MM:SS` past
   the hour** — attack the truncation choice and the `\d{1,2}` hour ceiling in
   the pipeline's `_LEGACY_HEADER` (a >99h file is caught only by the
   self-verification, not by a named up-front rule).
5. **Identity is still the converted bytes' digest; `mint()`'s `source_id`
   override is deliberately NOT used** — rests on the assumption that a
   golden-bytes test is enough to keep a converter change from minting a
   duplicate meeting for a Zoom export already in the corpus. Attack that: is
   pinning bytes in a test the right guarantee, or should identity come from
   the operator's original file?
6. **`provenance.files[]` records the transient workspace path, and
   `transcriptDialect.source` is the only record of the operator's file** —
   attack whether a workspace path in a write-once manifest is acceptable.
7. **`teams-vtt` changes no bytes and only records a declaration** — attack
   whether a dialect that does nothing earns its place in the choice list, or
   whether it should validate that the files really are a Teams export
   (note: that would be inference, which the AC forbids).
8. **The emitted `.vtt` strips the `Name: ` prefix** — rests on the assumption
   that a drop's VTT must be speaker-less (AD-13) and that cue text should be
   comparable to turn text for `merge_vtt_end_timings`'s jaccard. Attack
   whether that discards evidence the drop should keep.
9. **`classify_supplied` and `EXTENSION_TO_CANONICAL` were in the allowed
   footprint and were NOT edited** — the "two files map to one canonical name"
   case is refused earlier, in `dialects._zoom_source`. Attack whether that
   leaves a path where two files still collide inside `classify_supplied` with
   a worse message.
10. **`DialectError` is its own exception, caught beside `MintError` in
    `main()`** — rests on the assumption that `dialects` must not import
    `mintdrop` (it would cycle) and that the operator cannot act on the
    difference. Attack the error taxonomy.

## History a reviewer needs

- Baseline `d72c658` is the wave dispatch commit; the branch was cut from it
  and never rebased. Eight other lanes build beside this one; the wave
  footprint (`build-prompt-story-6-3-2026-08-30.md` table) is a contract — an
  edit outside it is a finding even if technically sound.
- The acceptance criteria explicitly require `pipeline/transcripts.py` to be
  **unchanged**, and `align` to resolve Zoom names through the roster exactly
  as Teams labels do. `git diff d72c658..HEAD -- server/meetingminer/pipeline/`
  must be empty; check it first.
- `story/6-2` is in review and shares `mintdrop.py`. `branch_conflicts.py`
  reports `story/6-3 × story/6-2` **clean**. `story/6-2-review` hardened
  `provenance_extra` afterwards (`_validate_provenance_extra`, refusing the
  mint-owned keys `title`, `mintedAt`, `suppliedBy`, `startedAtSource`,
  `files`), which shows as **one mechanical conflict** in that region. The
  recorded resolution is to take 6-2-review's side of that block whole —
  `transcriptDialect` is not a mint-owned key — and that resolution was
  executed and tested (103 tests green across `test_transcript_dialects.py`
  and `test_mint_drop.py`). Verify that claim rather than trusting it.
- Two deferred items are recorded in the spec's frontmatter (`Dr.`-style names;
  unbounded same-speaker merging). Re-raising them is fine; treat them as
  known, not as discoveries.

## Verification baseline (a deviation during review is a finding, not noise)

- `uv run --project server pytest server/tests/test_transcript_dialects.py -q`
  — 35 passed in 0.21s.
- A **14-mutation matrix** over `dialects.py` and the CLI wiring killed every
  mutation; the mutations and the tests that caught each are listed in the
  spec's Result section. If you find a rule the suite does not actually
  enforce, that is exactly the finding worth having.
- `make test` — 1762 passed in 9m22s, web build green, exit 0.
- `make test-fast` — one failure,
  `test_frame_image.py::test_an_unreadable_frame_raises_a_named_error`, on the
  fast-set *budget* (2.91s vs 2.00s) in a module this story does not touch;
  0.01s when re-run alone, and absent from the full gate. Cross-lane
  contention on the shared stack, as the budget message itself anticipates.
- `python3 _bmad/scripts/branch_conflicts.py --against story/6-3` — clean
  against `main`, `story/6-2`, `11-2` and `11-2-followup-review`. Three other
  kinds of pair, none of them code: the `6-2-review` pair is the named union
  above; `sprint-notes.md` conflicts with every lane that has also written its
  narrative there (`7-1`, `8-1`, `10-1`, `11-3`, `11-4`), because the wave
  rules put narrative in that file and git cannot union two appends after the
  same last line — this story's entry was trimmed to keep that hunk small;
  and the `11-2-review` spec and `11-4-review` report pairs conflict with
  `main` as well (inherited). If you think the sprint-notes collision was
  avoidable, that is a legitimate finding — say how.
- Not run: `make evals-run` (paid), the shared api or worker (never started),
  any model call. No test makes an HTTP call — the CLI tests install a fixture
  that fails the test if one is attempted.
