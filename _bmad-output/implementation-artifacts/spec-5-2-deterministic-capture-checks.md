---
title: 'Story 5.2: Deterministic Capture Checks with Immutable Run Artifacts'
type: 'feature'
created: '2026-08-19'
status: 'done'
baseline_revision: 'e3efde8d825e0ac8c660328d349f98132efaf964'
review_loop_iteration: 1
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/specs/spec-meetingminer/eval-design.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-5-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-5-1-ground-truth-schema-scripted-fixtures.md'
warnings:
  - 'The store-backed half of this story runs against the shared Docker stack. Hold the test stores one agent at a time (AGENTS.md) — story 2.1a is store-backed too and may be in flight beside this.'
  - 'Both shipped fixtures still carry placeholder `source_id` values, so a live run today selects ZERO eval subjects. That is expected and the run must fail loudly on it. Do not invent a subject, relax the selector, or mark the suite skipped to get a green result.'
  - '`make evals-test` is advertised in AGENTS.md as store-free and safe to run concurrently. Keep it that way: the store-backed checks get their own target.'
  - 'Story 2.1a is being built in parallel and adds `MM_DROPS_ROOT` to `server/meetingminer/config.py` as a named startup failure. This story imports `meetingminer.config`, so once 2.1a lands, any harness code path calling `load_config` fails until `.env` carries `MM_DROPS_ROOT`. Keep every store-free unit test off `load_config` — feed the connection settings in — so `make evals-test` cannot be broken by a config key it does not use.'
deferred:
  - summary: >-
      The harness's only database code has no assertion in any suite: swapping the
      LEFT JOIN in corpus.py's capture query for an INNER JOIN passes all 281
      store-free tests.
    evidence: |-
      captures_for / media_duration_ms / has_recording are imported by exactly two
      tests. One asserts substrings of the conninfo string; the other runs an INSERT
      and calls none of the three read methods. An INNER JOIN would drop every
      capture with no frame_ocr row, so ocr_defects reports nothing and the
      over-capture numerator shrinks -- a broken frames/ocr rerun would hide behind
      a clean recall number. This surface already regressed once uncaught (the
      missing %s::uuid casts, fixed in 4eeaa15 by reading, not by a test).
      Story 5.2 patched the pure row-to-Capture mapping; the SQL itself still needs
      a store-backed test that seeds a screenshot with a NULL representative frame,
      one whose frame has no frame_ocr row, and one with text.
    location: >-
      evals/harness/corpus.py:134-176
    severity: medium
  - summary: >-
      check-api's foreign-service identity guard has no test, though the identical
      guard on `make client` has two.
    evidence: |-
      server/tests/test_makefile_procs.py pins the same curl-plus-grep guard for
      `make client` with a fake curl on PATH. Deleting check-api's grep line would
      let an eval run proceed against a foreign service on :8000 and fail with a
      shape error instead of the named refusal, with nothing failing. The fix
      belongs in server/tests/test_makefile_procs.py, which this story's contract
      forbids touching ("No change under server/"), so it cannot be done here.
    location: >-
      infra/Makefile:239
    severity: low
  - summary: >-
      A manifest whose expected capture count exceeds ceil(duration_minutes) makes
      checks 2.1 and 2.2 mutually unsatisfiable, and nothing detects it.
    evidence: |-
      Check 2.1 requires every one of expected_screenshot_count entries to be
      captured; check 2.2 fails when captures exceed ceil(duration_minutes). A
      ground-truth author can write a manifest no run can ever pass. This is the
      same family as the duration-agreement precondition the story already added,
      and belongs beside it rather than surfacing as two unexplained check failures.
    location: >-
      evals/harness/checks.py
    severity: medium
  - summary: >-
      Check 2.3's classification accuracy is partly tautological, so a real
      misclassification reads as a milder number than it is.
    evidence: |-
      capture_recall matches participant segments only against captures already
      filtered by view_type == PARTICIPANT_VIEW, and the resulting EntryMatch
      carries expected_view=PARTICIPANT_VIEW with matched_view=capture.view_type.
      view_classification then scores those entries correct by construction. For
      the shipped ui-demo fixture that is 2 of 4 scored entries, so one
      misclassified screen reports 0.75 rather than 0.5. 2.3 is a reported metric
      and does not gate the run, so this misleads rather than breaks.
    location: >-
      evals/harness/checks.py:398-402
    severity: medium
  - summary: >-
      The store-backed suite memoizes the per-subject matching in a module-level
      dict that is never cleared and is keyed only by manifest id.
    evidence: |-
      _MATCHING couples checks 2.1 and 2.3 through a global so they score the same
      matching. That is the right guarantee reached the wrong way: it is incorrect
      under pytest-xdist or any repeated-run plugin, and it makes the agreement a
      property of the test module rather than of the run. A session-scoped fixture
      gives the same guarantee with no global.
    location: >-
      evals/checks/test_capture_checks.py
    severity: low
  - summary: >-
      EntryMatch.score carries two different meanings in one report column.
    evidence: |-
      For anchored entries it is a token-containment fraction; for participant
      segments it is a fabricated 1.0 or 0.0, because segments carry no anchor and
      are matched by count. A human triaging deterministic-report.yaml cannot tell a
      measured 1.0 from a placeholder. A null score for segments, or a separate
      match_kind field, would separate them.
    location: >-
      evals/harness/checks.py
    severity: low
  - summary: >-
      evals/runs/ has no pruning policy and no gitignore or gitkeep handling, while
      every run today fails and every run folder is immutable.
    evidence: |-
      The README states run folders are committed as the audit record. Both shipped
      fixtures carry placeholder source_ids, so every `make evals-run` fails on the
      zero-subject gate and leaves a folder that measured nothing; the immutability
      rule then forbids reusing or overwriting it. Nothing says when such a folder
      may be deleted, and the directory ships with no placeholder entry at all.
      Worktree-per-agent working means two agents also produce run folders that have
      to be merged.
    location: >-
      evals/README.md
    severity: low
