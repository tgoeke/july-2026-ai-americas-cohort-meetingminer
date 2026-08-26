"""Pixel measurement and the detect-once share-region survey (story 1.11).

Every image here is synthesized in the test, so the assertions are against
known geometry rather than against a committed binary fixture nobody can
re-derive. The numbers the survey separates on are the ones
`capture-measurements.md` §2 measured: a webcam column that is dark where the
share area is bright, and a taskbar that does not change over time.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from meetingminer.config import ScreensConfig
from meetingminer.pipeline import frameimage

# Analysis scale exactly, so nothing here depends on a resampling filter.
WIDTH, HEIGHT = 320, 180
COLUMN_X = 280  # 0.875 — the boundary §2 measured at 87.8 %
TASKBAR_Y = 168  # 0.9333 — a ~6.7 % static bottom strip

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

FULL_FRAME = frameimage.CropRegion()


def config(**overrides: object) -> ScreensConfig:
    return ScreensConfig(**{**DEFAULTS, **overrides})


def write_png(path: Path, image: Image.Image) -> Path:
    image.save(path, format="PNG")
    return path


def solid(color: tuple[int, int, int], size: tuple[int, int] = (WIDTH, HEIGHT)) -> Image.Image:
    return Image.new("RGB", size, color)


def meeting_frame(bright: bool) -> Image.Image:
    """A frame in §2's two-part layout.

    Share area on the left, a dark webcam column on the right, a mid-gray
    taskbar along the bottom. ``bright`` flips the share area between white
    and black, which is what gives the *rows* something to vary by: the
    taskbar is then the only strip whose brightness does not move.
    """
    image = solid((0, 0, 0))
    if bright:
        image.paste((255, 255, 255), (0, 0, COLUMN_X, TASKBAR_Y))
    image.paste((128, 128, 128), (0, TASKBAR_Y, WIDTH, HEIGHT))
    return image


def survey_frames(tmp_path: Path, count: int = 8) -> list[Path]:
    return [
        write_png(tmp_path / f"frame-{index:03d}.png", meeting_frame(index % 2 == 0))
        for index in range(count)
    ]


# --- per-frame pixel facts -------------------------------------------------


def test_white_fraction_counts_only_bright_pixels(tmp_path: Path) -> None:
    image = solid((0, 0, 0))
    image.paste((255, 255, 255), (0, 0, WIDTH // 2, HEIGHT))
    path = write_png(tmp_path / "half.png", image)
    measurement = frameimage.measure_frame(path, FULL_FRAME, config())
    assert measurement.white_fraction == pytest.approx(0.5)

    # 200 is the floor, and it is exclusive: a pixel *at* the level is not white.
    at_level = write_png(tmp_path / "at.png", solid((200, 200, 200)))
    assert frameimage.measure_frame(at_level, FULL_FRAME, config()).white_fraction == 0.0
    above = write_png(tmp_path / "above.png", solid((201, 201, 201)))
    assert frameimage.measure_frame(above, FULL_FRAME, config()).white_fraction == 1.0


def test_mean_saturation_separates_camera_colour_from_grey_chrome(tmp_path: Path) -> None:
    """§4's second metric: camera video is saturated, screen share is not."""
    colourful = write_png(tmp_path / "red.png", solid((255, 0, 0)))
    grey = write_png(tmp_path / "grey.png", solid((128, 128, 128)))
    assert frameimage.measure_frame(colourful, FULL_FRAME, config()).mean_saturation == 1.0
    assert frameimage.measure_frame(grey, FULL_FRAME, config()).mean_saturation == 0.0


