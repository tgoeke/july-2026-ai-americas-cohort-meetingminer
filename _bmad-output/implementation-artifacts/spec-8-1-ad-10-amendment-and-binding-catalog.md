---
title: 'Story 8.1: AD-10 Amendment and Binding Catalog'
type: 'feature'
created: '2026-08-30'
status: 'review'
review_loop_iteration: 0
followup_review_recommended: true
context: ['AGENTS.md', '_bmad-output/implementation-artifacts/wave-2026-08-30-rules.md', '_bmad-output/implementation-artifacts/build-prompt-story-8-1-2026-08-30.md']
warnings: ['oversized']
deferred:
  - summary: >-
      A role's `fallback` tag is subject to neither new rule.
    evidence: |-
      `llm.roles.extraction.fallback` is a live model tag resolved at call
      time, yet it need not be in the catalog and its provider is never
      checked against `providers:`. The undeclared-provider refusal therefore
      covers the declarative catalog but not both tags that can actually be
      sent. Out of scope here (the AC speaks only of catalog bindings) but it
      is the same class of defect the story exists to prevent.
    location: >-
      server/meetingminer/config.py - Settings._catalog_providers_are_declared
    severity: medium
  - summary: >-
      Three provider-derivation rules now exist in the tree and they disagree.
    evidence: |-
      `adapters/llm/litellm.py:resolve_api_base` and `api/status.py:provider_of`
      both resolve bare `claude-...` to anthropic and bare OpenAI spellings to
      openai; `config._provider_prefix` deliberately does not. The divergence
      is documented in the new docstring and is deliberate - copying the
      bare-spelling tables would write provider names into config.py - but
      nothing pins the three against each other, so they may drift further.
      Consequence today: a legacy `model: claude-sonnet-5` synthesizes an entry
      with no derivable provider while `/config` and `/status` report anthropic
      for the same tag. Prefixed legacy tags retain their derived provider but
      are marked internally so the new authored-catalog refusal is skipped.
    location: >-
      server/meetingminer/config.py:141
    severity: medium
  - summary: >-
      The catalog is invisible to an operator of the running stack.
    evidence: |-
      `GET /config`'s `LlmRoleView` is an explicit allowlist and
      `test_api_config_view.py` pins its field set, so the catalog and default
      appear nowhere in any api response. The story's user is an operator, and
      the declaration is only visible in the file. Serving it is story 8.2's
      `GET /settings/models`, so this is a scope boundary rather than a defect
      - recorded so 8.2 does not assume the surface already exists.
    location: >-
      server/meetingminer/api/config_view.py
    severity: medium
  - summary: >-
      A resolved-config dump no longer round-trips for a role whose catalog
      was synthesized from a prefixed tag.
    evidence: |-
      `Settings.model_dump(mode="json")` emits the synthesized entry's public
      fields but not its private synthesized marker. Feeding that back to
      `Settings.model_validate` makes the entry look authored and checks its
      provider, so a dump of a config whose tag prefix names an undeclared
      provider would be refused on the way back in. Nothing
      re-loads a dump today, but `evals/harness/run.py` writes exactly this as
      `config-snapshot.yaml`.
    location: >-
      server/meetingminer/config.py - LlmRoleBinding._catalog_from_model
    severity: low
  - summary: >-
      Smaller loader gaps left unfixed: no duplicate-binding refusal, only the
      first undeclared provider is reported, `catalog: null` and `catalog: []`
      behave oppositely, and a blank `model` is reported by the default rule.
    evidence: |-
      Each is real and each is cheap, but none is required by the AC and
      together they would widen this story's diff well past its footprint.
      Duplicates matter most: the catalog exists to feed a picker (8.3), where
      two rows for one binding is exactly the defect a loader catches cheaply.
      The blank-model case also changes an existing behaviour: `model` is a
      plain `str` with no non-empty constraint, so `model: ""` loaded before
      and is now refused - by a message that names the default, not the model.
    location: >-
      server/meetingminer/config.py
    severity: low
baseline_revision: '4b9d79a109300e4dc3db160a125289eb13142939'
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

