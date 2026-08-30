"""``youtube-drop``: turn a published YouTube video into a source drop.

AD-1 names three sources — the Teams puller, a local recording, a future
YouTube — and this is the producer for the third (FR33, story 6.2). It takes a
public video URL, downloads a browser-playable MP4 plus English captions with
``yt-dlp``, and assembles the drop through :func:`meetingminer.mintdrop.mint` —
the existing staging → validate → atomic-rename path — via keyword overrides
that default to today's behaviour. There is no second finalize implementation
and no second ingestion path.

Run it from the repository::

    cd server && .venv/bin/python -m meetingminer.youtube \\
        'https://www.youtube.com/watch?v=...'

or through ``make youtube-drop URL=<url>`` (options via ``YT_ARGS``).

What it guarantees, and why each one is here:

* **Refuse before permanent writes.** Every refusal is a named error with a
  non-zero exit stating the rule and remediation. URL, tool, and probe-known
  refusals happen before media download. A downloaded-metadata drift or missing
  selected caption can be known only after yt-dlp wrote temporary bytes; those
  paths still refuse before finalization, remove the private temp directory,
  and leave no source drop.
* **Identity from the source.** ``sourceId`` is ``youtube:<videoId>``, parsed
  from the URL offline, and :func:`~meetingminer.mintdrop.find_existing_drop`
  answers before any ``yt-dlp`` invocation: on ``exists`` the downloader is
  never invoked and no network traffic for media occurs. The exists path still
  POSTs, as ``mint-drop``'s does, so a dropped hand-off is recoverable by
  re-running the same command.
* **An honest wall clock.** ``startedAt`` comes from the video's own publish
  metadata — ``release_timestamp`` at second precision, else ``upload_date``
  at day precision (``T00:00:00Z``) — never from a file's mtime, and never
  guessed: a video carrying neither is refused.
* **``info.json`` is read, not shipped.** The download writes ``info.json``
  beside the media in a private temp directory and *that* file is the metadata
  source (only it names the actually-selected ``format_id``); it is never
  copied into the drop.

``yt-dlp`` is a subprocess by name, mirroring ``pipeline/media.py``'s
ffmpeg pattern: a CLI tool checked at run time by a named refusal needs no
import and no dependency entry, and ``check-tools`` deliberately knows nothing
about it.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NoReturn, TypeGuard

from meetingminer.config import ConfigError
from meetingminer.domain.drops import (
    RECORDING_FILENAME,
    TRANSCRIPT_TEXT_FILENAME,
    TRANSCRIPT_VTT_FILENAME,
    DropError,
    read_drop,
    sha256_and_size,
)
from meetingminer.mintdrop import (
    IntakeError,
    MintError,
    MintResult,
    _iso_second_utc,
    _load_cli_config,
    _report,
    find_existing_drop,
    ingest_command,
    mint,
    post_ingest,
    resolve_api_url,
    resolve_drops_root,
)

PROGRAM = "youtube-drop"

#: Checked at run time by name, never imported and never added to
#: ``check-tools`` — the same rule ``mint-drop`` applies to ffprobe.
YT_DLP = "yt-dlp"
FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"

#: Prefixed so a minted id can never be confused with ``mint-drop``'s
#: content-derived ``sha256:`` ids or the puller's Stream-URL ids.
YOUTUBE_SOURCE_ID_PREFIX = "youtube:"

#: The acceptance criterion's selector: a browser-playable H.264 MP4 with AAC
#: audio, merged, falling back to the best progressive MP4. avc1 rather than
#: vp9/av1 because the replay surface is a plain <video> tag.
FORMAT_SELECTOR = "bv*[ext=mp4][vcodec^=avc1]+ba[ext=m4a]/b[ext=mp4]"

#: An 11-character YouTube video id, and nothing that merely resembles one.
VIDEO_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{11}")

#: Named in the duration refusal so the operator knows exactly what to retune.
MAX_DURATION_CONFIG_KEY = "acquisition.youtube.max_duration_minutes"

#: The probe reads metadata only; a hang here means something is badly wrong.
#: The media download deliberately gets no timeout — a multi-gigabyte talk on
#: a slow line is legitimate work (the same reasoning as ffmpeg's in
#: ``pipeline/media.py``).
PROBE_TIMEOUT_SECONDS = 300


class YoutubeError(RuntimeError):
    """A named refusal: the command declines and writes nothing."""


# --- URL classification (offline) ------------------------------------------


def watch_url(video_id: str) -> str:
    """The canonical watch URL — what ``provenance.url`` carries.

    ``DropContents.stream_url`` and story 6.6's deep links read this, so one
    spelling is written no matter which URL shape the user pasted.
    """
    return f"https://www.youtube.com/watch?v={video_id}"


def video_id_from_url(url: str) -> str:
    """The 11-character video id, parsed offline, or a named refusal.

    Accepted shapes: ``youtube.com/watch?v=<id>`` (any ``*.youtube.com``
    host; extra query keys such as ``&list=`` are ignored — the single video
    is acquired), ``youtube.com/shorts/<id>``, and ``youtu.be/<id>``. HTTP(S)
    only. Everything else — a playlist-only URL, another host, a malformed
    id — is refused before any subprocess runs.
    """
    from urllib.parse import parse_qs, urlsplit

    refusal = (
        f"not a YouTube video URL: {url!r} — give a watch"
        " (youtube.com/watch?v=...), shorts, or youtu.be link to one video."
        " Playlists are not supported."
    )
    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise YoutubeError(refusal) from exc
    if parsed.scheme.lower() not in ("http", "https"):
        raise YoutubeError(refusal)
    host = (parsed.hostname or "").lower()
    segments = [segment for segment in parsed.path.split("/") if segment]
    candidate: str | None = None
    if host == "youtu.be":
        if len(segments) == 1:
            candidate = segments[0]
    elif host == "youtube.com" or host.endswith(".youtube.com"):
        if segments == ["watch"]:
            values = parse_qs(parsed.query).get("v", [])
            if len(values) == 1:
                candidate = values[0]
        elif len(segments) == 2 and segments[0] == "shorts":
            candidate = segments[1]
    if candidate is None or not VIDEO_ID_PATTERN.fullmatch(candidate):
        raise YoutubeError(refusal)
    return candidate


# --- tools and subprocesses -------------------------------------------------


def ensure_tools() -> None:
    """Refuse by name before any network when a required tool is missing.

    ``ffmpeg`` is needed twice: yt-dlp merges the video and audio streams with
    it, and ``mint()``'s video check needs the ffprobe it ships with.
    """
    for tool, install_name in (
        (YT_DLP, YT_DLP),
        (FFMPEG, FFMPEG),
        (FFPROBE, FFMPEG),
    ):
        if shutil.which(tool) is None:
            raise YoutubeError(
                f"{tool} is not on PATH — acquiring a YouTube video needs it."
                f" Install it with 'brew install {install_name}' (checked at run time"
                " by name; acquisition does not depend on the rest of the"
                " stack)"
            )


def _run(
    command: list[str], *, timeout: float | None = None
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command, capture_output=True, text=True, timeout=timeout
        )
    except OSError as exc:
        raise YoutubeError(f"{command[0]} could not be run: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise YoutubeError(
            f"{command[0]} did not answer within {timeout} seconds"
        ) from exc


def classify_probe_failure(stderr: str) -> str:
    """yt-dlp's own message, carried into the refusal.

    A private video, a removed video, and a region lock all surface here as
    yt-dlp ``ERROR:`` lines; naming them verbatim beats paraphrasing a tool
    that already explains itself.
    """
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    errors = [line for line in lines if line.startswith("ERROR:")]
    detail = "; ".join(errors) if errors else (lines[-1] if lines else "no error output")
    return (
        f"the video cannot be acquired — {YT_DLP} refused: {detail}"
        " (a private or removed video cannot enter the corpus)"
    )


def yt_dlp_version() -> str:
    """Recorded in provenance: extractor behaviour changes release to release."""
    completed = _run([YT_DLP, "--version"], timeout=PROBE_TIMEOUT_SECONDS)
    if completed.returncode != 0:
        raise YoutubeError(
            f"{YT_DLP} --version failed: {classify_probe_failure(completed.stderr)}"
        )
    version = completed.stdout.strip()
    if not version:
        raise YoutubeError(
            f"{YT_DLP} --version returned an empty version — reinstall or upgrade"
            f" it with 'brew install {YT_DLP}' before acquiring evidence"
        )
    return version


# --- probe and the refusal matrix -------------------------------------------


def probe(url: str) -> dict[str, Any]:
    """``yt-dlp -J --no-playlist``: the whole refusal matrix, no media bytes."""
    completed = _run(
        [YT_DLP, "-J", "--no-playlist", url], timeout=PROBE_TIMEOUT_SECONDS
    )
    if completed.returncode != 0:
        raise YoutubeError(classify_probe_failure(completed.stderr))
    try:
        info = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise YoutubeError(
            f"{YT_DLP} produced unreadable probe output for {url}"
        ) from exc
    if not isinstance(info, dict):
        raise YoutubeError(f"{YT_DLP} produced unreadable probe output for {url}")
    return info


def _is_finite_number(value: object) -> TypeGuard[int | float]:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _duration_seconds(info: dict[str, Any]) -> int | float:
    duration = info.get("duration")
    if not _is_finite_number(duration) or duration < 0:
        raise YoutubeError(
            "the video duration is missing or invalid — yt-dlp must report a"
            " finite non-negative number before evidence can be downloaded"
        )
    return duration


def _channel_from_info(info: dict[str, Any]) -> str:
    for field in ("channel", "uploader"):
        value = info.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise YoutubeError(
        "the video channel is missing or invalid — provenance requires the"
        " source publisher before evidence can be finalized"
    )


def _format_id_from_info(info: dict[str, Any]) -> str:
    format_id = info.get("format_id")
    if not isinstance(format_id, str) or not format_id.strip():
        raise YoutubeError(
            "the downloaded format_id is missing or invalid — provenance must"
            " identify the format whose bytes were finalized"
        )
    return format_id.strip()


def _validate_video_identity(info: dict[str, Any], expected_video_id: str) -> None:
    actual = info.get("id")
    if not isinstance(actual, str) or actual != expected_video_id:
        shown = repr(actual) if actual is not None else "missing"
        raise YoutubeError(
            f"yt-dlp metadata video id {shown} does not match requested video id"
            f" {expected_video_id!r} — refusing to mint bytes under the wrong"
            " source identity"
        )


def refuse_unacceptable(info: dict[str, Any], *, max_duration_minutes: int) -> None:
    """The probe-time refusals: no video stream, over the duration cap."""
    formats = info.get("formats")
    has_video = isinstance(formats, list) and any(
        isinstance(entry, dict) and entry.get("vcodec") not in (None, "none")
        for entry in formats
    )
    if not has_video:
        raise YoutubeError(
            "the video carries no video stream — recording.mp4 must be a"
            " video, and an audio-only publication is not one"
        )
    duration = _duration_seconds(info)
    if duration > max_duration_minutes * 60:
        raise YoutubeError(
            f"the video is {duration / 60:.1f} minutes long — over the"
            f" {max_duration_minutes}-minute cap. Raise"
            f" {MAX_DURATION_CONFIG_KEY} in config.yaml if this video really"
            " belongs in the corpus"
        )


def validate_info(
    info: dict[str, Any],
    *,
    expected_video_id: str,
    max_duration_minutes: int,
    require_format_id: bool,
) -> None:
    """Fail-closed metadata boundary shared by probe and download results."""
    _validate_video_identity(info, expected_video_id)
    refuse_unacceptable(info, max_duration_minutes=max_duration_minutes)
    started_at_from_info(info)
    _channel_from_info(info)
    if require_format_id:
        _format_id_from_info(info)


def started_at_from_info(info: dict[str, Any]) -> tuple[str, str, str]:
    """``(startedAt, precision, source)`` from the video's publish metadata.

    ``release_timestamp`` is a real instant, so it maps to second precision;
    ``upload_date`` is a date the platform knows and a time of day it does
    not, which is exactly the schema's ``day`` precision (``T00:00:00Z``).
    Neither present is a refusal: a wall clock is never guessed from a file's
    mtime, and a drop is write-once (AD-1).
    """
    release = info.get("release_timestamp")
    if _is_finite_number(release):
        try:
            moment = datetime.fromtimestamp(release, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            pass
        else:
            return _iso_second_utc(moment), "second", "release_timestamp"
    upload = info.get("upload_date")
    if isinstance(upload, str) and re.fullmatch(r"\d{8}", upload):
        try:
            day = datetime.strptime(upload, "%Y%m%d")
        except ValueError:
            day = None
        if day is not None:
            return f"{day:%Y-%m-%d}T00:00:00Z", "day", "upload_date"
    raise YoutubeError(
        "the video carries neither release_timestamp nor a usable upload_date"
        " — a meeting's wall clock is never guessed (not from an mtime, not"
        " from today), and a drop is write-once"
    )


def select_captions(info: dict[str, Any]) -> tuple[str, str] | None:
    """``(language, kind)`` for the caption track to download, or ``None``.

    English manual captions first (``en`` exactly, else the first ``en-*``),
    else the same rule over the auto-generated set, else no captions — a
    recording-only drop is still valid.
    """
    for field, kind in (("subtitles", "manual"), ("automatic_captions", "auto")):
        tracks = info.get(field)
        if not isinstance(tracks, dict):
            continue
        english = sorted(
            key
            for key, value in tracks.items()
            if isinstance(key, str)
            and (key == "en" or key.startswith("en-"))
            and value
        )
        if english:
            return ("en" if "en" in english else english[0]), kind
    return None


# --- download ---------------------------------------------------------------


def download(
    url: str,
    video_id: str,
    workdir: Path,
    captions: tuple[str, str] | None,
) -> tuple[Path, Path | None, dict[str, Any]]:
    """Download media + captions + ``info.json`` into a private temp dir.

    Returns ``(recording, transcript or None, downloaded info.json)``. The
    downloaded ``info.json`` — not the probe's — is the metadata source: only
    it names the ``format_id`` of the format actually selected.
    """
    command = [
        YT_DLP,
        "--no-playlist",
        "-f",
        FORMAT_SELECTOR,
        "--merge-output-format",
        "mp4",
        "--write-info-json",
        "-o",
        str(workdir / f"{video_id}.%(ext)s"),
    ]
    if captions is not None:
        language, kind = captions
        command.append("--write-subs" if kind == "manual" else "--write-auto-subs")
        command.extend(["--sub-langs", language, "--convert-subs", "vtt"])
    command.append(url)
    completed = _run(command)
    if completed.returncode != 0:
        raise YoutubeError(classify_probe_failure(completed.stderr))
    recording = workdir / f"{video_id}.mp4"
    if not recording.is_file():
        raise YoutubeError(
            f"{YT_DLP} reported success but wrote no {recording.name} — its"
            f" output was: {completed.stderr.strip() or '(empty)'}"
        )
    info_path = workdir / f"{video_id}.info.json"
    try:
        info = json.loads(info_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise YoutubeError(
            f"{YT_DLP} wrote no readable {info_path.name}: {exc}"
        ) from exc
    if not isinstance(info, dict):
        raise YoutubeError(f"{info_path.name} is not a JSON object")
    transcript: Path | None = None
    if captions is not None:
        language, kind = captions
        expected = workdir / f"{video_id}.{language}.vtt"
        if not expected.is_file():
            raise YoutubeError(
                f"yt-dlp selected the {kind} {language!r} caption track but wrote"
                " no VTT — retry after upgrading yt-dlp; recording-only is allowed"
                " only when the probe reports no English captions"
            )
        transcript = expected
    return recording, transcript, info


# --- metadata mapping -------------------------------------------------------


def provenance_extra_from_info(
    info: dict[str, Any], video_id: str, tool_version: str
) -> dict[str, Any]:
    """The provenance keys the acceptance criteria name, merged over
    ``build_metadata``'s defaults (which is how ``tool`` becomes this
    program's name rather than ``mint-drop``)."""
    _validate_video_identity(info, video_id)
    if not isinstance(tool_version, str) or not tool_version.strip():
        raise YoutubeError(
            "yt-dlp version is missing or invalid — provenance must record the"
            " extractor version that produced the evidence"
        )
    extra: dict[str, Any] = {
        "tool": PROGRAM,
        "url": watch_url(video_id),
        "ytDlpVersion": tool_version.strip(),
        "channel": _channel_from_info(info),
        "durationSeconds": _duration_seconds(info),
        "formatId": _format_id_from_info(info),
    }
    return extra


