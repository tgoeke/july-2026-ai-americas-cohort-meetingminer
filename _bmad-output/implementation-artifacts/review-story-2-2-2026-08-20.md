# Code review — Story 2.2: Moment View

**Reviewed:** `story/2-2`, `f653a3d..fe99d9c` (23 files, +3,199/−88)

**Verdict:** pass. The Epic 4 ownership decision and all five patches are resolved. The frozen Story 2.2 intent and acceptance criteria are implemented.

## Findings

1. **[medium][resolved decision] Assign the Epic 4 artifact-hydration owner.** `server/meetingminer/api/moments.py:346-375` always emits `artifacts=[]`. Story 4.1's `0009_artifacts.sql` agrees with the frozen `MomentArtifact` kind/state/title/body shape (its two current kinds are a valid subset), but Story 4.1's frozen contract also says no API/web changes because Story 2.2 owns the right-rail read. **Resolved 2026-08-20: Story 4.3 owns the moment-detail artifact query and any required rail rendering extension.** Story 4.1's stale ownership claim and Story 4.3's implementation contract must record that assignment.

2. **[medium][patch] Cross-meeting evidence can be returned from malformed internal links.** `server/meetingminer/api/moments.py:72-110` joins `moment_segment` and `transcript_segment` without requiring the segment's `meeting_id` to equal the moment's; `:91-98` joins `screenshot` by id alone. The migration permits those cross-meeting references because its foreign keys validate each endpoint independently. If a stage regression or repair creates such a link, the list preview/detail transcript or `screenshotPath` exposes another meeting's evidence. Scope the joins to the moment's meeting and add a two-meeting regression test.

3. **[low][patch] Standalone moment lists expose an enabled no-op control.** `web/src/features/moments/MeetingMoments.tsx:157-163` always renders “Open moment,” although `onOpenMoment` is optional and is absent in several legitimate component renders. The optional call silently does nothing. Render that control only when the callback exists, with a regression test.

4. **[low][patch] The generated OpenAPI contract lies for malformed moment ids.** `server/meetingminer/api/moments.py:234-248` declares only 404/409. On a malformed id the global handler actually returns RFC 9457 `application/problem+json` (covered by `server/tests/test_api_moments.py:238-243`), but OpenAPI declares FastAPI's `application/json` `HTTPValidationError`; generated client lines `web/src/client/types.gen.ts:725-728,763-766` repeat the mismatch. Declare a 422 problem response with the real media type/schema and pin the operation schema/client output.

5. **[low][patch] The repeatable-read guarantee has no regression proof.** `server/meetingminer/api/moments.py:281-290,331-337` relies on `REPEATABLE READ`, but the test suite would stay green if that isolation setting disappeared. Add a coordinated second-connection test that changes the evidence state and rows between the route's reads, and confirm it fails when the isolation setting is removed.

6. **[low][patch] Stale response suppression is unpinned in both loaders.** `web/src/features/moments/MeetingMoments.test.tsx:193-209` only proves a changed id sends another request; it never lets the aborted original resolve late, and `MomentView` has no equivalent. Resolve the first deferred request after switching ids and prove it cannot overwrite the second view; confirm each regression test fails when its abort guard is removed.

## Dismissed candidates

Seven unique candidate issues were rejected: URL/router and retry affordances are excluded by the frozen boundaries; keeping the home mounted is the explicit navigation decision; preview capping is an accepted recorded design decision; rendering artifact body is not a Story 2.2 acceptance criterion; OpenAPI's 404/409 `unknown` typing follows the established project generator pattern; and the remaining candidates were duplicates or test-wish-list variants of the findings above.

## Verification run by this review

- `cd server && .venv/bin/python -m pytest tests/test_api_moments.py -q` — 16 passed.
- `cd server && .venv/bin/python -m pytest tests/ -q` — 1102 passed, 1 pre-existing Starlette deprecation warning.
- `make web-test` — 130 passed across 9 files.
- `pnpm --dir web run lint` — passed with the documented pre-existing `src/components/ui/button.tsx` fast-refresh warning.
- `pnpm --dir web run build` — passed.
- `make client` — intentionally not run: port 8000 serves a different checkout's pre-2.2 schema, as documented by the story's existing deferred item.

## Review layers

- Blind Hunter and Edge Case Hunter supplied candidate findings.
- Verification Gap Reviewer and Acceptance Auditor reported no additional findings.

## Remediation completion — 2026-08-20

The five patches were implemented under `spec-2-2-moment-view-review-remediation.md` and independently reviewed. A post-implementation layer added three hardening changes: foreign screenshot IDs are suppressed alongside paths, both list and detail reads have deterministic snapshot regressions, and a runtime `null` navigation callback is treated as absent.

Final verification: `test_api_moments.py` 20 passed; full server suite 1106 passed; web suite 134 passed; production build passed; lint has only the pre-existing `button.tsx` fast-refresh warning. `make client` remains intentionally skipped because port 8000 serves another checkout; the client was regenerated from this branch's in-process schema with the documented localhost server entry.
