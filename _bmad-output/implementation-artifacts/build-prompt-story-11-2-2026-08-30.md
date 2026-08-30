# Builder handoff — Story 11-2 follow-up remediation

Use `bmad-build-auto` to remediate the completed follow-up review of Story 11-2, Per-Run Store Isolation.

## Verdict and exact source

Story 11-2 **does not pass review as it stands**. Seven high/medium findings block merge. Three low findings are in-scope cleanup and verification work but do not independently block completion.

- Repository: `/Users/devopsterus/current/cohort/meetingminer`
- Implementation worktree: `/Users/devopsterus/current/cohort/meetingminer-wt/11-2`
- Implementation branch: `story/11-2`
- Reviewed head: `fa86b864c7101e2a45d2c278a9562669c72d962c`
- Baseline: `de0fc0816c26a8131fdc153368719e6f3808f40e`
- Reviewed range: `de0fc0816c26a8131fdc153368719e6f3808f40e..fa86b864c7101e2a45d2c278a9562669c72d962c`
- The implementation branch had not moved when review closed.
- Review artifacts branch: `story/11-2-review`
- Review artifacts head before this handoff: `d3792db`
- Review report: `/Users/devopsterus/current/cohort/meetingminer-wt/11-2-review/_bmad-output/implementation-artifacts/review-story-11-2-2026-08-30.md`
- Frozen spec: `/Users/devopsterus/current/cohort/meetingminer-wt/11-2-review/_bmad-output/implementation-artifacts/spec-11-2-per-run-store-isolation.md`

Work only in a dedicated worktree and branch. The existing `11-2` implementation worktree is clean at the reviewed head and owns a private Docker stack. Never edit the main checkout, never reset/stash/clean a shared tree, never `git add -A`, and never run `make evals-run`. Commit and push coherent fixes as they complete.

## Fix now — blocking safety themes

The four high findings are three remediation themes; the pruner theme has two independent destructive paths. Do not count them as unrelated architecture failures, but do close each path.

### 1. Worktree metadata must fail closed as one coherent ownership record

**Anchor:** `infra/Makefile:224-227`; `infra/worktree_stack.py:63-66,196-207,275-303`; `server/tests/conftest.py:206-244`

**Wrong behavior:** The Makefile and test-session guards accept any readable/existing `.env.worktree`. The provisioner requires only `MM_STACK_NAME` plus seven nonblank ports, does not require either test-twin URL, does not ensure the project name belongs to the requested slug, and does not reject malformed/duplicate ports, incoherent URLs, or foreign keys before keeping the file. Publication uses a non-atomic `write_text()`.

**Concrete failure:** A file truncated after the seventh port is accepted, then projection tests default to the main checkout twins at 7688/7701 and call `drop_all()` there. A still-shorter readable file leaves the worker on the main dev ports. A copied file naming another worktree can make provision/start/removal target that other stack. The reviewed suite explicitly treats a name-only file as sufficient at `test_worktree_stack.py:466-474`.

**Required outcome:** Every linked-worktree entry point validates one exact, coherent generated-file schema before any store connection or Compose action: expected stack name for the checkout, seven valid and distinct ports, twin URLs derived from the declared test ports, and no foreign keys. Interrupted publication must not create accepted state. Fail named and before writing.

### 2. The destructive pruner must prove ownership for names and volumes

**Anchors:** `infra/worktree_stack.py:359-360,379-420,424-476`

**Wrong behavior A:** `_is_worktree_project()` accepts any `meetingminer-` prefix instead of requiring the provisioner's valid slug suffix.

**Concrete failure A:** `meetingminer-Foo`, `meetingminer-.backup`, or `meetingminer-` with a missing working-directory owner is classified as a removable known stack and receives `docker compose ... down -v`, even though it cannot be a stack this tool provisioned.

**Wrong behavior B:** If containers provide any working-directory label, `worktree_stacks()` returns before validating the project's volumes.

**Concrete failure B:** A valid-prefix project with a missing owner path and `meetingminer-probe_foreign-data` is classified `unknown=False`; `prune()` deletes the foreign volume with `-v`, contradicting the module's leave-unknown-volumes-alone contract.

**Required outcome:** Only exact `meetingminer-<valid-slug>` candidates may enter pruning, and every candidate's discovered volumes must pass ownership recognition regardless of container presence. Foreign/malformed projects and any unknown volume layout must be reported and skipped, never torn down.

### 3. Pre-11.2 failure recovery must stay on the safe invoking Makefile

**Anchor:** `infra/Makefile:298-312`; `AGENTS.md:49-58`

