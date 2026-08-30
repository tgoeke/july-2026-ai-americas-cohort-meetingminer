# Scoped Verification Review — Story 11-3 Remediation

## Scope

- Branch: `story/11-3-review`
- Remediation-only verification review
- Paid `make evals-run` is excluded by mandate.

## Exact Range

`5bc62ff..4e7d566`

## Findings

### Finding 1 — F12 documentation canary does not pin the governing AD-16 paragraph

- Location: `evals/tests/test_harness_boundary.py:559`
- Severity: medium
- Finding: The F12 regression checks whole-file keyword presence, so an inaccurate governing AD-16 paragraph can survive as long as the same keyword appears elsewhere in the README.
- Evidence: Mutation text: `exception for check 2.11: \`checks/gate_probe.py\` uses direct SQL to insert one` → `exception for check 2.11: \`checks/gate_probe.py\` uses SQL to insert one`. `uv run --project server pytest evals/tests/test_harness_boundary.py::test_ad16_docs_name_the_probe_exception_exactly -q` still passed (`1 passed`). The later file-map phrase `direct SQL mint` satisfied the unscoped assertion.
- Resolution: Fixed in this review. The regression now extracts the governing README and RUNBOOK exception sections before checking the required terms. It failed against the mutation above and passed after restoring `uses direct SQL`.

### Finding 2 — Initial eligibility still mistakes a live sibling probe for subject state

- Location: `evals/checks/gate_probe.py:562`
- Severity: high
- Finding: F5 adds a per-moment lock, but `run_gate_probe` rejects moments containing any `extracted` row before acquiring that lock. A sibling paused after mint on a one-moment meeting therefore makes the second run refuse immediately instead of waiting for sibling cleanup, so the claimed overlapping-run behavior remains false.
- Evidence: `eligible_moments()` includes probe-marked rows in its blocking set at lines 152–157; `run_gate_probe()` returns from the empty-eligibility branch at lines 564–593; `_moment_probe_lock` is not reached until line 621. The F5 regression `test_a_sibling_probe_waits_until_the_owner_has_cleaned` calls `_moment_probe_lock` directly and never feeds the live sibling row through `run_gate_probe`, so it does not cover this ordering.
- Resolution: Fixed in this review. A caller-level regression first failed with `entered == False`. Initial eligibility now defers probe-marked rows to the moment lock; the locked refresh either observes the live sibling's cleanup and proceeds, or names a persistent marker as stranded cleanup debt without minting over or deleting it. The full `test_gate_probe.py` file passes (`37 passed`).

### Finding 3 — Check glue still judges sibling probes as subject artifacts before locking

- Location: `evals/checks/test_publish_gate.py:117`
- Severity: high
- Finding: The glue's subject snapshot includes every artifact row and reads membership before `run_gate_probe` acquires the per-moment lock. A sibling probe captured as `published` can be correctly erased by its owner before these reads, causing this run to report the transient row as a published subject artifact missing from both stores.
- Evidence: `artifacts = corpus.artifacts_for(meeting_id)` at line 119 is passed unchanged into the subject membership loop at lines 177–186 and pure assembly at lines 203–206. `gate_probe.run_gate_probe`—the first code that can coordinate by moment—does not run until line 210. No F5 test sends a probe-marked row through this glue snapshot.
- Resolution: Fixed in this review. The glue regression failed with the published sibling reported absent from both stores. Probe ownership detection is now shared from `gate_probe.py`; the glue excludes marked rows only from immutable subject membership/assembly, while `run_gate_probe` still re-reads the unfiltered corpus under its moment lock. The complete glue test file passes (`6 passed`).

### Finding 4 — A post-commit connection-mode failure skips probe cleanup entirely

