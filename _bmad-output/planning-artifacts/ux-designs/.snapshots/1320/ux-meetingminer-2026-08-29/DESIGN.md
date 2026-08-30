---
name: MeetingMiner
description: Visual identity for the MeetingMiner web app — the dark, data-dense evidence idiom of spec-ui-reimagine, extended with a color system that carries meaning (moment kind, ingestion state, provider health, thread identity) and nothing else. Built on shadcn/ui over Tailwind v4; this file states the delta from web/src/index.css.
status: draft
updated: 2026-08-29
sources:
  - _bmad-output/planning-artifacts/epics.md  (Epics 6, 7, 8, 10; FR33–FR43; UX-DR12–UX-DR18)
  - _bmad-output/planning-artifacts/sprint-change-proposal-2026-08-29.md
  - _bmad-output/specs/spec-ui-reimagine/SPEC.md, reference-ui.md, current-ui-inventory.md
  - web/src/index.css  (the live token surface, read from worktree 6-1 at e5510c7)
  - web/src/features/meetings/stageStyles.ts  (the state colors already in use)
  - docs/glossary.md
colors:
  # Base — byte-identical to web/src/index.css `.dark`; listed so the file stands alone. Hex is the sRGB rendering of the oklch value in the comment.
  background: '#0A0A0A'   # oklch(0.145 0 0)
  card: '#171717'   # oklch(0.205 0 0)
  popover: '#171717'   # oklch(0.205 0 0)
  foreground: '#FAFAFA'   # oklch(0.985 0 0)
  muted: '#262626'   # oklch(0.269 0 0)
  muted-foreground: '#A1A1A1'   # oklch(0.708 0 0)
  border: '#FFFFFF1A'   # rgba(255,255,255,0.10) — white at 10% over background (index.css: oklch(1 0 0 / 10%))
  ring: '#4BA3F7'   # oklch(0.7 0.15 250)  — NEW: focus ring gains chroma (was oklch(0.556 0 0))
  primary: '#E5E5E5'   # oklch(0.922 0 0)
  primary-foreground: '#171717'   # oklch(0.205 0 0)
  secondary: '#262626'   # oklch(0.269 0 0) — index.css .dark, unchanged
  accent: '#262626'   # oklch(0.269 0 0) — index.css .dark, unchanged (shadcn hover surface, not a brand accent)
  destructive: '#FF6467'   # oklch(0.704 0.191 22.216) — index.css .dark, unchanged
  input: '#FFFFFF26'   # oklch(1 0 0 / 15%) — index.css .dark, unchanged
  # Moment kinds — one hue per MomentArtifact.kind, 51° apart, rotated off the state hues. Chip = fill + text + border; the same text color is the kind used as plain colored text.
  kind-decision-fill: '#142B40'   # oklch(0.28 0.05 249)
  kind-decision-text: '#ADD6FF'   # oklch(0.86 0.0723 249)
  kind-decision-border: '#487EB3'   # oklch(0.58 0.1 249)
  kind-adr-fill: '#2D233E'   # oklch(0.28 0.05 300)
  kind-adr-text: '#D9C6FF'   # oklch(0.86 0.0812 300)
  kind-adr-border: '#846CAD'   # oklch(0.58 0.1 300)
  kind-action-item-fill: '#302907'   # oklch(0.28 0.05 96)
  kind-action-item-text: '#E6D17A'   # oklch(0.86 0.11 96)
  kind-action-item-border: '#8C7A2B'   # oklch(0.58 0.1 96)
  kind-story-fill: '#172F1A'   # oklch(0.28 0.05 147)
  kind-story-text: '#A0E5A7'   # oklch(0.86 0.11 147)
  kind-story-border: '#4F8A57'   # oklch(0.58 0.1 147)
  kind-requirement-fill: '#003031'   # oklch(0.28 0.0488 198)
  kind-requirement-text: '#6CE7EB'   # oklch(0.86 0.11 198)
  kind-requirement-border: '#008C8F'   # oklch(0.58 0.0989 198)
  kind-bug-fix-fill: '#3B1E2C'   # oklch(0.28 0.05 351)
  kind-bug-fix-text: '#FFB9D8'   # oklch(0.86 0.0889 351)
  kind-bug-fix-border: '#A76082'   # oklch(0.58 0.1 351)
  kind-change-request-fill: '#3D2013'   # oklch(0.28 0.05 45)
  kind-change-request-text: '#FFC1A5'   # oklch(0.86 0.0812 45)
  kind-change-request-border: '#AB6646'   # oklch(0.58 0.1 45)
  # Ingestion, acquisition, and rerun states — the Tailwind v4 values behind the classes web/src/features/meetings/stageStyles.ts already uses. Meaning and value unchanged.
  state-running-bar: '#FE9A00'   # oklch(0.769 0.188 70.08)
  state-running-text: '#FFB900'   # oklch(0.828 0.189 84.429)
  state-done-bar: '#009966'   # oklch(0.596 0.145 163.225)
  state-posted-bar: '#009966'   # oklch(0.596 0.145 163.225)
  state-posted-text: '#00D492'   # oklch(0.765 0.177 163.223)
  state-skipped-bar: '#90A1B9'   # oklch(0.704 0.04 256.788)
  state-failed-bar: '#EC003F'   # oklch(0.586 0.253 17.585)
  state-failed-text: '#FF637E'   # oklch(0.712 0.194 13.428)
  state-unknown-bar: '#C800DE'   # oklch(0.591 0.293 322.896)
  state-unknown-text: '#ED6AFF'   # oklch(0.74 0.238 322.16)
  state-queued-bar: 'transparent'   # dashed border in {colors.muted-foreground} at 40%
  # Provider and component health — dot + word, never the dot alone. Same three hues as the states: the eye learns one vocabulary.
  health-ok-dot: '#009966'   # oklch(0.596 0.145 163.225)
  health-ok-text: '#00D492'   # oklch(0.765 0.177 163.223)
  health-degraded-dot: '#FE9A00'   # oklch(0.769 0.188 70.08)
  health-degraded-text: '#FFB900'   # oklch(0.828 0.189 84.429)
  health-invalid-dot: '#EC003F'   # oklch(0.586 0.253 17.585)
  health-invalid-text: '#FF637E'   # oklch(0.712 0.194 13.428)
  health-missing-dot: '#EC003F'   # oklch(0.586 0.253 17.585)
  health-missing-text: '#FF637E'   # oklch(0.712 0.194 13.428)
  health-not-required-dot: '#90A1B9'   # oklch(0.704 0.04 256.788)
  health-not-required-text: '#90A1B9'   # oklch(0.704 0.04 256.788)
  health-stopped-dot: '#EC003F'   # oklch(0.586 0.253 17.585)
  health-stopped-text: '#FF637E'   # oklch(0.712 0.194 13.428)
  # Thread identity — 12 hues 30° apart at L 0.72 C 0.13; lap 2 is the same hue darker and hatched; beyond 24 the band is muted-foreground and the name carries identity.
  thread-1-band: '#E680A1'   # oklch(0.72 0.13 0)
  thread-1-band-lap2: '#9C5A6F'   # oklch(0.55 0.09 0)
  thread-2-band: '#EB8373'   # oklch(0.72 0.13 30)
  thread-2-band-lap2: '#9F5C52'   # oklch(0.55 0.09 30)
  thread-3-band: '#DF8F48'   # oklch(0.72 0.13 60)
  thread-3-band-lap2: '#986438'   # oklch(0.55 0.09 60)
  thread-4-band: '#C4A032'   # oklch(0.72 0.13 90)
  thread-4-band-lap2: '#866F2C'   # oklch(0.55 0.09 90)
  thread-5-band: '#9AB04B'   # oklch(0.72 0.13 120)
  thread-5-band-lap2: '#6B7939'   # oklch(0.55 0.09 120)
  thread-6-band: '#62BB78'   # oklch(0.72 0.13 150)
  thread-6-band-lap2: '#488055'   # oklch(0.55 0.09 150)
  thread-7-band: '#06BFA8'   # oklch(0.72 0.13 180)
  thread-7-band-lap2: '#218373'   # oklch(0.55 0.09 180)
  thread-8-band: '#00B9CF'   # oklch(0.72 0.1247 210)
  thread-8-band-lap2: '#177F8E'   # oklch(0.55 0.09 210)
  thread-9-band: '#4BAEED'   # oklch(0.72 0.13 240)
  thread-9-band-lap2: '#3A78A1'   # oklch(0.55 0.09 240)
  thread-10-band: '#859FF6'   # oklch(0.72 0.13 270)
  thread-10-band-lap2: '#5D6FA6'   # oklch(0.55 0.09 270)
  thread-11-band: '#B191EA'   # oklch(0.72 0.13 300)
  thread-11-band-lap2: '#7A659E'   # oklch(0.55 0.09 300)
  thread-12-band: '#D285CB'   # oklch(0.72 0.13 330)
  thread-12-band-lap2: '#8F5E8B'   # oklch(0.55 0.09 330)
  thread-on-band: '#0B0B0B'   # oklch(0.15 0 0) — label text laid over a band
