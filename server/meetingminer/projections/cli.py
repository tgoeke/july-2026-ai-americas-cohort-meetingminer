"""``rebuild``: regenerate both retrieval stores from Postgres + config (FR24).

AD-4's answer to a corrupt or drifted store is this command, never a hand
edit of an index. It is also how an embedder swap lands (AD-8) and how a
chunking retune lands (`retrieval-prior-art.md` §6) — both invalidate every
projected document, and both are config edits followed by ``rebuild --all``.

**When to run it.** After an embedder swap or a chunking retune in
``config.yaml`` (both invalidate every projected vector and every chunk
boundary); after wiping or losing a store volume; and any time a store's
content is suspect — AD-4's answer to corruption is regeneration, never a hand
edit. Routine ingestion needs none of this: the worker projects each meeting
as its evidence completes.

**Prerequisite for the embedding pass.** The model named by ``embedder.model``
must be pulled on the local Ollama host (``ollama pull qwen3-embedding:0.6b``
for the shipped binding). Without it the structural pass still succeeds and
the corpus stays BM25-searchable — see ``--structural-only``.

Startup is the same sequence of gates the worker uses: config loads, then
migrations are current. Failures are named errors on stderr with a non-zero
exit and no traceback.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from uuid import UUID

import psycopg

from meetingminer import db
from meetingminer.adapters.embed import EmbedderError
from meetingminer.config import (
    CONFIG_PATH_ENV_VAR,
    ENV_PATH_ENV_VAR,
    ConfigError,
    load_config,
)
from meetingminer.projections import RebuildReport, rebuild
from meetingminer.projections.stores import ProjectionError

PROGRAM = "rebuild"


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
            "Regenerate the Neo4j and Meilisearch projections from Postgres"
            " and config.yaml alone."
        ),
    )
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument(
        "--all",
        action="store_true",
        help=(
            "every meeting whose evidence is complete. Required for a"
            " corpus-wide run, because a structural one drops both stores"
            " first so no orphan node or document survives — the flag is what"
            " makes that deliberate rather than what you get by typing"
            " 'rebuild'. Harmless with --embed-only, which drops nothing."
        ),
    )
    scope.add_argument(
        "--meeting",
        metavar="UUID",
        action="append",
        default=[],
        help=(
            "project only this meeting (repeatable). Scoped to that meetingId;"
            " no other meeting's rows are touched and nothing is dropped."
        ),
    )
    pass_choice = parser.add_mutually_exclusive_group()
    pass_choice.add_argument(
        "--embed-only",
        action="store_true",
        help=(
            "compute and write vectors for meetings that are already"
            " structurally projected; no structural rewrite, nothing dropped."
        ),
    )
    pass_choice.add_argument(
        "--structural-only",
        action="store_true",
        help=(
            "write nodes and documents with no model call at all — the pass"
            " that works with the Ollama host down."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be projected and touch nothing.",
    )
    return parser


def _parse_meetings(values: list[str]) -> list[UUID]:
    parsed: list[UUID] = []
    for value in values:
        try:
            parsed.append(UUID(value))
        except ValueError as exc:
            raise ValueError(f"--meeting {value!r} is not a UUID") from exc
    return parsed


def _report(report: RebuildReport, dry_run: bool) -> None:
    """Print the per-meeting outcome then the summary line."""
    for outcome in report.outcomes:
        if outcome.skipped_reason:
            state = f"skipped ({outcome.skipped_reason})"
        elif outcome.embedded:
            state = "structural+embedded" if outcome.structural else "embedded"
        elif outcome.structural:
            state = "structural"
        else:
            state = "no-op"
        line = (
            f"{outcome.meeting_id} {state}"
            f" moments={outcome.moment_documents} chunks={outcome.chunk_documents}"
            f" artifacts={outcome.artifact_documents}"
        )
        if outcome.warning:
            line += f" — {outcome.warning}"
        print(line)
    for meeting_id, error in report.failures:
        print(f"{meeting_id} FAILED — {error}", file=sys.stderr)

    verb = "would project" if dry_run else "projected"
    print(
        f"{PROGRAM}: {verb} {len(report.outcomes)} meeting(s);"
        f" structural {report.projected}, embedded {report.embedded},"
        f" failed {len(report.failures)}"
        + ("; both stores were dropped first" if report.dropped else "")
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    if not args.all and not args.meeting:
        # No implicit corpus-wide run. `--all` drops both stores before it
        # rewrites them, and that is not something a bare `rebuild` should do
        # to a developer who mistyped a flag.
        print(
            f"fatal: {PROGRAM} aborted: choose a scope — '--all' for every"
            " meeting whose evidence is complete (drops both stores first), or"
            " '--meeting <uuid>' for one meeting (drops nothing)",
            file=sys.stderr,
        )
        return 2

    try:
        meetings = _parse_meetings(args.meeting)
    except ValueError as exc:
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
            report = rebuild(
                conn,
                config,
                meeting_ids=meetings or None,
                embed_only=args.embed_only,
                structural_only=args.structural_only,
                dry_run=args.dry_run,
                log=_log,
            )
    except (db.MigrationsPendingError, db.MigrationError) as exc:
        print(f"fatal: {PROGRAM} aborted: {exc}", file=sys.stderr)
        return 1
    except psycopg.OperationalError as exc:
        print(f"fatal: {PROGRAM} aborted: database unreachable: {exc}", file=sys.stderr)
        return 1
    except (ProjectionError, EmbedderError) as exc:
        # Named refusals land here: a held lock, a dimension mismatch, a store
        # that is down. Refusals raised *before* the run starts wrote nothing;
        # this is not a general "nothing was written" guarantee, and two paths
        # break it. An `--all` run that raises after `drop_all` leaves both
        # stores empty (rerun `rebuild --all` — the drop is the first thing it
        # does anyway), and a fatal embedder error is raised after the
        # structural rows for that meeting are already committed, which is why
        # its message says so.
        print(f"fatal: {PROGRAM} aborted: {exc}", file=sys.stderr)
        return 1
    except psycopg.Error as exc:
        print(f"fatal: {PROGRAM} aborted: database error: {exc}", file=sys.stderr)
        return 1

    _report(report, args.dry_run)
    return 0 if report.ok else 1


def _log(event: str, **fields: object) -> None:
    """Progress lines on stderr, so stdout stays the per-meeting report."""
    detail = " ".join(f"{key}={value}" for key, value in fields.items())
    print(f"{event} {detail}".rstrip(), file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
