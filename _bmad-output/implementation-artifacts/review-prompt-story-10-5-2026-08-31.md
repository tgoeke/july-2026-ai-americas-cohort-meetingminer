# Review handoff — Story 10.5: Moments View and Front Door

Branch `story/10-5`, `c33dfe0..106461d` (three commits). Built 2026-08-31.
Story: `epics.md` line 1777. Builder contract:
`build-prompt-story-10-5-2026-08-31.md`. Wave rules:
`wave-2026-08-30-rules.md`.

Work in your own worktree — `make worktree STORY=10-5-review BASE=story/10-5`,
then `make bootstrap` and `uv sync --project server` there. **Never work in the
main checkout, never commit to `main`, never merge — the owner runs
`integrate`.**

## The review lane fixes what it finds

Owner ruling, 2026-08-30, and it is not optional here:

> Report every finding in the report file first (report-first, committed before
> reading code), then FIX the patchable ones yourself on `story/10-5-review` in
> your own worktree, red-first — the test observed failing against the unfixed
> code, then the fix, then green — committing each with its finding number.
> Leave unfixed, and clearly marked open, only what needs an owner decision or
> is rooted in the frozen spec. Never commit to `main`, never work in the main
> checkout, never merge — the owner runs `integrate`.

Do not copy the older `review-prompt-story-*.md` files in this directory. Some
predate that ruling and carry "Report findings — do NOT fix them"; that
instruction is retired.

## This is the demo's opening screen

The owner made it non-negotiable and the deadline is today. Weigh findings
accordingly: a defect a viewer would see on `/` at 1280×800 outranks a
stylistic one. **Look at the screen in a browser** — this lane found two real
defects that way which the test tree could not (see Verification below), and a
review that only reads the diff will miss the same class.

## What was built

- **`/` is the ranked Moments feed.** `web/src/features/moments/MomentsFeed.tsx`
  and `MomentCard.tsx`, over `feed.ts`. Cards carry the screenshot, the meeting
  and offset, the reason line, thread chips, the excerpt; each replays in place
  and links to its moment and its meeting. Filters for corpus, thread and kind
  are URL query params. Paging is `Show N more`.
- **`/threads` is the second primary view**, behind
  `features/threads/ThreadsPlaceholder.tsx` for story 10.6 to fill.
- **`/meetings` is the reimagined home, relocated whole**: corpus counts,
  meeting cards, health panel — unchanged inside.
- **The chrome** is one sticky bar: brand, the six standing destinations, Add
  meeting, health indicator; search and ask stand under it on every route.
- **Dark at the root**, with `index.css` carrying the Ember & Ink delta.
- **B-13 closed** by `web/src/shellPlacement.test.tsx`.

## Where to look hardest

1. **The two acceptance clauses that are easy to lose.**
   - *Nothing regresses.* The 294 pre-existing web tests still pass, but 13 of
     them were edited: they asserted what `/` renders, which is the one thing
     this story changes. Read that diff in `web/src/App.test.tsx` closely and
     judge whether any assertion was **weakened** rather than re-pointed. The
     intent was re-pointing only — starting location `/meetings`, `Home` →
     `Moments`, the Participants button → the chrome link. A weakened
     assertion here is the highest-value finding in the story.
   - *The shell's child-screen placement is pinned.* `shellPlacement.test.tsx`
     asserts it over `childRoutes` with `compareDocumentPosition`. Try to break
     the invariant (move the `<Outlet />` below the search chrome in `App.tsx`)
     and confirm the test goes red. If it does not, the pin is decorative and
     B-13 is not actually closed.

