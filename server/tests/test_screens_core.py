"""The `screens` stage's decision rules, with no database and no OCR engine.

Every threshold these assert against comes from a :class:`ScreensConfig`
built here, so the tests describe the *rule* rather than the shipped defaults
in config.yaml — retuning those numbers must not silently rewrite what the
stage is supposed to do.
"""

from __future__ import annotations

import hashlib
from typing import Sequence
from uuid import UUID

import pytest

from meetingminer.config import ScreensConfig
from meetingminer.pipeline import screens as core

MEETING_ID = UUID("018f6a2e-0000-7000-8000-000000000001")

DEFAULTS = dict(
    analysis_width=320,
    pixel_diff_threshold=16,
    white_pixel_level=200,
    change_threshold=0.10,
    settled_change_threshold=0.03,
    settled_change_frames=3,
    settle_threshold=0.02,
    settle_text_growth_ratio=1.5,
    settle_timeout_seconds=10,
    crop_survey_frames=24,
    crop_column_white_max=0.25,
    crop_min_region_width=0.6,
    crop_row_static_range_max=80,
    crop_max_bottom_strip=0.12,
    camera_max_white_fraction=0.118,
    camera_min_saturation=0.212,
    lineage_threshold=0.8,
    min_signature_tokens=3,
    gallery_max_blocks=6,
    gallery_max_text_density=0.02,
    slide_min_block_height=0.04,
    slide_max_blocks=25,
)


def config(**overrides: object) -> ScreensConfig:
    return ScreensConfig(**{**DEFAULTS, **overrides})


def frame(
    offset_ms: int,
    text: str = "",
    *,
    change: float = 0.0,
    white_fraction: float = 0.5,
    mean_saturation: float = 0.05,
    block_count: int = 10,
    text_density: float = 0.2,
    mean_block_height: float = 0.02,
) -> core.FrameFacts:
    """One frame's facts, already cropped to the share region.

    The pixel defaults are a screen share as §4 measured it — bright and
    desaturated — so a test that says nothing about pixels is a test about
    something else.
    """
    return core.FrameFacts(
        frame_id=f"frame-{offset_ms}",
        offset_ms=offset_ms,
        normalized_text=core.normalize_text(text),
        block_count=block_count,
        text_density=text_density,
        mean_block_height=mean_block_height,
        change_fraction_vs_previous=change,
        white_fraction=white_fraction,
        mean_saturation=mean_saturation,
    )


def still(offset_ms: int, text: str = "", **overrides: object) -> core.FrameFacts:
    """A frame whose region did not move since its predecessor."""
    return frame(offset_ms, text, change=0.0, **overrides)  # type: ignore[arg-type]


def summed(frames: Sequence[core.FrameFacts]) -> core.ChangeSinceEmitted:
    """A stand-in for the pixel comparison against the last emitted shot.

    The real one is a true diff of two decoded frames
    (:func:`frameimage.change_fraction`), which needs images. These frames are
    synthetic and one-dimensional — every step moves the same region the same
    way — so summing the per-frame deltas between the emitted shot and the
    frame in hand is the same quantity, and the segmentation rules stay
    testable with no imaging library in the room.
    """
    ordered = sorted(frames, key=lambda item: item.offset_ms)
    index = {item.frame_id: position for position, item in enumerate(ordered)}

    def compare(emitted: core.FrameFacts, current: core.FrameFacts) -> float:
        span = ordered[index[emitted.frame_id] + 1 : index[current.frame_id] + 1]
        return sum(item.change_fraction_vs_previous for item in span)

    return compare


def segment(frames: Sequence[core.FrameFacts], config: ScreensConfig) -> list[core.Capture]:
    """Segment ``frames`` through the stand-in comparator."""
    return core.segment_captures(frames, config, summed(frames))


# --- normalization + similarity -------------------------------------------


