# Code review — Story 2.1: Media Streaming & Replay Foundation

- **Range reviewed:** `961254eb69eae2ff0d5859b4ac7e2a31dbb731fe..9633dd05bd2ef6ed26fe69e4e74dab674a5efc93` on `story/2-1`
- **Contract:** `spec-2-1-media-streaming-replay-foundation.md`, the amended AD-3, and `spec-meetingminer/storage-layout.md`
- **Layers:** Blind Hunter, Edge Case Hunter, Verification Gap Reviewer, Acceptance Auditor
- **Result:** the media foundation passes review within its frozen scope. Root anchoring, file provenance, and source-drop symlink admissibility are required follow-up work in Story 2.1a; sprint tracking remains `in-progress` until that conformance story lands.

## Findings

### 1. Resolved — root-anchored recording provenance belongs to Story 2.1a

**Location:** `server/meetingminer/api/media.py:385-425`

The reviewed implementation resolves the video via the absolute, intake-supplied `job.drop_path` and no database column records the recording's drop-relative path or identity. The re-reviewed, amended AD-3 establishes two configured permanent roots: arrived material, including recordings, remains in the drop and is relative to `MM_DROPS_ROOT`; produced material is relative to `MM_CONTENT_ROOT`.

**Outstanding conformance:** moving the drops root breaks replay, `GET /jobs` exposes the stored absolute `job.drop_path`, composing `job.drop_path` with `RECORDING_FILENAME` leaves the served path half data and half code, and no recording row carries its checksum or size provenance.

**Resolution:** this is not a content-root exception and recording video must not be copied. It is the explicit required conformance scope of `spec-2-1a-evidence-paths-anchored-to-configured-roots.md`; the obsolete `spec-2-1-recording-under-the-content-root.md` was withdrawn during the rebase and must not be built.

### 2. Resolved — source-drop symlink admissibility belongs to Story 2.1a

**Location:** `server/meetingminer/api/ingests.py:188-195`; `server/meetingminer/domain/drops.py:216-225`; `server/meetingminer/api/media.py:371-377`

Intake and `read_drop()` use `Path.is_file()`, which accepts a symlinked `recording.mp4`; the worker can therefore set `meeting.has_recording = true`. The new replay route rejects that exact file because `_drop_recording()` rejects symlinks.

**Failure scenario:** submit a drop whose `recording.mp4` is a symlink to a readable MP4. The worker processes it and mints a recording-backed meeting, but every `GET /media/recordings/{meetingId}` is `404 media-not-found`.

**Resolution:** amended AD-1 decides that such a drop is invalid: a symlink puts the bytes outside the write-once, backed-up drop and makes AD-17 provenance unstable. Story 2.1a now requires intake and `domain/drops.py` to reject symlinked canonical evidence before a job exists; hard links remain valid. The replay route's current refusal is consistent with that target policy, so no 2.1 media-route patch is warranted.

## Reviewed but not re-filed

The unrestricted media path, active MIME types, check/open race, HEAD support, generated-client drift, CORS exposure, validators, replay error UI, URL normalisation, frame-row coverage, and browser-level integration remain in the story's existing deferred list or its explicit known limitations. The literal `../..` status mismatch is likewise recorded as a client-normalisation artifact. Per the handoff, these were not duplicated as new findings. The root-anchoring and provenance work is tracked by 2.1a rather than duplicated here.

## Verification note

This review session did not re-run the shared-store suites after the user released the stores. The supplied builder evidence records `72` media tests, `816` server tests, `52` web tests, isolated Ruff, and the multi-chunk mutation check as passing on the reviewed tip.
