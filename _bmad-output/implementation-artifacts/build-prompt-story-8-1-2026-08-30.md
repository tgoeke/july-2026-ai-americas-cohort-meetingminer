# Builder handoff — Story 8.1: AD-10 Amendment and Binding Catalog

Agent: `bmad-build-auto`. Read `wave-2026-08-30-rules.md` in this directory
first (wave-wide rules and the conflict check), then this file.

- Repository: `/Users/devopsterus/current/cohort/meetingminer`
- Worktree: `../meetingminer-wt/8-1`, branch `story/8-1`, cut from current `main`
- Story: `_bmad-output/planning-artifacts/epics.md` → "Story 8.1: AD-10
  Amendment and Binding Catalog" (FR38). Two Given/When/Then clauses. Stories
  8.2 / 8.2a / 8.3 (persisted selection, provider health, picker UI) are NOT
  in scope — this story stops at the config contract.

## Why this is launchable beside six in-flight lanes

Measured, not assumed: `story/11-2` rewrote AD-10's *environment-variable*
sentence; you rewrite its *binding* sentence. `story/10-1` adds
`topics_prompt` inside `ExtractionRoleBinding`; you add fields to
`LlmRoleBinding`. `story/7-1` owns `DiarizerConfig`; `story/6-2` appends
`acquisition` at the tail of `Settings`. Your footprint is disjoint from all
of them — keep it that way.

## Footprint

| Path | Allowed edit |
|---|---|
| `server/meetingminer/config.py` | NEW class `CatalogEntry` (`binding`, `label`, `provider`) inserted immediately BEFORE `class LlmRoleBinding`; `catalog: list[CatalogEntry]` and `default` added to `LlmRoleBinding` only. Do NOT touch `ExtractionRoleBinding`, `DiarizerConfig`, `LlmRoles`, or the tail of `Settings` — three other lanes own those exact regions. |
| `config.yaml` | Inside each `llm.roles.<role>` block, add `catalog:` and `default:` as the FIRST keys of that block. Do not reorder or reflow the existing keys, and do not touch the end of the file. |
| `docs/architecture.md` | AD-10 only, and only its binding sentence plus the catalog wording. **Rebase onto `origin/main` first and preserve 11-2's environment-variable sentence verbatim** — it is a different sentence in the same paragraph. |
| `project-context.md` | The one policy line about bindings. Nothing else. |
| `server/tests/test_config_catalog.py` | NEW. All coverage lives here — never append to `test_config.py`. |
| `_bmad-output/implementation-artifacts/` | Your spec, `sprint-status.yaml`, `sprint-notes.md`, `review-prompt-story-8-1-<date>.md`. |

## Two contract details

1. **Fail closed, fail named**: the loader refuses a `default` outside its
   catalog and a catalog binding naming an undeclared provider; an existing
   single-`model` file still loads as a one-entry catalog. Both refusals get
   a test naming the exact message.
2. **The AC's third clause is likely already satisfied**: it asks you to
   remove "the stale chat comment about the revoked key", but no `revoked`
   text remains in `config.yaml` or `config.py` (the key was restored
   2026-08-29). Verify, then record it as already-satisfied in the spec —
   do not invent work to fill the clause.

## Verification

- `uv run --project server pytest server/tests/test_config_catalog.py -q`
- `make test-fast`; `make test` once before `review`.
- `python3 _bmad/scripts/branch_conflicts.py --against story/8-1` — clean
  against `main` and every `story/*` lane except `_bmad-output` process-file
  appends and `*-review` pairs, which integrate absorbs.

## Completion

Spec `status: review`, `8-1-ad-10-amendment-and-binding-catalog: review` and
`epic-8: in-progress` in `sprint-status.yaml`, review prompt written, all
pushed, SHAs reported. Do not merge, do not mark done.
