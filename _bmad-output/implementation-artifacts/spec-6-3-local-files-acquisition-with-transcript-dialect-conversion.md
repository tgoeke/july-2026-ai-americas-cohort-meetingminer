---
title: 'Story 6.3: Local-Files Acquisition with Transcript Dialect Conversion'
type: 'feature'
created: '2026-08-30'
status: 'in-review'
baseline_revision: 'd72c658'
baseline_commit: 'b3bb1d09cdf19c72af46d10abbec1ba02bdfda63'
review_loop_iteration: 1
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/implementation-artifacts/build-prompt-story-6-3-2026-08-30.md'
  - '{project-root}/_bmad-output/implementation-artifacts/wave-2026-08-30-rules.md'
  - '{project-root}/.claude/skills/integrate/conflict-playbook.md'
deferred:
  - summary: >-
      A cue prefix containing `.`, `?` or `!` is not read as a speaker, so a
      name written `Dr. Alice Chen` becomes an `Unknown` turn. The rule is
      deliberate — the alternative reads `Right. So:` as a person — but a
      roster-aware second pass (accept a rejected prefix that normalizes onto
      a name the same file already established) would recover it without
      guessing. Out of scope here: it needs the drop's participant graph,
      which mint-drop does not read.
    location: 'server/meetingminer/transcripts/dialects.py:_is_speaker_name'
    severity: low
  - summary: >-
      Turn merging is "consecutive cues by the same speaker", with no gap
      bound, so a speaker whose cues straddle a long silence with nobody else
      speaking becomes one turn. `align` caps the derived end at
      `pipeline.align.max_segment_ms`, so the effect is confined to turn
      granularity, and a gap threshold would be a new tunable in `config.yaml`
      — outside this story's footprint.
    location: 'server/meetingminer/transcripts/dialects.py:zoom_turns'
    severity: low
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

## Result

Landed on `story/6-3`:

| SHA | What |
|---|---|
| `f145c1e` | this spec, and the story 6.2 `mint()`/`build_metadata()` override hunk taken verbatim |
| `bb5d031` | `meetingminer/transcripts/` (new), the `--transcript-dialect` CLI, `test_transcript_dialects.py` (35 tests) |
| `05315d6` | `docs/README.md` — the "Transcript dialects" subsection and one argument-table row |

### Footprint, as actually used

