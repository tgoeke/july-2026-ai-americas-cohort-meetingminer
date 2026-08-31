# Builder handoff — Story 7.4: Speaker Naming UI

Agent: `bmad-build-auto`. Worktree `../meetingminer-wt/7-4`, branch
`story/7-4`, from current `main`. Story: `epics.md` Story 7.4.
Mockup: `_bmad-output/planning-artifacts/ux-designs/ux-meetingminer-2026-08-29/mockups/speaker-naming.html`.

**Stories 7.1, 7.2 and 7.3 all landed today** and the whole chain is currently
invisible without this screen. Diarization now runs against a LAN GPU service
and produces `SPEAKER_NN` tags; `GET /meetings/{id}/speakers` serves them with
talk time, segment count and sample offsets; `PUT /meetings/{id}/speakers/{tag}`
accepts a participant id, a new display name, or `unresolved`. **Both
endpoints are already in the generated TS client** — no client regeneration
needed.

## Footprint

| Path | Edit |
|---|---|
| `web/src/features/speakers/` — new files | The naming panel. |
| the meeting view — minimal insertion only | Reach the panel. Do NOT restructure it; story 2.2 owns it. |
| `web/src/**` tests — NEW files | Fixture-driven. |

Story 10.5 owns the shell and 8.3 the ask box — touch neither.

## Clauses that carry the risk

- Assigning to an existing participant, a **new** display name, or
  `unresolved` — all three paths.
- **Never guess an identity** (AD-13): an unresolved tag stays
  `SPEAKER_NN` with resolution `placeholder`, and the UI must not present a
  guessed name as if the system knew it.
- A rename **re-arms the meeting's job** for `align → moments → extract`;
  surface that the meeting is reprocessing rather than appearing to hang.
- Story 7.3 admits the PUT even when a meeting's evidence is unsettled, so a
  curator can correct a failed rerun. **The UI must remain usable in that
  state** — that exception exists precisely so this screen still works.

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
