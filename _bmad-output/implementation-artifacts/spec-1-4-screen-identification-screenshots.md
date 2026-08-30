---
title: 'Story 1.4: Screen Identification & Screenshots'
type: 'feature'
created: '2026-08-18'
baseline_revision: 'ea33274e1bc3773959c1bcdb7eaf947932ccf963'
baseline_commit: 'ea33274e1bc3773959c1bcdb7eaf947932ccf963'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
warnings: ['oversized']
deferred:
  - summary: >-
      Re-running `frames` alone, while `ocr` and `screens` are already checkpointed `done`, leaves a
      meeting with regenerated JPEGs, zero OCR rows, and screenshots whose representative frame is
      NULL.
    evidence: |-
      The runner skips any stage in _SETTLED_STAGE_STATUSES, and frames.run deletes the meeting's
      `frame` rows, which cascades `frame_ocr` away and nulls screenshot.representative_frame_id. No
      downstream checkpoint is invalidated when an upstream stage re-executes. Pre-existing story-1.3
      resume semantics; story 1.4 is the first story with downstream state to corrupt. Not reachable
      through the normal intake path, which re-seeds all eight stages, so it needs a deliberate
      operator reset. Closing it means deciding whether a stage rerun invalidates its successors,
      which spans every remaining pipeline story.
    location: >-
      server/meetingminer/pipeline/runner.py (run_job stage loop)
    severity: medium
  - summary: >-
      The shipped `screens` thresholds exceed NFR2's over-capture guardrail on every real meeting
      measured, by 1.2x to 17x.
    evidence: |-
      NFR2 (epics.md:59) caps distinct captures at one per minute of meeting duration, and Epic 5
      story 5.2 fails a run above it. Measured across all nine real meetings this pipeline has now
      processed, captures per minute are 1.23, 2.19, 3.00, 3.27, 4.36, 6.42, 6.61, 7.63 and 16.99 --
      every one over the cap. Story 1.4's acceptance criterion cites only NFR8 (over-capture
      preferred to loss), so the current behavior implements the stated intent; the two NFRs pull
      opposite ways and choosing the operating point needs the scripted ground-truth corpus that does
      not exist yet. `stage.screens.captured` now carries `captures_per_minute` so the gap is visible
      per meeting instead of silent.
    location: >-
      config.yaml (pipeline.screens thresholds)
    severity: medium
  - summary: >-
      Screen identity records nothing about which OCR engine produced its signature, so engaging the
      Tesseract fallback silently forks every screen lineage in the corpus.
    evidence: |-
      identity_key_for is sha256 of the normalized text with no engine or recognizer-revision
      component, and `screen` has no engine column (`frame_ocr` does). Apple Vision and Tesseract do
      not produce byte-identical normalized text for the same screen, and VNRecognizeTextRequest is
      created without pinning setRevision_, so a macOS upgrade has the same effect. Whether the right
      answer is recording the engine, pinning the revision, or keying identity on it is a design
      decision that belongs with the Epic 5 eval baselines.
    location: >-
      server/meetingminer/pipeline/screens.py (identity_key_for)
    severity: medium
  - summary: >-
      OCR block confidence is captured and persisted but never used; low-confidence text feeds screen
      identity, Jaccard comparison, and view-type density unfiltered.
    evidence: |-
      OcrBlock.confidence is stored in frame_ocr.blocks, but ScreensConfig has no minimum-confidence
      threshold and neither normalize_text nor signature_for filters on it. Tesseract's -1
      confidences are folded to 0.0 and then averaged in. Picking a threshold is tuning work that
      belongs with the eval harness.
    location: >-
      server/meetingminer/adapters/ocr/port.py
    severity: low
  - summary: >-
      Orphaned `screen` rows accumulate with no cleanup path and no query that could even find them.
    evidence: |-
      A screens rerun with different segmentation leaves the previous run's screen rows referenced by
      nothing, and `meeting:<id>:<ordinal>` scoped rows survive their meeting's deletion because
      `screenshot` cascades and `screen` does not. Never deleting screens by a stage rerun is correct
      per AD-5, so this needs a deliberate garbage-collection story rather than a stage change.
    location: >-
      server/meetingminer/migrations/0003_screens_screenshots.sql (screen)
    severity: low
  - summary: >-
      Screen lineage loads every `screen` row in the corpus on every run and scores them in Python,
      so cost grows with total corpus size rather than with the meeting being processed.
    evidence: |-
      _ScreenUpserter.__init__ issues an unbounded SELECT over `screen`, and best_lineage_match then
      does a Jaccard scan of every non-scoped signature per capture. At 1857 screens after nine
      meetings this is already O(captures x screens) per meeting and grows with the corpus. Bounding
      it wants a signature index (trigram or prefix) rather than a code tweak.
    location: >-
      server/meetingminer/pipeline/stages/screens.py (_ScreenUpserter)
    severity: low
  - summary: >-
      `screenshot.capture_cues` has no CHECK constraint, unlike the guarded `view_type` columns beside
      it, so an unrecognized cue value would persist silently.
    evidence: |-
      The four cue names are module constants in pipeline/screens.py with no database-side guard.
      Adding the CHECK means editing migration 0003, which is already applied to the development
      database, and the project has no migration-checksum drift detection (itself already deferred
      from story 1.2) -- so the constraint belongs in a later migration rather than an edit in place.
    location: >-
      server/meetingminer/migrations/0003_screens_screenshots.sql (screenshot.capture_cues)
    severity: low
