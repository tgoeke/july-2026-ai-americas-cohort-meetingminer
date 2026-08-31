# Reviewer handoff — Story 8.2a: Provider Health on the Status Surface

## What you must produce, before anything else

**Write your report to
`_bmad-output/implementation-artifacts/review-story-8-2a-2026-08-31.md`.**

**REPORT-FIRST — do this before you read a single line of code.** Create that
file as a skeleton (scope, review range, an empty findings section), and commit
it. Then append each finding as you confirm it and commit incrementally. Four
reviews in this repository were completed in a terminal and never filed, every
one written report-last; a crashed or closed session must lose prose, never the
artifact.

Each finding takes this structure:

- **Location** — `path:line`
- **Severity** — low / medium / high
- **Finding** — what is wrong
- **Evidence** — what you ran or read that shows it
- **Suggested direction** — not a patch, a direction

**The review lane applies its own patch findings.** This is the repository's
convention, corrected by owner ruling on 2026-08-30. Report every finding in the
report file first, then **fix the patchable ones yourself** on branch
`story/8-2a-review`, cut from `story/8-2a`, in your own worktree
(`make worktree STORY=8-2a-review` from the main checkout — never the main
checkout itself). Fix **red-first**: write the test, observe it failing against
the unfixed code, then the fix, then green. Commit each fix with its finding
number. You hand nothing back to a builder.

What you must **not** fix: anything needing an owner decision, and anything whose
root cause is the frozen `<intent-contract>` in the spec. Report those, mark them
clearly **open**, and leave them for the owner. Never commit to `main`, never
work in the main checkout, and never merge — the owner runs `integrate`.

**Closeout.** Before you report completion, run `make check-reviews` (it fails
while any dispatched review lacks a committed report, including this one) and
state the SHA carrying your report's final version. A review reported in the
terminal but not filed does not exist.

---

## Repo, branch, range

- Repo: `/Users/devopsterus/current/cohort/meetingminer`, worktree
  `../meetingminer-wt/8-2a`, branch `story/8-2a`.
- Review range: `9fc760fe..HEAD` (`9fc760fe` is `main` at the time the branch
  was cut). Every commit in the range belongs to this story.
- **No rebase.** The branch was cut from `9fc760fe` and never rebased; the
  reviewed range is the range that lands.

`git log --oneline 9fc760fe..story/8-2a` is the authority.

## Do not run these

- **Never `make evals-run`.** Never start the shared api or worker: a corpus
  ingest was running on the main stack while this story was built, and the api
  and web ports are still fixed across checkouts (B-35).
- **Never call a paid model.** This story's whole probe contract is free
  endpoints; a review that spends money contradicts what it is reviewing.
- The TS client was regenerated **without** starting an api: the schema was
  dumped from `meetingminer.api.main.app.openapi()` into a temp file and
  `pnpm --dir web run client -i <file>` was run against it. Two artefacts of
  generating from a file rather than a URL were reverted by hand —
  `client.gen.ts` (which lost its `baseUrl`) and the `ClientOptions.baseUrl`
  literal in `types.gen.ts`. **Check that the committed client is exactly what a
  live-api `make client` would produce apart from this story's additions.**

## The spec, and which half is frozen

`_bmad-output/implementation-artifacts/spec-8-2a-provider-health-on-the-status-surface.md`.

- **Frozen intent** — everything inside `<intent-contract>`: Intent, Boundaries
  & Constraints, and the I/O & Edge-Case Matrix. A finding rooted here is
  reported and left open for the owner, never patched.
- **Everything else** — the Code Map, Verification, the Spec Change Log, and
  every implementation choice below is fair game.

## Architecture authority

- **AD-10 as amended 2026-08-31** — the model *catalog* is a process-start
  snapshot (`api/main.py` holds `CONFIG = _load_or_die()` at module level) while
  a *selection* is a per-request `app_setting` read
  (`domain/model_selection.py`). The api and the worker hold independent
  snapshots. **Check the implementation against that wording, not against this
  prompt.** Note that the amendment lived only in
  `_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md`
  (commit `91432022`); this story copied it into `docs/architecture.md`, which
  had been out of sync on exactly the paragraph the third criterion rests on.
  **Verify the two documents now say the same thing.**
- **AD-18** — degradation is never silent, and a surface that reports a state
  the system is not in is an AD-18 violation. That is the whole reason the
  attribution fields exist.
