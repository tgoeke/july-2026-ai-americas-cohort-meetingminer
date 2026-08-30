---
title: 'Story 1.5: Transcript Verification, Alignment & Participants'
type: 'feature'
created: '2026-08-18'
baseline_revision: 'a16c19872d4bf72dca393b0ce22dbf17ea160f8b'
baseline_commit: 'a16c19872d4bf72dca393b0ce22dbf17ea160f8b'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
  - '{project-root}/_bmad-output/specs/spec-meetingminer/corpus-facts.md'
warnings: ['multiple-goals', 'oversized']
deferred:
  - summary: >-
      A meeting ingested before the puller bridges the participant graph into the drop, and the
      same meeting ingested after, key the same humans differently — `name:avery reed` versus
      `mail:avery.reed@corp.com` — so one person becomes two `participant` rows with no link
      between them.
    evidence: |-
      Measured end to end on the real drop
      `2026-04-28-supplier-hub-design-icontract-review-059c6916`, run twice: once as it exists
      today (no `participants` key, 9 name-keyed participants) and once with the live
      `org chart.json` mapped into `metadata.participants` (10 participants, 9 mail-keyed plus the
      external falling back to a name key). Across the two meetings that is 18 distinct
      `participant` rows for what is really 10 people. Today the corpus has no drops carrying the
      graph, so nothing is split yet — the split appears the moment the bridge lands and older
      meetings are not re-ingested. The alias table is the designed remedy (AD-5) and it works,
      but it needs a human to run it, and nothing currently surfaces which rows need merging.
      Closing this means deciding whether the bridge landing triggers a backfill re-ingest, or a
      one-off reconciliation that writes alias rows by matching normalized names to mails. That
      choice also bears on story 1.12, whose late-recording augmentation requires identity to
      survive a later augmenting ingest.
    location: >-
      server/meetingminer/pipeline/speakers.py (identity_key_for) and the puller's emit-drop step
    severity: medium
  - summary: >-
      The participant graph treats a conference room as a person, and the pipeline stores it as
      one.
    evidence: |-
      The live org chart for the 4.28.26 occurrence lists `VA30-09012-Conference Room 1` with
      `mail: va30-room09012@corp.com`, and it lands as a `participant` row indistinguishable from a
      human. The graph is the source of record for who attended and this story does not second-guess
      it, so filtering rooms out here would be inventing a rule the source did not state. It matters
      downstream: a room in the participants list skews the "who was in the room" query and any
      share-of-talk view, and rooms have `spokeTurns: 0` but so do silent humans.
    location: >-
      server/meetingminer/pipeline/stages/align.py (_graph_roster)
    severity: low
  - summary: >-
      `transcript_segment.stt_source_id` is `ON DELETE CASCADE`, so deleting the STT lane destroys
      derived rows whose text and speaker labels came from the provided `.txt`, not from STT.
    evidence: |-
      The anchor is one column on a row whose other content is independent of it. `transcribe`
      upserts rather than deletes (now regression-tested), and the runner's transcript-only cleanup
      deliberately re-queues `align` afterwards, so no path in this story reaches the bad state.
      It is one careless `DELETE FROM transcript_source` away, and `ON DELETE SET NULL` plus an
      `align` requeue would express the intent better than CASCADE.
    location: >-
      server/meetingminer/migrations/0005_transcripts_participants.sql (transcript_segment)
    severity: medium
  - summary: >-
      No automated test reads a real corpus transcript or a real `org chart.json`; every parsing,
      alignment, and identity assertion runs against hand-authored fixtures.
    evidence: |-
      The rules were derived from measured corpus facts — the past-the-hour `MM:SS`->`HH:MM:SS`
      switch, the legacy preamble, mail on 222/225 person-rows — but the fixtures reproduce the
      documented shapes rather than the files. The real 2-hour legacy transcript that motivated the
      field-count rule (`08:47` early, `01:57:24` late) sits at a known path and is never parsed by
      the suite. The corpus was exercised by hand this run (28/28 transcripts parse; the 4.28.26
      occurrence ran end to end both with and without its live org chart) but nothing re-runs that.
      A corpus-gated test module, skipped with a named reason when the drops root is absent, would
      turn those one-off measurements into a regression net.
    location: >-
      server/tests/test_transcripts_core.py and server/tests/test_worker_transcripts.py
    severity: medium
  - summary: >-
      With a participant graph present, a speaker the graph omits is recorded `unresolved` and never
      becomes a participant — the graph is read as the authority, not unioned with transcript labels.
    evidence: |-
      AC 4's "derived from transcript speaker attribution joined to the drop's participant graph" is
      readable either way. The graph-as-authority reading is what corpus-facts §4 argues for
      ("treat the chart as the participant source of record and the transcript as the corroborating
      signal"), and it is what never-guess implies. On today's data the readings are
      indistinguishable because no drop carries a graph; the difference becomes load-bearing the
      moment the bridge lands. Worth an explicit decision before then rather than after.
    location: >-
      server/meetingminer/pipeline/stages/align.py (_graph_roster / run)
    severity: medium
  - summary: >-
      An empty provided `transcript.txt` parses as a legitimate zero-turn transcript but fails the
      `align` stage; neither behaviour is pinned by a test.
    evidence: |-
      `parse_text_transcript` documents "a legitimate zero-turn transcript, not a parse failure" and
      is unit-tested for it, but at the stage boundary a zero-segment text source leaves no label
      source and the guard raises. The two halves disagree and no test records which is intended.
    location: >-
      server/meetingminer/pipeline/stages/align.py (run, label-source selection)
    severity: medium
  - summary: >-
      `transcript_source` declares four kind/format/path coherence rules in comments that no
      constraint enforces, and `participant.normalized_name` has no index.
    evidence: |-
      `kind='stt'` should imply `format='stt'`, `content_path IS NOT NULL`, `drop_relative_path IS
      NULL`; a provided kind implies the reverse. All four are written in comments and none is
      checkable. Separately, the `normalized_name` comment says it exists "so a name lookup still
      works on a row whose identity is a mail address" — that lookup is a sequential scan today.
    location: >-
      server/meetingminer/migrations/0005_transcripts_participants.sql
    severity: low
  - summary: >-
      `align` inserts derived rows one round-trip at a time while the participant insert beside it
      uses `executemany`.
    evidence: |-
      The module's own `PROGRESS_EVERY_SEGMENTS = 500` heartbeat exists because this loop is slow on
      the multi-thousand-segment meetings the docstrings cite. Batching it is mechanical.
    location: >-
      server/meetingminer/pipeline/stages/align.py (run, segment insert loop)
    severity: low
  - summary: >-
      `speakers.roster_from_labels` is not called by any production code, and `transcribe.speaker_at`
      is never exercised with any diarization turns.
    evidence: |-
      `align` builds its roster with its own `_label_roster`, which re-implements the same
      placeholder rule against `RosterEntry`; `roster_from_labels` is referenced only by tests, so a
      test reading as coverage of the stage's rule actually pins an unused function. `speaker_at` is
      the longest-overlap diarization picker and the only bundled diarizer returns no turns, so it
      has no coverage at all — it becomes live the moment a real diarizer is bound.
    location: >-
      server/meetingminer/pipeline/speakers.py and server/meetingminer/pipeline/stages/transcribe.py
    severity: low
  - summary: >-
      Two file-digest helpers do the same job in two stage modules.
    evidence: |-
      `transcribe.sha256_of` (chunked, path-based) and `align._read_drop_file`'s inline
      `hashlib.sha256(raw)`; neither lives in a shared location.
    location: >-
      server/meetingminer/pipeline/stages/transcribe.py and .../align.py
    severity: low
---

<intent-contract>

## Intent

**Problem:** The pipeline pauses at `transcribe`. A meeting's evidence bundle has screens but no
trustworthy transcript: no STT verification lane, no reconciliation of the provided transcript
against it, no speaker attribution, and no participants — so no moment can ever say who said a thing,
and "no citation, no answer" has nothing to cite.

**Approach:** Add the `Stt` and `Diarizer` ports (AD-8) and build the `transcribe` and `align` stages.
`transcribe` runs STT over the recording's extracted audio. `align` parses the provided transcript in
both corpus lineages, reconciles it against the STT lane by text alignment within a ±2 s anchor
window, and writes *new* derived `transcript_segment` rows carrying provenance to both inputs (AD-13).
The same stage derives participants from speaker attribution joined to the drop's participant graph,
resolving identity through normalized display name scoped to that meeting's roster and then the
API-owned alias table (AD-5) — never guessing.

## Boundaries & Constraints

**Always:**
- Drop contents are read-only (AD-13). The provided transcript is parsed in place and never rewritten,
  copied over, or deleted; every derived row is new and names its inputs.
- Speaker attribution never guesses. A label resolving to no roster entry is recorded `unresolved`; one
  resolving to more than one is recorded `ambiguous`; a `Speaker N` / `Unknown` placeholder is recorded
  `placeholder`. None of the three is ever merged into a resolved participant.
- Parse transcript timestamps **by field count**: 2 fields → `MM:SS`, 3 → `HH:MM:SS`. Both lineages are
  second-precision, so the alignment anchor window is ±2 s, not a minute floor.
- Both lineages are parsed: Teams `[m:ss] Lastname, Firstname: text` (source of record) and legacy
  `<Name> | MM:SS` with the text on following lines. The legacy parser is not optional.
- Every threshold and engine binding comes from `config.yaml` (AD-8, AD-10). No model call decides
  alignment, attribution, or identity — evidence is deterministic code output.
- Participants and screens are cross-meeting entities upserted by identity key; a rerun never deletes
  them (AD-11). Meeting-scoped rows are replaced wholesale by a rerun.
- Externals (`unresolved: true` in the participant graph) are preserved as external participants —
  never dropped, never merged into a resolved person.

**Block If:**
- Closing story 1.6's open question (whether a transcript-only moment gets a source deep-link replay
  affordance) turns out to be required to finish this story. Record the dependency and proceed if it
  does not; HALT if a task cannot be completed without deciding it.
