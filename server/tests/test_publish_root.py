"""MM_PUBLISH_ROOT is an api startup gate (story 4.3).

Same shape as `require_content_root` (`test_content_root.py`): set, absolute,
creatable, a directory, and write-probed, because the api both creates and
writes into this location on every publish gesture. No subprocess coverage
here — the worker never touches the publish folder, and the api's own
subprocess/failfast coverage lives in `test_failfast.py`-style suites, not
duplicated per root.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from meetingminer.config import AppConfig, ConfigError, load_config, require_publish_root

from repo_paths import REPO_ROOT


def _config_with_root(tmp_path: Path, value: str | None) -> AppConfig:
    envfile = tmp_path / "env"
    envfile.write_text(
        "" if value is None else f"MM_PUBLISH_ROOT={value}\n", encoding="utf-8"
    )
    return load_config(REPO_ROOT / "config.yaml", envfile)


@pytest.fixture(autouse=True)
def _no_ambient_publish_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """The process environment wins over .env, so clear the developer's value."""
    monkeypatch.delenv("MM_PUBLISH_ROOT", raising=False)


def test_unset_publish_root_is_a_named_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="MM_PUBLISH_ROOT is not set"):
        require_publish_root(_config_with_root(tmp_path, None))


def test_blank_publish_root_is_a_named_error(tmp_path: Path) -> None:
    """A placeholder left as `MM_PUBLISH_ROOT=` must not coerce to a default."""
    with pytest.raises(ConfigError, match="MM_PUBLISH_ROOT is not set"):
        require_publish_root(_config_with_root(tmp_path, ""))


def test_existing_writable_root_is_returned_resolved(tmp_path: Path) -> None:
    root = tmp_path / "publish"
    root.mkdir()
    resolved = require_publish_root(_config_with_root(tmp_path, str(root)))
    assert resolved == root.resolve()
    assert resolved.is_absolute()


def test_missing_root_is_created(tmp_path: Path) -> None:
    root = tmp_path / "nested" / "publish"
    resolved = require_publish_root(_config_with_root(tmp_path, str(root)))
    assert resolved.is_dir()
    # The write probe cleans up after itself.
    assert list(resolved.iterdir()) == []


def test_uncreatable_root_is_a_named_error(tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("I am a file, not a directory", encoding="utf-8")
    with pytest.raises(ConfigError, match="MM_PUBLISH_ROOT could not be created"):
        require_publish_root(_config_with_root(tmp_path, str(blocker / "publish")))


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses directory permissions")
def test_non_writable_root_is_a_named_error(tmp_path: Path) -> None:
    root = tmp_path / "readonly"
    root.mkdir(mode=0o500)
    try:
        with pytest.raises(ConfigError, match="MM_PUBLISH_ROOT is not writable"):
            require_publish_root(_config_with_root(tmp_path, str(root)))
    finally:
        root.chmod(0o700)  # so pytest can clean the temp tree up
