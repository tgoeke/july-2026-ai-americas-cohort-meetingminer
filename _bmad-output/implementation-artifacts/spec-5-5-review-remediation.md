---
title: 'Story 5.5 Review Remediation: Executable Final Verdicts'
type: 'bugfix'
created: '2026-08-20'
status: 'done'
baseline_commit: 'af3c1242635167a08264e8e297eced84adcfac66'
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Story 5.5’s operator documentation misstates a few current-system behaviors and promises that a human can overrule deterministic evidence even though the immutable deterministic report alone controls PASS. Its deferred check designs also leave several future algorithms non-deterministic or impossible to satisfy.

**Approach:** Make the runbook accurate and executable; add a store-free final-verdict evaluator that records auditable human overrides without altering the deterministic report; and sharpen the four documented-only designs so later implementers have one unambiguous contract.

## Boundaries & Constraints

**Always:** Preserve `deterministic-report.yaml` and `Run.passed` as a factual deterministic record. A generated final verdict may PASS only when every failed applicable blocking result has exactly one valid human `pass` override, there is no human `fail`, and no report-integrity problem exists (run-level problem, zero subjects, missing required check, or inapplicable blocking result). Overrides must identify `(manifest, check)`, carry a reason, and be visible with report/human-artifact hashes in the immutable final verdict. Keep the harness an AD-16 client; all new tests are store-free.

**Ask First:** Any request to let a human override a report-integrity problem or to make a final PASS operator-authored rather than evaluator-generated.

**Never:** Mutate the deterministic report to encode a human ruling; reopen/overwrite an existing `verdict.md`; add store, server, infra, or web implementation; make any documented-only retrieval/action/citation design runnable in this remediation; or infer unavailable meeting-view evidence from a directory scan.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|---------------|---------------------------|----------------|
| Human clears a failed applicable blocking check | Valid human YAML contains one targeted `pass` override with a reason | Finalizer writes an immutable PASS only if all other final-PASS conditions hold | Wrong, duplicate, missing, or non-failed target rejects finalization |
| Deterministic report is incomplete | Run-level problem, no subject, required-check omission, or inapplicable blocking check | Finalizer produces/returns FAIL regardless of human rulings | Report the named integrity reason; no override may suppress it |
| Human artifact is incomplete | Wrong run, missing metadata/worksheet, invalid item or no reconciliation | No verdict is written | Refuse before closing the run folder |
| Human evidence cannot be inspected | No current app drill-down/replay evidence for a worksheet item | Item is recorded fail/block with reason; it is not silently omitted | Finalizer prevents a PASS with that fail |

</frozen-after-approval>

## Code Map

- `evals/harness/run.py:52-55,225-350` -- run-artifact constants, immutable folder behavior, and deterministic-only `Run.passed`; keep its meaning unchanged and expose shared report facts if needed.
- `evals/conftest.py:193-201` -- deterministic report is written at pytest teardown, so finalization must be a separate post-suite entry point.
- `evals/harness/checks.py` and `evals/harness/checks.py:REQUIRED_CHECKS` -- existing blocking/applicability records the final evaluator must validate, not reinterpret.
- `evals/harness/verdict.py` (new) -- typed human-artifact loading, final-PASS evaluation, immutable Markdown writer, and `python -m` CLI.
- `evals/tests/test_final_verdict.py` (new) -- store-free evaluator and refusal tests; extend existing run-artifact tests only for shared constants/immutability.
- `evals/RUNBOOK.md:38-58,202-223,277-478` -- storage roots, retry semantics, worksheets, human-artifact audit, generated verdict, and complete rerun rule.
- `evals/README.md:140-150` -- correct failed-job requeue explanation while retaining Story 5.5 pointers.
- `evals/designs/{citation-timestamp-window,action-item-fuzzy-match,retrieval-eval,eval-cadence}.md` -- documented-only contracts to make deterministic and feasible; no new check module or fixture.
- `server/meetingminer/api/ingests.py:756-789`, `server/meetingminer/config.py:704-772`, and `web/src/App.tsx:91-96` -- read-only evidence for the runbook; do not edit.

## Tasks & Acceptance

