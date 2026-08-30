---
title: 'Code Review: Story 2.3 — Meeting Drill-Down with Screenshot Series'
date: '2026-08-20'
review_range: 'c61e9175f6f5d532520ecfd9c72dbd629d0614ed..80cb6cc'
branch: 'story/2-3'
verdict: 'needs-fixes'
findings: {medium: 1, low: 3, high: 0}
---

# Code Review — Story 2.3

## Verdict

Needs fixes before merge. No high-severity defects were found; the covered-segment interaction misses an explicit acceptance criterion, and three low-severity contract/regression gaps remain.

## Findings

### 1. Covered transcript text is not the moment affordance

- Severity: medium
- Location: `web/src/features/moments/MeetingMoments.tsx:400`
- Sources: blind-hunter

The transcript `<li>` renders its text inert and exposes a separate `Open moment` button at line 410. The frozen contract requires that clicking a covered segment opens its moment, and the execution task says the segment click opens `momentId`; only clicking the auxiliary control currently calls `onOpenMoment`.

Make the covered segment/text an accessible moment affordance without nesting it around the replay button, and add a test that clicks the text/segment itself. The present test only clicks the separate button, so it passes while the required interaction is absent.

### 2. Unicode folding suppresses unrelated valid highlights

- Severity: low
- Location: `web/src/features/moments/moments.ts:119`
- Sources: blind-hunter

`highlightRuns` abandons highlighting for an entire segment whenever any case fold changes its string length. Thus `İpek discussed the contract` cannot highlight a search for `contract`, even though that match is unambiguous and unrelated to the expanding `İ` fold. This conflicts with the requirement to mark every case-insensitive occurrence.

Use index mapping or another Unicode-safe approach that preserves slices from the original text, then add a mixed case-fold regression test. Confirm the test fails against the current fallback before treating it as coverage.

### 3. One SDK mock factory omits `getMeetingDrilldown`

- Severity: low
- Location: `web/src/features/meetings/useJobEvents.test.tsx:8`
- Sources: blind-hunter + acceptance-auditor

The `useJobEvents` factory still mocks only its older operation subset. The story explicitly requires every `@/client/sdk.gen` mock factory to include the regenerated operation; this one is omitted, so future imports can fail with a misleading missing-export error instead of being covered by the factory-completeness convention.

Add `getMeetingDrilldown: vi.fn()` to this factory and keep the suite green.

### 4. `classificationTags` has no non-empty fidelity test

- Severity: low
- Location: `server/tests/test_api_moments.py:564`
- Sources: blind-hunter + verification-gap

The new response field is asserted only as `[]`. Replacing `classification_tags=list(row[7] or ())` with `[]`, or selecting the wrong source, leaves the server and web suites green. The generated client exposes the field, so the route must prove that stored non-empty tags survive exactly and in order.

Seed or update a screenshot with multiple tags and assert the returned `classificationTags`; the new test must be demonstrated to fail against the unfixed code.

## Verified Clean

- Focused server contract suite: `cd server && .venv/bin/python -m pytest tests/test_domain_jobs.py tests/test_api_moments.py -q` — 47 passed.
- Web suite: `make web-test` — 156 passed across 9 files.
- Web lint: only the acknowledged pre-existing `src/components/ui/button.tsx` fast-refresh warning.
- Web production build: `pnpm --dir web run build` completed successfully.
- The new read stays on the existing moments router, executes its header/gate/payload reads under `REPEATABLE READ`, and keeps cross-meeting guards on the new moment joins.

## Triage

- Patch: 4 (1 medium, 3 low)
- Deferred: 0
- Dismissed as noise, already handled, or contrary to a documented design decision: 10

## Remediation Outcome

All four patch findings were completed in `c7e33a6`, with a follow-up Unicode and accessibility correction in `56bda3c`. The final verification pass was clean: focused API tests (36), web tests (157), production build, and the full server suite (1,190); lint retains only the pre-existing `button.tsx` warning.
