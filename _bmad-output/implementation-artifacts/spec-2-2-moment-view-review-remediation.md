---
title: 'Story 2.2: Moment View Review Remediation'
type: 'bugfix'
created: '2026-08-20'
status: 'done'
baseline_commit: 'a2aba5021ef60f6f8328fc2f7399d71bf78b5db8'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/spec-2-2-moment-view.md'
  - '{project-root}/_bmad-output/implementation-artifacts/review-story-2-2-2026-08-20.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Story 2.2 review found defensive-read, generated-contract, and regression-coverage gaps. Malformed internal evidence links can cross meeting boundaries, malformed UUID documentation promises FastAPI's body rather than the RFC 9457 body actually emitted, the list offers a no-op control outside the shell, and the new snapshot/abort safeguards are unpinned.

**Approach:** Harden the existing moment readers and list, then add deterministic server and web regressions. Preserve the frozen Moment View payload and navigation behavior; this remediation does not add Epic 4 artifact hydration, which is assigned to Story 4.3.

## Boundaries & Constraints

**Always:** Keep API reads SELECT-only and store-free; preserve camelCase wire fields and the existing 404/409 semantics. Constrain transcript and screenshot reads to the requested moment's meeting without a migration. The 422 OpenAPI response must describe only the media type the global handler emits (`application/problem+json`) and reference `ProblemDetails`. Regenerate—not hand-edit—the TypeScript client from this branch's in-process OpenAPI schema. Late, aborted SDK promises must not replace the newer route state.

**Ask First:** A schema migration, a new artifact query, router/URL changes, or a change to the frozen `MomentArtifact` shape.

**Never:** Do not change pipeline writers, evidence-stage semantics, media containment behavior, `ReplayPlayer`, or the two existing deferred client-generation/load-hook items.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|---------------|----------------------------|----------------|
| Cross-meeting link | A moment references another meeting's screenshot or transcript segment through individually valid FKs | Detail omits the foreign screenshot path and transcript; list preview omits foreign text | No cross-meeting evidence leaves the route |
| Malformed moment/meeting id | Non-UUID route parameter | Runtime and OpenAPI both describe RFC 9457 `ProblemDetails` under `application/problem+json` | 422 `invalid-request` |
| Standalone list | `MeetingMoments` has no `onOpenMoment` callback | Rows remain readable; no enabled “Open moment” no-op renders | No dead affordance |
| Late old response | First SDK request resolves after the id changes and its signal was aborted | Newer list/detail remains rendered | Old result is ignored |
| Augmentation commits mid-read | Evidence gate passes, then a second connection changes a stage and segment before the route's later read | Current request returns the pre-change snapshot | Subsequent request observes the mutation |

</frozen-after-approval>

## Code Map

- `server/meetingminer/api/moments.py` -- `_LIVE_MOMENTS`, `_MOMENT_WITH_MEETING`, and `_COVERING_SEGMENTS` are the defensive joins; `_PROBLEM_RESPONSES` is reused by both endpoints; each route establishes `REPEATABLE READ` before its reads.
- `server/meetingminer/api/problems.py` -- `PROBLEM_MEDIA_TYPE` and `ProblemDetails` define the actual RFC 9457 contract; the app-wide validation handler proves the runtime 422 shape.
- `server/meetingminer/migrations/0006_moments.sql` -- individual foreign keys permit a repaired/corrupt cross-meeting relationship, so readers must scope it defensively; read only.
- `server/tests/test_api_moments.py` -- route matrix tests and `test_pool` seed helpers; add two-meeting, OpenAPI, and coordinated-snapshot regressions here.
- `web/src/features/moments/MeetingMoments.tsx` -- optional `onOpenMoment` controls the row button; `load` already has the abort guard to pin.
- `web/src/features/moments/MomentView.tsx` -- corresponding detail loader and abort guard; no player behavior changes.
- `web/src/features/moments/{MeetingMoments,MomentView}.test.tsx` -- SDK mocks; use manually controlled promises so an aborted request can resolve late.
- `web/openapi-ts.config.ts`, `web/src/client/types.gen.ts` -- generate the corrected route 422 types from a dumped in-process schema; do not edit generated output by hand.

