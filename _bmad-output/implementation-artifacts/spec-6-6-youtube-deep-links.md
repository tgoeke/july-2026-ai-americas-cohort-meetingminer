---
title: 'Story 6.6: YouTube Deep Links'
type: 'feature'
created: '2026-08-29'
status: 'done'
baseline_revision: 'd8a279f8882d24beef8b99c4c5db00d45b057bcd'
review_loop_iteration: 1
followup_review_recommended: false
context: []
warnings: [oversized]
deferred:
  - summary: >-
      The moments stage nulls a moment's source_deep_link once replay exists, so the beside-replay YouTube link is reachable on real data only from the drill-down until the stage retains the link.
    evidence: |-
      `server/meetingminer/pipeline/stages/moments.py:301-302` sets `deep_link = None if has_replay else ctx.drop.stream_url`, and `:385-399` nulls the column on superseded rows once replay exists; store-backed assertions pin it (`server/tests/test_worker_moments.py:434` "replay exists, so no transitional link", `test_augmentation.py:208`). Every YouTube meeting story 6.2 mints has a recording, so `MomentDetail`, `SearchHit`, and `CitationModel` arrive with `sourceDeepLink: null`; only `_DRILLDOWN_HEADER` (`server/meetingminer/api/moments.py:160-163`) reads `meeting.provenance->>'url'` regardless of replay. Pre-existing pipeline rule, surfaced by this story; server tests are owned by in-flight story 11-1 and the shared stores cannot be claimed unattended. Needs a `docs/backlog.md` entry and a server change: retain the link when replay exists (the web already prefers replay for non-YouTube hosts, so nothing else changes).
    location: >-
      server/meetingminer/pipeline/stages/moments.py:301-302
    severity: medium
---

<intent-contract>

## Intent

**Problem:** A moment from a YouTube meeting has no way back to the original video at that moment: the web offers a source deep link only when no local replay exists, and labels every link "Open in Stream" (UX-DR12; Story 6.6; Sprint Change Proposal 2026-08-29).

**Approach:** Teach the shared affordance helper to recognise a YouTube `sourceDeepLink`, build a moment-timed URL with the browser `URL` API, and return it *beside* replay; then render "Open on YouTube at H:MM:SS" as a secondary outline link in moment view, drill-down, chat citations, and search hits, leaving non-YouTube links and replay-less meetings exactly as they behave today.

## Boundaries & Constraints

