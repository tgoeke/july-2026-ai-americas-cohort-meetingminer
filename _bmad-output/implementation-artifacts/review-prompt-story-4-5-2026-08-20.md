# Reviewer Handoff — Story 4-5: Morning Digest Example Email

## Required output (do this first, before reading any code)

Write your findings to:

`_bmad-output/implementation-artifacts/review-story-4-5-2026-08-20.md`

Each finding must use this structure:

```
### <short title>

- **Location:** file:line
- **Severity:** high | medium | low
- **Finding:** what is wrong
- **Evidence:** why — cite the actual code/behavior
- **Suggested direction:** what a fix would need to address (do not write the fix)
```

**Report findings — do not fix them.** This review produces a report file, not
a patch. Do not edit any file under `server/`, `web/`, `infra/`, or
`pull_transcript/`.

**REPORT-FIRST.** Before reading any code, create and commit the report file
as a skeleton: scope, review range, and an empty findings section. Commit
that skeleton immediately. Then read the diff and the code it touches, and
append each finding to the file **as you confirm it**, committing
incrementally (one commit per finding, or a small batch — do not hold
findings in your working copy until the end). A crashed or closed session
must lose prose, never the artifact.

**Closeout check.** Before reporting your review complete, run
`make check-reviews` from the repo root — it fails while any dispatched
review lacks a committed report, including this one. State the exact git SHA
that carries the report's final version. A review reported only in the
terminal, and not filed as a committed file, does not exist for this
project's purposes.

---

## Repo, branch, range

