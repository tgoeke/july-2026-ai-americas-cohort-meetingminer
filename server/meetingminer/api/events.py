"""GET /jobs/events — the live half of ingestion progress (FR8, story 1.9).

Three wire event names and no others: ``job.stage``, ``job.done``,
``job.error``. They are deliberately *not* the worker's structured log-event
vocabulary (``stage.started``, ``stage.done``, ``job.paused``, …): that is a
logging contract with a different granularity and a different audience, and it
must never leak onto this stream. Many log events collapse into one
``job.stage`` here, and ``job.done`` fires on evidence completeness rather
than on any single log line. This module's *own* log events are prefixed
``jobevents.`` for the same reason — a log line must never be mistakable for a
wire event.

The stream *reads* job rows on an interval and diffs them (AD-11). It starts
no pipeline work, writes nothing, and needs no cooperation from the worker —
every stage transition is a committed UPDATE and ``job_stage.updated_at`` is
maintained by a database trigger, so the rows are the whole mechanism. The
alternative (LISTEN/NOTIFY from the worker) would add a publisher to the
pipeline and buy latency nobody can perceive on stages that run for minutes.
If load ever makes polling wrong, the internals change here and the wire
contract does not.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import AsyncIterator, Iterable, Literal
from uuid import UUID

import anyio
from fastapi import APIRouter, Request
from fastapi.responses import EventSourceResponse
from fastapi.sse import ServerSentEvent
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from meetingminer import logs
from meetingminer.api.jobs import stage_sort_key
from meetingminer.domain.jobs import evidence_complete

router = APIRouter()

# Registered before `jobs`: `/jobs/{job_id}`
# would otherwise swallow `/jobs/events` and reject `events` as a malformed
# UUID. Declared here rather than inherited from the alphabet — see
# meetingminer/api/registry.py and tests/test_api_registry.py.
ROUTER_ORDER = 10

# The wire contract (FR8). Constants, so a rename is a deliberate edit here
# rather than a typo in a format string.
EVENT_STAGE = "job.stage"
EVENT_DONE = "job.done"
EVENT_ERROR = "job.error"
WIRE_EVENT_NAMES: tuple[str, ...] = (EVENT_STAGE, EVENT_DONE, EVENT_ERROR)

# Comment payloads. Comments are ignored by every SSE client; they exist to
# prove the connection is alive (and, for `connected`, that the baseline
# snapshot has been taken and anything that follows is genuinely new).
CONNECTED_COMMENT = "connected"
HEARTBEAT_COMMENT = "heartbeat"

# A tick's read can fail for reasons that pass: the pool times out under load,
# Postgres restarts, a connection is reset. The headers are long since sent by
# then, so letting the exception escape would truncate the body and explain
# nothing to either side. Instead the tick is skipped and the next one retries.
#
# Persistent failure is different, and this is the policy: after this many
# consecutive failed reads the stream closes cleanly (a normal end of body,
# logged). The client reconnects on its own; if the database is genuinely gone
# the reconnect fails at the HTTP level, where the client's backoff belongs.
# Holding a connection open forever against a dead database would report
# "live" for a stream that can never carry an event again.
MAX_CONSECUTIVE_READ_FAILURES = 5

_SETTLED_STAGE_STATUSES = frozenset({"done", "skipped"})
_TERMINAL_JOB_STATUSES = frozenset({"done", "failed"})

# One statement per tick, so a tick can never see a job paired with stages it
# never had. Every job is read rather than only the live ones: a job paused at
# the unregistered `extract` stage stays `running` forever, so no status filter
# would meaningfully shrink this on the real corpus. Two small tables.
_JOBS_WITH_STAGES = (
    "SELECT j.id, j.status, j.error, s.name, s.status, s.error"
    " FROM job j LEFT JOIN job_stage s ON s.job_id = j.id"
)


class JobEvent(BaseModel):
    """One streamed event.

    ``event`` repeats the SSE event name inside the payload. That is not
    redundancy for its own sake: the generated TypeScript client yields event
    *data* without the name attached, so carrying it makes the payload
    dispatchable on its own and a captured stream self-describing.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    event: Literal["job.stage", "job.done", "job.error"]
    job_id: UUID
    job_status: str
    # Every payload carries the job's current viewability, not just
    # `job.done`. The gate then self-heals: a client that missed an event
    # still converges on the next one it does see.
    viewable: bool
    stage: str | None = None
    status: str | None = None
    error: str | None = None