- The `align` stage cannot produce derived rows without either a provided transcript or STT output for
  a drop that has one of them — that is a bug, not a design choice; HALT rather than inventing a
  fallback that fabricates timing.

**Never:**
- No Microsoft Graph call and no AAD/directory-identifier dedup path. Graph is an explicit SPEC
  non-goal; `metadata.participants[].aadObjectId` is legacy schema surface this story ignores.
- No merging of two raw transcript sources into one raw source; reconciliation produces derived rows
  only.
- No changes under `pull_transcript/` — the puller is the upstream source of record and out of scope.
- No `moments` (1.6), `projections` (1.7), UI/SSE (1.9), or screen-capture retune (1.11) work; do not
  touch the `screens`/`ocr` stages or their config.
- No `.vtt` used as a substitute for the speaker-attributed `.txt` — in this corpus every drop `.vtt`
  is a speaker-less subtitle track.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Teams transcript + recording | drop with `recording.mp4` + Teams-format `transcript.txt` | `transcribe` writes STT rows; `align` writes derived segments whose speaker labels come from the `.txt` and whose timing is anchored to STT within ±2 s, each row naming both sources | No error expected |
| Legacy transcript | `<Name> \| MM:SS` blocks, `<Name> started transcription` preamble | preamble skipped, one segment per block, text joined from the following lines | No error expected |
| Past-the-hour timestamps | same file mixes `08:47` and `01:57:24` | both parse correctly (field count decides) | Malformed stamp → `StageError` naming file and line |
| VTT present alongside `.txt` | speaker-less `transcript.vtt` + Teams `.txt` | speaker labels from `.txt`, cue **end** timings from the VTT where a cue matches; VTT never supplies speakers | Unparseable VTT → recorded as a source with 0 segments, `.txt` still used |
| Recording, no transcript, noop diarizer | drop with `recording.mp4` only | derived segments are the STT segments, every `speaker_label` `Unknown` and `speaker_resolution` `placeholder` | No error expected |
| Transcript-only drop | no `recording.mp4` | `transcribe` is `skipped` by the runner; `align` runs on the provided transcript alone, `stt_source_id` NULL | No error expected |
| Drop omits participants | no `metadata.participants` | roster is the set of non-placeholder speaker labels; each becomes a participant keyed by normalized display name | No error expected |
| Drop carries participant graph | `metadata.participants` with 15-field entries | roster is the graph; graph-only people are still recorded as meeting participants with `spoke_turns`/`spoke_words`/`found_in` preserved | Entry without `displayName` → `StageError` naming the index |
| Bare first name in roster | label `Avery`, roster has exactly one `Reed, Avery` | resolved to that participant | — |
| Bare first name, two matches | label `Jordan`, roster has two people named Jordan | recorded `ambiguous`, no participant link | — |
| Unknown label | label matches nobody | recorded `unresolved`, no participant link, never merged | — |
| Placeholder label | `Speaker 8` | recorded `placeholder`, never becomes a participant | — |
| External attendee | graph entry `unresolved: true` | participant created with `external = true`, kept | — |
| Alias table hit | `participant_alias` maps a key to a surviving participant | worker resolves through it before insert; the merge survives the rerun | — |
| STT engine unavailable | `mlx_whisper` not importable | `StageError` naming the engine and how to install it | Stage + job recorded `failed` |
| `diarizer.engine: pyannote` | configured but not bundled | `StageError` saying pyannote is documented, not bundled | Stage + job recorded `failed` |
| Rerun of `align` | rows already present | meeting-scoped rows replaced, cross-meeting `participant` rows upserted and never deleted | No error expected |