**Wrong behavior:** Successful initial startup for `BASE=<pre-11.2-ref>` uses the new invoking Makefile, but both error messages send the user into the old checkout.

**Concrete failure:** After provision failure, `cd <old-worktree> && make worktree-provision` cannot run because the target/script do not exist there. After Compose failure, `cd <old-worktree> && make infra-up` uses the old Makefile and starts the fixed main `meetingminer` stack; subsequent old tests can use and wipe main stores.

**Required outcome:** Both repair paths must be executable for an old ref and continue through post-11.2 Makefile/compose logic with the new worktree's env files and project directory. No documented retry may enter old stack logic.

## Fix now — remaining blocking correctness findings

### 4. Docker-down creation must not revive a stale stack

**Anchor:** `infra/Makefile:289-312`; `server/tests/test_makefile_procs.py:1596-1612`

**Wrong behavior:** Docker-down creation skips the stale-project sweep, writes the worktree metadata, then documents a direct `infra-up` retry with no sweep.

**Concrete failure:** Reusing a slug whose abandoned project/volumes still exist silently attaches the new checkout to those volumes when Docker returns.

**Required outcome:** The retry path must perform the same stale-owner check and teardown as normal creation before Compose startup, while refusing any live owner.

### 5. Cleanup must never report success after inventory or teardown failure

**Anchor:** `infra/Makefile:272-281,354-375`

**Wrong behavior:** Failed `docker ps`/`docker volume ls` substitutions look like an absent stack. A failed `docker compose down -v` in `worktree-prune` can be masked by the following branch-delete command ending in `|| true`.

**Concrete failure:** The checkout/branch is removed and the target exits zero while the stack and volumes remain orphaned.

**Required outcome:** Inventory failures and teardown failures are named, nonzero, and propagated through both removal targets. A later cleanup command must not overwrite the failure status.

### 6. Pruning must not act on a stale owner snapshot during creation

**Anchor:** `infra/worktree_stack.py:275-303,424-476`; `infra/Makefile:284-312,587-592`

**Wrong behavior:** `.provision.lock` protects only allocation/publication. `prune()` neither shares it nor rechecks ownership immediately before `down -v`.

**Concrete failure:** `test-db-prune` can snapshot an abandoned `meetingminer-x`; a concurrent `make worktree STORY=x` can sweep it, create its owner, and start the replacement before the first pruner resumes and deletes the new live stack/volumes.

**Required outcome:** Creation and destructive pruning must be serialized where necessary and/or ownership must be authoritatively re-resolved immediately before every teardown. A directory that now exists always wins and is skipped.

## Fix now — non-blocking in-scope gaps

### 7. Verify actual provisioning-lock exclusion

**Anchor:** `infra/worktree_stack.py:275-303`; `server/tests/test_worktree_stack.py:116-127,171-182`

**Wrong behavior:** Tests prove that the lock file exists but not that it excludes concurrent allocators.

**Concrete failure mutation:** Removing the `flock` acquire/release leaves all reviewed tests green; two simultaneous slugs hashing to one base can both publish the same seven ports.

**Required outcome:** A coordinated multi-process regression forces the same starting base and proves the second creator sees the first publication and selects disjoint ports.

### 8. Reject a final newline in `MM_PROJECTION_LOCK_KEY`

**Anchor:** `server/meetingminer/projections/locks.py:58-76`; `server/tests/test_projections_locks.py:81-90`

**Wrong behavior:** `re.match()` with `$` accepts immediately before a final newline.

**Concrete failure:** `MM_PROJECTION_LOCK_KEY="b14-key\n"` passes the promised `[A-Za-z0-9._-]{1,64}` rule and puts a newline in the lock/holder filename.

**Required outcome:** Validate the entire value strictly and add newline-ending cases to the invalid-value regression table.

### 9. Put the concrete VM bound in every document named by the AC

**Anchor:** `README.md:351-355`; `project-context.md:102-108`; `docs/glossary.md:306-309`

**Wrong behavior:** These three files point to AGENTS.md rather than each stating the concrete OrbStack bound required by the frozen documentation AC.

**Concrete failure:** A reader of any one required document sees “AGENTS.md carries” the bound, not that OrbStack reports 23.5 GiB against the 128 GB host or what that means operationally.

**Required outcome:** State the measured OrbStack VM bound and its implication directly in README, project-context, and the glossary; AGENTS.md remains the detailed source.

## Specification assessment