def test_normalize_folds_case_punctuation_and_layout_whitespace() -> None:
    assert core.normalize_text("  Quarterly  Review:\n  Q3 — 2026!  ") == (
        "quarterly review q3 2026"
    )
    assert core.normalize_text("") == ""
    assert core.normalize_text("...---...") == ""


def test_normalize_keeps_non_ascii_letters() -> None:
    """Screen identity must work outside English, not silently collapse to ''."""
    # Accented Latin survives as whole words, not as ASCII fragments.
    assert core.normalize_text("Café Münster — Q3") == "café münster q3"
    # NFKC folds a decomposed accent onto the same token as the composed form.
    assert core.normalize_text("Cafe\u0301") == core.normalize_text("Café")
    # A non-Latin script normalizes to real tokens...
    assert core.normalize_text("Отчёт о доходах") == "отчёт о доходах"
    assert core.normalize_text("四半期 売上") == "四半期 売上"
    # ...so it clears the signature floor and takes a corpus-wide identity
    # rather than being scoped to its meeting as if it were blank.
    signature = core.normalize_text("Отчёт о доходах")
    assert len(core.tokens(signature)) == 3
    assert not core.is_scoped_identity(
        core.identity_key_for(signature, MEETING_ID, 1, config())
    )


def test_underscores_separate_tokens_rather_than_joining_them() -> None:
    assert core.normalize_text("invoice_total_due") == "invoice total due"


def test_jaccard_boundaries() -> None:
    # Two textless frames are not a change: nothing moved.
    assert core.jaccard(core.tokens(""), core.tokens("")) == 1.0
    # Text appearing over a textless frame is a total change.
    assert core.jaccard(core.tokens(""), core.tokens("a b")) == 0.0
    assert core.jaccard(core.tokens("a b"), core.tokens("a b")) == 1.0
    assert core.jaccard(core.tokens("a b"), core.tokens("b c")) == pytest.approx(1 / 3)


# --- segmentation: the cue ------------------------------------------------


def test_first_frame_always_opens_a_capture() -> None:
    [capture] = segment([frame(0, "roadmap")], config())
    assert capture.ordinal == 1
    assert capture.cues == (core.CUE_FIRST_FRAME,)
    assert (capture.start_offset_ms, capture.end_offset_ms) == (0, 0)
    assert capture.frame_count == 1
    assert capture.tags == ()


def test_a_region_change_starts_a_capture() -> None:
    frames = [
        frame(0, "quarterly revenue growth"),
        still(2000, "quarterly revenue growth"),
        frame(4000, "deployment pipeline architecture", change=0.4),
        still(6000, "deployment pipeline architecture"),
    ]
    first, second = segment(frames, config())
    assert first.cues == (core.CUE_FIRST_FRAME,)
    assert first.frame_count == 2
    assert (first.start_offset_ms, first.end_offset_ms) == (0, 2000)
    assert second.cues == (core.CUE_REGION_CHANGE,)
    assert (second.start_offset_ms, second.end_offset_ms) == (4000, 6000)


def test_text_alone_never_starts_a_capture() -> None:
    """Story 1.11: OCR text decides screen identity, not capture boundaries.

    Every measured text cue put the run over `eval-design.md` §2.2's one
    capture per minute; the cropped pixel change is what decides now.
    """
    frames = [
        frame(0, "quarterly revenue growth"),
        still(2000, "deployment pipeline architecture"),
    ]
    assert len(segment(frames, config())) == 1


def drifting(last_offset_ms: int, step: float = 0.02) -> list[core.FrameFacts]:
    """A form being filled in: every frame barely moves, but it keeps moving."""
    frames = [frame(0, "invoice form")]
    frames += [
        frame(offset, "invoice form", change=step)
        for offset in range(2000, last_offset_ms + 2000, 2000)
    ]
    return frames