---

<intent-contract>

## Intent

**Problem:** A recording job stops at `ocr`: frames are sampled but nothing reads them, no screen is identified, and no screenshot exists. FR6 — "every distinct application screen or slide captured, so no shown screen is lost" — has no implementation, and stories 1.6 (moments) and 1.7 (projections) have no `SCREEN`/`SCREENSHOT` rows to build on.

**Approach:** Add the `Ocr` adapter port (Apple Vision primary, Tesseract fallback, both bound in `config.yaml`) and the two stages that consume it: `ocr` stores recognized text and block geometry per frame; `screens` groups consecutive frames by OCR-text similarity, emits a screenshot per capture with its cue and view type, and upserts a cross-meeting `Screen` entity by identity key.

## Boundaries & Constraints

**Always:**
- AD-8: feature code calls the project-owned `Ocr` port only — never PyObjC/Vision or a tesseract call site outside `server/meetingminer/adapters/ocr/`. Engine choice and every threshold come from `config.yaml` (AD-10); swapping `apple-vision` ↔ `tesseract` is a config edit with no feature-code change.
- `adapters` never import `domain` or `pipeline`; `pipeline` may import `domain` and `adapters`; `api` never imports `pipeline`.
- AD-3: screenshot images are written under `MM_CONTENT_ROOT/meetings/<meeting_id>/screenshots/`; the DB stores root-relative POSIX paths only.
- AD-11 idempotence: a rerun of `ocr` or `screens` replaces only rows keyed to *this* meeting, and only that meeting's own subtree on disk.
- AD-5: `screen` is a cross-meeting entity — upserted by identity key, **never** deleted or truncated by a stage rerun. Screenshots (per-meeting) are replaced.
- NFR8 bias to over-capture: an uncertain boundary produces an extra capture, never a dropped one. Segmentation splits on OCR-text dissimilarity *or* encoded-frame-size delta, and a long dwell whose text has drifted produces a re-capture.
- Every capture records a view type (`slide` | `ui-screen` | `participant-gallery`) and the cue(s) that produced it.
- AD-1/AD-13: transcript-only drops still skip `ocr` and `screens`; the drop directory stays read-only — screenshots are copied out of the content root's frames, never out of the drop.
- Failures surface as a named `StageError`, recorded on `job_stage` and `job`; every worker/pipeline log line carries `job_id` and `stage` (NFR17/NFR18).
- A recording job now pauses at `transcribe` instead of `ocr`; nothing may be marked `done`/`skipped` on behalf of unbuilt stages.

**Block If:**
- Identifying screens would require image-similarity comparison rather than OCR text (explicit non-goal — the spine and eval design fix OCR-text similarity as the identity mechanism).
- Making Apple Vision usable would require the worker to run inside a container (AD-9 forbids it).