---

<intent-contract>

## Intent

**Problem:** Story 5.1 landed the ground-truth contract — the manifest, its loader, the recall
denominator, the subject selector — and nothing that reads the system. Every quality claim in the
SPEC's success signal ("100% capture recall against ground truth", the over-capture guardrail) is
still asserted by hand. There is also no run artifact: nothing records what was measured, against
which resolved configuration, so a verdict cannot be reproduced or invalidated.

**Approach:** Land tier-1 as pytest tests over the four BUILD capture checks (eval-design §2.1–2.4),
reading captures and their OCR text read-only from Postgres and the corpus through the public API,
plus a small session plugin that creates `evals/runs/<run-id>/`, snapshots the resolved
configuration, and writes `deterministic-report.yaml` once. The check algorithms are pure functions
in `evals/harness/`, unit-tested with no store; the store-backed tests are the thin layer that feeds
them real rows. No LLM judge, no retrieval checks, no human-verdict files — those are 5.3/5.4/5.5.

## Boundaries & Constraints

**Always:**
- Zero eval subjects is a **failure**, never a pass and never a skip. A check suite that finds
  nothing to measure and reports success is exactly the *no silent zero* constraint's failure mode.
  The run fails naming each unmatched manifest and each corpus mismatch the selector reported.
- The denominator comes from the manifest, never from what the pipeline emitted
  (eval-design §2.1 independence rule). `Manifest.expected_screenshot_count` from 5.1 is the one
  implementation; do not compute a second one.
- Capture recall threshold is 1.0. Any unmatched manifest entry fails the run.
- Over-capture fails when distinct captures > `ceil(manifest.duration_minutes)`. "Distinct captures"
  is the count of `screenshot` rows for the meeting — pinned here because eval-design §2.2 says
  "distinct captures" without saying distinct by what.
- OCR text is folded with 5.1's `normalize_anchor` before any comparison. Check 2.1 has to fold
  identically to the uniqueness rule or authoring-time collision rejection means nothing.
- A capture that cannot produce OCR text — no `representative_frame_id`, or no `frame_ocr` row for
  it — is reported as a defect of the run, not silently excluded from the haystack or the count.
