# Builder handoff — Story 8.2: Persisted Selection

Agent: `bmad-build-auto`. Worktree `../meetingminer-wt/8-2`, branch `story/8-2`,
cut from current `main`. Story: `epics.md` → "Story 8.2: Persisted Selection"
(FR38, FR39), three Given/When/Then clauses. Stories 8.2a and 8.3 are NOT in
scope.

**Story 8.1 has landed.** `config.yaml` now declares a per-role `catalog[]` and
`default`, and — this is the part that shapes your work —
`server/meetingminer/domain/model_providers.py` holds the **single** rule for
which provider serves a model. `api/status.py` aliases it deliberately so
config, call-time resolution and the display surface run the same function
object. **Use that one rule. Do not add a second.**

## Footprint

| Path | Allowed edit |
|---|---|
| `server/meetingminer/migrations/0016_app_setting.sql` | NEW. **`0015` belongs to story 10.2, in review and landing first — take `0016`.** An api-owned table; label it as such the way 0014 labels worker-owned rows. |
| `server/meetingminer/api/settings.py` | NEW. `PUT /settings/roles/{role}` and `GET /settings/models`. Auto-discovered; never hand-edit `api/main.py`. |
| the role-resolution path | Chat reads the selection **per request**, the worker **per job**. |
| the eval snapshot | Record the **effective** binding beside the file value. |
| `server/tests/test_api_settings.py`, `server/tests/test_settings_resolution.py` | NEW. All coverage here. |
| `web/src/client/` | Regenerate only if the schema changes, from the in-process schema. |

Not yours: `config.py`'s catalog model (8.1 owns it), `domain/model_providers.py`
(use it, don't change it), anything under `web/` beyond the generated client.

## The clause that carries an owner ruling

The third AC is the owner's standing rule in story form: when a selected
binding fails at call time it surfaces as RFC 9457 type
`urn:meetingminer:problem:binding-failed` with `provider`, `binding`, and the
upstream status in `detail` — and **no other model is substituted**. Silently
answering from a different model is the silent fallback this project has
rejected by explicit owner decision. Pin "no substitution" with a test.

**Close backlog B-38 as part of this story.** B-38 ("Fail loudly when a
provider does not serve the configured model", filed by story 8.1) is the same
requirement reached from the other direction: a model-not-found must name the
provider actually called, the endpoint URL, and the model asked for, and must
never engage the fallback. Implement it here, mark B-38 closed in
`docs/backlog.md` with the commit that closed it, and say so in your report.
Genuine host outages keep the existing `LlmUnavailableError` fallback — that
one is deliberate.

**A selection must never name a binding outside its role's catalog** — refused
on write, and re-checked on read in case the catalog changed under it.

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
