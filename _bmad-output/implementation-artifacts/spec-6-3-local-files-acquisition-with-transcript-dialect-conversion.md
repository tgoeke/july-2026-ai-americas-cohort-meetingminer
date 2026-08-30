---
title: 'Story 6.3: Local-Files Acquisition with Transcript Dialect Conversion'
type: 'feature'
created: '2026-08-30'
status: 'draft'
baseline_revision: 'd72c658'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/build-prompt-story-6-3-2026-08-30.md'
  - '{project-root}/_bmad-output/implementation-artifacts/wave-2026-08-30-rules.md'
  - '{project-root}/.claude/skills/integrate/conflict-playbook.md'
deferred: []
---

<intent-contract>

## Intent

**Problem:** A meeting exported from Zoom carries a `.vtt` whose cue payloads
read `Name: text`. The pipeline's transcript contract has exactly three
lineages — Teams `[m:ss] Last, First: text`, legacy `<Name> | MM:SS` blocks, and
a speaker-less VTT that contributes end timings only — and a VTT never supplies
a speaker (AD-13). So a Zoom export minted today loses every speaker: the `.txt`
is absent, the `.vtt`'s cues are read speaker-less, and every derived segment is
`Unknown`/`placeholder`. Those meetings cannot enter the corpus with their
speakers intact (FR35).

**Approach:** Convert at *acquisition*, never in the pipeline. `mint-drop` gains
`--transcript-dialect {plain,teams-vtt,zoom}` (default `plain`, never inferred
from content). For `zoom`, a new `meetingminer.transcripts.dialects` module
turns the supplied Zoom `.vtt` into the two files the drop actually holds — a
legacy-lineage `transcript.txt` (`<Name> | MM:SS` header, utterance beneath) and
a speaker-less `transcript.vtt` carrying every cue's timing — writes them into a
temporary workspace, and hands *those* paths to the unchanged `mint()`.
`provenance.transcriptDialect` records the dialect, the conversion, and the file
converted from, through story 6.2's `provenance_extra` keyword override.
`pipeline/transcripts.py` and `pipeline/stages/align.py` are untouched: the
converted `.txt` is an ordinary legacy transcript, so `align` resolves Zoom names
through the roster by exactly the path a Teams label takes.

## Boundaries & Constraints

**Always:**
- The dialect is **declared, never inferred**. No content sniffing decides it;
  `plain` is the default and is today's behaviour bit-for-bit (no
  `transcriptDialect` key is written at all for `plain`).
- `teams-vtt` passes every supplied file through unchanged — a Teams export
  already *is* the trusted format — and records
  `{"dialect": "teams-vtt", "converted": false}` as the operator's declaration.
- `zoom` converts, and **verifies its own output with the pipeline's own
  parser** before anything is minted: the produced `.txt` must re-parse through
  `pipeline.transcripts.parse_text_transcript` as `FORMAT_LEGACY` with the exact
  turn count, speaker labels, and start offsets the converter intended, or the
  command refuses and writes nothing. A drop is write-once, so a transcript the
  `align` stage would fail on must never reach the drops root — the same
  argument that puts schema validation inside `_assemble`.
