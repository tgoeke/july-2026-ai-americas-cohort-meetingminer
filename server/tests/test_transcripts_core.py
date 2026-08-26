"""Parsing both transcript lineages: the story 1.5 I/O matrix's parsing rows.

Pure-function tests — no Postgres, no drop on disk, no engine — because that
is the point of :mod:`meetingminer.pipeline.transcripts`: every rule the real
corpus forced is checkable on its own.
"""

from __future__ import annotations

import pytest

from meetingminer.pipeline.transcripts import (
    FORMAT_LEGACY,
    FORMAT_TEAMS,
    FORMAT_VTT,
    TranscriptParseError,
    detect_text_format,
    parse_legacy_text,
    parse_teams_text,
    parse_text_transcript,
    parse_timestamp,
    parse_vtt,
)

# Verbatim line shapes from the two transcript lineages the parser accepts.
TEAMS = (
    "[0:27] Goeke, Timothy: Everybody, good morning.\n"
    "[0:30] oakleylangmere: Hey, good morning, everyone.\n"
    "[2:33] Dunmore, Tobin (CNTR): Ohh, I think we can get started: what do you think?\n"
    "[1:00:16] Calloway, Frankie Sage: Past the hour now.\n"
)

LEGACY = (
    "Stonebridge, Finley started transcription\n"
    "\n"
    "Ironside, Indigo | 00:00\n"
    "Starting. Okay, perfect.\n"
    "So welcome, everyone.\n"
    "\n"
    "Kendall | 08:47\n"
    "Quick question on that.\n"
    "\n"
    "Speaker 8 | 01:00:20\n"
    "Past the hour now.\n"
)


# --- timestamps: parsed by field count -------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("00:00", 0),
        ("08:47", 527_000),
        ("0:27", 27_000),
        ("01:57:24", 7_044_000),
        ("1:00:16", 3_616_000),
        ("00:00:27.702", 27_702),
        ("00:00:27,702", 27_702),
    ],
)
def test_timestamps_are_parsed_by_field_count(raw: str, expected: int) -> None:
    assert parse_timestamp(raw) == expected


def test_malformed_timestamp_names_the_line() -> None:
    with pytest.raises(TranscriptParseError, match="line 4"):
        parse_timestamp("1:2:3:4", line_number=4)
    with pytest.raises(TranscriptParseError, match="not numeric"):
        parse_timestamp("ab:cd")


@pytest.mark.parametrize("raw", ["60:00", "00:60", "01:60:00", "01:00:60"])
def test_timestamp_clock_components_must_be_in_range(raw: str) -> None:
    with pytest.raises(TranscriptParseError, match="outside their valid ranges"):
        parse_timestamp(raw)


# --- format detection ------------------------------------------------------


def test_detect_text_format_distinguishes_the_two_lineages() -> None:
    assert detect_text_format(TEAMS) == FORMAT_TEAMS
    assert detect_text_format(LEGACY) == FORMAT_LEGACY
    assert detect_text_format("just some prose\nwith no timestamps\n") is None


def test_unrecognized_file_is_a_parse_error_not_a_silent_skip() -> None:
    with pytest.raises(TranscriptParseError, match="matches either transcript lineage"):
        parse_text_transcript("just some prose\nwith no timestamps\n")


def test_empty_file_is_zero_turns_not_a_failure() -> None:
    assert parse_text_transcript("   \n\n").segments == ()


# --- the Teams lineage -----------------------------------------------------


def test_teams_lineage_keeps_labels_verbatim_and_switches_form_past_the_hour() -> None:
    parsed = parse_teams_text(TEAMS)
    assert parsed.format == FORMAT_TEAMS
    assert [s.speaker_label for s in parsed.segments] == [
        "Goeke, Timothy",
        "oakleylangmere",
        "Dunmore, Tobin (CNTR)",
        "Calloway, Frankie Sage",
    ]
    assert [s.start_ms for s in parsed.segments] == [27_000, 30_000, 153_000, 3_616_000]
    assert [s.ordinal for s in parsed.segments] == [1, 2, 3, 4]
    # A label containing a comma splits on the *first* colon after the bracket,
    # so a colon inside the utterance stays in the utterance.
    assert parsed.segments[2].text == "Ohh, I think we can get started: what do you think?"
    # Neither text lineage records an end.
    assert all(s.end_ms is None for s in parsed.segments)


