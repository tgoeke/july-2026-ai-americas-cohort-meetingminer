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
