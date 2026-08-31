---
title: 'Story 6.4a: Upload Sessions'
type: 'feature'
created: '2026-08-31'
baseline_revision: '2d68dcc6dba31007c7d6fd84f0884edbc79508d5'
status: 'in-progress'
review_loop_iteration: 1
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/spec-6-4-acquisition-launch-surface.md'
  - '{project-root}/docs/source-drop.schema.json'
warnings: ['oversized']
deferred: []
---

<intent-contract>

## Intent

**Problem:** A Zoom or Teams export a person already has on disk can only enter
MeetingMiner by typing `make mint-drop` on the api host. The Add-meeting UI
(6.5a) has bytes in a browser and no way to hand them over — and the obvious
implementation is unsafe, because a source drop is write-once and
content-addressed while an upload arrives over the wire in pieces.

**Approach:** Two requests, and no pipeline work in either. `POST /uploads`
streams the parts of one multipart session straight into a private staging
directory under `MM_DROPS_ROOT/.staging/uploads/<sessionId>/`, refusing by name
before or during the stream on missing metadata, an undeclared dialect, an
unsupported type, or a size over the configured cap. `POST /acquisitions` then
names that session instead of a URL and launches the same detached runner story
6.4 built, which converts the declared dialect and calls `mintdrop.mint()` — the
one staging-validate-atomic-rename finalize — then `post_ingest()`, then removes
the session directory. The api never mints, never converts and never ingests.

## Boundaries & Constraints

**Always:**
- Identity is content, not the wire: the runner calls
  `dialects.convert_supplied()` then `mintdrop.mint(started_at_argument=...)` in
  the order `mintdrop.main()` calls them, so `sourceId` and the
  `startedAt`/`startedAtPrecision` pair are byte-for-byte what `mint-drop` would
  produce for the same bytes, title and timestamp.
- Uploaded bytes are written only under `MM_DROPS_ROOT/.staging/uploads/`, never
  into a drop directory, and the session directory never holds a
  `metadata.json` — so it can never be POSTed to `/ingests` as a drop, and
  `find_existing_drop` prunes it (dot-prefixed).
- The session directory is removed once the drop is finalized, once the
  acquisition fails, on `DELETE /uploads/{id}`, and by a TTL sweep — a failed or
  abandoned session leaves nothing behind.
- `startedAt` is required and must be RFC 3339 with a numeric UTC offset. A
  date-only value is refused: `second` precision only, never `day`.
- `corpus` is required and must be `real`.
- `transcriptDialect` is required whenever a `.vtt` part is present, declared,
  never sniffed.
- Every refusal is RFC 9457 with `rule`, `detail` and `remediation` extensions
  (AD-18) — the same three fields story 6.4's refusals carry.
- `POST /ingests` stays the only intake door (AD-14); the runner reaches it
  through `mintdrop.post_ingest()` unchanged.

**Block If:**
- The acceptance criteria would require changing `mintdrop.mint()`'s identity
  rule or `_assemble()`'s finalize.

**Never:**
- No UI (6.5/6.5a own `/add` and the tabs). No edits under `web/src/features/`,
  `api/extraction*`, `api/status.py`, or `web/src/features/threads/`.
- No second finalize, no second intake door, no folder watcher.
- No resumable/chunked upload protocol, no Postgres row for a session, no
  migration — an upload session is transient producer-side state, the way story
  6.4's acquisition status file is, and AD-2 governs domain objects.
- No `mint-drop` subprocess: the runner calls the same functions the CLI's
  `main()` calls, in the same order.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Recording + transcript | multipart with title, startedAt, corpus=real, transcriptDialect=zoom, a `.mp4` and a `.vtt` | 201 with `uploadSessionId`, `files[]` (canonical name, sha256, byteSize), `expiresAt`; both parts on disk under `.staging/uploads/<id>/` | No error expected |