typography:
  # Families are what index.css binds today: `--font-sans: 'Geist Variable'` and Tailwind's default `--font-mono` stack. No new family.
  sans:
    fontFamily: "'Geist Variable', ui-sans-serif, system-ui, sans-serif"
  mono:
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace"
  display:
    fontFamily: '{typography.sans.fontFamily}'
    fontSize: 30px
    fontWeight: '600'
    lineHeight: '1.2'
    letterSpacing: -0.02em
  title:
    fontFamily: '{typography.sans.fontFamily}'
    fontSize: 18px
    fontWeight: '600'
    lineHeight: '1.3'
    letterSpacing: -0.01em
  section-title:
    fontFamily: '{typography.sans.fontFamily}'
    fontSize: 14px
    fontWeight: '500'
    lineHeight: '1.4'
  card-title:
    fontFamily: '{typography.sans.fontFamily}'
    fontSize: 15px
    fontWeight: '600'
    lineHeight: '1.35'
  body:
    fontFamily: '{typography.sans.fontFamily}'
    fontSize: 14px
    fontWeight: '400'
    lineHeight: '1.5'
  body-sm:
    fontFamily: '{typography.sans.fontFamily}'
    fontSize: 12px
    fontWeight: '400'
    lineHeight: '1.45'
  label:
    fontFamily: '{typography.sans.fontFamily}'
    fontSize: 10px
    fontWeight: '500'
    lineHeight: '1.2'
    letterSpacing: 0.1em
  stat:
    fontFamily: '{typography.mono.fontFamily}'
    fontSize: 20px
    fontWeight: '400'
    lineHeight: '1.2'
  mono-sm:
    fontFamily: '{typography.mono.fontFamily}'
    fontSize: 12px
    fontWeight: '400'
    lineHeight: '1.4'
  mono-xs:
    fontFamily: '{typography.mono.fontFamily}'
    fontSize: 11px
    fontWeight: '400'
    lineHeight: '1.3'
rounded:
  # Derived from the one `--radius: 0.625rem` in index.css: sm = ×0.6, md = ×0.8, lg = ×1, xl = ×1.4.
  sm: 6px
  md: 8px
  lg: 10px
  xl: 14px
  full: 9999px
spacing:
  # Tailwind's 4px scale is inherited unchanged; these are the named distances the screens are built from.
  '1': 4px
  '2': 8px
  '3': 12px
  '4': 16px
  '5': 20px
  '6': 24px
  '8': 32px
  page-padding: 32px
  block-gap: 32px
  chrome-height: 56px
  card-padding: 16px
  card-gap: 20px
  chip-padding: 2px 8px
  chip-gap: 6px
  rail-width: 280px
  film-strip-width: 200px
  thread-list-width: 280px
  band-height: 20px
  band-gap: 4px
  timeline-row: 28px
  shell-max-width: 1600px
  reading-max-width: 1024px
  form-max-width: 720px
