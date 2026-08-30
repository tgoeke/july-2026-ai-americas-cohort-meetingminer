---
title: 'Story 2.1b Review Remediation: Safe and Viewable Local Recording Drops'
type: 'bugfix'
created: '2026-08-20'
status: 'done'
baseline_commit: '23f9afdfe99bdaf2bbf4d0ee3443ed4314b8c5d7'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/review-story-2-1b-2026-08-20.md'
  - '{project-root}/_bmad-output/specs/spec-meetingminer/storage-layout.md'
  - '{project-root}/docs/source-drop.schema.json'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The reviewed local-recording producer can create permanent drops the only intake door cannot accept, can race into duplicate source identities, and can finalize changed non-video bytes. It also accepts an audio-less video-only MP4 that the current worker leaves failed and non-viewable, despite the frozen Story 2.1b video-only contract.

**Approach:** Make minting fail closed against the configured intake boundary and source identity, validate the exact staged recording, and cover the real HTTP handoff. Preserve the user's explicit decision that a video-only recording remains supported: when it has no transcript or audio, the worker completes its screen-and-replay evidence path rather than failing alignment.

## Boundaries & Constraints

**Always:**

- A mint may finalize only below the configured `MM_DROPS_ROOT`; descendants are valid, sibling or external roots are refused before staging.
- The content-derived `sourceId` is write-once across concurrent processes, independent of a caller's title or start time.
- A recording must be verified as video after its bytes reach staging and before a directory becomes visible.
- An accepted API value is an HTTP(S) base URL with a host and no query or fragment; the printable curl request and `urllib` POST target the same `/ingests` URL.
- A silent/video-only recording reaches a settled, viewable evidence bundle: it may have zero transcript segments, but it retains recording replay and screen-derived moments when screenshots exist. No transcript text, timing, speaker, or participant is invented.
- The real HTTP test mints under a unique child of the configured drops root and cleans only that test child after it completes.

**Ask First:** Stop for a human decision if preserving a video-only meeting requires creating transcript content, fabricating timing, or widening the source-drop schema.

**Never:** Do not add another intake endpoint, make the drop mutable, write outside the configured root, alter `pull_transcript/`, or downgrade the user decision by rejecting audio-less MP4s.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| External root | `--drops` is outside configured root | No staging directory or finalized drop | Named non-zero refusal before copy |
| Nested root | `--drops` is a child of configured root | Valid drop, intake-relative path resolves | No error |
| Simultaneous same content | Two processes, same bytes, distinct title/start | Exactly one creates; the other reports `exists` | No duplicate finalized |
| Source replacement | MP4 changes after first probe | Staged bytes are re-probed and rejected | Staging removed, no finalized drop |
| Invalid API base | Hostless, query, or fragment-bearing URL | Refused before mint | Named non-zero refusal |
| Silent video only | MP4 has video but neither audio nor transcript | Job settles evidence stages, meeting is viewable and replay serves | Zero transcript rows; no fabricated evidence |

</frozen-after-approval>

## Code Map

- `server/meetingminer/mintdrop.py` — `resolve_drops_root`, `find_existing_drop`, `mint`, `_source_id_lock`, `_assemble`, `resolve_api_url`, `ingest_command`, and `post_ingest`; contain the configured-root identity, write-once, and endpoint faults.
- `server/meetingminer/domain/drops.py:153` — `drop_relative_path` establishes intake's root-containment semantics; use it as behavioral evidence, but root validation must accept the root itself.
- `server/meetingminer/pipeline/stages/transcribe.py:109-153` — already treats no audio as a legitimate no-STT path and removes stale audio output.
- `server/meetingminer/pipeline/stages/align.py:505-670` — currently raises with neither provided transcript nor STT; the empty screen-only path must instead clear stale derived rows and settle honestly.
- `server/meetingminer/pipeline/stages/moments.py` and `server/meetingminer/pipeline/moments.py` — already derive screen-only moments from screenshots with an empty segment list; preserve this behavior.
- `server/meetingminer/domain/jobs.py:103-111` — `evidence_complete()` is the shared viewability gate; no new gate or schema is needed.
- `server/tests/test_mint_drop.py` — move mint fixtures beneath the configured root and add deterministic contention, staged-validation, URL, and real HTTP intake coverage.
- `server/tests/test_worker_runner.py` / `server/tests/test_worker_transcripts.py` — existing store-backed worker patterns for a silent-video, no-transcript regression.

## Tasks & Acceptance

**Execution:**

- [x] `server/meetingminer/mintdrop.py` — reject an explicit root outside `MM_DROPS_ROOT`, serialize the source-id existence/finalize interval with a crash-safe cross-process lock, re-probe staged recordings, and parse API bases before minting.
- [x] `server/meetingminer/pipeline/stages/align.py` — turn the no-transcript/no-STT recording case into an honest zero-segment completion while clearing any stale derived transcript and participant rows.
- [x] `server/tests/test_mint_drop.py` — migrate fixtures to contained temporary roots; add tests for external rejection, nested-root success, deterministic concurrent identity protection, post-copy video validation, URL construction, and real HTTP `/ingests` behavior.
- [x] `server/tests/test_worker_runner.py` or the established worker-stage test owner — add a silent, video-only, no-transcript end-to-end worker case proving the completed viewable state and no invented transcript evidence.
- [x] `docs/README.md` — correct any operator-facing behavior changed by the hardened root/API validation, without adding hand-authored JSON guidance.

**Acceptance Criteria:**

- Given identical content is minted concurrently with different labels, when both processes finish, then one finalized drop and one source identity exist and both callers receive a truthful result.
- Given a source file changes after its first probe, when minting reaches the staged copy, then no invalid recording becomes a drop.
- Given a valid configured-root mint and real API, when the CLI posts it, then the route returns 201 and a queued job stores a drops-root-relative path.
- Given an audio-less MP4 and no transcript, when its job runs, then every evidence stage settles, replay serves the recording, and the meeting is viewable without transcript segments.

## Design Notes

Fixed-shard advisory locks belong in a hidden directory at the configured drops root, so every writer sharing that storage contends on the same inode without accumulating one file per recording; the kernel still releases a held lock when its process exits. The empty alignment path must not create a placeholder transcript: screens already provide the lawful timeline evidence, while a fabricated speaker or time would violate AD-13. A declared participant graph is independent source evidence and is retained without fabricating speech.

## Verification

**Commands:**

- `cd server && .venv/bin/python -m pytest tests/test_mint_drop.py -q` — expected: all mint safety and real HTTP boundary tests pass.
- `cd server && .venv/bin/python -m pytest tests/test_worker_runner.py tests/test_worker_transcripts.py -q` — expected: silent video-only worker regression passes.
- `cd server && .venv/bin/python -m pytest tests/ -q` — expected: full suite remains green.
- `make puller-test` — expected: unchanged, passing vendored puller suite.
- `make mint-drop MINT_ARGS='--help'` — expected: usage text and exit 0.
