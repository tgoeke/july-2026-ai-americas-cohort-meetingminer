"""GET /jobs/events contract tests (run against meetingminer_test; skip without Postgres).

The event-name contract (FR8) and the viewability gate are the two things a
future refactor is most likely to break silently, so both are pinned here on
the wire — the actual `event:`/`data:` bytes — rather than through the
endpoint's internals.

Two mechanics worth knowing before reading the tests:

* These tests speak ASGI directly instead of using ``TestClient``. Starlette's
  test client buffers a whole response before it returns one, which an endless
  stream never gives it; here the app runs in a portal thread and every body
  chunk lands on a queue the test thread reads as it arrives.
* Synchronisation needs no sleeps: the stream emits a ``: connected`` comment
  the moment its baseline snapshot has been taken, so a test that has seen
  that comment knows any row it writes afterwards is a genuine change the next
  tick must report.
"""

from __future__ import annotations

import json
import queue
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator

import anyio
import pytest
from anyio.from_thread import start_blocking_portal

import meetingminer.api.events as events_module
from meetingminer.api.events import (
    MAX_CONSECUTIVE_READ_FAILURES,
    EVENT_DONE,
    EVENT_ERROR,
    EVENT_STAGE,
    WIRE_EVENT_NAMES,
)
from meetingminer.domain.jobs import EVIDENCE_STAGES, VIDEO_ONLY_STAGES

# The worker's structured log-event vocabulary. None of it is a wire contract,
# and none of it may appear on this stream.
WORKER_LOG_EVENTS = (
    "stage.started", "stage.done", "stage.skipped", "stage.resumed",
    "stage.failed", "job.paused", "job.failed", "job.claimed",
)

# Fast enough that no test waits on a real interval, slow enough that a tick
# still costs a real round trip to Postgres.
POLL_SECONDS = 0.02
HEARTBEAT_SECONDS = 0.15
# Generous: this only ever bounds a hang, never a passing test.
READ_TIMEOUT = 20.0


def _submit(client, make_drop, source_id: str = "source-1") -> str:
    from conftest import valid_metadata

    drop = make_drop(valid_metadata(source_id))
    response = client.post("/ingests", json={"dropPath": str(drop)})
    assert response.status_code == 201, response.text
    return response.json()["jobId"]


def _set_stages(pool, job_id: str, status: str, names: tuple[str, ...]) -> None:
    with pool.connection() as conn:
        conn.execute(
            "UPDATE job_stage SET status = %s WHERE job_id = %s AND name = ANY(%s)",
            (status, job_id, list(names)),
        )


def _fail_stage(pool, job_id: str, name: str, error: str) -> None:
    """Exactly what the runner's `_fail_job` commits: stage row plus job row."""
    with pool.connection() as conn:
        conn.execute(
            "UPDATE job_stage SET status = 'failed', error = %s"
            " WHERE job_id = %s AND name = %s",
            (error, job_id, name),
        )
        conn.execute(
            "UPDATE job SET status = 'failed', error = %s WHERE id = %s",
            (f"stage {name} failed: {error}", job_id),
        )


class _Wire:
    """One in-flight GET, read chunk by chunk as the app sends it."""

    def __init__(self, app: Any, path: str) -> None:
        self._app = app
        self._path = path
        self._start: queue.Queue[dict[str, Any]] = queue.Queue()
        self._chunks: queue.Queue[bytes | None] = queue.Queue()
        self._request_sent = False
        self._disconnected = threading.Event()
        self._buffer = ""
        self.raw: list[str] = []

    # --- ASGI side (runs in the portal thread) ---------------------------
    async def _receive(self) -> dict[str, Any]:
        if not self._request_sent:
            self._request_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        # Returned without awaiting once disconnect is requested: the response's
        # own disconnect listener polls this with a near-zero timeout.
        while not self._disconnected.is_set():
            await anyio.sleep(0.01)
        return {"type": "http.disconnect"}

    async def _send(self, message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            self._start.put(message)
        elif message["type"] == "http.response.body":
            body = message.get("body", b"")
            if body:
                self._chunks.put(body)
            if not message.get("more_body", False):
                self._chunks.put(None)

    async def run(self) -> None:
        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": self._path,
            "raw_path": self._path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [(b"host", b"testserver"), (b"accept", b"text/event-stream")],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "state": {},
        }
        try:
            await self._app(scope, self._receive, self._send)
        finally:
            self._chunks.put(None)

    # --- test side -------------------------------------------------------
    def disconnect(self) -> None:
        self._disconnected.set()

    def status_and_headers(self) -> tuple[int, dict[str, str]]:
        message = self._start.get(timeout=READ_TIMEOUT)
        headers = {
            key.decode().lower(): value.decode() for key, value in message["headers"]
        }
        return message["status"], headers

    def next_line(self) -> str | None:
        """The next line of the body, or None once the server closes the stream."""
        while "\n" not in self._buffer:
            chunk = self._chunks.get(timeout=READ_TIMEOUT)
            if chunk is None:
                return None
            self._buffer += chunk.decode("utf-8")
        line, _, self._buffer = self._buffer.partition("\n")
        self.raw.append(line)
        return line


