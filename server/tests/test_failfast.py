"""Fail-fast contract: api and worker exit non-zero naming the config problem
(never a raw traceback) when config.yaml is missing or invalid — including
through the real uvicorn launcher (story 1.10, finding 25)."""

from __future__ import annotations

import os
import selectors
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

from repo_paths import REPO_ROOT

pytestmark = pytest.mark.slow(reason="spawns the api and the worker to watch them exit: 12 tests, 6.8s at e5510c7")


def _run(
    args: list[str],
    config_path: Path,
    tmp_path: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["MM_CONFIG_PATH"] = str(config_path)
    env["MM_ENV_PATH"] = str(tmp_path / "absent.env")
    env.update(extra_env or {})
    return subprocess.run(
        [sys.executable, *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


@pytest.fixture()
def bad_yaml(tmp_path: Path) -> Path:
    path = tmp_path / "broken.yaml"
    path.write_text("ocr: [unclosed\n  engine: :::", encoding="utf-8")
    return path


def test_worker_exits_1_on_missing_config(tmp_path: Path) -> None:
    proc = _run(["-m", "meetingminer.worker.main"], tmp_path / "nope.yaml", tmp_path)
    assert proc.returncode == 1
    assert "config file not found" in proc.stderr
    assert '"event": "worker.fatal"' in proc.stderr
    assert "Traceback" not in proc.stderr


def test_worker_exits_1_on_invalid_config(tmp_path: Path, bad_yaml: Path) -> None:
    proc = _run(["-m", "meetingminer.worker.main"], bad_yaml, tmp_path)
    assert proc.returncode == 1
    assert "not valid YAML" in proc.stderr
    assert "Traceback" not in proc.stderr


def test_api_exits_1_on_missing_config(tmp_path: Path) -> None:
    proc = _run(["-c", "import meetingminer.api.main"], tmp_path / "nope.yaml", tmp_path)
    assert proc.returncode == 1
    assert "fatal: api startup aborted" in proc.stderr
    assert "config file not found" in proc.stderr
    assert "Traceback" not in proc.stderr


def test_api_exits_1_on_invalid_config(tmp_path: Path, bad_yaml: Path) -> None:
    proc = _run(["-c", "import meetingminer.api.main"], bad_yaml, tmp_path)
    assert proc.returncode == 1
    assert "fatal: api startup aborted" in proc.stderr
    assert "not valid YAML" in proc.stderr
    assert "Traceback" not in proc.stderr


def test_api_exits_1_when_publish_root_is_unset_after_valid_config_loads(tmp_path: Path) -> None:
    """Exercise the real API import, not `require_publish_root` in isolation.

    The configured root is process environment, and the test suite normally
    supplies one before imports. Remove it in an otherwise valid subprocess so
    the publish-root startup gate cannot regress behind that global fixture.
    """
    drops = tmp_path / "drops"
    drops.mkdir()
    env = os.environ.copy()
    env["MM_CONFIG_PATH"] = str(REPO_ROOT / "config.yaml")
    env["MM_ENV_PATH"] = str(tmp_path / "absent.env")
    env["MM_DROPS_ROOT"] = str(drops)
    env.pop("MM_PUBLISH_ROOT", None)
    proc = subprocess.run(
        [sys.executable, "-c", "import meetingminer.api.main"],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert proc.returncode == 1
    assert "fatal: api startup aborted" in proc.stderr
    assert "MM_PUBLISH_ROOT is not set" in proc.stderr
    assert "Traceback" not in proc.stderr


# --- the gates *after* the config gate ------------------------------------
#
# Every case above aborts inside `load_config`, which means none of them ever
# reaches the startup gates that run after it. Those gates need a config that
# is valid — and wrong in exactly one way.


@pytest.fixture()
def config_with_no_embedder_provider(tmp_path: Path) -> Path:
    """A valid config.yaml whose `embedder` block no provider serves.

    Copied from the real one and edited, so it stays valid against every other
    part of `Settings` — the point is to get *past* `load_config` and stop at
    the embedder binding. The drop schema is copied alongside it because
    `api/ingests.drop_schema_path` anchors to the config's own directory, and
    that gate runs first.
    """
    raw = yaml.safe_load((REPO_ROOT / "config.yaml").read_text(encoding="utf-8"))
    raw["providers"].pop("ollama", None)
    # Removing a provider that `llm.roles.*.catalog` still names is a config
    # error in its own right (story 8.1), raised inside `load_config` — which
    # would stop this fixture short of the gate it exists to reach, and name
    # the catalog instead of the embedder. Drop the authored catalogs along
    # with the provider: each role then falls back to the one-entry catalog
    # synthesized from its own `model`, which carries no provider and so
    # asserts nothing about the map this fixture just edited.
    for role_block in raw["llm"]["roles"].values():
        role_block.pop("catalog", None)
        role_block.pop("default", None)
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    schema_dir = tmp_path / "docs"
    schema_dir.mkdir(exist_ok=True)
    shutil.copy(
        REPO_ROOT / "docs" / "source-drop.schema.json",
        schema_dir / "source-drop.schema.json",
    )
    return path


def _write_corrupt_schema(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "source-drop.schema.json").write_text("{ not json", encoding="utf-8")


def _write_invalid_schema(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "source-drop.schema.json").write_text('{"type": 42}', encoding="utf-8")


@pytest.mark.parametrize(
    "break_schema",
    [
        pytest.param(lambda tmp_path: None, id="missing"),
        pytest.param(_write_corrupt_schema, id="corrupt"),
        pytest.param(_write_invalid_schema, id="invalid-schema"),
    ],
)
def test_api_exits_1_when_the_drop_schema_is_missing_or_corrupt_at_boot(
    tmp_path: Path, break_schema
) -> None:
    """The schema gate (story 2-6): a missing or corrupt
    docs/source-drop.schema.json aborts the boot with the named error — never
    a first-ingest surprise. The real config.yaml is copied into the tmp tree,
    so the config and drops-root gates pass and the schema gate is the one
    that fires: the schema is missing, unparseable, or semantically invalid."""
    path = tmp_path / "config.yaml"
    shutil.copy(REPO_ROOT / "config.yaml", path)
    break_schema(tmp_path)
    drops = tmp_path / "drops"
    drops.mkdir()
    proc = _run(
        ["-c", "import meetingminer.api.main"],
        path,
        tmp_path,
        extra_env={"MM_DROPS_ROOT": str(drops)},
    )
    assert proc.returncode == 1
    assert "fatal: api startup aborted" in proc.stderr
    assert "source-drop schema unreadable" in proc.stderr
    assert "Traceback" not in proc.stderr


def test_api_exits_1_when_no_provider_serves_the_configured_embedder(
    tmp_path: Path, config_with_no_embedder_provider: Path
) -> None:
    """The embedder binding is a startup gate, not a first-search surprise.

    AD-8 makes the embedder the one port whose binding is projection state, and
    `build_embedder` contacts no host — so a model no provider serves is a
    *config* error, and a config error belongs with the other startup gates
    rather than surfacing as a 503 on somebody's first search. A host that is
    merely down is the other case entirely: that one degrades `/search` to
    keyword ranking and never touches startup.
    """
    drops = tmp_path / "drops"
    drops.mkdir()
    proc = _run(
        ["-c", "import meetingminer.api.main"],
        config_with_no_embedder_provider,
        tmp_path,
        extra_env={"MM_DROPS_ROOT": str(drops)},
    )
    assert proc.returncode == 1
    assert "fatal: api startup aborted" in proc.stderr
    assert "no providers.ollama endpoint to serve it" in proc.stderr
    assert "Traceback" not in proc.stderr


# --- through the real uvicorn launcher (story 1.10, finding 25) ------------


def test_uvicorn_exits_1_on_missing_config(tmp_path: Path) -> None:
    """The supervisor layer between the app's SystemExit and the exit code
    the Makefile observes: plain uvicorn must propagate the failure."""
    proc = _run(
        ["-m", "uvicorn", "meetingminer.api.main:app", "--port", "0"],
        tmp_path / "nope.yaml",
        tmp_path,
    )
    assert proc.returncode == 1
    assert "fatal: api startup aborted" in proc.stderr
    assert "config file not found" in proc.stderr
    assert "Traceback" not in proc.stderr


def test_uvicorn_reload_child_reports_named_error(tmp_path: Path) -> None:
    """`--reload` variant: the reloader parent survives an app-import failure
    (which is why `make api` preflights — see the Makefile), but the named
    error must still reach stderr, without a traceback."""
    env = os.environ.copy()
    env["MM_CONFIG_PATH"] = str(tmp_path / "nope.yaml")
    env["MM_ENV_PATH"] = str(tmp_path / "absent.env")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "meetingminer.api.main:app",
         "--reload", "--port", "0"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        cwd=tmp_path,  # keep the file watcher off the repo tree
    )
    seen: list[str] = []
    try:
        deadline = time.monotonic() + 30
        assert proc.stderr is not None
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stderr, selectors.EVENT_READ)
            while time.monotonic() < deadline:
                events = selector.select(timeout=min(0.25, deadline - time.monotonic()))
                if not events:
                    continue
                chunk = os.read(proc.stderr.fileno(), 4096).decode(errors="replace")
                if not chunk:
                    break
                seen.append(chunk)
                if "fatal: api startup aborted" in chunk:
                    break
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    output = "".join(seen)
    assert "fatal: api startup aborted" in output
    assert "config file not found" in output
    assert "Traceback" not in output


def test_make_api_preflights_config_before_reloader(tmp_path: Path) -> None:
    """`make api` must exit non-zero on a broken config without ever starting
    the uvicorn reloader (story 1.10, finding 9)."""
    envfile = tmp_path / ".env"
    # MM_DROPS_ROOT so `check-env` (story 2.1a) passes: this test is about the
    # *config* preflight, and an env guard firing first would let the preflight
    # rot undetected behind a green assertion.
    envfile.write_text(f"MM_DROPS_ROOT={tmp_path / 'drops'}\n", encoding="utf-8")
    env = os.environ.copy()
    env["MM_CONFIG_PATH"] = str(tmp_path / "nope.yaml")
    env["MM_ENV_PATH"] = str(envfile)
    proc = subprocess.run(
        ["make", "-C", str(REPO_ROOT / "infra"), "api", f"ENVFILE={envfile}"],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    output = proc.stdout + proc.stderr
    assert proc.returncode != 0
    assert "fatal: api startup aborted" in output
    assert "config file not found" in output
    assert "Started reloader process" not in output