- Postgres access is read-only *mechanically*: the connection sets
  `default_transaction_read_only = on`, so a write raises rather than relying on reviewer vigilance.
- AD-16 holds: the harness mutates the system only through the public API and asserts through API
  reads, read-only store queries, and run artifacts.
- The run folder is written once and never edited. Starting a run against a folder that already
  holds `verdict.md` is refused.
- The configuration snapshot is **secret-free**. Run folders are committed as the audit record, so a
  snapshot carrying `.env` values would commit them.
- Every threshold this story applies is written into the report beside the result it produced
  (eval-design §6: thresholds are provisional and a change invalidates prior verdicts).

**Block If:**
- The check algorithms cannot be exercised without a live store. If `evals/harness/` grows a store
  import, the split is wrong: the algorithms are pure functions over rows, and `corpus.py` is the
  only module that opens a connection.

**Never:**
- No check 2.5–2.11: no citation-window check, no action-item matching, no LLM judge, no doc-index
  recall, no publish gate. 2.10/2.11 are story 5.3 and append to the same report.
- No `human-verdicts.yaml`, no `verdict.md`, no triage tooling — story 5.5 owns the runbook and the
  verdict.
- No change to any manifest fixture's `source_id`. They stay placeholders until the scripted
  meetings are recorded and pulled; `test_shipped_source_ids_are_still_placeholders` is deleted, not
  edited, when the real ids land.
- No change under `server/` — not the schema, not a route, not a stage. This story reads.
- No new runtime dependency. The fuzzy comparison is stdlib (`difflib`); rapidfuzz is not in
  `server/pyproject.toml` and this story does not add it.
