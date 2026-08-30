# Review — Story 1.2: Source-Drop Intake Endpoint

- date: 2026-08-18
- content reviewed: current `HEAD` (`43e24dd`) for the Story 1.2 scoped files, against the frozen block in `spec-1-2-source-drop-intake-endpoint.md`
- original scope reference: commit `41bf5a9`; findings anchor to today’s namespaced paths
- lenses: adversarial (12 signals), edge-case-hunter (2), verification-gap (1), acceptance-auditor (0)
- exclusions: the three pre-recorded Story 1.2 deferred items and Story 1.10 config/namespace/Makefile work

Findings confirmed by more than one independent lens are marked (xN).

## Intake acceptance verification

1. **Canonical `.vtt`-only drops have no executable acceptance test (x2 — adversarial and verification-gap).** `transcript.vtt` is one of the three canonical evidence files accepted by the intake check (`server/meetingminer/api/ingests.py:76,150-158`), but endpoint tests cover only `transcript.txt` (`server/tests/test_ingests.py:27-48`) and `recording.mp4` (`:51-55`). The schema test merely checks that the filename appears in descriptive prose (`server/tests/test_drop_schema.py:98-101`). Demonstration: removing `transcript.vtt` from `EVIDENCE_FILENAMES` makes a valid VTT-only drop fail with 422, yet `make test` still passed with **154 passed, 1 warning**. Fix: add a DB-backed `POST /ingests` test with `files=("transcript.vtt",)` that asserts 201 and the queued job/checkpoint result.

## Read-model consistency

2. **`GET /jobs/{id}` can combine two committed states during a failed-job requeue.** The endpoint reads the job (`server/meetingminer/api/jobs.py:52-56`) and its stages in a second statement (`:59-62`). PostgreSQL’s default Read Committed isolation takes a new snapshot per statement. If a requeue transaction commits between them, a caller can receive the old failed job state paired with freshly reset queued stages, which contradicts the endpoint’s status-plus-checkpoints read model. Fix: read both data sets under one repeatable-read transaction or use a single query/statement that returns the job and ordered stages from one snapshot; add a concurrent requeue/read regression test.