def test_the_cue_measures_against_the_last_emitted_shot_not_the_previous_frame() -> None:
    """Slow drift accumulates until it crosses the line — the old dwell rule.

    No single step here comes near the threshold, so a previous-frame
    comparison would never fire at all; measured against the last emitted
    shot, the distance keeps growing until it cues. Quiet drift is exactly a
    sustained settled change, so it crosses at the settled-change gate: at
    0.02 a step, the run over `settled_change_threshold` (0.04, 0.06, 0.08)
    completes `settled_change_frames` at the fourth step after emission.
    """
    first, second = segment(drifting(10_000), config())
    assert first.cues == (core.CUE_FIRST_FRAME,)
    assert second.cues == (core.CUE_SETTLED_CHANGE,)
    assert second.start_offset_ms == 8_000


def test_the_accumulator_restarts_at_every_emission() -> None:
    """Otherwise every frame after the first cue would be its own capture."""
    captures = segment(drifting(40_000), config())
    # The first post-emission step (0.02) is under the settled floor and does
    # not count; the run 0.04 -> 0.06 -> 0.08 then cues, so the period is
    # four steps.
    assert [capture.start_offset_ms for capture in captures] == [
        0, 8_000, 16_000, 24_000, 32_000, 40_000,
    ]


def test_a_settled_same_chrome_change_cues_under_the_region_threshold() -> None:
    """Demo-001's miss mode: dense same-chrome pages sit under 0.10 forever.

    A real page change arrives and then *stays*: the region is pixel-quiet at
    a new sustained distance from the emitted shot, above
    `settled_change_threshold` but below `change_threshold`. After
    `settled_change_frames` such frames the settled-change cue fires.
    """
    frames = [
        frame(0, "order search results"),
        still(2000, "order search results"),
        still(4000, "line items and tax breakdown"),
        still(6000, "line items and tax breakdown"),
        still(8000, "line items and tax breakdown"),
        still(10_000, "line items and tax breakdown"),
    ]

    def compare(emitted: core.FrameFacts, current: core.FrameFacts) -> float:
        # The page flipped at 4000 and holds a 0.06 distance from the shot —
        # under the 0.10 gate, over the 0.03 settled floor.
        return 0.06 if current.offset_ms >= 4000 else 0.0

    first, second = core.segment_captures(frames, config(), compare)
    assert first.cues == (core.CUE_FIRST_FRAME,)
    assert second.cues == (core.CUE_SETTLED_CHANGE,)
    assert second.start_offset_ms == 8_000  # the third sustained quiet frame
    assert second.tags == ()
    assert second.signature == "line items and tax breakdown"


def test_a_transient_blip_resets_the_settled_change_run() -> None:
    """A menu or tooltip spikes and returns; a page change arrives and stays.

    The blip frame is over the settled floor vs the emitted shot but it is
    not pixel-quiet, and the frame after it falls back under the floor — both
    reset the run, so no capture fires.
    """
    frames = [
        frame(0, "order search results"),
        still(2000, "order search results"),
        # A transient: moves 0.04, is not quiet, and reverts next sample.
        frame(4000, "order search results", change=0.04),
        frame(6000, "order search results", change=0.04),  # moving back
        still(8000, "order search results"),
        still(10_000, "order search results"),
    ]

    def compare(emitted: core.FrameFacts, current: core.FrameFacts) -> float:
        return 0.04 if current.offset_ms == 4000 else 0.0

    captures = core.segment_captures(frames, config(), compare)
    assert len(captures) == 1


def test_quiet_frames_under_the_settled_floor_never_cue() -> None:
    """Persistent noise against the emitted shot stays absorbed."""
    frames = [frame(0, "order search results")]
    frames += [still(offset, "order search results") for offset in range(2000, 30_000, 2000)]

    def compare(emitted: core.FrameFacts, current: core.FrameFacts) -> float:
        return 0.02  # persistent, quiet, and under the 0.03 floor

    captures = core.segment_captures(frames, config(), compare)
    assert len(captures) == 1


