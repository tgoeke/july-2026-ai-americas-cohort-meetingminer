---
story: "6.1"
reviewed_branch: story/6-1
reviewed_head: e5510c7caf385720851b199382b62aa1221f4051
review_baseline: full-content artifact review
review_snapshot: _bmad-output/planning-artifacts/ux-designs/.snapshots/1423-final-system-c/ux-meetingminer-2026-08-29
reviewer_branch: story/6-1-review
date: 2026-08-29
status: action-required
verdict: changes-requested
---

# Story 6.1 Code Review

## Verdict

Changes requested. The design spines are substantial and mechanically sound, but Story 6.1 does not yet satisfy the acceptance requirement that every designed element be backed by an existing API field or a named future story. Five owner decisions and nine bounded document/mockup patches remain. The story branch must not merge yet.

The four required review layers completed successfully: blind adversarial review, edge-case review, verification-gap review, and acceptance audit. They produced 60 raw observations, normalized to 39 unique candidates. Fourteen are retained below; 25 were dismissed as duplicates, contradicted by the artifacts, speculative implementation advice, or already covered by a stronger retained finding.

## Scope and cutoff

- Reviewed story branch: `story/6-1` at `e5510c7caf385720851b199382b62aa1221f4051`.
- The branch has no meaningful Git diff because the UX workspace is ignored. Review therefore used the complete promoted artifact set, not a commit range.
- Immutable review cutoff: `.snapshots/1423-final-system-c/ux-meetingminer-2026-08-29`.
- Cutoff aggregate SHA-256, excluding `.snapshots-tmp`: `5b6ef1afec911eaf47b71bbfe6bee2ed2f25f7f425356927dace76cb7f9efffd`.
- Spine SHA-256: `DESIGN.md` `1f1321a22c40f61b5645eb667ebcff466974471ce8986daa7edd2d3dfac65e68`; `EXPERIENCE.md` `ff4890ff528e74f1a0c8dc21555b685984d90aa800564707c2c10f28b53b027a`.

## Verification performed

- Both spine frontmatters parse as YAML and declare `status: final`.
- The System C `colors` block contains 76 hex values.
- The contrast table contains 116 measured rows: 49 AAA, 14 AA, and 53 non-text pairs at or above 3.0:1; no row declares a failure.
- All seven promoted HTML mockups open in headless Chromium.
- A reference scan found no simple missing internal section target in `EXPERIENCE.md`.
- No repository test suite was run because this story delivers ignored UX documents and standalone HTML mockups, not application code.

## Owner decisions required

### D1 — Contract ownership for designed data and endpoints

**Severity:** High
**Root cause:** specification
**Route:** `decision_needed`

The traceability claim in Story 6.1 requires every element to map to an existing field or a named future story, but the design still labels material contracts as assumptions or open findings: feed item/reason/paging fields (F-3), thread/evidence fields (F-5), the acquisition probe endpoint (F-6), named refusal and `exists` outcomes (F-7/F-8), upload metadata (F-9), provider/binding fields (F-14), provenance, and risk/question kinds (F-4). The source stories do not yet own all of these shapes.

**Decision:** either amend the named source stories to own the proposed contracts, simplify the UX to contracts already owned, or decide each contract separately. Until then, the “every element backed” acceptance criterion is knowingly unmet.

**Owner resolution — 2026-08-29:** Amend the named source stories. The proposed UX contracts remain in scope; remediation must add the fields, result shapes, problem types, and endpoints to the stories that own their implementation. No contract may remain traceable only through an assumption tag.

### D2 — Stable thread-color identity

**Severity:** High
**Root cause:** specification
**Route:** `decision_needed`

`DESIGN.md` derives thread hue from a client-computed first-mention ordinal while promising colors never change or get reused. Sorting by `firstMentionAt` and `threadId` cannot preserve that promise after imports, merges, or splits, and `EXPERIENCE.md` maps no persisted color ordinal.

**Decision:** persist an immutable ordinal, use a stable identifier hash and weaken ordinal language, or explicitly weaken the non-recoloring promise.

**Owner resolution — 2026-08-29:** Persist an immutable `colorOrdinal` on each thread as part of the Story 10.3 contract. Assign it once and never recycle it within the corpus. A new thread created by a split receives a new ordinal; the surviving thread in a merge retains its ordinal. The client maps the persisted ordinal through the eight-hue, two-lap palette and uses grey beyond ordinal 16.

### D3 — Absolute timeline placement

**Severity:** High
**Root cause:** specification
**Route:** `decision_needed`

The multi-meeting timeline is described in wall-clock time, but mapped moment evidence supplies relative `startMs` only. The design does not define the meeting anchor/time zone or a deterministic fallback, so cross-meeting placement cannot be implemented consistently.

**Decision:** expose an absolute evidence timestamp, define placement as `meeting.startedAt + startMs` with time-zone rules, or redesign the axis to avoid absolute placement.

### D4 — WCAG resize/reflow exception

**Severity:** High
**Root cause:** product decision
**Route:** `decision_needed`

`EXPERIENCE.md` records desktop-only deviations from WCAG 1.4.4 above 150% and 1.4.10, while F-21 still asks whether to keep the deviation or fund a narrow layout. The validation report describes the item as resolved even though the owner decision remains open.

**Decision:** accept and clearly scope the exception, or require a narrow/reflow layout and update the component and flow specifications.

### D5 — Versioning the design of record

