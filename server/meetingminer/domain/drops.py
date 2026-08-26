"""Source-drop vocabulary shared by api and worker (AD-1).

One definition of the canonical drop filenames, one reader for a drop's
contents, and one pair of functions converting between an absolute drop path
and the drops-root-relative path the database stores. It lives in ``domain``
because both sides need it and neither may import the other: the api never
imports ``pipeline``, and the worker never imports ``api``.

The drop directory is read-only (AD-13). Nothing in this module writes to,
renames, or deletes anything inside a drop — it only reads ``metadata.json``
and reports which canonical evidence files are present.

**The drops root (story 2.1a, `storage-layout.md` §4).** Every stored drop
path is relative to ``MM_DROPS_ROOT`` and never absolute, so relocating the
drops volume is an environment change rather than a data migration. The two
directions live here together — :func:`drop_relative_path` on the way in,
:func:`resolve_drop_path` on the way out — because a relativizer and a
resolver that disagree about symlinks or containment fail silently, serving
one meeting's bytes for another's id.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import jsonschema

# Canonical drop filenames (AD-1); every other file in the drop is ignored.
METADATA_FILENAME = "metadata.json"
RECORDING_FILENAME = "recording.mp4"
TRANSCRIPT_VTT_FILENAME = "transcript.vtt"
TRANSCRIPT_TEXT_FILENAME = "transcript.txt"

# The two extraction documents a drop may carry (story 4.1a): the puller's
# summariser writes them beside the transcript, and the `extract` stage adopts
# them instead of re-deriving what a model already produced.
EXTRACTION_SUMMARY_FILENAME = "extraction-summary.md"
EXTRACTION_ACTIONS_FILENAME = "extraction-action-items.md"

# `metadata.extractions` key -> the canonical filename it declares. The drop
# schema pins each key's value to exactly this filename, so the declaration and
# the file it names cannot disagree about *which* file is meant — only about
# whether it is there, which is what the `extract` stage cross-checks.
EXTRACTION_DECLARATION_KEYS: dict[str, str] = {
    "archSummary": EXTRACTION_SUMMARY_FILENAME,
    "actionItems": EXTRACTION_ACTIONS_FILENAME,
}
EXTRACTIONS_METADATA_KEY = "extractions"

# At least one of these must be present for a drop to be ingestible; the api
# enforces that at intake. Order is the schema's, not a precedence.
#
# The extraction documents are deliberately NOT here: they are derivative of a
# transcript, so a drop carrying only them has no evidence to ingest and must
# still be refused.
EVIDENCE_FILENAMES = (
    RECORDING_FILENAME,
    TRANSCRIPT_VTT_FILENAME,
    TRANSCRIPT_TEXT_FILENAME,
)

# Everything a conforming drop may hold. `metadata.json` is in the list
# because a symlinked one is the same escape as a symlinked recording: the
# bytes a checksum or a participant comparison describes must live in the
# write-once drop, not behind a link that can be repointed afterwards. The
# extraction documents are in it for exactly that reason too — `extract`
# records each adopted document's sha256, and a link whose target can change
# afterwards would make that checksum describe bytes nobody read.
CANONICAL_FILENAMES = (METADATA_FILENAME,) + EVIDENCE_FILENAMES + (
    EXTRACTION_SUMMARY_FILENAME,
    EXTRACTION_ACTIONS_FILENAME,
)


class DropError(RuntimeError):
    """Raised when a drop directory cannot be read as a source drop.

    Intake (story 1.2) validates the drop against the JSON Schema before a job
    row exists, so the worker meeting this error means the drop changed or
    vanished between intake and the claim.
    """


class DropPathError(DropError):
    """A drop path is not a usable path under the configured drops root.

    A subclass of :class:`DropError` so every existing caller that already
    treats an unreadable drop as a job failure treats an uncontainable one the
    same way, and the two can still be told apart where that matters (intake
    answers 400 for this and 422 for a malformed drop).
    """


class SymlinkedEvidenceError(DropPathError):
    """A drop directory, or a canonical file inside one, is a symbolic link.

    Refused rather than followed: a drop is write-once (AD-1/AD-13), and a
    link can be repointed at other bytes after the checksum that describes it
    was recorded. A *hard* link is not a symlink and stays permitted — it is
    the same inode, so the bytes cannot change out from under the row.
    """


# --- the drops root: absolute in, relative stored, resolved at use time -----


def _contained_parts(root: Path, relative: str) -> tuple[str, ...]:
    """The POSIX components of ``relative``, or raise :class:`DropPathError`.

    Refuses the spellings that make containment a lie before any filesystem
    call happens: an embedded NUL (every later path call would raise), an
    absolute path, and non-canonical segments.  The database has the same
    rules, but legacy rows predate its ``NOT VALID`` transcript constraint, so
    reads must not normalize a malformed stored spelling into accepted evidence.
    """
    if "\x00" in relative:
        raise DropPathError("a stored drop path may not contain a NUL byte")
    if not relative or relative in (".", "./"):
        raise DropPathError("a stored drop path may not be empty")
    if relative.startswith("/"):
        raise DropPathError(
            f"a stored drop path must be relative to the drops root, not absolute:"
            f" {relative!r}"
        )
    # Do not use ``PurePosixPath.parts`` here: it deliberately normalizes
    # ``./drop`` and ``drop//file`` before this guard can reject them.
    parts = tuple(relative.split("/"))
    if any(part in (".", "..") for part in parts):
        raise DropPathError(
            f"a stored drop path may not contain '.' or '..' components:"
            f" {relative!r} (root {root})"
        )
    if any(not part for part in parts):
        raise DropPathError(
            f"a stored drop path may not use duplicate or trailing separators:"
            f" {relative!r} (root {root})"
        )
    return parts


def resolve_drop_path(drops_root: Path, relative: str) -> Path:
    """Resolve a stored drops-root-relative path, or raise :class:`DropPathError`.

    The read side of the anchor rule, and the only way a stored path becomes a
    filesystem path. It mirrors ``pipeline/outputs.py:assert_private_meeting_subdir``:
    reject the hostile spellings, reject a symlink at *any* component below the
    root, then resolve and require containment.

    Components *above* the root are deliberately not walked: the root itself is
    resolved by the config loader, and on macOS the temporary and home trees
    legitimately sit behind links (``/var`` is one), so walking upwards would
    refuse ordinary drops.

    Existence is not checked here. "Where is this drop" and "is it still there"
    are separate questions with separate answers — a missing drop is a job
    failure or a 404, not a containment breach.
    """
    root = drops_root.resolve()
    target = root
    for part in _contained_parts(drops_root, relative):
        target = target / part
        if target.is_symlink():
            raise SymlinkedEvidenceError(
                f"refusing a symlinked component of a drop path: {relative!r}"
            )
    if not target.resolve().is_relative_to(root):
        raise DropPathError(
            f"drop path {relative!r} resolves outside the drops root {root}"
        )
    return target


def drop_relative_path(drops_root: Path, absolute: Path) -> str:
    """The path to store for a drop directory given as an absolute path.

    The write side of the anchor rule: intake accepts an absolute ``dropPath``
    on the wire (the puller is untouched) and this is the single place that
    absolute path becomes the relative one the database keeps.

    ``resolve()`` first, because the poster's spelling and the configured root
    may differ by a symlinked ancestor and mean the same directory — ``/tmp``
    against ``/private/tmp`` on macOS is the everyday case. The drop directory
    itself is checked for being a link by :func:`assert_unlinked_evidence`
    before this is called, so resolving here cannot launder one away.
    """
    root = drops_root.resolve()
    resolved = absolute.resolve()
    if resolved == root:
        raise DropPathError(
            f"the drops root itself is not a drop: {absolute} (root {root})"
        )
    if not resolved.is_relative_to(root):
        raise DropPathError(
            f"drop directory {absolute} is not under the configured drops root"
            f" {root}; move the drop under the root or correct MM_DROPS_ROOT"
        )
    return resolved.relative_to(root).as_posix()


def assert_unlinked_evidence(drop_dir: Path) -> None:
    """Refuse a drop directory that is a symlink, or that holds one.

    Called at intake, before a job row exists, and by :func:`read_drop`, so the
    worker cannot inherit a drop that became a link afterwards. ``is_file()``
    follows links, so without this a symlinked ``recording.mp4`` is admitted,
    reports ``has_recording=true``, and only fails at replay.
    """
    if drop_dir.is_symlink():
        raise SymlinkedEvidenceError(
            f"drop directory is a symbolic link: {drop_dir} — a drop is"
            " write-once evidence and must be a real directory (AD-1, AD-13)"
        )
    for name in CANONICAL_FILENAMES:
        if (drop_dir / name).is_symlink():
            raise SymlinkedEvidenceError(
                f"{name} in the drop is a symbolic link — evidence must live in"
                " the write-once drop, not behind a link whose target can change"
                " after its checksum is recorded (AD-1, AD-13)"
            )


def sha256_and_size(path: Path) -> tuple[str, int]:
    """Digest and byte size of a file, read in bounded chunks.

    One implementation for every caller — the `probe` stage recording the
    recording's provenance, the `transcribe` stage recording the extracted
    audio's, intake comparing two recordings, and the backfill. A second
    spelling of this would be a second answer to "did these bytes change".
    """
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


@dataclass(frozen=True)
class DropContents:
    """What a drop directory holds, read once when the job is claimed."""

    path: Path
    metadata: dict[str, Any]
    recording_path: Path | None
    transcript_vtt_path: Path | None
    transcript_text_path: Path | None
    # Story 4.1a: the summariser documents the drop carried, when it carried
    # them. Absent is the ordinary shape of every drop emitted before 4.1a and
    # of any pull whose summariser failed — the `extract` stage then generates
    # the missing document instead of adopting it.
    extraction_summary_path: Path | None = None
    extraction_actions_path: Path | None = None

    @property
    def has_recording(self) -> bool:
        """Whether the video stages have anything to run on (AD-1).

        ``False`` makes this a transcript-only drop: ``probe frames ocr
        screens transcribe`` are recorded as ``skipped``.
        """
        return self.recording_path is not None

    @property
    def transcript_paths(self) -> tuple[Path, ...]:
        """Provided transcripts, in the drop's own order (never merged here)."""
        return tuple(
            p
            for p in (self.transcript_vtt_path, self.transcript_text_path)
            if p is not None
        )

    @property
    def source_id(self) -> str:
        return str(self.metadata["sourceId"])

    @property
    def corpus(self) -> str:
        return str(self.metadata["corpus"])

    @property
    def started_at(self) -> datetime:
        """Meeting start as declared by the source side, never re-derived."""
        return parse_started_at(self.metadata["startedAt"])

    @property
    def started_at_precision(self) -> str:
        return str(self.metadata["startedAtPrecision"])

    @property
    def provenance(self) -> dict[str, Any]:
        value = self.metadata.get("provenance")
        return value if isinstance(value, dict) else {}

    @property
    def stream_url(self) -> str | None:
        """The drop's source page URL, when it is one a link may point at.

        One place decides what counts as a usable source link, so the
        `moments` stage never has to (UX-DR11's transitional deep link is the
        only consumer today). ``None`` unless ``provenance.url`` is a non-empty
        string with an ``http`` or ``https`` scheme and an authority/host — a
        hostless pseudo-URL, `javascript:`, or `file:` value is treated as
        absent rather than stored, because a rendered link must never carry a
        target this project did not intend.
        A value the URL parser cannot read at all — an unterminated IPv6
        bracket, say — is absent for the same reason: one malformed field in a
        drop must not fail the stage that reads it.

        Otherwise the surrounding whitespace is stripped and nothing else is
        changed: no time parameter is appended, since no deep-link time syntax
        has been verified against SharePoint Stream and an invented one would
        be fabricated behaviour.
        """
        raw = self.provenance.get("url")
        if not isinstance(raw, str):
            return None
        url = raw.strip()
        if not url:
            return None
        try:
            parsed = urlsplit(url)
            # Accessing ``port`` performs URL parser validation; malformed or
            # out-of-range ports raise ``ValueError`` lazily.
            parsed.port
        except ValueError:
            return None
        if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
            return None
        return url

    @property
    def declared_extractions(self) -> frozenset[str]:
        """The `metadata.extractions` keys this drop declares.

        Empty for every drop emitted before the declaration existed, and for a
        drop whose summariser did not run — which is the ordinary shape, not an
        error. A drop that *declares* a document it does not carry is a
        different matter, and the `extract` stage refuses it: the schema's
        fail-closed version gate buys nothing if the reader then decides on
        file presence alone.
        """
        declared = self.metadata.get(EXTRACTIONS_METADATA_KEY)
        if not isinstance(declared, dict):
            return frozenset()
        return frozenset(
            key for key in declared if key in EXTRACTION_DECLARATION_KEYS
        )

    @property
    def title(self) -> str | None:
        """Best-effort human label: the source side's provenance ``title``."""
        title = self.provenance.get("title")
        if isinstance(title, str) and title.strip():
            return title.strip()
        return None


