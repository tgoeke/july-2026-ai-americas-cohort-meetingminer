---
title: 'Story 2.3 Review Remediation: Drill-Down Interaction and Contract Pins'
type: 'bugfix'
created: '2026-08-20'
status: 'done'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/review-story-2-3-2026-08-20.md'
baseline_revision: '1ccadd1c3c0bde227bf2f585a20390336592e386'
baseline_commit: '5d62afaff4c77072bb1c81d44fd74c3d73e63106'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The completed Story 2.3 drill-down misses one specified interaction — its covered transcript text is not itself a moment link — and has three small test/Unicode hardening gaps that can conceal future payload or highlighting regressions.

**Approach:** Make covered transcript text the accessible moment affordance, retain independent replay controls, make highlighting robust when a length-changing Unicode case fold precedes an otherwise valid match, and complete the missing contract pins.

## Boundaries & Constraints

**Always:** Keep the drill-down read-only; preserve a single inline replay and do not make replay clicks navigate; preserve original transcript text and casing in `SnippetRunModel`; retain the generated client untouched; keep the new tests additive and prove their target behavior against the unfixed implementation.

**Ask First:** None.

**Never:** Do not change API payload shapes, OpenAPI error-extension typing, screenshot-series layout, replay seek behavior, source-link behavior, migrations, or the documented unbounded-payload/caching deferrals.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|---------------|----------------------------|----------------|
| Covered segment navigation | Covered transcript segment with a callable `onOpenMoment` | Clicking its text opens exactly its `momentId`; its Replay button does not navigate | Uncovered segment stays non-navigable |
| Unicode highlight | `İpek discussed the contract`, term `contract` | The original prefix stays plain and `contract` is one highlighted run | No text corruption or surrogate splitting |
| Screenshot tags | Stored ordered non-empty `classification_tags` | Drill-down returns the same ordered camelCase array | No error expected |

</frozen-after-approval>

## Code Map

- `web/src/features/moments/MeetingMoments.tsx:166-209,395-416` — transcript region layout; reuse the screenshot's real-button affordance but make text and replay sibling controls.
- `web/src/features/moments/MeetingMoments.test.tsx:201-298` — existing covered-segment navigation and replay tests; extend them to exercise text click without replay bubbling.
- `web/src/features/moments/moments.ts:119-143` — pure `highlightRuns`; current lowercase-index length guard loses valid later matches.
- `web/src/features/moments/moments.test.ts:129-179` — helper truth table, including the current length-changing-fold fallback test to replace.
- `web/src/features/meetings/useJobEvents.test.tsx:6-14` — the sole SDK mock factory that omits `getMeetingDrilldown`.
- `server/meetingminer/api/moments.py:149-160,587-600` — route selects and serializes `classification_tags` in screenshot ordinal order; read-only and unchanged by this remediation.
- `server/tests/test_api_moments.py:516-587` — drill-down happy path, appropriate place to store ordered tags and assert payload fidelity.

## Tasks & Acceptance

**Execution:**

- [x] `web/src/features/moments/MeetingMoments.tsx` and `MeetingMoments.test.tsx` — replace the separate covered-segment Open control with a button around only the transcript text, calling its `momentId`; retain replay as a sibling button and test both interactions.
- [x] `web/src/features/moments/moments.ts` and `moments.test.ts` — replace the whole-segment Unicode length fallback with a folded-index mapping that returns original-text runs; test a length-changing fold before an unrelated ordinary match and confirm the test fails on the prior implementation.
- [x] `web/src/features/meetings/useJobEvents.test.tsx` — add `getMeetingDrilldown` to the SDK mock factory, matching the project's complete-factory convention.
- [x] `server/tests/test_api_moments.py` — set a screenshot's `classification_tags` to multiple ordered strings and assert the exact drill-down result; confirm the assertion fails when the route emits an empty array.

**Acceptance Criteria:**

- Given a covered transcript segment, when its displayed text is clicked, then the meeting view opens that segment's moment and replay remains an independent control.
- Given a segment containing a length-changing Unicode case fold before an ASCII match, when the ASCII term is typed, then that occurrence is wrapped in `<mark>` without changing displayed text.
- Given the client test suite, when SDK modules are mocked, then every factory declares `getMeetingDrilldown`.
- Given non-empty ordered screenshot tags, when drill-down is requested, then `classificationTags` returns those same values in order.

## Spec Change Log

## Design Notes

The transcript affordance cannot make the whole `<li>` clickable because its replay control is interactive. A text-only button keeps the controls siblings and avoids click bubbling. Highlighting must map folded search coordinates back to source boundaries before slicing; a global fallback is safe from corruption but fails the user-visible search contract.

## Verification

**Commands:**
- `cd server && .venv/bin/python -m pytest tests/test_api_moments.py -q` — expected: drill-down API coverage green, including non-empty tags.
- `make web-test` — expected: all component/helper suites green, including text navigation, replay independence, and Unicode highlighting.
- `pnpm --dir web run lint` — expected: no new warnings beyond `button.tsx` fast-refresh.
- `pnpm --dir web run build` — expected: TypeScript and Vite build clean.

## Suggested Review Order

**Unicode-safe highlighting**

- Preserve whole-string lowercase behavior while slicing only original-text boundaries.
  [`moments.ts:119`](../../web/src/features/moments/moments.ts#L119)

- Pin expanding and context-sensitive folds before reviewing broader component behavior.
  [`moments.test.ts:172`](../../web/src/features/moments/moments.test.ts#L172)

**Transcript interaction**

- Make the covered text the accessible moment action while replay stays a sibling.
  [`MeetingMoments.tsx:400`](../../web/src/features/moments/MeetingMoments.tsx#L400)

- Exercise text navigation, accessible naming, and replay independence together.
  [`MeetingMoments.test.tsx:201`](../../web/src/features/moments/MeetingMoments.test.tsx#L201)

**Contract regression pins**

- Complete the generated SDK mock factory convention.
  [`useJobEvents.test.tsx:6`](../../web/src/features/meetings/useJobEvents.test.tsx#L6)

- Assert ordered non-empty screenshot tags survive the drill-down response.
  [`test_api_moments.py:516`](../../server/tests/test_api_moments.py#L516)
