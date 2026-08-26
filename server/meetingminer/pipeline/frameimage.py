"""Pixel facts for the `screens` stage — the only module that opens a frame.

`capture-measurements.md` §2 is the reason this exists: an uncropped frame has
no usable dynamic range for change detection, because the webcam column keeps
moving and decorrelates over minutes, so *any* whole-frame proxy for change
(encoded byte size included) measures the participant tiles as much as the
shared screen. Cropping is therefore a precondition on the change-detection
*input*, never on the stored screenshot.

The layout §2 measured is stable for a whole recording — shared screen on the
left, a fixed webcam column starting around x = 87.8 %, a taskbar in the
bottom few percent — so the region is surveyed **once per recording** here
rather than looked for per frame, and never by a model or a template match.

Three per-frame numbers come out of this module, all measured on the cropped
region at ``analysis_width`` scale:

* ``white_fraction`` and ``mean_saturation`` — the pair §4 showed separates
  camera/gallery video from screen share with no model at all.
* ``change_fraction`` between two frames — the signal segmentation runs on.

Pillow is imported here and nowhere else in the server, which is what keeps
:mod:`meetingminer.pipeline.screens` a pure function over plain numbers.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from PIL import Image, ImageChops, ImageStat, UnidentifiedImageError

from meetingminer.config import ScreensConfig

# What `method` records when the survey found nothing to crop.
METHOD_INCONCLUSIVE = "inconclusive"
METHOD_WEBCAM_COLUMN = "webcam-column"
METHOD_BOTTOM_STRIP = "bottom-strip"


class FrameImageError(RuntimeError):
    """A sampled frame image is missing, truncated, or not an image.

    Named so the `screens` stage can turn it into a recorded
    :class:`~meetingminer.pipeline.stage.StageError` that tells the operator
    to rerun `frames`, rather than letting a bare ``OSError`` escape.
    """


@dataclass(frozen=True)
class CropRegion:
    """The share region, as fractions of the full frame, origin top left.

    ``detected`` is specifically *did the survey find the webcam column* —
    the defining feature of §2's two-part layout. A recording whose right
    edge is as bright as the share area gets the full-frame fallback and
    ``detected=False``, which is recorded rather than hidden. ``method``
    names whatever the survey did find, for the same reason.
    """

    left: float = 0.0
    top: float = 0.0
    right: float = 1.0
    bottom: float = 1.0
    detected: bool = False
    method: str = METHOD_INCONCLUSIVE

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.bottom - self.top

    @property
    def is_full_frame(self) -> bool:
        return (self.left, self.top, self.right, self.bottom) == (0.0, 0.0, 1.0, 1.0)

    def pixel_box(self, width: int, height: int) -> tuple[int, int, int, int]:
        """This region as a Pillow crop box, never empty and never off-image."""
        left = max(0, min(width - 1, round(self.left * width)))
        top = max(0, min(height - 1, round(self.top * height)))
        right = max(left + 1, min(width, round(self.right * width)))
        bottom = max(top + 1, min(height, round(self.bottom * height)))
        return (left, top, right, bottom)


class FrameMeasurement:
    """One frame's cropped pixel facts, plus the pixels a diff needs.

    The cropped grayscale image is kept because ``change_fraction`` compares
    consecutive frames; it is at analysis scale, so a whole meeting's worth is
    a few megabytes, not a few gigabytes.
    """

    __slots__ = ("white_fraction", "mean_saturation", "gray")

    def __init__(self, white_fraction: float, mean_saturation: float, gray: Image.Image) -> None:
        self.white_fraction = white_fraction
        self.mean_saturation = mean_saturation
        self.gray = gray


def _load_analysis_image(path: Path | str, analysis_width: int) -> Image.Image:
    """Decode one frame down to ``analysis_width``, as RGB.

    ``draft`` lets the JPEG decoder throw away DCT coefficients instead of
    decoding full resolution and then discarding it; §1 already established
    that decode cost is not a feasibility constraint, so this is only about
    keeping a 1727-frame meeting comfortable rather than about making it
    possible.
    """
    try:
        with Image.open(path) as handle:
            # Height 1 so only the width constrains the draft scale.
            handle.draft("RGB", (analysis_width, 1))
            image = handle.convert("RGB")
    except (OSError, ValueError, UnidentifiedImageError) as exc:
        raise FrameImageError(f"could not read frame image {path}: {exc}") from exc
    if image.width != analysis_width:
        height = max(1, round(image.height * analysis_width / image.width))
        image = image.resize((analysis_width, height), Image.BILINEAR)
    return image


def white_fraction(gray: Image.Image, white_pixel_level: int) -> float:
    """Fraction of pixels brighter than ``white_pixel_level`` (§4's "white")."""
    histogram = gray.histogram()
    total = sum(histogram)
    if not total:  # pragma: no cover - pixel_box never yields an empty crop
        return 0.0
    return sum(histogram[white_pixel_level + 1 :]) / total


def mean_saturation(image: Image.Image) -> float:
    """Mean HSV saturation of an RGB image, as a 0-1 fraction (§4)."""
    return ImageStat.Stat(image.convert("HSV").getchannel("S")).mean[0] / 255.0


def measure_frame(
    path: Path | str, region: CropRegion, config: ScreensConfig
) -> FrameMeasurement:
    """Decode one frame and measure it over ``region`` only."""
    image = _load_analysis_image(path, config.analysis_width)
    cropped = image.crop(region.pixel_box(image.width, image.height))
    gray = cropped.convert("L")
    return FrameMeasurement(
        white_fraction=white_fraction(gray, config.white_pixel_level),
        mean_saturation=mean_saturation(cropped),
        gray=gray,
    )


def change_fraction(
    previous: FrameMeasurement | None,
    current: FrameMeasurement,
    pixel_diff_threshold: int,
) -> float:
    """Fraction of the region's pixels that moved by at least the threshold.

    ``None`` for ``previous`` is the first frame of a recording: nothing has
    changed yet, so it is 0.0 rather than a fabricated 1.0.
    """
    if previous is None:
        return 0.0
    if previous.gray.size != current.gray.size:  # pragma: no cover - one crop per meeting
        return 1.0
    difference = ImageChops.difference(previous.gray, current.gray)
    histogram = difference.histogram()
    total = sum(histogram)
    if not total:  # pragma: no cover - pixel_box never yields an empty crop
        return 0.0
    return sum(histogram[pixel_diff_threshold:]) / total


def crop_blocks(
    blocks: Iterable[Mapping[str, Any]] | None, region: CropRegion
) -> tuple[int, float, float]:
    """Recompute ``(block_count, text_density, mean_block_height)`` on a region.

    ``blocks`` is ``frame_ocr.blocks`` — the shape
    :meth:`~meetingminer.adapters.ocr.port.OcrBlock.as_json` writes: ``x``,
    ``y``, ``width``, ``height`` as fractions of the *full* frame with the
    origin top left. Each box is clipped to the region and renormalized to it,
    so a view-type rule tuned on full frames keeps meaning the same thing once
    the webcam column stops contributing boxes. Overlapping boxes are counted
    twice and the total clamped to 1.0, exactly as ``OcrResult.text_density``
    does — this is the same coarse "how busy is this frame" signal.
    """
    if blocks is None or region.width <= 0 or region.height <= 0:
        return 0, 0.0, 0.0
    count = 0
    density = 0.0
    height_total = 0.0
    for block in blocks:
        x = float(block.get("x", 0.0) or 0.0)
        y = float(block.get("y", 0.0) or 0.0)
        left = max(x, region.left)
        top = max(y, region.top)
        right = min(x + float(block.get("width", 0.0) or 0.0), region.right)
        bottom = min(y + float(block.get("height", 0.0) or 0.0), region.bottom)
        if right <= left or bottom <= top:
            continue
        count += 1
        box_width = (right - left) / region.width
        box_height = (bottom - top) / region.height
        density += box_width * box_height
        height_total += box_height
    if not count:
        return 0, 0.0, 0.0
    return count, min(density, 1.0), height_total / count


def _survey_paths(paths: Sequence[Path | str], wanted: int) -> list[Path | str]:
    """``wanted`` frames spread evenly across the recording, in order.

    Evenly spread rather than the first N: §2's finding is that the layout
    holds *across the full hour*, and a survey confined to the opening minute
    could not have shown that.
    """
    if not paths:
        return []
    if len(paths) <= wanted:
        return list(paths)
    step = len(paths) / wanted
    return [paths[min(len(paths) - 1, int(index * step))] for index in range(wanted)]


def detect_share_region(
    paths: Sequence[Path | str], config: ScreensConfig
) -> CropRegion:
    """Survey a recording once for its share region (§2's detect-once geometry).

    Two independent surveys, each on a measured gap rather than a guess:

    * **Columns.** The webcam column is dark where the share area is bright:
      mean white fraction ~0.62 left of the boundary, 0.00-0.13 right of it.
      Scanning in from the right edge while columns stay under
      ``crop_column_white_max`` finds the boundary. Saturation is *not* used
      here — it did not separate the column in the measured recording — it is
      used at frame level for view classification, which is where §4 measured
      it.
    * **Rows.** The taskbar is the strip that does not change over time:
      temporal range ~48 against ~200 for live rows. Scanning up from the
      bottom while rows stay under ``crop_row_static_range_max`` finds it, and
      ``crop_max_bottom_strip`` caps how much it may take.

    A boundary that would leave less than ``crop_min_region_width`` of the
    frame is refused — that is a dark screen, not a webcam column — and the
    full frame is used with ``detected=False``.
    """
    survey = _survey_paths(paths, config.crop_survey_frames)
    if not survey:
        return CropRegion()

    # The survey's grayscale images are held, not re-derived: the row scan has
    # to run *after* the column boundary is known (see below), and 24 frames
    # at analysis scale is well under a megabyte.
    grays: list[Image.Image] = []
    column_white: list[float] | None = None
    for path in survey:
        gray = _load_analysis_image(path, config.analysis_width).convert("L")
        if grays and gray.size != grays[0].size:
            raise FrameImageError(
                f"survey frame {path} is {gray.width}x{gray.height} but the first"
                f" survey frame is {grays[0].width}x{grays[0].height} — the crop"
                " survey needs one geometry per recording"
            )
        grays.append(gray)
        # A 0/255 mask averaged down to one row is the per-column white
        # fraction. `tobytes` on a single-row "L" image is the raw byte per
        # pixel, in order — no per-pixel Python loop over the image.
        mask = gray.point(lambda value: 255 if value > config.white_pixel_level else 0)
        columns = [value / 255.0 for value in mask.resize((gray.width, 1), Image.BOX).tobytes()]
        column_white = (
            columns
            if column_white is None
            else [total + value for total, value in zip(column_white, columns)]
        )

    if column_white is None:  # pragma: no cover - survey is non-empty above
        return CropRegion()
    surveyed = len(grays)
    column_white = [total / surveyed for total in column_white]

    right, detected = _column_boundary(column_white, config)
    if not detected:
        # The I/O contract treats a layout without the defining webcam column
        # as inconclusive. A static footer alone is not enough evidence that
        # it is disposable chrome, so keep the complete frame for capture
        # decisions rather than silently excluding bottom-of-screen content.
        return CropRegion()

    # Rows are scanned on the *column-cropped* frame. A live webcam column
    # moves in every frame, so measuring row ranges across the full width
    # would put that motion into every row's range and hide a genuinely
    # static taskbar. It did not show here — this recording's tiles are
    # mostly static avatars — but it is the case §2 measured, where the
    # column decorrelates over minutes.
    row_means = [
        list(
            gray.crop((0, 0, max(1, round(right * gray.width)), gray.height))
            .resize((1, gray.height), Image.BOX)
            .tobytes()
        )
        for gray in grays
    ]
    bottom = 1.0 - _bottom_strip(row_means, config)

    method = "+".join(
        part
        for part in (
            METHOD_WEBCAM_COLUMN if detected else "",
            METHOD_BOTTOM_STRIP if bottom < 1.0 else "",
        )
        if part
    )
    return CropRegion(
        left=0.0,
        top=0.0,
        right=right,
        bottom=bottom,
        detected=detected,
        method=method or METHOD_INCONCLUSIVE,
    )


def _column_boundary(column_white: Sequence[float], config: ScreensConfig) -> tuple[float, bool]:
    """Where the dark webcam column starts, as a fraction, and whether it exists."""
    width = len(column_white)
    boundary = width
    while boundary > 0 and column_white[boundary - 1] <= config.crop_column_white_max:
        boundary -= 1
    if boundary == width:
        return 1.0, False  # no dim column at the right edge
    right = boundary / width
    if right < config.crop_min_region_width:
        # Refusing here rather than cropping: a band this narrow is a dark
        # screen or a blank recording, and cropping to it would blind change
        # detection to most of the meeting.
        return 1.0, False
    return right, True


def _bottom_strip(row_means: Sequence[Sequence[float]], config: ScreensConfig) -> float:
    """Height of the static bottom strip, as a fraction, capped by config."""
    height = len(row_means[0])
    if height == 0:  # pragma: no cover - an image always has rows
        return 0.0
    ranges = [
        max(frame[row] for frame in row_means) - min(frame[row] for frame in row_means)
        for row in range(height)
    ]
    boundary = height
    while boundary > 0 and ranges[boundary - 1] <= config.crop_row_static_range_max:
        boundary -= 1
    if boundary == 0:
        # Every row is static: one survey frame, or a still recording. That is
        # the absence of a signal, not a full-frame taskbar.
        return 0.0
    return min((height - boundary) / height, config.crop_max_bottom_strip)
