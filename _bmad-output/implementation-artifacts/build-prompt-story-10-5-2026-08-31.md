# Builder handoff — Story 10.5: Moments View and Front Door

Agent: `bmad-build-auto`. Worktree `../meetingminer-wt/10-5`, branch
`story/10-5`, from current `main`. Story: `epics.md` line 1777.
Mockup: `_bmad-output/planning-artifacts/ux-designs/ux-meetingminer-2026-08-29/mockups/moments.html`.

**This is the demo's opening screen — the owner has made it non-negotiable.**

## You own the shell; story 10.6 does not

You recompose the front door: **Moments is the default route, Threads the
second primary view**, Meetings/Participants/Status/Settings stay reachable
from the chrome, search and ask stay persistent, and the shell applies the dark
theme class the design specifies. Create the **Threads route as a placeholder**
— story 10.6 is building that screen in parallel and will fill it. Do not build
the Threads screen yourself, and do not edit files under a threads feature
directory.

Story 8.3 (model picker) and 7.4 (speaker naming) are also building against
this shell. Keep your shell edits to routing, navigation and theme; do not
restructure the ask box or the meeting view.

## Footprint

| Path | Edit |
|---|---|
| `web/src/features/moments/` — new files | The ranked moment cards. |
| the shell / route registry | Moments default, Threads second, chrome intact. Routes are auto-discovered `*.route.tsx` (story 2.8) — adding a file is enough. |
| `web/src/**` tests — NEW files | Fixture-driven. |

## Clauses that carry the risk

- **Cards show** screenshot, meeting and offset, the stated reason, thread
  chips; each replays in place and links to its moment and meeting. Filters for
  corpus, thread and kind.
- **Nothing regresses**: the corpus counts and meeting cards of the reimagined
  home stay reachable (a Meetings view or panel), and **the existing demo path
  and web tests stay green** — that is an explicit acceptance clause.
- **The shell's child-screen placement is pinned by a test** (closes backlog
  B-13).
- **The API (`GET /moments/feed`, story 10.4) is being built in parallel.**
  Code against the field names in 10.4's acceptance criteria —
  `{items, total, limit, offset}`, each item with `momentId`, `meetingId`,
  `meetingTitle`, `startedAt`, `startMs`, `corpus`, `hasRecording`,
  `screenshotId`, `viewType`, `preview`, `threads[]{threadId,name,colorOrdinal}`
  and an ordered `reasons[]` of `{kind,label,ref?,at?}` — and test against
  fixtures. Do not block on the API existing.

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