class _Frames:
    """SSE frames off a wire, in order."""

    def __init__(self, wire: _Wire) -> None:
        self._wire = wire

    @property
    def raw(self) -> list[str]:
        return self._wire.raw

    def _next_frame(self) -> tuple[str, Any] | None:
        """('comment', text) or ('event', (name, payload)); None at end of stream."""
        name: str | None = None
        while True:
            line = self._wire.next_line()
            if line is None:
                return None
            if line.startswith(":"):
                return ("comment", line[1:].strip())
            if line.startswith("event:"):
                name = line[len("event:") :].strip()
            elif line.startswith("data:"):
                return ("event", (name, json.loads(line[len("data:") :])))

    def comments(self, count: int) -> list[str]:
        """Read ``count`` comments, failing if an event turns up instead."""
        seen: list[str] = []
        while len(seen) < count:
            frame = self._next_frame()
            assert frame is not None, "stream ended while waiting for a comment"
            assert frame[0] == "comment", f"unexpected event on an idle stream: {frame}"
            seen.append(frame[1])
        return seen

    def events(self, count: int) -> list[tuple[str, dict[str, Any]]]:
        """Read ``count`` events, ignoring any comments interleaved with them."""
        seen: list[tuple[str, dict[str, Any]]] = []
        while len(seen) < count:
            frame = self._next_frame()
            assert frame is not None, (
                f"stream ended after {len(seen)} of {count} events: {self.raw}"
            )
            if frame[0] == "event":
                seen.append(frame[1])
        return seen

    def drain(self) -> list[tuple[str, dict[str, Any]]]:
        """Every remaining event, returning when the server closes the stream."""
        seen: list[tuple[str, dict[str, Any]]] = []
        while True:
            frame = self._next_frame()
            if frame is None:
                return seen
            if frame[0] == "event":
                seen.append(frame[1])


@contextmanager
def open_stream(
    client, poll: float = POLL_SECONDS, heartbeat: float = HEARTBEAT_SECONDS
) -> Iterator[_Frames]:
    """Open /jobs/events at test-speed intervals, past its baseline snapshot.

    ``client`` is taken (and unused for the request itself) so the stream runs
    against the same app instance the fixture pointed at the test database.
    """
    import meetingminer.api.main as api_main

    assert client is not None
    original = api_main.app.state.config
    patched = original.model_copy(deep=True)
    patched.settings.api.job_events_poll_seconds = poll
    patched.settings.api.job_events_heartbeat_seconds = heartbeat
    api_main.app.state.config = patched
    wire = _Wire(api_main.app, "/jobs/events")
    try:
        with start_blocking_portal() as portal:
            portal.start_task_soon(wire.run)
            try:
                status, headers = wire.status_and_headers()
                assert status == 200
                assert headers["content-type"].startswith("text/event-stream")
                frames = _Frames(wire)
                assert frames.comments(1) == ["connected"], "baseline not taken"
                yield frames
            finally:
                wire.disconnect()
    finally:
        api_main.app.state.config = original


def test_stage_transition_emits_job_stage_carrying_the_job_id(
    client, test_pool, make_drop
) -> None:
    job_id = _submit(client, make_drop)

    with open_stream(client) as frames:
        _set_stages(test_pool, job_id, "running", ("probe",))
        ((name, payload),) = frames.events(1)
        assert name == EVENT_STAGE
        assert payload["jobId"] == job_id
        assert payload["stage"] == "probe"
        assert payload["status"] == "running"
        assert payload["viewable"] is False

        _set_stages(test_pool, job_id, "done", ("probe",))
        ((name, payload),) = frames.events(1)
        assert name == EVENT_STAGE
        assert payload["stage"] == "probe"
        assert payload["status"] == "done"