- The conversion is **deterministic**: the same Zoom `.vtt` produces the same
  bytes, so a transcript-only re-mint reaches `exists` (identity is still the
  digest of the bytes that entered the drop — `mint()`'s rule is unchanged). A
  golden-bytes test pins the output so a converter change cannot silently mint a
  duplicate meeting.
- A cue's speaker is the text before the first `:` on its first payload line,
  accepted only when it is 1–6 whitespace-separated tokens, contains a letter,
  and contains none of `.`, `?`, `!`. An unrecognised prefix yields the
  pipeline's `Unknown` placeholder — never the previous speaker's name, because
  a wrong attribution is worse than an absent one.
- Consecutive cues by the same speaker merge into one turn (start = the first
  cue's start), which is what a "turn" means in both existing text lineages.
- `mint()` and `build_metadata()` are extended **only** through story 6.2's
  existing keyword-override path, taken verbatim (below).
- Footprint is the wave contract: `server/meetingminer/transcripts/` (new),
  `mintdrop.py`'s `_parser()`/`main()` plus the 6.2 override regions,
  `docs/README.md` (own section + one argument-table row),
  `server/tests/test_transcript_dialects.py` (new), and this story's
  `_bmad-output` artifacts.

**Block If:**
- The story cannot land without editing `server/meetingminer/pipeline/
  transcripts.py` or `pipeline/stages/align.py` — the acceptance criteria
  require both unchanged.
- The 6.2 override regions on `origin/story/6-2` change shape mid-run.

**Never:** `pipeline/transcripts.py`, `pipeline/stages/align.py`,
`pipeline/speakers.py`, `server/tests/conftest.py`,
`server/tests/test_mint_drop.py`, `infra/Makefile`, `config.py`, `config.yaml`,
root `README.md`, `AGENTS.md`, `docs/backlog.md`. No dialect inference from
content. No second mechanism for provenance overrides. No edit inside a
finalized drop. No paid model call; no store fixtures; no shared api or worker.

## The pinned 6.2 coupling

`server/meetingminer/mintdrop.py`'s `build_metadata()` and `mint()` keyword
overrides are **taken verbatim from `story/6-2` commit `7625b79`** ("feat:
mint() keyword overrides and acquisition config (story 6.2 groundwork)"), whose
parent's `mintdrop.py` is byte-identical to `main`'s at `d72c658`. This branch
therefore carries the *same* hunk, not a parallel one — the two regions merge
with no resolution at all, which is the mechanical form of the `seed_meeting()`
precedent in `.claude/skills/integrate/conflict-playbook.md`.

The pinned shape, unchanged by this story:

```python
def build_metadata(..., provenance_extra: dict[str, Any] | None = None) -> dict[str, Any]
def mint(..., source_id: str | None = None,
              started_at_override: tuple[str, str, str] | None = None,
              provenance_extra: dict[str, Any] | None = None) -> MintResult
```

`provenance_extra` is merged over the provenance defaults. Story 6.3 passes
only `provenance_extra`; `source_id` and `started_at_override` arrive with the
verbatim hunk and are story 6.2's callers to exercise.

## The provenance record

Written under `provenance.transcriptDialect` (the drop schema's `provenance` is
an open object, so this is schema-valid and needs no schema edit):

```json
"transcriptDialect": {
  "dialect": "zoom",
  "converted": true,
  "outputs": ["transcript.vtt", "transcript.txt"],
  "source": {"sourcePath": "/abs/path/zoom.vtt", "sha256": "…", "byteSize": 1234},
  "cueCount": 12,
  "turnCount": 5,
  "speakerLabels": ["Alice Chen", "Bob Smith"]
}
```

`provenance.files[]` records the bytes that entered the drop — the *converted*
files, with a `sourcePath` inside the transient workspace. `transcriptDialect.
source` is therefore the only record of the operator's original file, and it
carries that file's digest and size so the conversion is auditable after the
workspace is gone.

For `teams-vtt`: `{"dialect": "teams-vtt", "converted": false}`. For `plain`:
the key is absent.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Zoom transcript-only | `zoom.vtt` with `Name: text` cues, `--transcript-dialect zoom` | drop holds `transcript.txt` (legacy blocks) + speaker-less `transcript.vtt`; `provenance.transcriptDialect.converted` true | — |
| Zoom + recording | `.mp4` + `zoom.vtt` | all three evidence files; identity still the recording's digest | — |
| Zoom names align | converted `.txt` | `parse_text_transcript` → `FORMAT_LEGACY`; `roster_from_labels` + `resolve_label` resolve every real name, exactly as the same names spelled Teams-style | — |
| Same names, graph roster | drop-graph match keys | Zoom labels resolve to the same roster entries a Teams label does | — |
| Consecutive same speaker | 3 cues by one speaker | one turn, start = first cue, text joined | — |
| No speaker prefix on a cue | `so anyway we shipped` | that cue becomes an `Unknown` turn (placeholder), never the previous speaker | — |
| Prose colon | `Right. So: here we go` | prefix rejected (contains `.`) → `Unknown` | — |
| Cue with prefix and no text | `Alice Chen:` | cue skipped in both outputs | — |
| Zero cues carry a speaker | a speaker-less VTT declared `zoom` | named refusal naming `--transcript-dialect teams-vtt` | nothing written |
| Not WebVTT | a `.txt` or a file with no `WEBVTT` header supplied as the zoom source | named refusal | nothing written |
| Unparseable cue timing | `00:00:01 -> bad` | named refusal quoting the line number | nothing written |
| No `.vtt` supplied | `--transcript-dialect zoom` with only `.mp4` | named refusal | nothing written |
| `.txt` also supplied | `--transcript-dialect zoom` with `.vtt` + `.txt` | named refusal (the conversion produces the `.txt`) | nothing written |
| Body text with ` \| ` | a cue payload containing a pipe | self-verification refuses, naming the turn | nothing written |
| Past the hour | a cue at 01:57:24 | header stamp `01:57:24` (`HH:MM:SS`), parsed by field count | — |
| `--transcript-dialect teams-vtt` | Teams `.txt` + `.vtt` | files pass through byte-identical; `converted: false` recorded | — |
| `--transcript-dialect plain` / omitted | anything | today's behaviour exactly; no `transcriptDialect` key | — |
| Unknown dialect | `--transcript-dialect webex` | argparse refuses with the choice list | exit 2 |
| Re-mint the same Zoom file | second run | `exists`, nothing written (deterministic conversion) | — |

</intent-contract>

## Code Map

- `server/meetingminer/transcripts/dialects.py` — **new**. `DIALECTS`,
  `DialectError`, `Conversion`, `convert_supplied()`, plus the pure pieces:
  `read_zoom_cues()`, `zoom_turns()`, `render_legacy_text()`,
  `render_timing_vtt()`, `format_block_stamp()`, `format_cue_time()`,
  `verify_legacy_text()`. Imports `meetingminer.domain.drops` for the canonical
  filenames and `meetingminer.pipeline.transcripts` **read-only**, for
  `parse_timestamp` (one timestamp rule) and for the self-verification parse.
  It cannot import `mintdrop` — `mintdrop` imports it.
- `server/meetingminer/mintdrop.py` — `build_metadata()` `:549`, `mint()` `:615`
  (the verbatim 6.2 hunk); `_parser()` `:935` gains `--transcript-dialect`;
  `main()` `:1035` opens the workspace, converts, and passes
  `provenance_extra`. `classify_supplied` and `EXTENSION_TO_CANONICAL` are in
  the allowed footprint but need **no** edit: the converted paths are ordinary
  `.vtt`/`.txt` files and the "two files map to one canonical name" case is
  refused earlier, by name, in `dialects`.
- `server/meetingminer/pipeline/transcripts.py` — read-only. `_LEGACY_HEADER`
  `:49`, `parse_legacy_text()` `:239`, `parse_text_transcript()` `:330`,
  `detect_text_format()` `:160` are the contract the converted `.txt` satisfies.
- `server/meetingminer/pipeline/stages/align.py` — read-only. `_label_roster`
  `:339`, `speakers.resolve_label` at `:621`: the path a converted label takes.
- `server/tests/test_transcript_dialects.py` — **new**, all coverage. Store-free
  (`tmp_path` sources, a per-test child of the configured drops root exactly as
  `test_mint_drop.py`'s `mint_root` does), no `conftest.py` edit, no api call.

## Verification

- `uv run --project server pytest server/tests/test_transcript_dialects.py -q`
- Round trip: Zoom `.vtt` fixture → `mint()` → read the drop's `transcript.txt`
  → `parse_text_transcript` → `roster_from_labels`/`resolve_label` resolve the
  Zoom names, and the same roster resolves the same people written Teams-style.
- `make test-fast`, then `make test` once before `review`.
- `python3 _bmad/scripts/branch_conflicts.py --against story/6-3`.
