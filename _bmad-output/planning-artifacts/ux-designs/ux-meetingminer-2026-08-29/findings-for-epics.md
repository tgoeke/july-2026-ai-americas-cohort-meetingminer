# Findings for the epics — from story 6.1 (UX design spec), 2026-08-29

Gaps and contradictions the design exposed while mapping every element to a field. Each is written against the story that owns it, using the ids after Sprint Change Proposal Addendum 3 (2026-08-29 re-slicing). The 2026-08-29 Story 6.1 review resolved the contract findings by amending those source stories; the final spines contain no inferred field contract. This file preserves the decisions and implementation handoffs.

## Blocking for the surface named (a builder cannot finish without a decision)

**F-1 · Story 10.5 — the dark idiom is not applied today.** `web/src/index.css` declares the `.dark` tokens, but `index.html` carries no class and `main.tsx` adds none: the app renders shadcn light, and every `dark:` variant in the codebase is inert. *Resolved by Addendum 3:* story 10.5's AC now says "the shell applies the dark theme class the story 6.1 design specifies". Kept for the record: until 10.5 lands, no token in `DESIGN.md` takes effect on screen.

**F-2 · Story 10.5 — the shell is capped at `max-w-5xl` (1024px). Resolved by Addendum 3 and the owner review.** Story 10.5 owns the per-route shell widths from `DESIGN.md · Layout & Spacing`: wide for `/`, `/threads`, and `/meetings`; 1024px for existing child screens; 720px for `/add`. The same test that pins child-screen placement (B-13, absorbed into 10.5) pins the route widths.

**F-3 · Story 10.4 — feed fields. Resolved by owner review.** The AC now owns `{items,total,limit,offset}` and each card's `momentId`, `meetingId`, `meetingTitle`, `startedAt`, `startedAtPrecision`, `startMs`, `endMs`, `corpus`, `hasRecording`, `sourceDeepLink`, opaque `screenshotId`, `viewType`, `preview`, `threads[]{threadId,name,colorOrdinal}`, and non-empty `reasons[]{kind,label,ref?,at?}`. Empty or unknown reasons drop and log the item; screenshot media is ID-addressed under AD-17.

**F-4 · FR40 / Story 10.4 — risk and question signals. Resolved by owner review.** Story 10.4 now owns strict-parser, moment-anchored persisted ranking-signal rows of kind `risk | question`, produced through `Llm(extraction)` and replaced on rerun. They are not publishable `MomentArtifact.kind` values and render as literal muted reason text, so the approved seven-kind palette does not invent two artifact colors.

**F-5 · Story 10.3 — thread and timeline fields. Resolved by owner review.** `GET /threads` now owns `threadId`, `name`, counts, first/last mention, and immutable `colorOrdinal`; timeline items own replay fields, opaque media ids, topic membership for Split, and canonical RFC 3339 UTC `occurredAt` plus precision. The client never reconstructs cross-meeting time or color identity.

**F-6 · Story 6.4 / 6.5 — pre-submit URL probe. Resolved by owner review.** Story 6.4 now creates `POST /acquisitions/probe {url}` → `{title,durationMs,captions:{kind,language},sourceId}` or refusal Problem Details. It performs the 6.2 checks without download, mint, process launch, or acquisition-state write; Story 6.5 gates Submit on its current response.

**F-7 · Story 6.4 — named failed acquisition. Resolved by owner review.** `failed` status now owns `refusal:{rule,detail,remediation}` from the YouTube tool or upload session; the log tail remains diagnostic and is never parsed for UI copy.

**F-8 · Story 6.2 / 6.4 — `exists` outcome. Resolved by owner review.** The status remains `posted` and carries `result: exists` plus the existing job and meeting ids; the UI states `Already in the corpus — nothing downloaded.`

**F-9 · Story 6.4a — upload metadata. Resolved by owner review.** The multipart session now requires `title`, RFC 3339 `startedAt`, `corpus: real`, and explicit `transcriptDialect` whenever VTT is present.

## Non-blocking (the design routes around them; recorded so they are decisions, not omissions)

**F-10 · Story 10.2a — thread curation is now a UI story; `Split…` needs data.** *Resolved by Addendum 3* for rename and merge (the design puts them on the thread's list row and the focused band's header, mirroring Participants). `Split…` is designed as a panel listing the thread's topics by meeting with checkboxes; the data it lists is F-5's last sentence.

**F-11 · Stories 6.2 / 6.4 — provenance summary. Resolved by owner review.** The full provenance remains in the drop; posted acquisition status now serves the card-safe summary `source:{sourceId,tool,toolVersion}`.

