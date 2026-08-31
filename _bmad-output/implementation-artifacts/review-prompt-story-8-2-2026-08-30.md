# Reviewer handoff — Story 8.2: Persisted Selection

## What you must produce, before anything else

**Write your report to
`_bmad-output/implementation-artifacts/review-story-8-2-2026-08-30.md`.**

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
`story/8-2-review`, cut from `story/8-2`, in your own worktree
(`make worktree STORY=8-2-review` from the main checkout — never the main
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
  `../meetingminer-wt/8-2`, branch `story/8-2`.
- Review range: `ea0c113..HEAD` (`ea0c113` is `main` at the time the branch was
  cut). Every commit in the range belongs to this story; none belongs to another.

Commits, oldest first:

| Revision | Subject |
|---|---|
| `a85fddd` | spec: story 8.2 persisted selection (ready-for-dev) |
| `ca9689a` | fix(8-2): fail loudly when a provider does not serve the model (B-38) |
| `b6a24c1` | feat(8-2): app_setting table and the one role-resolution rule |
| `4fd780c` | feat(8-2): serve the catalog and persist a per-role selection |
| `a4c7a04` | test(8-2): register the settings router in the pinned baseline order |
| `6557d9d` | feat(8-2): resolve the selection per chat request and per worker job |
| `b312e27` | feat(8-2): record the effective binding in the eval run snapshot |
| `837c646` | docs(8-2): close B-38, and regenerate the typed client |
| `6026045` | fix(8-2): keep the litellm stub in sync, and stop the SDK leaking .env |

(Plus the closing documentation commit that carries this file, the spec's final
state, and the sprint keys.)

## The spec, and which half is frozen

`_bmad-output/implementation-artifacts/spec-8-2-persisted-selection.md`.

- **Frozen intent** — everything inside `<intent-contract>`: Intent, Boundaries &
  Constraints, and the I/O & Edge-Case Matrix. A finding rooted here is reported
  and left open for the owner, never patched.
- **Planner work you may attack freely** — the Code Map, Tasks & Acceptance,
  Design Notes, the Spec Change Log, and every implementation choice below.

## Architecture authority

- **AD-10** (`docs/architecture.md`) — one config file declares every adapter
  binding; story 8.1 amended it so a user's selection is user-declared data in
  Postgres, resolved at call time by api and worker, recorded in every eval run's
  snapshot beside the file values, bounded by the catalog, and never a fallback.
  This story implements those clauses. **Check the implementation against that
  wording, not against this prompt.**
- **AD-8** — model interaction is expressed only through the `Llm` port; no
  provider SDK in feature code. The new `LlmModelNotServedError` and its mapping
  live behind that port.
- **AD-5** — table ownership is disjoint. `app_setting` is api-owned: only
  `api/settings.py` writes it, and the worker only reads it.
- **AD-16** — the eval harness is a client, never a housemate. This is why the
  effective binding is read from `GET /settings/models` rather than from
  Postgres, and it is worth checking that the choice actually holds.
- **AD-4 / AD-6 / AD-15** — unchanged by this story, but `api/chat.py` was
  edited; confirm the citation and single-writer properties still hold.

## Scope

**In scope** — the files this story touched:

- `server/meetingminer/migrations/0016_app_setting.sql` (new)
- `server/meetingminer/domain/model_selection.py` (new)
- `server/meetingminer/api/settings.py` (new)
- `server/meetingminer/adapters/llm/port.py`, `litellm.py`, `__init__.py`
- `server/meetingminer/api/chat.py`
- `server/meetingminer/pipeline/stages/extract.py`
- `evals/harness/run.py`, `evals/conftest.py`
- `server/tests/test_settings_resolution.py` (new),
  `server/tests/test_api_settings.py` (new),
  `evals/tests/test_run_effective_bindings.py` (new)
- Three footprint extensions, each with its reason in the spec's change log:
  `server/tests/test_api_registry.py` (one name in `BASELINE_ROUTER_ORDER`),
  `server/tests/test_extraction_core.py` (one name in the `litellm` stub),
  `evals/tests/test_harness_boundary.py` (one name in the httpx allowlist)
- `web/src/client/` (regenerated), `docs/backlog.md` (B-38 closed)

**Out of scope** — do not report as gaps:

- The status surface showing provider key health and the active binding per role
  (**story 8.2a**), and the picker UI (**story 8.3**). `api/status.py` and web
  feature code are deliberately untouched.
- `config.py`'s catalog model and `domain/model_providers.py` — story 8.1 owns
  both; this story consumes them.
- Everything already recorded in the spec's `deferred:` frontmatter.
- Vendored trees and `web/src/client/`'s generated content (review the fact that
  it was regenerated, not its diff line by line).

## The design decisions to attack

Each is a choice plus the assumption under it. The planner is not a neutral judge
of its own calls, so these are handed over rather than left to be rediscovered.

