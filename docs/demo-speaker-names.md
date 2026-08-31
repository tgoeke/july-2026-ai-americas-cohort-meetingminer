# Assigned speaker names — demo corpus

**These are assigned labels for a demo corpus, not identifications.** The
recordings are public meetings; nothing here claims to name the real people in
them. Assigned 2026-08-31 through the ordinary curator path
(`PUT /meetings/{id}/speakers/{tag}`), which is how AD-13 says a tag is
resolved.

Use this list to search the corpus for a speaker.

## METRO Green Line Extension Corridor Management Committee (June 3)

`01a057d1-7348-7c2a-a001-a9c1f582220e`

| tag | assigned name | segments |
|---|---|---|
| SPEAKER_00 | Dana Whitfield | 96 |
| SPEAKER_01 | Marcus Ellery | 116 |
| SPEAKER_02 | Priya Raghunathan | 148 |
| SPEAKER_03 | Tobias Lindqvist | 115 |
| SPEAKER_04 | Rosalind Achebe | 118 |

## Green Line Extension Corridor Management Committee (September 10)

`01a057d3-cfe8-7522-a689-ca73ae421853`

| tag | assigned name | segments |
|---|---|---|
| SPEAKER_00 | Nadia Boulanger | 306 |
| SPEAKER_01 | Emmett Kowalski | 116 |
| SPEAKER_02 | Sunita Varma | 209 |
| SPEAKER_03 | Gregor Halvorsen | 57 |
| SPEAKER_04 | Imani Fitzgerald | 151 |

## Why only these two meetings

Measured across the whole corpus on 2026-08-31:

| speaker labelling | meetings | segments |
|---|---|---|
| `Unknown` | 29 | 55,669 |
| `SPEAKER_NN` (diarized) | 2 | 1,432 |
| Real names from a Teams export | 2 | 24 |

Only two meetings carry `SPEAKER_NN` tags, so only two had anything to assign.

The reason is the ingestion path, not diarization. A YouTube drop carries the
video **and** its auto-generated `transcript.vtt`. When a drop supplies a
transcript, the pipeline parses it instead of running speech recognition — and
**auto-generated captions carry no speaker labels**, so every segment lands as
`Unknown`. Diarization never gets a chance to attribute anything, because the
transcript it would attribute was already provided.

The two meetings above are the exception because they were deliberately
re-minted from `recording.mp4` **alone**, with no transcript, which forces
speech recognition plus diarization and produces `SPEAKER_NN` tags.

**To get speaker separation on more meetings**, re-mint them from the recording
only. Cost per meeting is roughly transcription (~104 s median), diarization on
the LAN GPU host (fast, free), then align → moments → extract, where extraction
is the paid model at about $0.47 a meeting. Doing all 29 would be several hours
and roughly $14; doing the three or four the walkthrough actually opens is
minutes and small change.
