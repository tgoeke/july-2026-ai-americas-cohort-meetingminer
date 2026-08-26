"""`frames` — sample JPEGs from the recording under MM_CONTENT_ROOT (AD-3).

Idempotent in both stores it touches: a rerun deletes this meeting's frame
rows and replaces *only* ``meetings/<meeting_id>/frames/`` in the content
root, so stale files from a previous sampling interval cannot survive and no
other meeting is affected. The staging/backup/atomic-swap mechanics that make
a *failed* rerun leave the previous output intact live in
:class:`~meetingminer.pipeline.outputs.OutputDirSwap`, shared with `screens`.

Only the root-relative path is stored in the database — never the absolute
one, so relocating the content root never invalidates a row.
"""

from __future__ import annotations

from meetingminer.pipeline.media import MediaToolError, sample_frames, sampled_frame_offsets
from meetingminer.pipeline.outputs import OutputDirSwap
from meetingminer.pipeline.stage import StageContext, StageError

FRAMES_SUBDIR = "frames"


def run(ctx: StageContext) -> None:
    recording = ctx.drop.recording_path
    if recording is None:  # pragma: no cover - the runner skips video stages
        raise StageError(
            "frames needs a recording but the drop has none — a transcript-only"
            " drop should have skipped this stage"
        )

    swap = OutputDirSwap(ctx, FRAMES_SUBDIR)
    staging_dir = swap.open_staging()

    frames_config = ctx.config.settings.pipeline.frames
    interval = frames_config.interval_seconds

    try:
        produced = sample_frames(
            source=recording,
            output_dir=staging_dir,
            interval_seconds=interval,
            jpeg_quality=frames_config.jpeg_quality,
        )
        if not produced:
            raise MediaToolError(
                f"ffmpeg produced no frames from {recording} — the recording has no"
                " decodable video stream"
            )
        offsets = sampled_frame_offsets(recording, interval, len(produced))
        if len(offsets) != len(set(offsets)):
            raise MediaToolError(
                "sampled frame timestamps are not unique at millisecond precision"
            )
    except MediaToolError as exc:
        swap.discard()
        raise StageError(str(exc)) from exc

    swap.publish()
    frames_dir = swap.target

    try:
        # Replace, never accumulate: the rows for this meeting only (AD-11).
        ctx.conn.execute("DELETE FROM frame WHERE meeting_id = %s", (ctx.meeting_id,))
        ctx.conn.cursor().executemany(
            "INSERT INTO frame (meeting_id, offset_ms, path) VALUES (%s, %s, %s)",
            [
                (ctx.meeting_id, offsets[index], ctx.relative_path(frames_dir / path.name))
                for index, path in enumerate(produced)
            ],
        )
    except Exception:
        swap.restore()
        raise
    swap.arm_hooks()
    ctx.log(
        "stage.frames.sampled",
        meeting_id=ctx.meeting_id,
        frame_count=len(produced),
        interval_seconds=interval,
        directory=ctx.relative_path(frames_dir),
    )
