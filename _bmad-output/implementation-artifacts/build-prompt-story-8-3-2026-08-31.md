# Builder handoff — Story 8.3: Model Picker UI

Agent: `bmad-build-auto`. Worktree `../meetingminer-wt/8-3`, branch
`story/8-3`, from current `main`. Story: `epics.md` Story 8.3.
Mockup: `_bmad-output/planning-artifacts/ux-designs/ux-meetingminer-2026-08-29/mockups/ask-box-model-select.html`.

**Stories 8.1 and 8.2 landed today.** `GET /settings/models` serves the
catalog with the active selection and `PUT /settings/roles/{role}` persists a
choice; both are already in the generated TS client. A binding outside the
catalog is refused, and a failed binding surfaces as RFC 9457
`urn:meetingminer:problem:binding-failed`.

## Footprint

| Path | Edit |
|---|---|
| `web/src/features/settings/` or a model-select component — new files | The popover. |
| the ask box — minimal insertion only | Mount the trigger. Do not restructure the chrome; story 10.5 owns the shell. |
| `web/src/**` tests — NEW files | Fixture-driven. |

## Clauses that carry the risk

- **`judge` is deliberately absent from the settings surface** (owner decision,
  story 8.2): it is file-only until a later story wires it, and `PUT` on it is
  refused by name. Do not add it back.
- **The picker must not mislead about what is being called.** The provider
  shown is derived from one shared rule, never a hand-typed label — that was an
  explicit owner ruling. `ollama/...` means local and free; `openai/...`
  means remote and paid. Make that legible.
- **A failed binding surfaces where it happens**, not hidden by the picker: an
  entry whose provider is unavailable renders muted with its remediation and
  stays selectable.
- **No other model is ever substituted** for a failed selection.

## Standing rules

Read `wave-2026-08-30-rules.md` in this directory. Private Docker stack per
worktree — `make bootstrap` first, `uv sync --project server` before
`make lint`. `make test-fast` runs lint and typecheck and your branch cannot
land until both pass. New tests in NEW files. `sprint-notes.md` has no merge
driver: short entry, expect a union. Backlog ids are a shared counter — file in
`docs/backlog.md` or it does not exist; highest in use is **B-40**.

**Design source of truth:** `_bmad-output/planning-artifacts/ux-designs/ux-meetingminer-2026-08-29/DESIGN.md` and `EXPERIENCE.md`, with the
mockup named below. The spines win where a mockup disagrees with them.

**This is demo-critical with a hard deadline of early afternoon 2026-08-31.**
Build the acceptance criteria and nothing more; file anything adjacent.

## Completion

Spec `status: review`, sprint keys set, `review-prompt-story-<id>-<date>.md`
written stating **the review lane fixes what it finds**, everything pushed.
Report SHAs and real verification output. Do not merge, do not mark done.
