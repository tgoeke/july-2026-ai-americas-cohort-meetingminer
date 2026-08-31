# Epic 8 Context: Choose the Model

<!-- Generated from planning artifacts. Regenerate with compile-epic-context if planning docs change. -->

## Goal

A user picks which model answers questions and which model extracts artifacts, choosing only from a catalog the config file declares per LLM role, with each provider's key health shown beside the choice. Today the config file is the sole binding source and the UI's only advice is "edit the file and restart"; this epic opens a bounded choice inside that boundary — the file still declares what is allowed and what the default is, while a persisted user selection picks among the allowed entries and is what the system actually calls. It matters because the demo corpus mixes local and hosted providers whose keys come and go: the user needs to steer the model without editing YAML, and needs a bad key or a failing binding to be visible before asking rather than discovered as a silent degradation.

## Stories

- Story 8.1: AD-10 amendment and binding catalog
- Story 8.2: Persisted selection
- Story 8.2a: Provider health on the status surface
- Story 8.3: Model picker UI

## Requirements & Constraints

- Per LLM role, the config declares a catalog of allowed bindings and a default. The api serves the catalog, persists the user's selection as user-declared data, and that selection is what chat resolves per request and the worker resolves per job. The effective binding is recorded in every eval run's config snapshot, beside the file value.
- Nothing outside the catalog can be selected. A selection request naming a binding not in the role's catalog is refused.
- **No selection is a fallback.** When a selected binding fails at call time, the failure surfaces as a named error at the point of use — never a substituted model, never a silently degraded answer. This is an owner-level rule, not a preference.
- The status surface reports key validity per configured provider and the active binding per role. Key probing uses free provider endpoints only (a model listing, never a completion) and is cached between polls — no money may be spent to render a status page.
- No fragment of any API key may serialize into any response, log, or UI surface. Secrets stay in environment variables; the config file carries bindings and endpoints only.
- Backward compatibility: existing single-model role declarations must still load, treated as a one-entry catalog.
- Fail closed at load: a default outside its catalog, or a catalog entry naming an undeclared provider, is a named startup error before any partial boot.
- Documentation is part of the deliverable: the architecture decision text, the repo's agent-instruction policy line about bindings, and a stale config comment about a previously revoked key all change with the amendment.
- Anthropic model ids and parameters must be taken from the `claude-api` reference at build time, never from memory.

## Technical Decisions

- **Ports, not SDKs (AD-8).** All model calls go through the project's own `Llm` port with the binding supplied by config. Provider SDKs never appear in feature code, so adding a catalog entry stays a config edit. The embedder is explicitly outside this epic's choice surface: its model and dimension are projection state, and changing either forces a full rebuild.
- **One config file (AD-10, amended by this epic).** The file remains the single declaration of every adapter binding, model, threshold, and endpoint. The amendment adds, for LLM roles only, the catalog a user may choose between plus the default; the user's pick lives in Postgres, not in the file. The eval harness continues to snapshot the resolved config into every run, now recording both the file value and the effective binding so any run stays reproducible.
- **Table ownership is disjoint (AD-5).** The selection is user-declared data, so the api owns the table and the migration; the worker only reads it when resolving a role for a job. The worker never writes it.
- **Error shape.** Every api error body is `application/problem+json`. A failing binding gets its own problem type carrying the provider, the binding, and the upstream status in the detail, so the UI can name the provider and the remediation rather than showing a generic failure.
- **Resolution timing differs by caller.** Chat resolves the selection per request (a change takes effect on the next question); the worker resolves per job (a change takes effect on the next extraction job). Neither caches a binding across that boundary.
- **Provider entries** in config carry base URLs per provider; a role may override the endpoint for its own binding. Roles today include extraction, chat, and judge; extraction is bound to a local model by default so no paid provider is reachable from the committed file.
- Related known gaps, useful context but not in scope: synthesized legacy
  entries and the live `fallback` remain exempt from the authored-catalog
  provider check; bindings are not probed against an endpoint's model list at
  startup; and the legacy `model` field still accepts empty/whitespace strings.

## UX & Interaction Patterns

- Model selection appears in exactly two places: inside the ask box (so the choice is one click from where a question is typed) and on the settings page, first inside each LLM role's section.
- The picker's trigger reads role, binding, provider, and a health dot plus the health *word* — never a dot alone. Its accessible name includes the health word; the dot itself is hidden from assistive technology.
- The popover is a single-select listbox grouped by provider. Each option shows a label and its binding with that provider's health, joined by exact provider id. The active binding is marked as selected, not with a text character.
- An option whose provider key is missing or invalid stays **selectable** and is rendered muted with its remediation attached as a description. It is deliberately not disabled: choosing it must fail loudly at the ask, not be quietly filtered out of the list.
- Degenerate catalogs render honestly: a one-entry catalog still shows the select (no "choose" affordance is invented); an empty catalog shows the trigger with a message naming the file to edit and the restart, and invents no default.
- A binding failure renders as an in-place refusal box in the answer region — rule name, detail, remediation — with the previous answer left intact. Never a toast.
- Selection is persisted immediately on choice; rapid successive selections must not let an older response overwrite the latest choice.
- Keyboard: arrows move, Enter selects, Esc closes and returns focus to the trigger.

## Cross-Story Dependencies

- 8.1 gates everything: the catalog schema and loader validation must exist before a selection can reference a catalog entry.
- 8.2 gates 8.2a and 8.3: the status surface reports the active binding *as resolved from* the persisted selection, and the UI reads the catalog-and-selection endpoint and writes through the selection endpoint.
- 8.3 consumes the UX design spec produced in Epic 6 (story 6.1) as its design companion; deviations must be recorded with a reason in the story's spec.
- 8.2 touches the Epic 5 eval harness (run snapshot must record effective bindings) and the existing status surface, which is why the amendment is the highest-risk item in this epic — it reaches api, worker, status, and eval at once.
- Epic 9 (close-out walkthrough) exercises this epic end to end on real data; the model picker and provider health are on the recorded demo path.
