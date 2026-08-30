---
title: 'Puller source moves to tools/puller; its working archive leaves the repo'
type: 'refactor'
created: '2026-08-22'
status: 'done'
review_loop_iteration: 0
baseline_commit: '65f097f4ae6c00bff4a2ea72dd0a5b8f8b45b576'
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `pull_transcript/` sits at the repo root holding 3.0 GB of untracked working data — the real corp/vendor meeting archive, a live Microsoft SSO session (`.transcript-profile/`), `node_modules`, ledgers and launchd logs — while only 17 files in it are tracked source. The data has no business in the project tree, and the directory name states a task rather than naming a component.

**Approach:** `git mv pull_transcript tools/puller` so the tracked tool source becomes an ordinary in-project component beside `tools/puller-package/`, retarget every operational reference, and move the remaining untracked working directory out of the repo to `/Users/devopsterus/current/pull_transcript`.

## Boundaries & Constraints

**Always:**
- Move the **directory**, not the files: `pull_transcript/.gitignore` is a `*` allowlist whose `!` exceptions are directory-relative. Moving files individually leaves every puller file untracked-and-ignored.
- Keep the make target names `puller-test`, `puller-package`, and `bootstrap`. `server/tests/test_makefile_procs.py:1120` pins `puller-test`, its ordering before `infra-up`, and the presence of `ajv-formats` + `exit 1` in the rule.
- The drop-schema check in the puller suite must stay **armed** after the move. It is the only source-side validation of `docs/source-drop.schema.json` (AD-1).
- The external copy at `/Users/devopsterus/current/pull_transcript` must remain a working puller install: source, `node_modules`, `.transcript-profile/`, ledgers and occurrence folders together, because `--all` and `--login` resolve against `__dirname`.

**Ask First:**
- Deleting any occurrence folder, `pulls.jsonl`, `archives.txt`, or `.transcript-profile/`. This task moves data; it never removes it.
- Rewriting `tools/puller-package/build.sh:35` `ORG_CHART_SRC`. That absolute path names the *external summariser lineage* on `/Volumes/nvmepool`, not this repo's directory, and must not be retargeted.

**Never:**
- Do not touch `_bmad-output/` historical references (667 hits across 95 files). It is an append-only record; `sprint-status.yaml:53` `1-8-teams-puller-emits-source-drops` is a story-id key, not a path.
- Do not import server code, read `config.yaml`, or read `.env` from the puller. The AD-1 black-box seam survives the move unchanged.
- Do not dirty the main checkout at `/Users/devopsterus/current/cohort/meetingminer`. Another agent's unstaged deletion of `_bmad-output/specs/spec-ui-reimagine/reference-competitor-meeting-view.png` is already present there and is not ours.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Schema present in repo | `tools/puller/test/` runs under a full checkout | Schema resolves; every `SCHEMA_TEST` case validates emitted `metadata.json` against `docs/source-drop.schema.json` | N/A |
| Standalone checkout | Puller unpacked alone on the work laptop, no `docs/` above it | Schema cases skip with the existing named reason | Skip, never fail |
| Schema present but corrupt | `docs/source-drop.schema.json` unreadable or ajv missing | Suite fails at load | Named error, not a skip |
| Puller relocated again | Package moved to a different depth | Schema still resolves | Must not degrade to a silent skip |
| `--all` from `tools/puller/` | No occurrence sidecars beside the source | "No occurrences" | Clean no-op, exit non-zero per existing rule |

</frozen-after-approval>

## Code Map

