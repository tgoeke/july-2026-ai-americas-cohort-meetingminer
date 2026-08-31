# Reviewer handoff — Story 8.3: Model Picker UI

Branch under review: `story/8-3` (built 2026-08-31, from `main` at `3211a7f`).
Spec: `_bmad-output/implementation-artifacts/spec-8-3-model-picker-ui.md`
(`status: review`). Builder's contract:
`_bmad-output/implementation-artifacts/build-prompt-story-8-3-2026-08-31.md`.
Design source of truth:
`_bmad-output/planning-artifacts/ux-designs/ux-meetingminer-2026-08-29/`
— `DESIGN.md` § Components › model-select, `EXPERIENCE.md` § Model select /
Ask box / Flow 4, and `mockups/ask-box-model-select.html`.

## How this review works

**The review lane fixes what it finds.** Owner ruling, 2026-08-30.

Report every finding in the report file first — `review-story-8-3-<date>.md`,
committed before you read any code with fixing in mind — then FIX the patchable
ones yourself on `story/8-3-review` in your own worktree, red-first: the test
observed failing against the unfixed code, then the fix, then green, committing
each with its finding number. Leave unfixed, and clearly marked open, only what
needs an owner decision or is rooted in the frozen spec. Never commit to
`main`, never work in the main checkout, never merge — the owner runs
`integrate`.

Set up with `make worktree STORY=8-3-review BASE=story/8-3` from the main
checkout, then `make bootstrap` and `uv sync --project server` in it.

## What this story is

`GET /settings/models` and `PUT /settings/roles/{role}` landed in stories 8.1
and 8.2 and nothing rendered them. This story renders them twice: a popover in
the ask box's header row bound to the `chat` role, and a per-role list on the
Settings page. No server code changed, no migration, no `config.yaml` edit, and
`web/src/client/` is untouched.

Read in this order: `web/src/features/settings/models.ts` (every rule),
`useModelSettings.ts` (both reads, the one write, the ownership rule),
`ModelOptionRow.tsx`, `ModelSelect.tsx`, `ModelRoles.tsx`, then the two
insertions in `ChatPanel.tsx` and `SettingsPage.tsx`.

## The four clauses that carry the risk — audit these first

Three are owner rulings made on 2026-08-31. Attack each as a claim to be
falsified, not a box to tick.

1. **The judge is deliberately absent from the settings surface.** It is
   file-only until a later story wires it (B-41), and `PUT` on it is refused by
   name. Prove nothing in the web tree can produce a judge control, including
   through a payload that names it. Note the shape of the boundary: the client
   renders the roles the api serves, so the guarantee is the api's — check that
   the client cannot *add* one and does not assume `chat` is present either.
2. **The picker must not mislead about what is being called.** The provider is
   the server's derivation (`domain/model_providers.provider_for_model`),
   surfaced through `catalog[].provider`; locality and cost are keyed on that
   provider id in `PROVIDER_TRAITS`. Try to make the screen lie: a catalog
   label that contradicts its binding, a provider absent from the table, a
   `null` provider, a binding whose prefix disagrees with the served provider.
   The correct answer to an unclassified provider is *no claim*. Is that what
   happens on every path, including the trigger's accessible name?
3. **A failed binding surfaces where it happens.** `invalid`, `missing` and
   `unreachable` mute the row, show the api's remediation, and leave it
   selectable — never `aria-disabled`, never filtered, never reordered. Check
   the inverse too: `unknown` (status unread, or no role names the provider)
   must not mute and must not claim `ok`.
4. **No other model is ever substituted.** A refused or failed `PUT` must leave
   the ✓, the trigger and the effective binding exactly as the api last
   reported them. Look for any path — the generation counter, the `finally`
   block, an unmounted component, a role removed between reads — where a stale
   or partial response could move the ✓ or apply a default.

## Where to push hardest

