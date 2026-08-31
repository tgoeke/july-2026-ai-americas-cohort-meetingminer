# Story 10.2a Thread Curation — Adversarial Review

## Scope

Adversarial design and implementation review of Story 10.2a, with particular attention to whether curation remains an input to `derive_threads` across later derivations, plus red-first remediation of patchable findings.

## Review range

`2d68dcc6..8cd911bc` on `story/10-2a`, reviewed and remediated on `story/10-2a-review`.

The review branch must be rebased onto the then-current `origin/main` before closeout; the final reviewed/remediated range and head will be recorded below.

## Findings

### F1 — Open for remediation: an ambiguous split silently widens on rerun

- **Location:** `server/meetingminer/api/thread_curation.py` (`split_thread`, durable-pin construction); `server/meetingminer/domain/thread_curation.py` (`EFFECTIVE_MEMBERSHIP` versus `ThreadCuration.thread_for`)
- **Severity:** Major
- **Finding:** The API accepts a split that selects one topic UUID when the same meeting contains another topic whose name normalizes to the same `(meeting_id, normalized_name)` key. The immediate SQL read path joins the pin's one `topic_id` hint, so it shows only the selected topic moved. The next `derive_threads` pass joins by the durable content key and moves both topics. A successful curation therefore changes after rerun without another human action—the central silent-overwrite failure this story exists to prevent.
- **Evidence:** Added `test_a_split_refuses_a_subject_key_that_identifies_multiple_topics`. Against the unfixed branch it failed red: the request returned `201 Created` and logged `threads.split` instead of the required `422` refusal. Migration 0014 has no uniqueness constraint on `(meeting_id, normalized topic name)`, so the state is record-valid and reachable.
- **Suggested direction:** Refuse a split whenever any requested durable subject key identifies more than one currently held topic. Name the ambiguity and leave every row unchanged. Supporting a grouped move later would require a read representation that can make all affected topics visible immediately; the current single `topic_id` hint cannot do so honestly.

## Verification

Pending.

## Closeout

Pending.
