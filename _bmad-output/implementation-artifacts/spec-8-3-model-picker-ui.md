---
title: 'Story 8.3: Model Picker UI'
type: 'feature'
created: '2026-08-31'
status: 'review'
review_loop_iteration: 0
followup_review_recommended: false
context: ['AGENTS.md', '_bmad-output/implementation-artifacts/wave-2026-08-30-rules.md', '_bmad-output/implementation-artifacts/build-prompt-story-8-3-2026-08-31.md', '_bmad-output/planning-artifacts/ux-designs/ux-meetingminer-2026-08-29/DESIGN.md', '_bmad-output/planning-artifacts/ux-designs/ux-meetingminer-2026-08-29/EXPERIENCE.md']
deferred:
  - summary: >-
      Provider health is derived from `GET /status.llmRoles[]`, joined by
      provider id, because the per-provider array does not exist yet.
    evidence: |-
      EXPERIENCE.md joins each catalog option to `GET /status.providers[]` by
      exact provider id, and attributes that array to story 8.2a, which is
      still `backlog` in `sprint-status.yaml`. The only place the api reports
      key state today is `llmRoles[]` — one row per configured role carrying
      `provider`, `keyState`, `state` and `remediation`. `providerHealthIndex`
      joins those by provider and keeps the worst row. A credential fact
      (`missing`/`invalid`) is genuinely provider-wide; endpoint reachability
      is not, because `llm.roles.extraction` has its own `base_url`. So an
      unreachable extraction host makes every `ollama/…` option read
      `unreachable`, including one whose call would resolve through
      `providers.ollama`. The api's remediation sentence names the host, so the
      reader can see which machine is meant. Filed as B-42.
    location: >-
      web/src/features/settings/models.ts - providerHealthIndex
    severity: medium
  - summary: >-
      A `binding-failed` 502 renders through chat's generic `problem` sentence
      and clears the previous answer.
    evidence: |-
      EXPERIENCE.md § Ask box asks for a refusal box in the answer region with
      the previous answer left intact. Today `classifyFailure` maps every
      non-422 `ChatHttpError` to `problem`, and `ask()` clears
      `answer`/`citations`/`route` on every failure. The api's own sentence —
      naming provider, binding, role and upstream status — is what renders, so
      the failure is surfaced and correctly attributed; what is lost is the
      answer the reader was already reading. Changing it is a change to chat's
      five-kind failure taxonomy, not to the picker, and this story's footprint
      is a minimal insertion into the ask box. Filed as B-43.
    location: >-
      web/src/features/chat/chat.ts - classifyFailure; ChatPanel.ask
    severity: low
  - summary: >-
      The popover is hand-rolled rather than built on the installed
      `@base-ui/react` primitives.
    evidence: |-
      `@base-ui/react` is a dependency but no component in `web/src` uses it
      yet, so adopting it here would have set a pattern for the whole product
      inside a demo-critical story. The hand-rolled version implements what
      EXPERIENCE.md § Popovers requires — arrow keys, Enter, Esc, focus to the
      trigger on Esc, outside-pointer dismissal, `aria-activedescendant`, and
      no focus trap — in about forty lines. Choosing the primitive is a
      product-wide decision for the shell story or a follow-up, not for this
      one.
    location: >-
      web/src/features/settings/ModelSelect.tsx
    severity: low
baseline_revision: '3211a7f'
---

<intent-contract>

## Intent

**Problem:** Stories 8.1 and 8.2 made the per-role catalog real — `GET /settings/models`
serves each selectable role's catalog with the binding actually in force, and
`PUT /settings/roles/{role}` persists a choice bounded by that catalog — and nothing renders
either. The choice a user is entitled to make is reachable only with `curl`, and the fact that
distinguishes the choices from one another (a local free model versus a metered remote API) is
visible nowhere. FR38, FR39, UX-DR15.

