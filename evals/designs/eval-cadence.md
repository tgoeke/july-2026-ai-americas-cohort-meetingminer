# Design: Eval Cadence (eval-design §5)

**Status: the capstone run is committed; everything past it is documented
only.** Deferred per `docs/architecture.md` ("design
everything, build the slice"). The contract of record is `eval-design.md` §5;
this file expands its two lines into the full cadence design. Nothing here is
tooling — a cadence is a rule about *when* `evals/RUNBOOK.md` is executed, so
"implementing" any trigger below means running the runbook, not writing code.

## The capstone run (committed)

**One full pre-demo run**, in a fixed position in the epic's sequence:

```
judge bake-off (§7, if the LLM judge harness is built)
        ↓
ONE full eval run — RUNBOOK.md steps 1–8, verdict recorded
        ↓                            ↺ on FAIL: fix, then a fresh run
demo-script work begins                (rerun rule — new folder, from step 1)
```

- **After the bake-off**, so the winning judge model is pinned going into the
  run and its exact id/version lands in the run metadata. If story 5.4 (the
  judge harness, a nice-to-have) is not built, the bake-off prerequisite
  dissolves with it and the run proceeds deterministic + human only.
- **Before any demo-script work** — a sequencing constraint, not a
  preference. The SPEC states it as a Constraints bullet ("Sequencing: the
  eval harness and all its setup are completed before demo-script work
  begins", `SPEC.md` Constraints); the **NFR12** label for it comes from the
  planning artifacts (`docs/project-record.md`), which is
  where that numbering lives — no file under `docs/` uses NFR
  numbers. The eval run is the gate the demo scripts wait behind, so the demo
  is built on a measured pipeline rather than the pipeline being tuned to the
  demo.
- **A FAIL does not open the gate.** "One full run" names the position in the
  sequence, not a single attempt: a FAIL verdict is recorded, the cause is
  fixed, and the rerun rule produces a fresh run folder from step 1 —
  demo-script work waits on a *recorded PASS*, however many runs that takes.
- Its verdict is recorded per RUNBOOK.md step 6, and epic 5's success test
  (CAP-7: recall 100%, guardrail holds) is read off that verdict.

## Documented-only cadence (product, not capstone)

Two trigger classes, both expressed as instances of the runbook's rerun rule
(step 8): a trigger fires → any prior verdict is stale → a fresh run folder,
from step 1. No scheduled/calendar cadence is defined — every run is caused by
a change or a gate, because a run on an unchanged pipeline can only reproduce
the verdict it already has.

### 1. Change-triggered runs

A full run is required after any change to what the pipeline *does* to
evidence:

| Trigger | Why it invalidates |
|---------|--------------------|
| Any extraction/summarization **prompt change** | The planted-item checks (2.6, 2.7) measure prompt behavior directly |
| Any **screenshot-algorithm change** (capture selection, dedup, view classification, OCR engine or its configuration) | Checks 2.1–2.4 measure exactly this surface; the config snapshot exists so the engine travels with the number it produced |
| Any **pipeline-stage change** beyond those two, an **embedder change**, or a **judge-model change** | The runbook's step-8 list; §4.7 |
| Any **threshold change** (§6) | Recorded in `verdict.md`; all prior verdicts invalidated |
| Ground-truth manifest or retrieval-ground-truth companion change | The expected population/denominator changed |
| Scripted corpus, recording, capture evidence, or source/job identity change | The measured inputs no longer establish the old result |

The discipline: the change lands, the runbook runs in a new folder, and the
new verdict — not the stale one — is what any claim about the pipeline cites.

### 2. The go-to-production gate run

Before **any delivery** (a release, a handover, anything leaving the dev
machine), one full runbook execution against the then-current pipeline, with a
recorded PASS. This is the change-triggered rule applied cumulatively: however
many small changes accrued since the last verdict, delivery is what forces the
re-measure. A delivery may reuse an existing PASS only with explicit
input-integrity evidence. This is a **future artifact, not implemented now**:
`input-integrity.yaml` beside that run's artifacts will minimally contain:

```yaml
version: 1
ground_truth_sha256: {<relative-path>: <sha256>}
config_snapshot_sha256: <sha256>
subjects:
  - manifest: <id>
    source_id: <id>
    meeting_id: <id>
    job_id: <id>
    evidence_complete: {state: <bool>, revision: <opaque revision>}
```

At delivery, recompute and compare every listed value; a missing artifact,
unavailable evidence, tuple change, serialized evidence-complete state or
revision change, or hash difference requires a fresh run. Unchanged pipeline
code alone never proves an old PASS reusable.

## Data sources

The cadence consumes and produces only runbook artifacts: `evals/runs/<run-id>/`
folders, their `verdict.md` files (which carry threshold changes), the future
`input-integrity.yaml` evidence described above, and the git history of the
pipeline (which is what answers "has a trigger fired since the last verdict?").

## What implementing requires

The capstone needs nothing beyond executing the runbook at its slot. The
documented-only cadence, if ever automated, needs: a change-detection hook
mapping commits touching prompt/capture/embedder/judge configuration to a
"verdict stale" flag, and a delivery checklist entry demanding a fresh PASS.
Both are process before they are code, and neither is capstone scope.
