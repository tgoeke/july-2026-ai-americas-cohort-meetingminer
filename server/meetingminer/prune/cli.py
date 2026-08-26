"""``prune``: delete every meeting outside an explicitly named keep-set.

The command exists because the corpus is not append-only forever: material
gathered under one set of expectations (a client's real meetings) has to be
removable when the corpus moves to another (an owned sandbox), and there is
no other way to take a meeting out of this system.

It is built to be hard to fire by accident. A bare ``prune`` refuses: the
keep-set is always explicit, never inferred, and reporting is the default
while deleting takes ``--delete`` — the same posture ``rebuild`` takes toward
its own corpus-wide drop. What it will remove is printed in full before it
removes anything, including the source drops it is *not* touching.

Startup mirrors ``rebuild``: config loads, migrations are checked, failures
are named errors on stderr with a non-zero exit and no traceback.

After a purge, both projection stores still describe the old corpus. Run
``make rebuild`` — the command says so on the way out rather than leaving it
to be remembered.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from uuid import UUID

import psycopg

from meetingminer import db
from meetingminer.config import (
    CONFIG_PATH_ENV_VAR,
    ENV_PATH_ENV_VAR,
    ConfigError,
    load_config,
)
from meetingminer.prune import (
    COUNTED_TABLES,
    PruneError,
    PurgePlan,
    PurgeReport,
    execute_purge,
    plan_purge,
    resolve_scope,
    stale_orphans,
)
from meetingminer.prune.files import (
    PublishRemovalError,
    remove_content_dirs,
    remove_drops,
    remove_published_files,
)

PROGRAM = "prune"


def _repository_config_path() -> Path:
    """Locate the checkout config for the installed development command."""
    return Path(__file__).resolve().parents[3] / "config.yaml"


def _load_cli_config():
    """Use repository defaults while retaining explicit environment overrides."""
    if os.environ.get(CONFIG_PATH_ENV_VAR):
        return load_config()
    root_config = _repository_config_path()
    env_path = os.environ.get(ENV_PATH_ENV_VAR) or root_config.with_name(".env")
    return load_config(root_config, env_path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description=(
            "Delete every meeting outside the keep-set, with the evidence,"
            " produced content and published documents derived from it."
        ),
    )
    parser.add_argument(
        "--keep",
        metavar="UUID",
        action="append",
        default=[],
        help="keep this meeting (repeatable). Combines with --keep-corpus.",
    )
    parser.add_argument(
        "--keep-corpus",
        metavar="NAME",
        action="append",
        default=[],
        help=(
            "keep every meeting in this corpus, e.g. 'scripted' (repeatable)."
            " Combines with --keep."
        ),
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help=(
            "actually delete. Without it the command reports what it would"
            " remove and writes nothing — the report is the default because"
            " none of this is recoverable from inside the application."
        ),
    )
    parser.add_argument(
        "--sweep-orphans",
        action="store_true",
        help=(
            "also delete screens and participants that were ALREADY"
            " unreferenced before this run — the rows a participant merge or"
            " an earlier deletion left behind. Off by default because those"
            " rows are not this purge's to judge; on when the point is that"
            " no trace of the old corpus survives."
        ),
    )
    parser.add_argument(
        "--drops",
        action="store_true",
        help=(
            "also delete each purged meeting's source drop under"
            " MM_DROPS_ROOT. Write-once arrived material that nothing"
            " reproduces: without this flag a purged meeting can still be"
            " re-ingested, and with it, it cannot."
        ),
    )
    return parser


def _parse_keep(values: list[str]) -> list[UUID]:
    parsed: list[UUID] = []
    for value in values:
        try:
            parsed.append(UUID(value))
        except ValueError as exc:
            raise PruneError(f"--keep {value!r} is not a UUID") from exc
    return parsed


def _report_plan(
    plan: PurgePlan, *, delete: bool, drops: bool, sweep_orphans: bool, stale: int
) -> None:
    verb = "purging" if delete else "would purge"
    print(f"{PROGRAM}: {verb} {len(plan.purge_ids)} meeting(s):")
    for meeting_id in plan.purge_ids:
        print(f"  {meeting_id}  {plan.titles.get(meeting_id, '(untitled)')}")

    print("rows:")
    for table in COUNTED_TABLES:
        count = plan.row_counts.get(table, 0)
        if count:
            print(f"  {table:22} {count}")
    if plan.orphan_screen_ids:
        print(f"  {'screen (orphaned)':22} {len(plan.orphan_screen_ids)}")
    if plan.orphan_participant_ids:
        print(f"  {'participant (orphaned)':22} {len(plan.orphan_participant_ids)}")
    if not sweep_orphans:
        if stale:
            print(
                f"note: {stale} screen/participant row(s) were already"
                " unreferenced before this purge and are being KEPT."
                " Pass --sweep-orphans to delete them too."
            )

    if plan.content_dirs:
        print(f"content directories ({len(plan.content_dirs)}):")
        for directory in plan.content_dirs:
            print(f"  {directory}{'' if directory.is_dir() else '  (already absent)'}")
    if plan.published_files:
        print(f"published documents ({len(plan.published_files)}):")
        for published in plan.published_files:
            print(f"  {published.relative_path}")
    if plan.drop_paths:
        fate = "DELETING" if drops else "keeping (pass --drops to delete)"
        print(f"source drops ({len(plan.drop_paths)}) — {fate}:")
        for relative in plan.drop_paths:
            print(f"  {relative}")


def _report_result(report: PurgeReport) -> None:
    deleted = ", ".join(
        f"{table} {count}" for table, count in report.deleted_rows.items() if count
    )
    print(f"{PROGRAM}: deleted {deleted or 'no rows'}")
    if report.removed_dirs:
        print(f"{PROGRAM}: removed {len(report.removed_dirs)} directory(ies)")
    if report.absent_dirs:
        print(f"{PROGRAM}: {len(report.absent_dirs)} directory(ies) were already absent")
    if report.removed_files:
        print(f"{PROGRAM}: removed {len(report.removed_files)} published document(s)")
    if report.absent_files:
        print(f"{PROGRAM}: {len(report.absent_files)} published document(s) were already absent")
    if report.commit_sha:
        print(f"{PROGRAM}: publish repo commit {report.commit_sha}")
    print(
        f"{PROGRAM}: the projection stores still describe the old corpus —"
        " run 'make rebuild' next"
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    if not args.keep and not args.keep_corpus:
        # No implicit keep-set. An unscoped run would mean "delete the whole
        # corpus", which is never what a mistyped flag should reach.
        print(
            f"fatal: {PROGRAM} aborted: name what to keep — '--keep <uuid>'"
            " (repeatable) or '--keep-corpus <name>', e.g."
            " '--keep-corpus scripted'",
            file=sys.stderr,
        )
        return 2

    try:
        keep_ids = _parse_keep(args.keep)
    except PruneError as exc:
        print(f"fatal: {PROGRAM} aborted: {exc}", file=sys.stderr)
        return 2

    try:
        config = _load_cli_config()
    except ConfigError as exc:
        print(f"fatal: {PROGRAM} aborted: {exc}", file=sys.stderr)
        return 1

    try:
        with psycopg.connect(db.conninfo(config), connect_timeout=10) as conn:
            db.check_migrations_current(conn)
            keep, purge = resolve_scope(
                conn, keep_ids=keep_ids, keep_corpus=args.keep_corpus
            )
            plan = plan_purge(conn, config, purge, sweep_orphans=args.sweep_orphans)
            print(f"{PROGRAM}: keeping {len(keep)} meeting(s)")
            _report_plan(
                plan,
                delete=args.delete,
                drops=args.drops,
                sweep_orphans=args.sweep_orphans,
                stale=stale_orphans(conn, purge),
            )

            if not args.delete:
                conn.rollback()
                print(
                    f"{PROGRAM}: dry run — nothing was written."
                    " Re-run with --delete to apply."
                )
                return 0

            report = PurgeReport(plan=plan)
            report.deleted_rows = execute_purge(conn, plan)
            conn.commit()
    except PruneError as exc:
        print(f"fatal: {PROGRAM} aborted: {exc}", file=sys.stderr)
        return 2
    except (db.MigrationsPendingError, db.MigrationError) as exc:
        print(f"fatal: {PROGRAM} aborted: {exc}", file=sys.stderr)
        return 1
    except psycopg.OperationalError as exc:
        print(f"fatal: {PROGRAM} aborted: database unreachable: {exc}", file=sys.stderr)
        return 1
    except psycopg.Error as exc:
        print(f"fatal: {PROGRAM} aborted: database error: {exc}", file=sys.stderr)
        return 1

    # Past this point the rows are gone and committed. A filesystem failure is
    # reported as a resumable leftover, never as "the purge failed".
    remove_content_dirs(plan, report)
    try:
        remove_published_files(config.secrets.mm_publish_root, plan, report)
    except PublishRemovalError as exc:
        print(f"{PROGRAM}: rows deleted, but {exc}", file=sys.stderr)
        _report_result(report)
        return 1
    if args.drops:
        remove_drops(config.secrets.mm_drops_root, list(plan.drop_paths), report)

    _report_result(report)
    return 0
