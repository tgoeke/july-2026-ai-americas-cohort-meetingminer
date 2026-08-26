"""MM_CONTENT_ROOT is a worker startup gate (story 1.3).

The frames stage writes media under this root and AD-3 stores only paths
relative to it, so an unset or unusable root must stop the worker before it
claims anything — named error, exit 1, no traceback, exactly like the config
and migration gates. In-process tests cover require_content_root() directly;
the subprocess tests follow the test_failfast.py pattern and prove the real
`python -m meetingminer.worker.main` entry point honours it.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from meetingminer.config import AppConfig, ConfigError, load_config, require_content_root
from meetingminer.worker.main import acquire_worker_lock

from conftest import REPO_ROOT


# --- require_content_root() ------------------------------------------------


def _config_with_root(tmp_path: Path, value: str | None) -> AppConfig:
    """Load the real config.yaml with MM_CONTENT_ROOT taken from a temp .env."""
    envfile = tmp_path / "env"
    envfile.write_text(
        "" if value is None else f"MM_CONTENT_ROOT={value}\n", encoding="utf-8"
    )
    return load_config(REPO_ROOT / "config.yaml", envfile)


@pytest.fixture(autouse=True)
def _no_ambient_content_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """The process environment wins over .env, so clear the developer's value."""
    monkeypatch.delenv("MM_CONTENT_ROOT", raising=False)


def test_unset_content_root_is_a_named_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="MM_CONTENT_ROOT is not set"):
        require_content_root(_config_with_root(tmp_path, None))


def test_blank_content_root_is_a_named_error(tmp_path: Path) -> None:
    """A placeholder left as `MM_CONTENT_ROOT=` must not coerce to a default."""
    with pytest.raises(ConfigError, match="MM_CONTENT_ROOT is not set"):
        require_content_root(_config_with_root(tmp_path, ""))


def test_existing_writable_root_is_returned_resolved(tmp_path: Path) -> None:
    root = tmp_path / "content"
    root.mkdir()
    resolved = require_content_root(_config_with_root(tmp_path, str(root)))
    assert resolved == root.resolve()
    assert resolved.is_absolute()


def test_missing_root_is_created(tmp_path: Path) -> None:
    root = tmp_path / "nested" / "content"
    resolved = require_content_root(_config_with_root(tmp_path, str(root)))
    assert resolved.is_dir()
    # The write probe cleans up after itself.
    assert list(resolved.iterdir()) == []


def test_uncreatable_root_is_a_named_error(tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("I am a file, not a directory", encoding="utf-8")
    with pytest.raises(ConfigError, match="MM_CONTENT_ROOT could not be created"):
        require_content_root(_config_with_root(tmp_path, str(blocker / "content")))


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses directory permissions")
def test_non_writable_root_is_a_named_error(tmp_path: Path) -> None:
    root = tmp_path / "readonly"
    root.mkdir(mode=0o500)
    try:
        with pytest.raises(ConfigError, match="MM_CONTENT_ROOT is not writable"):
            require_content_root(_config_with_root(tmp_path, str(root)))
    finally:
        root.chmod(0o700)  # so pytest can clean the temp tree up


# --- the worker startup gate (subprocess) ----------------------------------


def _worker(config_path: Path, envfile: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["MM_CONFIG_PATH"] = str(config_path)
    env["MM_ENV_PATH"] = str(envfile)
    env.pop("MM_CONTENT_ROOT", None)
    return subprocess.run(
        [sys.executable, "-m", "meetingminer.worker.main"],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


@pytest.fixture()
def unreachable_config(tmp_path: Path) -> Path:
    """A config whose Postgres cannot be reached.

    The content-root gate runs *before* the migration gate, so a failure here
    must surface as the content-root error even though the database is
    unusable — that ordering is what these tests pin, and it means they need
    no Postgres at all.
    """
    raw = yaml.safe_load((REPO_ROOT / "config.yaml").read_text(encoding="utf-8"))
    raw["stores"]["postgres"]["port"] = 1  # nothing ever listens here
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    (tmp_path / "docs").symlink_to(REPO_ROOT / "docs", target_is_directory=True)
    return path


def test_worker_exits_1_when_content_root_is_unset(
    tmp_path: Path, unreachable_config: Path
) -> None:
    envfile = tmp_path / "env"
    envfile.write_text("", encoding="utf-8")
    proc = _worker(unreachable_config, envfile)
    assert proc.returncode == 1
    assert '"event": "worker.fatal"' in proc.stderr
    assert "MM_CONTENT_ROOT is not set" in proc.stderr
    assert "Traceback" not in proc.stderr
    assert "worker.startup" not in proc.stdout


def test_worker_exits_1_when_content_root_is_uncreatable(
    tmp_path: Path, unreachable_config: Path
) -> None:
    envfile = tmp_path / "env"
    envfile.write_text("MM_CONTENT_ROOT=/nonexistent/nope\n", encoding="utf-8")
    proc = _worker(unreachable_config, envfile)
    assert proc.returncode == 1
    assert '"event": "worker.fatal"' in proc.stderr
    assert "MM_CONTENT_ROOT could not be created" in proc.stderr
    assert "Traceback" not in proc.stderr
    assert "worker.startup" not in proc.stdout


def test_content_root_gate_runs_before_the_database_gate(
    tmp_path: Path, unreachable_config: Path
) -> None:
    """Nothing is claimed before the root is known good."""
    envfile = tmp_path / "env"
    envfile.write_text("", encoding="utf-8")
    proc = _worker(unreachable_config, envfile)
    assert "database unreachable" not in proc.stderr
    assert "MM_CONTENT_ROOT" in proc.stderr


class _LockResult:
    def __init__(self, acquired: bool) -> None:
        self.acquired = acquired

    def fetchone(self) -> tuple[bool]:
        return (self.acquired,)


class _LockConnection:
    def __init__(self, acquired: bool) -> None:
        self.acquired = acquired
        self.statement = ""

    def execute(self, statement: str) -> _LockResult:
        self.statement = statement
        return _LockResult(self.acquired)


def test_worker_advisory_lock_rejects_a_competing_worker() -> None:
    first = _LockConnection(True)
    second = _LockConnection(False)
    assert acquire_worker_lock(first) is True
    assert acquire_worker_lock(second) is False
    assert "pg_try_advisory_lock" in first.statement
