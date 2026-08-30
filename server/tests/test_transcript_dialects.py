"""Transcript dialect conversion at acquisition (story 6.3, FR35).

Store-free by construction: the only I/O is `tmp_path` and a per-test child of
the configured drops root, exactly as `test_mint_drop.py`'s `mint_root` does.
No Postgres fixture, no api, no ffprobe (nothing here mints a recording).

Three things are asserted, and they are the three the acceptance criteria name:

* a Zoom `.vtt` becomes the **legacy** lineage `.txt` plus a speaker-less
  `.vtt`, byte for byte — the bytes are pinned because they are part of a
  transcript-only drop's `sourceId`, so a converter change that alters them
  would mint a second meeting for a file already in the corpus;
* `teams-vtt` and `plain` pass through, and no dialect is ever inferred; and
* the converted transcript is read by `pipeline/transcripts.py` and resolved by
  `pipeline/speakers.py` **unchanged** — a Zoom name resolves through the
  roster by exactly the code path a Teams label takes. Those two modules are
  imported here and never edited by this story; if the conversion needed a
  pipeline change, these tests would be the ones that could not be written.
"""

from __future__ import annotations

import json
import shutil
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from meetingminer import mintdrop
from meetingminer.config import AlignConfig
from meetingminer.pipeline import speakers, transcripts
from meetingminer.pipeline.alignment import TimedText, merge_vtt_end_timings
from meetingminer.transcripts import dialects

from conftest import DROPS_ROOT
from repo_paths import REPO_ROOT

SCHEMA = json.loads(
    (REPO_ROOT / "docs" / "source-drop.schema.json").read_text(encoding="utf-8")
)
VALIDATOR = jsonschema.Draft202012Validator(
    SCHEMA, format_checker=jsonschema.FormatChecker()
)

# A Zoom audio-transcript export: `WEBVTT`, numbered cues, `Name: text`
# payloads, one cue per sentence and the name repeated on every one.
ZOOM_VTT = """WEBVTT

1
00:00:01.000 --> 00:00:04.120
Ironside, Indigo: Good morning everyone.

2
00:00:04.500 --> 00:00:07.000
Ironside, Indigo: Let us start with the migration.

3
00:00:07.400 --> 00:00:11.250
Priya Holloway: The staging cutover finished last night.

4
00:00:11.900 --> 00:00:15.000
Ironside, Indigo: Good, that unblocks the rollout.
"""

# What the conversion above must produce, byte for byte.
EXPECTED_TEXT = """Ironside, Indigo | 00:01
Good morning everyone. Let us start with the migration.

Priya Holloway | 00:07
The staging cutover finished last night.

Ironside, Indigo | 00:11
Good, that unblocks the rollout.
"""

EXPECTED_VTT = """WEBVTT

00:00:01.000 --> 00:00:04.120
Good morning everyone.

00:00:04.500 --> 00:00:07.000
Let us start with the migration.

00:00:07.400 --> 00:00:11.250
The staging cutover finished last night.

00:00:11.900 --> 00:00:15.000
Good, that unblocks the rollout.

"""

# The same meeting as Teams writes it. Used to show the two lineages resolve
# through the roster identically — the third acceptance clause.
TEAMS_TEXT = """[0:01] Ironside, Indigo: Good morning everyone.
[0:07] Holloway, Priya: The staging cutover finished last night.
"""

ALIGN = AlignConfig(
    anchor_window_seconds=2.0, min_match_score=0.35, max_segment_ms=60000
)


# --- helpers ---------------------------------------------------------------


@pytest.fixture()
def workspace(tmp_path: Path) -> Iterator[Path]:
    """Where a conversion writes, when the test drives the module directly."""
    out = tmp_path / "workspace"
    out.mkdir()
    yield out


@pytest.fixture()
def zoom(tmp_path: Path) -> Path:
    path = tmp_path / "Migration Sync.vtt"
    # The configured drops root is shared by concurrent server-suite runs and
    # source identity is global there, so a test transcript must not
    # impersonate another worker's.
    path.write_text(
        ZOOM_VTT.replace("the rollout", f"the rollout {tmp_path.name}"),
        encoding="utf-8",
    )
    return path


