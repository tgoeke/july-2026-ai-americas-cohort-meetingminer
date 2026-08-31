# Reviewer handoff — Story 10.6: Threads Zoomable Timeline

Branch `story/10-6`, built from `main` at `3211a7f`. Spec:
`_bmad-output/implementation-artifacts/spec-10-6-threads-zoomable-timeline.md`
(`status: review`). Read `AGENTS.md` and
`_bmad-output/implementation-artifacts/wave-2026-08-30-rules.md` first.

## The review lane fixes what it finds

Owner ruling, 2026-08-30, and it governs this review:

> Report every finding in the report file first (report-first, committed before
> reading code), then FIX the patchable ones yourself on `story/10-6-review` in
> your own worktree, red-first — the test observed failing against the unfixed
> code, then the fix, then green — committing each with its finding number.
> Leave unfixed, and clearly marked open, only what needs an owner decision or
> is rooted in the frozen spec. Never commit to `main`, never work in the main
> checkout, never merge — the owner runs `integrate`.

Set up with `make worktree STORY=10-6-review BASE=story/10-6`, then
`make bootstrap` and `uv sync --project server` there.

## What this story is

The owner calls zooming a thread the best part of the demo. The screen opens on
every thread as a band across the corpus span and one continuous zoom carries
the reader down through meetings to moments without changing screens.

Footprint: `web/src/features/threads/` (all new) and an append to
`docs/backlog.md` (B-44, B-45), which the build prompt authorises
explicitly. Nothing else was touched.

## Where to push hardest

1. **The zoom's smoothness is the demo beat.** Pan and zoom are two CSS custom
   properties on the canvas root (`threads.css`, `useTimelineView.ts`); each
   item carries `--t` and computes its own x. Verify there is no per-frame React
   render, that a hard wheel spin accumulates into the target rather than
   queueing animations, and that the ease restarts from the *drawn* view so a
   fast gesture never snaps backward.
2. **"No layout jump" as a property, not a claim.** The tier is a pure function
   of `scale` (`tierForScale`), so a tier change touches neither `from` nor
   `scale`. `Threads.test.tsx` asserts the focused instant's x is unchanged
   across a threshold crossing. Try to break it: a `Fit` that jumps two tiers, a
   crossing while a fetch is in flight, a re-anchor of `epochMs` mid-gesture.
3. **Nothing shown that a moment does not back.** An empty bucket is drawn (its
   span is real) but is not a cell and carries no label. Hunt for anywhere the
   screen could draw a finer tier from coarser data, interpolate a gap, or keep
   a stale payload past its generation.
4. **`threadsApi.ts` assumes response *shapes*.** Story 10.3's acceptance
   criteria fix the field names, not the envelopes. The assumed bodies are
   listed in the spec's Code Map. **If `story/10-3` has landed by the time you
   read this, reconcile against what it actually serves** — that is the single
   most likely thing to be wrong, and it is one file.
5. **Route ranking against story 10.5's placeholder.** 10.5 mounts a
   `/threads/*` splat from its own `Threads.route.tsx`; this story adds
   `ThreadsTimeline.route.tsx` (`/threads`) and `ThreadFocus.route.tsx`
   (`/threads/:threadId`) beside it rather than editing 10.5's file. Confirm
   react-router really does rank the literal and the param above the splat once
   both branches are on one tree — that is a claim taken from 10.5's comment and
   it has not been verified with both modules mounted together.
6. **Accessibility floor.** `role="grid"` with the tier and window in its name;
   every cell's accessible name carries its own data; ≥ 24 × 24 hit areas via
   `.mm-hit` on drawn geometry that may be 3px wide; roving tabindex; the polite
   region announcing a tier change once and not on continuous zoom; focus never
   lost to the page. The last of these was a defect the tests found — check the
   fix holds when a cell vanishes for a reason other than clustering.
7. **Colour from `colorOrdinal` only.** Sorting, filtering and search must never
   recolour a thread. Lap 2 hatched, past 16 grey with the name carrying
   identity.

## Verification to reproduce

`make test-fast` was green at `39ccfba` and re-run after the route change: ruff `All checks passed!`, mypy
`Success: no issues found in 13 source files`, vitest `353 passed (20 files)`,
pytest `2173 passed, 3 skipped, 411 deselected in 103.27s` (the three skips are
the standing named ones). `pnpm exec tsc -b --force` exits 0.

The CSS geometry was measured in Chrome 151 against a probe page carrying the
same `.mm-at` / `.mm-span` rules, because jsdom computes no layout and no vitest
test can show the calc working. **Re-do that measurement rather than trusting
it**, and consider whether it should become a checked-in browser test.

## Deliberately not here

The evidence tier and inline replay (story 10.6a), curation (10.2a), pins
(B-45) and a corpus-wide bands level (B-44). Do not build them; do check they
were the right things to leave.

## Rules

Never `make evals-run`, never `make up`, never start the shared api or worker.
New tests in new files. Stage only paths you changed; never `git add -A`. Run
`python3 _bmad/scripts/branch_conflicts.py --against story/10-6-review` before
your final push.