components:
  chrome:
    background: '{colors.background}'
    border-bottom: '1px solid {colors.border}'
    height: '{spacing.chrome-height}'
    position: 'sticky top'
  section-header:
    font: '{typography.section-title}'
    color: '{colors.muted-foreground}'
    count-font: '{typography.mono-sm}'
    count-color: '{colors.foreground}'
  moment-card:
    background: '{colors.card}'
    border: '1px solid {colors.border}'
    radius: '{rounded.lg}'
    padding: '{spacing.card-padding}'
    title-font: '{typography.card-title}'
    meta-font: '{typography.mono-sm}'
    meta-color: '{colors.muted-foreground}'
    screenshot-ratio: '16 / 9'
  screenshot-frame:
    background: '{colors.muted}'
    radius: '{rounded.md}'
    offset-chip-font: '{typography.mono-xs}'
    offset-chip-background: 'rgba(0,0,0,0.60)'
    offset-chip-color: '{colors.foreground}'
  kind-chip:
    radius: '{rounded.sm}'
    padding: '{spacing.chip-padding}'
    font: '{typography.body-sm}'
    glyph: 'decision ◆ · adr § · action-item ☐ · story ▣ · requirement ≡ · bug-fix ✕ · change-request Δ'
    fill: '{colors.kind-<kind>-fill}'
    color: '{colors.kind-<kind>-text}'
    border: '1px solid {colors.kind-<kind>-border}'
  thread-chip:
    radius: '{rounded.full}'
    padding: '{spacing.chip-padding}'
    font: '{typography.body-sm}'
    prefix: '#'
    color: '{colors.thread-<n>-band}'
    border: '1px solid {colors.thread-<n>-band}'
    background: 'transparent'
  thread-band:
    height: '{spacing.band-height}'
    gap: '{spacing.band-gap}'
    fill: '{colors.thread-<n>-band}'
    fill-lap2: '{colors.thread-<n>-band-lap2} hatched 135° 3px/7px'
    fill-beyond: '{colors.muted-foreground} at 35%'
    density-alpha: '0.08 · 0.30 · 0.50 · 0.75 · 1.00  (quintiles of mentions per bucket; 0 mentions = 0.08)'
    label-font: '{typography.body-sm}'
    label-color: '{colors.thread-<n>-band}'
    on-band-label-color: '{colors.thread-on-band}'
  state-bar:
    height: 6px
    radius: '{rounded.sm}'
    queued: '1px dashed {colors.muted-foreground} at 40%, transparent fill'
    running: '{colors.state-running-bar}, 2s pulse (none under reduced motion)'
    done: '{colors.state-done-bar}'
    posted: '{colors.state-posted-bar}'
    skipped: '{colors.state-skipped-bar} hatched 135° 2px/5px, 1px border at 60%'
    failed: '{colors.state-failed-bar}'
    unknown: '{colors.state-unknown-bar}, 1px darker border'
  state-word:
    font: '{typography.mono-xs}'
    running: '{colors.state-running-text}'
    posted: '{colors.state-posted-text}'
    failed: '{colors.state-failed-text}'
    unknown: '{colors.state-unknown-text}'
    done: '{colors.foreground}'
    skipped: '{colors.muted-foreground} italic'
    queued: '{colors.muted-foreground} at 60%'
  health-dot:
    size: 8px
    radius: '{rounded.full}'
    ok: '{colors.health-ok-dot}'
    degraded: '{colors.health-degraded-dot}'
    invalid: '{colors.health-invalid-dot}'
    missing: '{colors.health-missing-dot}'
    not-required: '{colors.health-not-required-dot}'
    stopped: '{colors.health-stopped-dot}'
    word-font: '{typography.body-sm}'
    word-color: '{colors.health-<state>-text}'
  reason-line:
    gap: '{spacing.chip-gap}'
    chips: '{components.kind-chip} for artifact/due reasons · {components.thread-chip} for thread reasons · plain {typography.body-sm} {colors.muted-foreground} for recency/publication reasons'
  refusal-box:
    background: '{colors.state-failed-bar} at 12%'
    border: '1px solid {colors.state-failed-bar}'
    radius: '{rounded.md}'
    padding: '{spacing.3} {spacing.4}'
    rule-font: '{typography.mono-sm}'
    rule-color: '{colors.state-failed-text}'
    detail-font: '{typography.body}'
    remediation-prefix: '→'
  source-tab:
    font: '{typography.body}'
    inactive-color: '{colors.muted-foreground}'
    active-color: '{colors.foreground}'
    active-indicator: '2px solid {colors.primary} bottom edge'
    padding: '{spacing.2} {spacing.4}'
  acquisition-stepper:
    steps: 'launch → running → posted → ingesting'
    bar: '{components.state-bar}'
    word: '{components.state-word}'
    log-font: '{typography.mono-xs}'
    log-background: '{colors.muted} at 40%'
  speaker-row:
    tag-font: '{typography.mono-sm}'
    share-bar-height: 6px
    share-bar-fill: '{colors.primary} at 70%'
    share-bar-track: '{colors.muted}'
    share-font: '{typography.mono-sm}'
  clip-button:
    variant: 'outline'
    font: '{typography.mono-sm}'
    glyph: '▶'
    active-border: '1px solid {colors.ring}'
  model-select:
    trigger-font: '{typography.body-sm}'
    trigger-border: '1px solid {colors.border}'
    popover-background: '{colors.popover}'
    popover-border: '1px solid {colors.border}'
    popover-radius: '{rounded.md}'
    option-font: '{typography.body-sm}'
    option-active-mark: '✓ in {colors.foreground}'
    option-health: '{components.health-dot} + word'
    option-unavailable-color: '{colors.muted-foreground}'
  focus-ring:
    ring: '3px {colors.ring} at 50%'
    offset: 0
  timeline-axis:
    label-font: '{typography.mono-xs}'
    label-color: '{colors.muted-foreground}'
    gridline: '1px solid {colors.border}'
    cursor-line: '1px solid {colors.foreground} at 40%'
  lod-card:
    background: '{colors.card}'
    border: '1px solid {colors.border}'
    radius: '{rounded.md}'
    screenshot-width: 160px
    excerpt-font: '{typography.body-sm}'
    anchor-font: '{typography.mono-xs}'
---

# MeetingMiner — Design Spine

> Peer of `EXPERIENCE.md` (how it works). This file owns how it looks. Both spines win over every mock under `mockups/` and every study under `.working/` on conflict. Token references use `{path.to.token}` against the frontmatter above.

## Brand & Style

MeetingMiner is an evidence instrument, not a meeting-notes app. Every number on screen is a database-of-record count, every claim traces to a moment you can replay, and the interface says so by never decorating: no illustration, no gradient, no color that does not name a fact. The adopted base is the reimagined UI's dark, data-dense idiom — counts in section headers (`Screens 158`), offsets as the connective tissue (`12:40`, `1:04:09`), honest absence written in place ("No participant graph for this meeting — no transcript speaker resolved to a participant record").