| Transcript only | one `.vtt`, dialect declared | 201; a transcript-only session is first-class | No error expected |
| Missing metadata | no `title`, or no `startedAt`, or no `corpus` | 400 `upload-metadata-missing`, naming the field | staging dir removed |
| Date-only startedAt | `startedAt=2026-08-05` | 400 `upload-started-at-invalid` | staging dir removed |
| Undeclared dialect | a `.vtt` part, no `transcriptDialect` | 400 `upload-dialect-undeclared` | staging dir removed |
| Unsupported type | a `.pdf` part, or two `.mp4`s | 415 `upload-unsupported-type` / 400 `upload-duplicate-role` | staging dir removed |
| Over the size cap | `.mp4` longer than `acquisition.upload.max_recording_bytes` | 413 `upload-too-large`, refused from `Content-Length` before reading, and again mid-stream when the header lied | staging dir removed |
| Not a video | a `.mp4` ffprobe rejects | 415 `upload-not-a-video` | staging dir removed |
| Over the duration cap | recording longer than `acquisition.upload.max_duration_minutes` | 422 `upload-duration-cap` | staging dir removed |
| Acquisition names a session | `POST /acquisitions {uploadSessionId}` | 202, `kind: upload`; runner mints, posts, removes the session dir; `GET /acquisitions/{id}` walks queued → running → posted | mint/intake failure → `failed` with rule/detail/remediation, session dir still removed |
| Both or neither ref | body with `url` *and* `uploadSessionId`, or with neither | 400 `acquisition-source-ambiguous` / `acquisition-source-missing` | nothing started |
| Session already claimed | `POST /acquisitions` twice for one session | 409 `acquisition-in-progress` (live) or 404 `upload-session-not-found` (consumed) | nothing started |

</intent-contract>

## Code Map

- `server/meetingminer/mintdrop.py` -- read-only. `mint()` (line 654) is the
  finalize: `classify_supplied` → `_digest_supplied` → identity lock →
  `find_existing_drop` → `build_metadata` → `_assemble` (staging, schema
  validation, one `os.rename`). `SOURCE_ID_PREFIX` + `primary.sha256` is the
  identity; `started_at_from_argument` (246) is the precision pair;
  `STAGING_DIRNAME = ".staging"` (line ~104) is the assembly area this story
  puts `uploads/` beside; `post_ingest` (958), `resolve_api_url` (892),
  `resolve_drops_root` (401), `_load_cli_config` (388), `MINT_OWNED_PROVENANCE_KEYS`.
- `server/meetingminer/acquisitions.py` -- the launch mechanism to extend:
  `AcquisitionRecord` (~377), `claim_lock`, `live_record_for_source`,
  `child_command` (~660), `launch` (~672), `run_acquisition` (~727), `main`.
  `REMEDIATIONS` / `PROBLEM_STATUS` are pinned to `youtube.REFUSAL_RULES` by
  `test_api_acquisitions.py:917-920` — do not add upload rules to them.
- `server/meetingminer/api/acquisitions.py` -- `AcquisitionRequest` (url-only
  today), `_refusal_problem` (reads `PROBLEM_STATUS` directly), `AcquisitionStatus`.
- `server/meetingminer/transcripts/dialects.py` -- `DIALECTS`,
  `DEFAULT_DIALECT`, `workspace()`, `convert_supplied()` returning
  `Conversion(supplied, provenance_extra)`; `PROVENANCE_KEY`.
- `server/meetingminer/domain/drops.py` -- `EVIDENCE_FILENAMES`,
  `RECORDING_FILENAME`, `TRANSCRIPT_VTT_FILENAME`, `TRANSCRIPT_TEXT_FILENAME`,
  `METADATA_FILENAME`, `sha256_and_size`.
- `server/meetingminer/pipeline/media.py` -- `probe_media()` (120) for the video
  assertion and duration; `MediaToolError`; `FFPROBE`.
- `server/meetingminer/config.py` -- `AcquisitionConfig` (~900) gains `upload`;
  `_StrictModel`, `Field(gt=0)`, `validate_drops_root`.
- `server/meetingminer/api/registry.py` -- auto-discovery: a module-level
  `router` is enough; `/uploads/{id}` has no literal sibling, so default order.
