# Reviewer Handoff — Story 5.4: LLM Judge Harness & Bake-Off (nice-to-have)

## Required output — do this first, before reading anything else below

Write your report to:

```
_bmad-output/implementation-artifacts/review-story-5-4-2026-08-20.md
```

Finding structure, one block per finding:

```markdown
### <one-line title>

- **Location:** file:line
- **Severity:** high | medium | low
- **Finding:** what is wrong
- **Evidence:** what you read that proves it
- **Suggested direction:** what a fix would need to do — do not write the fix
```

**Report findings; do not fix them.** This review's job is to produce the report file, not to
patch code.

**REPORT-FIRST.** Before reading any code, create and commit the report file as a skeleton (scope,
range, an empty findings section) on this branch. Append each finding as you confirm it and commit
incrementally. Six reviews in this repo's history produced a report only as terminal text because
the file requirement sat at the end of a long prompt and got compacted out of context before
wrap-up — the file must exist and be committed before you do the actual reading, not after.

**Closeout check.** Before reporting completion, run `make check-reviews` from the repo root — it
fails while any dispatched review lacks a committed report, including this one — and state the SHA
carrying the report's final version. A review reported only in the terminal, with no committed
file, does not exist as far as this project is concerned.

---

## Repo, branch, range

- Repo: `meetingminer` (worktree used for the build: `../meetingminer-wt/5-4`, branch `story/5-4`)
- Base: `69b767b50a42c04ba726c707fb68f0f7aa113219` (main, after this branch was rebased onto it)
- Review range: `69b767b50a42c04ba726c707fb68f0f7aa113219..79a9b18` on `story/5-4`
- Commits in range, oldest first:
  - `2281ff0` docs(epic-5): refresh epic context cache — planning-support only, no product code;
    epics.md had changed since the cached epic-5 context was last compiled, so it was regenerated
    before planning this story. Not itself reviewable product change.
  - `f20b8e4` docs(5-4): plan LLM judge harness & bake-off spec — the spec this story implements.
  - `40c7171` docs(5-4): mark spec in-progress, capture baseline revision — frontmatter only.
  - `22a136d` feat(5-4): LLM judge harness and bake-off CLI — the implementation.
  - `30a7bde` fix(5-4): review findings — skip judge call on missing citation, fix grading — this
    build's own internal review pass (see below), applied before this handoff.
  - `f0b6c37` docs(5-4): review triage log, deferred items, and Auto Run Result — spec bookkeeping.
  - `79a9b18` docs(5-4): reviewer handoff prompt for the Codex bmad-code-review agent — this file.

The product diff worth reading closely is `22a136d` + `30a7bde` together (the second is a
same-story follow-up fixing findings from this build's own internal review, not a separate change).

This branch was rebased onto main once, after the handoff prompt was first drafted, to pick up
main's intervening commits (all in story 3-4's `web/` files and sprint docs — no overlap with this
story's files). The commit SHAs above are the post-rebase ones; if you're reading a stale copy of
this file, re-derive the range from `git log --oneline origin/main..story/5-4` rather than trusting
old SHAs.

## The spec: what is frozen vs. what you may critique

Spec: `_bmad-output/implementation-artifacts/spec-5-4-llm-judge-harness-bake-off-nice-to-have.md`

- The `<intent-contract>` block (Intent, Boundaries & Constraints, I/O & Edge-Case Matrix) is
  **frozen** — it was authored by the planner from the epics.md story text and eval-design.md §7,
  and is not itself in scope for critique of "should this exist." It IS fair game for "does the
  code actually honor this boundary" (e.g., does any test ever call a real LLM; does a candidate
  call ever receive a recording path).
- Everything below `<intent-contract>` — Code Map, Tasks & Acceptance, **Design Notes** — is
  planner work product and squarely open to challenge, especially the three Design Notes
  rationales (see "Design decisions to attack" below).
- The spec's own `## Review Triage Log` records an internal review pass this build already ran and
  fixed (13 patches, 2 deferred, 8 rejected) before this handoff. Read it — it tells you what was
  already found and fixed, and what was deliberately rejected with a stated reason, so you are not
  re-discovering the same ground blind. Treat a rejected finding there as a claim to verify, not as
  settled: the rejections were reasoned by re-reading the code directly (not just trusting the
  reviewing subagents), but a fresh, skeptical pass is exactly what independence is for.

## Architecture authority

- **AD-8 (`All model calls go through configured ports`)** — every LLM call in this diff goes
  through `meetingminer.adapters.llm.build_llm` / the `Llm` Protocol (`complete()`); no provider
  SDK is imported directly. Check this holds for both `judge.py` and `bakeoff.py`.