def parse_started_at(raw: object) -> datetime:
    """Parse a drop's ``startedAt`` into an aware UTC datetime.

    Public because intake compares an augmenting drop's declared wall clock
    against the target meeting's persisted one and has to parse it exactly the
    way the pipeline will (`api/ingests.py`).
    """
    if not isinstance(raw, str):
        raise DropError(f"startedAt must be an ISO 8601 UTC string, got {raw!r}")
    # The schema pins the trailing "Z" | "+00:00" form; fromisoformat handles
    # "+00:00" natively and (3.11+) "Z" as well, but normalize for clarity.
    text = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise DropError(f"startedAt is not a valid ISO 8601 timestamp: {raw!r}") from exc


def read_metadata(drop_dir: Path) -> dict[str, Any]:
    """Parse ``metadata.json`` from a drop directory.

    Raises :class:`DropError` naming the problem. Schema validation is the
    api's job at intake (it owns the RFC 9457 response shape); this reader
    only guarantees a JSON object came back.
    """
    metadata_path = drop_dir / METADATA_FILENAME
    try:
        text = metadata_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise DropError(f"drop is missing {METADATA_FILENAME}: {metadata_path}") from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise DropError(f"{METADATA_FILENAME} could not be read: {exc}") from exc
    try:
        metadata = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DropError(f"{METADATA_FILENAME} is not valid JSON: {exc}") from exc
    if not isinstance(metadata, dict):
        raise DropError(f"{METADATA_FILENAME} must be a JSON object: {metadata_path}")
    return metadata


