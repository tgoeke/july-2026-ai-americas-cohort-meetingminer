---
title: 'Story 8.1: AD-10 Amendment and Binding Catalog'
type: 'feature'
created: '2026-08-30'
status: 'ready-for-dev'
review_loop_iteration: 0
followup_review_recommended: false
context: []
warnings: ['oversized']
deferred: []
---

<intent-contract>

## Intent

**Problem:** `config.yaml` binds exactly one model per LLM role, so a user who wants a
different model edits the file and restarts. Epic 8 opens a bounded choice, and nothing
downstream — a persisted selection (8.2), provider health (8.2a), a picker (8.3) — can
reference a catalog entry until the file declares one. FR38.

**Approach:** Add a per-role `catalog[]` of `binding` / `label` / `provider` plus a
`default` to `llm.roles.<role>`, validated when the file loads. A `default` outside its
own catalog, and a catalog entry naming a provider that `providers:` does not declare,
are both named refusals; a file that declares only `model` still loads, as a one-entry
catalog. Carry the amendment into AD-10 and the repository's binding policy line. This
story stops at the config contract: it changes no call path.

## Boundaries & Constraints

**Always:**
- Fail closed and fail named. Both refusals raise from `Settings` validation, which is the
  layer `load_config` already wraps into `ConfigError` — the message names the file, the
  role, the offending value, and the legal set.
- Backward compatible. Every `config.yaml` that loads today still loads: an absent
  `catalog` becomes one entry synthesized from `model`, an absent `default` becomes
  `model`.
- `model` remains the field every adapter caller reads (`build_llm`, `resolve_api_base`,
  `_role_view`). The catalog is declaration only until 8.2 resolves a selection.
- Declared-ness is a fact about the file, never about reachability. No provider is probed
  at load.
- The footprint is a contract. Eight other story lanes are in flight; every push is
  measured with `python3 _bmad/scripts/branch_conflicts.py --against story/8-1`. A new
  conflict in any file outside `_bmad-output/` means this story's edit is narrowed and the
  gap recorded in the Spec Change Log — never that another branch's region is edited to
  make room.

**Block If:**
- The AD-10 amendment cannot be written without changing a sentence story 11-2 rewrites,
  AND the owner has not accepted the overlap. (The build prompt already accepts it: it
  directs this story to amend the binding sentence and preserve 11-2's environment-variable
  sentence verbatim, which is a same-paragraph overlap `integrate` resolves.)

**Never:**
- No persisted selection, `app_setting` table, `/settings/*` route, status-surface row, or
  picker UI. Those are 8.2 / 8.2a / 8.3.
- No edit to `ExtractionRoleBinding`, `DiarizerConfig`, `LlmRoles`, `load_config`, the tail
  of `Settings`, `server/tests/conftest.py`, `infra/Makefile`, `AGENTS.md`,
  `docs/backlog.md`, or `README.md` — other lanes own those exact regions.
- Never append to `server/tests/test_config.py`; all coverage lives in a new module.
- No provider name is hardcoded in Python. The declared set is whatever `providers:` holds.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Legacy single-model role | `chat: {model: openai/gpt-5.2}`, no `catalog`, no `default` | Loads. Catalog is one entry: binding and label `openai/gpt-5.2`, provider `openai` derived from the tag prefix. `default` is `openai/gpt-5.2` | No error expected |
| Legacy bare tag | `chat: {model: some-model}` (no `/` prefix) | Loads. One-entry catalog, `provider` is `None` — the file named none and a file that loads today must keep loading | No error expected |
| Authored catalog | two entries, `default` equal to the second entry's binding | Loads. Entries keep file order; `default` is as written; `model` is untouched | No error expected |
| Default outside catalog | `default: openai/gpt-9`, not among the entries | Refused before any partial boot | `ConfigError` naming the role's default and every catalog binding |
| Undeclared provider | entry `provider: moonshot`; `providers:` declares anthropic/openai/openrouter/ollama | Refused | `ConfigError` naming role, binding, the undeclared provider, and the declared providers |
| Provider omitted, derivable | entry binding `ollama/qwen3:30b`, no `provider` | Provider derived as `ollama`, then checked against `providers:` | Refused by the undeclared-provider rule if the derived prefix is not declared |
| Provider omitted, underivable | authored entry binding `claude-sonnet-5`, no `provider` | Refused: an entry whose tag carries no prefix must say which provider serves it | `ConfigError` naming the role and the binding |
| Authored empty catalog | `catalog: []` | Refused — `default` (or `model`) cannot be in an empty catalog | Falls out of the default-in-catalog rule; no separate rule invented |