- **AD-10 (`One config file drives everything`)** — bake-off candidates are NOT new `config.yaml`
  keys (the `LlmRoles` schema `extra="forbid"`s that); they live in a separate
  `evals/bakeoff-candidates.yaml`, built into ad-hoc `LlmRoleBinding` instances in memory. No
  code path writes to `config.yaml`. Check this claim against the actual diff.
- **AD-12 (`Egress is unrestricted system-wide; the judge rule stays eval-scoped`)** — cloud judge
  candidates must receive only derived text (transcript snippets, extracted artifact text), never
  a recording. This diff claims to enforce this both by construction (a `JudgeItem`'s fields are
  built only from Postgres/`/chat` reads) and by a boundary test extending
  `evals/tests/test_harness_boundary.py`. Verify the boundary test actually asserts something
  meaningful and isn't a tautology.
- **AD-16 (`The eval harness is a client, not a housemate`)** — the harness must mutate the system
  only via the public API and read only read-only (API reads, direct read-only Postgres queries,
  run artifacts). `evals/harness/corpus.py` gained `artifacts_for`/`segments_for_moment` as
  read-only queries; `judge.py`'s `ask_chat` is the one HTTP call, hitting `POST /chat` (public
  API). Verify no write path was introduced anywhere in this diff.
- `_bmad-output/specs/spec-meetingminer/eval-design.md` §7 (bake-off) and §2.7 (rubric) are the
  frozen product spec this story implements; §7.1 is a new additive note this story added,
  recording implementation-level decisions eval-design itself left open (the judge JSON schema,
  the mechanical-vs-LLM criterion split, the tie-break order). Additive notes should never
  contradict the section they annotate — check that §7.1 doesn't quietly narrow or change §7's
  actual rules.

## Scope

**In scope (this story's files):**
- `evals/harness/judge.py`, `evals/harness/bakeoff.py` (new)
- `evals/harness/corpus.py` (extended: two new read-only functions)
- `evals/bakeoff-candidates.yaml`, `evals/bakeoff-samples/sample-001.yaml` (new fixtures)
- `evals/checks/test_corpus_artifacts.py` (new, store-backed)
- `evals/tests/test_judge_scoring.py`, `evals/tests/test_bakeoff.py`, `evals/tests/test_run_judge.py`
  (new/extended, all store-free, all against fakes)
- `evals/tests/test_harness_boundary.py` (extended)
- `evals/RUNBOOK.md`, `_bmad-output/specs/spec-meetingminer/eval-design.md` §7.1 (documentation)

**Out of scope, explicitly:**
- Any change under `server/` — none was made; confirm with
  `git diff --name-only 69b767b..79a9b18 -- server/` (expect empty).
- Story 4.3's approval/publish API routes (still backlog) — this story reads the `artifact` table
  directly instead of waiting on that route; that is a stated, deliberate design decision (see
  below), not an oversight to flag as a gap.
- Eval-design check 2.8 (right-moment-cited) — a citation resolving to the *correct* planted
  moment, as opposed to rubric 2.7's "is a citation present and is the answer faithful to whatever
  it cites," is explicitly a different, unbuilt, human-judge-only check. Do not flag rubric 2.7's
  scorer for not verifying `qa.expected_moment` — that's 2.8's job, and this story's own internal
  review already raised and rejected that exact point on that basis (see the spec's triage log,
  reject list) — but re-verify eval-design.md §2.7/§2.8's actual boundary yourself rather than
  taking the rejection on faith.
- Executing a real bake-off or a real judge run. Both CLIs are deliberately manual and
  RUNBOOK-invoked; `evals/runs/` does not exist anywhere in this worktree. This is intentional
  scope (see below), not incompleteness.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — touched only to mark this story
  in-progress; not itself a reviewable behavior change.

## Design decisions to attack

The planner is not a neutral judge of its own calls. Each of these is a choice plus the assumption
it rests on — attack the assumption.

1. **Manual-CLI-only, never pytest-collected.** Both `bakeoff.py` and `judge.py` refuse to run
   under any automated suite (`make evals-test`, `make evals-run`); every test uses a fake `Llm`.
   Assumption: this is the only realistic way to guarantee `pytest`/`make test` can never trigger
   a real, paid LLM call by accident. Attack: is there a path — a fixture, a conftest autouse, an
   import side effect — where these modules' code executes with a live network client during
   `make evals-test` or `make evals-run`? Grep for it; don't take the docstrings' word for it.
2. **Mechanical vs. LLM criterion split.** Rubric 2.7 names four criteria; this story computes
   `citation_present` and `contains_required_terms` in code and asks the model only `faithful` and
   `no_unsupported_claims`. Assumption: the two computed criteria are objectively decidable facts
   an LLM would answer less reliably. Attack: is `contains_required_terms`'s normalized-substring
   match actually equivalent to what a human grading rubric 2.7 by hand would intend, or does it
   admit false positives/negatives eval-design's wording doesn't anticipate?
3. **Reading `artifact` directly instead of waiting for story 4.3's API.** AD-16 permits direct
   read-only Postgres access, not only the public API; story 4.3 (which would add an artifacts API
   route) is still backlog. Assumption: this is genuinely equivalent to an API read for AD-16's
   purposes, not a shortcut that will need redoing once 4.3 lands. Attack: does `artifacts_for`
   read anything an eventual API route would filter or shape differently (e.g., artifact `state`,
   soft-deleted rows) such that this harness could see or judge something the public surface would
   never expose?
4. **Agreement graded from the first repeat, not an aggregate.** `run_bakeoff` grades `agreement`
   from `repeat_scores[0]` and uses all repeats only for the secondary `consistency` signal — a
   fix applied during this build's own internal review (previously used the *last* repeat).
   Assumption: eval-design §7's "primary score is agreement with human verdicts" describes one
   measurement, not an average across `--repeats`. Attack: is there a reading of §7 where an
   averaged agreement is actually intended, and if so does "first repeat" undersell what
   `--repeats > 1` is supposed to buy an operator running the real bake-off?
5. **No minimum-agreement floor on the winner.** `_select_winner` can crown a lone surviving
   candidate regardless of how low its absolute agreement is; this was deferred, not fixed, on the
   reasoning that eval-design §7 sets no such threshold and a human reads the score before editing
   `config.yaml`. Attack: is deferring this actually safe, or does the report's framing ("winner")
   make it too easy for an operator to skip reading the number?

## History / regression-vs-pre-existing context

- Nothing in this range was rebased or force-pushed after review; `427488e` is the original
  implementation, `99c60ea` is a same-run fix-forward after this build's own internal review
  (blind-hunter, edge-case-hunter, verification-gap, intent-alignment — four subagents run against
  the diff, findings triaged by re-reading the actual code before dispatching fixes). There is no
  dropped variant or superseded baseline to reconcile.
- `config.yaml`'s `llm.roles.judge` fallback was changed on `main` (unrelated commit, before this
  branch was cut) from a dead `ollama/qwen3:32b` tag to `ollama/qwen3:30b`. This diff does not
  touch `config.yaml` at all; if you see `qwen3:30b` referenced anywhere in this diff's fixtures or
  docs, that is this story picking up the already-correct tag, not a new change to evaluate.
