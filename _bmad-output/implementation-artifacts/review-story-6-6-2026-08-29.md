# Code Review: Story 6.6 — YouTube Deep Links

## Scope

- Repository: `meetingminer`
- Review branch: `story/6-6-review`
- Source branch: `story/6-6`
- Reviewed range: `d8a279f8882d24beef8b99c4c5db00d45b057bcd..f5c49180ea058dbaf58e20914d8feb593d98e0d3`
- Review mode: full, against `spec-6-6-youtube-deep-links.md`
- Review method: unchunked adversarial review using blind-hunter, edge-case-hunter, verification-gap, and acceptance-auditor layers.

## Findings

### 1. Unsafe source addresses disappear when replay exists

- **Source:** acceptance-auditor
- **Location:** `web/src/lib/affordance.ts:145-151`
- **Severity:** low
- **Route:** patch
- **Finding:** The replay branch calls `sourceLinkOf`, but collapses both a refused unsafe URL and an absent/non-YouTube source to `source: null`. The Story 6.6 I/O matrix explicitly requires an unsafe scheme in either replay state to render as the existing inert `*-unsafe-link` text, never an anchor.
- **Evidence:** `affordanceOf({hasRecording: true, sourceDeepLink: 'javascript:x'})` returns `{kind: 'replay', source: null}` and `affordance.test.ts:138-142` pins that contradictory result. MomentView and CorpusSearch only render inert text for `kind === 'inertLink'`; MeetingMoments' recorded row controls likewise accept only a safe YouTube source.
- **Concrete failure:** A recorded item whose provenance contains an unsafe or malformed address keeps Replay but silently hides the rejected source value, so the user cannot see that source provenance existed and was deliberately refused.
- **Required outcome:** Preserve Replay as the primary affordance while representing and rendering the refused address as inert text after it on recorded MomentView, search-hit, and drill-down rows. It must never become an `href`. Add regressions that fail against the reviewed code and prove the replay control and inert warning coexist.
- **Resolution:** Patched in `eef842d` on `story/6-6-review`. The replay state now carries `inertSource` separately from the safe YouTube `source`; all three replay-capable surfaces render it after Replay as text, and new regressions cover the shared decision plus MomentView, search, and both drill-down row kinds.

## Dismissed candidates

Twenty-one normalized candidates were dismissed:

- Meeting-scoped timestamps, untimed Shorts/embed/live paths, exact `#t=` fragment handling, browser query reserialization, and the `Open in Stream` label are explicit contract decisions.
- `/watch/`, `/WATCH`, trailing-slash short links, missing video IDs, alternative time parameters, and timing Shorts/embed/live would add normalization or video validation the contract expressly excludes; the prior triage log records these decisions.
- Trailing-dot DNS hosts and astronomically large offsets are not emitted by the validated ingestion path and have no meaningful main-consumer consequence.
- The new-tab accessible name and hidden glyph exactly follow the accessibility contract.
- Repository-wide call-site inspection found no unconverted consumer of the changed `Affordance` union.
- A recorded drill-down with no screenshot or transcript rows is outside the row-scoped acceptance criterion; the empty chat control wrapper is inert layout markup.
- The proposed HTTP/subdomain, unsupported-path-with-replay, and callback-free chat tests would add defense in depth, but existing helper, component, typecheck, and surface tests already compose those branches; the suggested mutations do not expose a current implementation defect or an unmet verification command.

## Verification

- Targeted regressions: 4 test files, 133 tests passed.
- Full web suite: `make web-test` — 16 test files, 291 tests passed.
- Production build: `pnpm --dir web run build` — exit 0 (`✓ built`).
- Lint: `pnpm --dir web run lint` — 0 errors; four pre-existing `react(only-export-components)` warnings in untouched files.
- Original patch commit: `eef842d` on `story/6-6-review`, pushed to `origin/story/6-6-review`.
- Rebased integration commits: `a5b851c` (feature), `51d4182` (first review remediation), `28ea43d` (follow-up remediation) on `story/6-6-review-integrate`.
- Exact integration history was reverified with the same results, then fast-forwarded and pushed to `main` at `28ea43d4fba4510278c524e730d86c944a781181`.

## Verdict

**Passes after remediation and is integrated.** The one low contract violation is fixed and regression-tested. No must-fix finding remains; the previously documented medium server-side data-retention gap remains deliberately deferred and does not block the web-only story. `main` and `origin/main` both point to `28ea43d4fba4510278c524e730d86c944a781181`.
