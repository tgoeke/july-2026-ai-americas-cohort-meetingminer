"""Migration runner idempotency + boot gates (fail-fast and success paths).

Subprocess tests follow the test_failfast.py pattern: temp config via
MM_CONFIG_PATH, real .env via MM_ENV_PATH, assert named errors and no
traceback. DB-backed tests need the compose Postgres (named skip otherwise);
the unreachable-database tests deliberately need no Postgres at all.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Iterator

import psycopg
import pytest
import yaml

from meetingminer import db
from meetingminer.config import AppConfig, load_config

from conftest import (
    RUN_ID,
    cleanup_owned_database,
    create_owned_database,
    database_owner_lock,
    drop_owned_database,
)
from repo_paths import REPO_ROOT

pytestmark = pytest.mark.slow(reason="CREATE DATABASE per test and spawned api/worker boots: 10 tests, 16.9s at e5510c7")

# Per-run like `TEST_DATABASE` (story 2.7): both are dropped WITH (FORCE),
# so fixed names let one run delete a concurrent run's database.
PENDING_DATABASE = f"meetingminer_test_pending_{RUN_ID}"
CLI_DATABASE = f"meetingminer_test_cli_{RUN_ID}"

# TCP port 1 is never a Postgres: connect fails immediately with refusal.
UNREACHABLE_PORT = 1


def _write_config(
    directory: Path, database: str | None = None, port: int | None = None
) -> Path:
    """A copy of the repo config.yaml with the Postgres target patched.

    docs/ is symlinked beside the copy: the source-drop schema anchors off
    the resolved config file's parent (story 1.10, finding 17), so a config
    relocated for a subprocess must bring the docs tree with it.
    """
    raw = yaml.safe_load((REPO_ROOT / "config.yaml").read_text(encoding="utf-8"))
    if database is not None:
        raw["stores"]["postgres"]["database"] = database
    # The tracked file names the main checkout's port; the port this checkout
    # actually uses may come from .env.worktree (story 11.2). Write the
    # effective one, so the copy targets the same Postgres the session's
    # per-run database was created on — unless the test asks for another.
    raw["stores"]["postgres"]["port"] = (
        port
        if port is not None
        else load_config(REPO_ROOT / "config.yaml", REPO_ROOT / ".env").settings.stores.postgres.port
    )
    config_path = directory / "config.yaml"
    config_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    docs_link = directory / "docs"
    if not docs_link.exists():
        docs_link.symlink_to(REPO_ROOT / "docs", target_is_directory=True)
    return config_path


def _env(config_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["MM_CONFIG_PATH"] = str(config_path)
    env["MM_ENV_PATH"] = str(REPO_ROOT / ".env")
    # The worker's content-root gate (story 1.3) runs before the migration
    # gate, so these tests must supply a usable root of their own — otherwise
    # they would assert the migration contract against whatever the developer
    # happens to have in .env. The worker creates the directory itself.
    env["MM_CONTENT_ROOT"] = str(config_path.parent / "content")
    # The loader applies MM_POSTGRES_PORT from the checkout's .env.worktree
    # (story 11.2) over the config file's port, so a worktree would silently
    # redirect the patched port — the unreachable one above included — to its
    # private stack. The process environment wins over that file: name the
    # port this copy of the config carries, so the subprocess targets exactly
    # what the test wrote.
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    env["MM_POSTGRES_PORT"] = str(raw["stores"]["postgres"]["port"])
    return env


def _run(args: list[str], config_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        capture_output=True,
        text=True,
        env=_env(config_path),
        timeout=60,
    )


_API_LIFESPAN_SCRIPT = """
import asyncio
import meetingminer.api.main as api_main

async def boot():
    async with api_main.lifespan(api_main.app):
        pass

