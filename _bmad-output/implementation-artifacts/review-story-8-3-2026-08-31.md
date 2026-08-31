# Code Review — Story 8.3: Model Picker UI

- Review date: 2026-08-31
- Branch reviewed: `story/8-3`
- Review branch: `story/8-3-review`
- Reviewed range: `3211a7f..54d6142`
- Spec: `_bmad-output/implementation-artifacts/spec-8-3-model-picker-ui.md`
- Status: findings confirmed; remediation in progress

## Verdict

Does not pass as built. Eleven patchable findings require remediation. One
accessibility/composition conflict is open because the frozen story contract
and the adopted experience spine require incompatible DOM placement.

## Findings

### F1 — Selection ownership is component-local, so the two surfaces and Postgres can disagree — high — patch

**Sources:** blind-hunter + edge-case-hunter + verification-gap + acceptance-auditor.

`web/src/features/settings/useModelSettings.ts:60-184` gives every hook instance
private reads, generations and visible state. `App.tsx:195-209` keeps the ask
box mounted while Settings mounts a second hook at
`SettingsPage.tsx:132-136`, so a successful Settings selection updates only
Settings while the persistent ask trigger continues naming the old binding.
The next chat request reads the new Postgres row per request
(`server/meetingminer/api/chat.py:1161-1168`), making the trigger lie.

The same local generation rule discards stale responses but does not order the
unconditional UPSERTs at `server/meetingminer/domain/model_selection.py:243-269`.
If PUT 2 commits before PUT 1, the UI keeps PUT 2 while Postgres ends on PUT 1.
The current rapid-click test controls response order but has no mutable backing
store, so it proves only stale rendering. The fix must share selection events
across mounted surfaces and serialize writes per role so issue order is commit
order; different roles must remain independent.

**Status:** confirmed — patch pending, red-first.

### F2 — A failed or malformed PUT can make a false binding claim or inject a returned role — medium — patch

**Sources:** blind-hunter + edge-case-hunter + acceptance-auditor.

`useModelSettings.ts:140-180` has no selection timeout or abort signal. A
rejected transport can occur after the server committed, yet the refusal says
the api did not accept the choice and is still bound to the old value. A 200
response is also trusted without verifying `data.role === requestedRole`; on
the Settings surface a malformed response can replace `chat` with `judge`,
creating a control the client did not receive from the catalog read. The fix
must time-bound the request, distinguish an HTTP refusal from an unconfirmed
transport outcome, name the attempted binding, and refuse a mismatched role
response without moving the check or adding a role.

**Status:** confirmed — patch pending, red-first.

### F3 — Provider-wide worst-row health makes a role-specific endpoint failure sound universal — medium — patch

**Sources:** blind-hunter + edge-case-hunter + acceptance-auditor.

`web/src/features/settings/models.ts:115-157` calls a present-but-degraded role
`unreachable`, then joins the worst row by provider id. An unreachable
extraction-only Ollama `base_url` therefore mutes chat's Ollama option with a
remediation sentence naming extraction's host. The word and its remediation
contradict the evidence. Credential `missing`/`invalid` is provider-wide;
reachability and `ok` are role-endpoint evidence. The client can mitigate B-42
now by using role+provider evidence for reachability while preserving
provider-wide credential facts and reporting unobserved alternatives as
`unknown`. B-42 remains the server-side completion for direct per-provider
health.

**Status:** confirmed — patch pending, red-first.

### F4 — The ask popover omits its required provider groups and Settings route — medium — patch

**Sources:** blind-hunter + acceptance-auditor.

`ModelSelect.tsx:184-216` renders a flat option list. `EXPERIENCE.md` requires a
named `group` per provider and the mockup already has two providers; it also
defines `All roles… (Settings)` as the route from the popover to `/settings`.
Neither is present. Grouping must preserve the api's catalog order rather than
sorting it.

**Status:** confirmed — patch pending, red-first.

### F5 — The popover can render off-screen or below its own messages — medium — patch

**Source:** blind-hunter.

`ModelSelect.tsx:145-250` makes the whole trigger/message column the absolute
positioning block, then places the popover at `left-0 top-full`. In the right
side of the two-column ask layout it expands toward the viewport edge; when a
source, stale, pending or refusal sentence is present, `top-full` is below all
of those messages rather than directly below the trigger. A larger legitimate
catalog also has no maximum height or scroll. The trigger/popover need their
own right-aligned positioning wrapper and a bounded scrolling list.

**Status:** confirmed — patch pending, red-first.

### F6 — StrictMode can let an aborted first read overwrite the second mount — medium — patch

**Source:** blind-hunter.

Both read effects use the shared `mounted` ref at
`useModelSettings.ts:69-129`. StrictMode cleans up the first effect pass, then
the second setup sets the same ref true; a first-pass fetch that settles after
that can update the second pass with stale data or a spurious failure. Each
read needs request-local ownership (including an aborted-signal check), not a
shared mount bit.

**Status:** confirmed — patch pending, red-first.

