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
- **Red regression:** `test_linked_worktree_refusal_cannot_be_masked_by_a_process_name_override` failed at `assert message is not None`; the observed guard result was exactly `None` for a copied `meetingminer-other` file masked by `MM_STACK_NAME=meetingminer-probe`.
- **Resolution:** Fixed on the review branch. The config module now exposes the validated file declarations before process precedence; the session guard compares that source record with the directory while retaining `merged_env` for base-file validation and runtime endpoint precedence.
- **Green verification:** The red regression, the existing linked-worktree semantics test, and all of `test_config.py` passed: 117 tests.

### Finding 3 — Non-assignment Make syntax bypasses the ownership-record guard

- **Location:** `infra/Makefile:25`
- **Severity:** high
- **Finding:** The parse-time guard extracts only assignment-shaped keys, then `-include`s the entire file. Non-assignment directives, Make expansion expressions, and duplicate assignments are invisible to the guard; the Python parser likewise ignores non-assignment lines and overwrites duplicate keys, so the advertised whole-file schema is not actually shared or closed.
- **Evidence:** Appending `include /tmp/override.mk` or `$(eval ROOT := /elsewhere)` to an otherwise valid `.env.worktree` produces no `WT_ENVFILE_FOREIGN` key, and Make executes it during `-include` before `check-env`. Appending a non-assignment line is skipped by `parse_env_lines`; repeating a canonical key overwrites its first value in the returned dict. Thus a file can contain executable Make syntax while `validate_env_file` and `merged_env` still see only the expected final key set.
- **Suggested direction:** Before inclusion, parse the file as data with the same strict ownership-record grammar used by both Python readers: only blank/comment lines and one assignment for each canonical key, with no duplicate, directive, expansion, or ignored line. Any syntax error must stop Make at parse time before the file is included.
- **Red regression:** `test_a_stack_file_make_directive_is_refused_before_include_executes_it` failed at `assert proc.returncode != 0`: `make help` returned 0 and printed the full target list after including the injected file. The reader matrix also failed: the script did not raise for `include /tmp/override.mk`, and the loader did not raise for that line or a duplicate `MM_STACK_NAME`.
- **Resolution:** Fixed on the review branch. Both Python readers now reject every non-comment/nonblank line that is not a data assignment and reject duplicate keys. Make runs the stdlib validator at parse time and includes the file only when that check is silent, so directives and expansions never execute first.
- **Green verification:** The eight focused script/loader/Make regressions passed, `make help` accepted the real generated record, and the fast infrastructure/config/compose group passed with 288 tests (1 expected deselection). The later full slow process module exposed one pre-existing partial-record fixture that the stricter schema correctly refused; after converting that fixture to the canonical complete record, its store-port assertion passed.

### Finding 4 — Same-target provisioners can publish two incarnation IDs

- **Location:** `infra/worktree_stack.py:483`
- **Severity:** medium
- **Finding:** `provision` checks whether `.env.worktree` exists before acquiring `.provision.lock`, but does not recheck after it gets the lock. Two concurrent provisions of the same absent target both pass the outer check; the waiter then overwrites the first caller's complete record with a new stack id.
- **Evidence:** Caller A and caller B both observe no file. A acquires the lock and atomically publishes id A; after A releases, B acquires the lock, allocates again, and `os.replace`s the record with id B because lines 492–497 contain no inside-lock existence check. Concurrent `worktree-start` calls can consequently claim/start different incarnations, with one treating the other's just-created resources as stale.
- **Suggested direction:** Recheck for the record immediately after acquiring the provisioning lock; if present, validate it for the target slug and return it unchanged. Only the lock holder that still observes absence may allocate and publish a new id.
- **Red regression:** `test_provision_rechecks_the_target_after_acquiring_the_lock` injected the first caller's valid publication at lock acquisition and failed at `assert written is False`; the waiter returned `written=True` and replaced the first record.
- **Resolution:** Fixed on the review branch. A provisioner now rechecks and validates the target record immediately after acquiring `.provision.lock`; a record published while it waited is returned unchanged with `written=False`.
- **Green verification:** The red regression and the complete `test_worktree_stack.py` suite, including the subprocess lock mutation test, passed: 129 tests.

### Finding 5 — `worktree-remove` accepts a path traversal instead of a slug

