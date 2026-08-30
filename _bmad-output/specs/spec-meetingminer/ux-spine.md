# User-Experience Spine

Companion to `SPEC.md`. The concrete flows and view anatomy the capstone UI implements.

## Ingestion flow

Meeting hosted/recorded on the corp Teams tenant → open recap in browser → capture Stream URL → paste into the puller script (`pull_transcript`) → the puller finalizes a write-once drop (recording and/or transcript plus metadata sidecar with embedded provenance) in the drop folder on the dev Mac and notifies MeetingMiner, which ingests it — files in the folder alone never ingest. Ingestion completes before viewing: video processed, screenshots extracted, moments identified, transcript segmented to match video flow — all precomputed. Transcript-only meetings (no downloadable recording) get moments from transcript segmentation: searchable and citable, without screenshots, and with a transitional source deep link to the original recap where the replay button would sit. When the recording is recovered later, it augments the meeting in place — screens, screenshots, alignment and true replay appear on the existing moments, and the deep link retires. Participants are derived from transcript speakers and the sidecar at ingest to build the participant graph.

## Moment view anatomy

- Still screenshot on top.
- Transcript section below.
- Right rail: extracted analytics — action items, ADRs, decisions, stories, requirements, bug fixes, change requests.
- Full audio+video replay button.

Screenshots + transcript segments are what people actually review; video clips are rarely watched but serve as proof that derived artifacts are correct. Decision records link back to their video moment.

## Search and locate

- Corpus-wide topic search → candidate meetings → drill into transcript with highlighted mentions → small inline video replays.
- Search by meeting name, topic, mention; ask questions about any decision.
- Meeting drill-down shows the captured screenshot series: UI screens, slides, or participant headshots when nobody is presenting.

## Meeting archetypes

Two archetypes drive different screenshot types and artifact sets:

1. Slide-deck presentations.
2. UI demos.

## Human-approved publishing

Extracted artifacts start unpublished. On first visit the user chooses to push stories/tasks/decision docs out — "AI proposes, humans approve" as a UX gesture, per moment. Outbound links to anything created are shown in context; MeetingMiner never shows or owns downstream status.