- No writes to any store, and no auto-collapse of a dedup candidate. Candidates are listed for a
  human; the system is biased toward over-capture over loss.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| No eval subjects | Every manifest unmatched (today's state) | Run fails, naming each unmatched manifest and each corpus mismatch | Session-level failure before any check runs |
| Every manifest entry matched | Captures whose OCR covers every anchor | Recall 1.0, check 2.1 passes, per-entry detail in the report | No error expected |
| One anchor unmatched | A screen the extractor missed | Recall < 1.0, run fails, the report names the missing entry id and its anchor | Check failure, not an exception |
| OCR noise on a matched anchor | Anchor tokens present with character-level corruption | Still matches at the documented threshold; the achieved score is recorded | No error expected |
| Capture with no OCR text | `representative_frame_id` NULL, or no `frame_ocr` row | Reported as a run defect naming the screenshot ordinal; never dropped from the count | Check failure |
| Over-capture within budget | Captures ≤ `ceil(duration_minutes)` | Check 2.2 passes; count and budget both recorded | No error expected |
| Over-capture over budget | Captures > `ceil(duration_minutes)` | Check 2.2 fails, recording count, budget and captures-per-minute | Check failure |
| Manifest duration disagrees with the recording | `duration_minutes` differs from `meeting_media.duration_ms` by more than one minute | Reported as a ground-truth authoring error; the run fails | The manifest may be describing a different meeting |
| Transcript-only subject | Scripted meeting with `has_recording = false` | Capture checks report *not applicable* explicitly and the run fails — a scripted eval subject with no recording cannot measure capture | Named failure, never an empty pass |
| View classification | Captures matched to manifest entries | Accuracy reported against the manifest-implied label (`screens`→`ui-screen`, `slides`→`slide`, `participant_segments`→`participant-gallery`) | Reported metric; does **not** fail the run |
| Dedup candidates | Sequential captures whose normalized OCR similarity > 0.9 | Pairs listed with their scores for human ruling | Never fails the run, never collapses |
| Run folder already has a verdict | `evals/runs/<run-id>/verdict.md` exists | Refused before anything is written | Named error naming the folder |
| Run folder exists without a verdict | Rerun of an interrupted run | Refused; a run gets its own folder | Named error |
| Config snapshot | Any run | Resolved settings written to the run folder with every secret redacted | Test asserts no `.env` value appears |
| Harness attempts a write | `INSERT` through the harness connection | Postgres refuses (read-only transaction) | Pinned by a test |

</intent-contract>

## Code Map

- `evals/harness/groundtruth.py:92-105` `normalize_anchor` -- the exact folding
  (`[^\w\s]` → space, lowercase, collapse). Check 2.1 folds OCR text with this function, not a
  second spelling of it; its docstring already says so.
- `evals/harness/groundtruth.py:108-160` `Manifest` -- `entries`, `section`, `duration_minutes`,
  `expected_screenshot_count`, `participant_segments`. The manifest side of every check is already
  here; nothing about ground truth is re-parsed.
- `evals/harness/subjects.py` -- `select_subjects`, `Selection` with `subjects` / `unmatched` /
  `corpus_mismatches`, `fetch_meetings` (the one network call, `GET /meetings`). The zero-subject
  failure reads `Selection.problems()`, which already renders both problem kinds.
- `evals/tests/test_harness_boundary.py:30-40` `FORBIDDEN` -- the AD-16 import guard. It currently
  bans the bare `meetingminer` root, which also bans `meetingminer.config`. This story adds a
  single named allowance (see Design Notes) and a test that the allowance is exactly that module.
- `evals/tests/test_harness_boundary.py:92-116` -- the "one network module" test; mirror its shape
  for a "one database module" test over `corpus.py`.
- `server/meetingminer/migrations/0003_screens_screenshots.sql:9-31` `frame_ocr` -- `text`,
  `normalized_text`, `engine`, keyed by `frame_id` with `meeting_id` beside it. This is the haystack.
- `server/meetingminer/migrations/0003_screens_screenshots.sql:64-90` `screenshot` -- `ordinal`
  (unique per meeting), `representative_frame_id` (nullable, `SET NULL` on a frames rerun),
  `view_type` (`slide` | `ui-screen` | `participant-gallery`), `path`, `capture_cues`. One row per
  capture: the count check 2.2 measures and the sequence check 2.4 walks.
- `server/meetingminer/migrations/0002_meetings_media_frames.sql:26-45` `meeting` -- `source_id`,
  `corpus`, `has_recording`. `:51-71` `meeting_media` -- `duration_ms`, for the manifest-duration
  cross-check.
- `server/meetingminer/db.py:44-56` `conninfo` -- the conninfo shape to mirror. **Do not import it**
  (`meetingminer.db` opens write pools and stays forbidden); build the read-only conninfo in
  `corpus.py` from `config.settings.stores.postgres` plus the `.env` password, adding
  `options="-c default_transaction_read_only=on"`.
- `server/meetingminer/config.py:644-688` `load_config` -- returns `AppConfig(settings, secrets,
  config_path)`. `settings` is the resolved `config.yaml`; `secrets` is `.env` and must never reach
  the snapshot.
- `config.yaml` -- what the snapshot captures: `config_version`, `ocr`, `stt`, `llm.roles`,
  `embedder`, stores. The OCR engine binding is why the snapshot matters — a recall number is only
  interpretable next to the engine that produced the text.
- `server/tests/test_projections_single_writer.py:26-50` -- the AST-guard convention the boundary
  test already follows; reuse it for the new one-database-module guard.
- `infra/Makefile:187-201` -- `test` runs the store-free group (`puller-test`, `web-test`,
  `evals-test`) before `infra-up`. `evals-test` must stay in that group; the new store-backed target
  sits with the server suite, after `infra-up`.
- `AGENTS.md:86-89` -- names `make evals-test` as store-free and concurrently safe. It gains a line
  for the store-backed target rather than a correction.
- `_bmad-output/specs/spec-meetingminer/eval-design.md:74-93` -- §2.1–2.4, the four algorithms and
  their thresholds. §6 is the threshold-policy rule the report obeys.

## Tasks & Acceptance

**Execution:**
- `evals/harness/checks.py` -- new, pure: `token_containment(anchor, text)` (the documented fuzzy
  comparison), `capture_recall(manifest, captures)`, `over_capture(manifest, captures)`,
  `view_classification(manifest, matches)`, `dedup_candidates(captures)`. Each returns a result
  object carrying its threshold, its score, and per-entry detail — the report is a serialization of
  these, not a second computation.
- `evals/harness/corpus.py` -- new, the only module that opens a database connection: a read-only
  connection built from the resolved config, `captures_for(meeting_id)` returning ordinal, view
  type, OCR text and representative-frame presence per capture, and `media_duration_ms(meeting_id)`.
  Rows in, dataclasses out; no algorithm lives here.
- `evals/harness/run.py` -- new: `Run` — folder creation under `evals/runs/<run-id>/`, refusal when
  the folder exists, the redacted configuration snapshot, and `write_report(results)` producing
  `deterministic-report.yaml` exactly once.
- `evals/conftest.py` -- new: `--run-id` / `--run-label` options and the session fixtures
  (`run`, `subjects`) the check tests request. Creates nothing unless a check test asks for it, so
  `evals/tests/` stays store-free and folder-free.
- `evals/checks/__init__.py`, `evals/checks/test_capture_checks.py` -- new: the store-backed tier-1
  tests, parametrized per eval subject, one test per check, each recording its result into the run.
- `evals/checks/test_subjects_exist.py` -- new: the zero-subject failure, ordered first so a run
  with nothing to measure fails on that rather than on four empty checks.
- `evals/tests/test_checks.py` -- new: the algorithms over synthetic captures — every matrix row
  that is not store-backed, including the OCR-noise tolerance and both threshold boundaries.
- `evals/tests/test_run_artifacts.py` -- new: folder creation, the verdict-exists refusal, the
  write-once rule, and the assertion that no secret value appears in the snapshot.
- `evals/tests/test_harness_boundary.py` -- extend: the named `meetingminer.config` allowance with a
  test that `meetingminer.db` / `.pipeline` / `.projections` / `.worker` are still refused, and a
  one-database-module guard mirroring the one-network-module test.
- `evals/README.md` -- extend: what a run is, how to start one, what lands in the folder, why the
  folder is immutable, and that a run with no subjects fails by design.
- `infra/Makefile` -- add `evals-run` (store-backed, needs the api and the stores), list it in
  `.PHONY` and `help`; leave `evals-test` store-free and in the pre-`infra-up` group.
- `AGENTS.md` -- add `make evals-run` to the store-holding suites, beside the server tests.
- `_bmad-output/specs/spec-meetingminer/eval-design.md` -- additive note recording the two decisions
  this story makes precise: the exact fuzzy comparison behind "token-set match ≥ 0.8", and that
  "distinct captures" means `screenshot` rows. Same additive discipline story 5.1 used for §1.

**Acceptance Criteria:**
- Given no manifest matches an ingested scripted meeting, when a run is started, then it fails
  naming every unmatched manifest and every corpus mismatch, and no check reports a pass.
- Given an eval subject whose captures cover every manifest anchor, when check 2.1 runs, then recall
  is 1.0, the check passes, and the report carries a per-entry line naming the matched capture and
  the score it achieved.
- Given an eval subject missing one manifest entry, when check 2.1 runs, then the run fails and the
  report names the missing entry id and its anchor.
- Given a capture with no `representative_frame_id` or no `frame_ocr` row, when the checks run, then
  the run fails naming that capture's ordinal — it is never dropped from the haystack or the count.
- Given an eval subject, when check 2.2 runs, then distinct captures, `ceil(duration_minutes)` and
  captures-per-minute are all recorded, and the check fails when the count exceeds the budget.
- Given a manifest whose `duration_minutes` differs from the recording's probed duration by more
  than a minute, when a run starts, then it fails as a ground-truth authoring error.
- Given matched captures, when check 2.3 runs, then classification accuracy is reported against the
  manifest-implied label and the run's pass/fail does not depend on it.
- Given sequential captures above the dedup threshold, when check 2.4 runs, then the pairs and their
  scores are listed for human ruling and nothing is collapsed.
- Given a completed run, when the folder is inspected, then it holds `deterministic-report.yaml` and
  a resolved configuration snapshot with every secret redacted, and a second run against the same
  folder is refused.
- Given the harness's database connection, when a write is attempted through it, then Postgres
  refuses it.
- Given the repository, when `make evals-test` runs, then the store-free suite still passes with no
  Docker store, no api, and no run folder created.

## Design Notes

**The haystack is the pipeline's own OCR text, and that is safe in the direction that matters.**
Check 2.1 could re-OCR each captured PNG with its own engine, which eval-design §2.1 reads as. It
does not, for two reasons. The independence rule constrains the *denominator* — the manifest — and
the denominator here is authored from the meeting script and untouched by this story. And the
failure direction is safe: a capture that was never taken has no row and no text, so it fails; a
capture that was taken but whose OCR is too corrupt to match also fails. Both are the correct
verdict. The mode this trades away is a capture that exists and is legible to a second engine but
not to the configured one — which is a genuine finding about the configured engine, and is why the
run's configuration snapshot records the engine beside the recall number. Re-OCR is a later
refinement, not a precondition.

**The fuzzy comparison is defined here rather than borrowed.** eval-design §2.1 says "fuzzy
token-set match ≥ 0.8" without naming an implementation, and rapidfuzz is not a dependency. Define
it as: fold both sides with `normalize_anchor`; an anchor token is *present* when some OCR token
scores ≥ 0.85 against it under `difflib.SequenceMatcher` (character-level OCR noise); the score is
present-anchor-tokens / total-anchor-tokens; the entry matches at ≥ 0.8. Two named constants, both
written into the report, both pinned by boundary tests. The alternative — adding rapidfuzz for
`token_set_ratio` — buys a well-known implementation at the cost of a dependency whose exact
semantics would then be the contract, undocumented, in a check whose threshold §6 says will be
recalibrated anyway.

**`meetingminer.config` becomes the one named import allowance.** AD-16 bans imports that let the
harness *change* state; the 5.1 guard implements that as a total ban on the package, which is
stricter than AD-16 and was already recorded as a deferred finding on 5.1. `config.py` parses
`config.yaml` and `.env` and mutates nothing. The rejected alternative — the harness parsing both
files itself — duplicates not a key name but the whole `.env` resolution contract (`MM_ENV_PATH`,
expansion, the config-anchored search), which is more surface to drift than the import is coupling.
The allowance is exactly one module and the guard test says so; `meetingminer.db` stays forbidden
even though `conninfo` lives there, because that module's job is opening write pools.

**Read-only is a Postgres setting, not a convention.** The harness connects with
`options="-c default_transaction_read_only=on"`. AD-16's whole point is that the publish-gate check
(5.3) is meaningless if the harness can write what it audits, and a rule enforced by review is a
rule that survives exactly as long as reviewers do.

**A run with no subjects fails, and today that is every run.** Both fixtures carry placeholder
`source_id` values, so `make evals-run` exits non-zero on the very first test until the scripted
meetings are recorded, pulled, and ingested, and the real ids replace the placeholders. That is the
correct state, not a defect of this story: the alternative — skipping, or passing vacuously — is the
exact shape the *no silent zero* constraint exists to forbid, and it is how a harness comes to
report 100% while measuring nothing.

## Verification

**Commands:**
- `make evals-test` -- expected: passes, store-free, no api, no run folder created. Includes the new
  algorithm, run-artifact and boundary tests.
- `uv run --project server pytest evals/checks -q` -- expected: **fails**, on the zero-subject test,
  naming both unmatched fixtures. Report this result as-is; a green run here today means the
  selector or the failure was weakened. **Store-backed — safe to run concurrently since story 2.7; only `make evals-run` is one at a time (AGENTS.md).**
- `cd server && .venv/bin/python -m pytest tests/ -q` -- expected: unchanged and passing, proving
  this story touched nothing under `server/`. **Store-backed — safe to run concurrently since story 2.7; only `make evals-run` is one at a time (AGENTS.md).**
- `uvx ruff check --isolated evals/` -- expected: clean.

**Manual checks:**
- Confirm every new regression test fails against the unfixed code before reporting completion.
- Confirm `evals/runs/` holds no folder after `make evals-test`.
- Confirm the configuration snapshot contains no value from `.env` — grep it for the Postgres
  password and the API keys.

## Review Triage Log

### 2026-08-20 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 10: (high 0, medium 6, low 4)
- defer: 7: (high 0, medium 3, low 4)
- reject: 9: (high 0, medium 1, low 8)
- addressed_findings:
  - `[medium]` `[patch]` `_record` recorded checks 2.3 and 2.4 as `blocking=True` for an
    unmeasurable subject, because `not_applicable` defaults to blocking — contradicting the
    contract's "does not fail the run" / "Never fails the run". Blocking-ness is now threaded
    through to the call site.
  - `[medium]` `[patch]` An exception inside a check's `compute()` propagated, so the check was
    never recorded and `Run.passed` computed over the survivors — a check silently absent from the
    report reads as a check that passed. Now recorded as not-applicable, noted on the run, and
    re-raised.
  - `[medium]` `[patch]` The row-to-`Capture` mapping in `corpus.py` had no assertion in any suite;
    swapping two positional indices passed all 281 tests. Extracted as `capture_from_row` with a
    named column contract and unit-tested store-free.
  - `[medium]` `[patch]` The ambiguous-manifest rule — the one decision story 5.1 explicitly handed
    to 5.2 — was reachable by no suite that runs. Added a store-free test over `_split`.
  - `[medium]` `[patch]` One capture could satisfy two manifest entries (two near-identical anchors,
    or an anchored entry plus a participant segment), reporting recall 1.0 while a scripted screen
    was never captured. Double assignment is now reported as a problem; the matching is unchanged,
    because greedy repair would make a script error look like a pipeline miss.
  - `[medium]` `[patch]` The write probe ran `INSERT INTO screen` on an autocommit connection, so a
    regression of the read-only guarantee would leave a permanent junk row in the one shared dev
    Postgres. Now runs inside a force-rollback transaction with a follow-up count assertion.
  - `[low]` `[patch]` `--run-id` / `--run-label` were joined onto `RUNS_ROOT` unvalidated, so `..`
    wrote outside `evals/runs/`. Both are now refused unless they match a safe character class.
  - `[low]` `[patch]` Snapshot redaction matched key names only, so a credential embedded in a
    URL-shaped value would reach a committed run folder. String values are now scrubbed for the
    three shapes a credential takes, which keeps `base_url` / `uri` / `url` readable — the endpoint
    is what makes a snapshot interpretable — while covering keys nobody thought to list.
  - `[low]` `[patch]` `evals/README.md:11` claimed the harness "imports no server module", which the
    same change made false and which contradicted its own `ALLOWED` guard. Also documented
    `--api-base-url` and the `recall: 1.0` next to `passed: false` triage case.
  - `[low]` `[patch]` `evals-run` probed the api before `infra-up`, and the recipe's hardcoded
    default api port could diverge from the port `check-api` validated. Reordered, and the recipe
    now passes `--api-base-url $(CLIENT_URL)`. The eval-design note was also moved out of §2.4,
    where it read as part of the dedup check, into its own §2.4a.

## Auto Run Result

Status: done

**Implemented change.** Tier-1 of the eval harness: the four BUILD capture checks from
eval-design §2.1–2.4 as pure functions over rows, a read-only corpus reader, and an immutable run
folder carrying a redacted configuration snapshot and a single `deterministic-report.yaml`. The
store-free algorithm tests and the store-backed thin layer are split as the contract requires, and
a run that finds no eval subjects fails loudly rather than passing vacuously.

**Files changed.**
- `evals/harness/checks.py` — new; the five check algorithms plus duration agreement, OCR-defect
  detection and the not-applicable result, all pure.
- `evals/harness/corpus.py` — new; the only module that opens a database connection, read-only by
  libpq option, with the row mapping extracted as a pure function.
- `evals/harness/run.py` — new; run folder creation and refusal, redacted config snapshot,
  write-once report.
- `evals/conftest.py` — new; run options, collection-time subject selection, the session fixtures.
- `evals/checks/` — new; the store-backed suite, zero-subject gate ordered first.
- `evals/tests/test_checks.py`, `test_run_artifacts.py`, `test_check_recording.py`,
  `test_capture_rows.py`, `test_subject_split.py` — new; store-free coverage.
- `evals/tests/test_harness_boundary.py` — extended; the single `meetingminer.config` allowance,
  a one-database-module guard, and the read-only conninfo assertion.
- `infra/Makefile` — `evals-run` and `check-api`; `evals-test` stays store-free and in `make test`.
- `AGENTS.md`, `evals/README.md`, `eval-design.md` — the store-holding target, the runbook, and an
  additive §2.4a recording the two thresholds this story made precise.

**Review findings.** 10 patches applied, 7 deferred (frontmatter), 9 rejected. Rejected as noise:
null-`ocr_anchor` and unknown-`section` crashes (the JSON schema makes `ocr_anchor` required on
both sections and constrains `archetype`, so neither state reaches the check), the duplicated
health-check body, README tree ordering, the heading-anchor rename, typing-style nits, and
recording residual risks in `deferred-work.md` (the spec's own `deferred` list is the mechanism).

**Follow-up review recommended.** Patched this pass: 0 high, 6 medium, 4 low.
Score = 3×6 + 1×4 = 22, which is ≥ 5, so `true`.

**Verification performed.** All commands run by me in this worktree, after the patches:
- `make evals-test` → **337 passed in 0.26s**, store-free, no api, `evals/runs/` absent afterwards.
- `uvx ruff check --isolated evals/` → **All checks passed!**
- `uv run --project server pytest evals/checks -q` → **2 failed, 1 passed, 5 skipped** — the
  expected result. Both failures are the zero-subject gate naming both placeholder manifests. The
  one pass is `test_the_harness_connection_refuses_a_write` against live Postgres, which closes the
  only I/O-matrix row that had no executed coverage.
- `cd server && .venv/bin/python -m pytest tests/ -q` → **816 passed** in 241s, confirming this
  story touched nothing under `server/` (`git diff --name-only e3efde8..HEAD -- server/` is empty).
- Manual: every value in the real `.env` grepped against both run artifacts → no leaks. The two
  run folders created during verification were deleted; the tree is clean.

**Residual risks.**
- The corpus SQL itself still has no assertion — the patch covered the row mapping, not the
  `LEFT JOIN`. Recorded as the first deferred item.
- The five parametrized capture checks have never executed against a real subject and cannot until
  the scripted meetings are recorded, pulled and ingested and the placeholder `source_id`s are
  replaced. That is the designed state, not a defect.
- Verification ran against the pre-2.1a server. Story 2.1a makes `MM_DROPS_ROOT` a required startup
  variable; `make evals-run` calls `load_config` and will need it, while `make evals-test` will not.
  Whichever story merges second should re-run.

### Review Findings — 2026-08-19 Follow-up Review

- [x] [Review][Patch] Partial runs can report a pass without either capture gate [evals/harness/run.py:308] — fixed: every selected subject must record the complete tier-1 check set; a partial report names its missing checks and cannot pass.
- [x] [Review][Patch] Over-capture records a threshold different from the rule applied [evals/harness/checks.py:477] — fixed: the report now records the computed `max_captures` budget and `ceil(duration_minutes)` formula; a fractional-duration regression pins the result.
- [x] [Review][Patch] Configuration snapshots can leak secret-shaped settings [evals/harness/run.py:66] — fixed: private-key and authorization fields plus token-only URL authorities and authorization query parameters are redacted, with snapshot regression coverage.
- [x] [Review][Patch] Corpus read failures disappear from the audit artifact [evals/conftest.py:263] — fixed: a `CorpusQueryError` becomes named unmeasurable evidence, so each requested check records a not-applicable result and the run report keeps the diagnosis.

The two SQL/API test gaps and the lack of a real scripted subject were revalidated from the prior review. They are already tracked in this story's `deferred` frontmatter and are intentionally not duplicated here.

**Follow-up verification.** The four regression cases were observed to fail before the fixes. Afterward, `make evals-test` passed (**341 passed**), `uvx ruff check --isolated evals/` passed, and the store-backed `uv run --project server pytest evals/checks -q` produced the designed result (**2 failed, 1 passed, 5 skipped**): only the two placeholder-manifest zero-subject gates failed; the read-only write probe passed.