**Approach:** One picker, two mountings. A popover in the ask box binds the `chat` role where a
question is asked; a per-role list on the Settings page offers every role the api serves. Both
mount one hook that owns the two reads and the one write, so the read, the write and the
ownership rule exist once. Every word beside a binding is derived rather than authored: the
provider comes from the server's one spelling rule, locality and cost are keyed on that
provider id, and health is joined from `GET /status`. A binding whose provider is unavailable
renders muted with the api's remediation and stays selectable; a refused selection changes
nothing and says what is still in force.

## Boundaries & Constraints

**Always:**
- **Nothing is labelled by hand.** `PROVIDER_TRAITS` is keyed on the provider id the server
  derived (`domain/model_providers.provider_for_model`), never on a binding spelling or a
  catalog label. `ollama` is local and free; `openai`, `anthropic` and `openrouter` are remote
  and paid. A provider the table does not classify yields *no* claim — "where it runs and what
  it costs are not known here" — because a wrong claim about cost is worse than an absent one.
- **A failed binding surfaces, muted and selectable.** `invalid`, `missing` and `unreachable`
  mute the row and show the api's remediation. The row is never `aria-disabled`, never
  filtered, never reordered. Choosing it must fail loudly at the ask, where the failure is.
- **Health is never assumed.** An unread `GET /status`, or a provider no role names, reads
  `unknown` — not `ok`, and not a failure either. The catalog still renders and stays
  selectable: choosing a model does not depend on the health surface being up.
- **No substitution.** A refused or failed `PUT` leaves the binding in force exactly as the api
  last reported it, and the refusal restates it. No other entry is marked, and no default is
  applied in its place.
- **The later choice wins.** Every selection carries a per-role generation; a response may
  update visible state only while its generation is the latest. Late success and late failure
  are both discarded.
- **The roles offered are the roles served.** `judge` is absent from `GET /settings/models` by
  owner decision (story 8.2) and nothing here adds it back. A role the payload omits gets a
  named "not offered for selection", never an invented control.
- **A selection is live; the catalog is a snapshot.** The choice is a stored row read per
  request, so no copy on that path mentions a restart. The catalog is `config.yaml` as the api
  read it at startup, and the Settings surface says so once.
- **`source` is reported honestly.** A stored choice and an inherited file default are told
  apart in words, so an inherited default is never presented as a deliberate pick.

**Never:**
- No restructuring of the ask box (story 10.5 owns the shell) beyond one element in its header
  row, and no edit to the meeting view (story 7.4).
- No server change of any kind: no new endpoint, no migration, no `config.yaml` edit.
- No hand-edit or regeneration of `web/src/client/`.
- No second copy of the provider spelling rule in the web tree.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Render the trigger | `GET /settings/models` served, `chat` bound to `openai/gpt-5.2` | Trigger reads `chat · openai/gpt-5.2 · openai ● <health>`; accessible name adds `remote · paid` and the health word | No error expected |
| Open the catalog | click the trigger | `listbox` with every catalog entry in the api's order, the binding in force `aria-selected` and drawn ✓ | No error expected |
| Legibility of the choice | an `ollama/…` and an `openai/…` entry | `local · free` and `remote · paid`, each beside its exact binding | No error expected |
| Unclassified provider | catalog entry on a provider not in `PROVIDER_TRAITS` | "where it runs and what it costs are not known here" | Never guessed |
| Select | click or Enter on an entry | `PUT /settings/roles/{role}` with `{binding}`; the api's re-resolved view replaces the role's; trigger names the new binding | Refusal below |
| Refused selection | `PUT` answers 422 `binding-not-in-catalog` | Refusal names the api's sentence, restates the binding in force, says nothing was substituted | The ✓ does not move |
| Rapid selections | two clicks, the second answering first | The later choice is what renders; the earlier response is discarded on arrival | No stale overwrite |
| Failed provider key | `GET /status` reports `missing`/`invalid` for the provider | Row muted, remediation shown, `aria-description` carries it, row still selectable and its `PUT` still issued | Not hidden, not disabled |
| Status unreadable | `GET /status` rejects | Every option reads `unknown`, nothing is muted, the catalog still renders | Silent by design — no dot is claimed |
| Catalog unreadable | `GET /settings/models` rejects | Named in place: "cannot read the model catalog from `<api>`: `<reason>`" | The ask box still works |
| Empty catalog | role served with `catalog: []` | Trigger visible, opens nothing, `No models configured — …config.yaml…restart the api` | No default invented |
| Role not served | `chat` absent from the payload | "the chat role is not offered for selection" | No control invented |
| Stale selection | payload carries `staleSelection`/`staleReason` | Both named, with the file default now in force | Never silent |
| Settings page | `/settings` | One block per served role, each with its catalog, ✓, source sentence, and the catalog's own change path | Judge absent |

