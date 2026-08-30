---
title: 'Story 2.1 — Media Streaming & Replay Foundation'
type: 'feature'
created: '2026-08-19'
status: 'in-progress'
review_loop_iteration: 0
followup_review_recommended: true
context: []
warnings: [oversized]
deferred:
  - summary: >-
      FILED as story `2-1a-evidence-paths-anchored-to-configured-roots`. The recording has no
      row and no stored path; it should carry a drop-relative path the way transcript_source
      already does for the transcript.
    evidence: |-
      Migration 0005 already documents the two-case convention: transcript_source.content_path
      for material the pipeline produced (relative to MM_CONTENT_ROOT) and
      transcript_source.drop_relative_path for material that arrived in the drop (relative to
      the drop directory), plus sha256 and byte_size so a re-ingest can prove the input did not
      change. The transcript is drop-resident and recorded that way; the recording is
      drop-resident and recorded nowhere. Story 2.1 therefore resolves it as job.drop_path
      (data) plus RECORDING_FILENAME (a constant in domain/drops.py) — half the path in the
      database, half in code. Two consequences: job.drop_path is absolute (intake requires it,
      api/ingests.py:133), so moving the drops folder breaks replay for every ingested meeting
      while frames and screenshots survive — the exact failure AD-3 exists to prevent; and with
      no recorded sha256, a swapped recording is undetectable where a swapped transcript is not.
      The amended AD-3 now states the two-root position. Story 2.1a supplies `MM_DROPS_ROOT`,
      relative storage, resolve-at-use-time, the recording provenance row, and a fail-closed
      backfill; the recording stays in its permanent drop and is not copied under the content
      root.
    location: >-
      _bmad-output/implementation-artifacts/spec-2-1a-evidence-paths-anchored-to-configured-roots.md
    severity: medium
  - summary: >-
      GET /media/{path} serves any file under the content root, not only paths registered on a
      screenshot or frame row.
    evidence: |-
      The acceptance criterion describes resolving "the DB's relative paths", but get_media_file
      never consults screenshot.path or frame.path — it resolves whatever the client sends. The
      containment guard is therefore the only line of defence rather than defence in depth.
      Constraining to the meetings/ subtree, or validating against a DB row, would close it.
    location: server/meetingminer/api/media.py:379
    severity: medium
  - summary: >-
      Media content type is an unrestricted mimetypes.guess_type with no allowlist.
    evidence: |-
      X-Content-Type-Options: nosniff does not help when the declared type is itself the
      dangerous one: an .html or .svg file under the content root is served as text/html or
      image/svg+xml from the API origin. An allowlist of image/video types falling back to
      application/octet-stream would match the module docstring's stated intent.
    location: server/meetingminer/api/media.py
    severity: medium
  - summary: >-
      No ETag, Last-Modified, Cache-Control, or If-Range on media responses.
    evidence: |-
      Story 2.3's screenshot series is explicitly a timeline of many images; with no validators
      every render re-downloads all of them. The spec's Never list rules out "a byte-range
      caching layer", which is not the same as ruling out response validators, so this reads as
      an omission rather than a decision.
    location: server/meetingminer/api/media.py
    severity: medium
  - summary: >-
      ReplayPlayer has no failure surface and no contract for the media-no-recording 404.
    evidence: |-
      No error handler, no fallback children, no handling of the 404 the API legitimately
      returns for a transcript-only meeting — it renders a silently blank video box. Epic 2
      requires transcript-only meetings to show a transitional recap deep link exactly where the
      replay affordance sits. Story 2.1's Never list defers the UI, but the shared player 2.2
      and 2.3 will mount carries no forward obligation for the absent-recording case.
    location: web/src/features/replay/ReplayPlayer.tsx
    severity: medium
  - summary: HEAD returns 405 on both media routes.
    evidence: |-
      Verified against FastAPI 0.141.1 / Starlette 1.6.0: APIRoute does not inherit Starlette's
      automatic HEAD-for-GET, so HEAD /media/... answers 405. Players, caching proxies and
      curl -I probe media URLs with HEAD to learn size and Accept-Ranges before ranging.
      Browsers' <video> uses GET with Range, so nothing is broken today.
    location: server/meetingminer/api/media.py:341
    severity: low
  - summary: The committed generated TypeScript client no longer mirrors the api's operation set.
    evidence: |-
      getRecording and getMediaFile are new operations; web/src/client/*.gen.ts was not
      regenerated. Nothing detects the drift — make check-client only asserts the three .gen.ts
      files exist. Deliberate in effect (a <video src> needs a URL, not a fetch wrapper), but
      unrecorded.
    location: web/src/client/sdk.gen.ts
    severity: low
  - summary: Check-then-open race between the containment guard and the file open.
    evidence: |-
      _resolve_under_root walks components calling is_symlink(), then _stream_file independently
      calls is_file(), stat() and open(). The bytes served come from a different lookup than the
      one that was guarded, and size comes from a separate stat() than the open handle. Opening
      once with O_NOFOLLOW and taking size from os.fstat would close both. Local-only exposure
      on an unauthenticated loopback api, so low.
    location: server/meetingminer/api/media.py:155
    severity: low
  - summary: CORS expose_headers is unset, hiding Content-Range and Accept-Ranges from scripted reads.
    evidence: |-
      CORSMiddleware allows the Vite dev origin with wildcard methods and headers but sets no
      expose_headers, so Content-Range, Accept-Ranges and Content-Length are invisible to
      fetch/XHR from :5173. A <video src> is a no-CORS media load so replay works today; this
      surfaces the first time something scripts a range probe.
    location: server/meetingminer/api/main.py:83
    severity: low
  - summary: mediaUrl strips a leading slash, so the api's absolute-path rejection is unreachable from the app.
    evidence: |-
      The helper's test says it "escapes rather than sanitises — the api owns the containment
      guard", but stripping a leading "/" is a rewrite. It also special-cases only exact . and ..
      segments, so an already-percent-encoded input double-encodes. The precondition that input
      is always a raw DB path is unstated.
    location: web/src/lib/media.ts
    severity: low
  - summary: frame.path is named as a first-class case but exercised by no test.
    evidence: |-
      The module docstring, the Code Map and mediaUrl's docstring all name frame.path alongside
      screenshot.path; only screenshot-shaped paths are tested, and nothing pins that a path
      outside meetings/ behaves as intended.
    location: server/tests/test_api_media.py
    severity: low
baseline_revision: '961254eb69eae2ff0d5859b4ac7e2a31dbb731fe' # branch point from main; the story's review range is this..HEAD
---

<intent-contract>

## Intent

**Problem:** Every piece of Epic 1's evidence bundle is on disk and unreachable from the browser: no route serves screenshots, and no route serves the recording at all, so no moment can be viewed or replayed. Stories 2.2 and 2.3 — and citation replay in later epics — cannot start.

**Approach:** Add a read-only `/media` surface to the api that streams content-root files by root-relative path and streams a meeting's recording by meeting id, both honouring HTTP Range so an HTML5 `<video>` can seek; plus a small web player that opens at a given `startMs`. No schema change, no pipeline change, no writes.

## Boundaries & Constraints

**Always:**
- Resolve every client-supplied path against `MM_CONTENT_ROOT` and refuse anything that escapes it — `..`, absolute paths, and symlinks that leave the root. Follow the guard already established in `pipeline/outputs.py:assert_private_meeting_subdir` (resolve, then `is_relative_to`, then reject symlinked components).
- No absolute filesystem path ever appears in a response body, header, or problem detail.
- Every error is RFC 9457 `application/problem+json` via `api/problems.py:Problem`.
- Range responses follow RFC 9110: `206` with `Content-Range` and `Accept-Ranges: bytes`; unsatisfiable ranges give `416` with `Content-Range: bytes */<size>`; a malformed/unparseable `Range` is ignored and the full `200` is served.
- The api stays read-only here: it reads `meeting`, `job`, and `screenshot` and writes nothing (AD-5/AD-11). It never touches a source drop.
- Serve the recording from the drop **read-only**. Drops are write-once (AD-1/AD-13); nothing in this story copies, moves, or rewrites one.

**Block If:**
- Serving the recording requires materialising it under `MM_CONTENT_ROOT` (a new column plus a multi-GB copy in a worker-owned stage). That is a pipeline/schema change outside this story's boundary — HALT rather than widening scope. See Design Notes for why the drop-resident reading was taken.

**Never:**
- No moment view, no drill-down, no screenshot series UI (stories 2.2/2.3).
- No `viewable`/evidence gate on these routes (story 2.3 owns the detail-route gate).
- No transcoding, no media server, no byte-range caching layer — plain file streaming only.
- No changes to `config.py`, migrations, any `pipeline/` module, or worker-owned tables.
- No authentication (the whole api is unauthenticated loopback today; do not invent a scheme here).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Screenshot fetch | `GET /media/meetings/<id>/screenshots/shot-01.jpg`, file exists under root | `200`, image bytes, `Accept-Ranges: bytes`, correct `Content-Type` | No error expected |
| Range on video | `GET /media/recordings/<meetingId>` with `Range: bytes=1000-1999` | `206`, exactly 1000 bytes, `Content-Range: bytes 1000-1999/<size>` | No error expected |
| Open-ended range | `Range: bytes=1000-` | `206`, bytes 1000..EOF, correct `Content-Range` | No error expected |
| Suffix range | `Range: bytes=-500` | `206`, final 500 bytes | No error expected |
| Unsatisfiable range | `Range: bytes=<size>-` (start past EOF) | `416`, `Content-Range: bytes */<size>` | RFC 9457 body |
| Malformed range | `Range: furlongs=1-2` | `200`, whole file (range ignored per RFC 9110) | No error expected |
| Traversal attempt | `GET /media/../../etc/passwd` (and encoded forms) | `400` problem, no bytes served | `media-path-invalid`; detail names no absolute path |
| Symlink escape | Content-root file is a symlink pointing outside the root | `400` problem | `media-path-invalid` |
| Missing file | Path resolves inside root but no file there | `404` problem | `media-not-found` |
| Directory requested | Path resolves to a directory | `404` problem | `media-not-found` |
| Unknown meeting | `GET /media/recordings/<unknown uuid>` | `404` problem | `media-not-found` |
| Transcript-only meeting | Meeting exists, `has_recording = false` | `404` problem naming that the meeting has no recording | `media-no-recording` |
| Recording missing on disk | `has_recording = true`, drop file gone | `404` problem | `media-not-found` |
| Content root unset | `MM_CONTENT_ROOT` absent from env | `500` problem naming the misconfiguration | `media-root-unconfigured` |

</intent-contract>

## Code Map

- `server/meetingminer/api/media.py` -- **new**; both routes, the range parser, and the path guard.
- `server/meetingminer/api/main.py:88-92` -- router registration. Register `media.router` here. Order matters: the api already documents this hazard for `events` vs `jobs` (`main.py:89-91`); `/media/recordings/{meeting_id}` must be declared before the `/media/{path:path}` catch-all.
- `server/meetingminer/api/problems.py:44` -- `Problem(status, slug, detail)`; `_STATUS_TITLES` already covers 400/404/500. `416` is absent — pass an explicit `title`.
- `server/meetingminer/pipeline/outputs.py:32-56` -- `assert_private_meeting_subdir`: the existing content-root containment guard (resolve → `is_relative_to` → per-component symlink rejection). **Read-only reference — do not import**; `pipeline/` is off-limits per Boundaries, and that function creates/validates a *write* target. Reimplement the read-only equivalent in `api/media.py`.
- `server/meetingminer/config.py:Secrets.mm_content_root` -- already absolute and `.resolve()`d at load, or `None`. Reach it via `request.app.state.config` (set in `main.py:79`). **Do not** call `config.require_content_root`: it creates the directory and write-probes it, which the read-only api must not do.
- `server/meetingminer/migrations/0002_meetings_media_frames.sql:26-42` -- `meeting`: has `job_id` (UNIQUE), `has_recording`. **No recording path column** — this is why the recording resolves through the job's drop.
- `server/meetingminer/api/ingests.py` (`UPDATE job SET ... drop_path`) -- `job.drop_path` is the absolute drop directory; the recording is `<drop_path>/recording.mp4`.
- `server/meetingminer/domain/drops.py:26` -- `RECORDING_FILENAME = "recording.mp4"`. Import it; do not restate the literal.
- `server/meetingminer/migrations/0003_screens_screenshots.sql:64-78` -- `screenshot.path`, relative to the content root (the same is true of `frame.path`, `0002:76-84`). These are what the catch-all route serves.
- `server/tests/conftest.py:269` -- `content_root` fixture; `:131` `client`; `:122` `test_pool`; `:222` `make_drop`; `:277` `synthetic_recording` (a real small mp4, session-scoped) — use it for the range tests rather than inventing a fixture.
- `server/tests/test_api_meetings.py:1-30` -- house style for store-backed api tests (module docstring says what a refactor would break; `_submit` helper).
- `web/src/lib/api.ts` -- `API_BASE`; the one place the api address is known. The media URL helper belongs beside it.
- `web/src/features/meetings/MeetingsList.tsx` + `.test.tsx` -- house style for a feature component and its vitest.

## Tasks & Acceptance

**Execution:**
- `server/meetingminer/api/media.py` -- new module: `_resolve_under_root()` (containment + symlink guard), `_parse_range()` (returns a byte range, `None` for absent/malformed, or unsatisfiable), a shared file-streaming responder, `GET /media/recordings/{meeting_id}`, and `GET /media/{path:path}` -- one module so the guard and the range parser cannot drift apart from the routes that depend on them.
- `server/meetingminer/api/main.py` -- import and `include_router(media.router)` with a comment pinning why the recordings route precedes the catch-all -- the same ordering hazard already documented for `events`/`jobs`.
- `server/tests/test_api_media.py` -- new: cover every row of the I/O matrix, including each range form and each traversal form -- the guard and the range arithmetic are the two things a refactor breaks silently.
- `web/src/lib/media.ts` -- new: `mediaUrl(path)` and `recordingUrl(meetingId)` building on `API_BASE` -- keeps URL construction out of components.
- `web/src/features/replay/ReplayPlayer.tsx` -- new: an HTML5 `<video>` that seeks to `startMs` once metadata loads, and re-seeks when `startMs` changes -- the shared player 2.2's replay button and 2.3's inline replay both mount.
- `web/src/features/replay/ReplayPlayer.test.tsx` -- new: assert the element's `src`, that `currentTime` is set from `startMs` after `loadedmetadata`, and that a later `startMs` re-seeks.

**Acceptance Criteria:**
- Given a completed recording-backed meeting, when `GET /media/recordings/{meetingId}` is requested with no `Range`, then the whole recording streams with `200` and `Accept-Ranges: bytes`.
- Given the same meeting, when the request carries `Range: bytes=1000-1999`, then exactly those bytes return with `206` and a matching `Content-Range`, so an HTML5 player can seek to any offset.
- Given a screenshot row whose `path` is root-relative, when that path is requested under `/media/`, then its bytes stream with the right content type.
- Given any request whose path escapes the content root by traversal, absolute path, or symlink, then the api answers RFC 9457 with no bytes served and no absolute path in the body.
- Given a `ReplayPlayer` mounted with a `startMs`, when metadata loads, then `currentTime` equals `startMs / 1000`.
- Given the full suite, when `make web-test` and the server tests run, then they pass with no new lint errors.

## Design Notes

**Why the recording is served from the drop, not the content root.** Amended AD-3 defines two permanent configured roots: material that arrived, including the recording, remains in its write-once drop; material the pipeline produced goes under `MM_CONTENT_ROOT`. The recording is therefore deliberately not copied. Story 2.1 provides an opaque `/media/recordings/{meetingId}` while the pre-existing absolute `job.drop_path` remains the temporary anchor.

The temporary anchor is not the final AD-3 implementation: the route composes an absolute stored drop path with `recording.mp4`, and the recording has no provenance row. Story 2.1a owns the required `MM_DROPS_ROOT`, drop-relative storage, resolve-at-use-time, and recording path/checksum/size work. Its outcome preserves the drop-resident recording rather than copying it into the content root.

**Two routes, one prefix.** `/media/recordings/{meetingId}` is id-addressed because there is no path to give; `/media/{path:path}` is path-addressed because that is what `screenshot.path` and `frame.path` hold, and it is why the traversal criterion exists at all — a client-supplied path is the only thing there is to guard. The content root's only written subtree is `meetings/` (`pipeline/outputs.py`), so `recordings/` cannot collide with a real file.

## Verification

**Commands:**
- `make web-test` -- expected: all vitest suites pass, including the new `ReplayPlayer` tests. Store-free, safe to run at any time.
- `cd server && .venv/bin/python -m pytest tests/test_api_media.py -v` -- expected: every I/O-matrix row passes. **Store-backed — requires Postgres; announce and hold the stores before running (AGENTS.md).**
- `cd server && .venv/bin/python -m pytest tests/ -q` -- expected: no regressions. **Store-backed — same hold.**
- `cd server && .venv/bin/ruff check meetingminer/api/media.py` -- expected: clean.

## Auto Run Result

Status: done

### Implemented change

A read-only `/media` surface on the api plus the browser primitives that consume it.
`GET /media/{path}` streams a content-root-relative file (what `screenshot.path` and
`frame.path` hold); `GET /media/recordings/{meetingId}` streams the meeting's recording,
resolved `meeting -> job.drop_path -> recording.mp4` server-side. Both honour HTTP Range per
RFC 9110 so an HTML5 player can seek. No schema change, no pipeline change, no writes.

### Files changed

- `server/meetingminer/api/media.py` — new: both routes, the range parser, the containment
  guard, and the chunked responder.
- `server/meetingminer/api/main.py` — registers the router, with the ordering hazard pinned in
  a comment.
- `server/tests/test_api_media.py` — new: 72 tests covering every I/O-matrix row plus unit
  tests of the two pure functions.
- `web/src/lib/media.ts`, `web/src/lib/media.test.ts` — new: `mediaUrl` / `recordingUrl`.
- `web/src/features/replay/ReplayPlayer.tsx`, `ReplayPlayer.test.tsx` — new: the shared HTML5
  player that seeks to `startMs`.
- `_bmad-output/implementation-artifacts/epic-2-context.md` — new, then corrected: its
  constraint paraphrase asserted that media is served by resolving DB-stored root-relative
  paths, which is the one thing the recordings route deliberately does not do.

### Review findings

7 patched (1 high, 3 medium, 3 low), 11 deferred (5 medium, 6 low), 9 rejected.
Follow-up review recommended: **true** — a high-severity finding was patched
(score 3x3 + 1x3 = 12, threshold 5; either condition alone suffices).

### Verification performed

All commands run by the orchestrator, not reported from a subagent:

- `pytest tests/test_api_media.py -q` — **72 passed**, 0 skipped (57 before patches).
- `pytest tests/ -q` — **816 passed**, 0 failed, 0 skipped, 3m43s (801 before patches).
- `make web-test` — **52 passed**, 5 files (48 before patches).
- `uvx ruff check --isolated` on `media.py` and `test_api_media.py` — clean.
- Independent mutation check: forcing `_iter_chunks` single-shot
  (`remaining -= len(chunk)` -> `remaining = 0`) fails exactly the two new multi-chunk tests
  and nothing else; `media.py` restored and confirmed marker-free afterwards.

Deviation: the spec's `.venv/bin/ruff` command cannot run — ruff is installed nowhere in this
repo and has no `pyproject.toml` config (already a standing deferred item from story 1.1).
`uvx ruff check --isolated` was used instead. Its two findings are both in `main.py` and are
pre-existing: linting `main.py` at `961254eb` produces the identical two.

### Residual risks

- **Root anchoring and recording provenance await Story 2.1a.** The recording correctly remains
  in its write-once drop under the amended two-root AD-3, but the existing implementation still
  stores an absolute `job.drop_path`, composes it with a filename constant, and has no recording
  provenance row. Story 2.1a is the required conformance work.
- **The seek -> Range -> 206 loop is never closed end to end.** `ReplayPlayer` is tested in
  jsdom, which loads no media and has no `readyState` semantics; the 206 is tested through the
  ASGI client. The repo has no browser or e2e harness, so the acceptance criterion "the player
  opens positioned at that offset" is verified on each surface separately and never together.
- **Nothing mounts the player yet** and no route emits a media path, so `mediaUrl` has no
  caller. That is story 2.1 being a foundation, but it means the first real consumer (2.2) is
  where the integration is first exercised.
- **The literal `../..` matrix row cannot behave as written.** Every conforming client collapses
  it before routing, so it 404s from the router rather than 400-ing from the guard. Both
  spellings are pinned as tests asserting no bytes are served; the security property holds, the
  status code differs from the row.

### Review Findings

- [x] [Review][Defer] Root-anchored recording provenance — deferred to `spec-2-1a-evidence-paths-anchored-to-configured-roots.md`, pre-existing. The amended AD-3 establishes that recordings are arrived material and remain in their permanent source drops, relative to `MM_DROPS_ROOT`; they are not copied under the content root. Story 2.1a owns the outstanding conformance work: remove absolute `job.drop_path` storage and its `GET /jobs` leak, make the full recording path data rather than `job.drop_path` plus `RECORDING_FILENAME`, and record the recording's drop-relative path, checksum, and size. This review's former one-root AD-3 finding was based on superseded architecture text.
- [x] [Review][Defer] Source-drop symlink admissibility — deferred to `spec-2-1a-evidence-paths-anchored-to-configured-roots.md`, pre-existing. Amended AD-1 requires each canonical evidence file and the drop directory itself to be regular rather than symlinked; a hard link remains permitted. The current replay refusal is therefore correct defensive behaviour, while 2.1a closes the pre-existing intake/worker gap that currently lets a symlinked recording produce `has_recording = true` and later 404 at replay.