# --- acquisition ------------------------------------------------------------


def _refuse_legacy_drop(path: Path, detail: str) -> NoReturn:
    raise YoutubeError(
        f"existing YouTube drop {path} is incomplete: {detail} — do not POST"
        " this legacy drop; quarantine it outside MM_DROPS_ROOT for repair,"
        " then rerun youtube-drop"
    )


def validate_existing_youtube_drop(
    path: Path,
    *,
    video_id: str,
    source_id: str,
    config_path: Path,
    max_duration_minutes: int,
) -> dict[str, Any]:
    """Validate a local ``exists`` result without invoking yt-dlp.

    Story 6.2's first implementation could finalize schema-valid drops whose
    open provenance object omitted YouTube-required facts. Such a drop must not
    be POSTed merely because its source id matches.
    """
    try:
        contents = read_drop(path, config_path)
    except DropError as exc:
        _refuse_legacy_drop(path, str(exc))
    metadata = contents.metadata
    if metadata.get("sourceId") != source_id:
        _refuse_legacy_drop(path, "sourceId does not match the requested video")
    if metadata.get("corpus") != "real":
        _refuse_legacy_drop(path, "corpus must be 'real'")
    if contents.recording_path is None:
        _refuse_legacy_drop(path, f"required evidence {RECORDING_FILENAME} is missing")
    if contents.transcript_text_path is not None:
        _refuse_legacy_drop(
            path, f"unexpected YouTube evidence {TRANSCRIPT_TEXT_FILENAME} is present"
        )

    provenance = metadata.get("provenance")
    if not isinstance(provenance, dict):
        _refuse_legacy_drop(path, "provenance is not an object")
    if provenance.get("tool") != PROGRAM:
        _refuse_legacy_drop(path, f"provenance.tool must be {PROGRAM!r}")
    if provenance.get("url") != watch_url(video_id):
        _refuse_legacy_drop(path, "provenance.url is not the canonical watch URL")
    for key in ("channel", "ytDlpVersion", "formatId"):
        value = provenance.get(key)
        if not isinstance(value, str) or not value.strip():
            _refuse_legacy_drop(path, f"provenance.{key} is missing or blank")

    duration = provenance.get("durationSeconds")
    if not _is_finite_number(duration) or duration < 0:
        _refuse_legacy_drop(
            path, "provenance.durationSeconds is not a finite non-negative number"
        )
    if duration > max_duration_minutes * 60:
        _refuse_legacy_drop(
            path,
            f"provenance.durationSeconds exceeds the {max_duration_minutes}-minute cap",
        )

    expected_start_source = {
        "second": "release_timestamp",
        "day": "upload_date",
    }.get(metadata.get("startedAtPrecision"))
    if provenance.get("startedAtSource") != expected_start_source:
        _refuse_legacy_drop(
            path,
            "provenance.startedAtSource does not match startedAtPrecision",
        )

    files = provenance.get("files")
    if not isinstance(files, list):
        _refuse_legacy_drop(path, "provenance.files is not a list")
    entries = {
        entry.get("dropFilename"): entry
        for entry in files
        if isinstance(entry, dict) and isinstance(entry.get("dropFilename"), str)
    }
    actual = {RECORDING_FILENAME: contents.recording_path}
    if contents.transcript_vtt_path is not None:
        actual[TRANSCRIPT_VTT_FILENAME] = contents.transcript_vtt_path
    if set(entries) != set(actual):
        _refuse_legacy_drop(
            path,
            "provenance.files does not exactly describe the finalized evidence",
        )
    for name, evidence_path in actual.items():
        assert evidence_path is not None
        digest, size = sha256_and_size(evidence_path)
        entry = entries[name]
        if entry.get("sha256") != digest or entry.get("byteSize") != size:
            _refuse_legacy_drop(
                path, f"provenance.files entry for {name} does not match its bytes"
            )
    return metadata


