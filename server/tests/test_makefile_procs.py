"""No-Docker orchestration coverage (story 1.10, finding 24).

Drives the Makefile's stop/start pidfile machinery against decoy processes:
a matching decoy must be killed, a near-miss spared, and a live matching
pidfile must make a second start a no-op. `LOGS=<tmp>` points the targets at
a scratch pidfile directory, so the repo's real .logs/ is never touched and
no Docker or real service is needed.

The decoys are bash scripts whose argv reproduces (or near-misses) the
anchored launch-command patterns the Makefile greps for.
"""

from __future__ import annotations

import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from repo_paths import REPO_ROOT

pytestmark = pytest.mark.slow(reason="spawns make targets with readiness polls, decoy processes and throwaway git repositories: 63 tests, 61.1s at a352ee0")

INFRA = str(REPO_ROOT / "infra")
TEST_WORKER_OWNER = "test-owner"

DECOY_BODY = "#!/bin/bash\ntrap 'exit 0' TERM INT\nwhile :; do sleep 1; done\n"

# (decoy script path relative to the scratch tree, decoy argv tail).
# The api and web patterns are scoped to $(VENV)/$(WEB), so the decoys must sit
# where those variables point and be launched by absolute path — exactly how
# the Makefile launches the real ones.
MATCHING = {
    "api": ("venv/bin/uvicorn", ["meetingminer.api.main:app", "--host", "127.0.0.1"]),
    "worker": ("venv/bin/python", ["-m", "meetingminer.worker.main", f"--mm-owner={TEST_WORKER_OWNER}"]),
    "web": ("web/node_modules/.bin/vite", ["--port", "5173", "--strictPort"]),
}

NEAR_MISS = {
    "api": ("venv/bin/uvicorn", ["someone_elses.api.main:app"]),
    "worker": ("venv/bin/python", ["-m", "meetingminer_other.worker.main"]),
    # Right name, but outside this checkout's web tree: another project's vite.
    "web": ("elsewhere/node_modules/.bin/vite", ["--port", "5173", "--strictPort"]),
}


def _tree_vars(tmp_path: Path) -> dict[str, str]:
    """VENV/WEB pointed at the scratch tree the decoys live in.

    `WT_ENVFILE` points there too, so the checkout's own `.env.worktree`
    (story 11.2) can never leak into a test: absent, the Makefile is the
    main checkout's (project `meetingminer`, default ports); a test that
    writes the file gets a worktree's.
    """
    return {
        "VENV": str(tmp_path / "venv"),
        "WEB": str(tmp_path / "web"),
        "WORKER_OWNER": TEST_WORKER_OWNER,
        "WT_ENVFILE": str(tmp_path / ".env.worktree"),
    }


def _spawn_decoy(
    base: Path, script_rel: str, args: list[str]
) -> subprocess.Popen[bytes]:
    script = base / script_rel
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(DECOY_BODY, encoding="utf-8")
    script.chmod(0o755)
    # Own session: the Makefile's group-kill can never touch pytest's group.
    return subprocess.Popen([str(script), *args], start_new_session=True)


def _make(
    targets: list[str],
    variables: dict[str, str] | None = None,
    *,
    logs: Path | None = None,
    tmp_path: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 180,
) -> subprocess.CompletedProcess[str]:
    """`make -C infra <targets> VAR=value ...` with an optional env override.

    `logs` sets `LOGS` (a scratch pidfile directory) and `tmp_path` points
    `VENV`/`WEB` at the decoy tree under it (`_tree_vars`); both precede
    `variables` on the command line, in that order, and a key in `variables`
    overrides the one `logs`/`tmp_path` set.
    """
    assert not isinstance(targets, str), "targets is a list of make targets, not one target"
    settings: dict[str, str] = {}
    if logs is not None:
        settings["LOGS"] = str(logs)
    if tmp_path is not None:
        settings.update(_tree_vars(tmp_path))
    settings.update(variables or {})
    # A nested make must never inherit the outer one's jobserver or flags:
    # running this suite via `make test` would otherwise let MAKEFLAGS decide
    # whether the ordering assertions below mean anything.
    child_env = dict(os.environ if env is None else env)
    child_env.pop("MAKEFLAGS", None)
    child_env.pop("MFLAGS", None)
    child_env.pop("MAKELEVEL", None)
    return subprocess.run(
        ["make", "-C", INFRA, *targets, *(f"{k}={v}" for k, v in settings.items())],
        capture_output=True,
        text=True,
        env=child_env,
        timeout=timeout,
    )


