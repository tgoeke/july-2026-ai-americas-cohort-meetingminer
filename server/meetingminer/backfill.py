"""``backfill drop-paths``: convert pre-2.1a absolute paths to root-relative ones.

Story 2.1a made ``MM_DROPS_ROOT`` the anchor for every path to material that
*arrived*. Rows written before it hold three shapes that predate the rule:

* ``job.drop_path`` — the absolute drop directory intake stored verbatim;
* ``meeting_media`` — no recording path and no checksum at all, because the
  recording had no row of its own;
* ``transcript_source.drop_relative_path`` — a bare filename
  (``transcript.txt``), relative to the drop's own folder rather than to a
  root, which is the one thing a recorded path may never be
  (`storage-layout.md` §5).

This command converts all three in one pass, per job, inside one transaction.

**Fail closed.** Every row it cannot place under the configured root is printed
with its path and the command exits non-zero, so a partial backfill cannot look
like a clean one. Converted rows still commit — leaving a placeable row
unconverted to punish an unplaceable one would help nobody — but the exit code
and the report say exactly which rows still need a human.

**Idempotent.** A job already carrying a ``drop_relative_path`` is converted no
further, but the rows anchored to it — its transcripts, its recording — are
still checked, because the realistic upgrade order is migrate, restart the api,
backfill later, and intake anchors new jobs from the moment the api restarts.

**It repairs a worker that ran too early.** A worker started between the
migration and this command claims those jobs, finds no relative path, and fails
each one with :data:`~meetingminer.domain.jobs.UNBACKFILLED_DROP_PATH_ERROR`.
That must not cost an operator the jobs, so every job this command converts
that is sitting in ``failed`` with *exactly* that error goes back to ``queued``.
The match is equality against that one string and never ``status = 'failed'``
generally: a job that failed because ffprobe rejected its recording has nothing
to do with this and must stay failed.

Run it after ``make migrate``. Running it before starting the worker is tidier;
running it after costs a second invocation, not data:

    cd server && .venv/bin/python -m meetingminer.backfill drop-paths
    cd server && .venv/bin/python -m meetingminer.backfill drop-paths --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import psycopg
from psycopg import Connection

from meetingminer import db
from meetingminer.config import (
    CONFIG_PATH_ENV_VAR,
    ENV_PATH_ENV_VAR,
    AppConfig,
    ConfigError,
    load_config,
    require_drops_root,
)
from meetingminer.domain.drops import (
    RECORDING_FILENAME,
    DropContents,
    DropError,
    DropPathError,
    drop_relative_path,
    read_drop,
    resolve_drop_path,
    sha256_and_size,
)
from meetingminer.domain.jobs import UNBACKFILLED_DROP_PATH_ERROR

PROGRAM = "backfill"


@dataclass
class Report:
    """What one run did, and everything it could not do."""

    converted_jobs: list[tuple[str, str]] = field(default_factory=list)
    already_relative: int = 0
    converted_transcripts: int = 0
    converted_media: int = 0
    # Jobs a too-early worker had already failed, put back to `queued` here.
    requeued_jobs: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def _repository_config_path() -> Path:
    """Locate the checkout config for the installed development command."""
    return Path(__file__).resolve().parents[2] / "config.yaml"


def _load_cli_config() -> AppConfig:
    """Use repository defaults while retaining explicit environment overrides."""
    if os.environ.get(CONFIG_PATH_ENV_VAR):
        return load_config()
    root_config = _repository_config_path()
    env_path = os.environ.get(ENV_PATH_ENV_VAR) or root_config.with_name(".env")
    return load_config(root_config, env_path)


def _requeue_if_a_worker_failed_it_early(
    conn: Connection, job_id: object, report: Report, *, dry_run: bool
) -> None:
    """Put back a job a worker failed only because this command had not run.

    Matched on equality against :data:`UNBACKFILLED_DROP_PATH_ERROR` and on
    nothing looser. ``status = 'failed'`` would sweep up every unrelated
    failure in the table — a rejected recording, a drop that vanished — and
    re-queue work a human decided was finished.

    The UPDATE carries the predicate itself rather than trusting a value read a
    moment ago, so a job that failed for a different reason between the read
    and the write is not touched.
    """
    if dry_run:
        matched = conn.execute(
            "SELECT id FROM job WHERE id = %s AND status = 'failed' AND error = %s",
            (job_id, UNBACKFILLED_DROP_PATH_ERROR),
        ).fetchone()
    else:
        matched = conn.execute(
            "UPDATE job SET status = 'queued', error = NULL"
            " WHERE id = %s AND status = 'failed' AND error = %s RETURNING id",
            (job_id, UNBACKFILLED_DROP_PATH_ERROR),
        ).fetchone()
    if matched is not None:
        report.requeued_jobs.append(str(job_id))


def _backfill_transcripts(
    conn: Connection,
    job_id: object,
    relative: str,
    drops_root: Path,
    report: Report,
    *,
    dry_run: bool,
) -> None:
    """Widen this job's meeting's transcript paths to root-relative ones.

    A bare filename is recognised by having no ``/`` in it; a value that
    already names a directory is left untouched, so a second run converts
    nothing. The drop directory is the job's *current* one, which is the drop
    those rows were last parsed from — `align` rewrites them on every run.

    The widened path is resolved and required to be a file before it is
    written. The job may since have been re-armed onto a sibling drop that
    never carried this transcript form, and a confidently wrong path recorded
    as a success is exactly what the fail-closed contract exists to prevent.
    """
    rows = conn.execute(
        "SELECT ts.id, ts.kind, ts.drop_relative_path, ts.sha256, ts.byte_size"
        " FROM transcript_source ts"
        " JOIN meeting m ON m.id = ts.meeting_id"
        " WHERE m.job_id = %s AND ts.drop_relative_path IS NOT NULL",
        (job_id,),
    ).fetchall()
    for source_id, kind, stored, expected_digest, expected_size in rows:
        widened = stored if "/" in stored else f"{relative}/{stored}"
        try:
            transcript = resolve_drop_path(drops_root, widened)
            if not transcript.is_file():
                raise DropPathError("path is not a regular file")
            digest, actual_size = sha256_and_size(transcript)
        except (DropPathError, OSError, ValueError) as exc:
            report.problems.append(
                f"transcript_source {source_id} ({kind}): {widened!r} could not"
                f" be resolved under the drops root: {exc}"
            )
            continue
        if digest != expected_digest or actual_size != expected_size:
            report.problems.append(
                f"transcript_source {source_id} ({kind}): {widened!r} does not"
                " match its recorded sha256 and byte_size"
            )
            continue
        if widened != stored and not dry_run:
            conn.execute(
                "UPDATE transcript_source SET drop_relative_path = %s WHERE id = %s",
                (widened, source_id),
            )
        if widened != stored:
            report.converted_transcripts += 1


def _backfill_media(
    conn: Connection,
    job_id: object,
    relative: str,
    drops_root: Path,
    report: Report,
    *,
    dry_run: bool,
) -> None:
    """Record the recording's path and checksum for an already-ingested meeting.

    Only for a meeting whose ``has_recording`` is true and whose
    ``meeting_media`` row has no path yet. The checksum is computed here rather
    than deferred to the next `probe` run, because the point of the row is that
    a substitution becomes detectable — a row with a path and no checksum
    proves nothing.

    A recording that is missing, unreadable, or whose size disagrees with the
    ffprobe ``size_bytes`` already on the row is reported and not written: a
    checksum over bytes that do not match what was probed would be provenance
    for the wrong file.

    **LEFT JOIN, deliberately.** A meeting can be ``has_recording = true`` with
    no ``meeting_media`` row at all — a job whose `probe` never settled. An
    inner join answers "nothing to do" for exactly that meeting, which is the
    one whose replay stays a permanent 404 after a backfill that reported
    clean. It is a problem, not a silence.
    """
    row = conn.execute(
        "SELECT m.id, mm.meeting_id, mm.size_bytes, mm.drop_relative_path, mm.sha256"
        " FROM meeting m LEFT JOIN meeting_media mm ON mm.meeting_id = m.id"
        " WHERE m.job_id = %s AND m.has_recording",
        (job_id,),
    ).fetchone()
    if row is None:
        # No meeting for this job at all: the worker never minted one. Nothing
        # claims to have a recording, so there is nothing to record.
        return
    meeting_id, media_meeting_id, size_bytes, existing_relative, existing_digest = row
    if media_meeting_id is None:
        report.problems.append(
            f"meeting {meeting_id}: has_recording is true but there is no"
            " meeting_media row to anchor the recording to — re-run the job's"
            " `probe` stage, or the meeting's replay will stay a 404"
        )
        return
    recording_relative = existing_relative or f"{relative}/{RECORDING_FILENAME}"
    try:
        recording = resolve_drop_path(drops_root, recording_relative)
        if not recording.is_file():
            raise DropPathError("path is not a regular file")
        digest, actual_size = sha256_and_size(recording)
    except (DropPathError, OSError, ValueError) as exc:
        report.problems.append(
            f"meeting {meeting_id}: recording {recording_relative!r} could not be"
            f" read for checksumming: {exc}"
        )
        return
    if existing_relative is not None:
        if existing_digest != digest or size_bytes != actual_size:
            report.problems.append(
                f"meeting {meeting_id}: recording {recording_relative!r} does not"
                " match its recorded sha256 and size_bytes"
            )
        return
    if size_bytes is not None and size_bytes != actual_size:
        report.problems.append(
            f"meeting {meeting_id}: recording {recording_relative!r} is"
            f" {actual_size} bytes but ffprobe recorded {size_bytes} — the file"
            " on disk is not the one that was probed"
        )
        return
    if not dry_run:
        conn.execute(
            "UPDATE meeting_media SET drop_relative_path = %s, sha256 = %s,"
            " size_bytes = %s WHERE meeting_id = %s",
            (recording_relative, digest, actual_size, meeting_id),
        )
    report.converted_media += 1


def _validate_current_drop(
    drops_root: Path, relative: str, *, config_path: Path | None
) -> DropContents:
    """Require a real, schema-valid source drop before anchoring it.

    ``drop_relative_path`` deliberately only answers containment; a file or a
    malformed directory below the root is contained but is not evidence.  The
    backfill has to make the same read-only validation the worker will make,
    otherwise it can report a conversion that immediately fails at claim.
    """
    drop_dir = resolve_drop_path(drops_root, relative)
    return read_drop(drop_dir, config_path=config_path)


def backfill_drop_paths(
    conn: Connection,
    drops_root: Path,
    *,
    dry_run: bool = False,
    config_path: Path | None = None,
) -> Report:
    """Convert every job's drop path, and the rows anchored to it, in place."""
    report = Report()
    # Enumerate identities only.  Each row is fetched and locked below, after
    # any concurrent re-arm that happened while this command was walking the
    # table has committed.  Never convert a stale drop_path snapshot over the
    # current sibling-drop anchor.
    jobs = conn.execute(
        "SELECT id FROM job ORDER BY created_at"
    ).fetchall()
    for (job_id,) in jobs:
        current = conn.execute(
            "SELECT id, source_id, corpus, drop_path, drop_relative_path"
            " FROM job WHERE id = %s FOR UPDATE",
            (job_id,),
        ).fetchone()
        if current is None:  # a concurrent delete won before the lock
            continue
        _, source_id, corpus, absolute, relative = current
        legacy = relative is None
        if relative is not None:
            # Already anchored — by intake after the api restarted, or by an
            # earlier run of this command. The job needs nothing, but the rows
            # hanging off it may: that is the realistic upgrade order, so the
            # two converters below run either way.
            report.already_relative += 1
        else:
            if absolute is None:  # pragma: no cover - the CHECK forbids it
                report.problems.append(f"job {job_id}: has neither drop path")
                continue
            try:
                if Path(absolute).is_symlink():
                    raise DropPathError("legacy drop directory is a symbolic link")
                relative = drop_relative_path(drops_root, Path(absolute))
            except (DropPathError, OSError, ValueError) as exc:
                report.problems.append(f"job {job_id}: {absolute}: {exc}")
                continue
        try:
            drop = _validate_current_drop(drops_root, relative, config_path=config_path)
        except (DropError, OSError, ValueError) as exc:
            report.problems.append(
                f"job {job_id}: drop {relative!r} is not a usable source drop: {exc}"
            )
            continue
        if drop.source_id != source_id or drop.corpus != corpus:
            report.problems.append(
                f"job {job_id}: drop {relative!r} declares sourceId"
                f" {drop.source_id!r} and corpus {drop.corpus!r}, but the locked"
                f" job has source_id {source_id!r} and corpus {corpus!r}"
            )
            continue

        problems_before_validation = len(report.problems)
        _backfill_transcripts(
            conn, job_id, relative, drops_root, report, dry_run=dry_run
        )
        _backfill_media(conn, job_id, relative, drops_root, report, dry_run=dry_run)

        # A legacy job is only anchored after every row underneath it has
        # passed validation.  Otherwise a too-early worker failure would be
        # requeued onto a drop whose provenance is already known bad, making a
        # hard upgrade failure look recoverable.
        if legacy and len(report.problems) == problems_before_validation:
            if not dry_run:
                conn.execute(
                    "UPDATE job SET drop_relative_path = %s, drop_path = NULL"
                    " WHERE id = %s AND drop_relative_path IS NULL",
                    (relative, job_id),
                )
            report.converted_jobs.append((str(job_id), relative))
            _requeue_if_a_worker_failed_it_early(conn, job_id, report, dry_run=dry_run)
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description=(
            "Convert pre-2.1a absolute and drop-relative paths to paths"
            " anchored to MM_DROPS_ROOT."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    drop_paths = sub.add_parser(
        "drop-paths",
        help=(
            "convert job.drop_path, widen transcript_source.drop_relative_path,"
            " and record the recording's path and checksum on meeting_media."
        ),
    )
    drop_paths.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be converted and write nothing.",
    )
    return parser