**Never:**
- No `transcribe`, `align`, `moments`, or `extract` implementations (stories 1.5–1.6, Epic 4).
- No projections, Neo4j, or Meilisearch writes (story 1.7); no participants or transcript rows (story 1.5).
- No API surface change — `GET /jobs/{id}` keeps its shape, so the committed TS client stays valid; no SSE work (story 1.9).
- No screenshot-serving endpoint and no UI (Epic 2).
- No image-similarity dedup, no perceptual hashing, no model-based screen classification.
- Never modify `pull_transcript/`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Recording job reaches the new stages | job with `frames` `done` | `ocr` + `screens` `done`; one `frame_ocr` row per frame; ≥1 `screenshot` row with a file under `meetings/<id>/screenshots/`; job stays `running` with `transcribe` `queued` | N/A |
| Distinct screens in one meeting | frames whose OCR text differs across a boundary | a separate screenshot per group, `capture_cues` naming `text-change` | N/A |
| Same screen in a later meeting | a capture whose signature matches an existing screen above the lineage threshold | the existing `screen.id` is reused (lineage); no duplicate screen row | N/A |
| Textless frames | frames whose OCR yields no text (camera gallery, video) | still captured; identity is scoped to this meeting rather than collapsed onto other textless screens | N/A |
| `ocr` rerun | `ocr` reset to `queued`, rows already present | this meeting's `frame_ocr` rows replaced, not duplicated; other meetings untouched | N/A |
| `screens` rerun | `screens` reset to `queued`, screenshots on disk | this meeting's screenshot rows and `screenshots/` subtree replaced; `screen` rows survive | N/A |
| Failed `screens` rerun | ffmpeg/copy or DB failure mid-rerun | previous screenshot files and rows remain intact | `StageError`, stage + job recorded `failed` |
| No OCR engine available | `apple-vision` unavailable and no usable fallback | `ocr` fails with a named engine error | `StageError` naming the engine and how to install it |
| Transcript-only retry replacing a recording | failed recording job re-POSTed transcript-only | stale screenshots (rows + files) are cleared along with frames/media before the video stages are skipped | recorded as a job failure if cleanup fails |
| Frames stage produced nothing | `frames` `done` but zero frame rows | `ocr` and `screens` complete with zero outputs and log it, rather than failing | N/A |

</intent-contract>

## Code Map

