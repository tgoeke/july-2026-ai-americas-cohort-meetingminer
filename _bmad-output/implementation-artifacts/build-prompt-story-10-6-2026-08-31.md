# Builder handoff — Story 10.6: Threads Zoomable Timeline

Agent: `bmad-build-auto`. Worktree `../meetingminer-wt/10-6`, branch
`story/10-6`, from current `main`. Story: `epics.md` line 1797.
Mockups: `_bmad-output/planning-artifacts/ux-designs/ux-meetingminer-2026-08-29/mockups/threads-bands.html` and `threads-moments.html`.

**The owner calls zooming a thread the best part of the demo, and has made it
non-negotiable.** This is the highest-value screen in the wave.

## Boundary with story 10.5

Story 10.5 owns the shell, routing and theme, and is creating a **Threads route
placeholder** for you. You own the Threads **screen** — build it in its own
feature directory and fill that route. Do not recompose the shell, the ask box
or navigation.

## Footprint

| Path | Edit |
|---|---|
| `web/src/features/threads/` — new files | Bands → meetings → moments, zoom and pan. |
| `web/src/**` tests — NEW files | Fixture data at each level. |

## Clauses that carry the risk

- **Opens zoomed out**: every thread a band across the corpus time span with
  mention density, sortable by activity and recency, searchable by name.
- **Continuous zoom and pan**; crossing level-of-detail thresholds reveals
  meetings, then moments with titles and speakers — **smooth transitions, no
  layout jump**. That smoothness is the demo beat; budget your time for it.
- **Nothing is shown that a moment does not back.** No decorative density.
- A moment at the moments tier links to moment view.
- **The evidence tier and inline replay are story 10.6a — NOT yours.**
- **Web tests cover bands → meetings → moments with fixture data at each
  level** — the acceptance criteria specify fixtures, so build and test against
  them rather than waiting for the API.
- **The API (story 10.3) is being built in parallel.** Code against 10.3's
  acceptance-criteria field names exactly: `GET /threads` returns `threadId`,
  `name`, `mentionCount`, `meetingCount`, `firstMentionAt`, `lastMentionAt`,
  `colorOrdinal`; `GET /threads/{id}/timeline?from=&to=&level=` takes
  `bands|meetings|moments|evidence`. Use the served `occurredAt` — never
  reconstruct wall-clock time client-side. `colorOrdinal` is immutable per
  thread, so derive colour from it rather than from list position.

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