</intent-contract>

## Code Map

- `server/meetingminer/pipeline/stages/__init__.py` — `STAGE_IMPLEMENTATIONS` (`:25`) is the registry;
  an unregistered name is the pause signal. Add `transcribe` and `align` (one line each); the runner
  needs no other change for stage arrival. Update the module docstring's "pauses at `transcribe`".
- `server/meetingminer/domain/jobs.py` — `STAGE_NAMES` (`:11`) and `VIDEO_ONLY_STAGES` (`:25`), which
  already contains `transcribe`. Do **not** add `align` to it: a transcript-only drop must run `align`.
- `server/meetingminer/pipeline/runner.py` — `_clear_replaced_video_evidence()` (`:141`) deletes
  screenshots/frames/media and the `screenshots`/`frames` subtrees; it must also clear the extracted
  audio subtree and the STT-lane rows a now-transcript-only meeting must not keep.
  `_VIDEO_OUTPUT_SUBDIRS` (`:138`) gains `"audio"`. `run_job()` (`:227`) needs no change.
- `server/meetingminer/pipeline/stage.py` — `StageContext` (`:31`) with `meeting_dir()` (`:49`),
  `relative_path()` (`:58`) and the `after_commit`/`after_rollback` hooks (`:46`); `StageError` (`:21`).
- `server/meetingminer/pipeline/outputs.py` — `OutputDirSwap(ctx, subdir)`: the symlink/escape guard,
  orphan-backup recovery, staging directory and atomic `os.replace` that `frames`/`screens` use. Reuse
  it verbatim for the `audio/` subtree; `remove_meeting_subdir` is what the runner calls.
- `server/meetingminer/pipeline/stages/ocr.py` — the exact stage shape to imitate: build the port once,
  delete-then-insert this meeting's rows (including on the empty path), `_strip_nuls` (`:47`) because
  Postgres rejects a literal NUL in `text` *and* `jsonb`, and the periodic progress event (`:130`).
- `server/meetingminer/adapters/ocr/__init__.py` — `build_ocr` (`:53`) and the structural `OcrBinding`
  Protocol (`:41`): the factory pattern to mirror for `build_stt` / `build_diarizer`. The adapter
  package imports no project module other than its own port.
- `server/meetingminer/adapters/ocr/port.py` — `Ocr` Protocol (`:87`) with `name` and the **static**
  `unavailable_reason()` the factory probes before constructing; `OcrError` (`:21`).
- `server/meetingminer/adapters/ocr/apple_vision.py` — the lazy-import pattern: the provider is
  imported inside the method so a host without it reports unavailability instead of failing at import.
- `server/meetingminer/pipeline/media.py` — `MediaToolError` (`:34`), `_run()` (`:60`) subprocess
  contract, `FFMPEG` (`:23`). Audio extraction is a plain ffmpeg call and belongs here, not in an
  adapter (AD-8 covers model calls only).
- `server/meetingminer/pipeline/screens.py` — the precedent for a pure, DB-free stage core
  (`normalize_text`, `tokens`, `jaccard`). `normalize_text` is reused by the aligner's token scorer;
  the new transcript/speaker cores follow the same "unit-testable without Postgres" shape.
- `server/meetingminer/config.py` — `SttConfig` (`:116`) and `DiarizerConfig` (`:120`) exist with an
  `engine` field only; `PipelineConfig` (`:220`) holds `frames`/`screens`; `_StrictModel` is
  `extra="forbid"` (`:92`); `OcrConfig` (`:102`) is the binding shape to mirror.
- `config.yaml` — `stt:` (`:14`), `diarizer:` (`:17`), `pipeline:` (`:50`). Every threshold this story
  introduces belongs here.
- `server/meetingminer/migrations/0003_screens_screenshots.sql` — the migration house style: `uuidv7()`
  PKs, `set_updated_at` triggers on every table, CHECK constraints for enums, meeting-scoped indexes.
  Next file is `0004_`. `server/meetingminer/db.py` `MIGRATIONS_DIR` (`:27`) applies in filename order.
- `server/meetingminer/migrations/0002_meetings_media_frames.sql` — `meeting` (`:26`), `set_updated_at()`
  (`:7`), `frame` (`:76`) for FK targets and style.
- `server/meetingminer/domain/drops.py` — `DropContents` (`:48`) with `transcript_vtt_path`,
  `transcript_text_path`, `transcript_paths` (`:67`), `has_recording` (`:58`), `metadata` (the
  `participants` array lives here). Read-only from stages.
- `docs/source-drop.schema.json` — `participants` (`:36`, `aadObjectId` at `:46`) is optional with `displayName` required and
  `additionalProperties: true`, so a 15-field org-chart entry validates as-is. Its `aadObjectId`
  description still calls that "the primary deduplication key" — stale against the amended SPEC;
  correct the **description text only** (no structural change, so `pull_transcript`'s schema tests
  keep passing).
- `server/tests/conftest.py` — `EVIDENCE_TABLES` (`:146`) must name every new table or isolation leaks;
  `make_drop` (`:162`), `valid_metadata()` (`:70`), `content_root` (`:209`), `synthetic_recording`
  (`:217`), `requires_ffmpeg` (`:195`), `requires_ocr` (`:255`) is the skip-marker pattern to copy.
- `server/tests/test_worker_runner.py` — `enqueue()` (`:52`), `stage_statuses()` (`:74`),
  `make_recording_drop` (`:39`). The assertion that a recording job pauses at `transcribe` **must
  move** to `moments`, and the transcript-only pause moves from `align` to `moments`.
- `server/pyproject.toml` — `requires-python` (`:5`) and the `sys_platform == 'darwin'` marker
  precedent (`:23`). `server/uv.lock` is committed and must be refreshed.
