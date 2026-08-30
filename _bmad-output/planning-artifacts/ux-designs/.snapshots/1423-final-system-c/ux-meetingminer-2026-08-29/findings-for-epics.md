# Findings for the epics — from story 6.1 (UX design spec), 2026-08-29

Gaps and contradictions the design exposed while mapping every element to a field. Each is written against the story that should resolve it, using the ids after Sprint Change Proposal Addendum 3 (2026-08-29 re-slicing). The owner decides whether the epic changes; the design already states which way it assumed (tagged `[ASSUMPTION]` in the spines). Nothing here was edited into `epics.md`.

## Blocking for the surface named (a builder cannot finish without a decision)

**F-1 · Story 10.5 — the dark idiom is not applied today.** `web/src/index.css` declares the `.dark` tokens, but `index.html` carries no class and `main.tsx` adds none: the app renders shadcn light, and every `dark:` variant in the codebase is inert. *Resolved by Addendum 3:* story 10.5's AC now says "the shell applies the dark theme class the story 6.1 design specifies". Kept for the record: until 10.5 lands, no token in `DESIGN.md` takes effect on screen.

**F-2 · Story 10.5 — the shell is capped at `max-w-5xl` (1024px).** The Threads timeline and the three-column Moments grid need the wide shell `DESIGN.md · Layout & Spacing` specifies (1600px). Resolution assumed: the shell width becomes per-route (wide for `/`, `/threads`, `/meetings`; 1024px for the existing child screens; 720px for `/add`), pinned by the same test that pins child-screen placement (B-13, absorbed into 10.5).

**F-3 · Story 10.4 — the feed item's fields are not enumerated.** The AC names only "reasons as structured data". The Moments card needs, per item: `momentId`, `meetingId`, `meetingTitle`, `startedAt`, `startedAtPrecision`, `startMs`, `endMs`, `corpus`, `hasRecording`, `sourceDeepLink`, `screenshotPath` (or id), `preview`, `threads[]{threadId,name}`, and `reasons[]`. Proposed reason shape, so the card can pick a chip by kind and render the label verbatim: `{kind: 'decision'|'adr'|'action-item'|…|'due'|'recency'|'published'|'thread', label: string, ref?: {artifactId?|threadId?}, at?: number}`. Also a `total` and `limit/offset` for `Moments 6 of 24` and `Show 24 more`.

**F-4 · FR40 / Story 10.4 — "risks and open questions" have no kind.** The ranking signals name them, but `MomentArtifact.kind` is `action-item | adr | decision | story | requirement | bug-fix | change-request`. Either a story adds `risk` and `question` to extraction (new kinds, new prompts, new parser rows), or FR40's signal list drops them. The design colors only the seven existing kinds and draws no risk or question chip.

**F-5 · Story 10.3 — `GET /threads` list fields are not enumerated.** The Threads list needs `threadId`, `name`, `mentionCount`, `meetingCount`, `firstMentionAt`, `lastMentionAt` to sort by activity and recency and to place bands. The `moments` and `evidence` tiers need `meetingId`, `startMs`, `hasRecording` on each item (or the client reads `GET /moments/{id}` per card) to replay in place (story 10.6a). Story 10.2a's `Split…` needs the thread's topics by meeting — from `GET /threads/{id}` or the `meetings` level.

**F-6 · Story 6.4 / 6.5 — the pre-submit URL probe has no endpoint.** After Addendum 3, story 6.5's AC *requires* "a URL probe naming the refusing rule before submit", but story 6.4 creates only `POST /acquisitions` and `GET /acquisitions/{id}`, and the refusals (private/removed, no video stream, duration over cap, tools missing) live in the 6.2 tool, which runs after launch. 6.4 needs a probe — proposed `POST /acquisitions/probe {url}` → `{title, durationMs, captions, sourceId}` or a ProblemDetails refusal, a dry run of the 6.2 checks that writes nothing. The design draws both the pre-submit probe states (`Probing…`, probe answered, probe refused) and the post-launch refusal as the fallback until the endpoint exists.

**F-7 · Story 6.4 — a failed acquisition should carry a named refusal.** The AC gives `failed` a log tail. The refusal box needs the rule name, detail, and remediation as fields — `refusal: {rule, detail, remediation}` on the status — so the web does not parse a log. The rule names come from story 6.2's refusals and, for uploads, from story 6.4a's (`undeclared dialect`, `unsupported file type`, `size over cap`).

**F-8 · Story 6.2 / 6.4 — how `exists` surfaces.** A repeat run reports `exists` without downloading (6.2), but the 6.4 status enum is `queued | running | posted | failed`. The design assumes `posted` with the existing meeting's job id and the sentence `Already in the corpus — nothing downloaded.`; a distinct `exists` status would also work. Decide one.

**F-9 · Story 6.4a — the upload session's remaining fields.** Addendum 3 made the dialect a declared field of the session (good). Minting a local-files drop also needs `title`, `startedAt`, and `corpus` (fixed `real`); the 6.4a AC does not say how the session receives them. The design draws title and date and assumes the session accepts them.

## Non-blocking (the design routes around them; recorded so they are decisions, not omissions)

**F-10 · Story 10.2a — thread curation is now a UI story; `Split…` needs data.** *Resolved by Addendum 3* for rename and merge (the design puts them on the thread's list row and the focused band's header, mirroring Participants). `Split…` is designed as a panel listing the thread's topics by meeting with checkboxes; the data it lists is F-5's last sentence.

**F-11 · Story 6.2 — provenance is written but not served.** `channel`, `duration`, `yt-dlp` version, and `format` land in the drop's `metadata.json`; no endpoint serves them, so the finished meeting card cannot show `youtube:<id> · yt-dlp 2026.07.04`. The design omits that line; add the fields to the drilldown or the meeting row if wanted.