</intent-contract>

## Code Map

- `web/src/features/settings/models.ts` — NEW. The rules: `providerTrait`,
  `healthOfRoleRow`, `providerHealthIndex`, `healthFor`, `isFailedHealth`, `optionsFor`,
  `rolesOf`/`roleNamed`, the trigger and option accessible names, and every sentence the
  surface says (`sourceNotice`, `staleSelectionNotice`, `selectionRefusal`,
  `NO_MODELS_CONFIGURED`, `CATALOG_IS_A_STARTUP_SNAPSHOT`).
- `web/src/features/settings/useModelSettings.ts` — NEW. The one place the picker talks to the
  api: `getModelSettings`, `getSystemStatus`, `selectRoleBinding`, plus the per-role generation
  counter that makes the later choice win.
- `web/src/features/settings/ModelOptionRow.tsx` — NEW. `HealthBadge` and `OptionBody`, shared
  by both surfaces so a row says the same thing in both.
- `web/src/features/settings/ModelSelect.tsx` — NEW. The ask box's popover: trigger, listbox,
  arrow/Enter/Esc keyboard, outside-pointer dismissal, and the empty/not-offered/unreadable
  states.
- `web/src/features/settings/ModelRoles.tsx` — NEW. The Settings page's per-role lists.
- `web/src/features/chat/ChatPanel.tsx` — one import and one element in the header row. The
  panel's anatomy, streaming, citations and failure handling are untouched.
- `web/src/features/settings/SettingsPage.tsx` — one "Model per role" block above the read-only
  "LLM roles" section, deliberately outside that section because its change path (a file edit
  plus a restart) is exactly what a selection is not.
- `web/src/features/settings/settings.ts` — `READ_ONLY_CONTRACT` now names its one exception
  rather than being left to contradict the screen.
- `web/src/client/` — read only. `getModelSettings`, `selectRoleBinding` and `getSystemStatus`
  were already generated by story 8.2.

## Verification

- `make lint` — All checks passed. `make typecheck` — no issues in 13 source files.
- `pnpm exec tsc -b --force` — clean. `pnpm exec oxlint` — four pre-existing
  `only-export-components` warnings, none in this story's files.
- `make web-test` — 19 files, 340 tests, all passing (54 of them in
  `web/src/features/settings/`).
- `make test-fast` — 2172 passed, 3 skipped (network-gated), 411 deselected, one failure:
  `test_frame_image.py::test_an_unreadable_frame_raises_a_named_error` exceeded the 2.00s
  fast-set budget at 2.15s. Re-run alone as the plugin's own message instructs, its call phase
  is 0.01s. Contention from six parallel worktree builds, not a regression, and not this
  story's file.
- `python3 _bmad/scripts/branch_conflicts.py --against story/8-3` — 11 clean pairs, 0
  conflicting, against `main` and every other in-flight `story/*`.

## Spec Change Log

- Two existing test files were edited rather than only added to, both inside this story's
  footprint. `web/src/features/chat/ChatPanel.test.tsx`: the ask box now mounts a component
  that reads two endpoints on mount, and that file's assertions count `fetch` calls to prove
  one question makes one request — its stub now routes the picker's reads away from the chat
  mock, which leaves every existing assertion exactly as it was.
  `web/src/features/settings/SettingsPage.test.tsx`: the page's read-only claim changed with
  the page, so the assertion changed with it, and a test was added for the picker mounting.
- `docs/backlog.md` gained B-42 and B-43 (the prompt named B-40 as the highest in use; B-41 was
  taken by story 8.2 in the meantime).
