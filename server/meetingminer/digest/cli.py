"""``digest``: write one example Morning Digest email from Postgres alone (FR31).

Read-only sibling to `meetingminer.projections.cli`'s `rebuild`: same config
load, same `psycopg.connect` + `db.check_migrations_current` startup gate,
same `fatal: ... aborted: ...` stderr convention on failure. It demonstrates
the Morning Digest concept without a delivery mechanism — no SMTP, no
scheduler, no per-recipient filtering, no "yesterday's meetings" windowing.
One file per run, at the path a required `--output PATH` names; there is no
default path and no new config/env key, mirroring `rebuild`'s refusal of an
implicit scope.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

import psycopg

from meetingminer import db
from meetingminer.config import (
    CONFIG_PATH_ENV_VAR,
    ENV_PATH_ENV_VAR,
    ConfigError,
    load_config,
)
from meetingminer.digest.generator import read_published_artifacts, render_digest

PROGRAM = "digest"


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
            "Write one example Morning Digest email from every published"
            " artifact in Postgres, demonstrating FR31 without a delivery"
            " mechanism."
        ),
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        default=None,
        help=(
            "write the example digest to this path. Required — there is no"
            " default path and no new config key, so a mistyped invocation"
            " can never land a file somewhere unnoticed."
        ),
    )
    return parser


def _write_digest(output_path: Path, text: str) -> None:
    """Publish a complete digest at ``output_path`` without corrupting an old one."""
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(text)
        temporary_path.replace(output_path)
    except OSError:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except (FileNotFoundError, OSError):
                pass
        raise


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    if not args.output:
        # No implicit output path. Unlike `rebuild --all`, this CLI has no
        # destructive default to protect against — but a silent default (a
        # hidden repo-relative file, say) risks landing in the git tree
        # unnoticed. Requiring `--output` keeps the generator's only side
        # effect explicit.
        print(
            f"fatal: {PROGRAM} aborted: --output PATH is required",
            file=sys.stderr,
        )
        return 2

    try:
        config = _load_cli_config()
    except ConfigError as exc:
        print(f"fatal: {PROGRAM} aborted: {exc}", file=sys.stderr)
        return 1

    try:
        with psycopg.connect(db.conninfo(config), connect_timeout=10) as conn:
            db.check_migrations_current(conn)
            meetings = read_published_artifacts(conn)
    except (db.MigrationsPendingError, db.MigrationError) as exc:
        print(f"fatal: {PROGRAM} aborted: {exc}", file=sys.stderr)
        return 1
    except psycopg.OperationalError as exc:
        print(f"fatal: {PROGRAM} aborted: database unreachable: {exc}", file=sys.stderr)
        return 1
    except psycopg.Error as exc:
        print(f"fatal: {PROGRAM} aborted: database error: {exc}", file=sys.stderr)
        return 1

    text = render_digest(meetings)
    output_path = Path(args.output)
    try:
        _write_digest(output_path, text)
    except OSError as exc:
        print(f"fatal: {PROGRAM} aborted: could not write {output_path}: {exc}", file=sys.stderr)
        return 1

    print(f"{PROGRAM}: wrote {len(meetings)} meeting(s) to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