The owner's direction on top of that base: *make sure there's a bit of color*, and *the UI needs to be amazing*. This spine spends its color budget on exactly five meanings and refuses a sixth:

| Meaning | Where it appears | Carrier besides hue |
|---|---|---|
| Moment kind (the seven `MomentArtifact.kind` values) | kind chips on cards, rail headers, feed filters, timeline evidence | leading glyph + the kind's name |
| Ingestion / acquisition / rerun state | stage bars, acquisition stepper, meeting cards | bar texture (dashed, solid, hatched, pulse) + the state word |
| Provider and component health | model selector, status page, chrome indicator | dot + the state word + remediation |
| Thread identity | thread bands, thread chips, thread reasons | `#name` text, always |
| Ranking reason | the reason line on a Moments card | the api's own reason label, verbatim |

Everything else — chrome, text, borders, buttons, inputs, screenshots — stays on the achromatic base that `web/src/index.css` already declares. The result reads like a dark instrument panel where the colored elements are the readings.

Posture in three words: **dense, literal, calm.** Dense because the operator is an architect who wants the whole meeting on one screen. Literal because the product's promise is that nothing on screen is invented. Calm because the color is rare enough to be a signal.

`[ASSUMPTION]` **Design direction: "Relaxed cards" for the Moments front door, "Mono-dense" everywhere else.** The two directions were rendered to `.working/direction-mono-dense.html` and `.working/direction-relaxed-cards.html`. The Moments view is the one surface read at a glance rather than scanned, so its cards get the 16:9 screenshot, `{typography.card-title}`, `{spacing.card-padding}`, and `{spacing.card-gap}`; the meeting view, rails, timeline tiers, Add-meeting, and Speaker naming keep the reference density (12px paddings, `{typography.mono-sm}` everywhere a value is served). The owner can swap by name; nothing in EXPERIENCE.md depends on the choice.

## Colors

`[ASSUMPTION]` **Color system A · Signal is the pick.** Three systems were rendered with every text-on-surface pair measured by script (oklch → sRGB → WCAG 2.x): `.working/color-system-a-signal.html`, `.working/color-system-b-spectrum.html`, `.working/color-system-c-ember.html`. A keeps the base byte-identical to `index.css` `.dark`, so the four existing screens migrate by applying one class; B tints the base blue-black and adds a teal brand accent with solid chips; C warms the base and collapses kinds to three hue families told apart by glyph. A was chosen because the owner asked for *a bit* of color, and A is the only one whose color appears nowhere a meaning does not. To swap: replace the `colors:` block with the values in the chosen page's `<style>` comment; the semantic assignments below do not change.

**Dark is the only mode.** The app's `.dark` tokens exist but are never applied today (`index.html` carries no class); this design commits to a single dark look and the shell applies `.dark` at the `html` element (recorded for story 10.7 in `findings-for-epics.md`). Light tokens in `index.css` are left untouched and unsupported.

### Base (shadcn names, values from `index.css` `.dark`)

- **background `{colors.background}`** — the page. Nothing sits on it but text, the chrome, and cards.
- **card `{colors.card}`** — every bounded surface: cards, rails, panels, the ask box, popovers. One step up in tone; the only elevation the product has (see Elevation & Depth).
- **foreground `{colors.foreground}`** — body text, titles, counts. 18.96:1 on background.
- **muted-foreground `{colors.muted-foreground}`** — section headers, labels, offsets, meta lines, absence notes. 7.63:1 on background (AAA), 6.91:1 on card (AA). This is the app's *quiet* voice, and most of its text is quiet.
- **muted `{colors.muted}`** — screenshot placeholders, share-bar tracks, log backgrounds at 40%.
- **border `{colors.border}`** — white at 10%; the only line weight is 1px.
- **primary `{colors.primary}` / primary-foreground** — the one filled button per surface (Replay, Add meeting, Ask, Save). Near-white on near-black: 14.22:1. Deliberately achromatic so the primary action never competes with a meaning color.
- **ring `{colors.ring}`** — *the one changed base token.* Focus must be visible on a dark instrument, and grey-on-grey was 4.1:1 against the page; blue at L 0.70 is 7.44:1 and shares no hue with a state or health color (decision blue is a chip, never an outline). Used only for `:focus-visible` and the active clip button.
- **destructive `{colors.destructive}`** — kept for shadcn's destructive button variant only. Failure *states* use `state-failed-*`, not destructive, so "this failed" and "this button deletes" never share a color.

### Moment kinds

One hue per `MomentArtifact.kind`, seven hues 51° apart, rotated so none lands on a state hue: change-request 45°, action-item 96°, story 147°, requirement 198°, decision 249°, adr 300°, bug-fix 351°. Each kind has a **fill** (L 0.28, dark tint), a **text** (L 0.86) and a **border** (L 0.58). A kind chip is fill + text + border + glyph; the same text color is used when a kind is written as colored words (a rail header, a reason). Text-on-fill is AAA for all seven (9.38–9.74:1); text-on-card is AAA for all seven (≥ 11.27:1); border-on-card is 3.96–4.38:1 for all seven.

The glyphs — ◆ decision, § adr, ☐ action-item, ▣ story, ≡ requirement, ✕ bug-fix, Δ change-request — are not decoration: they are the second carrier that lets two kinds 51° apart be told apart by a reader who cannot tell the hues apart. A chip without its glyph is a defect.

Kinds that do not exist in the api do not get a color. FR40 names "risks and open questions" as ranking signals, but no `risk` or `question` kind exists in `MomentArtifact.kind`; no card draws one, and the gap is recorded in `findings-for-epics.md`.

### States

The stage bars already speak: `stageStyles.ts` renders running as amber-500 with a pulse, done as emerald-600, failed as rose-600, skipped as a slate-400 hatch, queued as a dashed outline, unknown as fuchsia-600. Those exact values are the state tokens here — same meaning, same value — extended to the two new state machines: acquisition (`queued | running | posted | failed`, story 6.4) and the speaker-naming rerun (the existing stages, re-queued). `posted` is emerald because it means "handed to `/ingests`" — done from acquisition's point of view — and the meeting card's stage bars take over from there.

