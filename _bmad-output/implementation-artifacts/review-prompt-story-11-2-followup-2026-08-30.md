# Follow-up code review — Story 11-2, Per-Run Store Isolation (remediation round)

You are reviewing the remediation of Story 11-2. A first follow-up review of this
story returned ten findings; this range is the work that closed them. You have
none of that run's context, so everything you need is below.

## 1. Required output — read this first, act on it before reading any code

**Report file (mandatory):**
`_bmad-output/implementation-artifacts/review-story-11-2-followup-2026-08-30.md`

The filename is deliberately distinct from the first round's
`review-story-11-2-2026-08-30.md`, which already exists and must not be
overwritten or edited.

**REPORT-FIRST — do this before you read a single line of code.** Create that
file as a skeleton (scope, review range, an empty findings section) and **commit
it**. Then append each finding as you confirm it and commit incrementally. Six
reviews in this repository produced their report only as terminal text and were
lost; a crashed or closed session must lose prose, never the artifact.

**Finding structure** — every finding carries all five fields:

- **Location** — `path:line`
- **Severity** — high / medium / low
- **Finding** — what is wrong, in one or two sentences
- **Evidence** — the concrete failing case: the input, the state, the observed
  behavior. Not a suspicion.
- **Suggested direction** — how it should behave, not a patch.

**This lane fixes what it finds.** In this repository the Codex review lane
applies its own patch findings rather than handing them back to a builder. So,
after the report exists and a finding is filed in it:

1. Work in **your own worktree** on branch **`story/11-2-followup-review`**, cut
   from `story/11-2`. `make worktree STORY=11-2-followup-review BASE=story/11-2`
   from a checkout whose Makefile is post-11.2 (the story worktree or main once
   this lands) creates it with its own private Docker stack.
2. File the finding in the report **first**, then fix it in that worktree.
3. **Red first.** Write the regression, run it, observe and record the failure
   (test id plus the assertion that failed) in the report, then make it pass.
   The commit sequence "tests red → fix green" is the evidence. A test never
   seen red does not count.
4. Verify, then commit and push your own remediation commits on
   `story/11-2-followup-review`.
5. **Stop and ask rather than guess** on anything that needs an owner decision —
   a change to frozen intent, a new dependency, a behavior the spec does not
   settle, or a fix that would need a file another in-flight lane owns. Record
   the question in the report and leave that finding unfixed rather than
   deciding it yourself.
6. **Never commit to `main`, never work in the main checkout
   (`/Users/devopsterus/current/cohort/meetingminer`), and never merge.** The
   owner runs `integrate` for the whole wave. Do not merge this or any branch.

**Closeout check.** Before you report completion, run `make check-reviews` — it
fails while any dispatched review lacks a committed report, including this one —
and state the SHA that carries the report's final version. A review reported in
the terminal but not filed does not exist.

## 2. Repository, branch, range

- Repository: `/Users/devopsterus/current/cohort/meetingminer`
- Branch under review: `story/11-2`, head **`e331fb6e26c785ee02952bc5e56208c6887c6165`**
- Implementation worktree: `/Users/devopsterus/current/cohort/meetingminer-wt/11-2`
  (owns the private stack `meetingminer-11-2`, ports 21761–21767)
- **Primary review range — the remediation, new since the first follow-up
  review:** `ebbcd6c5ae887707e741aaefd7a12b1b0d20788d..e331fb6e26c785ee02952bc5e56208c6887c6165`
  (12 commits)
- **Full story range, for context:**
  `a011695dedf1135bf0bb27df1b2c76a40990dc99..e331fb6e26c785ee02952bc5e56208c6887c6165`
  (24 commits; `a011695` is the merge-base with `origin/main`)

The 12 commits in the primary range, oldest first — note the deliberate
red/green pairing:

| Revision | Subject |
|---|---|
| `04822cd296bdbb2aa131dcee53cfa01a359a95ea` | test: red regressions for the validated stack-file schema (finding 1) |
| `e3aae50d7ea05bb8f7ea52178a9f7cc7fadbb404` | fix: `.env.worktree` is one validated ownership record (finding 1) |
| `32ceb3fb0be7fa2cdc5b84ea89dcf5847b9fa900` | feat: `MM_STACK_ID` stamped on every container and volume (incarnation identity) |
| `a508c2ac31d4ea0710a1e6b6a64f8c3862c6d45c` | test: red regressions for pruner ownership (findings 2, 3) |
| `6b7b82f3ab89f49914d770c2c99e0e2297a77e61` | fix: the pruner proves ownership for names and volumes (findings 2, 3) |
| `523c788e388634d4cdfcc16766cc6613394b2200` | test: red regressions for claim and the unified start path (findings 4, 5) |
| `f972c70952fcb85fa00b5f70647e8c14be6c9d42` | fix: claim before every start; `worktree-start` is the one start path (findings 4, 5) |
| `72cd10b9ded7c54629bd82c887c95cb52d5fcf45` | test: red regressions for teardown status propagation (finding 6) |
| `29c776293003e0aa6dcaa96be47f9be7c7380fc3` | fix: teardown status is honest end to end (finding 6) |
| `37a3bf78ae352d698b25dfd9381a76b204b7b6c0` | test: red regressions for the sweep lock, lock exclusion and strict lock keys (findings 7-9) |
| `ef0565e0ac81b4c1c9507599ec8ec97badd8a950` | fix: prune serializes on the provisioning lock; strict lock-key match (findings 7, 9) |
| `24176c85434d7a41a0ec49ade8182326a9df7932` | docs: the concrete VM bound in every required document; the ownership record documented (finding 10) |
| `e331fb6e26c785ee02952bc5e56208c6887c6165` | docs: findings closed, remediation record filed, story to review |

## 3. History you need to tell a regression from a pre-existing condition

- **`story/11-2` was rebased onto `origin/main` on 2026-08-30.** The first
  follow-up review read range `de0fc08..fa86b86`; those SHAs no longer exist on
  the branch. `fa86b86` is content-identical to today's `ebbcd6c` — the base of
  the primary range above. `git cherry` confirmed all replayed commits are
  patch-identical, so nothing was silently altered by the rebase.
- **`origin/main` has since moved past this branch's base**, to `5ed7a2d`, as
  other lanes in the same wave land. The branch has not been rebased again. A
  difference from `main`'s current tip is not necessarily this story's doing.
- `_bmad-output/` became a tracked directory on `main` on 2026-08-30 (owner
  decision, previously ignored). Spec, sprint-status and notes edits inside the
  range are therefore normal tracked changes, not a mistake.
- **Five other story lanes are building in parallel** (`6-2`, `10-1`, `7-1`,
  `11-3`, `11-4`). Known cross-lane conflicts involving this branch, all to be
  resolved by the owner at integrate, none introduced by the remediation:
  `story/11-3` on `.claude/skills/integrate/dispatch.md` and `AGENTS.md`;
  `story/7-1-review` on `sprint-notes.md`; `story/11-2-review` broadly (it
  carries the pre-remediation copy of the story). The 12 remediation commits
  touch neither `dispatch.md` nor `sprint-notes.md`.

## 4. The spec: what is frozen, what you may attack

Spec: `_bmad-output/implementation-artifacts/spec-11-2-per-run-store-isolation.md`

- **Frozen intent — do not re-derive, do not propose changing:** everything
  inside `<intent-contract>` (Intent, Boundaries & Constraints, the I/O &
  Edge-Case Matrix). The previous review concluded no finding had a
  specification root cause; that still holds.
- **Planner work, open to critique:** `## Code Map`, `## Remediation Plan —
  follow-up review 2026-08-30`, `## Design Notes`, `## Verification`,
  `## Auto Run Result`. The Remediation Plan in particular is a design authored
  in response to review findings and has itself never been reviewed.
- The `### Review Findings` checklist at the end of the spec lists the ten
  findings this range closes; all ten are checked. Judge whether each is
  genuinely closed, not merely ticked.

## 5. Architecture authority

