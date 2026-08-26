"""GET /jobs/{id} contract tests (run against meetingminer_test; skip without Postgres)."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Callable, Iterator
from uuid import uuid4

PROBLEM = "application/problem+json"
STAGES = ["probe", "frames", "ocr", "screens", "transcribe", "align", "moments", "extract"]


def test_get_unknown_job_is_404_problem(client) -> None:
    response = client.get(f"/jobs/{uuid4()}")
    assert response.status_code == 404
    assert response.headers["content-type"] == PROBLEM
    body = response.json()
    assert body["type"] == "urn:meetingminer:problem:not-found"
    assert "detail" in body and "job" in body["detail"]


def test_get_queued_job_returns_status_and_stage_checkpoints(
    client, make_drop
) -> None:
    drop = make_drop()
    job_id = client.post("/ingests", json={"dropPath": str(drop)}).json()["jobId"]

    response = client.get(f"/jobs/{job_id}")
    assert response.status_code == 200

    body = response.json()
    assert set(body) == {
        "jobId", "status", "sourceId", "dropPath", "corpus", "error",
        "createdAt", "stages",
    }
    assert body["jobId"] == job_id
    assert body["status"] == "queued"
    assert body["sourceId"] == "source-1"
    # Root-relative, never absolute: no filesystem path leaves the server
    # (story 2.1a). A caller resolves this against the root it configured.
    assert body["dropPath"] == drop.name
    assert body["corpus"] == "real"
    assert body["error"] is None
    assert body["createdAt"]  # ISO timestamp present

    # Stages come back in canonical pipeline order, all queued.
    assert [stage["name"] for stage in body["stages"]] == STAGES
    assert all(stage["status"] == "queued" for stage in body["stages"])
    assert all(stage["error"] is None for stage in body["stages"])


def test_get_legacy_job_keeps_drop_path_null_and_never_leaks_its_absolute_value(
    client, test_pool
) -> None:
    """The migration read-model remains wire-compatible without exposing paths."""
    absolute = "/legacy/operator-private/drop-17"
    with test_pool.connection() as conn:
        job_id = conn.execute(
            "INSERT INTO job (source_id, drop_path, corpus) VALUES (%s, %s, 'real')"
            " RETURNING id",
            ("legacy-job-response", absolute),
        ).fetchone()[0]

    response = client.get(f"/jobs/{job_id}")

    assert response.status_code == 200
    assert response.json()["dropPath"] is None
    assert absolute not in response.text


# --- read-model consistency during a concurrent requeue --------------------


class _HookedConnection:
    """Connection proxy that fires a callback after the first statement."""

    def __init__(self, conn: Any, owner: "_HookAfterFirstStatement") -> None:
        self._conn = conn
        self._owner = owner

    def execute(self, query: Any, params: Any = None, **kwargs: Any) -> Any:
        cursor = self._conn.execute(query, params, **kwargs)
        self._owner.statements += 1
        if self._owner.statements == 1:
            self._owner.after()
        return cursor

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


class _HookAfterFirstStatement:
    """Pool proxy: runs ``after`` the moment the first statement returns.

    This is the deterministic stand-in for a concurrent writer landing in the
    exact window the endpoint is vulnerable to — no sleeps, no thread timing.
    The callback commits on its own connection, so whether the endpoint sees
    it depends purely on how many snapshots the endpoint takes.
    """

    def __init__(self, pool: Any, after: Callable[[], None]) -> None:
        self._pool = pool
        self.after = after
        self.statements = 0

    @contextmanager
    def connection(self) -> Iterator[Any]:
        with self._pool.connection() as conn:
            yield _HookedConnection(conn, self)


def _fail_job(pool: Any, job_id: str) -> None:
    with pool.connection() as conn:
        conn.execute(
            "UPDATE job SET status = 'failed', error = 'probe blew up' WHERE id = %s",
            (job_id,),
        )
        conn.execute(
            "UPDATE job_stage SET status = 'failed', error = 'boom'"
            " WHERE job_id = %s AND name = 'probe'",
            (job_id,),
        )


def _requeue_job(pool: Any, job_id: str) -> None:
    """The write half of a failed-job resubmit, committed on its own connection."""
    with pool.connection() as conn:
        conn.execute(
            "UPDATE job SET status = 'queued', error = NULL WHERE id = %s", (job_id,)
        )
        conn.execute(
            "UPDATE job_stage SET status = 'queued', error = NULL WHERE job_id = %s",
            (job_id,),
        )


def test_requeue_committed_mid_read_cannot_split_job_from_its_stages(
    client, test_pool, make_drop
) -> None:
    """A requeue committing mid-read must never be half-visible.

    The endpoint used to read the job and its checkpoints in two statements.
    Under Read Committed each statement takes its own snapshot, so a requeue
    committing between them produced a response pairing the old `failed` job
    with eight freshly reset `queued` stages — a state that never existed in
    the database.

    The hook commits exactly that requeue as soon as the endpoint's first
    statement returns. However many statements the endpoint uses, the response
    must be internally consistent: reading everything from one snapshot means
    the whole response predates the requeue.
    """
    import meetingminer.api.main as api_main

    job_id = client.post("/ingests", json={"dropPath": str(make_drop())}).json()["jobId"]
    _fail_job(test_pool, job_id)

    hooked = _HookAfterFirstStatement(test_pool, lambda: _requeue_job(test_pool, job_id))
    api_main.app.state.pool = hooked
    try:
        response = client.get(f"/jobs/{job_id}")
    finally:
        api_main.app.state.pool = test_pool

    assert response.status_code == 200
    body = response.json()
    stages = {stage["name"]: stage["status"] for stage in body["stages"]}

    # The requeue is committed by now, so the endpoint must not have seen a
    # torn mix of it: a failed job whose stages are all queued is the exact
    # impossible state this guards.
    assert not (
        body["status"] == "failed" and set(stages.values()) == {"queued"}
    ), f"torn read: {body['status']} job with stages {stages}"

    # Concretely: the whole response predates the requeue.
    assert body["status"] == "failed"
    assert body["error"] == "probe blew up"
    assert stages["probe"] == "failed"
    assert [stage["name"] for stage in body["stages"]] == STAGES

    # The requeue really did commit while the request was in flight.
    with test_pool.connection() as conn:
        after = conn.execute(
            "SELECT status FROM job WHERE id = %s", (job_id,)
        ).fetchone()[0]
    assert after == "queued"


def test_job_with_no_stage_rows_still_returns_the_job(
    client, test_pool, make_drop
) -> None:
    """The LEFT JOIN must not turn a stage-less job into a 404."""
    job_id = client.post("/ingests", json={"dropPath": str(make_drop())}).json()["jobId"]
    with test_pool.connection() as conn:
        conn.execute("DELETE FROM job_stage WHERE job_id = %s", (job_id,))

    response = client.get(f"/jobs/{job_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["jobId"] == job_id
    assert body["stages"] == []