Texture is the second carrier: dashed = not started, solid = happened, hatched = legitimately skipped, pulse = happening. A colorblind reader reads the bars from texture alone; the state word beside the bar is the third.

### Health

Three hues the eye already knows from the states, reused for a different noun: ok = emerald, degraded = amber, invalid/missing/stopped = rose, not-required = slate. A health reading is always a dot **and** a word (`● ok`, `● invalid`), and a degraded or invalid reading always carries its `remediation` sentence beside it (`→ set OPENAI_API_KEY in .env, restart the api`). The dot alone appears only in the chrome indicator, which the existing `StatusIndicator` already labels with text.

### Threads

Twelve hues, 30° apart, at L 0.72 C 0.13 — light enough to sit on the page at ≥ 7.5:1 as a band and to be read as text on a card at ≥ 6.79:1 (threads 1–3 and 11–12 are AA at 6.79–6.99:1; threads 4–10 are AAA at 7.10–7.66:1). A thread's hue is **stable**: `[ASSUMPTION]` it is assigned client-side from a hash of the thread id (`FNV-1a(threadId) mod 12`), so a thread keeps its color across sessions, sorts, and filters without the api knowing about palettes. Two adjacent bands in the Threads view can therefore share a hue; the design accepts that because the band's `#name` label is always rendered and the sort is by activity, so neighbors are usually far apart in id space.

Past twelve: threads 13–24 take the same hue at **lap 2** — L 0.55, hatched 135° 3px/7px — which is 3.88–4.28:1 on the page and visibly not lap 1. Past 24 the band is `{colors.muted-foreground}` at 35% with no hatch, and the name alone identifies it. A corpus with more than 24 live threads is a corpus whose Threads view is being sorted and filtered anyway; the palette does not pretend 40 hues are distinguishable.

Mention density on a band is alpha, not hue: five steps — 0.08, 0.30, 0.50, 0.75, 1.00 — by quintile of mentions-per-bucket across the visible window, with zero mentions drawn at 0.08 so the band's span stays legible. A numeric tooltip states the count; alpha is a shape, not a reading.

### Contrast — every pair, measured

Method: each oklch value converted to sRGB (clamped to gamut), WCAG 2.x relative luminance, ratio rounded to two places. Text pairs are graded AAA ≥ 7, AA ≥ 4.5; non-text pairs (bars, dots, borders, rings) pass at ≥ 3. The 97 pairs below are the pairs the screens use; a builder adding a new pair adds a row here.

**AAA (41 pairs):** all body and title text on page and card; muted text on the page; every kind chip label on its fill; every kind as colored text on a card; running, posted, and ok words; the primary button; every thread name laid over its own band; threads 4–10 as text on a card.
**AA (12 pairs):** `muted-foreground` on card (6.91); the failed, unknown, invalid, missing, stopped, and not-required words on card (6.26–6.94); threads 1, 2, 3, 11, 12 as text on card (6.79–6.99). None of these carries body text; all are labels beside a bar, dot, or band that carries the same fact.
**Non-text (44 pairs):** all ≥ 3.88; the lowest are the lap-2 thread bands at 3.88–4.28, which are also hatched; kind chip borders are 3.96–4.38 and sit inside a chip whose text is AAA.

