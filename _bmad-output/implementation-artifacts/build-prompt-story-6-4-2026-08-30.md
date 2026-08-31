# Builder handoff — Story 6.4: Acquisition Launch Surface

Agent: `bmad-build-auto`. Worktree `../meetingminer-wt/6-4`, branch `story/6-4`,
cut from current `main`. Story: `epics.md` → "Story 6.4: Acquisition Launch
Surface" (FR34), four Given/When/Then clauses. Stories 6.4a, 6.5 and 6.5a are
NOT in scope.

**Stories 6.2, 6.2a and 6.3 have landed** — `server/meetingminer/youtube.py`
and `mintdrop.py` on `main` are your foundation. Read them first.

## The point of this story

The api **accepts and reports on** an acquisition; it does not perform one.
The tool runs as a detached host process. If you find yourself downloading
media inside a request handler, you have built the wrong thing.

## Footprint

| Path | Allowed edit |
|---|---|
| `server/meetingminer/api/acquisitions.py` | NEW. All three routes. Registration is auto-discovered (story 2.8) — adding the file is enough; never hand-edit `api/main.py` or a registry. |
| `server/meetingminer/youtube.py` | A probe-only entry point that runs 6.2's URL, availability, stream, tool and duration checks **without** downloading media, minting a drop, starting a process, or writing acquisition state. Reuse 6.2's existing checks; do not fork them. |
| a new module for the launcher/status-file handling | NEW. Detached process, per-acquisition status file and log under `.logs/`. |
| `server/tests/test_api_acquisitions.py` (+ fixtures) | NEW. All coverage here. |

Not yours: `mintdrop.py`, `config.py` beyond what 6.2 already added, anything
under `web/`, `conftest.py`.

## Contract details that will be got wrong if not named

- **`POST /acquisitions`** answers **202** with an acquisition id and refuses a
  second running acquisition **for the same source id** with a conflict.
- **`POST /acquisitions/probe`** returns `{title, durationMs, captions: {kind,
  language}, sourceId}` on success. Refusal is **RFC 9457 Problem Details**
  carrying stable `rule`, `detail` and `remediation`. Story 6.2a already gave
  `YoutubeError` an optional `rule=` at every raise site with a closed,
  test-pinned vocabulary — **use that vocabulary; do not invent a second one.**
- **`GET /acquisitions/{id}`** reports `queued | running | posted | failed`
  from the status file with the log tail. `posted` carries `result: created |
  exists`, the job id and meeting id from or resolved around `POST /ingests`,
  and `source: {sourceId, tool, toolVersion}`. **6.2's `exists` short-circuit
  maps to `posted` with `result: exists` and the existing ids, with no media
  network traffic** — test that no download occurs.
- **`failed` carries `refusal: {rule, detail, remediation}`.** The web client
  must never have to parse the log tail to learn why something failed. That is
  the clause most likely to be skipped; test it directly.
- Tests must not reach the network. Any live test is env-flagged and skipped by
  default, exactly as 6.2's network test is.

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
