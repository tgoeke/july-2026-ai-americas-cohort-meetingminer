"""``youtube-drop``: the YouTube acquisition producer (story 6.2).

Offline by construction: tool presence, probes, and downloads are stubbed;
metadata mapping runs over recorded ``info.json`` fixtures pruned to the
fields the command reads; every drops root is a ``tmp_path`` directory and no
store fixture is requested. Like ``test_mint_drop.py``, every drop these
tests produce is validated against ``docs/source-drop.schema.json`` — the
same contract intake enforces. The one test that touches the network runs
only behind ``MM_YOUTUBE_NETWORK_TEST=1``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import jsonschema
import pytest
import yaml

from meetingminer import mintdrop, youtube
from meetingminer.pipeline import media

from repo_paths import REPO_ROOT

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "youtube"
SCHEMA = json.loads(
    (REPO_ROOT / "docs" / "source-drop.schema.json").read_text(encoding="utf-8")
)
VALIDATOR = jsonschema.Draft202012Validator(
    SCHEMA, format_checker=jsonschema.FormatChecker()
)

VALID_ID = "aB3dEfGhIj0"
WATCH_URL = f"https://www.youtube.com/watch?v={VALID_ID}"

TRANSCRIPT_VTT = "WEBVTT\n\n00:00:00.000 --> 00:00:04.000\nmorning all\n"
NETWORK_FLAG = "MM_YOUTUBE_NETWORK_TEST"


# --- helpers ---------------------------------------------------------------


def schema_errors(metadata: dict[str, Any]) -> list[str]:
    return [
        ("/".join(str(p) for p in error.absolute_path) or "(root)")
        + ": "
        + error.message
        for error in VALIDATOR.iter_errors(metadata)
    ]


def info_fixture(name: str) -> dict[str, Any]:
    return json.loads(
        (FIXTURES / f"{name}.info.json").read_text(encoding="utf-8")
    )


def read_drop_metadata(drop: Path) -> dict[str, Any]:
    metadata = json.loads((drop / "metadata.json").read_text(encoding="utf-8"))
    assert schema_errors(metadata) == [], f"{drop} violates the source-drop schema"
    return metadata


def _must_not_run(name: str):
    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError(f"{name} must not be invoked")

    return _boom


def acquire_kwargs(root: Path, cap_minutes: int = 180) -> dict[str, Any]:
    return {
        "drops_root": root,
        "identity_root": root,
        "config_path": REPO_ROOT / "config.yaml",
        "max_duration_minutes": cap_minutes,
    }


def cli_config(root: Path, *, cap_minutes: int = 37) -> SimpleNamespace:
    return SimpleNamespace(
        config_path=REPO_ROOT / "config.yaml",
        secrets=SimpleNamespace(mm_drops_root=root),
        settings=SimpleNamespace(
            acquisition=SimpleNamespace(
                youtube=SimpleNamespace(max_duration_minutes=cap_minutes)
            )
        ),
    )


def cli_result(tmp_path: Path, *, status: str = "created") -> mintdrop.MintResult:
    path = tmp_path / "drop"
    return mintdrop.MintResult(
        status=status,
        path=path,
        source_id=f"youtube:{VALID_ID}",
        metadata={
            "startedAt": "2026-08-12T15:30:19Z",
            "startedAtPrecision": "second",
            "corpus": "real",
            "provenance": {"files": [{"dropFilename": "recording.mp4"}]},
        },
    )


def write_existing_youtube_drop(root: Path) -> tuple[Path, dict[str, Any]]:
    source_id = f"youtube:{VALID_ID}"
    drop = root / mintdrop.drop_name(
        "2026-08-12T15:30:19Z", "Platform Sync — August", source_id
    )
    drop.mkdir()
    recording = drop / "recording.mp4"
    recording.write_bytes(b"existing youtube recording")
    digest, size = mintdrop.sha256_and_size(recording)
    metadata = {
        "schemaVersion": 1,
        "sourceId": source_id,
        "corpus": "real",
        "startedAt": "2026-08-12T15:30:19Z",
        "startedAtPrecision": "second",
        "provenance": {
            "tool": "youtube-drop",
            "title": "Platform Sync — August",
            "mintedAt": "2026-08-30T12:00:00Z",
            "suppliedBy": "test",
            "startedAtSource": "release_timestamp",
            "url": WATCH_URL,
            "channel": "MeetingMiner Sandbox",
            "durationSeconds": 1830,
            "ytDlpVersion": "2026.07.04",
            "formatId": "137+140",
            "files": [
                {
                    "dropFilename": "recording.mp4",
                    "sourcePath": "/private/tmp/source.mp4",
                    "sha256": digest,
                    "byteSize": size,
                }
            ],
        },
    }
    (drop / "metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    return drop, metadata


@pytest.fixture()
def drops_root(tmp_path: Path) -> Path:
    root = tmp_path / "drops"
    root.mkdir()
    return root


@pytest.fixture()
def tools_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both CLI tools 'installed', without touching the real PATH."""
    monkeypatch.setattr(shutil, "which", lambda name: f"/stub/bin/{name}")


@pytest.fixture()
def stub_mint_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """ffprobe stand-ins for `mint()`'s video checks (test_mint_drop's rule:
    most rows are about the minting logic, not the codec)."""

    def _probe_media(path: Path) -> media.MediaFacts:
        return media.MediaFacts(
            duration_ms=6000,
            container="mov,mp4,m4a",
            size_bytes=1,
            video_codec="h264",
            width=320,
            height=240,
            frame_rate=10.0,
            video_bit_rate=None,
            audio_codec="aac",
            audio_channels=1,
            audio_sample_rate=16000,
            audio_bit_rate=None,
        )

    monkeypatch.setattr(mintdrop, "probe_media", _probe_media)
    monkeypatch.setattr(mintdrop, "probe_creation_time", lambda path: None)