def test_the_opening_title_card_folds_into_the_capture_that_replaces_it() -> None:
    """A first frame replaced by the very next sample was never a view.

    Teams recordings open on an injected title card that is gone before the
    second sample. It must not be stored as a screen the meeting never held —
    the slate frame is discarded outright, so the recording's first sample
    belongs to no capture by design, and the capture that replaces it records
    both cue doors (`first-frame` then `region-change`).
    """
    frames = [
        # Dark and desaturated, as demo-001's Teams slate measured (§4 fails
        # both classes: not bright like a share, not saturated like camera).
        frame(
            0,
            "scripted ui demo orders module recorded by",
            white_fraction=0.01,
            mean_saturation=0.14,
        ),
        frame(2000, "", change=0.9),  # the real meeting starts painting
        frame(4000, "order search results", change=0.01),
        still(6000, "order search results"),
    ]
    [capture] = segment(frames, config())
    assert capture.cues == (core.CUE_FIRST_FRAME, core.CUE_REGION_CHANGE)
    # The slate frame is discarded, not folded in: it is the text-richest
    # frame of any transition window, so keeping it would hand the
    # settle-timeout fallback the slate as the stored screen.
    assert capture.start_offset_ms == 2000
    assert capture.frame_count == 3
    assert capture.signature == "order search results"


def test_a_held_opening_screen_is_not_folded() -> None:
    """The fold is only for a first frame gone within one sampling interval."""
    frames = [
        frame(0, "quarterly report title"),
        still(2000, "quarterly report title"),
        frame(4000, "next screen entirely", change=0.5),
        still(6000, "next screen entirely"),
    ]
    first, second = segment(frames, config())
    assert first.cues == (core.CUE_FIRST_FRAME,)
    assert first.signature == "quarterly report title"
    assert second.cues == (core.CUE_REGION_CHANGE,)


def test_a_bright_opening_frame_gone_in_one_sample_is_still_a_capture() -> None:
    """NFR8: only a dark, desaturated recorder slate folds — a real view
    (bright share pixels) that lasted one sample keeps its own capture."""
    frames = [
        frame(0, "real first screen content"),  # bright share defaults
        frame(2000, "second screen entirely", change=0.5),
        still(4000, "second screen entirely"),
    ]
    first, second = segment(frames, config())
    assert first.cues == (core.CUE_FIRST_FRAME,)
    assert first.signature == "real first screen content"
    assert second.cues == (core.CUE_REGION_CHANGE,)
    assert second.signature == "second screen entirely"


def test_a_saturated_opening_frame_gone_in_one_sample_is_still_a_capture() -> None:
    """The fold needs dark AND desaturated — camera-class pixels do not fold.

    A dark but *saturated* one-sample opening frame reads as camera video
    (§4's other class), not as a recorder slate, so it keeps its own capture.
    This pins the saturation conjunct of the fold guard: dropping it would
    fold real camera openings and no other test would notice.
    """
    frames = [
        frame(
            0,
            "presenter webcam moment",
            white_fraction=0.03,
            mean_saturation=0.35,
        ),
        frame(2000, "second screen entirely", change=0.5),
        still(4000, "second screen entirely"),
    ]
    first, second = segment(frames, config())
    assert first.cues == (core.CUE_FIRST_FRAME,)
    assert first.signature == "presenter webcam moment"
    assert second.cues == (core.CUE_REGION_CHANGE,)


def test_sustained_motion_in_the_settled_band_never_cues() -> None:
    """The pixel-quiet conjunct: distance alone is not a settled change.

    Live gallery video hovers at a steady distance from the emitted shot
    while every consecutive pair keeps moving (over `settle_threshold`).
    Without the quiet requirement the settled-change cue would fire every
    `settled_change_frames` samples and flood galleries with captures.
    """
    frames = [frame(0, "order search results"), still(2000, "order search results")]
    frames += [
        frame(offset, "order search results", change=0.04)  # never quiet
        for offset in range(4000, 18_000, 2000)
    ]

    def compare(emitted: core.FrameFacts, current: core.FrameFacts) -> float:
        # In the settled band the whole time — over 0.03, under 0.10.
        return 0.05 if current.offset_ms >= 4000 else 0.0

    captures = core.segment_captures(frames, config(), compare)
    assert len(captures) == 1


