"""Upload sessions: bytes from a browser, staged where a drop is minted from.

A source drop is write-once and content-addressed (AD-1). An upload is neither:
it arrives over a socket, in pieces, and may stop half way. This module is the
join between the two, and it does it by never letting an upload near a drop.

**Where the bytes go.** Every part of one session streams into

    <MM_DROPS_ROOT>/.staging/uploads/<sessionId>/

which is inside the drops root — the same volume the drop will be minted on, so
finalizing is a rename and not a copy across filesystems — and invisible as a
drop three times over: the directory is under the dot-prefixed ``.staging``
assembly area ``mintdrop.find_existing_drop`` prunes, it is under a second
``uploads`` level that no drop scan descends into, and it never holds a
``metadata.json``. Intake reads a drop by reading that file, so a session
directory posted to ``POST /ingests`` is refused for being what it is. That is
the guarantee behind "an abandoned session leaves nothing behind that a later
ingest could pick up": not a cleanup that has to run, a shape that cannot be
read as evidence.

**Why the parser is driven by hand.** ``await request.form()`` would spool each
file part into a ``SpooledTemporaryFile`` under ``TMPDIR`` — the boot volume —
and only then hand it over to be copied to ``MM_DROPS_ROOT``: two writes of a
multi-gigabyte recording, ``TMPDIR`` as the real size limit, and a cap that can
only be checked once the bytes have already landed. :func:`create_session`
drives ``python_multipart``'s callbacks over the request stream instead, so each
part is written once, straight to its destination, and the byte counter refuses
mid-stream — which is also the only way to refuse a body whose
``Content-Length`` lied.

**What this module does not do.** It does not mint, convert, probe a dialect,
or talk to intake. ``POST /acquisitions`` names a finished session and
:mod:`meetingminer.acquisitions` runs the same detached child story 6.4 built,
which calls ``dialects.convert_supplied()`` and ``mintdrop.mint()`` in the order
``mintdrop.main()`` calls them. That ordering is not a detail: it is what makes
an uploaded meeting and a hand-minted one the same meeting, because ``sourceId``
is the digest of the bytes that entered the drop and ``startedAt`` comes from
``mintdrop.started_at_from_argument`` either way.

**Refusals are a closed vocabulary**, deliberately this module's own rather than
an extension of ``youtube.REFUSAL_RULES``: the shapes are the same three fields
(``rule``, ``detail``, ``remediation``) but the two sets have nothing to say
about each other, and ``acquisitions.REMEDIATIONS`` is pinned to YouTube's set.
:func:`refusal_for` and ``acquisitions.problem_status`` are where they meet.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import unicodedata
import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Iterable

from python_multipart.multipart import MultipartParser, parse_options_header

from meetingminer.config import AppConfig, ConfigError, validate_drops_root
from meetingminer.domain.drops import (
    EVIDENCE_FILENAMES,
    RECORDING_FILENAME,
    TRANSCRIPT_VTT_FILENAME,
    sha256_and_size,
)
from meetingminer.mintdrop import (
    EXTENSION_TO_CANONICAL,
    STAGING_DIRNAME,
    MintError,
    started_at_from_argument,
)
from meetingminer.pipeline.media import FFPROBE, MediaToolError, probe_media
from meetingminer.transcripts import dialects

#: The second level under ``.staging``. Separate from the mint's own assembly
#: directories, which are siblings of it: a mint creates and removes its own
#: directory per drop, and must never trip over a session that is still being
#: uploaded.
UPLOADS_DIRNAME = "uploads"

#: One session's state, beside its evidence. Not a canonical drop filename, and
#: deliberately not ``metadata.json``: this directory must never read as a drop.
SESSION_FILENAME = "session.json"

#: The in-progress half of an atomic session write, matching the suffix
#: ``acquisitions.write_record`` uses for the same reason.
TEMP_SUFFIX = ".tmp"

#: The multipart field names this endpoint knows. Anything else is refused by
#: name rather than silently ignored, so a misspelled ``titel`` is reported as
#: the typo it is instead of as a missing title.
TEXT_FIELDS = frozenset({"title", "startedAt", "corpus", "transcriptDialect", "suppliedBy"})

#: A drop's ``corpus`` is ``scripted`` or ``real``; an upload may only be
#: ``real``. ``scripted`` meetings are eval subjects, and an eval subject that
#: entered through a browser upload cannot be reproduced from the repository —
#: those are minted on the host with ``make mint-drop``.
UPLOAD_CORPUS = "real"

#: A text part is metadata, so it is bounded far below any file cap. A field
#: this large is a client bug or an attempt to fill the disk through a name.
MAX_FIELD_BYTES = 64 * 1024

#: Bound on how many parts one session may carry. Two files and five fields is
#: the whole contract; the slack is for a client that sends them twice before
#: the duplicate-role refusal fires.
MAX_PARTS = 32

#: A title long enough to be a payload rather than a label. The drop's
#: directory name truncates a slug to 60 characters anyway (``mintdrop.slugify``),
#: so nothing downstream reads more than this.
MAX_TITLE_CHARS = 300

#: What a session's directory name may be, so a path read off disk during a
#: sweep is checked before it is removed rather than trusted.
SESSION_ID_PATTERN = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


class UploadError(RuntimeError):
    """Base for this module's failures."""


