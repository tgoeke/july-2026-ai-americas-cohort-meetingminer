# Builder handoff — Story 7.2: Speaker Tags on the Wire

Agent: `bmad-build-auto`.

- Worktree: `../meetingminer-wt/7-2`, branch `story/7-2`, cut from current `main`
- Story: `_bmad-output/planning-artifacts/epics.md` → "Story 7.2: Speaker Tags
  on the Wire" (FR36). Two Given/When/Then clauses. Stories 7.3 (assignment)
  and 7.4 (naming UI) are NOT in scope — this story only *exposes* what exists.
- **Story 7.1 has landed**: the `Diarizer` port has a real pyannote engine
  behind the optional `diarize` extra, `noop` remains the default, and
  `speaker_at` stamps `SPEAKER_NN` tags onto transcript segments. You are
  putting those tags on the wire.

## Footprint

| Path | Allowed edit |
|---|---|
| `server/meetingminer/api/speakers.py` | NEW. `GET /meetings/{id}/speakers`, read-only. Registration is auto-discovered (story 2.8) — adding the file is enough, do NOT edit `api/main.py` or any registry by hand. |
| `server/meetingminer/domain/` or a new module | Only if the aggregation (talk time, segment count, sample offsets) needs a home outside the route. Prefer a new module over editing a shared one. |
| `server/tests/test_api_speakers.py` | NEW. All coverage here. |
| `web/src/client/` | Regenerate ONLY if the OpenAPI schema changes, and regenerate from the in-process schema (the story 2.2 pattern) — never point `make client` at a running api that serves another checkout. |
| `_bmad-output/implementation-artifacts/` | Your spec, tracking, review prompt. |

Not yours: `pipeline/speakers.py`, `pipeline/stages/transcribe.py`,
`adapters/diarize/**` — 7.1 owns the tag-producing side and this story must not
change it. No migration: everything you need is already stored.

## Contract details

- Each tag row: talk time, segment count, and **three sample offsets chosen
  from its longest segments**; every row carries nullable `participantId` and
  `displayName`, populated when the source or an alias resolves the label.
- The second clause is the subtle one: a meeting whose transcript **already
  carried real speaker names** (a Teams archive drop, or a Zoom transcript
  converted by story 6.3) must list each label as a resolved participant with
  the same talk time and sample offsets — **named and unnamed sources share one
  response shape**. Test both kinds of meeting.
- Never guess an identity: a `SPEAKER_NN` tag resolves to a participant only
  when the source or an alias says so (AD-13).

## Wave rules (this is a second wave — read the differences)

Read `wave-2026-08-30-rules.md` in this directory for the standing rules, then
these amendments, which come from what the first wave actually cost:

- **Your worktree owns a private Docker stack.** Story 11.2 landed: `make
  worktree` provisions `meetingminer-<slug>` on its own ports and writes
  `.env.worktree`. Suites in different worktrees no longer contend at all. Run
  `make bootstrap` first. `MM_STACK_NAME`/`MM_STACK_ID` are NOT overridable —
  do not try.
- **`make test-fast` now runs `make lint` and `make typecheck`** (story 11.4).
  Your branch cannot land until both pass. The ruff baseline is shrink-only, so
  fix real findings rather than widening it, and never sweep files outside your
  footprint. Run `uv sync --project server` in your worktree before `make lint`.
- **Two lint rules bite new code and are worth knowing up front**: `ISC004`
  wants implicit string concatenations inside list/tuple literals wrapped in
  parentheses (it cannot tell a deliberate multi-line string from a forgotten
  comma), and `DTZ` rules flag naive datetimes. If a finding is a genuine false
  positive, add a `# noqa: <CODE>` with a one-line rationale — never silently.
- **`sprint-notes.md` has no merge driver.** Keep your entry short and at the
  end; expect integrate to union it.
- **Backlog ids are a shared counter.** If you file one, take the next free id
  and say in your report that you took it — two lanes both grabbed `B-35` last
  wave. Highest currently used: **B-37**.
- **Do not flip `sprint-status.yaml` and assume it sticks** — say the final
  status in your report so integrate can verify it after the rebase.
- New tests go in NEW files. Never append to `conftest.py`,
  `test_compose_contract.py`, `test_config.py`, or another lane's module.

## Completion

Spec `status: review`, your sprint keys set, `review-prompt-story-<id>-<date>.md`
written (**the review lane fixes what it finds** — say so in the prompt; do not
copy the retired "report findings, do not fix" wording from older prompts in
this directory), everything committed and pushed. Report SHAs and the real
verification output. Do not merge to `main`, do not mark the story done.
