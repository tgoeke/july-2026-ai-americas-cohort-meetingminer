# Demo readiness — story ui-5 (CAP-4 dry-run gate)

Run 2026-08-21 against the running app: main-checkout api on `:8000`
(healthy, on merged main), the pre-existing Vite dev server on `:5173`
(CORS-allowlisted origin, serving the same merged main tree). Browser
walkthrough via Playwright; server state cross-checked with `curl`.

## Verdict

**Demo-ready for the screens that don't call out to paid services or the
search index; NOT demo-ready for live corpus search or live Ask-the-corpus
right now.** Both failures are external/infra, not UI code, and both are
outside this story's file boundary (no server files touched, per the build
prompt). The presenter needs to know before tomorrow morning — see
"Blocking issues" below. Everything else in the reimagined chrome (CAP-1,
CAP-2, CAP-3, replay) worked cleanly, live, with real data.

## Screen-by-screen

**Home dashboard (CAP-1).** Real corpus counts render without a click: 34
meetings, 25.6 hours of evidence, 1813 moments, 647 screens, 399 artifacts,
99 participants, 11 published documents. Evidence cards show poster
screenshot, title, date, duration, corpus (real/scripted), transcript-only
badge, per-meeting counts, and a per-stage ingestion pipeline (probe →
frames → ocr → screens → transcribe → align → moments → extract), each
stage colored and labeled with its failure detail when one exists (e.g.
"Review 2.1b Live Intake" cleanly shows its align-stage refusal instead of
inventing timing). Corpus filter (All/real/scripted) and "newest first"
sort are present and worked. No console errors on load.

**Search + Ask (persistent chrome).** Present on every screen tested
(home, meeting, moment, settings, status). See "Blocking issues" — both are
functionally broken tonight for reasons outside the UI.

**Dense meeting view (CAP-2)**, opened on "Q3 Architecture Review"
(scripted, 11 screens, 16 moments, 6 artifacts, 2 participants) and on
"project- R2C Functional Demo" (real, transcript-only, 443 turns, 40
moments, 15 artifacts). Header stat line (date · duration · turns · words ·
passages · source lineage) renders correctly for both. Three-column layout:
screens film-strip left (each with timestamp, kind label, Replay button),
full speaker-attributed transcript center (highlight-a-term box works),
right rail of extracted artifacts grouped by kind (Action items, ADRs, and
empty-but-honest Decisions/Stories/Requirements/Bug fixes/Change requests
sections with `0` rather than being hidden) — each with its moment anchor,
publish state, and jump link. Participants and Published documents sections
both rendered with real names/counts. The transcript-only meeting correctly
substitutes an "Open in Stream" link where the screens column would be,
instead of showing an empty column. No console errors on either meeting.
Did not observe the "may be incomplete" fan-out advisory on either meeting
sampled (neither is large enough by screen count to be conclusive either
way — noted as an open advisory, not cleared).

**Moment page + replay.** Clicked through from the meeting view's "Write
the ADR for the retrieval split before the next review" artifact card into
its moment (`/moments/...`). Screen capture, active extraction prompts, and
extracted artifacts (with publish state) all rendered. Clicking Replay
opened a real HTML5 video player correctly seeked to 4:19/7:14 with a
synced transcript underneath — this is the full "open a cited moment →
replay its evidence" leg of the demo path, and it works end to end.

**Configuration page (CAP-3).** LLM roles (extraction/chat/judge) with
model, fallback, provider, endpoint, timeout, and expandable full-text
prompts; capture thresholds; API search/chat knobs (including the semantic
ratio and synonyms table); projections config (moments/chunks index
schemas, ranking rules, synonyms); store coordinates (Postgres, Neo4j,
Meilisearch). Every section states the `config.yaml`-edit-plus-restart
change path, and the page states up front it is read-only with no edit
control planned. Ran a regex scan of the rendered page text for
`sk-...`/`password`/`api[_-]?key: <value>` patterns — none found; no secret
leaked.