def acquire(
    url: str,
    *,
    drops_root: Path,
    identity_root: Path | None,
    config_path: Path,
    max_duration_minutes: int,
) -> MintResult:
    """One video → one drop, or the drop already minted for it.

    In order: classify the URL offline, answer ``exists`` from the drops root
    before any ``yt-dlp`` invocation, check the tools, probe, run the refusal
    matrix, download into a private temp directory, and hand assembly to
    :func:`~meetingminer.mintdrop.mint` — which re-checks ``exists`` under the
    identity lock, so a concurrent acquisition of the same video still
    resolves to one drop.
    """
    video_id = video_id_from_url(url)
    source_id = f"{YOUTUBE_SOURCE_ID_PREFIX}{video_id}"
    scope = (identity_root or drops_root).resolve()
    existing = find_existing_drop(scope, source_id)
    if existing is not None:
        metadata = validate_existing_youtube_drop(
            existing,
            video_id=video_id,
            source_id=source_id,
            config_path=config_path,
            max_duration_minutes=max_duration_minutes,
        )
        return MintResult(
            status="exists",
            path=existing,
            source_id=source_id,
            metadata=metadata,
        )
    ensure_tools()
    canonical = watch_url(video_id)
    info = probe(canonical)
    validate_info(
        info,
        expected_video_id=video_id,
        max_duration_minutes=max_duration_minutes,
        require_format_id=False,
    )
    captions = select_captions(info)
    tool_version = yt_dlp_version()
    with tempfile.TemporaryDirectory(prefix="youtube-drop-") as tmp:
        workdir = Path(tmp)
        recording, transcript, downloaded = download(
            canonical, video_id, workdir, captions
        )
        validate_info(
            downloaded,
            expected_video_id=video_id,
            max_duration_minutes=max_duration_minutes,
            require_format_id=True,
        )
        downloaded_captions = select_captions(downloaded)
        if downloaded_captions != captions:
            raise YoutubeError(
                "caption availability changed between probe and downloaded"
                f" metadata ({captions!r} -> {downloaded_captions!r}) — retry;"
                " no drop was finalized"
            )
        supplied = [str(recording)]
        if transcript is not None:
            supplied.append(str(transcript))
        title = downloaded.get("title")
        return mint(
            supplied=supplied,
            corpus="real",
            drops_root=drops_root,
            config_path=config_path,
            title=title if isinstance(title, str) and title.strip() else video_id,
            identity_root=identity_root,
            source_id=source_id,
            started_at_override=started_at_from_info(downloaded),
            provenance_extra=provenance_extra_from_info(
                downloaded, video_id, tool_version
            ),
        )


