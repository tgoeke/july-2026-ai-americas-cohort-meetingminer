"""`probe` — record ffprobe media facts and provenance for the drop's recording.

Idempotent by construction: ``meeting_media`` is keyed by ``meeting_id``, so a
rerun upserts that one row and touches nothing belonging to another meeting.

The Meeting row itself is *not* minted here. `probe` is skipped for
transcript-only drops (AD-1), which would leave those jobs meeting-less; the
runner mints at claim time instead.

**The recording's provenance row (story 2.1a).** This is the first stage that
opens the recording, so it is where the file's identity is recorded:
``drop_relative_path`` anchored to ``MM_DROPS_ROOT`` and ``sha256`` of the
bytes, beside the ``size_bytes`` ffprobe already reported. Until now the
recording was the one piece of evidence with no row of its own — half its
served path was data and half a Python constant, and a substituted recording
was undetectable where a substituted transcript was not.

The size is corroborated rather than duplicated: ffprobe's reported size and
the file's own size must agree, and the stage fails when they do not, because
two numbers that can disagree are worse than one number that cannot.
"""

from __future__ import annotations

from meetingminer.domain.drops import sha256_and_size
from meetingminer.pipeline.media import MediaToolError, probe_media
from meetingminer.pipeline.stage import StageContext, StageError

_UPSERT = """
INSERT INTO meeting_media (
    meeting_id, duration_ms, container, size_bytes,
    video_codec, width, height, frame_rate, video_bit_rate,
    audio_codec, audio_channels, audio_sample_rate, audio_bit_rate,
    drop_relative_path, sha256
) VALUES (
    %(meeting_id)s, %(duration_ms)s, %(container)s, %(size_bytes)s,
    %(video_codec)s, %(width)s, %(height)s, %(frame_rate)s, %(video_bit_rate)s,
    %(audio_codec)s, %(audio_channels)s, %(audio_sample_rate)s, %(audio_bit_rate)s,
    %(drop_relative_path)s, %(sha256)s
)
ON CONFLICT (meeting_id) DO UPDATE SET
    duration_ms        = EXCLUDED.duration_ms,
    container          = EXCLUDED.container,
    size_bytes         = EXCLUDED.size_bytes,
    video_codec        = EXCLUDED.video_codec,
    width              = EXCLUDED.width,
    height             = EXCLUDED.height,
    frame_rate         = EXCLUDED.frame_rate,
    video_bit_rate     = EXCLUDED.video_bit_rate,
    audio_codec        = EXCLUDED.audio_codec,
    audio_channels     = EXCLUDED.audio_channels,
    audio_sample_rate  = EXCLUDED.audio_sample_rate,
    audio_bit_rate     = EXCLUDED.audio_bit_rate,
    drop_relative_path = EXCLUDED.drop_relative_path,
    sha256             = EXCLUDED.sha256
"""


def run(ctx: StageContext) -> None:
    recording = ctx.drop.recording_path
    if recording is None:  # pragma: no cover - the runner skips video stages
        raise StageError(
            "probe needs a recording but the drop has none — a transcript-only"
            " drop should have skipped this stage"
        )

    relative = ctx.drop_relative_path(recording)

    try:
        facts = probe_media(recording)
    except MediaToolError as exc:
        raise StageError(str(exc)) from exc

    try:
        digest, byte_size = sha256_and_size(recording)
    except OSError as exc:
        raise StageError(f"recording could not be read for checksumming: {exc}") from exc

    if facts.size_bytes is not None and facts.size_bytes != byte_size:
        # Not a warning: `size_bytes` is the number the api serves and the one
        # the checksum is corroborated by. A disagreement means the file
        # changed between ffprobe and this read, or that ffprobe read a
        # different file — either way nothing derived from it can be trusted.
        raise StageError(
            f"recording size disagrees: ffprobe reported {facts.size_bytes} bytes"
            f" and the file is {byte_size} bytes — the recording changed under"
            " the stage, or ffprobe read a different file"
        )

    previous = ctx.conn.execute(
        "SELECT drop_relative_path, sha256 FROM meeting_media WHERE meeting_id = %s",
        (ctx.meeting_id,),
    ).fetchone()

    if (
        previous is not None
        and previous[0] == relative
        and previous[1] is not None
        and previous[1] != digest
    ):
        # A sibling drop is a legitimate augmentation, but a different digest
        # at the same arrived-evidence path means write-once material was
        # substituted.  Crucially, fail *before* the upsert: the existing row
        # remains the provenance of the bytes this meeting was built from.
        raise StageError(
            "recording changed at the same drop-relative path: "
            f"{relative} (recorded sha256 {previous[1]}, found {digest})"
        )

    ctx.conn.execute(
        _UPSERT,
        {
            "meeting_id": ctx.meeting_id,
            "duration_ms": facts.duration_ms,
            "container": facts.container,
            "size_bytes": byte_size,
            "video_codec": facts.video_codec,
            "width": facts.width,
            "height": facts.height,
            "frame_rate": facts.frame_rate,
            "video_bit_rate": facts.video_bit_rate,
            "audio_codec": facts.audio_codec,
            "audio_channels": facts.audio_channels,
            "audio_sample_rate": facts.audio_sample_rate,
            "audio_bit_rate": facts.audio_bit_rate,
            "drop_relative_path": relative,
            "sha256": digest,
        },
    )
    ctx.log(
        "stage.probe.recorded",
        meeting_id=ctx.meeting_id,
        duration_ms=facts.duration_ms,
        container=facts.container,
        video_codec=facts.video_codec,
        width=facts.width,
        height=facts.height,
        path=relative,
        sha256=digest,
        size_bytes=byte_size,
    )