def test_baseline_state_is_never_replayed_as_progress(
    client, test_pool, make_drop
) -> None:
    """A stream that opens onto existing rows reports only what happens next."""
    job_id = _submit(client, make_drop)
    _set_stages(test_pool, job_id, "done", ("probe", "frames"))

    with open_stream(client) as frames:
        # Nothing has changed since the baseline: heartbeats only.
        assert frames.comments(2) == ["heartbeat", "heartbeat"]
        _set_stages(test_pool, job_id, "done", ("ocr",))
        ((name, payload),) = frames.events(1)
        assert (name, payload["stage"]) == (EVENT_STAGE, "ocr")


def test_evidence_completion_emits_job_done_exactly_once(
    client, test_pool, make_drop
) -> None:
    job_id = _submit(client, make_drop, source_id="source-a")
    # A second, permanently queued job keeps the stream open past the moment
    # the job under test settles, so a duplicate `job.done` would be visible.
    _submit(client, make_drop, source_id="source-b")

    with open_stream(client) as frames:
        _set_stages(test_pool, job_id, "done", EVIDENCE_STAGES)
        events = frames.events(len(EVIDENCE_STAGES) + 1)
        done = [event for event in events if event[0] == EVENT_DONE]
        assert len(done) == 1
        assert done[0][1]["jobId"] == job_id
        assert done[0][1]["viewable"] is True

        # Later activity on the same job must not re-announce completion.
        _set_stages(test_pool, job_id, "running", ("extract",))
        ((name, payload),) = frames.events(1)
        assert name == EVENT_STAGE
        assert payload["stage"] == "extract"
        assert payload["viewable"] is True


def test_job_done_fires_for_a_transcript_only_drop(client, test_pool, make_drop) -> None:
    """Skipped video stages are settled, so a transcript-only meeting completes."""
    job_id = _submit(client, make_drop, source_id="source-a")
    _submit(client, make_drop, source_id="source-b")

    with open_stream(client) as frames:
        with test_pool.connection() as conn:
            conn.execute(
                "UPDATE job_stage SET status = CASE"
                " WHEN name = ANY(%s) THEN 'skipped' ELSE 'done' END"
                " WHERE job_id = %s AND name = ANY(%s)",
                (list(VIDEO_ONLY_STAGES), job_id, list(EVIDENCE_STAGES)),
            )

        events = frames.events(len(EVIDENCE_STAGES) + 1)

    skipped = {
        payload["stage"]
        for name, payload in events
        if name == EVENT_STAGE and payload["status"] == "skipped"
    }
    assert skipped == set(VIDEO_ONLY_STAGES)
    assert not any(payload.get("status") == "failed" for _, payload in events)
    assert [name for name, _ in events][-1] == EVENT_DONE


def test_failed_stage_emits_job_error_with_the_recorded_text(
    client, test_pool, make_drop
) -> None:
    job_id = _submit(client, make_drop, source_id="source-a")
    _submit(client, make_drop, source_id="source-b")
    recorded = "ffprobe exited 1: moov atom not found"

    with open_stream(client) as frames:
        _fail_stage(test_pool, job_id, "probe", recorded)
        events = frames.events(2)

    by_name = {name: payload for name, payload in events}
    assert set(by_name) == {EVENT_STAGE, EVENT_ERROR}
    assert by_name[EVENT_STAGE]["stage"] == "probe"
    assert by_name[EVENT_STAGE]["status"] == "failed"
    # Verbatim, in both places it appears.
    assert by_name[EVENT_STAGE]["error"] == recorded
    assert by_name[EVENT_ERROR]["error"] == recorded
    assert by_name[EVENT_ERROR]["jobId"] == job_id
    assert by_name[EVENT_ERROR]["jobStatus"] == "failed"
    assert by_name[EVENT_ERROR]["viewable"] is False


def test_only_the_three_pinned_names_reach_the_wire(client, test_pool, make_drop) -> None:
    """FR8: exactly `job.stage`, `job.done`, `job.error` — no log-event names."""
    first = _submit(client, make_drop, source_id="source-a")
    second = _submit(client, make_drop, source_id="source-b")
    _submit(client, make_drop, source_id="source-c")  # keeps the stream open

    with open_stream(client) as frames:
        _set_stages(test_pool, first, "done", EVIDENCE_STAGES)
        _fail_stage(test_pool, second, "frames", "ffmpeg died")
        events = frames.events(len(EVIDENCE_STAGES) + 3)
        stream_text = "\n".join(frames.raw)

    names = {name for name, _ in events}
    assert names == {EVENT_STAGE, EVENT_DONE, EVENT_ERROR}
    assert names <= set(WIRE_EVENT_NAMES)
    for log_event in WORKER_LOG_EVENTS:
        assert log_event not in stream_text, f"worker log event {log_event} leaked"
    # And every payload is keyed by job.
    assert all(payload["jobId"] for _, payload in events)


