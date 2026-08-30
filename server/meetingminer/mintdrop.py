"""``mint-drop``: turn a local recording or transcript into a source drop.

AD-1 names three sources — the Teams puller, a local recording, a future
YouTube — and every one of them enters the system as a source drop. This is the
producer for the second: it takes a file a human already has on disk, mints a
schema-valid drop under ``MM_DROPS_ROOT``, and hands the drop to the one intake
door. There is no second ingestion path and no way to POST a bare file; a drop
is still the only thing MeetingMiner consumes.

Run it from the repository::

    cd server && .venv/bin/python -m meetingminer.mintdrop \\
        ~/Downloads/standup.mp4 --corpus scripted --title "Daily Standup"

or through ``make mint-drop MINT_ARGS='...'``.

What it guarantees, and why each one is here:

* **The same door.** The assembled ``metadata.json`` is validated against
  ``docs/source-drop.schema.json`` — the same file intake validates against,
  resolved from the same loaded ``config.yaml`` — before anything is finalized.
  A drop is write-once, so a drop that would fail at intake must never reach
  the drops root: it could then be neither ingested nor deleted.
* **Atomic finalize.** The drop is assembled under ``<drops-root>/.staging/``
  and moved into place with one ``rename``, so a directory visible under the
  drops root is always a whole drop. Every failure path removes the staging
  directory.
* **Identity from content.** ``sourceId`` is ``sha256:<hex>`` of the primary
  evidence file, so re-running on the same file resolves to the same
  occurrence instead of minting a duplicate meeting. Re-run detection is by
  ``sourceId`` and not by directory name, because the name embeds a date and a
  title the user can change between runs.
* **An honest wall clock.** ``startedAt`` comes from ``--started-at`` or from
  the container's own ``creation_time``, never from the filesystem: an mtime is
  reset by copying and downloading. With neither, the command refuses rather
  than guessing — the pipeline never re-derives wall clock from media metadata
  (AD-1), so this is the only chance to get it right.

What it never does: copy anything back to the source, modify or transcode the
original, write inside an existing drop, or open a second ingestion path. The
drop's ``recording.mp4`` is a byte-identical copy of the file supplied.

This is a *producer*, the local-file counterpart of the puller's
``emit-drop.js``. It matches that tool's behaviour — the drop directory name,
staging-then-rename, the ``created``/``exists`` vocabulary, the intake status
mapping — and imports none of its code: the puller reads no ``.env`` and
imports no server code by design (AD-1's black box), and this command has to
know ``MM_DROPS_ROOT`` in this project's dialect. One duplicated
staging-and-finalize implementation is the price of that rule.
"""

from __future__ import annotations

import argparse
import fcntl
import getpass
import hashlib
import json
import os
import re
import shlex
import shutil
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from meetingminer.config import (
    CONFIG_PATH_ENV_VAR,
    ENV_PATH_ENV_VAR,
    AppConfig,
    ConfigError,
    load_config,
    validate_drops_root,
)
from meetingminer.domain.drops import (
    EVIDENCE_FILENAMES,
    METADATA_FILENAME,
    RECORDING_FILENAME,
    TRANSCRIPT_TEXT_FILENAME,
    TRANSCRIPT_VTT_FILENAME,
    DropError,
    read_drop,
    read_metadata,
    sha256_and_size,
)
from meetingminer.pipeline.media import (
    FFPROBE,
    MediaToolError,
    probe_creation_time,
    probe_media,
)

PROGRAM = "mint-drop"

#: Where a drop is assembled before it is one. Same name the puller uses, so a
#: single drops root has one staging area rather than two.
STAGING_DIRNAME = ".staging"

#: The intake door, when neither ``--api`` nor ``MM_API_URL`` says otherwise.
DEFAULT_API_URL = "http://127.0.0.1:8000"
API_URL_ENV_VAR = "MM_API_URL"

#: An api that accepts the connection and then never answers must not park the
#: command forever: the drop is already finalized by then, and the operator
#: needs the re-POST line rather than a hung terminal.
INTAKE_TIMEOUT_SECONDS = 30

#: Prefixed so a minted id can never be confused with the puller's Stream-URL
#: ids, which are absolute URLs.
SOURCE_ID_PREFIX = "sha256:"

#: The one 409 that is not a failure. Matched in full rather than by suffix:
#: `api/problems.py` builds every `type` as ``urn:meetingminer:problem:<slug>``
#: and puts a *generic* status title ("Conflict") in `title`, so the type is the
#: only field that identifies the problem and a suffix match would also accept
#: some other namespace's ``…:duplicate-source``.
DUPLICATE_SOURCE_PROBLEM_TYPE = "urn:meetingminer:problem:duplicate-source"

#: Schemes ``curl`` and :mod:`urllib` can both actually speak. A bare
#: ``127.0.0.1:8000`` is neither, and the re-POST line printed for a finalized
#: drop must be a command that works.
API_URL_SCHEMES = ("http://", "https://")