def _write_script(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return path


def _free_port() -> int:
    """A port nothing is listening on — so a readiness poll against it fails
    fast and can never be satisfied by a real api the developer has running.

    The kernel can hand the released port to someone else, so confirm it is
    actually refusing connections before handing it out, and retry if not.
    """
    for _ in range(20):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = int(sock.getsockname()[1])
        with socket.socket() as probe:
            probe.settimeout(0.5)
            if probe.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError("could not find a free port")


def _path_env(bin_dir: Path) -> dict[str, str]:
    """Process env with bin_dir prepended to PATH (decoy `docker`/`curl`/…)."""
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    return env


# --- decoy script bodies ---------------------------------------------------

# Writes a recognizable line to its log, then dies: "process dies during startup".
DIE_BODY = "#!/bin/bash\necho 'decoy: exploded during startup'\nexit 1\n"

# Records its own pid, serves 200 on the --port it was given, stays alive.
SERVE_BODY = """#!/bin/bash
echo "__LABEL__" >> "__EVENTS__"
echo "$$" >> "__LAUNCHES__"
PORT=""; prev=""
for a in "$@"; do
  if [ "$prev" = "--port" ]; then PORT="$a"; fi
  prev="$a"
done
"__PYTHON__" "__SERVER_PY__" "$PORT" &
CHILD=$!
trap 'kill $CHILD 2>/dev/null; exit 0' TERM INT
wait $CHILD
"""

# A venv python that answers both `-m meetingminer.db migrate` and
# `-m meetingminer.worker.main` the way the real ones do.
PYTHON_BODY = """#!/bin/bash
case "$*" in
  *meetingminer.db*)
    echo "migrate" >> "__EVENTS__"
    echo "nothing to apply — database is up to date"
    exit 0 ;;
  *meetingminer.worker.main*)
    echo "start-worker" >> "__EVENTS__"
    echo '{"event": "worker.startup"}'
    trap 'exit 0' TERM INT
    while :; do sleep 1; done ;;
esac
exit 0
"""

# A docker that records every argv and can be told to fail the --env-file
# variant (simulating .env interpolation blowing up).
DOCKER_BODY = """#!/bin/bash
echo "$*" >> "__ARGV__"
echo "env MM_STACK_NAME=$MM_STACK_NAME MM_POSTGRES_PORT=$MM_POSTGRES_PORT" >> "__ARGV__"
if [ "$1" = "info" ]; then exit 0; fi
case "$*" in
  *" up "*) echo "compose-up" >> "__EVENTS__" ;;
  *down*)   echo "compose-down" >> "__EVENTS__" ;;
esac
case "$*" in
  *--env-file*) exit __ENVFILE_EXIT__ ;;
esac
exit 0
"""

HEALTH_SERVER_PY = """
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"ok","service":"meetingminer-api"}')

    def log_message(self, *args):
        pass


HTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
"""


def _serving_decoy(path: Path, label: str, events: Path, launches: Path) -> Path:
    """A decoy that satisfies the Makefile's readiness poll, so `up` can be
    driven to completion without any real service."""
    server_py = _write_script(path.parent / "_health_server.py", HEALTH_SERVER_PY)
    body = (
        SERVE_BODY.replace("__LABEL__", label)
        .replace("__EVENTS__", str(events))
        .replace("__LAUNCHES__", str(launches))
        .replace("__PYTHON__", sys.executable)
        .replace("__SERVER_PY__", str(server_py))
    )
    return _write_script(path, body)


def _kill_from_pidfile(pidfile: Path) -> None:
    """Terminate a decoy the Makefile launched (its own process group)."""
    try:
        pid = int(pidfile.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def _wait_no_match(marker: str, timeout: float = 15.0) -> bool:
    """Poll until no process command contains `marker`. Polled, not slept:
    a decoy that traps TERM finishes its in-flight `sleep` first, so exit is
    graceful-but-not-instant."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = subprocess.run(
            ["pgrep", "-f", marker], capture_output=True, text=True
        ).stdout.strip()
        if not found:
            return True
        time.sleep(0.1)
    return False


def _kill_stragglers(marker: str) -> None:
    """Kill any decoy still alive whose command contains `marker` (the test's
    own tmp path). Belt-and-braces cleanup: on a *failing* assertion the
    Makefile may not have stopped what it launched, and no test may leak a
    daemon into the developer's machine.
    """
    found = subprocess.run(
        ["pgrep", "-f", marker], capture_output=True, text=True
    ).stdout.split()
    for raw in found:
        try:
            pid = int(raw)
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (ValueError, ProcessLookupError, PermissionError):
            continue


def _events(events: Path) -> list[str]:
    if not events.exists():
        return []
    return events.read_text(encoding="utf-8").split()


def _wait_gone(proc: subprocess.Popen[bytes], timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return True
        time.sleep(0.1)
    return False


def _cleanup(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is None:
        proc.kill()
    proc.wait(timeout=10)


@pytest.mark.parametrize("name", sorted(MATCHING))
def test_stop_kills_matching_process(name: str, tmp_path: Path) -> None:
    script_rel, args = MATCHING[name]
    decoy = _spawn_decoy(tmp_path, script_rel, args)
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / f"{name}.pid").write_text(str(decoy.pid), encoding="utf-8")
    try:
        proc = _make([f"stop-{name}"], logs=logs, tmp_path=tmp_path, timeout=60)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert f"{name}: stopping (pid {decoy.pid})" in proc.stdout
        assert _wait_gone(decoy), "matching decoy should have been terminated"
        assert not (logs / f"{name}.pid").exists()
    finally:
        _cleanup(decoy)


@pytest.mark.parametrize("name", sorted(NEAR_MISS))
def test_stop_spares_near_miss_process(name: str, tmp_path: Path) -> None:
    """PID reuse safety: a pid whose command does not match the anchored
    launch pattern is never killed — only the stale pidfile is removed."""
    script_rel, args = NEAR_MISS[name]
    decoy = _spawn_decoy(tmp_path, script_rel, args)
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / f"{name}.pid").write_text(str(decoy.pid), encoding="utf-8")
    try:
        proc = _make([f"stop-{name}"], logs=logs, tmp_path=tmp_path, timeout=60)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "removing stale pidfile without killing" in proc.stdout
        time.sleep(0.5)
        assert decoy.poll() is None, "near-miss decoy must not be killed"
        assert not (logs / f"{name}.pid").exists()
    finally:
        _cleanup(decoy)


def test_stop_with_dead_pid_removes_stale_pidfile(tmp_path: Path) -> None:
    decoy = _spawn_decoy(tmp_path, *MATCHING["api"])
    decoy.kill()
    decoy.wait(timeout=10)
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "api.pid").write_text(str(decoy.pid), encoding="utf-8")
    proc = _make(["stop-api"], logs=logs, tmp_path=tmp_path, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "api: not running" in proc.stdout
    assert not (logs / "api.pid").exists()


def test_start_is_noop_when_matching_process_running(tmp_path: Path) -> None:
    """No duplicate starts (finding 2): a live pid whose command matches the
    launch pattern makes start-api skip the launch — and a reused PID (the
    near-miss suite above) would not, because the command name is verified.
    Readiness still runs, so the pidfile keeps pointing at the same process.
    """
    logs = tmp_path / "logs"
    logs.mkdir()
    events = tmp_path / "events.txt"
    launches = tmp_path / "launches.txt"
    port = _free_port()
    script = _serving_decoy(
        tmp_path / "venv" / "bin" / "uvicorn", "start-api", events, launches
    )
    decoy = subprocess.Popen(
        [str(script), "meetingminer.api.main:app", "--host", "127.0.0.1",
         "--port", str(port)],
        start_new_session=True,
    )
    (logs / "api.pid").write_text(str(decoy.pid), encoding="utf-8")
    try:
        proc = _make(
            ["start-api"], {"API_PORT": str(port)}, logs=logs, tmp_path=tmp_path
        )
        output = proc.stdout + proc.stderr
        assert proc.returncode == 0, output
        assert f"api: already running (pid {decoy.pid})" in output
        # One launch: the decoy this test started, not a second one.
        assert launches.read_text(encoding="utf-8").split() == [str(decoy.pid)]
        assert decoy.poll() is None
        assert (logs / "api.pid").read_text(encoding="utf-8").strip() == str(decoy.pid)
    finally:
        _cleanup(decoy)
        _kill_stragglers(str(tmp_path))


def test_repeat_start_on_a_hung_process_is_not_a_success(tmp_path: Path) -> None:
    """The inaccurate-success mode this story exists to remove: a process
    that is alive but no longer answering must fail `up`, not be waved
    through as "already running"."""
    logs = tmp_path / "logs"
    logs.mkdir()
    # Matches the launch pattern, never binds the port: a hung api.
    script = _write_script(tmp_path / "venv" / "bin" / "uvicorn", DECOY_BODY)
    decoy = subprocess.Popen(
        [str(script), "meetingminer.api.main:app", "--host", "127.0.0.1"],
        start_new_session=True,
    )
    (logs / "api.pid").write_text(str(decoy.pid), encoding="utf-8")
    try:
        proc = _make(
            ["start-api"],
            {"API_PORT": str(_free_port()), "READY_TRIES": "3", "READY_DELAY": "0.1"},
            logs=logs,
            tmp_path=tmp_path,
        )
        output = proc.stdout + proc.stderr
        assert proc.returncode != 0, output
        assert "already running" in output
        assert "never became ready" in output
        assert "api: failed to start" in output
        assert _wait_no_match(str(tmp_path / "venv")), "hung process was not stopped"
    finally:
        _cleanup(decoy)
        _kill_stragglers(str(tmp_path))


# =========================================================================
# I/O & edge-case matrix rows (story 1.10). Every row below is driven
# through the real make recipes with overridable variables (LOGS, VENV,
# WEB, ENVFILE, API_PORT, …) plus PATH-injected decoys — no Docker, no
# real services, and the repo's own .logs/ is never touched.
# =========================================================================


# --- row: fresh clone, generated client absent ----------------------------


def test_check_client_fails_with_named_error_when_client_absent(
    tmp_path: Path,
) -> None:
    """`up` must not proceed into a Vite import-resolution error (finding 1)."""
    web = tmp_path / "web"
    (web / "src").mkdir(parents=True)  # a checkout without src/client/
    proc = _make(["check-client"], {"WEB": str(web)})
    assert proc.returncode != 0
    assert "generated TS client incomplete" in proc.stdout + proc.stderr


def test_check_client_passes_on_the_real_checkout() -> None:
    """The committed client is present, so a fresh clone gets past the guard."""
    proc = _make(["check-client"], {})
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_check_client_supports_a_web_path_with_spaces(tmp_path: Path) -> None:
    """Repository-derived shell paths stay quoted (review finding 2)."""
    web = tmp_path / "web with spaces"
    client_dir = web / "src" / "client"
    client_dir.mkdir(parents=True)
    for name in ("client.gen.ts", "sdk.gen.ts", "types.gen.ts"):
        (client_dir / name).write_text("// generated", encoding="utf-8")

    proc = _make(["check-client"], {"WEB": str(web)})
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_check_client_rejects_a_partial_client(tmp_path: Path) -> None:
    """App.tsx imports client.gen.ts, sdk.gen.ts and types.gen.ts, so a
    checkout carrying only some of them is just as broken as one carrying
    none — the guard must not pass it."""
    client_dir = tmp_path / "web" / "src" / "client"
    client_dir.mkdir(parents=True)
    for name in ("client.gen.ts", "sdk.gen.ts"):  # types.gen.ts missing
        (client_dir / name).write_text("// generated", encoding="utf-8")

    proc = _make(["check-client"], {"WEB": str(tmp_path / "web")})
    assert proc.returncode != 0
    assert "types.gen.ts is missing" in proc.stdout + proc.stderr


def test_make_web_refuses_without_the_generated_client(tmp_path: Path) -> None:
    """The foreground dev server is a documented path to the same broken
    fresh-clone page that finding 1 exists to prevent, so it carries the same
    guard as start-web."""
    web = tmp_path / "web"
    (web / "src").mkdir(parents=True)
    proc = _make(["web"], {"WEB": str(web)}, timeout=60)
    output = proc.stdout + proc.stderr
    assert proc.returncode != 0
    # Specifically the client guard — not merely "web deps missing", which
    # would also fail here if the client check had been dropped.
    assert "generated TS client incomplete" in output


def test_check_env_rejects_an_unreadable_env_file(tmp_path: Path) -> None:
    """-r, not -f (finding 12): a present but unreadable .env must fail the
    guard that exists to name exactly that problem."""
    envfile = tmp_path / ".env"
    envfile.write_text("POSTGRES_PASSWORD=x\n", encoding="utf-8")
    envfile.chmod(0o000)
    try:
        proc = _make(["check-env"], {"ENVFILE": str(envfile)})
        assert proc.returncode != 0
        assert "missing or unreadable" in proc.stdout + proc.stderr
    finally:
        envfile.chmod(0o600)


def test_check_env_rejects_a_readable_env_without_a_drops_root(tmp_path: Path) -> None:
    envfile = tmp_path / ".env"
    envfile.write_text("POSTGRES_PASSWORD=x\n", encoding="utf-8")

    proc = _make(["check-env"], {"ENVFILE": str(envfile)})

    assert proc.returncode != 0
    assert "MM_DROPS_ROOT is not set" in proc.stdout + proc.stderr


@pytest.mark.parametrize("quoted", ['""', "''"])
def test_check_env_rejects_a_quoted_empty_drops_root(
    tmp_path: Path, quoted: str
) -> None:
    envfile = tmp_path / ".env"
    envfile.write_text(f"MM_DROPS_ROOT={quoted}\n", encoding="utf-8")

    proc = _make(["check-env"], {"ENVFILE": str(envfile)})

    assert proc.returncode != 0
    assert "MM_DROPS_ROOT is empty" in proc.stdout + proc.stderr


def test_unwritable_logs_dir_fails_loudly(tmp_path: Path) -> None:
    """A pidfile claim can fail because another start holds it (skip) or
    because the pidfile cannot be created at all (unwritable directory, full
    disk). The second must never be reported as a duplicate start that
    silently launched nothing."""
    logs = tmp_path / "logs"
    logs.mkdir()
    venv = tmp_path / "venv"
    _write_script(venv / "bin" / "uvicorn", DECOY_BODY)
    logs.chmod(0o500)  # readable, not writable
    try:
        proc = _make(
            ["start-api"], {"API_PORT": str(_free_port())}, logs=logs, tmp_path=tmp_path
        )
        output = proc.stdout + proc.stderr
        assert proc.returncode != 0, output
        assert "cannot create" in output
        assert "skipping duplicate start" not in output
    finally:
        logs.chmod(0o700)
        _kill_stragglers(str(tmp_path))


def test_worker_readiness_ignores_a_startup_line_from_a_previous_run(
    tmp_path: Path,
) -> None:
    """Readiness reads only the bytes this run appended: worker.log is
    append-only across restarts, so an old `worker.startup` line would
    otherwise pass a worker that came up hung and never logged anything."""
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "worker.log").write_text(
        '{"ts": "2026-08-18T00:00:00+00:00", "event": "worker.startup"}\n',
        encoding="utf-8",
    )
    venv = tmp_path / "venv"
    # Matches the worker pattern, stays alive, logs nothing.
    _write_script(venv / "bin" / "python", DECOY_BODY)

    try:
        proc = _make(
            ["start-worker"],
            {"READY_TRIES": "3", "READY_DELAY": "0.1"},
            logs=logs,
            tmp_path=tmp_path,
        )
        output = proc.stdout + proc.stderr
        assert proc.returncode != 0, output
        assert "never became ready" in output
        assert "worker: failed to start" in output
    finally:
        _kill_stragglers(str(tmp_path))


def test_worker_readiness_accepts_the_startup_line_this_run_wrote(
    tmp_path: Path,
) -> None:
    """The mirror of the test above: a worker that does log startup after a
    stale line is still recognized as ready."""
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "worker.log").write_text(
        '{"ts": "2026-08-18T00:00:00+00:00", "event": "worker.startup"}\n',
        encoding="utf-8",
    )
    venv = tmp_path / "venv"
    _write_script(
        venv / "bin" / "python",
        "#!/bin/bash\n"
        "echo '{\"ts\": \"now\", \"event\": \"worker.startup\"}'\n"
        "trap 'exit 0' TERM INT\n"
        "while :; do sleep 1; done\n",
    )
    try:
        proc = _make(["start-worker"], logs=logs, tmp_path=tmp_path)
        output = proc.stdout + proc.stderr
        assert proc.returncode == 0, output
        assert "worker: ready" in output
    finally:
        _kill_from_pidfile(logs / "worker.pid")
        _kill_stragglers(str(tmp_path))


def test_repeated_worker_start_keeps_the_existing_worker_running(tmp_path: Path) -> None:
    """A repeat start verifies the owned process is alive; it must not demand
    a second startup event from an already-running worker."""
    logs = tmp_path / "logs"
    logs.mkdir()
    decoy = _spawn_decoy(tmp_path, *MATCHING["worker"])
    (logs / "worker.pid").write_text(str(decoy.pid), encoding="utf-8")
    (logs / "worker.log").write_text(
        '{"ts": "earlier", "event": "worker.startup"}\n', encoding="utf-8"
    )
    try:
        proc = _make(["start-worker"], logs=logs, tmp_path=tmp_path, timeout=60)
        output = proc.stdout + proc.stderr
        assert proc.returncode == 0, output
        assert f"worker: already running (pid {decoy.pid})" in output
        assert "worker: ready" in output
        assert decoy.poll() is None
    finally:
        _cleanup(decoy)
        _kill_stragglers(str(tmp_path))


# --- row: process dies during startup -------------------------------------


def test_start_api_failure_names_process_and_tails_its_log(tmp_path: Path) -> None:
    """A process that dies during startup must fail `up` with the process
    named and its last log lines printed — never just a log path (finding 5)."""
    logs = tmp_path / "logs"
    logs.mkdir()
    venv = tmp_path / "venv"
    _write_script(venv / "bin" / "uvicorn", DIE_BODY)

    proc = _make(
        ["start-api"],
        {
            "VENV": str(venv),
            "API_PORT": str(_free_port()),
            "READY_TRIES": "5",
            "READY_DELAY": "0.1",
        },
        logs=logs,
    )
    output = proc.stdout + proc.stderr
    assert proc.returncode != 0
    assert "api: failed to start" in output
    # The tail of the dead process's log, not merely its path.
    assert "decoy: exploded during startup" in output
    assert not (logs / "api.pid").exists()


def test_start_api_alive_but_never_ready_is_a_failure(tmp_path: Path) -> None:
    """Liveness is not readiness (finding 6): a process that stays up but
    never binds its port must fail the start and be stopped."""
    logs = tmp_path / "logs"
    logs.mkdir()
    venv = tmp_path / "venv"
    _write_script(venv / "bin" / "uvicorn", DECOY_BODY)  # lives, never binds

    try:
        proc = _make(
            ["start-api"],
            {
                "VENV": str(venv),
                "API_PORT": str(_free_port()),
                "READY_TRIES": "3",
                "READY_DELAY": "0.1",
            },
            logs=logs,
        )
        output = proc.stdout + proc.stderr
        assert proc.returncode != 0
        assert "never became ready" in output
        assert "api: failed to start" in output
        assert not (logs / "api.pid").exists()
        # The never-ready process was stopped, not left behind.
        assert _wait_no_match(str(venv)), "never-ready process was not stopped"
    finally:
        _kill_stragglers(str(tmp_path))


# --- row: .logs/ deleted while processes run ------------------------------


def test_down_warns_about_processes_it_holds_no_pidfile_for(tmp_path: Path) -> None:
    """Lost pidfiles must not orphan processes silently (finding 7): `down`
    names the stray pids and still exits 0."""
    decoy = _spawn_decoy(tmp_path, *MATCHING["api"])
    logs = tmp_path / "logs"  # stands in for a deleted .logs/
    logs.mkdir()
    envfile = tmp_path / ".env"
    envfile.write_text("POSTGRES_PASSWORD=x\n", encoding="utf-8")
    docker_bin = tmp_path / "path"
    argv_log = tmp_path / "docker-argv.txt"
    _write_script(
        docker_bin / "docker",
        DOCKER_BODY.replace("__ARGV__", str(argv_log))
        .replace("__EVENTS__", str(tmp_path / "events.txt"))
        .replace("__ENVFILE_EXIT__", "0"),
    )
    try:
        proc = _make(
            ["down"],
            {"ENVFILE": str(envfile)},
            logs=logs,
            tmp_path=tmp_path,
            env=_path_env(docker_bin),
        )
        output = proc.stdout + proc.stderr
        assert proc.returncode == 0, output
        assert "still running without pidfiles" in output
        assert str(decoy.pid) in output
        assert decoy.poll() is None  # warned about, not killed
    finally:
        _cleanup(decoy)


# --- row: .env breaks compose interpolation -------------------------------


def test_down_falls_back_when_env_file_interpolation_fails(tmp_path: Path) -> None:
    """A broken .env must never leave containers running (finding 8)."""
    logs = tmp_path / "logs"
    logs.mkdir()
    envfile = tmp_path / ".env"
    envfile.write_text("POSTGRES_PASSWORD=\n", encoding="utf-8")
    docker_bin = tmp_path / "path"
    argv_log = tmp_path / "docker-argv.txt"
    _write_script(
        docker_bin / "docker",
        DOCKER_BODY.replace("__ARGV__", str(argv_log))
        .replace("__EVENTS__", str(tmp_path / "events.txt"))
        # every `compose --env-file …` invocation fails, as compose does when
        # a required ${VAR:?} has no value
        .replace("__ENVFILE_EXIT__", "1"),
    )

    proc = _make(
        ["down"],
        {"ENVFILE": str(envfile)},
        logs=logs,
        tmp_path=tmp_path,
        env=_path_env(docker_bin),
    )
    output = proc.stdout + proc.stderr
    assert proc.returncode == 0, output
    assert "falling back to project-name teardown" in output

    invocations = argv_log.read_text(encoding="utf-8").splitlines()
    assert any(line.startswith("compose --env-file") for line in invocations)
    # The fallback actually ran, without --env-file interpolation.
    assert "compose -p meetingminer down" in invocations


# --- row: a worktree's private stack (story 11.2) ---------------------------


def test_down_refuses_a_linked_worktree_without_an_ownership_record(
    tmp_path: Path,
) -> None:
    """A missing record must not make worktree teardown target main."""
    repo, docker_bin, argv_log = _throwaway_repo(tmp_path)
    worktree = _linked_worktree_without_stack(repo, "probe")
    argv_log.write_text("", encoding="utf-8")

    proc = _make_at(worktree, docker_bin, ["down"])
    output = proc.stdout + proc.stderr
    assert proc.returncode != 0, output
    assert "linked git worktree with no .env.worktree" in output
    assert not any("compose" in line for line in _argv_lines(argv_log))


def test_down_tears_down_the_worktree_stack_named_in_env_worktree(tmp_path: Path) -> None:
    """A checkout with a `.env.worktree` passes it to compose as the second
    --env-file and names ITS project — on the fallback path too, so a broken
    .env can never tear down the main checkout's stack instead."""
    logs = tmp_path / "logs"
    logs.mkdir()
    envfile = tmp_path / ".env"
    envfile.write_text("POSTGRES_PASSWORD=x\n", encoding="utf-8")
    worktree_env = tmp_path / ".env.worktree"
    worktree_env.write_text(
        "MM_STACK_NAME=meetingminer-probe\nMM_POSTGRES_PORT=20001\n", encoding="utf-8"
    )
    docker_bin = tmp_path / "path"
    argv_log = tmp_path / "docker-argv.txt"
    _write_script(
        docker_bin / "docker",
        DOCKER_BODY.replace("__ARGV__", str(argv_log))
        .replace("__EVENTS__", str(tmp_path / "events.txt"))
        .replace("__ENVFILE_EXIT__", "1"),
    )

    proc = _make(
        ["down"],
        {"ENVFILE": str(envfile)},
        logs=logs,
        tmp_path=tmp_path,
        env=_path_env(docker_bin),
    )
    output = proc.stdout + proc.stderr
    assert proc.returncode == 0, output

    invocations = argv_log.read_text(encoding="utf-8").splitlines()
    prefix = f"compose --env-file {envfile} --env-file {worktree_env} -p meetingminer-probe "
    assert any(
        line.startswith(prefix) and line.endswith(" down") for line in invocations
    ), invocations
    assert "compose -p meetingminer-probe down" in invocations
    assert "compose -p meetingminer down" not in invocations


def test_compose_receives_the_resolved_stack_values_through_the_environment(tmp_path: Path) -> None:
    """The process environment wins over `.env.worktree` for `-p` AND for the
    values compose interpolates; a blank exported value is unset, so the
    file's values reach compose (compose alone would publish the default)."""
    logs = tmp_path / "logs"
    logs.mkdir()
    envfile = tmp_path / ".env"
    envfile.write_text("POSTGRES_PASSWORD=x\n", encoding="utf-8")
    (tmp_path / ".env.worktree").write_text(
        "MM_STACK_NAME=meetingminer-probe\nMM_POSTGRES_PORT=20001\n", encoding="utf-8"
    )
    docker_bin = tmp_path / "path"
    argv_log = tmp_path / "docker-argv.txt"
    _write_script(
        docker_bin / "docker",
        DOCKER_BODY.replace("__ARGV__", str(argv_log))
        .replace("__EVENTS__", str(tmp_path / "events.txt"))
        .replace("__ENVFILE_EXIT__", "0"),
    )

    def run_down(overrides: dict[str, str]) -> list[str]:
        argv_log.write_text("", encoding="utf-8")
        proc = _make(
            ["down"],
            {"ENVFILE": str(envfile)},
            logs=logs,
            tmp_path=tmp_path,
            env=_path_env(docker_bin) | overrides,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        return _argv_lines(argv_log)

    lines = run_down({"MM_STACK_NAME": "meetingminer-envname", "MM_POSTGRES_PORT": "20099"})
    assert any(line.startswith("compose --env-file") and " -p meetingminer-envname " in line for line in lines), lines
    assert "env MM_STACK_NAME=meetingminer-envname MM_POSTGRES_PORT=20099" in lines

    lines = run_down({"MM_STACK_NAME": "", "MM_POSTGRES_PORT": ""})
    assert any(line.startswith("compose --env-file") and " -p meetingminer-probe " in line for line in lines), lines
    assert "env MM_STACK_NAME=meetingminer-probe MM_POSTGRES_PORT=20001" in lines


def test_check_dev_stores_probes_this_checkouts_ports(tmp_path: Path) -> None:
    """With a `.env.worktree`, the Meilisearch probe hits its port and the
    Bolt probe names its port in the error."""
    bolt_port = _free_port()
    (tmp_path / ".env.worktree").write_text(
        f"MM_MEILI_PORT=20004\nMM_NEO4J_BOLT_PORT={bolt_port}\n", encoding="utf-8"
    )
    fake_bin = tmp_path / "path"
    curl_log = tmp_path / "curl-argv.txt"
    _write_script(fake_bin / "curl", f"#!/bin/bash\necho \"$*\" >> {curl_log}\nexit 0\n")
    proc = _make(["check-dev-stores"], tmp_path=tmp_path, env=_path_env(fake_bin))
    output = proc.stdout + proc.stderr
    assert proc.returncode != 0, output
    assert "http://localhost:20004/health" in curl_log.read_text(encoding="utf-8")
    assert f"Neo4j Bolt is not answering on :{bolt_port}" in output


# --- row: foreign service on :8000 ----------------------------------------


def test_client_refuses_a_foreign_service(tmp_path: Path) -> None:
    """`make client` verifies identity, not reachability (finding 11)."""
    fake_bin = tmp_path / "path"
    pnpm_marker = tmp_path / "pnpm-was-called.txt"
    _write_script(
        fake_bin / "curl",
        '#!/bin/bash\necho \'{"status":"ok","service":"some-other-api"}\'\nexit 0\n',
    )
    _write_script(
        fake_bin / "pnpm",
        f"#!/bin/bash\necho \"$*\" >> {pnpm_marker}\nexit 0\n",
    )

    proc = _make(["client"], {}, env=_path_env(fake_bin))
    output = proc.stdout + proc.stderr
    assert proc.returncode != 0
    assert "did not identify as the MeetingMiner api" in output
    assert not pnpm_marker.exists(), "client generation must not run"


def test_client_accepts_the_meetingminer_api(tmp_path: Path) -> None:
    """The identity guard passes for the real service name, so `make client`
    still works — the guard rejects foreigners, not everyone."""
    fake_bin = tmp_path / "path"
    pnpm_marker = tmp_path / "pnpm-was-called.txt"
    _write_script(
        fake_bin / "curl",
        '#!/bin/bash\necho \'{"status":"ok","service":"meetingminer-api"}\'\nexit 0\n',
    )
    _write_script(
        fake_bin / "pnpm",
        f"#!/bin/bash\necho \"$*\" >> {pnpm_marker}\nexit 0\n",
    )

    proc = _make(["client"], {}, env=_path_env(fake_bin))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert pnpm_marker.exists()
    assert "run client" in pnpm_marker.read_text(encoding="utf-8")


# --- row: old flat imports are gone ---------------------------------------


@pytest.mark.parametrize("module", ["config", "db", "api.main", "worker.main", "domain"])
def test_flat_top_level_modules_are_not_importable(module: str) -> None:
    """The installed distribution must claim no generic top-level name
    (finding 19). Run from the repo root — the strictest realistic cwd."""
    proc = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=60,
    )
    assert proc.returncode != 0
    assert "ModuleNotFoundError" in proc.stderr


@pytest.mark.parametrize(
    "module",
    ["meetingminer.config", "meetingminer.db", "meetingminer.domain.jobs"],
)
def test_namespaced_modules_are_importable(module: str) -> None:
    proc = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr


# --- row: concurrent `make up` x2 / `make -j up` --------------------------


def test_empty_pidfile_is_an_in_flight_claim_not_a_stale_file(
    tmp_path: Path,
) -> None:
    """Deterministic cover for the noclobber claim window.

    Between one start's `: > api.pid` claim and its `echo $! > api.pid`, the
    pidfile exists but is empty. A second start that reads it in that window
    must wait for the pid rather than deleting the claim and launching a
    duplicate. Reproduced exactly: an empty pidfile whose pid arrives shortly
    after, with a live matching process behind it.

    (The two-real-makes test below asserts the same end-to-end property but
    cannot be relied on to land inside this microsecond-wide window.)
    """
    logs = tmp_path / "logs"
    logs.mkdir()
    venv = tmp_path / "venv"
    events = tmp_path / "events.txt"
    launches = tmp_path / "launches.txt"
    port = _free_port()
    # The winner behind the claim has to actually serve: readiness now runs on
    # the already-running path too, so a hung stand-in would fail the start.
    script = _serving_decoy(venv / "bin" / "uvicorn", "start-api", events, launches)
    decoy = subprocess.Popen(
        [str(script), "meetingminer.api.main:app", "--host", "127.0.0.1",
         "--port", str(port)],
        start_new_session=True,
    )
    pidfile = logs / "api.pid"
    pidfile.write_text("", encoding="utf-8")  # claim in flight, pid not yet written

    def fill_claim() -> None:
        time.sleep(0.4)
        pidfile.write_text(f"{decoy.pid}\n", encoding="utf-8")

    filler = threading.Thread(target=fill_claim)
    filler.start()
    try:
        proc = _make(
            ["start-api"], {"API_PORT": str(port)}, logs=logs, tmp_path=tmp_path
        )
        output = proc.stdout + proc.stderr
        assert proc.returncode == 0, output
        assert f"api: already running (pid {decoy.pid})" in output
        launched = launches.read_text(encoding="utf-8").split()
        assert launched == [str(decoy.pid)], (
            f"the in-flight claim must not be duplicated, got launches {launched}"
        )
    finally:
        filler.join()
        _cleanup(decoy)
        _kill_from_pidfile(pidfile)
        _kill_stragglers(str(tmp_path))


def test_unfilled_fresh_pidfile_claim_fails_instead_of_reporting_success(
    tmp_path: Path,
) -> None:
    """A concurrent starter cannot claim success until the owner publishes a
    PID that readiness can verify."""
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "api.pid").write_text("", encoding="utf-8")
    venv = tmp_path / "venv"
    _write_script(venv / "bin" / "uvicorn", DECOY_BODY)

    proc = _make(
        ["start-api"],
        {"API_PORT": str(_free_port()), "CLAIM_TRIES": "2", "CLAIM_DELAY": "0.01"},
        logs=logs,
        tmp_path=tmp_path,
    )
    output = proc.stdout + proc.stderr
    assert proc.returncode != 0, output
    assert "did not publish a pid" in output


def test_two_concurrent_starts_launch_exactly_one_process(tmp_path: Path) -> None:
    """Two `make up` invocations racing must not produce duplicate processes
    (finding 4): the noclobber pidfile claim lets exactly one through."""
    logs = tmp_path / "logs"
    logs.mkdir()
    venv = tmp_path / "venv"
    events = tmp_path / "events.txt"
    launches = tmp_path / "launches.txt"
    _serving_decoy(venv / "bin" / "uvicorn", "start-api", events, launches)
    variables = {
        "VENV": str(venv),
        "API_PORT": str(_free_port()),
    }

    results: list[subprocess.CompletedProcess[str]] = []
    barrier = threading.Barrier(2)

    def run() -> None:
        barrier.wait()
        results.append(_make(["start-api"], variables, logs=logs))

    threads = [threading.Thread(target=run) for _ in range(2)]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)
        # Assert completion explicitly: a hung make would otherwise surface as
        # a confusing missing-file error below instead of a timeout.
        assert all(not thread.is_alive() for thread in threads), "a make run hung"
        assert len(results) == 2

        assert launches.exists(), "neither start launched the process"
        launched = launches.read_text(encoding="utf-8").split()
        assert len(launched) == 1, f"expected one launch, got {launched}"

        combined = "\n".join(r.stdout + r.stderr for r in results)
        assert (
            "skipping duplicate start" in combined
            or "already running" in combined
        ), combined
        assert "api: ready" in combined
    finally:
        _kill_from_pidfile(logs / "api.pid")
        _kill_stragglers(str(tmp_path))