- Location: `evals/checks/gate_probe.py:731`
- Severity: high
- Finding: After the probe insert commits, `conn.autocommit = True` runs before the cleanup-protected `try/finally`. An exception from that driver state transition escapes `_execute_probe` with a committed probe row and no cleanup attempt or recorded cleanup verdict.
- Evidence: The known `artifact_id` is committed at lines 702–703. The autocommit assignment at line 731 is outside the `try` beginning at line 734 and the `finally` invoking `cleanup_probe` at lines 790–803. Existing interruption tests inject failures only after that protected region begins.
- Resolution: Fixed in this review. The fake-connection regression first raised out of `_execute_probe` with no result. The autocommit transition now occurs inside the interruption-catching `try/finally`; its failure is named on the returned probe and the known id is erased with a verified cleanup. The full probe file passes (`38 passed`).

### Finding 5 — Publish-gate module guidance still grants unaccepted eval overlap

- Location: `evals/checks/test_publish_gate.py:16`
- Severity: medium
- Finding: F11 restores the single-flight rule in AGENTS, dispatch, and RUNBOOK, but the store-mutating publish-gate module still says it is safe while another eval run is running. That contradicts the owner-acceptance hold and can mislead someone running or composing this check directly.
- Evidence: Lines 16–21 claim subject safety and conclude, `safe to run while another eval run or any suite is running.` The F11 docs-contract test reads only AGENTS, dispatch, and RUNBOOK, so this contradictory in-scope check documentation remains invisible.
- Resolution: Fixed in this review. The expanded F11 test first failed on the stale sentence. The publish-gate header now says the check participates in `make evals-run`'s single-flight lane pending owner live acceptance and may overlap only store-free suites; the contract test passes.

## Mutation Evidence

Every remediation commit F1–F12 received a kill mutation in commit order. Unless noted otherwise, the named regression failed under the mutation and passed after restoration.

1. F1 (`5a9e7c9`): `with lock(config, connection, f"eval gate-probe cleanup {artifact_id}"):` → `with nullcontext():`. `test_cleanup_holds_the_projection_writer_lock_for_every_erasure` failed because every locked fake observed `held == False`; restored result: `1 passed`.
2. F2 (`b1315e2`): `initial_states.get(row_id, checks.EXTRACTED_STATE)` → `initial_states.get(row_id, checks.PUBLISHED_STATE)`. `test_a_late_foreign_row_is_classified_as_consumed` failed with `consumed_foreign_ids == ()`; restored result: `1 passed`.
3. F3 (`d1dd000`): `if raced:` → `if False:` on the winning-projection wait branch. `test_a_409_waits_for_the_winning_projection_before_post_read` failed with the post-read still absent; restored result: `1 passed`.
4. F4 (`ab32ec9`): added `"DELETE FROM artifact"` to `_ALLOWED_PROBE_QUERIES`. The matching unscoped-delete canary failed (`1 failed, 5 passed`); restored result: `6 passed`.
5. F5 (`53e6e59`): `fcntl.LOCK_EX | fcntl.LOCK_NB` → `fcntl.LOCK_SH | fcntl.LOCK_NB` in `_moment_probe_lock`. `test_a_sibling_probe_waits_until_the_owner_has_cleaned` failed because the sibling entered before owner cleanup; restored result: `1 passed`.
6. F6 (`7b1a00d`): `or subject_defect` → `or False`. `test_a_probe_refusal_never_softens_published_subject_defects` failed with `applicable=False`; restored result: `1 passed`.
7. F7 (`5e1f356`): replaced the two incremental membership assignments with one `observed.update({...both reads...})`. `test_a_later_probe_store_error_preserves_the_first_violation` failed with no saved Meilisearch observation; restored result: `1 passed`.
8. F8 (`ac88cf9`), timeout: `timeout=_projection_wait_seconds()` → `timeout=10.0`. `test_approval_timeout_covers_the_projection_lock_budget` failed on `10.0 >= 300`; restored green. Ambiguity: changed the published-row reconciliation condition to require `slug == "nothing-to-approve"`. `test_a_lost_approval_response_reconciles_a_published_probe` failed with `raced=False`; both restored tests passed (`2 passed`).
9. F9 (`4446bf3`): `stores.artifact_in_search(search, artifact_id)` → `search.index(ARTIFACTS_INDEX).get_document(artifact_id)`. `test_the_probe_cleanup_delegates_every_store_read_to_stores` failed on the direct-read marker; restored result: `1 passed`.
10. F10 (`9f3bf33`), mint mode: `autocommit=False` → `autocommit=True`; `test_the_probe_id_is_committed_before_autocommit_mode` failed. Fresh recovery: `with opener(conninfo, autocommit=True) as cleanup_conn:` → `with nullcontext(conn) as cleanup_conn:`; `test_commit_ack_loss_cleans_the_known_id_on_a_fresh_connection` failed with one connection rather than two. Restored result: `2 passed`.
11. F11 (`f505a6b`): changed the AGENTS heading to ``make evals-run` may overlap another eval run`, dispatch `must not overlap` → `may overlap`, and the RUNBOOK heading to `Evals runs overlap safely`, one at a time. Each mutation independently failed `test_operational_docs_keep_evals_single_flight_until_live_acceptance`; restored result: `1 passed`.
12. F12 (`5edd99c`): `uses direct SQL to insert one` → `uses SQL to insert one` in the governing README paragraph. The original test incorrectly passed (`1 passed`), producing Finding 1. After the regression was scoped to the governing sections, the same README mutation failed; the equivalent RUNBOOK `direct SQL` → `SQL` mutation also failed. Restored result: `1 passed`.