# A bounded wait is deliberately short enough to make a wedged producer
# actionable.  The lock is advisory and held across an ordinary copy, so
# waiting forever would turn one stuck process into an invisible outage for
# every later retry of that recording.
MINT_LOCK_TIMEOUT_SECONDS = 30
MINT_LOCK_SHARDS = 256

#: Supplied-file extension -> canonical drop filename. The extension decides
#: the *role*; ffprobe decides whether a file claiming to be a recording is
#: one. Mirrors the puller's EVIDENCE_MAP.
EXTENSION_TO_CANONICAL = {
    ".mp4": RECORDING_FILENAME,
    ".vtt": TRANSCRIPT_VTT_FILENAME,
    ".txt": TRANSCRIPT_TEXT_FILENAME,
}

#: Containers that carry no real creation time sometimes still carry a tag, set
#: to one of the two epoch origins (ISO base media format's 1904, Unix's 1970).
#: Both mean "the recorder did not know", and writing one into a write-once
#: drop as a meeting's wall clock is exactly the unrecoverable guess AD-1
#: forbids — so they are read as absent.
EPOCH_SENTINELS = frozenset({"1904-01-01T00:00:00", "1970-01-01T00:00:00"})


class MintError(RuntimeError):
    """A named refusal: the command declines and writes nothing."""


class IntakeError(RuntimeError):
    """The drop was finalized but the api did not accept it."""


# --- naming ----------------------------------------------------------------


def slugify(title: str) -> str:
    """The puller's slug rule, respelled (`emit-drop.js` ``slugify``).

    Matched deliberately: both producers write into one drops root, and a
    reader scanning that folder must not have to know which tool made a name.
    """
    text = unicodedata.normalize("NFKD", str(title or "")).lower()
    slug = re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:60].rstrip("-")
    return slug or "untitled"


def source_id_digest(source_id: str) -> str:
    """The 8 hex characters a drop directory name ends in."""
    return hashlib.sha1(source_id.encode("utf-8")).hexdigest()[:8]


def drop_name(started_at: str, title: str, source_id: str) -> str:
    """``<YYYY-MM-DD>-<title-slug>-<sha1(sourceId)[0:8]>`` (AD-1)."""
    return f"{started_at[:10]}-{slugify(title)}-{source_id_digest(source_id)}"


# --- wall clock ------------------------------------------------------------


def _iso_second_utc(moment: datetime) -> str:
    """``YYYY-MM-DDTHH:MM:SSZ`` — the schema's ``second`` precision spelling."""
    return moment.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_offset_timestamp(raw: str) -> datetime | None:
    """An ISO 8601 timestamp that names its own offset, or ``None``.

    A timestamp without an offset is refused rather than assumed local or UTC:
    the drop is write-once and a wall clock that is wrong by a timezone can
    never be corrected, which is the same reason the puller refuses to convert
    an un-suffixed Teams stamp.
    """
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def started_at_from_argument(raw: str) -> tuple[str, str]:
    """``--started-at`` -> ``(startedAt, startedAtPrecision)``.

    ``2026-08-05`` is a date the user knows and a time of day they do not, which
    is precisely what the schema's ``day`` precision means: midnight UTC, and
    the pipeline reads the time part as unknown rather than as 00:00.
    """
    value = raw.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        try:
            day = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError as exc:
            raise MintError(f"--started-at is not a real calendar date: {raw!r}") from exc
        return _iso_second_utc(day), "day"
    parsed = _parse_offset_timestamp(value)
    if parsed is None:
        raise MintError(
            f"--started-at is not a usable timestamp: {raw!r} — give a date"
            " (2026-08-05, recorded as day precision) or a timestamp that names"
            " its offset (2026-08-05T12:00:19Z, 2026-08-05T08:00:19-04:00). A"
            " timestamp without an offset is ambiguous, and a drop is write-once"
        )
    return _iso_second_utc(parsed), "second"


def started_at_from_container(raw: str) -> tuple[str, str] | None:
    """The container's ``creation_time`` as a drop wall clock, or ``None``.

    ``None`` for anything that is not an unambiguous instant — no offset, an
    epoch sentinel, unparseable — so the caller refuses and asks for
    ``--started-at`` instead of writing a guess into a write-once drop.
    """
    parsed = _parse_offset_timestamp(raw.strip())
    if parsed is None:
        return None
    if parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") in EPOCH_SENTINELS:
        return None
    return _iso_second_utc(parsed), "second"


# --- what the user supplied ------------------------------------------------


@dataclass(frozen=True)
class SuppliedFile:
    """One file the user supplied, and the drop filename it becomes."""

    source: Path
    canonical: str
    sha256: str
    byte_size: int


