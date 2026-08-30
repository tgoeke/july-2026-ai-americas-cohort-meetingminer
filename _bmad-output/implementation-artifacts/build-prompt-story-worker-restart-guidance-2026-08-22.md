---
title: 'Builder Handoff: Worker Restart Guidance'
story: 'worker-restart-guidance'
source_review: '_bmad-output/implementation-artifacts/review-story-worker-restart-guidance-2026-08-22.md'
review_status: 'passed'
date: '2026-08-22'
---

# Builder Handoff — Worker Restart Guidance

Use `bmad-build-auto` only to integrate the already-reviewed result. The story
passes review and no product-code finding remains. Do not reopen discovery or
look for additional scope.

## Exact source

- Repository: `/Users/devopsterus/current/cohort/meetingminer`
- Original story branch: `story/worker-restart-guidance`
- Original reviewed range:
  `8b99f1c4dbb1500024777b688b21219b97cf0a9d..7b88adb`
- Reviewed remediation branch: `story/worker-restart-guidance-codex-review`
- Final verified implementation: `3119d7c`
- Passed review report commit: `1631912c230a830c64ef7e97deeba3551b3977c9`
- Review report:
  `_bmad-output/implementation-artifacts/review-story-worker-restart-guidance-2026-08-22.md`
- Frozen/amended contract:
  `_bmad-output/implementation-artifacts/spec-worker-restart-guidance.md`

The original story branch moved to `55098fa` after the pinned review target.
Use the reviewed remediation branch above as the integration source; do not
silently substitute the later original-branch head.

## Verdict and required action

**PASSED.** There are no fix-now product changes. The builder's job is to
integrate the reviewed branch, preserve the reviewed behavior, rerun the listed
verification, then mark the integration complete, commit, and push. Do not hunt
for more work.

An attempted rebase onto `main` at
`f90065bb0989006aba57bb12e717ee53065ccf3d` stopped on a conflict in
`_bmad-output/implementation-artifacts/deferred-work.md` while replaying the
story's first commit (`8b99f1c`). The rebase was aborted without changing
`main`. Reconcile that documentation conflict deliberately; do not choose one
side wholesale or discard unrelated concurrent deferred-work entries.

There is no matching `worker-restart-guidance` sprint-status key, so no sprint
status entry was changed. The story spec itself is already `status: done`.

## Resolved findings — preserve these results

### 1. Configuration snapshots were ambiguous — resolved

- Location: `server/meetingminer/api/status.py:397-408`
- Original failure: `/status` could present the API's import-time extraction
  binding as if a newly started worker were guaranteed to use it, even though
  the worker reloads `config.yaml` at startup.
- Required and implemented result: identify the exact primary/fallback binding
  as the snapshot loaded by this API process and state that a new worker reloads
  `config.yaml`, so its loaded binding may differ. Do not reload configuration
  inside `/status` and do not claim the snapshots match.
- Root cause was in the frozen specification. The owner selected the qualified
  snapshot contract, and the spec was amended before implementation.

### 2. Cost vocabulary conflicted with exact identifiers — resolved

- Locations: `server/tests/test_api_status.py:107-130,477-548` and
  `web/src/features/status/status.test.tsx:8-10,62-79`
- Original failure: the contract both banned words such as `free` from the
  complete message and required exact model identifiers, which is impossible
  for an identifier such as `openrouter/example:free`.
- Required and implemented result: apply the no-cost-verdict invariant only to
  authored prose. Preserve primary and fallback identifiers byte-for-byte and
  exempt them from prose vocabulary scanning.
- Root cause was in the frozen specification. The owner selected the prose-only
  invariant, and the spec was amended before implementation.

### 3. Tests allowed unlisted cost verdicts — resolved

- Location: `server/tests/test_api_status.py:107-130`
- Original failure: a blacklist-only assertion allowed prose such as
  `Restarting will be billable.`
- Required and implemented result: assert the complete deterministic authored
  message while inserting configured identifiers unchanged. Any extra authored
  judgment must fail.

### 4. Paused-work count omitted mixed-state verification — resolved

- Locations: `server/meetingminer/api/status.py:397-399` and
  `server/tests/test_api_status.py:405-429`
- Original failure: tests covered queued jobs only, so an implementation that
  ignored crash-orphaned `running` jobs could pass.
- Required and implemented result: report the current paused snapshot as
  `queued + running`; retain the endpoint test with two queued and one running
  job and the expected count of three.

### 5. Post-fix review gaps — resolved

- Location: the same server and web files above.
- Required and implemented result: the message reports a current paused
  snapshot rather than predicting what startup will do; both vocabulary-bearing
  primary and fallback identifiers are covered; the web check scans authored
  prose rather than the fully interpolated message.

## Deferred and no-action items

Do not widen this integration to address these items:

- `server/meetingminer/config.py:168-169`: `LlmRoleBinding.model` and
  `.fallback` accept blank or whitespace-only strings. This is a pre-existing
  shared-config validation issue recorded in `deferred-work.md`.
- `server/meetingminer/api/status.py:19-21`: the module docstring still frames
  every remediation as an edit-and-restart instruction. This broader status
  documentation correction is recorded in `deferred-work.md`.
- Requests to describe every worker stage, omit bindings for an empty queue,
  name endpoint overrides, singularize `job(s)`, classify provider costs,
  change the status schema/client, restart a shared worker, or duplicate generic
  indicator rendering coverage were rejected as frozen-design, unrelated, or
  already-covered changes.
- Historical review prompts and review reports are evidence artifacts, not live
  implementation instructions; do not rewrite their earlier observations.

## Integration order and dependencies

1. Rebase `story/worker-restart-guidance-codex-review` onto current `main`.
2. Reconcile only the `deferred-work.md` conflict, preserving both this review's
   two entries and unrelated entries that landed on `main`.
3. Confirm the story spec and passed review report remain present.
4. Run all verification below.
5. Merge to `main`, commit any deliberate conflict resolution, and push.

No product-code dependency or additional implementation patch is expected. If
the rebase exposes a conflict outside the known documentation file, stop and
report it instead of resolving blindly.

## Required verification

Run from the integrated checkout:

```sh
uv run --project server pytest server/tests/test_api_status.py -q
cd web && pnpm vitest run src/features/status
cd web && pnpm lint
```

The reviewed result produced 14 passing server tests and 5 passing web tests;
lint exited zero with four pre-existing fast-refresh warnings.

Mutation confirmation has already been performed against the reviewed tests:
an appended `billable` verdict, a queued-only count, and a sanitized
`openrouter/example:free` fallback each failed its targeted test and passed
again after restoration. Repeat mutation testing only if those assertions are
changed during conflict resolution.

A manual `curl localhost:8000/status` reached an older shared API process, not
this branch. Do not restart shared services solely for this integration. If an
isolated API for the integrated checkout is already available, a smoke request
is useful; otherwise the passing advisory-lock endpoint test is the required
running-worker verification.

