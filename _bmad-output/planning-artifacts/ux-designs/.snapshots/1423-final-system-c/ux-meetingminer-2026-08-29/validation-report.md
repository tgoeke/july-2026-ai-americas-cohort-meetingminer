# Validation Report — meetingminer

- **DESIGN.md:** `_bmad-output/planning-artifacts/ux-designs/ux-meetingminer-2026-08-29/DESIGN.md`
- **EXPERIENCE.md:** `_bmad-output/planning-artifacts/ux-designs/ux-meetingminer-2026-08-29/EXPERIENCE.md`
- **Run at:** 2026-08-29T13:55 (local)
- **Lenses:** rubric walker (`review-rubric.md`), accessibility (`review-accessibility.md`), editorial structure + prose (`review-editorial.md`)
- **Mode:** headless Finalize gate; every finding below carries its resolution in the spines, or the reason it was not taken.

> **Post-gate change (2026-08-29):** the owner chose color system **C · Ember & Ink** after this report was synthesized. `DESIGN.md`'s token block, prose, and contrast table were regenerated for C and re-measured by the same script — 116 pairs, 49 AAA, 14 AA, 53 non-text ≥ 3.0, none failing (the count fell from 134 because the thread palette is eight hues, not twelve). The mockups were re-skinned to C. Everything else in this report stands.

## Overall verdict

The rubric walker read the pair as a usable contract for seven of nine consumer stories — every dotted token reference resolves, the contrast summary matches its table row for row, the component name map holds across both files, all seven UX-DR clauses map to real sections, and six Key Flows carry verbatim strings, calls, climaxes, and failure paths — with two consumers unable to source-extract: story 6.5a (file tabs) and story 10.2a (thread curation), both created by Sprint Change Proposal Addendum 3 after the drafts were written. Both gaps are now closed: an `upload` stepper stage, Drop zone / File row / Dialect select / Split panel components, eleven new state rows, and Flows 7 and 8.

The accessibility lens shifted the picture more than the rubric did: the 97 measured pairs were accurate, but the focus ring as drawn (50% alpha) was 2.60:1, five alpha composites the screens rely on fell under 3:1, page-scoped single-key shortcuts failed WCAG 2.1.4, the solid states had no texture, and reflow was excluded while AA was claimed. All of it was resolved inside the token system (two-tone ring, `control-border`, textures for the solid group, a 0.60 density floor, a shortcuts toggle, grid semantics and focus transfer on the timeline, alt and captions rules) and the one thing the design cannot meet on a desktop-only surface — 1.4.10 reflow and 1.4.4 above 150% — is now stated as an owner deviation rather than claimed. The editorial lens found six table rows split by unescaped pipes inside code spans, three contradictions (health dot, Enter semantics, viewport), and a set of naming and voice issues; all applied except three rows rejected on shape grounds.

## Category verdicts

- Flow coverage — adequate → strong after Flows 7 and 8
- Token completeness — strong
- Component coverage — adequate → strong after the 6.5a and 10.2a components
- State coverage — adequate → strong after the eleven added rows
- Visual reference coverage — adequate (mocks lag closed in the final promotion; `.working/key-*` duplicates retired)
- Bloat & overspecification — adequate
- Inheritance discipline — adequate (glossary gap recorded as F-25 for the owner)
- Shape fit — strong

## Findings by severity

### Critical (3 — all from the accessibility lens; all resolved)

**[Accessibility]** — Focus ring at 50% alpha is 2.60:1, invisible on bands (DESIGN.md · Components · Focus ring)
Composited ring over page = 2.60:1; over `thread-9-band` = 1.09:1.
Fix: two-tone ring — 2px `{colors.ring}` at 100% outside a 1px `{colors.background}` gap; pairs `ring / card` 6.73 and `background gap / ring` 7.44 added to the table; `button.tsx` change recorded as F-23. **Resolved.**

**[Accessibility]** — Single-key shortcuts fail WCAG 2.1.4 (EXPERIENCE.md · Interaction Primitives)
"Never inside a text field" is not one of the three permitted mechanisms.
Fix: a **Single-key shortcuts** toggle on Settings (default on, `localStorage`), speaker-list arrows scoped to the roving group, timeline keys exempt under the focus rule. **Resolved.**

**[Accessibility]** — Reflow and resize excluded while AA claimed (EXPERIENCE.md · Accessibility Floor)
1.4.4 at 200% and 1.4.10 at 320px are not met by a desktop-only design.
Fix: the floor now states both as deviations by owner decision; F-21 asks the owner to keep or fund a narrow layout. **Resolved as a stated deviation.**

### High (7 — resolved)

