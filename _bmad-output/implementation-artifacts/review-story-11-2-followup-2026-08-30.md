# Follow-up Code Review — Story 11-2, Per-Run Store Isolation

## Scope

- Remediation follow-up for Story 11-2.
- In-scope files and frozen-intent boundaries are those supplied in the review dispatch.
- Review lane: `story/11-2-followup-review` in its isolated worktree.

## Review Range

- Primary range: `ebbcd6c5ae887707e741aaefd7a12b1b0d20788d..e331fb6e26c785ee02952bc5e56208c6887c6165`
- Context range: `a011695dedf1135bf0bb27df1b2c76a40990dc99..e331fb6e26c785ee02952bc5e56208c6887c6165`
- Review target: `story/11-2` at `e331fb6e26c785ee02952bc5e56208c6887c6165`.
- The source branch had moved to `9a30e69` when this review worktree was created; the dispatched ranges above remain the review boundary.

## Findings

### Finding 1 — Worktree removal trusts an unvalidated target stack name

- **Location:** `infra/Makefile:382`
- **Severity:** high
- **Finding:** `worktree-remove` reads `MM_STACK_NAME` from the target checkout with `sed`, removes that checkout, and passes the unvalidated name to `down`; `down` proves only that the name matches `meetingminer-<slug>`, not that the project belongs to the removed checkout or carries its incarnation id. A copied or tampered target file can therefore route `down -v` to another live worktree's stack.
- **Evidence:** With target `x/.env.worktree` declaring `MM_STACK_NAME=meetingminer-victim`, `git worktree remove x` succeeds and the subsequent call is `worktree_stack.py down --project meetingminer-victim`. Direct execution of the current `down("meetingminer-victim")` with inventory reporting a container observed `removed stack meetingminer-victim` and issued `docker compose -p meetingminer-victim down -v --remove-orphans`; it requested no worktree path, expected id, volume layout, or ownership evidence.
- **Suggested direction:** Before removing the checkout, validate its complete ownership record against its directory and preserve the expected stack id; teardown should re-inventory under the provisioning lock and remove volumes only when the project's recognised resources all carry that id. A missing or invalid record, a foreign owner/layout, or an id mismatch must leave the stack intact and return non-zero.
- **Red regression:** `test_worktree_remove_refuses_a_target_file_that_names_another_stack` failed at `assert proc.returncode != 0`: the observed command returned 0, removed the `probe` checkout, printed `removed stack meetingminer-victim`, and reached the victim project's `down -v` path. The batch twin, `test_worktree_prune_refuses_a_target_file_that_names_another_stack`, failed at the same assertion: it pruned both checkouts and reported `removed stack meetingminer-victim` twice.
- **Resolution:** Fixed on the review branch. Both removal targets validate an existing ownership record before removing the checkout, preserve its stack id, and call a teardown that re-inventories the recognised layout under the provisioning lock. Teardown now refuses a foreign checkout or mismatched resource labels; the documented id-less fallback remains limited to the expected directory and recognised volume layout.
- **Green verification:** Both red regressions and 17 focused `down` tests passed; the combined `test_worktree_stack.py` + `test_makefile_procs.py` run reached 197 passes before exposing one test-fixture setup error, whose corrected three affected status-propagation cases then passed.

### Finding 2 — A process override can hide a copied stack file from the test-session guard

- **Location:** `server/tests/conftest.py:237`
- **Severity:** high
- **Finding:** `linked_worktree_refusal` compares the expected checkout name with `merged_env`, after process-environment precedence has overwritten the file's `MM_STACK_NAME`. A copied file can therefore pass the directory-ownership check while its unoverridden twin URLs still select the source worktree's destructive test stores.
- **Evidence:** In checkout directory `probe`, a structurally valid copied file declaring `MM_STACK_NAME=meetingminer-other` and the `other` worktree's twin URLs is accepted when the process exports only `MM_STACK_NAME=meetingminer-probe`: `_validate_worktree_env` validates the copied file, `merged_env` replaces its name from the process, and `linked_worktree_refusal` returns `None`; `_STACK_ENV` then keeps the copied `MM_TEST_NEO4J_URI` and `MM_TEST_MEILI_URL`, which the projection fixtures wipe.
- **Suggested direction:** Validate and compare the name declared by `.env.worktree` itself against the checkout directory before applying process overrides. Keep the frozen process-environment precedence for runtime endpoints, but do not use an overridable merged value as proof that the ownership record belongs to this checkout.
