# Review handoff — Story 8.1: AD-10 Amendment and Binding Catalog

## What you must produce, before anything else

Write your report to
`_bmad-output/implementation-artifacts/review-story-8-1-2026-08-30.md`.

**Create and commit that file as a skeleton — scope, range, an empty findings
section — BEFORE you read a line of code.** Then append each finding as you
confirm it and commit incrementally. Six reviews in this repository produced
their report only as terminal text because the file requirement sat at the tail
of a long prompt; four more were finished in a session and never filed at all. A
crashed or closed session must lose prose, never the artifact.

Each finding carries: **Location / Severity / Finding / Evidence / Suggested
direction.**

**This review lane applies its own patch findings** (repository convention,
corrected 2026-08-30). Report every finding in the report file first. Then fix
the patchable ones yourself on `story/8-1-review`, cut from `story/8-1`, in its
own worktree (`make worktree STORY=8-1-review` — never the main checkout).
Red-first: observe the test failing against the unfixed code, then the fix, then
green. Hand nothing back to a builder.

Do **not** fix: anything needing an owner decision, and anything whose root
cause is the frozen spec. Report those, mark them open, leave them for the
owner. Never merge to `main`; the owner runs `integrate`.

**Closeout.** Before reporting completion, run `make check-reviews` — it fails
while any dispatched review lacks a committed report, including this one — and
state the SHA carrying the report's final version. A review reported in the
terminal but not filed does not exist.

---

## Repo, branch, range

- Repository: `/Users/devopsterus/current/cohort/meetingminer`
- Branch under review: `story/8-1` (pushed to `origin`)
- Review range: `82f864b51d210920ab07770720c2d81bde200355..HEAD`

Commits in the range, newest first:

- `36ab7fe6fb7a982f76ce88dbf29833ae32c5a730` fix(config): a synthesized catalog entry carries no provider (story 8.1)
- `4f6b5e7880771ffecaec66c1a9a93477928830ff` chore: story 8.1 tracking — epic-8 in-progress, 8-1 review
- `1abb1b1f0b4ba201cddc502bb020d46a97f53c7d` docs: AD-10 carries the catalog amendment (story 8.1)
- `77a89cce33169d68cdebceb4e3a77999b3628a72` feat(config): per-role binding catalog and default (story 8.1, FR38, AD-10)
- `4b9d79a109300e4dc3db160a125289eb13142939` spec: story 8.1 AD-10 amendment and binding catalog (ready-for-dev)

Every commit in the range belongs to story 8.1. None belongs to another story.

## Spec

`_bmad-output/implementation-artifacts/spec-8-1-ad-10-amendment-and-binding-catalog.md`

- **Frozen intent** — everything inside `<intent-contract>`: Intent, Boundaries
  & Constraints, and the I/O & Edge-Case Matrix. A defect whose root cause is in
  there is reported and left open, never patched.
- **Planner work you may attack** — Code Map, Tasks & Acceptance, Design Notes,
  Verification, Spec Change Log, and the `deferred` frontmatter. The design
  calls below all live here.

The story's own text (FR38) is in `_bmad-output/planning-artifacts/epics.md`
under "Story 8.1". The owner-approved AD-10 wording this drew from is in
`sprint-change-proposal-2026-08-29.md` §2.

## Architecture authority

- **AD-10 — one config file drives everything** (`docs/architecture.md`). The
  decision this story amends. Judge the amendment against the sprint change
  proposal's wording and against what the code actually makes true.
- **AD-8 — ports and adapters.** `config.py` must depend on no adapter; the
  binding is named in config and nowhere else.
- **AD-5 — table ownership** and the no-silent-fallback rule are epic-8 context
  but are 8.2's to implement, not this story's.

## Scope

In scope — the eight changed paths:

- `server/meetingminer/config.py`, `server/tests/test_config_catalog.py` (new),
  `server/tests/test_failfast.py` (fixture only), `config.yaml`,
  `docs/architecture.md`, `project-context.md`, and under
  `_bmad-output/implementation-artifacts/`: the spec, `epic-8-context.md`,
  `sprint-status.yaml`, `sprint-notes.md`.

Out of scope:

- Stories 8.2 / 8.2a / 8.3 — persisted selection, the `app_setting` table,
  `/settings/*` routes, provider health on `/status`, the picker UI. This story
  stops at the config contract; nothing reads `catalog` or `default` yet.
- `docs/project-record.md`, which is written at integration, not by a builder.
- `docs/backlog.md`, `AGENTS.md`, `README.md`, `infra/Makefile`,
  `server/tests/conftest.py` — off limits to this lane by the wave rules.
- The seven items in the spec's `deferred` frontmatter are already recorded.
  Confirm or challenge the triage; do not re-report them as new.

## Design decisions to attack

Each is a choice plus the assumption under it. The planner is not a neutral
judge of its own calls.

1. **The catalog×providers cross-check lives on `Settings`, between the
   `providers` field and `stores`.** Assumption: `Settings` is the outermost
   class that holds both sections *and* whose `ValidationError` `load_config`
   wraps into the named `ConfigError` — the `AppConfig(...)` construction on
   `load_config`'s last line is not wrapped, so a refusal raised there would
   escape as a raw pydantic error. Second assumption: placing it mid-field-list
   rather than at the class tail is acceptable, because story 6-2 appends
   `acquisition` at that tail and a validator there would conflict. Attack
   both: is the placement defensible on its own terms once 6-2 has landed, or
   should it move?