**F-12 · Story 7.2 — resolved-by-source speaker row. Resolved by owner review.** Every speakers row now carries nullable `participantId` and `displayName`, populated for source- or alias-resolved labels; Story 7.4 owns Correct.

**F-13 · Story 7.4 — clip stop. Resolved by owner review.** `ReplayPlayer` gains optional `endMs`; speaker samples set `startMs + 8000`, and existing callers omit it to retain current behavior.

**F-14 · Story 8.2 / 8.2a — binding and provider shapes. Resolved by owner review.** The failing-binding type is `urn:meetingminer:problem:binding-failed` with provider, binding, and upstream status in `detail`; `/status` owns `providers[]{provider,keyState,detail,remediation}` beside role bindings.

**F-15 · Story 6.6 — `affordanceOf()` hides the deep link when a recording exists.** Today `deepLink` is only offered when `hasRecording` is false. UX-DR12 wants the YouTube link *beside* replay; 6.6 changes the decision to return both, and labels the link `Open on YouTube at H:MM:SS` when the host is `youtube.com` / `youtu.be` (the existing Teams label `Open in Stream` stays for other hosts).

**F-16 · Story 10.5 — the `api /health` panel leaves the front door.** The design keeps it on `/meetings` only; `/status` and the chrome dot answer the same question. Confirm, since the current home test may pin it.

**F-17 · Story 10.5 / 10.6 — keyboard shortcuts.** `EXPERIENCE.md · Interaction Primitives` adds `/`, `a`, `n`, `g m`, `g t`, `g e` and the timeline keys. No story names shortcuts; the global ones belong to 10.5 (chrome) and the timeline ones to 10.6/10.6a.

**F-18 · Owner — versioning. Resolved by owner review.** The dated workspace's spines, seven promoted mockups, validation reports, findings, and adoption guide are tracked. `.working/`, screenshots, memlogs, and snapshots remain ignored local evidence.

**F-19 · Story 6.2a / 6.5 — playlist URLs in the UI.** Story 6.2a acquires playlists from the command line; no UI story accepts a playlist URL. The design's shape check refuses one on the URL tab with `Playlist URLs are not accepted on this tab — paste one video's watch link.` If the owner wants playlists in Add-meeting, a story must add it (probe + one acquisition per video).

**F-20 · Story 10.2b — no UI change.** Thread questions route through the existing ask box and cite moments only; the design adds nothing for it and notes it here so the omission is deliberate.

## Added after the reviewer gate (accessibility and editorial lenses, 2026-08-29)

**F-21 · Owner — WCAG resize and reflow. Resolved by owner review.** The narrow layout is funded and specified: 200% text resize, page reflow to 320 CSS px, two-row chrome, one-column Moments and Add-meeting, stacked Speaker naming, and a named timeline data scrollport. The prior desktop-only exception is removed.

**F-22 · Story 10.5 / 10.6a / 7.4 — captions on the inline player and `alt` on screenshots.** The product owns a transcript for every meeting, so `ReplayPlayer` can attach a WebVTT captions track generated client-side from `/drilldown` `segments[]` (WCAG 1.2.2, Level A); nothing serves it today. The design specifies it (off by default, remembered per browser) and the screenshot `alt` rule `<viewType> at <offset>, <meetingTitle>`; the feed item (story 10.4, F-3) needs `viewType` for the latter. `ReplayPlayer` is shared, so the track prop is optional and lands with whichever of 10.5, 10.6a, or 7.4 touches the player first.

**F-23 · Story 10.5 — the `Button` focus ring.** `components/ui/button.tsx` draws `focus-visible:ring-3 ring-ring/50`, which composites to 2.60:1 on the dark base. `DESIGN.md · Components · Focus ring` replaces it with a two-tone ring (2px `{colors.ring}` at 100% outside a 1px background gap); the change is one class list in `button.tsx` plus the `--ring` value in `index.css`, and belongs to 10.5 with the dark class.

**F-24 · Story 10.5 — control borders.** shadcn's `border` at white 10% identifies inputs and outline buttons at 1.25:1; `DESIGN.md` adds `control-border` (white 34%) for inputs, select triggers, and outline buttons. One token in `index.css` and the `outline` variant in `button.tsx`; 10.5 with the rest of the shell.

**F-25 · Owner — nine spine terms have no `docs/glossary.md` entry.** *thread, topic, speaker tag, alias, rerun, binding, catalog, role, provider* are defined in `EXPERIENCE.md · Voice and Tone` because the glossary lacks them. Adding them to `docs/glossary.md` in the spine's wording (a `docs/` edit, outside this story's boundary) keeps one vocabulary; until then the spine's definitions govern the UI copy.
