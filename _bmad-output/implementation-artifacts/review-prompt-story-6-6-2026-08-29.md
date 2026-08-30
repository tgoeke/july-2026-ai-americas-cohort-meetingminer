# Review handoff — Story 6.6: YouTube Deep Links

## REQUIRED OUTPUT — read this before anything else

**Your deliverable is a file, not terminal text.** Write the review to
`_bmad-output/implementation-artifacts/review-story-6-6-2026-08-29.md` in the
main checkout (`/Users/devopsterus/current/cohort/meetingminer`). A review that
exists only in the terminal does not exist. Six reviews in this repo were lost
that way.

**Report first.** Before reading a single line of code:

1. Create the report file as a skeleton — title, scope, the exact review range,
   an empty `## Findings` section — and commit it.
2. Then read the code, appending each finding as you confirm it, committing
   incrementally. A crashed or closed session must lose prose, never the
   artifact.

**Finding structure** (one block per finding, in this order):

- **Location** — `path:line` (repo-relative)
- **Severity** — high | medium | low, by consequence to the person using the web app
- **Finding** — one sentence stating the defect
- **Evidence** — what you observed (a test you ran, a line you read, a command output)
- **Suggested direction** — the shape of a fix, not the fix

**Report findings; do not fix.** Do not edit application code. If you must
demonstrate a failure, do it in a scratch copy or a throwaway test you delete.

**Closeout check.** Before reporting completion, run `make check-reviews` from
the main checkout — it fails while any dispatched review lacks a committed
report, including this one — and state the SHA carrying the report's final
version.

Work in your own worktree: `make worktree STORY=6-6-review` then
`cd ../meetingminer-wt/6-6-review && make bootstrap`. Never work in the main
checkout or in `../meetingminer-wt/6-6`. Read `AGENTS.md` at the repo root
first; commit and push without asking; never `git add -A`; never reset a tree
you do not own.

Note that `_bmad-output/` is a local, untracked process record (`main` commit
`a22d67c` stopped tracking it). Your report file lives there too: commit it in
the worktree with `git add` on its explicit path only if the repository's
`.gitignore` still permits it; if it is ignored, keep it on disk in the main
checkout's `_bmad-output/implementation-artifacts/` and say so in the closeout
— `make check-reviews` reads that directory.

## Repository, branch, range

- Repository: `/Users/devopsterus/current/cohort/meetingminer` (remote `origin`, private)
- Branch: `story/6-6` (pushed; in sync with `origin/story/6-6` at handoff)
- Baseline: `d8a279f8882d24beef8b99c4c5db00d45b057bcd` (`main` at the time; `chore: sprint status — 6-6 in progress`)
- **Review range:** `d8a279f8882d24beef8b99c4c5db00d45b057bcd..f5c49180ea058dbaf58e20914d8feb593d98e0d3`
  - `a8ae945ef582a542a7bc5daa48a29e637bc8d719` — feat: Story 6.6 — YouTube deep links beside replay (UX-DR12)
  - `f5c49180ea058dbaf58e20914d8feb593d98e0d3` — fix: Story 6.6 review — one SourceLinkAnchor, keep non-time fragments
- `main` has since moved by one commit, `a22d67c` (`chore: stop tracking _bmad-output; it is local process record`), which touches no story file. The branch was **not** rebased onto it; `git diff main -- web/src` is the story's whole change and `git diff main` outside `web/src` shows only `a22d67c`'s deletions — not a regression.

## The spec

`_bmad-output/implementation-artifacts/spec-6-6-youtube-deep-links.md` (main checkout, local).

- **Frozen intent** = everything inside `<intent-contract>` (Intent, Boundaries &
  Constraints, I/O & Edge-Case Matrix). It was derived from Story 6.6 in
  `_bmad-output/planning-artifacts/epics.md` (lines 1447–1461) and UX-DR12
  (line 128). Critique it against the story text, not against the plan.
- **Planner work you may critique** = Code Map, Tasks & Acceptance, Design Notes,
  the review triage log, and the Auto Run Result. The triage log lists sixteen
  rejected findings with reasons; re-litigate any you disagree with.

## Architecture authority

- `docs/architecture.md` — AD-6 (citation ids stay resolvable), AD-15 (one
  citation wire format: `sourceDeepLink` on `CitationModel` is read from
  Postgres only), and the general rule that the web never invents behaviour
  the server has not verified (no fabricated time syntax).
- Design companion (adopted, versioned, `updated: 2026-08-29`):
  `_bmad-output/planning-artifacts/ux-designs/ux-meetingminer-2026-08-29/EXPERIENCE.md`
  — Voice table row `Replay 12:40 · Open on YouTube at 12:40 ↗`; Component
  Patterns · Moment card (line 85: parse with `URL`, replace/insert the
  provider time parameter, never concatenate); Accessibility (line 206: names
  carry the offset; glyphs hidden); Data Traceability · "YouTube deep link
  (6.6)" (lines 319–323). `findings-for-epics.md` F-15 names `affordanceOf`
  as what 6.6 changes. Spines win over mockups.
- `AGENTS.md` for working rules; `project-context.md` for the repo map.

## Scope

**In scope (13 files, all `web/src`):**
`lib/affordance.ts`, `lib/affordance.test.ts` (new), `components/SourceLinkAnchor.tsx` (new), `components/SourceLinkAnchor.test.tsx` (new), `features/search/hits.ts`, `features/moments/MomentView.tsx` + `.test.tsx`, `features/moments/MeetingMoments.tsx` + `.test.tsx`, `features/chat/ChatPanel.tsx` + `.test.tsx`, `features/search/CorpusSearch.tsx` + `.test.tsx`.