- `server/meetingminer/pipeline/stages/__init__.py` — `STAGE_IMPLEMENTATIONS` (`:23`) is the registry; unregistered = pause. Add `ocr` and `screens` here (one line each) — nothing else in the runner changes for stage arrival.
- `server/meetingminer/pipeline/stage.py` — `StageContext` (`:31`) with `meeting_dir()` (`:49`), `relative_path()` (`:58`), and the `after_commit`/`after_rollback` hooks (`:46`) both new stages reuse; `StageError` (`:21`).
- `server/meetingminer/pipeline/stages/frames.py` — `_assert_private_frames_dir()` (`:24`) and the staging→backup→`os.replace` durability dance (`:99`–`:137`). This is the logic to **extract and reuse**, not to copy: it is the shape the story-1.3 review hardened.
- `server/meetingminer/pipeline/runner.py` — `_clear_replaced_video_evidence()` (`:136`) deletes `frame`/`meeting_media` and the `frames/` subtree; it must also clear screenshots. `run_job()` (`:201`) needs no other change.
- `server/meetingminer/pipeline/media.py` — `MediaToolError` (`:34`), `_run()` (`:60`) subprocess contract to mirror for the tesseract engine.
- `server/meetingminer/config.py` — `OcrConfig` (`:99`) is the AD-8 binding to extend with `fallback`; `FramesConfig`/`PipelineConfig` (`:157`–`:169`) are the pattern for a `ScreensConfig`; `_StrictModel` is `extra="forbid"` (`:92`).
- `config.yaml` — `ocr:` (`:8`) and the `pipeline:` block (`:47`): every threshold this story introduces belongs here, not in code.
- `server/meetingminer/adapters/__init__.py` — currently a docstring only (`:1`); the `Ocr` port and its two engines land under `adapters/ocr/`.
- `server/meetingminer/migrations/0002_meetings_media_frames.sql` — `frame` (`:76`, unique per meeting+offset), `meeting` (`:26`), and the `set_updated_at()` trigger function (`:7`) the new tables must wire up. Next migration file is `0003_`.
- `server/meetingminer/db.py` — `MIGRATIONS_DIR` (`:27`); migrations apply in filename order.
- `server/tests/conftest.py` — `EVIDENCE_TABLES` (`:140`) must name every new table (its comment says a missing one should fail loudly); `content_root` (`:199`), `synthetic_recording` (`:207`), `requires_ffmpeg` (`:186`), `make_drop` (`:152`), `valid_metadata()` (`:66`).
- `server/tests/test_worker_runner.py` — `enqueue()` (`:46`), `stage_statuses()` (`:68`), `make_recording_drop` (`:33`) to reuse. `test_recording_drop_runs_probe_and_frames_then_pauses` (`:141`) asserts `STAGE_NAMES[2:] == ["queued"]*6` and **must be updated**: the pause moves to `transcribe`.
- `server/meetingminer/pipeline/stages/probe.py` — the minimal stage shape (upsert + one log event) to imitate.
- `server/pyproject.toml` — dependency list (`:6`); Apple Vision needs PyObjC, added with a `sys_platform == "darwin"` marker so the lock stays resolvable elsewhere.
- `infra/Makefile` — `check-tools` (`:95`) is where ffmpeg/ffprobe are required; tesseract is optional and must **not** become a hard requirement.
- `_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md` — read-only authority: AD-3 (`:186`), AD-4 (`:192`), AD-5 (`:198`), AD-8 (`:212`), AD-11 (`:234`), stage list (`:135`), ERD `SCREEN ||--o{ SCREENSHOT` / `MEETING ||--o{ SCREENSHOT` (`:356`–`:361`), `screens` note (`:377`).
- `pull_transcript/` — READ-ONLY corpus; never written by this story.

## Tasks & Acceptance

