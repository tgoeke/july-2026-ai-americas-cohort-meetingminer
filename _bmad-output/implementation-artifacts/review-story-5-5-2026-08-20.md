# Code review — Story 5.5: Eval Runbook & Documented-Only Designs (2026-08-20)

**Verdict: request changes.** Review target: `origin/main...origin/story/5-5` at
`e0e7fddd885e529fe6bbb3feb788cc40980c8aad`.

## Findings

### Resolved decision — patch required

1. **[high] Human-final judgment must override the deterministic gate** —
   `evals/RUNBOOK.md:345` says human judgment wins a disagreement with a
   deterministic result, while `:370-379` makes `deterministic-report.yaml`’s
   `passed: true` and every-subject 2.1/2.2 pass mandatory. `Run.passed`
   (`evals/harness/run.py:327-337`) cannot become true through a human ruling.
   **User resolution:** human rulings override blocking deterministic failures.
   Define and implement auditable override semantics in the harness and verdict
   artifacts, then make the runbook describe that executable behavior.

### Patches

1. **[medium] Failed-job retry behavior is misstated** —
   `evals/RUNBOOK.md:217-221` says re-posting a failed drop runs only unfinished
   stages. `server/meetingminer/api/ingests.py:786-789` instead deletes and
   re-seeds all stage rows. Describe the full retry accurately.
2. **[high] Required human inspection surface does not exist** —
   `evals/RUNBOOK.md:289-300` directs worksheets 1, 2, and 4 to a meeting view,
   but `web/src/App.tsx:91-96` says the drill-down page is a later story. Add a
   current, runnable inspection route or mark the affected worksheets blocked.
3. **[medium] `MM_CONTENT_ROOT` is missing from run prerequisites** —
   `evals/RUNBOOK.md:48-58` names only the drops root, but the worker requires a
   usable content root (`server/meetingminer/config.py:704-740`). Document its
   absolute, writable requirement.
4. **[low] Quoted dotenv values defeat the manual path check** —
   `evals/RUNBOOK.md:56-58` passes quote characters to `test -d` for a normal
   quoted root. Use a quote-safe validation or the startup check.
5. **[medium] Human-verdict completeness has no operational audit** —
   `evals/RUNBOOK.md:337-365` checks only keys and `run:`. Before closing a
   verdict, require audit of judge/completion fields, record shape/reasons, and
   every candidate surfaced by machine reports so missing items cannot create a
   vacuous human PASS.
6. **[low] Citation result’s delta has contradictory sign semantics** —
   `evals/designs/citation-timestamp-window.md:28-30,63` computes a nonnegative
   distance but calls it signed. Define the sign or rename it.
7. **[medium] Citation population and hard-failure handling are underspecified** —
   `evals/designs/citation-timestamp-window.md:22,78-85` must define whether
   every citation or just the Q&A top citation is evaluated and how no/wrong
   citations are recorded.
8. **[medium] Greedy action-item matching can misclassify a valid set** —
   `evals/designs/action-item-fuzzy-match.md:40-48` needs maximum-cardinality
   threshold-qualified matching before score/order tie-breaking.
9. **[medium] Topic recall@5 lacks a feasible-set rule** —
   `evals/designs/retrieval-eval.md:35-43` must constrain expected meeting-set
   size, vary `k`, or specify a set-recall metric.
10. **[medium] Graph traversal expected-set data is not canonical** —
    `evals/designs/retrieval-eval.md:54-57,127-130` leaves its source shape and
    identity projection undecided. Define the canonical data artifact and tuple
    fields.
11. **[medium] Eval cadence overlooks changes to measured inputs** —
    `evals/designs/eval-cadence.md:44-80` must include ground-truth/corpus or
    evidence mutations and all runbook invalidators before allowing a PASS to
    be reused.

### Deferred

1. **[low] `evals/README.md:148-150` describes obsolete failed-job behavior** —
   it predates this branch’s pointer-only README edit and is recorded in
   `deferred-work.md` for a separate reference-documentation correction.

## Verification

- `make evals-test` — 341 passed in 0.51s; `evals/runs/` remains absent.
- `uvx ruff check --isolated evals/` — all checks passed.
- `git diff --name-only origin/main...HEAD -- evals/harness evals/checks evals/tests evals/conftest.py infra server` — empty.
- `git diff --numstat origin/main...HEAD -- _bmad-output/specs/spec-meetingminer/eval-design.md` — `2 0` (additive).

## Remediation Status — 2026-08-20

All accepted review findings are resolved by the approved 5.5 remediation:
the generated store-free finalizer preserves deterministic evidence and
requires versioned, complete human reconciliation; the runbook now describes
current retry, storage-root, inspection, and finalization behavior; and the
four documented-only designs now have deterministic result/matching/projection
and PASS-reuse contracts. Verification: `make evals-test` (355 passed) and
`uvx ruff check --isolated evals/` (clean).

## Confirmed sound

- The implementation boundary is intact: no harness, check, test, infra, or
  server code changed in the reviewed branch range.
- The eval-design companion change is additive only.
- The runbook correctly documents existing run-folder refusal/immutability and
  its overall-report gate tracks `Run.passed`; the remaining issue is the
  incompatible unqualified human-override promise.