def test_two_jobs_in_flight_update_independently(client, test_pool, make_drop) -> None:
    first = _submit(client, make_drop, source_id="source-a")
    second = _submit(client, make_drop, source_id="source-b")

    with open_stream(client) as frames:
        _set_stages(test_pool, first, "running", ("probe",))
        _set_stages(test_pool, second, "running", ("probe",))
        events = frames.events(2)

    assert {payload["jobId"] for _, payload in events} == {first, second}
    assert all(payload["stage"] == "probe" for _, payload in events)


def test_a_job_submitted_mid_stream_announces_itself(client, make_drop) -> None:
    """A drop accepted while the list is open must not stay invisible."""
    _submit(client, make_drop, source_id="source-a")

    with open_stream(client) as frames:
        new_job = _submit(client, make_drop, source_id="source-b")
        ((name, payload),) = frames.events(1)

    assert name == EVENT_STAGE
    assert payload["jobId"] == new_job
    assert payload["stage"] == "probe"
    assert payload["status"] == "queued"
    assert payload["viewable"] is False


def test_idle_stream_heartbeats_and_emits_no_events(client) -> None:
    """No jobs at all: the connection is held open by comments alone."""
    with open_stream(client) as frames:
        assert frames.comments(3) == ["heartbeat"] * 3


def test_configured_heartbeat_cadence_is_honored(client) -> None:
    """A fast heartbeat stays fast even when reads are deliberately slow."""
    fast = 0.2
    with open_stream(client, poll=2.5, heartbeat=fast) as frames:
        # `open_stream` has consumed `: connected`, so this excludes connection
        # and baseline-read setup from the cadence measurement.
        started = time.monotonic()
        assert frames.comments(3) == ["heartbeat"] * 3
    elapsed = time.monotonic() - started
    assert 0.35 <= elapsed < 1.5, f"three {fast}s heartbeats took {elapsed:.2f}s"


@pytest.mark.slow(reason="waits out a real 3s heartbeat interval: 3.0s at e5510c7")
def test_a_slow_configured_heartbeat_is_not_overridden_by_a_faster_default(
    client,
) -> None:
    """The other direction: a fixed *fast* interval must fail too.

    Without this, hardcoding 1s would still pass the test above. A configured
    3s heartbeat must actually take about 3s to arrive.
    """
    slow = 3.0
    with open_stream(client, poll=0.2, heartbeat=slow) as frames:
        started = time.monotonic()
        assert frames.comments(1) == ["heartbeat"]
    elapsed = time.monotonic() - started
    # The lower bound sits well above any plausible cap, not just above the
    # default. At 1.5 it was the cap value itself, so `min(heartbeat, 1.5)` —
    # the very mutation this test exists to reject — landed on the boundary and
    # passed. 2.0 leaves a full second of margin either side of a real 3s wait.
    assert 2.0 <= elapsed < 4.5, f"a {slow}s heartbeat arrived after {elapsed:.2f}s"


@pytest.mark.slow(reason="waits out the configured poll cadence before a stage change surfaces: 2.5s at e5510c7")
def test_configured_poll_cadence_is_honored(client, test_pool, make_drop) -> None:
    """A stage transition surfaces no faster than the configured poll allows.

    Heartbeats are kept fast so the stream stays readable; only the poll is
    slowed, so what is timed here is the change detection alone.
    """
    slow = 2.5
    job_id = _submit(client, make_drop)

    with open_stream(client, poll=slow, heartbeat=0.2) as frames:
        _set_stages(test_pool, job_id, "running", ("probe",))
        started = time.monotonic()
        ((name, payload),) = frames.events(1)
        elapsed = time.monotonic() - started

    assert (name, payload["stage"]) == (EVENT_STAGE, "probe")
    assert 1.5 <= elapsed < 4.5, f"a {slow}s poll reported the change after {elapsed:.2f}s"


def test_stream_closes_once_every_watched_job_has_settled(
    client, test_pool, make_drop
) -> None:
    job_id = _submit(client, make_drop)

    with open_stream(client) as frames:
        _set_stages(test_pool, job_id, "done", EVIDENCE_STAGES)
        events = frames.drain()  # returns only when the server closes the stream

    assert [name for name, _ in events][-1] == EVENT_DONE


