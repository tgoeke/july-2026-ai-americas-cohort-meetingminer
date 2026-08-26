"""Structured JSON logging for the worker and the pipeline (NFR17/NFR18).

One line of JSON per event on stdout, so `.logs/worker.log` stays greppable by
the Makefile readiness poll and by anything that parses it later. Every
pipeline line carries ``job_id`` and ``stage``; :func:`bind` produces a logger
that attaches them so no call site can forget.

Deliberately named ``logs`` rather than ``logging``: a module named
``logging`` inside the package would shadow the stdlib module for anything
that does a relative-looking import, and the confusion is not worth it.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import IO, Any
from uuid import UUID


def _emit(stream: IO[str], event: str, fields: dict[str, Any]) -> None:
    record: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
    }
    for key, value in fields.items():
        record[key] = str(value) if isinstance(value, UUID) else value
    # default=str so an unexpected non-JSON value degrades to its repr rather
    # than losing the whole log line to a TypeError.
    print(json.dumps(record, default=str), file=stream, flush=True)


def log_event(event: str, **fields: Any) -> None:
    """Emit one structured JSON event on stdout."""
    _emit(sys.stdout, event, fields)


def log_error_event(event: str, **fields: Any) -> None:
    """Emit one structured JSON event on stderr (fatals, unexpected errors)."""
    _emit(sys.stderr, event, fields)


@dataclass(frozen=True)
class BoundLogger:
    """A logger that stamps every line with its ``job_id`` and ``stage``."""

    job_id: UUID | str | None = None
    stage: str | None = None

    def bind(self, **fields: Any) -> "BoundLogger":
        return BoundLogger(
            job_id=fields.get("job_id", self.job_id),
            stage=fields.get("stage", self.stage),
        )

    def _context(self) -> dict[str, Any]:
        context: dict[str, Any] = {}
        if self.job_id is not None:
            context["job_id"] = self.job_id
        if self.stage is not None:
            context["stage"] = self.stage
        return context

    def __call__(self, event: str, **fields: Any) -> None:
        _emit(sys.stdout, event, {**self._context(), **fields})

    def error(self, event: str, **fields: Any) -> None:
        _emit(sys.stderr, event, {**self._context(), **fields})


def bind(job_id: UUID | str | None = None, stage: str | None = None) -> BoundLogger:
    """A logger bound to a job (and optionally a stage)."""
    return BoundLogger(job_id=job_id, stage=stage)