## Tasks & Acceptance

**Execution:**
- [x] `server/meetingminer/api/moments.py` -- scope each evidence join to the moment's meeting and explicitly describe 422 as `ProblemDetails` at `application/problem+json` -- prevents cross-meeting disclosure and false API documentation.
- [x] `server/tests/test_api_moments.py` -- add a two-meeting malformed-link test, an OpenAPI response assertion for both operations, and a deterministic second-connection snapshot test -- prove each server protection against the known-bad behavior.
- [x] `web/src/features/moments/MeetingMoments.tsx` and `MeetingMoments.test.tsx` -- omit the open control without its callback and prove a late aborted response cannot overwrite a newer meeting -- preserves usable standalone behavior and navigation correctness.
- [x] `web/src/features/moments/MomentView.test.tsx` -- add the corresponding late aborted detail response regression -- protects moment drill-down state.
- [x] `web/src/client/types.gen.ts` -- regenerate from this branch's dumped OpenAPI schema after the response correction -- keeps generated client metadata faithful without relying on port 8000.

**Acceptance Criteria:**
- Given a cross-meeting screenshot or segment link, when either moment reader responds, then no foreign path or text is returned.
- Given a malformed moment or meeting id, when an API consumer inspects runtime and OpenAPI behavior, then both identify the same RFC 9457 problem media/schema.
- Given an unanswered first web request and a later id change, when the first request eventually resolves, then it cannot replace the later view in either component.
- Given the generated client, when web tests and a production build run, then the corrected 422 types compile and all moment behavior remains green.

## Spec Change Log

## Design Notes

The snapshot test coordinates its writer inside a monkeypatched gate call: it commits after the route's gate query and before its segment query. This avoids sleeps or timing races; deleting `REPEATABLE READ` makes the route observe the writer's new text. The stale web tests intentionally allow an aborted mock promise to resolve, which tests the post-await guard rather than cancellation alone.

## Verification

**Commands:**
- `cd server && .venv/bin/python -m pytest tests/test_api_moments.py -q` -- expected: all API matrix and remediation regressions pass.
- `cd server && .venv/bin/python -m pytest tests/ -q` -- expected: no server regressions.
- `make web-test` -- expected: all list/detail stale-response and affordance tests pass.
- `pnpm --dir web run lint` -- expected: only the pre-existing `button.tsx` fast-refresh warning.
- `pnpm --dir web run build` -- expected: generated client compiles.

## Suggested Review Order

**Evidence containment**

- Scope every reader edge to the moment's meeting before serializing evidence.
  [`moments.py:72`](../../server/meetingminer/api/moments.py#L72)

- The two-meeting regression demonstrates foreign paths, identifiers, and text stay absent.
  [`test_api_moments.py:141`](../../server/tests/test_api_moments.py#L141)

**Snapshot and error contracts**

- Advertise only the RFC 9457 validation response the application actually emits.
  [`moments.py:240`](../../server/meetingminer/api/moments.py#L240)

- Deterministically prove both routes retain their gate-approved snapshot.
  [`test_api_moments.py:305`](../../server/tests/test_api_moments.py#L305)

- Generated operation errors now expose `ProblemDetails` for malformed identifiers.
  [`types.gen.ts:716`](../../web/src/client/types.gen.ts#L716)

**Web-state safety**

- Render the navigation affordance only for a callable shell callback.
  [`MeetingMoments.tsx:157`](../../web/src/features/moments/MeetingMoments.tsx#L157)

- Late aborted responses cannot overwrite the newer meeting or moment view.
  [`MeetingMoments.test.tsx:232`](../../web/src/features/moments/MeetingMoments.test.tsx#L232)

- Detail loader receives the same stale-response regression protection.
  [`MomentView.test.tsx:275`](../../web/src/features/moments/MomentView.test.tsx#L275)