- `pull_transcript/` → `tools/puller/` -- 17 tracked files; `git mv` the whole directory so `.gitignore` travels with it.
- `pull_transcript/test/emit-drop.test.js:21` -- `path.resolve(__dirname, '..', '..', 'docs', 'source-drop.schema.json')`. **The defect this move would introduce.** At `tools/puller/test/` the two-level walk resolves to `tools/docs/…` → ENOENT, which lines 33-38 convert to `schemaSkip`, and line 63 `SCHEMA_TEST = schemaSkip ? {skip} : {}` disarms every schema assertion at lines 409, 529, 1511 plus `assertValid()` (53-61). `npm test` still exits 0, so `make test` stays green with the AD-1 contract check retired. Fix depth-independently, not by counting `..`.
- `infra/Makefile:17` -- `PULLER := $(ROOT)/pull_transcript`. The single path binding; lines 251, 268, 385-391, 510-511 all derive from it.
- `infra/Makefile:385-391` -- `puller-test` rule: skips when `$(PULLER)` is absent, errors when `node_modules/{ajv,ajv-formats}` are missing. Keep both behaviours.
- `tools/puller-package/build.sh:30` -- `PULLER="$ROOT/pull_transcript"`, hardcoded; `build.sh:29` `ROOT` walk stays correct since build.sh does not move. Line 35 `ORG_CHART_SRC` is read-only for this task.
- `puller` -- tracked symlink, mode `120000`, blob content `pull_transcript`; the repo's only tracked symlink. No code traverses it (Makefile and build.sh both use the real path); README:257 states it is ergonomics only.
- `server/tests/test_makefile_procs.py:1120-1147` -- structural backstop. Path-independent, but it does **not** catch the schema-path defect: the Makefile rule stays intact while the JS resolution breaks.
- `README.md:57,256,257,258,265-266` -- arch diagram (column width matters), tree listing, and a live markdown link to `pull_transcript/CLAUDE.md` that would 404.
- `project-context.md:49-50` -- agent-facing path references.
- `tools/puller/CLAUDE.md` -- its "Layout" section lists `pulls.jsonl`, `SESSION_HANDOFF.md`, `migration-plan.txt`, `.transcript-profile/` and `<Title>/<M.D.YY>/` as siblings of the source. After the move they are not.
- Read-only, verified unaffected: root `.gitignore` (no puller entry), `.gitattributes` (no entry), `package.json` scripts and `bin` (bare basenames), `index-archives.sh:6` (`cd "$(dirname "$0")"`), all `__dirname`-anchored JS paths, `emit-drop.js:43` `DEFAULT_DROPS_ROOT` (absolute, unrelated), `web/src/features/meetings/MeetingsList.test.tsx:126` (UI copy). No CI exists in this repo.

## Tasks & Acceptance

**Execution:**
- [x] `pull_transcript/` -- `git mv pull_transcript tools/puller` -- relocate the whole directory in one operation so the allowlist `.gitignore` travels and git records renames rather than delete+add.
- [x] `tools/puller/test/emit-drop.test.js` -- replace the fixed two-level walk at line 21 with an upward search from `__dirname` for `docs/source-drop.schema.json` -- depth counting is what makes a relocation silently disarm the contract check; searching upward cannot rot the same way. Preserve both existing outcomes: not found → named skip; found but unusable → fail at load.
- [x] `infra/Makefile` -- point `PULLER` at `$(ROOT)/tools/puller` and update the comment block at 13-16 -- one binding, every target derives from it.
- [x] `tools/puller-package/build.sh` -- set `PULLER="$ROOT/tools/puller"` at line 30, leaving line 35 untouched -- restores the `[ -f "$PULLER/$f" ]` preflight.
- [x] `puller` -- delete the tracked symlink -- reinstating a root-level entry pointing at the puller defeats the move, and nothing operational traverses it.
- [x] `tools/puller/CLAUDE.md` -- correct the Layout section and add one paragraph naming the external working archive -- an agent reading it must not expect the corpus beside the source.
- [x] `README.md` -- update the diagram line, the tree listing, the removed symlink line, and the `CLAUDE.md` link target -- a 404 link is the most visible breakage.
- [x] `project-context.md` -- retarget the two path references at 49-50 -- this file is loaded as fact by every agent on this repo.
- [x] `/Users/devopsterus/current/cohort/meetingminer/pull_transcript` -- move the 35 **untracked** entries (3.0 GB: occurrence folders, `.transcript-profile/`, `node_modules/`, ledgers, logs) to `/Users/devopsterus/current/pull_transcript` and copy the 17 tracked source files in beside them -- done without waiting for the branch to land, which the "after the branch lands" sequencing existed only to permit. Leaving the tracked files in place keeps the shared main checkout clean; the merge removes them and the 320K remainder with it. Same APFS volume, so the move was instant.

