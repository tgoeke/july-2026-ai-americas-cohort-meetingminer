---
title: 'Story 4-3 Remediation: Safe Per-Moment Publishing'
type: 'bugfix'
created: '2026-08-21'
status: 'done'
baseline_commit: 'c850928ef3b79d67c464c31544de65d9286e9c7d'
review_loop_iteration: 0
context:
  - '{project-root}/project-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/review-story-4-3-2026-08-21.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-4-3-per-moment-approval-publishing.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Story 4-3's approval path can leave the browser indefinitely in
“Publishing…”, and its Git operations can race across different moments,
commit unrelated staged files, or record the wrong commit SHA. Its required
store-free timeout test is red, so the claimed verification baseline is not
reliable.

**Approach:** Harden the single per-moment approval gesture without changing
its lifecycle or projection boundaries: bound UI requests, make Git operations
safe for one configured repository, honor a configured pre-existing Git repo,
and add focused regression coverage.

## Boundaries & Constraints

**Always:** `MM_PUBLISH_ROOT` configuration authorizes an operator-created
existing Git repository; initialize it only when Git metadata is absent.
Serialize all API-process mutations of one publish repository, commit only the
ADR being published, and record that artifact's own commit. Preserve the
one-way lifecycle, filesystem/git-before-Postgres ordering, RFC 9457 error
shape, and the rule that action items are never committed. Treat inherited Git
repository/index environment overrides as untrusted. Timeout must restore the
approval control and leave its rail unchanged.

**Ask First:** None.

**Never:** Do not change worker extraction, artifact content ownership,
projection/indexing, the per-moment gesture, or add a Git library dependency.
Do not address upstream duplicate artifact pairs here; they remain Epic 4
triage work.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|---------------|----------------------------|----------------|
| Existing repo | Configured root has a valid repository and prior commit | ADR export commits there; existing history remains | No marker-based refusal |
| Parallel ADRs | Different moments approve concurrently to one root | Each commit contains only its own ADR and each row stores its own SHA | Lock serializes repository mutation |
| Staged unrelated file | Action-item or human file already staged | ADR commit omits it | No accidental commit |
| UI stall | Approve request exceeds 8 seconds | Error names timeout; button re-enables; rail stays extracted | Abort request safely |
| Bad Git environment/config | Inherited Git redirect variable or local identity setup fails | No redirected commit; named Git failure | DB rows stay extracted |

</frozen-after-approval>

## Code Map

- `server/meetingminer/publish/export.py` -- existing lazy Git initialization,
  subprocess wrapper, and add/commit/sha sequence; own the repository-wide
  cross-process critical section and sanitized subprocess environment here.
- `server/meetingminer/api/moments.py` -- maps export failures to Problems;
  remove the obsolete marker-refusal mapping and call the atomic ADR publish
  operation while retaining its moment-row transaction.
- `web/src/features/moments/MomentView.tsx` -- `load` already has a
  cancellable 8-second timeout; apply that pattern to `handleApprove`.
- `server/tests/test_publish_export.py` -- real local-Git unit coverage,
  including the red fake-Git timeout test.
- `server/tests/test_artifact_publish.py` -- endpoint seed helpers and
  publish-root override support for concurrent, scoped-commit coverage.
- `server/tests/test_failfast.py` -- subprocess API-startup contract tests.
- `web/src/features/moments/MomentView.test.tsx` -- approval request-state
  tests and fake-timer timeout regression.

## Tasks & Acceptance

**Execution:**
- [x] `server/meetingminer/publish/export.py` -- accept an existing configured
  repository; provide an atomic, cross-process-safe ADR publish operation;
  sanitize Git environment variables; and report identity configuration errors.
- [x] `server/meetingminer/api/moments.py` -- use the atomic publish operation
  and remove the marker-specific error route.
- [x] `web/src/features/moments/MomentView.tsx` -- apply the existing timeout
  and stale-response rules to approve requests.
- [x] `server/tests/test_publish_export.py` and
  `server/tests/test_artifact_publish.py` -- cover existing repos, environment
  isolation, configuration failures, scoped commits, parallel publication, and
  real timeout behavior.
- [x] `server/tests/test_failfast.py` -- test API startup with an unset publish
  root after valid configuration otherwise loads.
- [x] `web/src/features/moments/MomentView.test.tsx` -- test a timed-out
  approval re-enables the button and cannot replace the rail late.

**Acceptance Criteria:**
- Given an existing configured publish repository, when an ADR is approved,
  then its export is committed without losing prior repository history.
- Given simultaneous approvals of distinct moments, when both publish ADRs,
  then each artifact records the commit that contains only its own ADR and no
  staged action item is committed.
- Given an approval request that stalls, when eight seconds elapse, then the
  UI names the timeout, restores the button, and preserves the draft rail.
- Given a missing publish root at real API startup, when the app imports, then
  it exits 1 with the named configuration error and no traceback.

## Design Notes

Keep Git initialization, identity configuration, staging, commit, and SHA
derivation in one repository lock so a different moment cannot interleave
between them. The lock must be cross-process because API workers do not share
Python memory. Git's default index is process-global to that repository, so the
commit command must name the target file rather than committing all staged
content.

## Verification

**Commands:**
- `uv run --project server pytest server/tests/test_publish_export.py server/tests/test_publish_root.py server/tests/test_failfast.py -q` -- expected: all pass.
- `uv run --project server pytest server/tests/test_artifact_publish.py server/tests/test_api_moments.py -q` -- expected: all pass; shared stores required.
- `pnpm --dir web exec vitest run src/features/moments/MomentView.test.tsx` -- expected: all pass.
- `pnpm --dir web exec tsc --noEmit` -- expected: clean.
- `make check-reviews` -- expected: every dispatched review has a committed report.

## Suggested Review Order

**Repository publication safety**

- One atomic operation owns initialization, scoped commit, and path-specific SHA lookup.
  [`export.py:129`](../../server/meetingminer/publish/export.py#L129)

- The bounded system lock serializes API processes without dirtying the configured repository.
  [`export.py:247`](../../server/meetingminer/publish/export.py#L247)

- Local identity respects an operator's existing repository configuration.
  [`export.py:143`](../../server/meetingminer/publish/export.py#L143)

**Approval boundary**

- The route delegates ADR mutation to the atomic publication operation.
  [`moments.py:654`](../../server/meetingminer/api/moments.py#L654)

- The UI deadline aborts the request, restores control, and discards late results.
  [`MomentView.tsx:126`](../../web/src/features/moments/MomentView.tsx#L126)

**Regression evidence**

- Real Git tests cover independent processes, staged-file isolation, and retry provenance.
  [`test_publish_export.py:156`](../../server/tests/test_publish_export.py#L156)

- The browser test proves deadline abort, recovery, and late-response isolation.
  [`MomentView.test.tsx:393`](../../web/src/features/moments/MomentView.test.tsx#L393)
