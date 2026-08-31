---
title: 'Story 8.2a: Provider Health on the Status Surface'
type: 'feature'
created: '2026-08-31'
status: 'review'
review_loop_iteration: 0
followup_review_recommended: false
context: ['AGENTS.md', 'docs/architecture.md', '_bmad-output/planning-artifacts/epics.md', '_bmad-output/specs/spec-system-status/SPEC.md', '_bmad-output/implementation-artifacts/spec-8-2-persisted-selection.md', '_bmad-output/implementation-artifacts/spec-8-3-model-picker-ui.md']
deferred:
  - summary: >-
      The api cannot report the worker's binding, only say that it holds a
      different one.
    evidence: |-
      The third acceptance criterion requires the surface to attribute its
      reading rather than claim the worker's. It does: every row names the api
      as the observing process and the extraction row names the worker as the
      caller. What it still cannot do is *show* the worker's snapshot, because
      nothing publishes it — the worker holds `config.yaml` in its own process
      and writes no record of what it loaded. Closing that means the worker
      recording its loaded binding and config-load timestamp on a row the api
      can read (a heartbeat or an `app_setting`-adjacent table), which is a
      worker change and a migration, outside this story's server footprint.
      Until then the honest surface is the attributed one. Filed as B-53.
    location: >-
      server/meetingminer/api/status.py - _role_attribution; server/meetingminer/worker
    severity: medium
  - summary: >-
      `docs/backlog.md` carries two entries numbered `B-42`.
    evidence: |-
      Story 8.3 filed "Serve provider health per provider, not per role" as
      B-42 while stories 10.3/10.4 filed "AD-17's id-addressed media route does
      not exist" as B-42 on the same day in parallel branches. This story
      closes the first. Renumbering either would break references already
      written into landed story specs, so the collision is recorded in
      `docs/backlog.md` beside the closure rather than resolved here.
    location: >-
      docs/backlog.md
    severity: low
baseline_commit: '9fc760fe'
baseline_revision: '9fc760fe'
---

<intent-contract>

## Intent

**Problem:** `GET /status` reported key state only as a side effect of the roles
that happened to bind a provider, and it reported the *file's* model rather than
the binding actually in force — so a configured provider nothing binds had no
health at all, and a story 8.2 selection pointing at a different provider was
invisible. Worse, the surface spoke as though one answer covered the whole
system. On 2026-08-31 a `config.yaml` edit was followed by a worker restart and
no api restart, and `GET /status` advertised local extraction from its stale
startup snapshot while the worker was genuinely calling a paid provider. AD-10
as amended records why: the catalog is a process-start snapshot
(`api/main.py` holds `CONFIG = _load_or_die()` at module level) while a
selection is a per-request `app_setting` read (`domain/model_selection.py`), and
the api and the worker hold independent snapshots. Reporting a state the system
is not in is an AD-18 violation.

**Outcome:** `GET /status` reports key validity per configured provider, the
binding each role is actually serving beside the file default, and — for every
one of those readings — whose view it is. The status page and the chrome
indicator name the provider or role and the remediation; no fragment of any key
serializes anywhere; and no wording implies that one answer covers both
processes.

## Boundaries & Constraints

- **Free probes only.** Key validity comes from a provider's model-list
  endpoint (`/v1/models`, `/models`, `/api/tags`) and never from a completion.
  Pinned by a test that exercises `_probe_provider` itself, asserts the exact
  URLs, bans every completion path fragment, and fails the run if the probe
  issues anything but a GET. No paid call is made anywhere in this story.
- **Cached between polls.** `providers[]` and the role rows share
  `_PROBE_CACHE`, keyed `(provider, base_url)` and never by key material, so a
  poll costs at most one free request per endpoint per `PROBE_TTL_SECONDS`
  (60s) regardless of how many rows name that endpoint.
- **Secrets never serialize.** The payload stays an explicit field-by-field
  allowlist. `_api_key` exists only to hand a key to a probe.
- **Read-only.** Nothing here mutates anything; nothing touches the worker.
- **One resolution rule.** The active binding comes from
  `domain/model_selection.resolve`, the same function `GET /settings/models`
  and the worker use — status derives no selection logic of its own. Which
  roles adopt a persisted selection is read from `api/settings.py`'s single
  `SETTINGS_ROLE_POLICY` table rather than re-listed.
