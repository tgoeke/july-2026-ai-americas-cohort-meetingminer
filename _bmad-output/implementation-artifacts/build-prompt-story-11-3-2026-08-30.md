# Builder remediation handoff — Story 11.3: Eval Runs Own Their Namespace

Agent: `bmad-build-auto`. This is a remediation pass after adversarial review.
The story **does not pass review as it stands**.

## Exact context

- Repository: `/Users/devopsterus/current/cohort/meetingminer`
- Story branch: `story/11-3` (reviewed through `644faa0`)
- Review branch: `story/11-3-review`
- Reviewed range: `211857c..644faa0`
- Review artifact:
  `_bmad-output/implementation-artifacts/review-story-11-3-2026-08-30.md`
- Final report commit: `4b80826`
- Frozen intent:
  `_bmad-output/implementation-artifacts/spec-11-3-eval-runs-own-their-namespace.md`

Create/use the Story 11.3 builder worktree, rebase the story branch onto current
`main` before the process-file edits, and preserve the frozen `<intent-contract>`.
The review changed no implementation code.

## Fix now — concurrency and ownership foundation

These findings interact and should be designed together before patching. The
result must make overlapping runs correct at the real API/store ordering, not
only under atomic fakes.

1. **Shared-store cleanup is outside the writer lock**
   (`evals/checks/gate_probe.py:246-278`). Cleanup directly deletes and verifies
   Neo4j/Meilisearch without the exclusion domain used by projection writers. A
   writer that already captured the published row can recreate the document or
   node after cleanup reports verified absence. Make the complete
   delete-and-verify sequence participate in the same lock domain and lock
   order, or retain a truthful single-flight rule against every dev-store
   writer. A successful cleanup verdict must remain true after concurrent
   projection work settles.

2. **The new-subject-row consumption window is silently missed**
   (`evals/checks/gate_probe.py:414-450,566-605`;
   `evals/harness/checks.py:1224,1296-1313`). The API publishes every extracted
   row on the moment, but detection only recognizes foreign ids present in an
   older snapshot. A row landing after eligibility is consumed and ignored.
   Prevent that ownership violation or classify every newly published foreign
   row from authoritative data tied to the request outcome. Do not misattribute
   rows another actor published independently.

3. **A 409 is judged before the winning projection finishes**
   (`evals/checks/gate_probe.py:520-523,583-602`). Postgres becomes `published`
   before post-commit graph/search projection. The loser can see a 409 and read
   absent/partial stores while the winner is healthy but still running. The
   losing path must reach a bounded terminal projection state before judging
   the positive half, and cleanup must wait until no winner can still write the
   owned id.

4. **Sibling probes are treated as subject artifacts**
   (`evals/checks/test_publish_gate.py:117-186`;
   `evals/checks/gate_probe.py:135-150,414-445`). A sibling paused after mint
   makes a one-moment meeting ineligible; a sibling paused after publish can be
   snapshotted as a subject then erased, producing a false absence. Add an
   ownership/coordination model that keeps transient probes out of immutable
   subject assertions and distinguishes live ownership from abandoned cleanup
   debt. Runs may serialize per shared target while still overlapping elsewhere.

5. **The approval timeout is shorter than lawful lock waiting**
   (`evals/harness/retrieval.py:32,184-203`;
   `evals/checks/gate_probe.py:566-603`). The client times out after 10 seconds
   while projection may wait 300 seconds. A timeout/lost response can start
   cleanup while the server request remains alive. Align the mutating call with
   the lock contract and reconcile every ambiguous POST outcome before cleanup.

Required regression tests (confirm each against the unfixed code first):

- Pause a projection after its authoritative Postgres read and before store
  writes; cleanup must not report success and later leave an orphan.
- Insert a subject row after candidate selection and before the API locks
  pending rows; it must not be consumed silently.
- Expose `published` while holding the winning store projection; the 409 loser
  must neither false-fail nor clean ahead of the winner.
- Pause a sibling after mint and after publish on a one-moment meeting; both
  runs must reach truthful outcomes with no transient probe treated as subject.
- Hold the projection lock beyond the old client timeout and drop a successful
  response after commit; reconciliation and final cleanup must remain correct.

## Fix now — verdict and recovery correctness

6. **Published-subject defects become NOT APPLICABLE**
   (`evals/harness/checks.py:1231-1262,1364-1377`). When the probe is
   unmeasurable, published absence/miscitation does not set the literal
   `GATE VIOLATION` marker and applicability stays false. Track measured subject
   defects structurally; every proven subject failure must stay applicable and
   eligible for normal reconciliation.