def test_change_fraction_is_the_share_of_pixels_that_moved(tmp_path: Path) -> None:
    before = write_png(tmp_path / "before.png", solid((0, 0, 0)))
    after_image = solid((0, 0, 0))
    after_image.paste((255, 255, 255), (0, 0, WIDTH // 4, HEIGHT))
    after = write_png(tmp_path / "after.png", after_image)

    first = frameimage.measure_frame(before, FULL_FRAME, config())
    second = frameimage.measure_frame(after, FULL_FRAME, config())
    assert frameimage.change_fraction(first, second, 16) == pytest.approx(0.25)
    # No predecessor is 0.0, not a fabricated total change.
    assert frameimage.change_fraction(None, second, 16) == 0.0


def test_a_change_below_the_pixel_threshold_does_not_count(tmp_path: Path) -> None:
    """JPEG noise must not read as motion — that is what the threshold is for."""
    before = write_png(tmp_path / "flat.png", solid((100, 100, 100)))
    after = write_png(tmp_path / "nudged.png", solid((110, 110, 110)))
    first = frameimage.measure_frame(before, FULL_FRAME, config())
    second = frameimage.measure_frame(after, FULL_FRAME, config())
    assert frameimage.change_fraction(first, second, 16) == 0.0
    assert frameimage.change_fraction(first, second, 5) == pytest.approx(1.0)


def test_the_crop_is_what_gets_measured(tmp_path: Path) -> None:
    """The same frame reads differently once the webcam column is excluded."""
    path = write_png(tmp_path / "layout.png", meeting_frame(bright=True))
    uncropped = frameimage.measure_frame(path, FULL_FRAME, config())
    region = frameimage.CropRegion(right=COLUMN_X / WIDTH, bottom=TASKBAR_Y / HEIGHT)
    cropped = frameimage.measure_frame(path, region, config())
    assert cropped.white_fraction == pytest.approx(1.0)
    assert uncropped.white_fraction < cropped.white_fraction


def test_an_unreadable_frame_raises_a_named_error(tmp_path: Path) -> None:
    missing = tmp_path / "gone.png"
    with pytest.raises(frameimage.FrameImageError, match="gone.png"):
        frameimage.measure_frame(missing, FULL_FRAME, config())

    corrupt = tmp_path / "corrupt.png"
    corrupt.write_bytes(b"not an image at all")
    with pytest.raises(frameimage.FrameImageError, match="corrupt.png"):
        frameimage.measure_frame(corrupt, FULL_FRAME, config())


# --- the share-region survey ----------------------------------------------


def test_detect_finds_the_webcam_column_and_the_taskbar(tmp_path: Path) -> None:
    region = frameimage.detect_share_region(survey_frames(tmp_path), config())
    assert region.detected is True
    assert region.right == pytest.approx(COLUMN_X / WIDTH)
    assert region.bottom == pytest.approx(TASKBAR_Y / HEIGHT)
    assert (region.left, region.top) == (0.0, 0.0)
    assert region.method == "webcam-column+bottom-strip"


def test_the_survey_spans_the_recording_rather_than_its_opening(tmp_path: Path) -> None:
    """§2's claim is that the layout holds across the *whole* hour."""
    frames = survey_frames(tmp_path, count=40)
    region = frameimage.detect_share_region(frames, config(crop_survey_frames=4))
    assert region.detected is True
    assert region.right == pytest.approx(COLUMN_X / WIDTH)


def test_a_too_narrow_share_region_is_refused(tmp_path: Path) -> None:
    """A mostly-dark frame is a dark screen, not an enormous webcam column."""
    paths = []
    for index in range(4):
        image = solid((0, 0, 0))
        image.paste((255, 255, 255), (0, 0, WIDTH // 5, HEIGHT if index % 2 else 1))
        paths.append(write_png(tmp_path / f"narrow-{index}.png", image))
    region = frameimage.detect_share_region(paths, config())
    assert region.detected is False
    assert region.right == 1.0


def test_a_uniform_frame_reports_inconclusive(tmp_path: Path) -> None:
    paths = [write_png(tmp_path / f"flat-{i}.png", solid((128, 128, 128))) for i in range(4)]
    region = frameimage.detect_share_region(paths, config())
    assert region.detected is False
    assert region.is_full_frame
    assert region.method == frameimage.METHOD_INCONCLUSIVE


def test_a_bright_right_edge_is_not_a_webcam_column(tmp_path: Path) -> None:
    """The I/O matrix's "no webcam column": full frame, recorded as undetected."""
    paths = [write_png(tmp_path / f"bright-{i}.png", solid((255, 255, 255))) for i in range(4)]
    region = frameimage.detect_share_region(paths, config())
    assert region.detected is False
    assert region.right == 1.0


def test_no_webcam_column_does_not_crop_a_static_bottom_band(tmp_path: Path) -> None:
    """An inconclusive layout keeps its static footer as evidence (I/O matrix)."""
    paths = []
    for index in range(4):
        image = solid((255, 255, 255))
        image.paste((0 if index % 2 else 180,) * 3, (0, 0, COLUMN_X, TASKBAR_Y))
        paths.append(write_png(tmp_path / f"no-column-{index}.png", image))

    region = frameimage.detect_share_region(paths, config())

    assert region.is_full_frame
    assert region.detected is False
    assert region.method == frameimage.METHOD_INCONCLUSIVE


def test_no_frames_yields_the_full_frame(tmp_path: Path) -> None:
    region = frameimage.detect_share_region([], config())
    assert region.is_full_frame and region.detected is False


def test_a_single_survey_frame_finds_no_taskbar(tmp_path: Path) -> None:
    """One frame has no temporal range, so the row survey has no signal.

    Absence of evidence must not become a 12 % crop off the bottom.
    """
    [path] = survey_frames(tmp_path, count=1)
    region = frameimage.detect_share_region([path], config())
    assert region.bottom == 1.0
    assert region.method == "webcam-column"


def test_the_bottom_strip_is_capped(tmp_path: Path) -> None:
    region = frameimage.detect_share_region(
        survey_frames(tmp_path), config(crop_max_bottom_strip=0.02)
    )
    assert region.bottom == pytest.approx(0.98)


# --- OCR geometry recomputed on the region ---------------------------------


def block(x: float, y: float, width: float, height: float) -> dict[str, float]:
    return {"x": x, "y": y, "width": width, "height": height}


def test_crop_blocks_drops_boxes_outside_the_region() -> None:
    region = frameimage.CropRegion(right=0.875, bottom=0.95)
    blocks = [block(0.1, 0.1, 0.2, 0.05), block(0.90, 0.2, 0.05, 0.05)]
    count, density, mean_height = frameimage.crop_blocks(blocks, region)
    assert count == 1
    # Renormalized to the region, so a rule tuned on full frames still means
    # the same thing: 0.2/0.875 wide by 0.05/0.95 high.
    assert density == pytest.approx((0.2 / 0.875) * (0.05 / 0.95))
    assert mean_height == pytest.approx(0.05 / 0.95)


def test_crop_blocks_clips_a_box_that_straddles_the_boundary() -> None:
    region = frameimage.CropRegion(right=0.5, bottom=1.0)
    count, density, _ = frameimage.crop_blocks([block(0.4, 0.0, 0.4, 0.1)], region)
    assert count == 1
    assert density == pytest.approx((0.1 / 0.5) * 0.1)


def test_crop_blocks_handles_no_ocr_row() -> None:
    assert frameimage.crop_blocks(None, FULL_FRAME) == (0, 0.0, 0.0)
    assert frameimage.crop_blocks([], FULL_FRAME) == (0, 0.0, 0.0)


# --- the downscale every production frame goes through ---------------------


def test_a_full_size_frame_measures_the_same_as_its_analysis_scale_twin(
    tmp_path: Path,
) -> None:
    """Real frames are 1920x1080; every test frame is already 320 wide.

    That leaves the resize in `_load_analysis_image` — the code path 100 % of
    production frames take and 0 % of the others — unexercised. Collapsing it
    to something absurd (one pixel tall) kept the rest of the suite green, so
    this asserts the downscale preserves what the survey and the classifier
    read off a frame.
    """
    settings = config()
    small = meeting_frame(bright=True)
    large = small.resize((WIDTH * 4, HEIGHT * 4), Image.NEAREST)
    small_path = write_png(tmp_path / "small.png", small)
    large_path = write_png(tmp_path / "large.png", large)

    small_measured = frameimage.measure_frame(small_path, FULL_FRAME, settings)
    large_measured = frameimage.measure_frame(large_path, FULL_FRAME, settings)

    assert large_measured.gray.size == small_measured.gray.size, (
        "the downscale must land on the analysis scale, aspect preserved"
    )
    assert large_measured.white_fraction == pytest.approx(
        small_measured.white_fraction, abs=0.02
    )
    assert large_measured.mean_saturation == pytest.approx(
        small_measured.mean_saturation, abs=0.02
    )


def test_the_survey_finds_the_same_region_at_full_size(tmp_path: Path) -> None:
    """The crop survey is scale-invariant, or the fractions it stores are wrong."""
    settings = config()
    small_paths = [
        write_png(tmp_path / f"s{index}.png", meeting_frame(index % 2 == 0))
        for index in range(8)
    ]
    large_paths = [
        write_png(
            tmp_path / f"l{index}.png",
            meeting_frame(index % 2 == 0).resize(
                (WIDTH * 4, HEIGHT * 4), Image.NEAREST
            ),
        )
        for index in range(8)
    ]

    small_region = frameimage.detect_share_region(small_paths, settings)
    large_region = frameimage.detect_share_region(large_paths, settings)

    assert large_region.detected is small_region.detected is True
    assert large_region.right == pytest.approx(small_region.right, abs=0.01)
    assert large_region.bottom == pytest.approx(small_region.bottom, abs=0.01)