def test_parallel_make_up_runs_stores_then_migrate_then_host_processes(
    tmp_path: Path,
) -> None:
    """`make -j up` must not race host processes past the store healthcheck
    gate (finding 3). Drives the whole `up` chain under `-j4` with decoy
    docker/venv/web, asserting the real execution order.

    This covers the ordering guarantee; it does not exercise real container
    health, which would need Docker.
    """
    logs = tmp_path / "logs"
    logs.mkdir()
    events = tmp_path / "events.txt"
    launches = tmp_path / "launches.txt"
    argv_log = tmp_path / "docker-argv.txt"

    venv = tmp_path / "venv"
    _serving_decoy(venv / "bin" / "uvicorn", "start-api", events, launches)
    _write_script(venv / "bin" / "python", PYTHON_BODY.replace("__EVENTS__", str(events)))

    web = tmp_path / "web"
    (web / "src" / "client").mkdir(parents=True)
    for _name in ("client.gen.ts", "sdk.gen.ts", "types.gen.ts"):
        (web / "src" / "client" / _name).write_text("//", encoding="utf-8")
    _serving_decoy(web / "node_modules" / ".bin" / "vite", "start-web", events, launches)

    docker_bin = tmp_path / "path"
    _write_script(
        docker_bin / "docker",
        DOCKER_BODY.replace("__ARGV__", str(argv_log))
        .replace("__EVENTS__", str(events))
        .replace("__ENVFILE_EXIT__", "0"),
    )

    envfile = tmp_path / ".env"
    # MM_DROPS_ROOT so `check-env` (story 2.1a) passes: this test is about what
    # `make up` starts and rolls back, not about the env gate, and without the
    # key it would stop at `check-env` before reaching that.
    envfile.write_text(
        f"POSTGRES_PASSWORD=x\nMM_DROPS_ROOT={tmp_path / 'drops'}\n",
        encoding="utf-8",
    )

    proc = _make(
        ["-j4", "up"],
        {
            "VENV": str(venv),
            "WEB": str(web),
            "ENVFILE": str(envfile),
            "API_PORT": str(_free_port()),
            "WEB_PORT": str(_free_port()),
        },
        logs=logs,
        env=_path_env(docker_bin),
    )
    try:
        output = proc.stdout + proc.stderr
        assert proc.returncode == 0, output
        assert _events(events) == [
            "compose-up",
            "migrate",
            "start-api",
            "start-worker",
            "start-web",
        ], output
        assert "up: stores healthy" in output
    finally:
        for name in ("api", "worker", "web"):
            _kill_from_pidfile(logs / f"{name}.pid")
        _kill_stragglers(str(tmp_path))


