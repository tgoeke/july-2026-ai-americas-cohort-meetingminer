"""Acquisitions: the detached runner and the state the api reads (story 6.4).

``POST /acquisitions`` accepts an acquisition; it never performs one. AD-11
keeps download, conversion and pipeline execution out of the request handler,
so the api's whole part is: classify the URL offline, claim the source id,
write a status file, and start

    python -m meetingminer.acquisitions --run --acquisition-id <id> --url <url>

as a **detached** host process (``start_new_session=True``) whose stdout is
that acquisition's log. The child is this same module, and it deliberately
imports nothing from ``meetingminer.api``: it runs without FastAPI, outlives
an api restart, and calls story 6.2's :func:`~meetingminer.youtube.acquire`
and :func:`~meetingminer.mintdrop.post_ingest` unchanged — so the runner opens
no second intake door (AD-14).

**The status file is the contract, in one direction.** The child writes it
atomically (a temp file in the same directory, then :func:`os.replace`); the
api only ever reads it. Everything the web client needs to render a failure —
``rule``, ``detail``, ``remediation`` — is a field in that file. The log tail
is diagnostic and is never the source for *why* something failed.

``meetingId`` is deliberately **not** in the file. The worker creates the
meeting row after intake, so the api resolves it per read from
``meeting.job_id``; a later poll shows it appear.

**Liveness, not a registry.** "Is a second acquisition already running for
this source id?" is answered by scanning the status directory under one
``fcntl.flock``, held across the scan, the write and the ``Popen`` so the pid
is always recorded before the lock is released. A ``queued``/``running``
record whose pid is dead — or unset, which can only mean the api died
mid-claim — is not live. Pid reuse could in principle keep a stale record
live; the cost is one spurious conflict that a rerun clears, which is
preferable to a launch that races a live download.

**The refusal vocabulary is story 6.2a's**, reached through
:func:`~meetingminer.youtube.refusal_rule`. This module adds no second
vocabulary: it adds exactly one remediation and one HTTP status *per rule in
that closed set*, as two literal tables. They are literal rather than
comprehensions on purpose — a rule added to ``REFUSAL_RULES`` later must fail
a test loudly rather than acquire a silent default.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager, suppress
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from meetingminer import youtube
from meetingminer.config import AppConfig, ConfigError
from meetingminer.mintdrop import (
    IntakeError,
    MintError,
    _load_cli_config,
    ingest_command,
    post_ingest,
    resolve_api_url,
    resolve_drops_root,
)

PROGRAM = "acquisitions"

#: How the api spells the child on the command line, and how the child is
#: reached by ``python -m``. One constant so the two cannot drift.
MODULE_NAME = "meetingminer.acquisitions"

#: Anchored on the config this process was actually loaded from, never on
#: ``__file__`` (story 1.10, finding 17): an explicitly-passed config path and
#: the `.logs/` beside it can then never disagree, and no later cwd change can
#: move the anchor.
LOGS_DIRNAME = ".logs"
ACQUISITIONS_DIRNAME = "acquisitions"

STATUS_SUFFIX = ".json"
LOG_SUFFIX = ".log"
#: The in-progress half of an atomic status write. A distinct suffix, because
#: ``Path.glob`` matches dotfiles and a ``*.json`` temp name would be scanned
#: as a record mid-write.
TEMP_SUFFIX = ".tmp"
CLAIM_LOCK_FILENAME = ".claim.lock"

#: The four states ``GET /acquisitions/{id}`` reports.
STATUSES = ("queued", "running", "posted", "failed")

#: The two a launch may collide with. ``posted`` and ``failed`` are terminal,
#: so a finished record never blocks a new acquisition of the same video.
LIVE_STATUSES = frozenset({"queued", "running"})

#: Seconds to wait for the claim lock before refusing. The lock is held only
#: across a directory scan, one small write and a ``Popen``, so a wait this
#: long already means something is wedged.
CLAIM_LOCK_TIMEOUT_SECONDS = 10.0

#: The log tail is bounded twice — by bytes read off the end of the file and
#: by lines returned — so neither a single enormous line nor a very long run
#: can make a status poll expensive.
LOG_TAIL_MAX_BYTES = 16 * 1024
LOG_TAIL_MAX_LINES = 200


class AcquisitionError(RuntimeError):
    """Base for the two failures this module raises at its own boundary."""


class AcquisitionNotFound(AcquisitionError):
    """No status file for that acquisition id."""


class AcquisitionStateError(AcquisitionError):
    """The status directory could not be read, locked, or written."""


class AcquisitionInProgress(AcquisitionError):
    """A live acquisition already holds this source id."""

    def __init__(self, record: "AcquisitionRecord") -> None:
        super().__init__(
            f"acquisition {record.acquisition_id} is already {record.status}"
            f" for {record.source_id}"
        )
        self.record = record


# --- the refusal tables ------------------------------------------------------

#: One remediation per rule in :data:`~meetingminer.youtube.REFUSAL_RULES`.
#: The refusal *message* says what happened; this says what the operator can
#: do about it, which is the half a web client has no way to derive.
REMEDIATIONS: dict[str, str] = {
    # story 6.2's single-video refusals
    "not-a-video-url": (
        "Paste a link to one YouTube video — a watch (youtube.com/watch?v=...),"
        " shorts, or youtu.be URL."
    ),
    "tool-missing": (
        "Install the missing tool on the api host ('brew install yt-dlp ffmpeg')"
        " and retry."
    ),
    "tool-unrunnable": (
        "The tool is on PATH but could not be executed — check its permissions,"
        " reinstall it ('brew reinstall yt-dlp ffmpeg'), and retry."
    ),
    "tool-timeout": (
        "yt-dlp did not answer in time — check the api host's network and retry."
    ),
    "version-failed": (
        "'yt-dlp --version' failed on the api host — reinstall or upgrade it"
        " ('brew reinstall yt-dlp') and retry."
    ),
    "version-empty": (
        "'yt-dlp --version' printed nothing — reinstall or upgrade it"
        " ('brew reinstall yt-dlp') and retry."
    ),
    "probe-failed": (
        "yt-dlp could not read this video. Check the link is publicly playable;"
        " a private, removed or region-locked video cannot enter the corpus."
        " If the video does play in a browser, upgrade yt-dlp"
        " ('brew upgrade yt-dlp') — its extractor may be out of date."
    ),
    "probe-unreadable": (
        "yt-dlp produced output this server could not parse — upgrade it"
        " ('brew upgrade yt-dlp') and retry."
    ),
    "duration-unknown": (
        "yt-dlp reported no usable duration, so the length cap cannot be"
        " checked — upgrade it ('brew upgrade yt-dlp') and retry."
    ),
    "duration-cap": (
        f"Raise {youtube.MAX_DURATION_CONFIG_KEY} in config.yaml and restart the"
        " api if this video really belongs in the corpus."
    ),
    "no-video-stream": (
        "recording.mp4 must carry a video stream. Bring an audio-only"
        " publication in as a local recording instead."
    ),
    "channel-missing": (
        "yt-dlp reported neither a channel nor an uploader, and provenance"
        " records the publisher — upgrade it ('brew upgrade yt-dlp') and retry."
    ),
    "format-id-missing": (
        "yt-dlp did not name the format it downloaded, and provenance records"
        " which format's bytes were finalized — upgrade it and retry."
    ),
    "identity-mismatch": (
        "yt-dlp returned metadata for a different video — retry, and upgrade it"
        " ('brew upgrade yt-dlp') if it repeats. No drop was finalized."
    ),
    "started-at-unknown": (
        "This video publishes neither a release timestamp nor an upload date,"
        " and a meeting's wall clock is never guessed. Mint it by hand with"
        " 'make mint-drop' and an explicit --started-at."
    ),
    "download-failed": (
        "yt-dlp failed while downloading — check the api host's network,"
        " upgrade yt-dlp, and retry. No drop was finalized."
    ),
    "download-incomplete": (
        "yt-dlp reported success but wrote no usable media — upgrade it"
        " ('brew upgrade yt-dlp') and retry. No drop was finalized."
    ),
    "captions-missing-vtt": (
        "yt-dlp selected an English caption track but wrote no VTT — upgrade it"
        " ('brew upgrade yt-dlp') and retry. No drop was finalized."
    ),
    "captions-changed": (
        "Caption availability changed between the probe and the download —"
        " retry. No drop was finalized."
    ),
    "tool-version-missing": (
        "The yt-dlp version could not be recorded, and provenance names the"
        " extractor that produced the evidence — reinstall it and retry."
    ),
    "drops-root-changed": (
        "MM_DROPS_ROOT resolved differently during the acquisition — check the"
        " mount and .env on the api host, restart it, and retry."
    ),
    "existing-drop-incomplete": (
        "A drop for this video already exists but is not a complete YouTube"
        " drop. Quarantine it outside MM_DROPS_ROOT for repair, then retry."
    ),
    # story 6.2a's playlist refusals. Unreachable through the api — it accepts
    # one video per acquisition — but the table covers the whole vocabulary,
    # so a rule that becomes reachable later already has an answer.
    "not-a-playlist-url": (
        "Playlists are not acquired through the api. Run"
        " 'make youtube-drop URL=<playlist url> YT_ARGS=--playlist' on the host."
    ),
    "playlist-failed": (
        "yt-dlp could not list that playlist. Playlists are acquired on the host"
        " with 'make youtube-drop URL=<playlist url> YT_ARGS=--playlist'."
    ),
    "playlist-unreadable": (
        "yt-dlp produced a playlist listing this server could not parse —"
        " upgrade it ('brew upgrade yt-dlp') and retry on the host."
    ),
    "playlist-empty": (
        "That playlist has no entries to acquire — check the link lists the"
        " videos you expect."
    ),
    "entry-not-a-video": (
        "A playlist row named no YouTube video. Acquire the videos you want"
        " one at a time by their own URLs."
    ),
    # refusals raised outside youtube.py, and the fallback
    "mint-refused": (
        "The drop could not be assembled — the detail names what was refused."
        " Check MM_DROPS_ROOT is mounted and writable on the api host, then"
        " retry."
    ),
    "config": (
        "The api host's configuration refused this acquisition — the detail"
        " names the setting. Correct config.yaml or .env and restart the api."
    ),
    "unclassified": (
        "The acquisition failed for a reason this server cannot classify. Read"
        " the detail and the log tail, then retry."
    ),
}

#: One HTTP status per rule, in three buckets: ``not-a-video-url`` is 400 —
#: the client sent the wrong thing; the host-side rules are 503 — this server
#: cannot answer and the URL may be perfectly fine; everything else is 422 —
#: the URL is well-formed but this video cannot enter the corpus.
PROBLEM_STATUS: dict[str, int] = {
    # the client sent the wrong thing
    "not-a-video-url": 400,
    # this server cannot answer; the URL may be fine
    "tool-missing": 503,
    "tool-unrunnable": 503,
    "tool-timeout": 503,
    "version-failed": 503,
    "version-empty": 503,
    "config": 503,
    # the URL is well-formed; this video cannot enter the corpus
    "probe-failed": 422,
    "probe-unreadable": 422,
    "duration-unknown": 422,
    "duration-cap": 422,
    "no-video-stream": 422,
    "channel-missing": 422,
    "format-id-missing": 422,
    "identity-mismatch": 422,
    "started-at-unknown": 422,
    "download-failed": 422,
    "download-incomplete": 422,
    "captions-missing-vtt": 422,
    "captions-changed": 422,
    "tool-version-missing": 422,
    "drops-root-changed": 422,
    "existing-drop-incomplete": 422,
    "not-a-playlist-url": 422,
    "playlist-failed": 422,
    "playlist-unreadable": 422,
    "playlist-empty": 422,
    "entry-not-a-video": 422,
    "mint-refused": 422,
    "unclassified": 422,
}


@dataclass(frozen=True)
class Refusal:
    """Why an acquisition declined, as fields rather than as prose.

    ``rule`` is story 6.2a's closed token, ``detail`` is the refusal's own
    message, and ``remediation`` is what to do about it. A web client renders
    all three without reading a line of the log.
    """

    rule: str
    detail: str
    remediation: str

    def to_json(self) -> dict[str, str]:
        return {
            "rule": self.rule,
            "detail": self.detail,
            "remediation": self.remediation,
        }

    @classmethod
    def from_json(cls, raw: Any) -> "Refusal | None":
        if not isinstance(raw, dict):
            return None
        rule = raw.get("rule")
        if not isinstance(rule, str):
            return None
        return cls(
            rule=rule,
            detail=str(raw.get("detail", "")),
            remediation=str(raw.get("remediation", "")),
        )


def _one_line(text: str) -> str:
    """A refusal message flattened to one line, as the playlist table does."""
    return " ".join(str(text).split())


def refusal_for(error: BaseException) -> Refusal:
    """Classify any refusal through story 6.2a's vocabulary.

    :func:`~meetingminer.youtube.refusal_rule` is the only classifier; this
    adds the remediation the closed set already has an entry for.
    """
    rule = youtube.refusal_rule(error)
    return Refusal(
        rule=rule, detail=_one_line(str(error)), remediation=REMEDIATIONS[rule]
    )


# --- the status file ---------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class AcquisitionRecord:
    """One acquisition's whole state, as the child last wrote it."""

    acquisition_id: str
    source_id: str
    url: str
    status: str
    created_at: str
    updated_at: str
    #: The detached child's pid, recorded by the api before it releases the
    #: claim lock. ``None`` only between the record's first write and the
    #: ``Popen`` returning — which a reader can only observe if the api died
    #: in that window, and which is therefore read as *not live*.
    pid: int | None = None
    #: ``created`` or ``exists`` — :class:`~meetingminer.mintdrop.MintResult`'s
    #: own status, not intake's.
    result: str | None = None
    job_id: str | None = None
    tool: str | None = None
    tool_version: str | None = None
    refusal: Refusal | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "acquisitionId": self.acquisition_id,
            "sourceId": self.source_id,
            "url": self.url,
            "status": self.status,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "pid": self.pid,
            "result": self.result,
            "jobId": self.job_id,
            "tool": self.tool,
            "toolVersion": self.tool_version,
            "refusal": None if self.refusal is None else self.refusal.to_json(),
        }

    @classmethod
    def from_json(cls, raw: Any, *, source: Path) -> "AcquisitionRecord":
        if not isinstance(raw, dict):
            raise AcquisitionStateError(f"{source} is not a JSON object")
        for key in ("acquisitionId", "sourceId", "url", "status"):
            if not isinstance(raw.get(key), str):
                raise AcquisitionStateError(f"{source} has no usable {key}")
        pid = raw.get("pid")
        return cls(
            acquisition_id=raw["acquisitionId"],
            source_id=raw["sourceId"],
            url=raw["url"],
            status=raw["status"],
            created_at=str(raw.get("createdAt", "")),
            updated_at=str(raw.get("updatedAt", "")),
            pid=pid if isinstance(pid, int) and not isinstance(pid, bool) else None,
            result=raw.get("result") if isinstance(raw.get("result"), str) else None,
            job_id=raw.get("jobId") if isinstance(raw.get("jobId"), str) else None,
            tool=raw.get("tool") if isinstance(raw.get("tool"), str) else None,
            tool_version=(
                raw.get("toolVersion")
                if isinstance(raw.get("toolVersion"), str)
                else None
            ),
            refusal=Refusal.from_json(raw.get("refusal")),
        )

    def advanced(self, **changes: Any) -> "AcquisitionRecord":
        """A copy with ``updatedAt`` moved — every transition goes through it."""
        return replace(self, updated_at=_now(), **changes)


