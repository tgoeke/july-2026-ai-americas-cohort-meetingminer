"""MeetingMiner worker process (AD-11).

Startup is a sequence of gates, each fatal in the same way — named error on
stderr, non-zero exit, no traceback:

1. config.yaml loads and validates;
2. ``MM_CONTENT_ROOT`` is set, absolute, creatable, and writable (the
   `frames` stage writes media there);
3. ``MM_DROPS_ROOT`` is set, absolute, and present (every stored drop path is
   relative to it, and nothing is ever written inside it);
4. database migrations are current.

The `Ocr` binding is probed at startup too, but is *not* a gate: a host with
no usable engine can still process transcript-only drops, which skip `ocr`.
An unusable binding is a named warning, and the engine actually resolved is
reported on ``worker.startup``.

Then jobs left `running` by a crash are re-queued once, the ``worker.startup``
event is emitted (the Makefile's readiness poll greps for it on stdout), and
the process polls the runner: claim a queued job, advance its stages,
checkpoint each one. The api never executes a stage.
"""

from __future__ import annotations

import signal
import sys
import time
from types import FrameType

import psycopg

from meetingminer import db, logs
from meetingminer.adapters.ocr import OcrError, build_ocr
from meetingminer.config import (
    AppConfig,
    ConfigError,
    load_config,
    require_content_root,
    require_drops_root,
)
from meetingminer.pipeline import runner

_POLL_SECONDS = 1.0
_stop = False


def acquire_worker_lock(conn: psycopg.Connection) -> bool:
    """Attempt the process-lifetime Postgres singleton lock."""
    return bool(
        conn.execute(
            "SELECT pg_try_advisory_lock(hashtext('meetingminer-worker'))"
        ).fetchone()[0]
    )


def _handle_stop(signum: int, _frame: FrameType | None) -> None:
    global _stop
    _stop = True


def _fatal(error: str) -> int:
    logs.log_error_event("worker.fatal", error=error)
    return 1


def resolve_ocr_engine(config: AppConfig) -> str | None:
    """Name the OCR engine this host will actually use, or ``None``.

    Deliberately *not* a startup gate. A host with no usable engine still has
    transcript-only drops to process, and those skip `ocr` entirely — killing
    the worker would stop legitimate work. But finding out mid-pipeline, after
    `probe` and `frames` have already spent minutes on a recording, is worse
    than finding out now, so an unusable binding is a named warning at
    startup.
    """
    try:
        return build_ocr(config.settings.ocr).name
    except OcrError as exc:
        logs.log_error_event(
            "worker.ocr_unavailable",
            engine=config.settings.ocr.engine,
            fallback=config.settings.ocr.fallback,
            error=str(exc),
        )
        return None


def main() -> int:
    try:
        config = load_config()
    except ConfigError as exc:
        return _fatal(str(exc))

    # The content root gate lives here rather than in load_config(): the api
    # and the migrate CLI do not write media, so an unset root must not stop
    # them booting. The worker does, so for it this is fatal.
    try:
        content_root = require_content_root(config)
    except ConfigError as exc:
        return _fatal(str(exc))

    # The other anchor (story 2.1a): every stored drop path is relative to it,
    # so a worker without it can resolve no drop at all. Same gate shape, same
    # fatal-at-startup contract; the runner re-reads it per claim.
    try:
        drops_root = require_drops_root(config)
    except ConfigError as exc:
        return _fatal(str(exc))

    # Install signal handlers before the DB gate so a signal during the
    # (up to 10s) connect still gets a structured shutdown.
    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    # Fail fast on pending migrations (same contract as config: named error,
    # no traceback). An unreachable or broken database is equally fatal — the
    # worker cannot verify the schema without it.
    lock_conn: psycopg.Connection | None = None
    try:
        with psycopg.connect(db.conninfo(config), connect_timeout=10) as conn:
            db.check_migrations_current(conn)
        # Hold a database advisory lock for this process lifetime. The
        # pidfile is helpful for local operations, but this prevents a second
        # worker from requeueing work an active worker is executing.
        lock_conn = psycopg.connect(db.conninfo(config), connect_timeout=10)
        locked = acquire_worker_lock(lock_conn)
        if not locked:
            lock_conn.close()
            return _fatal("worker already running (Postgres advisory lock is held)")
        # Orphan recovery happens only after exclusive ownership is established.
        requeued = runner.requeue_orphaned_jobs(lock_conn)
    except (db.MigrationsPendingError, db.MigrationError) as exc:
        return _fatal(str(exc))
    except psycopg.OperationalError as exc:
        if lock_conn is not None:
            lock_conn.close()
        return _fatal(f"database unreachable: {exc}")
    except psycopg.Error as exc:
        if lock_conn is not None:
            lock_conn.close()
        return _fatal(f"database error: {exc}")

    for job_id in requeued:
        logs.log_event("worker.job_requeued", job_id=job_id)

    ocr_engine = resolve_ocr_engine(config)

    logs.log_event(
        "worker.startup",
        service=f"{config.settings.service}-worker",
        configVersion=config.settings.config_version,
        # What is configured, and what this host resolved it to — they differ
        # when the fallback engaged, and `null` means the video stages will
        # fail on the first recording drop.
        ocrEngine=config.settings.ocr.engine,
        ocrEngineResolved=ocr_engine,
        sttEngine=config.settings.stt.engine,
        diarizerEngine=config.settings.diarizer.engine,
        embedderModel=config.settings.embedder.model,
        embedderDimension=config.settings.embedder.dimension,
        contentRoot=str(content_root),
        dropsRoot=str(drops_root),
        requeuedJobs=len(requeued),
    )

    pool = db.create_pool(config)
    try:
        pool.open(wait=True, timeout=10.0)
    except psycopg.Error as exc:
        pool.close()
        if lock_conn is not None:
            lock_conn.close()
        return _fatal(f"database pool could not be opened: {exc}")

    try:
        while not _stop:
            if lock_conn is None or lock_conn.closed:
                return _fatal("worker advisory-lock connection was lost; stopping before more work")
            try:
                claimed = runner.run_once(pool, config, content_root)
            except psycopg.Error as exc:
                # Transient database trouble: report it and keep polling. The
                # job stays `running` and startup orphan recovery re-queues it.
                logs.log_error_event("worker.error", error=f"database error: {exc}")
                claimed = False
            # An empty queue idles quietly — no log line per poll. A claimed
            # job means there may be another, so poll again immediately.
            if not claimed:
                time.sleep(_POLL_SECONDS)
    finally:
        pool.close()
        if lock_conn is not None:
            lock_conn.close()

    logs.log_event("worker.shutdown", service=f"{config.settings.service}-worker")
    return 0


if __name__ == "__main__":
    # argv is deliberately not parsed. `make up` appends a
    # `--mm-owner=<checkout>` marker so ps can tell this checkout's worker
    # from another clone's; it carries no meaning for the process itself.
    # Any future CLI parsing here must keep ignoring unknown --mm-owner.
    raise SystemExit(main())