def test_up_rolls_back_only_processes_started_by_this_invocation(tmp_path: Path) -> None:
    """A worker startup failure must stop the API that this `up` launched,
    rather than leaving a partial host environment behind (review finding 1)."""
    logs = tmp_path / "logs"
    logs.mkdir()
    events = tmp_path / "events.txt"
    launches = tmp_path / "launches.txt"
    argv_log = tmp_path / "docker-argv.txt"

    venv = tmp_path / "venv"
    _serving_decoy(venv / "bin" / "uvicorn", "start-api", events, launches)
    _write_script(
        venv / "bin" / "python",
        """#!/bin/bash
case \"$*\" in
  *meetingminer.db*) echo \"migrate\" >> \"__EVENTS__\"; exit 0 ;;
  *meetingminer.worker.main*) echo \"worker startup failed\"; exit 1 ;;
esac
exit 0
""".replace("__EVENTS__", str(events)),
    )

    web = tmp_path / "web"
    (web / "src" / "client").mkdir(parents=True)
    for _name in ("client.gen.ts", "sdk.gen.ts", "types.gen.ts"):
        (web / "src" / "client" / _name).write_text("//", encoding="utf-8")

    docker_bin = tmp_path / "path"
    _write_script(
        docker_bin / "docker",
        DOCKER_BODY.replace("__ARGV__", str(argv_log))
        .replace("__EVENTS__", str(events))
        .replace("__ENVFILE_EXIT__", "0"),
    )
    envfile = tmp_path / ".env"
    # MM_DROPS_ROOT so `check-env` (story 2.1a) passes: this test is about what
    # `make up` starts and rolls back, not about the env gate, and without the
    # key it would stop at `check-env` before reaching that.
    envfile.write_text(
        f"POSTGRES_PASSWORD=x\nMM_DROPS_ROOT={tmp_path / 'drops'}\n",
        encoding="utf-8",
    )

    try:
        proc = _make(
            ["up"],
            {
                "VENV": str(venv),
                "WEB": str(web),
                "ENVFILE": str(envfile),
                "API_PORT": str(_free_port()),
                "WEB_PORT": str(_free_port()),
                "READY_TRIES": "10",
                "READY_DELAY": "0.1",
            },
            logs=logs,
            env=_path_env(docker_bin),
        )
        output = proc.stdout + proc.stderr
        assert proc.returncode != 0, output
        assert "worker: failed to start" in output
        assert "api: stopping" in output
        assert _wait_no_match(str(tmp_path)), "API was left running after failed up"
    finally:
        for name in ("api", "worker", "web"):
            _kill_from_pidfile(logs / f"{name}.pid")
        _kill_stragglers(str(tmp_path))