- `server/meetingminer/api/problems.py` -- `Problem`, `ProblemDetails`,
  `problem_response`; extensions may not shadow the four RFC members.
- `server/tests/test_api_acquisitions.py` -- read-only pattern source: the
  `make_env` fixture (~175) swaps `app.state.config` for a `tmp_path` repo root
  and drops root; `Env.record`; `dead_pid()`; must-not-run stubs.
- `web/openapi-ts.config.ts` / `infra/Makefile:1150` -- `make client` requires a
  live api on :8000, which this wave forbids starting; `-i <file>` overrides the
  configured input, so the schema is dumped from `app.openapi()` instead.

## Tasks & Acceptance

**Execution:**
- `server/pyproject.toml`, `server/uv.lock` -- add `python-multipart` -- the
  streaming multipart parser Starlette itself uses; needed to write parts
  straight to the evidence volume instead of spooling them through `TMPDIR`.
- `config.yaml`, `server/meetingminer/config.py` -- add
  `acquisition.upload.{max_recording_bytes,max_transcript_bytes,max_duration_minutes,session_ttl_minutes}`
  as a required strict model -- a refusal boundary is configuration, not a code
  constant (AD-10), and an omitted one must fail closed.
- `server/meetingminer/uploads.py` -- NEW. The session: `session_root()`,
  `create_session()` (streams a multipart body through
  `python_multipart.MultipartParser` callbacks into the staging dir, enforcing
  per-part and total caps as bytes arrive), `read_session()`,
  `discard_session()`, `sweep_expired()`, `UploadRefused(rule=...)` plus its own
  `REFUSAL_RULES` / `REMEDIATIONS` / `PROBLEM_STATUS` tables -- the whole
  refusal vocabulary for uploads in one closed set.
- `server/meetingminer/api/uploads.py` -- NEW router: `POST /uploads`,
  `GET /uploads/{uploadSessionId}`, `DELETE /uploads/{uploadSessionId}` --
  auto-discovered (story 2.8), every refusal an RFC 9457 problem carrying
  `rule`/`remediation`.
- `server/meetingminer/acquisitions.py` -- `AcquisitionRecord` gains `kind`
  (`youtube`|`upload`) and `upload_session_id`; `launch_upload()`;
  `child_command` and `main` take `--upload-session` as the alternative to
  `--url`; `run_upload_acquisition()` converts, mints, posts and removes the
  session dir in a `finally`; `refusal_for` dispatches on `UploadRefused` and
  `problem_status(rule)` reads both tables -- one status file, one state
  machine, two source kinds.
- `server/meetingminer/api/acquisitions.py` -- `AcquisitionRequest` accepts
  exactly one of `url` / `uploadSessionId`; `AcquisitionStatus` gains `kind` and
  `uploadSessionId`; `_refusal_problem` reads `problem_status()`.
- `server/tests/test_api_uploads.py` -- NEW. The I/O matrix above, end to end
  through `TestClient`, plus the identity test: the same bytes minted through
  `mint-drop`'s own call order and through the upload runner produce one
  `sourceId`, one `startedAt`, one precision.
- `server/tests/test_api_acquisitions.py` -- extend for the upload launch,
  ambiguous/missing source refs, and the unchanged youtube rows.
- `web/src/client/*.gen.ts` -- regenerate from a dumped `app.openapi()` schema
  (`pnpm --dir web run client -i <file>`) -- the epic's last clause, and 6.5a
  cannot call an endpoint the client does not know.
- `docs/README.md`, `docs/project-record.md`, `docs/backlog.md` -- record the
  upload door beside `mint-drop`, and what it deliberately does not do.

**Acceptance Criteria:**
- Given a multipart session with a recording and a Zoom `.vtt`, when it is
  posted and then named by `POST /acquisitions`, then `GET /acquisitions/{id}`
  reaches `posted` with a `jobId`, the drop under `MM_DROPS_ROOT` validates
  against `source-drop.schema.json`, and the session directory is gone.