- `infra/Makefile` — `check-tools` (`:95`) already requires ffmpeg/ffprobe (the STT lane needs them);
  `bootstrap` (`:124`) runs `uv sync --project server`, the single install path.
- **Read-only authority:** `_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md`
  — AD-5 (`:194`, table ownership + participant dedup + alias rows), AD-8 (`:212`, ports),
  AD-10 (`:224`), AD-11 (`:230`, cross-meeting entities), AD-13 (`:242`, merge-never-erase +
  multi-form precedence), stage list (`:126`), ERD `PARTICIPANT ||--o{ TRANSCRIPT_SEGMENT` (`:365`).
- **Read-only corpus evidence** (verified on disk this run, do not re-derive):
  - Drops root `/Users/devopsterus/current/meetingminer-drops` holds 28 finalized drops; 8 carry
    `recording.mp4`, all 28 carry `transcript.txt`, 20 also carry `transcript.vtt`.
  - **No drop carries a `participants` key** — `pull_transcript/emit-drop.js:288` deliberately omits it,
    and no `org chart.json` exists anywhere on this machine. See Design Notes.
  - Every drop `.vtt` is a speaker-less subtitle track (GUID cue ids, bare text, no `<v Name>`).
  - Teams lineage sample: `[0:16] Coleman, Reese: Good morning.` — one line per turn; labels include
    `Last, First`, bare first names (`Robin`), and login-shaped tokens (`venkatmylavarapu`).
  - Legacy lineage sample: `Speaker 2 | 00:00` on one line, the utterance on the line(s) after.
- `pull_transcript/` — READ-ONLY. Never written by this story.

## Tasks & Acceptance

**Execution:**
- `server/pyproject.toml` — pin `requires-python = ">=3.12,<3.13"` and add `mlx-whisper` +
  `parakeet-mlx` under `sys_platform == 'darwin'`; add `server/.python-version` holding `3.12`. The ASR
  wheels have no build for the machine-default 3.14, so the interpreter is part of the contract.
  Refresh `server/uv.lock`.
- `server/meetingminer/adapters/stt/port.py` — `SttError`, `SttSegment` (`start_ms`, `end_ms`, `text`),
  `SttResult` (segments, `text`, `engine`, `model`, `language`), and the `Stt` protocol
  (`name`, static `unavailable_reason()`, `transcribe(path) -> SttResult`). No provider import here.
- `server/meetingminer/adapters/stt/mlx_whisper.py` — lazy `import mlx_whisper`;
  `transcribe(audio, path_or_hf_repo=model)` returns `dict(text, segments[{start,end,text}], language)`
  with float seconds; convert to integer ms. Missing package → `SttError` naming `uv sync`.
- `server/meetingminer/adapters/stt/parakeet_mlx.py` — lazy `from parakeet_mlx import from_pretrained`;
  `from_pretrained(model).transcribe(path)` returns `AlignedResult` with `.text` and `.sentences[]`
  carrying float `.start`/`.end`/`.text`. Same error contract.
- `server/meetingminer/adapters/stt/__init__.py` — `build_stt(stt_config, log=None)` factory over an
  `ENGINES` map; the only place either engine is named. No fallback key: AC 1 asks for *swappable*,
  not *fallback*.
- `server/meetingminer/adapters/diarize/port.py` — `DiarizerError`, `DiarizationTurn`
  (`start_ms`, `end_ms`, `speaker`), `Diarizer` protocol (`name`, `diarize(path) -> tuple[...]`).
- `server/meetingminer/adapters/diarize/noop.py` — returns an empty tuple; its docstring states that
  segments then carry the `Unknown` placeholder (AD-13).
- `server/meetingminer/adapters/diarize/__init__.py` — `build_diarizer(diarizer_config)`: `noop`
  constructs; `pyannote` raises `DiarizerError` saying it is documented but not bundled and what
  installing it would take. No stub engine module that can never run.
- `server/meetingminer/config.py` — extend `SttConfig` with `model: NonEmptyText`; add
  `AlignConfig` (`anchor_window_seconds`, `min_match_score`, `max_segment_ms`) with bounded `Field`
  constraints and hang it off `PipelineConfig`.
- `config.yaml` — add `stt.model`, and the `pipeline.align:` block with the documented defaults
  (`anchor_window_seconds: 2.0`, `min_match_score: 0.35`), each with the comment saying what moving it
  changes.
- `server/meetingminer/migrations/0004_transcripts_participants.sql` — five tables:
  `transcript_source` (meeting FK, `kind` CHECK `provided-text|provided-vtt|stt`, `format` CHECK
  `teams|legacy|vtt|stt`, `drop_relative_path`, `content_path`, `sha256`, `byte_size`,
  `segment_count`, `engine`, `model`, `language`, UNIQUE (meeting_id, kind));
  `transcript_segment` (uuidv7 pk, meeting FK, `ordinal`, `start_ms`, `end_ms`, `text`,
  `speaker_label`, `participant_id` FK NULL, `speaker_resolution` CHECK
  `resolved|unresolved|ambiguous|placeholder`, `label_source_id` FK, `timing_source_id` FK,
  `stt_source_id` FK NULL, `stt_start_ms`, `alignment_delta_ms`, `match_score`,
  UNIQUE (meeting_id, ordinal));
  `participant` (uuidv7 pk, `identity_key` UNIQUE, `display_name`, `normalized_name`);
  `meeting_participant` (meeting FK + participant FK composite pk, `mail`, `title`, `department`,
  `dept_code`, `line_of_business`, `office`, `org`, `is_guest`, `is_external`, `spoke_turns`,
  `spoke_words`, `found_in` text[], `derived_from` CHECK `drop-graph|transcript|both`, `source` jsonb);
  `participant_alias` (`alias_key` pk, participant FK) — API-owned, created here, read by the worker.
  Plus `set_updated_at` triggers on all five and meeting-scoped indexes.
- `server/meetingminer/pipeline/transcripts.py` — the pure, DB-free parsing core:
  `parse_timestamp()` (by field count), `parse_teams_text()`, `parse_legacy_text()`, `parse_vtt()`,
  `detect_text_format()`, and a `ParsedTranscript` carrying segments + the detected format. No
  Postgres, no filesystem beyond a passed-in string.
- `server/meetingminer/pipeline/speakers.py` — the pure identity core: `normalize_display_name()`
  (case-fold, strip parenthetical qualifiers, reorder `Last, First`, collapse whitespace),
  `is_placeholder_label()`, `identity_key_for()`, and `resolve_label(label, roster)` returning
  resolved / ambiguous / unresolved / placeholder with the candidate set. Bare first names and
  initials resolve **only** against the passed roster.