def test_notparallel_directive_is_present() -> None:
    """Structural backstop for the ordering test above: the serial guarantee
    comes from `.NOTPARALLEL:`, so its removal must fail a test even if the
    dynamic ordering run were ever skipped."""
    makefile = (REPO_ROOT / "infra" / "Makefile").read_text(encoding="utf-8")
    assert "\n.NOTPARALLEL:" in makefile


def test_root_delegate_force_target_is_phony() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    assert ".PHONY: FORCE" in makefile


def test_test_target_runs_the_puller_suite() -> None:
    """Structural backstop for AD-1's "puller and pipeline both validate
    against the drop schema in their tests" (story 1.8).

    The puller suite is the only thing that checks emitted drops against
    docs/source-drop.schema.json from the source side. If `puller-test` were
    ever dropped from `test:`, every server test here would still pass and the
    contract would be half-unverified with nothing to say so.
    """
    makefile = (REPO_ROOT / "infra" / "Makefile").read_text(encoding="utf-8")

    test_rule = next(
        line for line in makefile.splitlines()
        if line.startswith("test:")
    )
    assert "puller-test" in test_rule, (
        "infra/Makefile's `test:` target must list puller-test as a prerequisite"
    )
    # It must run before the stores come up: the puller suite needs neither
    # Docker nor the api, so it should fail fast rather than after compose.
    prereqs = test_rule.split(":", 1)[1].split()
    assert prereqs.index("puller-test") < prereqs.index("infra-up")

    # And missing dev deps must fail the target rather than skip it — a skip
    # would make `make test` green on a fresh clone with none of it run.
    puller_rule = makefile.split("\npuller-test:", 1)[1].split("\n\n", 1)[0]
    assert "ajv-formats" in puller_rule
    assert "exit 1" in puller_rule


def _puller_rule() -> str:
    makefile = (REPO_ROOT / "infra" / "Makefile").read_text(encoding="utf-8")
    return makefile.split("\npuller-test:", 1)[1].split("\n\n", 1)[0]


def _puller_dir() -> Path:
    """The directory infra/Makefile's PULLER binding actually names."""
    makefile = (REPO_ROOT / "infra" / "Makefile").read_text(encoding="utf-8")
    match = re.search(r"^PULLER\s*:=\s*\$\(ROOT\)/(.+?)\s*$", makefile, re.M)
    assert match, "infra/Makefile must bind PULLER as $(ROOT)/<path>"
    return REPO_ROOT / match.group(1)


def test_puller_binding_resolves_to_a_real_package() -> None:
    """A stale PULLER binding must not be able to skip the suite silently.

    This is the failure the relocation to tools/puller could have caused one
    level above the schema check: the binding goes stale, `puller-test` takes
    its directory-absent branch, and every puller test — including AD-1's only
    source-side validation of the drop schema — leaves `make test` while it
    still reports green. Reading the rule text cannot catch that, because the
    binding is not in the rule.
    """
    puller = _puller_dir()
    assert puller.is_dir(), f"PULLER names {puller}, which is not a directory"
    assert (puller / "package.json").is_file(), (
        f"PULLER names {puller}, which has no package.json — not the puller package"
    )

    # And the rule must refuse to skip when the binding cannot resolve inside a
    # MeetingMiner checkout, which docs/source-drop.schema.json identifies.
    rule = _puller_rule()
    assert "docs/source-drop.schema.json" in rule, (
        "`puller-test` must distinguish a standalone checkout, where the puller "
        "may legitimately be absent, from this repo, where a missing PULLER is a "
        "stale binding and must fail rather than skip"
    )


def test_puller_suite_cannot_skip_its_drop_schema_cases() -> None:
    """The suite finds docs/source-drop.schema.json by searching upward, and a
    miss is indistinguishable from a standalone checkout — which it skips. The
    test file arms itself whenever it can see a repo marker above it, and the
    Makefile sets the flag too, so neither `make puller-test` nor a bare
    `npm test` in tools/puller can report green with the contract unchecked.
    """
    assert "MM_REQUIRE_DROP_SCHEMA=1" in _puller_rule(), (
        "infra/Makefile's `puller-test` must run the suite with "
        "MM_REQUIRE_DROP_SCHEMA=1 so the drop-schema cases cannot skip here"
    )


# --- rows: worktree provision / bad slug / remove (story 11.2) --------------
#
# The real infra/Makefile, worktree_stack.py and docker-compose.yml run against
# a throwaway git repository under tmp_path, so nothing here touches this
# repository, its branches, or Docker: the Makefile derives ROOT from its own
# location and WT_ROOT from that repo's git common dir, and `docker` on PATH
# is a decoy that records its argv. python3 is the real one (worktree_stack.py
# is stdlib-only and probes real loopback ports, which is what `make worktree`
# does too).

WORKTREE_DOCKER_BODY = """#!/bin/bash
echo "$*" >> "__ARGV__"
echo "env MM_STACK_NAME=$MM_STACK_NAME MM_POSTGRES_PORT=$MM_POSTGRES_PORT" >> "__ARGV__"
if [ "$1" = "info" ]; then exit __INFO_EXIT__; fi
case "$*" in
  "ps -aq --filter "*) if [ "__PS_Q_EXIT__" != "0" ]; then exit __PS_Q_EXIT__; fi; echo "deadbeefcafe" ;;
  "ps -a --filter "*) if [ "__PS_Q_EXIT__" != "0" ]; then exit __PS_Q_EXIT__; fi; printf '%b' "__PS_ROWS__" ;;
  "volume ls -q --filter "*) : ;;
  "volume ls --filter "*) printf '%b' "__VOLUME_ROWS__" ;;
esac
case "$*" in
  compose*" down"*) exit __DOWN_EXIT__ ;;
  *" up "*) exit __UP_EXIT__ ;;
esac
exit 0
"""


def _write_worktree_docker(
    docker_bin: Path,
    argv_log: Path,
    *,
    info_exit: int = 0,
    ps_rows: str = "",
    volume_rows: str = "",
    up_exit: int = 0,
    down_exit: int = 0,
    ps_q_exit: int = 0,
) -> None:
    _write_script(
        docker_bin / "docker",
        WORKTREE_DOCKER_BODY.replace("__ARGV__", str(argv_log))
        .replace("__INFO_EXIT__", str(info_exit))
        .replace("__PS_Q_EXIT__", str(ps_q_exit))
        .replace("__UP_EXIT__", str(up_exit))
        .replace("__DOWN_EXIT__", str(down_exit))
        .replace("__PS_ROWS__", ps_rows.replace("\\", "\\\\"))
        .replace("__VOLUME_ROWS__", volume_rows.replace("\\", "\\\\")),
    )

PRUNE_PS_PREFIX = "ps -a --filter label=com.docker.compose.project"

_GIT_ID = ["-c", "user.name=test", "-c", "user.email=test@example.invalid"]


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *_GIT_ID, "-C", str(repo), *args], capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc.stdout.strip()


def _throwaway_repo(
    tmp_path: Path,
    *,
    docker_info_exit: int = 0,
    ps_rows: str = "",
    volume_rows: str = "",
    up_exit: int = 0,
    down_exit: int = 0,
    ps_q_exit: int = 0,
    origin: bool = False,
) -> tuple[Path, Path, Path]:
    """A committed `main` with the real infra files, a `.env`, and a decoy docker.

    Returns (repo, docker_bin, argv_log). The repository's REAL `.gitignore`
    is committed: `git worktree remove` counts untracked files as dirt, so
    the generated `.env.worktree` and the `.env` link must be ignored for a
    clean removal, exactly as in this repository. `ps_rows` is what the decoy
    answers to the pruner's `docker ps -a --filter …` (tab-separated
    `project<TAB>working_dir` lines). `origin` adds a bare remote with `main`
    pushed, for `worktree-prune`.
    """
    repo = tmp_path / "repo"
    infra = repo / "infra"
    infra.mkdir(parents=True)
    for name in ("Makefile", "worktree_stack.py", "docker-compose.yml"):
        (infra / name).write_bytes((REPO_ROOT / "infra" / name).read_bytes())
    (repo / ".gitignore").write_bytes((REPO_ROOT / ".gitignore").read_bytes())
    (repo / ".env").write_text(f"POSTGRES_PASSWORD=x\nMM_DROPS_ROOT={tmp_path}\n", encoding="utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", ".gitignore", "infra")
    _git(repo, "commit", "-q", "-m", "base")
    if origin:
        bare = tmp_path / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True, timeout=60)
        _git(repo, "remote", "add", "origin", str(bare))
        _git(repo, "push", "-q", "origin", "main")
    docker_bin = tmp_path / "path"
    argv_log = tmp_path / "docker-argv.txt"
    _write_worktree_docker(
        docker_bin,
        argv_log,
        info_exit=docker_info_exit,
        ps_rows=ps_rows,
        volume_rows=volume_rows,
        up_exit=up_exit,
        down_exit=down_exit,
        ps_q_exit=ps_q_exit,
    )
    return repo, docker_bin, argv_log


def _linked_worktree_without_stack(repo: Path, slug: str) -> Path:
    """A linked worktree made by git alone: `.env` linked, no `.env.worktree`."""
    worktree = repo.parent / "meetingminer-wt" / slug
    _git(repo, "worktree", "add", "-q", "-b", f"story/{slug}", str(worktree), "main")
    (worktree / ".env").symlink_to(repo / ".env")
    return worktree


def _compose_up_line(env_dir: Path, compose_file: Path, project_dir: Path, project: str) -> str:
    return (
        f"compose --env-file {env_dir / '.env'} --env-file {env_dir / '.env.worktree'}"
        f" -p {project} -f {compose_file} --project-directory {project_dir} up -d --wait"
    )


