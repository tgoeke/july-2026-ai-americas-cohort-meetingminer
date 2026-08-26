"""The `moments` decision core: the story 1.6 I/O matrix rows that need no DB.

Every rule here is a pure function over plain facts, so boundary computation,
coverage, screenshot selection and identity keys are all testable without
Postgres, ffmpeg or a model — which is also what keeps them from quietly
becoming a model call (AD-13).
"""

from __future__ import annotations

from uuid import UUID

import pytest

from meetingminer.config import MomentsConfig
from meetingminer.pipeline import moments as core

CONFIG = MomentsConfig(gap_seconds=20, max_duration_ms=180_000)


def uid(n: int) -> UUID:
    return UUID(int=n, version=4)


def segment(
    n: int, start_ms: int, end_ms: int | None = None, ordinal: int | None = None
) -> core.SegmentFacts:
    """A turn whose end defaults to its start, the way `align` synthesizes it."""
    return core.SegmentFacts(
        segment_id=uid(n),
        ordinal=n if ordinal is None else ordinal,
        start_ms=start_ms,
        end_ms=start_ms if end_ms is None else end_ms,
    )


def shot(n: int, start_offset_ms: int, end_offset_ms: int) -> core.ScreenshotFacts:
    return core.ScreenshotFacts(
        screenshot_id=uid(1000 + n),
        start_offset_ms=start_offset_ms,
        end_offset_ms=end_offset_ms,
    )


def starts(planned: tuple[core.PlannedMoment, ...]) -> list[int]:
    return [moment.start_ms for moment in planned]


# --- identity keys ---------------------------------------------------------


def test_identity_key_names_the_anchor_that_minted_the_moment() -> None:
    assert core.identity_key_for(core.DERIVED_TRANSCRIPT, 0) == "transcript:0"
    assert core.identity_key_for(core.DERIVED_SCREEN, 30_000) == "screen:30000"


def test_a_coincident_boundary_is_keyed_on_the_transcript_anchor() -> None:
    """`both` takes the transcript key: that is the key that survives 1.12."""
    assert core.identity_key_for(core.DERIVED_BOTH, 30_000) == "transcript:30000"


# --- transcript boundaries -------------------------------------------------


def test_the_first_segment_opens_the_first_moment() -> None:
    [boundary] = core.transcript_boundaries([segment(1, 2_000)], CONFIG)
    assert boundary == core.Boundary(2_000, core.BOUNDARY_FIRST_SEGMENT)


def test_a_silence_gap_longer_than_the_threshold_starts_a_new_moment() -> None:
    segments = [segment(1, 0), segment(2, 5_000), segment(3, 40_000)]
    boundaries = core.transcript_boundaries(segments, CONFIG)
    assert [(b.start_ms, b.reason) for b in boundaries] == [
        (0, core.BOUNDARY_FIRST_SEGMENT),
        (40_000, core.BOUNDARY_SILENCE_GAP),
    ]


def test_a_gap_exactly_at_the_threshold_does_not_split() -> None:
    """The rule is *more than* `gap_seconds`, so the boundary case stays whole."""
    segments = [segment(1, 0), segment(2, 20_000)]
    assert len(core.transcript_boundaries(segments, CONFIG)) == 1


def test_the_gap_is_measured_start_to_start_not_end_to_start() -> None:
    """`align` synthesizes ends, so end-to-start gaps carry no signal."""
    segments = [segment(1, 0, end_ms=60_000), segment(2, 30_000, end_ms=60_000)]
    boundaries = core.transcript_boundaries(segments, CONFIG)
    assert [b.reason for b in boundaries] == [
        core.BOUNDARY_FIRST_SEGMENT,
        core.BOUNDARY_SILENCE_GAP,
    ]


def test_an_unbroken_block_is_split_at_the_first_turn_past_the_cap() -> None:
    # Turns every 10s (never a gap) for well past the three-minute cap.
    segments = [segment(n, n * 10_000) for n in range(40)]
    boundaries = core.transcript_boundaries(segments, CONFIG)
    assert [(b.start_ms, b.reason) for b in boundaries] == [
        (0, core.BOUNDARY_FIRST_SEGMENT),
        (190_000, core.BOUNDARY_MAX_DURATION),
        (380_000, core.BOUNDARY_MAX_DURATION),
    ]


def test_the_duration_cap_is_measured_from_the_current_blocks_start() -> None:
    """A gap split restarts the clock; the cap is not absolute meeting time."""
    segments = [segment(1, 0), segment(2, 100_000)] + [
        segment(n, 100_000 + (n - 2) * 10_000) for n in range(3, 30)
    ]
    boundaries = core.transcript_boundaries(segments, CONFIG)
    assert [(b.start_ms, b.reason) for b in boundaries] == [
        (0, core.BOUNDARY_FIRST_SEGMENT),
        (100_000, core.BOUNDARY_SILENCE_GAP),
        (290_000, core.BOUNDARY_MAX_DURATION),
    ]


def test_no_segments_means_no_transcript_boundaries() -> None:
    assert core.transcript_boundaries([], CONFIG) == ()


