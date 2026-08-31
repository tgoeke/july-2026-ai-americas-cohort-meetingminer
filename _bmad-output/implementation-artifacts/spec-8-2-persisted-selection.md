---
title: 'Story 8.2: Persisted Selection'
type: 'feature'
created: '2026-08-30'
status: 'review'
review_loop_iteration: 0
followup_review_recommended: false
context: ['AGENTS.md', '_bmad-output/implementation-artifacts/wave-2026-08-30-rules.md', '_bmad-output/implementation-artifacts/build-prompt-story-8-2-2026-08-30.md']
warnings: ['oversized', 'multiple-goals']
deferred:
  - summary: >-
      Importing `litellm` injects the repository's real `.env` into
      `os.environ` for the rest of the process.
    evidence: |-
      `import litellm` (1.97.0) calls `load_dotenv()` at import time. Measured
      here: with `POSTGRES_PASSWORD` absent from the process environment, it is
      present immediately after the import, and that was enough to make
      `test_config.py::test_merged_env_precedence_is_env_then_worktree_then_process`
      and `..._worktree_env_file_is_found_beside_the_env_path_not_its_target`
      read the developer's real password instead of their fixture's. This story
      contained it inside its own module-scoped fixture, which restores the
      environment it found. Nothing stops the next module that imports the SDK
      from reintroducing it, and no guard names the hazard. A session-scoped
      autouse guard in `server/tests/conftest.py` would close it, which is a
      file this wave forbids editing.
    location: >-
      server/tests/test_settings_resolution.py - litellm_sdk fixture
    severity: medium
  - summary: >-
      `domain/model_selection.py` is outside the mypy scope.
    evidence: |-
      `[tool.mypy] files` in `server/pyproject.toml` lists the decision-core
      modules and is pinned by `tests/test_lint_contract.py`; story 11.4 owns
      both. `domain/model_providers.py` was left out for the same reason in
      story 8.1, so the two halves of the model-binding rule are consistently
      unchecked. Widening the list is a one-line edit in a file another lane
      owns this wave.
    location: >-
      server/pyproject.toml - [tool.mypy] files
    severity: low
  - summary: >-
      A role's `fallback` tag is still not bounded by the catalog.
    evidence: |-
      Inherited from story 8.1's deferred list and unchanged here. A selection
      is now bounded by the catalog on write and on read, but
      `llm.roles.<role>.fallback` remains a live model tag that need not be a
      catalog binding and whose provider is never checked against `providers:`.
      An outage therefore still substitutes a model no picker ever offered —
      deliberate for outages, but the *choice* of substitute is unbounded.
    location: >-
      server/meetingminer/config.py - LlmRoleBinding.fallback
    severity: medium
baseline_revision: 'a85fddd186953bf89eca2a65b2afe8a5de70a4eb'
---

<intent-contract>

## Intent

**Problem:** Story 8.1 made `config.yaml` declare a per-role `catalog[]` and `default`, but
the declaration is inert: every call path still reads the role's `model`, nothing persists a
user's pick, and no api surface serves the catalog. A selector built on this today would be
decorative. Separately (backlog B-38), a provider that does not serve the configured model
raises a generic `LlmError` that `FallbackLlm` absorbs — so a wrong binding is answered by a
*different* model, silently. FR38, FR39.

**Approach:** Add an api-owned `app_setting` table and two routes — `PUT /settings/roles/{role}`
and `GET /settings/models` — that persist and serve a per-role binding selection bounded by
that role's catalog. Chat resolves the selection per request and the worker per job, both
through one shared rule that derives provider identity from story 8.1's
`provider_for_model` and re-checks catalog membership on read. A binding that the provider
does not serve becomes its own configuration-shaped port error, excluded from fallback, and
surfaces at the point of use as RFC 9457 `urn:meetingminer:problem:binding-failed`. The eval
run's config snapshot records the effective binding beside the file value.

## Boundaries & Constraints

**Always:**
- **One rule.** Provider identity comes from `domain/model_providers.provider_for_model` and
  nothing else. Catalog membership is decided by one function used by both the write path and
  the read path; no second copy in the api, the worker, or the eval harness.