No finding has a specification root cause. Do not amend the frozen intent or re-derive the story. The findings are implementation and verification gaps against explicit fail-closed, pruning-safety, recovery, concurrency, and documentation requirements.

## No action

The review dismissed 11 deduplicated candidates because they were explicitly by design, inside accepted residual risk, already assigned to another story/integration, or adequately tested at the relevant abstraction. In particular, do not widen this round to change:

- the process-wide nature of `MM_PROJECTION_LOCK_KEY`;
- process-environment precedence over `.env.worktree`;
- port-only endpoint overrides that preserve configured hosts;
- external `MM_ENV_PATH` semantics;
- per-worktree API/web ports (B-35);
- eval-run serialization/documentation (Story 11.3);
- `docs/project-record.md` (integration-owned);
- remote or arbitrary test-twin endpoint support;
- per-session Neo4j containers, Meilisearch prefixes, or Compose memory caps.

## Required ordering

1. Write red regressions for each current defect before changing production code. Confirm each regression fails against `fa86b86`; a new test that was never observed red does not count.
2. Establish the authoritative `.env.worktree` validator/publication contract first; Makefile, conftest, provision, recovery, and their tests all depend on it.
3. Repair the unified creation/retry path, including old-ref and Docker-down/stale-stack behavior.
4. Repair pruner ownership classification, then close the creation/prune race using the same ownership definition.
5. Repair cleanup status propagation after pruner behavior is stable.
6. Add the provisioning-lock contention test, strict lock-key validation, and documentation corrections.
7. Run all verification below, update the review checklist/status to done only when green, commit each coherent unit, and push `story/11-2`.

## Regression evidence required

For every new regression, first run it against the unfixed `fa86b86` behavior and record the observed failure in the final report. At minimum cover:

- stack files truncated before each twin URL, name-only files, wrong project names, invalid/duplicate ports, incoherent twin URLs, and foreign keys at every linked-worktree guard;
- atomic/interrupted publication behavior;
- malformed-prefix foreign Compose projects;
- container-backed candidates with foreign volumes;
- old-ref provision failure and old-ref Compose failure, proving the printed retry works and never targets `meetingminer`;
- Docker-down creation with a stale same-name stack/volume set;
- Docker inventory failure and `down -v` failure propagation in `worktree-remove` and `worktree-prune`;
- a coordinated stale-prune versus same-slug creation race;
- two concurrent provisioners forced to the same base;
- final-newline lock keys;
- the concrete OrbStack bound in all four required documents.

## Full verification gate

Run every command from the Story 11-2 worktree and its private stack. Never run `make evals-run`.

1. `uv run --project server pytest server/tests/test_worktree_stack.py server/tests/test_config.py server/tests/test_compose_contract.py -q`
2. `uv run --project server pytest -m "" server/tests/test_makefile_procs.py server/tests/test_projections_locks.py server/tests/test_parallel_store_safety.py -q`
3. `make worktree STORY=11-2-probe BASE=story/11-2`, then inspect `docker compose ls` and `docker ps`: main and probe projects must both be running five services on different ports.
4. Run `MM_REQUIRE_TEST_STORES=1 uv run --project server pytest -m "" server/tests/test_projections_search.py::test_configured_projection_stores_are_reachable` in the story worktree and the main checkout; each must resolve its own twin ports.
5. Run `time make test` alone, then concurrently in the story and probe worktrees. Both concurrent runs must exit zero, show no `ProjectionLockedError`, and have different lock paths. Record wall times.
6. Run `docker stats --no-stream` and record per-stack memory plus the OrbStack VM figure.
7. Reproduce the spec's orphan case on a disposable probe: deliberately hand-delete that probe directory without first running `git worktree remove`, run `make test-db-prune`, prove the probe stack/volumes are gone, owned stacks are skipped, and `meetingminer` is untouched, then run `git worktree prune` to clear the stale registration.
8. Run `make worktree-remove` on a disposable probe and prove its project and volumes are gone.
9. Run `uv run --project server pytest server/tests --co -q | tail -1` and `make check-test-stores`.
10. Run `make check-reviews`.

The original follow-up review observed 181 fast tests and 93 Makefile/lock/parallel-safety tests passing on the unfixed branch. Those green baselines do not cover the red regressions required above.

## Completion contract

Do not merge to `main` during remediation unless a fresh follow-up review passes. When implementation and verification are complete:

- check off the review findings in the story spec;
- set the story to `review`, not `done`;
- sync `sprint-status.yaml` to `review`;
- commit and push every changed path with exact SHAs in the report;
- request another independent `bmad-code-review` run.