class UploadRefused(UploadError):
    """A named refusal: nothing is kept and the caller is told which rule fired.

    ``rule`` is the short stable token a web client switches on; ``str(error)``
    is the operator-facing detail. The pair is the same shape story 6.2a's
    ``YoutubeError`` carries, so ``acquisitions.Refusal`` renders either.
    """

    def __init__(self, message: str, *, rule: str) -> None:
        if rule not in REFUSAL_RULES:
            raise ValueError(f"unknown upload refusal rule: {rule}")
        super().__init__(message)
        self.rule = rule


class UploadSessionNotFound(UploadError):
    """No session directory for that id — never created, swept, or consumed."""


class UploadStateError(UploadError):
    """The staging area could not be created, read, or written."""


#: The closed vocabulary. ``server/tests/test_api_uploads.py`` pins every
#: ``rule=`` literal in this module against this set, and pins the two tables
#: below to it, so a rule can never be raised without a status and a remedy.
REFUSAL_RULES = frozenset(
    {
        # the request is not one this endpoint can read
        "upload-not-multipart",
        "upload-malformed",
        "upload-too-many-parts",
        "upload-unknown-field",
        # the metadata is missing or is not what the drop contract needs
        "upload-metadata-missing",
        "upload-metadata-invalid",
        "upload-started-at-invalid",
        "upload-dialect-undeclared",
        # the files are not evidence this system can hold
        "upload-no-evidence",
        "upload-unsupported-type",
        "upload-duplicate-role",
        "upload-empty-file",
        "upload-too-large",
        "upload-not-a-video",
        "upload-duration-unknown",
        "upload-duration-cap",
        # the host cannot answer
        "upload-probe-unavailable",
        "upload-staging-unwritable",
        # the session named does not exist
        "upload-session-not-found",
    }
)

#: One remediation per rule. The detail says what happened; this says what the
#: person at the browser can do about it, which is the half a client has no way
#: to derive.
REMEDIATIONS: dict[str, str] = {
    "upload-not-multipart": (
        "Send the session as multipart/form-data with a boundary — this endpoint"
        " takes files, not a JSON body."
    ),
    "upload-malformed": (
        "The multipart body ended early or did not parse. Retry the upload; if it"
        " repeats, the connection is dropping mid-transfer."
    ),
    "upload-too-many-parts": (
        f"Send at most {MAX_PARTS} parts: the meeting's title, timestamp, corpus"
        " and dialect, plus a recording and/or a transcript."
    ),
    "upload-unknown-field": (
        "Remove the unrecognized field. This session takes title, startedAt,"
        " corpus, transcriptDialect and suppliedBy, plus the files themselves."
    ),
    "upload-metadata-missing": (
        "Fill in the named field. A drop is write-once, so its title, start time"
        " and corpus are collected before anything is written, never guessed"
        " afterwards."
    ),
    "upload-metadata-invalid": (
        "Correct the named field to one of the values it accepts."
    ),
    "upload-started-at-invalid": (
        "Give the meeting's start as a full RFC 3339 timestamp with its offset"
        " (2026-08-05T12:00:19Z or 2026-08-05T08:00:19-04:00). A date alone does"
        " not say when the meeting started, and a drop is write-once."
    ),
    "upload-dialect-undeclared": (
        "Say which export the .vtt is — plain, teams-vtt, or zoom. It is declared,"
        " never detected: a wrong guess produces a meeting whose every speaker is"
        " Unknown, and the drop cannot be rewritten."
    ),
    "upload-no-evidence": (
        "Attach a recording (.mp4) and/or a transcript (.vtt or .txt). A"
        " transcript-only meeting is fine; a meeting with neither is not a meeting."
    ),
    "upload-unsupported-type": (
        "Attach only .mp4, .vtt or .txt files — those are the three files a source"
        " drop holds."
    ),
    "upload-duplicate-role": (
        "Attach one file per role: a drop holds one recording, one .vtt and one"
        " .txt."
    ),
    "upload-empty-file": "Attach the file itself — an empty file is not evidence.",
    "upload-too-large": (
        "The file is over this server's cap. Raise acquisition.upload in"
        " config.yaml and restart the api if a file this size really belongs in"
        " the corpus, or bring it in on the host with 'make mint-drop'."
    ),
    "upload-not-a-video": (
        "recording.mp4 must be a real video file. A renamed document or an"
        " audio-only file cannot be a recording."
    ),
    "upload-duration-unknown": (
        "ffprobe read no duration from the recording, so the length cap cannot be"
        " checked. Re-export the file, or bring it in on the host with"
        " 'make mint-drop'."
    ),
    "upload-duration-cap": (
        "Raise acquisition.upload.max_duration_minutes in config.yaml and restart"
        " the api if a recording this long really belongs in the corpus."
    ),
    "upload-probe-unavailable": (
        "ffprobe is missing or unrunnable on the api host — install it"
        " ('brew install ffmpeg') and retry. Your file was not the problem."
    ),
    "upload-staging-unwritable": (
        "The upload staging area under MM_DROPS_ROOT could not be written —"
        " check the volume is mounted and writable on the api host, then retry."
    ),
    "upload-session-not-found": (
        "Upload the files again: this session has expired, was discarded, or was"
        " already turned into a drop."
    ),
}