**Execution:**
- `server/meetingminer/adapters/ocr/port.py` — define `OcrError`, `OcrBlock` (text + normalized `x/y/width/height` + confidence), `OcrResult` (blocks, reading-order `text`, `engine`), and the `Ocr` protocol (`recognize(path) -> OcrResult`). No provider import here.
- `server/meetingminer/adapters/ocr/apple_vision.py` — Vision `VNRecognizeTextRequest` via PyObjC, imported lazily so a non-macOS host reports unavailability instead of failing at import. Expose an `available()` probe and raise `OcrError` naming the missing framework.
- `server/meetingminer/adapters/ocr/tesseract.py` — `tesseract <image> stdout tsv` subprocess wrapper parsing the TSV into blocks; missing binary → `OcrError` naming `brew install tesseract`.
- `server/meetingminer/adapters/ocr/__init__.py` — `build_ocr(ocr_config)` factory: construct the configured `engine`, and when it is unavailable fall back to the configured `fallback` (logging the substitution once); raise `OcrError` when neither is usable. This is the only place either engine is named.
- `server/meetingminer/config.py` — add `fallback: Literal["apple-vision","tesseract"] | None` to `OcrConfig`; add `ScreensConfig` (`similarity_threshold`, `lineage_threshold`, `dwell_seconds`, `dwell_drift_threshold`, `size_delta_ratio`, `min_signature_tokens`, `gallery_max_blocks`, `gallery_max_text_density`, `slide_min_block_height`, `slide_max_blocks`) with bounded `Field` constraints, and hang it off `PipelineConfig`.
- `config.yaml` — set `ocr.fallback: tesseract` and add the `pipeline.screens:` block with the documented defaults from Design Notes.
- `server/meetingminer/migrations/0003_screens_screenshots.sql` — `frame_ocr` (frame PK, meeting FK, engine, `text`, `normalized_text`, `block_count`, `text_density`, `mean_block_height`, `blocks` jsonb); `screen` (uuidv7 pk, `identity_key` UNIQUE, `signature`, `label`, `view_type` CHECK); `screenshot` (uuidv7 pk, meeting FK, screen FK, `ordinal`, `start_offset_ms`, `end_offset_ms`, `frame_count`, `representative_frame_id`, root-relative `path`, `view_type` CHECK, `capture_cues` text[], UNIQUE (meeting_id, ordinal)); plus `set_updated_at` triggers on all three and a `frame_ocr(meeting_id)` index.
- `server/meetingminer/pipeline/outputs.py` — extract the frames durability dance into one reusable `OutputDirSwap(ctx, subdir)`: symlink/escape guard, orphan-backup recovery, staging directory, atomic `os.replace`, and the `after_commit`/`after_rollback` hooks. Behavior must stay identical to today's `frames`.
- `server/meetingminer/pipeline/stages/frames.py` — rewrite on top of `OutputDirSwap`, deleting the now-duplicated helpers. No behavior change.
- `server/meetingminer/pipeline/screens.py` — the pure, DB-free core: `normalize_text()`, `tokens()`, `jaccard()`, `segment_captures()` (frames + sizes → captures with offsets, cues, representative frame), `classify_view_type()`, `signature_for()` / `identity_key_for()`. Unit-testable without Postgres or an OCR engine.
- `server/meetingminer/pipeline/stages/ocr.py` — build the port once, recognize every frame of this meeting in offset order, replace this meeting's `frame_ocr` rows, log one summary event (engine, frame count, frames with text).
- `server/meetingminer/pipeline/stages/screens.py` — read this meeting's frames + OCR rows, stat each frame file for the size-delta cue, run the core, copy representative frames into a swapped `screenshots/` directory, upsert `screen` by identity key (with lineage lookup above `lineage_threshold`), replace this meeting's `screenshot` rows, log a summary event.
- `server/meetingminer/pipeline/stages/__init__.py` — register `ocr` and `screens`.
- `server/meetingminer/pipeline/runner.py` — extend `_clear_replaced_video_evidence()` to delete this meeting's `screenshot` rows and its `screenshots/` subtree alongside frames/media.
- `server/pyproject.toml` — add `pyobjc-framework-Vision` under a `sys_platform == "darwin"` marker; refresh `server/uv.lock`.
- `server/tests/conftest.py` — add `frame_ocr`, `screen`, `screenshot` to `EVIDENCE_TABLES`; add a deterministic fake-`Ocr` fixture and a `requires_ocr` skip marker.
- `server/tests/test_screens_core.py` — unit-cover the pure core: text-change split, size-delta split, dwell-drift re-capture, representative selection, each view-type branch, blank-text identity scoping, Jaccard boundaries.
- `server/tests/test_ocr_adapter.py` — `build_ocr` returns the configured engine and falls back when the primary is unavailable; each engine recognizes text in a generated high-contrast image, skipping with a named reason when unavailable.
- `server/tests/test_worker_runner.py` — update the pause assertion to `transcribe`; add matrix rows: OCR + screens produce rows and files, reruns replace without duplicating, screens survive as cross-meeting entities, transcript-only replacement clears screenshots, a failed screens rerun retains the previous output, an OCR engine failure is recorded on stage + job.

**Acceptance Criteria:**
- Given the epics.md Story 1.4 acceptance criteria, when each is exercised against the running worker, then it passes as written.
- Given `config.yaml` with `ocr.engine: tesseract`, when the worker runs the same drop, then the tesseract engine is used and no file outside `server/meetingminer/adapters/ocr/` changed.
- Given two meetings whose recordings show the same screen, when both are ingested, then their screenshots reference one `screen` row, and re-running `screens` on either meeting leaves that row present.
- Given `uv run --project server pytest server/tests`, when run with the compose Postgres up, then the whole suite passes with no new skips beyond the documented ffmpeg/Postgres/OCR-engine ones.

### Review Findings