- **Location:** `infra/Makefile:394`
- **Severity:** high
- **Finding:** Unlike creation and start, `worktree-remove` checks only that `STORY` is nonempty. A traversal-shaped value can resolve `$(WT_ROOT)/$(STORY)` to a different linked checkout; because that target's own ownership record is valid for its actual directory, the new validation and owned teardown both approve deleting it.
- **Evidence:** With an existing `$(WT_ROOT)/victim`, `STORY=../meetingminer-wt/victim` resolves back to that checkout. `worktree_stack.py check --worktree <resolved victim>` validates `meetingminer-victim`, `git worktree remove` removes the victim checkout, and the hardened `down` sees the victim's expected path/id and removes its volumes. No guard compares the user input with `SLUG_RULE` before path construction.
- **Suggested direction:** Apply the exact creation/start slug validation before any target path or branch name is derived in `worktree-remove`; invalid input must perform no Git or Docker action.
- **Red regression:** `test_worktree_remove_refuses_path_traversal_before_git_or_docker` failed at `assert proc.returncode != 0`: the observed command returned 0, removed the real `victim` checkout through `../meetingminer-wt/victim`, printed `removed stack meetingminer-victim`, and completed its owned `down -v` teardown.
- **Resolution:** Fixed on the review branch. `worktree-remove` now applies the same anchored slug rule as creation and start before deriving a filesystem or branch path.
- **Green verification:** All six `worktree-remove` process tests passed, including the red traversal regression.

### Finding 6 — `make down` can stop the main stack from an unprovisioned worktree

- **Location:** `infra/Makefile:987`
- **Severity:** high
- **Finding:** `down` has no linked-worktree ownership-record prerequisite. If `.env.worktree` is missing, Make silently resolves `MM_STACK_NAME` to `meetingminer`, so invoking `make down` inside that worktree targets the main checkout's containers—the exact unsafe fallback that `check-env` blocks on every start path.
- **Evidence:** In a real linked checkout with `.git` as a file and no `.env.worktree`, the Make defaults select `COMPOSE ... -p meetingminer`; with Docker available, `down` invokes that compose command and its project-name fallback is also `docker compose -p meetingminer down`. The target reaches Docker without running `check-env` or any equivalent ownership-state check.
- **Suggested direction:** Give teardown a record-state guard that runs before host-process stops or Docker: linked worktrees must have a valid directory-owned `.env.worktree`, main must have none. Keep the frozen unreadable-`.env` fallback by separating this ownership check from the secret-file readability checks used by startup.
- **Red regression:** `test_down_refuses_a_linked_worktree_without_an_ownership_record` failed at `assert proc.returncode != 0`: `make down` returned 0 from an actual linked checkout with no record after printing only the three pidfile notes; its Docker log contained the main-project compose teardown.
- **Resolution:** Fixed on the review branch. The linked/main checkout ownership-state check is now a standalone prerequisite shared by `check-env` and `down`, so teardown refuses before stopping host processes or invoking Docker while its unreadable-`.env` project-name fallback remains available for a valid owner.
- **Green verification:** The red regression, main-checkout unreadable-`.env` fallback, valid worktree teardown, and process-precedence compose tests all passed: 4 tests.

### Finding 7 — The application loader accepts another worktree's ownership record

- **Location:** `server/meetingminer/config.py:899`
- **Severity:** high
- **Finding:** The loader validates `.env.worktree` structurally but deliberately omits the directory/name ownership check. An API or worker loaded directly in linked checkout `probe` therefore accepts a copied, fully valid `meetingminer-other` record and connects to the other worktree's Postgres, Neo4j, and Meilisearch ports; only Make and pytest have the directory guard.
- **Evidence:** Beside `probe/.env` with `probe/.git` as a linked-worktree file, a complete `good_stack_text("other")` passes `merged_env` and returns `MM_STACK_NAME=meetingminer-other`, `MM_POSTGRES_PORT=20001`, and the copied twin URLs. `load_config` subsequently applies those copied store ports without consulting the checkout name, so direct server entrypoints read/write the wrong stack.
- **Suggested direction:** When the resolved `.env` actually lives at a Git checkout root, bind a present ownership record to that root: linked worktrees require `MM_STACK_NAME=meetingminer-<directory>`, and a main checkout must not carry the record. Preserve the accepted external `MM_ENV_PATH` behavior for env files outside a checkout root.
- **Red regression:** `test_loader_refuses_another_worktrees_record_at_a_linked_checkout_root` failed with `Failed: DID NOT RAISE ConfigError`: the loader accepted the complete `meetingminer-other` record beside `probe/.env` even though `probe/.git` identified a linked checkout.
- **Resolution:** Fixed on the review branch. The application-side ownership-record reader now binds a record to a linked checkout's directory name and refuses any record beside a main-checkout `.git` directory; env paths outside a checkout root retain the frozen external-path semantics.
- **Green verification:** The red regression and the complete config module passed: 118 tests.

### Finding 8 — `worktree-prune` reports success when Git cannot remove a candidate

