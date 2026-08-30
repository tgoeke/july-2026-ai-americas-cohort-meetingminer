---
title: 'Eval Runs Own Their Namespace'
type: 'chore'
created: '2026-08-30'
baseline_revision: '5cdfce72813d68c2d81f5e02f715b8863f8492af'
status: 'in-progress'
review_loop_iteration: 0
followup_review_recommended: false
context: ['{project-root}/AGENTS.md']
warnings: ['multiple-goals', 'oversized']
deferred:
  - summary: >-
      AD-16's wording ("read-only store access") should gain the cleanup sanction this story builds: a delete-only module, scoped to ids the run minted, that erases the run's probe from both stores after the check's assertions complete.
    evidence: |-
      docs/architecture.md is outside this story's footprint (build prompt). The mechanism is pinned by evals/tests/test_harness_boundary.py's amended driver guard and the new delete-only stem pin; the spine sentence lands at integration.
    location: >-
      docs/architecture.md AD-16
    severity: medium
---

<intent-contract>

## Intent

**Problem:** `make evals-run` is the last serial rule (AGENTS.md: "one at a time"): check 2.11 approves each subject's `extracted` artifacts through `POST /moments/{id}/approve`, consuming shared state one-way — the next run finds `nothing-to-approve` — and its store writes land under ids the run does not own. The run folder also has a TOCTOU window: a racing `mkdir` reports "could not create" instead of the ownership refusal.

**Approach:** The publish-gate check stops mutating subject artifacts. Per subject it asserts membership read-only, then measures the gate on one run-owned **probe artifact** (title/body carry the run id) minted onto an already-projected subject moment that holds no `extracted` rows, approved through the public api, asserted in both stores, and erased afterward — Postgres row, publish-root export, Meilisearch document, Neo4j node — with cleanup verified and recorded in the report. `Run.create` refuses a lost `mkdir` race by name. Docs replace the serial rule with the measured truth (AGENTS.md and dispatch.md last, after rebase).

## Boundaries & Constraints

**Always:**
- Footprint: `evals/**`; `infra/Makefile` `evals-run` recipe only (unchanged is fine); optional NEW `server/tests/test_makefile_evals.py`; one sentence each in `AGENTS.md` and `.claude/skills/integrate/dispatch.md` (edited last, after `git fetch && git rebase origin/main`); `_bmad-output/implementation-artifacts/` process files. Nothing else.
- Never run `make evals-run`, `make up`, `make rebuild`, or the worker; never call the `chat`/`judge` roles. Prove behavior with `make evals-test` and store-free unit tests over fakes; the real concurrent measurement is written into `## Verification` for the owner.
- The run mutates only what it owns: the probe artifact row it minted (deleted on the way out), the store documents the api projected for that row (deleted by the new delete-only cleanup module), and the export file the api wrote (removed). Subject artifacts are never approved by the run; the shared corpus's `extracted` rows survive every run.
- The harness boundary stays falsifiable: `harness/stores.py` remains the only harness store-driver module and keeps its write-stem pin; the cleanup module lives in `evals/checks/`, is admitted by name in the amended driver guard, and gains its own textual pin allowing delete-shaped store calls only (no add/update/create/execute_write) — the check can erase its own probe but can never create membership it asserts.
- Probe approval races are tolerated by design: a 409 `nothing-to-approve` re-reads the probe row — if a concurrent approve published it, the gate was still exercised through the public api and the positive half is asserted; response rows for artifacts the run did not mint are ignored, never a divergence.
- Cleanup failure is loud: any leftover (row, file, document, node) is a named problem that fails the check and lands in the report with the exact ids.
- Every refusal names its cause (existing folder, non-scripted tag, no eligible moment, unprojected meeting, unreachable store); no silent fallback anywhere.

**Block If:**
- The approve route's projection turns out not to be all-or-nothing per call (graph write failure but search doc written), making the probe's post-assert unable to distinguish a gate defect from a partial write — that is a server-side finding this story may not fix.
- Ownership of the probe requires any edit under `server/meetingminer/**` or `server/tests/conftest.py`.