- **Never outside the catalog.** A `PUT` naming a binding absent from that role's catalog is
  refused and nothing is written. A stored selection is re-checked on every read, because
  `config.yaml` can change under it.
- **No substitution.** When the selected binding fails because the provider does not serve it,
  the failure propagates: `FallbackLlm` re-raises without calling the fallback, and the point
  of use names the provider, the binding, and the upstream status. This is the owner's
  standing rule, not a preference.
- **Genuine outages keep today's fallback.** `LlmUnavailableError` (unreachable host, timeout,
  refused credentials) still engages the role's configured fallback, unchanged.
- **Nothing degrades quietly.** A stored selection the catalog no longer offers is discarded in
  favour of the role's `default`, and that discard is named in the `GET /settings/models`
  payload and in a log event. It is never applied and never hidden.
- **Table ownership is disjoint (AD-5).** The api owns `app_setting` and writes it; the worker
  only reads it.
- **The footprint is a contract.** Six other lanes are in flight; every push is measured with
  `python3 _bmad/scripts/branch_conflicts.py --against story/8-2`. A conflict outside
  `_bmad-output/` narrows *this* story's edit and is recorded in the Spec Change Log.

**Block If:**
- Closing B-38 would require changing `LlmUnavailableError`'s fallback behaviour. (It does not:
  the new error is a distinct type on a distinct SDK exception.)

**Never:**
- No status-surface row for the active binding and no provider key probing (story 8.2a); no
  picker UI or web feature code (story 8.3) beyond regenerating `web/src/client/`.
- No edit to `config.py`'s catalog model, `domain/model_providers.py`, `config.yaml`,
  `api/status.py`, `api/config_view.py`, `server/tests/conftest.py`, `infra/Makefile`,
  `AGENTS.md`, `project-context.md`, or `docs/architecture.md` — other lanes own those.
- Never append to an existing server test module; both new test modules are new files.
- No migration number other than `0016` (story 10.2 owns `0015`).
- No hand-edit of `web/src/client/`, and no running api or worker to regenerate it.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Persist a selection | `PUT /settings/roles/chat {"binding": "<second catalog binding>"}` | 200; row written to `app_setting`; the response's `effectiveBinding` is the new binding with `source: "selection"` | No error expected |
| Serve catalog + selection | `GET /settings/models` after that PUT | 200; every role listed with its catalog, `fileBinding`, `default`, `selected`, `effectiveBinding`, `provider`, `source` | No error expected |
| Binding outside the catalog | `PUT /settings/roles/chat {"binding": "openai/gpt-9"}` | Refused; nothing written | 422 `urn:meetingminer:problem:binding-not-in-catalog`, detail names role, binding, and every catalog binding |
| Unknown role | `PUT /settings/roles/nope` | Refused | 404 `urn:meetingminer:problem:unknown-role`, detail names the known roles |
| No selection stored | fresh database | Every role resolves to its `default` with `source: "file-default"`, `selected: null` | No error expected |
| Catalog changed under a stored selection | stored `chat` selection no longer in the catalog | Effective binding is the role's `default`; `staleSelection` names the discarded binding and why; `llm.selection_stale` is logged | Not applied, never silent |
| Chat resolves per request | selection changed between two `POST /chat` calls | The second question is classified and synthesized on the new binding without an api restart | No error expected |
| Worker resolves per job | selection changed between two extraction jobs | The second job's `extract` stage builds its completer on the new binding | No error expected |
| Provider does not serve the model | upstream answers 404 for the selected binding | `LlmModelNotServedError`, message beginning `provider '<p>' at '<endpoint>' does not serve model '<m>'`; the fallback is never called | Chat: 502 `urn:meetingminer:problem:binding-failed` with `provider`, `binding`, `role`, and the upstream status in `detail`. Worker: `StageError` carrying the same sentence |
| Genuine host outage | upstream unreachable / times out | Unchanged: `LlmUnavailableError`, the role's fallback engages, `fallback_engaged=True` | Chat keeps `chat-model-unavailable` (503) |
| Eval snapshot | a run created against a reachable api | `config-snapshot.yaml` carries `llm_bindings` — per role the file value and the effective binding, provider, and source | Api unreachable: the effective half is `null` with a named `problem`, recorded rather than guessed |