- `docs/architecture.md` — **AD-10** is the decision this story amends: it now
  admits a checkout's private stack name and ports to the environment, in one
  sentence. Check the amendment says exactly what the code does and nothing
  more. **AD-4** (fixed Meilisearch index names) is why projection stores cannot
  be namespaced per session and why dedicated test twins exist at all. **AD-3**
  (the two storage roots, `MM_CONTENT_ROOT` / `MM_DROPS_ROOT`) is the class of
  configuration the story argues these ports belong to.
- `AGENTS.md` — the operating contract for every agent here: the worktree rules,
  the store-isolation rules, the fast-loop/full-gate split, and the staging
  rules. This story rewrites its worktree and store sections; verify the file
  now describes the mechanism that exists.
- `docs/project-record.md` is written at integration, not by this story — it is
  deliberately still stale and is **not** a finding.

## 6. Scope

**In scope — the 18 files the remediation touched:**
`infra/worktree_stack.py`, `infra/Makefile`, `infra/docker-compose.yml`,
`server/meetingminer/config.py`, `server/meetingminer/projections/locks.py`,
`server/tests/conftest.py`, `server/tests/test_worktree_stack.py`,
`server/tests/test_config.py`, `server/tests/test_compose_contract.py`,
`server/tests/test_makefile_procs.py`,
`server/tests/test_projections_locks.py`, `AGENTS.md`, `README.md`,
`project-context.md`, `docs/glossary.md`, `.env.example`, and the spec and
`sprint-status.yaml` under `_bmad-output/implementation-artifacts/`.

**Out of scope:**

- `docs/project-record.md` (written at integration) and `evals/` documentation
  (story 11.3) — both recorded as accepted deferrals in the spec frontmatter.
- Per-worktree api/web ports — filed as backlog item B-35, deliberately not
  built.
- Eval-run serialization — story 11.3.
- The eleven candidates the first review dismissed as by-design or already
  assigned: the process-wide nature of `MM_PROJECTION_LOCK_KEY`,
  process-environment precedence over `.env.worktree`, port-only endpoint
  overrides that preserve configured hosts, external `MM_ENV_PATH` semantics,
  remote or arbitrary test-twin endpoints, per-session Neo4j containers,
  Meilisearch prefixes, and Compose memory caps. Do not reopen these without
  new evidence.
- The 12 earlier commits in the full story range were reviewed in round one;
  read them for context, but findings should come from the primary range.

## 7. Design decisions to attack

These are the author's own calls, stated with the assumption each rests on. The
planner is not a neutral judge of its own decisions — that is why they are
handed to you rather than left to be rediscovered.

From the remediation round:

- **(e) Incarnation identity as a compose label.** `MM_STACK_ID` (12 hex chars,
  generated per provision) is written into `.env.worktree` and stamped as
  `com.meetingminer.stack-id` on all five services and all seven volumes.
  Assumes compose reuses an existing differently-labeled volume without
  recreating it (the author proved this on a throwaway project before use — check
  that evidence in `## Auto Run Result`), and that recreating the main stack's
  *containers* once at the next `up` is acceptable while its corpus *volumes*
  are never recreated.
- **(f) The stack name must equal `meetingminer-<directory name>` at every
  guard.** Assumes nobody moves a worktree with `git worktree move`; the
  refusal message says so. Is a rename really refused everywhere, and is the
  message actionable?
- **(g) `claim` runs before every `infra-up` that has a stack file** and tears
  down a same-named project that does not carry the file's id. Assumes a
  worktree's stores are disposable, and that a fail-closed teardown beats a
  refusal the operator would resolve with the same `down -v` by hand. This is
  the most destructive decision in the change: attack it hardest.
- **(h) The Makefile refuses foreign keys in `.env.worktree` at parse time**
  with `$(shell sed …)`. Assumes one `sed` per make invocation is acceptable
  cost, and that the extraction is correct for every assignment form.
- **(i) Existing worktree stacks (id-less) are treated as stale by `claim`** the
  first time they start after this lands — a one-time migration that discards
  those stores.