**F-12 · Story 7.2 — the speakers row for a resolved-by-source label.** Addendum 3 merged 7.5's "resolved-label shape on the wire" into 7.2. The design shows `Tim Goeke · from transcript` on such a row; the 7.2 response needs `participantId` and a display name per tag for that, and story 7.4 owns `Correct`.

**F-13 · Story 7.4 — clips need a stop.** Three clips per tag play through the existing `ReplayPlayer` (`meetingId` + `startMs`); an eight-second clip needs an optional `endMs` prop. `ReplayPlayer` is shared with search and the moment view, so the prop must be optional and default to today's behavior. Inside 7.4's file boundary; noted so the builder does not treat it as scope creep.

**F-14 · Story 8.2 / 8.2a — name the failing-binding problem and the provider-health shape.** The web maps RFC 9457 `type` slugs to sentences per feature; a failing binding (8.2, "a named error at the point of use") needs a stable type (proposed `urn:meetingminer:problem:binding-failed`) carrying provider, binding, and the upstream status in `detail`. Story 8.2a's "key validity per configured provider" needs a shape on `/status` (proposed `providers[]{provider, keyState, detail, remediation}`) beside the existing `llmRoles[]`.

**F-15 · Story 6.6 — `affordanceOf()` hides the deep link when a recording exists.** Today `deepLink` is only offered when `hasRecording` is false. UX-DR12 wants the YouTube link *beside* replay; 6.6 changes the decision to return both, and labels the link `Open on YouTube at H:MM:SS` when the host is `youtube.com` / `youtu.be` (the existing Teams label `Open in Stream` stays for other hosts).

**F-16 · Story 10.5 — the `api /health` panel leaves the front door.** The design keeps it on `/meetings` only; `/status` and the chrome dot answer the same question. Confirm, since the current home test may pin it.

**F-17 · Story 10.5 / 10.6 — keyboard shortcuts.** `EXPERIENCE.md · Interaction Primitives` adds `/`, `a`, `n`, `g m`, `g t`, `g e` and the timeline keys. No story names shortcuts; the global ones belong to 10.5 (chrome) and the timeline ones to 10.6/10.6a.

**F-18 · Owner — the design workspace is gitignored.** `_bmad-output/` is ignored by commit cf0214b, so this spec is not versioned; builders cite a path and a date. Un-ignoring `_bmad-output/planning-artifacts/ux-designs/` (or copying the spines into `docs/design/` by a story) is the owner's call.

**F-19 · Story 6.2a / 6.5 — playlist URLs in the UI.** Story 6.2a acquires playlists from the command line; no UI story accepts a playlist URL. The design's shape check refuses one on the URL tab with `Playlist URLs are not accepted on this tab — paste one video's watch link.` If the owner wants playlists in Add-meeting, a story must add it (probe + one acquisition per video).

**F-20 · Story 10.2b — no UI change.** Thread questions route through the existing ask box and cite moments only; the design adds nothing for it and notes it here so the omission is deliberate.

## Added after the reviewer gate (accessibility and editorial lenses, 2026-08-29)

**F-21 · Owner — WCAG 2.2 AA is claimed with two stated deviations.** The design is desktop-only at ≥ 1280 × 800 by owner decision; it meets 1.4.4 Resize Text to 150% at 1280px but not 200%, and does not meet 1.4.10 Reflow at 320 CSS px (no narrow layout for the chrome, Moments grid, Add-meeting, Speaker naming). `EXPERIENCE.md · Accessibility Floor` states both. Keep the deviation, or fund one narrow layout (≤ 900 CSS px: chrome on two rows, one Moments column, stacked Speaker naming) as a story.

**F-22 · Story 10.5 / 10.6a / 7.4 — captions on the inline player and `alt` on screenshots.** The product owns a transcript for every meeting, so `ReplayPlayer` can attach a WebVTT captions track generated client-side from `/drilldown` `segments[]` (WCAG 1.2.2, Level A); nothing serves it today. The design specifies it (off by default, remembered per browser) and the screenshot `alt` rule `<viewType> at <offset>, <meetingTitle>`; the feed item (story 10.4, F-3) needs `viewType` for the latter. `ReplayPlayer` is shared, so the track prop is optional and lands with whichever of 10.5, 10.6a, or 7.4 touches the player first.

**F-23 · Story 10.5 — the `Button` focus ring.** `components/ui/button.tsx` draws `focus-visible:ring-3 ring-ring/50`, which composites to 2.60:1 on the dark base. `DESIGN.md · Components · Focus ring` replaces it with a two-tone ring (2px `{colors.ring}` at 100% outside a 1px background gap); the change is one class list in `button.tsx` plus the `--ring` value in `index.css`, and belongs to 10.5 with the dark class.

**F-24 · Story 10.5 — control borders.** shadcn's `border` at white 10% identifies inputs and outline buttons at 1.25:1; `DESIGN.md` adds `control-border` (white 34%) for inputs, select triggers, and outline buttons. One token in `index.css` and the `outline` variant in `button.tsx`; 10.5 with the rest of the shell.

**F-25 · Owner — nine spine terms have no `docs/glossary.md` entry.** *thread, topic, speaker tag, alias, rerun, binding, catalog, role, provider* are defined in `EXPERIENCE.md · Voice and Tone` because the glossary lacks them. Adding them to `docs/glossary.md` in the spine's wording (a `docs/` edit, outside this story's boundary) keeps one vocabulary; until then the spine's definitions govern the UI copy.