- **Location:** `infra/Makefile:428`
- **Severity:** medium
- **Finding:** The prune loop sets `rc=1` for invalid ownership and failed Docker teardown, but the `git worktree remove` branch has no failure arm. If Git refuses after the earlier clean snapshot, the target continues, may attempt branch deletion, and finally exits 0 even though the checkout and its stack remain.
- **Evidence:** For a clean, landed `probe` candidate, an injected `git worktree remove <probe>` exit 1 leaves the checkout present. The recipe's `if ...; then` body is skipped, no statement changes `rc`, and `done; exit $rc` returns success; this can occur without injection when the tree changes or Git metadata becomes unavailable between the status check and removal.
- **Suggested direction:** Treat a failed Git removal as a named non-zero candidate failure, leave both its branch and stack intact, continue sweeping other candidates, and propagate the aggregate status at the end.
- **Red regression:** `test_worktree_prune_propagates_git_worktree_removal_failure` failed at `assert proc.returncode != 0`: an injected `git worktree remove` exit 23 printed its failure, but `make worktree-prune` returned 0 while the checkout, branch, and stack all remained.
- **Resolution:** Fixed on the review branch. A failed Git removal now names the kept candidate, sets the aggregate failure status, and gates branch deletion on successful checkout removal; the sweep can continue without misreporting completion.
- **Green verification:** The red Git-removal regression and the existing failed-Docker-teardown prune regression both passed.

### Finding 9 — The ownership-recheck regression does not exercise the recheck

- **Location:** `server/tests/test_worktree_stack.py:972`
- **Severity:** low
- **Finding:** The test claimed to close prior finding 7 by proving ownership is re-resolved immediately before teardown, but it creates worktree `b` while tearing down `a`. Even the pre-fix loop first evaluates `b.present_owner` only after that creation, so the test passes without the newly added second check and cannot prevent its removal.
- **Evidence:** The red-test commit itself records that “present_owner was already evaluated lazily per iteration, so no red was observable for that half.” In the committed scenario, `_CreatingDocker` creates `owner_b` during `meetingminer-a`'s down; both the parent implementation (one check) and remediation (two checks) then skip `b` at their first ownership evaluation, yielding the same assertions.
- **Suggested direction:** Trigger directory creation after the target stack's first ownership evaluation but before its final teardown check, and mutation-prove that deleting the second check makes the regression fail by issuing `down -v` for that target.
- **Red regression:** With the production second check locally reverted to the dispatched pre-fix shape, the strengthened `test_prune_rechecks_ownership_immediately_before_teardown` failed at `assert ws.prune(...) == []`: the observed result was `['meetingminer-b']`, and the fake Docker received that target's teardown after its owner directory appeared.
- **Resolution:** Fixed on the review branch. The regression now creates the owner immediately after the same stack's first `present_owner` evaluation, so only the final recheck prevents teardown; the red commit mutation-removes that production check and the green commit restores it.
- **Green verification:** With the final ownership check restored, the strengthened regression and the complete worktree-stack module passed: 129 tests.

### Finding 10 — `claim` proves one project while Compose starts another

- **Location:** `infra/Makefile:626`
- **Severity:** high
- **Finding:** `check-stack` always claims the raw ownership record's project/id, but the subsequent `COMPOSE` command honors process-environment precedence for `MM_STACK_NAME` and `MM_STACK_ID`. A valid worktree file can therefore pass ownership proof for `meetingminer-probe` and then start or recreate `meetingminer-victim` (including `meetingminer`) without ever inventorying that effective project; an id override also makes the next start classify this checkout's newly created volumes as stale and delete them.
- **Evidence:** In a real throwaway linked `probe` checkout with its generated record, running `MM_STACK_NAME=meetingminer-victim make infra-up` returned 0. The observed Docker sequence inventoried globally for `claim` and printed `no stale stack meetingminer-probe`, then invoked `docker compose ... -p meetingminer-victim ... up -d --wait`; no ownership check was performed for `meetingminer-victim`. The final compose environment carried the victim name while retaining `probe`'s allocated ports.
- **Suggested direction:** The project name and incarnation id used by ownership proof and Compose must be identical for every start. If process overrides of safety identity remain supported, claim the effective values and refuse main/foreign ownership before `up`; otherwise classify these two generated ownership fields as non-overridable while preserving the frozen precedence for the port/endpoint overrides.
- **Status / owner question:** Open and intentionally unfixed. The dispatched exclusions explicitly accept process-environment precedence over `.env.worktree`; choosing whether `MM_STACK_NAME`/`MM_STACK_ID` are exceptions changes that frozen behavior, while allowing them requires a new effective-identity claim contract. Which behavior owns the contract?

### Finding 11 — AD-10 omits the new environment-owned incarnation identity

