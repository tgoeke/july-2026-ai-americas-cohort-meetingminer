# Code review handoff — Story 2.1b: Bring Your Own Recording

You are reviewing a completed, pushed branch. You have none of the build run's context; everything
you need is below. Read `AGENTS.md` at the repository root first and follow it.

## Where the code is

- **Repo:** `/Users/devopsterus/current/cohort/meetingminer` (a worktree of the same branch is at
  `/Users/devopsterus/current/cohort/meetingminer-wt/2-1b`).
- **Branch:** `story/2-1b`, pushed to `origin/story/2-1b`.
- **Review range:** `0df90afb2bb1a0d5f5cc4e34f2c30dd2c02f6dbd..HEAD` — that base is `origin/main`
  at the time the branch was cut, so the range is exactly this story.

```
git fetch origin && git log --reverse --oneline 0df90af..origin/story/2-1b
git diff 0df90af..origin/story/2-1b
```

Commits in the range, oldest first — **all nine belong to story 2.1b**; none belongs to another
story:

- `182167b1e983139ec3b17a3b16e1cbf189fd14eb` docs(2.1b): plan the bring-your-own-recording drop tool
- `8209679da3cbaf5e7d05b19ec8924dbcafa1fd8d` feat(2.1b): mint a source drop from a local recording
- `b635bc08b77bf8b4a2386bded1431b57e7da01e2` test(2.1b): cover mint-drop's I/O matrix and acceptance criteria
- `642aa7363a572f31f15669092ba4861d8f0d5310` feat(2.1b): wire mint-drop into the scripts, the Makefile, and docs
- `fefde42b6159bc45ab61af46074ec57e05e3ff6e` docs(2.1b): record the implementation baseline on the story spec
- `9605f4e8dd57aea4b0e6a8536ec17ec5d93c0277` fix(2.1b): address review findings in mint-drop
- `d7efc31cc011aef017734c9745b89cbc5093a7ca` docs(2.1b): correct and complete the mint-drop procedure
- `c5cf7abbf081603936324c6862957668a9807bb9` docs(2.1b): record the review triage, deferrals and run result
- `695bdceb36b93b598dea9d9e472a056630784cb8` chore(sprint): story 2.1b is built and awaiting code review

## The specification

`_bmad-output/implementation-artifacts/spec-2-1b-bring-your-own-recording-drops.md`.

- Everything inside `<intent-contract>` — Intent, Boundaries & Constraints, the I/O & Edge-Case
  Matrix — is **frozen intent**. It was written before this run and preserved verbatim. Do not
  treat a deviation from it as acceptable, but do not propose rewriting it either.
- Everything outside that block — **Code Map, Tasks & Acceptance, Design Notes, Verification** — is
  planner work produced by this run and is fair game. Attack it.

## Architecture authority

Read these decision records specifically; they are what governs this change:

- **AD-1 (One canonical inbox: the source drop)** in
  `_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md`.
  Names "Teams puller, local recording, future YouTube" as the three sources and requires every one
  of them to land as a write-once drop validated against `docs/source-drop.schema.json`. Also fixes
  the puller as a black box that imports no server code — which is the reason this tool duplicates
  rather than shares the puller's staging-and-finalize logic.
- **AD-13 (Provided transcripts are immutable inputs)** — drop contents are read-only *after
  intake*. The relevant question for this review is whether the tool ever writes inside an existing
  drop, not whether it writes to the drops root at all.
- **AD-14 (One intake door)** — `POST /ingests` is the only way in. Check that this tool adds no
  second path and that its status mapping matches the door's real responses.
- `_bmad-output/specs/spec-meetingminer/storage-layout.md` — **section 1** names "the
  bring-your-own-recording tool" as a legitimate writer of the drops root beside the puller's
  `emit-drop`; **section 6** is the frozen description of this tool; **section 4** is the anchor rule.

## Scope

**In scope — the files this story owns:**

- `server/meetingminer/mintdrop.py` (new, ~1000 lines) — the command.
- `server/tests/test_mint_drop.py` (new) — 53 store-free tests.
- `server/meetingminer/pipeline/media.py` — one additive public function, `probe_creation_time()`.
- `server/pyproject.toml` — one `[project.scripts]` entry.
- `infra/Makefile` — the `mint-drop` target, `MINT_ARGS`, `.PHONY` and `help` entries.
- `docs/README.md` — the user-facing procedure, replacing a three-line stub.
- `_bmad-output/implementation-artifacts/spec-2-1b-*.md`, `sprint-status.yaml` — process artifacts.

**Explicitly out of scope:**

- `pull_transcript/` — the vendored puller is untouched by this story. `make puller-test` is a
  regression check only.
- Augmentation (`augments`, `schemaVersion: 2`). The tool mints version 1 drops only. The gap this
  leaves is recorded as a deferred item in the spec's frontmatter, not an oversight.
- Story 3.1 (Corpus Search) is in flight in another worktree and owns its own files.
- The four items in the spec's frontmatter `deferred:` list are already recorded. Re-reporting them
  is noise; finding them *wrongly characterised* is not.

## Design decisions to attack

These are the calls the planner made. The planner is not a neutral judge of its own work, so they
are handed over rather than left to be rediscovered. Each is stated as the choice plus the
assumption under it.