#: One HTTP status per rule. Four buckets: the client sent the wrong thing
#: (400), the file is too big (413) or of a type this system does not hold
#: (415), the request is well-formed but the recording cannot enter the corpus
#: (422), and this server cannot answer (503).
PROBLEM_STATUS: dict[str, int] = {
    "upload-not-multipart": 400,
    "upload-malformed": 400,
    "upload-too-many-parts": 400,
    "upload-unknown-field": 400,
    "upload-metadata-missing": 400,
    "upload-metadata-invalid": 400,
    "upload-started-at-invalid": 400,
    "upload-dialect-undeclared": 400,
    "upload-no-evidence": 400,
    "upload-duplicate-role": 400,
    "upload-empty-file": 400,
    "upload-too-large": 413,
    "upload-unsupported-type": 415,
    "upload-not-a-video": 415,
    "upload-duration-unknown": 422,
    "upload-duration-cap": 422,
    "upload-probe-unavailable": 503,
    "upload-staging-unwritable": 503,
    "upload-session-not-found": 404,
}


@dataclass(frozen=True)
class UploadLimits:
    """The four refusal boundaries, read from ``acquisition.upload`` (AD-10)."""

    max_recording_bytes: int
    max_transcript_bytes: int
    max_duration_minutes: int
    session_ttl_minutes: int

    @classmethod
    def from_config(cls, config: AppConfig) -> "UploadLimits":
        upload = config.settings.acquisition.upload
        return cls(
            max_recording_bytes=upload.max_recording_bytes,
            max_transcript_bytes=upload.max_transcript_bytes,
            max_duration_minutes=upload.max_duration_minutes,
            session_ttl_minutes=upload.session_ttl_minutes,
        )

    def cap_for(self, canonical: str) -> int:
        return (
            self.max_recording_bytes
            if canonical == RECORDING_FILENAME
            else self.max_transcript_bytes
        )

    @property
    def max_body_bytes(self) -> int:
        """The largest body worth reading: both caps, plus room for the fields.

        Used only for the ``Content-Length`` short-circuit. The per-file caps
        are what actually decide, and they are enforced as bytes arrive.
        """
        return self.max_recording_bytes + self.max_transcript_bytes + MAX_FIELD_BYTES * 8


