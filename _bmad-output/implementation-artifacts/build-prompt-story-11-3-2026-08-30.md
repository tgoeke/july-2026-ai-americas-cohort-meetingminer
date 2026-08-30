# Builder handoff — Story 11.3: Eval Runs Own Their Namespace

Agent: `bmad-build-auto`. Read `wave-2026-08-30-rules.md` in this directory
first; it carries the wave-wide rules and the conflict check you must pass.

- Repository: `/Users/devopsterus/current/cohort/meetingminer`
- Worktree: `/Users/devopsterus/current/cohort/meetingminer-wt/11-3`, branch `story/11-3`
- Story: `_bmad-output/planning-artifacts/epics.md` → "Story 11.3: Eval Runs
  Own Their Namespace" (NFR20). One Given/When/Then clause.
- Context: `_bmad-output/implementation-artifacts/epic-11-context.md`,
  `evals/RUNBOOK.md`, `evals/harness/run.py` (`default_run_id`),
  `evals/conftest.py` (`--run-id`), the publish-gate check under
  `evals/checks/`, `infra/Makefile` `evals-run` (main lines 360–366).

## Footprint — the only files and regions you may change

| Path | Allowed edit |
|---|---|
| `evals/**` | Harness, conftest, checks, tests, README, RUNBOOK: run folder owned by its run id (never reused, never overwritten — refuse an existing folder by name); the publish-gate check writes through the public api into a namespace the run owns (run-id-prefixed ids) and cleans it up; dev stores read-only otherwise. |
| `infra/Makefile` | The `evals-run` recipe only (main lines 360–366). No other Makefile line. |
| `server/tests/test_makefile_evals.py` | NEW, if you need Make-level assertions. Do not edit `test_makefile_procs.py`. |
| `AGENTS.md` | Exactly one change: the sentence that says `make evals-run` is one at a time becomes the measured truth. **Edit it last**, after `git fetch && git rebase origin/main` — 11-2 rewrites that section and is landing during your build; edit whichever version you rebase onto. |
| `.claude/skills/integrate/dispatch.md` | Same rule, same sentence (step 2's last line), same "rebase first". |
| `_bmad-output/implementation-artifacts/` | Your spec, `sprint-status.yaml`, `sprint-notes.md`, `review-prompt-story-11-3-<date>.md`. |

Not yours: `server/tests/conftest.py`, `server/meetingminer/**`, `docs/backlog.md`,
`project-context.md`, root `README.md`.

## Hard constraint — no paid run

`make evals-run` calls the `chat` and `judge` roles (`openai/gpt-5.2`, paid).
**Do not run it.** Prove namespace ownership with `make evals-test` and unit
tests against the harness (fake api, recorded responses). If the acceptance
clause's "measured truth" needs a real concurrent run, write the exact command
and expected observation into the spec's verification section for the owner
to execute, and say so in the report.

## Verification

- `make evals-test`; `uv run --project server pytest server/tests/test_makefile_evals.py -q` if created.
- `make test-fast`.
- `python3 _bmad/scripts/branch_conflicts.py --against story/11-3` → clean.

## Completion

Spec `status: review`, `11-3-eval-runs-own-their-namespace: review` in
`sprint-status.yaml`, review prompt written, all pushed, SHAs reported.