**Never:**
- No new api endpoint, no server code change, no `docs/architecture.md` edit (deferred note instead).
- No direct store *writes* beyond the pinned delete-only cleanup of run-minted ids; no store reads outside `harness/stores.py`'s read-only helpers.
- No approval of any artifact the run did not mint; no rebuild of a shared meeting as cleanup (a structural rebuild drops that meeting's vectors).
- No weakening of `Run.create`'s existing refusals or of the report-completeness rules.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Folder race | Two runs, same `--run-id`, `mkdir` collides after `exists()` said no | Loser gets the ownership refusal naming the folder ("a run gets its own folder") | `RunError`, never "could not create" |
| Probe happy path | Subject moment projected, no `extracted` rows on it | Pre-absent both stores → approve 200 publishes exactly the probe → post-present both stores citing the moment → cleanup verified | — |
| Concurrent approve | Second run's approve gets 409 `nothing-to-approve`; probe row re-reads `published` | Gate half recorded as measured-by-concurrent-approval; positive half asserted; cleanup proceeds | Detail names the race |
| Foreign rows in response | Approve response carries artifacts the run did not mint | Ignored for ownership asserts; recorded in detail | Never a divergence problem |
| No eligible moment | Every subject moment holds an `extracted` row, or no moments | Blocking not-applicable naming the state and the remedy | Check fails, run reports why |
| Meeting never projected | Chosen moment has no `Moment` node in the graph | Blocking not-applicable naming `rebuild --meeting <id>` | No seed, no approve |
| Subject `extracted` rows | Unconsumed extracted artifacts on other moments | Negative half asserted (absent both stores); states recorded; **no** approval, no divergence | — |
| Subject has no artifacts | `artifacts_for` returns () | Blocking not-applicable (unchanged §2.11 semantics — never a vacuous pass); probe outcome still recorded in detail | — |
| Cleanup leftover | Meili delete task fails / node survives | Named problem with ids; check fails; report says what to remove | Manual remedy named |
| Non-scripted tag | Corpus tag ≠ `scripted` | Existing refusal, unchanged, still before any write | No seed made |

</intent-contract>

## Code Map

- `evals/harness/run.py:243-259` -- `Run.create`: `folder.exists()` then `folder.mkdir(parents=True)`; generic `OSError` catch swallows the race. Catch `FileExistsError` first → the "already exists" refusal wording. `RUNS_ROOT`, `safe_name`, `VERDICT_NAME` unchanged.
- `evals/conftest.py` -- `run` (session) fixture: `run_id = --run-id or default_run_id(label)`; the probe layer reads `run.run_id` for its marker. `app_config` fixture is the config door (`meetingminer.config` allowance). No changes needed here beyond what the check glue consumes.
- `evals/harness/corpus.py` -- read-only psycopg (the only harness psycopg module — keep it that way). Has `artifacts_for`, `meeting_corpus`, `segments_for_moment`. ADD read-only `moments_for(meeting_id) -> tuple[MomentRow,...]` (id, identity_key) and `stage_status(meeting_id, stage) -> str | None` (job_stage via meeting.job_id) so probe eligibility is chosen from reads.
- `evals/harness/stores.py` -- read-only membership (`artifact_in_search`, `artifact_in_graph`, `search_client`, `graph_driver`). ADD read-only `moment_in_graph(driver, moment_id) -> bool` (label-agnostic `MATCH (m:Moment {id: $id})`). Must stay clean of `_STORE_WRITE_STEMS` (add_document/delete/update/create_index/execute_write) — the pin scans this file's text.
- `evals/harness/checks.py:856-1160` -- `StorePresence`, `ApproveOutcome`, `PUBLISH_GATE_THRESHOLDS`, `publish_gate_refusal` (unchanged), `publish_gate` (rework). New frozen dataclasses `GateProbe` (artifact_id, moment_id, pre/post membership, `ApproveOutcome`, `CleanupReport | None`, `problem: str | None`) and `CleanupReport` (per-target booleans + problems tuple). `publish_gate(meeting_id, artifacts, membership, probe)` new contract: subject rows read-only (non-published absent; published present + cited), probe carries the mutation sequence; drop the "extracted but no approval attempted" divergence and the "consumed lifecycle" branch; keep the no-artifacts blocking not-applicable and the GATE VIOLATION headline. Thresholds text updated to name probe ownership.
- `evals/checks/gate_probe.py` -- NEW, importable (not `test_`-prefixed). Owns: `_writable_conninfo` (mirror of `evals/checks/test_corpus_artifacts.py:38-53`), eligibility (moments via corpus reads, `extract` stage settled, no `extracted` rows on the moment, `moment_in_graph` true; choice spread by `hash(run_id, moment_id)` to de-collide concurrent runs), seeding one `artifact` row (`kind='action-item'` — no git path; title `eval-gate-probe-<run-id>`, body names run + manifest), approve via `evals.harness.retrieval.approve_moment`, ownership filter on the response, and cleanup: Meili `delete_document` on `artifacts` index + task wait, Neo4j `MATCH (a {id: $id}) DETACH DELETE a`, publish-root `action-item/<uuid>.md` unlink (`config.secrets.mm_publish_root`), Postgres `DELETE FROM artifact WHERE id = %s`; verify absence after each and report `CleanupReport`. Store-delete calls are the ONLY write-shaped store calls in `evals/` and only ever take the run-minted uuid.
- `evals/checks/test_publish_gate.py` -- rework glue: keep the remote-url guard, the corpus-tag refusal, the record-and-reraise `_record`/`_not_applicable` shapes; replace approve-the-subject with probe orchestration; single membership read per subject artifact (no mutation → no pre/post split for subjects); probe pre/post via `stores` helpers.
- `evals/tests/test_harness_boundary.py:268-289` -- driver guard `assert users == {"harness/stores.py"}` → add `"checks/gate_probe.py"` with rationale; ADD a delete-only stem pin for `gate_probe.py` (forbid `add_document*`, `update*`, `create_index*`, `execute_write*`; allow `delete_document`/`DETACH DELETE`) plus its guard-on-the-guard cases.
- `evals/tests/test_publish_gate_algorithm.py` -- rewrite the matrix for the new contract (clean sequence, violation headline, probe problems, cleanup failure, race tolerance, foreign rows ignored, no-artifacts branch, refusals unchanged).
- `evals/tests/test_publish_gate_check_layer.py` -- keep the remote-guard test; extend for probe-layer fakes (fake corpus, fake stores seam, `httpx.MockTransport` approve).
- `evals/tests/test_gate_probe.py` -- NEW: eligibility, marker format (run-id-prefixed), ownership filter, cleanup report, de-collision spread — all over fakes.
- `evals/tests/test_run_namespace.py` -- NEW: mkdir-race refusal (pre-create folder, monkeypatch `Path.exists` → False, expect the ownership wording), and that the refusal still names a closed (verdict-holding) folder distinctly.
- `evals/README.md:9-70, 208-300, 377-390`; `evals/RUNBOOK.md:98-134, 208-300, 549-556`; `evals/checks/__init__.py:10`; headers of `test_capture_checks.py`, `test_retrieval_checks.py`, `test_corpus_artifacts.py`, `test_publish_gate.py` -- replace "hold the shared Docker stores — one agent at a time" and the 2.11 consumes-state narrative with: reads are read-only and concurrent-safe; the one mutation is the run-owned probe, erased on exit; runs may overlap each other and any suite.
- `infra/Makefile:360-366` -- `evals-run` recipe: NO change required (prereqs and command already correct for concurrent runs); leave untouched, so `server/tests/test_makefile_evals.py` is not needed.
- `AGENTS.md` (post-rebase location) + `.claude/skills/integrate/dispatch.md` step 2 last line -- ONE sentence each, LAST: replace "`make evals-run` is still one at a time" with the measured truth (see Verification for what the owner measures).
- Boundary evidence: `graph.project_artifacts` (`server/meetingminer/projections/graph.py:521-535`) MERGEs Artifact + CITES matching existing `Moment` nodes — one transaction, missing Moment rolls back → probe MUST cite a projected moment. `approve route` (`server/meetingminer/api/moments.py:608-732`): publishes in Postgres first, then best-effort projection of exactly the published ids; returns every artifact under the moment. `rebuild` CLI has no retirement mode; api has no DELETE — hence the delete-only cleanup module. READ-ONLY references; none of these files change.

## Tasks & Acceptance

**Execution:**
1. `evals/tests/test_run_namespace.py` -- RED: race-refusal tests -- prove the TOCTOU wording gap first.
2. `evals/harness/run.py` -- catch `FileExistsError` in `Run.create` → ownership refusal (closed-folder wording when `verdict.md` exists) -- GREEN.
3. `evals/harness/corpus.py` + `evals/harness/stores.py` -- add the read-only helpers (`moments_for`, `stage_status`, `moment_in_graph`) with unit tests beside the existing ones (`evals/tests/test_store_asserts.py` patterns; fakes only).
4. `evals/harness/checks.py` -- RED algorithm matrix in rewritten `evals/tests/test_publish_gate_algorithm.py`, then implement `GateProbe`/`CleanupReport`/new `publish_gate` -- the pure core first.
5. `evals/checks/gate_probe.py` + `evals/tests/test_gate_probe.py` -- probe orchestration + cleanup over fakes -- the only store-write-shaped code, delete-only, run-minted ids only.
6. `evals/tests/test_harness_boundary.py` -- amend driver guard; add the delete-only pin + its self-tests -- the mechanism that keeps the sanction narrow.
7. `evals/checks/test_publish_gate.py` + `evals/tests/test_publish_gate_check_layer.py` -- rework glue and its store-free safety tests.
8. `evals/README.md`, `evals/RUNBOOK.md`, `evals/checks/__init__.py`, check-module headers -- rewrite the serial-rule and consumes-state narrative.
9. Rebase onto `origin/main`; then `AGENTS.md` + `.claude/skills/integrate/dispatch.md` -- one sentence each.
10. `_bmad-output/implementation-artifacts/sprint-status.yaml` -- `11-3-eval-runs-own-their-namespace: review`; note in `sprint-notes.md`; review prompt file.

**Acceptance Criteria:**
- Given an existing `evals/runs/<id>` folder created between the `exists()` check and `mkdir`, when `Run.create` runs, then it raises the ownership refusal naming the folder, not a generic create error.
- Given a subject with unconsumed `extracted` artifacts, when the run's 2.11 executes, then those rows are still `extracted` afterward and the check asserted only their absence from both stores.
- Given an eligible projected subject moment, when the probe runs against a fake api + fake store seams, then the recorded sequence is pre-absent → approve(own id only) → post-present-cited → cleanup verified, and every minted id appears in the result detail.
- Given a cleanup step that reports a leftover, when the result is assembled, then the check fails naming the id and target store.
- Given `make evals-test`, when run, then it passes store-free with no folder under `evals/runs/` created.
- Given the branch, when `python3 _bmad/scripts/branch_conflicts.py --against story/11-3` runs, then every pair except ones involving `story/11-2-review` is clean.

## Spec Change Log

## Review Triage Log

## Design Notes

- **Why the probe cites a subject moment:** `graph.project_artifacts` rolls back on a missing `Moment` node, and only the worker/rebuild project meetings — a run-seeded meeting can never satisfy the positive half. The probe therefore rides an existing projected moment; ownership lives in the artifact row (run minted it, run erases it), and the run-id prefix lives in the artifact's title/body and in the report's minted-id list — Postgres mints UUIDs, so the prefix cannot live in the primary key itself.
- **Why cleanup is a delete-only module instead of an api call or retirement:** the api has no DELETE surface, `rebuild` has no retirement mode, and `rebuild --meeting <subject>` would drop the subject's vectors (destructive). The guard amendment is the narrowest honest mechanism: one named module, delete stems only, run-minted ids only, pinned by the same boundary suite that pins everything else. AD-16 wording follows at integration (deferred).
- **Race posture:** two runs may pick the same moment; approval is first-writer-wins and the loser's 409 resolves by re-reading its own row. Response rows are filtered to minted ids because the route returns every artifact under the moment by design.

## Verification

**Commands:**
- `make evals-test` -- expected: all store-free suites green; `evals/runs/` untouched.
- `uv run --project server pytest evals/tests evals/checks -q --collect-only` -- expected: collection clean (checks collect without stores; they skip/refuse at runtime, not import time).
- `make test-fast` -- expected: green (no server files changed; guards against accidental footprint escape).
- `python3 _bmad/scripts/branch_conflicts.py --against story/11-3` -- expected: `clean` against `main` and every `story/*` except pairs involving `story/11-2-review`.

**Owner-run measured truth (NOT run by this story — paid-adjacent live stack):**
- In the main checkout with the stack up: `make evals-run EVAL_ARGS='--run-label left'` and, concurrently in a second shell, `make evals-run EVAL_ARGS='--run-label right'`, while a worktree runs `make test`. Expected: both runs exit on their own verdicts with two distinct `evals/runs/2026-*-left|right` folders; each report's 2.11 detail lists its own probe ids with cleanup verified; `SELECT count(*) FROM artifact WHERE title LIKE 'eval-gate-probe-%'` is 0 afterward; no `nothing-to-approve` failure caused by the sibling run (a concurrent-approval note is acceptable). That observation is the sentence AGENTS.md gets.