- **Repo:** `/Users/devopsterus/current/cohort/meetingminer` (this review should run in its own worktree/checkout — do not use `meetingminer-wt/4-5`, which is the builder's own worktree)
- **Branch:** `story/4-5`, rebased onto `main` at `72d49bb7a13abfd5fec5e04d77d2f5983dcd5207` (pushed to `origin/story/4-5`)
- **Review range:** `b0206320060bdba6914eefc6b409a1dc89342cb3..story/4-5`

Commits in range, by revision and subject:

```
d8d6b3d feat(4-5): add digest CLI generating the example Morning Digest email
6c2945e fix(4-5): indent every line of a multi-line artifact body in the digest
425dfe4 docs(4-5): close review triage log and mark spec done
```

(An earlier commit, `b020632 docs(4-5): plan Morning Digest example email
spec`, is the review range's baseline/exclusive start — it is planning
documentation only, not implementation, and is not part of what you are
reviewing. This story was rebased onto `main` after the review-workflow pass
recorded in the spec's Review Triage Log; the rebase carried the same file
contents forward under new SHAs — the log's `112e38b..9f7b827` reference and
this range's `b020632..d8d6b3d` name the same diff.)

## Spec — frozen intent vs. planner work

- **Spec:** `_bmad-output/implementation-artifacts/spec-4-5-morning-digest-example-email.md`
- The `<intent-contract>` block (Intent, Boundaries & Constraints, I/O & Edge-Case Matrix) is **frozen intent** — treat it as the requirement, not as something to second-guess. It reflects Story 4.5 in `_bmad-output/planning-artifacts/epics.md` ("Morning Digest Example Email", COULD/droppable) and `_bmad-output/specs/spec-meetingminer/scope.md` Cluster F.
- Everything below `</intent-contract>` (Code Map, Tasks & Acceptance, Design Notes) is **planner work product** — the planning agent's own investigation and decisions, fully open to critique. In particular, the Design Notes section records three deliberate choices the planner made without an explicit spec mandate (required `--output` with no default; no new config key; plain-text/Markdown output instead of a real MIME `.eml`) — see "Design decisions to attack" below.
- This spec's `## Review Triage Log` already records one review pass performed by the build workflow itself (blind-hunter, edge-case-hunter, verification-gap, intent-alignment reviewers) — 3 patch findings applied, 11 deferred, 5 rejected. That pass is **not independent** — it ran inside the same automated session that wrote the code. Do not treat its "resolved" status as authoritative; re-examine anything in that log you find suspicious, and the frontmatter `deferred:` list in particular is fair game (all 11 items were rated low severity by that same non-independent pass).

## Architecture authority

- `_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md`, **Deferred** section: names Morning Digest as "a single generator reading published artifacts from Postgres, writing one example email file; no delivery, no scheduler, no architectural footprint. Build only if time permits, per scope.md Cluster F" — and explicitly defers exact format decisions ("decide at build") for this kind of item.
- **AD-2** (Postgres is the sole authoritative store) and **AD-4** (all store writes go through the shared projections module) govern why this story is read-only raw SQL, not a projections-module write path — confirm the code actually stays read-only (no `INSERT`/`UPDATE`/`DELETE` anywhere in `server/meetingminer/digest/`).
- `_bmad-output/implementation-artifacts/epic-4-context.md` — Epic 4 context, records that Story 4.5 "depends only on published artifacts existing in Postgres (4.3) and is droppable without impact" — confirm the code has no runtime dependency on Story 4.3's approval endpoint (which does not exist yet; 4.3 is still `backlog` in `sprint-status.yaml`).

## Scope

**In scope (this review):**
- `server/meetingminer/digest/__init__.py`, `cli.py`, `generator.py` (new module)
- `server/pyproject.toml` (one new `[project.scripts]` entry)
- `infra/Makefile` (one new target + `.PHONY`/help/`DIGEST_ARGS` additions)
- `server/tests/test_digest.py`, `server/tests/test_digest_generator.py` (new)

**Out of scope:**
- Story 4.3 (per-moment approval & publishing) and 4.4 (published artifacts become citable knowledge) — both still `backlog`. This story's tests seed `artifact.state = 'published'` rows directly via SQL rather than through 4.3's (nonexistent) approval endpoint; that is by design, not a gap this review should flag.
- `server/meetingminer/projections/cli.py` (`rebuild`) and its tests — read-only reference material this story's CLI was modeled on; not itself changed.
- `pull_transcript/`, `web/` — untouched by this story.
- Any other in-flight branch's changes (`3-4`, `4-3`, `5-4`, `2-8` per the current sprint wave) — none of their files intersect this diff's file list above; if your diff tool shows anything outside that list, it belongs to a different story and should be called out separately rather than reviewed here.

## Design decisions to attack

Each is a choice the planner made, plus the assumption it rests on:

1. **`--output PATH` is required, with no default and no new config key.** Assumption: an implicit/default output path (e.g. a hidden repo-relative file) risks landing in the git tree unnoticed, so forcing the caller to be explicit is safer than a default. Attack: is a required flag actually the right tradeoff for a "one-shot demo" tool, versus a documented default under an existing root (e.g. `MM_CONTENT_ROOT`)? Does requiring it needlessly complicate the `make digest` invocation compared to `make rebuild`'s zero-argument-safe default?

2. **No new `publish_folder`/config key, even though the epic context describes a "publish folder" as the eventual home for published artifacts.** Assumption: since Story 4.3/4.4 haven't built that config key yet, adding one now for this story alone would be exactly the "architectural footprint" the story's own AC forbids. Attack: is this actually correct, or does it just defer an inevitable config decision onto whichever story lands second?

3. **Output is plain text/Markdown, not a real MIME `.eml` file**, despite the story and scope.md both literally calling the deliverable an "email." The intent-alignment reviewer (build workflow's own pass) flagged this exact divergence and did not resolve it — it noted the diff's own code comment supplies the justification ("no delivery mechanism exists to consume a real .eml file"), but that justification is not sourced to any AC or scope.md line. Attack directly: is "plain text, not MIME" a defensible reading of "one example email file," or is this a spec/intent gap that should have blocked implementation rather than being resolved by the implementer's own comment?

4. **The `Owner:` line convention is parsed by exact-prefix string match** (`body.startswith("Owner: ")`) off `artifact.body`, coupling this story to `pipeline/extraction.py`'s current, unversioned text convention rather than a structured column. Assumption: this is the only place an assignee is recorded today (confirmed true as of this story), so there was no structured alternative. Attack: what happens, silently, the moment that convention's exact string shape changes upstream (case, wording, or removal) — does the digest fail loudly, or does every action item just quietly render "Unassigned"?

## History / regression context

- `story/4-5` was rebased onto `main` once (`72d49bb`) after this story's own review-workflow pass and before this handoff was filed, to keep the reviewed range the range that lands (`main` had advanced 14 commits — story 3-4 landing plus sprint docs — none touching this story's files). The rebase carried every commit's content forward unchanged, only SHAs moved; it is not a dropped variant or a superseded baseline. Every commit in the review range was authored in one unattended build run. There is no pre-existing condition to distinguish from a regression here; anything wrong in the reviewed files was introduced by this range.
- One unrelated, non-reproducing flake was observed mid-run during a full `pytest tests/` pass: `test_parallel_store_safety.py::test_projection_lock_times_out_with_holder_details_then_releases` timed out because a concurrent worktree (`4-3`) held the cross-worktree projection lock at that moment (confirmed via `ps aux` during that run). A second full run, after the patch commit, was clean. The `digest` module makes no calls into the projections module and cannot itself cause that test to fail — if you see it fail again, it is store contention from a sibling worktree, not this story.

## Verification baseline

Commands and their last confirmed results (all run from `server/` unless noted):

- `uv run pytest tests/test_digest_generator.py -q` — 8 passed, store-free.
- `uv run pytest tests/test_digest.py -q` — 6 passed, store-backed (per-run test database).
- `uv run pytest tests/ -q` — 1456 passed (full suite, post-patch run; see History note above on the one pre-patch flake).
- `make web-test` (from repo root) — 157 passed across 9 files, unaffected as expected (no `web/` changes in this story).
- Manual smoke test against the real dev Postgres, read-only: `digest --output <path>` with no published artifacts yet → exit 0, wrote "No artifacts are published yet."; `digest` with no `--output` → exit 2 with `fatal: digest aborted: --output PATH is required`.

If any of the commands above behave differently when you run them, or a command in the spec's own `## Verification` section fails, that is itself a finding — do not silently re-run past it or treat a skip as a pass.

---

This handoff is ready. Hand it to the Codex `bmad-code-review` agent to
produce `_bmad-output/implementation-artifacts/review-story-4-5-2026-08-20.md`.