</intent-contract>

## Code Map

- `server/meetingminer/domain/model_providers.py:19` — `provider_for_model`. The single
  spelling rule. **Read only** (story 8.1 owns it); import it, never re-derive.
- `server/meetingminer/config.py:219` — `CatalogEntry` (`binding`, `label`, computed
  `provider`); `:268` `LlmRoleBinding` (`model`, `fallback`, `base_url`,
  `fallback_base_url`, `timeout_seconds`, `num_ctx`, `catalog`, `default`); `:409`
  `LlmRoles` (`extraction`, `chat`, `judge`). **Read only** — the role name set is derived
  from `LlmRoles.model_fields`, never hardcoded.
- `server/meetingminer/api/registry.py:63` — routers are auto-discovered by module-level
  `router`; `main.py` has no `include_router`. A new `api/settings.py` needs no edit anywhere
  else. `/settings/models` and `/settings/roles/{role}` have no parameterized sibling, so
  `DEFAULT_ROUTER_ORDER` is correct.
- `server/meetingminer/api/problems.py:52` — `Problem(status, slug, detail, title, **ext)`;
  `_STATUS_TITLES` has no 502, so `binding-failed` passes `title="Bad Gateway"` explicitly
  rather than editing that module.
- `server/meetingminer/api/chat.py:1136-1138` — `binding = config.settings.llm.roles.chat`
  then `build_llm(...)`. This is the per-request resolution point; `request.app.state.pool` is
  already in scope at `:1126`. `_complete` (`:1046`) maps port errors to problems and gains
  the `LlmModelNotServedError` branch.
- `server/meetingminer/pipeline/stages/extract.py:304-305` — the same two lines for the
  worker, inside the runner's transaction (`ctx.conn`). Per-job resolution goes here.
- `server/meetingminer/adapters/llm/port.py:25-33` — `LlmError` / `LlmUnavailableError`. The
  new `LlmModelNotServedError` subclasses `LlmError` so existing `except LlmError` callers
  (chat's `_complete`, extract's three `except LlmError` sites at `:253`, `:262`, `:270`)
  keep working.
- `server/meetingminer/adapters/llm/__init__.py:81-95` — `FallbackLlm.complete`'s
  `except LlmError` is what B-38 must not reach; a preceding re-raise clause is the fix.
  `build_llm` (`:112`) takes the structural `RoleBinding`, so a `model_copy(update=...)` of a
  pydantic role binding satisfies it unchanged.
- `server/meetingminer/adapters/llm/litellm.py:139-159` — the `except` tuple mapping SDK
  errors to `LlmUnavailableError`, then the generic `except Exception` at `:160`.
  `litellm.exceptions.NotFoundError` (litellm 1.97.0, an `APIStatusError` with `status_code`
  and `llm_provider`) currently falls into the generic branch; it gets its own branch
  **before** the generic one.
- `server/meetingminer/db.py:26` — `MIGRATIONS_DIR`; migrations are applied in filename order
  and `server/tests/conftest.py:400` applies them to a fresh per-run database, so `0016` is
  live in every store-backed test with no fixture edit.
- `server/meetingminer/migrations/0014_topics.sql:1-11` — the ownership-labelling convention
  (`WORKER-OWNED and MACHINE-DERIVED, and every reader must label them as such`). `0016`
  labels itself api-owned and user-declared the same way. `set_updated_at()` exists from
  `0001_jobs.sql:69`.
- `server/tests/conftest.py:435` — the `client` fixture injects `test_pool` and
  `app_config`; `:468` `EVIDENCE_TABLES` does **not** include `app_setting` and no test
  asserts that tuple is complete, so the new tests clean the table with their own
  module-local autouse fixture. **conftest.py is read only.**
