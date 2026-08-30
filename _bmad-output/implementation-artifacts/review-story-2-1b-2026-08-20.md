# Code review — Story 2.1b: Bring Your Own Recording

**Reviewed range:** `0df90afb2bb1a0d5f5cc4e34f2c30dd2c02f6dbd..3d49f1fa4d6c40a112551e26fb0788d7628b1e98` on `story/2-1b`.

**Verdict:** Not fit to merge as it stands. Three write-once correctness defects are reproducible; the video-only acceptance claim also needs a product-level resolution.

## Findings

### 1. External `--drops` finalizes a permanently un-ingestible drop

- **Location:** `server/meetingminer/mintdrop.py:368-416`
- **Severity:** high
- **What is wrong:** An explicit `--drops` outside `MM_DROPS_ROOT` only emits a warning, then mints and posts a drop that the only intake door rejects.
- **Why it is real:** `resolve_drops_root()` calls `_warn_if_outside_configured_root()` at line 375 and returns the external directory. `main()` subsequently finalizes it and calls `post_ingest()`. The story's own test at `server/tests/test_mint_drop.py:657-670` asserts this success path and proves that `drop_relative_path()` rejects the resulting directory. The drop is write-once, so it is permanently unusable.
- **Suggested direction:** Refuse any requested root that is not contained by the configured drops root before staging. Use containment rather than equality: a descendant of `MM_DROPS_ROOT` is accepted by intake and must not be falsely rejected.

### 2. Concurrent mints of the same bytes can create two write-once drops

- **Location:** `server/meetingminer/mintdrop.py:590-626`
- **Severity:** high
- **What is wrong:** The `sourceId` existence scan and the final rename are not serialized for the identity; different titles or start times select different target paths.
- **Why it is real:** I synchronized two `mint()` calls immediately after both found no existing drop, using identical `.mp4` bytes but titles `Alpha` and `Beta`. Both returned `created` and finalized `2026-08-05-alpha-eecec02e` and `2026-08-05-beta-eecec02e`. They carry the same `sourceId`; the second POST is therefore a duplicate-source conflict, leaving an un-ingestible permanent drop.
- **Suggested direction:** Acquire a cross-process lock keyed by the content-derived `sourceId` before `find_existing_drop()` and retain it through finalization, then re-check while holding the lock. Add a regression test using two simultaneous calls with distinct titles.

### 3. The recorded video can change after its only video probe

- **Location:** `server/meetingminer/mintdrop.py:575-579`, `server/meetingminer/mintdrop.py:724-725`
- **Severity:** high
- **What is wrong:** The source is ffprobe-validated before it is digested and copied, but the staged `recording.mp4` is never validated as video.
- **Why it is real:** A focused reproduction changed the supplied file to non-video bytes from the initial `probe_media()` call. The command then digested and copied those replacement bytes, verified their checksum, validated the metadata schema, and returned `created`. The immutable resulting `recording.mp4` contained `b'not a video after the probe'` and fails later in the pipeline.
- **Suggested direction:** Probe the staged recording after its verified copy and before `read_drop()`/rename, so the validation describes the bytes that will become immutable. Preserve the current cleanup behavior on failure.

### 4. Audio-less video-only drops meet the CLI gate but fail the core ingestion path

- **Location:** `server/meetingminer/mintdrop.py:316-340`; frozen I/O matrix “Video only”
- **Severity:** high
- **What is wrong:** The CLI accepts an `.mp4` with a video stream but no audio or transcript, although the worker cannot make that recording viewable.
- **Why it is real:** I minted a fresh one-second video-only MP4 through `make mint-drop` into the configured drops root. The real `POST /ingests` returned `201`, created job `01a01f6c-f509-783d-98fb-f0d275e0f7da`, and persisted a meeting with its recording (the replay endpoint returned `200`). The job then failed at `align`: “no transcript to derive from … no STT source,” and `GET /meetings` returned `status: failed, viewable: false`. The frozen matrix says a local video alone succeeds, and the acceptance intent requires a downstream-equivalent meeting.
- **Suggested direction:** This needs an explicit product decision before implementation: either support screen/video-only evidence through the worker without transcript alignment, or narrow the source contract and refuse recordings that lack both transcript evidence and usable audio. Do not silently finalize an input the product cannot make viewable.