def test_a_quiet_frame_back_under_the_floor_resets_the_run() -> None:
    """The under-floor reset arm, isolated from the non-quiet arm.

    A run accrues two quiet over-floor frames, a quiet frame then drops back
    under the floor (reset), and only a fresh three-frame run fires — so the
    cue lands at the end of the second run, not the tally of both.
    """
    frames = [frame(0, "order search results")]
    frames += [still(offset, "order search results") for offset in range(2000, 16_000, 2000)]

    distances = {
        4000: 0.05,   # run: 1
        6000: 0.05,   # run: 2
        8000: 0.02,   # quiet but under the floor: reset
        10_000: 0.05,  # run: 1
        12_000: 0.05,  # run: 2
        14_000: 0.05,  # run: 3 -> fires here
    }

    def compare(emitted: core.FrameFacts, current: core.FrameFacts) -> float:
        return distances.get(current.offset_ms, 0.0)

    first, second = core.segment_captures(frames, config(), compare)
    assert second.cues == (core.CUE_SETTLED_CHANGE,)
    assert second.start_offset_ms == 14_000


def test_the_cue_asks_about_the_emitted_shot_not_the_previous_frame() -> None:
    """The reference is the shot on disk, which is what §2 measured against.

    Recorded here because the difference is invisible in the numbers: a chain
    of consecutive-frame deltas and a true diff against the emitted shot are
    different quantities, and on the 57-minute meeting they differ by 40
    captures.
    """
    frames = [frame(0, "one"), frame(2000, "two", change=0.5), frame(4000, "three", change=0.0)]
    asked: list[tuple[int, int]] = []

    def compare(emitted: core.FrameFacts, current: core.FrameFacts) -> float:
        asked.append((emitted.offset_ms, current.offset_ms))
        return 0.0

    core.segment_captures(frames, config(), compare)
    assert asked == [(0, 2000), (0, 4000)]


def test_nothing_is_compared_while_a_capture_is_still_settling() -> None:
    """The reference stays the previous emission until this one has a shot."""
    frames = [
        frame(0, "one"),
        frame(2000, "mid load", change=0.9),
        frame(4000, "mid load still", change=0.9),
        frame(6000, "settled", change=0.0),
        frame(8000, "settled", change=0.0),
    ]
    asked: list[tuple[int, int]] = []

    def compare(emitted: core.FrameFacts, current: core.FrameFacts) -> float:
        asked.append((emitted.offset_ms, current.offset_ms))
        return 1.0 if current.offset_ms == 2000 else 0.0

    core.segment_captures(frames, config(), compare)
    # 4000 is inside the new capture's transition burst, so it is never asked
    # about; once the region settles at 6000 that frame becomes the reference.
    assert asked == [(0, 2000), (6000, 8000)]


def test_a_static_screen_is_captured_once_however_long_it_dwells() -> None:
    frames = [still(offset, "static slide title") for offset in range(0, 1_800_000, 2000)]
    captures = segment(frames, config())
    assert len(captures) == 1
    assert captures[0].frame_count == len(frames)


def test_no_frames_produces_no_captures() -> None:
    assert segment([], config()) == []


def test_frames_arrive_in_offset_order_however_they_are_passed() -> None:
    frames = [
        frame(4000, "second screen here", change=0.5),
        frame(0, "first screen here"),
        still(2000, "first screen here"),
    ]
    captures = segment(frames, config())
    assert [c.start_offset_ms for c in captures] == [0, 4000]


# --- segmentation: the settle ---------------------------------------------


