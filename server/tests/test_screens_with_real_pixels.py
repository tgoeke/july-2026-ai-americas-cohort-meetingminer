"""Segmentation driven by the *production* pixel comparator, on real images.

`test_screens_core.py` exercises the rules against hand-written numbers with a
summing stand-in for the comparator, which is what keeps the decision core
testable with no imaging library. But the one thing story 1.11 changed — the
cue is a bounded diff against the last *emitted* shot, not a chain of
consecutive deltas — is precisely the thing that stand-in cannot represent.
Measured on the 57-minute meeting the two differ by 40 captures, so a rule
that only ever runs against the stand-in is a rule with no test.

Everything here therefore wires :func:`segment_captures` to the real
:func:`frameimage.change_fraction` over synthesized PNGs, in the same shape
the `screens` stage does. Images are generated in the test rather than
committed, so every threshold these assert against is re-derivable.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from meetingminer.config import ScreensConfig
from meetingminer.pipeline import frameimage
from meetingminer.pipeline import screens as core

WIDTH, HEIGHT = 320, 180
COLUMN_X = 280  # the webcam column boundary §2 measured at 87.8 %

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


def screen(tmp_path: Path, name: str, *, filled: float, shade: int = 0) -> Path:
    """A mostly-white "screen" with ``filled`` of its area painted in.

    Stands in for a page's content: 0.0 is a blank grid, 0.4 is a populated
    one. ``shade`` distinguishes two populated screens that fill the same
    area, which is the case the pixel cue has to see.
    """
    image = Image.new("RGB", (WIDTH, HEIGHT), (255, 255, 255))
    if filled > 0:
        rows = round(HEIGHT * filled)
        image.paste((shade, shade, shade), (0, 0, COLUMN_X, rows))
    path = tmp_path / f"{name}.png"
    image.save(path, format="PNG")
    return path


def camera(tmp_path: Path, name: str) -> Path:
    """A camera frame as §4 measured it: dark and saturated."""
    image = Image.new("RGB", (WIDTH, HEIGHT), (140, 30, 20))
    path = tmp_path / f"{name}.png"
    image.save(path, format="PNG")
    return path


def facts(
    paths: list[Path],
    settings: ScreensConfig,
    *,
    blocks: list[int] | None = None,
    texts: list[str] | None = None,
) -> tuple[list[core.FrameFacts], core.ChangeSinceEmitted]:
    """Measure real images into `FrameFacts`, exactly as the stage does."""
    region = frameimage.CropRegion(0.0, 0.0, COLUMN_X / WIDTH, 1.0)
    measurements = {
        path: frameimage.measure_frame(path, region, settings) for path in paths
    }
    by_id: dict[str, Path] = {}
    built: list[core.FrameFacts] = []
    previous = None
    for index, path in enumerate(paths):
        measurement = measurements[path]
        frame_id = f"frame-{index}"
        by_id[frame_id] = path
        built.append(
            core.FrameFacts(
                frame_id=frame_id,
                offset_ms=index * 2000,
                normalized_text=core.normalize_text(
                    texts[index] if texts else f"screen {index}"
                ),
                block_count=blocks[index] if blocks else 40,
                text_density=0.2,
                mean_block_height=0.02,
                change_fraction_vs_previous=frameimage.change_fraction(
                    previous, measurement, settings.pixel_diff_threshold
                ),
                white_fraction=measurement.white_fraction,
                mean_saturation=measurement.mean_saturation,
            )
        )
        previous = measurement

    def change_since_emitted(
        emitted: core.FrameFacts, current: core.FrameFacts
    ) -> float:
        return frameimage.change_fraction(
            measurements[by_id[str(emitted.frame_id)]],
            measurements[by_id[str(current.frame_id)]],
            settings.pixel_diff_threshold,
        )

    return built, change_since_emitted


def test_a_static_screen_is_one_capture_under_the_real_comparator(
    tmp_path: Path,
) -> None:
    """Thirty identical frames are one capture, not thirty.

    Under a summing comparator this is the case that silently breaks:every frame
    contributes ~0 and the sum stays flat, so the stand-in agrees for the
    wrong reason. Here the diff is genuinely taken against the emitted shot.
    """
    settings = config()
    paths = [screen(tmp_path, f"s{i}", filled=0.4, shade=60) for i in range(30)]
    frames, comparator = facts(paths, settings)
    captures = core.segment_captures(frames, settings, comparator)
    assert len(captures) == 1


def test_drift_that_never_resets_still_crosses_the_line(tmp_path: Path) -> None:
    """A page filling in a little at a time eventually cues.

    This is what replaced the dwell rule. Each step moves ~2 % of the region,
    far under `change_threshold`, so a consecutive-frame cue would never fire;
    against the emitted shot the distance keeps growing until it does.
    """
    settings = config()
    paths = [screen(tmp_path, f"d{i}", filled=0.02 * i, shade=60) for i in range(1, 16)]
    frames, comparator = facts(paths, settings)
    captures = core.segment_captures(frames, settings, comparator)
    assert len(captures) > 1, "slow drift must eventually produce a second capture"
    assert all(
        frame.change_fraction_vs_previous < settings.change_threshold
        for frame in frames[1:]
    ), "no single step may reach the cue on its own, or this proves nothing"


def test_the_skeleton_is_not_the_stored_screen(tmp_path: Path) -> None:
    """The regression this story's own review found, at the real comparator.

    Two failures compound, and the second is why this matters. A blank grid is
    pixel-quiet between samples while its text has not arrived, so a
    pixel-only settle stores it; and because a blank grid and a lightly
    populated one are both mostly white, the populated view that follows never
    reaches `change_threshold` against the stored skeleton, so it is never
    captured at all. The populated frame here paints only 8 % of the region,
    under the 10 % cue, which is what reproduces that second half.
    """
    settings = config()
    paths = [
        screen(tmp_path, "before", filled=0.5, shade=0),
        screen(tmp_path, "skeleton", filled=0.0),
        screen(tmp_path, "skeleton2", filled=0.0),
        screen(tmp_path, "populated", filled=0.08, shade=230),
        screen(tmp_path, "settled", filled=0.08, shade=230),
    ]
    blocks = [40, 30, 31, 90, 90]
    frames, comparator = facts(paths, settings, blocks=blocks)

    # The populated view cannot re-cue on its own against the skeleton: that
    # is the premise, so assert it rather than trusting the shades.
    assert comparator(frames[2], frames[3]) < settings.change_threshold

    captures = core.segment_captures(frames, settings, comparator)
    stored = [capture.representative.block_count for capture in captures]
    assert 90 in stored, "the populated screen must be captured"
    assert 30 not in stored and 31 not in stored, (
        f"a skeleton was stored as a settled screen: {stored}"
    )


def test_camera_frames_classify_from_their_own_measured_pixels(
    tmp_path: Path,
) -> None:
    """§4's pair, applied to pixels this test actually measured.

    `test_screens_core.py` asserts the rule against invented `white_fraction`
    and `mean_saturation` values chosen to sit on the right side of the
    thresholds. This one measures a dark saturated frame and a bright
    desaturated one and checks the shipped defaults separate them.
    """
    settings = config()
    paths = [camera(tmp_path, "cam"), screen(tmp_path, "share", filled=0.2, shade=60)]
    frames, _ = facts(paths, settings)
    camera_frame, share_frame = frames

    assert camera_frame.white_fraction <= settings.camera_max_white_fraction
    assert camera_frame.mean_saturation >= settings.camera_min_saturation
    assert core.classify_view_type(camera_frame, settings)[0] == (
        core.VIEW_PARTICIPANT_GALLERY
    )

    assert share_frame.white_fraction > settings.camera_max_white_fraction
    assert share_frame.mean_saturation < settings.camera_min_saturation
    assert core.classify_view_type(share_frame, settings)[0] != (
        core.VIEW_PARTICIPANT_GALLERY
    )


def test_settled_same_chrome_pages_are_each_captured(tmp_path: Path) -> None:
    """Demo-001's miss, reproduced at the real comparator (this story's bug).

    Four dense UI pages share their browser and app chrome, so each pair
    differs by only ~6 % of the region — under `change_threshold` (0.10), the
    gate that absorbed 176 seconds of paging into one capture on demo-001
    (measured sustained distances there: 0.047-0.081). Each page is held for
    ~20 s (10 frames at the 2 s interval), so the settled-change cue must
    capture every page: pixel-quiet at a sustained distance over the 0.03
    floor.
    """
    settings = config()
    held = 10  # ~20 s per page at 2 s sampling
    pages = 4
    paths: list[Path] = []
    for index in range(pages):
        # Same fill fraction, different shade: same-chrome pages whose only
        # difference is the 6 % of the region their content occupies.
        page = screen(tmp_path, f"chrome{index}", filled=0.06, shade=40 + 50 * index)
        paths.extend([page] * held)
    frames, comparator = facts(paths, settings)
    captures = core.segment_captures(frames, settings, comparator)

    # The premise, both bounds: no page flip reaches the region-change gate
    # on its own...
    assert all(
        frame.change_fraction_vs_previous < settings.change_threshold
        for frame in frames[1:]
    ), "a page flip reached change_threshold, so this reproduces nothing"
    # ...and every flip clears the settled floor vs the shot it must cue
    # against (pages are held identically, so page-to-page distance is the
    # emitted-shot distance). Without this, a shade drift under 0.03 would
    # fail on a misleading capture-count message instead of on the premise.
    assert all(
        comparator(frames[(page - 1) * held], frames[page * held])
        >= settings.settled_change_threshold
        for page in range(1, pages)
    ), "a page flip fell under settled_change_threshold, so this reproduces nothing"

    assert len(captures) == pages, (
        f"{pages} settled same-chrome pages must be {pages} captures,"
        f" got {len(captures)}"
    )
    assert [capture.cues for capture in captures[1:]] == [
        (core.CUE_SETTLED_CHANGE,)
    ] * (pages - 1)
    assert all(capture.tags == () for capture in captures)


def test_the_shipped_defaults_hold_the_over_capture_guardrail(tmp_path: Path) -> None:
    """`eval-design.md` §2.2: fewer captures than minutes of meeting.

    Ten distinct screens, each held for a minute at the project's two-second
    sampling, is 300 frames of ten minutes. The guardrail is what this story
    exists to satisfy, and nothing else in the suite asserts it — the real
    check lands in story 5.2, over a scripted corpus this repository does not
    have yet, so this is the arithmetic and not a substitute for it.
    """
    settings = config()
    held = 30  # frames per screen = 60 s at 2 s sampling
    paths: list[Path] = []
    for index in range(10):
        page = screen(tmp_path, f"page{index}", filled=0.3, shade=20 * index)
        paths.extend([page] * held)
    frames, comparator = facts(paths, settings)
    captures = core.segment_captures(frames, settings, comparator)

    minutes = len(paths) * 2 / 60
    assert len(captures) <= minutes, (
        f"{len(captures)} captures over {minutes:g} minutes exceeds one per minute"
    )
    assert len(captures) == 10, "each distinct screen should be captured exactly once"
