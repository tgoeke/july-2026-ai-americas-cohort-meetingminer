# Story 10.2a Thread Curation — Adversarial Review

## Scope

Adversarial design and implementation review of Story 10.2a, with particular attention to whether curation remains an input to `derive_threads` across later derivations, plus red-first remediation of patchable findings.

## Review range

`2d68dcc6..8cd911bc` on `story/10-2a`, reviewed and remediated on `story/10-2a-review`.

The review branch must be rebased onto the then-current `origin/main` before closeout; the final reviewed/remediated range and head will be recorded below.

## Findings

### F1 — Remediated: an ambiguous split silently widened on rerun

- **Location:** `server/meetingminer/api/thread_curation.py` (`split_thread`, durable-pin construction); `server/meetingminer/domain/thread_curation.py` (`EFFECTIVE_MEMBERSHIP` versus `ThreadCuration.thread_for`)
- **Severity:** Major
- **Finding:** The API accepts a split that selects one topic UUID when the same meeting contains another topic whose name normalizes to the same `(meeting_id, normalized_name)` key. The immediate SQL read path joins the pin's one `topic_id` hint, so it shows only the selected topic moved. The next `derive_threads` pass joins by the durable content key and moves both topics. A successful curation therefore changes after rerun without another human action—the central silent-overwrite failure this story exists to prevent.
- **Evidence:** Added `test_a_split_refuses_a_subject_key_that_identifies_multiple_topics`. Against the unfixed branch it failed red: the request returned `201 Created` and logged `threads.split` instead of the required `422` refusal. Migration 0014 has no uniqueness constraint on `(meeting_id, normalized topic name)`, so the state is record-valid and reachable.
- **Suggested direction:** Refuse a split whenever any requested durable subject key identifies more than one currently held topic. Name the ambiguity and leave every row unchanged. Supporting a grouped move later would require a read representation that can make all affected topics visible immediately; the current single `topic_id` hint cannot do so honestly.
- **Remediation:** `split_thread` now indexes every currently held topic by the durable key and refuses a requested key that maps to more than one row before minting a thread or pin. The red regression is green; the complete curation module is **23 passed**.

### F2 — Open, spec/design decision required: topic-name drift makes split and merge corrections disappear

- **Location:** `server/meetingminer/migrations/0021_thread_curation.sql` (`thread_alias` is keyed only by old thread UUID; `thread_topic_pin` is keyed only by `(meeting_id, normalized_name)`); `server/meetingminer/domain/threads.py` (`derive_threads` has no replacement-topic lineage to resolve)
- **Severity:** Major
- **Finding:** The central claim is false for a valid Story 10.1 replacement in which the extractor changes a topic's normalized name. A split pin no longer matches and the curated band loses its membership; a merge alias remains attached to the old empty thread while the renamed replacement mints an unaliased thread. In both cases the next derivation changes the grouping the user sees. `unmatched_pins` logs the split's old key but does not preserve the correction or surface it on the Threads view; merges have no equivalent unmatched report at all.
- **Evidence:** Two review reproductions were run red against the unfixed design. After splitting meeting 2's `Vendor Feed`, replacing that topic with `Vendor billing feed`, and deriving, `ThreadDerivation.unmatched_pins` contained `(meeting_2, "vendor feed")` and the replacement did not belong to the curated thread. After merging `Billing Portal` into `Vendor Feed`, replacing it with `Accounts payable portal`, and deriving, the replacement belonged to a newly minted UUID rather than the survivor. Both states are valid under migration 0014, which replaces topic rows wholesale and has no stable topic-lineage key.
- **Suggested direction:** Amend the frozen contract with a durable replacement-topic lineage that is independent of both topic UUID and mutable display name (for example an extraction-owned stable subject identity with explicit reconciliation), then re-derive curation against that identity. Until that exists, the product must not promise survival across every re-extraction; unmatched split and orphaned merge corrections also need a user-visible degraded state rather than an operator-only log event. This is not safely fixable by guessing from gist, embeddings, or meeting membership in the review patch.

### F3 — Open for remediation: a human-named split is labeled machine-derived

- **Location:** `server/meetingminer/api/thread_curation.py` (`_THREAD_WITH_CURATION` and `split_thread`); `server/meetingminer/domain/thread_curation.py` (`CURATED_NAME_IS_CURATED_EXPR`)
- **Severity:** Moderate
- **Finding:** A split writes its human-supplied name into the newly minted `thread` row but creates no `thread_curation` row. Both response paths define `nameIsCurated` only as the presence of `thread_curation`, so the split response and subsequent list row say `false`; the UI prints `machine-derived` beside a thread and name created entirely by the user. This violates the explicit requirement that a reader can distinguish human and machine names.
- **Evidence:** Strengthened `test_a_split_survives_a_rerun_without_the_derivation_reclaiming_its_thread` to assert the write response and list provenance. Against the unfixed branch it failed red at the first assertion: `split.json()["nameIsCurated"]` was `False`.
- **Suggested direction:** Treat a `thread` whose immutable provenance is `link_rule = 'curated'` as human-named in both the curation response query and the shared list expression. Preserve the distinction after a later rename is cleared: the split's original name remains human-originated even without a rename override.

## Verification

Pending.

## Closeout

Pending.
