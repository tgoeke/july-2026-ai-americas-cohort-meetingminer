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


# --- the exists short-circuit ------------------------------------------------


def test_an_already_minted_video_short_circuits_before_any_yt_dlp_call(
    drops_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Acceptance: `find_existing_drop` answers first; the downloader and the
    probe are never invoked and no network traffic for media occurs."""
    source_id = f"youtube:{VALID_ID}"
    drop = drops_root / mintdrop.drop_name(
        "2026-08-12T15:30:19Z", "Platform Sync — August", source_id
    )
    drop.mkdir()
    metadata = {
        "schemaVersion": 1,
        "sourceId": source_id,
        "corpus": "real",
        "startedAt": "2026-08-12T15:30:19Z",
        "startedAtPrecision": "second",
        "provenance": {"tool": "youtube-drop", "url": WATCH_URL},
    }
    (drop / "metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )

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


def test_mint_refuses_provenance_collisions_before_writing(tmp_path: Path) -> None:
    vtt = tmp_path / "talk.vtt"
    vtt.write_text(TRANSCRIPT_VTT, encoding="utf-8")
    root = tmp_path / "drops"
    root.mkdir()

    with pytest.raises(
        mintdrop.MintError,
        match=r"provenance_extra collides with mint-owned keys: files, mintedAt",
    ):
        mintdrop.mint(
            supplied=[str(vtt)],
            corpus="real",
            drops_root=root,
            config_path=REPO_ROOT / "config.yaml",
            source_id=f"youtube:{VALID_ID}",
            started_at_override=("2026-08-12T00:00:00Z", "day", "upload_date"),
            provenance_extra={"files": [], "mintedAt": "fabricated"},
        )

    assert list(root.iterdir()) == []


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


# --- the Makefile door -------------------------------------------------------


def test_makefile_has_the_youtube_drop_target_with_a_url_guard() -> None:
    makefile = (REPO_ROOT / "infra" / "Makefile").read_text(encoding="utf-8")
    assert "\nyoutube-drop: check-env\n" in makefile
    recipe = makefile.split("\nyoutube-drop: check-env\n", 1)[1].split("\n\n", 1)[0]
    assert 'error: URL is required' in recipe
    assert '-m meetingminer.youtube "$(URL)" $(YT_ARGS)' in recipe
    # Placed directly after the mint-drop recipe, as the wave footprint pins.
    assert makefile.index("\nmint-drop: check-env\n") < makefile.index(
        "\nyoutube-drop: check-env\n"
    )


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
