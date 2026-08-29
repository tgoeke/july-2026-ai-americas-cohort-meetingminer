"""Regression coverage for cross-process test-store ownership (story 2.7)."""

from __future__ import annotations

import os
import json
import subprocess
import sys
import time
import types
import warnings
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from conftest import _projection_lock_paths, _projection_lock_timeout_seconds
from repo_paths import REPO_ROOT


def _database_exists(conninfo: str, name: str) -> bool:
    with psycopg.connect(conninfo, autocommit=True) as conn:
        return conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (name,)
        ).fetchone() is not None


def _drop_database(conn: psycopg.Connection, name: str) -> None:
    conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def test_prune_preserves_owned_database_and_removes_abandoned(pg_conninfo: str) -> None:
    """The pruner must use the suite's durable owner lock, not activity alone."""
    suffix = uuid4().hex[:12]
    owned = f"meetingminer_test_{suffix}"
    abandoned = f"meetingminer_test_pending_{suffix}"
    excluded = f"meetingminer_testing_{suffix}"
    owner_lock_name = f"meetingminer-test-owner:{owned}"

    with psycopg.connect(pg_conninfo, autocommit=True) as owner:
        owner.execute(
            "SELECT pg_advisory_lock(hashtextextended(%s, 0))", (owner_lock_name,)
        )
        owner.execute(f'CREATE DATABASE "{owned}"')
        owner.execute(f'CREATE DATABASE "{abandoned}"')
        owner.execute(f'CREATE DATABASE "{excluded}"')
        try:
            result = subprocess.run(
                ["make", "test-db-prune"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=90,
            )
            assert result.returncode == 0, result.stdout + result.stderr
            assert _database_exists(pg_conninfo, owned)
            assert not _database_exists(pg_conninfo, abandoned)
            assert _database_exists(pg_conninfo, excluded)
        finally:
            _drop_database(owner, owned)
            _drop_database(owner, abandoned)
            _drop_database(owner, excluded)


def _run_pytest_with_plugin(
    tmp_path: Path, plugin_source: str, target: str
) -> tuple[subprocess.CompletedProcess[str], str]:
    database_name = tmp_path / "database-name"
    plugin = tmp_path / "cleanup_plugin.py"
    plugin.write_text(plugin_source, encoding="utf-8")
    env = os.environ.copy()
    env["MM_PARALLEL_STORE_DATABASE_NAME"] = str(database_name)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(tmp_path), str(REPO_ROOT / "server"), str(REPO_ROOT / "server" / "tests"), env.get("PYTHONPATH", "")]
    )
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "cleanup_plugin", target, "-q"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
    )
    return result, database_name.read_text(encoding="utf-8")


def test_database_fixture_cleans_up_after_migration_setup_failure(
    pg_conninfo: str, tmp_path: Path
) -> None:
    """A post-create migration failure must not leak the session database."""
    result, database = _run_pytest_with_plugin(
        tmp_path,
        """
import os
from pathlib import Path
from conftest import TEST_DATABASE
from meetingminer import db

Path(os.environ[\"MM_PARALLEL_STORE_DATABASE_NAME\"]).write_text(TEST_DATABASE)
def fail_migrations(*_args, **_kwargs):
    raise db.MigrationError(\"forced migration setup failure\")
db.apply_migrations = fail_migrations
""",
        "server/tests/test_migrations.py::test_apply_migrations_twice_second_run_is_noop",
    )
    assert result.returncode != 0
    assert "forced migration setup failure" in result.stdout + result.stderr
    assert not _database_exists(pg_conninfo, database)


def test_cli_migration_config_failure_cleans_up_database(
    pg_conninfo: str, tmp_path: Path
) -> None:
    """The CLI migration test registers cleanup before writing its temp config."""
    result, database = _run_pytest_with_plugin(
        tmp_path,
        """
import os
from pathlib import Path
import test_migrations

Path(os.environ[\"MM_PARALLEL_STORE_DATABASE_NAME\"]).write_text(test_migrations.CLI_DATABASE)
def fail_config(*_args, **_kwargs):
    raise OSError(\"forced config setup failure\")
test_migrations._write_config = fail_config
""",
        "server/tests/test_migrations.py::test_migrate_cli_applies_then_noop",
    )
    assert result.returncode != 0
    assert "forced config setup failure" in result.stdout + result.stderr
    assert not _database_exists(pg_conninfo, database)


