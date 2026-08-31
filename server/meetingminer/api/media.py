"""GET /media — read-only byte streaming for the evidence bundle (story 2.1).

Two routes share one prefix because they answer the same question ("give me
the bytes behind this piece of evidence") from two different addresses:

* ``/media/recordings/{meetingId}`` is id-addressed, because a meeting id is
  what a citation carries. The bytes are found through the recording's own
  provenance row: ``meeting_media.drop_relative_path``, anchored to
  ``MM_DROPS_ROOT`` and resolved at request time (story 2.1a). The path is
  entirely data — no filename constant is spliced into it — and the drop is
  opened read-only and never written (AD-1/AD-13).
* ``/media/{path:path}`` is path-addressed, because ``screenshot.path`` and
  ``frame.path`` are stored relative to ``MM_CONTENT_ROOT`` and nothing else
  (AD-3). A client-supplied path is the only thing here that needs guarding,
  which is why :func:`_resolve_under_root` exists.

The guard, the range parser and the responder live in this one module on
purpose: a route that streams bytes without the containment check, or a range
header parsed one way in one place and another way elsewhere, are both silent
failures. Keeping them together makes them impossible to drift apart.

The api is read-only here (AD-5/AD-11): it reads ``meeting`` and
``meeting_media`` and writes nothing, transcodes nothing, and caches nothing.

No absolute filesystem path ever appears in a response body or header — not in
a problem detail, not in a 404. Both configured roots are server-side facts the
client never learns.
"""

from __future__ import annotations

import mimetypes
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO
from uuid import UUID

from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse

from meetingminer.api.problems import (
    DROPS_ROOT_UNCONFIGURED,
    Problem,
    ProblemDetails,
    problem_response,
)
from meetingminer.config import ConfigError, validate_drops_root
from meetingminer.domain.drops import DropPathError, resolve_drop_path

router = APIRouter()
ROUTER_ORDER = 70

# 64 KiB: large enough that a multi-GB recording is not read a syscall at a
# time, small enough that a seek-heavy player does not park megabytes per
# in-flight request.
CHUNK_SIZE = 64 * 1024

# What an unrecognised extension is served as. Never guessed from content:
# sniffing is what turns an uploaded file into a script in someone's browser.
DEFAULT_MEDIA_TYPE = "application/octet-stream"

_PROBLEM_RESPONSE = {"model": ProblemDetails, "content": {"application/problem+json": {}}}

_MEDIA_RESPONSES: dict[int | str, dict] = {
    200: {"content": {"application/octet-stream": {}}, "description": "The file's bytes."},
    206: {
        "content": {"application/octet-stream": {}},
        "description": "The requested byte range.",
    },
    400: _PROBLEM_RESPONSE,
    404: _PROBLEM_RESPONSE,
    416: _PROBLEM_RESPONSE,
    500: _PROBLEM_RESPONSE,
}


# --- the content root ------------------------------------------------------


def _content_root(request: Request) -> Path:
    """The configured ``MM_CONTENT_ROOT``, or a 500 naming the misconfiguration.

    Reached through ``app.state.config`` rather than by importing
    ``api.main`` (which would be circular), and deliberately *not* through
    :func:`meetingminer.config.require_content_root`: that helper creates the
    directory and write-probes it, which is exactly what a read-only api must
    not do.

    A root that is set but is not a directory is the same class of fault as an
    unset one — an operator error, not a missing file — so it answers 500 too
    rather than reporting every request as a 404.
    """
    root = request.app.state.config.secrets.mm_content_root
    if root is None:
        raise Problem(
            500,
            "media-root-unconfigured",
            "MM_CONTENT_ROOT is not set on the api process, so no media can be"
            " served; set it in .env and restart the api",
        )
    if not root.is_dir():
        raise Problem(
            500,
            "media-root-unconfigured",
            "MM_CONTENT_ROOT is set on the api process but is not a directory,"
            " so no media can be served",
        )
    return root


def _drops_root(request: Request) -> Path:
    """The configured ``MM_DROPS_ROOT``, or a 500 naming the misconfiguration.

    The same shape and the same reasoning as :func:`_content_root`, for the
    other anchor (`storage-layout.md` §1). The api gates on
    ``require_drops_root`` at startup, so an unset root here means the config
    was swapped underneath a running process; it is still answered rather than
    assumed, because assuming would resolve every stored path against ``/``.

    Its own problem type, not the content root's: two roots reported under one
    slug leave an operator unable to tell from the response which of them is
    broken, and they are set independently.
    """
    try:
        return validate_drops_root(request.app.state.config.secrets.mm_drops_root)
    except ConfigError:
        raise Problem(
            500,
            DROPS_ROOT_UNCONFIGURED,
            "MM_DROPS_ROOT is unavailable on the api process, so no recording"
            " can be served; correct the mount or .env and restart the api",
        ) from None