asyncio.run(boot())
print("lifespan completed")
"""


# --- runner behavior -------------------------------------------------------


def test_apply_migrations_twice_second_run_is_noop(app_config, test_database) -> None:
    with psycopg.connect(db.conninfo(app_config, database=test_database)) as conn:
        assert db.pending_migrations(conn) == []
        assert db.apply_migrations(conn) == []
        db.check_migrations_current(conn)  # must not raise


def test_migration_files_are_discovered_in_order() -> None:
    names = [p.name for p in db.migration_files()]
    assert names[:3] == [
        "0001_jobs.sql",
        "0002_meetings_media_frames.sql",
        "0003_screens_screenshots.sql",
    ]
    assert names == sorted(names)


def test_missing_migrations_directory_is_a_named_error(tmp_path: Path) -> None:
    with pytest.raises(db.MigrationError, match="migrations directory not found"):
        db.migration_files(tmp_path / "absent")



# --- pending-migration fail-fast ------------------------------------------


@pytest.fixture(scope="module")
def pending_db_config_path(
    app_config: AppConfig, pg_conninfo: str, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Path]:
    """An empty database (all migrations pending) + a config.yaml pointing at it.

    Dropped on the way out: the name is per-run (story 2.7), so without this
    every suite would leave one behind instead of reusing a fixed name.
    """
    with database_owner_lock(pg_conninfo, PENDING_DATABASE) as owner_conn:
        created = False
        try:
            drop_owned_database(owner_conn, PENDING_DATABASE)
            create_owned_database(owner_conn, PENDING_DATABASE)
            created = True
            yield _write_config(
                tmp_path_factory.mktemp("pending-config"), database=PENDING_DATABASE
            )
        finally:
            if created:
                cleanup_owned_database(owner_conn, PENDING_DATABASE)


def test_worker_exits_1_on_pending_migrations(pending_db_config_path: Path) -> None:
    proc = _run(["-m", "meetingminer.worker.main"], pending_db_config_path)
    assert proc.returncode == 1
    assert '"event": "worker.fatal"' in proc.stderr
    assert "pending database migration" in proc.stderr
    assert "0001_jobs.sql" in proc.stderr
    assert "make migrate" in proc.stderr
    assert "Traceback" not in proc.stderr


def test_api_refuses_boot_on_pending_migrations(pending_db_config_path: Path) -> None:
    proc = _run(["-c", _API_LIFESPAN_SCRIPT], pending_db_config_path)
    assert proc.returncode == 1
    assert "fatal: api startup aborted" in proc.stderr
    assert "pending database migration" in proc.stderr
    assert "Traceback" not in proc.stderr
    assert "lifespan completed" not in proc.stdout


# --- unreachable-database fail-fast (no Postgres needed) -------------------


@pytest.fixture(scope="module")
def unreachable_config_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _write_config(
        tmp_path_factory.mktemp("unreachable-config"), port=UNREACHABLE_PORT
    )


def test_worker_exits_1_on_unreachable_database(unreachable_config_path: Path) -> None:
    proc = _run(["-m", "meetingminer.worker.main"], unreachable_config_path)
    assert proc.returncode == 1
    assert '"event": "worker.fatal"' in proc.stderr
    assert "database unreachable" in proc.stderr
    assert "Traceback" not in proc.stderr


def test_api_refuses_boot_on_unreachable_database(
    unreachable_config_path: Path,
) -> None:
    # Takes ~10s: the pool retries until its open timeout expires.
    proc = _run(["-c", _API_LIFESPAN_SCRIPT], unreachable_config_path)
    assert proc.returncode == 1
    assert "fatal: api startup aborted" in proc.stderr
    assert "Traceback" not in proc.stderr
    assert "lifespan completed" not in proc.stdout


# --- success paths ---------------------------------------------------------


def test_api_lifespan_boots_when_migrations_are_current(
    app_config, test_database, tmp_path: Path
) -> None:
    current_config = _write_config(tmp_path, database=test_database)
    proc = _run(["-c", _API_LIFESPAN_SCRIPT], current_config)
    assert proc.returncode == 0, proc.stderr
    assert "lifespan completed" in proc.stdout


def test_worker_boots_idles_and_shuts_down_cleanly(
    app_config, test_database, tmp_path: Path
) -> None:
    current_config = _write_config(tmp_path, database=test_database)
    proc = subprocess.Popen(
        [sys.executable, "-m", "meetingminer.worker.main"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_env(current_config),
    )
    try:
        # Read lines until the startup event: orphan recovery (story 1.3) can
        # emit worker.job_requeued lines ahead of it, and the Makefile's
        # readiness poll greps the log rather than reading only the first line.
        startup = None
        for _ in range(20):
            line = proc.stdout.readline()  # blocks until the worker logs
            if '"event": "worker.startup"' in line:
                startup = json.loads(line)
                break
        else:
            raise AssertionError("worker never logged worker.startup")
        proc.send_signal(signal.SIGTERM)
        stdout, stderr = proc.communicate(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()
    assert proc.returncode == 0, stderr
    assert '"event": "worker.shutdown"' in stdout
    # Story 1.4: the binding is resolved at startup, so an unusable OCR engine
    # is known before a recording drop has burned time in probe and frames.
    assert startup is not None
    assert startup["ocrEngine"] == "apple-vision"
    assert "ocrEngineResolved" in startup
    if startup["ocrEngineResolved"] is None:
        assert '"event": "worker.ocr_unavailable"' in stderr
    else:
        assert startup["ocrEngineResolved"] in {"apple-vision", "tesseract"}


def test_migrate_cli_applies_then_noop(pg_conninfo: str, tmp_path: Path) -> None:
    """`python -m meetingminer.db migrate` is what `make migrate`/`make up` run."""
    with database_owner_lock(pg_conninfo, CLI_DATABASE) as owner_conn:
        created = False
        try:
            drop_owned_database(owner_conn, CLI_DATABASE)
            create_owned_database(owner_conn, CLI_DATABASE)
            created = True
            cli_config = _write_config(tmp_path, database=CLI_DATABASE)

            first = _run(["-m", "meetingminer.db", "migrate"], cli_config)
            assert first.returncode == 0, first.stderr
            assert "applied 0001_jobs.sql" in first.stdout

            second = _run(["-m", "meetingminer.db", "migrate"], cli_config)
            assert second.returncode == 0, second.stderr
            assert "nothing to apply" in second.stdout
        finally:
            if created:
                cleanup_owned_database(owner_conn, CLI_DATABASE)