- The two ground-truth fixtures (story 5.1) still carry placeholder `source_id`s, so zero real
  eval subjects exist. This is documented, pre-existing, and outside this story's boundary — the
  same state story 5.2 and 5.3 already operate under.
- **New since this story's implementation, from a real extraction run (main commit `69b767b`,
  `_bmad-output/implementation-artifacts/sprint-notes.md`):** the two whole-transcript extraction
  passes (story 4.1a) can each independently mint an artifact for the same real decision, one as
  `kind: adr` and one as `kind: action-item`, sharing an identical `anchor_ms`/moment — nothing
  reconciles them. This is a gap in the frozen extraction contract, not a defect of this story, and
  this story's code does not create or worsen it. It bears on this story's judge rubric only
  indirectly: `run_judge`'s `artifacts_for(meeting_id)` loop in `evals/harness/judge.py` scores
  every `artifact` row for a meeting as an independent `JudgeItem`, so on a real corpus exhibiting
  this duplication, the same underlying decision would be judged (and reported in
  `llm-judge-report.yaml`) twice under two different `kind`s. That is a faithful reflection of what
  the pipeline actually produced (this story's job is to score what exists, not deduplicate it),
  but flag it if you think the report should surface duplicate-anchor artifacts distinctly rather
  than silently as two unrelated items.

## Verification baseline

Run from `../meetingminer-wt/5-4` (or your own checkout of `story/5-4`):

- `uvx ruff check --isolated evals/` — expected: clean.
- `uv run --project server pytest evals/tests/test_judge_scoring.py evals/tests/test_bakeoff.py evals/tests/test_harness_boundary.py evals/tests/test_run_judge.py -q` — expected: 114 passed, store-free, no real LLM call (grep these four files for any provider SDK import or live HTTP client — none should exist).
- `make evals-test` — expected: 447 passed, store-free, no api, no Docker store, no run folder left in `evals/runs/`.
- `uv run --project server pytest evals/checks/test_corpus_artifacts.py -q` — expected: 4 passed, against the shared dev Postgres (announce before running, per this repo's shared-store convention; safe to run concurrently per story 2.7's fix).
- `uv run --project server python -m evals.harness.bakeoff --help` and `... -m evals.harness.judge --help` — expected: usage text only, no network call.

If any of these produces a different result than stated, that is itself a finding — the build's
own verification claims (in the spec's `## Auto Run Result`) should reproduce exactly.

---

This file is ready to hand to the Codex `bmad-code-review` agent.