- `server/meetingminer/pipeline/alignment.py` — the pure aligner: given provided segments and STT
  segments plus an `AlignConfig`, return per-provided-segment matches (`stt_index`, `delta_ms`,
  `match_score`) using token-overlap scoring constrained to the anchor window, and the VTT end-timing
  merge. Deterministic; no model call.
- `server/meetingminer/pipeline/stages/transcribe.py` — extract 16 kHz mono WAV from the recording
  into a swapped `audio/` subtree, build the `Stt` port, transcribe, run the `Diarizer`, replace this
  meeting's `kind='stt'` `transcript_source` row and its STT segments, log one summary event.
- `server/meetingminer/pipeline/stages/align.py` — read the drop's transcripts, record each as a
  `transcript_source` with its sha256, parse both lineages, reconcile against the STT lane, write the
  derived `transcript_segment` rows, then derive participants (roster from `metadata.participants`
  when present, else from non-placeholder speaker labels), resolving identity through
  `participant_alias` before every upsert. Replace meeting-scoped rows; never delete `participant`.
- `server/meetingminer/pipeline/media.py` — add `extract_audio(source, destination)`: one ffmpeg call
  producing 16 kHz mono PCM WAV, reading the drop read-only, raising `MediaToolError` on failure.
- `server/meetingminer/pipeline/stages/__init__.py` — register `transcribe` and `align`; update the
  docstring's pause point.
- `server/meetingminer/pipeline/runner.py` — add `"audio"` to `_VIDEO_OUTPUT_SUBDIRS` and delete this
  meeting's `kind='stt'` `transcript_source` row in `_clear_replaced_video_evidence()`.
- `docs/source-drop.schema.json` — correct the `aadObjectId` description only: it is legacy source-side
  surface that the pipeline ignores, not a deduplication key. No structural change.
- `server/tests/conftest.py` — add the five new tables to `EVIDENCE_TABLES`; add a deterministic fake
  `Stt` fixture and a `requires_stt` skip marker mirroring `requires_ocr`.
- `server/tests/test_transcripts_core.py` — unit-cover the I/O matrix's parsing rows: both lineages,
  the `started transcription` preamble, `MM:SS`↔`HH:MM:SS` switching mid-file, multi-line legacy
  blocks, a label containing a comma, a speaker-less VTT, an empty file, and a malformed stamp.
- `server/tests/test_speakers_core.py` — unit-cover resolution: `Last, First` ↔ `First Last`,
  parenthetical qualifiers, bare first name with one and with two roster matches, initials,
  `Speaker N` placeholders, and that unresolved/ambiguous never yield a participant id.
- `server/tests/test_alignment_core.py` — unit-cover the aligner: a match inside the anchor window, one
  outside it, a below-`min_match_score` pair left unmatched, VTT end-timing merge, and STT-only and
  provided-only inputs.
- `server/tests/test_stt_adapter.py` — `build_stt` returns the configured engine and names the missing
  package when it cannot run; `build_diarizer` returns noop and refuses pyannote with the documented
  message.
- `server/tests/test_worker_runner.py` — move the pause assertions to `moments`; add DB-backed rows:
  Teams drop end to end, legacy drop end to end, recording-without-transcript yielding `Unknown`
  placeholders, transcript-only drop with `stt_source_id` NULL, `align` rerun replacing without
  duplicating, a participant surviving a rerun, an alias row redirecting an insert, an external
  participant preserved, and an STT failure recorded on stage + job.

**Acceptance Criteria:**
- Given the epics.md Story 1.5 acceptance criteria, when each is exercised against the running worker,
  then it passes as written.
- Given `config.yaml` with `stt.engine: parakeet-mlx`, when the worker runs the same drop, then the
  parakeet engine is used and no file outside `server/meetingminer/adapters/stt/` changed.
- Given two meetings whose transcripts name the same person, when both are ingested, then both
  reference one `participant` row, and re-running `align` on either leaves that row present.
- Given a real drop from `/Users/devopsterus/current/meetingminer-drops` carrying a Teams
  `transcript.txt`, when it is ingested, then every derived segment's `speaker_resolution` is one of
  the four documented values and no segment with `unresolved` or `ambiguous` carries a
  `participant_id`.
- Given `uv run --project server pytest server/tests`, when run with the compose Postgres up, then the
  whole suite passes with no new skips beyond the documented ffmpeg/Postgres/OCR/STT ones.

### Review Findings — 2026-08-18

- [x] [Review][Patch] Reject invalid STT provider timestamps instead of converting them to `0 ms` [server/meetingminer/adapters/stt/port.py:88]
- [x] [Review][Patch] Validate minute and second ranges in parsed transcript timestamps [server/meetingminer/pipeline/transcripts.py:107]
- [x] [Review][Patch] Fail a text transcript that contains a malformed timestamp header rather than treating it as utterance text [server/meetingminer/pipeline/transcripts.py:48]
- [x] [Review][Patch] Do not attribute or discard nonblank text that occurs before the first transcript turn [server/meetingminer/pipeline/transcripts.py:190]
- [x] [Review][Patch] Mark retained video-only checkpoints skipped when retry cleanup converts a job to transcript-only [server/meetingminer/pipeline/runner.py:274]
- [x] [Review][Patch] Sanitize diarizer speaker labels before serializing the STT source JSON [server/meetingminer/pipeline/stages/transcribe.py:94]
- [x] [Review][Patch] Align the source-drop schema’s participant identity documentation with the mail-first implementation [docs/source-drop.schema.json:46]

## Spec Change Log

Deviations from the spec as written, each with the reason. Nothing was dropped.

- **The migration is `0005_transcripts_participants.sql`, not `0004_`.** Story 1.11 landed
  `0004_capture_retune.sql` in the same working tree while this story was being built.
  `db.py` applies files in filename order, so two `0004_` files would leave application order
  decided by the rest of the name. Renumbering keeps the order explicit.
- **`transcript_source` carries one column the spec's list does not name: `segments jsonb`.**
  The spec has `transcribe` write "its STT segments" and `align` replace the meeting's
  `transcript_segment` rows. Storing the raw STT segments *as* derived rows makes `align`
  destroy its own verification anchor: the second run of `align` would find no STT lane and
  produce rows with every anchor column NULL, so the stage would not be idempotent (AD-11).
  The provided transcript can be re-parsed from the read-only drop every run; the STT lane
  cannot be re-derived cheaply, so it is persisted on its own raw source row. `transcript_segment`
  then holds only `align`'s derived output, which is also what keeps AD-13's "no two raw sources
  merged into one raw source" literally true of the schema.