| Pair | Ratio | Grade | Used for |
|---|---:|---|---|
| `foreground / background` | 18.96 | AAA | body text on the page |
| `foreground / card` | 17.16 | AAA | body text on cards, rails, popovers |
| `muted-foreground / background` | 7.63 | AAA | section headers, labels, offsets on the page |
| `muted-foreground / card` | 6.91 | AA | section headers, labels, offsets on cards |
| `primary-foreground / primary` | 14.22 | AAA | primary button label |
| `ring / background (non-text)` | 7.44 | ok | focus ring (non-text, ≥3:1) |
| `kind-decision-text / kind-decision-fill` | 9.57 | AAA | kind chip label on its fill |
| `kind-decision-as-text / card` | 11.77 | AAA | kind as colored text (reason line, rail header) |
| `kind-decision-border / card (non-text)` | 4.21 | ok | chip outline (non-text, ≥3:1) |
| `kind-adr-text / kind-adr-fill` | 9.47 | AAA | kind chip label on its fill |
| `kind-adr-as-text / card` | 11.45 | AAA | kind as colored text (reason line, rail header) |
| `kind-adr-border / card (non-text)` | 4.03 | ok | chip outline (non-text, ≥3:1) |
| `kind-action-item-text / kind-action-item-fill` | 9.57 | AAA | kind chip label on its fill |
| `kind-action-item-as-text / card` | 11.75 | AAA | kind as colored text (reason line, rail header) |
| `kind-action-item-border / card (non-text)` | 4.19 | ok | chip outline (non-text, ≥3:1) |
| `kind-story-text / kind-story-fill` | 9.74 | AAA | kind chip label on its fill |
| `kind-story-as-text / card` | 12.16 | AAA | kind as colored text (reason line, rail header) |
| `kind-story-border / card (non-text)` | 4.37 | ok | chip outline (non-text, ≥3:1) |
| `kind-requirement-text / kind-requirement-fill` | 9.73 | AAA | kind chip label on its fill |
| `kind-requirement-as-text / card` | 12.19 | AAA | kind as colored text (reason line, rail header) |
| `kind-requirement-border / card (non-text)` | 4.38 | ok | chip outline (non-text, ≥3:1) |
| `kind-bug-fix-text / kind-bug-fix-fill` | 9.38 | AAA | kind chip label on its fill |
| `kind-bug-fix-as-text / card` | 11.27 | AAA | kind as colored text (reason line, rail header) |
| `kind-bug-fix-border / card (non-text)` | 3.96 | ok | chip outline (non-text, ≥3:1) |
| `kind-change-request-text / kind-change-request-fill` | 9.46 | AAA | kind chip label on its fill |
| `kind-change-request-as-text / card` | 11.44 | AAA | kind as colored text (reason line, rail header) |
| `kind-change-request-border / card (non-text)` | 4.03 | ok | chip outline (non-text, ≥3:1) |
| `state-running-bar / background (non-text)` | 9.23 | ok | stage / acquisition bar (non-text, ≥3:1) |
| `state-running-text / card` | 10.43 | AAA | state word beside the bar |
| `state-done-bar / background (non-text)` | 5.40 | ok | stage / acquisition bar (non-text, ≥3:1) |
| `state-posted-bar / background (non-text)` | 5.40 | ok | stage / acquisition bar (non-text, ≥3:1) |
| `state-posted-text / card` | 9.27 | AAA | state word beside the bar |
| `state-skipped-bar / background (non-text)` | 7.53 | ok | stage / acquisition bar (non-text, ≥3:1) |
| `state-failed-bar / background (non-text)` | 4.39 | ok | stage / acquisition bar (non-text, ≥3:1) |
| `state-failed-text / card` | 6.26 | AA | state word beside the bar |
| `state-unknown-bar / background (non-text)` | 4.25 | ok | stage / acquisition bar (non-text, ≥3:1) |
| `state-unknown-text / card` | 6.94 | AA | state word beside the bar |
| `health-ok-dot / card (non-text)` | 4.89 | ok | health dot (non-text, ≥3:1) |
| `health-ok-text / card` | 9.27 | AAA | health word beside the dot |
| `health-degraded-dot / card (non-text)` | 8.35 | ok | health dot (non-text, ≥3:1) |
| `health-degraded-text / card` | 10.43 | AAA | health word beside the dot |
| `health-invalid-dot / card (non-text)` | 3.97 | ok | health dot (non-text, ≥3:1) |
| `health-invalid-text / card` | 6.26 | AA | health word beside the dot |
| `health-missing-dot / card (non-text)` | 3.97 | ok | health dot (non-text, ≥3:1) |
| `health-missing-text / card` | 6.26 | AA | health word beside the dot |
| `health-not-required-dot / card (non-text)` | 6.82 | ok | health dot (non-text, ≥3:1) |
| `health-not-required-text / card` | 6.82 | AA | health word beside the dot |
| `health-stopped-dot / card (non-text)` | 3.97 | ok | health dot (non-text, ≥3:1) |
| `health-stopped-text / card` | 6.26 | AA | health word beside the dot |
| `thread-1-band / background (non-text)` | 7.50 | ok | band vs page (non-text, ≥3:1) |
| `thread-1-on-band / thread-1-band` | 7.45 | AAA | thread name laid over its band |
| `thread-1-band as text / card` | 6.79 | AA | thread name as colored text (chip, legend) |
| `thread-1-band-lap2 / background (non-text)` | 3.88 | ok | lap-2 band vs page (non-text, ≥3:1) |
| `thread-2-band / background (non-text)` | 7.56 | ok | band vs page (non-text, ≥3:1) |
| `thread-2-on-band / thread-2-band` | 7.52 | AAA | thread name laid over its band |
| `thread-2-band as text / card` | 6.85 | AA | thread name as colored text (chip, legend) |
| `thread-2-band-lap2 / background (non-text)` | 3.91 | ok | lap-2 band vs page (non-text, ≥3:1) |
| `thread-3-band / background (non-text)` | 7.72 | ok | band vs page (non-text, ≥3:1) |
| `thread-3-on-band / thread-3-band` | 7.67 | AAA | thread name laid over its band |
| `thread-3-band as text / card` | 6.99 | AA | thread name as colored text (chip, legend) |
| `thread-3-band-lap2 / background (non-text)` | 3.98 | ok | lap-2 band vs page (non-text, ≥3:1) |
| `thread-4-band / background (non-text)` | 7.95 | ok | band vs page (non-text, ≥3:1) |
| `thread-4-on-band / thread-4-band` | 7.90 | AAA | thread name laid over its band |
| `thread-4-band as text / card` | 7.20 | AAA | thread name as colored text (chip, legend) |
| `thread-4-band-lap2 / background (non-text)` | 4.07 | ok | lap-2 band vs page (non-text, ≥3:1) |
| `thread-5-band / background (non-text)` | 8.21 | ok | band vs page (non-text, ≥3:1) |
| `thread-5-on-band / thread-5-band` | 8.16 | AAA | thread name laid over its band |
| `thread-5-band as text / card` | 7.43 | AAA | thread name as colored text (chip, legend) |
| `thread-5-band-lap2 / background (non-text)` | 4.17 | ok | lap-2 band vs page (non-text, ≥3:1) |
| `thread-6-band / background (non-text)` | 8.41 | ok | band vs page (non-text, ≥3:1) |
| `thread-6-on-band / thread-6-band` | 8.36 | AAA | thread name laid over its band |
| `thread-6-band as text / card` | 7.61 | AAA | thread name as colored text (chip, legend) |
| `thread-6-band-lap2 / background (non-text)` | 4.25 | ok | lap-2 band vs page (non-text, ≥3:1) |
| `thread-7-band / background (non-text)` | 8.47 | ok | band vs page (non-text, ≥3:1) |
| `thread-7-on-band / thread-7-band` | 8.42 | AAA | thread name laid over its band |
| `thread-7-band as text / card` | 7.66 | AAA | thread name as colored text (chip, legend) |
| `thread-7-band-lap2 / background (non-text)` | 4.28 | ok | lap-2 band vs page (non-text, ≥3:1) |
| `thread-8-band / background (non-text)` | 8.34 | ok | band vs page (non-text, ≥3:1) |
| `thread-8-on-band / thread-8-band` | 8.29 | AAA | thread name laid over its band |
| `thread-8-band as text / card` | 7.55 | AAA | thread name as colored text (chip, legend) |
| `thread-8-band-lap2 / background (non-text)` | 4.23 | ok | lap-2 band vs page (non-text, ≥3:1) |
| `thread-9-band / background (non-text)` | 8.11 | ok | band vs page (non-text, ≥3:1) |
| `thread-9-on-band / thread-9-band` | 8.06 | AAA | thread name laid over its band |
| `thread-9-band as text / card` | 7.34 | AAA | thread name as colored text (chip, legend) |
| `thread-9-band-lap2 / background (non-text)` | 4.14 | ok | lap-2 band vs page (non-text, ≥3:1) |
| `thread-10-band / background (non-text)` | 7.84 | ok | band vs page (non-text, ≥3:1) |
| `thread-10-on-band / thread-10-band` | 7.79 | AAA | thread name laid over its band |
| `thread-10-band as text / card` | 7.10 | AAA | thread name as colored text (chip, legend) |
| `thread-10-band-lap2 / background (non-text)` | 4.03 | ok | lap-2 band vs page (non-text, ≥3:1) |
| `thread-11-band / background (non-text)` | 7.63 | ok | band vs page (non-text, ≥3:1) |
| `thread-11-on-band / thread-11-band` | 7.59 | AAA | thread name laid over its band |
| `thread-11-band as text / card` | 6.91 | AA | thread name as colored text (chip, legend) |
| `thread-11-band-lap2 / background (non-text)` | 3.94 | ok | lap-2 band vs page (non-text, ≥3:1) |
| `thread-12-band / background (non-text)` | 7.52 | ok | band vs page (non-text, ≥3:1) |
| `thread-12-on-band / thread-12-band` | 7.47 | AAA | thread name laid over its band |
| `thread-12-band as text / card` | 6.80 | AA | thread name as colored text (chip, legend) |
| `thread-12-band-lap2 / background (non-text)` | 3.89 | ok | lap-2 band vs page (non-text, ≥3:1) |

