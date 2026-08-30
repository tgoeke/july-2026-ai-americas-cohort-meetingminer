# Wave 2026-08-30 — shared rules for every builder in this wave

Read this once, then your own `build-prompt-story-<id>-2026-08-30.md`. Both are
tracked in git under `_bmad-output/` (owner decision 2026-08-30: the directory
is no longer ignored — commit your spec, status and notes edits like any file).

## Why this wave is wide

The owner's direction (2026-08-30): the test reorg and the story re-slicing
existed to run more stories at once — "no more excuses". The dispatch rule is
therefore measured, not guessed: two stories run in parallel when their
*changed regions* are disjoint, checked with `git merge-tree`, not when their
*filenames* are. Your prompt names the exact regions you may edit — that
footprint is your contract, the same way the frozen spec is.

Check yourself before every push:

```bash
python3 _bmad/scripts/branch_conflicts.py --against story/<your-slug>
```

It must print `clean` against `main` and every other `story/*` branch. If it
reports a conflict, narrow *your* edit — never touch the other branch's file
to make room. `--hunks story/<slug>` shows your own regions in `main` line
numbers if you need to compare against your footprint.

## In flight beside you

- `story/11-2` (remediation, worktree `../meetingminer-wt/11-2`): `infra/Makefile`,
  `infra/docker-compose.yml`, `infra/worktree_stack.py`, `AGENTS.md` §"worktrees"
  and §"stores", `server/tests/conftest.py`, `server/meetingminer/config.py`
  (imports and lines 750–1010: the stack-override loader), `test_config.py`
  (appended at EOF), `test_makefile_procs.py`, `test_compose_contract.py`
  (lines 10–100), `test_migrations.py`, the projection-lock tests, `README.md`,
  `CLAUDE.md`, `project-context.md`, `docs/architecture.md` AD-10,
  `docs/backlog.md`, `docs/glossary.md`, `.env.example` header.
- `story/6-2`, `story/10-1`, `story/7-1`, `story/11-3`, `story/11-4`: see each
  prompt's footprint. They were chosen because their regions are pairwise
  disjoint; keep it that way.

## Rules that make the footprint hold

1. **New tests go in new files.** Never append to a shared test module
   (`test_config.py`, `test_migrations.py`, `test_makefile_procs.py`,
   `test_compose_contract.py`, `test_extraction_core.py`, …). Name the file
   after your story's concern.
2. **New fixtures live in your test module** or in a subdirectory `conftest.py`
   you create — never in `server/tests/conftest.py`.
3. **Config classes**: add fields inside the class your prompt names, at the
   anchor it names. Do not reorder, do not add a field to `Settings` unless
   your prompt says where.
4. **`config.yaml`**: edit only the block your prompt names.
5. **Docs**: `docs/project-record.md` is written at integration, not by you.
   `docs/backlog.md`, `project-context.md`, root `README.md`, `AGENTS.md` are
   off limits unless your prompt names an exact anchor; put anything you
   would have written there in your spec's deferred section instead.
6. **Nothing under `server/tests/conftest.py`, `infra/Makefile`, `AGENTS.md`**
   beyond what your prompt names.

If the story genuinely needs an edit outside its footprint, stop that task,
record it in the spec's change log with the exact file and reason, keep
building the rest, and leave the story in `review` with the gap named. Do not
widen quietly.

## When you write the reviewer handoff prompt

**The review lane fixes what it finds.** Owner ruling, 2026-08-30. Your
generated `review-prompt-story-<id>-<date>.md` must say so explicitly:

> Report every finding in the report file first (report-first, committed
> before reading code), then FIX the patchable ones yourself on
> `story/<id>-review` in your own worktree, red-first — the test observed
> failing against the unfixed code, then the fix, then green — committing each
> with its finding number. Leave unfixed, and clearly marked open, only what
> needs an owner decision or is rooted in the frozen spec. Never commit to
> `main`, never work in the main checkout, never merge — the owner runs
> `integrate`.

**Do not copy the older `review-prompt-story-*.md` files in this directory.**
Several of them predate this ruling and carry the line "Report findings — do
NOT fix them". That instruction is retired; it made every review hand its
findings back to a builder and cost this wave a full round-trip per story.
Those files are kept as the historical record of what was dispatched, not as
templates.

## Git and process

- Read `AGENTS.md` first. Commit each coherent unit as it completes; stage only
  the paths you changed (`git status --short` first, never `git add -A`); push
  without asking. Never reset, stash or clean anything outside your worktree.
- Branch `story/<slug>`, worktree `../meetingminer-wt/<slug>`, created by the
  owner with `make worktree STORY=<slug>` from the main checkout. Run
  `make bootstrap` there before anything else.
- **Stores today**: your worktree uses the shared Docker stack (story 2.7
  rules — every run owns a per-run Postgres database; projection suites queue
  on a cross-worktree file lock; a contiguous block of `AdminShutdown` errors
  means another lane recreated the stack — re-run, then `make test-db-prune`).
- **When 11-2 lands** (it is in remediation; expect it during your build):
  after `git rebase origin/main`, run `make worktree-provision` once. It
  writes `.env.worktree` and starts your private stack; without it `make test`
  refuses to run in a linked worktree by design.
- **Never**: `make evals-run` (paid judge role), `make up`, starting or
  restarting the shared api/worker, calling the `chat`/`judge` roles. The
  extraction role is local Ollama and free; still, test with fakes.
- Sprint tracking: flip your story in
  `_bmad-output/implementation-artifacts/sprint-status.yaml` (key-wise merge
  driver; `_bmad/scripts/install_merge_drivers.sh` once per clone). Narrative
  goes in `sprint-notes.md` under a heading with your story id and the date.
- Finish per the `bmad-build-auto` customization: spec `status: review`,
  `review-prompt-story-<id>-<date>.md` written, everything pushed, SHAs in
  your report.
