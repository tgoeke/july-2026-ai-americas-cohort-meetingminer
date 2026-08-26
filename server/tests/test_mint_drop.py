"""``mint-drop``: the bring-your-own-recording producer (story 2.1b).

Store-free by construction — the drops root is a ``tmp_path`` directory and no
Postgres fixture is requested — but *not* contract-free: every drop these tests
produce is validated against ``docs/source-drop.schema.json`` with the same
``Draft202012Validator`` + ``FormatChecker`` the api uses at intake. A drop is
write-once, so a metadata shape that would earn a 422 could afterwards be
neither ingested nor deleted; asserting the schema here is what keeps the tool
and the door on one contract.

ffprobe is stubbed for everything except the two end-to-end tests: the point of
most rows is the minting logic, not the codec, and a suite that needs ffmpeg to
say anything at all says nothing on a machine without it.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import jsonschema
import pytest
import uvicorn

from meetingminer import mintdrop
from meetingminer.domain.drops import drop_relative_path
from meetingminer.pipeline import media

from conftest import DROPS_ROOT, FFMPEG, REPO_ROOT, requires_ffmpeg

SCHEMA = json.loads(
    (REPO_ROOT / "docs" / "source-drop.schema.json").read_text(encoding="utf-8")
)
VALIDATOR = jsonschema.Draft202012Validator(
    SCHEMA, format_checker=jsonschema.FormatChecker()
)

VIDEO_BYTES = b"pretend this is an mp4 " * 64
TRANSCRIPT_TEXT = "[0:00] Peyton Fenwick: morning all\n[0:04] Priya Holloway: morning\n"
TRANSCRIPT_VTT = "WEBVTT\n\n00:00:00.000 --> 00:00:04.000\nmorning all\n"


# --- helpers ---------------------------------------------------------------


def schema_errors(metadata: dict[str, Any]) -> list[str]:
    return [
        ("/".join(str(p) for p in error.absolute_path) or "(root)") + ": " + error.message
        for error in VALIDATOR.iter_errors(metadata)
    ]


def read_drop_metadata(drop: Path) -> dict[str, Any]:
    """A produced drop's metadata, asserted schema-valid on the way out."""
    metadata = json.loads((drop / "metadata.json").read_text(encoding="utf-8"))
    assert schema_errors(metadata) == [], f"{drop} violates the source-drop schema"
    return metadata


def drop_dirs(root: Path) -> list[Path]:
    """Every finalized drop visible under the root (staging is not one)."""
    return sorted(p for p in root.iterdir() if not p.name.startswith("."))


def facts(*, has_video: bool = True) -> media.MediaFacts:
    return media.MediaFacts(
        duration_ms=6000,
        container="mov,mp4,m4a",
        size_bytes=len(VIDEO_BYTES),
        video_codec="h264" if has_video else None,
        width=320 if has_video else None,
        height=240 if has_video else None,
        frame_rate=10.0 if has_video else None,
        video_bit_rate=None,
        audio_codec="aac",
        audio_channels=1,
        audio_sample_rate=16000,
        audio_bit_rate=None,
    )


@pytest.fixture()
def stub_probe(monkeypatch: pytest.MonkeyPatch):
    """Install ffprobe stand-ins; returns a setter for the two answers."""

    def _install(
        *,
        has_video: bool = True,
        creation_time: str | None = None,
        error: str | None = None,
    ) -> None:
        def _probe_media(path: Path) -> media.MediaFacts:
            if error is not None:
                raise media.MediaToolError(error)
            return facts(has_video=has_video)

        def _probe_creation_time(path: Path) -> str | None:
            return creation_time

        monkeypatch.setattr(mintdrop, "probe_media", _probe_media)
        monkeypatch.setattr(mintdrop, "probe_creation_time", _probe_creation_time)

    _install()
    return _install


@pytest.fixture()
def mint_root(tmp_path: Path) -> Iterator[Path]:
    # The producer may only write under the configured intake root.  A unique
    # child preserves per-test isolation while exercising the real boundary.
    root = DROPS_ROOT / f"mint-{tmp_path.name}"
    root.mkdir()
    try:
        yield root
    finally:
        # This fixture owns exactly this child, never the shared configured
        # root or drops emitted by any other concurrent test process.
        shutil.rmtree(root)


@pytest.fixture()
def video(tmp_path: Path) -> Path:
    path = tmp_path / "Team Sync.mp4"
    # The configured drops root is shared by concurrent server-suite runs.
    # Source identity is intentionally global there, so test videos must not
    # impersonate the same user recording across workers.
    path.write_bytes(VIDEO_BYTES + tmp_path.name.encode())
    return path


