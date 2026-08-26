"""Postgres access + numbered-SQL migration mechanism.

Migrations are plain ``.sql`` files in ``server/meetingminer/migrations/``, named
``NNNN_description.sql`` and applied in filename order. Applied filenames are
recorded in ``schema_migrations``; ``apply_migrations`` is idempotent (a
second run is a no-op). Both the api and the worker refuse to boot while
migrations are pending (:class:`MigrationsPendingError` — named error, no
traceback, matching the config fail-fast contract).

Run ``python -m meetingminer.db migrate`` (or ``make migrate``) to apply
pending migrations.
"""

from __future__ import annotations

import sys
from pathlib import Path

import psycopg
from psycopg import Connection
from psycopg_pool import ConnectionPool

from meetingminer.config import AppConfig, ConfigError, load_config

# __file__-relative is correct here (unlike config.yaml anchoring): the
# migrations directory lives inside this package and ships with the wheel.
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


class MigrationError(RuntimeError):
    """Raised when the migration mechanism itself fails (bad file, SQL error)."""


class MigrationsPendingError(RuntimeError):
    """Raised at startup when unapplied migrations exist — run `make migrate`."""

    def __init__(self, pending: list[str]) -> None:
        self.pending = pending
        names = ", ".join(pending)
        super().__init__(
            f"{len(pending)} pending database migration(s): {names} — run 'make migrate'"
        )


def conninfo(config: AppConfig, database: str | None = None) -> str:
    """Build a psycopg conninfo string from config.yaml + the .env password."""
    pg = config.settings.stores.postgres
    return psycopg.conninfo.make_conninfo(
        host=pg.host,
        port=pg.port,
        dbname=database or pg.database,
        user=pg.user,
        password=config.secrets.postgres_password,
    )


def create_pool(config: AppConfig, database: str | None = None) -> ConnectionPool:
    """Create a (closed) connection pool; callers open/close it explicitly."""
    return ConnectionPool(
        conninfo=conninfo(config, database=database),
        min_size=1,
        max_size=4,
        open=False,
        name="meetingminer",
    )


def migration_files(migrations_dir: Path = MIGRATIONS_DIR) -> list[Path]:
    """The numbered .sql files, in application order.

    A missing directory is a named error, never an empty list — otherwise the
    boot gates would pass against a schemaless database.
    """
    if not migrations_dir.is_dir():
        raise MigrationError(f"migrations directory not found: {migrations_dir}")
    return sorted(p for p in migrations_dir.glob("*.sql") if p.is_file())


def _applied_migrations(conn: Connection) -> set[str]:
    row_exists = conn.execute(
        "SELECT 1 FROM information_schema.tables"
        " WHERE table_schema = 'public' AND table_name = 'schema_migrations'"
    ).fetchone()
    if row_exists is None:
        return set()
    rows = conn.execute("SELECT filename FROM schema_migrations").fetchall()
    return {row[0] for row in rows}


def pending_migrations(
    conn: Connection, migrations_dir: Path = MIGRATIONS_DIR
) -> list[str]:
    """Filenames of migrations not yet recorded in schema_migrations, in order."""
    applied = _applied_migrations(conn)
    return [p.name for p in migration_files(migrations_dir) if p.name not in applied]


def apply_migrations(
    conn: Connection, migrations_dir: Path = MIGRATIONS_DIR
) -> list[str]:
    """Apply every pending migration in order; returns the filenames applied.

    Each migration runs in its own transaction together with its
    schema_migrations record, so a failure leaves no half-recorded state.
    A session-level advisory lock serializes concurrent migrate runs.
    """
    conn.execute("SELECT pg_advisory_lock(hashtext('meetingminer_migrations'))")
    conn.commit()
    try:
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " filename text PRIMARY KEY,"
                " applied_at timestamptz NOT NULL DEFAULT now()"
                ")"
            )
            conn.commit()
        except psycopg.Error as exc:
            conn.rollback()
            raise MigrationError(
                f"could not ensure schema_migrations table: {exc}"
            ) from exc

        applied: list[str] = []
        for path in migration_files(migrations_dir):
            if path.name in _applied_migrations(conn):
                continue
            try:
                conn.execute(path.read_text(encoding="utf-8"))
                conn.execute(
                    "INSERT INTO schema_migrations (filename) VALUES (%s)", (path.name,)
                )
                conn.commit()
            except (psycopg.Error, OSError, UnicodeDecodeError) as exc:
                conn.rollback()
                raise MigrationError(f"migration {path.name} failed: {exc}") from exc
            applied.append(path.name)
        return applied
    finally:
        try:
            conn.execute(
                "SELECT pg_advisory_unlock(hashtext('meetingminer_migrations'))"
            )
            conn.commit()
        except psycopg.Error:
            pass  # a broken session releases the lock on disconnect anyway


def check_migrations_current(conn: Connection) -> None:
    """Raise :class:`MigrationsPendingError` if any migration is unapplied."""
    pending = pending_migrations(conn)
    if pending:
        raise MigrationsPendingError(pending)


def _cli_migrate() -> int:
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"fatal: migrate aborted: {exc}", file=sys.stderr)
        return 1
    try:
        with psycopg.connect(conninfo(config)) as conn:
            applied = apply_migrations(conn)
    except (psycopg.Error, MigrationError) as exc:
        print(f"fatal: migrate aborted: {exc}", file=sys.stderr)
        return 1
    if applied:
        for name in applied:
            print(f"applied {name}")
    else:
        print("nothing to apply — database is up to date")
    return 0


def main(argv: list[str]) -> int:
    if argv == ["migrate"]:
        return _cli_migrate()
    print("usage: python -m meetingminer.db migrate", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
