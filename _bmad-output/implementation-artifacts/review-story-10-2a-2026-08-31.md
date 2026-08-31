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

### F3 — Remediated: a human-named split was labeled machine-derived

- **Location:** `server/meetingminer/api/thread_curation.py` (`_THREAD_WITH_CURATION` and `split_thread`); `server/meetingminer/domain/thread_curation.py` (`CURATED_NAME_IS_CURATED_EXPR`)
- **Severity:** Moderate
- **Finding:** A split writes its human-supplied name into the newly minted `thread` row but creates no `thread_curation` row. Both response paths define `nameIsCurated` only as the presence of `thread_curation`, so the split response and subsequent list row say `false`; the UI prints `machine-derived` beside a thread and name created entirely by the user. This violates the explicit requirement that a reader can distinguish human and machine names.
- **Evidence:** Strengthened `test_a_split_survives_a_rerun_without_the_derivation_reclaiming_its_thread` to assert the write response and list provenance. Against the unfixed branch it failed red at the first assertion: `split.json()["nameIsCurated"]` was `False`.
- **Suggested direction:** Treat a `thread` whose immutable provenance is `link_rule = 'curated'` as human-named in both the curation response query and the shared list expression. Preserve the distinction after a later rename is cleared: the split's original name remains human-originated even without a rename override.
- **Remediation:** The shared provenance expression now treats either a rename row or `thread.link_rule = 'curated'` as human-originated, and the write response uses that same expression. Both red assertions are green; the complete curation module remains **23 passed**.

### F4 — Remediated: curation did not schedule the graph projection promised by the AC

- **Location:** `server/meetingminer/api/thread_curation.py` (all three successful write paths omit `meeting_projection` invalidation); `server/meetingminer/projections/__init__.py:projection_action`
- **Severity:** Major
- **Finding:** A projected meeting retains a current `meeting_projection` row after rename, merge, or split. `projection_action` therefore returns `none` at the ordinary next pass, so `projections.evidence.read_meeting` never gets a chance to consume the new effective membership/name and Neo4j remains on the pre-curation grouping. Merely changing the projection reader is insufficient when its scheduler declares there is no work.
- **Evidence:** Added `test_a_rename_invalidates_every_affected_meeting_projection`. Two meetings in one thread were given current projection-state rows, then the thread was renamed. Against the unfixed branch the test failed red: both `meeting_projection` rows remained after the successful `200` response.
- **Suggested direction:** In the same transaction as each curation write, delete `meeting_projection` for every meeting whose effective thread identity or name changed: all meetings currently in a renamed thread, both effective sides of a merge, and every meeting containing a split pin. Do not call the existing helper that commits internally; curation must remain atomic with its invalidation.
- **Remediation:** Each route now resolves its affected meetings before changing membership/name and deletes their projection-state rows in the same transaction. Rename invalidates all meetings in the thread, merge invalidates both effective sides, and split invalidates only meetings whose topics moved. Three focused regressions and the complete curation module are green (**26 passed**).

### F5 — Remediated: merge left an obsolete Thread node in Neo4j

- **Location:** `server/meetingminer/projections/graph.py` (`delete_meeting` preserves every cross-meeting `Thread`; `_write_topics` only `MERGE`s current identities)
- **Severity:** Major
- **Finding:** After a merge is reprojected, the absorbed meeting's `Topic` node and old `INCLUDES` edge are replaced, but the absorbed cross-meeting `Thread` node is deliberately outside the per-meeting delete and no later statement removes it. The graph therefore contains a thread identity the API has hidden and the human explicitly merged away. F4 is necessary to schedule projection but does not make its result equivalent to effective Postgres membership.
- **Evidence:** Added twin-backed `test_reprojecting_a_merge_removes_the_absorbed_orphan_thread_node`. It projected two machine threads, recorded an alias, invalidated/reprojected the affected meeting, and queried Neo4j for the absorbed id. Against the unfixed branch it failed red: the obsolete `Thread` node was still returned after the successful projection.
- **Suggested direction:** Inside the same Neo4j transaction as the scoped delete/write, retire only `Thread` nodes with no remaining `INCLUDES` edge after current topics have been written. Do not delete a cross-meeting thread merely because one meeting stopped using it; orphanhood must be evaluated graph-wide after the replacement.
- **Remediation:** The graph projection now removes graph-wide orphan `Thread` nodes after writing the current meeting's topics and edges, inside the same Neo4j transaction. A thread still used by any projected meeting retains an `INCLUDES` edge and survives; the absorbed last-use node is retired. The twin-backed red regression is green.