Two regions the build prompt allowed were **not** edited, because nothing
needed them: `classify_supplied` and `EXTENSION_TO_CANONICAL`. The converted
files are ordinary `.vtt`/`.txt` paths by the time `mint()` sees them, and the
"two files map to one canonical name" case is refused earlier and by a better
name in `dialects._zoom_source` ("the conversion produces `transcript.txt`, and
a drop holds one of each") than `classify_supplied` could give it while naming
two workspace paths. Not editing them also keeps `mintdrop.py`'s diff to the
6.2 hunk plus the CLI, which is what keeps the branch pair clean below.

`server/meetingminer/pipeline/transcripts.py` and `pipeline/stages/align.py`
are untouched, as the acceptance criteria require. Both are *imported* by the
converter and by the tests — `parse_timestamp` so this repository has one
answer to what `00:01:02.500` means, `parse_text_transcript` so the converter's
self-check is the pipeline's own reading rather than a second implementation of
it, and `speakers.resolve_label` so the roster assertion is the resolver's real
behaviour.

### The branch pair, and the one named conflict

`python3 _bmad/scripts/branch_conflicts.py --against story/6-3` reports
`story/6-3 × story/6-2` **clean** — the verbatim hunk did what it was meant to:
both branches carry the identical change, so there is nothing to resolve.

`story/6-3 × story/6-2-review` reports one conflict, in `mintdrop.py`, and it
is mechanical. `story/6-2-review` hardened `provenance_extra` after `6-2` was
cut (`_validate_provenance_extra`, refusing the mint-owned keys `title`,
`mintedAt`, `suppliedBy`, `startedAtSource`, `files`); its merge base with this
branch predates the block entirely, so both sides read as "added the same
region". **Resolution: take `story/6-2-review`'s side of that block whole.** It
is a strict superset of the block this branch carries, this branch adds no
other line inside it, and `transcriptDialect` is not a mint-owned key.

That resolution was executed and tested rather than asserted: resolving the
conflict that way and running `test_transcript_dialects.py` plus the whole of
`test_mint_drop.py` against the result gives **103 passed**.

The other two kinds of pair this run reported are not about code:

- `sprint-notes.md` conflicts with every lane that has also written its
  narrative there (`7-1`, `8-1`, `10-1`, `11-3`, `11-4`). The wave rules put
  narrative in that file, every lane appends at EOF, and git cannot union two
  appends after the same last line — so this is inherent to the instruction,
  not to any lane's edit. The narrowing available was to make the hunk small:
  this story's entry was trimmed to the decisions and the coupling result,
  with the detail left here, in the file only this lane owns. Resolution at
  integrate is "keep both sections".
- `spec-11-2-per-run-store-isolation.md` (with `11-2-review`) and
  `review-story-11-4-2026-08-30.md` (with `11-4-review`) conflict with `main`
  as well, so they are inherited, not introduced here.

### Verification actually run

- `uv run --project server pytest server/tests/test_transcript_dialects.py -q`
  — **35 passed** in 0.21s (every test store-free and inside the fast budget).
- **A 14-mutation matrix** over the converter and the CLI wiring, each mutation
  applied to the implementation and the suite re-run: turns never merge, any
  prefix is a speaker, self-verification disabled, the emitted `.vtt` keeps the
  speaker prefix, no hour field in the block stamp, `teams-vtt` records
  nothing, `plain` infers zoom from content, a malformed cue timing is skipped
  rather than refused, a supplied `.txt` is allowed beside the conversion,
  `mint()` is not given the dialect provenance, the stamp rounds instead of
  truncating, a speaker-less export declared `zoom` is accepted, a cue with no
  words is kept, the converted files are never handed to `mint()`. **Every
  mutation was killed**, each by the test that names the rule.
- `make test-fast` — one failure, `test_frame_image.py::
  test_an_unreadable_frame_raises_a_named_error`, on the fast-set *budget*
  (2.91s against 2.00s) in a module this story does not touch. Re-run alone it
  takes 0.01s, so it is the contention the budget message itself tells you to
  check for, from the other lanes' suites on the shared stack. It did not recur
  in the full gate.
- `make test` — **1762 passed** in 9m22s, plus the web build.
- `python3 _bmad/scripts/branch_conflicts.py --against story/6-3` — as above.

Not run: `make evals-run` (paid), the shared api and worker (never started), any
model call. No test posts to an api; the two mint-through-the-CLI tests pass
`--no-post` and install a fixture that fails the test if any HTTP call is made.

## Owner ruling follow-up — F6 (2026-08-30)

The owner **deferred** F6. Do not amend the whole-second truncation contract and
do not change the converter. The reproduced mechanism is real, but the corpus
does not yet establish how often genuine Zoom exports contain sub-second
speaker changes. Preserve the exact reproduction in `deferred-work.md` with a
revisit trigger of real Zoom exports in the new corpus showing sub-second
speaker changes.

The only code change authorized by this ruling is observability at the existing
fallback boundary. When alignment's existing fallback produces a zero-duration
turn because two turn starts collide, emit a named structured warning carrying
the meeting, the turn, and both colliding stamps. This is a log line only: no
behavior change, no contract amendment, no retry, and no converter edit. Keep
the pure alignment decision function unchanged and emit at the pipeline stage
boundary where the meeting identity and structured logger are available.

### Tasks & Acceptance — F6 owner ruling

- [x] Record F6 as **DEFERRED** in the review report and
  `_bmad-output/implementation-artifacts/deferred-work.md`, retaining verbatim:
  cues at 1.100s and 1.900s; observed
  `merge_vtt_end_timings() -> (None, 2200)`; resulting zero-duration boundary;
  revisit only when real Zoom exports in the new corpus show sub-second speaker
  changes.
- [x] Add a red-first regression test proving the fallback emits one named
  structured warning with the meeting, affected turn, and the two colliding
  stamps.
- [x] Add the warning at the alignment stage boundary without changing
  `resolve_end_times()`, converter output, accepted inputs, or stored timing
  behavior. Assert the reproduced result remains the zero-duration first
  boundary followed by 2200ms.
- [x] Update the owner/spec handoff after the F6 ruling. The later F1 ruling is
  recorded below; do not merge to `main`.

## Owner ruling follow-up — F1 (2026-08-30)

The owner **deferred** F1. Do not amend the identity contract and do not change
code or tests. The reproduction remains real: `Alice: identical words` and
`Bob: identical words` produce the same `sha256:d53bde...` identity because
`transcript.vtt` sorts before `transcript.txt` in
`_digest_supplied(classify_supplied(...))`; `_evidence_not_in()` cannot warn
because the existing drop already carries the canonical filename.

Revisit only when an operator re-mints a corrected Zoom export and the system
reports `exists` while keeping the old attribution. Preserve both candidate
fixes for that future decision: identity from the operator's original supplied
file, or a deterministic digest over both converted artifacts. The full
reproduction and trigger are recorded in `deferred-work.md`.

## Suggested Review Order

**Owner ruling and observability**

- Start with the final identity ruling that clears the last open finding.
  [`spec-6-3-local-files-acquisition-with-transcript-dialect-conversion.md:345`](spec-6-3-local-files-acquisition-with-transcript-dialect-conversion.md#L345)

- Inspect the warning-only boundary; timing decisions remain in the pure core.
  [`align.py:587`](../../server/meetingminer/pipeline/stages/align.py#L587)

**Deferred evidence and landing state**

- Confirm F1's exact collision, trigger, and both candidate fixes remain intact.
  [`deferred-work.md:272`](deferred-work.md#L272)

- Confirm F6's exact reproduction and corpus-based revisit trigger remain intact.
  [`deferred-work.md:265`](deferred-work.md#L265)

- Verify both owner deferrals leave no finding open for remediation.
  [`review-story-6-3-2026-08-30.md:168`](review-story-6-3-2026-08-30.md#L168)

- Review the ready-to-land state and explicit owner-operated integration handoff.
  [`build-prompt-story-6-3-2026-08-30.md:3`](build-prompt-story-6-3-2026-08-30.md#L3)

**Regression coverage**

- Reproduce the two sub-second cues and unchanged stored boundaries.
  [`test_worker_transcripts.py:928`](../../server/tests/test_worker_transcripts.py#L928)

- Check the review-found descending-start edge uses warning-only behavior.
  [`test_worker_transcripts.py:980`](../../server/tests/test_worker_transcripts.py#L980)