def read_drop(drop_dir: Path, config_path: Path | None = None) -> DropContents:
    """Read a drop directory: metadata plus which canonical files are present.

    Raises :class:`DropError` when the directory is missing, is not a
    directory, has no readable ``metadata.json``, or carries neither a
    recording nor a transcript.
    """
    if not drop_dir.is_dir():
        raise DropError(f"drop directory does not exist: {drop_dir}")
    # Re-checked here and not only at intake: the drop was validated before the
    # job row existed, and this is the worker's own look at the same directory.
    assert_unlinked_evidence(drop_dir)

    metadata = read_metadata(drop_dir)
    if config_path is not None:
        schema_path = config_path.parent / "docs" / "source-drop.schema.json"
        try:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            violations = sorted(
                jsonschema.Draft202012Validator(
                    schema, format_checker=jsonschema.FormatChecker()
                ).iter_errors(metadata),
                key=lambda error: list(error.absolute_path),
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, jsonschema.SchemaError) as exc:
            raise DropError(f"source-drop schema could not be read: {schema_path}: {exc}") from exc
        if violations:
            detail = "; ".join(
                ("/".join(str(p) for p in error.absolute_path) or "(root)")
                + ": " + error.message
                for error in violations
            )
            raise DropError(f"{METADATA_FILENAME} no longer matches the source-drop schema: {detail}")

    def present(name: str) -> Path | None:
        candidate = drop_dir / name
        return candidate if candidate.is_file() else None

    contents = DropContents(
        path=drop_dir,
        metadata=metadata,
        recording_path=present(RECORDING_FILENAME),
        transcript_vtt_path=present(TRANSCRIPT_VTT_FILENAME),
        transcript_text_path=present(TRANSCRIPT_TEXT_FILENAME),
        extraction_summary_path=present(EXTRACTION_SUMMARY_FILENAME),
        extraction_actions_path=present(EXTRACTION_ACTIONS_FILENAME),
    )
    if not contents.has_recording and not contents.transcript_paths:
        raise DropError(
            f"drop contains neither a recording nor a transcript: {drop_dir} "
            f"(expected one of {', '.join(EVIDENCE_FILENAMES)})"
        )
    for field in ("sourceId", "corpus", "startedAt", "startedAtPrecision"):
        if field not in metadata:
            raise DropError(f"{METADATA_FILENAME} is missing required field {field!r}")
    return contents