- `evals/harness/run.py:255-289` — `Run.create(run_id, *, config, root, label, api_base_url)`
  writes `config-snapshot.yaml`; `resolved_settings` (`:216`) already emits each role's
  catalog through `model_dump`. The snapshot gains a sibling key, not a rewrite.
- `evals/harness/retrieval.py:116` — the harness idiom for an httpx call with an injectable
  `transport`, which is how the new api read is tested without a server.
- `evals/tests/test_harness_boundary.py:62` — `ALLOWED = ("meetingminer.config",
  "meetingminer.adapters.llm")`. Reading the effective binding over HTTP keeps the harness a
  client and leaves this guard untouched.
- `evals/conftest.py:189-207` — the session `run` fixture, which owns `--api-base-url`.
- `web/openapi-ts.config.ts` and `infra/Makefile:1139` — `pnpm --dir web run client -i <input>`
  accepts an input override, so the committed client is regenerated from a schema dumped
  in-process (`api.main.app.openapi()`), with no api started.
- `docs/backlog.md:156-179` — B-38, including the exact required message template.

## Tasks & Acceptance

**Execution:**
- `server/tests/test_settings_resolution.py` — NEW. Domain rules, per-request/per-job
  resolution, the adapter's model-not-served mapping, the composer's no-substitution
  guarantee, and the eval snapshot. Every test observed failing against unfixed code first.
- `server/tests/test_api_settings.py` — NEW. Both routes, both refusals, the stale-selection
  read, and chat's `binding-failed` surface. Module-local autouse fixture clears `app_setting`.
- `server/meetingminer/migrations/0016_app_setting.sql` — NEW. `app_setting (key text primary
  key, value text not null, updated_at)` with the api-owned/user-declared label and the
  `set_updated_at` trigger.
- `server/meetingminer/domain/model_selection.py` — NEW. `selection_key(role)`, the catalog
  membership check with its named error, `EffectiveBinding`, `resolve_effective_binding`, and
  the two SQL reads/writes over a structurally typed connection. Provider identity delegates
  to `provider_for_model`.
- `server/meetingminer/adapters/llm/port.py` — add `LlmModelNotServedError(LlmError)` carrying
  `provider`, `model`, `api_base`, `upstream_status`, documenting why it is excluded from
  fallback (B-38).
- `server/meetingminer/adapters/llm/litellm.py` — map `litellm.exceptions.NotFoundError` to it
  with B-38's message template, deriving the provider from the shared rule.
- `server/meetingminer/adapters/llm/__init__.py` — export it; `FallbackLlm.complete` re-raises
  it before the `except LlmError` that engages the fallback.
- `server/meetingminer/api/settings.py` — NEW. `GET /settings/models`, `PUT /settings/roles/{role}`.
- `server/meetingminer/api/chat.py` — resolve the chat role per request from the pool; map
  `LlmModelNotServedError` to the `binding-failed` problem.
- `server/meetingminer/pipeline/stages/extract.py` — resolve the extraction role per job from
  `ctx.conn`, and log the effective binding.
- `evals/harness/run.py` — `fetch_effective_bindings(base_url, ...)` plus a `Run.create`
  keyword that writes `llm_bindings` into the snapshot beside `settings`.
- `evals/conftest.py` — pass the fetched bindings into `Run.create`.
- `web/src/client/` — regenerate from the in-process schema.
- `docs/backlog.md` — mark B-38 closed, naming the commit that closed it.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — `epic-8: in-progress`,
  `8-2-persisted-selection: review`.
- `_bmad-output/implementation-artifacts/sprint-notes.md` — append a dated 8.2 section.

**Acceptance Criteria:**
- Given a role and one of its catalog bindings, when `PUT /settings/roles/{role}` is called,
  then the selection persists across api restarts and `GET /settings/models` reports it as the
  effective binding beside the file value and the catalog.
- Given a persisted selection, when a chat request and an extraction job each resolve their
  role, then both call the selected binding, chat re-reading it on every request and the worker
  on every job, with no process restart in between.
