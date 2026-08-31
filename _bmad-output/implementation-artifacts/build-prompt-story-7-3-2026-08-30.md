# Builder handoff — Story 7.3: Speaker Assignment

Agent: `bmad-build-auto`. Worktree `../meetingminer-wt/7-3`, branch `story/7-3`,
cut from current `main`. Story: `epics.md` → "Story 7.3: Speaker Assignment"
(FR37), four Given/When/Then clauses. Story 7.4 (naming UI) is NOT in scope.

**Story 7.2 has landed**: `server/meetingminer/api/speakers.py` exists and
serves `GET /meetings/{meetingId}/speakers`. You add the write side to that
same file. Read it, and story 7.1's `speaker_at`, before designing anything.

## Footprint

| Path | Allowed edit |
|---|---|
| `server/meetingminer/api/speakers.py` | Add `PUT /meetings/{id}/speakers/{tag}`. Do not restructure the existing read route or its response shape — 7.2's one-shape criterion is pinned by tests. |
| alias/domain module | The `participant_alias` write in the `speaker:<meetingId>:<tag>` namespace (AD-5). Prefer a new module over editing a shared one. |
| the job re-arm path | Re-arm the meeting's job for **`align → moments → extract` only**. |
| `server/tests/test_api_speaker_assignment.py` | NEW. All coverage here — never append to `test_api_speakers.py`. |
| `web/src/client/` | Regenerate ONLY if the OpenAPI schema changes, from the in-process schema (the 2.2 / 7.2 pattern), never against a running api. |

Not yours: `pipeline/speakers.py`, `stages/transcribe.py`, `adapters/diarize/**`.

## The clause that matters most

**A rename must not break anything already cited or published.** After the
rerun, every pre-existing moment id, every citation, and every approved or
published artifact must still resolve — the AC requires this **pinned by a
test**, so write that test first and make it fail before the fix exists.
Extraction replaces **drafts only**; an approved or published artifact is never
replaced by a re-arm. This is the story's real risk: someone corrects a
speaker's name months later and silently invalidates a published citation.

Also: `unresolved` keeps the tag with `speaker_resolution` `placeholder` and
**no name is guessed** (AD-13). A tag resolves to a person only when the source
or an alias says so.

## Standing wave rules

Read `wave-2026-08-30-rules.md` in this directory. In short: your worktree owns
a private Docker stack (`make bootstrap` first, `uv sync --project server`
before `make lint`); `make test-fast` runs `make lint` and `make typecheck`, and
your branch cannot land until both pass; the ruff baseline is shrink-only, so
fix real findings rather than widening it and never sweep files outside your
footprint. `ISC004` wants implicit string concatenations inside list/tuple
literals parenthesised; a genuine false positive gets `# noqa: <CODE>` with a
one-line rationale, never a silent one. New tests go in NEW files — never
append to `conftest.py`, `test_config.py`, or `test_compose_contract.py`.
`sprint-notes.md` has no merge driver: keep your entry short, expect integrate
to union it. **Backlog ids are a shared counter and naming one in a spec does
not reserve it — file it in `docs/backlog.md` or it does not exist.** Highest
in use is B-38. Say your final sprint status in the report rather than assuming
the flip survives a rebase.

## Completion

Spec `status: review`, sprint keys set, `review-prompt-story-<id>-<date>.md`
written stating that **the review lane fixes what it finds** (do not copy the
retired "report findings, do not fix" wording from older prompts here),
everything committed and pushed. Report SHAs and real verification output. Do
not merge to `main`, do not mark the story done.