### F7 — Selection refusals omit the rule-first contract and do not return focus — medium — patch

**Source:** acceptance-auditor.

`useModelSettings.ts:148-176` flattens Problem Details through
`problemMessage()`, losing the `binding-not-in-catalog`/`role-file-only` slug.
`selectionRefusal()` then begins with generic prose despite the component's
comment claiming the rule is first. `ModelSelect.tsx:116-140,208-211` leaves a
clicked or Enter-selected request in the open listbox, so a later refusal does
not appear while focus remains on the trigger as the adopted refusal pattern
requires. The fix must preserve the problem slug and close/refocus the picker
when selection starts.

**Status:** confirmed — patch pending, red-first.

### F8 — Unknown health still draws a status dot it cannot support — low — patch

**Sources:** blind-hunter + verification-gap.

`ModelOptionRow.tsx:25-33` and `ModelSelect.tsx:169-175` render `●` for
`unknown`. The implementation comments and the story contract explicitly say
an unread status draws no dot it cannot support. Unknown must remain an
unmuted word with no dot; failed and ok states keep dot+word.

**Status:** confirmed — patch pending, red-first.

### F9 — Option names expose decorative separators and repeat their description — low — patch

**Source:** acceptance-auditor.

`ModelOptionRow.tsx:53-68` leaves the visible `·` and `→` inside the computed
name of each `role=option`, while `aria-description` repeats provider, traits,
health and remediation. The Accessibility Floor hides those decorative glyphs.
Each option needs a deliberate name containing its label, exact binding and
health, with provider traits/remediation carried once as its description.

**Status:** confirmed — patch pending, red-first.

### F10 — Settings copy implies judge is editable and omits the eval-snapshot fact — medium — patch

**Source:** acceptance-auditor.

`web/src/features/settings/settings.ts:34-38` exempts “the model bound to each
LLM role,” while the read-only LLM section can show file-only judge and the
editable block correctly cannot. The exception must be scoped to roles the api
offers in “Model per role.” The adopted traceability contract also requires the
Settings sentence that every eval snapshot records the effective binding
beside the file value; `ModelRoles.tsx` does not render it. Selection copy must
continue to carry no restart instruction, while catalog copy keeps the api
startup-snapshot restart path.

**Status:** confirmed — patch pending, red-first.

### F11 — Modified fetch routers weaken existing regression tests and named ownership cases are absent — medium — patch

**Sources:** blind-hunter + verification-gap + acceptance-auditor.

`ChatPanel.test.tsx:95-133` treats every `Request` object as a picker read, so a
future Request-shaped `/chat` call bypasses the one-request assertion. No
ChatPanel assertion requires the picker to be mounted.
`SettingsPage.test.tsx:134-159` returns the config payload for every
unrecognized URL. The ownership
suite also omits the handoff's required two-role concurrency, unmount during a
PUT, rejected PUT, rendered muted state, and served-provider/binding-prefix
disagreement cases. Routers must classify exact paths and fail closed; the
named cases need regressions that are observed red against the original code.

**Status:** confirmed — patch pending, red-first.

### F12 — Header-row placement conflicts with the required ask-box DOM order — medium — decision needed

**Source:** acceptance-auditor.

`EXPERIENCE.md` Accessibility Floor requires ask-box DOM order `textarea →
model select → Ask button`, but the frozen Story 8.3 code map and boundary
require one model-select element in `ChatPanel`'s header row. The implementation
at `ChatPanel.tsx:176-205` follows the frozen header-row requirement and
therefore precedes the textarea in DOM order. Meeting both would restructure
the ask-box composition owned by Story 10.5, which this story explicitly must
not do.

**Status:** open — owner must choose whether the frozen header-row placement or
the adopted DOM-order sentence wins. No patch is authorized inside this story.

## Deferred-item confirmation

- **B-42:** confirmed. The provider-wide `unreachable` word is broader than the
  role-endpoint evidence and its worst-row remediation can contradict the
  option. F3 will remove that false client claim; B-42 remains open for the
  server's direct provider-health array and complete health for alternatives.
- **B-43:** correctly deferred. Preserving a prior cited answer for a
  `binding-failed` chat response changes ChatPanel's shared failure taxonomy,
  outside the picker insertion and inside the filed backlog item.
- **Hand-rolled popover:** defensible for this story once F4/F5/F7 are fixed.
  It already implements the required listbox ownership, arrows, Enter, Esc,
  outside dismissal and no focus trap; adopting Base UI remains a shell-level
  pattern decision.
- **Judge boundary:** confirmed. The client renders only roles the api serves,
  does not synthesize judge, and does not assume chat is present. A payload that
  names judge is the api crossing its own boundary and is intentionally
  rendered; F2 prevents a malformed PUT response from adding one locally.
- **Settings list keyboard model:** accepted as built for this story. Each
  option is a real focusable button, matching the mockup; the spine's explicit
  `aria-activedescendant`/arrow-key mandate is scoped to the popover.

## Verification

Pending.