2. **The three recorded deviations.** Each is in `sprint-notes.md` under
   `## 10-5 built`. Judge whether each is the right call, not whether it is
   disclosed:
   - Search and ask are **not** inside the 56px chrome bar that
     EXPERIENCE.md · Chrome specifies. Doing it means redesigning
     `CorpusSearch` and `ChatPanel`, and `ChatPanel` is story 8.3's surface
     this wave. Consequence: on `/` the feed starts about 310 CSS px down.
     Is that acceptable for the opening screen, or is there a cheaper
     composition inside this story's footprint?
   - The thread filter's options come from the threads the **served items**
     carry, not `GET /threads` (story 10.3, not built).
   - `GET /moments/feed` is read by a hand-written reader in `feed.ts` rather
     than the generated client, because story 10.4 builds the endpoint in
     parallel and regenerating would fight that lane for `client/sdk.gen.ts`.
     **Check the field names against story 10.4's acceptance criteria
     one by one** — `momentId`, `meetingId`, `meetingTitle`, `startedAt`,
     `startMs`, `corpus`, `hasRecording`, `screenshotId`, `viewType`,
     `preview`, `threads[]{threadId,name,colorOrdinal}`, ordered
     `reasons[]{kind,label,ref?,at?}`. A drift here is a demo-day break.

3. **The design spines win over the mockup.** `DESIGN.md` and `EXPERIENCE.md`
   in `_bmad-output/planning-artifacts/ux-designs/ux-meetingminer-2026-08-29/`.
   Specifically worth checking: a kind chip never without its glyph; `risk` and
   `question` never drawn as kind chips; thread hue derived only from the
   persisted `colorOrdinal` and never from list position; the counted header
   shape (`Moments 24`, `Moments 6 of 24`); ISO dates and `H:MM:SS` offsets with
   no relative dates; every reason label rendered verbatim.

4. **Contrast and the token block.** `index.css` gained a second `.dark` block
   rather than editing the shadcn one. Confirm the six base values and the kind
   and thread families match `DESIGN.md`'s frontmatter, and that no new
   text-on-surface pair was introduced without a measured row in that file's
   contrast table.

5. **Boundaries this lane was told to respect.** It must not have restructured
   the ask box (story 8.3) or the meeting view (story 7.4), must not have
   hand-edited a route registry, and must not have built the Threads screen.
   The one deliberate seam is `web/src/features/threads/Threads.route.tsx` —
   created here, filled by 10.6, registered at `/threads/*` so a thread chip's
   deep link resolves rather than falling to the catch-all.

## Verification this lane actually ran

Read these as claims to audit, not as evidence accepted.

- `make test-fast` — **green**: 2173 passed, 3 skipped with named reasons, 411
  deselected. That target includes `check-client`, `lint`, `typecheck`,
  `puller-test`, `web-test` and `evals-test`.
- `make web-test` — **350 passed across 19 files** (294 before this story).
- `pnpm exec tsc -b` clean; `oxlint` reports only the four pre-existing
  `only-export-components` warnings.
- **An earlier `make test-fast` failed twice on the fast-set time budget** —
  `test_frame_image.py::test_an_unreadable_frame_raises_a_named_error` at 2.11s
  and `test_mint_drop.py::test_a_minted_nested_drop_posts_to_the_real_ingests_route`
  at 2.35s. Re-run alone they take 0.02s and 0.22s, and neither touches
  anything this story changed, so this was cross-lane contention, which
  AGENTS.md says is not a reason to mark a test slow. The re-run was green.
  Worth knowing if you see the same two.
- **Rendered and read in a browser** at 1440×900 against a throwaway fixture
  api on private ports (never the shared stack): the front door, the expanded
  replay state, and `/meetings`. That is what caught the grid breakpoint and
  the expanded card's stranded action row, both fixed in `106461d`.

**Not run:** `make test` (the full gate, twin-bound) and `make evals-run`
(paid; forbidden to this lane). The change is web-only, but the full gate is
still owed at integration.

## Standing rules

New tests in NEW files. Stage only paths you changed; never `git add -A`; never
reset, stash or clean outside your worktree. Commit and push without asking.
Never `make evals-run`, never start the shared api or worker. Before your final
push run `python3 _bmad/scripts/branch_conflicts.py --against story/10-5-review`
and narrow your own edit if it reports a conflict.