# --- the path guard --------------------------------------------------------


def _invalid_path() -> Problem:
    """The one rejection message every guard failure uses.

    Deliberately uniform and deliberately path-free: telling a caller *which*
    check its path tripped tells it how to probe the filesystem layout, and
    echoing the path back tells it what the server resolved.
    """
    return Problem(
        400,
        "media-path-invalid",
        "the requested media path is not a valid content-root-relative path",
    )


def _resolve_under_root(root: Path, relative: str) -> Path:
    """Return the file ``relative`` names under ``root``, or raise a 400.

    The read-only twin of ``pipeline/outputs.py:assert_private_meeting_subdir``
    and it uses that guard's shape: reject the obviously-hostile spellings,
    reject a symlink at *any* component from the root down, then resolve and
    require containment. It is reimplemented rather than imported because the
    api never imports ``pipeline`` and because that function validates a
    *write* target (it also refuses non-directories, and is called with a
    server-chosen subdir rather than a client-supplied path).

    Every symlinked component is refused, not only one that leaves the root.
    The content root's written subtree is entirely worker-created
    (``meetings/<id>/{frames,screenshots}/``) and contains no symlink, so
    there is nothing legitimate to lose, and "does this link land back inside
    the root" is a question with a different answer at every moment.
    """
    # A NUL makes every downstream path call raise ValueError; catch it here so
    # the answer is a 400 rather than the catch-all 500.
    if "\x00" in relative:
        raise _invalid_path()
    # `/media//etc/passwd` arrives as the absolute `/etc/passwd`: the router's
    # `{path:path}` converter hands over whatever follows the prefix verbatim.
    if relative.startswith("/"):
        raise _invalid_path()

    parts = PurePosixPath(relative).parts
    if any(part == ".." for part in parts):
        raise _invalid_path()

    # Walking component by component builds the target as it checks it, so the
    # path that was guarded is exactly the path that gets served.
    target = root
    for part in parts:
        target = target / part
        if target.is_symlink():
            raise _invalid_path()

    if not target.resolve().is_relative_to(root.resolve()):
        raise _invalid_path()
    return target


# --- the range parser ------------------------------------------------------


@dataclass(frozen=True)
class _ByteRange:
    """An inclusive byte range, already clamped to the file it describes."""

    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start + 1


@dataclass(frozen=True)
class _Unsatisfiable:
    """Sentinel: the ``Range`` header parsed, but names nothing the file has.

    Distinct from ``None`` (absent or ignorable) because the two answers get
    opposite responses: 416 versus the whole file.
    """


_UNSATISFIABLE = _Unsatisfiable()

# Room for any offset a filesystem can address (2**63 is 19 digits), and a hard
# stop well short of the interpreter's own int-conversion limit.
_MAX_OFFSET_DIGITS = 19


def _offset(text: str) -> int | None:
    """Parse one number out of a range-spec, or ``None`` if it is not one.

    ``str.isdigit`` is not the same question as "``int()`` will take this".
    It is true for superscripts, which ``int()`` then refuses — a Range header
    is decoded as latin-1, so a raw ``0xB2`` byte arrives as ``"²"`` — and it
    is true for other scripts' digits, which ``int()`` silently accepts as
    values no HTTP client meant to send. A run of a few thousand digits trips
    the interpreter's conversion limit instead. Every one of those would raise
    out of a route the matrix says must ignore an unusable Range and serve the
    whole file, so the accepted spelling is narrowed to ASCII and bounded.
    """
    if not text.isascii() or not text.isdigit() or len(text) > _MAX_OFFSET_DIGITS:
        return None
    return int(text)