- Given the same recording bytes, when one is minted by `mint-drop`'s call
  order and the other through an upload session with the same title and
  `--started-at`, then both produce the same `sourceId` and the same
  `startedAt`/`startedAtPrecision`, and the second reports `exists`.
- Given an acquisition that fails at mint or at intake, when the runner
  finishes, then the record is `failed` with `rule`/`detail`/`remediation` and
  the session directory is gone.
- Given a session that is never claimed, when `session_ttl_minutes` has passed
  and any later `POST /uploads` runs, then its directory is swept.
- Given route registration, when the app starts, then `/uploads` is registered
  through auto-discovery and `web/src/client/` names the three operations.

## Spec Change Log

## Review Triage Log

### Review Findings

- [ ] [Review][Patch] Reject truncated multipart bodies unless the parser reaches its terminal state. [`server/meetingminer/uploads.py:882`]
- [ ] [Review][Patch] Enforce the observed whole-request ceiling against streamed bytes. [`server/meetingminer/uploads.py:849`]
- [ ] [Review][Patch] Budget both transcript roles in the declared body ceiling. [`server/meetingminer/uploads.py:320`]
- [ ] [Review][Patch] Refuse repeated immutable metadata fields. [`server/meetingminer/uploads.py:742`]
- [ ] [Review][Patch] Use the same filename-extension rule as `mint-drop`, without compatibility normalization. [`server/meetingminer/uploads.py:786`]
- [ ] [Review][Patch] Enforce the upload contract's RFC 3339 grammar before shared timestamp normalization. [`server/meetingminer/uploads.py:983`]
- [ ] [Review][Patch] Refuse Zoom declarations that cannot convert before publishing the session. [`server/meetingminer/uploads.py:1005`]
- [ ] [Review][Patch] Classify session-state and dialect failures through the upload refusal vocabulary. [`server/meetingminer/acquisitions.py:377`]
- [ ] [Review][Patch] Remove sessions on every ordinary acquisition failure boundary, including pre-dispatch config and process-start failures. [`server/meetingminer/acquisitions.py:778`]
- [ ] [Review][Patch] Serialize launch/delete/sweep ownership so claimed or actively streaming sessions cannot be erased. [`server/meetingminer/acquisitions.py:821`]
- [ ] [Review][Patch] Add `rule` and `remediation` to source-selection and upload-collision refusals. [`server/meetingminer/api/acquisitions.py:223`]
- [ ] [Review][Patch] Derive source tool from immutable drop provenance for `exists`. [`server/meetingminer/acquisitions.py:1098`]
- [ ] [Review][Patch] Hash during streaming and move ffprobe off the API event loop. [`server/meetingminer/uploads.py:742`]
- [ ] [Review][Patch] Translate parser-constructor failures into named multipart refusals. [`server/meetingminer/uploads.py:868`]
- [ ] [Review][Patch] Renumber Story 6.4a's colliding backlog entries to B-55/B-56 after rebasing. [`docs/backlog.md`]
- [ ] [Review][Patch] Pin upload-side timestamp/precision identity for every supported primary/dialect shape. [`server/tests/test_api_uploads.py:934`]
- [ ] [Review][Patch] Pin the real detached upload argv and CLI dispatch. [`server/meetingminer/acquisitions.py:701`]

## Design Notes

**Why a hand-rolled streaming reader.** `await request.form()` spools every
file part into a `SpooledTemporaryFile` under `TMPDIR` — the boot volume — and
only then hands it over to be copied to `MM_DROPS_ROOT` on the evidence volume:
two writes of a multi-gigabyte recording, a cap that can only be checked after
the bytes have landed, and `TMPDIR` as the real limit. Driving
`python_multipart.MultipartParser`'s callbacks over `request.stream()` writes
each part once, where it belongs, and lets the byte counter refuse mid-stream.

**Why `url` stays a required string.** Story 6.5 is being built in parallel
against the current OpenAPI. Making `url` nullable would change a field its
generated client already uses, so an upload acquisition records the opaque
source reference `upload:<sessionId>` and the new `kind` field is what tells a
client whether `url` is a link. `sourceId` is still content-derived.