@dataclass(frozen=True)
class UploadedFile:
    """One staged file: what it became, and what it arrived as."""

    canonical: str
    original_filename: str
    sha256: str
    byte_size: int

    def to_json(self) -> dict[str, Any]:
        return {
            "canonical": self.canonical,
            "originalFilename": self.original_filename,
            "sha256": self.sha256,
            "byteSize": self.byte_size,
        }

    @classmethod
    def from_json(cls, raw: Any) -> "UploadedFile":
        if not isinstance(raw, dict):
            raise UploadStateError("a session file entry is not a JSON object")
        try:
            return cls(
                canonical=str(raw["canonical"]),
                original_filename=str(raw.get("originalFilename", "")),
                sha256=str(raw["sha256"]),
                byte_size=int(raw["byteSize"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise UploadStateError(f"a session file entry is unusable: {exc}") from exc


@dataclass(frozen=True)
class UploadSession:
    """One finished session: the metadata a mint needs, and where its bytes are.

    Everything here is what the *client* declared plus what the server measured.
    Nothing is derived from a file's name or its mtime, because the drop this
    becomes is write-once.
    """

    session_id: str
    directory: Path
    title: str
    started_at: str
    corpus: str
    transcript_dialect: str
    supplied_by: str
    created_at: str
    expires_at: str
    files: tuple[UploadedFile, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "uploadSessionId": self.session_id,
            "title": self.title,
            "startedAt": self.started_at,
            "corpus": self.corpus,
            "transcriptDialect": self.transcript_dialect,
            "suppliedBy": self.supplied_by,
            "createdAt": self.created_at,
            "expiresAt": self.expires_at,
            "files": [f.to_json() for f in self.files],
        }

    @classmethod
    def from_json(cls, raw: Any, *, directory: Path) -> "UploadSession":
        if not isinstance(raw, dict):
            raise UploadStateError(f"{directory / SESSION_FILENAME} is not a JSON object")
        required = (
            "uploadSessionId",
            "title",
            "startedAt",
            "corpus",
            "transcriptDialect",
            "createdAt",
            "expiresAt",
        )
        for key in required:
            if not isinstance(raw.get(key), str):
                raise UploadStateError(
                    f"{directory / SESSION_FILENAME} has no usable {key}"
                )
        entries = raw.get("files")
        if not isinstance(entries, list) or not entries:
            raise UploadStateError(f"{directory / SESSION_FILENAME} names no files")
        return cls(
            session_id=raw["uploadSessionId"],
            directory=directory,
            title=raw["title"],
            started_at=raw["startedAt"],
            corpus=raw["corpus"],
            transcript_dialect=raw["transcriptDialect"],
            supplied_by=str(raw.get("suppliedBy", "")),
            created_at=raw["createdAt"],
            expires_at=raw["expiresAt"],
            files=tuple(UploadedFile.from_json(entry) for entry in entries),
        )

    def staged_paths(self) -> list[str]:
        """The staged files, in the order ``mint-drop`` would take them.

        :func:`mintdrop.classify_supplied` re-orders by
        :data:`~meetingminer.domain.drops.EVIDENCE_FILENAMES` anyway, so this is
        the same list the CLI would build from an operator's argv — which is
        what makes the primary file, and therefore the identity, the same one.
        """
        return [str(self.directory / f.canonical) for f in self.files]


# --- where sessions live ----------------------------------------------------


def sessions_root(config: AppConfig) -> Path:
    """``<MM_DROPS_ROOT>/.staging/uploads``.

    Anchored on the configured drops root and never on a caller-supplied path:
    the whole point of the location is that it is on the same volume as the
    drop, inside an area nothing scans for drops.
    """
    try:
        root = validate_drops_root(config.secrets.mm_drops_root)
    except ConfigError as exc:
        raise UploadRefused(
            f"the drops root is unusable, so no upload can be staged: {exc}",
            rule="upload-staging-unwritable",
        ) from exc
    return root / STAGING_DIRNAME / UPLOADS_DIRNAME


def session_directory(root: Path, session_id: str) -> Path:
    """One session's directory, refusing any id that is not a UUID.

    The api types the path parameter as a ``UUID`` so a request can never name
    a file; this is the same check made where the value is turned into a path,
    for callers that did not come through the api.
    """
    if not SESSION_ID_PATTERN.fullmatch(session_id):
        raise UploadRefused(
            f"not an upload session id: {session_id!r}",
            rule="upload-session-not-found",
        )
    return root / session_id


def write_session(session: UploadSession) -> None:
    """Write ``session.json`` atomically: temp file beside it, then rename.

    The same discipline ``acquisitions.write_record`` uses, and for a stronger
    reason: a reader that saw a half-written session would mint a drop from a
    half-declared meeting.
    """
    target = session.directory / SESSION_FILENAME
    try:
        handle, temp_name = tempfile.mkstemp(
            dir=session.directory, prefix=SESSION_FILENAME + ".", suffix=TEMP_SUFFIX
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(session.to_json(), stream, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, target)
        except BaseException:
            with suppress(OSError):
                temp_path.unlink()
            raise
    except OSError as exc:
        raise UploadStateError(
            f"the upload session could not be written to {target}: {exc}"
        ) from exc


def read_session(root: Path, session_id: str) -> UploadSession:
    """One session, or :class:`UploadSessionNotFound`.

    Every file the session names must still be on disk. A directory that lost
    one is not a session that can be minted from, and reporting it as one would
    trade a clear 404 for a mint refusal an hour later.
    """
    directory = session_directory(root, session_id)
    path = directory / SESSION_FILENAME
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise UploadSessionNotFound(f"no upload session at {directory}") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UploadStateError(f"the upload session at {path} is unreadable: {exc}") from exc
    session = UploadSession.from_json(raw, directory=directory)
    if session.session_id != session_id:
        raise UploadStateError(
            f"the upload session at {path} names {session.session_id!r},"
            f" not {session_id!r}"
        )
    for staged in session.files:
        if not (directory / staged.canonical).is_file():
            raise UploadSessionNotFound(
                f"the upload session at {directory} has lost {staged.canonical}"
            )
    return session


def discard_session(root: Path, session_id: str) -> bool:
    """Remove one session's directory. ``True`` when there was one to remove.

    Never raises for a missing directory: this runs on the failure path of an
    acquisition, and a cleanup that can fail is a cleanup that leaves bytes
    behind.
    """
    try:
        directory = session_directory(root, session_id)
    except UploadRefused:
        return False
    if not directory.is_dir():
        return False
    shutil.rmtree(directory, ignore_errors=True)
    return not directory.exists()


def expired_at(created: datetime, limits: UploadLimits) -> datetime:
    return created + timedelta(minutes=limits.session_ttl_minutes)


def sweep_expired(root: Path, limits: UploadLimits, *, now: datetime) -> list[str]:
    """Remove session directories past their TTL; return the ids removed.

    Cheap and bounded — one ``listdir`` of a directory that holds only live
    sessions — so it runs at the start of every ``POST /uploads`` rather than
    needing a timer nobody would notice had stopped. Story 6.4's spec recorded
    that nothing reaped staged state and left the sweep to this story.

    A directory whose name is not a session id is left alone: this deletes
    recursively under the drops root, so it only ever deletes what it can prove
    it made. A directory with no readable ``session.json`` is swept only once it
    is older than the TTL by its own mtime — an upload in flight has no session
    file yet, and must not be deleted out from under itself.
    """
    if not root.is_dir():
        return []
    removed: list[str] = []
    try:
        entries = sorted(root.iterdir())
    except OSError:
        return []
    for entry in entries:
        if not entry.is_dir() or not SESSION_ID_PATTERN.fullmatch(entry.name):
            continue
        try:
            session = read_session(root, entry.name)
        except UploadSessionNotFound:
            session = None
        except UploadError:
            session = None
        if session is not None:
            if _parse_stamp(session.expires_at) > now:
                continue
        else:
            try:
                mtime = datetime.fromtimestamp(entry.stat().st_mtime, tz=timezone.utc)
            except OSError:
                continue
            if expired_at(mtime, limits) > now:
                continue
        shutil.rmtree(entry, ignore_errors=True)
        if not entry.exists():
            removed.append(entry.name)
    return removed


def _parse_stamp(raw: str) -> datetime:
    """A stamp this module wrote, or the epoch when it cannot be read.

    An unreadable ``expiresAt`` reads as long expired: the alternative is a
    directory that can never be swept because its own clock is broken.
    """
    try:
        # `%z` accepts the literal `Z` this module writes, and returns an aware
        # datetime, so the comparison against `now` is never naive.
        return datetime.strptime(raw, "%Y-%m-%dT%H:%M:%S%z")
    except (TypeError, ValueError):
        return datetime.fromtimestamp(0, tz=timezone.utc)


def _stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- receiving one session --------------------------------------------------


class _PartSink:
    """The parser's callbacks, holding the one part currently being written.

    Kept as an object rather than a closure soup because the parser hands back
    header bytes in arbitrarily many pieces, so every field here is an
    accumulator that only means something at ``on_part_end``.
    """

    def __init__(self, directory: Path, limits: UploadLimits) -> None:
        self.directory = directory
        self.limits = limits
        self.fields: dict[str, str] = {}
        self.files: dict[str, UploadedFile] = {}
        self.parts = 0
        self._header_field = bytearray()
        self._header_value = bytearray()
        self._disposition: dict[bytes, bytes] = {}
        self._name: str | None = None
        self._filename: str | None = None
        self._canonical: str | None = None
        self._handle: Any = None
        self._written = 0
        self._text = bytearray()

    # -- parts

    def on_part_begin(self) -> None:
        self.parts += 1
        if self.parts > MAX_PARTS:
            raise UploadRefused(
                f"the session carries more than {MAX_PARTS} parts",
                rule="upload-too-many-parts",
            )
        self._disposition = {}
        self._name = None
        self._filename = None
        self._canonical = None
        self._handle = None
        self._written = 0
        self._text = bytearray()

    def on_header_field(self, data: bytes, start: int, end: int) -> None:
        self._header_field.extend(data[start:end])

    def on_header_value(self, data: bytes, start: int, end: int) -> None:
        self._header_value.extend(data[start:end])

    def on_header_end(self) -> None:
        name = bytes(self._header_field).lower()
        value = bytes(self._header_value)
        self._header_field = bytearray()
        self._header_value = bytearray()
        if name == b"content-disposition":
            _, options = parse_options_header(value)
            self._disposition = options

    def on_headers_finished(self) -> None:
        raw_name = self._disposition.get(b"name")
        if raw_name is None:
            raise UploadRefused(
                "a part of the upload declared no field name",
                rule="upload-malformed",
            )
        self._name = _decode(raw_name)
        raw_filename = self._disposition.get(b"filename")
        if raw_filename is None:
            if self._name not in TEXT_FIELDS:
                raise UploadRefused(
                    f"unknown field {self._name!r} — this session takes"
                    f" {', '.join(sorted(TEXT_FIELDS))}, plus the files themselves",
                    rule="upload-unknown-field",
                )
            return
        self._filename = _decode(raw_filename)
        self._canonical = _canonical_for(self._filename)
        if self._canonical in self.files:
            raise UploadRefused(
                f"two files map to {self._canonical}: {self.files[self._canonical].original_filename!r}"
                f" and {self._filename!r} — a drop holds one of each",
                rule="upload-duplicate-role",
            )
        destination = self.directory / self._canonical
        try:
            self._handle = destination.open("wb")
        except OSError as exc:
            raise UploadRefused(
                f"the upload could not be staged at {destination}: {exc}",
                rule="upload-staging-unwritable",
            ) from exc

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        chunk = data[start:end]
        if self._handle is None:
            self._text.extend(chunk)
            if len(self._text) > MAX_FIELD_BYTES:
                raise UploadRefused(
                    f"the {self._name!r} field is over {MAX_FIELD_BYTES} bytes",
                    rule="upload-too-large",
                )
            return
        self._written += len(chunk)
        cap = self.limits.cap_for(self._canonical or "")
        if self._written > cap:
            # Refused here rather than from Content-Length alone: a body may
            # arrive chunked, or may simply have lied about its length, and by
            # then the bytes are already landing on the evidence volume.
            raise UploadRefused(
                f"{self._filename!r} is over this server's {cap}-byte cap for"
                f" {self._canonical}",
                rule="upload-too-large",
            )
        try:
            self._handle.write(chunk)
        except OSError as exc:
            raise UploadRefused(
                f"{self._filename!r} could not be written to the staging"
                f" directory: {exc}",
                rule="upload-staging-unwritable",
            ) from exc

    def on_part_end(self) -> None:
        if self._handle is None:
            if self._name is not None:
                self.fields[self._name] = _decode(bytes(self._text)).strip()
            return
        try:
            self._handle.close()
        except OSError as exc:
            raise UploadRefused(
                f"{self._filename!r} could not be written to the staging"
                f" directory: {exc}",
                rule="upload-staging-unwritable",
            ) from exc
        self._handle = None
        canonical = self._canonical or ""
        path = self.directory / canonical
        if self._written == 0:
            raise UploadRefused(
                f"{self._filename!r} is empty — an empty file is not evidence",
                rule="upload-empty-file",
            )
        digest, size = sha256_and_size(path)
        self.files[canonical] = UploadedFile(
            canonical=canonical,
            original_filename=self._filename or canonical,
            sha256=digest,
            byte_size=size,
        )

    def close(self) -> None:
        if self._handle is not None:
            with suppress(OSError):
                self._handle.close()
            self._handle = None

    def ordered_files(self) -> tuple[UploadedFile, ...]:
        """The staged files in canonical drop order, so the primary is first."""
        return tuple(self.files[name] for name in EVIDENCE_FILENAMES if name in self.files)


def _decode(raw: bytes) -> str:
    return raw.decode("utf-8", errors="replace")


def _canonical_for(filename: str) -> str:
    """The drop filename an uploaded file becomes, by extension — never by sniffing.

    The same rule ``mint-drop`` applies to an operator's argv
    (``EXTENSION_TO_CANONICAL``), so an upload and a hand mint of the same file
    produce the same drop. The client's own path separators are stripped first:
    a browser may send a full path, and nothing here may read one.
    """
    name = unicodedata.normalize("NFKD", filename).replace("\\", "/").rsplit("/", 1)[-1]
    suffix = Path(name).suffix.lower()
    canonical = EXTENSION_TO_CANONICAL.get(suffix)
    if canonical is None:
        raise UploadRefused(
            f"{filename!r} is not evidence this system holds — a drop holds"
            f" {', '.join(EVIDENCE_FILENAMES)}, so an upload must be one of"
            f" {', '.join(sorted(EXTENSION_TO_CANONICAL))}",
            rule="upload-unsupported-type",
        )
    return canonical


def boundary_from(content_type: str | None) -> bytes:
    """The multipart boundary, or a named refusal."""
    if not content_type:
        raise UploadRefused(
            "the request declared no Content-Type; an upload session is"
            " multipart/form-data",
            rule="upload-not-multipart",
        )
    media_type, options = parse_options_header(content_type)
    if media_type.lower() != b"multipart/form-data":
        raise UploadRefused(
            f"the request is {_decode(media_type)!r}, not multipart/form-data",
            rule="upload-not-multipart",
        )
    boundary = options.get(b"boundary")
    if not boundary:
        raise UploadRefused(
            "the multipart request declared no boundary",
            rule="upload-not-multipart",
        )
    return boundary


async def create_session(
    *,
    root: Path,
    content_type: str | None,
    content_length: int | None,
    body: AsyncIterator[bytes],
    limits: UploadLimits,
    now: datetime,
) -> UploadSession:
    """Receive one multipart session into its own staging directory.

    Every failure removes the directory before it propagates, so a refused
    session leaves nothing behind — not a partial recording, and above all not
    a directory a later ingest could find. The order is deliberate: the
    boundary and the declared length are checked before a directory exists, the
    files stream in with their caps enforced as they arrive, and the metadata is
    validated once the whole body has been read, because a multipart body may
    put its fields after its files and the client does not control that.
    """
    boundary = boundary_from(content_type)
    if content_length is not None and content_length > limits.max_body_bytes:
        raise UploadRefused(
            f"the upload declares {content_length} bytes, over this server's"
            f" {limits.max_body_bytes}-byte cap for one session",
            rule="upload-too-large",
        )

    session_id = str(uuid.uuid4())
    directory = session_directory(root, session_id)
    try:
        directory.mkdir(parents=True)
    except OSError as exc:
        raise UploadRefused(
            f"the upload staging directory could not be created at {directory}:"
            f" {exc}",
            rule="upload-staging-unwritable",
        ) from exc

    sink = _PartSink(directory, limits)
    try:
        parser = MultipartParser(
            boundary,
            {
                "on_part_begin": sink.on_part_begin,
                "on_header_field": sink.on_header_field,
                "on_header_value": sink.on_header_value,
                "on_header_end": sink.on_header_end,
                "on_headers_finished": sink.on_headers_finished,
                "on_part_data": sink.on_part_data,
                "on_part_end": sink.on_part_end,
            },
        )
        try:
            async for chunk in body:
                if chunk:
                    parser.write(chunk)
            parser.finalize()
        except UploadError:
            raise
        except Exception as exc:  # the parser's own errors, and a dropped socket
            raise UploadRefused(
                f"the multipart body could not be read: {exc}",
                rule="upload-malformed",
            ) from exc
        finally:
            sink.close()

        session = _finish(
            session_id=session_id,
            directory=directory,
            sink=sink,
            limits=limits,
            now=now,
        )
        write_session(session)
    except BaseException:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    return session


def _finish(
    *,
    session_id: str,
    directory: Path,
    sink: _PartSink,
    limits: UploadLimits,
    now: datetime,
) -> UploadSession:
    """Validate what arrived and turn it into a session record.

    Runs after the whole body: the metadata rules need to know which files came
    with it (the dialect is only required when a ``.vtt`` did), and a multipart
    body may order its parts however it likes.
    """
    files = sink.ordered_files()
    if not files:
        raise UploadRefused(
            "the session carried no recording and no transcript — attach a .mp4,"
            " a .vtt, or a .txt",
            rule="upload-no-evidence",
        )

    title = _require(sink.fields, "title")
    if len(title) > MAX_TITLE_CHARS:
        raise UploadRefused(
            f"title is longer than {MAX_TITLE_CHARS} characters",
            rule="upload-metadata-invalid",
        )

    corpus = _require(sink.fields, "corpus")
    if corpus != UPLOAD_CORPUS:
        raise UploadRefused(
            f"corpus must be {UPLOAD_CORPUS!r} for an upload, not {corpus!r} —"
            " scripted meetings are eval subjects and are minted on the api host"
            " with 'make mint-drop'",
            rule="upload-metadata-invalid",
        )

    started_at = _started_at(_require(sink.fields, "startedAt"))
    dialect = _dialect(sink.fields.get("transcriptDialect"), files)
    supplied_by = sink.fields.get("suppliedBy", "").strip() or "upload"

    recording = next((f for f in files if f.canonical == RECORDING_FILENAME), None)
    if recording is not None:
        _assert_video_within_cap(directory / recording.canonical, limits)

    created = _stamp(now)
    return UploadSession(
        session_id=session_id,
        directory=directory,
        title=title,
        started_at=started_at,
        corpus=corpus,
        transcript_dialect=dialect,
        supplied_by=supplied_by,
        created_at=created,
        expires_at=_stamp(expired_at(now, limits)),
        files=files,
    )


def _require(fields: dict[str, str], name: str) -> str:
    value = fields.get(name, "").strip()
    if not value:
        raise UploadRefused(
            f"{name} is required and was not supplied — a drop is write-once, so"
            " its metadata is collected before anything is written",
            rule="upload-metadata-missing",
        )
    return value


def _started_at(raw: str) -> str:
    """The declared start, as the drop will carry it, or a named refusal.

    Parsed by ``mintdrop.started_at_from_argument`` — the same function the CLI
    hands ``--started-at`` to — so an uploaded meeting and a hand-minted one
    cannot disagree about what a timestamp means. Day precision is then refused
    rather than accepted: a date is a date the *file* was made, not a time the
    meeting started, and the UI collects a real timestamp (story 6.5a).
    """
    try:
        started_at, precision = started_at_from_argument(raw)
    except MintError as exc:
        raise UploadRefused(str(exc), rule="upload-started-at-invalid") from exc
    if precision != "second":
        raise UploadRefused(
            f"startedAt must name a time of day and its offset, not just a date:"
            f" {raw!r} — an upload never records day precision",
            rule="upload-started-at-invalid",
        )
    return started_at


def _dialect(declared: str | None, files: Iterable[UploadedFile]) -> str:
    """Which export the transcript is — declared, never sniffed.

    Required whenever a ``.vtt`` is present, because that is the file whose
    meaning differs between exports: a Zoom VTT carries its speakers inside the
    cue payloads and mints, unconverted, into a meeting whose every turn is
    ``Unknown``. Without a VTT the declaration has nothing to act on, so the
    default stands.
    """
    has_vtt = any(f.canonical == TRANSCRIPT_VTT_FILENAME for f in files)
    value = (declared or "").strip()
    if not value:
        if has_vtt:
            raise UploadRefused(
                "transcriptDialect is required when a .vtt is uploaded: say"
                f" which export it is ({', '.join(dialects.DIALECTS)}). It is"
                " declared, never detected — a drop is write-once",
                rule="upload-dialect-undeclared",
            )
        return dialects.DEFAULT_DIALECT
    if value not in dialects.DIALECTS:
        raise UploadRefused(
            f"unknown transcript dialect {value!r} — expected one of"
            f" {', '.join(dialects.DIALECTS)}",
            rule="upload-metadata-invalid",
        )
    return value


def _assert_video_within_cap(path: Path, limits: UploadLimits) -> None:
    """The recording is a video, and it is not longer than the configured cap.

    Both checks happen here, before a session is reported complete, so a file
    that can never become a drop is refused while the person who chose it is
    still looking at the screen — rather than an hour later, from a detached
    runner, as a failed acquisition.
    """
    if shutil.which(FFPROBE) is None:
        raise UploadRefused(
            f"{FFPROBE} is not on PATH on the api host, so an uploaded recording"
            " cannot be checked",
            rule="upload-probe-unavailable",
        )
    try:
        facts = probe_media(path)
    except MediaToolError as exc:
        raise UploadRefused(
            f"the uploaded recording is not readable as a video: {exc}",
            rule="upload-not-a-video",
        ) from exc
    if not facts.has_video:
        raise UploadRefused(
            f"the uploaded recording carries no video stream (container"
            f" {facts.container or 'unknown'}) — {RECORDING_FILENAME} must be a"
            " video",
            rule="upload-not-a-video",
        )
    if facts.duration_ms is None:
        raise UploadRefused(
            "ffprobe read no duration from the uploaded recording, so"
            " acquisition.upload.max_duration_minutes cannot be checked",
            rule="upload-duration-unknown",
        )
    minutes = facts.duration_ms / 60_000
    if minutes > limits.max_duration_minutes:
        raise UploadRefused(
            f"the recording is {minutes:.1f} minutes, over the"
            f" {limits.max_duration_minutes}-minute cap"
            " (acquisition.upload.max_duration_minutes)",
            rule="upload-duration-cap",
        )
