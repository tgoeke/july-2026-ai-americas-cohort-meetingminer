---
runScope: 'epic-level'
runKey: 'epic-1'
workflowStatus: 'completed'
totalSteps: 5
stepsCompleted: ['step-01-detect-mode', 'step-02-load-context', 'step-03-risk-and-testability', 'step-04-coverage-plan', 'step-05-generate-output']
lastStep: 'step-05-generate-output'
nextStep: ''
lastSaved: '2026-08-19'
inputDocuments:
  - '_bmad-output/planning-artifacts/epics.md'
  - '_bmad-output/implementation-artifacts/epic-1-context.md'
  - '_bmad-output/implementation-artifacts/sprint-status.yaml'
  - '_bmad-output/implementation-artifacts/spec-1-7-evidence-projections-rebuild-cli.md'
  - '_bmad-output/implementation-artifacts/spec-1-8-teams-puller-emits-source-drops.md'
  - '_bmad-output/implementation-artifacts/spec-1-9-ingestion-progress-in-the-ui.md'
  - '_bmad-output/implementation-artifacts/spec-1-10-development-environment-hardening.md'
  - '_bmad-output/implementation-artifacts/spec-1-11-screen-capture-retune-against-measured-baselines.md'
  - '_bmad-output/implementation-artifacts/spec-1-12-late-recording-augmentation.md'
  - '_bmad-output/specs/spec-meetingminer/SPEC.md'
  - '_bmad-output/specs/spec-meetingminer/capture-measurements.md'
  - '.agents/skills/bmad-testarch-test-design/resources/knowledge/risk-governance.md'
  - '.agents/skills/bmad-testarch-test-design/resources/knowledge/probability-impact.md'
  - '.agents/skills/bmad-testarch-test-design/resources/knowledge/test-levels-framework.md'
  - '.agents/skills/bmad-testarch-test-design/resources/knowledge/test-priorities-matrix.md'
  - '.agents/skills/bmad-testarch-test-design/resources/knowledge/nfr-criteria.md'
---

# Epic 1 Test-Design Run

Mode: Epic-level. The requester explicitly named Epic 1 and requested a UAT document.

Prerequisites confirmed: `_bmad-output/planning-artifacts/epics.md` defines Epic 1 and its stories; frozen story contracts and the Epic 1 context are available in `_bmad-output/implementation-artifacts/`. Architecture and UX context are available under `_bmad-output/specs/spec-meetingminer/`.

## Context loaded

The product is full-stack (React/Vite frontend and FastAPI/Postgres worker backend). Epic 1's user-visible surface is the meeting-ingestion list and its live progress/error presentation. The current sprint state marks stories 1.1–1.12 done and Story 1.13 in review, so the UAT covers Story 1.13 separately as a release-candidate check.

Existing automated coverage is concentrated in `server/tests/` (ingestion, pipeline, projections, augmentation, progress API/SSE, and environment cases) and `pull_transcript/test/` (drop emission). No browser E2E suite or Playwright configuration is present. `playwright-cli` is unavailable in this checkout, so browser exploration was not performed. The UAT must therefore provide manual web verification alongside API, CLI, and data-store checks.

Known scope boundary: Epic 2 has not started. The UAT validates that a completed meeting becomes *viewable* in the Epic 1 list, but does not claim a moment-detail/replay UI exists yet.

## Risk assessment

| Risk | Category | P | I | Score | UAT mitigation / release evidence |
| --- | --- | ---: | ---: | ---: | --- |
| An accepted drop is lost, duplicated, or partially ingested | DATA | 3 | 3 | 9 | Block release: exercise accepted, invalid, duplicate, and rerun paths; verify one job/meeting and preserved source files. |
| A late recording changes or invalidates existing moment/citation identity | DATA | 3 | 3 | 9 | Block release: take before/after IDs and counts around augmentation; confirm prior moments remain addressable. |
| A job is shown as ready before complete evidence exists | BUS | 2 | 3 | 6 | Confirm each stage progresses live, errors are visible, and no in-flight/failed record is marked View meeting. |
| Failure or restart silently drops a stage output | OPS | 2 | 3 | 6 | Use a controlled invalid media/input failure; check recorded stage/error, restart behavior, and source immutability. |
| Screens that carry evidence are missed or capture noise overwhelms the bundle | BUS | 2 | 3 | 6 | Review screenshots from a representative recording; verify capture rate, settled frames, and transition/gallery treatment. |
| Projection is stale, incomplete, or uses mismatched IDs | DATA | 2 | 3 | 6 | Compare a completed meeting in Postgres with Neo4j/Meilisearch; run a rebuild and compare again. |
| Puller emits an invalid or mutable source drop | DATA | 2 | 3 | 6 | Validate puller/backfill output with the same schema and verify re-pull does not overwrite finalized evidence. |
| Configuration and local-only service bindings fail on another Mac | OPS | 2 | 2 | 4 | Fresh-environment startup/check-env and health-panel checks; verify services bind to loopback. |

NFR evidence to collect: source/drop immutability; UUID and provenance retention; pipeline restartability; logs with job/stage correlation; full precompute gate; localhost-only stores; capture-density result; and rebuild reproducibility. No user-facing performance latency threshold is defined for this epic, so the UAT records observed duration only rather than asserting an invented limit.

## Coverage plan

The UAT is intentionally end-to-end and operator-facing; it does not duplicate unit or contract assertions already in the automated suites. P0 covers the local source-drop intake, transcript-only completion, UI readiness/progress gate, and late-recording augmentation. P1 covers failure/retry, Teams puller/backfill, evidence/provenance, capture review, and projections/rebuild. P2 covers environment resilience and edge cases. Story 1.13 receives a separately marked P1 release-candidate test while it remains in review.

Execution: run all automated functional suites in PRs when store access is serialized; run this UAT against a disposable development corpus before an Epic 1 release; run capture-density/manual visual review and a full projection rebuild only when using representative media or after capture/embedder/config changes. Estimate for one prepared UAT pass: 2–4 hours, plus recording-processing time; preparation or automation of the matrix would take approximately 2–4 working days.

## Output generated

Generated `_bmad-output/test-artifacts/test-design-epic-1.md`, a human-runnable Epic 1 UAT checklist. It contains 17 prioritized acceptance cases, a recording-backed/transcript-only evidence-bundle spot check, an explicit Story 1.13 release-candidate case, a run record, and release gate criteria. The document was checked for whitespace errors, required source references, and all 17 UAT case identifiers.
