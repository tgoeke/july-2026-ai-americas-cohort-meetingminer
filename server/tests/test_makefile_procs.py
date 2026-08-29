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
    """VENV/WEB pointed at the scratch tree the decoys live in."""
    return {
        "VENV": str(tmp_path / "venv"),
        "WEB": str(tmp_path / "web"),
        "WORKER_OWNER": TEST_WORKER_OWNER,
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
    `variables` on the command line, in that order.
    """
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
            ["start-api"],
            {"LOGS": str(logs), "API_PORT": str(port), **_tree_vars(tmp_path)},
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
            {
                "LOGS": str(logs),
                "API_PORT": str(_free_port()),
                "READY_TRIES": "3",
                "READY_DELAY": "0.1",
                **_tree_vars(tmp_path),
            },
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
            ["start-api"],
            {"LOGS": str(logs), "API_PORT": str(_free_port()), **_tree_vars(tmp_path)},
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
            {
                "LOGS": str(logs),
                "READY_TRIES": "3",
                "READY_DELAY": "0.1",
                **_tree_vars(tmp_path),
            },
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
        proc = _make(
            ["start-worker"],
            {"LOGS": str(logs), **_tree_vars(tmp_path)},
        )
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
            "LOGS": str(logs),
            "VENV": str(venv),
            "API_PORT": str(_free_port()),
            "READY_TRIES": "5",
            "READY_DELAY": "0.1",
        },
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
                "LOGS": str(logs),
                "VENV": str(venv),
                "API_PORT": str(_free_port()),
                "READY_TRIES": "3",
                "READY_DELAY": "0.1",
            },
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
            {"LOGS": str(logs), "ENVFILE": str(envfile), **_tree_vars(tmp_path)},
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
        {"LOGS": str(logs), "ENVFILE": str(envfile), **_tree_vars(tmp_path)},
        env=_path_env(docker_bin),
    )
    output = proc.stdout + proc.stderr
    assert proc.returncode == 0, output
    assert "falling back to project-name teardown" in output

    invocations = argv_log.read_text(encoding="utf-8").splitlines()
    assert any(line.startswith("compose --env-file") for line in invocations)
    # The fallback actually ran, without --env-file interpolation.
    assert "compose -p meetingminer down" in invocations


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
            ["start-api"],
            {
                "LOGS": str(logs),
                "API_PORT": str(port),
                **_tree_vars(tmp_path),
            },
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
        {
            "LOGS": str(logs),
            "API_PORT": str(_free_port()),
            "CLAIM_TRIES": "2",
            "CLAIM_DELAY": "0.01",
            **_tree_vars(tmp_path),
        },
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
        "LOGS": str(logs),
        "VENV": str(venv),
        "API_PORT": str(_free_port()),
    }

    results: list[subprocess.CompletedProcess[str]] = []
    barrier = threading.Barrier(2)

    def run() -> None:
        barrier.wait()
        results.append(_make(["start-api"], variables))

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
            "LOGS": str(logs),
            "VENV": str(venv),
            "WEB": str(web),
            "ENVFILE": str(envfile),
            "API_PORT": str(_free_port()),
            "WEB_PORT": str(_free_port()),
        },
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
                "LOGS": str(logs),
                "VENV": str(venv),
                "WEB": str(web),
                "ENVFILE": str(envfile),
                "API_PORT": str(_free_port()),
                "WEB_PORT": str(_free_port()),
                "READY_TRIES": "10",
                "READY_DELAY": "0.1",
            },
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