def test_pending_migration_config_failure_cleans_up_database(
    pg_conninfo: str, tmp_path: Path
) -> None:
    """The pending-db fixture cleans up when writing its temp config fails."""
    result, database = _run_pytest_with_plugin(
        tmp_path,
        """
import os
from pathlib import Path
import test_migrations

Path(os.environ[\"MM_PARALLEL_STORE_DATABASE_NAME\"]).write_text(test_migrations.PENDING_DATABASE)
def fail_config(*_args, **_kwargs):
    raise OSError(\"forced pending config setup failure\")
test_migrations._write_config = fail_config
""",
        "server/tests/test_migrations.py::test_worker_exits_1_on_pending_migrations",
    )
    assert result.returncode != 0
    assert "forced pending config setup failure" in result.stdout + result.stderr
    assert not _database_exists(pg_conninfo, database)


@pytest.mark.parametrize("value", ["NaN", "inf", "-inf", "0", "-0.1"])
def test_projection_lock_timeout_requires_a_positive_finite_value(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("MM_PROJECTION_LOCK_TIMEOUT_SECONDS", value)
    with pytest.raises(RuntimeError, match="positive finite number"):
        _projection_lock_timeout_seconds()


def test_cleanup_failure_is_reported_without_warning_escalation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Cleanup diagnostics must not mask an earlier fixture/setup failure."""
    import conftest

    def fail_drop(*_args, **_kwargs) -> None:
        raise psycopg.OperationalError("forced cleanup failure")

    monkeypatch.setattr(conftest, "drop_owned_database", fail_drop)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        conftest.cleanup_owned_database(object(), "meetingminer_test_abcdef123456")
    assert "forced cleanup failure" in capsys.readouterr().err


def test_prune_script_continues_after_failure_and_returns_nonzero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The Makefile script reports incomplete cleanup to automation."""
    makefile = (REPO_ROOT / "infra" / "Makefile").read_text(encoding="utf-8")
    script = makefile.split("define PRUNE_TEST_DBS\n", maxsplit=1)[1].split(
        "\nendef", maxsplit=1
    )[0]

    class FakeError(Exception):
        pass

    class Result:
        def __init__(self, rows: list[tuple[object, ...]]) -> None:
            self.rows = rows

        def fetchall(self) -> list[tuple[object, ...]]:
            return self.rows

        def fetchone(self) -> tuple[object, ...] | None:
            return self.rows[0] if self.rows else None

    class FakeSql:
        class SQL:
            def __init__(self, statement: str) -> None:
                self.statement = statement

            def format(self, *_identifiers: object) -> "FakeSql.SQL":
                return self

        class Identifier:
            def __init__(self, name: str) -> None:
                self.name = name

    class FakeConnection:
        def __init__(self) -> None:
            self.drop_attempts = 0
            self.dropped = 0

        def __enter__(self) -> "FakeConnection":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(
            self, statement: object, _params: tuple[object, ...] | None = None
        ) -> Result:
            if isinstance(statement, FakeSql.SQL):
                self.drop_attempts += 1
                if self.drop_attempts == 1:
                    raise FakeError("forced first drop failure")
                self.dropped += 1
                return Result([])
            statement_text = str(statement)
            if "SELECT datname" in statement_text:
                return Result(
                    [
                        ("meetingminer_test_aaaaaaaaaaaa",),
                        ("meetingminer_test_cli_bbbbbbbbbbbb",),
                    ]
                )
            if "pg_try_advisory_lock" in statement_text:
                return Result([(True,)])
            if "pg_stat_activity" in statement_text:
                return Result([])
            return Result([(True,)])

    fake_connection = FakeConnection()
    fake_psycopg = types.ModuleType("psycopg")
    fake_psycopg.Error = FakeError
    fake_psycopg.connect = lambda *_args, **_kwargs: fake_connection
    fake_psycopg.sql = FakeSql
    fake_meetingminer = types.ModuleType("meetingminer")
    fake_meetingminer.db = types.SimpleNamespace(conninfo=lambda *_args: "conninfo")
    fake_config = types.ModuleType("meetingminer.config")
    fake_config.load_config = lambda: object()
    monkeypatch.setitem(sys.modules, "psycopg", fake_psycopg)
    monkeypatch.setitem(sys.modules, "psycopg.sql", FakeSql)
    monkeypatch.setitem(sys.modules, "meetingminer", fake_meetingminer)
    monkeypatch.setitem(sys.modules, "meetingminer.config", fake_config)

    with pytest.raises(SystemExit, match="1"):
        exec(script, {})
    output = capsys.readouterr().out
    assert "failed meetingminer_test_aaaaaaaaaaaa" in output
    assert "dropped meetingminer_test_cli_bbbbbbbbbbbb" in output
    assert output.index("failed meetingminer_test") < output.index(
        "dropped meetingminer_test"
    )
    assert fake_connection.dropped == 1


def _wait_for_path(path: Path, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while not path.exists():
        if time.monotonic() >= deadline:
            raise AssertionError(f"timed out waiting for {path}")
        time.sleep(0.02)


def _lock_process_script(ready_path: Path, release_path: Path | None = None) -> str:
    """Acquire the projection lock, announce readiness, hold until released.

    A fixed ``time.sleep`` hold cannot work here: the waiter subprocess spends
    ~0.9s importing conftest (fastapi and friends) before it even attempts the
    lock, so any hold short enough to keep the test fast loses the race on a
    loaded machine — the holder exits, the waiter acquires, and the test fails
    claiming the lock was never held. Holding until the parent writes
    ``release_path`` (with a 60s backstop so a crashed parent cannot wedge the
    holder) removes the timing dependence entirely. ``release_path=None``
    releases immediately — the acquire-and-exit probe the release check reuses.
    """
    release_wait = (
        f"""
    deadline = time.monotonic() + 60.0
    while not Path({str(release_path)!r}).exists():
        if time.monotonic() >= deadline:
            raise AssertionError(\"holder was never released by the test\")
        time.sleep(0.02)
"""
        if release_path is not None
        else ""
    )
    return f"""
import time
from pathlib import Path
from conftest import _projection_store_lock
from repo_paths import REPO_ROOT
from meetingminer.config import load_config

config = load_config(REPO_ROOT / \"config.yaml\", REPO_ROOT / \".env\")
with _projection_store_lock(config):
    Path({str(ready_path)!r}).write_text(\"ready\")
{release_wait}"""


def test_projection_lock_times_out_with_holder_details_then_releases(tmp_path: Path) -> None:
    """A stuck holder is bounded and named; a later requester still succeeds."""
    ready = tmp_path / "holder-ready"
    release = tmp_path / "holder-release"
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(REPO_ROOT / "server"), str(REPO_ROOT / "server" / "tests"), env.get("PYTHONPATH", "")]
    )
    holder = subprocess.Popen(
        [sys.executable, "-c", _lock_process_script(ready, release_path=release)],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for_path(ready)
        from meetingminer.config import load_config

        _, holder_path = _projection_lock_paths(
            load_config(REPO_ROOT / "config.yaml", REPO_ROOT / ".env")
        )
        holder_metadata = json.loads(holder_path.read_text(encoding="utf-8"))
        assert holder_metadata["pid"] == holder.pid
        assert holder_metadata["host"]
        assert isinstance(holder_metadata["acquiredAt"], float)
        waiter_env = env | {"MM_PROJECTION_LOCK_TIMEOUT_SECONDS": "0.20"}
        waiter = subprocess.run(
            [
                sys.executable,
                "-c",
                """
import sys
import time
from conftest import _projection_store_lock
from repo_paths import REPO_ROOT
from meetingminer.config import load_config

started = time.monotonic()
try:
    with _projection_store_lock(load_config(REPO_ROOT / \"config.yaml\", REPO_ROOT / \".env\")):
        raise AssertionError(\"waiter acquired a lock held by another process\")
except RuntimeError as exc:
    print(f\"{time.monotonic() - started:.3f}|{exc}\")
    sys.exit(0)
""",
            ],
            cwd=REPO_ROOT,
            env=waiter_env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert waiter.returncode == 0, waiter.stdout + waiter.stderr
        elapsed_text, diagnostic = waiter.stdout.strip().split("|", maxsplit=1)
        assert float(elapsed_text) < 0.8
        assert "timed out" in diagnostic
        assert "meetingminer-projections-" in diagnostic
        holder_json = diagnostic.rsplit("holder metadata: ", maxsplit=1)[1]
        assert json.loads(holder_json) == holder_metadata
    finally:
        release.write_text("released")
        stdout, stderr = holder.communicate(timeout=10)
        assert holder.returncode == 0, stdout + stderr

    released = subprocess.run(
        [sys.executable, "-c", _lock_process_script(tmp_path / "released")],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert released.returncode == 0, released.stdout + released.stderr