**Acceptance Criteria:**
- Given a full checkout after the move, when `make puller-test` runs, then the suite passes **and** the drop-schema cases execute rather than skip.
- Given the puller directory is copied out on its own with no `docs/` above it, when `npm test` runs, then the schema cases skip with a named reason and the suite still passes.
- Given `make test`, when it runs to completion, then `puller-test` still runs before `infra-up` and `server/tests/test_makefile_procs.py::test_test_target_runs_the_puller_suite` passes.
- Given `make puller-package` with `ORG_CHART_SRC` pointed at a readable file, when it runs, then it assembles the tarball from `tools/puller/`.
- Given the work is complete, when the repo root is listed, then neither `pull_transcript/` nor a `puller` symlink is present, and `git status` in the main checkout shows no puller-related change.
- Given the external directory, when `node emit-drop.js --all --dry-run` runs there, then it finds the occurrence sidecars — proving the archive travelled intact with a working install.

## Spec Change Log

- **Finding:** all three review layers independently found that `puller-test`
  skips and exits 0 when `$(PULLER)` is not a directory, so the stale binding a
  relocation produces removes all 128 puller tests from a green `make test`.
  `MM_REQUIRE_DROP_SCHEMA` runs inside the suite and never executes in that case.
  **Amended:** nothing in the frozen intent — the constraint "the drop-schema
  check must stay armed after the move" already covered it; the Code Map had
  named the inner defect and missed the outer one.
  **Known-bad state avoided:** arming the inner door and shipping while the outer
  one stands open, which is the same failure class the spec was written to kill.
  **KEEP:** the upward search, and the decision not to fix this by counting `..`.
- **Finding:** the archive copy was seeded from the main checkout before the fix,
  so it carried the old depth-coupled resolution; acceptance criterion 2 had
  never been run against the copy that exists. Nothing detected the drift.
  **Amended:** the last task's text, to describe the untracked-only move actually
  performed; Design Notes, whose ordering rationale contradicted it.
  **Known-bad state avoided:** a two-copy split with the tested copy and the
  running copy silently diverging from the first commit onward.
  **KEEP:** the split itself — the archive must hold the tool, because `--all`
  and `--login` resolve against `__dirname`.

## Design Notes

**Why the schema fix is not "add a third `..`".** It would work today and rot on the next move, in the one way this codebase has already shown it cannot detect: a skip that keeps the suite green. `infra/Makefile:380-383` and `test_makefile_procs.py:1121-1125` both encode the rule that a missing puller check must fail rather than skip, yet neither catches an ENOENT *inside* the JS. Resolving upward removes the depth coupling that creates the hazard.

**Ordering of the physical move.** The data lives only in the main checkout; the worktree ever held just the 320K source copy. Moving the whole directory would leave that shared checkout showing 17 deleted tracked files, which this repo's policy treats as another agent's hazard — so only the 35 untracked entries moved, and the tracked files stayed until the merge removes them. That made "after the branch lands" unnecessary rather than merely early. What it did NOT avoid: `node_modules` went with the untracked entries, and `puller-test` is the first prerequisite of `test:`, so `make test` on main broke until `npm --prefix pull_transcript install` restored it. A clean `git status` is not a working tree.

**Why the external copy gets its own source.** `emit-drop.js:863` and `grab-teams-transcript.js:143` scan `__dirname`, and `.transcript-profile/` is resolved the same way. An archive without the tool beside it is inert.

## Verification