1. **The tool is Python inside the server package, not a sibling of `pull_transcript/emit-drop.js`.**
   Assumption: the acceptance criterion "someone follows the documented procedure and reaches an
   ingested meeting without hand-writing JSON" requires the tool to know `MM_DROPS_ROOT` without the
   user restating it, and only `meetingminer.config` reads this project's `.env` dialect. Teaching
   the puller to read `.env` would break AD-1's black-box property. **The cost is a second,
   independent staging-and-finalize implementation that can drift from the puller's.** If you think
   the drift risk outweighs the config-reading benefit, say so — that is the central call here.

2. **`sourceId` is `sha256:<hex>` of the *primary* evidence file**, primary meaning the first
   present of `recording.mp4`, `transcript.vtt`, `transcript.txt`. Assumption: a local file has no
   natural stable identity and a path is not one. Consequence the spec accepts: a transcript-only
   mint and a later video mint of the same meeting are two occurrences.

3. **Re-run detection scans the drops root by `sourceId`, not by directory name.** Assumption: the
   name embeds a date and title slug the user can change between runs, so a name-keyed check would
   let a second write-once drop be finalized that intake then refuses with 409 forever. Cost: an
   `iterdir()` plus a `metadata.json` read per candidate on every mint.

4. **`startedAt` comes from `--started-at` or the container's `creation_time`, never the
   filesystem.** Assumption: mtime is reset by copying and downloading, so deriving a wall clock
   from it is the guess the intent forbids. Consequence: every transcript-only mint, and every mp4
   whose `creation_time` was stripped by a remux, requires `--started-at`. Judge whether that
   pushes a matrix edge case onto the default path.

5. **`--drops` pointing outside the configured root warns rather than refuses.** Assumption: the
   test suite depends on the flag to stay store-free. The warning says intake will answer 400. An
   operator who ignores it still finalizes an unusable write-once drop. A hard refusal when a POST
   would follow is the obvious alternative — assess it.

6. **`probe_creation_time()` was added to `pipeline/media.py`** rather than duplicating subprocess
   handling in the CLI, on the principle that ffprobe knowledge belongs to one module. That module's
   docstring says the pipeline never derives wall clock from media metadata; the new function's
   caller is the source side, not the pipeline. Judge the siting.

## History you need to tell a regression from a pre-existing condition

- **The branch was re-baselined mid-run.** It was first cut from `story/2-1a` under the mistaken
  belief that 2.1a had not landed. `origin/main` already carried 2.1a merged and remediated, so the
  branch was reset onto `origin/main` (`0df90af`) **before any code was written**. No 2.1a commits
  appear in the range and nothing from the discarded baseline survives.
- **A review pass already ran on this branch**, inside the build run: four parallel reviewers, then
  14 patches applied in `9605f4e` and `d7efc31`. The spec's `## Review Triage Log` records every
  finding, what was done, and what was rejected and why. Four of those findings were proven by
  mutation testing. **You are the second pass; expect the obvious defects to be gone and look
  past them.** Two first-pass claims were rejected as not reproducing — a supposed traceback from a
  schemeless `--api` (it is a caught `URLError`) and a `find_existing_drop` blind spot on `-NNN`
  sequence drops. If you disagree, reproduce rather than restate.
- The test count moved 37 → 53 in the patch pass. The 16 new tests pin guards that were previously
  deletable without the suite noticing.
- `docs/README.md` grew from a 3-line stub to the procedure. The whole file is effectively new.
- The spec's Verification section was edited to drop a stale "hold the shared stores" line,
  matching `e794365` on main: story 2.7 made the server suite safe to run concurrently.

## Verification baseline

These were all run on the final tree. A skip or a failure when you run them is a **finding**, not
noise:

| Command | Result |
|---|---|
| `cd server && .venv/bin/python -m pytest tests/test_mint_drop.py -q` | 53 passed |
| `cd server && .venv/bin/python -m pytest tests/ -q` | 982 passed, 0 failed, 0 skipped (3m59s) |
| `make puller-test` | 102 pass, 0 fail |
| `make mint-drop MINT_ARGS='--help'` | usage, exit 0 |

The server suite is safe to run concurrently (story 2.7: per-run Postgres database, projection tests
on a bounded cross-worktree lock). Only `make evals-run` is one at a time.

**Not verified, and the largest open claim in the story:** the manual end-to-end — mint a drop, POST
it to a running api, and confirm the meeting is viewable with replay working. It needs the full
stack up and no run has proved a minted drop actually ingests against a live api. Every test drives
the process surface (argv in, exit code out, `tmp_path` root, stubbed `urlopen`); the door's
containment rule is asserted only through `drop_relative_path`. If you can stand the stack up, that
is the highest-value thing you can do with this review.

## Required output

Write your findings to
`_bmad-output/implementation-artifacts/review-story-2-1b-2026-08-20.md`.

**Report findings; do not apply fixes.** Leave the tree as you found it.

Structure each finding as:

- **Location** — `file:line`.
- **Severity** — high / medium / low, by consequence to the operator minting a drop.
- **What is wrong** — one sentence.
- **Why it is real** — the concrete input or state that triggers it and the wrong result it
  produces. A finding you could not reproduce should say so.
- **Suggested direction** — not a patch.

Close with an overall verdict: is this branch fit to merge to `main` as it stands?