- Given a selected binding whose provider answers "no such model", when the call is made, then
  the fallback completer is never invoked and the failure names the provider, the endpoint, and
  the model — as `urn:meetingminer:problem:binding-failed` from chat and as a `StageError` from
  the worker.
- Given an unreachable model host, when the call is made, then today's `LlmUnavailableError`
  fallback behaviour is unchanged.
- Given an eval run, when its folder is created, then `config-snapshot.yaml` records each
  role's file value and its effective binding.

## Spec Change Log

**2026-08-30 — Investigation run without subagents, deliberately.** Step-02 offers synchronous
subagents for deep exploration. This run's dispatch forbids background agents outright, and
this harness's Agent tool is background-only. The exploration this story needed was narrow and
localized (eleven files, all named in the Code Map), so it was done directly, which step-02
sanctions for exactly that case. Nothing was delegated and nothing was skipped.

**2026-08-30 — The epic-8 context cache was accepted despite newer file mtimes.** Step-01's
validity rule compares mtimes, and every file in a freshly created worktree carries the
checkout's timestamp, so the rule reports every planning artifact as newer. Git shows no
planning artifact committed since `epic-8-context.md` was last written (2026-08-30T20:12),
and that file carries two corrections made by story 8.1's review (`5a00b60`, `f9d9e71`).
Recompiling would have discarded verified corrections to satisfy a timestamp artifact.

**2026-08-30 — Two measured conflicts, neither narrowable, both for `integrate`.**
`python3 _bmad/scripts/branch_conflicts.py --against story/8-2`, run with the
story complete, reports every code pair clean. What is not clean:

* `story/8-2 x story/7-3` — `web/src/client/{index,sdk.gen,types.gen}.ts`. Both
  stories add an api operation (`assignMeetingSpeaker` there, `getModelSettings`
  and `selectRoleBinding` here) and both regenerate the committed client, which
  appends to the same three generated files. Narrowing is not available: leaving
  the client unregenerated would commit a client that no longer matches the
  schema, which is the drift `check-client` and the tracked-client rule exist to
  prevent. It is a generated artifact, so the resolution is one `make client` (or
  the in-process equivalent) after the merge — not a hand-merge of either diff.
* `sprint-notes.md` against `main` and every other `story/*` branch. The wave
  rules already name this file as having no merge driver and expect `integrate`
  to union it. It is not specific to this branch: `main x story/10-2` conflicts
  on the same file, because `main` advanced to `e5e0ff9` with its own end-of-file
  append while this branch was building. Every append to the end of that file
  collides with every other, so the only narrowing available would be to place
  this story's section out of chronological order, which trades a sanctioned
  union for a confusing file. The entry was shortened instead, as the wave rules
  ask. **No code file conflicts with `main`.**

**2026-08-30 — Three edits outside the build prompt's footprint.** Each is a
"both places" contract this story could not satisfy from inside its footprint,
and none adds coverage to a shared module:

* `server/tests/test_api_registry.py` — `BASELINE_ROUTER_ORDER` pins the
  registration order of every discovered router. Adding `api/settings.py`
  without adding the name fails
  `test_existing_routers_keep_the_baseline_registration_order`. Added between
  `participants` and `speakers` (default order, name tie-break) with the
  same style of comment every previous story left.
* `server/tests/test_extraction_core.py` — its `stub_litellm` fixture builds a
  fake `litellm` module carrying only the exception names the adapter
  referenced. The adapter now also references `NotFoundError`, so the lazy
  `import litellm` inside `complete` resolved to a stub without it and eight
  mapped-exception tests raised `AttributeError` instead of asserting. One name
  added to the fixture's tuple, plus the docstring sentence saying why every
  referenced name must appear. No test appended.
* `evals/tests/test_harness_boundary.py` — the guard pinning which harness
  modules may import `httpx`. `harness/run.py` joins it, exactly as
  `retrieval.py` did in story 5.3 and `judge.py` in 5.4, with the reason stated
  in the guard's own docstring: the effective binding is read from the public
  `GET /settings/models`, and the alternative (re-deriving the selection from
  Postgres in the harness) would be both a second copy of a one-copy rule and
  the housemate coupling AD-16 forbids.