def _make_at(
    repo: Path, docker_bin: Path, targets: list[str], variables: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """`make -C <repo>/infra <targets> VAR=value ...` with the decoy docker on PATH."""
    env = _path_env(docker_bin)
    for key in ("MAKEFLAGS", "MFLAGS", "MAKELEVEL"):
        env.pop(key, None)
    return subprocess.run(
        ["make", "-C", str(repo / "infra"), *targets, *(f"{k}={v}" for k, v in (variables or {}).items())],
        capture_output=True,
        text=True,
        env=env,
        timeout=180,
    )


def _argv_lines(argv_log: Path) -> list[str]:
    return argv_log.read_text(encoding="utf-8").splitlines() if argv_log.exists() else []


def _set_stack_inventory(
    docker_bin: Path,
    argv_log: Path,
    worktrees: list[Path],
    *,
    down_exit: int = 0,
    ps_exit: int = 0,
) -> None:
    """Rewrite the decoy with the compose resources provisioned by the test."""
    ps_rows: list[str] = []
    volume_rows: list[str] = []
    volume_names = (
        "postgres-data",
        "neo4j-data",
        "neo4j-logs",
        "meilisearch-data",
        "neo4j-test-data",
        "neo4j-test-logs",
        "meilisearch-test-data",
    )
    for worktree in worktrees:
        values = dict(
            line.split("=", 1)
            for line in (worktree / ".env.worktree").read_text(encoding="utf-8").splitlines()
            if line and not line.startswith("#") and "=" in line
        )
        project = values["MM_STACK_NAME"]
        stack_id = values["MM_STACK_ID"]
        ps_rows.append(f"{project}\t{worktree / 'infra'}\t{stack_id}\n")
        volume_rows.extend(
            f"{project}_{name}\t{project}\t{stack_id}\n" for name in volume_names
        )
    _write_worktree_docker(
        docker_bin,
        argv_log,
        ps_rows="".join(ps_rows),
        volume_rows="".join(volume_rows),
        down_exit=down_exit,
        ps_q_exit=ps_exit,
    )


def test_worktree_provisions_and_starts_a_private_stack(tmp_path: Path) -> None:
    """Row `Provision`, Docker up: worktree on story/<slug> from main beside the
    repo, `.env` linked, `.env.worktree` written, compose told the stack's
    name and both env files, and the banner naming it."""
    repo, docker_bin, argv_log = _throwaway_repo(tmp_path)
    proc = _make_at(repo, docker_bin, ["worktree"], {"STORY": "probe"})
    output = proc.stdout + proc.stderr
    assert proc.returncode == 0, output

    worktree = tmp_path / "meetingminer-wt" / "probe"  # WT_ROOT from the git common dir
    assert worktree.is_dir(), output
    assert _git(repo, "rev-parse", "--verify", "refs/heads/story/probe")
    assert _git(worktree, "rev-parse", "--abbrev-ref", "HEAD") == "story/probe"
    assert (worktree / ".env").is_symlink()
    assert (worktree / ".env").resolve() == (repo / ".env").resolve()
    env_lines = (worktree / ".env.worktree").read_text(encoding="utf-8").splitlines()
    assert "MM_STACK_NAME=meetingminer-probe" in env_lines
    ports = [line for line in env_lines if re.match(r"^MM_[A-Z0-9_]+_PORT=\d+$", line)]
    assert len(ports) == 7, env_lines

    lines = _argv_lines(argv_log)
    expected_up = _compose_up_line(
        worktree, repo / "infra" / "docker-compose.yml", worktree / "infra", "meetingminer-probe"
    )
    assert expected_up in lines, lines
    # The stale-stack sweep for this name ran first, and nothing was torn down.
    sweep = [i for i, line in enumerate(lines) if line.startswith(PRUNE_PS_PREFIX)]
    assert sweep and sweep[0] < lines.index(expected_up), lines
    assert not any(" down " in line for line in lines)
    assert "no stale stack meetingminer-probe" in output
    assert "stack meetingminer-probe is up" in output
    assert "MM_STACK_NAME=meetingminer-probe" in output


def test_worktree_starts_the_stack_through_the_invoking_makefile_and_compose_file(tmp_path: Path) -> None:
    """A worktree checked out from a pre-11.2 ref carries an old infra/: its
    Makefile has no stack targets and its compose file would start the MAIN
    stack. The invoking checkout's Makefile and compose file bring the new
    stack up, with the new worktree's env files and infra/ as the project
    directory (the label the pruner keys on)."""
    repo, docker_bin, argv_log = _throwaway_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "old")
    (repo / "infra" / "Makefile").write_text("all:\n\t@echo old makefile\n", encoding="utf-8")
    (repo / "infra" / "docker-compose.yml").write_text(
        "name: meetingminer\nservices: {}\n", encoding="utf-8"
    )
    _git(repo, "commit", "-q", "-am", "pre-11.2 infra")
    _git(repo, "checkout", "-q", "main")

    proc = _make_at(repo, docker_bin, ["worktree"], {"STORY": "probe", "BASE": "old"})
    output = proc.stdout + proc.stderr
    assert proc.returncode == 0, output
    worktree = tmp_path / "meetingminer-wt" / "probe"
    assert (worktree / "infra" / "Makefile").read_text(encoding="utf-8").startswith("all:")
    lines = _argv_lines(argv_log)
    expected_up = _compose_up_line(
        worktree, repo / "infra" / "docker-compose.yml", worktree / "infra", "meetingminer-probe"
    )
    assert expected_up in lines, lines
    assert "env MM_STACK_NAME=meetingminer-probe MM_POSTGRES_PORT=" in "\n".join(lines)
    assert "stack meetingminer-probe is up" in output


def test_worktree_sweeps_a_stale_stack_of_the_same_name_before_provisioning(tmp_path: Path) -> None:
    """A hand-deleted worktree leaves its project behind; re-using the slug
    must not attach the new worktree to it."""
    gone = tmp_path / "meetingminer-wt" / "probe" / "infra"  # does not exist
    repo, docker_bin, argv_log = _throwaway_repo(tmp_path, ps_rows=f"meetingminer-probe\t{gone}\n")
    proc = _make_at(repo, docker_bin, ["worktree"], {"STORY": "probe"})
    output = proc.stdout + proc.stderr
    assert proc.returncode == 0, output
    lines = _argv_lines(argv_log)
    down = "compose -p meetingminer-probe down -v --remove-orphans"
    assert down in lines, lines
    assert lines.index(down) < next(i for i, line in enumerate(lines) if line.endswith(" up -d --wait"))
    assert "removed stack meetingminer-probe" in output


def test_worktree_refuses_a_slug_whose_stack_belongs_to_an_existing_checkout(tmp_path: Path) -> None:
    other = tmp_path / "meetingminer-wt" / "other"
    (other / "infra").mkdir(parents=True)  # a moved/renamed worktree still running that project
    repo, docker_bin, argv_log = _throwaway_repo(tmp_path, ps_rows=f"meetingminer-probe\t{other / 'infra'}\n")
    proc = _make_at(repo, docker_bin, ["worktree"], {"STORY": "probe"})
    output = proc.stdout + proc.stderr
    assert proc.returncode != 0, output
    assert f"belongs to the existing checkout {other}" in output
    assert not (tmp_path / "meetingminer-wt" / "probe").exists()
    assert _git(repo, "branch", "--list", "story/probe") == ""
    assert not any("down" in line or " up " in line for line in _argv_lines(argv_log))


def test_worktree_from_inside_a_worktree_places_the_sibling_beside_the_main_repo(tmp_path: Path) -> None:
    repo, docker_bin, _argv_log = _throwaway_repo(tmp_path)
    assert _make_at(repo, docker_bin, ["worktree"], {"STORY": "probe"}).returncode == 0
    probe = tmp_path / "meetingminer-wt" / "probe"
    proc = _make_at(probe, docker_bin, ["worktree"], {"STORY": "sibling"})
    output = proc.stdout + proc.stderr
    assert proc.returncode == 0, output
    sibling = tmp_path / "meetingminer-wt" / "sibling"
    assert sibling.is_dir() and not (probe / "meetingminer-wt").exists()
    assert (sibling / ".env").is_symlink()
    assert Path(os.path.realpath(sibling / ".env")) == (repo / ".env").resolve()
    assert "MM_STACK_NAME=meetingminer-sibling" in (sibling / ".env.worktree").read_text(encoding="utf-8")


def test_the_real_gitignore_ignores_the_worktree_stack_file() -> None:
    """What the throwaway repo relies on must hold in this repository."""
    proc = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "check-ignore", "-q", ".env.worktree"],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_check_env_refuses_a_linked_worktree_without_a_stack_file(tmp_path: Path) -> None:
    repo, docker_bin, _argv_log = _throwaway_repo(tmp_path)
    worktree = _linked_worktree_without_stack(repo, "probe")
    proc = _make_at(worktree, docker_bin, ["check-env"])
    output = proc.stdout + proc.stderr
    assert proc.returncode != 0, output
    assert f"{worktree} is a linked git worktree with no .env.worktree" in output
    assert "make worktree-provision" in output
    # The main checkout (a .git directory) is not a linked worktree.
    assert _make_at(repo, docker_bin, ["check-env"]).returncode == 0


def test_worktree_provision_writes_this_checkouts_file_and_starts_its_stack(tmp_path: Path) -> None:
    repo, docker_bin, argv_log = _throwaway_repo(tmp_path)
    worktree = _linked_worktree_without_stack(repo, "probe")
    proc = _make_at(worktree, docker_bin, ["worktree-provision"])
    output = proc.stdout + proc.stderr
    assert proc.returncode == 0, output
    env_lines = (worktree / ".env.worktree").read_text(encoding="utf-8").splitlines()
    assert "MM_STACK_NAME=meetingminer-probe" in env_lines
    expected_up = _compose_up_line(
        worktree, worktree / "infra" / "docker-compose.yml", worktree / "infra", "meetingminer-probe"
    )
    assert expected_up in _argv_lines(argv_log), _argv_lines(argv_log)
    assert _make_at(worktree, docker_bin, ["check-env"]).returncode == 0

    main_proc = _make_at(repo, docker_bin, ["worktree-provision"])
    assert main_proc.returncode != 0
    assert "is the main checkout" in main_proc.stdout + main_proc.stderr
    assert not (repo / ".env.worktree").exists()


def test_worktree_prune_tears_down_the_pruned_worktrees_stack_only(tmp_path: Path) -> None:
    repo, docker_bin, argv_log = _throwaway_repo(tmp_path, origin=True)
    assert _make_at(repo, docker_bin, ["worktree"], {"STORY": "probe"}).returncode == 0  # HEAD == origin/main
    assert _make_at(repo, docker_bin, ["worktree"], {"STORY": "keep"}).returncode == 0
    keep = tmp_path / "meetingminer-wt" / "keep"
    (keep / "work.txt").write_text("unmerged\n", encoding="utf-8")
    _git(keep, "add", "work.txt")
    _git(keep, "commit", "-q", "-m", "unmerged work")
    _set_stack_inventory(
        docker_bin,
        argv_log,
        [tmp_path / "meetingminer-wt" / "probe", keep],
    )
    argv_log.write_text("", encoding="utf-8")

    proc = _make_at(repo, docker_bin, ["worktree-prune"])
    output = proc.stdout + proc.stderr
    assert proc.returncode == 0, output
    assert not (tmp_path / "meetingminer-wt" / "probe").exists()
    assert keep.is_dir()
    assert "removed stack meetingminer-probe" in output
    lines = _argv_lines(argv_log)
    assert "compose -p meetingminer-probe down -v --remove-orphans" in lines, lines
    assert not any("meetingminer-keep" in line for line in lines)
    assert "keep" in output and "not merged into origin/main" in output


