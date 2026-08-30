# Reviewer handoff — Story 5.2: Deterministic Capture Checks with Immutable Run Artifacts

You are reviewing a completed, pushed story branch. You have none of the build
run's context; everything you need is below. **Report findings — do not apply
fixes.**

## Repo, branch, range

- Repo: `/Users/devopsterus/current/cohort/meetingminer` (branch `story/5-2`,
  pushed to `origin/story/5-2`). A worktree for it exists at
  `../meetingminer-wt/5-2`; either checkout works.
- Review range: **`e3efde8d825e0ac8c660328d349f98132efaf964..HEAD`** (8 commits,
  16 files, +2596/−22 before the patch pass; larger after).
- Every commit in the range belongs to story 5.2. **No commit in this range
  belongs to another story.**

```
- cb6bd412b5a896f0e643140fd7bae21c84cab952  feat(evals): tier-1 capture checks with immutable run artifacts
- caa2b12e8f8faaf111070bdf28ae06f2685678af  docs(evals): document the run, and add `make evals-run`
- 4eeaa1568f7a0c8a0ef8edebfb51a2bb14386338  fix(evals): cast meeting ids to uuid, and pin read-only with no store
- 493529b35365013c340b2c8f2b34bd5c8280bfbf  docs(story 5.2): record the build baseline and move to review
- 62b0672c58cbc48e834417c108b6c948bac5f18f  docs(story 5.2): record the seven deferred review findings
- 6a4a8b7e1004711ff11bb3af4eccdf99bec16394  fix(evals): close the review findings on the capture checks
- 032d85443ae5d2aa05f37f7a66baf695ba7ee1a6  docs(evals): fix the run target's ordering and the claims it documented
- 1c79f74b6a802170f7eee7a951dd15885ccf98a3  docs(story 5.2): record the review triage and the run result
```

## The spec, and which parts you may attack

Spec: `_bmad-output/implementation-artifacts/spec-5-2-deterministic-capture-checks.md`

- **Frozen intent — do not critique, treat as given:** everything inside the
  `<intent-contract>` block (Intent, Boundaries & Constraints, I/O &
  Edge-Case Matrix). If you believe the code is right and the contract is
  wrong, say so as a finding, but judge the code against the contract.
- **Planner work — fair game:** Code Map, Tasks & Acceptance, Design Notes,
  Verification, Review Triage Log, Auto Run Result, and the `deferred` list.
  The Design Notes in particular are where this story's contestable calls live.

## Architecture authority

- `_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md`
  — **AD-16** is the decision that governs this change: the eval harness mutates
  the system only through the public API and asserts only through API reads,
  read-only store queries, and run artifacts. Two mechanisms in this diff
  implement it, and both are worth attacking: the AST import guard in
  `evals/tests/test_harness_boundary.py`, and the libpq
  `default_transaction_read_only=on` option in `evals/harness/corpus.py`.
- `_bmad-output/specs/spec-meetingminer/eval-design.md` — **§2.1–2.4** are the
  four check algorithms and their thresholds; **§6** is the policy that
  thresholds are provisional and a change invalidates prior verdicts, which is
  why every threshold must be written into the report beside its result. §1 is
  the expected-screenshot-count formula. This diff **adds §2.4a** to that
  document.