**Out of scope:**
- The server. In particular `server/meetingminer/pipeline/stages/moments.py:301-302, 385-399` nulls a moment's `source_deep_link` once replay exists; that is a **recorded deferred finding** (spec frontmatter `deferred`, medium), not a defect of this range. Do not report it again unless you find the recording wrong.
- `docs/backlog.md` (owned by in-flight story 11-1), `docs/project-record.md` (epic-level entry at epic close), the generated `web/src/client/` (untouched).
- Moments cards / `MomentListItem` (story 10.x), the Add-meeting flow (6.5), YouTube acquisition itself (6.2 — not built yet; no YouTube drop exists in the corpus).
- No commit in the range belongs to another story.

## Planner decisions to attack

Each is a choice plus the assumption it rests on. The planner is not a neutral judge of these.

1. **Web-only, despite the data gap.** Choice: implement the four rendering
   surfaces against `sourceDeepLink` + `startMs` as the design spec's
   traceability maps them, and defer the server change that would make the
   beside-replay link reachable on moment view, search, and chat. Assumption:
   the story is a web story ("web tests cover both hosts and both replay
   states"), server tests are owned by 11-1, and the drill-down (which reads
   `meeting.provenance->>'url'` regardless of replay) is a real, reachable
   surface today. Attack: is a story whose headline state is unreachable on
   three of four surfaces "done"?
2. **`affordanceOf` returns both.** Choice: `replay` carries
   `source: SourceLink | null` (YouTube only; any other host → `null`), and
   `deepLink` carries a classified `source` instead of a bare `href`; the
   public `Affordance` shape changed and `CorpusSearch` was edited although the
   story does not name it. Assumption: F-15 and EXPERIENCE.md (which lists
   `SearchHit`) make the shared decision the intent's mechanism.
3. **Replay-less YouTube link is timed and relabelled.** Choice: with no
   recording, a YouTube link is the sole affordance *and* reads
   `Open on YouTube at H:MM:SS` with `t=` set; "existing behaviour holds" was
   read as the placement rule, not the label. Assumption: calling a YouTube
   URL "Open in Stream" (SharePoint Stream) would be wrong copy. The AC's
   second Given can be read the other way.
4. **Drill-down granularity.** Choice: every screenshot row and every
   transcript row gets a link timed at its own offset when the meeting has a
   recording; the degraded (no recording) header link is untimed
   (`Open on YouTube`), and degraded rows get no per-row link. Assumption: the
   drill-down's link is meeting-scoped and only rows with replay have a
   replay to be "secondary to".
5. **Time syntax.** Choice: `t=<whole seconds>` for `youtube.com/watch` and
   `youtu.be/<id>` only; any other YouTube path (`/shorts/`, `/embed/`,
   `/live/`) is offered untimed rather than with an unverified parameter;
   `*.youtube.com` subdomains count as YouTube; only a `#t=` fragment is
   dropped. Assumption: `t=<seconds>` is accepted by both timed forms;
   yt-dlp's `webpage_url` is the canonical `watch?v=` form so `/watch/` or
   case variants need no normalisation.
6. **Anchor styling by provider.** Choice: the YouTube anchor is an outline
   button with an `aria-hidden` `↗`; the other-host `Open in Stream` keeps its
   underline text look; the accessible name does not say "opens in a new
   tab". Assumption: DESIGN.md's Moment card ("Open on YouTube as outline
   buttons"), EXPERIENCE.md line 206 (glyphs hidden from names), and AC2
   ("existing behaviour holds") together fix this.
7. **Chat citation without `onOpenMoment`.** Choice: the YouTube anchor and
   the `Open moment` button are independent, so a citation rendered by a
   shell that wired no navigation shows the anchor alone. Assumption: a real
   link is not a dead affordance. Untested.

## History the reviewer needs

- No rebase, no dropped variants. Two commits; the second is the in-run
  review's seven low-severity patches (fragment scope, the shared anchor
  component, `rel` assertions, a fractional-offset test, a doc citation, a
  stale comment, a test title). The triage log in the spec records every
  finding and its route.
- The spec's frontmatter carries `warnings: [oversized]` (it is over the
  1600-token target) and `followup_review_recommended: true` — the latter is
  the formula (7 low patches ⇒ score 7 ≥ 5), not a correctness concern.

## Verification baseline (observed by the run at `f5c4918`, from `../meetingminer-wt/6-6`)

- `make web-test` → 16 test files passed, 288 tests passed (store-free; safe to run concurrently).
- `pnpm --dir web run build` → `tsc -b && vite build` exit 0.
- `pnpm --dir web run lint` → 0 errors; 4 pre-existing `react(only-export-components)` warnings in files this story does not touch.
- `git diff --stat main -- web/src` → 13 files, +739/−83.
- `git status --porcelain` empty; `git rev-list --left-right --count HEAD...@{u}` → `0	0`.
- Not run: `make test` / any `server/tests` suite — no server file changed, and the shared Docker stores were not claimed. A skip or failure you see in the web suite is a finding, not noise.
- Note: `tsc`, vitest, and vite write cache files under the worktree's `node_modules`; a sandboxed shell may need the worktree path allowed.