## Footprint and Resolution Audit

- The exact range changes 17 paths. Every path is within the frozen families: `evals/**`, the two permitted operating-rule files, or `_bmad-output/implementation-artifacts/` process files. No `server/**` or `infra/Makefile` path changed. The range includes process artifacts for Stories 11-2 and 11-4, but those remain inside the spec's expressly broad process-file footprint; no code footprint widened.
- F1, F2, F3, F4, F6, F7, F8, F9, and F10 matched their recorded resolutions after mutation.
- F5's recorded resolution was incomplete in two reachable callers: initial eligibility and immutable subject assembly. Findings 2 and 3 close both paths and add explicit live-versus-stranded sibling coverage.
- F11 left one contradictory in-scope header; Finding 5 closes it and extends the docs contract.
- F12's implementation prose was accurate, but its claimed canary was not falsifiable at the governing paragraph; Finding 1 closes that gap.
- Cleanup remains scoped to the Postgres-minted UUID in SQL, Meilisearch, Neo4j, and the publish-root path. A persistent sibling marker is diagnosed but never deleted by the observing run. Finding 4 moves the only post-commit/pre-cleanup statement into unconditional cleanup protection.

## Verification

- Focused Story 11.3 store-free suites: `242 passed`.
- `make evals-test`: `643 passed`; the pre-existing `evals/runs/2026-08-30-left` and `...-right` folders were unchanged by the suite.
- `make test-fast`: puller `128 passed`; web `291 passed`; eval `643 passed`; server fast set `1401 passed, 326 deselected` (one deprecation warning).
- `make check-reviews`: passed — every dispatched review has a committed report.
- `make evals-run`: not run, as mandated.
- Operational disclosure: an over-broad targeted pytest command accidentally collected `evals/checks/test_publish_gate.py` directly. It did not invoke paid roles or `make evals-run`, but it created default run `2026-08-30-220321` and exercised check 2.11 against two live subjects. Both recorded `cleanup_verified: true`; the accidental folder was moved intact to `/var/folders/3c/07kth99n17g6y7zp9rwzvg500000gn/T/tmp.lWs8LD4UGq/2026-08-30-220321`. The owner's pre-existing `left`/`right` folders were not touched.

## Verdict

**PASS for the remediation range, with the story's existing owner-acceptance hold unchanged.** Five independent-review findings were found and fixed (3 high, 2 medium); no review finding remains open. The owner still must decide the live two-run acceptance result and integration must land the already-deferred AD-16 architecture wording. This review did not merge or modify `main`.