**Severity:** High
**Root cause:** repository policy
**Route:** `decision_needed`

The design workspace and snapshots are ignored, yet `adoption.md` directs builders to cite this dated path as the design of record. The artifact changed materially during review and has no reviewable Git history. A local snapshot helps this review but does not make the specification available to other clones or future builders.

**Decision:** un-ignore and version the promoted design workspace, or promote the canonical spines/mockups into a tracked documentation path with an explicit update policy.

## Patches required after decisions

### P1 — Finish the System C promotion and repair stale validation evidence

**Severity:** High
**Route:** `patch`

The promoted set contradicts its System C declaration:

- `DESIGN.md` retains both “A picked” and the later C owner decision.
- `.working/README.md` likewise names A and C as the pick.
- `mockups/threads-bands.html` and `mockups/threads-moments.html` retain thread 9–12 variables despite the canonical eight-hue/lap-two scheme.
- Multiple mockups retain the rejected A-blue focus color `rgba(75,163,247,.5)`.
- Some mockups use `#1C0D06` for a C surface where the canonical card/popover value is `#1B1715`.
- `validation-report.html` still states the A-era 84-token/134-pair result in its detailed verification sections despite the appended C note.
- The screenshot evidence does not cover all seven promoted mockups under System C.

Regenerate the detailed validation text, normalize all mockup tokens and thread variables, and capture evidence for every promoted mockup from the final files.

### P2 — Make the System C color rules internally consistent

**Severity:** Medium
**Route:** `patch`

`DESIGN.md` says the seven kinds occupy “three hue families” but lists four: records, actions, backlog, and corrections. It also says color has exactly five meanings and refuses a sixth while System C adds ember as brand/action/focus, and a do/don’t example says not to color the button although the canonical primary button is ember. Two prose contrast values (7.44 and 5.50) are stale against the C table (8.72 and 5.42). Reconcile the taxonomy and replace stale examples and ratios.

### P3 — Make the add-meeting flows obey the probe state machine

**Severity:** High
**Route:** `patch`

The component states require a pre-submit URL probe, but Key Flow 1 enables/submits after shape validation and Key Flow 2 sends a long URL directly into refusal handling. Once D1 resolves the endpoint, route both flows through idle/debouncing/probing/supported-or-refused states and define how probe results gate submission.

### P4 — Replace path-addressed media with ID-addressed media

**Severity:** High
**Route:** `patch`

`EXPERIENCE.md` maps `screenshotPath` to `GET /media/{path}`, conflicting with architecture AD-17’s ID-only media boundary. Map screenshot/replay affordances to an opaque media/evidence identifier and an ID-addressed endpoint, then update F-3 and affected mockup annotations.

### P5 — Specify safe source deep-link construction

**Severity:** Medium
**Route:** `patch`

The design appends `&t=` to `sourceDeepLink`. That fails for URLs without a query string and can duplicate an existing time parameter. Require URL parsing and replacement/insertion of the provider-specific time parameter, with an unavailable-link fallback.

### P6 — Make feed-reason rendering total

**Severity:** Medium
**Route:** `patch`

F-3 includes a `due` reason that has no matching token/glyph, and the renderer permits an empty `reasons` array even though UX-DR17 requires a stated reason for every item. Add the missing branch and specify whether an empty/unknown reason causes item omission, an explicit “reason unavailable” state, or a contract error.

### P7 — Replace the obsolete model-selection mock interaction

**Severity:** Medium
**Route:** `patch`

`mockups/ask-box-model-select.html` presents a radio group and tells the user to edit configuration and restart, contradicting the final experience specification’s persisted `PUT` selector. Rebuild the promoted mockup around the final interaction, including save, failure, and restored-selection behavior.

### P8 — Define stale-response handling for asynchronous controls

**Severity:** Medium
**Route:** `patch`

The probe, timeline zoom/fetch, and rapid model-selection interactions can resolve out of order. Add a shared invariant that superseded work is aborted when possible and that responses are applied only when their request generation/key still matches current UI state.

### P9 — Repair mockup accessibility semantics and target sizes

**Severity:** Medium
**Route:** `patch`

The thread mockups declare `role="grid"` without the required row/gridcell hierarchy; add-meeting progress bars are hidden from assistive technology despite the spine requiring announced progress; and file-removal controls are 22×22 rather than the documented 24×24 minimum. Align the promoted HTML with the Accessibility Floor and rerun the focused checks.

## Dismissed observations

Twenty-five normalized candidates were dismissed. The main dismissal reasons were duplicate manifestations of the retained System C or contract findings; unsupported assumptions about diarization, clustering, paging implementation, or replay internals; implementation-level preferences not required by the story; and claims disproved by the final spines. Dismissal does not certify future implementation behavior beyond Story 6.1’s design scope.

## Required re-verification

After the owner decisions and patches:

1. Re-run all four review layers against one immutable final snapshot.
2. Parse both frontmatters and the complete color block.
3. Recompute every contrast pair from canonical tokens.
4. Validate all traceability rows against the amended source stories and architecture decisions.
5. Open and interact with all seven promoted mockups in Chromium; verify console output, keyboard order, roles, accessible names, target sizes, and asynchronous states.
6. Confirm the Markdown and HTML validation reports contain the same System C counts and conclusions with no superseded A-era claims.
7. Commit and push the versioned design-of-record artifacts if D5 selects repository versioning.
