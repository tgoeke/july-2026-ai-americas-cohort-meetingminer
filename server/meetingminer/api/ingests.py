"""POST /ingests — the one intake door (AD-14).

Validates a source drop at an absolute path against
``docs/source-drop.schema.json`` (AD-1) and inserts the job row plus its
pre-seeded stage checkpoints. Intake never writes into or deletes from the
drop directory (AD-13) and never executes pipeline stages — the worker
(story 1.3) claims the job.

A drop declaring ``augments`` (``schemaVersion: 2``, story 1.12) is the one
case where a second drop for an occurrence is not a conflict: it brings
evidence the occurrence lacks, and the meeting it belongs to already exists.
Two shapes exist today — a recording recovered after a transcript-only ingest
(story 1.12), and the source side's participant graph reaching a meeting whose
drop was emitted without one (story 1.13) — and the door is one door for both:
a drop is augmenting if it adds a recording the meeting has not got, or a
``participants`` array its current drop has not got. A drop that adds neither
is refused rather than run, because re-arming stages over unchanged evidence
costs the meeting a re-projection and produces the same bundle back.

**The wire keeps absolute paths; the database does not** (story 2.1a). The
puller posts the absolute ``dropPath`` it just finalized, unchanged. This
module is the single place that path is checked for being under
``MM_DROPS_ROOT`` and converted to the root-relative form the database stores,
and every read of a stored path resolves back through the configured root. A
drop outside the root is refused before a job row exists, and no absolute path
is written to Postgres or returned to a client.

Intake re-arms *that occurrence's existing job* in place — new drop path,
and back to ``queued`` either the video stages plus ``align`` and ``moments``
(a recovered recording) or just ``align`` and ``moments`` (no new recording, so
the frames and screenshots already derived from the unchanged video stand) —
rather than opening a second one, because ``meeting.job_id`` and
``meeting.source_id`` are UNIQUE and a second job could therefore never own the
meeting (AD-14: re-processing an occurrence is a rerun of its existing job).
Keeping the job keeps the meeting id, which is what keeps every moment id,
citation, and published artifact valid.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NoReturn
from uuid import UUID

import jsonschema
import psycopg.errors
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from psycopg import Connection
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from referencing.exceptions import Unresolvable

from meetingminer.api.problems import (
    DROPS_ROOT_UNCONFIGURED,
    Problem,
    ProblemDetails,
)
from meetingminer.config import AppConfig, ConfigError, validate_drops_root
from meetingminer.domain.drops import (
    EVIDENCE_FILENAMES,
    METADATA_FILENAME,
    RECORDING_FILENAME,
    TRANSCRIPT_TEXT_FILENAME,
    TRANSCRIPT_VTT_FILENAME,
    DropError,
    DropPathError,
    SymlinkedEvidenceError,
    assert_unlinked_evidence,
    drop_relative_path,
    parse_started_at,
    read_metadata,
    resolve_drop_path,
    sha256_and_size,
)
from meetingminer.domain.jobs import (
    AUGMENTATION_STAGES,
    PARTICIPANT_AUGMENTATION_STAGES,
    STAGE_NAMES,
    evidence_complete,
)
from meetingminer.logs import log_error_event, log_event


def drop_schema_path(config: AppConfig) -> Path:
    """The drop contract, anchored to the config.yaml actually loaded.

    Derived from ``config.config_path`` rather than re-resolved from
    ``MM_CONFIG_PATH``/cwd (finding 17, and the cwd-freezing hazard of doing
    this at import time): the schema and the config always come from one tree.
    """
    return config.config_path.parent / "docs" / "source-drop.schema.json"


@dataclass(frozen=True)
class _LoadedSchema:
    """The installed drop-schema validator plus the file identity it came from.

    ``mtime_ns``, ``size``, and ``ino`` are the stat signature `_validator()`
    re-checks per request; a mismatch triggers a reload, so a schema edited on
    disk takes effect on the next ingest without an api restart (the
    2026-08-19 incident: a stale in-process copy refused 28 drops the on-disk
    schema accepted). The inode is part of the signature because an
    atomic-rename deploy (`rsync -a`, `cp -p` then rename) can preserve both
    mtime and size while swapping the content.
    """

    path: Path
    mtime_ns: int
    size: int
    ino: int
    validator: jsonschema.Draft202012Validator


_SCHEMA: _LoadedSchema | None = None

# The reload-failure slug is inline (like `invalid-drop`) rather than a
# `problems.py` constant, because this module is its only consumer —
# `DROPS_ROOT_UNCONFIGURED` is a constant only because two routers share it.
_SCHEMA_UNREADABLE = "drop-schema-unreadable"

# Everything that can go wrong turning a file path into an installed
# validator: stat/read (OSError), decode, parse, and a JSON document that is
# not itself a valid 2020-12 schema.
_SCHEMA_LOAD_ERRORS = (
    OSError,
    UnicodeDecodeError,
    json.JSONDecodeError,
    jsonschema.SchemaError,
)


def install_drop_schema(path: Path) -> _LoadedSchema:
    """Read, check, and install the drop schema at ``path``; log the load.

    The stat comes *before* the read: if the file changes in between, the
    recorded signature is stale, so the next request's stat differs and
    triggers a convergent reload. The global swap is a single assignment
    (atomic in CPython), and it only happens after the new validator is fully
    built — a failed load leaves the previous schema installed. Returns the
    record it installed, so a caller never has to re-read the global.

    Raises the `_SCHEMA_LOAD_ERRORS` on failure; callers decide whether that
    is fatal (startup) or a fail-closed 500 (per-request reload).
    """
    global _SCHEMA
    stat = path.stat()
    parsed: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        # `true`/`false` (or any non-object) is valid JSON *and* a valid
        # boolean 2020-12 schema, so `check_schema` would pass it — but the
        # drop contract is an object schema, and a non-dict here would crash
        # `parsed.get("$id")` outside the named error paths.
        raise jsonschema.SchemaError(f"drop schema must be a JSON object: {path}")
    schema: dict[str, Any] = parsed
    jsonschema.Draft202012Validator.check_schema(schema)
    record = _LoadedSchema(
        path=path,
        mtime_ns=stat.st_mtime_ns,
        size=stat.st_size,
        ino=stat.st_ino,
        validator=jsonschema.Draft202012Validator(
            schema, format_checker=jsonschema.FormatChecker()
        ),
    )
    _SCHEMA = record
    log_event(
        "drop_schema_loaded",
        path=str(path),
        schemaId=schema.get("$id"),
        mtime=datetime.fromtimestamp(
            stat.st_mtime_ns / 1_000_000_000, tz=timezone.utc
        ).isoformat(),
        # The exact integer the reload check keys on; the ISO form above is
        # for humans and loses sub-microsecond precision to float division.
        mtimeNs=stat.st_mtime_ns,
        size=stat.st_size,
    )
    return record


def load_drop_schema(config: AppConfig) -> None:
    """Load and install the drop contract, fail-fast style (named error).

    Called at api startup, after the config gate, so an unreadable schema
    aborts the boot instead of failing the first ingest. Startup is only the
    *first* load: `_validator()` re-stats the file on every ingest request and
    reinstalls it when it has changed on disk. Returns nothing — the installed
    state lives in the module global, and no caller consumes a return value.
    """
    path = drop_schema_path(config)
    try:
        install_drop_schema(path)
    except _SCHEMA_LOAD_ERRORS as exc:
        print(
            f"fatal: api startup aborted: source-drop schema unreadable:"
            f" {path}: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc


def _validator() -> _LoadedSchema:
    """The current loaded drop schema, reloaded if the file changed.

    A `stat()` per request, not a read: an unchanged file (same ``mtime_ns``,
    ``size``, and inode) reuses the installed validator without re-parsing.
    The inode catches a same-mtime same-size atomic-rename replace; the one
    change stat alone cannot see is an in-place same-size write with a
    preserved mtime. Any failure to stat or reload fails *closed* as a 500
    problem naming the schema file — never `422 invalid-drop`, because no
    judgment about the drop is possible when the schema itself cannot be
    loaded. The previous validator stays installed, so once the file is
    readable and valid again the next request reloads it and proceeds
    normally — no restart needed.
    """
    record = _SCHEMA
    if record is None:  # pragma: no cover - startup always installs it
        raise RuntimeError(
            "source-drop schema not loaded — call load_drop_schema() at startup"
        )
    try:
        stat = record.path.stat()
        if (stat.st_mtime_ns, stat.st_size, stat.st_ino) != (
            record.mtime_ns,
            record.size,
            record.ino,
        ):
            record = install_drop_schema(record.path)
    except _SCHEMA_LOAD_ERRORS as exc:
        _raise_drop_schema_unreadable(record.path, exc)
    return record


def _raise_drop_schema_unreadable(path: Path, exc: Exception) -> NoReturn:
    """Log and report a schema the current request cannot use."""
    # The client sees the 500 problem; without this line the server side would
    # be silent — and a fault observable only as client refusals is exactly the
    # failure mode this story removes.
    log_error_event("drop_schema_load_failed", path=str(path), error=str(exc))
    raise Problem(
        500,
        _SCHEMA_UNREADABLE,
        f"source-drop schema unreadable: {path}: {exc}",
    ) from exc

# METADATA_FILENAME / EVIDENCE_FILENAMES are defined once in
# meetingminer.domain.drops and imported here: the worker needs the same
# vocabulary, and it may not import api any more than api may import pipeline.

router = APIRouter()
ROUTER_ORDER = 0


class IngestRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    # Still absolute, and deliberately so: the puller finalizes a drop at an
    # absolute path and knows nothing about this server's MM_DROPS_ROOT. The
    # conversion to the stored relative form happens here, on the server, in
    # `_validate_drop_path` and nowhere else (story 2.1a).
    drop_path: str


class IngestResult(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    job_id: UUID


def drops_root(request: Request) -> Path:
    """The configured ``MM_DROPS_ROOT`` this process anchors drop paths to.

    Reached through ``app.state.config`` rather than by importing ``api.main``
    (which would be circular), and deliberately not through
    :func:`meetingminer.config.require_drops_root`: the api gates on that at
    startup, so by the time a request arrives an unset root can only mean a
    test swapped the config. It is still answered as a 500 rather than assumed,
    because the alternative is resolving every stored path against ``/``.
    """
    try:
        return validate_drops_root(request.app.state.config.secrets.mm_drops_root)
    except ConfigError:
        raise Problem(
            500,
            DROPS_ROOT_UNCONFIGURED,
            "MM_DROPS_ROOT is unavailable on the api process, so no drop path"
            " can be anchored; correct the mount or .env and restart the api",
        ) from None


def _validate_drop_path(raw_path: str, root: Path) -> tuple[Path, str]:
    """Check the posted absolute path and return it beside its stored form.

    The wire contract is unchanged: ``dropPath`` is still absolute, because the
    puller finalizes a drop at an absolute path and knows nothing about this
    server's configuration. What changes is what gets stored — the path
    relative to ``MM_DROPS_ROOT`` — and this is the single place the conversion
    happens, so a second spelling of it cannot appear elsewhere.
    """
    path = Path(raw_path)
    if not path.is_absolute():
        raise Problem(
            400, "invalid-drop-path", f"dropPath must be an absolute path: {raw_path!r}"
        )
    try:
        exists = path.exists()
        is_dir = path.is_dir()
    except (ValueError, OSError) as exc:  # e.g. embedded NUL byte, name too long
        raise Problem(
            400, "invalid-drop-path", f"drop path could not be checked: {exc}"
        ) from exc
    if not exists:
        raise Problem(400, "invalid-drop-path", f"drop directory does not exist: {path}")
    if not is_dir:
        raise Problem(400, "invalid-drop-path", f"drop path is not a directory: {path}")
    # Before relativizing, not after: `drop_relative_path` resolves links to
    # compare against the root, so a symlinked drop directory would otherwise
    # be laundered into the real path it points at and admitted.
    try:
        assert_unlinked_evidence(path)
    except SymlinkedEvidenceError as exc:
        raise Problem(400, "symlinked-evidence", str(exc)) from None
    except OSError as exc:
        raise Problem(
            400, "invalid-drop-path", f"drop path could not be checked: {exc}"
        ) from None
    try:
        relative = drop_relative_path(root, path)
    except DropPathError as exc:
        raise Problem(400, "invalid-drop-path", str(exc)) from None
    except OSError as exc:
        raise Problem(
            400, "invalid-drop-path", f"drop path could not be checked: {exc}"
        ) from None
    return path, relative


def _resolved_drop(root: Path, relative: str | None) -> Path | None:
    """A stored drop path as a directory, or ``None`` when it is not usable.

    ``None`` covers both a row the 2.1a backfill has not reached (its
    ``drop_relative_path`` is still NULL) and a stored path that no longer
    resolves inside the root. Every caller already has a "the target drop
    cannot be read" branch, and both cases belong in it: an occurrence whose
    drop cannot be located is not an occurrence anything may be attached to.
    """
    if relative is None:
        return None
    try:
        return resolve_drop_path(root, relative)
    except (DropPathError, OSError, ValueError):
        return None


def _load_metadata(drop_dir: Path, schema: _LoadedSchema) -> dict[str, Any]:
    metadata_path = drop_dir / METADATA_FILENAME
    if not metadata_path.is_file():
        raise Problem(
            422, "invalid-drop", f"drop is missing required file {METADATA_FILENAME}"
        )
    try:
        text = metadata_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise Problem(
            422, "invalid-drop", f"{METADATA_FILENAME} could not be read: {exc}"
        ) from exc
    try:
        metadata = json.loads(text)
    except json.JSONDecodeError as exc:
        raise Problem(
            422, "invalid-drop", f"{METADATA_FILENAME} is not valid JSON: {exc}"
        ) from exc

    try:
        violations = sorted(
            schema.validator.iter_errors(metadata), key=lambda e: list(e.absolute_path)
        )
    except Unresolvable as exc:
        # A syntactically valid schema can still be unusable: `check_schema()`
        # accepts external `$ref` values, which the validator resolves only
        # when it evaluates a matching instance. That is a schema failure, not
        # an invalid source drop, so preserve the same fail-closed problem.
        _raise_drop_schema_unreadable(schema.path, exc)
    if violations:
        messages = [
            (("/".join(str(p) for p in error.absolute_path) or "(root)") + ": " + error.message)
            for error in violations
        ]
        raise Problem(
            422,
            "invalid-drop",
            f"{METADATA_FILENAME} violates the source-drop schema: "
            + "; ".join(messages),
            violations=messages,
        )
    return metadata


def _check_evidence_present(drop_dir: Path) -> None:
    if not any((drop_dir / name).is_file() for name in EVIDENCE_FILENAMES):
        raise Problem(
            422,
            "invalid-drop",
            "drop contains neither a recording nor a transcript — at least one of "
            + ", ".join(EVIDENCE_FILENAMES)
            + " must be present",
        )


def _conflict(source_id: str, job_id: Any | None) -> Problem:
    extensions = {} if job_id is None else {"jobId": str(job_id)}
    return Problem(
        409,
        "duplicate-source",
        f"sourceId {source_id!r} already has a non-failed job",
        **extensions,
    )


def _select_jobs(conn: Connection, source_id: str) -> list[tuple[Any, str]]:
    """All job rows for a sourceId, newest first (separate function so tests
    can force the lost-race paths through the UniqueViolation handlers)."""
    return conn.execute(
        "SELECT id, status FROM job WHERE source_id = %s ORDER BY created_at DESC",
        (source_id,),
    ).fetchall()


def _live_job_id(conn: Connection, source_id: str) -> Any | None:
    row = conn.execute(
        "SELECT id FROM job WHERE source_id = %s AND status != 'failed'",
        (source_id,),
    ).fetchone()
    return row[0] if row else None


def _seed_stages(conn: Connection, job_id: Any) -> None:
    conn.cursor().executemany(
        "INSERT INTO job_stage (job_id, name) VALUES (%s, %s)",
        [(job_id, name) for name in STAGE_NAMES],
    )


# --- augmentation: evidence that reached the occurrence after its ingest ----

# The transcript forms a drop may carry. An augmenting drop must carry every one
# its target's current drop carries: `align` deletes the `transcript_source` row
# for a provided kind that is no longer present (pipeline/stages/align.py), so a
# recording-only augmenting drop would erase the provided transcript, move every
# transcript boundary, and supersede every moment derived from it — the exact
# opposite of AD-13. Refusing at the door is cheaper and safer than teaching
# `align` to remember a drop it can no longer see.
_TRANSCRIPT_FILENAMES = (TRANSCRIPT_VTT_FILENAME, TRANSCRIPT_TEXT_FILENAME)


def _invalid_augmenting_drop(detail: str) -> Problem:
    return Problem(422, "invalid-augmenting-drop", detail)


def _augment_target(conn: Connection, target_source_id: str) -> tuple[Any, ...]:
    """The occurrence an augmenting drop names, or a 422 saying it is not there.

    "There" means a non-failed job that already owns a Meeting row. A failed
    job is deliberately not a declared augmentation target, even though it may
    own a Meeting after minting; its ordinary retry route validates the
    replacement against that durable Meeting instead. A job whose worker has
    not minted the meeting yet is not an occurrence anything can be attached to.
    """
    row = conn.execute(
        "SELECT j.id, j.corpus, j.drop_relative_path, m.id, m.has_recording,"
        " m.started_at, m.started_at_precision"
        " FROM job j JOIN meeting m ON m.job_id = j.id"
        " WHERE j.source_id = %s AND j.status != 'failed' FOR UPDATE OF j",
        (target_source_id,),
    ).fetchone()
    if row is None:
        raise Problem(
            422,
            "unknown-augment-target",
            f"augments.sourceId {target_source_id!r} names no ingested occurrence:"
            " there is no non-failed job with a meeting for that sourceId",
        )
    return row


def _check_target_is_augmentable(
    conn: Connection, target_source_id: str, job_id: Any
) -> None:
    statuses = {
        name: status
        for name, status in conn.execute(
            "SELECT name, status FROM job_stage WHERE job_id = %s", (job_id,)
        ).fetchall()
    }
    if not evidence_complete(statuses):
        # `evidence_complete()` and not `job.status = 'done'`: `extract` has no
        # implementation, so no job ever reaches `done` and gating on it would
        # make augmentation permanently unreachable. This is the same predicate
        # the meetings list already publishes as `viewable`.
        raise Problem(
            409,
            "augment-target-incomplete",
            f"occurrence {target_source_id!r} is still ingesting — its evidence"
            " stages must all be done or skipped before further evidence can be"
            " added to it",
            jobId=str(job_id),
        )


def _has_participant_graph(metadata: dict[str, Any]) -> bool:
    """Whether a drop's metadata carries a non-empty participant graph.

    Empty deliberately does not count, on either side of the comparison. An
    empty array is an assertion — `align` reads it as "the source looked and
    found nobody" and does *not* fall back to transcript labels — so a drop
    carrying one brings no participants to add, and a target carrying one has
    no graph a later drop would be duplicating.
    """
    value = metadata.get("participants")
    return isinstance(value, list) and bool(value)


def _target_drop_has_participant_graph(target_dir: Path | None) -> bool:
    """Read the occurrence's current drop — never write to it (AD-13).

    ``target_dir`` is the stored relative path already resolved against the
    configured drops root, or ``None`` when it could not be placed there.

    An unreadable target drop answers ``False`` — "cannot tell" is reported as
    "no graph", which is the reading that lets a later drop supply one. It is
    not an acceptance on its own: a target *directory* that cannot be read
    fails :func:`_check_meeting_replacement` a moment later, because the
    transcripts this drop must preserve cannot be checked either. Only the
    narrower case — the directory readable but its ``metadata.json`` gone or
    corrupt — reaches acceptance here, and accepting there is right: the
    occurrence's own record of its participants is unreadable, so a drop
    offering one is new evidence by any reading.
    """
    if target_dir is None:
        return False
    try:
        metadata = read_metadata(target_dir)
    except (DropError, OSError, ValueError):
        return False
    return _has_participant_graph(metadata)


def _check_augmenting_drop(
    drop_dir: Path,
    metadata: dict[str, Any],
    target_source_id: str,
    job_id: Any,
    target_dir: Path | None,
    target_corpus: str,
    target_started_at: datetime,
    target_started_at_precision: str,
    *,
    target_has_recording: bool,
) -> bool:
    """Refuse an augmentation that adds nothing, then preserve the Meeting.

    A declared augmentation must bring the occurrence evidence it does not
    have: a recording the meeting has not got, or a ``participants`` array its
    current drop has not got. Anything else re-arms stages over unchanged
    evidence — a re-projection and a full re-derivation that produce the same
    bundle back — so it is refused at the door.

    Returns whether the drop adds a recording, which is the single question
    that decides how much of the pipeline is re-armed.

    The immutable Meeting comparison itself also protects plain retries after
    post-mint failures, so it deliberately lives in
    :func:`_check_meeting_replacement`.
    """
    adds_recording = (
        drop_dir / RECORDING_FILENAME
    ).is_file() and not target_has_recording
    target_has_graph = _target_drop_has_participant_graph(target_dir)
    adds_participants = _has_participant_graph(metadata) and not target_has_graph
    if not (adds_recording or adds_participants):
        # Its own problem type at 409, not `invalid-augmenting-drop`: nothing
        # about this drop is invalid — it is well formed, it agrees with the
        # meeting on every pinned field, and the identical drop would be
        # accepted against an occurrence that still lacked this evidence. What
        # refuses it is the target's current state, which is what 409 says and
        # is the same status as the `augment-target-has-recording` refusal this
        # supersedes. One problem type, one status.
        raise Problem(
            409,
            "augment-adds-nothing",
            f"this drop brings occurrence {target_source_id!r} no evidence it"
            " lacks: "
            + (
                "the occurrence already has a recording"
                if target_has_recording
                else f"the drop carries no {RECORDING_FILENAME}"
            )
            + ", and "
            + (
                "the occurrence's drop already carries a participants array"
                if target_has_graph
                else "the drop carries no participants array"
            )
            + ". An augmenting drop must add a recording the meeting has not"
            " got, or a participant graph its drop has not got",
            jobId=str(job_id),
        )
    _check_meeting_replacement(
        drop_dir,
        metadata,
        target_dir,
        target_corpus,
        target_started_at,
        target_started_at_precision,
        target_has_recording=target_has_recording,
    )
    return adds_recording


def _check_meeting_replacement(
    drop_dir: Path,
    metadata: dict[str, Any],
    target_dir: Path | None,
    target_corpus: str,
    target_started_at: datetime,
    target_started_at_precision: str,
    *,
    target_has_recording: bool,
) -> None:
    """Refuse a replacement that would erase or rewrite an existing Meeting.

    This deliberately does not require an ``augments`` declaration. A failed
    initial ingest with no Meeting retains its historical re-queue behavior;
    one that already owns a Meeting must preserve its identity and provided
    transcripts. A transcript-only Meeting may be retried without a recording,
    but a Meeting whose persisted state says it already has one may not be
    downgraded to transcript-only.

    **Why the clock fields are pinned and the descriptive ones are not.**
    ``mint_meeting``'s ``ON CONFLICT`` rewrites ``started_at``,
    ``started_at_precision``, ``title`` and ``provenance`` from whichever drop
    the job currently points at (`pipeline/runner.py`), and ``moments`` then
    re-stamps every moment's absolute ``started_at`` as ``meeting.started_at +
    start_ms`` (`pipeline/stages/moments.py`). An augmenting drop declaring a
    different ``startedAt`` or ``startedAtPrecision`` would therefore silently
    shift the wall clock of exactly the moments whose ids this feature exists to
    preserve — augmentation would destroy rather than add. ``title`` and
    ``provenance`` are deliberately still allowed to differ: nothing is keyed on
    them, the recovered recording is the better source for both, and the
    provenance deep link retires anyway once a screenshot replaces it (UX-DR11).
    """
    incoming_recording = drop_dir / RECORDING_FILENAME
    if target_has_recording and not incoming_recording.is_file():
        raise _invalid_augmenting_drop(
            f"a replacement for a recorded meeting must carry {RECORDING_FILENAME}"
            " — retrying an augmentation may not remove recovered evidence"
        )
    corpus = str(metadata["corpus"])
    if corpus != target_corpus:
        # Corpus is carried onto the Meeting row and decides whether the meeting
        # is an eval subject (AD-1). An augmenting drop that disagrees would
        # reclassify the meeting, so it is refused rather than applied.
        raise _invalid_augmenting_drop(
            f"corpus {corpus!r} does not match the target occurrence's"
            f" {target_corpus!r}; an augmenting drop may not reclassify a meeting"
        )

    declared_started_at = parse_started_at(metadata["startedAt"])
    if declared_started_at != target_started_at:
        raise _invalid_augmenting_drop(
            f"startedAt {metadata['startedAt']!r} does not match the target"
            f" occurrence's {target_started_at.isoformat()}; the meeting's wall"
            " clock is the origin every preserved moment's absolute timestamp is"
            " measured from, so an augmenting drop may not restate it"
        )
    declared_precision = str(metadata["startedAtPrecision"])
    if declared_precision != target_started_at_precision:
        raise _invalid_augmenting_drop(
            f"startedAtPrecision {declared_precision!r} does not match the target"
            f" occurrence's {target_started_at_precision!r}; the precision is"
            " stamped onto every moment beside its start, so an augmenting drop"
            " may not restate it"
        )

    # Read the target's drop, never write to it: the finalized drop is
    # write-once and this check is the only reason intake opens it at all.
    # An unreadable target drop is a refusal rather than an acceptance —
    # "no transcripts found" and "cannot tell" must not collapse into one
    # answer, or a vanished drop directory would silently license the
    # transcript-erasing case this guard exists to stop.
    try:
        if target_dir is None or not target_dir.is_dir():
            raise _invalid_augmenting_drop(
                "the target occurrence's drop directory is not readable under"
                " the configured drops root, so the transcripts this drop must"
                " preserve cannot be checked"
            )
        present = {
            name for name in _TRANSCRIPT_FILENAMES if (target_dir / name).is_file()
        }
    except (OSError, ValueError) as exc:  # unreadable path, name too long, NUL byte
        raise _invalid_augmenting_drop(
            f"the target occurrence's drop directory could not be read ({exc}),"
            " so the transcripts this drop must preserve cannot be checked"
        ) from None
    missing = sorted(name for name in present if not (drop_dir / name).is_file())
    if missing:
        raise _invalid_augmenting_drop(
            "an augmenting drop must carry every transcript the target"
            f" occurrence's drop carries; missing: {', '.join(missing)} (AD-13:"
            " a provided transcript is never erased)"
        )
    try:
        target_metadata = read_metadata(target_dir)
    except (DropError, OSError, ValueError) as exc:
        raise _invalid_augmenting_drop(
            f"the target occurrence's metadata could not be read ({exc})"
        ) from None
    if _has_participant_graph(target_metadata) and not _has_participant_graph(metadata):
        raise _invalid_augmenting_drop(
            "an augmenting drop must carry the participant graph the target occurrence's"
            " drop carries; a later recovery may not replace mail-keyed identities with"
            " transcript labels"
        )
    if target_has_recording:
        target_recording = target_dir / RECORDING_FILENAME
        try:
            if sha256_and_size(target_recording) != sha256_and_size(incoming_recording):
                raise _invalid_augmenting_drop(
                    "an augmenting drop for a recorded meeting must carry the same"
                    f" {RECORDING_FILENAME}; a changed recording needs a full replacement path"
                )
        except OSError as exc:
            raise _invalid_augmenting_drop(
                f"the target occurrence's {RECORDING_FILENAME} could not be read"
                f" ({exc})"
            ) from None


def _meeting_for_job(conn: Connection, job_id: Any) -> tuple[Any, ...] | None:
    """The immutable Meeting fields for a job, when minting already occurred."""
    return conn.execute(
        "SELECT j.drop_relative_path, m.corpus, m.started_at, m.started_at_precision,"
        " m.has_recording"
        " FROM job j JOIN meeting m ON m.job_id = j.id WHERE j.id = %s",
        (job_id,),
    ).fetchone()


def _rearm_job(
    conn: Connection, job_id: Any, relative: str, stages: tuple[str, ...]
) -> None:
    """Point the occurrence's existing job at the new drop and re-queue it.

    `source_id` and `corpus` are deliberately untouched: the job keeps the
    occurrence's identity (the augmenting drop may legitimately carry a
    different `sourceId` of its own), and the corpus was checked to match. Only
    the named stages go back to `queued`, so the runner's settled-stage guard
    resumes rather than restarts — `extract` in particular keeps whatever
    checkpoint it had. ``stages`` is ``AUGMENTATION_STAGES`` when the drop
    brings a recording the meeting had not got and
    ``PARTICIPANT_AUGMENTATION_STAGES`` when it does not, so an unchanged video
    is never re-sampled, re-OCR'd and re-screened to reach the same frames.

    The legacy absolute ``drop_path`` is cleared in the same statement: a job
    re-armed onto a new drop must not keep a stale absolute path the backfill
    would later mistake for the current one.
    """
    conn.execute(
        "UPDATE job SET status = 'queued', error = NULL,"
        " drop_relative_path = %s, drop_path = NULL, updated_at = now()"
        " WHERE id = %s",
        (relative, job_id),
    )
    conn.execute(
        "UPDATE job_stage SET status = 'queued', error = NULL"
        " WHERE job_id = %s AND name = ANY(%s)",
        (job_id, list(stages)),
    )


def _accept_augmenting_drop(
    conn: Connection,
    drop_dir: Path,
    relative: str,
    metadata: dict[str, Any],
    root: Path,
) -> JSONResponse:
    """Resolve the declared occurrence, refuse or re-arm, and answer 200."""
    source_id = str(metadata["sourceId"])
    target_source_id = str(metadata["augments"]["sourceId"])

    if target_source_id != source_id:
        # The drop carries its own identity — a recording recovered from the
        # recorder's personal drive has its own drive-item id (AD-1 admits both
        # forms). That is allowed, but only if that identity is not itself a
        # live occurrence: otherwise one drop would claim two meetings.
        other = _live_job_id(conn, source_id)
        if other is not None:
            raise _conflict(source_id, other)

    (
        job_id,
        target_corpus,
        target_relative_path,
        _meeting_id,
        has_recording,
        target_started_at,
        target_started_at_precision,
    ) = _augment_target(conn, target_source_id)
    _check_target_is_augmentable(conn, target_source_id, job_id)
    adds_recording = _check_augmenting_drop(
        drop_dir,
        metadata,
        target_source_id,
        job_id,
        _resolved_drop(root, target_relative_path),
        target_corpus,
        target_started_at,
        target_started_at_precision,
        target_has_recording=bool(has_recording),
    )
    _rearm_job(
        conn,
        job_id,
        relative,
        AUGMENTATION_STAGES if adds_recording else PARTICIPANT_AUGMENTATION_STAGES,
    )
    return JSONResponse(status_code=200, content={"jobId": str(job_id)})


@router.post(
    "/ingests",
    operation_id="createIngest",
    status_code=201,
    response_model=IngestResult,
    responses={
        200: {
            "model": IngestResult,
            "description": (
                "An existing job was re-queued in place rather than a new one"
                " opened — either the sourceId's only job had failed, or the drop"
                " declared `augments` and re-armed that occurrence's job so"
                " evidence the meeting lacked (a recording recovered later, or"
                " the source side's participant graph) is processed against the"
                " meeting that already exists (AD-14). The returned jobId is the"
                " existing one."
            ),
        },
        400: {"model": ProblemDetails, "content": {"application/problem+json": {}}},
        409: {"model": ProblemDetails, "content": {"application/problem+json": {}}},
        422: {"model": ProblemDetails, "content": {"application/problem+json": {}}},
        500: {"model": ProblemDetails, "content": {"application/problem+json": {}}},
    },
)
def create_ingest(body: IngestRequest, request: Request) -> Any:
    # This is deliberately the first request-level operation: an unreadable
    # changed schema must fail closed for *every* ingest, including one whose
    # path or metadata would otherwise be rejected as an invalid drop.
    schema = _validator()
    root = drops_root(request)
    drop_dir, relative = _validate_drop_path(body.drop_path, root)
    metadata = _load_metadata(drop_dir, schema)
    _check_evidence_present(drop_dir)

    source_id: str = metadata["sourceId"]
    corpus: str = metadata["corpus"]
    augments: dict[str, Any] | None = metadata.get("augments")
    pool = request.app.state.pool

    with pool.connection() as conn:
        if augments is not None:
            # Taken before the conflict raise below on purpose: the ordinary
            # augmenting drop is a video-bearing re-pull carrying the *same*
            # sourceId, so the target occurrence's live job is exactly the row
            # that would otherwise be reported as a duplicate.
            return _accept_augmenting_drop(conn, drop_dir, relative, metadata, root)

        rows = _select_jobs(conn, source_id)

        live = [row for row in rows if row[1] != "failed"]
        if live:
            raise _conflict(source_id, live[0][0])

        if rows:  # every job for this sourceId is failed — re-queue in place
            job_id = rows[0][0]
            meeting = _meeting_for_job(conn, job_id)
            if meeting is not None:
                (
                    target_relative_path,
                    target_corpus,
                    target_started_at,
                    target_started_at_precision,
                    target_has_recording,
                ) = meeting
                # Validate before changing the job, stage rows, or drop
                # reference. A recorded Meeting must retain a recording; a
                # transcript-only Meeting may still retry without one.
                _check_meeting_replacement(
                    drop_dir,
                    metadata,
                    _resolved_drop(root, target_relative_path),
                    target_corpus,
                    target_started_at,
                    target_started_at_precision,
                    target_has_recording=target_has_recording,
                )
            try:
                conn.execute(
                    "UPDATE job SET status = 'queued', error = NULL,"
                    " drop_relative_path = %s, drop_path = NULL, corpus = %s,"
                    " updated_at = now() WHERE id = %s",
                    (relative, corpus, job_id),
                )
                # Re-seed rather than reset in place, so the checkpoints always
                # match the current STAGE_NAMES even if the stage list changed.
                conn.execute("DELETE FROM job_stage WHERE job_id = %s", (job_id,))
                _seed_stages(conn, job_id)
            except psycopg.errors.UniqueViolation:
                # Lost a race: another request inserted a live job for this
                # sourceId between our SELECT and the UPDATE.
                conn.rollback()
                raise _conflict(source_id, _live_job_id(conn, source_id)) from None
            return JSONResponse(status_code=200, content={"jobId": str(job_id)})

        try:
            job_id = conn.execute(
                "INSERT INTO job (source_id, drop_relative_path, corpus)"
                " VALUES (%s, %s, %s) RETURNING id",
                (source_id, relative, corpus),
            ).fetchone()[0]
            _seed_stages(conn, job_id)
        except psycopg.errors.UniqueViolation:
            conn.rollback()
            raise _conflict(source_id, _live_job_id(conn, source_id)) from None

    return IngestResult(job_id=job_id)