## Typography

Two families, both already bound: **Geist Variable** (`{typography.sans}`) for everything a person wrote or reads as prose, and the platform monospace stack (`{typography.mono}`) for everything the system served — offsets, dates, counts, ids, config values, error text, log tails. The rule is provenance, not size: a served value is monospace even at 20px (`{typography.stat}`), a sentence is sans even at 10px.

| Role | Token | Used for |
|---|---|---|
| Display | `{typography.display}` | the app title in the chrome only |
| Title | `{typography.title}` | a screen's `h2` (meeting title, "Add a meeting", "Speakers") |
| Section title | `{typography.section-title}` | section headers, in `{colors.muted-foreground}`, count appended in `{typography.mono-sm}` `{colors.foreground}`: `Screens 158`, `Moments 24`, `Threads 11` |
| Card title | `{typography.card-title}` | a Moments card's meeting title |
| Body | `{typography.body}` | prose, transcript text, form labels, refusal detail |
| Body small | `{typography.body-sm}` | chips, meta sentences, absence notes, option rows |
| Label | `{typography.label}` | uppercase stat labels (`MEETINGS`, `HOURS OF EVIDENCE`) and artifact-group sub-headers |
| Stat | `{typography.stat}` | the corpus counts, talk-share percentages |
| Mono small | `{typography.mono-sm}` | offsets in cards and rails, dates, speaker tags, the rule name in a refusal |
| Mono xs | `{typography.mono-xs}` | offset chips on screenshots, axis labels, log tails, state words |

Counted headers keep the reference's shape — label, one space, count, optional unit — and the case the existing screens already use: sentence case in the meeting view (`Transcript 42 turns`), uppercase only where `MeetingsList` already uppercases its `h2`. Front-door headers follow the meeting view (sentence case). Tabular numerals (`font-variant-numeric: tabular-nums`) on every mono value so columns of offsets align.

Numbers and time: offsets as `H:MM:SS` or `M:SS` exactly as `offsetLabel()` renders them; dates as ISO `2026-08-14`; day-precision dates never show a time; durations as `1h 04m`. No relative dates ("3 days ago") anywhere — the product is about *when*, and a relative date decays.

## Layout & Spacing

**Viewport.** Desktop only; the minimum supported viewport is **1280 × 800** (Chrome on macOS is the recording target). Below 1280 the layout is allowed to scroll horizontally inside the timeline and to stack the Moments grid to two columns; nothing else adapts, and no mobile breakpoint exists.

**Shell.** The chrome is sticky at `{spacing.chrome-height}` and spans the viewport. Under it, the content width depends on what the screen is for:

| Width | Screens | Why |
|---|---|---|
| `{spacing.shell-max-width}` (1600px), centered, `{spacing.page-padding}` | Moments, Threads, Meetings | a ranked grid and a timeline are wider than a reading column |
| `{spacing.reading-max-width}` (1024px), centered | Meeting view, Moment view, Participants, Status, Settings, Speaker naming | the existing screens were built at `max-w-5xl`; they are not redesigned here |
| `{spacing.form-max-width}` (720px), centered | Add-meeting | a form reads at one column |

**Grids.** Moments: three columns of cards at ≥ 1440px, two at 1280–1439, `{spacing.card-gap}` between; an expanded card spans all columns. Threads: a `{spacing.thread-list-width}` list column (name, sort, search) beside a timeline canvas that takes the rest; the canvas is `{spacing.timeline-row}` per band row at the bands tier and grows per tier (see EXPERIENCE.md · Semantic Zoom). Speaker naming: three columns — speakers (`{spacing.rail-width}`), clips and naming (flexible), tag-filtered transcript (`{spacing.rail-width}`). Meeting view keeps its film-strip / transcript / rail grid from story ui-3 (`200px / 1fr / 280px`), with the new `Speakers` section added to the rail.

**Rhythm.** `{spacing.block-gap}` between top-level blocks, `{spacing.card-padding}` inside a Moments card, 12px (`{spacing.3}`) inside dense cards and rails, `{spacing.chip-gap}` between chips, `{spacing.band-gap}` between bands. The 4px scale is the only scale.

## Elevation & Depth