# --- the union -------------------------------------------------------------


def test_adding_screenshots_does_not_move_a_single_transcript_boundary() -> None:
    """The invariant story 1.12 rests on: a recovered recording cannot re-key a
    moment minted before it arrived.

    Compared through :func:`plan_moments`, which is the function that *could*
    interleave the two boundary sets and shift the transcript anchors — calling
    :func:`transcript_boundaries` twice would only restate that a pure function
    is pure.
    """
    segments = [segment(1, 0), segment(2, 18_000), segment(3, 42_000), segment(4, 120_000)]
    screenshots = [shot(1, 30_000, 95_000), shot(2, 95_000, 160_000)]

    before = core.plan_moments(segments, [], CONFIG)
    after = core.plan_moments(segments, screenshots, CONFIG)

    def transcript_anchors(planned: tuple[core.PlannedMoment, ...]) -> list[tuple[str, int]]:
        return [
            (moment.identity_key, moment.start_ms)
            for moment in planned
            if moment.derived_from != core.DERIVED_SCREEN
        ]

    assert transcript_anchors(after) == transcript_anchors(before)
    assert transcript_anchors(before) == [
        ("transcript:0", 0),
        ("transcript:42000", 42_000),
        ("transcript:120000", 120_000),
    ]
    # The screenshots did land — the comparison above is not vacuous because
    # nothing happened.
    assert len(after) == len(before) + 2
    assert [m.identity_key for m in after if m.derived_from == core.DERIVED_SCREEN] == [
        "screen:30000",
        "screen:95000",
    ]


def test_a_screenshot_inside_a_block_cuts_it_and_the_head_keeps_its_key() -> None:
    segments = [segment(1, 0), segment(2, 10_000), segment(3, 50_000)]
    without = core.plan_moments(segments, [], CONFIG)
    with_shot = core.plan_moments(segments, [shot(1, 30_000, 45_000)], CONFIG)

    assert starts(without) == [0, 50_000]
    assert starts(with_shot) == [0, 30_000, 50_000]
    # The head keeps its identity and start; it just gets shorter.
    assert without[0].identity_key == with_shot[0].identity_key == "transcript:0"
    assert without[0].end_ms == 50_000 and with_shot[0].end_ms == 30_000
    # ...and the tail it gave up is a new screen-anchored moment.
    tail = with_shot[1]
    assert tail.derived_from == core.DERIVED_SCREEN
    assert tail.identity_key == "screen:30000"
    assert tail.segment_ids == ()


def test_a_screenshot_landing_on_a_transcript_boundary_yields_one_both_moment() -> None:
    segments = [segment(1, 0), segment(2, 40_000)]
    planned = core.plan_moments(segments, [shot(1, 40_000, 60_000)], CONFIG)
    assert starts(planned) == [0, 40_000]
    coincident = planned[1]
    assert coincident.derived_from == core.DERIVED_BOTH
    assert coincident.identity_key == "transcript:40000"
    assert coincident.boundary == core.BOUNDARY_SILENCE_GAP


def test_a_screenshot_before_the_first_turn_gets_its_own_empty_moment() -> None:
    segments = [segment(1, 60_000)]
    planned = core.plan_moments(segments, [shot(1, 0, 40_000)], CONFIG)
    assert starts(planned) == [0, 60_000]
    assert planned[0].derived_from == core.DERIVED_SCREEN
    assert planned[0].segment_ids == ()
    assert planned[0].boundary == core.BOUNDARY_SCREENSHOT
    assert planned[1].segment_ids == (uid(1),)


def test_every_segment_is_covered_by_exactly_one_moment() -> None:
    segments = [segment(n, n * 7_000) for n in range(1, 60)]
    planned = core.plan_moments(segments, [shot(1, 100_000, 200_000)], CONFIG)
    covered = [sid for moment in planned for sid in moment.segment_ids]
    assert sorted(covered, key=str) == sorted((s.segment_id for s in segments), key=str)
    assert len(covered) == len(set(covered))
    assert sum(moment.segment_count for moment in planned) == len(segments)


def test_each_moment_names_the_screenshot_on_display_at_its_start() -> None:
    segments = [segment(1, 0), segment(2, 40_000), segment(3, 100_000)]
    screenshots = [shot(1, 0, 30_000), shot(2, 30_000, 90_000), shot(3, 90_000, 150_000)]
    planned = core.plan_moments(segments, screenshots, CONFIG)
    by_start = {moment.start_ms: moment.screenshot_id for moment in planned}
    assert by_start[0] == uid(1001)
    assert by_start[30_000] == uid(1002)
    assert by_start[40_000] == uid(1002)
    assert by_start[90_000] == uid(1003)
    assert by_start[100_000] == uid(1003)


def test_spans_are_contiguous_and_the_last_reaches_the_furthest_evidence() -> None:
    segments = [segment(1, 0, end_ms=20_000), segment(2, 40_000, end_ms=70_000)]
    planned = core.plan_moments(segments, [shot(1, 30_000, 120_000)], CONFIG)
    assert starts(planned) == [0, 30_000, 40_000]
    assert [m.end_ms for m in planned] == [30_000, 40_000, 120_000]
    for moment in planned:
        assert moment.end_ms >= moment.start_ms


