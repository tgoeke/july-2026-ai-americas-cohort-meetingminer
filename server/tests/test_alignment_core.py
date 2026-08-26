"""The aligner: anchor window, match floor, VTT end timings, and the empty lanes.

Deterministic code, so these run without Postgres, ffmpeg, or an STT engine —
which is exactly the property AD-13 needs, since alignment is evidence and
evidence is never model-written.
"""

from __future__ import annotations

import pytest

from meetingminer.config import AlignConfig
from meetingminer.pipeline.alignment import (
    TimedText,
    align_segments,
    merge_vtt_end_timings,
    resolve_end_times,
)

CONFIG = AlignConfig(anchor_window_seconds=2.0, min_match_score=0.35, max_segment_ms=60_000)


def seg(start_ms: int, text: str, end_ms: int | None = None) -> TimedText:
    return TimedText(start_ms=start_ms, end_ms=end_ms, text=text)


# --- anchoring -------------------------------------------------------------


def test_a_match_inside_the_anchor_window_records_a_signed_delta() -> None:
    provided = [seg(27_000, "Everybody, good morning.")]
    stt = [seg(27_702, "everybody good morning", 28_662)]
    [match] = align_segments(provided, stt, CONFIG)
    assert match.matched
    assert match.stt_index == 0
    assert match.stt_start_ms == 27_702
    assert match.delta_ms == 702
    assert match.match_score == pytest.approx(1.0)


def test_a_negative_delta_is_kept_signed() -> None:
    [match] = align_segments([seg(30_000, "morning all")], [seg(28_500, "morning all")], CONFIG)
    assert match.delta_ms == -1_500


def test_a_candidate_outside_the_window_is_left_unmatched() -> None:
    """Same words, five seconds away: never snapped to the nearest segment."""
    [match] = align_segments([seg(27_000, "good morning")], [seg(32_000, "good morning")], CONFIG)
    assert not match.matched
    assert (match.stt_index, match.stt_start_ms, match.delta_ms, match.match_score) == (
        None, None, None, None,
    )


def test_a_pair_below_the_match_floor_is_left_unmatched() -> None:
    [match] = align_segments(
        [seg(10_000, "the revenue slide for the third quarter")],
        [seg(10_100, "completely different words entirely")],
        CONFIG,
    )
    assert not match.matched


def test_the_best_scoring_candidate_in_the_window_wins() -> None:
    provided = [seg(10_000, "let us walk the revenue slide")]
    stt = [seg(9_000, "let us walk"), seg(10_200, "let us walk the revenue slide")]
    [match] = align_segments(provided, stt, CONFIG)
    assert match.stt_index == 1


def test_one_stt_segment_may_anchor_two_provided_turns() -> None:
    """Recognizer segmentation and turn segmentation genuinely disagree."""
    provided = [seg(1_000, "good morning"), seg(1_500, "good morning")]
    matches = align_segments(provided, [seg(1_100, "good morning")], CONFIG)
    assert [m.stt_index for m in matches] == [0, 0]


def test_a_provided_only_lane_yields_one_unmatched_record_per_turn() -> None:
    """A transcript-only drop: every row is honest about having no anchor."""
    matches = align_segments([seg(0, "hello"), seg(1_000, "again")], [], CONFIG)
    assert len(matches) == 2
    assert not any(match.matched for match in matches)


def test_an_stt_only_lane_yields_nothing_to_anchor() -> None:
    assert align_segments([], [seg(0, "hello")], CONFIG) == ()


# --- VTT end timings -------------------------------------------------------


def test_a_matching_vtt_cue_supplies_the_real_end() -> None:
    provided = [seg(27_000, "Everybody, good morning."), seg(30_000, "Morning.")]
    cues = [seg(27_702, "Everybody, good morning.", 28_662), seg(30_022, "Morning.", 30_662)]
    assert merge_vtt_end_timings(provided, cues, CONFIG) == (28_662, 30_662)


def test_a_turn_spanning_several_cues_ends_at_the_last_of_them() -> None:
    provided = [seg(10_000, "first part second part"), seg(20_000, "later")]
    cues = [
        seg(10_100, "first part second part", 11_000),
        seg(11_100, "first part second part again", 12_400),
    ]
    assert merge_vtt_end_timings(provided, cues, CONFIG)[0] == 12_400


def test_a_turn_no_cue_matches_gets_no_vtt_end() -> None:
    provided = [seg(10_000, "nothing like the cue text at all")]
    cues = [seg(10_100, "entirely unrelated wording", 11_000)]
    assert merge_vtt_end_timings(provided, cues, CONFIG) == (None,)


# --- resolved ends ---------------------------------------------------------


def test_without_a_vtt_a_turn_ends_where_the_next_begins() -> None:
    provided = [seg(0, "one"), seg(5_000, "two")]
    assert resolve_end_times(provided, (None, None), CONFIG) == (5_000, 65_000)


def test_the_vtt_end_wins_over_the_next_turns_start() -> None:
    """Overlapping speech is real, and the cue measured it."""
    provided = [seg(0, "one"), seg(5_000, "two")]
    assert resolve_end_times(provided, (5_400, None), CONFIG) == (5_400, 65_000)


def test_a_long_gap_is_capped_by_max_segment_ms() -> None:
    tight = AlignConfig(anchor_window_seconds=2.0, min_match_score=0.35, max_segment_ms=3_000)
    provided = [seg(0, "one"), seg(600_000, "two")]
    assert resolve_end_times(provided, (None, None), tight) == (3_000, 603_000)


def test_a_segment_that_already_carries_an_end_keeps_it() -> None:
    """VTT-only drops arrive with both ends already measured."""
    provided = [seg(0, "one", 900), seg(5_000, "two", 5_800)]
    assert resolve_end_times(provided, (None, None), CONFIG) == (900, 5_800)