Tonal, not cast. Three layers: **page** (`{colors.background}`), **surface** (`{colors.card}`, one step lighter, 1px `{colors.border}`), **popover** (`{colors.popover}` — same tone as surface — plus 1px border and shadcn's `shadow-md`, the one shadow in the product, used only for things that float over other things: the model-select popover, the status-indicator popover, tooltips on bands). Nothing else casts a shadow. A card never lifts on hover; hover is a border going from 10% to 20% white. The Threads timeline is flat: bands, marks, and evidence cards all sit on the page or on a surface, and depth along the zoom axis is expressed by *what is drawn*, never by stacking or blur.

## Shapes

One radius token, four sizes, assigned by role: `{rounded.lg}` for cards and buttons (what `Button` already uses), `{rounded.md}` for screenshot frames, inputs, popovers, refusal boxes, and evidence cards, `{rounded.sm}` for kind chips, state bars, and offset chips, `{rounded.full}` for thread chips and health dots. The two pill shapes — thread chips and dots — are pills *because* they are the two things that are never a kind chip: shape separates thread identity from moment kind before color does.

Screenshots are always framed at 16:9 (`{components.screenshot-frame}`) with the offset chip in the bottom-left corner; a frame with no screenshot shows `{colors.muted}` and the absence sentence, never a placeholder graphic.

## Components

Visual specs. Behavior lives in EXPERIENCE.md · Component Patterns under the same names.

- **Chrome** (`{components.chrome}`) — 56px sticky bar on `{colors.background}` with a bottom `{colors.border}`. Left: `MeetingMiner` in `{typography.display}` reduced to 18px, then the primary nav in `{typography.body}` `{colors.muted-foreground}` with the current view in `{colors.foreground}` and a 2px `{colors.primary}` underline. Center: the search input and the ask box side by side, each a `{colors.card}` field with `{colors.border}`. Right: **Add meeting** as the surface's one primary button, then the health dot and its word.
- **Section header** (`{components.section-header}`) — `Screens 158` shape; the count is mono and foreground so it reads as a served number.
- **Moment card** (`{components.moment-card}`) — surface with `{rounded.lg}`; 16:9 screenshot frame on top; `{typography.card-title}` meeting title; a `{typography.mono-sm}` meta line `2026-08-14 · 12:40–14:05 · real`; the **reason line**; a two-line excerpt in `{typography.body}` with quotation marks; an action row with Replay as the primary button and Open moment / Open on YouTube as outline buttons. Hover: border to 20%. Expanded: the card spans the grid and the inline player renders under the screenshot at the card's width.
- **Kind chip** (`{components.kind-chip}`) — glyph, one space, text; `{rounded.sm}`; fill/text/border per kind. Never a kind chip without its glyph; never colored text without the kind's name.
- **Thread chip** (`{components.thread-chip}`) — `#name` in the thread's band color with a 1px border of the same and no fill; `{rounded.full}`. Lap-2 threads get a hatched left edge 6px wide inside the chip; beyond-palette threads render in `{colors.muted-foreground}`.
- **Thread band** (`{components.thread-band}`) — 20px tall row of buckets, alpha by density quintile; the name in the band color at left in the list column; lap 2 hatched; beyond palette grey. Hover on a bucket: `{components.timeline-axis.cursor-line}` and a popover with the count and the bucket's dates.
- **State bar** (`{components.state-bar}`) — 6px, `{rounded.sm}`, one per stage; the acquisition stepper is four of them labelled launch / running / posted / ingesting. Colors and textures as in Colors · States.
- **State word** (`{components.state-word}`) — the state's name in `{typography.mono-xs}` beside its bar.
- **Health dot** (`{components.health-dot}`) — 8px circle plus the word in `{typography.body-sm}`; a degraded/invalid/stopped reading is followed by `→ remediation` in `{colors.muted-foreground}`.
- **Reason line** (`{components.reason-line}`) — the api's reasons, in order, each as a kind chip (artifact and due reasons), a thread chip (thread reasons), or plain muted text (recency and publication reasons), separated by `{spacing.chip-gap}`. The label text is the api's `label`, verbatim.
- **Refusal box** (`{components.refusal-box}`) — rose tint at 12% with a 1px rose border; first line the rule name in `{typography.mono-sm}` `{colors.state-failed-text}` (`youtube-drop: duration over cap`), then the detail in `{typography.body}`, then `→ remediation` in `{colors.muted-foreground}`. It sits in place — under the field, under the stepper, in the answer region — never as a toast.
- **Source tab** (`{components.source-tab}`) — four text tabs; the active one in foreground with a 2px primary underline. Tabs are a `role="tablist"`.
- **Acquisition stepper** (`{components.acquisition-stepper}`) — four state bars with words, then a `{typography.mono-xs}` log tail on `{colors.muted}` at 40%, then — once posted — the meeting card with its stage bars.
- **Speaker row** (`{components.speaker-row}`) — `SPEAKER_03` in `{typography.mono-sm}`, a 6px share bar filled with `{colors.primary}` at 70% over `{colors.muted}`, the share as `{typography.stat}` reduced to 14px (`41%`), then `12m 04s · 38 segments` in muted mono.
- **Clip button** (`{components.clip-button}`) — outline button, `▶ 12:40` in mono; the playing clip's border becomes `{colors.ring}`.
- **Model select** (`{components.model-select}`) — trigger reads `chat · claude-sonnet-5 · anthropic ● ok`; popover lists catalog entries grouped by provider, each `label · binding` with a health dot and word, the active entry marked ✓, an entry whose provider key is invalid/missing rendered in `{colors.muted-foreground}` with its remediation and still selectable (the failure must surface where it happens, not be hidden by the picker).
- **Focus ring** (`{components.focus-ring}`) — 3px `{colors.ring}` at 50% on `:focus-visible`, the ring `Button` already draws, now in a visible hue.
- **Timeline axis** (`{components.timeline-axis}`) — mono-xs labels in muted, 1px gridlines in border, a cursor line under the pointer.
- **LOD card** (`{components.lod-card}`) — the evidence-tier card on the timeline: 160px screenshot at left, `{typography.body-sm}` excerpt, artifact kind chips, `{typography.mono-xs}` anchor `12:40 · Retrieval bake-off review`.

Everything not listed is a shadcn default (`Button` variants and sizes as in `components/ui/button.tsx`, inputs, `details/summary` disclosures, popovers) and is not customized.

## Do's and Don'ts

| Do | Don't |
|---|---|
| Spend chroma only on kind, state, health, thread, reason | Color a heading, a card, a button, or a border for emphasis |
| Pair every hue with its second carrier — glyph, texture, word, `#name` | Ship a chip without its glyph or a dot without its word |
| Keep the `stageStyles.ts` state values byte-identical | Introduce a fourth "warning" hue or a second green |
| Put a served value in monospace, a sentence in Geist | Set transcript prose in mono because it "looks technical" |
| Write the count into the header: `Moments 24` | Write `Moments` and bury the count |
| Show a failure as a refusal box in place with rule and remediation | Toast it, or word it without the rule's name |
| Frame every screenshot 16:9 with its offset chip | Crop screenshots to fit, or show a placeholder illustration |
| Keep the base achromatic and dark; apply `.dark` once at the root | Tint the base, or leave the app rendering light |
| Assign thread hues by stable hash and always print the name | Assign hues by list position, or identify a thread by color alone |
| Measure a new text-on-surface pair before using it and add it to the table | Assume a Tailwind shade "is probably AA" |