def _parse_range(header: str | None, size: int) -> _ByteRange | _Unsatisfiable | None:
    """Interpret a ``Range`` header against a file of ``size`` bytes.

    Returns the clamped range, :data:`_UNSATISFIABLE` when the header is
    well-formed but names nothing the file has, or ``None`` when there is no
    usable range and the whole representation should be served.

    ``None`` covers every "ignore it" case RFC 9110 §14.2 allows: an absent
    header, a unit other than ``bytes``, a syntactically broken range-spec,
    and a multi-range request (this api never emits ``multipart/byteranges``,
    and a server may always answer the whole representation instead).
    """
    if header is None:
        return None
    unit, separator, spec = header.partition("=")
    if separator != "=" or unit.strip().lower() != "bytes":
        return None
    # One range only. `bytes=0-9, 20-29` is legal to answer in full.
    if "," in spec:
        return None
    first, separator, last = spec.strip().partition("-")
    if separator != "-":
        return None

    if first == "":
        # Suffix form, `bytes=-N`: the final N bytes. A suffix of zero bytes
        # names nothing, which RFC 9110 makes unsatisfiable rather than empty.
        suffix = _offset(last)
        if suffix is None:
            return None
        if suffix == 0 or size == 0:
            return _UNSATISFIABLE
        return _ByteRange(max(0, size - suffix), size - 1)

    start = _offset(first)
    if start is None:
        return None
    if last == "":
        end = size - 1
    else:
        stop = _offset(last)
        if stop is None:
            return None
        # Clamped, not rejected: a player that asks past EOF gets what exists.
        end = min(stop, size - 1)

    if start >= size:
        return _UNSATISFIABLE
    if end < start:
        # `bytes=5-2` is malformed, so the header is ignored entirely. (A
        # start inside the file with an end clamped below it is impossible:
        # end is clamped to size-1 and start < size.)
        return None
    return _ByteRange(start, end)


# --- the responder ---------------------------------------------------------


def _iter_chunks(stream: BinaryIO, start: int, length: int) -> Iterator[bytes]:
    """Yield ``length`` bytes from ``start``, closing ``stream`` when done.

    The handle is opened by the caller so that a permission error or a file
    deleted between the stat and the open becomes a problem response, rather
    than an exception raised after a 200 status line is already on the wire.
    """
    try:
        stream.seek(start)
        remaining = length
        while remaining > 0:
            chunk = stream.read(min(CHUNK_SIZE, remaining))
            if not chunk:  # truncated under us; stop rather than spin
                break
            remaining -= len(chunk)
            yield chunk
    finally:
        stream.close()


def _stream_file(request: Request, path: Path, missing_detail: str) -> Response:
    """Stream ``path``, honouring ``Range``; 404 with ``missing_detail`` if absent.

    ``missing_detail`` is supplied by the caller because only the caller knows
    how to describe the file without naming where it is: the path-addressed
    route talks about the requested path, the recording route talks about the
    meeting.
    """
    # `is_file()` follows links. That is safe only because every caller has
    # already refused a symlinked path — `_resolve_under_root` for the
    # path-addressed route, `resolve_drop_path` for the recording — so all
    # this call decides is a real file versus a directory or a missing entry.
    if not path.is_file():
        raise Problem(404, "media-not-found", missing_detail)
    try:
        size = path.stat().st_size
        stream = path.open("rb")
    except OSError:
        # Unreadable is indistinguishable from absent to a client that is never
        # told where the file is, and saying more would leak the layout.
        raise Problem(404, "media-not-found", missing_detail) from None

    media_type = mimetypes.guess_type(path.name)[0] or DEFAULT_MEDIA_TYPE
    requested = _parse_range(request.headers.get("range"), size)

    if isinstance(requested, _Unsatisfiable):
        stream.close()
        return problem_response(
            416,
            "media-range-unsatisfiable",
            f"the requested range lies outside this {size}-byte resource",
            title="Range Not Satisfiable",
            headers={"Content-Range": f"bytes */{size}", "Accept-Ranges": "bytes"},
        )

    if requested is None:
        return StreamingResponse(
            _iter_chunks(stream, 0, size),
            status_code=200,
            media_type=media_type,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(size),
                # The declared type is the whole type: a route that hands back
                # raw file bytes must not let a browser re-decide what they are.
                "X-Content-Type-Options": "nosniff",
            },
        )

    return StreamingResponse(
        _iter_chunks(stream, requested.start, requested.length),
        status_code=206,
        media_type=media_type,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(requested.length),
            "Content-Range": f"bytes {requested.start}-{requested.end}/{size}",
            "X-Content-Type-Options": "nosniff",
        },
    )


# --- routes ----------------------------------------------------------------