**[Rubric]** — Story 6.5a has no Key Flow and the stepper has no upload stage → Flow 7, `upload` bar with `<sent> / <total>`, Uploading / Upload refused / Polling lost states. **Resolved.**
**[Rubric]** — 6.5a components absent from both spines → Drop zone, File row, Dialect select entries and rows; traceability rows. **Resolved.**
**[Accessibility]** — Solid states share hue only (done vs failed 1.24:1) and bars are `aria-hidden` → failed notch + ✕, unknown dotted, running reduced-motion top edge; bars `role="img"` named `<stage> <state>`. **Resolved.**
**[Accessibility]** — Five composites below threshold (queued word 3.30, queued bar 2.11, beyond-palette 1.88, density 0.30/0.50, lap-2 names 3.50, on-band labels over hatch) → queued word 100%, bar 60%, beyond 60%, density floor 0.60 (0.55 still failed four hues), names in lap-1 hue with a lap swatch, labels only on full-alpha bands; 37 rows added to the table. **Resolved.**
**[Accessibility]** — Timeline focus lost on tier change; roving model unbuildable → `role="grid"`, cells per tier, focus transfer rule (same `x`; Enter → first child, Backspace → parent), LOD card inner tab stops, tier in the grid's name. **Resolved.**
**[Accessibility]** — No alt text or captions → `alt = <viewType> at <offset>, <meetingTitle>`; client-generated WebVTT captions track from `/drilldown`; F-22. **Resolved.**
**[Accessibility]** — Timeline targets under 24px and overlapping → ≥ 24×24 hit areas, clustering (`3 moments, 12:40–12:52`), 24px bands, strips not targets. **Resolved.**

### Medium (26 — 24 resolved, 2 recorded)

Rubric: 10.2a flow/states/Split panel (→ Flow 8, four states, component); Add-meeting upload / polling-lost states (→ added); Threads search-no-match / unknown-id / curation states (→ added); `threads-bands.html` one revision behind (→ re-rendered: 24px, grid name, layout defect fixed); Add-meeting mocks missing probe and `exists` states (→ re-rendered); glossary claim (→ reworded; F-25 for the owner); `status: draft` while handed off (→ `final` at close).
Accessibility: control borders 1.25:1 (→ `control-border` token, F-24); refusal boxes not announced (→ `role="alert"`); no non-drag pointer path (→ control cluster); font glyphs unreliable (→ inline SVG sprite, checkbox/bookmark pair); expanded-card focus (→ `aria-expanded`, focus return); chip toggle state and height (→ `aria-pressed`, 3px padding); log tail auto-scroll (→ pin-to-bottom); speaker keys and Enter (→ scoped list, one Enter rule); model-select semantics (→ listbox, groups, `aria-selected`, remediation as description); thread-hue rule contradiction (→ first-mention ordinal, merge/split rule).
Editorial: the six pipe-split table rows (→ escaped); health-dot contradiction (→ never alone, remediation rule); Enter semantics (→ one rule); viewport stated four times (→ DESIGN.md owns it, `thread-list-width-narrow` token); model-select schema vs examples (→ binding model id); remediation string mismatch (→ unified); glossary terms undefined (→ defined inline); `roles` ambiguity (→ user accounts); Surface closure paragraph (→ cut); reasons sentence (→ rewritten); component name map (→ Health dot row, closing sentence); LOD card / Moments naming (→ unified); remediation subsets (→ one rule); brace disambiguation (→ preamble); Source column enum (→ normalized); `24-hue` string (→ corrected); duplicate example tag (→ `SPEAKER_00`); half-open intervals (→ stated); Add-meeting rule (→ stated in Voice and Tone); display/stat overrides (→ `brand`, `stat-sm` tokens); `p` shortcut (→ listed); editorial voice in Semantic Zoom (→ mechanism stated).

### Low (39 — 31 applied, 8 noted)

Applied: `=`/`-` aliases; `Show 24 more` focus and announcement; bucket tooltip on focus; label 11px; one live region per list; card image link named by title; offset-chip Don't; health control min-height; Flow 2 `Alternate outcome`; distinct meeting id `2b7e…`; UX-DR12 row names drill-down; templated-token expansion rule; `state-queued-bar` hex; `rounded.xl` used by the drop zone; Meeting card named as existing; Speaker naming cold load and rerun failed; Moments end of feed and replay failed; `ui-3`/`ui-4` cited as spec-ui-reimagine stories; "spines win" reduced to the two preambles; chrome height and screenshot width cited by token; State Patterns restatements trimmed; American spelling; `1–3`; ISO datetime in the rerun sentence; duration rule both forms; wheel axis; `rerun · queued` mapping; density rule in fewer places; mock comments corrected; `.working/key-*` retired at close.
Noted, not applied: rubric row on Key Flow payoff sentences (the skill's flow shape asks for a climax beat); editorial rows 12, 26, 27 (flow shape; machine-read table suffixes; the B/C one-liners help the owner swap); unused spacing steps (kept as the named scale); `updated:` timestamp granularity (the memlog carries the minute-level chronology); the `.working/screens/` jpegs (verification evidence, referenced from the memlog).

## Reviewer files
- `review-rubric.md`
- `review-accessibility.md`
- `review-editorial.md`