- [x] [Review][Patch] Empty `screens` reruns leave stale screenshot files [server/meetingminer/pipeline/stages/screens.py:187] — fixed by atomically publishing an empty replacement directory; a populated-to-empty rerun is regression-tested.
- [x] [Review][Patch] Tesseract parser can violate the normalized geometry contract [server/meetingminer/adapters/ocr/tesseract.py:113] — fixed by rejecting non-finite values and clipping page-overrun boxes before line aggregation; malformed TSV coverage added.
- [x] [Review][Patch] Intermediate output-path symlink guards lack regression coverage [server/tests/test_output_dir_swap.py:201] — fixed by parameterizing regression coverage for `meetings/`, the meeting directory, and the final output directory.

## Spec Change Log

## Review Triage Log

### 2026-08-18 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 17: (high 0, medium 5, low 12)
- defer: 8: (high 0, medium 3, low 5)
- reject: 5: (high 0, medium 0, low 5)
- addressed_findings:
  - `[medium]` `[patch]` `normalize_text` deleted every non-ASCII letter, so accented, Cyrillic and CJK screens normalized to nothing and never gained lineage — switched to a Unicode-aware split and covered by tests.
  - `[medium]` `[patch]` The `screen` INSERT had no `ON CONFLICT`, so a race aborted the stage and an exact-key hit left a meeting-scoped row's stale signature and view type forever — now a real upsert, which also makes the `set_updated_at` trigger reachable.
  - `[medium]` `[patch]` `_clear_replaced_video_evidence` left `.frames-previous` / `.screenshots-previous` behind, and the next `open_staging` restored them onto the emptied target — resurrecting exactly the video evidence a transcript-only replacement erases.
  - `[medium]` `[patch]` Mutation testing proved the `size-delta` cue could be killed outright (`size_bytes=0` in `_load_frames`) with the whole suite green — every worker test disabled the cue; added a DB-backed test at the shipped ratio.
  - `[medium]` `[patch]` Mutation testing proved the entire screen-lineage branch could be deleted with the suite green — the two-meeting test scripted identical text and never reached it; added a near-duplicate-text case.
  - `[low]` `[patch]` `min_signature_tokens` allowed `0`, which inverts the guard and collapses every textless screen in the corpus onto one row — now `ge=1`.
  - `[low]` `[patch]` A first-ever run that failed after `publish()` left a populated `screenshots/` directory no row named — `restore()` now deletes it when there is no backup behind it.
  - `[low]` `[patch]` Killed processes leaked `.<subdir>-XXXX` staging directories forever, the orphan-backup `os.replace` escaped as an unnamed OSError, and a non-directory at the target was not refused.
  - `[low]` `[patch]` Commit hooks ran inside the runner's `try`, so a failing hook triggered `after_rollback` and reverted the directory the committed rows named — moved out, with a `stage.hook_failed` event.
  - `[low]` `[patch]` A NUL in recognized text failed the insert on a readable frame (text and the jsonb blocks payload both), and a 1700-frame meeting logged nothing for six minutes — NULs stripped, periodic progress event added.
  - `[low]` `[patch]` Zero-frame and zero-capture log paths omitted fields the populated paths emit; parity restored and `captures_per_minute` added so the NFR2 tension is observable.
  - `[low]` `[patch]` Tesseract silently recognized a page of text as empty on an unexpected TSV header, and admitted negative geometry; both now named errors or dropped rows.
  - `[low]` `[patch]` Apple Vision bounding boxes outside the unit square skewed density and classification, and a lazy `Foundation` import escaped as `ImportError` — clamped and wrapped.
  - `[low]` `[patch]` The `Ocr` protocol omitted `unavailable_reason()` that the factory calls, `ENGINES` was untyped, a defensive `getattr` contradicted the declared binding, and four `available()` helpers were dead.
  - `[low]` `[patch]` An unusable OCR binding surfaced mid-pipeline after probe and frames had burned time — the worker now probes it at startup as a non-fatal named warning and reports `ocrEngineResolved`.
  - `[low]` `[patch]` The four core decision functions took a bare unannotated `config`; now typed `ScreensConfig`.
  - `[low]` `[patch]` `conftest.py` carried three module-level imports behind `# noqa: E402`; moved to the top with the rest.