**2026-08-30 — The eval snapshot records the problem but does not fail the run.**
The first implementation called `run.note(...)` when the effective binding could
not be read, which fails the run. It broke five existing `evals/tests` cases and,
more importantly, changed what a verdict means: whether an unreadable binding
should invalidate a run is a question about the verdict, which this story does
not answer. The problem is recorded in `config-snapshot.yaml` — which is what the
acceptance clause asks for — and the checks decide whether the run passed.

**2026-08-30 — Implementation run without the step-03 subagent, deliberately.**
Step-03 directs the implementation to a synchronous subagent. This run's dispatch
forbids background agents outright and this harness's Agent tool is
background-only, so the work was done directly, red-first, at the same rigor: every
behaviour was observed failing against unfixed code before the fix landed, and the
reds are named in the commits. Recorded here rather than left as an unexplained
deviation.

## Design Notes

**Why `binding` means the model tag in the problem body.** Chat's existing problems use
`binding="llm.roles.chat"` (the config path). Epic 8's own vocabulary, set by 8.1's
`CatalogEntry.binding`, makes a *binding* the model tag. AC3 pairs `binding` with `provider`,
which only reads coherently as the tag. The `binding-failed` body therefore carries
`binding` = the tag, `provider` = the derived provider, `role` = the role name, and
`configPath` = `llm.roles.<role>` so the operator still gets the file anchor. The two existing
slugs keep their meaning; nothing that passes today changes shape.

**Why a stale selection falls back to `default` rather than refusing.** The catalog lives in
`config.yaml` and an operator may edit it while a selection is stored. Refusing every chat
request until someone edits a database row would make a config edit an outage. Discarding the
stale pick restores exactly the documented meaning of `default` — but only loudly: it is named
in the api payload (`staleSelection`) and logged as `llm.selection_stale` on every resolution.
This is not the rejected silent fallback, which is *answering from a different model after the
selected one failed at call time*; here the selection was withdrawn by the file before any
call was made.

**Why the role's `base_url` still applies to a selected binding.** `llm.roles.<role>.base_url`
is declared as the endpoint for that role's primary model, and the selection replaces the
primary. Carrying it over is the least surprising reading and preserves the endpoint the file
declares. The known hazard — an endpoint that does not serve the newly selected tag — is
precisely what B-38 converts from a silent substitution into a named refusal, so the two halves
of this story close each other's gap.

**Why the eval harness reads the effective binding over HTTP.** AD-16 makes the harness a
client. `GET /settings/models` already computes the effective binding with the one rule, so
reading it over httpx keeps a single implementation and leaves the AD-16 import allowlist
(`evals/tests/test_harness_boundary.py`) untouched, where a `meetingminer.domain` import would
have required widening it.

**Why 502 for `binding-failed`.** 503 promises that retrying later may work. A provider that
does not serve the requested model will answer identically forever; the operator must change
the selection or the file. 502 separates it from the outage path that keeps 503.

## Verification

**Commands:**
- `uv run --project server pytest server/tests/test_settings_resolution.py server/tests/test_api_settings.py -q`
  — expected: all pass; each test observed failing against unfixed code first.
- `uv run --project server pytest server/tests/test_worker_extract.py server/tests/test_api_chat.py -q`
  — expected: unchanged pass; proves the resolution change did not alter existing behaviour.
- `uv run --project evals pytest evals/tests -q` (`make evals-test`) — expected: unchanged
  pass plus the new snapshot coverage; no run folder created, no api contacted.
- `make lint` and `make typecheck` — expected: clean, with no baseline widened.
- `make test-fast` — expected: green, every skip printed with a named reason.
- `make test` — the full gate. Run 2026-08-30: **2366 passed, 2 skipped**
  in 625.67s, then the web production build, exit code 0. Both skips are the
  pre-existing named ones (no `pyannote` in the venv; the opt-in YouTube
  network case).
- `python3 _bmad/scripts/branch_conflicts.py --against story/8-2` — expected: `clean` against
  `main` and every other `story/*` branch.