</intent-contract>

## Code Map

- `server/meetingminer/config.py:141` — `class LlmRoleBinding(_StrictModel)`: `model`,
  `fallback`, `base_url`, `fallback_base_url`, `timeout_seconds`, `num_ctx`. The new
  `CatalogEntry` class goes immediately before it; `catalog` and `default` are added to it.
  `ExtractionRoleBinding` (line 176) subclasses it and is owned by story 10-1 — read only.
- `server/meetingminer/config.py:689` — `class Settings`: fields `config_version` … `api`,
  including `llm: LlmConfig` and `providers: dict[str, ProviderEndpoint]`. The
  catalog×providers cross-check lives here because it is the only class holding both, and
  because `load_config` wraps *this* class's `ValidationError` into `ConfigError`. Story
  6-2 appends a field after `api: ApiConfig`, so nothing is added at the class tail.
- `server/meetingminer/config.py:968` — `load_config`: `Settings.model_validate(raw)` inside
  `try/except ValidationError` → `ConfigError(f"config file failed validation: {path}\n{exc}")`.
  The `AppConfig(...)` construction on its last line is **not** wrapped, which is why the
  cross-check is not placed there. Read only — story 11-2 rewrites this function's tail.
- `server/meetingminer/config.py:99` — `_StrictModel` is `extra="forbid"`; `NonEmptyText`
  (line 103) is the strip-and-min-length-1 alias used for required text.