# eq=False, so the id-based `__hash__` from object is inherited rather than a
# field-based one synthesized from the two dict fields, which would raise the
# moment anything hashed a snapshot. Nothing compares whole snapshots either:
# `diff_snapshots` compares the fields it cares about, one at a time.
@dataclass(frozen=True, eq=False)
class JobSnapshot:
    """What one tick knows about one job. Built complete; never mutated after."""

    status: str
    error: str | None
    stage_status: dict[str, str]
    stage_error: dict[str, str | None]

    @property
    def complete(self) -> bool:
        return evidence_complete(self.stage_status)

    @property
    def settled(self) -> bool:
        """Nothing more will happen to this job that this story can show.

        A terminal job status is the obvious half. Evidence completeness is
        the other: the runner pauses at the unregistered ``extract`` stage
        with the job still ``running``, so waiting for ``done`` would mean
        watching such a job forever.
        """
        return self.status in _TERMINAL_JOB_STATUSES or self.complete

    def failed_stage(self) -> str | None:
        """The earliest failed stage, or None. Earliest is the causal one."""
        for name in sorted(self.stage_status, key=stage_sort_key):
            if self.stage_status[name] == "failed":
                return name
        return None

    def has_failure(self) -> bool:
        return self.status == "failed" or self.failed_stage() is not None

    def current_stage(self) -> str | None:
        """The stage a reader would point at: the first not yet settled."""
        names = sorted(self.stage_status, key=stage_sort_key)
        for name in names:
            if self.stage_status[name] not in _SETTLED_STAGE_STATUSES:
                return name
        return names[-1] if names else None


def read_snapshot(pool: ConnectionPool) -> dict[UUID, JobSnapshot]:
    """Current job + checkpoint state keyed by job id, from one statement."""
    with pool.connection() as conn:
        rows = conn.execute(_JOBS_WITH_STAGES).fetchall()

    # The per-job dicts are filled before any snapshot is constructed, so a
    # JobSnapshot is complete the moment it exists.
    jobs: dict[UUID, tuple[str, str | None]] = {}
    stage_status: dict[UUID, dict[str, str]] = {}
    stage_error: dict[UUID, dict[str, str | None]] = {}
    for job_id, job_state, job_error, stage, status, error in rows:
        jobs[job_id] = (job_state, job_error)
        stage_status.setdefault(job_id, {})
        stage_error.setdefault(job_id, {})
        if stage is not None:
            stage_status[job_id][stage] = status
            stage_error[job_id][stage] = error

    return {
        job_id: JobSnapshot(state, error, stage_status[job_id], stage_error[job_id])
        for job_id, (state, error) in jobs.items()
    }


def _stage_event(job_id: UUID, snapshot: JobSnapshot, stage: str) -> JobEvent:
    return JobEvent(
        event=EVENT_STAGE,
        job_id=job_id,
        job_status=snapshot.status,
        viewable=snapshot.complete,
        stage=stage,
        status=snapshot.stage_status.get(stage),
        error=snapshot.stage_error.get(stage),
    )


def _job_event(job_id: UUID, snapshot: JobSnapshot) -> JobEvent:
    """A job-row move with no stage transition of its own to point at.

    Used when a job first appears and when the job row changes without any
    checkpoint changing (``queued`` -> ``running`` on claim, most often). It
    names wherever the job currently sits, which may be nothing at all for a
    job whose checkpoints have not been written yet.
    """
    stage = snapshot.current_stage()
    if stage is None:
        return JobEvent(
            event=EVENT_STAGE,
            job_id=job_id,
            job_status=snapshot.status,
            viewable=snapshot.complete,
        )
    return _stage_event(job_id, snapshot, stage)


def _error_event(job_id: UUID, snapshot: JobSnapshot) -> JobEvent:
    """A failure, carrying the recorded text verbatim — never swallowed.

    ``stage`` is None for the runner's stage-less failures (an unreadable
    drop, a meeting mint that raised, video-evidence cleanup that failed):
    those set ``job.error`` while every checkpoint stays ``queued``, so the
    job row's own error is the only text there is.
    """
    stage = snapshot.failed_stage()
    stage_error = snapshot.stage_error.get(stage) if stage is not None else None
    return JobEvent(
        event=EVENT_ERROR,
        job_id=job_id,
        job_status=snapshot.status,
        viewable=snapshot.complete,
        stage=stage,
        status="failed" if stage is not None else None,
        error=stage_error or snapshot.error,
    )


def _done_event(job_id: UUID, snapshot: JobSnapshot) -> JobEvent:
    return JobEvent(
        event=EVENT_DONE,
        job_id=job_id,
        job_status=snapshot.status,
        viewable=True,
    )