**Commands** (outcome recorded after each; `make test` as a whole was NOT run — the full gate is deferred to a dedicated pass after the reorg, by owner decision):
- `npm --prefix tools/puller install` -- PASS: 9 packages, ajv + ajv-formats present.
- `make puller-test` -- PASS: 128 tests, 128 pass, 0 skipped.
- `node --test tools/puller/test/emit-drop.test.js | grep -ci 'standalone checkout'` -- PASS: `0`.
- Bare `npm test` in `tools/puller/` with no flag -- PASS: 128 pass, 0 skipped (arms itself from the repo marker).
- Standalone copy, no repo marker above it -- PASS: 116 pass, 12 skipped, exit 0.
- Same copy with `MM_REQUIRE_DROP_SCHEMA=1` -- PASS: exit 1, names the refusal.
- Copy at depth 4 with a valid schema -- PASS: 128 pass, 0 skipped.
- Corrupt schema above the copy -- PASS: exit 1 at `JSON.parse`.
- `make -C infra puller-test PULLER=/nonexistent/path` -- PASS after the fix: exit 1. Before it: printed `skip` and exited 0.
- `uv run --project server pytest server/tests/test_makefile_procs.py -k puller` -- PASS: 4 tests. Negative-tested: a stale Makefile binding fails 2, a disagreeing `build.sh` fails 1.
- `git ls-files tools/puller | wc -l` -- PASS: `17`.
- `git log --follow --oneline -1 -- tools/puller/emit-drop.js` -- PASS: history survives the rename.
- `make puller-package` -- PASS: 68K tarball from `tools/puller/`, secret-exclusion asserts clean.
- `make puller-archive-check MM_PULLER_ARCHIVE=<archive>` -- PASS after `puller-sync`: in sync. Before it: found `CLAUDE.md` and `test/emit-drop.test.js` drifted.
- `node emit-drop.js --all --dry-run` in the archive -- PASS: 29 planned, 0 skipped, 0 failed.

**Owed to the deferred testing pass:** the server suite, the web suite, the eval suite, and the web build. None of them was run for this change.

**Manual checks:**
- Repo root contains neither `pull_transcript/` nor `puller`.
- `/Users/devopsterus/current/pull_transcript` holds the occurrence folders, `.transcript-profile/`, `pulls.jsonl`, `archives.txt`, `node_modules/`, and a copy of the tool source.
- The README link to the puller's `CLAUDE.md` resolves.
</content>
</invoke>

## Suggested Review Order

**The rename itself**

- One binding; every `puller-*` target derives from it.
  [`Makefile:19`](../../infra/Makefile#L19)

- The second, independent binding — no gate runs it, so it drifts silently.
  [`build.sh:30`](../../tools/puller-package/build.sh#L30)

**Keeping the drop-schema check armed — the point of the change**

- Start here: depth is what rotted, so nothing counts `..` any more.
  [`emit-drop.test.js:36`](../../tools/puller/test/emit-drop.test.js#L36)

- A repo marker above us means the schema must exist; a miss is a broken search.
  [`emit-drop.test.js:62`](../../tools/puller/test/emit-drop.test.js#L62)

- Where a required run refuses to skip, naming which requirement forced it.
  [`emit-drop.test.js:82`](../../tools/puller/test/emit-drop.test.js#L82)

- The outer door: a stale binding used to skip and exit 0.
  [`Makefile:406`](../../infra/Makefile#L406)

**Pinning it so the next move cannot undo it**

- The binding must name a real package — rule text alone cannot see it.
  [`test_makefile_procs.py:1164`](../../server/tests/test_makefile_procs.py#L1164)

- The packaging binding must agree with the tested one.
  [`test_makefile_procs.py:1203`](../../server/tests/test_makefile_procs.py#L1203)

- Nearest schema wins, so a longer walk cannot silently pick a stranger's.
  [`emit-drop.test.js:134`](../../tools/puller/test/emit-drop.test.js#L134)

- Four depths resolve identically — the property the whole fix rests on.
  [`emit-drop.test.js:159`](../../tools/puller/test/emit-drop.test.js#L159)

**The two-copy split this change creates**

- Tested copy here, running copy there; drift is now detected, not hoped against.
  [`Makefile:543`](../../infra/Makefile#L543)

- Per-machine, so it is an override with no default.
  [`Makefile:25`](../../infra/Makefile#L25)

- What an agent must read before running anything in either copy.
  [`CLAUDE.md:5`](../../tools/puller/CLAUDE.md#L5)

**Peripherals**

- Skips visibly rather than passing vacuously when the requirement is off.
  [`emit-drop.test.js:124`](../../tools/puller/test/emit-drop.test.js#L124)

- Agent-facing path facts, now marked machine-specific.
  [`project-context.md:49`](../../project-context.md#L49)

- Source tree listing and the link that would have 404'd.
  [`README.md:256`](../../README.md#L256)