**Why upload rules live in `uploads.py`.** `test_api_acquisitions.py` pins
`set(acquisitions.REMEDIATIONS) == set(youtube.REFUSAL_RULES)`. Upload refusals
are a second closed vocabulary with the same three-field shape, joined only at
`refusal_for()` and `problem_status()`.

**Why no migration.** 0020 was reserved and is not needed: a session is
transient producer-side state with a filesystem lifetime, exactly like story
6.4's acquisition status file, and it is deleted the moment the drop exists.

**Built here, not delegated.** The workflow's step-03 hands implementation to a
context-free subagent. This run implemented it directly instead, on the
operator's explicit "work synchronously, no background agents" instruction and
because the load-bearing part — the identity equality between an upload and a
hand mint — is a judgement about `mintdrop`'s call order that does not survive
being restated to a fresh agent. Recorded here so the reviewer knows which
process produced the diff.

**The client was regenerated without a live api.** `make client` health-checks
:8000 and this wave may not start one. The schema was dumped from
`app.openapi()` and openapi-ts pointed at the file, with `servers` injected
because generating from a URL is where the client's `baseUrl` otherwise comes
from — `client.gen.ts` is unchanged, which is where that difference would show.

**A failed acquisition loses the upload.** The acceptance criteria say the
staging directory is removed "once the drop is finalized or the acquisition
fails", so it is — which means an ffprobe hiccup costs a multi-gigabyte
re-upload. Implemented as written rather than softened; whether a failed
acquisition should keep its session for a retry is an owner's call, not a
builder's.

**Recompiled epic context, reverted.** `epic-6-context.md` was recompiled as the
workflow requires; the result was materially identical to the committed file
(only the generator comment differed), so the file was left at its committed
content rather than carrying a cosmetic diff into a shared artifact during a
parallel wave.

## Verification

**Results at `1db5b9b7` (2026-08-31), against this worktree's own stack:**

- `make lint` -- All checks passed.
- `make typecheck` -- Success: no issues found in 13 source files.
- `uv run --project server pytest -m "" server/tests/test_api_uploads.py -q` --
  47 passed.
- `uv run --project server pytest -m "" server/tests/test_api_acquisitions.py -q`
  -- 40 passed.
- `make web-test` -- 59 files, 669 tests passed.
- `make test` -- **2773 passed, 3 skipped, 0 failed in 696.71s**, plus web 669,
  evals 655, puller 92, and the web build. The 3 skips are pre-existing and
  unchanged: the same 3 appeared in the run before this story's pins landed.
- `python3 _bmad/scripts/branch_conflicts.py --against story/6-4a` -- this
  branch's own overlaps are `docs/backlog.md` (appended items),
  `web/src/client/*` (regenerated), `server/tests/test_api_registry.py` against
  story/10-3 (both add a router to the baseline list), and
  `config.yaml`/`config.py`/`test_config.py` against story/10-4 (both add config
  keys). Every other file in those rows is the other branch's own overlap with
  main.

**Commands:**
- `make lint` -- expected: ruff clean over the whole server tree.
- `make typecheck` -- expected: mypy clean over the decision-core modules.
- `uv run --project server pytest server/tests/test_api_uploads.py server/tests/test_api_acquisitions.py -v`
  -- expected: all pass, no skips other than named ones.
- `make test-fast` -- expected: `check-client`, lint, typecheck, the three
  store-free suites and the fast set all green; every skip printed with a reason.
- `uv run --project server pytest -m "" server/tests/test_api_uploads.py` --
  expected: the slow-marked ffprobe rows run and pass.
- `python3 _bmad/scripts/branch_conflicts.py --against story/6-4a` -- expected:
  no overlapping hunks with an in-flight branch.

**Manual checks (if no CLI):**
- `git diff --stat web/src/client/` shows only additions for the three upload
  operations and their models; no unrelated churn from a different generator
  version.
