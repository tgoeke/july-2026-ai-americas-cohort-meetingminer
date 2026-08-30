---
name: MeetingMiner
status: draft
updated: 2026-08-29
design: ./DESIGN.md
sources:
  - _bmad-output/planning-artifacts/epics.md  (Story 6.1 acceptance criteria; Epics 6, 7, 8, 10; FR33–FR43; UX-DR12–UX-DR18)
  - _bmad-output/planning-artifacts/sprint-change-proposal-2026-08-29.md  (owner direction, both addenda)
  - _bmad-output/specs/spec-ui-reimagine/SPEC.md, reference-ui.md, current-ui-inventory.md
  - _bmad-output/specs/spec-meetingminer/SPEC.md  (parent contract: no citation no answer; AI never owns truth)
  - web/src/client/types.gen.ts, sdk.gen.ts  (the existing operations, worktree 6-1 at e5510c7)
  - web/src/features/**  (the screens that exist and their verbatim strings)
  - docs/architecture.md  (AD-4, AD-5, AD-10, AD-11, AD-13, AD-14, AD-15)
  - docs/glossary.md
---

# MeetingMiner — Experience Spine

> Peer of `DESIGN.md` (how it looks). This file owns how it works: information architecture, behavior, states, interactions, accessibility, and the data every element is backed by. Token references use `{path.to.token}` against `DESIGN.md`'s frontmatter. Both spines win over every mock under `mockups/` and every study under `.working/` on conflict. Builders of stories 6.5, 6.6, 7.4, 8.3, 10.5, 10.6, and 10.7 cite this pair as their adopted design companion and deviate only with a reason recorded in the story's spec (`adoption.md`).

## Foundation

Desktop web, single surface, dark only. React 19 + react-router 7 + Vite, shadcn/ui components on Tailwind v4 with Base UI primitives (`components/ui/button.tsx`), Geist Variable. `DESIGN.md` is the visual identity and states the delta from `web/src/index.css`; this spine specifies only the behavioral delta from shadcn's defaults.

Minimum supported viewport **1280 × 800**; the recording target is Chrome on macOS at 1440 × 900 or wider. No mobile breakpoint, no touch-first gesture (pinch-zoom on the timeline is supported because trackpads emit it, not because phones exist).

One operator: the product owner — an architect who records their own meetings and demos and reviews them alone. Every Key Flow is a session of this one person. There are no roles, no sharing, no permissions.

Two contracts bind every screen and are not restated per element: **nothing on screen is invented** (a count is a database-of-record count, a reason is what the api returned, a name is what a human typed), and **no citation, no answer** (chat renders only from the structured citations array — AD-15 — never by parsing markers).

Routing: screens are `*.route.tsx` files discovered by `routes/registry.ts` and mounted in the shell's `<Outlet />`. The shell keeps the persistent chrome mounted across navigation; Back is browser history with a home floor. Story 10.7 changes what "home" is and how wide the shell is (see IA); it does not change the registry.

## Information Architecture

| Surface | Route | Reached from | Purpose | Builds in |
|---|---|---|---|---|
| **Moments** (default) | `/` | app open · chrome nav · brand | the most pressing moments first, each with its reason, replaying in place | 10.5, 10.7 |
| **Threads** | `/threads` · `/threads/:threadId` | chrome nav · a thread chip anywhere | a topic followed across meetings on a semantic-zoom timeline | 10.6, 10.7 |
| **Meetings** | `/meetings` | chrome nav · Add-meeting's "posted" step | the reimagined home's corpus counts and meeting cards, unchanged, relocated | 10.5, 10.7 |
| Meeting view | `/meetings/:meetingId` | a meeting card · a moment's meeting link | the dense three-column evidence view (story ui-3), plus a `Speakers` rail section | existing; 7.4 adds the section |
| **Speaker naming** | `/meetings/:meetingId/speakers` | the meeting view's `Speakers` section · Add-meeting's finished card | who spoke when; names assigned by a human | 7.4, 7.5 |
| Moment view | `/moments/:momentId` | a card's Open moment · a citation · a timeline evidence card | one moment: screenshot, replay, deep link, transcript, artifact rail | existing; 6.6 adds the YouTube link |
| **Add-meeting** | `/add` | chrome's Add meeting button (every screen) | one flow, four sources, validation before any write, progress to a live meeting card | 6.5 |
| Participants | `/participants` | chrome nav | rename and merge participants (story 2.4) | existing |
| Status | `/status` | chrome nav · health dot popover | live health per component and role, provider key validity, active binding per role | existing; 8.2 adds fields |
| **Settings** | `/settings` | chrome nav · model-select popover's "All roles…" | the declared stack read-only (story ui-4), plus the one editable thing: the model per role | existing; 8.3 adds the picker |

**What moved.** The reimagined home (`CorpusStats` + `MeetingsList` + the Participants button + the `api /health` panel) becomes the **Meetings** view at `/meetings`, unchanged inside; Moments takes `/`. The health panel is dropped from the front door — `/status` and the chrome's health dot already answer "is my environment up" — and stays on `/meetings`. Search and Ask stay in the chrome on every route, as today, side by side; Add meeting joins them.

**Chrome** (`{components.chrome}`), left to right: brand · primary nav `Moments · Threads · Meetings · Participants · Status · Settings` (current view underlined) · Search · Ask (with the model select inside it) · **Add meeting** (primary) · health dot + word. The chrome is sticky; child screens render under it at their own width (`DESIGN.md` · Layout & Spacing). The existing "← Back" control stays for child screens (meeting, moment, speakers, add) and keeps its history-floor behavior.

**Surface closure.** Every stated need lands on a surface: bring a meeting in → Add-meeting; who spoke → Speaker naming; which model → Settings and the ask box; what needs attention → Moments; what have we said about X over time → Threads; the corpus's scale → Meetings; open the source at this moment → Moment view, meeting view, chat citations, Moments cards (6.6). Every surface has a flow that lands there (Key Flows 1–6).

→ Composition reference: `mockups/moments.html`, `mockups/threads-bands.html`, `mockups/threads-moments.html`, `mockups/add-meeting-youtube.html`, `mockups/add-meeting-refusal.html`, `mockups/speaker-naming.html`, `mockups/ask-box-model-select.html`. Spines win on conflict.

## Voice and Tone

Microcopy rules. The brand posture (dense, literal, calm) lives in `DESIGN.md` · Brand & Style. The existing screens set the voice; new screens keep it.

| Do | Don't |
|---|---|
| `Moments 24` · `Threads 11` · `Speakers 4` — the count is part of the header | `Moments` with a badge somewhere else |
| `2026-08-14 · 12:40–14:05 · real` — ISO date, `H:MM:SS` offsets, corpus by its tag | `Aug 14`, `3 days ago`, `12:40 PM` |
| `Cannot reach the api at http://localhost:8000: fetch failed.` — the existing sentence, verbatim | `Something went wrong` |
| `youtube-drop: duration over cap — 3h 12m exceeds the configured 180 minutes. → Raise acquisition.youtube.maxDurationMinutes in config.yaml, or choose a shorter video.` — rule name, detail, remediation | `Video too long.` |
| `No participant graph for this meeting — no transcript speaker resolved to a participant record.` — absence stated in place, one sentence | an empty rail |
| `Unresolved — keep the tag` as the third choice, same weight as the other two | `Skip` |
| `Suggestions are shown, never applied — pick one or type a name.` | auto-filling the field with the top suggestion |
| `chat · claude-sonnet-5 · anthropic ● ok` | `Model: Claude (recommended)` |
| `Topics are machine-derived from the extract stage and named for navigation; rename or merge them here. They are never a fact in an answer.` | presenting a thread name as a conclusion |
| `Replay 12:40` · `Open on YouTube at 12:40 ↗` — replay first, the source second | `Watch on YouTube` as the primary |
| `ranked by decision, due date, recency, thread` — the signals, as nouns | `Recommended for you` |
| `→` before every remediation; the remediation names the file, the key, the process | `Please contact support` |
| Sentence case; no exclamation marks; no emoji; `api` lower-case as the codebase writes it | Title Case Buttons, `🎉`, `API` |

Words come from `docs/glossary.md`: *moment, meeting, thread, topic, artifact, drop, corpus, participant, speaker tag, alias, rerun, binding, catalog, role, provider*. "Acquisition" is the process; "Add meeting" is the button. A `SPEAKER_03` tag is a *tag* until a human names it.

## Component Patterns

Behavioral. Visual specs live in `DESIGN.md` · Components under the same names.

| Component | Where | Behavioral rules |
|---|---|---|
| Chrome | every route | Sticky. Current view underlined; keyboard `g m` / `g t` / `g e` jump to Moments / Threads / Meetings. Search and Ask keep their state across navigation (mounted once, as today). Add meeting navigates to `/add`. Health dot opens the existing status popover; its word is the existing `summarize()` label. |
| Section header | every list | Text + count from the data it heads, recomputed when a filter narrows: `Moments 24` becomes `Moments 6 of 24`. |
| Moment card | Moments | Click on the screenshot or title opens the moment view. **Replay** toggles the inline player under the screenshot; the card expands to span the grid; at most one card is expanded (opening another collapses the first — the single-open-key pattern `MeetingMoments` already uses). **Open moment** → `/moments/:id`. **Open on YouTube at H:MM:SS** is present only when `sourceDeepLink` is a YouTube URL; it opens a new tab at `sourceDeepLink` + `&t=<startMs/1000>s`. Kind chips filter the feed by that kind on click; thread chips open `/threads/:threadId`. The reason line is read-only. |
| Reason line | Moment card | Renders `reasons[]` from the feed in the api's order; `label` verbatim; the chip's kind is chosen by the reason's `kind` (artifact kinds → kind chip; `thread` → thread chip; `recency`, `published` → plain muted text). No reason is composed client-side; an empty `reasons[]` renders `ranked by recency` only if the api says so — otherwise the card shows no reason line and is logged, because a ranked item without a reason is a defect (story 10.4). |
| Kind chip | cards, rails, filters, timeline | Glyph + kind name. In a filter row it is a toggle; elsewhere a link to the filtered feed. Never rendered for a kind outside the seven `MomentArtifact.kind` values. |
| Thread chip | cards, reasons, timeline, moment view | `#name`; opens the thread in Threads focused at the meetings tier around the current moment. Hue from the stable hash (`DESIGN.md` · Threads). |
| Thread band | Threads | Rows in the list order. Hover on a bucket shows `14 mentions · 2026-06-08 → 2026-06-14`. Click or Enter on the band enters the thread (see Semantic Zoom). Density alpha is computed per visible window, so zooming rescales the quintiles. |
| Timeline canvas | Threads | DOM-rendered (SVG/HTML), never `<canvas>`, so every item is focusable and named. Continuous zoom and pan; tiers by threshold; fetch per tier per window. Full rules in Semantic Zoom. |
| LOD card | Threads, evidence tier | Screenshot, excerpt, artifact kind chips, anchor. **Replay** plays inline at the card; **Open moment** → `/moments/:id`. At most one player open on the canvas. |
| State bar + word | meeting cards, stepper, speaker rerun | Rendered from `stages[]` / acquisition `status` exactly as `StageProgress` does; `unknown` for anything this build does not recognise, never folded into a known state. Live-patched from `/jobs/events`. |
| Acquisition stepper | Add-meeting | Four bars: **launch** (POST accepted → `queued`), **running**, **posted**, **ingesting** (the meeting card's own bars take over). Polls `GET /acquisitions/{id}` every 2s while `queued | running`, stops on `posted | failed`. Log tail is a scrolling mono region, newest line last, `aria-live="off"` (it is noise) with a "Copy log" outline button. On `posted` the flow subscribes to `/jobs/events` for the returned job id and renders the meeting card in place, with the existing `Open` gate (`viewable`). |
| Source tab | Add-meeting | `role="tablist"`; arrow keys move, the panel swaps; a partially filled tab keeps its state when the user switches and back. Switching tabs never submits. |
| Refusal box | under a field, under the stepper, in the answer region, under the model select | In place; rule name first, then detail, then `→ remediation`. Sync refusals (409, 422 ProblemDetails) render from `title`/`detail`/`type` via `problemMessage()`; a failed acquisition renders the status file's refusal. Dismissed only by changing the input that caused it. Never a toast. |
| Speaker row | Speaker naming | One per tag from `/meetings/{id}/speakers`, sorted by talk time descending; the row is a button that selects the tag (clips and transcript follow). A resolved row (7.5, or after a rerun) shows the participant name beside the tag and a `Correct` action instead of `Name`. |
| Clip button | Speaker naming | Three per tag, at the api's sample offsets; press plays that clip in the one player on the panel from `offset` for **8 seconds** then pauses (`[ASSUMPTION]` the player gains an optional `endMs` — story 7.4's own web change). Keyboard `1` `2` `3` play clip n of the selected tag. |
| Name field | Speaker naming | A combobox: typing filters `GET /participants` display names as suggestions; suggestions are never auto-selected — Enter with a highlighted suggestion picks it, Enter with none submits the typed text as a new name. A third control, **Unresolved — keep the tag**, is a button of equal weight. **Save** sends one `PUT` per tag. |
| Model select | ask box, Settings | Trigger shows `role · label · provider ● state`. Popover lists the catalog grouped by provider with health per option; ✓ marks the active binding; selecting calls `PUT /settings/roles/{role}` and, on success, updates the trigger — the next question uses the new binding. An option whose provider key is `invalid`/`missing` stays selectable and is rendered muted with its remediation, because choosing it must fail *loudly* at the ask, not silently be filtered out. Keyboard: arrow keys move, Enter selects, Esc closes. |
| Ask box | chrome | As today (`ChatPanel`): textarea, Ask, streaming answer, citations opening moment view. Adds the model select inside the box's header row. A binding failure arrives as a named `problem` (`urn:meetingminer:problem:…`) and renders as a refusal box in the answer region; the previous answer is not cleared. |
| Filters row | Moments | Three selects — corpus (`real` / `scripted` / all), thread (from `GET /threads`, searchable), kind (the seven) — plus a hidden `meeting` filter set when arriving from a meeting. Filters are URL query params so a filtered view is a link. |
| Thread list | Threads | Searchable by name (client-side over `GET /threads`), sortable by activity (mentions in the visible window) and recency (last mention). Selecting a thread enters it; `Rename` and `Merge into…` are inline, mirroring `Participants` (rename input + Save/Cancel; merge select + Merge), against story 10.2's curation api; every list item carries the sentence `machine-derived` in `{typography.label}`. |

## State Patterns

| State | Surface | Treatment |
|---|---|---|
| Cold load | Moments | `Ranking the corpus…` in muted text under the header; no skeleton cards (a skeleton is an invented card). |
| Empty corpus | Moments | `No moments yet. Add a meeting — the front door fills once one is ingested.` with the Add meeting button repeated in the body. |
| Filter empty | Moments | `No moments match corpus real · thread #retrieval split · kind decision.` — the active filters named, a `Clear filters` outline button. |
| Feed unavailable | Moments | The existing sentence: `Cannot reach the api at {API_BASE}: {message}.` + Retry. If a previous feed is on screen it stays, with ` The cards below may be stale.` appended (the `MeetingsList` pattern). |
| Card without recording | Moments | No Replay; the action row says `Transcript only — no recording and no source link.` or offers the deep link, per `affordanceOf`. |
| Card without screenshot | Moments | Frame shows `{colors.muted}` with `No screenshot — transcript-anchored moment.` |
| Cold load | Threads | The list renders first (`GET /threads`), then bands as `level=bands` resolves; the canvas shows the axis and `Loading bands…` in the canvas area. |
| No threads | Threads | `No threads yet. Threads appear once two meetings share a topic — extract runs topics per meeting (story 10.1).` |
| Tier fetch pending | Threads | The outgoing tier stays drawn; a thin `{colors.state-running-bar}` progress line at the canvas top; no skeletons. |
| Tier fetch failed | Threads | Refusal box under the canvas with the api's problem; the outgoing tier stays; zooming further is blocked until Retry succeeds. |
| Beyond palette | Threads | Bands 25+ in grey; the list item says `beyond the 24-hue palette — identified by name`. |
| Reduced motion | Threads | No cross-fade, no zoom easing, no pulse (see Semantic Zoom). |
| Idle | Add-meeting | YouTube tab selected; URL field focused; Submit disabled until the URL passes the shape check. |
| Shape-invalid URL | Add-meeting | Under the field, muted: `Not a YouTube video URL — paste a watch or youtu.be link.` Submit stays disabled. Not a refusal box (nothing was refused; nothing was sent). |
| Sync refusal | Add-meeting | Refusal box under Submit from ProblemDetails: 409 `acquisition already running for youtube:<id>` with `→ open the running acquisition` link; 422 with the validator's detail. |
| Launched | Add-meeting | Stepper appears under the form; the form locks (fields read-only) until `posted | failed`; `Cancel` is not offered (6.4 defines no cancel). |
| Tool refusal | Add-meeting | `failed`: refusal box with the rule name from the status file (`youtube-drop: private or removed video`, `…: no video stream`, `…: yt-dlp missing`, `…: duration over cap`) and the remediation; the form unlocks; the log tail stays. |
| Already ingested | Add-meeting | The tool reports `exists` for a known `youtube:<videoId>`: stepper ends at **posted** with `Already in the corpus — nothing downloaded.` and the existing meeting card (`[ASSUMPTION]` how `exists` maps onto the 6.4 status enum is an open question recorded in `findings-for-epics.md`). |
| Files classified | Add-meeting (local / Zoom / Teams tabs) | Each dropped file gets a row: name · size · classification (`recording.mp4`, `transcript.vtt · zoom dialect (Name: cues)`, `transcript.txt · teams`, `ignored — not a drop file`); dialect is a select defaulted from the sniff, never locked. Submit enabled when at least one of recording/transcript is present and title + date are filled. |
| Posted → ingesting | Add-meeting | The meeting card renders under the stepper with its stage bars live from `/jobs/events`; `Open` enables when `viewable`; a `Name speakers` link appears once `transcribe` is `done` and the meeting had no speaker-attributed transcript. |
| No diarization | Speaker naming | `No speaker tags for this meeting — the transcript arrived speaker-attributed, or the diarizer is noop (config.yaml: diarizer.engine).` |
| Selected tag | Speaker naming | Clips and the tag-filtered transcript show that tag; the name field is empty and focused. |
| Saving | Speaker naming | `Saving…` on the button; on 200 the row shows the name and a `rerun queued` state word; stage bars for `align → moments → extract` appear in the panel header, live from `/jobs/events`. |
| Rerun landed | Speaker naming | Transcript segments re-read from `/drilldown`; the panel states `Rerun landed 14:02:11 — transcript, graph, and extractions now name SPEAKER_03 as Priya Natarajan. Moment ids and citations unchanged.` |
| Resolved by source | Speaker naming (7.5) | Rows already resolved show the name and `from transcript`; `Correct` opens the same name field. |
| Catalog with one entry | Model select | The select still renders (one option, ✓) so the surface is the same; no "choose" affordance is invented. |
| Invalid provider key | Model select | Option muted with `● invalid → set ANTHROPIC_API_KEY in .env, restart the api`; still selectable. |
| Binding failed at the ask | Ask box | Refusal box in the answer region: `chat: binding failed — anthropic/claude-sonnet-5: 401 invalid api key → set ANTHROPIC_API_KEY in .env, restart the api, or pick another binding.` No substitute answer, no silent fallback. |
| Save refused | Settings | 422 `binding not in catalog` rendered under the role's select; selection reverts to the active binding. |
| Superseded moment | Moment view | Existing amber notice, unchanged. |
| Api unreachable | every surface | The existing sentence with `API_BASE`, in place; stale content kept and labelled. |

## Interaction Primitives

**Mouse and trackpad.** Click acts; hover reveals nothing that keyboard cannot reach (hover only changes a border and shows a tooltip that is also the item's accessible name). Wheel over the timeline canvas zooms around the pointer (Ctrl/⌘ + wheel or pinch) or pans (plain wheel horizontally); drag pans. Double-click on a timeline item zooms to fit it. No drag-and-drop except the file drop zone in Add-meeting.

**Keyboard, global.** `/` focuses Search, `a` focuses Ask, `n` opens Add-meeting, `g m` `g t` `g e` go to Moments / Threads / Meetings, `Esc` closes the topmost popover or collapses the expanded card. Shortcuts never fire inside a text field.

**Keyboard, timeline.** `Tab` enters the canvas (roving tabindex on the current tier's items); `←` `→` move between items in the tier; `↑` `↓` between bands; `+` `−` zoom ×1.5 around the focused item; `Shift+←` `Shift+→` pan 80% of the window; `Home` fits the corpus span; `Enter` drills (zoom to fit the item, which crosses into the next tier); `Backspace` zooms out one tier; `Space` replays at the evidence tier; `o` opens the moment view.

**Keyboard, speaker naming.** `↑` `↓` select tags; `1` `2` `3` play clips; `Enter` in the name field submits; `u` marks unresolved.

**Banned everywhere:** toasts for anything that is a result (results render in place); infinite scroll (the feed is paged with a `Show 24 more` button); autoplay (a player starts only on Replay, Space, or a clip button); modal dialogs (Add-meeting is a route, not a modal, so Back and deep links work); hover-only affordances; disabled buttons without a sentence saying why.

## Semantic Zoom

The Threads timeline is the one place motion carries meaning, and the one place the data is fetched by what is visible (story 10.3). The canvas maps time to x: `x = (t − windowFrom) / scale`, with `scale` in **milliseconds per pixel**. Every tier reads the same mapping, which is what makes a tier change a reveal rather than a jump.

| Tier | `scale` (ms/px) | Enter at | Leave back at | Fetch | What is drawn |
|---|---|---|---|---|---|
| **bands** | ≥ 7 200 000 (2 h/px) | app open (`Home`) | — | `level=bands` for the window, bucket = the smallest of day / week / month that is ≥ 8px wide | every thread as a `{components.thread-band}`; alpha by density quintile |
| **meetings** | 240 000 – 7 200 000 (4 min/px – 2 h/px) | scale < 2 h/px | scale ≥ 2.5 h/px | `level=meetings` for the focused thread(s) | meetings on the band as marks whose width is their duration, with `title · N mentions`; other threads' bands collapse to 4px strips |
| **moments** | 2 000 – 240 000 (2 s/px – 4 min/px) | scale < 4 min/px | scale ≥ 5 min/px | `level=moments` | moments as ticks at `startMs` with title and speakers-where-known; the meeting's span drawn as a bracket |
| **evidence** | < 2 000 (2 s/px) | scale < 2 s/px | scale ≥ 2.5 s/px | `level=evidence` | each moment becomes a `{components.lod-card}` anchored at its `startMs`: screenshot, transcript excerpt, artifact kind chips, anchor |
| **replay** | (not a scale) | Space / Replay on an evidence card | Esc / another Replay | none — `/media/recordings/{meetingId}` Range | the one inline player at the card |

Hysteresis (the "leave back at" column, 1.25× the entry threshold) means a wheel notch that just crossed a threshold does not flap back. Zoom input steps are ×1.25 per wheel notch and ×1.5 per key press, always about a focus point (pointer, or the focused item's `x`), so the thing you were looking at stays under your eye.

**Fetch discipline.** The window fetched is the visible window padded 50% each side at the current tier; requests are debounced 120 ms and cached by `(threadId, level, bucketedFrom, bucketedTo)`. A finer tier is never drawn from a coarser tier's data — the outgoing tier stays until the fetch resolves, and a failure keeps it drawn with a refusal box under the canvas. Nothing is interpolated: a bucket with no data is drawn at 0.08 alpha, a meeting without moments in the window draws its bracket and `no moments in view`.

**Transitions.** Zoom steps animate `scale` over **120 ms ease-out**; a tier change cross-fades **160 ms** — the outgoing tier fades while the incoming tier fades in at the same `x` positions. The list column, the axis row, and the canvas height never reflow across a threshold; the canvas grows only when an evidence card needs a second row, and it grows below the fold, never above the pointer. **No layout jump** is a test: an item focused before the threshold has the same `x` after it.

**Reduced motion** (`prefers-reduced-motion: reduce`): zoom steps apply instantly, tier changes swap instantly, the running-pulse and the progress line stop animating, and pan has no inertia. Everything remains reachable; only easing is removed.

**Live announcement.** The canvas has a polite live region that announces a tier change once: `Meetings tier — retrieval split, 7 meetings between 2026-05-04 and 2026-07-20.` and, at the evidence tier, the focused card's anchor. Continuous zoom does not announce.

**Multi-thread.** At the bands tier every thread is visible. Entering a thread focuses it; up to three threads can be **pinned** (`p`) to compare — pinned threads keep full-height bands at the meetings tier, others collapse. Pins live in the URL.

## Accessibility Floor

Behavioral. Contrast lives in `DESIGN.md` · Colors · Contrast (97 measured pairs; AA minimum, 41 AAA). Targets WCAG 2.2 AA on a desktop browser with keyboard and screen reader.

- Every interactive element is a real `button`, `a`, `input`, or `[role]` element with an accessible name that includes its data: `Replay recording at 12:40`, `Open on YouTube at 12:40`, `Play clip 2 of SPEAKER_03 at 41:07`, `retrieval split, 2026-06-08 to 2026-06-14, 14 mentions`.
- **Focus order per screen** (DOM order equals reading order; nothing is reordered with CSS `order` except the meeting view's existing rail, which already puts the rail first in DOM for screen readers):
  - Chrome: brand → nav → Search → Ask (textarea → model select → Ask button) → Add meeting → health dot.
  - Moments: filters (corpus → thread → kind → Clear) → cards in rank order; inside a card: title → Replay → Open moment → Open on YouTube → (expanded) player controls; kind and thread chips after the actions.
  - Threads: list (search → sort → thread rows, each with Rename/Merge after the name) → canvas (roving) → evidence card actions.
  - Add-meeting: tabs → fields in visual order → Submit → stepper (bars are `aria-hidden`; the words are read) → log tail (region, `aria-live="off"`) → meeting card → Open / Name speakers.
  - Speaker naming: rerun status (if any) → speaker rows → clips 1-3 → name field → Unresolved → Save → tag-filtered transcript (region).
  - Settings: as today, with the model select first inside each LLM role section.
- **Live regions.** Ingestion and acquisition progress announce politely, once per stage transition (`transcribe running`, `posted — job 8f3c…`), through one region per stepper or card; failures announce assertively with the refusal's rule name. The chat answer region keeps its existing `aria-live="polite" aria-busy` behavior; the log tail is never announced.
- **Popovers** (model select, status, band tooltip) trap nothing; `Esc` closes; focus returns to the trigger.
- **Timeline** is DOM, focusable, named, and operable by keyboard as listed; zoom level and window are exposed as the canvas's `aria-description` (`bands tier, 2026-03-01 to 2026-08-29`). Color is never the only carrier of thread identity (name), kind (glyph + name), or state (texture + word).
- **Motion** honors `prefers-reduced-motion`; no content auto-advances; no player autoplays.
- **Text** scales: the layout survives 150% browser zoom at 1280px by wrapping cards to two columns and the timeline to horizontal scroll.

## Responsive & Platform

Desktop only. One breakpoint inside the supported range: at 1280–1439px the Moments grid is two columns and the Threads list column narrows to 240px; at ≥ 1440px three columns and 280px. Below 1280px is unsupported and only promised to scroll. Chrome on macOS is the recording target; Safari and Firefox are expected to work because nothing beyond standard DOM, `<video>` with Range, and CSS is used. No print styles. No offline mode: every screen already states `Cannot reach the api at …` in place and keeps stale content labelled.

## Inspiration & Anti-patterns

- **Lifted from Google Earth:** the owner's own reference for Threads — continuous zoom, detail revealed per level, nothing invented at any level. Applied as the tier table above; the "no layout jump" rule is what makes it feel like one surface.
- **Lifted from the competitor meeting view** (`spec-ui-reimagine/reference-ui.md`): counts in headers, timestamps as connective tissue, honest absence in place. Kept verbatim as the base idiom.
- **Lifted from the existing screens:** the single-open-player key, the `problemType()` → sentence mapping, `affordanceOf()`'s three-state replay decision, `StageProgress`'s texture-per-state — all reused, not redesigned.
- **Rejected — a "risk" or "question" kind chip.** FR40 names them as signals; no such kind exists in the api. Nothing is drawn for them until a story creates the kind.
- **Rejected — topic chips as facts.** Threads are navigation, labelled machine-derived, never presented as a conclusion and never a chat fact (FR41).
- **Rejected — auto-applied speaker suggestions, silent model fallback, decorative color, skeleton cards, toasts, modals.** Each is an invention or a hiding place.

## Data Traceability

Every element on every screen, the field that backs it, and whether it exists today (`existing`, from `web/src/client/types.gen.ts` at e5510c7) or is created by a story in this plan (`story N.N`, from that story's acceptance criteria in `epics.md`). Rows marked `[ASSUMPTION]` name a field the story's AC implies but does not enumerate; each is also a row in `findings-for-epics.md`. Nothing decorative survives this table.

### Chrome

| Element | Backing field / operation | Source |
|---|---|---|
| Primary nav: Participants, Status, Settings | routes `/participants`, `/status`, `/settings` | existing |
| Primary nav: Moments (default), Threads, Meetings | routes `/`, `/threads`, `/meetings` | story 10.7 |
| Search box and hits | `GET /search` (`q`, `limit`, `offset`, `meetingId`, `corpus`) → `SearchHit` | existing |
| Ask box, streamed answer, citations | `POST /chat` (`chat.token`, `chat.citations` → `CitationModel`, `chat.done` → `RouteModel`) | existing |
| Model select in the ask box | `GET /settings/models` → roles[] with `catalog[]{binding,label,provider}`, `default`, active selection; `PUT /settings/roles/chat` | story 8.2 |
| Health per model option | `GET /status` → `llmRoles[]{role,model,provider,keyState,state,detail,remediation}` (existing) plus key validity per configured provider | existing · story 8.2 |
| Add meeting button | route `/add` | story 6.5 |
| Health dot and word | `GET /status` → `overall`, `api`, `stores[]`, `llmRoles[]`, `worker` | existing |

### Moments (`/`)

| Element | Backing field / operation | Source |
|---|---|---|
| Ranked card order | `GET /moments/feed` items in deterministic score order | story 10.4 |
| Filters corpus · thread · kind (· meeting) | feed query `corpus | thread | meeting | kind`; thread options from `GET /threads` | story 10.4 · story 10.3 |
| Header count `Moments 24` | count of items returned (`[ASSUMPTION]` a `total` for `N of M`) | story 10.4 |
| Reason line | item `reasons[]` as structured data, each with a `kind` and a `label` rendered verbatim (`[ASSUMPTION]` shape: `{kind, label, ref?, at?}`) | story 10.4 |
| Kind chips in reasons | reason `kind` ∈ `MomentArtifact.kind` | story 10.4 · existing enum |
| Thread chips | item `threads[]{threadId,name}` (thread membership is a ranking signal) `[ASSUMPTION]` | story 10.4 |
| Screenshot | item `screenshotPath` → `GET /media/{path}` (`[ASSUMPTION]` the feed item mirrors `MomentDetail.screenshotPath`) | story 10.4 · existing media route |
| Meeting title, date, offsets, corpus | item `meetingId`, `meetingTitle`, `startedAt`, `startedAtPrecision`, `startMs`, `endMs`, `corpus` (`[ASSUMPTION]` mirrors `SearchHit`) | story 10.4 |
| Excerpt | item `preview` (`[ASSUMPTION]` mirrors `MomentListItem.preview`) | story 10.4 |
| Replay in place | `GET /media/recordings/{meetingId}` (Range) with `hasRecording`, `startMs` | existing |
| Open moment | route `/moments/:momentId` | existing |
| Open on YouTube at H:MM:SS | item `sourceDeepLink` (YouTube host) + `startMs` → `&t=<s>s` | existing field · story 6.6 |
| Empty / filter-empty sentences | feed returns zero items | story 10.4 |
| Show 24 more | feed `limit`/`offset` (`[ASSUMPTION]` paging params) | story 10.4 |

### Meetings (`/meetings`)

| Element | Backing field / operation | Source |
|---|---|---|
| Corpus counts | `GET /corpus/stats` → `CorpusStats` | existing |
| Meeting cards, stage bars, filters, sort | `GET /meetings` → `MeetingListItem`; `GET /jobs/events` → `JobEvent` | existing |
| api /health panel | `GET /health` | existing |

### Threads (`/threads`)

| Element | Backing field / operation | Source |
|---|---|---|
| Thread list: name, mention count, last mention, meetings | `GET /threads` (`[ASSUMPTION]` item fields `threadId, name, mentionCount, meetingCount, firstMentionAt, lastMentionAt`) | story 10.3 |
| Sort by activity / recency, search by name | client-side over the list | story 10.6 |
| `machine-derived` label | topics are machine-derived navigation (FR41) | story 10.1 |
| Rename · Merge into… · Split | api-owned thread curation (alias rows) | story 10.2 (api) — no UI story owns these controls; recorded in `findings-for-epics.md` |
| Bands with density per bucket | `GET /threads/{id}/timeline?from=&to=&level=bands` → buckets with mention density | story 10.3 |
| Meetings on a band with counts | `level=meetings` → meetings with counts | story 10.3 |
| Moments: title, offset, speakers-where-known, screenshot | `level=moments` → `title`, `offset`, `speakers`, `screenshotId` | story 10.3 |
| Evidence: excerpt, artifact anchors | `level=evidence` → transcript excerpt, artifact anchors, each carrying the moment id | story 10.3 |
| Replay on an evidence card | moment id → `meetingId`, `startMs`, `hasRecording` (`[ASSUMPTION]` carried on the evidence item, or read via `GET /moments/{id}`) → `GET /media/recordings/{meetingId}` | story 10.3 · existing |
| Open moment | route `/moments/:momentId` | existing |
| Thread hue | client-side stable hash of `threadId` | this design |

### Add-meeting (`/add`)

| Element | Backing field / operation | Source |
|---|---|---|
| Source tabs | client | story 6.5 |
| YouTube URL shape check | client (host `youtube.com` / `youtu.be`, video id present) | story 6.5 |
| Submit a URL | `POST /acquisitions` `{url}` → 202 `{acquisitionId}`; 409 conflict for a running acquisition on the same source id; 422 ProblemDetails | story 6.4 |
| Tool refusals: not a video, private/removed, no video stream, tools missing, duration over cap | `GET /acquisitions/{id}` `failed` with the log tail (`[ASSUMPTION]` a named `refusal{rule,detail,remediation}` on the status, so the box need not parse the log) | story 6.2 (rules) · story 6.4 (status) |
| Already ingested (`exists`) | `find_existing_drop(youtube:<id>)` before download → reported `exists` (`[ASSUMPTION]` how it maps onto `queued | running | posted | failed`) | story 6.2 · story 6.4 |
| File rows: name, size, classification | client (`File` API: extension + `Name: text` cue sniff for the Zoom dialect) | story 6.5 |
| Dialect select `zoom | teams-vtt | plain` | the `--transcript-dialect` values | story 6.3 |
| Title, date, corpus `real` for uploads | drop `metadata.json` requirements (`[ASSUMPTION]` `POST /acquisitions` upload session accepts `title`, `startedAt`, `transcriptDialect`) | story 6.4 · AD-1 |
| Upload streaming to staging | upload session → staging under the drops root | story 6.4 |
| Stepper launch / running / posted | `GET /acquisitions/{id}` → `queued | running | posted | failed`, log tail, `jobId` when posted | story 6.4 |
| Ingesting: the meeting card | `GET /meetings` row by `jobId`; `GET /jobs/events`; `viewable` gate | existing |
| Name speakers link | `transcribe` stage `done` in `stages[]` | existing · story 7.4 |
| Provenance line on the finished card (`youtube:<videoId> · yt-dlp 2026.07.04`) | drop provenance (`[ASSUMPTION]` surfaced on `MeetingListItem` or the drilldown — not served today) | story 6.2 writes it; no story serves it — recorded in `findings-for-epics.md` |

### YouTube deep link (6.6)

| Element | Backing field / operation | Source |
|---|---|---|
| `Open on YouTube at H:MM:SS` on moment view, drill-down, chat citations, Moments cards | `sourceDeepLink` on `MomentDetail`, `MomentListItem`, `DrilldownScreenshot`/`MeetingDrilldownResponse`, `CitationModel`, `SearchHit` + `startMs` | existing fields · story 6.6 (shown beside replay when both exist) |

### Speaker naming (`/meetings/:id/speakers`)

| Element | Backing field / operation | Source |
|---|---|---|
| Speaker rows: tag, talk time, segment count | `GET /meetings/{id}/speakers` → per tag `talkTime`, `segmentCount`, three sample offsets | story 7.2 |
| Talk share % | `talkTime / Σ talkTime`, client-side | story 7.2 |
| Three clips per tag | sample offsets → `GET /media/recordings/{meetingId}` (Range) via the existing player; 8-second stop is a 7.4 web change | story 7.2 · existing · story 7.4 |
| Tag-filtered transcript | `GET /meetings/{id}/drilldown` → `segments[].speakerLabel` (carries the tag), `speakerResolution`, `participantId`; filtered client-side | existing · story 7.2 |
| Existing-participant suggestions | `GET /participants` → `displayName` | existing |
| Assign: participant · new name · unresolved | `PUT /meetings/{id}/speakers/{tag}` with a participant id, a display name, or `unresolved` | story 7.3 |
| Rerun progress `align → moments → extract` | `GET /jobs/events` for the meeting's job | existing · story 7.3 |
| Rerun landed: names in the transcript | drilldown `segments[].speakerLabel` resolved, `speakerResolution` | existing · story 7.3 |
| Resolved-by-source rows (Zoom) | speakers endpoint reports the tag already resolved (`[ASSUMPTION]` `participantId`/`displayName` on the row) | story 7.5 |
| No-tags sentence | speakers list empty | story 7.2 |

### Model selection (Settings, ask box)

| Element | Backing field / operation | Source |
|---|---|---|
| Per-role catalog with labels and providers | `GET /settings/models` | story 8.2 (catalog declared by story 8.1) |
| Active binding marked | active selection in the same response | story 8.2 |
| Provider health per option | `GET /status` → `llmRoles[].keyState`, key validity per configured provider, active binding per role | existing · story 8.2 |
| Save | `PUT /settings/roles/{role}`; 422 for a binding outside the catalog | story 8.2 |
| Failing binding named at the ask | chat stream error as a named problem (`[ASSUMPTION]` a stable `type`, e.g. `urn:meetingminer:problem:binding-failed`) | story 8.2 |
| `Effective binding recorded in eval snapshots` note | eval snapshot records the effective binding | story 8.2 (not a UI element; a sentence on Settings) |

## Requirement Map

| Rule | Where it is honored |
|---|---|
| UX-DR12 — Open on YouTube at this moment beside replay, replay primary | Component Patterns · Moment card; Traceability · YouTube deep link; Flow 5 |
| UX-DR13 — one Add-meeting flow, source tabs, validation before any write, progress through ingestion, failures naming the rule | IA · Add-meeting; Component Patterns · Source tab, Acquisition stepper, Refusal box; State Patterns · Add-meeting rows; Flows 1 and 2 |
| UX-DR14 — talk share, three clips, tag-filtered transcript, inline naming, suggestions never auto-applied, unresolved first-class | Component Patterns · Speaker row, Clip button, Name field; State Patterns · Speaker naming rows; Flow 3 |
| UX-DR15 — model selection in the ask box and Settings, provider health beside each choice | Component Patterns · Model select, Ask box; State Patterns · Model select rows; Flow 4 |
| UX-DR16 — Moments first, Threads second, search/ask/Add-meeting persistent | IA table and Chrome; Flow 5 |
| UX-DR17 — a card states its reason, shows its screenshot, replays in place, nothing decorative | Component Patterns · Moment card, Reason line; Traceability · Moments; `DESIGN.md` · Brand & Style |
| UX-DR18 — Google-Earth zoom, level-of-detail thresholds, smooth transitions, detail per level, nothing invented | Semantic Zoom (tier table, hysteresis, fetch discipline, transitions, reduced motion); Flow 6 |

## Key Flows

All six are sessions of Tim, the owner — an architect reviewing recordings alone at a 1440 × 900 Chrome window.

### Flow 1 — Add a YouTube meeting and watch it become evidence (story 6.5)

1. Tim presses `n`. `/add` opens under the chrome; the YouTube tab is selected and the URL field is focused.
2. He pastes `https://www.youtube.com/watch?v=dQw4…`. The shape check passes; Submit enables. Nothing has been sent.
3. Enter. `POST /acquisitions` answers 202. The form locks; the stepper appears: **launch** solid, **running** pulsing amber, the log tail scrolling `yt-dlp: downloading 1080p mp4 … captions: manual en`.
4. The stepper reaches **posted** — `posted — job 8f3c…` — and the meeting card renders under it, its eight stage bars dashed.
5. **Climax:** without a reload, the bars fill left to right from `/jobs/events` — `probe`, `frames`, `ocr` — the poster screenshot appears on the card, and `Open` enables the moment `viewable` flips true. The same card, the same page, from URL to evidence.
6. He clicks `Name speakers` (transcribe is done and the captions carried no speakers) and lands in Flow 3.

Failure: the api is down at step 3 → `Cannot reach the api at http://localhost:8000: fetch failed.` under Submit, form unlocked, nothing written.

### Flow 2 — A refusal that names its rule (story 6.5, rules from 6.2)

1. Tim pastes a URL to a four-hour conference stream and presses Enter.
2. 202; **launch**, **running** — then the stepper stops at **failed**.
3. **Climax:** the refusal box under the stepper reads `youtube-drop: duration over cap — 4h 02m exceeds the configured 180 minutes. → Raise acquisition.youtube.maxDurationMinutes in config.yaml and restart the worker, or choose a shorter video.` The log tail above it shows the tool's own last lines. Nothing was downloaded, nothing minted, no meeting row exists.
4. He edits the URL; the refusal box clears because its cause changed; Submit re-enables.

Variant: the same video is already in the corpus → the stepper ends at **posted** with `Already in the corpus — nothing downloaded.` and the existing card.

### Flow 3 — Name the voices (story 7.4)

1. From the meeting card, `Name speakers` opens `/meetings/8f3c…/speakers`. Header: `Speakers 4 · 58m 12s of speech`. Rows sorted by talk share: `SPEAKER_00 41% · 23m 51s · 112 segments`, `SPEAKER_03 27%`, …
2. `SPEAKER_00` is selected; three clip buttons `▶ 4:12 · ▶ 19:40 · ▶ 41:07`; the right column shows only that tag's segments.
3. He presses `1`; the clip plays from 4:12 for eight seconds. He knows the voice. He types `pri` in the name field; the combobox suggests `Priya Natarajan` from `/participants` — highlighted, not filled.
4. Enter picks the suggestion; Save. `PUT /meetings/8f3c…/speakers/SPEAKER_00` returns 200; the row shows `Priya Natarajan` and the state word `rerun queued`; three stage bars — `align`, `moments`, `extract` — appear in the header and start filling.
5. `SPEAKER_03` next: two clips in, he is not sure. He presses `u`: **Unresolved — keep the tag.** Saved as a choice, not skipped.
6. **Climax:** `extract` goes done; the panel states `Rerun landed 14:02:11 — transcript, graph, and extractions now name SPEAKER_00 as Priya Natarajan. Moment ids and citations unchanged.` The transcript column re-reads and every one of her 112 segments carries her name. He opens a moment he had cited in chat that morning; it resolves at the same id.

Failure: the PUT is refused (participant merged away) → refusal box under the name field with the api's `title: detail`; the row stays a tag.

### Flow 4 — Pick the model, then ask (story 8.3)

1. Tim clicks the ask box's model select: `chat · gpt-5.2 · openai ● invalid → set OPENAI_API_KEY in .env, restart the api`.
2. The popover lists the catalog: under **anthropic**, `Claude Sonnet 5 · anthropic/claude-sonnet-5 ● ok`; under **openai**, the current one, muted, still selectable.
3. He chooses Sonnet. `PUT /settings/roles/chat` → 200; the trigger reads `chat · claude-sonnet-5 · anthropic ● ok`.
4. He types `what did we decide about the purchase order` and presses Ask. Tokens stream; citations land; `answered from 3 moments`.
5. **Climax:** he clicks the first citation, `12:40`, and the moment view opens with Replay and — because the meeting came from YouTube — `Open on YouTube at 12:40 ↗` beside it. The model he chose answered; the evidence is one click away.

Failure: he had left the openai binding selected → the answer region shows the refusal box `chat: binding failed — openai/gpt-5.2: 401 invalid api key → set OPENAI_API_KEY in .env, restart the api, or pick another binding.` No other model answered in its place.

### Flow 5 — Morning at the front door (story 10.5)

1. Tim opens the app. `/` is Moments: `Moments 24 · ranked by decision, due date, recency, thread`, filters at `corpus real`.
2. The first card: a slide screenshot with `slide · 12:40`, `Retrieval bake-off review · 2026-08-14 · 12:40–14:05 · real`, the reason line `◆ decision at 12:40 · ☐ 2 action items · due 2026-09-04 · #retrieval split`, the excerpt “BM25 stays first-class; hybrid only on paraphrase.”
3. He presses Replay. The card spans the grid; the player opens under the screenshot at 12:40. He listens to the decision being made.
4. **Climax:** he does not navigate anywhere. The card told him *why* it is first — the api's own reasons, verbatim — showed him the slide, and replayed the sentence, on the same surface that greeted him. He presses `Esc`; the grid closes back with no reflow.
5. He clicks `#retrieval split` to see how that decision came about — Flow 6.

Failure: the feed is unreachable → the sentence in place, `Retry`, and if a previous feed was on screen, the stale cards labelled stale.

### Flow 6 — Follow a thread from months to a sentence (story 10.6)

1. `/threads/…` opens focused on **retrieval split** at the meetings tier around 2026-08-14; the other ten bands are 4px strips above and below, the list column shows `Threads 11`, sorted by activity.
2. He presses `Home`. The canvas zooms out (120 ms) to the corpus span, bands tier: eleven bands from 2026-03 to 2026-08, retrieval split dense in May and August, quiet in June.
3. He hovers the May cluster: `14 mentions · 2026-05-11 → 2026-05-17`. Ctrl+wheel: the scale crosses 2 h/px and the meetings tier fades in at the same x — four meeting marks in May, `Embedding bake-off · 9 mentions` the widest.
4. Double-click on it: zoom to fit, moments tier — nine ticks with titles and `Priya Natarajan`, `Tim Goeke` under the ones that were named in Flow 3.
5. `Enter` on `Why BM25 wins on reused wording`: evidence tier — the LOD card with its screenshot, the excerpt, `◆ decision` and `§ adr` chips, the anchor `1:04:09 · Embedding bake-off`.
6. **Climax:** `Space`. The recording plays at 1:04:09, inside the timeline, three tiers below the band he started from, and the sentence that split retrieval is the one on screen. He never changed screens; every level was fetched for what it drew; nothing was shown that a moment did not back.

Failure: the evidence fetch fails → the moments tier stays drawn, a refusal box under the canvas names the problem, and `Enter` does nothing until Retry succeeds.
