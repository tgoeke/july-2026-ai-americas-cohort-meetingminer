# Epic 7 Context: Know Who Spoke

<!-- Generated from planning artifacts. Regenerate with compile-epic-context if planning docs change. -->

## Goal

A user can see who spoke when in any recording and put names to the voices without the system ever guessing: a real diarizer segments turns into anonymous tags stored as worker-owned evidence, a human assigns names as api-owned alias rows, and the assignment re-attributes the transcript, graph, and extractions while every moment id and citation survives.

## Stories

- Story 7.1: Diarizer Engine Behind the Port
- Story 7.2: Speaker Tags on the Wire
- Story 7.3: Speaker Assignment
- Story 7.4: Speaker Naming UI

(Story 7.5 is a retired id, merged into 7.2 — resolved-label wire shape — and 7.4 — correcting a resolved label. Never reuse the id.)

## Requirements & Constraints

- The machine never resolves a speaker tag to a person. Diarization turns are stored as recording-local `SPEAKER_NN` tags on STT segments; only a human assignment or a source-supplied attribution names anyone. Suggestions in the UI are never auto-applied, and "unresolved" is a first-class, permanent choice (segments keep the tag with `speaker_resolution: placeholder`).
- A speaker assignment must re-attribute the transcript, graph, and extractions by re-arming the meeting's existing job for `align → moments → extract` only — no video-stage rerun. Every pre-existing moment id, citation, and approved/published artifact must still resolve after the rerun, pinned by a test; extraction replaces drafts only.
- Diarization performance is measured, not assumed: wall-clock time and turn quality for a 60-minute recording go in the story report. First engine is `pyannote.audio` in-process on the dev Mac; the NeMo endpoint on the LAN GPU host is the config-swappable alternative if that is too slow. Note the currently deployed LAN service (VM 120) exposes transcription only — no diarizer endpoint exists there yet.
- Sources that already carry speaker names (Teams speaker-attributed export, Zoom transcripts converted by story 6.3) must surface through the same wire shape as diarized tags — resolved labels with the same talk time and sample offsets — so named and unnamed sources look identical to the UI, and correcting a resolved label uses the same assignment path.
- Failures surface visibly; no silent fallback. An unavailable diarizer engine raises the named `DiarizerError`.

## Technical Decisions

- **Port and config:** the diarizer binds through the existing `Diarizer` port; `config.yaml` `diarizer.engine` names the engine, `build_diarizer` returns it, and `noop` remains the default. No provider SDK in feature code; swapping engines is a config edit.
- **Table ownership (evidence vs. curation):** the worker writes STT segments and their `SPEAKER_NN` tags exactly as `speaker_at` assigns today (evidence). The assignment is an api-owned `participant_alias` row in a `speaker:<meetingId>:<tag>` namespace. The worker resolves identity keys through the alias table before any insert, so assignments survive reruns and re-ingests. Neither process writes the other's tables.
- **Transcript immutability and citation identity:** provided transcripts are immutable inputs; `align` merges lanes and writes new derived rows, never erasing. Where a drop provided a transcript, its cue timing owns `transcript_segment.start_ms` (STT timing goes to separate nullable columns), which is what holds `transcript:<start_ms>` moment identity — and therefore every citation — fixed across the assignment rerun. Never write STT timing into `start_ms`.
- **API surface:** `GET /meetings/{id}/speakers` is read-only and registered through the route registry; each row carries tag, talk time, segment count, three sample offsets chosen from the tag's longest segments, and nullable `participantId`/`displayName` populated when the source or an alias resolves the label. `PUT /meetings/{id}/speakers/{tag}` accepts a participant id, a new display name, or `unresolved`; acceptance writes the alias row and re-arms the job.
- **Rerun visibility:** the re-armed stages report through the existing job/stage rows and `/jobs/events` stream; no new schema. The UI reads rerun state from stage bars like any ingest.

## UX & Interaction Patterns

- Speaker naming is its own screen at `/meetings/:meetingId/speakers`, reached from the meeting view's `Speakers` rail section and from Add-meeting's finished card (a `Name speakers` link appears once `transcribe` is done and the meeting had no speaker-attributed transcript). Composition reference: the story 6.1 design's `speaker-naming.html` mockup.
- Speaker rows sort by talk time descending; selecting a row drives three sample clips and the tag-filtered transcript. Clips play through the existing Range-correct media route; `ReplayPlayer` gains an optional `endMs`, clips set `startMs + 8000` so playback pauses after eight seconds, and existing callers omit it to keep open-ended playback. Keyboard `1` `2` `3` play clip n of the selected tag.
- The name field is an accessible combobox filtering `GET /participants` display names; Enter on a highlighted suggestion picks it (participant id), Enter otherwise saves the typed text as a new name; **Unresolved — keep the tag** is a button of equal weight. A resolved row shows the name and a `Correct` action instead of `Name`.
- Defined states: cold load (`Loading speakers…`), no diarization (message naming the noop config), saving, rerun in progress (stage bars for `align → moments → extract` live from `/jobs/events`), rerun failed (names stay saved; transcript still shows tags; stage error shown), rerun landed (message stating attribution changed and moment ids/citations unchanged).
- Layout must reflow to 320 CSS px (stacked speaker naming) and survive 200% text resize; web tests cover all three naming choices.

## Cross-Story Dependencies

- Sequence within the epic: 7.1 produces the tags, 7.2 puts them on the wire, 7.3 makes assignment mutate state, 7.4 is the UI over 7.2 + 7.3. 7.2 and 7.4 also carry the absorbed resolved-label behavior (retired 7.5).
- From other epics: the story 6.1 UX design spec governs the screen; story 6.3's dialect conversion supplies the speaker-attributed transcripts that arrive pre-resolved; the replay media route and `ReplayPlayer` (Epic 2) serve the sample clips; routes register through the auto-discovery registry (story 2.7/2.8 conventions).
