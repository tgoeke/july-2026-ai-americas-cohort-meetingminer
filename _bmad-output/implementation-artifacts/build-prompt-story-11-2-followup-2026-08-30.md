# Owner/Builder Handoff — Story 11-2 Remediation Follow-up

## Review identity

- Repository: `/Users/devopsterus/current/cohort/meetingminer`
- Reviewed branch: `story/11-2`
- Dispatched reviewed head: `e331fb6e26c785ee02952bc5e56208c6887c6165`
- Primary reviewed range: `ebbcd6c5ae887707e741aaefd7a12b1b0d20788d..e331fb6e26c785ee02952bc5e56208c6887c6165`
- Context range: `a011695dedf1135bf0bb27df1b2c76a40990dc99..e331fb6e26c785ee02952bc5e56208c6887c6165`
- Review/remediation branch: `story/11-2-followup-review`
- Review report: `_bmad-output/implementation-artifacts/review-story-11-2-followup-2026-08-30.md`

The source branch had already moved to `9a30e69` when the review worktree was created; the immutable dispatched ranges above are the code that was reviewed. The review branch contains ten red/green fixes plus the persisted verdict. It is pushed and deliberately unmerged; the owner runs integration for the wave.

## Review verdict

**Story 11-2 does not pass review as it stands.** Ten patch findings are fixed on the review branch, but one unresolved high-severity behavior needs an owner contract decision before any further patch is valid. The spec and sprint tracker are therefore `in-progress`.

## Decision required before any builder acts

### Finding 10 — effective Compose identity differs from claimed identity

- Anchor: `infra/Makefile:626`
- Problem: `check-stack` claims the project name and incarnation id declared by `.env.worktree`, while the following Compose command honors process overrides for `MM_STACK_NAME` and `MM_STACK_ID`.
- Concrete failure: in linked checkout `probe`, `MM_STACK_NAME=meetingminer-victim make infra-up` returned 0 after claim reported `no stale stack meetingminer-probe`; Docker then received `compose ... -p meetingminer-victim ... up -d --wait`. The effective victim project—including `meetingminer`—was never ownership-checked. An id override can also cause the next start to classify this checkout's newly created volumes as stale and delete them.
- Required outcome: the identity proven by claim and the identity started by Compose must be identical, and a main or foreign effective project must never reach `up` from a worktree.
- Owner choice: either (A) make generated `MM_STACK_NAME` and `MM_STACK_ID` non-overridable safety fields while retaining process precedence for permitted port/endpoint fields, or (B) preserve their process precedence and define claim/refusal behavior over the effective values. The existing frozen intent accepts process-environment precedence generally, so a builder must not choose between A and B.

Do not patch Finding 10 until the owner records the choice in the Story 11-2 contract. Once chosen, write a regression first and observe the dispatched behavior fail as described above, then implement and run it green.

### Finding 11 — architecture authority omits incarnation identity

- Anchor: `docs/architecture.md:109` (AD-10)
- Problem: AD-10 permits secrets, two roots, a private-stack name, and host ports in environment state, but the remediation makes `MM_STACK_ID` a required generated environment field stamped onto five containers and seven volumes.
- Concrete mismatch: removing `MM_STACK_ID` fails every ownership-record validator, while AD-10 has no allowance for this label-backed identity.
- Required outcome: architecture authority must say exactly whether the generated incarnation id is part of the private-stack environment allowance.
- Routing: owner/integration or the in-flight Story 8-1 AD-10 lane. `docs/architecture.md` was outside this review's 18-file remediation scope, and conflict analysis now reports `story/11-2 × story/8-1` on that file. Do not edit it from a builder lane without owner coordination.

This is an architecture/documentation contract alignment, not permission to broaden environment-owned adapter configuration.

## Already fixed on `story/11-2-followup-review` — no builder action

The report carries full five-field evidence and red/green commit history for these closed findings:

1. Removal/prune could route `down -v` through a copied target record.
2. A process name override could mask a copied record from the pytest session guard.
3. Make directives, ignored lines, and duplicate assignments bypassed the ownership-record grammar.
4. Same-target provisioners could publish two incarnation ids.
5. `worktree-remove` accepted path traversal in `STORY`.
6. `make down` in a linked checkout with no record targeted the main stack.
7. The application loader accepted another worktree's copied record.
8. `worktree-prune` returned success after Git failed to remove a candidate.
9. The prior ownership-recheck regression did not exercise the second check; it is now mutation-proved red/green.
12. Slug/project/id regexes accepted a trailing newline.

Do not reimplement or duplicate these patches. Integrate the review branch after resolving the two owner decisions.

## Required verification after the owner-directed fix

Never run `make evals-run`.

1. Add the Finding 10 regression and observe it fail against the unfixed effective-identity path before implementing the owner-selected contract.
2. Run:
   - `uv run --project server pytest server/tests/test_worktree_stack.py server/tests/test_config.py server/tests/test_compose_contract.py -q`
   - `uv run --project server pytest -m "" server/tests/test_makefile_procs.py server/tests/test_projections_locks.py server/tests/test_parallel_store_safety.py -q`
   - `MM_REQUIRE_TEST_STORES=1 uv run --project server pytest -m "" server/tests/test_projections_search.py::test_configured_projection_stores_are_reachable -q`
   - `uv run --project server pytest server/tests --co -q | tail -1`
   - `make check-env`
   - `make check-test-stores`
   - `make test`
   - `make check-reviews`
   - `git diff --check`
3. Commit and push the owner-directed red test, green fix, contract/architecture update, and final status changes. Do not merge; the owner integrates the wave.

The follow-up review's completed baseline was 296 passed/1 deselected in the fast trio, 112 passed in the slow review trio, 1984 server tests, 128 puller tests, 291 web tests, 549 eval-harness tests, and a successful web build.

## Explicitly out of scope

- Frozen `<intent-contract>` changes other than the owner decision above.
- Per-worktree api/web ports (B-35).
- Eval-run serialization or namespaces (Story 11-3).
- `docs/project-record.md` and eval documentation.
- Reopening the previously accepted process-wide projection lock key, external `MM_ENV_PATH`, host-preserving port overrides, remote/arbitrary twin endpoints, per-session Neo4j containers, Meilisearch prefixes, or Compose memory caps without new evidence.
- Merging any story or review branch, changing `main`, or resolving other wave lanes' conflicts from this lane.