def test_teams_line_with_no_timestamp_continues_the_turn_above_it() -> None:
    parsed = parse_teams_text("[0:01] Cameron: first part\nwrapped continuation\n[0:09] Cameron: next\n")
    assert len(parsed.segments) == 2
    assert parsed.segments[0].text == "first part wrapped continuation"


def test_teams_line_with_no_colon_has_no_speaker_label() -> None:
    parsed = parse_teams_text("[0:01] no attribution here\n")
    assert parsed.segments[0].speaker_label is None
    assert parsed.segments[0].text == "no attribution here"


def test_teams_malformed_stamp_names_the_line() -> None:
    with pytest.raises(TranscriptParseError, match="line 2"):
        parse_teams_text("[0:01] Cameron: fine\n[1:2:3:4] Cameron: broken\n")


def test_teams_non_numeric_bracketed_header_is_not_continuation_text() -> None:
    with pytest.raises(TranscriptParseError, match="line 2"):
        parse_teams_text("[0:01] Cameron: fine\n[broken] Cameron: not speech\n")


def test_teams_text_before_the_first_turn_is_a_named_error() -> None:
    with pytest.raises(TranscriptParseError, match="line 1.*before the first"):
        parse_teams_text("Export title\n[0:01] Cameron: actual speech\n")


# --- the legacy lineage ----------------------------------------------------


def test_legacy_lineage_skips_the_preamble_and_joins_multi_line_blocks() -> None:
    parsed = parse_legacy_text(LEGACY)
    assert parsed.format == FORMAT_LEGACY
    assert [s.speaker_label for s in parsed.segments] == [
        "Ironside, Indigo",
        "Kendall",
        "Speaker 8",
    ]
    assert [s.start_ms for s in parsed.segments] == [0, 527_000, 3_620_000]
    # The `started transcription` line is not a speaker block, and the two body
    # lines of the first block become one utterance.
    assert parsed.segments[0].text == "Starting. Okay, perfect. So welcome, everyone."


def test_legacy_lineage_is_reached_through_the_dispatcher() -> None:
    assert parse_text_transcript(LEGACY).format == FORMAT_LEGACY
    assert parse_text_transcript(TEAMS).format == FORMAT_TEAMS


def test_legacy_malformed_header_is_not_attributed_as_body_text() -> None:
    with pytest.raises(TranscriptParseError, match="line 3.*expected MM:SS"):
        parse_legacy_text("Cameron | 00:01\nactual speech\nLisa | broken\n")


def test_legacy_text_before_the_first_turn_is_a_named_error() -> None:
    with pytest.raises(TranscriptParseError, match="line 1.*before the first"):
        parse_legacy_text("Export title\nKen | 00:01\nactual speech\n")


# --- the speaker-less VTT --------------------------------------------------


VTT = (
    "﻿WEBVTT\n"
    "\n"
    "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/13-0\n"
    "00:00:27.702 --> 00:00:28.662\n"
    "Everybody, good morning.\n"
    "\n"
    "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/14-0\n"
    "00:00:30.022 --> 00:00:30.662\n"
    "Morning.\n"
)


def test_vtt_supplies_cue_ends_and_never_a_speaker() -> None:
    parsed = parse_vtt(VTT)
    assert parsed.format == FORMAT_VTT
    assert [(s.start_ms, s.end_ms) for s in parsed.segments] == [
        (27_702, 28_662),
        (30_022, 30_662),
    ]
    assert [s.text for s in parsed.segments] == ["Everybody, good morning.", "Morning."]
    assert all(s.speaker_label is None for s in parsed.segments)


def test_vtt_voice_spans_are_stripped_rather_than_read_as_speakers() -> None:
    parsed = parse_vtt("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n<v Ellis>Hello there\n")
    assert parsed.segments[0].speaker_label is None
    assert parsed.segments[0].text == "Hello there"


def test_unparseable_vtt_yields_no_segments_rather_than_raising() -> None:
    """The `.txt` must still be usable when the VTT is junk."""
    assert parse_vtt("WEBVTT\n\nnot a cue at all\nnor this\n").segments == ()
    assert parse_vtt("").segments == ()