def diff_snapshots(
    previous: dict[UUID, JobSnapshot], current: dict[UUID, JobSnapshot]
) -> list[JobEvent]:
    """Every event the move from ``previous`` to ``current`` warrants.

    A job seen for the first time yields one ``job.stage`` naming where it
    currently sits: without it a drop submitted while the list is open would
    stay invisible until something else forced a reseed.

    A job that disappears yields nothing. Nothing deletes a job row today, and
    inventing a removal event for a state the pipeline cannot produce would be
    a contract with no writer behind it.
    """
    events: list[JobEvent] = []
    for job_id, snapshot in current.items():
        before = previous.get(job_id)
        if before is None:
            events.append(_job_event(job_id, snapshot))
            if snapshot.has_failure():
                events.append(_error_event(job_id, snapshot))
            if snapshot.complete:
                events.append(_done_event(job_id, snapshot))
            continue

        stage_moves = 0
        for stage in sorted(snapshot.stage_status, key=stage_sort_key):
            if snapshot.stage_status[stage] != before.stage_status.get(
                stage
            ) or snapshot.stage_error.get(stage) != before.stage_error.get(stage):
                events.append(_stage_event(job_id, snapshot, stage))
                stage_moves += 1

        # The job row moves on its own more often than it looks: `queued` ->
        # `running` on claim, and back to `queued` on a requeue, both without
        # any checkpoint changing. Without this the row's status would sit
        # stale until some later stage happened to move.
        if stage_moves == 0 and (
            snapshot.status != before.status or snapshot.error != before.error
        ):
            events.append(_job_event(job_id, snapshot))

        if snapshot.has_failure() and not before.has_failure():
            events.append(_error_event(job_id, snapshot))

        # Once, on the transition: the evidence bundle becoming complete is
        # the moment the meeting turns openable.
        if snapshot.complete and not before.complete:
            events.append(_done_event(job_id, snapshot))
    return events


def sse_event(event: JobEvent) -> ServerSentEvent:
    """Wrap one event for the wire.

    ``raw_data`` rather than ``data``: FastAPI serializes a ``data`` model with
    a plain ``model_dump_json()``, which would emit snake_case field names.
    Every other response in this api is camelCase at the boundary, and the
    generated client is typed from the camelCase schema, so the payload is
    serialized here with the aliases applied.
    """
    return ServerSentEvent(
        event=event.event, raw_data=event.model_dump_json(by_alias=True)
    )


def _any_live(snapshots: Iterable[JobSnapshot]) -> bool:
    return any(not snapshot.settled for snapshot in snapshots)


async def job_event_stream(
    pool: ConnectionPool, poll_seconds: float, heartbeat_seconds: float
) -> AsyncIterator[ServerSentEvent]:
    """Diff job rows on an interval and yield the events the changes warrant.

    Client disconnect is not polled for here: the response cancels this
    generator when the connection drops, and reading the disconnect message
    directly would compete with the very listener that does the cancelling.
    """
    # The opening read is a silent baseline, never replayed as events: the
    # client seeds the same state from GET /meetings, and replaying finished
    # ingests as "progress" would misreport what just happened.
    previous = await anyio.to_thread.run_sync(read_snapshot, pool)
    watched_live = _any_live(previous.values())
    logs.log_event("jobevents.opened", jobs=len(previous), watching=watched_live)
    yield ServerSentEvent(comment=CONNECTED_COMMENT)
    last_output = time.monotonic()
    last_read = last_output
    read_failures = 0

    while True:
        # Reading the database and proving a quiet connection is alive are
        # independent clocks. A valid config may make heartbeats more frequent
        # than reads, so sleeping for the whole poll interval would violate the
        # configured maximum silent period.
        now = time.monotonic()
        until_read = max(0.0, poll_seconds - (now - last_read))
        until_heartbeat = max(0.0, heartbeat_seconds - (now - last_output))
        await anyio.sleep(min(until_read, until_heartbeat))

        current: dict[UUID, JobSnapshot] | None = None
        if time.monotonic() - last_read >= poll_seconds:
            # Record the clock before the blocking read. A slow database may
            # delay output, but it must not trigger an unbounded catch-up loop.
            last_read = time.monotonic()
            try:
                current = await anyio.to_thread.run_sync(read_snapshot, pool)
            except Exception as exc:  # noqa: BLE001 - a tick must survive a bad read
                read_failures += 1
                logs.log_error_event(
                    "jobevents.read_failed",
                    error=f"{type(exc).__name__}: {exc}",
                    consecutive=read_failures,
                )
                if read_failures >= MAX_CONSECUTIVE_READ_FAILURES:
                    logs.log_error_event(
                        "jobevents.closed",
                        reason="job rows unreadable",
                        consecutive=read_failures,
                    )
                    return

        if current is not None:
            read_failures = 0
            for event in diff_snapshots(previous, current):
                yield sse_event(event)
                last_output = time.monotonic()
            previous = current

            if _any_live(current.values()):
                watched_live = True
            elif watched_live:
                # Everything this connection was watching has settled: end the
                # stream cleanly. A client that wants more reconnects and
                # re-seeds. A stream that never saw a live job (idle system,
                # empty corpus) stays open instead — closing it would put the
                # browser into a reconnect loop with nothing to report.
                logs.log_event("jobevents.closed", reason="no live job")
                return

        if time.monotonic() - last_output >= heartbeat_seconds:
            yield ServerSentEvent(comment=HEARTBEAT_COMMENT)
            last_output = time.monotonic()


@router.get(
    "/jobs/events",
    operation_id="streamJobEvents",
    response_class=EventSourceResponse,
    response_model=JobEvent,
)
async def stream_job_events(request: Request) -> AsyncIterator[ServerSentEvent]:
    settings = request.app.state.config.settings.api
    async for event in job_event_stream(
        request.app.state.pool,
        settings.job_events_poll_seconds,
        settings.job_events_heartbeat_seconds,
    ):
        yield event
