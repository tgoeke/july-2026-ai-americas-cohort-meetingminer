---
title: 'Story 6.2 Review Remediation'
type: 'bugfix'
created: '2026-08-30'
status: 'done'
review_loop_iteration: 0
baseline_commit: '2108c2a9385528756eb78b328585c5c2611230b1'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/review-story-6-2-2026-08-30.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-6-2-youtube-acquisition-command.md'
  - '{project-root}/docs/architecture.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Story 6.2 fails adversarial review: extractor metadata can bypass refusal and identity boundaries, mint provenance can be falsified, missing runtime tools/captions fail late or silently, the Make target permits shell injection, and the command boundaries lack deterministic coverage.

**Approach:** Resolve patch findings F1-F12 on the review lane with red-first regressions, constrained mint overrides, one fail-closed YouTube metadata boundary, safe CLI/Make transport, and direct download/main tests. Preserve F13 as an explicit unresolved specification decision.

## Boundaries & Constraints

**Always:** Fail named and before permanent writes; keep `mint()` as the only staging/finalize path; preserve default mint behavior; validate probe and downloaded metadata independently; keep tests offline and never POST to the shared API; record every resolution in the review report; commit incrementally with finding IDs.

**Ask First:** Any attempted resolution of F13's conflict between defaulted acquisition settings and AD-10; any required edit outside the original Story 6.2 footprint.

**Never:** Merge to `main`; implement playlists; widen mint-drop CLI/file classification; touch shared test infrastructure or web code; invent a failing test for F11/F12 behavior that is already correct.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Protected provenance | Extra map collides with mint-owned keys | No drop or lock artifact | Named `MintError` lists collisions |
| Invalid/drifting metadata | Missing/invalid duration, mismatched ID, incomplete provenance, invalid timestamp, over-cap downloaded info | Never reaches finalization | Named `YoutubeError`; valid upload-date fallback used |
| Missing dependency/caption | `ffprobe` absent or selected captions produce no VTT | No media download for tool gap; no recording-only downgrade | Named refusal with remediation |
| Hostile Make URL | URL includes quotes/shell metacharacters | Passed to Python as one data argument | No shell evaluation |
| CLI retry paths | created/exists/no-post/duplicate/intake failure | Same POST and recovery behavior as mint-drop | Non-zero with exact re-POST guidance on failure |

</frozen-after-approval>

## Code Map

- `server/meetingminer/mintdrop.py:541-710` -- F1: constrain producer overrides before locking; retain mint-owned integrity provenance.
- `server/meetingminer/youtube.py:166-464` -- F2-F8: tool preflight, normalized metadata validators, probe/download gates, caption materialization.
- `server/meetingminer/youtube.py:506-560` -- F9/F12: classify before resolvers and retain complete command/POST behavior.
- `infra/Makefile:554-557` -- F10: transport URL through the environment as quoted data, not Make-expanded shell source.
- `server/tests/test_youtube.py` -- red-first regressions and deterministic `_run()`/`main()` boundary coverage for F1-F12.
- `_bmad-output/implementation-artifacts/review-story-6-2-2026-08-30.md` -- append resolutions, verification, final verdict; leave F13 open.

## Tasks & Acceptance

**Execution:**
- [x] `server/tests/test_youtube.py`, `server/meetingminer/mintdrop.py` -- reproduce and fix F1 without changing default callers.
- [x] `server/tests/test_youtube.py`, `server/meetingminer/youtube.py` -- reproduce and fix F2-F8 through shared fail-closed validators.
- [x] `server/tests/test_youtube.py`, `server/meetingminer/youtube.py` -- close F9/F12 CLI ordering and behavior coverage.
- [x] `server/tests/test_youtube.py`, `server/meetingminer/youtube.py` -- close F8/F11 download-output and command coverage.
- [x] `server/tests/test_youtube.py`, `infra/Makefile` -- reproduce and fix F10 shell injection.
- [x] Review artifacts -- record F1-F12 resolved, F13 open, and the evidence-backed verdict.

**Acceptance Criteria:**
- Given each reproducible defect, when its regression runs against the unfixed implementation, then it fails for the reported reason before the corresponding fix is applied.
- Given F11/F12 behavior already correct, when coverage is added, then the report identifies it as coverage-only and does not claim a fabricated red state.
- Given all fixes, when Story 6.2 tests and `make test-fast` run in the foreground, then they pass with only the named network skip.
- Given F13 remains undecided, when the report closes, then it states that the story still cannot receive a fully clean verdict on that architecture question.

## Spec Change Log

- 2026-08-30 (implementation): F1-F12 remediated with red-first regressions for
  the reproducible defects and coverage-only tests for the already-correct
  F11/F12 behavior. F13 remains an unresolved human-owned architecture/spec
  decision and was not changed.

## Verification

**Commands:**
- `uv run --project server pytest server/tests/test_youtube.py -q` -- all offline tests pass; network test skips by name.
- `make test-fast` -- complete foreground fast gate passes.
- `make check-reviews` -- every dispatched review has a committed report.
- `python3 _bmad/scripts/branch_conflicts.py --against story/6-2-review` -- wave conflicts reported for integration awareness.

**Results (2026-08-30):**
- `uv run --project server pytest server/tests/test_youtube.py -q` -- 96 passed,
  1 skipped by the named `MM_YOUTUBE_NETWORK_TEST` gate.
- `make test-fast` -- puller 128, web 291, evals 549, server 1497 passed;
  1 named YouTube network skip and 326 slow tests deselected.
- `make check-reviews` -- every dispatched review has a committed report.
- `python3 _bmad/scripts/branch_conflicts.py --against story/6-2-review` -- 21
  clean pairs and 8 conflicts reported. This branch is clean against `main`
  and `story/6-2`; integration must reconcile `mintdrop.py` with `story/6-3`.

## Suggested Review Order

**Acquisition boundary**

- Start at orchestration: local identity, dual metadata gates, then one mint path.
  [`youtube.py:596`](../../server/meetingminer/youtube.py#L596)

- Validate legacy `exists` drops locally before allowing an idempotent re-POST.
  [`youtube.py:506`](../../server/meetingminer/youtube.py#L506)

- Centralize fail-closed identity, duration, stream, publisher, and format checks.
  [`youtube.py:335`](../../server/meetingminer/youtube.py#L335)

- Bind caption output to the exact selected English language track.
  [`youtube.py:409`](../../server/meetingminer/youtube.py#L409)

**Provenance integrity**

- Reject non-mappings and mint-owned collisions before classification or locking.
  [`mintdrop.py:174`](../../server/meetingminer/mintdrop.py#L174)

- Preserve write-once assembly while accepting only validated producer facts.
  [`mintdrop.py:653`](../../server/meetingminer/mintdrop.py#L653)

**Command boundary and evidence**

- Transport hostile Make values as data without exporting raw command-line input.
  [`Makefile:554`](../../infra/Makefile#L554)

- Read regressions for legacy drops, caption drift, provenance, CLI, and Make injection.
  [`test_youtube.py:581`](../../server/tests/test_youtube.py#L581)

- Confirm operator documentation accurately distinguishes temporary and permanent writes.
  [`README.md:182`](../../docs/README.md#L182)