- **Attribution is not optional.** Every provider and role row carries
  `observedBy`; every role row carries `servedBy` and an `attribution`
  sentence; the payload carries one `observedBy` block naming the process, the
  file it loaded and when. The page renders all of it and the indicator renders
  the one-line form even when everything is healthy.
- **Footprint.** Server work is confined to `api/status.py` plus two lines in
  `api/main.py`. Web work stays inside `features/status/` and the pure helpers
  in `features/settings/models.ts` — `App.tsx`, the chrome, `ChatPanel`,
  `CorpusSearch` (story 10.5) and `features/threads/` (story 10.6) are
  untouched, as are `ModelSelect.tsx` and `SettingsPage.tsx` (story 10.5's
  review branch).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Provider key good | key set, list endpoint answers 200 | `providers[]` row `keyState: present`, `state: ok`, `remediation: null` | No error expected |
| Provider key invalid | list endpoint answers 401/403 | `keyState: invalid`, `state: degraded`, detail names the env var, remediation names `.env` plus restarting api **and** worker; surface degrades | Never a completion retry |
| Provider key missing | env var unset | `keyState: missing`, `state: degraded`, and **no probe is issued** for that provider | A fact, not a request |
| Keyless provider | `ollama` | `keyState: not-required`; reachability is the whole question | Unreachable → degraded, host named |
| Provider nothing binds | declared in `providers:`, no role uses it | Still gets a row — the question is asked before anything is selected | No error expected |
| Selection in force | `app_setting` names a catalog binding | Role row's `model`/`provider` are the *selected* binding; the selected binding's endpoint is what gets probed; `defaultBinding`/`fileBinding` carry the file half | No error expected |
| Selection withdrawn from the catalog | stored binding no longer offered | `source: file-default`, `staleSelection`/`staleReason` named, row `degraded`, remediation names the settings page and `config.yaml` | Never applied, never hidden |
| Selection unreadable | Postgres down | `source: unknown`, row `degraded`, detail says the binding in force could not be determined, remediation points at the stores | The file default is shown but explicitly not claimed as in force |
| File-only role | `judge` (`SETTINGS_ROLE_POLICY`) | Resolved from the file alone; an `app_setting` row for it is never shown as in force; detail says why | No error expected |
| Role the api does not call | `extraction` | `servedBy: worker` and the verbatim disclaimer that this is the api's snapshot, not the worker's | Never claims the worker's state |
| Role the api does call | `chat` | `servedBy: api`; the row is the binding the next chat call from this process uses | No error expected |
| Chrome indicator, degraded | any provider or role degraded | Provider rows flow through `degradedRows()` before role rows, each with detail and remediation | No new component shape |
| Chrome indicator, healthy | everything ok | The expanded panel still carries the attribution line | Attribution is never summarised away |
| Picker health join | `providers[]` served | `providerHealthIndex` takes the credential verdict from `providers[]` (provider-wide) and reachability from the role rows (per role plus provider); `healthFor` prefers a role's own endpoint over the provider default | An uncovered option stays `unknown` |

</intent-contract>

## Code Map

- `server/meetingminer/api/status.py` — `ProviderStatus` and `ObservedBy`
  response models; `LlmRoleStatus` extended with `source`, `defaultBinding`,
  `fileBinding`, `selected`, `staleSelection`, `staleReason`, `observedBy`,
  `servedBy`, `attribution`. `_key_health` is the one credential decision, used
  by both the provider rows and the role rows so they cannot drift.
  `_provider_rows` walks `config.settings.providers`.
  `_resolve_effective_bindings` reads the stored selections once per request
  and returns `None` for a role whose selection could not be read.
  `_role_row` now probes the *effective* binding's endpoint.
  `OBSERVING_PROCESS`, `ROLE_CALLERS`, `_role_attribution` and the two note
  constants are the attribution vocabulary.
- `server/meetingminer/api/main.py` — records `CONFIG_LOADED_AT` beside
  `CONFIG` and puts it on `app.state`, so the payload can say how old the
  snapshot it is serving actually is.