From the original round, still standing:

- **(a)** `WT_ROOT` derived from the git common dir so a worktree can create
  siblings — assumes git ≥ 2.31.
- **(b)** The stack sweep inside `test-db-prune` runs for real during the
  parallel-safety test — assumes "directory exists" is a sufficient ownership
  signal.
- **(c)** `make worktree` requires Docker for the stack but leaves the worktree
  usable if compose fails — assumes a named retry instruction beats an
  all-or-nothing rollback.
- **(d)** The lock-key override is process-wide, so a shell that exports it also
  re-keys `rebuild` and the worker — accepted as a test-only knob, documented.

The two-layer ownership model is the concept to test hardest: **directory
ownership** governs the general prune (`make test-db-prune`), **incarnation
ownership** (the stack id) governs creation and every start. Ask what happens
where the layers disagree.

## 8. Verification baseline

Run every command from the story worktree and its private stack. **Never run
`make evals-run`** (paid judge role). Never start or restart the shared api or
worker, and never touch the `meetingminer` project, its volumes, or the
`meetingminer-11-2-review` stack.

These are the current results, re-run independently at `e331fb6` on 2026-08-30
after the remediation completed. A skip or failure you observe against these is
a finding, not noise:

| Command | Result |
|---|---|
| `uv run --project server pytest server/tests/test_worktree_stack.py server/tests/test_config.py server/tests/test_compose_contract.py -q` | **279 passed**, 1 deselected, 2.81s (181 before the remediation) |
| `uv run --project server pytest -m "" server/tests/test_makefile_procs.py server/tests/test_projections_locks.py server/tests/test_parallel_store_safety.py -q` | **106 passed**, 83.16s (93 before the remediation) |
| `MM_REQUIRE_TEST_STORES=1 … test_projections_search.py::test_configured_projection_stores_are_reachable` | 1 passed, against this worktree's twins (21766/21767) |
| `uv run --project server pytest server/tests --co -q \| tail -1` | 1595/1961 collected, 366 deselected |
| `make check-test-stores` | 1 passed |
| `make check-reviews` | every dispatched review has a committed report |
| `make test`, concurrent in two worktrees | both rc 0, **2×1961 passed**, no `ProjectionLockedError`, distinct lock paths (measured by the implementation lane) |
| `docker stats --no-stream` | `meetingminer-11-2` ≈1.86 GiB, `meetingminer` ≈2.01 GiB, `meetingminer-11-2-review` ≈1.29 GiB, against the OrbStack VM's 23.5 GiB |

Every one of the twelve rows in the spec's I/O & Edge-Case Matrix has at least
one named covering test, and all covering modules ran green above.

## 9. Two cautions about the live machine

1. **`../meetingminer-wt/11-2-review`'s stack is id-less.** It was provisioned
   before `MM_STACK_ID` existed, so `claim` will classify it as a stale
   incarnation and tear it down at its next `infra-up` — its stores are lost.
   That is the intended one-time migration (decision (i)), and those stores are
   disposable, but do not be surprised by it and do not treat it as a defect
   without arguing the decision itself.
2. **The main checkout's containers will recreate once** at its next `up`,
   because the five services gained a label. Its corpus **volumes** are not
   recreated and its data is not lost. Verify that claim rather than assuming
   it — it is the single most damaging thing this change could get wrong.

## 10. What a good review of this change looks like

The ten closed findings were about failing closed, proving ownership before
destroying anything, and recovery paths that stay on safe code. Judge the
remediation on the same axes:

- Can any validated-looking `.env.worktree` still point a reader at the main
  stack or the wrong twins?
- Can anything reach `down -v` without proving it owns what it deletes — by
  name, by volume layout, or by incarnation?
- Is every documented retry path executable, and does any of them still reach
  old pre-11.2 stack logic?
- Does a failure anywhere in inventory or teardown still surface as a non-zero
  exit, through both removal targets?
- Are the new regressions real — do they actually fail against the pre-fix
  behavior — or do they assert something weaker than the finding they close?
