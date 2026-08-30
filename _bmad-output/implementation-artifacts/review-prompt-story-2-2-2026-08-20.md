# Review handoff — Story 2.2: Moment View (2026-08-20)

You are the `bmad-code-review` agent. You have none of the build run's context; everything you
need is in this file and the repository. Report findings — do **not** apply fixes.

## Repo, branch, range

- Repo: `~/current/cohort/meetingminer` (or review in your own worktree:
  `make worktree STORY=2-2-review`). The story branch is **`story/2-2`**, pushed to origin.
- Review range: **`f653a3d..HEAD`** on `story/2-2` (baseline `f653a3d` = the branch point from
  `main`; also recorded as `baseline_revision` in the spec frontmatter).
- Commits in the range, oldest first:
  - `fa0d0f1` docs(spec): story 2.2 moment view — plan and frozen contract
  - `1fff9ab` feat(api): moment read routes — meeting moments list and moment detail (story 2.2)
  - `dffd0cb` chore(client): regenerate TS client with listMeetingMoments and getMoment
  - `12b5869` feat(web): moment view and meeting moments list; wire navigation (story 2.2)
  - `34a1672` docs(spec): 2.2 in-progress; log build decisions in the change log
  - `1d26e3a` docs(spec): 2.2 manual checks performed — seek/Range/206 loop confirmed on real corpus
  - `46599bc` fix(api): one snapshot per moment read; harden and bound the routes (review 2.2)
  - `8c204c1` fix(web): keep home mounted behind drill-downs; honest loading; review 2.2 patches
  - `14f80f9` docs(spec): 2.2 — correct stale 409-title Code Map note; record in-review status
  - `a0622d6` docs(spec): 2.2 done — triage log, deferred items, auto run result; sprint 2-2 to review

Every commit in the range belongs to story 2.2; none is another story's work. The three `fix(...)`
commits are the build run's own first-pass review remediation — they are in scope and reviewable
like everything else.

## Spec: what is frozen, what you may critique

- Spec: `_bmad-output/implementation-artifacts/spec-2-2-moment-view.md`.
- The `<intent-contract>` block (Intent, Boundaries & Constraints, I/O & Edge-Case Matrix) is
  **frozen intent** distilled from `_bmad-output/planning-artifacts/epics.md` §Story 2.2 — judge
  the code against it, do not critique it.
- Everything outside that block — Code Map, Tasks & Acceptance, Design Notes, the Spec Change Log's
  build decisions — is **planner work you may and should attack**.

## Architecture authority

- `_bmad-output/specs/spec-meetingminer/SPEC.md` — Constraints: *no citation, no answer*;
  *augmentation adds, never destroys* (moment ids are never re-keyed — this is why superseded
  moments must keep resolving by id); the two-roots rule (no absolute path leaves the server);
  *only published artifacts enter retrieval stores* (unpublished surface only in this rail).
- `_bmad-output/specs/spec-meetingminer/ux-spine.md` — "Moment view anatomy" (screenshot top,
  transcript below, right rail, replay button) and the transcript-only deep-link stand-in.
- `_bmad-output/specs/spec-meetingminer/glossary.md` — `evidence_complete`/`viewable` (legitimately
  false during augmentation), Source deep link (transitional, never time-parameterized), the
  artifact lifecycle (`extracted → approved → published`).
- AD-5/AD-11 (api reads evidence, never writes it), AD-3 (root-relative paths only) as rendered in
  the spine and enforced by `server/tests/test_projections_single_writer.py` (AST-walks `api/` for
  store imports).

## Scope

In scope (the whole diff):

- `server/meetingminer/api/moments.py` (new), `server/meetingminer/api/main.py` (registration)
- `server/tests/test_api_moments.py` (new, 16 tests)
- `web/src/client/{index,sdk.gen,types.gen}.ts` (regenerated)
- `web/src/features/moments/` (new: `MeetingMoments.tsx`, `MomentView.tsx`, `moments.ts`, 3 tests)
- `web/src/App.tsx` + `App.test.tsx` (view-stack navigation)
- `web/src/lib/affordance.ts`, `web/src/lib/problems.ts` (new), `web/src/features/search/hits.ts`
  (now re-exports), `web/src/features/search/CorpusSearch.tsx` + test ("Open moment" affordance)
- `web/src/features/meetings/MeetingsList.test.tsx` (mock factory)
- The spec file itself (planner sections only)

Out of scope:

- Meeting drill-down / screenshot series (story 2.3), participant curation (2.4), artifact
  extraction and the artifact table (Epic 4 — but see the coupling note below), URL routing.
- Already-recorded deferred items (spec frontmatter `deferred:`): the `types.gen.ts`
  baseUrl-literal drift + `check-client`'s inability to detect generated-content drift, and the
  four-copy abortable-load idiom awaiting a shared hook. Re-raise only if you find them worse than
  recorded.