def test_worktree_prune_refuses_a_target_file_that_names_another_stack(
    tmp_path: Path,
) -> None:
    """The batch removal path must not trust a copied ownership record either."""
    repo, docker_bin, argv_log = _throwaway_repo(tmp_path, origin=True)
    assert _make_at(repo, docker_bin, ["worktree"], {"STORY": "probe"}).returncode == 0
    assert _make_at(repo, docker_bin, ["worktree"], {"STORY": "victim"}).returncode == 0
    victim = tmp_path / "meetingminer-wt" / "victim"
    (victim / "work.txt").write_text("unmerged\n", encoding="utf-8")
    _git(victim, "add", "work.txt")
    _git(victim, "commit", "-q", "-m", "keep victim unmerged")
    probe = tmp_path / "meetingminer-wt" / "probe"
    stack_file = probe / ".env.worktree"
    stack_file.write_text(
        stack_file.read_text(encoding="utf-8").replace(
            "MM_STACK_NAME=meetingminer-probe",
            "MM_STACK_NAME=meetingminer-victim",
        ),
        encoding="utf-8",
    )
    argv_log.write_text("", encoding="utf-8")

    proc = _make_at(repo, docker_bin, ["worktree-prune"])
    output = proc.stdout + proc.stderr
    assert proc.returncode != 0, output
    assert probe.is_dir(), output
    assert "MM_STACK_NAME" in output
    assert not any("compose -p meetingminer-victim down -v" in line for line in _argv_lines(argv_log))


def test_worktree_branches_from_base_when_given(tmp_path: Path) -> None:
    repo, docker_bin, _argv_log = _throwaway_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "other")
    (repo / "marker.txt").write_text("other\n", encoding="utf-8")
    _git(repo, "add", "marker.txt")
    _git(repo, "commit", "-q", "-m", "other")
    other_head = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "main")
    assert _git(repo, "rev-parse", "HEAD") != other_head

    proc = _make_at(repo, docker_bin, ["worktree"], {"STORY": "probe2", "BASE": "other"})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    worktree = tmp_path / "meetingminer-wt" / "probe2"
    assert _git(worktree, "rev-parse", "HEAD") == other_head
    assert (worktree / "marker.txt").is_file()


def test_worktree_with_docker_down_keeps_the_checkout_and_names_the_retry(tmp_path: Path) -> None:
    """Row `Provision`, Docker down: non-zero, but the worktree and its
    `.env.worktree` stay and the error says `cd <wt> && make infra-up`."""
    repo, docker_bin, argv_log = _throwaway_repo(tmp_path, docker_info_exit=1)
    proc = _make_at(repo, docker_bin, ["worktree"], {"STORY": "probe"})
    output = proc.stdout + proc.stderr
    assert proc.returncode != 0, output

    worktree = tmp_path / "meetingminer-wt" / "probe"
    assert worktree.is_dir()
    assert (worktree / ".env").is_symlink()
    env_lines = (worktree / ".env.worktree").read_text(encoding="utf-8").splitlines()
    assert "MM_STACK_NAME=meetingminer-probe" in env_lines
    assert sum(bool(re.match(r"^MM_[A-Z0-9_]+_PORT=\d+$", line)) for line in env_lines) == 7
    assert "Docker daemon is not running" in output
    assert f"cd {worktree} && make infra-up" in output
    assert not any(" up " in line for line in _argv_lines(argv_log))


def test_worktree_refuses_a_bad_slug_before_any_git_action(tmp_path: Path) -> None:
    """Row `Bad slug`: exit 1 with the rule; no directory, no branch."""
    repo, docker_bin, argv_log = _throwaway_repo(tmp_path)
    proc = _make_at(repo, docker_bin, ["worktree"], {"STORY": "Foo_Bar!"})
    output = proc.stdout + proc.stderr
    assert proc.returncode != 0, output
    assert "STORY must match [a-z0-9][a-z0-9_-]*" in output
    assert not (tmp_path / "meetingminer-wt").exists()
    assert _git(repo, "branch", "--list", "story/Foo_Bar!") == ""
    assert len(_git(repo, "worktree", "list").splitlines()) == 1
    assert _argv_lines(argv_log) == []


def test_worktree_remove_tears_the_stack_down_after_git_removes_the_checkout(tmp_path: Path) -> None:
    """Row `Remove`, clean: the checkout goes, then `down -v` for its project."""
    repo, docker_bin, argv_log = _throwaway_repo(tmp_path)
    assert _make_at(repo, docker_bin, ["worktree"], {"STORY": "probe"}).returncode == 0
    _set_stack_inventory(
        docker_bin, argv_log, [tmp_path / "meetingminer-wt" / "probe"]
    )
    argv_log.write_text("", encoding="utf-8")

    proc = _make_at(repo, docker_bin, ["worktree-remove"], {"STORY": "probe"})
    output = proc.stdout + proc.stderr
    assert proc.returncode == 0, output
    assert not (tmp_path / "meetingminer-wt" / "probe").exists()
    assert len(_git(repo, "worktree", "list").splitlines()) == 1
    assert _git(repo, "rev-parse", "--verify", "refs/heads/story/probe")  # branch kept
    assert "removed stack meetingminer-probe" in output
    lines = _argv_lines(argv_log)
    assert "compose -p meetingminer-probe down -v --remove-orphans" in lines, lines
    assert lines.index("info") < lines.index("compose -p meetingminer-probe down -v --remove-orphans")


def test_worktree_remove_refuses_a_target_file_that_names_another_stack(
    tmp_path: Path,
) -> None:
    """A copied/tampered ownership record must not route target removal to a
    different live worktree's ``down -v``."""
    repo, docker_bin, argv_log = _throwaway_repo(tmp_path)
    assert _make_at(repo, docker_bin, ["worktree"], {"STORY": "probe"}).returncode == 0
    assert _make_at(repo, docker_bin, ["worktree"], {"STORY": "victim"}).returncode == 0
    probe = tmp_path / "meetingminer-wt" / "probe"
    stack_file = probe / ".env.worktree"
    stack_file.write_text(
        stack_file.read_text(encoding="utf-8").replace(
            "MM_STACK_NAME=meetingminer-probe",
            "MM_STACK_NAME=meetingminer-victim",
        ),
        encoding="utf-8",
    )
    argv_log.write_text("", encoding="utf-8")

    proc = _make_at(repo, docker_bin, ["worktree-remove"], {"STORY": "probe"})
    output = proc.stdout + proc.stderr
    assert proc.returncode != 0, output
    assert probe.is_dir(), output
    assert "MM_STACK_NAME" in output
    assert not any(" down -v " in line for line in _argv_lines(argv_log))


def test_worktree_remove_refuses_path_traversal_before_git_or_docker(
    tmp_path: Path,
) -> None:
    """STORY is a slug, never a path that can escape its worktree child."""
    repo, docker_bin, argv_log = _throwaway_repo(tmp_path)
    assert _make_at(repo, docker_bin, ["worktree"], {"STORY": "victim"}).returncode == 0
    victim = tmp_path / "meetingminer-wt" / "victim"
    _set_stack_inventory(docker_bin, argv_log, [victim])
    argv_log.write_text("", encoding="utf-8")

    proc = _make_at(
        repo,
        docker_bin,
        ["worktree-remove"],
        {"STORY": "../meetingminer-wt/victim"},
    )
    output = proc.stdout + proc.stderr
    assert proc.returncode != 0, output
    assert victim.is_dir(), output
    assert "STORY must match [a-z0-9][a-z0-9_-]*" in output
    assert not any(" down -v " in line for line in _argv_lines(argv_log))


def test_worktree_remove_of_a_dirty_checkout_leaves_the_stack_intact(tmp_path: Path) -> None:
    """Row `Remove`, dirty: git refuses as before and no teardown runs."""
    repo, docker_bin, argv_log = _throwaway_repo(tmp_path)
    assert _make_at(repo, docker_bin, ["worktree"], {"STORY": "probe"}).returncode == 0
    worktree = tmp_path / "meetingminer-wt" / "probe"
    (worktree / "scratch.txt").write_text("uncommitted\n", encoding="utf-8")
    argv_log.write_text("", encoding="utf-8")

    proc = _make_at(repo, docker_bin, ["worktree-remove"], {"STORY": "probe"})
    output = proc.stdout + proc.stderr
    assert proc.returncode != 0, output
    assert worktree.is_dir()
    assert "Stack meetingminer-probe is left intact" in output
    assert not any("down" in line for line in _argv_lines(argv_log))


# --- remediation 2026-08-30: the stack file is a validated ownership record --

from test_worktree_stack import good_stack_text  # noqa: E402


def test_check_env_names_an_invalid_stack_file_in_a_linked_worktree(tmp_path: Path) -> None:
    """A readable-but-wrong .env.worktree must fail check-env by name, not be
    accepted because it exists."""
    repo, docker_bin, _argv_log = _throwaway_repo(tmp_path)
    worktree = _linked_worktree_without_stack(repo, "probe")
    (worktree / ".env.worktree").write_text(
        good_stack_text("other"), encoding="utf-8"
    )
    proc = _make_at(worktree, docker_bin, ["check-env"])
    output = proc.stdout + proc.stderr
    assert proc.returncode != 0, output
    assert "MM_STACK_NAME" in output


def test_check_env_in_the_main_checkout_refuses_a_stack_file(tmp_path: Path) -> None:
    """The main checkout runs the main stack; a .env.worktree there is a
    misplaced ownership record and must be refused by name."""
    repo, docker_bin, _argv_log = _throwaway_repo(tmp_path)
    (repo / ".env.worktree").write_text(good_stack_text("repo"), encoding="utf-8")
    proc = _make_at(repo, docker_bin, ["check-env"])
    output = proc.stdout + proc.stderr
    assert proc.returncode != 0, output
    assert "main checkout" in output
    assert ".env.worktree" in output
    (repo / ".env.worktree").unlink()
    assert _make_at(repo, docker_bin, ["check-env"]).returncode == 0


def test_a_stack_file_assigning_a_makefile_variable_fails_at_parse_time(tmp_path: Path) -> None:
    """`-include .env.worktree` must never let the file assign ROOT, INFRA or
    any other Makefile variable — refused before any target runs."""
    repo, docker_bin, _argv_log = _throwaway_repo(tmp_path)
    worktree = _linked_worktree_without_stack(repo, "probe")
    (worktree / ".env.worktree").write_text(
        good_stack_text("probe") + "ROOT=/elsewhere\n", encoding="utf-8"
    )
    proc = _make_at(worktree, docker_bin, ["help"])
    output = proc.stdout + proc.stderr
    assert proc.returncode != 0, output
    assert "ROOT" in output
    assert "MeetingMiner targets" not in proc.stdout  # nothing ran


