# Code review dispatch — Story 5.3: Retrieval & Publish-Gate Checks

## REQUIRED OUTPUT — read this before anything else

Your review does not exist until its report file is committed. Six reviews in
this repository produced findings only as terminal text and lost them.

**Report path:**
`_bmad-output/implementation-artifacts/review-story-5-3-2026-08-21.md`

**Finding structure** (one block per finding):
- **Location** — `file:line`
- **Severity** — high | medium | low
- **Finding** — what is wrong, one paragraph
- **Evidence** — why it is real (code you read, a command you ran)
- **Suggested direction** — where a fix would go; **report findings, don't
  fix them.** You change no production or test code.

**REPORT-FIRST:** before reading any code, create the report file as a
skeleton — scope, review range, an empty findings section — commit it, and
push. Then read the code, appending each finding as it is confirmed,
committing incrementally. A crashed or closed session must lose prose, never
the artifact.

**Closeout:** before reporting completion, run `make check-reviews` (it fails
while any dispatched review lacks a committed report — including this one)
and state the SHA carrying the report's final version. A review reported in
the terminal but not filed does not exist.

## Repo, branch, range

- Repo: `/Users/devopsterus/current/cohort/meetingminer` — but work in your
  own worktree: `make worktree STORY=5-3-review`, then review branch
  `story/5-3` from there. Never review in the shared checkout.
- Branch: `story/5-3`, pushed to origin.
- Review range: `9d0ada4..4c51f80` (merge-base with `main` .. HEAD), 13
  commits:
  - `b82ff7e` docs(5-3): plan retrieval & publish-gate checks — spec ready-for-dev
  - `5d1282b` feat(5-3): retrieval and publish-gate checks — wip, checks.py algorithms to follow
  - `2d919bf` feat(5-3): checks 2.10/2.11 pure algorithms in harness/checks.py
  - `1ee8598` feat(5-3): docs, Makefile help, eval-design §2.11a, ruff ISC004 fixes
  - `24703e2` docs(5-3): record build result in the story artifact
  - `ec8b026` test(5-3): store-free coverage for stores.py error mapping
  - `139751d` fix(5-3): P1 — write-method pin matches stems, catching suffixed forms
  - `25cc773` fix(5-3): P2/P3/P11/P12/P13 — publish_gate divergences, pure scripted refusal, recall hardening, asserted_published
  - `825600d` fix(5-3): P4/P5 — robust document field read, multi-record graph merge with note
  - `430bc51` fix(5-3): P6 — retrieval status guards refuse anything but 200
  - `6c1e777` fix(5-3): P7/P8/P9/P10 — per-phrase query failures, refusal via pure function, record-and-reraise handle construction, meeting_corpus coverage
  - `3fc7a0a` docs(5-3): P14 + remediation record — assert-set bullet in §2.11a, truthful artifact note
  - `4c51f80` docs(5-3): close review pass — triage log, deferred item, status done, sprint review

## Spec and what you may critique

Spec: `_bmad-output/implementation-artifacts/spec-5-3-retrieval-publish-gate-checks.md`.
The `<intent-contract>` block (Intent, Boundaries & Constraints, I/O &
Edge-Case Matrix) is frozen intent — review the code against it, do not
critique it. Everything outside that block (Code Map, Tasks, Design Notes,
the triage/remediation records) is planner work you may attack. The spec's
`deferred` frontmatter lists already-recorded findings — do not re-report
them; the Review Triage Log lists what a first internal pass already patched
and rejected, so re-reporting a rejected item needs new evidence.

## Architecture authority

- `_bmad-output/specs/spec-meetingminer/eval-design.md` §2.10, §2.11 (the
  check contracts of record), §6 (threshold policy), and the additive §2.11a
  this story wrote (four resolutions: /search as 2.10's surface; "before
  approval" = every non-published row; membership via direct read-only store
  reads; citation resolution = `momentIds` / graph edge to `moment_id`).
- AD-16 (harness is a client: mutations only via the public API, asserts via
  API reads + read-only store queries) and AD-4 (nothing outside `published`
  is ever projected; unpublished artifacts visible only via Postgres API
  reads) — both restated in `_bmad-output/implementation-artifacts/epic-5-context.md`.
- `evals/designs/retrieval-eval.md` — leg 1 mandates 2.10 through the public
  api; note its §2.11 sentence ("api-visible behavior plus the corpus
  connection") is looser than eval-design §2.11's literal store assert; the
  story resolved that in §2.11a. You may attack the resolution, not re-run it.

## Scope

In scope (the story's whole footprint — nothing under `server/` changed;
`git diff --name-only main...HEAD -- server/` is empty):
- `evals/harness/checks.py`, `retrieval.py` (new), `stores.py` (new),
  `corpus.py` (`meeting_corpus`), `run.py` (REQUIRED_CHECKS, story string)
- `evals/checks/test_retrieval_checks.py` (new), `test_publish_gate.py`
  (new), `test_corpus_artifacts.py` (meeting_corpus coverage)
- `evals/tests/test_retrieval.py`, `test_publish_gate_algorithm.py`,
  `test_store_asserts.py` (all new), `test_harness_boundary.py`,
  `test_run_artifacts.py`, `test_check_recording.py`
- `evals/README.md`, `evals/RUNBOOK.md`, `infra/Makefile` (help text),
  `_bmad-output/specs/spec-meetingminer/eval-design.md` (§2.11a additive)

Out of scope: story 4-4's projection-on-publish wiring (backlog — its absence
is why 2.11's positive half is expected to fail; that is designed, not a
finding); the 5.1 ground-truth schema/loader; the 5.2 capture checks; the
5.4 judge harness (README/RUNBOOK text about it predates or accompanies this
story); placeholder `source_id`s in the fixtures (deliberate until the
scripted meetings are recorded); the spec's `deferred` items (hardcoded HTTP
timeouts, plus everything inherited from 5.2's list).