def test_the_emitted_frame_is_the_first_quiet_one_not_the_cue_frame() -> None:
    """§3: a blank mid-load page is the largest possible difference.

    Emitting at the moment of change would keep the spinner; emitting at the
    settle keeps the populated screen the spinner turned into.
    """
    frames = [
        frame(0, "dashboard"),
        still(1000, "dashboard"),
        frame(2000, "", change=0.8),  # blank mid-load
        frame(4000, "loading", change=0.3),  # spinner
        frame(6000, "invoice list total due", change=0.01),  # settled
        still(8000, "invoice list total due"),
    ]
    _, second = segment(frames, config())
    assert second.start_offset_ms == 2000, "the capture still spans its transition"
    assert second.representative.offset_ms == 6000
    assert second.signature == "invoice list total due"
    assert second.tags == ()


def test_a_pixel_quiet_frame_that_is_still_painting_has_not_settled() -> None:
    """A skeleton page holds still between samples while its text arrives.

    Measured on the 57-minute meeting: a loading spreadsheet moved 0.009 of
    its pixels — well under settle_threshold — while its cropped block count
    went 32 -> 82 across one two-second sample. On the pixel test alone the
    skeleton became the stored screen and the populated view that followed it
    was never captured, because both are mostly-white grids.
    """
    frames = [
        frame(0, "dashboard", block_count=80),
        still(1000, "dashboard", block_count=80),
        frame(2000, "", change=0.5, block_count=31),  # skeleton: cue fires
        frame(4000, "", change=0.009, block_count=32),  # quiet, but still painting
        frame(6000, "field matrix applicable law sla summary", change=0.06, block_count=82),
        still(8000, "field matrix applicable law sla summary", block_count=82),
    ]
    _, second = segment(frames, config())
    assert second.representative.offset_ms == 8000, "the skeleton is not the screen"
    assert second.representative.block_count == 82
    assert second.tags == ()


def test_text_that_grows_within_the_ratio_still_counts_as_settled() -> None:
    """The guard is for a page painting in, not for a screen that is busy."""
    frames = [
        frame(0, "dashboard", block_count=80),
        still(1000, "dashboard", block_count=80),
        frame(2000, "invoice list", change=0.5, block_count=40),
        frame(4000, "invoice list", change=0.01, block_count=50),  # 1.25x < 1.5x
        still(6000, "invoice list", block_count=50),
    ]
    _, second = segment(frames, config())
    assert second.representative.offset_ms == 4000


def test_a_capture_that_never_settles_times_out_and_is_tagged() -> None:
    """Tagged, never dropped (§4, NFR8) — and the window still gets a shot.

    The capture's window ends at the frame the timeout falls on; which frame
    inside it represents the screen is then the settle-timeout fallback's
    question, tested below.
    """
    frames = [frame(0, "dashboard"), still(1000, "dashboard")]
    frames += [frame(offset, "spinner", change=0.5) for offset in range(2000, 14000, 2000)]
    first, second = segment(frames, config())
    assert first.cues == (core.CUE_FIRST_FRAME,)
    assert second.cues == (core.CUE_REGION_CHANGE,)
    assert core.TAG_LIKELY_TRANSITION in second.tags
    # The cue is at 2000 and settle_timeout_seconds is 10, so the wait ends
    # at 12000 and the capture spans the whole burst.
    assert (second.start_offset_ms, second.end_offset_ms) == (2000, 12000)
    assert second.frame_count == 6


def test_the_timeout_representative_falls_back_to_the_most_text_rich_frame() -> None:
    frames = [frame(0, "dashboard"), still(1000, "dashboard")]
    frames += [
        frame(2000, "a", change=0.5),
        frame(4000, "a b c d e", change=0.5),
        frame(6000, "a b", change=0.5),
        frame(8000, "a b c", change=0.5),
    ]
    _, second = segment(frames, config(settle_timeout_seconds=6))
    assert core.TAG_LIKELY_TRANSITION in second.tags
    assert second.representative.offset_ms == 4000