**Status page.** Overall correctly shows **"attention needed"** (matches
`/status`'s `"overall":"degraded"`), with api/Postgres/Neo4j/Meilisearch
each individually "ok" and worker correctly reported "stopped — 0 paused
jobs, deliberate." This page is doing its job: it is the one place a
presenter would see the corpus/chat trouble coming.

## Blocking issues (not fixed — infra/server, outside ui-5's file boundary)

1. **Corpus search returns zero hits for everything.** Tested `pipeline`,
   `purchase order` (the placeholder's own example, and a configured
   synonym per `/settings`), `retrieval split` (a phrase spoken verbatim in
   the Q3 Architecture Review transcript), and `architecture`. All four
   returned `hits: []` from `GET /search`. One attempt (`pipeline`) instead
   503'd with `MeilisearchApiError. Error code: invalid_search_embedder.
   Cannot find embedder with name 'default'.` `/status` reports Meilisearch
   "ok" (health endpoint answering) — that check doesn't catch this. My
   read: the moments/chunks index is either not populated for the current
   corpus or its embedder config is broken, so hybrid search (config'd
   `semantic ratio: 0.3`) fails or comes back empty. This is a Meilisearch
   index/projection state issue, not a `web/src` bug — the UI is correctly
   and honestly rendering "No moments match that search" rather than
   inventing results. **Fallback:** none available in the reimagined UI;
   the corpus-search leg of the three-minute demo path cannot be
   demonstrated live right now. Recommend a `make rebuild` (or equivalent
   Meilisearch re-projection) before the demo — not run here, since it
   writes the shared stores and wasn't in this story's authorization.

2. **Ask-the-corpus is unusable: the paid chat role is out of credits.**
   Spent chat call 1 of 5 on `"What did we decide about the retrieval
   split for the Q3 architecture review?"`. The api's error, verbatim:
   `Service Unavailable: the 'llm.roles.chat' binding ('openai/gpt-5.2', no
   fallback configured) could not be reached for classification: ...
   RateLimitError: OpenAIException - You have no credits remaining. Add
   credits to continue using the API at
   https://platform.openai.com/settings/organization/billing/.` This is an
   OpenAI account billing exhaustion, not a code defect — every subsequent
   call would fail identically, so I stopped at 1 of 5 spent rather than
   burning the rest of the authorized budget on a deterministic failure.
   Note for whoever owns `/status`: the chat/judge roles there show `"ok"`
   with detail "key present and verified against the provider's free list
   endpoint" — that's a cheap check that doesn't consume credits and does
   not catch this failure mode; it will keep saying "ok" until someone
   tops up the account or a real chat call is attempted. The UI's handling
   of the failure itself is correct and demo-safe: it shows a clear,
   readable error box rather than a fabricated answer, which is honestly
   the right behavior under the parent spec's "no citation no answer"
   constraint. **Fallback:** none — the "ask → cited answer → open moment"
   legs of the demo path cannot run live until the OpenAI account has
   credits (or a fallback model is configured for `llm.roles.chat`).
   Everything downstream of a citation (open moment, replay) was verified
   working via direct navigation instead (see above).

## Known issue, not a regression (already separately tracked)

**Some screens are mislabeled `participant-gallery`.** On "Q3 Architecture
Review," the screen at 0:20 is visibly a bullet-point slide ("Retrieval
Split Graph and Document Index" deck) but is labeled `participant-gallery`
in the film-strip; screens at 0:00, 6:32, 6:38 (also slides) are correctly
labeled `ui-screen`, and 0:02, 6:50, 7:02 (actual two-person webcam shots)
are correctly labeled `participant-gallery`. So the classifier is right
most of the time but wrong on at least one same-chrome dense slide. This
matches the git history already on `main` — a `capture-view-classification`
break-fix spec exists (drafted after "demo-002 slides mislabeled
participant-gallery," landed as `demo-001-capture-recall`, with the sprint
note "capture-view-classification clear to start" as of the commit this
worktree branched from). It's screen-classification data coming from the
API, not something `web/src` computes — the UI is rendering the `viewType`
field faithfully. Nothing to fix here within this story's boundary; noting
it so the presenter isn't surprised if it comes up on a different meeting.

## ui-2 width advisory (CAP-2 judgment call, not a bug)

`web/src/App.tsx:129` wraps every page (including the CAP-2 three-column
meeting view) in `max-w-5xl` (1024px), centered. Judged live at 1440×900:
it's **usable, not broken** — all three columns (screens film-strip,
transcript, artifact rail) are legible and every element is clickable —
but it's on the tight side: transcript lines wrap inside a ~370px column,
screen thumbnails are a single narrow ~160px strip, and there's
substantial unused horizontal margin on both sides of the page at
1440px+. I did not widen it: this is a shared layout file touched by every
page in the app, the demo doesn't depend on it, and there wasn't enough
remaining test bandwidth tonight to re-verify all four screens after a
layout change this close to the demo. Recommend `max-w-6xl` or a
meeting-view-specific override post-demo.

## Chat-call spend

Authorized: 5 live `/chat` calls, paid `openai gpt-5.2` role, granted
2026-08-21 for this dry-run only.

**Spent: 1 of 5.** The one call failed at the provider (OpenAI account has
no credits — see Blocking issue 2). No further calls were issued: the
failure is deterministic and provider-side, so repeating it would not
produce new information and would just burn budget. The worker was never
started, stopped, or restarted.

## Verification run

- `make web-test` (worktree `ui-5`, branch `story/ui-5`): **250 passed,
  250 total, across 14 test files.** No failures, no skips.
- Web build (`pnpm run build`, i.e. `tsc -b && vite build`, the same build
  `make test`'s web step runs): **succeeded** — `tsc -b` clean, `vite
  build` emitted `dist/` (356.17 kB JS / 107.36 kB gzip, 34.95 kB CSS)
  with no errors or warnings.

## Regressions found / fixed

**None found in `web/src`.** Every screen in the new CAP-1/2/3/4 chrome
rendered correctly with real data, handled empty/failed/transcript-only
states honestly, and degraded gracefully (readable error boxes, no
crashes, no invented data) when the two infra-level failures above hit it.
No code changes were made in this worktree; nothing to fall back to
because nothing failed at the UI layer.

## What the presenter needs to know before tomorrow morning

1. Corpus search will return "No moments match that search" for
   everything right now (Meilisearch index/embedder issue). Consider
   re-projecting the search index before the demo, or scripting around
   the search leg if that can't happen in time.
2. Ask-the-corpus will fail with a visible OpenAI billing error until the
   OpenAI account has credits added (or a fallback chat model is
   configured). This blocks the "ask → cited answer" leg entirely.
3. Everything else — home dashboard, both meeting-view shapes (with and
   without screens), moment pages, real video replay with synced
   transcript, and the configuration/status pages — works live, tonight,
   against real data, with no secrets leaking and no UI regressions.
4. `/status` (top-right "attention needed" chip, and the `/status` page)
   already surfaces the degraded state honestly — point the audience at
   it as a feature if search/chat come up before they're fixed.
