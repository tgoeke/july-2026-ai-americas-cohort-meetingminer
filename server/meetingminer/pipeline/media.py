"""ffprobe / ffmpeg subprocess wrappers for the video stages.

These are plain command-line tools, not model calls, so they are deliberately
*not* adapter ports (AD-8 covers `Ocr`/`Stt`/`Llm`/`Embedder`). Everything that
can go wrong — the binary missing from PATH, a non-zero exit, output that will
not parse — surfaces as one named :class:`MediaToolError` the calling stage
turns into a recorded stage failure.

Neither function writes to, renames, or deletes anything inside a source drop
(AD-13): the recording is opened read-only and every output goes to a caller-
supplied directory under ``MM_CONTENT_ROOT``.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FFPROBE = "ffprobe"
FFMPEG = "ffmpeg"

# ffprobe reads headers only; a hang here means something is badly wrong.
# ffmpeg deliberately gets no timeout: sampling a multi-hour recording is
# legitimate work and a wall-clock cap would fail long meetings at random.
# Measured 2026-08-31 against the demo corpus: `-show_frames` on a 96-minute
# committee recording took 164s and emitted 4.7M lines of JSON, so 120s failed
# every long meeting at the `frames` stage. This is a guard against a wedged
# process, not a performance budget, so it is set well clear of the longest
# recording the 180-minute acquisition cap allows. `youtube.py` already used
# 300s for its own probe; this was the inconsistent one.
FFPROBE_TIMEOUT_SECONDS = 600

FRAME_FILENAME_TEMPLATE = "frame-%06d.jpg"
FRAME_FILENAME_GLOB = "frame-*.jpg"

# What the `Stt` port's engines are handed. Both bundled engines accept this
# shape natively, so neither resamples and neither sees a different waveform.
AUDIO_SAMPLE_RATE = 16_000
AUDIO_CHANNELS = 1


class MediaToolError(RuntimeError):
    """ffprobe/ffmpeg is missing, failed, or produced unusable output."""


@dataclass(frozen=True)
class MediaFacts:
    """The ffprobe facts the `probe` stage records on ``meeting_media``."""

    duration_ms: int | None
    container: str | None
    size_bytes: int | None
    video_codec: str | None
    width: int | None
    height: int | None
    frame_rate: float | None
    video_bit_rate: int | None
    audio_codec: str | None
    audio_channels: int | None
    audio_sample_rate: int | None
    audio_bit_rate: int | None

    @property
    def has_video(self) -> bool:
        return self.video_codec is not None


def _run(argv: list[str], timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    tool = argv[0]
    try:
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError as exc:
        raise MediaToolError(
            f"{tool} not found on PATH — install it (brew install ffmpeg) and retry"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaToolError(f"{tool} timed out after {timeout}s: {' '.join(argv)}") from exc
    except OSError as exc:
        raise MediaToolError(f"{tool} could not be executed: {exc}") from exc


def _first_stream(streams: list[dict[str, Any]], codec_type: str) -> dict[str, Any]:
    for stream in streams:
        if stream.get("codec_type") == codec_type:
            return stream
    return {}


def _as_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _as_ratio(value: Any) -> float | None:
    """ffprobe frame rates arrive as ``"30000/1001"`` (or ``"0/0"`` for none)."""
    if not isinstance(value, str) or "/" not in value:
        return None
    numerator, _, denominator = value.partition("/")
    try:
        num, den = float(numerator), float(denominator)
    except ValueError:
        return None
    if den == 0:
        return None
    return num / den


def probe_media(path: Path) -> MediaFacts:
    """Inspect a media file with ffprobe.

    Raises :class:`MediaToolError` when ffprobe is missing, exits non-zero
    (unreadable or corrupt input), or emits something that is not the JSON
    document we asked for.
    """
    result = _run(
        [
            FFPROBE,
            "-v", "error",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        timeout=FFPROBE_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or "no diagnostic output"
        raise MediaToolError(f"ffprobe failed for {path}: {detail}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise MediaToolError(f"ffprobe output for {path} was not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise MediaToolError(f"ffprobe output for {path} was not a JSON object")

    fmt = payload.get("format") or {}
    streams = [s for s in (payload.get("streams") or []) if isinstance(s, dict)]
    if not isinstance(fmt, dict):
        raise MediaToolError(f"ffprobe output for {path} has no usable format block")

    video = _first_stream(streams, "video")
    audio = _first_stream(streams, "audio")

    duration_seconds = fmt.get("duration")
    try:
        duration_ms = round(float(duration_seconds) * 1000) if duration_seconds else None
    except (TypeError, ValueError):
        duration_ms = None

    container = fmt.get("format_name")
    return MediaFacts(
        duration_ms=duration_ms,
        container=str(container) if container else None,
        size_bytes=_as_int(fmt.get("size")),
        video_codec=video.get("codec_name"),
        width=_as_int(video.get("width")),
        height=_as_int(video.get("height")),
        frame_rate=_as_ratio(video.get("avg_frame_rate")) or _as_ratio(video.get("r_frame_rate")),
        video_bit_rate=_as_int(video.get("bit_rate")),
        audio_codec=audio.get("codec_name"),
        audio_channels=_as_int(audio.get("channels")),
        audio_sample_rate=_as_int(audio.get("sample_rate")),
        audio_bit_rate=_as_int(audio.get("bit_rate")),
    )


def probe_creation_time(path: Path) -> str | None:
    """The container's own ``creation_time`` tag, or ``None`` when it has none.

    Deliberately *not* on :class:`MediaFacts`: the pipeline never derives a
    meeting's wall clock from media metadata (AD-1), so no stage may reach for
    this. Its one caller is ``meetingminer.mintdrop``, which runs before a drop
    exists and is therefore the source side — the only place allowed to decide
    what ``startedAt`` is. ffprobe knowledge stays in the module that owns it
    rather than being spelled a second time beside the minting logic.

    The value is returned verbatim, unparsed: what a recorder wrote is what the
    caller judges. Raises :class:`MediaToolError` when ffprobe is missing, exits
    non-zero, or emits something that is not the JSON document we asked for —
    the same contract as :func:`probe_media`.
    """
    result = _run(
        [
            FFPROBE,
            "-v", "error",
            "-print_format", "json",
            "-show_entries", "format_tags=creation_time",
            str(path),
        ],
        timeout=FFPROBE_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or "no diagnostic output"
        raise MediaToolError(f"ffprobe failed for {path}: {detail}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise MediaToolError(f"ffprobe output for {path} was not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise MediaToolError(f"ffprobe output for {path} was not a JSON object")
    fmt = payload.get("format")
    tags = fmt.get("tags") if isinstance(fmt, dict) else None
    value = tags.get("creation_time") if isinstance(tags, dict) else None
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def sample_frames(
    source: Path,
    output_dir: Path,
    interval_seconds: float,
    jpeg_quality: int,
) -> list[Path]:
    """Sample one JPEG every ``interval_seconds`` into ``output_dir``.

    Files are named ``frame-000001.jpg`` upward. ffmpeg's ``fps=1/N`` filter
    emits at exact multiples of the interval starting at t=0, so the caller
    can derive the offset arithmetically: ``offset_ms = (index - 1) * N *
    1000``. Story 1.4 reads those offsets for dwell detection — do not change
    the naming or the filter without changing that derivation with it.

    Returns the produced files in name order. An empty list is a legitimate
    result only for input with no video stream; callers that require frames
    should say so themselves.
    """
    if interval_seconds <= 0:
        raise MediaToolError(f"frame interval must be positive, got {interval_seconds}")
    output_dir.mkdir(parents=True, exist_ok=True)
    result = _run(
        [
            FFMPEG,
            "-nostdin",
            "-v", "error",
            "-y",
            "-i", str(source),
            "-vf", f"fps=1/{interval_seconds}",
            "-q:v", str(jpeg_quality),
            str(output_dir / FRAME_FILENAME_TEMPLATE),
        ]
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or "no diagnostic output"
        raise MediaToolError(f"ffmpeg frame sampling failed for {source}: {detail}")
    return sorted(output_dir.glob(FRAME_FILENAME_GLOB))


def sampled_frame_offsets(source: Path, interval_seconds: float, count: int) -> list[int]:
    """Map sampled outputs to timestamps from the source video's PTS timeline.

    The fps filter decides output cadence, but ordinal arithmetic loses a
    shifted start time and cannot describe VFR sources. Read the source frame
    timeline and select the first decoded frame at each sampling boundary;
    these are the timestamps persisted beside the sampled JPEGs.
    """
    result = _run(
        [
            FFPROBE, "-v", "error", "-print_format", "json", "-select_streams", "v:0",
            "-show_frames", str(source),
        ],
        timeout=FFPROBE_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or "no diagnostic output"
        raise MediaToolError(f"ffprobe frame timeline failed for {source}: {detail}")
    try:
        frames = json.loads(result.stdout).get("frames", [])
        points = [
            float(
                frame["best_effort_timestamp_time"]
                if "best_effort_timestamp_time" in frame
                else frame["pkt_pts_time"]
            )
            for frame in frames
            if isinstance(frame, dict)
            and ("best_effort_timestamp_time" in frame or "pkt_pts_time" in frame)
        ]
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise MediaToolError(f"ffprobe frame timeline for {source} was unusable: {exc}") from exc
    selected: list[int] = []
    cursor = 0
    if not points:
        raise MediaToolError(f"ffprobe frame timeline for {source} has no video timestamps")
    first_pts = points[0]
    for index in range(count):
        boundary = first_pts + index * interval_seconds
        while cursor < len(points) and points[cursor] + 1e-9 < boundary:
            cursor += 1
        if cursor >= len(points):
            raise MediaToolError(f"ffprobe frame timeline ended before sampled frame {index + 1}")
        selected.append(round(points[cursor] * 1000))
    return selected


def frame_offset_ms(index: int, interval_seconds: float) -> int:
    """Offset of the ``index``-th sampled frame (1-based), in whole ms.

    See :func:`sample_frames`: the ``fps`` filter emits the first frame at t=0.
    """
    return round((index - 1) * interval_seconds * 1000)


def extract_audio(source: Path, destination: Path) -> Path:
    """Extract one 16 kHz mono PCM WAV from a recording, for the STT lane.

    The engines take identical input this way: `mlx_whisper` shells out to
    ffmpeg itself, but `parakeet_mlx` loads audio through its own path, so
    handing both the same decoded WAV is what makes swapping the engine a
    config edit rather than a change in what was heard. It also keeps the drop
    untouched (AD-13) and leaves a rerun something to reuse.

    Raises :class:`MediaToolError` when ffmpeg is missing, exits non-zero, or
    produces no file — including the case where the recording carries no audio
    stream at all, which ffmpeg reports as a failure to build an output.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    result = _run(
        [
            FFMPEG,
            "-nostdin",
            "-v", "error",
            "-y",
            "-i", str(source),
            # No video, one channel, 16 kHz, uncompressed 16-bit PCM.
            "-vn",
            "-ac", str(AUDIO_CHANNELS),
            "-ar", str(AUDIO_SAMPLE_RATE),
            "-c:a", "pcm_s16le",
            str(destination),
        ]
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or "no diagnostic output"
        raise MediaToolError(f"ffmpeg audio extraction failed for {source}: {detail}")
    if not destination.is_file():  # pragma: no cover - ffmpeg exits non-zero first
        raise MediaToolError(
            f"ffmpeg reported success but wrote no audio for {source} -> {destination}"
        )
    return destination