# --- URL classification (offline) ------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        f"https://www.youtube.com/watch?v={VALID_ID}",
        f"http://youtube.com/watch?v={VALID_ID}",
        f"https://m.youtube.com/watch?v={VALID_ID}",
        f"https://youtu.be/{VALID_ID}",
        f"https://www.youtube.com/shorts/{VALID_ID}",
        f"https://www.youtube.com/watch?v={VALID_ID}&list=PL0123456789A&index=2",
        f"https://www.youtube.com/watch?list=PL0123456789A&v={VALID_ID}",
    ],
)
def test_every_video_url_shape_yields_the_same_id(url: str) -> None:
    assert youtube.video_id_from_url(url) == VALID_ID


@pytest.mark.parametrize(
    "url",
    [
        "https://vimeo.com/123456789",
        f"https://notyoutube.com/watch?v={VALID_ID}",
        f"https://youtube.com.evil.example/watch?v={VALID_ID}",
        "https://www.youtube.com/playlist?list=PL0123456789A",
        "https://www.youtube.com/watch",
        "https://www.youtube.com/watch?v=tooShort",
        "https://www.youtube.com/watch?v=" + "x" * 12,
        "https://www.youtube.com/watch?v=bad*chars!!",
        f"https://www.youtube.com/watch?v={VALID_ID}&v={VALID_ID}",
        f"ftp://www.youtube.com/watch?v={VALID_ID}",
        f"https://youtu.be/{VALID_ID}/extra",
        "https://youtu.be/",
        f"https://www.youtube.com/embed/{VALID_ID}",
        "not a url at all",
        "",
    ],
)
def test_everything_else_is_refused_by_name(url: str) -> None:
    with pytest.raises(youtube.YoutubeError, match="not a YouTube video URL"):
        youtube.video_id_from_url(url)


def test_the_canonical_watch_url_is_what_provenance_carries() -> None:
    assert youtube.watch_url(VALID_ID) == WATCH_URL


# --- info.json -> metadata mapping ------------------------------------------


def test_release_timestamp_maps_to_second_precision() -> None:
    assert youtube.started_at_from_info(info_fixture("full")) == (
        "2026-08-12T15:30:19Z",
        "second",
        "release_timestamp",
    )


def test_upload_date_alone_maps_to_day_precision_midnight() -> None:
    assert youtube.started_at_from_info(info_fixture("upload-date-only")) == (
        "2026-08-12T00:00:00Z",
        "day",
        "upload_date",
    )


def test_neither_timestamp_is_a_named_refusal_never_a_guess() -> None:
    info = info_fixture("full")
    del info["release_timestamp"]
    del info["upload_date"]
    with pytest.raises(youtube.YoutubeError, match="release_timestamp"):
        youtube.started_at_from_info(info)


@pytest.mark.parametrize(
    "release",
    [float("nan"), float("inf"), 10**30, pytest.param(10**1000, id="huge")],
)
def test_invalid_release_timestamp_uses_the_valid_upload_date(release: object) -> None:
    assert youtube.started_at_from_info(
        {"release_timestamp": release, "upload_date": "20260812"}
    ) == ("2026-08-12T00:00:00Z", "day", "upload_date")


def test_manual_english_captions_win_over_auto() -> None:
    assert youtube.select_captions(info_fixture("full")) == ("en", "manual")


def test_auto_captions_are_used_when_no_manual_english_exists() -> None:
    assert youtube.select_captions(info_fixture("auto-captions")) == ("en", "auto")


def test_no_english_captions_means_a_recording_only_drop() -> None:
    assert youtube.select_captions(info_fixture("no-english")) is None


def test_en_dash_variants_count_as_english_but_prefixes_do_not() -> None:
    track = [{"ext": "vtt"}]
    assert youtube.select_captions({"subtitles": {"en-GB": track}}) == (
        "en-GB",
        "manual",
    )
    # "english"/"enm" are not en/en-*: the rule is a language tag, not a prefix.
    assert youtube.select_captions({"subtitles": {"english": track, "enm": track}}) is None


def test_provenance_extra_carries_the_ac_field_list() -> None:
    extra = youtube.provenance_extra_from_info(
        info_fixture("full"), VALID_ID, "2026.07.04"
    )
    assert extra == {
        "tool": "youtube-drop",
        "url": WATCH_URL,
        "ytDlpVersion": "2026.07.04",
        "channel": "MeetingMiner Sandbox",
        "durationSeconds": 1830,
        "formatId": "137+140",
    }


def test_whitespace_channel_uses_a_normalized_uploader_fallback() -> None:
    info = info_fixture("full")
    info["channel"] = "   "
    info["uploader"] = "  Fallback Publisher  "
    assert youtube.provenance_extra_from_info(
        info, VALID_ID, "2026.07.04"
    )["channel"] == "Fallback Publisher"


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("channel", "", "channel"),
        ("duration", None, "duration"),
        ("format_id", "", "format_id"),
    ],
)
def test_incomplete_downloaded_provenance_is_refused_by_name(
    field: str, value: object, match: str
) -> None:
    info = info_fixture("full")
    info[field] = value
    if field == "channel":
        info.pop("uploader", None)
    with pytest.raises(youtube.YoutubeError, match=match):
        youtube.provenance_extra_from_info(info, VALID_ID, "2026.07.04")


def test_empty_yt_dlp_version_is_refused_by_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        youtube,
        "_run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0, "\n", ""),
    )
    with pytest.raises(youtube.YoutubeError, match="version"):
        youtube.yt_dlp_version()


# --- the refusal matrix (drops root untouched every time) --------------------


def test_a_missing_yt_dlp_is_refused_by_name_before_any_network(
    drops_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        shutil, "which", lambda name: None if name == youtube.YT_DLP else "/stub/x"
    )
    monkeypatch.setattr(youtube, "_run", _must_not_run("yt-dlp"))
    with pytest.raises(youtube.YoutubeError, match=r"yt-dlp is not on PATH.*brew install"):
        youtube.acquire(WATCH_URL, **acquire_kwargs(drops_root))
    assert list(drops_root.iterdir()) == []