@pytest.fixture()
def no_http(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly if a test that must make no HTTP call makes one."""

    def _forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the command made an HTTP call")

    monkeypatch.setattr(urllib.request, "urlopen", _forbidden)


def run(root: Path, *args: str, post: bool = False) -> int:
    argv = [*args, "--drops", str(root)]
    if not post:
        argv.append("--no-post")
    return mintdrop.main(argv)


# --- the I/O matrix --------------------------------------------------------


def test_video_only_produces_a_conforming_drop(
    mint_root: Path, video: Path, stub_probe, no_http, capsys
) -> None:
    """Acceptance: name, contents, schema, and a byte-identical recording."""
    code = run(
        mint_root,
        str(video),
        "--corpus", "scripted",
        "--title", "Daily Standup",
        "--started-at", "2026-08-05T12:00:19Z",
    )
    assert code == 0

    drops = drop_dirs(mint_root)
    assert len(drops) == 1
    drop = drops[0]
    metadata = read_drop_metadata(drop)
    assert drop.name == "2026-08-05-daily-standup-" + mintdrop.source_id_digest(
        metadata["sourceId"]
    )
    assert sorted(p.name for p in drop.iterdir()) == ["metadata.json", "recording.mp4"]
    assert (drop / "recording.mp4").read_bytes() == video.read_bytes()
    assert metadata["corpus"] == "scripted"
    assert metadata["provenance"]["title"] == "Daily Standup"
    # The only record of where these bytes came from: the original is neither
    # copied back nor modified.
    entry = metadata["provenance"]["files"][0]
    assert entry["sourcePath"] == str(video.resolve())
    assert entry["byteSize"] == video.stat().st_size
    assert metadata["sourceId"] == "sha256:" + entry["sha256"]
    assert "url" not in metadata["provenance"]
    assert "participants" not in metadata
    assert "created" in capsys.readouterr().out


def test_video_plus_transcript_lands_under_canonical_filenames(
    mint_root: Path, video: Path, tmp_path: Path, stub_probe, no_http
) -> None:
    vtt = tmp_path / "Team Sync.vtt"
    vtt.write_text(TRANSCRIPT_VTT, encoding="utf-8")
    text = tmp_path / "Team Sync.txt"
    text.write_text(TRANSCRIPT_TEXT, encoding="utf-8")

    assert run(
        mint_root,
        str(text), str(vtt), str(video),  # argument order must not matter
        "--corpus", "real",
        "--started-at", "2026-08-05T12:00:19Z",
    ) == 0

    drop = drop_dirs(mint_root)[0]
    assert sorted(p.name for p in drop.iterdir()) == [
        "metadata.json",
        "recording.mp4",
        "transcript.txt",
        "transcript.vtt",
    ]
    metadata = read_drop_metadata(drop)
    # Primary is the recording, whichever order the files were listed in, so a
    # later transcript-only mint of the same video cannot change the identity.
    assert metadata["sourceId"] == "sha256:" + mintdrop.sha256_and_size(video)[0]
    assert (drop / "transcript.vtt").read_text(encoding="utf-8") == TRANSCRIPT_VTT
    assert (drop / "transcript.txt").read_text(encoding="utf-8") == TRANSCRIPT_TEXT


def test_transcript_only_drop_is_first_class(
    mint_root: Path, tmp_path: Path, stub_probe, no_http
) -> None:
    text = tmp_path / "Retro.txt"
    text.write_text(TRANSCRIPT_TEXT, encoding="utf-8")

    assert run(
        mint_root, str(text), "--corpus", "real", "--started-at", "2026-08-05"
    ) == 0

    drop = drop_dirs(mint_root)[0]
    assert sorted(p.name for p in drop.iterdir()) == ["metadata.json", "transcript.txt"]
    metadata = read_drop_metadata(drop)
    assert metadata["sourceId"] == "sha256:" + mintdrop.sha256_and_size(text)[0]
    assert (metadata["startedAt"], metadata["startedAtPrecision"]) == (
        "2026-08-05T00:00:00Z",
        "day",
    )


def test_nothing_ingestible_is_refused_before_anything_is_written(
    mint_root: Path, stub_probe, no_http, capsys
) -> None:
    assert run(mint_root, "--corpus", "real") == 1
    assert "nothing ingestible" in capsys.readouterr().err
    assert list(mint_root.iterdir()) == []


def test_a_file_with_no_canonical_name_is_refused(
    mint_root: Path, tmp_path: Path, stub_probe, no_http, capsys
) -> None:
    notes = tmp_path / "notes.docx"
    notes.write_bytes(b"not evidence")
    assert run(mint_root, str(notes), "--corpus", "real") == 1
    assert "no canonical drop filename" in capsys.readouterr().err
    assert list(mint_root.iterdir()) == []


def test_rerun_on_the_same_content_reports_exists_and_writes_nothing(
    mint_root: Path, video: Path, stub_probe, no_http, capsys
) -> None:
    """Acceptance: the sourceId match decides, not the directory name."""
    assert run(
        mint_root, str(video),
        "--corpus", "scripted",
        "--title", "Daily Standup",
        "--started-at", "2026-08-05T12:00:19Z",
    ) == 0
    drop = drop_dirs(mint_root)[0]
    before = (drop / "metadata.json").read_text(encoding="utf-8")
    capsys.readouterr()

    assert run(
        mint_root, str(video),
        "--corpus", "real",
        "--title", "Something Else Entirely",
        "--started-at", "2020-01-01",
    ) == 0

    out = capsys.readouterr().out
    assert out.startswith("exists")
    assert str(drop) in out
    assert drop_dirs(mint_root) == [drop]
    assert (drop / "metadata.json").read_text(encoding="utf-8") == before


def test_explicit_started_at_is_recorded_verbatim_with_second_precision(
    mint_root: Path, video: Path, stub_probe, no_http
) -> None:
    assert run(
        mint_root, str(video), "--corpus", "real",
        "--started-at", "2026-08-05T12:00:19Z",
    ) == 0
    metadata = read_drop_metadata(drop_dirs(mint_root)[0])
    assert (metadata["startedAt"], metadata["startedAtPrecision"]) == (
        "2026-08-05T12:00:19Z",
        "second",
    )
    assert metadata["provenance"]["startedAtSource"] == "--started-at"


def test_an_offset_started_at_is_converted_to_utc(
    mint_root: Path, video: Path, stub_probe, no_http
) -> None:
    assert run(
        mint_root, str(video), "--corpus", "real",
        "--started-at", "2026-08-05T08:00:19-04:00",
    ) == 0
    assert read_drop_metadata(drop_dirs(mint_root)[0])["startedAt"] == "2026-08-05T12:00:19Z"


@pytest.mark.parametrize(
    "value",
    [
        "2026-08-05T12:00:19",  # no offset: ambiguous, and a drop is write-once
        "2026-02-31",           # not a real calendar day
        "yesterday",
    ],
)
def test_an_unusable_started_at_is_refused(
    mint_root: Path, video: Path, stub_probe, no_http, capsys, value: str
) -> None:
    assert run(mint_root, str(video), "--corpus", "real", "--started-at", value) == 1
    assert "--started-at" in capsys.readouterr().err
    assert list(mint_root.iterdir()) == []


def test_started_at_falls_back_to_the_containers_creation_time(
    mint_root: Path, video: Path, stub_probe, no_http
) -> None:
    stub_probe(creation_time="2026-08-05T12:00:19.000000Z")
    assert run(mint_root, str(video), "--corpus", "real") == 0
    metadata = read_drop_metadata(drop_dirs(mint_root)[0])
    assert (metadata["startedAt"], metadata["startedAtPrecision"]) == (
        "2026-08-05T12:00:19Z",
        "second",
    )
    assert metadata["provenance"]["startedAtSource"] == "container creation_time"


@pytest.mark.parametrize(
    "creation_time",
    [
        None,                            # the container carries none
        "1904-01-01T00:00:00.000000Z",   # the ISO base media format epoch
        "1970-01-01T00:00:00.000000Z",   # the Unix epoch; neither is a meeting
        "2026-08-05 12:00:19",           # no offset: not an instant
    ],
)
def test_no_derivable_start_time_is_refused_rather_than_guessed(
    mint_root: Path, video: Path, stub_probe, no_http, capsys, creation_time: str | None
) -> None:
    stub_probe(creation_time=creation_time)
    assert run(mint_root, str(video), "--corpus", "real") == 1
    err = capsys.readouterr().err
    assert "--started-at" in err and "mtime" in err
    assert list(mint_root.iterdir()) == []


def test_a_transcript_only_mint_never_reaches_for_a_timestamp(
    mint_root: Path, tmp_path: Path, stub_probe, no_http, capsys
) -> None:
    text = tmp_path / "Retro.txt"
    text.write_text(TRANSCRIPT_TEXT, encoding="utf-8")
    assert run(mint_root, str(text), "--corpus", "real") == 1
    assert "carries no timestamp metadata" in capsys.readouterr().err
    assert list(mint_root.iterdir()) == []


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root ignores file permissions, so chmod(0) cannot make a file unreadable",
)
def test_an_unreadable_file_is_refused(
    mint_root: Path, tmp_path: Path, stub_probe, no_http, capsys
) -> None:
    text = tmp_path / "Retro.txt"
    text.write_text(TRANSCRIPT_TEXT, encoding="utf-8")
    text.chmod(0o000)
    try:
        assert run(mint_root, str(text), "--corpus", "real", "--started-at", "2026-08-05") == 1
        assert "could not be read" in capsys.readouterr().err
    finally:
        text.chmod(0o600)
    assert list(mint_root.iterdir()) == []


def test_a_missing_file_is_refused(
    mint_root: Path, tmp_path: Path, stub_probe, no_http, capsys
) -> None:
    assert run(mint_root, str(tmp_path / "gone.mp4"), "--corpus", "real") == 1
    assert "does not exist" in capsys.readouterr().err
    assert list(mint_root.iterdir()) == []


def test_a_non_video_is_refused_at_probe(
    mint_root: Path, video: Path, stub_probe, no_http, capsys
) -> None:
    """A .docx renamed .mp4: ffprobe rejects it before a drop exists."""
    stub_probe(error="ffprobe failed for video: moov atom not found")
    assert run(mint_root, str(video), "--corpus", "real", "--started-at", "2026-08-05") == 1
    assert "not a readable video" in capsys.readouterr().err
    assert list(mint_root.iterdir()) == []


def test_a_missing_ffprobe_is_named_as_such_not_blamed_on_the_file(
    mint_root: Path, video: Path, stub_probe, no_http, capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """"your file is not a video" for a tool that is not installed sends the
    operator to inspect a recording that is perfectly fine."""
    monkeypatch.setattr(mintdrop.shutil, "which", lambda name: None)
    assert run(mint_root, str(video), "--corpus", "real", "--started-at", "2026-08-05") == 1
    err = capsys.readouterr().err
    assert "ffprobe is not on PATH" in err
    assert "brew install ffmpeg" in err
    assert "is not a readable video" not in err
    assert list(mint_root.iterdir()) == []


def test_an_audio_only_file_is_refused_at_probe(
    mint_root: Path, video: Path, stub_probe, no_http, capsys
) -> None:
    stub_probe(has_video=False)
    assert run(mint_root, str(video), "--corpus", "real", "--started-at", "2026-08-05") == 1
    assert "carries no video stream" in capsys.readouterr().err
    assert list(mint_root.iterdir()) == []


def test_a_failure_after_staging_began_finalizes_nothing(
    mint_root: Path, video: Path, stub_probe, no_http, capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Acceptance: no drop directory, and no staging directory, is left."""
    seen: list[Path] = []

    def _die(supplied: mintdrop.SuppliedFile, destination: Path) -> None:
        seen.append(destination)
        raise mintdrop.MintError("no space left on device")

    monkeypatch.setattr(mintdrop, "_copy_verified", _die)
    assert run(
        mint_root, str(video), "--corpus", "real", "--started-at", "2026-08-05"
    ) == 1
    # The staging directory really was created and written into before the
    # failure, so this is the atomicity claim and not a no-op.
    assert seen and seen[0].parent.parent.name == mintdrop.STAGING_DIRNAME
    assert "no space left" in capsys.readouterr().err
    assert list(mint_root.iterdir()) == []


def test_a_short_copy_is_caught_before_the_drop_is_finalized(
    mint_root: Path, video: Path, stub_probe, no_http, capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A truncated copy must not finalize a drop whose own checksum is wrong."""

    def _truncating_copy(source: Any, destination: Any) -> None:
        Path(destination).write_bytes(VIDEO_BYTES[:10])

    monkeypatch.setattr(mintdrop.shutil, "copyfile", _truncating_copy)
    assert run(
        mint_root, str(video), "--corpus", "real", "--started-at", "2026-08-05"
    ) == 1
    assert "does not match the original" in capsys.readouterr().err
    assert list(mint_root.iterdir()) == []


def test_the_staged_recording_is_reprobed_before_it_is_finalized(
    mint_root: Path, video: Path, stub_probe, no_http, capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The initial probe cannot describe bytes replaced before the copy."""
    monkeypatch.setattr(mintdrop.shutil, "which", lambda name: "/usr/bin/ffprobe")

    original_bytes = video.read_bytes()

    def _probe(path: Path) -> media.MediaFacts:
        if path == video:
            # The first probe sees the original recording, then a concurrent
            # replacement changes what digest/copy will stage.
            video.write_bytes(b"not a video after the first probe")
            return facts(has_video=True)
        return facts(has_video=path.read_bytes() == original_bytes)

    monkeypatch.setattr(mintdrop, "probe_media", _probe)
    assert run(
        mint_root, str(video), "--corpus", "real", "--started-at", "2026-08-05"
    ) == 1
    assert "recording.mp4 carries no video stream" in capsys.readouterr().err
    assert list(mint_root.iterdir()) == []


def test_a_drop_that_would_fail_the_schema_is_never_finalized(
    mint_root: Path, video: Path, stub_probe, no_http, capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The validate-before-rename gate, exercised through a broken metadata."""
    original = mintdrop.build_metadata

    def _broken(**kwargs: Any) -> dict[str, Any]:
        metadata = original(**kwargs)
        metadata["corpus"] = "neither"
        return metadata

    monkeypatch.setattr(mintdrop, "build_metadata", _broken)
    assert run(
        mint_root, str(video), "--corpus", "real", "--started-at", "2026-08-05"
    ) == 1
    assert "source-drop contract" in capsys.readouterr().err
    assert list(mint_root.iterdir()) == []


def test_an_unreadable_same_digest_drop_stops_the_mint(
    mint_root: Path, video: Path, stub_probe, no_http, capsys
) -> None:
    """"Cannot tell" must not read as "not there" — that mints a duplicate."""
    source_id = "sha256:" + mintdrop.sha256_and_size(video)[0]
    squatter = mint_root / f"2020-01-01-whatever-{mintdrop.source_id_digest(source_id)}"
    squatter.mkdir()

    assert run(
        mint_root, str(video), "--corpus", "real", "--started-at", "2026-08-05"
    ) == 1
    assert "could not be read" in capsys.readouterr().err
    assert drop_dirs(mint_root) == [squatter]


def test_a_missing_drops_root_is_refused(
    tmp_path: Path, video: Path, stub_probe, no_http, capsys
) -> None:
    assert run(tmp_path / "absent", str(video), "--corpus", "real") == 1
    assert "does not exist" in capsys.readouterr().err


def test_the_drops_root_comes_from_the_configuration_when_no_flag_is_given(
    drops_root: Path, video: Path, tmp_path: Path, stub_probe, no_http
) -> None:
    """MM_DROPS_ROOT without restating it — the point of a Python command."""
    code = mintdrop.main(
        [str(video), "--corpus", "real", "--started-at", "2026-08-05", "--no-post"]
    )
    assert code == 0
    digest = mintdrop.source_id_digest("sha256:" + mintdrop.sha256_and_size(video)[0])
    minted = [p for p in drops_root.iterdir() if p.name.endswith(digest)]
    try:
        assert len(minted) == 1
        read_drop_metadata(minted[0])
    finally:
        # The session root is shared with every other drop test; leave it as
        # this test found it rather than relying on teardown order.
        for path in minted:
            shutil.rmtree(path)



def test_a_rerun_without_a_started_at_still_reports_exists(
    mint_root: Path, tmp_path: Path, stub_probe, no_http, capsys
) -> None:
    """Identity is known before the wall clock is, so `exists` must not need one.

    A transcript-only mint has no creation_time to fall back on. Resolving
    `startedAt` before the existence scan made the second run refuse with "a
    transcript carries no timestamp metadata" — the tool declining to recognise
    the drop it had itself just written.
    """
    text = tmp_path / "Retro.txt"
    text.write_text(TRANSCRIPT_TEXT, encoding="utf-8")
    assert run(mint_root, str(text), "--corpus", "real", "--started-at", "2026-08-05") == 0
    drop = drop_dirs(mint_root)[0]
    capsys.readouterr()

    # No --started-at this time, exactly as an operator repeating the command
    # after a failed POST would type it.
    assert run(mint_root, str(text), "--corpus", "real") == 0
    out = capsys.readouterr().out
    assert out.startswith("exists")
    assert str(drop) in out
    assert drop_dirs(mint_root) == [drop]


def test_a_rerun_that_brings_new_evidence_says_what_it_ignored(
    mint_root: Path, video: Path, tmp_path: Path, stub_probe, no_http, capsys
) -> None:
    """Report-only: a finalized drop is never written into (AD-13)."""
    assert run(
        mint_root, str(video), "--corpus", "real", "--started-at", "2026-08-05"
    ) == 0
    drop = drop_dirs(mint_root)[0]
    capsys.readouterr()

    text = tmp_path / "Team Sync.txt"
    text.write_text(TRANSCRIPT_TEXT, encoding="utf-8")
    assert run(
        mint_root, str(video), str(text), "--corpus", "real", "--started-at", "2026-08-05"
    ) == 0

    out = capsys.readouterr().out
    assert out.startswith("exists")
    assert "ignored" in out and "transcript.txt" in out
    assert sorted(p.name for p in drop.iterdir()) == ["metadata.json", "recording.mp4"]


def test_the_default_title_is_the_primary_files_stem(
    mint_root: Path, video: Path, stub_probe, no_http
) -> None:
    """`--title` omitted: the label and the directory name come from the file."""
    assert run(
        mint_root, str(video), "--corpus", "real", "--started-at", "2026-08-05"
    ) == 0
    drop = drop_dirs(mint_root)[0]
    metadata = read_drop_metadata(drop)
    assert metadata["provenance"]["title"] == "Team Sync"
    assert drop.name == "2026-08-05-team-sync-" + mintdrop.source_id_digest(
        metadata["sourceId"]
    )


def test_the_default_title_comes_from_the_primary_file_not_the_first_argument(
    mint_root: Path, video: Path, tmp_path: Path, stub_probe, no_http
) -> None:
    """Several files, no --title: the recording names the meeting."""
    text = tmp_path / "raw-export.txt"
    text.write_text(TRANSCRIPT_TEXT, encoding="utf-8")
    assert run(
        mint_root, str(text), str(video), "--corpus", "real", "--started-at", "2026-08-05"
    ) == 0
    assert read_drop_metadata(drop_dirs(mint_root)[0])["provenance"]["title"] == "Team Sync"


def test_two_files_mapping_to_one_canonical_name_are_refused(
    mint_root: Path, tmp_path: Path, stub_probe, no_http, capsys
) -> None:
    """A drop holds one recording. Without this, only the second is copied and
    the drop silently claims to be the whole meeting."""
    morning = tmp_path / "morning.mp4"
    morning.write_bytes(VIDEO_BYTES)
    afternoon = tmp_path / "afternoon.mp4"
    afternoon.write_bytes(VIDEO_BYTES + b"different")

    assert run(
        mint_root, str(morning), str(afternoon), "--corpus", "real",
        "--started-at", "2026-08-05",
    ) == 1
    assert "two files map to recording.mp4" in capsys.readouterr().err
    assert list(mint_root.iterdir()) == []


def test_an_empty_file_is_refused(
    mint_root: Path, tmp_path: Path, stub_probe, no_http, capsys
) -> None:
    """The only size gate a transcript-only mint gets: it never reaches ffprobe,
    so an empty transcript would otherwise ingest as a real meeting."""
    empty = tmp_path / "Retro.txt"
    empty.write_bytes(b"")
    assert run(mint_root, str(empty), "--corpus", "real", "--started-at", "2026-08-05") == 1
    assert "is empty" in capsys.readouterr().err
    assert list(mint_root.iterdir()) == []


def test_a_non_ascii_title_is_stored_as_utf8_not_escaped(
    mint_root: Path, video: Path, stub_probe, no_http
) -> None:
    """The puller writes raw UTF-8 into this same root; one spelling, not two."""
    assert run(
        mint_root, str(video), "--corpus", "real", "--title", "Café Sync",
        "--started-at", "2026-08-05",
    ) == 0
    drop = drop_dirs(mint_root)[0]
    raw = (drop / "metadata.json").read_text(encoding="utf-8")
    assert "Café Sync" in raw and "\\u00e9" not in raw
    assert read_drop_metadata(drop)["provenance"]["title"] == "Café Sync"


def test_a_file_standing_at_the_target_path_is_refused(
    mint_root: Path, video: Path, stub_probe, no_http, capsys
) -> None:
    """`rename` would replace an empty directory silently, so the guarantee that
    nothing finalized is overwritten cannot be left to the syscall."""
    source_id = "sha256:" + mintdrop.sha256_and_size(video)[0]
    squatter = mint_root / mintdrop.drop_name("2026-08-05T00:00:00Z", "Team Sync", source_id)
    squatter.write_bytes(b"not a drop")

    assert run(
        mint_root, str(video), "--corpus", "real", "--started-at", "2026-08-05"
    ) == 1
    assert "not a directory" in capsys.readouterr().err
    assert squatter.read_bytes() == b"not a drop"


def test_a_foreign_source_id_at_the_target_path_is_refused(
    mint_root: Path, video: Path, stub_probe, no_http, capsys
) -> None:
    """A title/date collision must not silently retire new content as exists."""
    source_id = "sha256:" + mintdrop.sha256_and_size(video)[0]
    squatter = mint_root / mintdrop.drop_name("2026-08-05T00:00:00Z", "Team Sync", source_id)
    squatter.mkdir()
    (squatter / "metadata.json").write_text(
        json.dumps({"sourceId": "sha256:" + "0" * 64}), encoding="utf-8"
    )

    assert run(
        mint_root, str(video), "--corpus", "real", "--started-at", "2026-08-05"
    ) == 1
    assert "different sourceId" in capsys.readouterr().err
    assert json.loads((squatter / "metadata.json").read_text()) == {
        "sourceId": "sha256:" + "0" * 64
    }


def test_minting_outside_the_configured_root_is_refused_before_staging(
    tmp_path: Path, video: Path, stub_probe, no_http, capsys
) -> None:
    external = tmp_path / "external-drops"
    external.mkdir()
    assert run(
        external, str(video), "--corpus", "real", "--started-at", "2026-08-05"
    ) == 1
    err = capsys.readouterr().err
    assert "outside configured MM_DROPS_ROOT" in err
    assert list(external.iterdir()) == []


def test_a_nested_drops_root_resolves_for_intake(
    mint_root: Path, drops_root: Path, video: Path, stub_probe, no_http
) -> None:
    assert run(
        mint_root, str(video), "--corpus", "real", "--started-at", "2026-08-05"
    ) == 0
    [drop] = drop_dirs(mint_root)
    assert drop_relative_path(drops_root, drop) == f"{mint_root.name}/{drop.name}"


def test_nested_roots_share_one_source_identity(
    mint_root: Path, video: Path, stub_probe, no_http
) -> None:
    """Placement below the configured root must not fork intake identity."""
    first_root = mint_root / "first"
    second_root = mint_root / "second"
    first_root.mkdir()
    second_root.mkdir()

    assert run(
        first_root, str(video), "--corpus", "real", "--title", "Alpha",
        "--started-at", "2026-08-05",
    ) == 0
    assert run(
        second_root, str(video), "--corpus", "real", "--title", "Beta",
        "--started-at", "2026-08-05",
    ) == 0

    assert len(drop_dirs(first_root)) == 1
    assert drop_dirs(second_root) == []


def test_a_staging_descendant_is_refused_before_anything_is_minted(
    mint_root: Path, video: Path, stub_probe, no_http, capsys
) -> None:
    staging = mint_root / mintdrop.STAGING_DIRNAME
    staging.mkdir()
    assert run(
        staging, str(video), "--corpus", "real", "--started-at", "2026-08-05"
    ) == 1
    assert "must not point inside .staging" in capsys.readouterr().err
    assert list(staging.iterdir()) == []


def test_a_drop_minted_into_the_configured_root_resolves_for_intake(
    drops_root: Path, tmp_path: Path, stub_probe, no_http, capsys
) -> None:
    """The containment rule the door applies, asserted with the door's own
    function: `_validate_drop_path` answers 400 for anything this rejects."""
    video = tmp_path / f"Root Check {tmp_path.name}.mp4"
    # Unique bytes: the session root is shared, and identical content would
    # resolve to a drop another test minted.
    video.write_bytes(VIDEO_BYTES + tmp_path.name.encode())

    code = mintdrop.main(
        [str(video), "--corpus", "real", "--started-at", "2026-08-05", "--no-post"]
    )
    assert code == 0
    digest = mintdrop.source_id_digest("sha256:" + mintdrop.sha256_and_size(video)[0])
    minted = [p for p in drops_root.iterdir() if p.name.endswith(digest)]
    try:
        assert len(minted) == 1
        assert drop_relative_path(drops_root, minted[0]) == minted[0].name
        read_drop_metadata(minted[0])
        assert capsys.readouterr().err == ""
    finally:
        for path in minted:
            shutil.rmtree(path)


# --- intake ----------------------------------------------------------------


class FakeResponse:
    def __init__(self, status: int, body: dict[str, Any]) -> None:
        self.status = status
        self._body = json.dumps(body).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None


def stub_intake(
    monkeypatch: pytest.MonkeyPatch, status: int, body: dict[str, Any]
) -> list[dict[str, Any]]:
    """Install a fake /ingests; returns the list of request bodies seen."""
    seen: list[dict[str, Any]] = []

    def _urlopen(request: Any, timeout: float | None = None) -> FakeResponse:
        seen.append(json.loads(request.data.decode("utf-8")))
        if status >= 400:
            raise urllib.error.HTTPError(
                request.full_url, status, "", {}, io.BytesIO(json.dumps(body).encode())
            )
        return FakeResponse(status, body)

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)
    return seen


def test_no_post_prints_the_path_and_the_request_and_calls_nothing(
    mint_root: Path, video: Path, stub_probe, no_http, capsys
) -> None:
    """Acceptance: --no-post reports what to run and makes no HTTP call."""
    assert run(
        mint_root, str(video), "--corpus", "real", "--started-at", "2026-08-05"
    ) == 0
    drop = drop_dirs(mint_root)[0]
    out = capsys.readouterr().out
    assert str(drop) in out
    assert "POST http://127.0.0.1:8000/ingests" in out
    assert json.dumps({"dropPath": str(drop)}) in out


@pytest.mark.parametrize(
    ("status", "label"),
    [(201, "created"), (200, "requeued")],
)
def test_a_posted_drop_reports_the_intake_answer(
    mint_root: Path, video: Path, stub_probe, capsys,
    monkeypatch: pytest.MonkeyPatch, status: int, label: str,
) -> None:
    seen = stub_intake(monkeypatch, status, {"jobId": "job-1"})
    assert run(
        mint_root, str(video), "--corpus", "real", "--started-at", "2026-08-05",
        post=True,
    ) == 0
    drop = drop_dirs(mint_root)[0]
    assert seen == [{"dropPath": str(drop)}]
    out = capsys.readouterr().out
    assert f"intake {label} ({status}) jobId job-1" in out


def test_a_duplicate_source_is_already_ingested_and_exits_zero(
    mint_root: Path, video: Path, stub_probe, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Acceptance: a drop already in the system is not a tool failure."""
    stub_intake(
        monkeypatch,
        409,
        {
            "type": "urn:meetingminer:problem:duplicate-source",
            "title": "Conflict",
            "detail": "sourceId already has a non-failed job",
            "jobId": "job-9",
        },
    )
    assert run(
        mint_root, str(video), "--corpus", "real", "--started-at", "2026-08-05",
        post=True,
    ) == 0
    assert "intake already ingested (409) jobId job-9" in capsys.readouterr().out


def test_a_rejected_drop_exits_non_zero_and_prints_the_re_post_command(
    mint_root: Path, video: Path, stub_probe, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The drop is finalized by then: re-running the tool would say `exists`."""
    stub_intake(
        monkeypatch,
        422,
        {"type": "urn:meetingminer:problem:invalid-drop", "detail": "bad drop"},
    )
    assert run(
        mint_root, str(video), "--corpus", "real", "--started-at", "2026-08-05",
        post=True,
    ) == 1
    err = capsys.readouterr().err
    assert "intake FAILED" in err and "bad drop" in err
    assert f'"dropPath": "{drop_dirs(mint_root)[0]}"' in err


def test_an_unreachable_api_leaves_the_drop_and_says_so(
    mint_root: Path, video: Path, stub_probe, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _refused(request: Any, timeout: float | None = None) -> Any:
        raise urllib.error.URLError("Connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", _refused)
    assert run(
        mint_root, str(video), "--corpus", "real", "--started-at", "2026-08-05",
        post=True,
    ) == 1
    assert "is the api running?" in capsys.readouterr().err
    # Finalized, not rolled back: the operator re-POSTs this exact drop.
    assert len(drop_dirs(mint_root)) == 1


def test_the_api_url_comes_from_the_environment(
    mint_root: Path, video: Path, stub_probe, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MM_API_URL", "http://127.0.0.1:9999/")
    assert run(
        mint_root, str(video), "--corpus", "real", "--started-at", "2026-08-05"
    ) == 0
    assert "POST http://127.0.0.1:9999/ingests" in capsys.readouterr().out


def test_the_api_url_comes_from_the_flag_and_beats_the_environment(
    mint_root: Path, video: Path, stub_probe, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MM_API_URL", "http://127.0.0.1:9999")
    seen = stub_intake(monkeypatch, 201, {"jobId": "job-2"})
    assert run(
        mint_root, str(video), "--corpus", "real", "--started-at", "2026-08-05",
        "--api", "http://127.0.0.1:8123/", post=True,
    ) == 0
    assert seen == [{"dropPath": str(drop_dirs(mint_root)[0])}]
    assert "intake created (201)" in capsys.readouterr().out


def test_a_minted_nested_drop_posts_to_the_real_ingests_route(
    mint_root: Path,
    video: Path,
    stub_probe,
    capsys,
    client,
    test_pool,
) -> None:
    """The producer's urllib request reaches the real API route over HTTP."""
    import meetingminer.api.main as api_main

    previous_pool = getattr(api_main.app.state, "pool", None)
    api_main.app.state.pool = test_pool
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(api_main.app, host="127.0.0.1", port=port, log_level="error", lifespan="off")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while True:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    break
            except OSError:
                if time.monotonic() >= deadline:
                    raise AssertionError("real API server did not start")
                time.sleep(0.01)

        assert run(
            mint_root, str(video), "--corpus", "real", "--started-at", "2026-08-05",
            "--api", f"http://127.0.0.1:{port}", post=True,
        ) == 0
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        api_main.app.state.pool = previous_pool
    assert not thread.is_alive(), "real API server did not stop"

    [drop] = drop_dirs(mint_root)
    source_id = read_drop_metadata(drop)["sourceId"]
    with test_pool.connection() as conn:
        [stored_path] = conn.execute(
            "SELECT drop_relative_path FROM job WHERE source_id = %s", (source_id,)
        ).fetchone()
    assert stored_path == f"{mint_root.name}/{drop.name}"
    assert "intake created (201)" in capsys.readouterr().out


def test_a_schemeless_api_url_is_refused_before_anything_is_minted(
    mint_root: Path, video: Path, stub_probe, no_http, capsys
) -> None:
    """The printed re-POST line has to be a command that runs; a drop is
    write-once, so the url is checked before one exists."""
    assert run(
        mint_root, str(video), "--corpus", "real", "--started-at", "2026-08-05",
        "--api", "127.0.0.1:8000",
    ) == 1
    assert "must be an HTTP(S) URL with a host" in capsys.readouterr().err
    assert list(mint_root.iterdir()) == []


@pytest.mark.parametrize(
    "api_url",
    [
        "http://",
        "http://127.0.0.1:8000?trace=1",
        "https://example.test#fragment",
        "http://127.0.0.1:8000?",
        "https://example.test#",
        "http://127.0.0.1:not-a-port",
        "http://[::1",
    ],
)
def test_an_invalid_api_base_is_refused_before_anything_is_minted(
    mint_root: Path, video: Path, stub_probe, no_http, capsys, api_url: str
) -> None:
    assert run(
        mint_root, str(video), "--corpus", "real", "--started-at", "2026-08-05",
        "--api", api_url,
    ) == 1
    assert "api base url" in capsys.readouterr().err
    assert list(mint_root.iterdir()) == []


def test_concurrent_same_content_mints_one_identity(
    mint_root: Path, video: Path, stub_probe, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Different labels cannot split a source identity into two drops."""
    entered = threading.Event()
    release = threading.Event()
    original = mintdrop._assemble

    def _delayed_assemble(**kwargs: Any) -> mintdrop.MintResult:
        entered.set()
        assert release.wait(timeout=5), "second mint did not start while first held the lock"
        return original(**kwargs)

    monkeypatch.setattr(mintdrop, "_assemble", _delayed_assemble)

    def _mint(title: str) -> mintdrop.MintResult:
        return mintdrop.mint(
            supplied=[str(video)], corpus="real", drops_root=mint_root,
            config_path=REPO_ROOT / "config.yaml", title=title,
            started_at_argument="2026-08-05",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(_mint, "Alpha")
        assert entered.wait(timeout=5)
        second = executor.submit(_mint, "Beta")
        release.set()
        results = [first.result(timeout=10), second.result(timeout=10)]

    assert sorted(result.status for result in results) == ["created", "exists"]
    assert len(drop_dirs(mint_root)) == 1
    assert results[0].source_id == results[1].source_id


@requires_ffmpeg
def test_independent_processes_share_the_source_identity_lock(
    mint_root: Path, synthetic_recording: Path, tmp_path: Path
) -> None:
    """The filesystem flock, not Python thread scheduling, serializes mints."""
    entered = tmp_path / "entered"
    release = tmp_path / "release"
    script = """
from pathlib import Path
import sys
from meetingminer import mintdrop

video, root, entered, release = map(Path, sys.argv[1:5])
title, hold = sys.argv[5:7]
if hold == 'hold':
    original = mintdrop._assemble
    def delayed(**kwargs):
        entered.touch()
        for _ in range(500):
            if release.exists():
                break
            import time; time.sleep(0.01)
        else:
            raise RuntimeError('release gate timed out')
        return original(**kwargs)
    mintdrop._assemble = delayed
result = mintdrop.mint(
    supplied=[str(video)], corpus='real', drops_root=root,
    identity_root=root, config_path=Path(sys.argv[7]), title=title,
    started_at_argument='2026-08-05',
)
print(result.status)
"""
    first = subprocess.Popen(
        [sys.executable, "-c", script, str(synthetic_recording), str(mint_root),
         str(entered), str(release), "Alpha", "hold", str(REPO_ROOT / "config.yaml")],
        cwd=REPO_ROOT / "server", stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    deadline = time.monotonic() + 10
    while not entered.exists():
        if first.poll() is not None or time.monotonic() >= deadline:
            stdout, stderr = first.communicate(timeout=1)
            raise AssertionError(f"first process never held the mint lock: {stdout} {stderr}")
        time.sleep(0.01)
    second = subprocess.Popen(
        [sys.executable, "-c", script, str(synthetic_recording), str(mint_root),
         str(entered), str(release), "Beta", "wait", str(REPO_ROOT / "config.yaml")],
        cwd=REPO_ROOT / "server", stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    time.sleep(0.15)
    assert second.poll() is None, "second process passed the identity lock before release"
    release.touch()
    first_out, first_err = first.communicate(timeout=20)
    second_out, second_err = second.communicate(timeout=20)
    assert first.returncode == second.returncode == 0, (first_err, second_err)
    assert sorted((first_out.strip(), second_out.strip())) == ["created", "exists"]
    assert len(drop_dirs(mint_root)) == 1


@pytest.mark.parametrize(
    "problem_type",
    [
        "urn:meetingminer:problem:some-other-conflict",
        # A foreign namespace ending in the same slug: matching the full type
        # rather than a suffix is what keeps this a failure.
        "urn:something:else:duplicate-source",
    ],
)
def test_a_409_that_is_not_duplicate_source_is_still_a_failure(
    mint_root: Path, video: Path, stub_probe, capsys,
    monkeypatch: pytest.MonkeyPatch, problem_type: str,
) -> None:
    """`title` carries a generic status word ("Conflict"), so only the full
    problem `type` may decide that a 409 is the benign one."""
    stub_intake(
        monkeypatch,
        409,
        {
            "type": problem_type,
            "title": "Conflict",
            "detail": "something else entirely",
        },
    )
    assert run(
        mint_root, str(video), "--corpus", "real", "--started-at", "2026-08-05",
        post=True,
    ) == 1
    assert "something else entirely" in capsys.readouterr().err


# --- against a real recording ----------------------------------------------


@requires_ffmpeg
def test_a_real_recording_mints_and_validates(
    mint_root: Path, synthetic_recording: Path, no_http, capsys
) -> None:
    """No stubs: real ffprobe, real copy, real schema validation."""
    assert run(
        mint_root, str(synthetic_recording),
        "--corpus", "scripted",
        "--title", "Daily Standup",
        "--started-at", "2026-08-05T12:00:19Z",
    ) == 0
    drop = drop_dirs(mint_root)[0]
    read_drop_metadata(drop)
    assert (drop / "recording.mp4").read_bytes() == synthetic_recording.read_bytes()


@requires_ffmpeg
def test_a_stamped_recording_supplies_its_own_wall_clock(
    mint_root: Path, tmp_path: Path, no_http
) -> None:
    """The creation_time path end to end, against a container that carries one."""
    stamped = tmp_path / "Stamped.mp4"
    proc = subprocess.run(
        [
            FFMPEG, "-nostdin", "-v", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10:duration=1",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-metadata", "creation_time=2026-08-05T12:00:19Z",
            str(stamped),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0 or not stamped.is_file():
        pytest.skip(f"ffmpeg could not build the stamped recording: {proc.stderr.strip()}")

    assert media.probe_creation_time(stamped) is not None
    assert run(mint_root, str(stamped), "--corpus", "real") == 0
    metadata = read_drop_metadata(drop_dirs(mint_root)[0])
    assert metadata["startedAt"] == "2026-08-05T12:00:19Z"
    assert metadata["startedAtPrecision"] == "second"


@requires_ffmpeg
def test_probe_creation_time_is_none_when_the_container_carries_no_tag(
    tmp_path: Path,
) -> None:
    """`None`, not an invention — the caller then refuses instead of guessing."""
    bare = tmp_path / "bare.mp4"
    proc = subprocess.run(
        [
            FFMPEG, "-nostdin", "-v", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10:duration=1",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-map_metadata", "-1", "-fflags", "+bitexact",
            str(bare),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0 or not bare.is_file():
        pytest.skip(f"ffmpeg could not build the bare recording: {proc.stderr.strip()}")
    assert media.probe_creation_time(bare) is None


@requires_ffmpeg
def test_probe_creation_time_of_a_corrupt_file_is_a_named_error(tmp_path: Path) -> None:
    corrupt = tmp_path / "recording.mp4"
    corrupt.write_bytes(b"this is not an mp4" * 64)
    with pytest.raises(media.MediaToolError, match="ffprobe failed"):
        media.probe_creation_time(corrupt)
