# Review handoff — Story 2-6: Source-drop schema reloaded on change

Hand this file to the Codex `bmad-code-review` agent. It is self-contained; the
reviewer has none of the build run's context.

## Repo, branch, range

- Repo: `/Users/devopsterus/current/cohort/meetingminer` (build ran in worktree
  `/Users/devopsterus/current/cohort/meetingminer-wt/2-6`; the branch is pushed,
  so either checkout works).
- Branch: `story/2-6` (tracking `origin/story/2-6`, in sync).
- Review range: `444469d..4a7d4c7` (5 implementation commits; the handoff
  itself was added afterwards in `75878be`):
  - `0513c61` docs(2-6): plan source-drop schema reload spec
  - `abd8f66` fix(ingests): reload source-drop schema on change, fail closed when unloadable
  - `e2976de` docs(2-6): mark spec in-progress with baseline revision
  - `fb30af1` test(2-6): cover the startup schema gate in the fail-fast suite
  - `4a7d4c7` fix(2-6): apply review patches to the schema reload path

No commit in the range belongs to another story.

## Spec and intent authority

- Spec: `_bmad-output/implementation-artifacts/spec-2-6-source-drop-schema-reloaded-on-change.md`.
- The `<intent-contract>` block is frozen intent, derived from the story's
  actual contract: the `deferred-work.md` entry filed as
  `2-6-source-drop-schema-reloaded-on-change` (this story is **not in
  `epics.md`** — the id was minted into `sprint-status.yaml` when the defect was
  found in operation on 2026-08-19; there are no epic-level ACs to consult).
  Everything outside `<intent-contract>` (Code Map, Design Notes, tasks) is
  planner work the reviewer may critique.

## Architecture authority

- AD-1 (source-drop contract: `docs/source-drop.schema.json` is the intake
  contract) — this story changes *when* the api reads it, never its content.
- Finding 17 (schema anchored to `config.config_path.parent`, never
  `__file__`/cwd re-resolution) — `drop_schema_path()` is deliberately
  untouched; the known environment-dependence of which copy gets resolved is a
  separately filed deferred-work item (`docs_root()` entry), out of scope here.
- RFC 9457 problem convention (`api/problems.py`): every error body is
  `application/problem+json` with `urn:meetingminer:problem:<slug>` types.
- NFR17 structured logging: one JSON line per event via `meetingminer.logs`.

## Scope

In scope (the only files the story changed):
- `server/meetingminer/api/ingests.py`
- `server/tests/test_ingests.py`
- `server/tests/test_failfast.py`
- `_bmad-output/implementation-artifacts/spec-2-6-source-drop-schema-reloaded-on-change.md`

Out of scope: the worker's per-call schema read (`domain/drops.py:read_drop`,
already never stale), `mintdrop.py`, `api/main.py` (deliberately untouched —
`load_drop_schema(CONFIG)`'s call site and signature are unchanged),
`docs/source-drop.schema.json` itself, the `docs_root()` environment-dependence
deferred item, and any filesystem-watcher approach (spec forbids it:
poll-on-request only).

## Design decisions to attack

Each is the planner's call plus the assumption it rests on:

1. **Reload-on-change over fail-closed-only.** Assumes the sprint id naming
   the reload selects the "fuller fix" reading of the deferred-work entry, and
   that reload subsumes the minimum log-line fix.
2. **Fail closed as `500 drop-schema-unreadable` (not 503, not 422) when the
   schema cannot be loaded.** Assumes the incident's expensive property was a
   process fault presenting as a bad drop, and that the `drops-root-unconfigured`
   500 precedent covers "config unavailable on the api process."
3. **Stat signature `(st_mtime_ns, st_size, st_ino)` with no locking.**
   Assumes a module-global tuple swap is atomic in CPython, duplicate rebuilds
   are harmless, and the one undetectable case (in-place same-size write with a
   deliberately preserved mtime, same inode) is acceptable rather than paying a
   content hash per request. The limitation is documented in `_validator()`.
4. **The 500 detail names the absolute schema path.** Mandated by the
   intent-contract ("naming the schema file"); assumes a trusted-operator API.
5. **`schemaId` (`$id`) + `mtimeNs` as the load event's identity.** Assumes
   `$id` plus exact mtime is enough to tell copies apart; two edits keeping the
   same `$id` are distinguished only by mtime/size.
6. **Tests exercise the module surface via `TestClient` with a monkeypatched
   temp schema path**, not a real process editing the config-resolved file.
   Assumes the house TestClient convention plus the subprocess boot-gate tests
   cover the operational behavior; no test crosses a process boundary for the
   reload itself.

## History the reviewer needs

- Baseline `444469d` is current `main`. `0513c61` is spec-only; `abd8f66` is
  the core change; `fb30af1` and `4a7d4c7` came out of the build run's own
  four-layer review (7 patch findings applied, 11 rejected, 0 deferred — see
  the spec's Review Triage Log). `followup_review_recommended: true` was set
  by score (4 medium + 3 low patches), which is why this review exists.
- Pre-existing behavior kept deliberately: the startup fatal message text
  (`fatal: api startup aborted: source-drop schema unreadable: <path>: ...`),
  and `load_drop_schema`'s call site. New in the range: `load_drop_schema`
  now returns `None` (its schema-dict return was dead plumbing — verified no
  consumer), and `check_schema` now runs at load, adding
  `jsonschema.SchemaError` as a boot-abort cause that did not exist before.

## Verification baseline

Run from the repo root (store-backed; per-run Postgres database per AGENTS.md
story 2.7 — safe to run while other suites run):

- `uv run --project server pytest server/tests/test_ingests.py server/tests/test_drop_schema.py -q` → **86 passed** at `4a7d4c7`.
- `uv run --project server pytest server/tests/test_failfast.py -q` → **10 passed** at `4a7d4c7`.

Any skip or failure against these counts is a finding, not noise.

## Required output

Write findings (do not apply fixes) to
`_bmad-output/implementation-artifacts/review-story-2-6-2026-08-20.md`, with:
severity-ranked findings (file:line, claim, evidence, suggested action),
explicit verification of the baseline commands above with observed counts, and
a closing verdict (pass / pass-with-findings / fail).