- **Provided and STT `transcript_source` rows are upserted on `(meeting_id, kind)` rather than
  deleted and re-inserted.** A delete would cascade to the derived rows that name the source as
  provenance. Upserting keeps the row id stable across reruns.
- **`_clear_replaced_video_evidence()` also re-queues the `align` stage.** Deleting the
  `kind='stt'` source cascades to the derived rows anchored to it, so leaving an `align`
  checkpoint reading `done` would sit over a meeting whose transcript rows had just been removed.
  The function therefore takes `job_id` as well.
- **Story 1.5's DB-backed matrix lives in `server/tests/test_worker_transcripts.py`, not inside
  `test_worker_runner.py`.** Only the three pause assertions moved in the runner file, which
  story 1.11 was editing concurrently. `test_worker_transcripts.py` imports the runner file's
  helpers, so there is still one definition of `enqueue`, `stage_statuses`, and friends.
- **`tests/conftest.py` gained an autouse `_no_real_stt` fixture** binding `transcribe` to a
  silent fake engine unless a test installs its own. Unlike the OCR engines, a real `Stt` binding
  downloads a multi-gigabyte model, so a test that merely walks past `transcribe` would turn the
  suite into a download. `make_drop` also writes a parseable Teams transcript now that `align`
  actually parses what the factory produces.
- **`normalize_display_name` falls back to a label's parenthetical content when stripping
  qualifiers would empty it.** The real corpus carries a speaker labelled `(Foster, Logan)`;
  stripping the wrapper to nothing lost a person. Verified against all 28 drops: 7980 resolved,
  3 placeholder (`Unknown`), 0 unresolved, 0 ambiguous.
- **Story 1.6's open question did not block anything.** No task here needed the transcript-only
  replay-affordance decision; `moments` owns it. Recorded, not deferred.
- **`participant.identity_key` is the graph's `mail` when it has one, not the normalized display
  name.** The spec, this migration's comment, and `speakers.identity_key_for` all justified a
  name-only key by asserting that no source in this corpus supplies a directory identifier. That
  premise is false. Measured against the live corpus, `mail` is present on 222 of 225 person-rows
  (`cameron.blake@corp.com`), resolved from the SharePoint user-profile service over the puller's
  existing cookie session — no Microsoft Graph call, so the SPEC non-goal is untouched. The
  employee-number login (`10001@corp.com`) is a different field, and *that* is what would miss if
  joined. Both comments were rewritten rather than left to be defended by the next reader.
  The key is namespaced — `mail:...` / `name:...` — because it is a UNIQUE column the API writes
  alias rows against (AD-5), so which space a key belongs to is stated rather than inferred from
  punctuation. Nothing was broken at the time of the change: across all 225 rows, zero people
  appear under two names and zero names map to two mails. The change is about the failure that is
  *silent* — one same-named hire merges two humans onto one participant row, which is exactly the
  wrong attribution never-guess exists to prevent, and unlike a split it leaves no record. It was
  also the cheap moment: the migration was unapplied and uncommitted, no participant rows existed,
  and `mail` was already captured on `meeting_participant`.
- **`RosterEntry` now carries two keys, and `LabelResolution.identity_key` became `match_key`.**
  A transcript label never carries a mail address, so labels resolve against normalized display
  names while people are upserted by mail. Conflating the two is what made the collapse possible.
- **Two roster entries sharing a name now force `ambiguous`.** `resolve_label` compares against a
  *set* of keys, so two namesakes looked like one candidate to it and resolved — attributing every
  turn to whichever the roster listed first. The multiplicity is only knowable in `align`, so
  `_disambiguate` applies it there.

## Review Triage Log

### 2026-08-18 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 18: (high 1, medium 7, low 10)
- defer: 8: (high 0, medium 4, low 4)
- reject: 5: (high 0, medium 0, low 5)
- addressed_findings:
  - `[high]` `[patch]` `SPEAKER_00` — the exact tag `diarize/port.py` documents pyannote emits — was
    not a placeholder, because `_` is a word character and the pattern only allowed a space. Any
    non-noop diarizer would have minted a `participant` row for it and written every such turn
    `speaker_resolution = 'resolved'`: a diarizer tag becoming a person, which is the wrong
    attribution never-guess exists to prevent. Pattern widened to the `_`/`-` separators and to
    `spk`/`guest`/`attendee`/`participant`; real bare first names still pass through.
  - `[medium]` `[patch]` Two empty-text segments anchored to each other at `match_score = 1.0` —
    `jaccard` returns 1.0 for two empty sets, correct where it came from (textless frames are not a
    screen boundary) and wrong as a text-identity score. It fabricated a perfect anchor and a delta.
    Guarded in both `align_segments` and `merge_vtt_end_timings`.
  - `[medium]` `[patch]` A NUL in a speaker label failed the entire `align` stage on the participant
    insert, costing the meeting every transcript row — the exact failure `strip_nuls` exists to
    prevent, unguarded on the path that builds `identity_key`/`normalized_name`. Found by a test
    added in this pass, then fixed in `normalize_display_name` and both roster builders.
  - `[medium]` `[patch]` `_load_stt_source` turned a missing or unparseable `start_ms` into offset
    zero via `or 0` — a fabricated timestamp. Now a named `StageError`.
  - `[medium]` `[patch]` The participant graph was stored whole as jsonb without NUL stripping, so
    one bad byte anywhere in the drop's graph failed the stage. Added `_strip_nuls_deep`.
  - `[medium]` `[patch]` A VTT-only drop — a first-class shape `read_drop` accepts and the puller
    emits often — had no end-to-end coverage at all; the label-source branch it depends on was never
    taken, so deleting it would have failed every such meeting with a green suite. Test added.
  - `[medium]` `[patch]` Neither STT adapter's seconds-to-milliseconds mapping was ever executed:
    every worker test goes through a fake that already speaks milliseconds. Dropping the `* 1000`
    would have put every real segment at a thousandth of its offset with the suite green. Stubbed
    provider-payload tests added for both engines, covering the blank-text skip, the backwards-end
    clamp, and the negative-start clamp.
  - `[medium]` `[patch]` `transcribe`'s "upsert, never delete-then-insert" contract was asserted only
    in prose — no test re-ran it with an audio stream present, so the `ON CONFLICT` arm never
    executed. A delete would cascade away every anchored derived row while `align` still read `done`.
    Test added.
  - `[low]` `[patch]` Neither lane was sorted, but both cursors are forward-only, so an out-of-order
    start would silently skip real candidates. Both lanes are now ordered rather than assumed to be.
  - `[low]` `[patch]` An explicit `participants: []` was treated as "no graph" and fell back to
    transcript labels, inventing a roster the drop had declined to assert.
  - `[low]` `[patch]` The silent-recording path deleted the STT row but left the published `audio/`
    subtree, stranding a WAV no row named.
  - `[low]` `[patch]` `extract_audio`'s 16 kHz mono PCM contract — the thing that makes the two
    engines interchangeable — was only ever asserted as "the file exists". Format test added.
  - `[low]` `[patch]` The stale-provided-source deletion ran on every call but its effect was never
    observed; a removed VTT would have left a source row describing a file that is not there.
  - `[low]` `[patch]` `min_match_score` is allowed to be `0.0`, at which every in-window candidate
    anchored at zero overlap. Guarded with an explicit `score > 0`.
  - `[low]` `[patch]` The migration's `participant` comment still argued the two key spaces "need no
    prefix" after the key was namespaced — stale within this same run, and exactly the kind of
    comment the next reader defends.
  - `[low]` `[patch]` `_graph_roster`'s merge comment said "keep the first" while the merge let the
    second entry win field by field. Comment corrected to the actual behavior.
  - `[low]` `[patch]` The participant `executemany` cursor was never closed.
  - `[low]` `[patch]` A Design Note in this spec claimed no `org chart.json` existed anywhere on the
    machine, justifying leaving the graph path synthetic. All 28 exist on the `/Volumes/nvmepool`
    mount that the original search never reached. Corrected in place, with the correction marked
    rather than the false text silently deleted.