def classify_supplied(paths: list[str]) -> list[tuple[Path, str]]:
    """Supplied paths -> ``(absolute source, canonical drop filename)`` pairs.

    Ordered by :data:`EVIDENCE_FILENAMES`, so "the primary evidence file" is
    the first element for every caller and the identity a mint produces does
    not depend on argument order.
    """
    if not paths:
        raise MintError(
            "nothing ingestible was supplied — pass a recording and/or a"
            f" transcript ({', '.join(sorted(EXTENSION_TO_CANONICAL))})"
        )
    by_canonical: dict[str, Path] = {}
    for raw in paths:
        path = Path(raw).expanduser()
        canonical = EXTENSION_TO_CANONICAL.get(path.suffix.lower())
        if canonical is None:
            raise MintError(
                f"{path} has no canonical drop filename — a drop holds"
                f" {', '.join(EVIDENCE_FILENAMES)}, so a supplied file must be"
                f" one of {', '.join(sorted(EXTENSION_TO_CANONICAL))}"
            )
        if canonical in by_canonical:
            raise MintError(
                f"two files map to {canonical}: {by_canonical[canonical]} and"
                f" {path} — a drop holds one of each"
            )
        resolved = path.resolve()
        if not resolved.is_file():
            raise MintError(
                f"not a readable file: {path}"
                + ("" if resolved.exists() else " (it does not exist)")
            )
        by_canonical[canonical] = resolved
    return [
        (by_canonical[name], name) for name in EVIDENCE_FILENAMES if name in by_canonical
    ]


def _digest_supplied(pairs: list[tuple[Path, str]]) -> list[SuppliedFile]:
    """Read every supplied file once, before anything is written.

    Doubles as the readability gate: a permissions error or a vanished file
    surfaces here, at the point where nothing has been staged yet.
    """
    files: list[SuppliedFile] = []
    for source, canonical in pairs:
        try:
            digest, size = sha256_and_size(source)
        except OSError as exc:
            raise MintError(f"{source} could not be read: {exc}") from exc
        if size == 0:
            raise MintError(f"{source} is empty — an empty file is not evidence")
        files.append(
            SuppliedFile(source=source, canonical=canonical, sha256=digest, byte_size=size)
        )
    return files


def _assert_is_a_video(path: Path) -> None:
    """Refuse a non-video at probe rather than letting intake meet it.

    A renamed ``.docx`` and an audio-only file both reach the drops root
    otherwise, and a finalized drop can never be deleted or rewritten.
    """
    if shutil.which(FFPROBE) is None:
        # Checked before the probe so the refusal names the real problem: a
        # missing tool reported as "your file is not a video" sends the operator
        # looking at a recording that is perfectly fine.
        raise MintError(
            f"{FFPROBE} is not on PATH — minting from a video needs it to check"
            " the file and to read its creation_time. Install it with"
            " 'brew install ffmpeg' (`make bootstrap` checks for it; minting"
            " does not depend on the rest of the stack)"
        )
    try:
        facts = probe_media(path)
    except MediaToolError as exc:
        raise MintError(f"{path} is not a readable video: {exc}") from exc
    if not facts.has_video:
        raise MintError(
            f"{path} carries no video stream (container"
            f" {facts.container or 'unknown'}) — {RECORDING_FILENAME} must be a video"
        )


# --- the drops root --------------------------------------------------------


def _load_cli_config() -> AppConfig:
    """Use repository defaults while retaining explicit environment overrides.

    The same resolution ``backfill`` uses, so both operator commands read one
    ``config.yaml`` and one ``.env``.
    """
    if os.environ.get(CONFIG_PATH_ENV_VAR):
        return load_config()
    root_config = Path(__file__).resolve().parents[2] / "config.yaml"
    env_path = os.environ.get(ENV_PATH_ENV_VAR) or root_config.with_name(".env")
    return load_config(root_config, env_path)


def resolve_drops_root(explicit: str | None, config: AppConfig) -> Path:
    """The root this mint writes under, checked for being usable *and* writable.

    :func:`~meetingminer.config.validate_drops_root` deliberately never
    write-probes — the server only ever reads drops (AD-13) — but this command
    is one of the two writers `storage-layout.md` §1 names, so it makes that
    decision itself instead of discovering an unwritable root half way through
    a multi-gigabyte copy.
    """
    if explicit is not None:
        try:
            root = validate_drops_root(Path(explicit).expanduser().resolve())
        except ConfigError as exc:
            # The check speaks in MM_DROPS_ROOT because that is the value it
            # normally guards; say which root was actually asked for.
            raise MintError(f"--drops is not a usable drops root: {exc}") from exc
        configured = config.secrets.mm_drops_root
        if configured is None:
            raise MintError(
                "MM_DROPS_ROOT is not set — mint-drop can only write where"
                " intake can resolve permanent drops"
            )
        # The API stores a drops-root-relative path, so an explicit root may
        # be the configured root itself or one of its descendants — never a
        # sibling or an unrelated scratch directory.  Refuse before creating
        # `.staging`: an external drop would be immutable but unusable.
        try:
            relative = root.relative_to(configured.resolve())
        except ValueError as exc:
            raise MintError(
                f"--drops must be MM_DROPS_ROOT or a directory below it: {root}"
                f" is outside configured MM_DROPS_ROOT ({configured})"
            ) from exc
        if STAGING_DIRNAME in relative.parts:
            raise MintError(
                f"--drops must not point inside {STAGING_DIRNAME}: {root} is a"
                " transient assembly area, not an intake-visible drops root"
            )
    else:
        root = validate_drops_root(config.secrets.mm_drops_root)
    staging_root = root / STAGING_DIRNAME
    existed = staging_root.is_dir()
    try:
        staging_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise MintError(
            f"drops root is not writable: {root}: {exc} — minting creates a new"
            " drop directory there"
        ) from exc
    if not existed:
        # Leave nothing behind if the mint refuses for some later reason; the
        # assembly step recreates it.
        with suppress(OSError):
            staging_root.rmdir()
    return root