**Execution:**
- [x] `evals/harness/verdict.py`, `evals/harness/run.py` -- add a post-suite finalizer that validates versioned `human-verdicts.yaml`, accepts one targeted override for each failed applicable blocking result, rejects integrity failures and writes `verdict.md` once with source hashes.
- [x] `evals/tests/test_final_verdict.py`, `evals/tests/test_run_artifacts.py` -- cover a valid human override, no-override/human-fail failures, malformed or mismatched YAML, duplicate/nonblocking/passing targets, report-integrity failures, hashes, and overwrite refusal.
- [x] `evals/RUNBOOK.md`, `evals/README.md` -- correct intake/root facts; replace unavailable meeting-view instructions with report-first, current replay/search guidance and explicit unavailable-evidence failure; require worksheet reconciliation; invoke the finalizer; document generated PASS/FAIL and all code/config/ground-truth/corpus/evidence invalidators.
- [x] `evals/designs/citation-timestamp-window.md` -- define one top citation per `qa`, a signed nearest-edge delta, result states, and hard no/wrong/ambiguous-citation failures.
- [x] `evals/designs/action-item-fuzzy-match.md` -- specify maximum-cardinality threshold-qualified matching, then maximum score and deterministic tie-breaks.
- [x] `evals/designs/retrieval-eval.md`, `evals/designs/eval-cadence.md` -- constrain topic probes to feasible top-k sets; name the future versioned retrieval-ground-truth companion and canonical comparison projection; require input-integrity evidence before PASS reuse.
- [x] `_bmad-output/implementation-artifacts/spec-5-5-eval-runbook-documented-only-designs.md`, `review-story-5-5-2026-08-20.md` -- mark accepted review items resolved only after implementation and record the expanded remediation scope.

**Acceptance Criteria:**
- Given a deterministic blocking failure and a complete matching human `pass` override, when the finalizer runs, then deterministic `passed` remains false while generated `verdict.md` is PASS only if every final-PASS condition holds and contains the target, reason, and both artifact hashes.
- Given a run-integrity problem or invalid/incomplete human evidence, when finalization is attempted, then it cannot record a PASS or overwrite an existing verdict.
- Given an operator follows the runbook on today’s branch, when it reaches a human-inspection, root, or retry step, then every stated command and behavior exists and unavailable evidence is explicit rather than implied.
- Given the four design documents, when a later implementer reads their algorithms, then the result population, matching/ordering rules, source artifacts, feasibility bounds, and PASS-reuse invalidators are unambiguous without adding implementation now.

## Design Notes

The deterministic report is evidence, not the final adjudication. Keeping it immutable allows a finalizer to show both what the harness measured and precisely which human judgement overrode a measured failure. Integrity failures remain non-overridable because they mean the system did not measure a complete run at all.

## Spec Change Log

- 2026-08-20: Approved review remediation expanded the former operator-authored
  final-verdict procedure into a store-free, generated, hash-audited finalizer
  with versioned human reconciliation. It also resolves the runbook factual
  corrections and makes the four deferred check designs deterministic and
  feasible without implementing them.

## Verification

**Commands:**
- `make evals-test` -- expected: all store-free eval tests pass, including final-verdict tests, and no `evals/runs/` directory is created.
- `uvx ruff check --isolated evals/` -- expected: clean.
- `git diff --name-only origin/main...HEAD -- infra server web` -- expected: empty for the remediation implementation.

**Manual checks:**
- Read the generated PASS and FAIL verdict examples against their deterministic and human YAML artifacts; confirm hashes and every override are auditable.
- Walk the runbook’s commands against the actual Makefile/config/CLI and confirm the documented-only designs do not claim new executable checks.

## Suggested Review Order

**Final verdict integrity**

- Validates immutable evidence, targeted human judgment, and non-overridable run integrity.
  [`verdict.py:269`](../../evals/harness/verdict.py#L269)

- Publishes completed verdicts exactly once and exposes PASS/FAIL to automation.
  [`verdict.py:375`](../../evals/harness/verdict.py#L375)

**Operator contract**

- Defines the versioned human artifact, advisory evidence, and reconciliation behavior.
  [`RUNBOOK.md:315`](../../evals/RUNBOOK.md#L315)

- Documents generated verdict criteria and the finalizer’s observable outcome.
  [`RUNBOOK.md:379`](../../evals/RUNBOOK.md#L379)

**Future-check precision**

- Pins citation population, signed distance, and malformed-span failure handling.
  [`citation-timestamp-window.md:21`](../../evals/designs/citation-timestamp-window.md#L21)

- Makes fuzzy matching deterministic under duplicate values and tied scores.
  [`action-item-fuzzy-match.md:25`](../../evals/designs/action-item-fuzzy-match.md#L25)

- Defines feasible retrieval ground truth and delivery-integrity evidence.
  [`retrieval-eval.md:129`](../../evals/designs/retrieval-eval.md#L129)
  [`eval-cadence.md:73`](../../evals/designs/eval-cadence.md#L73)

**Regression evidence**

- Exercises overrides, malformed evidence, atomic closure, and generated status.
  [`test_final_verdict.py:100`](../../evals/tests/test_final_verdict.py#L100)