## Design Notes

- **Why the participant graph is specified but not yet reachable from a drop.** All 28 `org chart.json`
  files described by `corpus-facts.md` §4 exist, under
  `/Volumes/nvmepool/mm_current/pull_transcript/<Title>/<M.D.YY>/`, and carry all 16 documented fields
  on every one of 225 person-rows. What is missing is the *bridge*: `pull_transcript/emit-drop.js:288`
  deliberately omits a `participants` key, so none of the 28 finalized drops carries one, and the
  pipeline's only participant surface is `metadata.participants` (AD-1 — participant resolution is the
  source side's job). Mapping `org chart.json` into that key is `emit-drop` work and out of scope here.
  Note the field rename it will need: the chart writes `name`, the drop schema requires `displayName`.
  Both code paths are built and tested; the graph path was additionally exercised once against real
  data by hand (see the first `deferred` item), but no automated test reads a real chart.
  **Correction:** an earlier revision of this note claimed no such file existed anywhere on this
  machine. That was wrong — it recorded a search that never reached the `/Volumes/nvmepool` mount —
  and it is corrected here rather than deleted, because the false version was the stated justification
  for leaving the graph path synthetic.
- **Two different meanings of "unresolved", kept apart.** The participant graph's `unresolved: true`
  marks an *external* attendee not in the tenant directory; the never-guess constraint uses
  "unresolved" for a *speaker label that matched nobody*. They are stored in different columns —
  `meeting_participant.is_external` and `transcript_segment.speaker_resolution` — and must never be
  collapsed. An external attendee is a real, kept person; an unresolved label is an absent attribution.
- **Identity key: mail first, name as the documented fallback.** `identity_key` is
  `mail:<address>` when the participant graph supplies one — 222 of 225 corpus person-rows do —
  and `name:<normalized display name>` otherwise, which in practice means the external attendees,
  who carry `unresolved: true` and an empty mail. Mail is a real directory identifier that costs
  no Microsoft Graph call: it comes from the SharePoint user-profile service, so AD-5's "AAD
  object ID when present" clause stays vacuous while the *purpose* behind it is served. The
  worker resolves `identity_key` through `participant_alias` before every upsert, so an Epic-2
  human merge survives re-ingest and stage reruns.
- **Two "unresolved"s and two key spaces, all kept apart.** The graph's `unresolved: true` marks
  an *external attendee* (`meeting_participant.is_external`) and is preserved; a speaker label
  matching nobody is an *absent attribution* (`transcript_segment.speaker_resolution`). Do not
  key the external check on `guest`: it is `false` on all 225 corpus rows, so code reading it
  finds nobody. `is_guest` is recorded anyway, as a faithful but currently empty graph field.
- **Why bare first names resolve only inside a meeting's roster.** The legacy lineage mixes
  `Reed, Avery` with bare `Avery` inside one file. Corpus-wide, `Avery` is ambiguous; inside one
  meeting's roster it usually is not. Scoping the lookup is what makes resolution safe *and* keeps the
  never-guess rule honest — two roster matches stay `ambiguous` rather than picking the first.
- **Timing precedence (AD-13), concretely.** Speaker labels and text come from `transcript.txt`. The
  `.txt` gives only a start per turn, so a segment's end defaults to the next turn's start (capped at
  `max_segment_ms`); where a VTT cue's text matches, its real end replaces that. The STT lane supplies
  the verification anchor: `alignment_delta_ms` is the signed offset between the provided start and the
  matched STT start, and a delta outside ±2 s or a score below `min_match_score` leaves the row
  unmatched rather than snapping it. No file is ever picked wholesale.
- **Why audio is extracted rather than handed the mp4.** `mlx_whisper` shells to ffmpeg itself, but
  `parakeet_mlx` loads audio through its own path; extracting one 16 kHz mono WAV under
  `meetings/<id>/audio/` makes both engines take identical input, keeps the drop untouched, and gives a
  rerun something to reuse. It rides the existing `OutputDirSwap`, so the runner clears it with the
  other video-derived subtrees.
- **Why Python is pinned to 3.12.** The ASR wheels have no 3.14 build and this machine's default uv
  interpreter is 3.14.7. `server/.python-version` plus a `<3.13` bound makes `uv sync` reproducible;
  AD-9 fixes the runtime to one Mac, so a narrow bound costs nothing.

```text
MM_CONTENT_ROOT/meetings/<meeting_id>/
  frames/frame-000123.jpg          # frames stage (1.3)
  screenshots/screenshot-0001.jpg  # screens stage (1.4)
  audio/audio.wav                  # transcribe stage (1.5), 16 kHz mono
```

## Verification

**Commands:**
- `uv run --project server pytest server/tests` — expected: all pass (start Postgres with
  `make infra-up` first; ffmpeg/OCR/STT-dependent tests skip only with their named reason).