def test_payload_fields_are_camel_case(client, test_pool, make_drop) -> None:
    job_id = _submit(client, make_drop)

    with open_stream(client) as frames:
        _set_stages(test_pool, job_id, "running", ("probe",))
        ((_, payload),) = frames.events(1)

    assert set(payload) == {
        "event", "jobId", "jobStatus", "viewable", "stage", "status", "error",
    }
    assert not any("_" in key for key in payload)


@pytest.mark.parametrize("name", WIRE_EVENT_NAMES)
def test_wire_names_are_the_three_pinned_strings(name: str) -> None:
    """A guard on the constants themselves, so a rename cannot pass silently."""
    assert name in {"job.stage", "job.done", "job.error"}


def test_a_job_status_change_with_no_stage_move_is_reported(
    client, test_pool, make_drop
) -> None:
    """A claim moves the job row and nothing else; the row must not go stale."""
    job_id = _submit(client, make_drop, source_id="source-a")
    _submit(client, make_drop, source_id="source-b")

    with open_stream(client) as frames:
        with test_pool.connection() as conn:
            conn.execute("UPDATE job SET status = 'running' WHERE id = %s", (job_id,))
        ((name, payload),) = frames.events(1)

    assert name == EVENT_STAGE
    assert payload["jobId"] == job_id
    assert payload["jobStatus"] == "running"
    # It names where the job currently sits rather than inventing a transition.
    assert payload["stage"] == "probe"
    assert payload["status"] == "queued"


def test_a_stage_less_job_failure_emits_job_error_naming_no_stage(
    client, test_pool, make_drop
) -> None:
    """The runner fails a job with no stage implicated at three sites.

    An unreadable drop, a meeting mint that raised, and video-evidence cleanup
    that failed all set `job.error` while every checkpoint stays `queued`. The
    job row's own error is then the only text there is.
    """
    job_id = _submit(client, make_drop, source_id="source-a")
    _submit(client, make_drop, source_id="source-b")
    recorded = "source drop unreadable: metadata.json is not valid JSON"

    with open_stream(client) as frames:
        with test_pool.connection() as conn:
            conn.execute(
                "UPDATE job SET status = 'failed', error = %s WHERE id = %s",
                (recorded, job_id),
            )
        events = frames.events(2)

    by_name = {name: payload for name, payload in events}
    assert set(by_name) == {EVENT_STAGE, EVENT_ERROR}
    error = by_name[EVENT_ERROR]
    assert error["jobId"] == job_id
    assert error["jobStatus"] == "failed"
    assert error["stage"] is None
    assert error["error"] == recorded
    # No checkpoint was touched, so none may be reported as failed.
    with test_pool.connection() as conn:
        statuses = conn.execute(
            "SELECT DISTINCT status FROM job_stage WHERE job_id = %s", (job_id,)
        ).fetchall()
    assert [row[0] for row in statuses] == ["queued"]


def test_a_transient_read_failure_does_not_end_the_stream(
    client, test_pool, make_drop, monkeypatch
) -> None:
    """A pool timeout or a Postgres restart must not truncate the response.

    The headers are long gone by the time a tick runs, so an escaping
    exception would hand the client a body that just stops.
    """
    job_id = _submit(client, make_drop)
    real = events_module.read_snapshot
    calls = {"n": 0}

    def flaky(pool):
        calls["n"] += 1
        # Call 1 is the baseline; fail the first poll after it.
        if calls["n"] == 2:
            raise RuntimeError("connection reset by peer")
        return real(pool)

    monkeypatch.setattr(events_module, "read_snapshot", flaky)

    with open_stream(client) as frames:
        _set_stages(test_pool, job_id, "running", ("probe",))
        ((name, payload),) = frames.events(1)

    assert calls["n"] > 2, "the failing tick was never reached"
    assert name == EVENT_STAGE
    assert payload["stage"] == "probe"
    assert payload["status"] == "running"


def test_persistent_read_failures_close_the_stream_cleanly(
    client, make_drop, monkeypatch
) -> None:
    """The documented policy: give up after a bounded run of failures.

    Holding the connection open against a database that cannot be read would
    report a live stream that can never carry another event.
    """
    _submit(client, make_drop)
    real = events_module.read_snapshot
    calls = {"n": 0}

    def broken(pool):
        calls["n"] += 1
        if calls["n"] == 1:
            return real(pool)  # the baseline still succeeds
        raise RuntimeError("the database is gone")

    monkeypatch.setattr(events_module, "read_snapshot", broken)

    with open_stream(client) as frames:
        assert frames.drain() == []  # returns when the server closes the stream

    assert calls["n"] == MAX_CONSECUTIVE_READ_FAILURES + 1