def find_existing_drop(drops_root: Path, source_id: str) -> Path | None:
    """The finalized drop already minted for this content, if there is one.

    Found by ``sourceId`` rather than by directory name: the name embeds the
    date and the title slug, both of which the user can change between runs,
    and only the trailing digest is fixed. Without this,
    ``mint-drop video.mp4 --title A`` followed by ``--title B`` finalizes a
    second write-once drop for the same content that intake then refuses with
    409 — a drop that can never be ingested and can never be deleted.
    """
    digest = source_id_digest(source_id)
    unreadable: list[Path] = []
    def _walk_error(exc: OSError) -> None:
        raise MintError(f"drops root could not be listed: {drops_root}: {exc}") from exc

    # Search the configured root, not merely the caller-selected child: valid
    # nested roots share one intake namespace and therefore one source-id
    # namespace.  Hidden plumbing is never a permanent drop.
    candidates: list[Path] = []
    try:
        for directory, directories, _files in os.walk(drops_root, onerror=_walk_error):
            directories[:] = [name for name in directories if not name.startswith(".")]
            candidates.extend(Path(directory) / name for name in directories)
    except OSError as exc:
        raise MintError(f"drops root could not be listed: {drops_root}: {exc}") from exc
    for candidate in sorted(candidates, key=lambda candidate: str(candidate)):
        if candidate.name.startswith(".") or not candidate.name.endswith(f"-{digest}"):
            continue
        if not candidate.is_dir():
            continue
        try:
            metadata = read_metadata(candidate)
        except DropError:
            unreadable.append(candidate)
            continue
        if metadata.get("sourceId") == source_id:
            return candidate
    if unreadable:
        # "Cannot tell" must not read as "not there": minting anyway would put a
        # second write-once drop for this content in the root.
        raise MintError(
            f"a drop directory carrying this content's digest exists but its"
            f" {METADATA_FILENAME} could not be read: {unreadable[0]} — inspect it"
            " before minting again"
        )
    return None


@contextmanager
def _source_id_lock(identity_root: Path, source_id: str):
    """Serialize find/finalize for one content-derived source identity.

    The target directory also includes caller-controlled title and start time,
    so checking individual target names cannot prevent two concurrent callers
    from minting the same bytes under different names.  A per-root, per-source
    advisory file lock closes that interval across processes.
    """
    identity = hashlib.sha256(source_id.encode("utf-8")).digest()[0] % MINT_LOCK_SHARDS
    lock_dir = identity_root / ".mint-locks"
    try:
        lock_dir.mkdir(parents=True, exist_ok=True)
        # A fixed shard set prevents an unbounded temp-file leak while keeping
        # unrelated recordings concurrent in the common case.  It lives in the
        # configured shared root, rather than process-local /tmp, so separate
        # CLI processes and container mount namespaces contend on one inode.
        lock_file = (lock_dir / f"{identity:02x}.lock").open("a+", encoding="utf-8")
    except OSError as exc:
        raise MintError(f"could not acquire source identity lock for {source_id}: {exc}") from exc
    try:
        deadline = time.monotonic() + MINT_LOCK_TIMEOUT_SECONDS
        while True:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise MintError(
                        "timed out waiting for another mint of source identity"
                        f" {source_id}; retry after that producer finishes"
                    )
                time.sleep(0.05)
        yield
    except OSError as exc:
        raise MintError(f"could not lock source identity {source_id}: {exc}") from exc
    finally:
        with suppress(OSError):
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()


# --- minting ---------------------------------------------------------------


@dataclass(frozen=True)
class MintResult:
    """What one run did: ``created`` or ``exists``, and where."""

    status: str
    path: Path
    source_id: str
    metadata: dict[str, Any]
    #: Canonical filenames this run supplied that the reported drop does not
    #: hold. Only ever non-empty for ``exists``, and only ever *reported*:
    #: adding evidence to an occurrence is augmentation, which is intake's
    #: decision and a separate drop (AD-14), never a write into a finalized one
    #: (AD-13). Silence here would let a re-run that adds a transcript look
    #: exactly like one that adds nothing.
    ignored: tuple[str, ...] = ()


