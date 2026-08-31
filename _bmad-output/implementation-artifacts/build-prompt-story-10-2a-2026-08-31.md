# Builder handoff — Story 10.2a review outcome

You are receiving the completed adversarial review of MeetingMiner Story 10.2a.
Read the review artifact in full before acting:

`_bmad-output/implementation-artifacts/review-story-10-2a-2026-08-31.md`

## Repository and exact reviewed state

- Repository: `/Users/devopsterus/current/cohort/meetingminer`
- Builder branch originally reviewed: `story/10-2a`
- Original builder range: `2d68dcc6..8cd911bc`
- Builder range after the review branch's final rebase: `e46abe0d..d4d74609`
- Review/remediation branch: `story/10-2a-review`
- Review/remediation code head: `6128c5b9`
- Final review report commit: `79707979`
- Rebase base: `origin/main` at `bd1a8fc9`

The branch moved because the review lane rebased it onto current main and added
red-first remediations. Work only from the pushed `story/10-2a-review`; do not
recreate or discard those commits.

## Review verdict

**Story 10.2a does not pass review and must not be integrated yet.** Eight
patchable findings are already fixed on the review branch. Three open findings
change the frozen contract or data-lifecycle policy; they require an owner
ruling and specification amendment before a builder may implement them.

## Specification amendments required before more code

### F2 — Durable replacement-topic lineage

- Anchor: `server/meetingminer/migrations/0021_thread_curation.sql` and
  `server/meetingminer/domain/threads.py`
- Failure: split pins use `(meeting_id, normalized_name)` and merge aliases use
  the old thread UUID. If Story 10.1 replaces a topic under a changed normalized
  name, a split becomes unmatched and a merge's subject mints a fresh unaliased
  thread. The correction disappears from the UI on the next derivation.
- Required outcome: define a durable subject/replacement lineage independent of
  both topic UUID and mutable display name, and define a visible degraded state
  for corrections that cannot reconcile. Do not guess from embeddings, gist, or
  meeting membership.
- Action: **spec amendment and re-derivation first; no code workaround now.**

### F8 — Iterative canonical merge / alias retargeting

- Anchor: `server/meetingminer/migrations/0021_thread_curation.sql` function
  `thread_alias_is_flat`; `server/meetingminer/api/thread_curation.py`
  `merge_threads`
- Failure: after A→B, canonical B is forbidden from merging into C because it
  already absorbed A, while A is forbidden as an already-merged source. The
  documented cure “merge A directly onto C” cannot be performed by the API.
- Required outcome: define the semantics of B→C when aliases already end at B,
  including atomic retargeting/flattening, row-lock order, projection
  invalidation, audit behavior, and reversal policy.
- Action: **owner decision plus spec amendment and re-derivation; do not add an
  ad-hoc chain walker.**

### F9 — Curation-aware thread deletion

- Anchor: all curation foreign keys in
  `server/meetingminer/migrations/0021_thread_curation.sql`; the future dead-row
  sweep anticipated in `server/meetingminer/domain/threads.py`
- Failure: deleting a thread cascades its rename, incoming/outgoing aliases, and
  pins. A later derivation can restore machine grouping with no surviving audit
  or unmatched report.
- Required outcome: choose and specify either retention/refusal for any thread
  participating in curation or durable tombstone/retarget behavior before any
  sweep is built.
- Action: **owner lifecycle ruling; no deletion patch until that ruling exists.**

## Already fixed on the review branch — no further action

- F1 ambiguous split keys are refused before any write.
- F3 split-created names report human provenance.
- F4 all curation writes invalidate affected projection state atomically.
- F5 graph reprojection retires only graph-wide orphan Thread nodes.
- F6 successful curation invalidates list and timeline caches.
- F7 replacement rows store `linked_by = curated` with no machine similarity.
- F10 merge completion preserves/focuses the returned survivor identity.
- F11 curation success responses are parsed strictly.

Do not reopen B-53 duplicate display names in this round. The review accepted
the existing advisory backlog direction. Do not implement a general unmerge or
unsplit until F8's canonical-retargeting policy is decided. Do not run
`make evals-run`, a worker, an API process, or any paid model.

## Verification required after amended specs are implemented

Run every command in the amended spec's `## Verification`, plus:

1. `uv run --project server pytest -q server/tests/test_thread_curation.py`
2. `uv run --project server pytest -m "" -q server/tests/test_projections_threads.py`
3. `pnpm --dir web exec vitest run src/features/threads/ThreadCuration.test.tsx src/features/threads/Threads.test.tsx`
4. `make test-fast`
5. `make test`
6. `make check-reviews`

Every new regression for F2/F8/F9 must first be observed failing against the
unfixed code, then green after the implementation. In particular, retain the
review's compound merge+split+rename `xmin` no-write proof and the mutation
proof for split-row exclusion.

Commit and push each coherent red-first unit. Do not merge to main; return the
amended spec and implementation to a fresh adversarial review lane.