### F6 — Remediated: curation left the timeline on stale cached membership

- **Location:** `web/src/features/threads/Threads.tsx` (`reReadThreads`, `cacheRef`, `requestedKeyRef`, and the timeline-fetch effect)
- **Severity:** Major
- **Finding:** After rename, merge, or split succeeds, the Threads screen increments only `listRetryVersion`. The corrected list is fetched again, but the timeline request key and drawn/cache entries are unchanged, so no `level=bands` request follows and the canvas continues to show the pre-curation membership. The same screen therefore presents two contradictory answers about the user's correction.
- **Evidence:** Added the integration regression `invalidates timeline data after curation instead of leaving the corrected list on a stale canvas`. Against the unfixed branch, the merge returned successfully and the list re-read completed, but the number of timeline band requests stayed at three rather than increasing; the run ended **1 failed, 683 passed** with `expected 3 to be greater than 3`.
- **Suggested direction:** Treat successful curation as invalidating both list and timeline data. Clear the timeline cache/request guard and advance the timeline retry generation while retaining the currently drawn tier until the replacement fetch resolves, matching the screen's existing anti-flicker behavior.
- **Remediation:** Successful curation now clears the timeline and meeting caches, releases the request-key guard, and advances both timeline and list retry generations. The outgoing drawing remains visible only while the authoritative replacement request is pending. The focused red integration regression is green (**1 passed**).

### F7 — Remediated: re-extracted split membership lost its curated provenance

- **Location:** `server/meetingminer/domain/threads.py` (`derive_threads`, `_upsert_membership`); `server/meetingminer/domain/thread_curation.py` (`EFFECTIVE_MEMBERSHIP` and its stale-hint argument); `server/meetingminer/migrations/0015_threads_and_index.sql` / `0021_thread_curation.sql`
- **Severity:** Major
- **Finding:** A same-name re-extraction correctly matches the durable split pin and moves the replacement topic to the curated thread, but the derivation writes the cluster's machine `linked_by` leg into `topic_thread`. The pin's old `topic_id` hint no longer joins the replacement row, so every SQL reader reports the human-decided membership as `seed`, `normalized-name`, or `embedding-similarity`. The documented claim that `topic_thread` carries the complete pinned answer after a pass is therefore false: it carries the target UUID but not the required human provenance (and can retain an irrelevant similarity score).
- **Evidence:** Strengthened the same-name re-extraction regression to inspect the replacement row's stored linkage leg. Against the unfixed branch it failed red: the new UUID landed in the curated thread but stored `('normalized-name', NULL)` instead of `('curated', NULL)`.
- **Suggested direction:** Make curated provenance part of the derived output: permit `curated` in the membership constraint, and when `ThreadCuration.thread_for` says a pin fired, upsert `linked_by = 'curated'` with no similarity. Keep the API-owned durable pin immutable; derivation should derive its output from that input rather than mutate the UUID hint.
- **Remediation:** Migration 0021 extends the membership provenance constraint with `curated`, and the single derivation UPSERT writes that leg with no machine similarity whenever pin resolution fired. The API-owned pin and its deliberately stale UUID hint remain untouched. The focused re-extraction regression is green (**1 passed**).

### F8 — Open, spec/design decision required: the first merge permanently freezes its survivor