def _evidence_not_in(drop: Path, files: list[SuppliedFile]) -> tuple[str, ...]:
    """Which of the supplied files the existing drop does not already hold."""
    return tuple(f.canonical for f in files if not (drop / f.canonical).is_file())


def build_metadata(
    *,
    source_id: str,
    corpus: str,
    started_at: str,
    started_at_precision: str,
    started_at_source: str,
    title: str,
    supplied_by: str,
    files: list[SuppliedFile],
    minted_at: datetime,
    provenance_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The drop's ``metadata.json``.

    ``provenance`` is the only record of where these bytes came from — the
    original is neither copied back nor modified — so it carries the source
    path, size and checksum of every file, the wall clock this ran at, who
    supplied it, and which of the two sources ``startedAt`` came from.

    No ``url`` key: ``DropContents.stream_url`` turns ``provenance.url`` into
    UX-DR11's transitional "watch the original recap" deep link, and a local
    file has no such page. ``title`` *is* set — ``DropContents.title`` reads it
    as the meeting's human label. A producer whose source *does* have such a
    page merges it in through ``provenance_extra``, applied after the defaults
    so it may also deliberately override ``tool`` (story 6.2).

    No ``participants`` key either. Omitted and ``[]`` are different statements
    (glossary): omitted means the source did not look, and the pipeline falls
    back to transcript speaker attribution, which is the truth here.
    """
    provenance: dict[str, Any] = {
        "tool": PROGRAM,
        "title": title,
        "mintedAt": _iso_second_utc(minted_at),
        "suppliedBy": supplied_by,
        "startedAtSource": started_at_source,
        "files": [
            {
                "dropFilename": f.canonical,
                "sourcePath": str(f.source),
                "sha256": f.sha256,
                "byteSize": f.byte_size,
            }
            for f in files
        ],
    }
    if provenance_extra:
        provenance.update(provenance_extra)
    return {
        "schemaVersion": 1,
        "sourceId": source_id,
        "corpus": corpus,
        "startedAt": started_at,
        "startedAtPrecision": started_at_precision,
        "provenance": provenance,
    }


def _copy_verified(supplied: SuppliedFile, destination: Path) -> None:
    """Copy one file into staging and prove the copy is byte-identical.

    The checksum is re-read rather than assumed: a short copy (a full disk, a
    file still being written) otherwise finalizes a drop whose recording does
    not match the ``sha256`` its own provenance records, and the drop is
    write-once by then.
    """
    try:
        shutil.copyfile(supplied.source, destination)
    except OSError as exc:
        raise MintError(f"{supplied.source} could not be copied: {exc}") from exc
    digest, size = sha256_and_size(destination)
    if (digest, size) != (supplied.sha256, supplied.byte_size):
        raise MintError(
            f"the copy of {supplied.source} does not match the original"
            f" ({size} bytes/{digest} against {supplied.byte_size}/{supplied.sha256})"
            " — the source changed while it was read, or the copy was truncated"
        )


def mint(
    *,
    supplied: list[str],
    corpus: str,
    drops_root: Path,
    config_path: Path,
    title: str | None = None,
    started_at_argument: str | None = None,
    supplied_by: str | None = None,
    identity_root: Path | None = None,
    source_id: str | None = None,
    started_at_override: tuple[str, str, str] | None = None,
    provenance_extra: dict[str, Any] | None = None,
) -> MintResult:
    """Mint one drop, or report the one already minted for this content.

    In order: refuse when nothing ingestible was supplied, probe the video,
    digest every file, mint the id, look for an existing drop, resolve the wall
    clock, then assemble-validate-finalize. Nothing is written to the drops root
    before the last step, and that step either finalizes a whole drop or leaves
    the root untouched.

    The keyword overrides default to today's behaviour bit-for-bit. A producer
    with a source-side identity passes ``source_id`` verbatim (used for the
    identity lock, the existing-drop lookup, and ``metadata.sourceId``), an
    already-resolved wall clock as ``started_at_override``
    (``(startedAt, precision, source)``), and its own provenance keys as
    ``provenance_extra`` — assembly still goes through this one
    staging → validate → atomic-rename path (story 6.2).
    """
    pairs = classify_supplied(supplied)
    recording = next((p for p, name in pairs if name == RECORDING_FILENAME), None)
    if recording is not None:
        _assert_is_a_video(recording)
    files = _digest_supplied(pairs)

    primary = files[0]
    if source_id is None:
        source_id = f"{SOURCE_ID_PREFIX}{primary.sha256}"
    label = (title or primary.source.stem).strip() or primary.source.stem

    # Before the wall clock, not after: identity comes from the bytes, so a
    # re-run must reach `exists` for every input shape. Resolving startedAt
    # first made a transcript-only re-run refuse with "carries no timestamp
    # metadata" — the tool declining to recognise the drop it had just made,
    # because the *new* drop it was not going to write had no start time.
    scope = (identity_root or drops_root).resolve()
    with _source_id_lock(scope, source_id):
        # This re-check belongs inside the identity lock and is retained until
        # the staged directory is atomically finalized.
        existing = find_existing_drop(scope, source_id)
        if existing is not None:
            return MintResult(
                status="exists",
                path=existing,
                source_id=source_id,
                metadata=read_metadata(existing),
                ignored=_evidence_not_in(existing, files),
            )

        if started_at_override is not None:
            started_at, precision, started_at_source = started_at_override
        elif started_at_argument is not None:
            started_at, precision = started_at_from_argument(started_at_argument)
            started_at_source = "--started-at"
        else:
            started_at, precision, started_at_source = _started_at_from_media(recording)

        metadata = build_metadata(
            source_id=source_id,
            corpus=corpus,
            started_at=started_at,
            started_at_precision=precision,
            started_at_source=started_at_source,
            title=label,
            supplied_by=supplied_by or _default_supplied_by(),
            files=files,
            minted_at=datetime.now(timezone.utc),
            provenance_extra=provenance_extra,
        )
        name = drop_name(started_at, label, source_id)
        target = drops_root / name
        return _assemble(
            drops_root=drops_root,
            target=target,
            metadata=metadata,
            files=files,
            config_path=config_path,
            source_id=source_id,
        )


def _started_at_from_media(recording: Path | None) -> tuple[str, str, str]:
    """The container's wall clock, or a refusal — never the filesystem's.

    An mtime is reset by copying and downloading, so deriving a meeting's start
    from it is a guess that a write-once drop makes permanent.
    ``format.tags.creation_time`` is written by the recorder and is the only
    honest fallback there is.
    """
    reason = (
        "no --started-at was given and none can be derived: a meeting's wall"
        " clock is never taken from the file's mtime (copying and downloading"
        " reset it), so pass --started-at 2026-08-05T12:00:19Z, or"
        " --started-at 2026-08-05 for day precision"
    )
    if recording is None:
        raise MintError(f"{reason} — a transcript carries no timestamp metadata")
    try:
        raw = probe_creation_time(recording)
    except MediaToolError as exc:  # pragma: no cover - probe_media already ran
        raise MintError(f"{recording} could not be probed: {exc}") from exc
    if raw is None:
        raise MintError(f"{reason} — the container carries no creation_time")
    resolved = started_at_from_container(raw)
    if resolved is None:
        raise MintError(
            f"{reason} — the container's creation_time is not a usable instant"
            f" ({raw!r})"
        )
    started_at, precision = resolved
    return started_at, precision, "container creation_time"


def _default_supplied_by() -> str:
    try:
        return getpass.getuser()
    except (KeyError, OSError):  # pragma: no cover - no passwd entry
        return os.environ.get("USER") or "unknown"


def _existing_target(target: Path, source_id: str) -> MintResult:
    """Report a drop that appeared at the target path, or refuse to guess.

    Anything that is not a readable drop directory is a refusal rather than an
    ``exists``: reporting a plain file or a half-written directory as the drop
    for this content would retire the content silently — never minted, never
    POSTed, never mentioned again.
    """
    if not target.is_dir():
        raise MintError(f"drop target exists but is not a directory: {target}")
    try:
        metadata = read_metadata(target)
    except DropError as exc:
        raise MintError(
            f"a directory already stands at {target} but its"
            f" {METADATA_FILENAME} could not be read: {exc} — inspect it before"
            " minting again"
        ) from exc
    if metadata.get("sourceId") != source_id:
        raise MintError(
            f"a directory already stands at {target} for a different sourceId"
            " — inspect it before minting again"
        )
    return MintResult(
        status="exists", path=target, source_id=source_id, metadata=metadata
    )


def _assemble(
    *,
    drops_root: Path,
    target: Path,
    metadata: dict[str, Any],
    files: list[SuppliedFile],
    config_path: Path,
    source_id: str,
) -> MintResult:
    """Build the drop in staging, validate it, and finalize with one rename.

    The validation is not decoration: a drop is write-once, so one that intake
    would answer 422 to could afterwards be neither ingested nor deleted. It
    runs against ``docs/source-drop.schema.json`` resolved from the loaded
    ``config.yaml``, which is how the api resolves it, so both sides validate
    against one file.
    """
    staging_root = drops_root / STAGING_DIRNAME
    staging = staging_root / f"{target.name}.{os.getpid()}.{uuid4().hex[:8]}"
    finalized = False
    try:
        try:
            staging.mkdir(parents=True)
            # ensure_ascii=False: the puller's JSON.stringify writes raw UTF-8
            # into this same drops root, and a title escaped to \\u00e9 in one
            # producer's drop and left as é in the other's is two spellings of
            # one meeting label.
            (staging / METADATA_FILENAME).write_text(
                json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            raise MintError(f"the drop could not be assembled in {staging}: {exc}") from exc
        for supplied in files:
            _copy_verified(supplied, staging / supplied.canonical)
        if any(supplied.canonical == RECORDING_FILENAME for supplied in files):
            # The initial probe establishes the caller's input role.  This
            # second probe establishes that the exact bytes about to become
            # immutable evidence still are video.
            _assert_is_a_video(staging / RECORDING_FILENAME)
        try:
            read_drop(staging, config_path=config_path)
        except DropError as exc:
            raise MintError(
                f"the assembled drop does not match the source-drop contract:"
                f" {exc} — nothing was written to {drops_root}"
            ) from exc
        # POSIX ``rename`` replaces an existing *empty* directory without
        # complaint, so "a finalized drop is never overwritten" cannot be left
        # to the syscall failing. It refuses a non-empty one, which is the only
        # case the except branch below still has to cover.
        if os.path.lexists(target):
            return _existing_target(target, source_id)
        try:
            os.rename(staging, target)
            finalized = True
        except OSError as exc:
            # Another mint finalized this same drop between the check above and
            # this rename. A finalized drop is never overwritten, so that is the
            # `exists` outcome rather than an error.
            if target.is_dir():
                return _existing_target(target, source_id)
            raise MintError(f"the drop could not be finalized at {target}: {exc}") from exc
    finally:
        if not finalized:
            shutil.rmtree(staging, ignore_errors=True)
        # Removes the staging area once the last concurrent mint is done, and
        # fails harmlessly while another one is still assembling.
        with suppress(OSError):
            staging_root.rmdir()
    return MintResult(status="created", path=target, source_id=source_id, metadata=metadata)


# --- intake ----------------------------------------------------------------


def resolve_api_url(explicit: str | None) -> str:
    """The intake base url, refused unless it is one a client can call.

    Resolved (and therefore validated) *before* anything is minted: a schemeless
    ``127.0.0.1:8000`` reaches no api, and the re-POST command printed beside
    the finalized drop would be an unusable line the operator has to repair by
    hand.
    """
    raw = explicit or os.environ.get(API_URL_ENV_VAR) or DEFAULT_API_URL
    try:
        parsed = urlsplit(raw)
    except ValueError as exc:
        raise MintError(
            "the api base url must be an HTTP(S) URL with a host and no query"
            f" or fragment: {raw!r}"
        ) from exc
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or "?" in raw
        or "#" in raw
    ):
        raise MintError(
            "the api base url must be an HTTP(S) URL with a host and no query"
            f" or fragment: {raw!r} — pass --api http://127.0.0.1:8000 or set"
            f" {API_URL_ENV_VAR}"
        )
    try:
        # Accessing port validates values such as ``:not-a-port`` before a
        # permanent drop exists.
        parsed.port
    except ValueError as exc:
        raise MintError(f"the api base url has an invalid port: {raw!r}") from exc
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def ingest_url(api_url: str) -> str:
    """The single `/ingests` target shared by curl output and urllib."""
    return f"{api_url}/ingests"


def ingest_command(api_url: str, drop_path: Path) -> str:
    """The exact request that ingests this drop, ready to paste.

    Printed under ``--no-post`` and after a failed POST: the drop is finalized
    either way, and the operator needs the request for *this* drop. Re-running
    the command works too — an ``exists`` run still POSTs, which is exactly what
    a failed hand-off needs — but only if the same file is still on disk at the
    same path, and this line needs nothing but the drop.
    """
    body = json.dumps({"dropPath": str(drop_path)})
    return (
        f"curl -sS -X POST {shlex.quote(ingest_url(api_url))}"
        f" -H 'content-type: application/json'"
        f" -d {shlex.quote(body)}"
    )


def _json_body(raw: bytes) -> dict[str, Any]:
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def post_ingest(api_url: str, drop_path: Path, *, timeout: float = INTAKE_TIMEOUT_SECONDS) -> tuple[str, int, str | None]:
    """POST /ingests — the one intake door (AD-14).

    Returns ``(status, http status, jobId)`` with the puller's vocabulary:
    201 ``created``, 200 ``requeued``, 409 ``duplicate-source`` ``duplicate``.
    Anything else raises :class:`IntakeError`.
    """
    url = ingest_url(api_url)
    request = urllib.request.Request(
        url,
        data=json.dumps({"dropPath": str(drop_path)}).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status, body = response.status, _json_body(response.read())
    except urllib.error.HTTPError as exc:
        status, body = exc.code, _json_body(exc.read())
    except (urllib.error.URLError, OSError) as exc:
        raise IntakeError(f"POST {url} failed (is the api running?): {exc}") from exc
    job_id = body.get("jobId")
    job_id = str(job_id) if job_id is not None else None
    if status == 201:
        return "created", status, job_id
    if status == 200:
        return "requeued", status, job_id
    if status == 409 and body.get("type") == DUPLICATE_SOURCE_PROBLEM_TYPE:
        return "duplicate", status, job_id
    detail = body.get("detail") or body.get("title") or f"HTTP {status}"
    raise IntakeError(f"POST {url} rejected the drop ({status}): {detail}")


# --- CLI -------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description=(
            "Mint a MeetingMiner source drop from a local recording and/or"
            " transcript, then hand it to POST /ingests."
        ),
        epilog=(
            "example: "
            f"{PROGRAM} ~/Downloads/standup.mp4 --corpus scripted"
            ' --title "Daily Standup" --started-at 2026-08-05T12:00:19Z'
        ),
    )
    parser.add_argument(
        "files",
        nargs="*",
        metavar="FILE",
        help=(
            "the recording and/or transcript to mint from: .mp4 -> recording.mp4,"
            " .vtt -> transcript.vtt, .txt -> transcript.txt. A transcript-only"
            " drop is first-class (AD-1)."
        ),
    )
    parser.add_argument(
        "--corpus",
        choices=("scripted", "real"),
        required=True,
        help=(
            "eval-relevant tag carried onto the meeting row. Required and never"
            " defaulted: scripted meetings are eval subjects, real ones are demo"
            " corpus only, and the drop is write-once."
        ),
    )
    parser.add_argument(
        "--title",
        help="the meeting's human label (default: the primary file's name).",
    )
    parser.add_argument(
        "--started-at",
        dest="started_at",
        metavar="WHEN",
        help=(
            "meeting start: 2026-08-05T12:00:19Z (second precision) or"
            " 2026-08-05 (day precision). Without it the recording's own"
            " container creation_time is used, and the command refuses if there"
            " is none — a wall clock is never taken from the file's mtime."
        ),
    )
    parser.add_argument(
        "--supplied-by",
        dest="supplied_by",
        help="who supplied the file, recorded in provenance (default: $USER).",
    )
    parser.add_argument(
        "--drops",
        metavar="DIR",
        help="the drops root to mint into (default: MM_DROPS_ROOT from .env).",
    )
    parser.add_argument(
        "--api",
        metavar="URL",
        help=f"api base url (default: ${API_URL_ENV_VAR}, else {DEFAULT_API_URL}).",
    )
    parser.add_argument(
        "--no-post",
        dest="no_post",
        action="store_true",
        help="mint the drop but do not POST it; print the request instead.",
    )
    return parser


def _report(result: MintResult, files: list[str]) -> None:
    metadata = result.metadata
    print(f"{result.status:<8} {result.path}")
    print(f"           sourceId  {result.source_id}")
    print(
        f"           startedAt {metadata.get('startedAt')}"
        f" ({metadata.get('startedAtPrecision')}), corpus {metadata.get('corpus')}"
    )
    if result.status == "exists":
        # The name embeds a date and a title slug that this run may have
        # spelled differently; say what decided, so "why is my --title ignored"
        # is answered here rather than in the drops folder.
        print(
            "           this content was already minted; the sourceId matched,"
            " so nothing was written"
        )
        if result.ignored:
            # Evidence this run brought that the existing drop has not got.
            # Adding it is augmentation — a *new* drop declaring `augments`,
            # which intake decides on (AD-14) — never a write into a finalized
            # drop (AD-13). All this command may do is refuse to be silent.
            print(
                f"           ignored   {', '.join(result.ignored)} — the drop"
                " above does not hold this evidence, and a finalized drop is"
                " never written into. Bringing it in is an augmenting drop,"
                " which this command does not emit."
            )
    else:
        print(f"           files     {METADATA_FILENAME}, {', '.join(files)}")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    try:
        config = _load_cli_config()
    except ConfigError as exc:
        print(f"fatal: {PROGRAM} aborted: {exc}", file=sys.stderr)
        return 1

    try:
        # Before the mint, not after: a drop is write-once, so an unusable api
        # url must not first cost a finalized drop and then print a re-POST
        # line that cannot be run.
        api_url = resolve_api_url(args.api)
        drops_root = resolve_drops_root(args.drops, config)
        result = mint(
            supplied=args.files,
            corpus=args.corpus,
            drops_root=drops_root,
            config_path=config.config_path,
            title=args.title,
            started_at_argument=args.started_at,
            supplied_by=args.supplied_by,
            # An explicit child root is a placement choice, not a separate
            # intake namespace: all of MM_DROPS_ROOT shares source identity.
            identity_root=config.secrets.mm_drops_root,
        )
    except (ConfigError, MintError) as exc:
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
    # A drop already in the system is not a tool failure: the job exists, the
    # meeting exists, and re-running after a dropped connection must be able to
    # end here without a red exit code.
    label = "already ingested" if status == "duplicate" else status
    print(f"           intake {label} ({http_status}) jobId {job_id or '(none)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