@pytest.fixture()
def mint_root(tmp_path: Path) -> Iterator[Path]:
    root = DROPS_ROOT / f"dialect-{tmp_path.name}"
    root.mkdir()
    try:
        yield root
    finally:
        # This fixture owns exactly this child, never the shared configured
        # root or drops emitted by any other concurrent test process.
        shutil.rmtree(root)


@pytest.fixture()
def no_http(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly if a test that must make no HTTP call makes one."""

    def _forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the command made an HTTP call")

    monkeypatch.setattr(urllib.request, "urlopen", _forbidden)


def convert(source: Path, into: Path, *, dialect: str = dialects.DIALECT_ZOOM):
    return dialects.convert_supplied([str(source)], dialect=dialect, into=into)


def written(conversion: dialects.Conversion, suffix: str) -> Path:
    return next(Path(p) for p in conversion.supplied if p.endswith(suffix))


def run(root: Path, *args: str) -> int:
    return mintdrop.main([*args, "--drops", str(root), "--no-post"])


def only_drop(root: Path) -> Path:
    drops = sorted(p for p in root.iterdir() if not p.name.startswith("."))
    assert len(drops) == 1, drops
    return drops[0]


def read_drop_metadata(drop: Path) -> dict[str, Any]:
    metadata = json.loads((drop / "metadata.json").read_text(encoding="utf-8"))
    errors = [
        ("/".join(str(part) for part in error.absolute_path) or "(root)")
        + ": "
        + error.message
        for error in VALIDATOR.iter_errors(metadata)
    ]
    assert errors == [], f"{drop} violates the source-drop schema"
    return metadata


def vtt(*cues: tuple[str, str, str]) -> str:
    body = "".join(f"{start} --> {end}\n{payload}\n\n" for start, end, payload in cues)
    return f"WEBVTT\n\n{body}"


# --- the conversion itself -------------------------------------------------


def test_a_zoom_vtt_becomes_legacy_blocks_and_a_speakerless_vtt(
    tmp_path: Path, workspace: Path
) -> None:
    """Acceptance: both files, byte for byte, from one declared `.vtt`."""
    source = tmp_path / "sync.vtt"
    source.write_text(ZOOM_VTT, encoding="utf-8")

    conversion = convert(source, workspace)

    assert written(conversion, ".txt").read_text(encoding="utf-8") == EXPECTED_TEXT
    assert written(conversion, ".vtt").read_text(encoding="utf-8") == EXPECTED_VTT
    record = conversion.provenance_extra[dialects.PROVENANCE_KEY]
    assert record["dialect"] == "zoom"
    assert record["converted"] is True
    assert record["outputs"] == ["transcript.vtt", "transcript.txt"]
    assert record["cueCount"] == 4
    assert record["turnCount"] == 3
    assert record["speakerLabels"] == ["Ironside, Indigo", "Priya Holloway"]
    # The only record of the operator's own file: `provenance.files[]`
    # describes the converted bytes, whose path is a workspace that is gone.
    assert record["source"]["sourcePath"] == str(source.resolve())
    assert record["source"]["byteSize"] == source.stat().st_size


def test_the_converted_text_is_the_legacy_lineage_the_pipeline_already_parses(
    tmp_path: Path, workspace: Path
) -> None:
    """`pipeline/transcripts.py` reads it with no change of any kind."""
    source = tmp_path / "sync.vtt"
    source.write_text(ZOOM_VTT, encoding="utf-8")

    parsed = transcripts.parse_text_transcript(
        written(convert(source, workspace), ".txt").read_text(encoding="utf-8")
    )

    assert parsed.format == transcripts.FORMAT_LEGACY
    assert [segment.speaker_label for segment in parsed.segments] == [
        "Ironside, Indigo",
        "Priya Holloway",
        "Ironside, Indigo",
    ]
    assert [segment.start_ms for segment in parsed.segments] == [1000, 7000, 11000]


def test_the_converted_vtt_carries_timing_and_never_a_speaker(
    tmp_path: Path, workspace: Path
) -> None:
    """A drop's VTT is a speaker-less subtitle track (AD-13); so is this one."""
    source = tmp_path / "sync.vtt"
    source.write_text(ZOOM_VTT, encoding="utf-8")

    parsed = transcripts.parse_vtt(
        written(convert(source, workspace), ".vtt").read_text(encoding="utf-8")
    )

    assert parsed.segment_count == 4
    assert all(segment.speaker_label is None for segment in parsed.segments)
    assert [segment.end_ms for segment in parsed.segments] == [4120, 7000, 11250, 15000]
    assert "Ironside" not in "".join(segment.text for segment in parsed.segments)


def test_consecutive_cues_by_one_speaker_become_one_turn(
    tmp_path: Path, workspace: Path
) -> None:
    """A turn is what one person said before somebody else spoke."""
    source = tmp_path / "sync.vtt"
    source.write_text(
        vtt(
            ("00:00:01.000", "00:00:02.000", "Alice Chen: One."),
            ("00:00:02.000", "00:00:03.000", "Alice Chen: Two."),
            ("00:00:03.000", "00:00:04.000", "Alice Chen: Three."),
        ),
        encoding="utf-8",
    )

    text = written(convert(source, workspace), ".txt").read_text(encoding="utf-8")

    assert text == "Alice Chen | 00:01\nOne. Two. Three.\n"


def test_a_cue_with_no_recognised_prefix_never_inherits_the_previous_speaker(
    tmp_path: Path, workspace: Path
) -> None:
    """A wrong attribution is worse than an absent one: it becomes Unknown."""
    source = tmp_path / "sync.vtt"
    source.write_text(
        vtt(
            ("00:00:01.000", "00:00:02.000", "Alice Chen: Morning."),
            ("00:00:02.000", "00:00:03.000", "and then the build broke"),
        ),
        encoding="utf-8",
    )

    parsed = transcripts.parse_text_transcript(
        written(convert(source, workspace), ".txt").read_text(encoding="utf-8")
    )

    assert [segment.speaker_label for segment in parsed.segments] == [
        "Alice Chen",
        transcripts.UNKNOWN_SPEAKER,
    ]
    # And the label the conversion chose is one the resolver already refuses to
    # turn into a person.
    assert speakers.is_placeholder_label(transcripts.UNKNOWN_SPEAKER)


def test_only_the_first_payload_line_can_supply_a_speaker(
    tmp_path: Path, workspace: Path
) -> None:
    source = tmp_path / "sync.vtt"
    source.write_text(
        "WEBVTT\n\n"
        "00:00:01.000 --> 00:00:02.000\n"
        "Good morning\n"
        "Alice Chen: this remains speech\n\n"
        "00:00:03.000 --> 00:00:04.000\n"
        "Bob Smith: Named cue.\n",
        encoding="utf-8",
    )

    parsed = transcripts.parse_text_transcript(
        written(convert(source, workspace), ".txt").read_text(encoding="utf-8")
    )

    assert [segment.speaker_label for segment in parsed.segments] == [
        transcripts.UNKNOWN_SPEAKER,
        "Bob Smith",
    ]
    assert parsed.segments[0].text == "Good morning Alice Chen: this remains speech"


def test_a_speaker_prefix_does_not_require_space_after_the_colon(
    tmp_path: Path, workspace: Path
) -> None:
    source = tmp_path / "sync.vtt"
    source.write_text(
        vtt(("00:00:01.000", "00:00:02.000", "Alice Chen:Morning.")),
        encoding="utf-8",
    )

    parsed = transcripts.parse_text_transcript(
        written(convert(source, workspace), ".txt").read_text(encoding="utf-8")
    )

    assert parsed.segments[0].speaker_label == "Alice Chen"
    assert parsed.segments[0].text == "Morning."


def test_a_prose_colon_is_not_read_as_a_speaker(
    tmp_path: Path, workspace: Path
) -> None:
    """`Right. So: here we go` is a sentence, and the words are kept whole."""
    source = tmp_path / "sync.vtt"
    source.write_text(
        vtt(
            ("00:00:01.000", "00:00:02.000", "Alice Chen: Morning."),
            ("00:00:05.000", "00:00:06.000", "Right. So: here we go."),
        ),
        encoding="utf-8",
    )

    parsed = transcripts.parse_text_transcript(
        written(convert(source, workspace), ".txt").read_text(encoding="utf-8")
    )

    assert parsed.segments[1].speaker_label == transcripts.UNKNOWN_SPEAKER
    assert parsed.segments[1].text == "Right. So: here we go."


def test_a_prefix_longer_than_a_name_is_not_read_as_a_speaker(
    tmp_path: Path, workspace: Path
) -> None:
    """Seven tokens before a colon is a clause, not a person."""
    speaker, spoken = dialects._split_speaker(
        "and then the whole team said this at once: we should ship it"
    )
    assert speaker is None
    assert spoken.startswith("and then the whole team")


def test_a_cue_whose_prefix_has_no_words_behind_it_is_skipped(
    tmp_path: Path, workspace: Path
) -> None:
    """`Alice Chen:` with nothing behind it is not evidence of anything."""
    source = tmp_path / "sync.vtt"
    source.write_text(
        vtt(
            ("00:00:01.000", "00:00:02.000", "Alice Chen:"),
            ("00:00:03.000", "00:00:04.000", "Alice Chen: Actually, morning."),
        ),
        encoding="utf-8",
    )

    conversion = convert(source, workspace)

    assert written(conversion, ".txt").read_text(encoding="utf-8") == (
        "Alice Chen | 00:03\nActually, morning.\n"
    )
    assert conversion.provenance_extra[dialects.PROVENANCE_KEY]["cueCount"] == 1


def test_markup_is_stripped_before_the_speaker_is_read(
    tmp_path: Path, workspace: Path
) -> None:
    source = tmp_path / "sync.vtt"
    source.write_text(
        vtt(("00:00:01.000", "00:00:02.000", "<b>Alice Chen</b>: <i>Morning.</i>")),
        encoding="utf-8",
    )

    assert written(convert(source, workspace), ".txt").read_text(
        encoding="utf-8"
    ) == "Alice Chen | 00:01\nMorning.\n"


def test_past_the_hour_the_block_stamp_switches_to_hours(
    tmp_path: Path, workspace: Path
) -> None:
    """The corpus's own shape: `08:47` early, `01:57:24` late (field count)."""
    source = tmp_path / "sync.vtt"
    source.write_text(
        vtt(
            ("00:08:47.000", "00:08:49.000", "Alice Chen: Early."),
            ("01:57:24.800", "01:57:26.000", "Bo Wren: Late."),
        ),
        encoding="utf-8",
    )

    text = written(convert(source, workspace), ".txt").read_text(encoding="utf-8")

    assert "Alice Chen | 08:47" in text
    assert "Bo Wren | 01:57:24" in text
    parsed = transcripts.parse_text_transcript(text)
    # Truncated, never rounded: 01:57:24.800 is not 01:57:25.
    assert [segment.start_ms for segment in parsed.segments] == [527000, 7044000]


def test_the_conversion_is_deterministic(tmp_path: Path, workspace: Path) -> None:
    """Identity of a transcript-only drop is the converted bytes' digest."""
    source = tmp_path / "sync.vtt"
    source.write_text(ZOOM_VTT, encoding="utf-8")
    second = tmp_path / "second"
    second.mkdir()

    first_run = written(convert(source, workspace), ".txt").read_bytes()
    second_run = written(convert(source, second), ".txt").read_bytes()

    assert first_run == second_run


# --- what it refuses -------------------------------------------------------


def test_a_speakerless_export_declared_zoom_is_refused(
    tmp_path: Path, workspace: Path
) -> None:
    """Declaring a Teams VTT `zoom` would mint a speaker-less transcript."""
    source = tmp_path / "sync.vtt"
    source.write_text(
        vtt(("00:00:01.000", "00:00:02.000", "morning all")), encoding="utf-8"
    )

    with pytest.raises(dialects.DialectError) as refusal:
        convert(source, workspace)

    assert "teams-vtt" in str(refusal.value)
    assert list(workspace.iterdir()) == []


def test_a_file_that_is_not_webvtt_is_refused(
    tmp_path: Path, workspace: Path
) -> None:
    source = tmp_path / "sync.vtt"
    source.write_text("Ironside, Indigo | 00:00\nmorning all\n", encoding="utf-8")

    with pytest.raises(dialects.DialectError) as refusal:
        convert(source, workspace)

    assert "WEBVTT" in str(refusal.value)


def test_a_malformed_timing_line_is_refused_naming_the_line(
    tmp_path: Path, workspace: Path
) -> None:
    """The pipeline skips a bad cue; here the cues *are* the words."""
    source = tmp_path / "sync.vtt"
    source.write_text(
        "WEBVTT\n\n1\n00:00:01.000 --> half past two\nAlice Chen: Morning.\n",
        encoding="utf-8",
    )

    with pytest.raises(dialects.DialectError) as refusal:
        convert(source, workspace)

    assert "line 4" in str(refusal.value)


def test_a_single_arrow_timing_line_is_refused_instead_of_dropped(
    tmp_path: Path, workspace: Path
) -> None:
    """The frozen malformed-line example must not disappear before validation."""
    source = tmp_path / "sync.vtt"
    source.write_text(
        "WEBVTT\n\n"
        "00:00:01.000 -> bad\n"
        "Alice Chen: This evidence must not disappear.\n\n"
        "00:00:03.000 --> 00:00:04.000\n"
        "Bob Smith: A later valid cue must not hide the error.\n",
        encoding="utf-8",
    )

    with pytest.raises(dialects.DialectError) as refusal:
        convert(source, workspace)

    assert "line 3" in str(refusal.value)
    assert list(workspace.iterdir()) == []


def test_a_reverse_cue_timing_is_refused(
    tmp_path: Path, workspace: Path
) -> None:
    source = tmp_path / "sync.vtt"
    source.write_text(
        vtt(("00:00:03.000", "00:00:01.000", "Alice Chen: Morning.")),
        encoding="utf-8",
    )

    with pytest.raises(dialects.DialectError) as refusal:
        convert(source, workspace)

    assert "ends before it starts" in str(refusal.value)
    assert "line 3" in str(refusal.value)


def test_a_missing_cue_separator_is_refused(
    tmp_path: Path, workspace: Path
) -> None:
    source = tmp_path / "sync.vtt"
    source.write_text(
        "WEBVTT\n\n"
        "00:00:01.000 --> 00:00:02.000\n"
        "Alice Chen: First cue.\n"
        "00:00:03.000 --> 00:00:04.000\n"
        "Bob Smith: Second cue.\n",
        encoding="utf-8",
    )

    with pytest.raises(dialects.DialectError) as refusal:
        convert(source, workspace)

    assert "separator" in str(refusal.value)
    assert "line 5" in str(refusal.value)


def test_out_of_order_cues_are_refused(
    tmp_path: Path, workspace: Path
) -> None:
    source = tmp_path / "sync.vtt"
    source.write_text(
        vtt(
            ("00:00:05.000", "00:00:06.000", "Alice Chen: Later."),
            ("00:00:01.000", "00:00:02.000", "Bob Smith: Earlier."),
        ),
        encoding="utf-8",
    )

    with pytest.raises(dialects.DialectError) as refusal:
        convert(source, workspace)

    assert "out of order" in str(refusal.value)
    assert "line 6" in str(refusal.value)


@pytest.mark.parametrize(
    "content",
    [
        "WEBVTT-NOT-A-HEADER\n\n00:00:01.000 --> 00:00:02.000\nAlice: Hi.\n",
        "WEBVTT\n\n00:00:01. --> 00:00:02.\nAlice: Hi.\n",
    ],
)
def test_malformed_webvtt_signatures_and_stamps_are_refused(
    tmp_path: Path, workspace: Path, content: str
) -> None:
    source = tmp_path / "sync.vtt"
    source.write_text(content, encoding="utf-8")

    with pytest.raises(dialects.DialectError):
        convert(source, workspace)


def test_an_utterance_shaped_like_a_legacy_header_is_refused(
    tmp_path: Path, workspace: Path
) -> None:
    """The self-check: the pipeline's parser reads what was written.

    ` | ` inside an utterance turns that line into a header candidate with an
    unparseable stamp, which fails the `align` stage for the whole meeting.
    A drop is write-once, so this must refuse instead.
    """
    source = tmp_path / "sync.vtt"
    source.write_text(
        vtt(("00:00:01.000", "00:00:02.000", "Alice Chen: try grep | wc next time")),
        encoding="utf-8",
    )

    with pytest.raises(dialects.DialectError) as refusal:
        convert(source, workspace)

    assert "does not parse" in str(refusal.value)


def test_an_empty_export_is_refused(tmp_path: Path, workspace: Path) -> None:
    source = tmp_path / "sync.vtt"
    source.write_text("   \n\n", encoding="utf-8")

    with pytest.raises(dialects.DialectError):
        convert(source, workspace)


def test_a_webvtt_with_no_cue_text_is_refused(
    tmp_path: Path, workspace: Path
) -> None:
    source = tmp_path / "sync.vtt"
    source.write_text("WEBVTT\n\n1\n00:00:01.000 --> 00:00:02.000\n", encoding="utf-8")

    with pytest.raises(dialects.DialectError) as refusal:
        convert(source, workspace)

    assert "nothing to" in str(refusal.value)


def test_bytes_that_are_not_utf8_are_refused(
    tmp_path: Path, workspace: Path
) -> None:
    """Replacement characters would be carried into a write-once drop."""
    source = tmp_path / "sync.vtt"
    source.write_bytes(b"WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nAlice: \xff\xfe\n")

    with pytest.raises(dialects.DialectError) as refusal:
        convert(source, workspace)

    assert "UTF-8" in str(refusal.value)


# --- choosing a dialect ----------------------------------------------------


def test_plain_passes_everything_through_and_records_nothing(
    tmp_path: Path, workspace: Path
) -> None:
    """The default is today's behaviour, bit for bit."""
    conversion = dialects.convert_supplied(
        ["a.mp4", "b.vtt", "c.txt"],
        dialect=dialects.DEFAULT_DIALECT,
        into=workspace,
    )

    assert dialects.DEFAULT_DIALECT == "plain"
    assert conversion.supplied == ["a.mp4", "b.vtt", "c.txt"]
    assert conversion.provenance_extra is None
    assert list(workspace.iterdir()) == []


def test_teams_vtt_passes_through_and_records_the_declaration(
    workspace: Path,
) -> None:
    """A Teams export already is the trusted format; this only says so."""
    conversion = dialects.convert_supplied(
        ["a.txt", "b.vtt"], dialect=dialects.DIALECT_TEAMS_VTT, into=workspace
    )

    assert conversion.supplied == ["a.txt", "b.vtt"]
    assert conversion.provenance_extra == {
        dialects.PROVENANCE_KEY: {"dialect": "teams-vtt", "converted": False}
    }
    assert list(workspace.iterdir()) == []


def test_a_dialect_is_never_inferred_from_content(
    tmp_path: Path, workspace: Path
) -> None:
    """The very same Zoom file, undeclared, is passed through untouched."""
    source = tmp_path / "sync.vtt"
    source.write_text(ZOOM_VTT, encoding="utf-8")

    conversion = dialects.convert_supplied(
        [str(source)], dialect=dialects.DIALECT_PLAIN, into=workspace
    )

    assert conversion.supplied == [str(source)]
    assert conversion.provenance_extra is None
    assert list(workspace.iterdir()) == []


def test_zoom_with_no_vtt_supplied_is_refused(workspace: Path) -> None:
    with pytest.raises(dialects.DialectError) as refusal:
        dialects.convert_supplied(
            ["recording.mp4"], dialect=dialects.DIALECT_ZOOM, into=workspace
        )

    assert "none was supplied" in str(refusal.value)


def test_zoom_with_a_text_transcript_as_well_is_refused(
    tmp_path: Path, workspace: Path
) -> None:
    """The conversion produces the `.txt`; a drop holds one of each."""
    source = tmp_path / "sync.vtt"
    source.write_text(ZOOM_VTT, encoding="utf-8")
    other = tmp_path / "sync.txt"
    other.write_text("[0:00] Alice Chen: morning\n", encoding="utf-8")

    with pytest.raises(dialects.DialectError) as refusal:
        dialects.convert_supplied(
            [str(source), str(other)], dialect=dialects.DIALECT_ZOOM, into=workspace
        )

    assert "one of each" in str(refusal.value)


def test_two_vtt_files_are_refused(tmp_path: Path, workspace: Path) -> None:
    with pytest.raises(dialects.DialectError) as refusal:
        dialects.convert_supplied(
            ["one.vtt", "two.vtt"], dialect=dialects.DIALECT_ZOOM, into=workspace
        )

    assert "two .vtt files" in str(refusal.value)


def test_a_missing_zoom_source_is_refused(tmp_path: Path, workspace: Path) -> None:
    with pytest.raises(dialects.DialectError) as refusal:
        dialects.convert_supplied(
            [str(tmp_path / "gone.vtt")], dialect=dialects.DIALECT_ZOOM, into=workspace
        )

    assert "does not exist" in str(refusal.value)


def test_an_unknown_dialect_is_refused_by_name(workspace: Path) -> None:
    with pytest.raises(dialects.DialectError) as refusal:
        dialects.convert_supplied(["a.vtt"], dialect="webex", into=workspace)

    assert "unknown transcript dialect" in str(refusal.value)


# --- through the command ---------------------------------------------------


def test_a_zoom_mint_holds_both_transcripts_and_records_the_dialect(
    mint_root: Path, zoom: Path, no_http, capsys
) -> None:
    """Acceptance, end to end: one supplied `.vtt`, two files in the drop."""
    code = run(
        mint_root,
        str(zoom),
        "--corpus", "scripted",
        "--transcript-dialect", "zoom",
        "--started-at", "2026-08-05T12:00:19Z",
    )
    assert code == 0

    drop = only_drop(mint_root)
    assert sorted(path.name for path in drop.iterdir()) == [
        "metadata.json",
        "transcript.txt",
        "transcript.vtt",
    ]
    metadata = read_drop_metadata(drop)
    record = metadata["provenance"][dialects.PROVENANCE_KEY]
    assert record["dialect"] == "zoom"
    assert record["source"]["sourcePath"] == str(zoom.resolve())
    assert record["speakerLabels"] == ["Ironside, Indigo", "Priya Holloway"]
    # The defaults story 6.2's override path is layered over are untouched.
    assert metadata["provenance"]["tool"] == "mint-drop"
    assert metadata["startedAt"] == "2026-08-05T12:00:19Z"
    # The title default is the operator's file, not the workspace's.
    assert metadata["provenance"]["title"] == "Migration Sync"
    assert "created" in capsys.readouterr().out


def test_a_plain_mint_records_no_dialect_at_all(
    mint_root: Path, zoom: Path, no_http
) -> None:
    """`plain` is the existing behaviour: the key is absent, not false."""
    assert run(
        mint_root,
        str(zoom),
        "--corpus", "scripted",
        "--started-at", "2026-08-05T12:00:19Z",
    ) == 0

    metadata = read_drop_metadata(only_drop(mint_root))
    assert dialects.PROVENANCE_KEY not in metadata["provenance"]
    assert sorted(p.name for p in only_drop(mint_root).iterdir()) == [
        "metadata.json",
        "transcript.vtt",
    ]


def test_a_teams_vtt_mint_records_the_declaration_and_converts_nothing(
    mint_root: Path, tmp_path: Path, no_http
) -> None:
    text = tmp_path / "Team Sync.txt"
    text.write_text(TEAMS_TEXT + f"[9:59] Bo Wren: {tmp_path.name}\n", encoding="utf-8")
    track = tmp_path / "Team Sync.vtt"
    track.write_text(
        vtt(("00:00:01.000", "00:00:03.000", "Good morning everyone.")),
        encoding="utf-8",
    )

    assert run(
        mint_root,
        str(text),
        str(track),
        "--corpus", "scripted",
        "--transcript-dialect", "teams-vtt",
        "--started-at", "2026-08-05T12:00:19Z",
    ) == 0

    drop = only_drop(mint_root)
    metadata = read_drop_metadata(drop)
    assert metadata["provenance"][dialects.PROVENANCE_KEY] == {
        "dialect": "teams-vtt",
        "converted": False,
    }
    assert (drop / "transcript.txt").read_bytes() == text.read_bytes()
    assert (drop / "transcript.vtt").read_bytes() == track.read_bytes()


def test_a_rerun_on_the_same_zoom_export_reports_exists(
    mint_root: Path, zoom: Path, no_http, capsys
) -> None:
    """Deterministic conversion is what makes the second run a no-op."""
    common = ("--corpus", "scripted", "--transcript-dialect", "zoom",
              "--started-at", "2026-08-05T12:00:19Z")
    assert run(mint_root, str(zoom), *common) == 0
    capsys.readouterr()

    assert run(mint_root, str(zoom), *common) == 0

    assert "exists" in capsys.readouterr().out
    assert len([p for p in mint_root.iterdir() if not p.name.startswith(".")]) == 1


def test_a_refused_conversion_writes_no_drop(
    mint_root: Path, tmp_path: Path, no_http, capsys
) -> None:
    source = tmp_path / "sync.vtt"
    source.write_text(
        vtt(("00:00:01.000", "00:00:02.000", "morning all")), encoding="utf-8"
    )

    code = run(
        mint_root,
        str(source),
        "--corpus", "scripted",
        "--transcript-dialect", "zoom",
        "--started-at", "2026-08-05T12:00:19Z",
    )

    assert code == 1
    assert "refused" in capsys.readouterr().err
    assert [p for p in mint_root.iterdir() if not p.name.startswith(".")] == []


def test_the_parser_refuses_a_dialect_it_does_not_know(zoom: Path) -> None:
    with pytest.raises(SystemExit) as exit_code:
        mintdrop.main([str(zoom), "--corpus", "scripted",
                       "--transcript-dialect", "webex"])

    assert exit_code.value.code == 2


# --- the third acceptance clause: align, unchanged -------------------------


def test_align_resolves_zoom_names_through_the_roster_exactly_as_teams_labels(
    mint_root: Path, zoom: Path, no_http
) -> None:
    """The whole point of converting at acquisition.

    This is the `align` stage's own code path for a drop with no participant
    graph — `pipeline/transcripts.py` to read the file, then
    `pipeline/speakers.py`'s roster and resolver — run over the minted drop.
    Neither module is touched by this story.
    """
    assert run(
        mint_root,
        str(zoom),
        "--corpus", "scripted",
        "--transcript-dialect", "zoom",
        "--started-at", "2026-08-05T12:00:19Z",
    ) == 0
    drop = only_drop(mint_root)

    parsed = transcripts.parse_text_transcript(
        (drop / "transcript.txt").read_text(encoding="utf-8")
    )
    roster = speakers.roster_from_labels(
        [segment.speaker_label for segment in parsed.segments]
    )
    resolutions = [
        speakers.resolve_label(segment.speaker_label, roster)
        for segment in parsed.segments
    ]

    assert roster == ("indigo ironside", "priya holloway")
    assert [resolution.status for resolution in resolutions] == [
        speakers.RESOLVED,
        speakers.RESOLVED,
        speakers.RESOLVED,
    ]
    assert [resolution.match_key for resolution in resolutions] == [
        "indigo ironside",
        "priya holloway",
        "indigo ironside",
    ]

    # The same people, spelled as Teams spells them, land on the same keys —
    # which is what "resolves exactly as Teams labels resolve" means.
    teams = transcripts.parse_text_transcript(TEAMS_TEXT)
    assert teams.format == transcripts.FORMAT_TEAMS
    assert [
        speakers.resolve_label(segment.speaker_label, roster).match_key
        for segment in teams.segments
    ] == ["indigo ironside", "priya holloway"]


def test_a_zoom_label_resolves_against_a_drop_graph_roster_too(
    tmp_path: Path, workspace: Path
) -> None:
    """The other roster source: match keys from the drop's participant graph."""
    source = tmp_path / "sync.vtt"
    source.write_text(ZOOM_VTT, encoding="utf-8")
    parsed = transcripts.parse_text_transcript(
        written(convert(source, workspace), ".txt").read_text(encoding="utf-8")
    )
    graph_roster = tuple(
        speakers.normalize_display_name(name)
        for name in ("Ironside, Indigo", "Holloway, Priya", "Wren, Bo")
    )

    resolutions = [
        speakers.resolve_label(segment.speaker_label, graph_roster)
        for segment in parsed.segments
    ]

    assert [resolution.match_key for resolution in resolutions] == [
        "indigo ironside",
        "priya holloway",
        "indigo ironside",
    ]


def test_the_converted_vtt_gives_each_turn_its_real_end(
    tmp_path: Path, workspace: Path
) -> None:
    """The `.vtt` half earns its place: `align` takes turn ends from it.

    Run through `pipeline/alignment.py`'s own `merge_vtt_end_timings`, so the
    assertion is about the aligner's behaviour rather than about the file.
    """
    source = tmp_path / "sync.vtt"
    source.write_text(ZOOM_VTT, encoding="utf-8")
    conversion = convert(source, workspace)
    turns = transcripts.parse_text_transcript(
        written(conversion, ".txt").read_text(encoding="utf-8")
    )
    cues = transcripts.parse_vtt(
        written(conversion, ".vtt").read_text(encoding="utf-8")
    )

    ends = merge_vtt_end_timings(
        tuple(
            TimedText(start_ms=s.start_ms, end_ms=s.end_ms, text=s.text)
            for s in turns.segments
        ),
        tuple(
            TimedText(start_ms=c.start_ms, end_ms=c.end_ms, text=c.text)
            for c in cues.segments
        ),
        ALIGN,
    )

    # Turn one spans two cues and ends where the later one does; every turn
    # gets a real end rather than the next turn's start.
    assert ends == (7000, 11250, 15000)