- **AD-5** — `app_setting` is api-owned. This story only reads it.
- **AD-8** — no provider SDK in feature code. The probes are plain `httpx.get`
  against list endpoints, which is the same posture `api/status.py` already had.

## Scope

**In scope** — the files this story touched:

- `server/meetingminer/api/status.py` (the bulk of it)
- `server/meetingminer/api/main.py` (two additions: `CONFIG_LOADED_AT` and its
  `app.state` binding)
- `server/tests/test_api_status.py` (14 tests before, 25 after)
- `docs/architecture.md` (AD-10 amendment), `docs/backlog.md` (B-42 closed,
  B-52 filed, the duplicate-B-42 note)
- `web/src/features/status/` — `status.ts`, `StatusPage.tsx`,
  `StatusIndicator.tsx`, `status.test.tsx`
- `web/src/features/settings/models.ts` and `models.test.ts`
- Fixture-only edits so the payloads type-check as payloads the api can emit:
  `ModelRoles.test.tsx`, `ModelSelect.test.tsx`,
  `ModelSettingsIntegration.test.tsx`
- `web/src/client/index.ts`, `web/src/client/types.gen.ts` (regenerated)

**Out of scope** — do not report as gaps:

- `App.tsx`, the chrome, `ChatPanel`, `CorpusSearch` (story 10.5) and
  `web/src/features/threads/` (story 10.6) were in flight and are untouched, as
  are `ModelSelect.tsx` and `SettingsPage.tsx` (story 10.5's review branch).
  The chrome indicator gets provider rows through `degradedRows()` precisely so
  no component another story owns had to change.
- `_bmad-output/implementation-artifacts/sprint-notes.md` was deliberately not
  written: `main × story/10-5`, `× story/10-6` and `× story/7-4` already
  conflict on that one file, and adding a third region would have turned a
  two-way conflict into a three-way one for the integrator. Say if you disagree.
- Everything in the spec's `deferred:` frontmatter (B-52, the duplicate B-42).
- `domain/model_selection.py`, `api/settings.py` and `config.py` — stories 8.1
  and 8.2 own them; this story consumes them and adds nothing to them.

## The design decisions to attack

Each is a choice plus the assumption under it. The builder is not a neutral
judge of its own calls, so these are handed over rather than left to be
rediscovered.

1. **`LlmRoleStatus.model` now means the binding in force, not the file's
   `model`.** Assumption: the field's whole job is "which model will this role
   call", and probing the file's model while a selection points elsewhere
   reports the health of a binding no call will use. The cost is that a field's
   meaning changed without its name changing, and `fileBinding` now carries the
   old value. Attack whether the rename should have been explicit.
2. **`ProviderStatus` carries `state` and `observedBy` beyond the four fields
   the acceptance criterion names.** Assumption: a reader deriving health from
   `remediation != null` is one wording change from being wrong, and attribution
   is required by the third criterion. Attack whether that is a superset the
   criterion permits, or a contract change that needs the owner.
3. **A discarded stale selection makes the role row `degraded`.** Assumption:
   the story's own goal line is "a bad key or a wrong selection is visible
   before I ask anything", and a choice that is not in force is exactly that.
   The counter-argument is that nothing is broken — the file default serves
   fine — and that this makes the surface amber for a condition the owner may
   consider normal. Attack it.
4. **Postgres down makes `source: "unknown"` rather than showing the file
   default as in force.** Assumption: AD-18 forbids claiming a state that cannot
   be supported. The cost is a second degraded signal for one outage the store
   row already reports. Attack whether the row should instead be silent about
   the binding entirely.
5. **`providers[]` covers every declared provider, including ones no role
   binds, and every provider row feeds the `overall` roll-up.** Consequence:
   `providers.ollama` at `http://localhost:11434` being down turns the surface
   amber even when no role uses that endpoint — though the embedder does
   resolve through it (`adapters/embed`). Attack whether that roll-up is right,
   and whether the embedder dependency makes it right for the wrong reason.
6. **`api/status.py` imports `SETTINGS_ROLE_POLICY` from `api/settings.py`.**
   Assumption: which roles adopt a persisted selection is one policy, and a
   second list in status is the drift story 8.1 spent a story removing. The cost
   is a router importing a router. Attack whether the table should move to
   `domain/`.
7. **The attribution is prose in the payload, not structure.** `attribution` is
   a server-authored sentence; the client renders it verbatim. Assumption: the
   wording is the contract (the incident was a wording failure), and a client
   that composes its own sentence can compose a wrong one. The cost is that
   sentence is untranslatable and untestable except by exact-match, which is how
   `test_every_reading_is_attributed_to_the_process_that_answered` pins it.
   Attack the trade.
8. **`CONFIG_LOADED_AT` is taken in `api/main.py` at module level, next to
   `CONFIG`.** It is the closest honest instant available. Attack whether
   `load_config` should stamp it instead, so the worker gets it for free when
   B-52 is built.
9. **The banned-wording test is a phrase list.** `test_no_wording_anywhere_speaks_for_the_whole_system`
   bans eight phrases across every role and provider sentence. A list cannot
   reject an unlisted way of speaking for both processes. The verbatim
   disclaimer pin on the extraction row is the stronger half. Attack whether
   the pair is enough.

## History you need to tell a regression from a pre-existing condition

- **Story 8.3 landed today** and already renders per-role model health in the
  ask popover and settings. This story extended `providerHealthIndex` rather
  than adding a second join, and deleted the comment in `models.ts` that
  predicted it ("Story 8.2a will serve `providers[]` directly; until it
  lands…"). B-42 was filed by 8.3 for exactly this and is closed here.
- **`docs/backlog.md` has two entries numbered `B-42`** — 8.3's provider-health
  item and 10.3/10.4's media-route item, filed the same day in parallel
  branches. Recorded in the file, not renumbered, because landed specs already
  reference the id.
- **`B-52` was allocated against main's highest id at cut time (`B-51`).**
  `story/10-6` is in flight carrying entries numbered `B-44` and `B-45`, which
  already collide with main's existing B-44/B-45; whoever lands 10-6 has to
  renumber and should check that the renumbering does not land on B-52.
- **Three skips appear in every run and are not this story's**, all opt-in:
  `test_youtube.py:1353` (`MM_YOUTUBE_NETWORK_TEST`),
  `test_diarize_pyannote.py:266` (no `pyannote` in the venv), and
  `test_diarize_remote.py:774` (`MM_DIARIZE_REMOTE_NETWORK_TEST`, the LAN GPU
  host started by hand).

## Verification baseline

Run these; a skip or failure that is not listed here is a finding, not noise.

- `make lint` — All checks passed.
- `make typecheck` — Success: no issues found in 13 source files.
- `uv run --project server pytest -m "" server/tests/test_api_status.py -q` —
  **25 passed** (14 before this story).
- `make web-test` — **24 files, 453 tests, all passing**.
- `pnpm --dir web exec tsc -b` — clean. `pnpm --dir web run lint` — five
  pre-existing `only-export-components` warnings, none in this story's files.
- `make test` — **2737 passed, 3 skipped**, 710s (11m50s), exit 0. The web
  production build (`tsc -b && vite build`) is part of that target and is clean.
- `python3 _bmad/scripts/branch_conflicts.py --against story/8-2a` — 6 clean
  pairs, 15 conflicting. Against the in-flight web stories the only conflicts
  are `sprint-notes.md` (10-5, 10-6) and `docs/backlog.md` (10-6), both of
  which `main` already conflicts with; **no source file this story touched
  conflicts with `story/10-5`, `story/10-5-review`, `story/10-6` or
  `story/10-6-review`.** The one genuinely new conflict is
  `story/8-2a × story/12-1` on `web/src/client/index.ts`: both branches
  regenerated the client, and the resolution on landing is to regenerate again
  rather than to merge the generated line. Conflicts against `story/7-4`,
  `story/8-3`, `story/10-3` and `story/10-4` are stale-branch noise — `main`
  conflicts with each of them identically, because those stories have landed and
  their branches were not deleted.

## Where to look hardest

The third acceptance criterion is the one that carries risk, and it comes from a
real incident on 2026-08-31. The question is not "does the payload have an
attribution field" — it does. The question is whether a reader of any surface
this story produces could still come away believing that what they read
describes the worker. Read `_role_attribution`, the two note constants,
`attributionLine`, `sourceLabel`, and every sentence `StatusPage.tsx` and
`StatusIndicator.tsx` render, asking that one question. If any of them can be
read as a statement about the system rather than about the api process, that is
a high-severity finding regardless of what the tests say.