- **`providerHealthIndex`'s join.** Health comes from `GET /status.llmRoles[]`
  joined by provider id, because story 8.2a's `providers[]` does not exist. The
  builder filed the known overstatement as **B-42**: a role with its own
  `base_url` (extraction's Ollama host) can make every `ollama/…` option read
  `unreachable`. Decide whether the *word chosen* is defensible given the
  evidence, and whether the worst-row rule can produce a claim the api's own
  remediation sentence contradicts.
- **The asynchronous ownership rule.** Per-role generation counters in a ref.
  Test two roles selecting concurrently, a component unmounting mid-flight, and
  a `PUT` that rejects rather than resolving. `ModelSelect.test.tsx` covers the
  two-rapid-clicks case by holding both responses; find the case it does not.
- **The two edits to existing test files.** Both are in-footprint but both
  weaken or move an existing assertion, so read them as a reviewer of the
  *original* intent. `ChatPanel.test.tsx`'s stub now routes `Request`-shaped
  calls to a canned picker response so the one-request-per-question assertions
  survive; check it cannot mask a real second chat request.
  `SettingsPage.test.tsx`'s read-only assertion changed because the page did;
  check the new sentence is true of the page as built and that "no other edit
  control exists" still holds.
- **The Settings page's contract sentence.** `READ_ONLY_CONTRACT` now carries
  an exception. Is the wording accurate for every section, and is the picker
  genuinely outside the "file edit plus restart" change path?
- **Restart language.** The coordinator verified mid-build that a selection is
  a Postgres row read per request (live) while the catalog is the api's startup
  snapshot. Hunt for any copy that implies a restart is needed to apply a
  choice, or that presents an inherited `file-default` as a deliberate pick.
- **Accessibility.** `EXPERIENCE.md` § Model select specifies a focusable
  `listbox` with `aria-activedescendant`, the health word inside the accessible
  name, the `●` hidden, remediation as an accessible description, and Esc
  returning focus to the trigger. The mockup also groups options by provider
  with a labelled `group`; the build does not. Judge whether that omission
  matters for a two-entry catalog and record the verdict either way.

## Known-and-filed — confirm the reasoning, do not re-litigate silently

The spec's `deferred` block carries three, with evidence: the health join
(B-42), the `binding-failed` refusal box that would need to stop clearing the
previous answer (B-43, a change to chat's failure taxonomy rather than to the
picker), and the hand-rolled popover instead of the installed `@base-ui/react`
primitives. If you think any of them should have been done inside this story,
say so with the footprint argument, and fix it only if it is genuinely
patchable without touching the shell (story 10.5) or the meeting view (7.4).

## Gates

Run in the foreground and read real output; never pipe through `tail`.

- `make lint`, `make typecheck`, `make web-test`, `make test-fast`.
- `pnpm exec tsc -b --force` in `web/`.
- `python3 _bmad/scripts/branch_conflicts.py --against story/8-3-review` before
  every push — clean against `main` and every other `story/*`.

Builder's measurements to reproduce or refute: lint clean; mypy 13 files clean;
`web-test` 19 files / 340 tests passing; `test-fast` 2172 passed, 3 skipped,
411 deselected with one contention-only failure
(`test_frame_image.py::test_an_unreadable_frame_raises_a_named_error`, 2.15s
against the 2.00s budget under six concurrent worktree builds, 0.01s alone —
not this story's file, and the plugin's own message says contention is not a
reason to mark it slow).

**Never**: `make evals-run`, `make up`, starting or restarting the shared
api/worker, or calling any paid model. Every test here is fixture-driven
against a stubbed `fetch`; keep it that way.

## Finishing

Report file `review-story-8-3-<date>.md` with every finding numbered, each
fixed one naming its commit, each open one naming what decision it needs. Set
the spec's `review_loop_iteration`, and leave the sprint key at `review` unless
the owner says otherwise. Push `story/8-3-review`. Do not merge.