def test_a_stack_file_make_directive_is_refused_before_include_executes_it(
    tmp_path: Path,
) -> None:
    """A non-assignment line must not disappear from the key extractor and
    execute as Make syntax before the ownership record is validated."""
    repo, docker_bin, _argv_log = _throwaway_repo(tmp_path)
    worktree = _linked_worktree_without_stack(repo, "probe")
    marker = tmp_path / "included-ran"
    override = tmp_path / "override.mk"
    override.write_text(f"SEEN := $$(shell touch {marker})\n", encoding="utf-8")
    (worktree / ".env.worktree").write_text(
        good_stack_text("probe") + f"include {override}\n", encoding="utf-8"
    )

    proc = _make_at(worktree, docker_bin, ["help"])
    output = proc.stdout + proc.stderr
    assert proc.returncode != 0, output
    assert "invalid line" in output
    assert not marker.exists()
    assert "MeetingMiner targets" not in proc.stdout


# --- remediation 2026-08-30: one start path, safe for old refs and retries --

import shutil  # noqa: E402

from test_worktree_stack import _our_volumes  # noqa: E402


def _python3_decoy(bin_dir: Path, fail_flag: Path) -> None:
    """A python3 on PATH that execs the real interpreter, except that a
    `provision` call fails while `fail_flag` exists."""
    real = shutil.which("python3")
    assert real is not None and not real.startswith(str(bin_dir))
    _write_script(
        bin_dir / "python3",
        f"""#!/bin/bash
if [ -e "{fail_flag}" ]; then
  case "$*" in
    *" provision "*) echo "error: provision refused (decoy failure)" >&2; exit 1 ;;
  esac
fi
exec "{real}" "$@"
""",
    )


def _old_ref_branch(repo: Path) -> None:
    """A branch whose infra/ predates story 11.2: no stack targets, and a
    compose file that names the MAIN project."""
    _git(repo, "checkout", "-q", "-b", "old")
    (repo / "infra" / "Makefile").write_text("all:\n\t@echo old makefile\n", encoding="utf-8")
    (repo / "infra" / "docker-compose.yml").write_text(
        "name: meetingminer\nservices: {}\n", encoding="utf-8"
    )
    _git(repo, "commit", "-q", "-am", "pre-11.2 infra")
    _git(repo, "checkout", "-q", "main")


def test_old_ref_provision_failure_names_a_retry_that_runs_from_this_checkout(
    tmp_path: Path,
) -> None:
    """The printed repair must be executable for a pre-11.2 worktree: the old
    checkout has no worktree-provision target, so the retry is
    `make worktree-start STORY=<slug>` from the invoking checkout — and
    running it drives the invoker's compose file at the worktree's stack,
    never the main project."""
    repo, docker_bin, argv_log = _throwaway_repo(tmp_path)
    _old_ref_branch(repo)
    flag = tmp_path / "fail-provision"
    flag.touch()
    _python3_decoy(docker_bin, flag)
    proc = _make_at(repo, docker_bin, ["worktree"], {"STORY": "probe", "BASE": "old"})
    output = proc.stdout + proc.stderr
    assert proc.returncode != 0, output
    assert "make worktree-start STORY=probe" in output
    assert "worktree-provision" not in output
    worktree = tmp_path / "meetingminer-wt" / "probe"
    assert worktree.is_dir()

    flag.unlink()
    retry = _make_at(repo, docker_bin, ["worktree-start"], {"STORY": "probe"})
    retry_output = retry.stdout + retry.stderr
    assert retry.returncode == 0, retry_output
    lines = _argv_lines(argv_log)
    expected_up = _compose_up_line(
        worktree, repo / "infra" / "docker-compose.yml", worktree / "infra", "meetingminer-probe"
    )
    assert expected_up in lines, lines
    assert not any(" -p meetingminer " in f" {line} " for line in lines), lines


def test_old_ref_compose_failure_never_points_at_the_old_makefile(tmp_path: Path) -> None:
    """`cd <wt> && make infra-up` in a pre-11.2 worktree would start the MAIN
    stack; the failure message must keep the operator on this checkout."""
    repo, docker_bin, _argv_log = _throwaway_repo(tmp_path, up_exit=1)
    _old_ref_branch(repo)
    proc = _make_at(repo, docker_bin, ["worktree"], {"STORY": "probe", "BASE": "old"})
    output = proc.stdout + proc.stderr
    assert proc.returncode != 0, output
    worktree = tmp_path / "meetingminer-wt" / "probe"
    assert f"cd {worktree} && make infra-up" not in output
    assert "make worktree-start STORY=probe" in output
    assert "predates story 11.2" in output


def test_post_112_compose_failure_names_infra_up_and_the_retry_claims_first(
    tmp_path: Path,
) -> None:
    """For a post-11.2 worktree the documented retry is its own
    `make infra-up` — safe only because infra-up claims the project name
    (docker ps inventory) before any `up`."""
    repo, docker_bin, argv_log = _throwaway_repo(tmp_path, up_exit=1)
    proc = _make_at(repo, docker_bin, ["worktree"], {"STORY": "probe"})
    output = proc.stdout + proc.stderr
    assert proc.returncode != 0, output
    worktree = tmp_path / "meetingminer-wt" / "probe"
    assert f"cd {worktree} && make infra-up" in output

    _write_worktree_docker(docker_bin, argv_log)  # compose now succeeds
    argv_log.write_text("", encoding="utf-8")
    retry = _make_at(worktree, docker_bin, ["infra-up"])
    retry_output = retry.stdout + retry.stderr
    assert retry.returncode == 0, retry_output
    lines = _argv_lines(argv_log)
    ps_index = next(i for i, line in enumerate(lines) if line.startswith(PRUNE_PS_PREFIX))
    up_index = next(i for i, line in enumerate(lines) if line.endswith(" up -d --wait"))
    assert ps_index < up_index, lines


def test_docker_down_creation_retry_sweeps_a_stale_incarnation(tmp_path: Path) -> None:
    """Docker down at creation leaves the worktree and its file; the retry
    must tear down a same-named stale project (which cannot carry the new
    file's id) before the first `up` — and keep a stack that does carry it."""
    worktree = tmp_path / "meetingminer-wt" / "probe"
    stale_ps = f"meetingminer-probe\t{worktree / 'infra'}\t\n"
    repo, docker_bin, argv_log = _throwaway_repo(
        tmp_path, docker_info_exit=1, ps_rows=stale_ps
    )
    proc = _make_at(repo, docker_bin, ["worktree"], {"STORY": "probe"})
    output = proc.stdout + proc.stderr
    assert proc.returncode != 0, output
    env_file = worktree / ".env.worktree"
    assert env_file.is_file()

    _write_worktree_docker(
        docker_bin,
        argv_log,
        ps_rows=stale_ps,
        volume_rows=_our_volumes("meetingminer-probe") + "\n",
    )
    argv_log.write_text("", encoding="utf-8")
    retry = _make_at(repo, docker_bin, ["worktree-start"], {"STORY": "probe"})
    retry_output = retry.stdout + retry.stderr
    assert retry.returncode == 0, retry_output
    assert "removed stale stack meetingminer-probe" in retry_output
    lines = _argv_lines(argv_log)
    down = "compose -p meetingminer-probe down -v --remove-orphans"
    assert down in lines, lines
    assert lines.index(down) < next(
        i for i, line in enumerate(lines) if line.endswith(" up -d --wait")
    ), lines

    stack_id = next(
        line.split("=", 1)[1]
        for line in env_file.read_text(encoding="utf-8").splitlines()
        if line.startswith("MM_STACK_ID=")
    )
    own_ps = f"meetingminer-probe\t{worktree / 'infra'}\t{stack_id}\n"
    own_volumes = _our_volumes("meetingminer-probe", stack_id) + "\n"
    _write_worktree_docker(docker_bin, argv_log, ps_rows=own_ps, volume_rows=own_volumes)
    argv_log.write_text("", encoding="utf-8")
    retry2 = _make_at(repo, docker_bin, ["worktree-start"], {"STORY": "probe"})
    retry2_output = retry2.stdout + retry2.stderr
    assert retry2.returncode == 0, retry2_output
    assert "kept stack meetingminer-probe" in retry2_output
    assert not any(" down" in line for line in _argv_lines(argv_log)), _argv_lines(argv_log)


# --- remediation 2026-08-30: cleanup status propagation (finding 6) ---------


def test_worktree_remove_fails_when_stack_inventory_fails(tmp_path: Path) -> None:
    """A failed `docker ps -aq` must be a named error, never mistaken for an
    absent stack."""
    repo, docker_bin, _argv_log = _throwaway_repo(tmp_path)
    assert _make_at(repo, docker_bin, ["worktree"], {"STORY": "probe"}).returncode == 0
    _set_stack_inventory(
        docker_bin,
        _argv_log,
        [tmp_path / "meetingminer-wt" / "probe"],
        ps_exit=3,
    )
    proc = _make_at(repo, docker_bin, ["worktree-remove"], {"STORY": "probe"})
    output = proc.stdout + proc.stderr
    assert proc.returncode != 0, output
    assert "already gone" not in output
    assert "removed stack meetingminer-probe" not in output
    assert "ps -a" in output  # the inventory failure is named


def test_worktree_remove_propagates_a_failed_teardown(tmp_path: Path) -> None:
    repo, docker_bin, _argv_log = _throwaway_repo(tmp_path, down_exit=1)
    assert _make_at(repo, docker_bin, ["worktree"], {"STORY": "probe"}).returncode == 0
    _set_stack_inventory(
        docker_bin,
        _argv_log,
        [tmp_path / "meetingminer-wt" / "probe"],
        down_exit=1,
    )
    proc = _make_at(repo, docker_bin, ["worktree-remove"], {"STORY": "probe"})
    output = proc.stdout + proc.stderr
    assert proc.returncode != 0, output
    assert not (tmp_path / "meetingminer-wt" / "probe").exists()  # checkout went
    assert "removed stack meetingminer-probe" not in output
    assert "down -v --remove-orphans failed" in output  # the teardown failure is named


def test_worktree_prune_propagates_a_failed_teardown_but_still_deletes_the_branch(
    tmp_path: Path,
) -> None:
    """The checkout is already gone when the teardown fails, so the branch
    delete still happens — but its `|| true` must not mask the failure."""
    repo, docker_bin, _argv_log = _throwaway_repo(tmp_path, down_exit=1, origin=True)
    assert _make_at(repo, docker_bin, ["worktree"], {"STORY": "probe"}).returncode == 0
    _set_stack_inventory(
        docker_bin,
        _argv_log,
        [tmp_path / "meetingminer-wt" / "probe"],
        down_exit=1,
    )
    proc = _make_at(repo, docker_bin, ["worktree-prune"])
    output = proc.stdout + proc.stderr
    assert proc.returncode != 0, output
    assert not (tmp_path / "meetingminer-wt" / "probe").exists()
    assert _git(repo, "branch", "--list", "story/probe") == ""
    assert "down -v --remove-orphans failed" in output