- **Location:** `server/meetingminer/migrations/0021_thread_curation.sql` (`thread_alias_is_flat`); `server/meetingminer/api/thread_curation.py` (`merge_threads`, `_HAS_ABSORBED` refusal)
- **Severity:** Major
- **Finding:** After A is merged into B, visible canonical thread B is prohibited from later merging into C because it has absorbed A. A is also prohibited as a source because it is already merged away. The migration comment and API refusal say the cure for avoiding A→B→C is to merge A directly into C, but neither endpoint operation can perform that cure. A normal corpus that later reveals B and C are one subject is permanently uncorrectable without direct database surgery.
- **Evidence:** Both the database trigger and API explicitly reject a source appearing as any alias target; the API additionally rejects an already-absorbed source before insertion. Thus there is no permitted sequence from A→B to effective A→C and B→C. This materially changes B-54: unmerge/retarget is not only an optional undo gesture; some form of transactional alias flattening is required for iterative correction.
- **Suggested direction:** Amend the contract to define canonical-merge retargeting. A B→C action should atomically retarget every alias currently ending at B to C and add B→C (or store canonical equivalence in a representation whose record constraints flatten it), with sorted locking and one projection invalidation set. Until that policy exists, this cannot be patched safely in the review lane.

### F9 — Open, deletion-policy decision required: cascades silently erase every kind of curation

- **Location:** `server/meetingminer/migrations/0021_thread_curation.sql` (all curation foreign keys use `ON DELETE CASCADE`); `server/meetingminer/domain/threads.py` (future dead-thread sweep is explicitly anticipated)
- **Severity:** Moderate
- **Finding:** Deleting a thread erases its rename, its outgoing/incoming aliases, and split pins that target it. A later derivation can then recreate the machine grouping with neither `unmatched_pins` nor any surviving record that a correction existed, contradicting the module's unconditional “nothing is discarded quietly” claim. There is no current delete route, but the thread model explicitly reserves deletion for a future dead-row sweep, so the record is unsafe for the lifecycle it documents.
- **Evidence:** Direct thread deletion reaches only cascading foreign keys; no tombstone, refusal trigger, or audit row survives. In particular, deleting a merge survivor cascades aliases whose absorbed source rows still exist, so those source clusters reappear on the next pass without an AD-18 signal.
- **Suggested direction:** Define curation-aware thread retention before adding the anticipated sweep: refuse deletion of any thread participating in curation, or preserve/retarget the human decision in durable tombstone/audit state. This is a data-lifecycle choice, not a safe review-time guess.

### F10 — Confirmed, remediation in progress: merge success discarded the canonical survivor identity

- **Location:** `web/src/features/threads/ThreadCuration.tsx` (`settle`); `web/src/features/threads/Threads.tsx` (focused thread and route ownership)
- **Severity:** Moderate
- **Finding:** The merge API deliberately returns the survivor, but `settle` discards the parsed response and calls a parameterless callback. When the absorbed row was focused, the fine-tier canvas remains focused on an empty UUID; on `/threads/:absorbed`, the next list read replaces the entire screen with “may have been merged away” instead of continuing on the canonical thread.
- **Evidence:** A component regression is being added to require merge completion to pass both the returned thread and the operation to its owner. The unchanged implementation calls `onCurated()` with no arguments.
- **Suggested direction:** Propagate the parsed result and action through `ThreadList`; after a merge, focus the returned survivor and replace a focused route with `/threads/{survivor}` while preserving its anchor query. Then invalidate both list and timeline as F6 requires.

### F11 — Confirmed, remediation in progress: malformed curation success bodies were silently accepted

- **Location:** `web/src/features/threads/threadsApi.ts` (`parseCuratedThread`); `web/src/features/threads/ThreadCuration.tsx` (`settle`)
- **Severity:** Moderate
- **Finding:** The purportedly strict response parser converts a missing or non-boolean `nameIsCurated` to `false` and a missing `mergedIntoThreadId` to `null`. A malformed 2xx therefore closes the editor and announces success, losing the user's draft, instead of surfacing a contract refusal.
- **Evidence:** A component regression is being added with a successful write body whose `nameIsCurated` is a string. The unchanged parser treats it as `false`, so `onCurated` fires and the panel closes.
- **Suggested direction:** Require an actual boolean and require the nullable merge field to be present and either a string or `null`, using the same named `ThreadsContractError` path as every other response field. A contract error must keep the panel and draft intact.

## Verification

Pending.

## Closeout

Pending.