- **Location:** `docs/architecture.md:109`
- **Severity:** low
- **Finding:** AD-10 says environment variables carry only secrets, the two roots, a checkout's private-stack name, and published host ports. The remediation adds `MM_STACK_ID` as an environment-owned, persisted compose-label identity, so the authority no longer says exactly what the code does.
- **Evidence:** Every generated `.env.worktree` now requires `MM_STACK_ID=<12 hex>`, Make exports it to Compose, and all five services and seven volumes interpolate it into `com.meetingminer.stack-id`; omitting it fails validation. The AD-10 sentence still ends its environment allowance at “private-stack name and the host ports its stores publish,” with no identity field.
- **Suggested direction:** Amend AD-10's single environment allowance to include the checkout stack's generated incarnation identity, narrowly describing the label-backed safety identity without admitting general adapter bindings or a second human-authored config source.
- **Status / owner question:** Open and intentionally unfixed. `docs/architecture.md` is architecture authority but is outside the dispatched 18-file remediation scope; should the owner amend AD-10 during integration, or explicitly treat the id as metadata implicit in “private stack”?

### Finding 12 — Stack identity regexes accept a trailing newline

- **Location:** `infra/worktree_stack.py:166`
- **Severity:** low
- **Finding:** The remediation made the projection lock key strict after a trailing-newline finding, but the analogous slug, project-name, and stack-id validators still use `re.match` with `$`. Python lets `$` match immediately before a final newline, so these safety identities are not exact despite their anchored-looking patterns.
- **Evidence:** Direct calls on the dispatched implementation observed `_SLUG_RE.match("probe\n")`, `_PROJECT_RE.match("meetingminer-probe\n")`, and `_STACK_ID_RE.match("aaaaaaaaaaaa\n")` all return matches while the corresponding `fullmatch` calls return false. Consequently `validate_slug("probe\n")`, `_is_worktree_project("meetingminer-probe\n")`, and `render_env(..., "aaaaaaaaaaaa\n")` accept inputs outside the documented grammar.
- **Suggested direction:** Use full-string matching for every slug/project/incarnation identity check in both stdlib and application validators, with newline/CR regression rows mirroring the projection-lock fix.
- **Red regression:** The focused newline/CR matrix produced three failures: `test_bad_slug_is_refused_by_name[probe\n]` and `test_render_refuses_a_stack_id_with_trailing_control_characters[0123456789ab\n]` both failed with `DID NOT RAISE StackError`; `test_a_prefix_with_an_invalid_slug_is_not_a_worktree_project[meetingminer-probe\n]` failed because `_is_worktree_project` returned `True`.
- **Resolution:** Fixed on the review branch. All slug, project-name, and incarnation-id validators in the stdlib stack tool and application loader now use full-string matching.
- **Green verification:** The newline/CR regressions and the complete worktree-stack plus config modules passed: 253 tests.

## Review Outcome

- **Verdict:** Changes requested — not ready to integrate while Finding 10 remains an unresolved high-severity owner decision.
- **Triage:** 12 confirmed findings: 10 patch findings fixed on this review branch; 2 decision-needed findings left open by contract/scope (`Finding 10`, high; `Finding 11`, low); no deferred findings.
- **Prior remediation assessment:** The production fixes for the ten dispatched findings hold under the exercised adversarial cases after this lane's patches. The claimed ownership-recheck regression for prior finding 7 was not discriminating; Finding 9 replaces it with an observed mutation-red test. The new effective-identity gap in Finding 10 prevents approval even though the original ten checklist rows are otherwise closed.
- **Story status:** `in-progress` in the spec and sprint tracker because unresolved high-severity behavior remains. No merge was performed.

## Final Verification

- `uv run --project server pytest server/tests/test_worktree_stack.py server/tests/test_config.py server/tests/test_compose_contract.py -q` — **296 passed, 1 deselected**.
- `uv run --project server pytest -m "" server/tests/test_makefile_procs.py server/tests/test_projections_locks.py server/tests/test_parallel_store_safety.py -q` — **112 passed**.
- `MM_REQUIRE_TEST_STORES=1 ... test_projections_search.py::test_configured_projection_stores_are_reachable` — **1 passed** against this worktree's twins; `make check-test-stores` independently passed the same required reachability gate.
- `uv run --project server pytest server/tests --co -q | tail -1` — **1612/1984 collected, 372 deselected**.
- `make check-env` — passed for this worktree's validated ownership record.
- `make test` — after the documented one-time `make bootstrap` installed missing worktree-local puller/web dependencies: puller **128 passed**, web **291 passed**, eval harness **549 passed**, server **1984 passed** in 579.13s, production web build succeeded.
- `git diff --check` — passed.
- `make evals-run` was not run (paid judge role, expressly excluded).