## Design Notes

- **Why a `frame_ocr` table rather than a column on `frame`:** stage ownership. `frames` owns `frame`; `ocr` owns its own table, so an `ocr` rerun replaces only its rows and a `frames` rerun cascades them away. Stage checkpoints are *not* invalidated downstream by a rerun of an earlier stage — resetting `frames` alone leaves `screens` marked `done` over deleted evidence. That is an operator action outside this story; the runner's resume semantics are unchanged.
- **Segmentation and capture rules** (all thresholds in `config.yaml`, defaults in parentheses):
  - New segment when `jaccard(prev, cur) < similarity_threshold` (0.6) — cue `text-change` — or when `|size_cur − size_prev| / size_prev ≥ size_delta_ratio` (0.35) — cue `size-delta`. The encoded JPEG byte size is the bitrate-delta proxy: it moves when the picture changes even where there is no text at all (video, camera gallery), which is exactly where OCR similarity is blind.
  - Every segment start emits a capture. Within a long segment, a further capture is emitted when `offset − last_capture_offset ≥ dwell_seconds` (20) **and** `jaccard(last_capture, cur) < dwell_drift_threshold` (0.9) — cue `dwell-drift`. This catches slow drift (a form being filled, a page scrolled) without turning a static 30-minute slide into 90 near-identical screenshots.
  - Representative frame = the most text-rich frame the capture covers, earliest on a tie; a transition frame therefore never represents the screen.
- **Screen identity.** `signature` = normalized representative text; `identity_key` = its SHA-256. Exact match upserts; otherwise the best existing screen scoring `≥ lineage_threshold` (0.8) is reused, giving lineage across meetings. Below `min_signature_tokens` (3) tokens the signature carries no evidence, so the key is scoped to the meeting (`meeting:<id>:<ordinal>`) rather than collapsing every textless screen in the corpus into one.
- **View type** from the representative frame's block geometry (normalized 0–1), first match wins: `block_count ≤ gallery_max_blocks` (6) and `text_density < gallery_max_text_density` (0.02) → `participant-gallery`; `mean_block_height ≥ slide_min_block_height` (0.04) and `block_count ≤ slide_max_blocks` (25) → `slide`; otherwise `ui-screen`. Deterministic and tunable by config — the Epic 5 harness scores it, so it must not be a model call.
- **Why `fallback` on the `ocr` binding:** AC 1 asks for Apple Vision *primary* with Tesseract as a *swappable fallback*. One `engine:` key cannot express both, so the binding mirrors the `llm.roles.*.fallback` shape already in `config.yaml`. The fallback engages only when the primary engine is unavailable on the host, and the substitution is logged.

```
MM_CONTENT_ROOT/meetings/<meeting_id>/
  frames/frame-000123.jpg        # frames stage (story 1.3)
  screenshots/screenshot-0001.jpg  # DB stores "meetings/<id>/screenshots/screenshot-0001.jpg"
```

## Verification

**Commands:**
- `uv run --project server pytest server/tests` — expected: all pass (start Postgres with `make infra-up` first; ffmpeg/OCR-dependent tests skip only with their named reason).
- `make migrate && make migrate` — expected: applies `0003_...` once; the second run reports nothing to apply.
- `make test` — expected: server suite passes and the web build succeeds unchanged (no API surface change, so the committed TS client stays valid).
- `make up`, POST a recording drop to `/ingests`, then `GET /jobs/{id}` — expected: `probe`/`frames`/`ocr`/`screens` `done`, `transcribe` `queued`; screenshots exist under `MM_CONTENT_ROOT/meetings/<id>/screenshots/`; `.logs/worker.log` carries `job_id` + `stage` on every line; the drop directory's file list, sizes, and mtimes are unchanged.
- `uv run --project server python -c "from meetingminer.config import load_config; from meetingminer.adapters.ocr import build_ocr; print(build_ocr(load_config().settings.ocr))"` — expected: prints the Apple Vision engine on this Mac, and names the fallback if Vision is unavailable.

## Auto Run Result

Status: done