- `server/meetingminer/adapters/llm/litellm.py:53` — `resolve_api_base`: the routing rule the
  provider derivation mirrors — `model.split("/", 1)[0]` when the tag is prefixed, and no
  provider (LiteLLM's own default) when it is not. Read only; not imported, because
  `config.py` must not depend on an adapter.
- `server/meetingminer/api/status.py:131` — `provider_of`, the same rule plus bare
  `claude-`/`gpt-` spellings. Read only, and deliberately not imported: `config.py` importing
  from `api/` would invert the dependency direction.
- `config.yaml:60`-`160` — `llm.roles.{extraction,chat,judge}`; `providers:` at line 169
  declares anthropic, openai, openrouter, ollama. All three roles use prefixed tags
  (`ollama/gpt-oss:120b`, `openai/gpt-5.2`), so every synthesized provider is declared.
- `config.yaml:147`-`154` — the stale chat comment ("the Anthropic key was deliberately
  invalidated"). Story 10-1 inserts at line 147 (measured); see the Spec Change Log.
- `docs/architecture.md:109`-`113` — AD-10. Story 11-2 rewrites lines 111-113 (the
  environment-variable sentence); this story amends the binding sentence at 109-110.
- `project-context.md:29`-`35` — the policy bullet about which roles bind to which models.
  Story 11-2 edits lines 18-21 and 96-110 only.
- `_bmad-output/planning-artifacts/sprint-change-proposal-2026-08-29.md:70`-`79` — the
  owner-approved AD-10 amendment wording this story draws from.

## Tasks & Acceptance

**Execution:**
- `server/tests/test_config_catalog.py` — NEW module holding every test for this story;
  write each test and observe it fail against the unfixed loader before the change lands —
  the two refusal messages, the back-compat synthesis, and the authored-catalog path.
- `server/meetingminer/config.py` — add `class CatalogEntry(_StrictModel)` (`binding`,
  `label`, `provider`) immediately before `class LlmRoleBinding`; add `catalog` and
  `default` to `LlmRoleBinding` with an after-validator that synthesizes the one-entry
  catalog, derives an omitted provider from the tag prefix, refuses an authored entry whose
  tag carries no prefix and no `provider`, and refuses a `default` outside the catalog.
- `server/meetingminer/config.py` — add an after-validator to `Settings`, placed with the
  `providers` field rather than at the class tail, refusing any catalog entry whose resolved
  provider is not a key of `providers`.
- `config.yaml` — add `catalog:` and `default:` as the first keys of each of the three
  `llm.roles.<role>` blocks, so the committed file demonstrates the new shape without
  changing which model any role uses.
- `docs/architecture.md` — amend AD-10's binding sentence with the catalog and default
  wording; leave 11-2's environment-variable sentence untouched.
- `project-context.md` — update the one policy line about bindings to say the file declares
  a per-role catalog and default.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — `epic-8: in-progress`,
  `8-1-ad-10-amendment-and-binding-catalog: review`.
- `_bmad-output/implementation-artifacts/sprint-notes.md` — append a dated 8.1 section.

**Acceptance Criteria:**
- Given the committed `config.yaml`, when the loader runs, then every role exposes a catalog
  whose entries all name a declared provider, and each role's `default` is one of its own
  catalog bindings.
- Given a `config.yaml` written before this story (role declares only `model`), when it
  loads, then it loads without error and the role's catalog has exactly one entry whose
  binding equals `model`.
- Given a role whose `default` names a binding absent from its catalog, when the loader runs,
  then it raises `ConfigError` and the message names both the default and the catalog's
  bindings.
- Given a role whose catalog entry names a provider absent from `providers:`, when the loader
  runs, then it raises `ConfigError` and the message names the role, the binding, the
  undeclared provider, and the declared providers.
- Given the amendment, when it lands, then AD-10 carries the catalog wording and
  `project-context.md`'s binding policy line matches it.

## Spec Change Log

**2026-08-30 — AC clause 3 (the stale chat comment) is NOT already satisfied; recorded as an
open gap rather than widened into.** The build prompt directed this story to verify that no
`revoked` text remains and record the clause as satisfied. The literal token is indeed absent
from `config.yaml` and `config.py`, but the comment the clause names is present at
`config.yaml:147`-`154`: "the Anthropic key was deliberately invalidated after unauthorized
paid use, and the spine's AD-10 default binding (claude-sonnet-5) is superseded". The
Anthropic key was restored on 2026-08-29, so the claim is stale, and the sprint change
proposal lists it as replaced by the catalog. It is left in place because `git diff
--unified=0 origin/main...origin/story/10-1 -- config.yaml` reports `@@ -146,0 +147,24 @@` —
story 10-1 inserts its `topics_prompt` block at exactly line 147, adjacent to every line of
that comment, so any edit of it conflicts with an in-flight lane. Per the wave rules the edit
is narrowed and the gap named here instead. Whoever lands after 10-1 should delete the two
stale sentences (the invalidated key and the superseded `claude-sonnet-5` default) and keep
the rest of that comment verbatim: the no-fallback owner decision and the `openai/` prefix
requirement are both live.

## Review Triage Log

## Design Notes

**Why the cross-check sits on `Settings` and not on `LlmRoleBinding` or `AppConfig`.** A role
binding cannot see `providers:` — only `Settings` holds both sections. `AppConfig` holds them
too, but `load_config` wraps only `Settings.model_validate` in the `except ValidationError`
that produces the named `ConfigError`; a refusal raised from `AppConfig` would escape as a raw
pydantic error. `Settings` is therefore the outermost layer where the check both has its
inputs and fails with the named message the AC requires.

**Why an omitted `provider` is derived rather than required.** `resolve_api_base` already
treats the tag prefix as the routing fact, so deriving `ollama` from `ollama/qwen3:30b` states
what the file already says instead of asking an author to repeat it. The rule is asymmetric on
purpose: an *authored* entry whose tag has no prefix must name its provider, because an entry
that names no provider cannot be checked against the declared set; a *synthesized* entry keeps
`provider: None` in that case, because it is a projection of a file written before the rule
existed and refusing it would break a file that loads today.

**Why no separate empty-catalog rule.** `default` falls back to `model`, and `model` is
required and non-empty, so an authored `catalog: []` is already refused by the
default-in-catalog rule with a message that names it. The UX design's "empty catalog renders
honestly" case is a UI robustness requirement for 8.3, not a loadable config state.

**Deferred to 8.2:** the rest of the owner-approved AD-10 wording — that a user's selection is
user-declared data persisted in Postgres, resolved at call time by api and worker, and recorded
in every eval run's config snapshot beside the file values. It is deliberately not written now,
because AD-10 would then describe behavior no code implements.

## Verification

**Commands:**
- `uv run --project server pytest server/tests/test_config_catalog.py -q` — expected: all new
  tests pass; each was observed failing against the unfixed loader first.
- `uv run --project server pytest server/tests/test_config.py -q` — expected: unchanged pass;
  proves the existing config contract still holds.
- `make test-fast` — expected: green, skips printed with named reasons only.
- `make test` — expected: green, once, before the spec moves to review.
- `python3 _bmad/scripts/branch_conflicts.py --against story/8-1` — expected: no conflicting
  pair outside `_bmad-output/`. Baseline before this story (recorded 2026-08-30) already has
  four: `spec-11-2-per-run-store-isolation.md`, `review-story-11-4-2026-08-30.md`, and
  `sprint-notes.md` against `story/7-1` and `story/7-1-review` — all present against `main`
  itself, and all absorbed by `integrate`.