def test_a_capture_whose_frames_run_out_mid_transition_is_tagged_too() -> None:
    frames = [
        frame(0, "dashboard"),
        still(1000, "dashboard"),
        frame(2000, "half drawn", change=0.6),
    ]
    _, second = segment(frames, config())
    assert core.TAG_LIKELY_TRANSITION in second.tags
    assert second.representative.offset_ms == 2000


def test_slow_drift_emits_immediately_because_there_is_nothing_to_settle() -> None:
    """The cue frame is already quiet, so waiting for a settle would be a lie."""
    _, second = segment(drifting(10_000), config())
    assert second.tags == ()
    assert second.representative.offset_ms == second.start_offset_ms


# --- representative selection ---------------------------------------------


def test_representative_is_the_most_text_rich_frame_not_a_transition() -> None:
    frames = [
        frame(0, "title", change=0.9),  # transition: half-drawn
        frame(2000, "title agenda budget timeline owners", change=0.9),
        frame(4000, "title agenda budget", change=0.9),
    ]
    assert core.choose_representative(frames).offset_ms == 2000
    assert core.signature_for(core.choose_representative(frames)) == (
        "title agenda budget timeline owners"
    )


def test_representative_ties_break_to_the_earliest_frame() -> None:
    frames = [frame(0, "alpha beta"), still(2000, "alpha beta")]
    [capture] = segment(frames, config())
    assert capture.representative.offset_ms == 0


# --- view type -------------------------------------------------------------


def camera(offset_ms: int = 0, **overrides: object) -> core.FrameFacts:
    """§4's camera/gallery video: dark and saturated."""
    return frame(offset_ms, white_fraction=0.03, mean_saturation=0.35, **overrides)  # type: ignore[arg-type]


def test_camera_pixels_are_a_gallery_whatever_the_text_geometry_says() -> None:
    """The pixel pair is tested first (§4) — that ordering is the retune.

    These block counts and heights are a slide's, and before story 1.11 the
    geometry decided. A camera frame with a few incidental OCR boxes would
    have been filed as a slide.
    """
    shot = camera(block_count=8, text_density=0.15, mean_block_height=0.08)
    assert core.classify_view_type(shot, config()) == (core.VIEW_PARTICIPANT_GALLERY, ())


def test_both_pixel_metrics_must_hold_for_the_camera_rule() -> None:
    dark_but_grey = frame(0, "dense", white_fraction=0.03, mean_saturation=0.05,
                          block_count=60, text_density=0.30, mean_block_height=0.015)
    bright_and_colourful = frame(0, "dense", white_fraction=0.5, mean_saturation=0.35,
                                 block_count=60, text_density=0.30, mean_block_height=0.015)
    assert core.classify_view_type(dark_but_grey, config())[0] == core.VIEW_UI_SCREEN
    assert core.classify_view_type(bright_and_colourful, config())[0] == core.VIEW_UI_SCREEN


def test_a_bright_desaturated_textless_frame_is_an_unresolved_avatar_gallery() -> None:
    """§4's known gap, labelled rather than asserted away.

    Avatar tiles on a light background pass the camera filter, so this frame
    could be a gallery or a near-empty screen. It is filed as a gallery —
    never `ui-screen` or `slide`, whose failure mode is calling a gallery a
    screen — and the ambiguity is recorded on the capture.
    """
    tile = frame(0, "", white_fraction=0.6, mean_saturation=0.04,
                 block_count=4, text_density=0.005, mean_block_height=0.03)
    view_type, tags = core.classify_view_type(tile, config())
    assert view_type == core.VIEW_PARTICIPANT_GALLERY
    assert tags == (core.TAG_AVATAR_GALLERY_UNRESOLVED,)


def test_view_type_slide() -> None:
    slide = frame(0, "big heading", block_count=8, text_density=0.15, mean_block_height=0.08)
    assert core.classify_view_type(slide, config()) == (core.VIEW_SLIDE, ())