**Implemented change.** The `Ocr` adapter port (AD-8) plus the `ocr` and `screens` pipeline stages.
`ocr` recognizes every sampled frame through whatever engine `config.yaml` binds and stores text and
block geometry per frame. `screens` groups frames into captures by OCR-text similarity with
encoded-size and dwell-drift cues, writes one screenshot per capture with its view type and cues, and
resolves each capture to a cross-meeting `Screen` upserted by identity key. A recording job now
advances to `transcribe` instead of pausing at `ocr`.

**Files changed**
- `server/meetingminer/adapters/ocr/{port,apple_vision,tesseract,__init__}.py` — the port, both engines, and `build_ocr`, the only place either engine is named.
- `server/meetingminer/pipeline/screens.py` — the DB-free decision core: normalization, Jaccard, segmentation, representative choice, view-type classification, screen identity and lineage.
- `server/meetingminer/pipeline/stages/{ocr,screens}.py` — the I/O around those decisions; registered in `stages/__init__.py`.
- `server/meetingminer/pipeline/outputs.py` — `OutputDirSwap` / `remove_meeting_subdir`, the durability dance extracted from `frames.py` and shared by both media stages.
- `server/meetingminer/pipeline/stages/frames.py` — rewritten on the shared swap, no behavior change.
- `server/meetingminer/pipeline/runner.py` — clears screenshots and the swap's sibling directories on a transcript-only replacement; commit hooks moved off the rollback path.
- `server/meetingminer/migrations/0003_screens_screenshots.sql` — `frame_ocr`, `screen`, `screenshot` plus triggers.
- `server/meetingminer/config.py`, `config.yaml` — `ocr.fallback` and the `pipeline.screens` thresholds.
- `server/meetingminer/worker/main.py` — non-fatal OCR-binding probe at startup; `ocrEngineResolved` on `worker.startup`.
- `server/pyproject.toml`, `server/uv.lock` — `pyobjc-framework-Vision` / `-Quartz`, macOS-only markers.
- `infra/Makefile` — a comment recording that tesseract is deliberately not a required tool.
- `server/tests/` — `test_screens_core.py`, `test_ocr_adapter.py`, `test_output_dir_swap.py`, plus worker-runner matrix rows and conftest fixtures.

**Review findings.** 4 layers (blind hunter, edge-case hunter, verification-gap with mutation testing,
intent-alignment). 17 patched, 8 deferred, 5 rejected. No intent gaps and no spec-level defects.

**Follow-up review recommended: true.** Patched by severity: high 0, medium 5, low 12.
Score = 3x5 + 1x12 = 27, at or above the threshold of 5.

**Verification performed** (all re-run after the patch round):
- `uv run --project server pytest server/tests` — 294 passed, 0 skipped.
- `make test` — 294 passed, web build succeeded unchanged.
- `make migrate && make migrate` — nothing to apply twice; `schema_migrations` records `0003_screens_screenshots.sql` applied once.
- `build_ocr(load_config().settings.ocr)` — `AppleVisionOcr`.
- Live stack: a real 57-minute meeting reached `probe/frames/ocr/screens` `done` with `transcribe` `queued`, 1727 frames, 1727 OCR rows, 188 screenshots, every stored path relative and present on disk; all pipeline log records since the current worker start carry `job_id` and `stage`.
- I/O matrix audit: all 10 rows covered by tests that ran and passed.

**Residual risks.**
- The `ocr` stage holds one transaction for the whole meeting — about six minutes and ~600 MB RSS for a 57-minute recording. It is the longest-held transaction in the system; the progress event makes it observable but does not shorten it.
- Capture density exceeds NFR2 on every real meeting measured (deferred above). Epic 5's gate will fail until the thresholds are tuned against a ground-truth corpus.
- Screen lineage reuse is running at roughly 18% across nine real meetings (1857 screens from 2266 screenshots); whether that reflects the corpus or too strict a `lineage_threshold` is unknown without ground truth.
- `tesseract` was installed on this machine to verify the fallback end-to-end. It is not a required tool, and its tests skip with a named reason where it is absent.