def test_an_empty_meeting_plans_nothing() -> None:
    assert core.plan_moments([], [], CONFIG) == ()
    assert core.boundary_counts(()) == {
        core.BOUNDARY_FIRST_SEGMENT: 0,
        core.BOUNDARY_SILENCE_GAP: 0,
        core.BOUNDARY_MAX_DURATION: 0,
        core.BOUNDARY_SCREENSHOT: 0,
    }


def test_a_screenshot_only_meeting_still_yields_a_moment() -> None:
    planned = core.plan_moments([], [shot(1, 0, 5_000)], CONFIG)
    assert [(m.start_ms, m.end_ms, m.derived_from) for m in planned] == [
        (0, 5_000, core.DERIVED_SCREEN)
    ]


def test_two_turns_sharing_a_start_do_not_open_two_moments() -> None:
    segments = [segment(1, 0), segment(2, 40_000), segment(3, 40_000)]
    planned = core.plan_moments(segments, [], CONFIG)
    assert starts(planned) == [0, 40_000]
    assert planned[1].segment_count == 2


def test_boundary_counts_report_every_reason_including_the_unused_ones() -> None:
    segments = [segment(1, 0), segment(2, 40_000)]
    counts = core.boundary_counts(core.plan_moments(segments, [shot(1, 10_000, 20_000)], CONFIG))
    assert counts == {
        core.BOUNDARY_FIRST_SEGMENT: 1,
        core.BOUNDARY_SILENCE_GAP: 1,
        core.BOUNDARY_MAX_DURATION: 0,
        core.BOUNDARY_SCREENSHOT: 1,
    }


def test_no_screenshot_is_named_past_the_end_of_the_last_capture() -> None:
    """A transcript routinely outruns its recording in this corpus.

    A moment starting after the final capture ended had nothing on screen, so
    it names no screenshot rather than inheriting the last one.
    """
    segments = [segment(1, 0), segment(2, 40_000), segment(3, 200_000)]
    planned = core.plan_moments(segments, [shot(1, 0, 100_000)], CONFIG)
    by_start = {moment.start_ms: moment.screenshot_id for moment in planned}
    assert by_start[0] == uid(1001)
    assert by_start[40_000] == uid(1001), "inside the capture, so it is on display"
    assert by_start[200_000] is None, "the recording had already ended"


def test_a_capture_is_still_carried_across_the_gap_between_two_captures() -> None:
    """The gaps *between* consecutive captures are sampling artifacts — the
    screen genuinely was still up — so only the tail past the last one is bare."""
    segments = [segment(1, 0), segment(2, 35_000)]
    screenshots = [shot(1, 0, 30_000), shot(2, 60_000, 90_000)]
    planned = core.plan_moments(segments, screenshots, CONFIG)
    by_start = {moment.start_ms: moment.screenshot_id for moment in planned}
    # 35_000 sits in the gap between capture 1 (ends 30_000) and capture 2
    # (starts 60_000), and still names capture 1.
    assert by_start[35_000] == uid(1001)


def test_a_covered_segment_may_end_after_the_moment_that_covers_it() -> None:
    """A stated consequence of contiguous tiling, not an accident.

    Segments are assigned by their start and `align` synthesizes ends up to
    `max_segment_ms`, so a turn beginning just before a boundary overhangs it.
    Stretching the moment instead would make spans overlap, and overlapping
    spans cannot answer "which moment covers this instant" single-valuedly.
    """
    segments = [segment(1, 0, end_ms=60_000), segment(2, 40_000, end_ms=90_000)]
    planned = core.plan_moments(segments, [], CONFIG)
    head = planned[0]
    assert head.end_ms == 40_000
    assert head.segment_ids == (uid(1),)
    assert segments[0].end_ms > head.end_ms, "the overhang is real and accepted"
    # ...and the tiling stays contiguous and non-overlapping regardless.
    assert [(m.start_ms, m.end_ms) for m in planned] == [(0, 40_000), (40_000, 90_000)]


def test_turns_sharing_a_start_are_covered_in_transcript_order() -> None:
    """Ordinal, not UUID text, is the tiebreak between same-start turns."""
    segments = [
        segment(30, 0, ordinal=3),
        segment(10, 0, ordinal=1),
        segment(20, 0, ordinal=2),
    ]
    [moment] = core.plan_moments(segments, [], CONFIG)
    assert moment.segment_ids == (uid(10), uid(20), uid(30))


@pytest.mark.parametrize("gap_seconds", [0, -1])
def test_a_nonpositive_gap_is_rejected_by_the_config_model(gap_seconds: float) -> None:
    """AD-10 keeps the thresholds in config; the model keeps them meaningful."""
    with pytest.raises(ValueError):
        MomentsConfig(gap_seconds=gap_seconds, max_duration_ms=180_000)
