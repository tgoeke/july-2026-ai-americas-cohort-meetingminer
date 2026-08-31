# Review — Story 6.4: Acquisition Launch Surface

## Scope

Adversarial review and report-first remediation of Story 6.4 on
`story/6-4-review`, limited to the story paths and tracking artifacts named in
the review handoff. Frozen intent defects will be reported but not patched.

## Range

- Baseline: `e5e0ff9`
- Story tip at review dispatch: `6269ad9`
- Review range: `e5e0ff9..6269ad9`
- Review branch: `story/6-4-review`, cut from `story/6-4`

## Findings

### F1 — The parent can overwrite a fast child's terminal status with `queued`

- **Location:** `server/meetingminer/acquisitions.py:684-713`
- **Severity:** High
- **Finding:** `launch()` starts the detached child and only afterwards writes
  the returned pid using its stale pre-launch `queued` record. The child does
  not take the claim lock before its first status transition, so it can write
  `running`, `posted`, or `failed` before the parent resumes from `Popen`; the
  parent's final write then regresses that newer state to `queued`. A fast
  `exists` acquisition can therefore appear queued forever and lose its
  `result`, job id, provenance, or refusal.
- **Evidence:** A direct scheduling reproduction replaced `Popen` with the
  behavior a fast child is permitted to exhibit: read the already-created
  record, write `posted/result=exists`, then return its pid. Unfixed
  `launch()` returned and stored `status=queued, result=None`, proving the
  terminal write was lost. The existing launch test substitutes `/bin/sleep`,
  which never writes acquisition state and cannot expose this interleaving.
- **Suggested direction:** Make the child's initial read/transition wait on
  the same claim lock the parent holds through its pid write, so the parent
  establishes `queued+pid` before the child can advance it. Add a deterministic
  concurrency regression that observes the child blocked until the parent
  releases the lock and proves a terminal transition is never overwritten.