No commit in the range belongs to another story.

## Design decisions to attack

Each stated as the choice plus the assumption it rests on — the planner is
not a neutral judge of its own calls:

1. **2.10 rides `GET /search`, unfiltered, not a raw Meilisearch query.**
   Rests on: the route is the promise; verbatim plants survive keyword-only
   ranking when the embedder is down (recorded, not failed); adding no
   `corpus` filter makes the check strictly harder, never easier.
2. **2.11 membership is a direct read-only store read.** Rests on: absence
   has no API surface (AD-4), and AD-16's "read-only store queries" licenses
   it. If you find an API-visible way to assert absence, that undercuts the
   §2.11a resolution.
3. **The positive half asserts a contract with no implementation (4-4
   backlog).** Rests on: a check that fails on a missing feature is signal,
   not noise, and the failure message says which it is. Attack whether the
   message/triage actually separates "not wired yet" from "regressed".
4. **Label-agnostic graph match on a node `id` property.** Rests on: UUID
   uniqueness across the graph and 4-4 carrying the artifact UUID as `id`.
   A 4-4 that stores the id under another property evades the assert.
5. **Already-published rows join the positive assert set** (the assert binds
   the published *state*, not this run's transition). Rests on: one-way
   lifecycle; asserting them is strictly more coverage.
6. **`ARTIFACTS_INDEX` is redeclared in `stores.py`, not imported** (the
   projections package is forbidden to the harness). Rests on: a 4-4 rename
   makes every published artifact read absent — loud, per the comment. Is it
   actually loud, or does it read as "not wired yet" forever?
7. **The scripted-corpus refusal re-reads the tag from Postgres via the pure
   `publish_gate_refusal`** before the one sanctioned mutation. Rests on:
   the read-only corpus connection is the same store the mutation would hit,
   and the race window (tag changed between selection and approval) is the
   only path to the branch.
8. **2.11 consumes state** — approving during a run means later runs find
   nothing `extracted` and record the gate half unmeasurable. Rests on: the
   alternative (harness seeding stores or resetting state) is the write the
   harness must never make. Documented in RUNBOOK; attack the rerun story.
9. **The store-free suites fake at the `stores.py` seam.** The live read
   paths — real get-document shape, real Cypher against a real graph, the
   real `/search` response — have zero executed coverage until real subjects
   and 4-4 exist. The duck-typed fakes are the assumption.

## History you need

- The first internal review pass triaged 30 findings: 14 patched (commits
  `139751d`..`3fc7a0a`), 1 deferred, 9 rejected (reasons in the spec's
  Review Triage Log — reject re-reports without new evidence).
- The six remediation commits lack the repo's `Co-Authored-By` trailer: a
  history rewrite to add them was denied and deliberately not forced on the
  shared branch. Cosmetic; not a finding.
- `evals/tests/test_store_asserts.py` was added between the build and the
  remediation (commit `ec8b026`) and later extended; it deliberately reaches
  the driver exception classes through `stores`' namespace so the
  one-module driver guard holds over the whole evals tree.
- Mid-build, a `git checkout` during mutation testing briefly wiped
  uncommitted `checks.py` edits; they were re-applied and re-verified. If
  something in `checks.py` looks half-restored, that is the incident to
  check against, not a rebase.

## Verification baseline

All run on `story/5-3` at `4c51f80` by the dispatching agent — a deviation
from these results during your review is a finding, not noise:

- `make evals-test` → **536 passed** in <1s, store-free, `evals/runs/`
  absent afterwards.
- `uvx ruff check --isolated evals/` → clean.
- `uv run --project server pytest evals/checks -q` → **2 failed, 7 passed,
  7 skipped** — designed: both failures are the zero-subject gate naming the
  two placeholder manifests; the 7 skips are the per-subject checks with an
  empty parametrization; the 7 passes include the seeded
  `test_corpus_artifacts.py` reads and the live write-probe. Store-backed:
  safe to run concurrently since story 2.7; never run `make evals-run`.
  Delete any `evals/runs/` folder your verification run creates (it
  measured nothing).
- `git diff --name-only main...HEAD -- server/` → empty.
- Worktree gotcha (4-5 precedent): a fresh worktree's `.env` template with
  placeholder roots breaks two exact-stderr server tests; `make worktree`
  symlinks the main checkout's `.env`, but if store-backed tests fail on
  credentials, that symlink is the first thing to check.
