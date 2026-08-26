"""GET /jobs/{jobId} — job status plus per-stage checkpoints (AD-11)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from meetingminer.api.problems import Problem, ProblemDetails
from meetingminer.domain.jobs import STAGE_NAMES

router = APIRouter()
ROUTER_ORDER = 20

_STAGE_ORDER = {name: index for index, name in enumerate(STAGE_NAMES)}


def stage_sort_key(name: str) -> int:
    """Canonical pipeline position for a stage name.

    Shared with the meetings list so both endpoints order checkpoints the same
    way; an unknown name sorts last rather than raising, because a stage row
    written by a newer worker must not 500 an older api.
    """
    return _STAGE_ORDER.get(name, len(STAGE_NAMES))

# One statement, therefore one snapshot. Under Read Committed every statement
# takes a fresh snapshot, so reading the job and its checkpoints separately let
# a failed-job requeue commit in between — the caller could receive the old
# `failed` job paired with the freshly reset `queued` stages, a state that
# never existed. The LEFT JOIN keeps a job with no stage rows visible: it comes
# back as a single row whose stage columns are NULL.
_JOB_WITH_STAGES = (
    "SELECT j.id, j.status, j.source_id, j.drop_relative_path, j.corpus, j.error,"
    " j.created_at, s.name, s.status, s.error"
    " FROM job j LEFT JOIN job_stage s ON s.job_id = j.id"
    " WHERE j.id = %s"
)


class JobStage(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    name: str
    status: str
    error: str | None = None


class JobResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    job_id: UUID
    status: str
    source_id: str
    # Preserve the public `dropPath` field name while changing its meaning to
    # a nullable MM_DROPS_ROOT-relative directory.  Legacy rows have only the
    # absolute database column, which must never leave the server.
    drop_path: str | None
    corpus: str
    error: str | None = None
    created_at: datetime
    stages: list[JobStage]


@router.get(
    "/jobs/{job_id}",
    operation_id="getJob",
    response_model=JobResponse,
    responses={
        404: {"model": ProblemDetails, "content": {"application/problem+json": {}}},
    },
)
def get_job(job_id: UUID, request: Request) -> JobResponse:
    pool = request.app.state.pool
    with pool.connection() as conn:
        rows = conn.execute(_JOB_WITH_STAGES, (job_id,)).fetchall()

    if not rows:
        raise Problem(404, "not-found", f"no job with id {job_id}")

    # Every row repeats the job columns; the stage columns are NULL only when
    # the job has no checkpoints at all.
    job = rows[0]
    stages = sorted(
        (
            JobStage(name=row[7], status=row[8], error=row[9])
            for row in rows
            if row[7] is not None
        ),
        key=lambda stage: stage_sort_key(stage.name),
    )
    return JobResponse(
        job_id=job[0],
        status=job[1],
        source_id=job[2],
        drop_path=job[3],
        corpus=job[4],
        error=job[5],
        created_at=job[6],
        stages=stages,
    )