- `docs/architecture.md` — AD-10 gains the different-clocks amendment the
  ARCHITECTURE-SPINE already carried at `91432022`; the two documents were out
  of sync on exactly the paragraph this story rests on.
- `web/src/features/status/status.ts` — `ProviderStatus`, `ObservedBy`,
  `RoleBindingSource`, the extended `LlmRoleStatus`, `providers` and
  `observedBy` on `SystemStatus`; `degradedRows()` now flattens provider rows;
  `attributionLine()` and `sourceLabel()` are the two sentences this module
  authors.
- `web/src/features/status/StatusPage.tsx` — a providers section, the
  attribution and the two notes above the overall line, and the source label
  plus attribution on every role row.
- `web/src/features/status/StatusIndicator.tsx` — one attribution line in the
  expanded panel. Provider rows needed no change here: they arrive through
  `degradedRows()`.
- `web/src/features/settings/models.ts` — `providerHealthIndex` reads
  `providers[]` for credential verdicts and keeps role rows for reachability;
  `healthFor` gains the provider-default-endpoint tier. The comment predicting
  this story is gone.
- `web/src/client/` — regenerated for the new schema (`ObservedBy`,
  `ProviderStatus`, the extended `LlmRoleStatus` and `StatusResponse`).
- `docs/backlog.md` — B-42 (provider health per provider) closed.

## Verification

- `make lint` — All checks passed. `make typecheck` — Success, no issues in 13
  source files.
- `pnpm exec tsc -b` — clean. `pnpm exec oxlint` — five pre-existing
  `only-export-components` warnings, none in this story's files.
- `make web-test` — 24 files, 453 tests, all passing.
- `uv run --project server pytest -m "" server/tests/test_api_status.py` — 25
  passed (14 before this story).
- `make test` — 2737 passed, 3 skipped, 710s (11m50s), exit 0. The web
  production build (`tsc -b && vite build`) runs inside that target and is
  clean. The three skips are pre-existing and opt-in: `test_youtube.py:1353`
  (`MM_YOUTUBE_NETWORK_TEST`), `test_diarize_pyannote.py:266` (no `pyannote` in
  the venv) and `test_diarize_remote.py:774` (`MM_DIARIZE_REMOTE_NETWORK_TEST`,
  the LAN GPU host started by hand).
- `python3 _bmad/scripts/branch_conflicts.py --against story/8-2a`, measured at
  `f194eeec` — 4 clean pairs, 17 conflicting. **No source file this story
  touched conflicts with `story/10-5`, `story/10-5-review`, `story/10-6` or
  `story/10-6-review`**: the only pairs against them are
  `sprint-notes.md` (10-5, 10-6 — untouched here, inherited from `main`) and
  `docs/backlog.md` (10-6 and 10-6-review, where the deferred item's append meets their own
  entries). Two genuinely new conflicts: `story/12-1` and `story/12-1-review`
  on `web/src/client/index.ts`, where both branches regenerated the client —
  the resolution on landing is to regenerate, not to merge the generated line.
  Conflicts against `story/7-4`, `story/8-3`, `story/10-3` and `story/10-4` are
  stale-branch noise: `main` conflicts with each identically because those
  stories landed and their branches were not deleted.

## Spec Change Log

- `docs/architecture.md` AD-10 was amended to match ARCHITECTURE-SPINE.md, which
  had carried the different-clocks paragraph since `91432022` while the shorter
  document did not. The story's third criterion cites "AD-10 as amended", and
  the amendment was only in one of the two documents.
- Four existing web test files in `features/settings/` gained the new required
  `StatusResponse`/`LlmRoleStatus` fields in their fixtures
  (`ModelRoles.test.tsx`, `ModelSelect.test.tsx`,
  `ModelSettingsIntegration.test.tsx`, `models.test.ts`). No assertion changed;
  the fixtures had to become payloads the api can actually emit.
- Two existing assertions in `features/status/status.test.tsx` were narrowed:
  the role remediation and the provider remediation for the same bad key both
  render now, so each assertion names the one it means ("requests on this
  binding fail" versus "requests on this provider fail").
