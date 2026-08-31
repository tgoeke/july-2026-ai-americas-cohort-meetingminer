"""``derive-threads`` — run the thread derivation over the whole corpus.

Story 10.2 built :func:`meetingminer.domain.threads.derive_threads` and the two
tables migration 0015 declares, but nothing in the running system called it: no
pipeline stage, no api route, no console script. Topics accumulated per meeting
from the `extract` stage while ``thread`` and ``topic_thread`` stayed empty, so
every thread-shaped surface read a corpus that had no threads in it. This is
the missing caller.

**Why it is its own command rather than part of ``rebuild``.** ``rebuild``
regenerates Neo4j and Meilisearch *from Postgres*, and states that contract in
its own docstring and in the README. Threading is the other direction: it
derives new primary rows and writes them **into** Postgres, which the graph
then reads back through ``projections/evidence.py``. Folding it into
``rebuild`` would make that command a Postgres writer and quietly break the
promise that a rebuild can be run at any time without changing primary data.

**So the order is: ingest, then ``make threads``, then ``make rebuild``.**
Threading first, because a moment's ``thread_id`` is null until it has run and
the graph projection copies whatever it finds at the time it runs.

Corpus-wide by construction: a thread is a subject followed *across* meetings,
so there is no per-meeting scope to offer. Idempotent by construction too — an
unchanged rerun writes nothing, not even ``updated_at`` — which is what makes
it safe to run again after every ingest.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg

from meetingminer import db
from meetingminer.adapters.embed import EmbedderError, build_embedder
from meetingminer.config import (
    CONFIG_PATH_ENV_VAR,
    ENV_PATH_ENV_VAR,
    ConfigError,
    load_config,
)
from meetingminer.domain.threads import ThreadDerivationError, derive_threads

PROGRAM = "derive-threads"


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
            "Derive threads from the stored topics, corpus-wide. Run after an"
            " ingest and before 'rebuild', because a moment's thread is null"
            " until this has run."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Read, embed and partition, then roll back instead of committing."
            " Reports what a real run would write."
        ),
    )
    return parser


def _log(event: str, **fields: object) -> None:
    """Progress lines on stderr, so stdout stays the report."""
    detail = " ".join(f"{key}={value}" for key, value in fields.items())
    print(f"{PROGRAM}: {event} {detail}".rstrip(), file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    try:
        config = _load_cli_config()
    except ConfigError as exc:
        print(f"fatal: {PROGRAM} aborted: {exc}", file=sys.stderr)
        return 1

    try:
        # Constructed up front: an embedder that cannot be *built* is a config
        # error, and there is no point opening a transaction to discover it.
        embedder = build_embedder(config)
    except EmbedderError as exc:
        print(f"fatal: {PROGRAM} aborted: {exc}", file=sys.stderr)
        return 1

    try:
        with psycopg.connect(db.conninfo(config), connect_timeout=10) as conn:
            db.check_migrations_current(conn)
            report = derive_threads(conn, config, embedder=embedder, log=_log)
            if args.dry_run:
                # derive_threads never commits — the caller owns the
                # transaction — so a rollback here is the whole dry run.
                conn.rollback()
    except (db.MigrationsPendingError, db.MigrationError) as exc:
        print(f"fatal: {PROGRAM} aborted: {exc}", file=sys.stderr)
        return 1
    except psycopg.OperationalError as exc:
        print(f"fatal: {PROGRAM} aborted: database unreachable: {exc}", file=sys.stderr)
        return 1
    except (ThreadDerivationError, EmbedderError) as exc:
        # The derivation reads, embeds and partitions before it writes
        # anything, so a model host that is down raises here having touched no
        # rows. It never falls back to threading by name alone.
        print(f"fatal: {PROGRAM} aborted: {exc}", file=sys.stderr)
        return 1
    except psycopg.Error as exc:
        print(f"fatal: {PROGRAM} aborted: database error: {exc}", file=sys.stderr)
        return 1

    verb = "would derive" if args.dry_run else "derived"
    print(
        f"{PROGRAM}: {verb} {report.thread_count} thread(s) from"
        f" {report.topic_count} topic(s);"
        f" {report.name_links} name link(s),"
        f" {report.embedding_links} embedding link(s)"
    )
    return 0