7. **Later store errors erase earlier evidence**
   (`evals/checks/gate_probe.py:366-370,493-528`;
   `evals/checks/test_publish_gate.py:173-196`). All-or-nothing dictionary
   construction drops a completed store observation when a later read raises.
   Accumulate observations and errors incrementally so a proven violation can
   never be softened into unmeasured state.

8. **Cleanup verification reads bypass the frozen read boundary**
   (`evals/checks/gate_probe.py:196-225,261-273`). Direct `get_document` and
   Neo4j verification queries violate the rule that reads live in
   `harness/stores.py` helpers. Route post-delete verification through the
   sanctioned read-only seam and make the boundary mechanically detect direct,
   duck-typed store reads in the probe module.

9. **Autocommit can strand a probe before its UUID is known**
   (`evals/checks/gate_probe.py:471-490`). If insert commits but `RETURNING`
   acknowledgement is lost, cleanup/report cannot name the row. Preserve the
   Postgres-minted id before an ambiguous commit, and reconcile/clean through a
   fresh connection if necessary. A unique run/subject ownership token is also
   acceptable if it keeps AD-6 identity intact.

Required regression tests (confirm against unfixed code first):

- Combine each probe refusal/interruption with published subject absence and
  citation mismatch; the result remains an applicable failure.
- Let the first store prove unpublished presence and the second raise, for both
  subject and probe paths; the violation survives.
- Prove post-delete reads use only the read-only store helper seam.
- Simulate commit acknowledgement loss with the inserted row visible to a
  second connection; cleanup identifies and removes it.

## Fix now — falsifiable boundary

10. **The write pin admits forbidden shapes**
    (`evals/tests/test_harness_boundary.py:396-478`). The scan is case-sensitive,
    allows any artifact insert, and drops the whole delete stem, so lowercase
    writes, published-state seeding, multi-row inserts, or bulk/unscoped deletes
    can keep the guard green. Pin the exact allowed mint and one-id delete/read
    statement shapes rather than blacklisting a few tokens. Include canaries
    for lowercase/mixed-case clauses, direct `published` seed, extra/multi-row
    inserts, missing `WHERE id`, unscoped Cypher, and bulk/index deletes.

## Fix last — operating and architecture documentation

These edits depend on the final concurrency and boundary mechanism. Do not
publish permissive operating guidance before the implementation tests pass.

11. **Concurrency guidance is both contradictory and unsafe**
    (`AGENTS.md:79,123-145`; `.claude/skills/integrate/dispatch.md:32-36`;
    `evals/RUNBOOK.md:98-107`). AGENTS still contains two serial rules while a
    new bullet and dispatch permit overlap and promise concurrent approval
    never fails. Keep the serial rule until the fixes are complete; afterward
    update every passage coherently and state exactly which writers/runs may
    overlap. The owner-gated live procedure must validate the final claim.

12. **The in-scope AD-16 explanation is false**
    (`evals/README.md:9-28,67-69`; `evals/RUNBOOK.md:44-46,98-100`). It still says
    all mutations are public-API-only, psycopg is confined to read-only
    `corpus.py`, and the probe is minted through the API. Document the exact
    direct-SQL mint, API approval, delete-only cleanup, and final read boundary.
    Keep the existing deferred architecture-spine amendment routed to
    integration; do not edit `docs/architecture.md` in this remediation.

## Routing

- Fix now: all 12 findings above.
- Defer: none from this review. Preserve the spec frontmatter's standing AD-16
  wording amendment for integration.
- No action: duplicate layer observations and mutation-test suggestions already
  subsumed by the requirements above.
- Specification-root findings: none. The defects violate the frozen intent;
  do not weaken the intent to accommodate them.

## Verification before returning to review

Run and report:

- `make evals-test` — must pass store-free and leave `evals/runs/` untouched.
- `uv run --project server pytest evals/tests evals/checks -q --collect-only`
  — collection must be clean.
- `make test-fast` — must pass.
- `python3 _bmad/scripts/branch_conflicts.py --against story/11-3` — report the
  exact current matrix; union known process-file conflicts at integration.
- Every new regression above must first be demonstrated against the unfixed
  code, then pass after remediation.

Do **not** run `make evals-run`, paid roles, the worker, rebuild, or `make up`.
Keep the final live two-run/store-orphan measurement in the spec for the owner.

## Scope guard

Allowed: the original Story 11.3 footprint (`evals/**`, the one AGENTS bullet
and dispatch step, sprint/spec/review process files; `infra/Makefile` recipe only
if genuinely needed). Forbidden: `server/meetingminer/**`,
`server/tests/conftest.py`, `docs/architecture.md`, and unrelated story files.
Do not merge. Return the story to review only after every finding is addressed,
the verification above passes, and all commits are pushed.
