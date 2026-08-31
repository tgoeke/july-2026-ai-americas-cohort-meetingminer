# Story 10.7 review-remediation handoff

Story 10.7 passes after red-first remediation on `story/10-7-review`. There is
no further builder remediation to perform. The owner should integrate the
review branch under the repository's normal integration procedure; this review
lane did not merge to `main`.

## Branch and reviewed range

- Repository: `/Users/devopsterus/current/cohort/meetingminer`
- Review worktree: `/Users/devopsterus/current/cohort/meetingminer-wt/10-7-review`
- Source branch: `story/10-7`
- Review branch: `story/10-7-review`
- Original builder range:
  `8bd54e868c591f000417ef916476500e768c7c18..82676eab9b32819f7d81103dd4e832b1e4f07701`
- Rebased, code-verified range: `a1d9182e..f2fff78e`
- Review report:
  `_bmad-output/implementation-artifacts/review-story-10-7-2026-08-31.md`

## Closed findings

1. **F1, high — false cap from synonymous topic rows.**
   `server/meetingminer/api/threads.py:283` counted topic-mention rows although
   the quote query returns distinct moments. The red regression observed
   `[2, 1]` for one shared moment. Both trace figures now count distinct live
   moment ids, so completeness prose describes the quoted row set.
2. **F2, high — route reuse preserved the old catalogue replacement.**
   `web/src/features/threads/ThreadTrace.tsx:86` left trace state mounted when
   `/threads/:threadId` became `/threads`. The red browser test retained the old
   timeline. The route effect now clears the front door and invalidates older
   request generations.
3. **F3, medium — first fit consumed a fake 1000px width.**
   `web/src/features/threads/TraceTimeline.tsx:79` could fit before the real
   layout measurement and never refit. The red test observed 7.46 px/day
   instead of 3.22 at 500px. Browser fitting now waits for positive measured
   width and keys ownership to the trace extent.

All three checklist entries are checked under `### Review Findings` in the
story spec, whose status and sprint status are `done`.

## Filed gaps

- **B-59 remains open:** generated-client refresh requires a live API health
  endpoint and OpenAPI document. The review did not start the API during the
  paid-model ingest. The current raw-fetch adapter is strict and candid.
- **B-60 is closed:** positive screen-chain coverage now pins `screenCount`,
  opaque screenshot ids, and rendered media.
- **B-61 is closed as not applicable:** `meeting.started_at` is `NOT NULL` in
  migration 0002. Day precision is pinned from midnight SQL anchoring through
  the visible `date only` label.

## Verification read from foreground output

- `make lint`: passed.
- `web/node_modules/.bin/tsc -b`: passed.
- `oxlint src/features/threads`: no Story 10.7/remediation finding; seven
  warnings only in retained Story 10.6 modules.
- Targeted server thread suites: 92 passed.
- `make web-test`: 788 passed, 65 files.
- `make test`: puller 128 passed; web 788 passed; eval harness 655 passed;
  isolated worker/STT/diarization 92 passed; store probe 1 passed; complete
  server suite 2901 passed, 3 skipped; production web build passed; exit 0.

The branch was rebased onto current `origin/main` `a1d9182e`. No API or worker
was started, `make evals-run` was not run, and no paid model was called.

## Outside this review

- Regenerating the client after the ingest ends (B-59).
- Removing the retained Story 10.6 catalogue and `GET /threads` (Story 10.7a).
- Thread curation (parked Story 10.2a).
- An undated lane while the schema makes undated meetings impossible.