- `make migrate && make migrate` — expected: applies `0004_...` once; the second run reports nothing
  to apply.
- `make test` — expected: server suite passes, puller suite unchanged, and the web build succeeds
  (no API surface change, so the committed TS client stays valid).
- `uv run --project server python -c "import sys; print(sys.version)"` — expected: 3.12.x.
- `make up`, POST a Teams drop from `/Users/devopsterus/current/meetingminer-drops` to `/ingests`, then
  `GET /jobs/{id}` — expected: `probe`…`align` `done`, `moments` `queued`; `transcript_segment` rows
  exist with populated `speaker_label` and a `speaker_resolution` in the four documented values; the
  drop directory's file list, sizes, and mtimes are unchanged.
- `uv run --project server python -c "from meetingminer.config import load_config; from meetingminer.adapters.stt import build_stt; print(build_stt(load_config().settings.stt))"`
  — expected: prints the mlx-whisper engine, or names precisely why it cannot run.

## Auto Run Result

Status: done

**Implemented change.** The `Stt` and `Diarizer` ports (AD-8) plus the `transcribe` and `align`
pipeline stages. `transcribe` extracts one 16 kHz mono WAV from the recording, runs whatever engine
`config.yaml` binds, and records its output as its own raw `transcript_source`. `align` parses the
provided transcript in both corpus lineages, reconciles it against that lane by token overlap inside
a ±2 s anchor window, and writes new derived `transcript_segment` rows naming every input — then
derives participants from speaker attribution joined to the drop's participant graph, resolving
identity through the API-owned alias table. A job now advances to `moments` instead of pausing at
`transcribe`, and a transcript-only drop runs `align` rather than stopping before it.

**Files changed.**
- `server/meetingminer/adapters/stt/{port,mlx_whisper,parakeet_mlx,__init__}.py` — the `Stt` port,
  both engines (lazily imported), and the `build_stt` factory with no silent fallback.
- `server/meetingminer/adapters/diarize/{port,noop,__init__}.py` — the `Diarizer` port, the noop
  default, and a factory that refuses `pyannote` with the documented "not bundled" message.
- `server/meetingminer/pipeline/transcripts.py` — timestamps by field count, Teams + legacy + VTT
  parsers, `strip_nuls`.
- `server/meetingminer/pipeline/speakers.py` — normalization, placeholder detection, roster-scoped
  resolution, and the namespaced `mail:`/`name:` identity key.
- `server/meetingminer/pipeline/alignment.py` — anchor-window token-overlap matching, VTT end merge,
  end-time resolution.
- `server/meetingminer/pipeline/stages/{transcribe,align}.py` — the two stages.
- `server/meetingminer/migrations/0005_transcripts_participants.sql` — `transcript_source`,
  `transcript_segment`, `participant`, `meeting_participant`, `participant_alias`.
- `server/meetingminer/pipeline/media.py` — `extract_audio`.
- `server/meetingminer/pipeline/runner.py` — `audio` subtree cleanup and the STT-lane clear.
- `server/meetingminer/pipeline/stages/__init__.py` — both stages registered.
- `server/meetingminer/config.py`, `config.yaml` — `SttConfig.model`, `AlignConfig`, and their
  documented defaults.
- `server/pyproject.toml`, `server/.python-version`, `server/uv.lock` — Python pinned to 3.12 and the
  MLX wheels added.
- `docs/source-drop.schema.json` — `aadObjectId` description corrected (text only).
- `server/tests/` — five new modules plus additions to `conftest.py`, `test_pipeline_media.py`, and
  the runner file's pause assertions.

**Review findings.** 18 patched (high 1, medium 7, low 10), 10 deferred, 5 rejected. 0 intent gaps,
0 spec defects. The high-severity patch was a diarizer tag (`SPEAKER_00`) that would have become a
resolved participant. Two of the patches were errors introduced by this run's own later amendment
(a migration comment that contradicted the namespaced key, and a Design Note asserting the corpus
did not exist); both were corrected rather than left standing.

**Follow-up review recommended: true.** Patched counts: high 1, medium 7, low 10. One high-severity
patch alone sets this true; the score is `3 x 7 + 1 x 10 = 31`, well over the threshold of 5.

**Verification performed.**
- `uv run --project server pytest server/tests` — **444 passed, 0 skipped, 2 failed**. Both failures
  (`test_parse_tsv_without_page_dimensions_is_a_named_error`,
  `test_empty_and_populated_stage_logs_carry_the_same_fields`) were reproduced against committed
  HEAD `a16c1987` in a clean detached worktree and are pre-existing, not this story's.
  Run in an isolated copy against a private test database: a parallel story-1.11 session shares the
  fixed-name `meetingminer_test` database, and interleaved runs produced between 2 and 62 spurious
  `AdminShutdown` failures. Only the isolated number is trustworthy.
- Fresh migration apply on an empty database: `0001`-`0005` applied once, second pass reports nothing
  to apply, all five story-1.5 tables present. `make migrate` twice: idempotent.
- `uv run --project server python -c "import sys; print(sys.version)"` — 3.12.14.
- Port bindings resolve: `build_stt` returns the mlx-whisper engine, `build_diarizer` the noop.
- **Real corpus, end to end through the actual worker.** The drop
  `2026-04-28-supplier-hub-design-icontract-review` twice: as it exists (9 name-keyed participants,
  55 segments, all resolved) and with the live `org chart.json` mapped into `metadata.participants`
  (10 participants — 9 mail-keyed, 1 name-keyed external — 55 segments, all resolved, 1 external
  preserved). Zero non-resolved rows carried a `participant_id` in either run. Re-run after every
  review patch with identical results.
- Corpus-wide parse check: all 28 real transcripts parse; the 28 real `org chart.json` files carry
  all 16 documented fields on 225/225 person-rows, 222 with `mail`, 3 external, 0 `guest`.

**Residual risks.**
- The participant-graph join is exercised against real data only by the by-hand run recorded above;
  no automated test reads a real chart. Deferred.
- No drop carries a `participants` key yet, so the mail-keyed path is dormant in production. When the
  puller bridges it, the same person will key differently before and after — 18 participant rows for
  10 people in the measured pair. Deferred, and it bears on story 1.12's identity-stability
  requirement.
- The graph is read as the roster authority rather than unioned with transcript labels. Defensible
  and argued in corpus-facts, but it is a reading, and it becomes observable when the bridge lands.
- Two pre-existing suite failures make `make test` red independently of this story.
