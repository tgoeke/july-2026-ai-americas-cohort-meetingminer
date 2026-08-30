# Epic 6 Context: Bring Any Meeting In

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Enable one first-class flow for adding published YouTube videos, Zoom exports, Teams exports, and loose recording or transcript files, then show each source becoming evidence with live progress. Every source must preserve the system's evidence guarantees: acquisition produces an immutable, schema-valid source drop, submits it through the sole intake endpoint, and leaves pipeline execution to the worker. The API may launch acquisition as a separate host process, but it must not download, convert, or ingest evidence in-process.

## Stories

- Story 6.1: UX Design Spec for the New Flows
- Story 6.2: YouTube Acquisition Command
- Story 6.2a: Playlist Acquisition
- Story 6.3: Local-Files Acquisition with Transcript Dialect Conversion
- Story 6.4: Acquisition Launch Surface
- Story 6.4a: Upload Sessions
- Story 6.5: Add-Meeting UI
- Story 6.5a: Add-Meeting File Tabs
- Story 6.6: YouTube Deep Links
- Story 6.7: Extraction Prompt Wording Generalized

## Requirements & Constraints

- YouTube acquisition downloads a browser-playable MP4 and English captions, preferring manual captions and falling back to auto-generated captions. It preserves stable source identity, source time, watch URL, channel, duration, tool version, selected format, and file checksums in the finalized drop. Reacquiring the same video reports `exists` without downloading media.
- Invalid or unavailable sources, missing tools or streams, and configured size or duration limits must fail before writing. Failures are named and include useful remediation; there are no silent fallbacks.
- Local acquisition accepts recording-only, transcript-only, or paired evidence. Zoom speaker-bearing VTT is converted before finalization into the trusted speaker-attributed text form plus timed VTT, while Teams exports retain their established form. Transcript dialect is declared explicitly, never inferred as truth from content.
- Web acquisition validates before submission, returns an acquisition identifier, and progresses from launch through posting into the existing ingest-stage stream. Upload metadata includes a user-supplied title and RFC 3339 timestamp with numeric offset; the system does not invent wall-clock time from a date or media metadata.
- Playlists are acquired sequentially as independent meetings with per-entry outcomes. A failed entry does not stop the remaining entries.
- YouTube moments retain local replay as the primary action and expose the original video at the moment offset as a secondary action.
- Acquisition adds real-corpus evidence and performs no paid model calls. Extraction wording must apply equally to meetings and recorded sessions without changing parser-sensitive output contracts.
- Routine tests remain offline and deterministic; live network coverage is explicitly opt-in.

## Technical Decisions

- A versioned source-drop schema is the boundary between acquisition and ingestion. Drops contain regular-file evidence, are assembled in staging, validated, and finalized atomically; finalized contents are never modified.
- `POST /ingests` is the only intake door. Duplicate source identities do not create duplicate meetings, and no folder watcher or direct database path may bypass intake.
- Acquisition commands reuse the established drop-minter finalization path rather than implementing a second staging or rename mechanism. Evidence metadata includes root-relative identity, checksums, and sizes; temporary extractor metadata is not part of the finalized drop.
- The API launches acquisition tools as detached host processes. Status is externalized per acquisition and reports `queued`, `running`, `posted`, or `failed`; successful status distinguishes newly created from existing evidence, while failure carries a structured rule, detail, and remediation. Diagnostic logs are not the UI contract.
- Uploads stream only into staging beneath the drops root. Conversion happens before finalization because intake treats source material as immutable.
- Thresholds such as maximum video duration and upload size live in versioned configuration. Secrets and machine-specific roots remain environment values.
- API failures use Problem Details. Routes follow the repository's discovery mechanism, and generated clients are refreshed only in the stories that change the API surface.
- Wall-clock timestamps remain source-derived UTC values with explicit precision; playback offsets remain integer milliseconds from recording start.

## UX & Interaction Patterns

- The adopted design companion is the versioned `DESIGN.md` and `EXPERIENCE.md` pair under the Epic 6 UX planning artifacts. Their behavioral and token spines override mockups; deviations require a recorded reason.
- Add-meeting is a route with four source tabs: YouTube URL, local files, Zoom export, and Teams export. It validates before any write, keeps partially entered tab state, and never submits merely by switching tabs.
- A successful URL probe shows source identity, title, duration, and caption availability before Submit enables. Async responses belong only to the current normalized input; stale probe results must not replace newer state.
- Acquisition and ingestion progress render in place. Refusals appear beside the responsible control with the rule, detail, and remediation; results are not toasts, and disabled actions state why.
- File classification may provide hints, but the operator explicitly chooses transcript dialect. Progress loss preserves the last known state and offers retry without inferring success or failure.
- The experience targets WCAG 2.2 AA: semantic controls, keyboard operation, data-bearing accessible names, meaningful state beyond color, polite progress announcements, assertive failure announcements, reduced motion, and single-column reflow at 200% text zoom down to 320 CSS pixels.

## Cross-Story Dependencies

- The delivered UX specification governs the Epic 6 UI and deep-link stories.
- The YouTube and local-file commands are the engines used by the acquisition launch and upload-session surfaces; those API surfaces provide the probe, status, and upload contracts rendered by the Add-meeting UI.
- Add-meeting reuses the existing ingest job stream, meeting card, viewability gate, and route registry. YouTube deep links reuse the existing replay and citation surfaces.
- Playlist acquisition remains command-line only. Downstream speaker work consumes anonymous YouTube speakers and source-resolved Zoom names; downstream corpus and thread work consumes the meetings created here.