1. **A stale selection falls back to the file's `default` instead of refusing.**
   Assumption: an operator editing `config.yaml`'s catalog must not turn every
   chat request into an outage, and reporting the discard (`staleSelection`,
   `staleReason`, a `llm.selection_stale` log event) makes it non-silent. Attack:
   is a *reported* discard still the silent fallback the owner rejected? The
   counter-argument is in the Design Notes; decide whether it holds.
2. **502, not 503, for `binding-failed`.** Assumption: 503 promises that retrying
   may work, and a provider that does not serve a model will answer identically
   forever. Attack: whether the UI and the eval harness treat 502 sensibly, and
   whether the two existing chat slugs (`chat-model-unavailable`,
   `chat-model-unusable`) should have been folded into the new type instead of
   kept beside it.
3. **`binding` in the problem body is the model tag, not the config path.**
   Assumption: epic 8's own vocabulary (8.1's `CatalogEntry.binding`) makes a
   binding a model tag, and AC3 pairs it with `provider`. But chat's two existing
   problems use `binding="llm.roles.chat"`. One api now spells `binding` two
   ways. Attack this; it is the weakest naming call in the story.
4. **The role's `base_url` still applies to a selected binding.** Assumption: the
   selection replaces the role's *primary model*, not the role, and dropping the
   endpoint would silently re-route to `providers.<prefix>.base_url`. The known
   hazard — an endpoint that does not serve the newly selected tag — is
   converted into a named call-time refusal by B-38. Attack whether that is
   adequate, especially for `llm.roles.extraction`, whose `base_url` points at a
   host chosen for one specific model.
5. **The role's `fallback` is still unbounded by the catalog.** An outage
   substitutes a model no picker ever offered. Deliberate for outages; recorded
   as deferred. Attack whether it belongs in this story.
6. **`app_setting` is a generic key/value table.** Assumption: settings are few
   and scalar, and a typed table per setting means a migration per setting. The
   cost is that no constraint can tell a valid binding from a typo — the catalog
   check lives in the api and the resolver instead. Attack the trade.
7. **The eval harness reads the effective binding over HTTP.** Assumption: AD-16
   makes it a client, and this avoided widening the AD-16 import allowlist. The
   cost is that a run started without `--api-base-url`, or against a down api,
   records a named problem instead of the binding. Attack whether a run whose
   provenance is that incomplete should still be allowed to proceed — the story
   deliberately does **not** fail such a run, on the grounds that verdict
   semantics are not its question.
8. **Chat's resolution shares the connection its no-evidence guard already
   holds.** Attack the transaction and pool implications.

## History you need to tell a regression from a pre-existing condition

- **No rebase.** The branch was cut from `ea0c113` and never rebased; the range
  is the range that lands.
- **`0015` is story 10.2's**, which is in review and lands first. This story
  deliberately takes `0016`.
- **Story 8.1 landed today** and is the immediate baseline: `config.yaml` gained
  per-role `catalog[]`/`default`, and `domain/model_providers.py` became the
  single provider-spelling rule that `api/status.py` aliases. B-38 was *filed* by
  8.1's review as out of its boundary, and is closed by this story.
- **`run.note(...)` was tried and withdrawn.** The first eval implementation
  noted an unreadable effective binding as a run problem, which fails the run and
  broke five existing `evals/tests` cases. Its absence now is a decision, not an
  oversight — see the change log.
- **Two pre-existing skips** appear in every run and are not this story's:
  `test_diarize_pyannote.py` (no `pyannote` in the venv) and `test_youtube.py`
  (opt-in network case).

## Verification baseline

Run these; a skip or failure that is not listed here is a finding, not noise.

- `uv run --project server pytest server/tests/test_settings_resolution.py server/tests/test_api_settings.py -q`
  — **26 passed**. Every test was observed failing against unfixed code first.
- `uv run --project server pytest evals/tests -q` — **655 passed**.
- `make lint` — **All checks passed** (the dated ruff baseline was not widened).
- `make typecheck` — **Success: no issues found in 13 source files.**
- `make web-test` — **294 passed** in 16 files.
- `make test-fast` — **1988 passed, 2 skipped, 378 deselected**; both skips are
  the pre-existing named ones above.
- `make test` — the full gate. Run 2026-08-30 on `6026045`: **2366 passed,
  2 skipped** in 625.67s, followed by the web production build; exit code 0.
  Re-run it yourself before you close.
- `python3 _bmad/scripts/branch_conflicts.py --against story/8-2` — **no code
  file conflicts with `main`.** Two conflict classes remain, both characterised
  in the spec's change log and both for `integrate`: `web/src/client/*` against
  `story/7-3` (both stories add an api operation and regenerate the committed
  client — resolved by regenerating once after the merge, never by hand-merging
  either diff), and `sprint-notes.md` against `main` and every other `story/*`
  branch (no merge driver; `main x story/10-2` conflicts on it independently of
  this branch).

The stack is this worktree's own (compose project `meetingminer-8-2`); bring it
up with `make infra-up` in your review worktree before the store-backed suites.