**Always:**
- Replay stays primary: the YouTube link is rendered after the Replay button, as an outline-styled anchor (`target="_blank" rel="noreferrer"`), never as the default-variant button (EXPERIENCE.md · Voice: "replay first, the source second").
- The timed URL is built by parsing with `new URL(...)` and `searchParams.set('t', '<whole seconds>')` — replace-or-insert, never string concatenation, so an existing `t` is replaced and a URL with or without a query gets exactly one `t`. A `#t=…` fragment is dropped when a `t` is set.
- YouTube means hostname `youtu.be`, `youtube.com`, or any `*.youtube.com` subdomain, over `http:`/`https:` only. A timed link is built for `youtu.be/<id>` and `youtube.com/watch` paths; another YouTube path (`/shorts/`, `/embed/`, `/live/`) gets the link untimed ("Open on YouTube") because no time syntax for it has been verified — nothing invented.
- Accessible names carry the offset: the anchor's text is `Open on YouTube at {offsetLabel(startMs)}`; any decorative `↗` glyph is `aria-hidden`.
- `safeHref`'s scheme rule still gates every rendered `href`; an unsafe scheme still renders as the existing inert text.
- Non-YouTube hosts: with replay, no source link is rendered (today's "replay wins"); without replay, the untimed link labelled "Open in Stream" is the sole affordance, exactly as today.
- Every element rendered is backed by fields the api serves today (`sourceDeepLink` + `startMs` on `MomentDetail`, `SearchHit`, `CitationModel`; `MeetingDrilldownResponse.sourceDeepLink` + `startOffsetMs`/`startMs` per row). No new endpoint, no `make client`.
- Design companion: `_bmad-output/planning-artifacts/ux-designs/ux-meetingminer-2026-08-29/` (`EXPERIENCE.md`, `DESIGN.md`, `updated: 2026-08-29`, adopted at `2c7af74`). Deviations, if any, go under `## Design deviations` in this spec.

**Block If:**
- Landing this requires changing how the `moments` stage stores `source_deep_link` (server/tests are owned by in-flight story 11-1 and store-backed suites cannot be claimed unattended) — record the gap in Design Notes instead and stay web-only.

**Never:**
- No server, pipeline, or `web/src/client/` change; never hand-edit the generated client.
- No `docs/backlog.md` edit (story 11-1 has it in flight); no `docs/project-record.md` entry (epic-level, recorded at epic close).
- No YouTube embed/iframe player, no fetch to YouTube, no video-id validation — the link is the drop's URL with a time parameter.
- No change to `ReplayPlayer`, to the single-open-player pattern, or to `MomentListItem`/rail rendering.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Watch URL, no query | `https://www.youtube.com/watch` … `?v=abc`, `startMs 754000`, replay | `…/watch?v=abc&t=754`; replay button first, then `Open on YouTube at 12:34` | No error expected |
| Watch URL with existing `t` | `…/watch?v=abc&t=10s&list=x`, `startMs 65000` | `…?v=abc&t=65&list=x` — one `t`, other params kept | No error expected |
| youtu.be, bare | `https://youtu.be/abc`, `startMs 3661000` | `https://youtu.be/abc?t=3661`; label `Open on YouTube at 1:01:01` | No error expected |
| youtu.be with query + `#t=` fragment | `https://youtu.be/abc?si=z#t=30s`, `startMs 5000` | `https://youtu.be/abc?si=z&t=5`, fragment dropped | No error expected |
| Non-watch YouTube path | `https://www.youtube.com/shorts/abc`, replay | link kept untimed; label `Open on YouTube` | No error expected |
| YouTube, no replay | `hasRecording: false`, watch URL | Sole affordance: timed link labelled `Open on YouTube at H:MM:SS`; no Replay button | No error expected |
| Other host, replay | `https://example.sharepoint.com/stream.aspx?id=x`, replay | Replay only; no source link (unchanged) | No error expected |
| Other host, no replay | same URL, `hasRecording: false` | `Open in Stream`, untimed, sole affordance (unchanged) | No error expected |
| Unsafe scheme | `javascript:alert(1)`, either state | Inert text, never an anchor (unchanged) | Rendered as existing `*-unsafe-link` text |
| Negative / NaN offset | `startMs -1` or `NaN` | `t=0`, label `Open on YouTube at 0:00` | Clamped, no throw |
| Chat citation from YouTube | `CitationModel{sourceDeepLink: watch URL, startMs}` | Citation row gains `Open on YouTube at H:MM:SS` beside `Open moment` | No error expected |
| Chat citation, other/null link | `sourceDeepLink: null` or SharePoint | Row unchanged (offset + `Open moment` only) | No error expected |
| Drill-down, YouTube meeting with recording | `MeetingDrilldownResponse.sourceDeepLink` watch URL | Every screenshot row and transcript row: Replay, then `Open on YouTube at <row offset>` | No error expected |
| Drill-down degraded, YouTube | `hasRecording: false`, watch URL | Header link labelled `Open on YouTube` (untimed — meeting scope) where the strip would be | No error expected |

</intent-contract>

## Code Map

- `web/src/lib/affordance.ts` -- the shared decision. `Affordance` union (line 21), `SAFE_LINK_SCHEMES`/`safeHref` (36–48), `ReplayEvidence` (53–55), `affordanceOf` (57–68: `hasRecording` → `replay`, else deep link/inert/none), `offsetLabel` (72–80, `H:MM:SS`). This is the single place to add `SourceLink`, `sourceLinkOf(raw, offsetMs)`, and the `source` field on `replay`/`deepLink`. (change)
- `web/src/features/search/hits.ts:17-22` -- re-exports `Affordance`, `affordanceOf`, `offsetLabel`, `safeHref` from `@/lib/affordance`; add the new exports so search callers keep one import. (change, two lines)
- `web/src/features/moments/MomentView.tsx` -- `affordance` computed at 217 from `detail`; replay button 404–414 (`aria-label` "Replay recording at …"); `deepLink` anchor 415–428 (`data-testid="moment-deep-link"`, text "Open in Stream"); inert 429–437; none 438–445; player gate 447. Add the secondary link after the Replay button and label the sole link by provider. (change)
- `web/src/features/moments/MeetingMoments.tsx` -- `headerAffordance = affordanceOf(data)` (309, meeting scope, no offset); `replayControls(key, where)` (325–341) rendered at 439 (film strip, `shot.startOffsetMs`) and 803 (transcript row, `segment.startMs`); degraded header block 696–727 (`drilldown-deep-link`, "Open in Stream"). Add a `sourceControls(startMs, where)` sibling built from `data.sourceDeepLink` and render it beside both `replayControls` calls; label the header link by provider. (change)
- `web/src/features/chat/ChatPanel.tsx` -- citation rows 255–286: offset span (265–267), `Open moment` button (274–283). `CitationModel` carries `sourceDeepLink` + `startMs` and no `hasRecording`; render the YouTube link only (no other-host behaviour exists on this surface). Import `sourceLinkOf` beside `offsetLabel` (line 4). (change)
- `web/src/features/search/CorpusSearch.tsx` -- `affordance = affordanceOf(hit)` (276); replay button 379–392; `deepLink` anchor 393–402 (`hit-deep-link-${key}`, "Open in Stream"); inert 403–415; none 417–425. Same treatment as the moment view; pass `hit.startMs`. (change)
- `web/src/components/ui/button.tsx` -- `buttonVariants({ variant: 'outline', size: 'sm' })` gives an `<a>` the outline-button look without the base-ui `render` prop. (read-only)
- `web/src/client/types.gen.ts` -- `MomentDetail` (999), `MomentListItem` (1071), `SearchHit` (1531), `CitationModel` (175), `MeetingDrilldownResponse` (732, meeting-level `sourceDeepLink` = `meeting.provenance->>'url'` verbatim). (read-only, generated)
- `server/meetingminer/pipeline/stages/moments.py:295-302, 385-399` -- `deep_link = None if has_replay else ctx.drop.stream_url`; a recording or any screenshot retires the moment-level link, and ~9 store-backed assertions in `server/tests/test_worker_moments.py` / `test_augmentation.py` pin it. Read-only evidence for the Design Notes gap; not changed here.
- `server/meetingminer/api/moments.py:154-163` -- `_DRILLDOWN_HEADER` selects `provenance->>'url'` regardless of replay: the drill-down is the one surface where a YouTube meeting *with* a recording carries its link today. (read-only)
- `_bmad-output/planning-artifacts/ux-designs/ux-meetingminer-2026-08-29/EXPERIENCE.md` -- Voice table row "Replay 12:40 · Open on YouTube at 12:40 ↗"; Component Patterns · Moment card (line 85: parse with `URL`, replace/insert the provider time parameter, never concatenate); Accessibility (206: names include the offset); Data Traceability · "YouTube deep link (6.6)" (319–323). `findings-for-epics.md` F-15 names the `affordanceOf` change. (read-only design contract)
- Tests to extend: `web/src/features/moments/MomentView.test.tsx` (`detail()` fixture 33–66, deep-link cases 546–597), `web/src/features/moments/MeetingMoments.test.tsx` (`response()` 36–…, degraded cases 477–517), `web/src/features/chat/ChatPanel.test.tsx` (`citation()` 67–76, citation click 120–149), `web/src/features/search/CorpusSearch.test.tsx` (deep-link cases 399–470, `affordanceOf` unit cases 703–722 assert the old shape and must move to the new one). New `web/src/lib/affordance.test.ts` beside `media.test.ts` for the URL matrix.

## Tasks & Acceptance

**Execution:**
- `web/src/lib/affordance.ts` -- add `SourceLink` (`{ provider: 'youtube'; href; offsetMs: number | null } | { provider: 'other'; href }`), `sourceLinkOf(raw, offsetMs)`, `sourceLinkLabel(link)`; extend `Affordance` to `replay: { source: SourceLink | null }` (YouTube only — other hosts stay `null`) and `deepLink: { source: SourceLink }`; `affordanceOf(evidence, offsetMs = null)` -- one decision for four consumers (F-15)
- `web/src/lib/affordance.test.ts` -- unit-test the I/O matrix's URL rows and the affordance rows -- pins replace-or-insert, host rules, clamping, and "other host with replay → no link"
- `web/src/features/search/hits.ts` -- re-export the new symbols -- keeps search's single import path
- `web/src/features/moments/MomentView.tsx` -- pass `detail.startMs`; render the secondary anchor (`data-testid="moment-youtube-link"`, outline-button classes) after Replay; label the sole `moment-deep-link` by provider -- UX-DR12 on the moment view
- `web/src/features/moments/MeetingMoments.tsx` -- `sourceControls` beside both `replayControls` sites using `data.sourceDeepLink` and the row offset (`data-testid="drilldown-youtube-link-<key>"`); header link labelled by provider -- UX-DR12 on the drill-down
- `web/src/features/chat/ChatPanel.tsx` -- YouTube-only anchor (`data-testid="chat-citation-youtube-<momentId>-<index>"`) after `Open moment` -- UX-DR12 on chat citations
- `web/src/features/search/CorpusSearch.tsx` -- same as the moment view with `hit.startMs` (`data-testid="hit-youtube-link-<key>"`) -- the helper's fourth consumer stays consistent
- `web/src/features/moments/MomentView.test.tsx`, `MeetingMoments.test.tsx`, `web/src/features/chat/ChatPanel.test.tsx`, `web/src/features/search/CorpusSearch.test.tsx` -- add both-hosts × both-replay-states cases per surface; update the `affordanceOf` shape assertions -- the AC's "web tests cover both hosts and both replay states"

**Acceptance Criteria:**
- Given a `MomentDetail` with `hasRecording: true` and a YouTube watch `sourceDeepLink`, when `MomentView` renders, then the Replay button precedes an anchor named `Open on YouTube at <offset>` whose `href` carries exactly one `t=<seconds>` and `target="_blank"`, and the player still opens only from Replay.
- Given the same detail with a SharePoint `sourceDeepLink`, when rendered, then no anchor is rendered beside Replay.
- Given `hasRecording: false` and a YouTube link, when any surface renders, then the timed anchor is the sole affordance and no Replay button exists; given a SharePoint link, the anchor reads `Open in Stream` with the href unchanged.
- Given a drill-down for a YouTube meeting with a recording, when it renders, then each screenshot row and each transcript row carries an anchor timed at that row's own offset, and `t` differs between rows with different offsets.
- Given a chat answer whose citation carries a YouTube link, when citations render, then the row offers `Open on YouTube at <offset>` and `Open moment` still opens by `momentId` alone.
- Given `make web-test`, when it runs, then every suite passes; given `pnpm --dir web run build` and `pnpm --dir web run lint`, then both exit 0.

### Review Findings

- [x] [Review][Patch] Preserve unsafe source addresses as inert text when replay exists [web/src/lib/affordance.ts:145] — fixed on `story/6-6-review` in `eef842d` and landed on `main` as `28ea43d`: Replay remains primary while recorded MomentView, search, and drill-down rows render a refused address as inert text, never an anchor.

## Spec Change Log

## Review Triage Log

### 2026-08-29 — Follow-up review
- intent_gap: 0
- bad_spec: 0
- patch: 1: (high 0, medium 0, low 1) — fixed in `eef842d`
- defer: 0 new; the existing medium data-retention defer remains
- reject: 21
- addressed_findings:
  - `[low]` `[patch]` unsafe source addresses disappeared whenever replay existed, contradicting the I/O matrix's “either state” rule — the replay affordance now carries `inertSource`, and MomentView, search, and drill-down rows render it after Replay as text, never an anchor (`eef842d`).
- followup_review_recommended: false — score = 3×0 + 1×1 = 1 (< 5).

### 2026-08-29 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 7: (high 0, medium 0, low 7)
- defer: 1: (high 0, medium 1, low 0)
- reject: 16
- addressed_findings:
  - `[low]` `[patch]` `sourceLinkOf` cleared every URL fragment, not only a `#t=` one as the Always rule states — now `if (/^#t=/i.test(url.hash)) url.hash = ''`, with tests that `#comments` survives and `#T=1m` is dropped (commit f5c49180ea058dbaf58e20914d8feb593d98e0d3).
  - `[low]` `[patch]` The outline anchor JSX was copied seven times across four surfaces — replaced by one `web/src/components/SourceLinkAnchor.tsx` (`{ link, testId }`) with its own test; every `data-testid` and label unchanged (f5c4918).
  - `[low]` `[patch]` `rel="noreferrer"` was never asserted on the search and drill-down anchors — asserted on `hit-youtube-link-*`, `hit-deep-link-*`, `drilldown-youtube-link-*`, `drilldown-deep-link` (f5c4918).
  - `[low]` `[patch]` Every test offset was a whole second, leaving floor-vs-round unpinned — added `sourceLinkOf(WATCH, 65_900)` → `t=65` and `Open on YouTube at 1:05` (f5c4918).
  - `[low]` `[patch]` JSDoc cited `EXPERIENCE.md`, a file under the untracked `_bmad-output/` tree — now cites UX-DR12 / story 6.6 (f5c4918).
  - `[low]` `[patch]` `hits.ts` header sentence did not name the three new re-exports — updated (f5c4918).
  - `[low]` `[patch]` The "keeps other params" unit test kept nothing — input now carries `&list=x` and asserts it survives beside `t` (f5c4918).
- deferred: the `moments` stage nulls `source_deep_link` once replay exists, so three of the four beside-replay surfaces are unreachable on real data until the stage retains the link (frontmatter `deferred`, medium; pre-existing pipeline rule, server tests owned by story 11-1).
- rejected, for the record: `searchParams.set` re-serialising other params (the intent mandates the browser URL API); `/watch/`, `/WATCH`, `youtu.be/<id>/` normalisation (not YouTube URL forms yt-dlp emits; inventing them is the fabricated behaviour the project refuses); a `/watch` URL without `v` (the drop's URL is broken regardless of `t`); per-row `new URL` cost on drill-down re-render (microseconds per row); a chat citation showing the YouTube link without a wired `onOpenMoment` (a real link is not a dead affordance); "opens in a new tab" in the accessible name (the design spec fixes the name and hides glyphs); `↗`/outline keyed on provider rather than `target` (AC2: "Open in Stream" keeps its existing look); `offsetMs: null` meaning both meeting scope and unverified path (the untimed label is the honest signal; recorded in Design Notes); `sourceControls` gating through `affordanceOf` rather than the `hasRecording` const (one decision, by design); non-YouTube replay-less citations still linkless in chat (existing behaviour the intent preserves); `offsetMs` holding raw ms while `t` floors (documented; now pinned by the fractional test); sprint-status vs spec status (integrate's job); literal `HH:MM:SS` (the design spec's `H:MM:SS`/`offsetLabel` form, matching the Replay button); drill-down rows timed on non-moment rows and replay-less drill-down rows left untimed (both recorded planner decisions — Design Notes and the I/O matrix); `CorpusSearch` changed though unnamed by the story (EXPERIENCE.md traceability lists `SearchHit`, and the shared type change required it).

## Design Notes

**Why the affordance returns both, not a second helper.** F-15 (findings-for-epics.md) names `affordanceOf` as the thing 6.6 changes. Carrying `source` on `replay` keeps the four consumers on one decision and makes "other host + replay → null" a tested rule rather than four `if`s. The `offsetMs` parameter is optional because the drill-down header is meeting-scoped: a YouTube link there is untimed ("Open on YouTube"), while each row times its own.

**Time parameter.** `t=<whole seconds>` is the one form both `youtube.com/watch` and `youtu.be` accept, so one rule serves both hosts. `URLSearchParams.set` is the replace-or-insert primitive the AC asks for; the `#t=` fragment is the only other carrier of a time and is dropped when a `t` is set.

**Known data gap, deliberately not closed here.** The `moments` stage writes `source_deep_link` only when the meeting has neither a recording nor screenshots (`moments.py:295-302`), and the superseded-row update nulls it once replay exists (`:385-399`). So on `MomentDetail`, `SearchHit`, and `CitationModel` a YouTube meeting *with* a recording — every meeting story 6.2 will mint — carries `sourceDeepLink: null`, and the secondary link this story renders will only appear on the drill-down (whose header reads `meeting.provenance->>'url'` directly) until the stage retains the link when replay exists. That change is server-side, pinned by store-backed tests in `test_worker_moments.py` and `test_augmentation.py`, and those files are owned by in-flight story 11-1; the shared stores cannot be claimed unattended. The web side is complete and tested against the field the design spec maps it to; the retention change is a named follow-up for the owner (backlog entry once 11-1 lands). The UI is already safe if it lands: replay wins for non-YouTube hosts.

**Working tree:** implemented in `/Users/devopsterus/current/cohort/meetingminer-wt/6-6` on branch `story/6-6` (baseline `d8a279f8882d24beef8b99c4c5db00d45b057bcd`), never in the main checkout.

## Auto Run Result

Status: done

**Implemented:** the shared affordance decision now classifies a source deep link by provider and, for YouTube, times it at the moment with the browser `URL` API (`t=<whole seconds>`, replace-or-insert, one `t`, `#t=` fragment dropped, other fragments kept). Moment view, drill-down (per screenshot row and per transcript row, each at its own offset), chat citations, and search hits render `Open on YouTube at H:MM:SS` as an outline anchor after Replay; without replay a YouTube link is the timed sole affordance and any other host keeps the untimed `Open in Stream`. One `SourceLinkAnchor` component renders every such anchor.

**Files changed (13, all under `web/src`):**
- `web/src/lib/affordance.ts` — `SourceLink`, `sourceLinkOf`, `sourceLinkLabel`; `Affordance.replay.source` / `deepLink.source`; `affordanceOf(evidence, offsetMs = null)`.
- `web/src/lib/affordance.test.ts` — new; the URL and affordance matrix (fragment scope, other-params survival, fractional offset included).
- `web/src/components/SourceLinkAnchor.tsx`, `SourceLinkAnchor.test.tsx` — new (review patch); the one anchor renderer and its test.
- `web/src/features/search/hits.ts` — re-exports the new symbols.
- `web/src/features/moments/MomentView.tsx` — timed at `detail.startMs`; `moment-youtube-link` beside Replay; sole link labelled by provider.
- `web/src/features/moments/MeetingMoments.tsx` — `sourceControls` beside both `replayControls` sites; degraded header labelled by provider, untimed.
- `web/src/features/chat/ChatPanel.tsx` — `chat-citation-youtube-<momentId>-<index>` after `Open moment`, YouTube only.
- `web/src/features/search/CorpusSearch.tsx` — timed at `hit.startMs`; `hit-youtube-link-<key>`; sole link labelled by provider.
- `MomentView.test.tsx`, `MeetingMoments.test.tsx`, `ChatPanel.test.tsx`, `CorpusSearch.test.tsx` — both hosts × both replay states per surface, order, names, `target`, `rel`, one-`t`.

**Commits on `story/6-6` (baseline d8a279f8882d24beef8b99c4c5db00d45b057bcd):**
- a8ae945ef582a542a7bc5daa48a29e637bc8d719 — feat: Story 6.6 — YouTube deep links beside replay (UX-DR12)
- f5c49180ea058dbaf58e20914d8feb593d98e0d3 — fix: Story 6.6 review — one SourceLinkAnchor, keep non-time fragments

**Review findings:** 24 after dedup — 7 patched (all low), 1 deferred (medium; frontmatter `deferred`), 16 rejected, 0 intent gaps, 0 bad-spec.

**Follow-up review recommendation:** true — patched: high 0, medium 0, low 7; score = 3×0 + 1×7 = 7 (≥ 5). Every patch is cosmetic or test-only; the flag is the formula's, not a correctness concern.

**Verification performed (worktree `../meetingminer-wt/6-6`, HEAD f5c4918, observed by the run after the patches):**
- `make web-test` → 16 test files passed, 288 tests passed (15 files / 283 tests observed after a8ae945, before the review patches; the `main` baseline count was not run by this pass).
- `pnpm --dir web run build` → `tsc -b && vite build` exit 0 (`✓ built`).
- `pnpm --dir web run lint` → 0 errors; 4 pre-existing `react(only-export-components)` warnings in untouched files.
- `git diff --stat main -- web/src` → 13 files, +739/−83; nothing outside `web/src` differs from `main` except `main`'s own later commit a22d67c (untracks `_bmad-output`), which touches no story file.
- Matrix audit: all 14 rows covered by `affordance.test.ts` rows and the per-surface component cases; all ran and passed.
- `git rev-list --left-right --count HEAD...@{u}` → `0	0`; `git status --porcelain` → empty.

**Residual risks:** on real data the beside-replay link is reachable today only from the drill-down (deferred finding); `main` moved by one commit after the baseline (no overlap) so the integrator merges, not fast-forwards; the spec's "only the files named under Execution" check reads as those 10 plus the review-added `SourceLinkAnchor` pair and the unit test.

**Follow-up review remediation:** `eef842d` preserves unsafe source provenance as inert text beside Replay on MomentView, search hits, and every drill-down row. Verification on `story/6-6-review`: 16 test files / 291 tests passed; build exit 0; lint 0 errors with the same four pre-existing warnings.

## Verification

**Commands:**
- `make web-test` (from the worktree; store-free) -- expected: all vitest suites pass, new cases included
- `pnpm --dir web run build` -- expected: `tsc -b` and `vite build` exit 0
- `pnpm --dir web run lint` -- expected: oxlint reports 0 errors
- `git diff --stat main -- web/src` -- expected: only the files named under Execution