2. **A synthesized entry carries no provider and is checked against nothing;
   an authored entry is strict.** Assumption: back-compatibility outranks the
   fail-closed rule for a projection of a file written before the rule existed.
   This was not the first implementation — the first derived a provider for
   synthesized entries too, and `make test` proved it refused files that load
   today. Attack the asymmetry: is "authored vs synthesized" a distinction a
   config author can predict, and is `provider: None` the right way to carry
   it rather than an explicit marker?

3. **`_provider_prefix` is deliberately narrower than the runtime routing
   rule.** `resolve_api_base` and `api/status.py:provider_of` both resolve bare
   `claude-…` and bare OpenAI spellings; this one resolves only
   `<provider>/…`. Assumption: a third copy of the bare-spelling tables would
   write provider names into `config.py` and give the tree a third rule to keep
   in step, so asking an authored entry to name its provider is the better
   trade. Consequence: a legacy `model: claude-sonnet-5` synthesizes
   `provider: None` while `/config` and `/status` report `anthropic`.

4. **`model` is not required to be in the role's own catalog.** Only
   `default in catalog` is enforced, and `default` falls back to `model` only
   when the file writes none — so `catalog: [a, b]`, `default: a`, `model: z`
   loads clean while `z` is the binding that runs. Three review layers raised
   this independently; it is deferred as an owner call because the AC does not
   ask for it and 8.2 makes the selection authoritative. **This is the finding
   most likely to be right and wrongly deferred — press on it.**

5. **`label` and `provider` are optional and mutated into place by
   after-validators.** Assumption: an omitted label should fall back to the
   binding so a picker always has text. Cost: 8.2/8.3 consumers still see
   `str | None`, and the mutation pattern breaks if `_StrictModel` ever gains
   `validate_assignment=True`.

6. **The committed `config.yaml` declares a two-entry catalog per role**, using
   only tags already in the file, each `default` equal to the `model` that role
   already ran. Both Ollama tags were verified served on
   `providers.ollama.base_url` via `/api/tags`. Assumption: demonstrating the
   shape in the shipped file is worth more than a degenerate one-entry catalog.
   Note the consequence: the shipped file is now part of the unit surface —
   removing a provider or a role tag breaks tests about temp files.

7. **AD-10 carries only the half this story makes true.** The persisted
   selection, call-time resolution and eval-snapshot sentences are left for 8.2,
   on the assumption that a decision record should not describe behavior no code
   implements. The competing reading — AD-10 is the contract 8.2 builds *from*,
   so it should land whole now — is defensible and is the largest
   reading-dependent gap an intent audit found.

## History you need to tell a regression from a pre-existing condition

- The branch was **rebased onto `origin/main` at `82f864b`** before any work.
  Story 11-2 has **not** landed on `main`, so AD-10's environment-variable
  sentence is still the pre-11-2 text; this story left it verbatim.
- **`docs/architecture.md` conflicts with `story/11-2`** — same AD-10 paragraph,
  different sentence. `sprint-notes.md` pre-declares this overlap as integrate's
  to union. It is not a defect of this branch and must not be reported as one.
- `sprint-notes.md` and two other lanes' `_bmad-output` records conflict exactly
  as they already do **against `main` itself** (measured before this story began:
  `spec-11-2-per-run-store-isolation.md`, `review-story-11-4-2026-08-30.md`,
  `sprint-notes.md` vs `story/7-1`). Pre-existing; integrate absorbs them.
- `server/tests/test_failfast.py` is edited **outside the build prompt's
  footprint**, deliberately: its fixture removes a provider the committed
  catalogs now name. No in-flight lane touches that file (measured against all
  seven `story/*` branches). This is recorded in the Spec Change Log.
- **AC clause 3 is unmet.** The build prompt asserted it was already satisfied
  because no literal `revoked` token remains. That premise is false: the comment
  it names is live at `config.yaml:147-154`. It was left alone because
  `story/10-1` inserts at exactly line 147. Deferred item 1 carries the evidence
  and the exact remedy for whoever lands after 10-1.

## Verification baseline

Current results on `story/8-1` — a skip or failure during review is a finding,
not noise:

- `uv run --project server pytest server/tests/test_config_catalog.py server/tests/test_config.py -q` → **67 passed**
- `uv run --project server pytest -m "" server/tests/test_failfast.py -q` → **12 passed**
- `make test-fast` → **1411 passed, 326 deselected, zero skips**; evals **549 passed**
- `make test` → **1739 passed** in 9m28s, web build clean
- `python3 _bmad/scripts/branch_conflicts.py --against story/8-1` → clean against
  `main`, `story/6-2`, `story/6-2-review`, `story/6-3`; `docs/architecture.md`
  against the 11-2 branches; `_bmad-output` process files elsewhere. No conflict
  in `config.py`, `config.yaml`, `project-context.md`, or any test module.

Note `server/tests/test_failfast.py` is a `slow` module: it needs `-m ""` on the
command line, and `make test-fast` does not run it. That is precisely why the
back-compat break in this story reached `make test` before it was caught.