def test_view_type_ui_screen() -> None:
    ui = frame(0, "dense", block_count=60, text_density=0.30, mean_block_height=0.015)
    assert core.classify_view_type(ui, config()) == (core.VIEW_UI_SCREEN, ())


def test_gallery_beats_slide_when_both_would_match() -> None:
    """First match wins: a few huge boxes on an almost-empty frame is a gallery."""
    ambiguous = frame(0, "", block_count=2, text_density=0.01, mean_block_height=0.2)
    assert core.classify_view_type(ambiguous, config())[0] == core.VIEW_PARTICIPANT_GALLERY


def test_a_slide_with_too_many_blocks_is_a_ui_screen() -> None:
    busy = frame(0, "x", block_count=40, text_density=0.3, mean_block_height=0.09)
    assert core.classify_view_type(busy, config()) == (core.VIEW_UI_SCREEN, ())


def test_a_capture_carries_the_classifier_tags_and_the_transition_tag() -> None:
    """A timed-out capture of an unresolved gallery records both, in order."""
    tiles = dict(white_fraction=0.6, mean_saturation=0.04, block_count=0,
                 text_density=0.0, mean_block_height=0.0)
    frames = [frame(0, "dashboard"), still(1000, "dashboard")]
    frames += [
        frame(offset, "", change=0.5, **tiles)  # type: ignore[arg-type]
        for offset in range(2000, 14000, 2000)
    ]
    _, second = segment(frames, config())
    assert second.view_type == core.VIEW_PARTICIPANT_GALLERY
    assert second.tags == (
        core.TAG_LIKELY_TRANSITION,
        core.TAG_AVATAR_GALLERY_UNRESOLVED,
    )


# --- identity --------------------------------------------------------------


def test_identity_key_of_a_real_signature_is_its_hash_and_crosses_meetings() -> None:
    signature = "quarterly revenue growth"
    expected = hashlib.sha256(signature.encode()).hexdigest()
    assert core.identity_key_for(signature, MEETING_ID, 1, config()) == expected
    # Same screen, different meeting and ordinal: same key, hence one row.
    other = UUID("018f6a2e-0000-7000-8000-000000000002")
    assert core.identity_key_for(signature, other, 7, config()) == expected
    assert not core.is_scoped_identity(expected)


def test_a_blank_signature_is_scoped_to_its_meeting() -> None:
    key = core.identity_key_for("", MEETING_ID, 3, config())
    assert key == f"meeting:{MEETING_ID}:3"
    assert core.is_scoped_identity(key)
    # Two textless screens in the same meeting are still two screens...
    assert key != core.identity_key_for("", MEETING_ID, 4, config())
    # ...and a textless screen in another meeting is not this one.
    other = UUID("018f6a2e-0000-7000-8000-000000000002")
    assert key != core.identity_key_for("", other, 3, config())


def test_a_signature_below_the_token_floor_is_scoped_too() -> None:
    assert core.is_scoped_identity(core.identity_key_for("ok go", MEETING_ID, 1, config()))
    assert not core.is_scoped_identity(
        core.identity_key_for("ok go now", MEETING_ID, 1, config())
    )


# --- lineage ---------------------------------------------------------------


def test_lineage_reuses_the_closest_screen_above_the_threshold() -> None:
    candidates = [
        ("screen-far", "totally different words here"),
        ("screen-near", "quarterly revenue growth fy26"),
    ]
    match = core.best_lineage_match("quarterly revenue growth fy26 draft", candidates, config())
    assert match == "screen-near"


def test_lineage_declines_below_the_threshold() -> None:
    candidates = [("screen-a", "alpha beta gamma delta")]
    assert core.best_lineage_match("epsilon zeta eta theta", candidates, config()) is None


def test_lineage_ties_break_on_the_lowest_id() -> None:
    candidates = [("screen-b", "alpha beta gamma"), ("screen-a", "alpha beta gamma")]
    assert core.best_lineage_match("alpha beta gamma", candidates, config()) == "screen-a"