def test_a_missing_ffmpeg_is_refused_by_name_before_any_network(
    drops_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        shutil, "which", lambda name: None if name == youtube.FFMPEG else "/stub/x"
    )
    monkeypatch.setattr(youtube, "_run", _must_not_run("yt-dlp"))
    with pytest.raises(youtube.YoutubeError, match=r"ffmpeg is not on PATH.*brew install"):
        youtube.acquire(WATCH_URL, **acquire_kwargs(drops_root))
    assert list(drops_root.iterdir()) == []


def test_a_missing_ffprobe_is_refused_before_media_download(
    drops_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        shutil, "which", lambda name: None if name == "ffprobe" else "/stub/x"
    )
    monkeypatch.setattr(youtube, "_run", _must_not_run("yt-dlp"))
    monkeypatch.setattr(youtube, "download", _must_not_run("download"))
    with pytest.raises(youtube.YoutubeError, match=r"ffprobe.*brew install ffmpeg"):
        youtube.acquire(WATCH_URL, **acquire_kwargs(drops_root))
    assert list(drops_root.iterdir()) == []


def test_a_private_or_removed_video_carries_yt_dlps_own_message(
    drops_root: Path, tools_present: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _failing_probe(command: list[str], **kwargs: Any) -> Any:
        return subprocess.CompletedProcess(
            args=command,
            returncode=1,
            stdout="",
            stderr="ERROR: [youtube] Private video."
            " Sign in if you've been granted access to this video\n",
        )

    monkeypatch.setattr(youtube, "_run", _failing_probe)
    monkeypatch.setattr(youtube, "download", _must_not_run("download"))
    with pytest.raises(youtube.YoutubeError, match="Private video"):
        youtube.acquire(WATCH_URL, **acquire_kwargs(drops_root))
    assert list(drops_root.iterdir()) == []


def test_no_video_stream_is_refused_at_probe(
    drops_root: Path, tools_present: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(youtube, "probe", lambda url: info_fixture("audio-only"))
    monkeypatch.setattr(youtube, "download", _must_not_run("download"))
    with pytest.raises(youtube.YoutubeError, match="no video stream"):
        youtube.acquire(
            "https://www.youtube.com/watch?v=AudioOnly01",
            **acquire_kwargs(drops_root),
        )
    assert list(drops_root.iterdir()) == []


def test_over_the_duration_cap_names_duration_cap_and_config_key(
    drops_root: Path, tools_present: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(youtube, "probe", lambda url: info_fixture("full"))
    monkeypatch.setattr(youtube, "download", _must_not_run("download"))
    with pytest.raises(
        youtube.YoutubeError,
        match=r"30\.5 minutes.*10-minute cap.*acquisition\.youtube\.max_duration_minutes",
    ):
        youtube.acquire(WATCH_URL, **acquire_kwargs(drops_root, cap_minutes=10))
    assert list(drops_root.iterdir()) == []


@pytest.mark.parametrize(
    "duration",
    [
        None,
        "1830",
        -1,
        float("nan"),
        float("inf"),
        True,
        pytest.param(10**1000, id="huge"),
    ],
)
def test_missing_or_invalid_duration_is_refused_before_download(
    duration: object,
    drops_root: Path,
    tools_present: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    info = info_fixture("full")
    info["duration"] = duration
    monkeypatch.setattr(youtube, "probe", lambda url: info)
    monkeypatch.setattr(youtube, "download", _must_not_run("download"))
    with pytest.raises(youtube.YoutubeError, match="duration"):
        youtube.acquire(WATCH_URL, **acquire_kwargs(drops_root))
    assert list(drops_root.iterdir()) == []


@pytest.mark.parametrize("metadata_id", [None, "different01"])
def test_probe_identity_must_match_the_requested_video(
    metadata_id: object,
    drops_root: Path,
    tools_present: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    info = info_fixture("full")
    info["id"] = metadata_id
    monkeypatch.setattr(youtube, "probe", lambda url: info)
    monkeypatch.setattr(youtube, "download", _must_not_run("download"))
    with pytest.raises(youtube.YoutubeError, match="video id"):
        youtube.acquire(WATCH_URL, **acquire_kwargs(drops_root))
    assert list(drops_root.iterdir()) == []


@pytest.mark.parametrize(
    "channel,uploader",
    [(None, None), ("", ""), ("   ", "\t")],
)
def test_probe_missing_or_blank_channel_refuses_before_download(
    channel: object,
    uploader: object,
    drops_root: Path,
    tools_present: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    info = info_fixture("full")
    info["channel"] = channel
    info["uploader"] = uploader
    monkeypatch.setattr(youtube, "probe", lambda url: info)
    monkeypatch.setattr(youtube, "download", _must_not_run("download"))
    with pytest.raises(youtube.YoutubeError, match="channel"):
        youtube.acquire(WATCH_URL, **acquire_kwargs(drops_root))
    assert list(drops_root.iterdir()) == []


def test_neither_timestamp_refuses_before_the_download(
    drops_root: Path, tools_present: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    info = info_fixture("full")
    del info["release_timestamp"]
    del info["upload_date"]
    monkeypatch.setattr(youtube, "probe", lambda url: info)
    monkeypatch.setattr(youtube, "download", _must_not_run("download"))
    with pytest.raises(youtube.YoutubeError, match="release_timestamp"):
        youtube.acquire(WATCH_URL, **acquire_kwargs(drops_root))
    assert list(drops_root.iterdir()) == []


@pytest.mark.parametrize(
    "changes,match",
    [
        ({"id": "different01"}, "video id"),
        ({"duration": 999999}, "over the.*cap"),
        ({"duration": None}, "duration"),
        ({"duration": float("nan")}, "duration"),
        ({"duration": -1}, "duration"),
        ({"formats": info_fixture("audio-only")["formats"]}, "no video stream"),
        ({"channel": "", "uploader": ""}, "channel"),
        ({"format_id": ""}, "format_id"),
        (
            {"release_timestamp": float("nan"), "upload_date": "invalid"},
            "release_timestamp",
        ),
    ],
)
def test_downloaded_metadata_is_revalidated_before_mint(
    changes: dict[str, object],
    match: str,
    drops_root: Path,
    tools_present: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe_info = info_fixture("full")
    downloaded = dict(probe_info)
    downloaded.update(changes)
    monkeypatch.setattr(youtube, "probe", lambda url: probe_info)
    monkeypatch.setattr(youtube, "yt_dlp_version", lambda: "2026.07.04")

    def fake_download(
        url: str, video_id: str, workdir: Path, captions: tuple[str, str] | None
    ) -> tuple[Path, Path | None, dict[str, Any]]:
        return workdir / f"{video_id}.mp4", None, downloaded

    monkeypatch.setattr(youtube, "download", fake_download)
    monkeypatch.setattr(youtube, "mint", _must_not_run("mint"))
    with pytest.raises(youtube.YoutubeError, match=match):
        youtube.acquire(WATCH_URL, **acquire_kwargs(drops_root))
    assert list(drops_root.iterdir()) == []


@pytest.mark.parametrize("captions", [("en", "manual"), ("en", "auto")])
def test_selected_captions_require_the_requested_english_vtt(
    captions: tuple[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / f"{VALID_ID}.mp4").write_bytes(b"media")
    (tmp_path / f"{VALID_ID}.info.json").write_text(
        json.dumps(info_fixture("full")), encoding="utf-8"
    )
    (tmp_path / f"{VALID_ID}.fr.vtt").write_text(
        TRANSCRIPT_VTT.replace("morning all", "bonjour"), encoding="utf-8"
    )
    monkeypatch.setattr(
        youtube,
        "_run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0, "", ""),
    )

    with pytest.raises(youtube.YoutubeError, match="caption.*no VTT"):
        youtube.download(WATCH_URL, VALID_ID, tmp_path, captions)


def test_downloaded_caption_availability_must_match_the_probe(
    drops_root: Path, tools_present: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    probe_info = info_fixture("no-english")
    downloaded = dict(probe_info)
    downloaded["automatic_captions"] = {"en": [{"ext": "vtt"}]}
    video_id = probe_info["id"]
    url = youtube.watch_url(video_id)
    monkeypatch.setattr(youtube, "probe", lambda canonical: probe_info)
    monkeypatch.setattr(youtube, "yt_dlp_version", lambda: "2026.07.04")

    def fake_download(
        canonical: str,
        received_video_id: str,
        workdir: Path,
        captions: tuple[str, str] | None,
    ) -> tuple[Path, Path | None, dict[str, Any]]:
        assert captions is None
        return workdir / f"{received_video_id}.mp4", None, downloaded

    monkeypatch.setattr(youtube, "download", fake_download)
    monkeypatch.setattr(youtube, "mint", _must_not_run("mint"))
    with pytest.raises(youtube.YoutubeError, match="caption availability.*changed"):
        youtube.acquire(url, **acquire_kwargs(drops_root))


@pytest.mark.parametrize(
    "fixture_name,expected_caption_args",
    [
        (
            "full",
            ["--write-subs", "--sub-langs", "en", "--convert-subs", "vtt"],
        ),
        (
            "auto-captions",
            [
                "--write-auto-subs",
                "--sub-langs",
                "en",
                "--convert-subs",
                "vtt",
            ],
        ),
        ("no-english", []),
    ],
)
def test_download_command_and_outputs_are_covered_without_network(
    fixture_name: str,
    expected_caption_args: list[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    info = info_fixture(fixture_name)
    video_id = info["id"]
    url = youtube.watch_url(video_id)
    captions = youtube.select_captions(info)
    expected_command = [
        youtube.YT_DLP,
        "--no-playlist",
        "-f",
        youtube.FORMAT_SELECTOR,
        "--merge-output-format",
        "mp4",
        "--write-info-json",
        "-o",
        str(tmp_path / f"{video_id}.%(ext)s"),
        *expected_caption_args,
        url,
    ]

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert command == expected_command
        (tmp_path / f"{video_id}.mp4").write_bytes(b"media")
        (tmp_path / f"{video_id}.info.json").write_text(
            json.dumps(info), encoding="utf-8"
        )
        if captions is not None:
            (tmp_path / f"{video_id}.{captions[0]}.vtt").write_text(
                TRANSCRIPT_VTT, encoding="utf-8"
            )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(youtube, "_run", fake_run)
    recording, transcript, downloaded = youtube.download(
        url, video_id, tmp_path, captions
    )

    assert recording == tmp_path / f"{video_id}.mp4"
    assert transcript == (
        tmp_path / f"{video_id}.{captions[0]}.vtt" if captions else None
    )
    assert downloaded == info


# --- the exists short-circuit ------------------------------------------------


def test_an_already_minted_video_short_circuits_before_any_yt_dlp_call(
    drops_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Acceptance: `find_existing_drop` answers first; the downloader and the
    probe are never invoked and no network traffic for media occurs."""
    source_id = f"youtube:{VALID_ID}"
    drop, metadata = write_existing_youtube_drop(drops_root)

    monkeypatch.setattr(youtube, "ensure_tools", _must_not_run("ensure_tools"))
    monkeypatch.setattr(youtube, "probe", _must_not_run("probe"))
    monkeypatch.setattr(youtube, "download", _must_not_run("download"))
    monkeypatch.setattr(youtube, "_run", _must_not_run("yt-dlp"))

    result = youtube.acquire(
        f"https://youtu.be/{VALID_ID}", **acquire_kwargs(drops_root)
    )
    assert result.status == "exists"
    assert result.path == drop
    assert result.source_id == source_id
    assert result.metadata == metadata
    # Nothing written: the pre-existing drop is still the only thing there.
    assert [p for p in drops_root.iterdir()] == [drop]


def test_incomplete_legacy_existing_drop_is_refused_without_yt_dlp(
    drops_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    drop, metadata = write_existing_youtube_drop(drops_root)
    del metadata["provenance"]["formatId"]
    (drop / "metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    monkeypatch.setattr(youtube, "ensure_tools", _must_not_run("ensure_tools"))
    monkeypatch.setattr(youtube, "probe", _must_not_run("probe"))
    monkeypatch.setattr(youtube, "download", _must_not_run("download"))

    with pytest.raises(
        youtube.YoutubeError,
        match=r"existing YouTube drop.*formatId.*do not POST.*quarantine",
    ):
        youtube.acquire(WATCH_URL, **acquire_kwargs(drops_root))


def test_existing_drop_with_false_evidence_digest_is_refused_without_yt_dlp(
    drops_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    drop, metadata = write_existing_youtube_drop(drops_root)
    metadata["provenance"]["files"][0]["sha256"] = "0" * 64
    (drop / "metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    monkeypatch.setattr(youtube, "ensure_tools", _must_not_run("ensure_tools"))
    monkeypatch.setattr(youtube, "probe", _must_not_run("probe"))
    monkeypatch.setattr(youtube, "download", _must_not_run("download"))

    with pytest.raises(
        youtube.YoutubeError,
        match=r"existing YouTube drop.*recording\.mp4.*does not match its bytes",
    ):
        youtube.acquire(WATCH_URL, **acquire_kwargs(drops_root))


def test_existing_drop_with_duplicate_manifest_rows_is_refused_without_yt_dlp(
    drops_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    drop, metadata = write_existing_youtube_drop(drops_root)
    metadata["provenance"]["files"].append(
        dict(metadata["provenance"]["files"][0])
    )
    (drop / "metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    monkeypatch.setattr(youtube, "ensure_tools", _must_not_run("ensure_tools"))
    monkeypatch.setattr(youtube, "probe", _must_not_run("probe"))
    monkeypatch.setattr(youtube, "download", _must_not_run("download"))

    with pytest.raises(youtube.YoutubeError, match=r"duplicate.*recording\.mp4"):
        youtube.acquire(WATCH_URL, **acquire_kwargs(drops_root))


def test_digest_named_drop_with_wrong_source_id_refuses_without_yt_dlp(
    drops_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    drop, metadata = write_existing_youtube_drop(drops_root)
    metadata["sourceId"] = "youtube:different01"
    (drop / "metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    monkeypatch.setattr(youtube, "ensure_tools", _must_not_run("ensure_tools"))
    monkeypatch.setattr(youtube, "probe", _must_not_run("probe"))
    monkeypatch.setattr(youtube, "download", _must_not_run("download"))

    with pytest.raises(
        youtube.YoutubeError,
        match=r"existing YouTube drop.*sourceId.*do not POST.*quarantine",
    ):
        youtube.acquire(WATCH_URL, **acquire_kwargs(drops_root))


def test_existing_drop_over_the_configured_cap_refuses_without_yt_dlp(
    drops_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    drop, metadata = write_existing_youtube_drop(drops_root)
    metadata["provenance"]["durationSeconds"] = 61 * 60
    (drop / "metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    monkeypatch.setattr(youtube, "ensure_tools", _must_not_run("ensure_tools"))
    monkeypatch.setattr(youtube, "probe", _must_not_run("probe"))
    monkeypatch.setattr(youtube, "download", _must_not_run("download"))

    with pytest.raises(youtube.YoutubeError, match=r"durationSeconds exceeds.*60-minute"):
        youtube.acquire(WATCH_URL, **acquire_kwargs(drops_root, cap_minutes=60))


def test_existing_drop_with_inconsistent_started_at_source_refuses_without_yt_dlp(
    drops_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    drop, metadata = write_existing_youtube_drop(drops_root)
    metadata["provenance"]["startedAtSource"] = "upload_date"
    (drop / "metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    monkeypatch.setattr(youtube, "ensure_tools", _must_not_run("ensure_tools"))
    monkeypatch.setattr(youtube, "probe", _must_not_run("probe"))
    monkeypatch.setattr(youtube, "download", _must_not_run("download"))

    with pytest.raises(youtube.YoutubeError, match="startedAtSource does not match"):
        youtube.acquire(WATCH_URL, **acquire_kwargs(drops_root))


# --- acquisition end to end, offline ----------------------------------------


def test_a_new_video_is_acquired_through_mint_with_the_ac_metadata_shape(
    drops_root: Path, stub_mint_probe: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Acceptance: `youtube:<videoId>` sourceId, corpus real, startedAt from
    release_timestamp, the named provenance keys, participants omitted, the
    per-file sha256/byteSize block, info.json read but never copied in."""
    info = info_fixture("full")

    monkeypatch.setattr(youtube, "ensure_tools", lambda: None)
    monkeypatch.setattr(youtube, "probe", lambda url: dict(info))
    monkeypatch.setattr(youtube, "yt_dlp_version", lambda: "2026.07.04")

    def fake_download(
        url: str, video_id: str, workdir: Path, captions: tuple[str, str] | None
    ) -> tuple[Path, Path | None, dict[str, Any]]:
        assert url == WATCH_URL  # canonicalized, whatever shape was pasted
        assert video_id == VALID_ID
        assert captions == ("en", "manual")
        recording = workdir / f"{video_id}.mp4"
        recording.write_bytes(b"pretend this is an mp4 " * 64)
        transcript = workdir / f"{video_id}.en.vtt"
        transcript.write_text(TRANSCRIPT_VTT, encoding="utf-8")
        (workdir / f"{video_id}.info.json").write_text(
            json.dumps(info), encoding="utf-8"
        )
        return recording, transcript, dict(info)

    monkeypatch.setattr(youtube, "download", fake_download)

    result = youtube.acquire(
        f"https://youtu.be/{VALID_ID}", **acquire_kwargs(drops_root)
    )
    assert result.status == "created"
    metadata = read_drop_metadata(result.path)
    assert metadata["sourceId"] == f"youtube:{VALID_ID}"
    assert metadata["corpus"] == "real"
    assert (metadata["startedAt"], metadata["startedAtPrecision"]) == (
        "2026-08-12T15:30:19Z",
        "second",
    )
    assert "participants" not in metadata
    provenance = metadata["provenance"]
    assert provenance["tool"] == "youtube-drop"
    assert provenance["url"] == WATCH_URL
    assert provenance["channel"] == "MeetingMiner Sandbox"
    assert provenance["durationSeconds"] == 1830
    assert provenance["ytDlpVersion"] == "2026.07.04"
    assert provenance["formatId"] == "137+140"
    assert provenance["startedAtSource"] == "release_timestamp"
    assert provenance["title"] == "Platform Sync — August"
    files = {entry["dropFilename"]: entry for entry in provenance["files"]}
    assert set(files) == {"recording.mp4", "transcript.vtt"}
    assert all(
        entry["sha256"] and entry["byteSize"] > 0 for entry in files.values()
    )
    # info.json was read for metadata and never copied into the drop.
    assert sorted(p.name for p in result.path.iterdir()) == [
        "metadata.json",
        "recording.mp4",
        "transcript.vtt",
    ]
    assert (result.path / "transcript.vtt").read_text(encoding="utf-8") == TRANSCRIPT_VTT


# --- the mint() keyword overrides -------------------------------------------


def test_mint_overrides_produce_the_youtube_metadata_shape(tmp_path: Path) -> None:
    """The overrides slot into the one staging → validate → rename path: a
    verbatim source id, an already-resolved wall clock, provenance extras."""
    vtt = tmp_path / "talk.vtt"
    vtt.write_text(TRANSCRIPT_VTT, encoding="utf-8")
    root = tmp_path / "drops"
    root.mkdir()
    source_id = f"youtube:{VALID_ID}"

    result = mintdrop.mint(
        supplied=[str(vtt)],
        corpus="real",
        drops_root=root,
        config_path=REPO_ROOT / "config.yaml",
        title="A Public Talk",
        source_id=source_id,
        started_at_override=("2026-08-12T00:00:00Z", "day", "upload_date"),
        provenance_extra={"tool": "youtube-drop", "url": WATCH_URL},
    )
    assert result.status == "created"
    metadata = read_drop_metadata(result.path)
    assert metadata["sourceId"] == source_id
    assert (metadata["startedAt"], metadata["startedAtPrecision"]) == (
        "2026-08-12T00:00:00Z",
        "day",
    )
    provenance = metadata["provenance"]
    assert provenance["tool"] == "youtube-drop"  # extra overrides the default
    assert provenance["url"] == WATCH_URL
    assert provenance["startedAtSource"] == "upload_date"
    assert provenance["files"][0]["dropFilename"] == "transcript.vtt"

    # Identity is the verbatim source id: different bytes, same id -> exists.
    other = tmp_path / "other.vtt"
    other.write_text(TRANSCRIPT_VTT + "\nmore\n", encoding="utf-8")
    again = mintdrop.mint(
        supplied=[str(other)],
        corpus="real",
        drops_root=root,
        config_path=REPO_ROOT / "config.yaml",
        source_id=source_id,
        started_at_override=("2026-08-12T00:00:00Z", "day", "upload_date"),
    )
    assert again.status == "exists"
    assert again.path == result.path


@pytest.mark.parametrize("protected_key", sorted(mintdrop.MINT_OWNED_PROVENANCE_KEYS))
def test_mint_refuses_every_provenance_collision_before_writing(
    protected_key: str, tmp_path: Path
) -> None:
    vtt = tmp_path / "talk.vtt"
    vtt.write_text(TRANSCRIPT_VTT, encoding="utf-8")
    root = tmp_path / "drops"
    root.mkdir()

    with pytest.raises(
        mintdrop.MintError,
        match=rf"provenance_extra collides with mint-owned keys: {protected_key}",
    ):
        mintdrop.mint(
            supplied=[str(vtt)],
            corpus="real",
            drops_root=root,
            config_path=REPO_ROOT / "config.yaml",
            source_id=f"youtube:{VALID_ID}",
            started_at_override=("2026-08-12T00:00:00Z", "day", "upload_date"),
            provenance_extra={protected_key: "fabricated"},
        )

    assert list(root.iterdir()) == []


def test_mint_refuses_a_non_mapping_provenance_override_before_writing(
    tmp_path: Path,
) -> None:
    vtt = tmp_path / "talk.vtt"
    vtt.write_text(TRANSCRIPT_VTT, encoding="utf-8")
    root = tmp_path / "drops"
    root.mkdir()

    with pytest.raises(mintdrop.MintError, match="provenance_extra must be a mapping"):
        mintdrop.mint(
            supplied=[str(vtt)],
            corpus="real",
            drops_root=root,
            config_path=REPO_ROOT / "config.yaml",
            source_id=f"youtube:{VALID_ID}",
            started_at_override=("2026-08-12T00:00:00Z", "day", "upload_date"),
            provenance_extra=[("files", [])],  # type: ignore[arg-type]
        )

    assert list(root.iterdir()) == []


def test_provenance_collision_refuses_even_when_source_id_already_exists(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.vtt"
    first.write_text(TRANSCRIPT_VTT, encoding="utf-8")
    second = tmp_path / "second.vtt"
    second.write_text(TRANSCRIPT_VTT + "\nsecond\n", encoding="utf-8")
    root = tmp_path / "drops"
    root.mkdir()
    source_id = f"youtube:{VALID_ID}"
    created = mintdrop.mint(
        supplied=[str(first)],
        corpus="real",
        drops_root=root,
        config_path=REPO_ROOT / "config.yaml",
        source_id=source_id,
        started_at_override=("2026-08-12T00:00:00Z", "day", "upload_date"),
    )
    before = sorted(root.iterdir())

    with pytest.raises(mintdrop.MintError, match="mint-owned keys: files"):
        mintdrop.mint(
            supplied=[str(second)],
            corpus="real",
            drops_root=root,
            config_path=REPO_ROOT / "config.yaml",
            source_id=source_id,
            started_at_override=("2026-08-12T00:00:00Z", "day", "upload_date"),
            provenance_extra={"files": []},
        )
    assert created.path in before
    assert sorted(root.iterdir()) == before


def test_mint_without_overrides_is_todays_behaviour_unchanged(tmp_path: Path) -> None:
    """Defaults preserve today's behaviour: sha256 identity, tool mint-drop,
    no url key — every existing call site byte-identical in effect."""
    txt = tmp_path / "notes.txt"
    txt.write_text("[0:00] Peyton Fenwick: morning all\n", encoding="utf-8")
    root = tmp_path / "drops"
    root.mkdir()

    result = mintdrop.mint(
        supplied=[str(txt)],
        corpus="real",
        drops_root=root,
        config_path=REPO_ROOT / "config.yaml",
        started_at_argument="2026-08-05T12:00:19Z",
    )
    assert result.status == "created"
    metadata = read_drop_metadata(result.path)
    assert metadata["sourceId"] == "sha256:" + mintdrop.sha256_and_size(txt)[0]
    provenance = metadata["provenance"]
    assert provenance["tool"] == "mint-drop"
    assert provenance["startedAtSource"] == "--started-at"
    assert "url" not in provenance


# --- configuration -----------------------------------------------------------


def test_acquisition_config_defaults_and_the_committed_block_agree() -> None:
    from meetingminer.config import AcquisitionConfig

    assert AcquisitionConfig().youtube.max_duration_minutes == 180
    committed = yaml.safe_load(
        (REPO_ROOT / "config.yaml").read_text(encoding="utf-8")
    )
    assert committed["acquisition"]["youtube"]["max_duration_minutes"] == 180


# --- CLI parity with mint-drop ----------------------------------------------


def test_main_classifies_an_invalid_url_before_resolving_a_writable_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "drops"
    root.mkdir()
    monkeypatch.setattr(youtube, "_load_cli_config", lambda: cli_config(root))

    def mutating_resolver(explicit: str | None, config: object) -> Path:
        (root / ".staging").mkdir()
        return root

    monkeypatch.setattr(youtube, "resolve_drops_root", mutating_resolver)
    assert youtube.main(["https://example.com/not-youtube"]) == 1
    assert list(root.iterdir()) == []
    assert "fatal: youtube-drop refused: not a YouTube video URL" in capsys.readouterr().err


def test_main_defers_the_drops_root_write_probe_until_acquisition_accepts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "drops"
    root.mkdir()
    monkeypatch.setattr(youtube, "_load_cli_config", lambda: cli_config(root))
    monkeypatch.setattr(youtube, "resolve_api_url", lambda explicit: "http://api.test")

    def mutating_resolver(explicit: str | None, config: object) -> Path:
        (root / ".staging").mkdir()
        return root

    monkeypatch.setattr(youtube, "resolve_drops_root", mutating_resolver)
    monkeypatch.setattr(
        youtube,
        "acquire",
        lambda url, **kwargs: (_ for _ in ()).throw(
            youtube.YoutubeError("probe refusal")
        ),
    )

    assert youtube.main([WATCH_URL]) == 1
    assert list(root.iterdir()) == []


@pytest.mark.parametrize("result_status", ["created", "exists"])
def test_main_posts_created_and_existing_drops_with_resolver_and_cap_parity(
    result_status: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "drops"
    placement = root / "imports"
    placement.mkdir(parents=True)
    config = cli_config(root)
    result = cli_result(tmp_path, status=result_status)
    seen: dict[str, Any] = {}
    monkeypatch.setattr(youtube, "_load_cli_config", lambda: config)

    def resolve_api(explicit: str | None) -> str:
        seen["api_arg"] = explicit
        return "http://resolved.test"

    def resolve_drops(explicit: str | None, received: object) -> Path:
        seen["drops_arg"] = explicit
        seen["config"] = received
        return placement

    def acquire(url: str, **kwargs: Any) -> mintdrop.MintResult:
        seen["acquire_url"] = url
        prepare_drops_root = kwargs.pop("prepare_drops_root")
        seen["prepared_root"] = prepare_drops_root()
        seen["acquire_kwargs"] = kwargs
        return result

    def post(api_url: str, drop_path: Path) -> tuple[str, int, str | None]:
        seen["post"] = (api_url, drop_path)
        return "created", 201, "job-1"

    monkeypatch.setattr(youtube, "resolve_api_url", resolve_api)
    monkeypatch.setattr(youtube, "resolve_drops_root", resolve_drops)
    monkeypatch.setattr(youtube, "acquire", acquire)
    monkeypatch.setattr(youtube, "post_ingest", post)
    monkeypatch.setattr(youtube, "_report", lambda value, files: None)

    assert youtube.main(
        [WATCH_URL, "--drops", str(placement), "--api", "http://requested.test"]
    ) == 0
    assert seen["api_arg"] == "http://requested.test"
    assert seen["drops_arg"] == str(placement)
    assert seen["config"] is config
    assert seen["acquire_url"] == WATCH_URL
    assert seen["prepared_root"] == placement
    assert seen["acquire_kwargs"] == {
        "drops_root": placement,
        "identity_root": root,
        "config_path": REPO_ROOT / "config.yaml",
        "max_duration_minutes": 37,
    }
    assert seen["post"] == ("http://resolved.test", result.path)


def test_main_no_post_prints_exact_recovery_and_suppresses_intake(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "drops"
    result = cli_result(tmp_path)
    monkeypatch.setattr(youtube, "_load_cli_config", lambda: cli_config(root))
    monkeypatch.setattr(youtube, "resolve_api_url", lambda explicit: "http://api.test")
    monkeypatch.setattr(youtube, "resolve_drops_root", lambda explicit, config: root)
    monkeypatch.setattr(youtube, "acquire", lambda url, **kwargs: result)
    monkeypatch.setattr(youtube, "_report", lambda value, files: None)
    monkeypatch.setattr(youtube, "post_ingest", _must_not_run("post_ingest"))
    monkeypatch.setattr(
        youtube,
        "ingest_command",
        lambda api_url, path: f"REPOST {api_url} {path}",
    )

    assert youtube.main([WATCH_URL, "--no-post"]) == 0
    assert f"REPOST http://api.test {result.path}" in capsys.readouterr().out


def test_main_reports_duplicate_intake(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "drops"
    result = cli_result(tmp_path, status="exists")
    monkeypatch.setattr(youtube, "_load_cli_config", lambda: cli_config(root))
    monkeypatch.setattr(youtube, "resolve_api_url", lambda explicit: "http://api.test")
    monkeypatch.setattr(youtube, "resolve_drops_root", lambda explicit, config: root)
    monkeypatch.setattr(youtube, "acquire", lambda url, **kwargs: result)
    monkeypatch.setattr(youtube, "_report", lambda value, files: None)
    monkeypatch.setattr(
        youtube, "post_ingest", lambda api_url, path: ("duplicate", 409, None)
    )

    assert youtube.main([WATCH_URL]) == 0
    assert "intake already ingested (409) jobId (none)" in capsys.readouterr().out


def test_main_intake_failure_is_nonzero_with_exact_repost_guidance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "drops"
    result = cli_result(tmp_path)
    monkeypatch.setattr(youtube, "_load_cli_config", lambda: cli_config(root))
    monkeypatch.setattr(youtube, "resolve_api_url", lambda explicit: "http://api.test")
    monkeypatch.setattr(youtube, "resolve_drops_root", lambda explicit, config: root)
    monkeypatch.setattr(youtube, "acquire", lambda url, **kwargs: result)
    monkeypatch.setattr(youtube, "_report", lambda value, files: None)
    monkeypatch.setattr(
        youtube,
        "post_ingest",
        lambda api_url, path: (_ for _ in ()).throw(mintdrop.IntakeError("down")),
    )
    monkeypatch.setattr(
        youtube,
        "ingest_command",
        lambda api_url, path: f"REPOST {api_url} {path}",
    )

    assert youtube.main([WATCH_URL]) == 1
    error = capsys.readouterr().err
    assert "intake FAILED: down" in error
    assert "re-POST this exact drop rather than re-running youtube-drop" in error
    assert f"REPOST http://api.test {result.path}" in error


# --- the Makefile door -------------------------------------------------------


def test_makefile_has_the_youtube_drop_target_with_a_url_guard() -> None:
    makefile = (REPO_ROOT / "infra" / "Makefile").read_text(encoding="utf-8")
    assert "\nyoutube-drop: check-env\n" in makefile
    recipe = makefile.split("\nyoutube-drop: check-env\n", 1)[1].split("\n\n", 1)[0]
    assert 'error: URL is required' in recipe
    assert "unexport URL" in makefile
    assert 'export MM_YOUTUBE_URL := $(value URL)' in makefile
    assert '"$${MM_YOUTUBE_URL}" $(YT_ARGS)' in recipe
    assert '$(URL)' not in recipe
    # Placed directly after the mint-drop recipe, as the wave footprint pins.
    assert makefile.index("\nmint-drop: check-env\n") < makefile.index(
        "\nyoutube-drop: check-env\n"
    )


@pytest.mark.parametrize("attack", ["shell", "make-shell"])
def test_makefile_passes_a_hostile_url_as_one_data_argument(
    attack: str, tmp_path: Path
) -> None:
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    fake_python = venv / "bin" / "python"
    fake_python.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$MM_TEST_CAPTURE\"\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    env_file = tmp_path / ".env"
    env_file.write_text("MM_DROPS_ROOT=/tmp/drops\n", encoding="utf-8")
    capture = tmp_path / "args.txt"
    injected = tmp_path / "injected"
    hostile = (
        f'{WATCH_URL}"; touch {injected}; #'
        if attack == "shell"
        else f"{WATCH_URL}$(shell touch {injected})"
    )
    env = dict(os.environ, MM_TEST_CAPTURE=str(capture))

    completed = subprocess.run(
        [
            "make",
            "-f",
            str(REPO_ROOT / "infra" / "Makefile"),
            "youtube-drop",
            f"URL={hostile}",
            f"ROOT={REPO_ROOT}",
            f"VENV={venv}",
            f"ENVFILE={env_file}",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )

    assert completed.returncode == 0, completed.stderr
    assert not injected.exists()
    assert capture.read_text(encoding="utf-8").splitlines() == [
        "-m",
        "meetingminer.youtube",
        hostile,
    ]


# --- the one network test ----------------------------------------------------


@pytest.mark.skipif(
    os.environ.get(NETWORK_FLAG) != "1",
    reason=f"real yt-dlp acquisition over the network: set {NETWORK_FLAG}=1 to run it",
)
def test_real_youtube_acquisition_end_to_end(tmp_path: Path) -> None:
    """Acquire a short public video for real — network, yt-dlp, ffmpeg.

    Run it by hand (the download outlives the fast-test budget, so raise it
    for this one run)::

        MM_YOUTUBE_NETWORK_TEST=1 uv run --project server pytest \\
            server/tests/test_youtube.py::test_real_youtube_acquisition_end_to_end \\
            -o mm_fast_test_budget_seconds=600 -q

    At integrate this test gains ``pytest.mark.slow`` plus the matching
    ``SLOW_TESTS`` pin in ``test_compose_contract.py`` — recorded as the
    story spec's deferred item; the mark cannot land from this branch.
    """
    root = tmp_path / "drops"
    root.mkdir()
    url = "https://www.youtube.com/watch?v=jNQXAC9IVRw"  # 19s, public, stable
    result = youtube.acquire(
        url,
        drops_root=root,
        identity_root=root,
        config_path=REPO_ROOT / "config.yaml",
        max_duration_minutes=180,
    )
    assert result.status == "created"
    metadata = read_drop_metadata(result.path)
    assert metadata["sourceId"] == "youtube:jNQXAC9IVRw"
    assert metadata["corpus"] == "real"
    assert (result.path / "recording.mp4").stat().st_size > 0
    assert "info.json" not in {p.name for p in result.path.iterdir()}

    again = youtube.acquire(
        url,
        drops_root=root,
        identity_root=root,
        config_path=REPO_ROOT / "config.yaml",
        max_duration_minutes=180,
    )
    assert again.status == "exists"
    assert again.path == result.path