- `ReplayPlayer` internals (story 2.1; its no-failure-surface limitation is a recorded 2.1
  deferral — this story's obligation was only to never mount it without a recording).

Cross-story coupling to check, not to fix: story 4-1 (in review on `story/4-1`) introduces
`0009_artifacts.sql` and the extraction stage. This story froze `MomentArtifact` (kinds =
CAP-4's seven categories as slugs; states import-locked to `projections/publish_gate.ARTIFACT_STATES`)
as Epic 4's forward wire contract, while `get_moment` returns a hardcoded `artifacts=[]`. If you
can see `story/4-1`'s schema, verifying the two agree is a high-value finding either way.

## Planner decisions to attack

Each stated as choice + the assumption it rests on. The planner is not a neutral judge of these:

1. **Gate semantics: 404 vs 409.** Unknown id → 404 `not-found`; existing meeting with unsettled
   evidence → 409 `meeting-not-viewable` on *both* routes. Assumes the status-code pair alone is
   an adequate rendering of the epic's "distinguish active augmentation from never ingested", and
   that 409 is the right code for a transient server-side state (vs 503/423/404-with-retry).
   Consequence accepted: during augmentation, *every* citation id of that meeting temporarily
   answers 409 — replay of cited evidence is briefly refused. Is that tension with "no citation,
   no answer" tolerable, and is the problem payload enough for a client to render it honestly?
2. **Superseded moments: list-hidden, detail-served flagged.** Assumes list consumers must never
   see ghosts while citation consumers must always resolve the id. The detail returns
   `segments: []` for superseded moments — is an empty transcript the right served state for a
   still-cited id?
3. **Typed-empty artifacts array.** `MomentArtifact` fields (`id`, `kind`, `state`, `title`,
   `body`) were frozen with zero producible rows. Assumes Epic 4 can live inside that shape
   (adds rows, never fields). Attack the field choice — especially `body` as a single opaque
   string, and the absence of any per-artifact moment/citation linkage.
4. **Hand-rolled view stack in `App.tsx`, no router.** Assumes no AC needs URLs and that the
   exported `AppView`/`OpenView` union is the navigation contract 2.3/3.4 will reuse. Attack:
   browser Back/refresh do nothing (stack is in-memory); home stays mounted-but-hidden behind
   drill-downs (polling continues hidden — HealthPanel and the meetings SSE keep running).
5. **`screenshotPath` beside `screenshotId` on the detail payload.** Assumes returning the stored
   content-root-relative path verbatim leaks nothing AD-3 cares about and that `GET /media/{path}`
   containment is the single defense that matters.
6. **REPEATABLE READ per read-block** (first-pass remediation). Assumes `SET TRANSACTION ISOLATION
   LEVEL REPEATABLE READ` as the first statement of psycopg's implicit transaction reliably scopes
   both/all statements to one snapshot under the app's pool settings — verify, don't trust.
7. **`preview` capped at `LEFT(text, 300)` server-side.** A field the SearchHit vocabulary does not
   carry, added for the list rows; assumes 300 chars is a safe wire/display bound and that
   truncation server-side (not a `…` marker) is acceptable.
8. **Client regeneration workaround.** The client was generated from `app.openapi()` dumped to a
   file with an injected `servers` entry because :8000 served another checkout. The recorded claim
   is `client.gen.ts` byte-identical and `types.gen.ts` off by the known one-line baseUrl literal.
   Verify the committed client actually matches this branch's schema semantically.

## History you need

- Baseline `f653a3d` is current `main`. There was no rebase; the range is linear.
- The build's own first-pass review (4 layers) already patched 13 findings — the patches are
  commits `46599bc`/`8c204c1`/`14f80f9`, and the triage log in the spec lists all 13 with the 4
  rejections and 2 deferrals. A finding you re-derive that is listed there as rejected/deferred
  deserves fresh evidence, not repetition.
- Stories 2.1/2.1a/2.1b landed the media routes, roots anchoring, and `mint-drop`; story 3.1
  landed search (its spec deferred the hit→moment-view link to this story — now wired as
  `onOpenMoment`).
- The moments-stage superseded semantics (`pipeline/stages/moments.py:214-232`) predate this story;
  this story is their first reader.

## Verification baseline

All run by the build orchestrator on 2026-08-20 after the remediation commits — a deviation from
these numbers during your review is a finding, not noise:

- `cd server && .venv/bin/python -m pytest tests/test_api_moments.py -q` — **16 passed**.
- `cd server && .venv/bin/python -m pytest tests/ -q` — **1102 passed**, 0 failed, 0 skipped
  (~5–6 min). Store-backed; per-run database, safe to run concurrently (AGENTS.md).
- `make web-test` — **130 passed**, 9 files. Store-free.
- `pnpm --dir web run lint` — clean except one pre-existing `button.tsx` fast-refresh warning.
- `pnpm --dir web run build` — clean (`tsc -b` against the committed client).
- `make client` — **cannot be run as written** while :8000 serves a different checkout's api; the
  health check will pass (same service name) and it would generate from the wrong schema. Do not
  run it casually; see planner decision 8 and the first deferred item.
- Manual end-to-end (build-time, Playwright, real corpus): 165-moment list; screenshot 200; replay
  answered 206 with `video.currentTime` at the moment offset; transcript-only meeting showed the
  deep link and no player. Recorded in the spec's Manual checks.

## Required output

Write your findings to
`_bmad-output/implementation-artifacts/review-story-2-2-2026-08-20.md` — **the file must exist on
disk and be committed before you report completion**; this repo has had three reviews whose reports
were never filed, and the sprint gate now holds the story at `review` until the report is
committed. Structure: verdict (pass / pass-with-findings / fail), then findings each with severity
(high/medium/low), file:line evidence, and the concrete failure scenario. Report findings only —
do not fix, do not commit code changes. Note explicitly which verification commands you ran and
their results, including any you skipped.