def _report(report: Report, dry_run: bool) -> None:
    verb = "would convert" if dry_run else "converted"
    requeued_verb = "would re-queue" if dry_run else "re-queued"
    for job_id, relative in report.converted_jobs:
        print(f"job {job_id} -> {relative}")
    for job_id in report.requeued_jobs:
        print(
            f"job {job_id} {requeued_verb}"
            " (a worker had failed it for the missing drop path)"
        )
    for problem in report.problems:
        print(f"UNPLACEABLE {problem}", file=sys.stderr)
    print(
        f"{PROGRAM}: {verb} {len(report.converted_jobs)} job(s),"
        f" {report.converted_transcripts} transcript path(s),"
        f" {report.converted_media} recording row(s);"
        f" {requeued_verb} {len(report.requeued_jobs)} job(s) a worker had"
        " failed for the missing drop path;"
        f" {report.already_relative} job(s) already anchored;"
        f" {len(report.problems)} row(s) could not be placed under the drops root"
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    try:
        config = _load_cli_config()
        drops_root = require_drops_root(config)
    except ConfigError as exc:
        print(f"fatal: {PROGRAM} aborted: {exc}", file=sys.stderr)
        return 1

    try:
        with psycopg.connect(db.conninfo(config), connect_timeout=10) as conn:
            db.check_migrations_current(conn)
            report = backfill_drop_paths(
                conn,
                drops_root,
                dry_run=args.dry_run,
                config_path=config.config_path,
            )
            if args.dry_run:
                conn.rollback()
    except (db.MigrationsPendingError, db.MigrationError) as exc:
        print(f"fatal: {PROGRAM} aborted: {exc}", file=sys.stderr)
        return 1
    except psycopg.OperationalError as exc:
        print(f"fatal: {PROGRAM} aborted: database unreachable: {exc}", file=sys.stderr)
        return 1
    except psycopg.Error as exc:
        print(f"fatal: {PROGRAM} aborted: database error: {exc}", file=sys.stderr)
        return 1

    _report(report, args.dry_run)
    # Non-zero on any unplaceable row, so a partial backfill cannot be mistaken
    # for a clean one by a script or by a human reading only the last line.
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
