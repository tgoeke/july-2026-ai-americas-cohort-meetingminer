"""ffprobe/ffmpeg wrappers, exercised against a real generated mp4.

Tests that need the binaries skip with a named reason when they are absent
(see the `requires_ffmpeg` marker in conftest); the error-path tests do not
need them at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import subprocess

from meetingminer.pipeline import media

from conftest import (
    SYNTHETIC_DURATION_SECONDS,
    SYNTHETIC_HEIGHT,
    SYNTHETIC_WIDTH,
    requires_ffmpeg,
)


# --- probe -----------------------------------------------------------------


@requires_ffmpeg
def test_probe_reads_container_and_stream_facts(synthetic_recording: Path) -> None:
    facts = media.probe_media(synthetic_recording)
    assert facts.duration_ms == pytest.approx(SYNTHETIC_DURATION_SECONDS * 1000, abs=200)
    assert "mp4" in (facts.container or "")
    assert facts.size_bytes == synthetic_recording.stat().st_size
    assert facts.video_codec == "h264"
    assert (facts.width, facts.height) == (SYNTHETIC_WIDTH, SYNTHETIC_HEIGHT)
    assert facts.frame_rate == pytest.approx(10.0, abs=0.1)
    assert facts.audio_codec == "aac"
    assert facts.audio_channels == 1
    assert facts.audio_sample_rate == 16000
    assert facts.has_video is True


@requires_ffmpeg
def test_probe_of_a_corrupt_file_is_a_named_error(tmp_path: Path) -> None:
    """The `ffprobe fails` row of the matrix: unreadable/corrupt recording."""
    corrupt = tmp_path / "recording.mp4"
    corrupt.write_bytes(b"this is not an mp4" * 64)
    with pytest.raises(media.MediaToolError, match="ffprobe failed"):
        media.probe_media(corrupt)


def test_probe_of_a_missing_file_is_a_named_error(tmp_path: Path) -> None:
    with pytest.raises(media.MediaToolError, match="ffprobe failed"):
        media.probe_media(tmp_path / "absent.mp4")


def test_missing_binary_is_a_named_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The `ffmpeg missing` row: no ffmpeg on PATH names the tool."""
    monkeypatch.setattr(media, "FFMPEG", "mm-nonexistent-ffmpeg")
    monkeypatch.setattr(media, "FFPROBE", "mm-nonexistent-ffprobe")
    with pytest.raises(media.MediaToolError, match=r"mm-nonexistent-ffmpeg not found on PATH"):
        media.sample_frames(tmp_path / "in.mp4", tmp_path / "out", 2, 3)
    with pytest.raises(media.MediaToolError, match=r"mm-nonexistent-ffprobe not found on PATH"):
        media.probe_media(tmp_path / "in.mp4")


# --- frames ----------------------------------------------------------------


@requires_ffmpeg
def test_sample_frames_writes_jpegs_at_the_configured_interval(
    synthetic_recording: Path, tmp_path: Path
) -> None:
    out = tmp_path / "frames"
    produced = media.sample_frames(synthetic_recording, out, interval_seconds=2, jpeg_quality=3)
    # 6s at one frame per 2s: t=0, 2, 4 (a trailing frame at exactly 6s is not
    # emitted because the stream ends there).
    assert len(produced) == 3
    assert [p.name for p in produced] == [
        "frame-000001.jpg",
        "frame-000002.jpg",
        "frame-000003.jpg",
    ]
    assert all(p.parent == out and p.stat().st_size > 0 for p in produced)
    # Real JPEGs, not empty placeholders.
    assert produced[0].read_bytes()[:2] == b"\xff\xd8"


@requires_ffmpeg
def test_sample_frames_is_denser_at_a_shorter_interval(
    synthetic_recording: Path, tmp_path: Path
) -> None:
    sparse = media.sample_frames(synthetic_recording, tmp_path / "a", 3, 3)
    dense = media.sample_frames(synthetic_recording, tmp_path / "b", 1, 3)
    assert len(dense) > len(sparse)


@requires_ffmpeg
def test_sample_frames_on_a_corrupt_file_is_a_named_error(tmp_path: Path) -> None:
    corrupt = tmp_path / "recording.mp4"
    corrupt.write_bytes(b"still not an mp4" * 64)
    with pytest.raises(media.MediaToolError, match="ffmpeg frame sampling failed"):
        media.sample_frames(corrupt, tmp_path / "frames", 2, 3)


def test_non_positive_interval_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(media.MediaToolError, match="interval must be positive"):
        media.sample_frames(tmp_path / "in.mp4", tmp_path / "out", 0, 3)


def test_frame_offsets_are_exact_multiples_of_the_interval() -> None:
    """Story 1.4 reads these offsets for dwell detection — pin the arithmetic."""
    assert media.frame_offset_ms(1, 2) == 0
    assert media.frame_offset_ms(2, 2) == 2000
    assert media.frame_offset_ms(3, 2) == 4000
    assert media.frame_offset_ms(4, 0.5) == 1500


def test_sampled_offsets_come_from_source_pts_not_output_ordinals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A shifted/VFR source timeline must not silently become 0, 2000, 4000."""
    monkeypatch.setattr(
        media,
        "_run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            ["ffprobe"], 0,
            '{"frames":[{"best_effort_timestamp_time":"5.000"},'
            '{"best_effort_timestamp_time":"7.125"},'
            '{"best_effort_timestamp_time":"9.875"}]}' , ""
        ),
    )
    assert media.sampled_frame_offsets(tmp_path / "shifted.mp4", 2, 3) == [5000, 7125, 9875]


@requires_ffmpeg
def test_sampling_does_not_modify_the_source(
    synthetic_recording: Path, tmp_path: Path
) -> None:
    """AD-13: reading the recording never writes back into the drop."""
    drop = tmp_path / "drop"
    drop.mkdir()
    recording = drop / "recording.mp4"
    recording.write_bytes(synthetic_recording.read_bytes())
    before = (recording.stat().st_size, recording.stat().st_mtime_ns)
    media.sample_frames(recording, tmp_path / "frames", 2, 3)
    media.probe_media(recording)
    assert (recording.stat().st_size, recording.stat().st_mtime_ns) == before
    assert [p.name for p in drop.iterdir()] == ["recording.mp4"]


# --- extract_audio ---------------------------------------------------------


@requires_ffmpeg
def test_extract_audio_pins_the_waveform_both_engines_receive(
    synthetic_recording: Path, tmp_path: Path
) -> None:
    """16 kHz mono PCM is the contract, not an implementation detail.

    Handing both recognizers the same decoded WAV is what makes swapping
    `stt.engine` a config edit rather than a change in what was heard. Nothing
    downstream can observe a regression here — the worker tests script a fake
    recognizer that never opens the file — so the format is asserted directly.
    """
    destination = tmp_path / "audio.wav"
    media.extract_audio(synthetic_recording, destination)

    assert destination.is_file()
    facts = media.probe_media(destination)
    assert facts.audio_codec == "pcm_s16le"
    assert facts.audio_channels == 1
    assert facts.audio_sample_rate == 16000
    # Audio only: handing a recognizer a video stream wastes a decode at best.
    assert facts.video_codec is None


@requires_ffmpeg
def test_extract_audio_names_a_missing_source(tmp_path: Path) -> None:
    with pytest.raises(media.MediaToolError):
        media.extract_audio(tmp_path / "absent.mp4", tmp_path / "out.wav")
