"""`screens` — group frames into captures, write screenshots, upsert Screens.

Two stores, two different idempotence rules, both from AD-5/AD-11:

* **Screenshots are this meeting's evidence.** A rerun replaces the meeting's
  `screenshot` rows, its whole ``screenshots/`` subtree, and its
  `meeting_crop` row, using the same staging/backup/atomic-swap dance `frames`
  uses, so a *failed* rerun leaves the previous files and rows intact.
* **Screens are cross-meeting entities.** They are upserted by identity key
  and never deleted or truncated by a rerun — that is what gives one screen
  lineage across the meetings it appears in.

Every decision (where a capture starts, which frame represents it, what view
type it is, what its identity key is) lives in
:mod:`meetingminer.pipeline.screens`, with the thresholds coming from
``config.yaml``. This module is the I/O around those decisions, and story 1.11
moved the pixel measuring into :mod:`meetingminer.pipeline.frameimage` so the
decision core still sees nothing but plain numbers.

The crop is a precondition on the change-detection *input* only. The stored
screenshot stays the full representative frame: cropping the evidence would
throw away the webcam column permanently, and NFR8 biases toward preserving
what a reviewer might need (`capture-measurements.md` §2).
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from meetingminer.config import ScreensConfig
from meetingminer.pipeline import frameimage
from meetingminer.pipeline import screens as core
from meetingminer.pipeline.outputs import OutputDirSwap
from meetingminer.pipeline.stage import StageContext, StageError

SCREENSHOTS_SUBDIR = "screenshots"
SCREENSHOT_FILENAME_TEMPLATE = "screenshot-%04d%s"
DEFAULT_IMAGE_SUFFIX = ".jpg"

_SELECT_FRAMES = """
SELECT f.id, f.offset_ms, f.path,
       COALESCE(o.normalized_text, ''),
       COALESCE(o.blocks, '[]'::jsonb)
