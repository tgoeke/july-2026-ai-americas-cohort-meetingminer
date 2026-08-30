# Reference UI

Companion to `SPEC.md`. The user-supplied competitor screenshot `reference-competitor-meeting-view.png` (in this folder) is the visual target for CAP-2 and the density bar for the whole reimagining: dark, data-dense, monospace-leaning, every element timestamp-anchored.

## Element map — reference → MeetingMiner data

| Reference element | Backing data here | Tonight? |
|---|---|---|
| Header: title · date · duration · turns · words · passages · source lineage ("Teams transcript (VTT) — speaker-attributed") | meeting row + transcript segments + `transcript_source`; counts are cheap aggregates | yes |
| "SCREENS 158" film-strip, thumbnails with `HH:MM:SS` under each | drilldown screenshot series (`viewType`, `screenLabel`, offset) | yes |
| Transcript passages: timestamp chip, speaker, flowing text | drilldown transcript segments (offset, speaker, text) | yes |
| EXTRACTED / ACTIONS n: timestamp range chip, text, id + owner + status line | `MomentArtifact` (7 kinds) with moment anchor, state (unpublished/published), published path/commit | yes — group by kind, real states |
| RISKS section | no risk kind extracted | no — render only kinds that exist |
| PARTICIPANTS incl. explicit absence note ("No participant graph for this meeting — …") | participants per meeting; transcript-only/absence cases exist | yes — absence note verbatim pattern |
| TOPICS frequency chips | no topic model computed | no — post-demo (open question) |
| GENERATED DOCUMENTS n with file sizes | published artifacts + publish folder / git commits | yes for published artifacts |

## Directions carried spec-wide

- Counts everywhere: a section header is "SCREENS 158", not "Screens".
- Timestamps are the connective tissue — every artifact, passage, and thumbnail shows its moment offset and jumps/replays on click.
- Honest absence beats decoration: when a meeting lacks a participant graph or a recording, say why in place, in one sentence.
