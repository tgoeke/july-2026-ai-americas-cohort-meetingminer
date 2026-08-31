# Story 6.5 Adversarial Review — Add-Meeting UI

Date: 2026-08-31

## Scope

- Review branch: `story/6-5-review`
- Source branch: `story/6-5`
- Original story range: `2d68dcc6dba31007c7d6fd84f0884edbc79508d5..d6216583cf601c925ef4ecdfae594c600be98a52`
- Required scope: the 13 additions listed in the Story 6.5 review contract
- Authority: frozen Story 6.5 intent contract, architecture decisions AD-11/AD-14/AD-18, adopted UX design, and Story 6.5 acceptance criteria

## Findings

### F1 — Probe transport Retry does not issue another probe

- **Location** — `web/src/features/acquisitions/AddMeeting.tsx:323`
- **Severity** — medium
- **Finding** — The Retry control shown after a probe transport failure clears the visible error but never reruns the probe. It assigns the current URL back to itself, so React preserves the state value and the probe effect's dependencies remain unchanged.
- **Evidence** — The handler clears `probeOwner.current.key`, sets `probeState` to `idle`, and calls `setUrl((current) => current)` at lines 323–328. The effect is keyed only by URL classification and normalized URL at line 143. Changing `probeState` therefore rerenders without re-entering the effect. This violates the frozen matrix's probe-transport row, which requires Retry, and leaves Submit disabled at `Waiting for the pre-flight check.` until the user edits the URL manually.
- **Suggested direction** — Give Retry an explicit dependency/generation that reruns the current normalized probe, and add a regression test that observes a second request and a successful answer after the first transport failure.
- **Disposition** — patchable; remediation in progress.

## Disposition

Review in progress. No pass/fail verdict has been assigned.

## Verification

Not run yet.