- `_bmad-output/specs/spec-meetingminer/SPEC.md` — the *no silent zero*
  constraint, and the success signal ("100% capture recall against ground
  truth") this harness is meant to make falsifiable.
- `AGENTS.md` — the shared-store rule. This diff edits it.

## Scope

**In scope (the story's file boundary):**
`evals/harness/checks.py`, `evals/harness/corpus.py`, `evals/harness/run.py`,
`evals/conftest.py`, `evals/checks/*`, `evals/tests/test_checks.py`,
`test_run_artifacts.py`, `test_check_recording.py`, `test_capture_rows.py`,
`test_subject_split.py`, `test_harness_boundary.py`, `evals/README.md`,
`infra/Makefile`, `AGENTS.md`, `eval-design.md`, plus small import-location
fixes in `evals/harness/groundtruth.py` and `subjects.py`.

**Explicitly out of scope — do not report as gaps:**

- Checks 2.5–2.11: no citation-window check, no action-item matching, no LLM
  judge, no doc-index recall, no publish gate. 2.10/2.11 are story 5.3.
- `human-verdicts.yaml`, `verdict.md`, and triage tooling — story 5.5.
- Anything under `server/`. The contract forbids it; `git diff --name-only
  e3efde8..HEAD -- server/` is empty and must stay empty.
- The placeholder `source_id` values in both shipped ground-truth fixtures.
  They stay placeholders until the scripted meetings are recorded and pulled.
- The seven items already in the spec's `deferred` frontmatter list. Read them
  first so you do not re-report them. If you think one is misclassified — that
  it should have been fixed here rather than deferred — that *is* a finding.

## Design decisions to attack

These are the planner's own calls. It is not a neutral judge of them.

1. **The haystack is the pipeline's own OCR text, not a re-OCR of each PNG.**
   eval-design §2.1 reads as "OCR every captured PNG". The story argues the
   independence rule constrains the *denominator* (the manifest), and that both
   failure directions are safe. The mode traded away: a capture that exists and
   is legible to a second engine but not to the configured one. Assumption: that
   this is a genuine finding about the configured engine rather than a false
   negative, and that recording the engine in the snapshot is sufficient
   mitigation.
2. **The fuzzy comparison is stdlib `difflib`, defined here rather than
   borrowed.** Two constants: an anchor token is present at
   `SequenceMatcher ≥ 0.85`; an entry matches at `≥ 0.8` of its tokens.
   Assumption: that a hand-defined comparison with documented constants beats
   adding rapidfuzz, whose exact `token_set_ratio` semantics would become the
   undocumented contract. Attack the constants themselves — nobody has measured
   0.85 against real OCR output.
3. **`meetingminer.config` is a single named import allowance in the AD-16
   guard.** 5.1 banned the whole package. Assumption: `config.py` mutates
   nothing, and re-implementing `.env` resolution in the harness would duplicate
   more surface than the import couples. Check the guard actually holds the line
   it claims — `meetingminer.db` must still be refused.
4. **Participant segments are matched by count against `participant-gallery`
   captures, one apiece in ordinal order.** Segments carry no `ocr_anchor`, and
   the §1 denominator includes them. Assumption: dropping them from the
   denominator would make a missing gallery capture invisible, which is worse
   than a weak matching rule. **Note this is a third decision written into
   `eval-design.md`, where the Tasks list authorized two.** A prior review layer
   also found this makes check 2.3's accuracy partly tautological — segments are
   scored against a view filter they were selected by — which is recorded as a
   deferred item.
5. **Double assignment is reported, not repaired.** One capture can satisfy two
   manifest entries. The patch pass added detection but deliberately did not add
   greedy exclusive assignment, on the argument that repairing it would make a
   ground-truth script error look like a pipeline miss. Attack whether reporting
   is enough given recall 1.0 is the pass threshold.
6. **Snapshot redaction scrubs values rather than blanking `url`/`uri` keys.**
   `dsn` and `conninfo` are key-redacted; `base_url`, `stores.neo4j.uri` and
   `stores.meilisearch.url` are kept readable and their *values* scrubbed for
   three credential shapes. Assumption: the endpoint is what makes a snapshot
   interpretable, and value scrubbing is a superset of key redaction. Attack the
   three regexes — a shape they miss reaches a committed run folder.
7. **A run with no subjects fails, and today that is every run.** Both fixtures
   carry placeholders, so `make evals-run` exits non-zero on the first test.
   This is asserted to be correct, not a defect.

## History you need to tell a regression from a pre-existing condition

- **No rebase.** The branch is a clean 8 commits on `e3efde8`, which was
  `origin/main` at build time and still is.
- **Commit `4eeaa15` fixed a defect introduced in `cb6bd41`** (missing
  `%s::uuid` casts, which would have made every corpus query return zero rows).
  It was found by reading, not by a test. Do not report it as shipped.
- **`uvx ruff check --isolated evals/` was already failing on `main`** before
  this story, on `typing` vs `collections.abc` import locations in 5.1's
  `groundtruth.py` and `subjects.py`. This diff fixes those two files. That is a
  deliberate pre-existing fix, not scope creep.
- **Story 2.1a was built in parallel and is not in this range.** It adds a
  required `MM_DROPS_ROOT` startup variable. `make evals-run` calls
  `load_config` and will need it once 2.1a merges; `make evals-test` calls
  `load_config` from nothing and will not. If you review after 2.1a merges,
  a `MM_DROPS_ROOT` failure in `evals-run` is expected, not a 5.2 regression.
- **The store-free suite grew 281 → 337 tests** across the patch pass. A count
  below 337 means something was lost.

## Verification baseline

All four run by the build agent in the worktree at `1c79f74`, after patching.
A different result during your review is a finding, not noise.

| Command | Result observed |
|---|---|
| `make evals-test` | **337 passed in 0.26s**; store-free, no api, `evals/runs/` absent afterwards |
| `uvx ruff check --isolated evals/` | **All checks passed!** |
| `uv run --project server pytest evals/checks -q` | **2 failed, 1 passed, 5 skipped** — the *expected* result |
| `cd server && .venv/bin/python -m pytest tests/ -q` | **816 passed** in 241s |

Two things about that third row, because a naive reading looks like a broken
build:

- The **two failures are the point.** They are the zero-subject gate naming both
  placeholder manifests. A green result there means the selector or the failure
  was weakened, and *that* is the finding.
- The **one pass is `test_the_harness_connection_refuses_a_write`** against live
  Postgres — the AD-16 read-only guarantee. The five skips are the capture
  checks parametrized over an empty subject set.

Manual checks also performed: every value in the real `.env` grepped against
both run artifacts (`config-snapshot.yaml`, `deterministic-report.yaml`) — no
leaks. Both probe run folders were deleted; the tree is clean.

**The last two rows are store-backed.** Postgres, Neo4j and Meilisearch are one
shared stack on fixed ports and the server fixture drops `meetingminer_test`
WITH FORCE. Confirm no other agent holds them before running either.

## Required output

Write your findings to:

```
_bmad-output/implementation-artifacts/review-story-5-2-2026-08-20.md
```

Structure it as:

1. **Verdict** — accept / accept-with-findings / reject, in one line.
2. **Findings**, each with: severity (high/medium/low), the file and line, what
   is wrong, the concrete failure scenario (inputs or state → wrong result), and
   what the fix must achieve. Rank most severe first.
3. **Design decisions reviewed** — for each of the seven above, whether you
   accept the call and why.
4. **Deferred items reviewed** — for each of the seven in the spec frontmatter,
   whether deferring was right.
5. **What you verified yourself**, and which commands you actually ran with
   their real output.

Report findings. Do not apply fixes.