### 5. `--api` accepts non-base URLs and then posts to the wrong route after minting

- **Location:** `server/meetingminer/mintdrop.py:770-777`, `server/meetingminer/mintdrop.py:805-819`
- **Severity:** medium
- **What is wrong:** Scheme-prefix validation accepts a URL containing a query or fragment, while string concatenation appends `/ingests` after that component.
- **Why it is real:** `resolve_api_url('http://127.0.0.1:8000?trace=1')` accepts the value. A captured `post_ingest()` request targets `http://127.0.0.1:8000?trace=1/ingests`, which is not the intake endpoint. The command therefore finalizes its drop before the failed hand-off despite its preflight guarantee.
- **Suggested direction:** Parse the value as a URL and require an HTTP(S) origin/base path with a host and no query or fragment; construct the endpoint from parsed components. Cover this shape in the CLI tests.

### 6. The producer-to-door HTTP boundary remains untested

- **Location:** `server/tests/test_mint_drop.py:718-754`
- **Severity:** medium
- **What is wrong:** Successful posting is proved only by a fake `urlopen` that does not inspect the request URL or serve the actual `/ingests` route.
- **Why it is real:** Changing `post_ingest()` from `/ingests` to `/ingest` would leave the current successful-post tests green: the stub records only the request body. The manual live check performed in this review confirmed the current path returns `201`, but it is not a regression test.
- **Suggested direction:** Add an integration test that mints beneath the API fixture’s configured drops root and sends the real HTTP request, asserting the 201 response and queued job. It must fail against the pre-fix URL mutation.

## Verification performed

- `cd server && .venv/bin/python -m pytest tests/test_mint_drop.py -q` — **53 passed**.
- `git diff --check 0df90af..HEAD` — clean.
- Live stack already running: `make mint-drop` produced a schema-valid configured-root drop and the real API returned **201**. The resulting video-only, audio-less input exposed finding 4: its recording endpoint was `200`, but the meeting finished `failed` and `viewable: false` because alignment had no transcript source.

## Triage

- **Patch:** findings 1, 2, 3, 5, and 6.
- **Decision resolved (2026-08-20):** preserve the frozen video-only contract. Finding 4 is a required patch: an audio-less recording must reach a viewable pipeline outcome rather than being refused or left failed.
- **Deferred:** none. The four pre-existing, documented frontmatter deferrals were not re-reported.
- **Dismissed as noise or non-actionable edge cases:** 8.

## Remediation review — 2026-08-20

The six findings are addressed by commits `33f4e95`, `66fa867`, and `6f1fa99`:

- Explicit roots are contained to the configured namespace, exclude `.staging`,
  and all valid nested roots share one bounded cross-process source-identity
  lock and recursive existing-drop scan.
- The immutable staged recording is re-probed; malformed API bases (including
  empty query/fragment delimiters, bad ports, and malformed IPv6) refuse before
  a mint; curl and urllib share one endpoint builder.
- The real HTTP route is exercised over Uvicorn, with server cleanup and a
  job-specific assertion. A subprocess regression proves the filesystem lock.
- Silent recordings produced by `mint()` now settle as screen/replay evidence;
  a declared participant graph remains source evidence, while stale
  transcript-derived participants are removed on rerun.

Focused verification passed:

- `pytest tests/test_mint_drop.py tests/test_worker_runner.py -q` — **114 passed**.
- `pytest tests/test_worker_transcripts.py -q` — **30 passed**.
- `make puller-test` — **102 passed**.
- `make mint-drop MINT_ARGS='--help'` — **exit 0**.

The full server suite was run twice after remediation and each time produced
**998 passed, 1 failed** in the pre-existing
`test_projection_lock_times_out_with_holder_details_then_releases`: its
one-second holder released while the waiter subprocess was importing, so the
waiter correctly acquired rather than timing out. The test passes in isolation.
This is recorded in `deferred-work.md`; it is outside Story 2.1b's changed
surface, but it prevents a green full-suite claim. The human owner explicitly
authorized merge on 2026-08-20 after reviewing that known test-harness issue;
the original story and remediation spec are therefore marked **done**.