**2026-08-30 — `make test` caught a back-compat break the fast set could not.**
The first implementation derived a provider for the *synthesized* one-entry
catalog and then checked it against `providers:`. That made every pre-catalog
file whose tag prefix names an undeclared provider refuse to load — a direct
violation of this spec's own "every `config.yaml` that loads today still loads"
invariant. It surfaced as `test_failfast.py::test_api_exits_1_when_no_provider_serves_the_configured_embedder`,
whose fixture removes `providers.ollama` and requires the config to still reach
the embedder gate; the module is `slow`, so `make test-fast` was green and only
the full gate found it. Fix: a synthesized entry retains a provider derivable
from its prefix, as the frozen I/O matrix requires, but carries an internal
marker that skips the authored-entry check; authored entries keep the strict
rule. A regression pins the exact shape
(`test_legacy_model_naming_an_undeclared_provider_still_loads`).

`server/tests/test_failfast.py` is edited **outside the build prompt's
footprint**, deliberately and recorded here: its fixture removes a provider the
committed catalogs now name, so it must drop the authored catalogs with it. No
in-flight lane touches that file (measured against all seven `story/*`
branches), and `branch_conflicts.py` stays clean on it.

**2026-08-30 — review-layer patches.** `_provider_prefix`'s docstring claimed to
restate `resolve_api_base`; it does not — the adapter also routes bare
`claude-`/`gpt-` spellings — so the docstring now states the narrowing and why
copying those tables was rejected. A written `provider` is now checked against
the tag's own prefix, closing a hole where `{binding: moonshot/kimi-k2,
provider: openai}` passed the declared-provider check while the call would route
elsewhere. The role loop guards on `isinstance`. Two test assertions were
tautological (the provider name is a substring of the binding) and the declared
set was hardcoded beside `config.yaml`; both now assert distinguishing text
derived from the file.

**2026-08-30 — Codex follow-up review, finding 2.** The prior triage deferred
`model in catalog` as an owner call. The follow-up review reversed that call:
the frozen intent says the catalog bounds what a role may be served by and also
says `model` remains the active call-time field until 8.2, so allowing an
authored `model` outside the catalog makes the new boundary false immediately.
Authored catalogs now require the active model to be one of their bindings;
legacy roles are unchanged because their synthesized catalog already contains
their model. A regression was observed failing before the validator was added.

**2026-08-30 — AC clause 3 was not already satisfied at build time.** The build prompt directed this story to verify that no
`revoked` text remains and record the clause as satisfied. The literal token is indeed absent
from `config.yaml` and `config.py`, but the comment the clause names is present at
`config.yaml:147`-`154`: "the Anthropic key was deliberately invalidated after unauthorized
paid use, and the spine's AD-10 default binding (claude-sonnet-5) is superseded". The
Anthropic key was restored on 2026-08-29, so the claim is stale, and the sprint change
proposal lists it as replaced by the catalog. It was left in place because `git diff
--unified=0 origin/main...origin/story/10-1 -- config.yaml` reports `@@ -146,0 +147,24 @@` —
story 10-1 inserts its `topics_prompt` block at exactly line 147, adjacent to every line of
that comment, so any edit of it conflicts with an in-flight lane. Per the wave rules the edit
was narrowed and the gap named here instead. The recorded remedy was to delete the two stale
sentences (the invalidated key and the superseded `claude-sonnet-5` default) and keep the rest
of that comment verbatim: the no-fallback owner decision and the `openai/` prefix requirement
are both live. After Story 10.1 landed, the follow-up review removed
the two stale claims and preserved those three live rules; AC clause 3 is now
satisfied.

## Review Triage Log

### 2026-08-30 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 6: (high 1, medium 2, low 3)
- defer: 7: (high 1, medium 4, low 2)
- reject: 9
- addressed_findings:
  - `[high]` `[patch]` Synthesized catalog entries were provider-checked, breaking every pre-catalog file whose tag prefix names an undeclared provider; caught by `make test` via the embedder fail-fast gate. The follow-up review preserves a derived provider but marks the entry synthesized so the new check is skipped; `test_failfast.py`'s fixture drops the authored catalogs with the provider it removes.
  - `[medium]` `[patch]` `_provider_prefix` docstring falsely claimed to restate `resolve_api_base`, which also routes bare `claude-`/`gpt-` spellings. Rewritten to state the narrowing and the reason for it.
  - `[medium]` `[patch]` A written `provider` was never checked against the tag's own prefix, so a declared-but-wrong provider passed while the call routed elsewhere. Now refused by name, with a test.
  - `[low]` `[patch]` The role loop assumed every `LlmRoles` field is an `LlmRoleBinding`; guarded with `isinstance`.
  - `[low]` `[patch]` Two assertions were tautological — the provider name is a substring of the binding it appears in. Now assert `provider '<name>'`.
  - `[low]` `[patch]` The declared-provider set was hardcoded in the tests beside `config.yaml`; now derived from the committed file.

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
`provider: None` only when its tag has no prefix, and its internal marker skips the new
declared-provider refusal because it projects a file written before that rule existed.

**Why no separate empty-catalog rule.** `default` falls back to `model`, and `model` is
required and non-empty, so an authored `catalog: []` is already refused by the
default-in-catalog rule with a message that names it. The UX design's "empty catalog renders
honestly" case is a UI robustness requirement for 8.3, not a loadable config state.

**Implemented by the follow-up review:** AD-10 now carries the full
owner-approved decision, including that a user's selection is user-declared
data persisted in Postgres, resolved at call time by api and worker, recorded
in every eval run's config snapshot beside the file values, bounded by the
catalog, and never a fallback. Stories 8.2 and later still own implementing
those clauses; the architecture decision is the contract they build from, not
an implementation-status report.

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

## Auto Run Result

Status: review (not `done`: the wave's build-auto customization and the build
prompt both end this story at `review`, for the Codex `bmad-code-review` lane).

**Implemented.** `llm.roles.<role>` declares `catalog[]` of
`binding` / `label` / `provider` plus a `default`, validated when `config.yaml`
loads. Two headline refusals, both raised from `Settings` validation — the layer
`load_config` wraps into the named `ConfigError`: a `default` outside its own
catalog, and an authored catalog entry naming a provider `providers:` does not
declare. Two more keep the second honest, on authored entries only: a tag with
no `<provider>/` prefix must name its provider, and a written provider may not
contradict the prefix the tag carries. A role declaring only `model` still
loads, as a one-entry catalog that retains any provider derivable from its tag
but is marked internally and skipped by the authored-entry provider check.
Declaration only — `model` remains what `build_llm`,
`resolve_api_base` and `_role_view` read; no call path changed.

**Files changed**

- `server/meetingminer/config.py` — `_provider_prefix`, `CatalogEntry`, the
  `catalog`/`default` fields and their two validators on `LlmRoleBinding`, and
  the catalog×providers cross-check on `Settings` (placed with the `providers`
  field, not the class tail, which story 6-2 appends to).
- `server/tests/test_config_catalog.py` — NEW; 13 tests covering every
  I/O-matrix row, the committed file, and the back-compat and active-model
  review regressions.
- `server/tests/test_failfast.py` — fixture only; drops the authored catalogs
  along with the provider it removes. Outside the build prompt's footprint,
  recorded in the Spec Change Log.
- `config.yaml` — `catalog:`/`default:` as the first keys of all three role
  blocks; every `default` equals the `model` that role already ran.
- `docs/architecture.md` — AD-10's binding sentence.
- `project-context.md` — the binding policy line.
- `_bmad-output/implementation-artifacts/` — this spec, `epic-8-context.md`,
  `sprint-status.yaml`, `sprint-notes.md`, the review prompt.

**Review findings.** 6 patched (1 high, 2 medium, 3 low), 7 deferred (see
frontmatter), 9 rejected. Follow-up review recommended: **true** — a `high`
finding was patched.

**Verification performed** (every command run in the foreground, output read)

- `uv run --project server pytest server/tests/test_config_catalog.py server/tests/test_config.py -q` → 67 passed.
- `uv run --project server pytest -m "" server/tests/test_failfast.py -q` → 12 passed.
- `make test-fast` → 1411 passed, 326 deselected, **zero skips**; evals 549 passed.
- `make test` → **1739 passed**, 9m28s, plus the web build (`tsc -b && vite build`) clean.
  The first run of this gate **failed** on the embedder fail-fast test; that
  failure is the Spec Change Log's first entry and is fixed.
- `python3 _bmad/scripts/branch_conflicts.py --against story/8-1` → see below.
- Both Ollama tags in the committed catalogs were checked against the live
  `providers.ollama` endpoint with `/api/tags`: `gpt-oss:120b` and `qwen3:30b`
  are both served there, so no catalog entry offers a binding that endpoint
  cannot answer.

**Residual risks**

- `docs/architecture.md` conflicts with `story/11-2` — the same AD-10 paragraph,
  a different sentence. Pre-declared by the owner in `sprint-notes.md` as
  integrate's to union; 11-2's environment-variable sentence is untouched here.
- The `_bmad-output` process files (`sprint-notes.md` and two other lanes'
  records) conflict as they already do against `main` itself; integrate absorbs
  them.