# --- CLI --------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description=(
            "Acquire a published YouTube video as a MeetingMiner source drop,"
            " then hand it to POST /ingests."
        ),
        epilog=(
            f"example: {PROGRAM} 'https://www.youtube.com/watch?v=...'"
            " --no-post"
        ),
    )
    parser.add_argument(
        "url",
        metavar="URL",
        help="a YouTube watch, shorts, or youtu.be link to one video.",
    )
    parser.add_argument(
        "--drops",
        metavar="DIR",
        help="the drops root to mint into (default: MM_DROPS_ROOT from .env).",
    )
    parser.add_argument(
        "--api",
        metavar="URL",
        help="api base url (default: $MM_API_URL, else mint-drop's default).",
    )
    parser.add_argument(
        "--no-post",
        dest="no_post",
        action="store_true",
        help="mint the drop but do not POST it; print the request instead.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    # URL classification is pure and must win the ordering race with the drops
    # resolver: that resolver write-probes ``.staging``. A non-YouTube URL is
    # refused before any filesystem mutation, even a temporary one.
    try:
        video_id_from_url(args.url)
    except YoutubeError as exc:
        print(f"fatal: {PROGRAM} refused: {exc}", file=sys.stderr)
        return 1

    try:
        config = _load_cli_config()
    except ConfigError as exc:
        print(f"fatal: {PROGRAM} aborted: {exc}", file=sys.stderr)
        return 1

    try:
        # Before the acquisition, not after (mint-drop's rule): an unusable
        # api url must not first cost a download and a finalized drop.
        api_url = resolve_api_url(args.api)
        drops_root = resolve_drops_root(args.drops, config)
        result = acquire(
            args.url,
            drops_root=drops_root,
            # An explicit child root is a placement choice, not a separate
            # intake namespace: all of MM_DROPS_ROOT shares source identity.
            identity_root=config.secrets.mm_drops_root,
            config_path=config.config_path,
            max_duration_minutes=(
                config.settings.acquisition.youtube.max_duration_minutes
            ),
        )
    except (ConfigError, MintError, YoutubeError) as exc:
        print(f"fatal: {PROGRAM} refused: {exc}", file=sys.stderr)
        return 1

    canonical = [
        entry["dropFilename"]
        for entry in result.metadata.get("provenance", {}).get("files", [])
        if isinstance(entry, dict) and "dropFilename" in entry
    ]
    _report(result, canonical)

    if args.no_post:
        print("           not posted (--no-post); ingest it with:")
        print(f"           {ingest_command(api_url, result.path)}")
        return 0

    try:
        status, http_status, job_id = post_ingest(api_url, result.path)
    except IntakeError as exc:
        print(f"           intake FAILED: {exc}", file=sys.stderr)
        print(
            "           the drop is finalized; re-POST this exact drop rather"
            f" than re-running {PROGRAM}:",
            file=sys.stderr,
        )
        print(f"           {ingest_command(api_url, result.path)}", file=sys.stderr)
        return 1
    label = "already ingested" if status == "duplicate" else status
    print(f"           intake {label} ({http_status}) jobId {job_id or '(none)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