FROM frame f
LEFT JOIN frame_ocr o ON o.frame_id = f.id
WHERE f.meeting_id = %s
ORDER BY f.offset_ms
"""

_INSERT_SCREENSHOT = """
INSERT INTO screenshot (
    meeting_id, screen_id, ordinal, start_offset_ms, end_offset_ms,
    frame_count, representative_frame_id, path, view_type, capture_cues,
    classification_tags
) VALUES (
    %(meeting_id)s, %(screen_id)s, %(ordinal)s, %(start_offset_ms)s, %(end_offset_ms)s,
    %(frame_count)s, %(representative_frame_id)s, %(path)s, %(view_type)s, %(capture_cues)s,
    %(classification_tags)s
)
"""

_INSERT_CROP = """
INSERT INTO meeting_crop (
    meeting_id, left_fraction, top_fraction, right_fraction, bottom_fraction,
    detected, method
) VALUES (%s, %s, %s, %s, %s, %s, %s)
"""


@dataclass(frozen=True)
class _FrameRow:
    """One `frame` row plus whatever the `ocr` stage recorded for it."""

    frame_id: UUID
    offset_ms: int
    relative_path: str
    normalized_text: str
    blocks: list[dict[str, Any]]


def _load_frame_rows(ctx: StageContext) -> list[_FrameRow]:
    """This meeting's frames, in offset order, with their raw OCR blocks.

    The block *geometry* is deliberately not read from `frame_ocr`'s summary
    columns any more: those describe the whole frame, and the view-type rules
    now run on the share region alone, so the boxes are re-summarized against
    the crop in :func:`frameimage.crop_blocks`. Nothing about the `ocr`
    stage's output changes — this is a different reading of the same rows.
    """
    rows = ctx.conn.execute(_SELECT_FRAMES, (ctx.meeting_id,)).fetchall()
    return [
        _FrameRow(
            frame_id=frame_id,
            offset_ms=int(offset_ms),
            relative_path=relative_path,
            normalized_text=normalized,
            blocks=list(blocks or ()),
        )
        for frame_id, offset_ms, relative_path, normalized, blocks in rows
    ]


def _detect_crop(
    ctx: StageContext, rows: list[_FrameRow], config: ScreensConfig
) -> frameimage.CropRegion:
    """Survey this recording once for its share region (§2)."""
    paths = [Path(ctx.content_root) / row.relative_path for row in rows]
    try:
        return frameimage.detect_share_region(paths, config)
    except frameimage.FrameImageError as exc:
        raise StageError(f"{exc} — rerun the frames stage") from exc


class _RegionChange:
    """Measures the cropped region of one frame against the emitted shot.

    This is the callable :func:`core.segment_captures` asks its cue question
    through. It cannot be a per-frame number: *which* frame was emitted is a
    decision the core has not made when the facts are built, and
    `capture-measurements.md` §2 measured the comparison specifically against
    the last emitted shot — the floor grows with time since the emission, so
    a chain of consecutive-frame deltas is not the same quantity.

    Only the reference frame's decode is held. The frame in hand is decoded
    per call, which costs one extra pass over the recording; §1 established
    that decode is not a constraint (211x realtime), and bounded memory over a
    two-hour recording is worth more than the nine seconds.
    """

    def __init__(
        self,
        ctx: StageContext,
        paths: dict[UUID, str],
        region: frameimage.CropRegion,
        config: ScreensConfig,
    ) -> None:
        self._ctx = ctx
        self._paths = paths
        self._region = region
        self._config = config
        self._reference_id: UUID | None = None
        self._reference: frameimage.FrameMeasurement | None = None

    def _measure(self, frame_id: UUID) -> frameimage.FrameMeasurement:
        return _measure_one(self._ctx, self._paths[frame_id], self._region, self._config)

    def __call__(self, emitted: core.FrameFacts, current: core.FrameFacts) -> float:
        if emitted.frame_id != self._reference_id:
            self._reference_id = emitted.frame_id  # type: ignore[assignment]
            self._reference = self._measure(emitted.frame_id)  # type: ignore[arg-type]
        return frameimage.change_fraction(
            self._reference,
            self._measure(current.frame_id),  # type: ignore[arg-type]
            self._config.pixel_diff_threshold,
        )


def _measure_one(
    ctx: StageContext,
    relative_path: str,
    region: frameimage.CropRegion,
    config: ScreensConfig,
) -> frameimage.FrameMeasurement:
    """Decode and measure one frame, naming the file if it will not open."""
    try:
        return frameimage.measure_frame(
            Path(ctx.content_root) / relative_path, region, config
        )
    except frameimage.FrameImageError as exc:
        raise StageError(f"{exc} — rerun the frames stage") from exc


def _measure_frames(
    ctx: StageContext,
    rows: list[_FrameRow],
    region: frameimage.CropRegion,
    config: ScreensConfig,
) -> list[core.FrameFacts]:
    """Turn each frame into the plain numbers the decision core consumes.

    Only the previous frame's measurement is held, so a 1700-frame meeting
    costs one decoded analysis-scale image at a time rather than all of them.
    """
    facts: list[core.FrameFacts] = []
    previous: frameimage.FrameMeasurement | None = None
    for row in rows:
        measurement = _measure_one(ctx, row.relative_path, region, config)
        block_count, text_density, mean_block_height = frameimage.crop_blocks(
            row.blocks, region
        )
        facts.append(
            core.FrameFacts(
                frame_id=row.frame_id,
                offset_ms=row.offset_ms,
                normalized_text=row.normalized_text,
                block_count=block_count,
                text_density=text_density,
                mean_block_height=mean_block_height,
                change_fraction_vs_previous=frameimage.change_fraction(
                    previous, measurement, config.pixel_diff_threshold
                ),
                white_fraction=measurement.white_fraction,
                mean_saturation=measurement.mean_saturation,
            )
        )
        previous = measurement
    return facts


class _ScreenUpserter:
    """Resolves each capture to a `screen` row, creating one only when needed.

    The existing screens are read once and the cache is updated as rows are
    written, so two captures of the same screen inside one meeting converge on
    one row without a second query.

    Two kinds of hit are deliberately handled differently. An *exact* identity
    key is this screen, so the row is upserted — a meeting-scoped screen whose
    segmentation changed between runs must not keep the first run's signature
    and view type forever. A *lineage* hit is a different key pointing at the
    same screen; that row is left alone, because overwriting a corpus-wide
    screen's signature with one meeting's variant would let it drift.
    """

    def __init__(self, ctx: StageContext, config: ScreensConfig) -> None:
        self._ctx = ctx
        self._config = config
        # identity_key -> the row that actually carries that key.
        self._by_key: dict[str, UUID] = {}
        # identity_key -> a row reached by lineage, which carries a different
        # key. Kept apart so a later capture never upserts against it.
        self._lineage: dict[str, UUID] = {}
        self._signatures: list[tuple[UUID, str]] = []
        for screen_id, identity_key, signature in ctx.conn.execute(
            "SELECT id, identity_key, signature FROM screen"
        ).fetchall():
            self._by_key[identity_key] = screen_id
            if not core.is_scoped_identity(identity_key):
                self._signatures.append((screen_id, signature))
        self.reused = 0
        self.created = 0

    def resolve(self, identity_key: str, signature: str, view_type: str) -> UUID:
        mapped = self._lineage.get(identity_key)
        if mapped is not None:
            self.reused += 1
            return mapped

        existed = identity_key in self._by_key
        if not existed and not core.is_scoped_identity(identity_key):
            # A signature that did not match exactly may still be the same
            # screen re-rendered (a changed clock, one edited bullet).
            match = core.best_lineage_match(signature, self._signatures, self._config)
            if match is not None:
                self._lineage[identity_key] = match
                self.reused += 1
                return match

        # A genuine upsert, not a bare INSERT: `identity_key` is UNIQUE, so a
        # row this transaction did not read would otherwise abort the whole
        # stage on a unique violation, and an exact-key hit would keep stale
        # values. The DO UPDATE is also what makes the screen_set_updated_at
        # trigger reachable.
        screen_id = self._ctx.conn.execute(
            "INSERT INTO screen (identity_key, signature, view_type)"
            " VALUES (%s, %s, %s)"
            " ON CONFLICT (identity_key) DO UPDATE SET"
            "   signature = EXCLUDED.signature,"
            "   view_type = EXCLUDED.view_type"
            " RETURNING id",
            (identity_key, signature, view_type),
        ).fetchone()[0]
        self._by_key[identity_key] = screen_id
        if not existed:
            if not core.is_scoped_identity(identity_key):
                self._signatures.append((screen_id, signature))
            self.created += 1
        else:
            self.reused += 1
        return screen_id


def _captures_per_minute(ctx: StageContext, capture_count: int) -> float | None:
    """Captures per minute of recording, or ``None`` when duration is unknown.

    Duration comes from `meeting_media`, which the `probe` stage wrote. A
    transcript-only or unprobed meeting simply has no rate to report — that is
    ``None``, never a fabricated number.
    """
    row = ctx.conn.execute(
        "SELECT duration_ms FROM meeting_media WHERE meeting_id = %s", (ctx.meeting_id,)
    ).fetchone()
    if row is None or row[0] is None or row[0] <= 0:
        return None
    return round(capture_count / (row[0] / 60_000.0), 3)


def _tag_counts(captures: list[core.Capture]) -> dict[str, int]:
    """How many captures carry each classification tag, for the stage log.

    Zero-valued keys are kept: a run that resolved every gallery and settled
    every capture should say so, rather than being indistinguishable from a
    run whose tagging quietly stopped working.
    """
    counts = {core.TAG_LIKELY_TRANSITION: 0, core.TAG_AVATAR_GALLERY_UNRESOLVED: 0}
    for capture in captures:
        for tag in capture.tags:
            counts[tag] = counts.get(tag, 0) + 1
    return counts


def run(ctx: StageContext) -> None:
    config = ctx.config.settings.pipeline.screens
    rows = _load_frame_rows(ctx)

    # Replace, never accumulate — including the empty case, so a rerun over a
    # meeting whose frames vanished clears the screenshots that described them
    # and the crop they were detected against.
    ctx.conn.execute("DELETE FROM screenshot WHERE meeting_id = %s", (ctx.meeting_id,))
    ctx.conn.execute("DELETE FROM meeting_crop WHERE meeting_id = %s", (ctx.meeting_id,))

    if not rows:
        # Publish an empty replacement rather than returning after the row
        # deletion. A prior populated run may have left JPEGs in this
        # directory; leaving them behind would make disk disagree with the
        # now-empty screenshot table. Keeping the empty directory lets the
        # same swap/rollback protocol protect the old output until commit.
        swap = OutputDirSwap(ctx, SCREENSHOTS_SUBDIR)
        swap.open_staging()
        swap.publish()
        swap.arm_hooks()
        # `frames` legitimately completed with nothing to group. Zero captures
        # is a result, not a failure. The same fields are emitted as the
        # non-empty path so a log consumer never has to special-case zero.
        ctx.log(
            "stage.screens.captured",
            meeting_id=ctx.meeting_id,
            frame_count=0,
            capture_count=0,
            screens_created=0,
            screens_reused=0,
            captures_per_minute=None,
            crop=None,
            crop_detected=False,
            crop_method=None,
            tags=_tag_counts([]),
            directory=ctx.relative_path(swap.target),
        )
        return

    # Detect-once geometry (§2): one survey for the recording, then every
    # frame measured through it.
    region = _detect_crop(ctx, rows, config)
    frames = _measure_frames(ctx, rows, region, config)
    frame_paths = {row.frame_id: row.relative_path for row in rows}
    captures = core.segment_captures(
        frames, config, _RegionChange(ctx, frame_paths, region, config)
    )

    ctx.conn.execute(
        _INSERT_CROP,
        (
            ctx.meeting_id,
            region.left,
            region.top,
            region.right,
            region.bottom,
            region.detected,
            region.method,
        ),
    )

    swap = OutputDirSwap(ctx, SCREENSHOTS_SUBDIR)
    staging_dir = swap.open_staging()
    filenames: list[str] = []
    try:
        for capture in captures:
            source = Path(ctx.content_root) / frame_paths[capture.representative.frame_id]
            filename = SCREENSHOT_FILENAME_TEMPLATE % (
                capture.ordinal,
                source.suffix or DEFAULT_IMAGE_SUFFIX,
            )
            # The *full* frame is copied, not the cropped analysis image: the
            # crop is an input to the decision, and the evidence a reviewer
            # opens must still show the whole meeting window (§2, NFR8).
            # Copied out of the content root's own frames, never out of the
            # drop: the drop directory stays read-only after intake (AD-13).
            shutil.copyfile(source, staging_dir / filename)
            filenames.append(filename)
    except OSError as exc:
        swap.discard()
        raise StageError(f"could not write screenshot for meeting {ctx.meeting_id}: {exc}") from exc

    swap.publish()

    try:
        upserter = _ScreenUpserter(ctx, config)
        for capture, filename in zip(captures, filenames):
            identity_key = core.identity_key_for(
                capture.signature, ctx.meeting_id, capture.ordinal, config
            )
            screen_id = upserter.resolve(identity_key, capture.signature, capture.view_type)
            ctx.conn.execute(
                _INSERT_SCREENSHOT,
                {
                    "meeting_id": ctx.meeting_id,
                    "screen_id": screen_id,
                    "ordinal": capture.ordinal,
                    "start_offset_ms": capture.start_offset_ms,
                    "end_offset_ms": capture.end_offset_ms,
                    "frame_count": capture.frame_count,
                    "representative_frame_id": capture.representative.frame_id,
                    "path": ctx.relative_path(swap.target / filename),
                    "view_type": capture.view_type,
                    "capture_cues": list(capture.cues),
                    "classification_tags": list(capture.tags),
                },
            )
    except Exception:
        swap.restore()
        raise
    swap.arm_hooks()

    ctx.log(
        "stage.screens.captured",
        meeting_id=ctx.meeting_id,
        frame_count=len(frames),
        capture_count=len(captures),
        screens_created=upserter.created,
        screens_reused=upserter.reused,
        # NFR2's over-capture guardrail is one capture per minute of meeting.
        # The stage does not enforce it — Epic 5's harness owns that check —
        # but logging the rate makes the tension visible per meeting instead
        # of only in an after-the-fact query.
        captures_per_minute=_captures_per_minute(ctx, len(captures)),
        # The crop is logged because it is the input every capture decision
        # was made against: a density number without it cannot be re-read.
        crop=[region.left, region.top, region.right, region.bottom],
        crop_detected=region.detected,
        crop_method=region.method,
        tags=_tag_counts(captures),
        directory=ctx.relative_path(swap.target),
    )
