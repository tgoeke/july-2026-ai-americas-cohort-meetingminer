"""The cross-process file lock over the shared Neo4j + Meilisearch stack.

Before this module existed there were *two* disjoint exclusion mechanisms over
the same two containers: the Postgres advisory lock (``stores.projection_lock``)
and the test suite's cross-worktree file lock in ``server/tests/conftest.py``.
A ``rebuild`` on one Postgres database and a projection test wiping the stores
from another worktree therefore raced freely — torn Neo4j writes, mid-run
index deletion. This module is the single implementation both sides now use:
every server entrypoint that writes Neo4j or Meilisearch takes
:func:`store_file_lock` *first*, then the advisory lock, and the test
fixture's ``_projection_store_lock`` delegates here.

The path derivation (sha256 of ``neo4j.uri|meilisearch.url`` in the system
temp dir), the holder JSON sidecar, and the
``MM_PROJECTION_LOCK_TIMEOUT_SECONDS`` env knob are exactly the conftest
scheme. That is deliberate: old and new code derive the same lock path, so
they contend on the same file rather than each excluding only itself. The
lock lives in the system temp dir, NOT the repo, and is keyed by the store
URLs: every writer of the same endpoints — whichever checkout it runs from —
contends on one file, and a separate stack (a worktree's private compose
project on its own ports, story 11.2) gets a separate lock without anyone
choosing one. ``MM_PROJECTION_LOCK_KEY`` replaces the derived key with a
named one; it is process-wide, so a shell that exports it re-keys ``rebuild``
and the worker too. It exists for a test that must own a lock nobody else
can hold (``test_parallel_store_safety``), and for nothing else.

The lock is **reentrant within one process**. A store-backed test already
holds it through the ``projection_stores`` fixture for the length of the test,
and the entrypoint under test must not deadlock against its own fixture.
Cross-process exclusion is this lock's job; within one process the Postgres
advisory lock is what serializes writers, as before. The reentry is
process-wide, not per-thread: a second thread joins the existing holding
(depth + 1) rather than contending, and the flock and holder file are
released by whichever exit brings the depth to zero, regardless of the order
the holdings are exited in.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import re
import socket
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Iterator

from meetingminer.config import AppConfig, ConfigError
from meetingminer.projections.stores import ProjectionLockedError

TIMEOUT_ENV = "MM_PROJECTION_LOCK_TIMEOUT_SECONDS"
#: Names the lock file instead of deriving it from the store URLs. A file
#: name fragment, so it is held to a safe character set and a length.
KEY_ENV = "MM_PROJECTION_LOCK_KEY"
_KEY_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def _lock_key(config: AppConfig) -> str:
    override = os.environ.get(KEY_ENV)
    if override is None:
        stores = config.settings.stores
        return hashlib.sha256(
            f"{stores.neo4j.uri}|{stores.meilisearch.url}".encode()
        ).hexdigest()[:16]
    if not _KEY_RE.fullmatch(override):
        raise ConfigError(
            f"{KEY_ENV} must match [A-Za-z0-9._-]{{1,64}}, got {override!r}"
        )
    return override


def store_lock_paths(config: AppConfig) -> tuple[Path, Path]:
    """Return the shared store lock path and its holder metadata path.

    Keyed by the configured store URLs, or by ``MM_PROJECTION_LOCK_KEY``
    when set; unset, the derivation is byte-identical to the historic
    conftest scheme.
    """
    key = _lock_key(config)
    lock_path = Path(tempfile.gettempdir()) / f"meetingminer-projections-{key}.lock"
    return lock_path, lock_path.with_suffix(".holder.json")


def lock_timeout_seconds() -> float:
    """How long to wait for the file lock before a named refusal."""
    raw = os.environ.get(TIMEOUT_ENV, "300")
    try:
        timeout = float(raw)
    except ValueError:
        raise RuntimeError(
            f"{TIMEOUT_ENV} must be a positive finite number"
        ) from None
    if not math.isfinite(timeout) or timeout <= 0:
        raise RuntimeError(f"{TIMEOUT_ENV} must be a positive finite number")
    return timeout


def _write_holder(path: Path, holder: str) -> None:
    """Publish diagnostics after acquiring the lock, atomically."""
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {
                "holder": holder,
                "pid": os.getpid(),
                "host": socket.gethostname(),
                "acquiredAt": time.time(),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    temporary.replace(path)


def _read_holder(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip() or "unavailable"
    except OSError:
        return "unavailable"


@dataclass
class _Held:
    """One process-wide holding of a lock path: the open handle and a depth."""

    handle: IO[str]
    depth: int = 1


# Reentrancy bookkeeping. `fcntl.flock` treats two descriptors of the same
# file in one process as *contenders*, so without this a fixture-held lock
# would deadlock the entrypoint it is testing. Every transition — reentry
# check, flock acquisition, registration, and release accounting — happens
# under this mutex, so two threads never race one open descriptor against
# another and the last exit is the one that releases.
_state = threading.Lock()
_held: dict[Path, _Held] = {}


def _try_acquire(lock_path: Path, holder_path: Path, holder: str) -> _Held | None:
    """One non-blocking acquisition attempt. Must be called under ``_state``.

    Returns the registered holding on success, ``None`` when another process
    holds the flock. Any failure after the flock succeeds releases it before
    re-raising — a held flock on an unregistered handle would never be
    released by anyone.
    """
    try:
        handle = open(lock_path, "a+")
    except OSError as exc:
        raise ProjectionLockedError(
            f"{holder} refused: the store lock file {lock_path} cannot be"
            f" opened ({type(exc).__name__}: {exc})"
        ) from exc
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    except BaseException:
        handle.close()
        raise
    try:
        _write_holder(holder_path, holder)
        entry = _Held(handle=handle)
        _held[lock_path] = entry
        return entry
    except BaseException:
        try:
            fcntl.flock(handle, fcntl.LOCK_UN)
        finally:
            handle.close()
        raise


def _release(lock_path: Path, holder_path: Path, entry: _Held) -> None:
    """Undo one holding; free the flock when it was the last one."""
    with _state:
        entry.depth -= 1
        last_out = entry.depth == 0
        if last_out:
            del _held[lock_path]
    if last_out:
        try:
            holder_path.unlink(missing_ok=True)
        finally:
            try:
                fcntl.flock(entry.handle, fcntl.LOCK_UN)
            finally:
                entry.handle.close()


@contextmanager
def store_file_lock(config: AppConfig, *, holder: str) -> Iterator[None]:
    """Hold the cross-process store file lock, or refuse by name.

    Blocks up to ``MM_PROJECTION_LOCK_TIMEOUT_SECONDS`` (default 300) for
    another *process* to release it, then raises :class:`ProjectionLockedError`
    naming the lock file and whatever the holder published about itself.
    Reentrant within one process (see the module docstring for why).
    """
    lock_path, holder_path = store_lock_paths(config)
    timeout = lock_timeout_seconds()
    started = time.monotonic()

    entry: _Held | None = None
    while entry is None:
        with _state:
            existing = _held.get(lock_path)
            if existing is not None:
                existing.depth += 1
                entry = existing
            else:
                entry = _try_acquire(lock_path, holder_path, holder)
        if entry is None:
            elapsed = time.monotonic() - started
            if elapsed >= timeout:
                current = _read_holder(holder_path)
                raise ProjectionLockedError(
                    f"{holder} refused: projection store lock timed out"
                    f" after {elapsed:.2f}s waiting for {lock_path};"
                    f" holder metadata: {current}"
                )
            time.sleep(min(0.05, timeout - elapsed))
    try:
        yield
    finally:
        _release(lock_path, holder_path, entry)