# One statement, therefore one snapshot: the meeting's recording flag and the
# recorded path have to be read together or a re-armed job could hand back one
# meeting's flag beside another run's path. LEFT JOIN, because a recorded
# meeting whose `probe` has not settled yet has no `meeting_media` row at all.
_MEETING_RECORDING = (
    "SELECT m.has_recording, mm.drop_relative_path"
    " FROM meeting m LEFT JOIN meeting_media mm ON mm.meeting_id = m.id"
    " WHERE m.id = %s"
)


@router.get(
    "/media/recordings/{meeting_id}",
    operation_id="getRecording",
    response_class=Response,
    responses=_MEDIA_RESPONSES,
)
def get_recording(meeting_id: UUID, request: Request) -> Response:
    """Stream a meeting's recording from its source drop, read-only.

    The drop is write-once (AD-1/AD-13) and nothing here copies, moves or
    rewrites it. The stored path is relative to ``MM_DROPS_ROOT`` and is
    resolved here; neither the root nor the resolved path ever reaches the
    client, which only ever names the meeting.
    """
    pool = request.app.state.pool
    with pool.connection() as conn:
        row = conn.execute(_MEETING_RECORDING, (meeting_id,)).fetchone()

    if row is None:
        raise Problem(404, "media-not-found", f"no meeting with id {meeting_id}")
    has_recording, relative = row
    if not has_recording:
        raise Problem(
            404,
            "media-no-recording",
            f"meeting {meeting_id} was ingested transcript-only and has no recording",
        )

    missing = f"the recording for meeting {meeting_id} is not on disk"
    if relative is None:
        # `has_recording` is true but nothing recorded where the bytes are:
        # `probe` has not settled, or the row predates story 2.1a and the
        # backfill has not run. Not servable, and not distinguishable to a
        # client from an absent file — which is the point.
        raise Problem(404, "media-not-found", missing)
    # Read after both 404 branches, not before them: a transcript-only meeting
    # answers `media-no-recording` whatever the drops root is doing, because
    # nothing about that answer depends on the root. Reading it first turned
    # every transcript-only replay into a 500 on a misconfigured server.
    root = _drops_root(request)
    try:
        recording = resolve_drop_path(root, relative)
    except (DropPathError, OSError, ValueError):
        # A refused symlink, a path that escapes the root, and an absent file
        # are one answer on purpose: the client is never told where the drop
        # is, so it cannot be told which.
        raise Problem(404, "media-not-found", missing) from None
    return _stream_file(request, recording, missing)


_SCREENSHOT_PATH = "SELECT path FROM screenshot WHERE id = %s"


# Declared before `{path:path}` for the same reason the recordings route is:
# a greedy path parameter would otherwise swallow `files/<uuid>`.
@router.get(
    "/media/files/{media_id}",
    operation_id="getMediaFileById",
    response_class=Response,
    responses=_MEDIA_RESPONSES,
)
def get_media_file_by_id(media_id: UUID, request: Request) -> Response:
    """Stream one screenshot by its id (AD-17: media is ID-addressed).

    Every caller that shows a screenshot holds an id, not a path — the moments
    feed, the moment card and the thread timeline all serve `screenshotId` and
    nothing else. Until this route existed they built a URL against it anyway
    and every card rendered "no screenshot" while 3,107 screens sat on disk,
    because the only file route took a content-root-relative path the client
    was never given. Story 10.3's review filed the gap; this closes it.

    The path stays server-side, which is the point of addressing by id: a
    client that cannot name a path cannot walk the content root, and the
    stored layout stays free to change without breaking a client.
    """
    pool = request.app.state.pool
    with pool.connection() as conn:
        row = conn.execute(_SCREENSHOT_PATH, (media_id,)).fetchone()
    if row is None or row[0] is None:
        raise Problem(
            404,
            "not-found",
            f"no media file with id {media_id}",
        )
    target = _resolve_under_root(_content_root(request), row[0])
    return _stream_file(request, target, "the media file's bytes are missing")


# Declared after the recordings route on purpose — see the registration
# comment in api/main.py; `{path:path}` would otherwise swallow it.
@router.get(
    "/media/{path:path}",
    operation_id="getMediaFile",
    response_class=Response,
    responses=_MEDIA_RESPONSES,
)
def get_media_file(path: str, request: Request) -> Response:
    """Stream one content-root-relative file — a screenshot or a frame (AD-3)."""
    root = _content_root(request)
    target = _resolve_under_root(root, path)
    return _stream_file(request, target, "no media file at the requested path")