def acquisitions_root(config: AppConfig) -> Path:
    """``<the config.yaml this process loaded>/../.logs/acquisitions``."""
    return config.config_path.parent / LOGS_DIRNAME / ACQUISITIONS_DIRNAME


def status_path(root: Path, acquisition_id: str) -> Path:
    return root / f"{acquisition_id}{STATUS_SUFFIX}"


def log_path(root: Path, acquisition_id: str) -> Path:
    return root / f"{acquisition_id}{LOG_SUFFIX}"


def write_record(root: Path, record: AcquisitionRecord) -> None:
    """Replace the status file atomically: temp file in the same directory,
    flushed and fsynced, then :func:`os.replace`.

    A reader therefore always sees a whole record — the previous one or the
    new one — never a half-written transition.
    """
    target = status_path(root, record.acquisition_id)
    try:
        root.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(
            dir=root, prefix=f"{record.acquisition_id}.", suffix=TEMP_SUFFIX
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(record.to_json(), stream, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, target)
        except BaseException:
            with suppress(OSError):
                temp_path.unlink()
            raise
    except OSError as exc:
        raise AcquisitionStateError(
            f"acquisition state could not be written to {target}: {exc}"
        ) from exc


def _read_record_file(path: Path) -> AcquisitionRecord:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AcquisitionNotFound(f"no acquisition state at {path}") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AcquisitionStateError(
            f"acquisition state is unreadable at {path}: {exc}"
        ) from exc
    return AcquisitionRecord.from_json(raw, source=path)


def read_record(root: Path, acquisition_id: str) -> AcquisitionRecord:
    """The record for one acquisition id, or :class:`AcquisitionNotFound`."""
    return _read_record_file(status_path(root, acquisition_id))


def log_tail(
    path: Path,
    *,
    max_bytes: int = LOG_TAIL_MAX_BYTES,
    max_lines: int = LOG_TAIL_MAX_LINES,
) -> list[str]:
    """The last lines of an acquisition's log, bounded by bytes and by lines.

    Diagnostic only. Nothing the api reports about *why* an acquisition failed
    is read from here — that is what :class:`Refusal` is for — so a missing,
    empty or unreadable log is an empty list rather than an error.
    """
    try:
        with path.open("rb") as stream:
            size = stream.seek(0, os.SEEK_END)
            truncated = size > max_bytes
            stream.seek(max(0, size - max_bytes))
            raw = stream.read()
    except OSError:
        return []
    if truncated:
        # The first line of a byte-bounded read is almost certainly a fragment
        # of a longer one; dropping it is more honest than reporting half.
        raw = raw.partition(b"\n")[2]
    return raw.decode("utf-8", errors="replace").splitlines()[-max_lines:]


# --- the source-id claim -----------------------------------------------------


def pid_is_live(pid: int | None) -> bool:
    """Whether a recorded pid still names a running process.

    ``signal 0`` checks existence and permission without delivering anything.
    A ``PermissionError`` means the process exists and belongs to someone
    else, which is still "live" — refusing is the safe answer.
    """
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def live_record_for_source(root: Path, source_id: str) -> AcquisitionRecord | None:
    """A ``queued``/``running`` record for this source id whose pid is alive.

    Call it holding :func:`claim_lock`. A record that cannot be parsed is
    skipped rather than raised on: one corrupt file must not make every
    future acquisition impossible.
    """
    if not root.is_dir():
        return None
    for path in sorted(root.glob(f"*{STATUS_SUFFIX}")):
        try:
            record = _read_record_file(path)
        except AcquisitionError:
            continue
        if record.source_id != source_id or record.status not in LIVE_STATUSES:
            continue
        if pid_is_live(record.pid):
            return record
    return None


@contextmanager
def claim_lock(root: Path) -> Iterator[None]:
    """Serialize the scan, the status write and the ``Popen`` of one launch.

    Held across all three so the pid is recorded before another claimant can
    scan, which is what makes :func:`live_record_for_source` a reliable
    answer. One lock for the whole directory rather than one per source id:
    the critical section is three cheap operations, and a single inode is
    what makes the scan itself safe.
    """
    try:
        root.mkdir(parents=True, exist_ok=True)
        handle = (root / CLAIM_LOCK_FILENAME).open("a+", encoding="utf-8")
    except OSError as exc:
        raise AcquisitionStateError(
            f"acquisition state directory is unusable: {root}: {exc}"
        ) from exc
    try:
        deadline = time.monotonic() + CLAIM_LOCK_TIMEOUT_SECONDS
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise AcquisitionStateError(
                        "timed out waiting for the acquisition claim lock at"
                        f" {root}; retry once the other launch finishes"
                    ) from None
                time.sleep(0.02)
        yield
    finally:
        with suppress(OSError):
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


# --- launching the detached child --------------------------------------------


def child_command(acquisition_id: str, url: str) -> list[str]:
    """The detached runner's argv. One function so a test can replace the
    whole command rather than stub the process machinery around it."""
    return [
        sys.executable,
        "-m",
        MODULE_NAME,
        "--run",
        "--acquisition-id",
        acquisition_id,
        "--url",
        url,
    ]


def launch(config: AppConfig, url: str) -> AcquisitionRecord:
    """Claim the source id, write the status file, start the detached child.

    Raises :class:`~meetingminer.youtube.YoutubeError` for a URL that is not
    one YouTube video — classified offline, before the status directory is
    even created, so a bad URL leaves no file and starts no process — and
    :class:`AcquisitionInProgress` when a live acquisition already holds the
    source id.
    """
    video_id = youtube.video_id_from_url(url)
    source_id = f"{youtube.YOUTUBE_SOURCE_ID_PREFIX}{video_id}"
    canonical = youtube.watch_url(video_id)
    root = acquisitions_root(config)

    with claim_lock(root):
        live = live_record_for_source(root, source_id)
        if live is not None:
            raise AcquisitionInProgress(live)

        acquisition_id = str(uuid4())
        now = _now()
        record = AcquisitionRecord(
            acquisition_id=acquisition_id,
            source_id=source_id,
            url=canonical,
            status="queued",
            created_at=now,
            updated_at=now,
        )
        write_record(root, record)

        try:
            stream = log_path(root, acquisition_id).open("ab")
        except OSError as exc:
            raise AcquisitionStateError(
                f"acquisition log could not be opened: {exc}"
            ) from exc
        try:
            # The argv is built by `child_command` from constants and two
            # already-validated values; no part of it comes from the request
            # body verbatim, and no shell is involved.
            process = subprocess.Popen(
                child_command(acquisition_id, canonical),
                stdin=subprocess.DEVNULL,
                stdout=stream,
                stderr=subprocess.STDOUT,
                # Detached: its own session, so an api restart (or the shell
                # that started the api going away) does not take the download
                # with it.
                start_new_session=True,
                close_fds=True,
                cwd=str(config.config_path.parent),
            )
        except OSError as exc:
            record = record.advanced(
                status="failed",
                refusal=Refusal(
                    rule="unclassified",
                    detail=_one_line(f"the acquisition process could not start: {exc}"),
                    remediation=REMEDIATIONS["unclassified"],
                ),
            )
            write_record(root, record)
            raise AcquisitionStateError(
                f"the acquisition process could not start: {exc}"
            ) from exc
        finally:
            stream.close()

        record = record.advanced(pid=process.pid)
        write_record(root, record)
    return record


# --- the detached runner -----------------------------------------------------


def run_acquisition(
    config: AppConfig, acquisition_id: str, url: str
) -> AcquisitionRecord:
    """One acquisition, start to finish, writing every transition to the file.

    Story 6.2's :func:`~meetingminer.youtube.acquire` and
    :func:`~meetingminer.mintdrop.post_ingest` are called unchanged: the
    ``exists`` short-circuit answers from the drops root with no ``yt-dlp``
    invocation at all, and intake is reached only through ``POST /ingests``.
    """
    root = acquisitions_root(config)
    record = read_record(root, acquisition_id).advanced(
        status="running", pid=os.getpid()
    )
    write_record(root, record)
    print(f"acquiring  {url}", flush=True)

    try:
        # Resolved before the acquisition, as `youtube-drop`'s CLI does: an
        # unusable api url must not first cost a download and a finalized drop.
        api_url = resolve_api_url(None)
        drops_root = resolve_drops_root(None, config)
        result = youtube.acquire(
            url,
            drops_root=drops_root,
            # All of MM_DROPS_ROOT shares source identity, so `exists` is
            # answered against the configured root, not a sub-directory.
            identity_root=config.secrets.mm_drops_root,
            config_path=config.config_path,
            max_duration_minutes=(
                config.settings.acquisition.youtube.max_duration_minutes
            ),
        )
    except (ConfigError, MintError, youtube.YoutubeError) as exc:
        print(f"refused    {exc}", file=sys.stderr, flush=True)
        record = record.advanced(status="failed", refusal=refusal_for(exc))
        write_record(root, record)
        return record

    print(f"{result.status:<10} {result.path}", flush=True)
    provenance = result.metadata.get("provenance")
    if not isinstance(provenance, dict):
        provenance = {}

    try:
        intake, http_status, job_id = post_ingest(api_url, result.path)
    except IntakeError as exc:
        print(f"intake     FAILED: {exc}", file=sys.stderr, flush=True)
        record = record.advanced(
            status="failed",
            refusal=Refusal(
                # `refusal_rule` classifies an IntakeError as `unclassified`:
                # the drop is fine and the *tool* refused nothing — the api
                # did not answer. The remediation is what makes that
                # actionable, and it is specific to this failure.
                rule=youtube.refusal_rule(exc),
                detail=_one_line(str(exc)),
                remediation=(
                    "The drop is finalized; re-POST this exact drop rather than"
                    " re-running the acquisition:"
                    f" {ingest_command(api_url, result.path)}"
                ),
            ),
        )
        write_record(root, record)
        return record

    print(f"intake     {intake} ({http_status}) jobId {job_id or '(none)'}", flush=True)
    record = record.advanced(
        status="posted",
        result=result.status,
        job_id=job_id,
        tool=provenance.get("tool") if isinstance(provenance.get("tool"), str) else None,
        tool_version=(
            provenance.get("ytDlpVersion")
            if isinstance(provenance.get("ytDlpVersion"), str)
            else None
        ),
    )
    write_record(root, record)
    return record


# --- CLI ---------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description=(
            "Run one acquisition to completion and write its state where"
            " GET /acquisitions/{id} reads it. Started by the api as a"
            " detached host process; not an operator command."
        ),
    )
    parser.add_argument(
        "--run",
        action="store_true",
        required=True,
        help=(
            "run the acquisition named by --acquisition-id. Required and"
            " explicit: this module is imported by the api, and being invoked"
            " with no mode must never be read as 'do the work'."
        ),
    )
    parser.add_argument(
        "--acquisition-id",
        required=True,
        metavar="UUID",
        help="the acquisition whose status file this run writes.",
    )
    parser.add_argument(
        "--url",
        required=True,
        metavar="URL",
        help="the canonical watch URL to acquire.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = _load_cli_config()
    except ConfigError as exc:
        # No config means no status directory to record this in; stderr is the
        # acquisition's own log, which the api serves as the tail.
        print(f"fatal: {PROGRAM} refused: {exc}", file=sys.stderr, flush=True)
        return 1
    try:
        record = run_acquisition(config, args.acquisition_id, args.url)
    except AcquisitionError as exc:
        print(f"fatal: {PROGRAM} refused: {exc}", file=sys.stderr, flush=True)
        return 1
    return 0 if record.status == "posted" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
